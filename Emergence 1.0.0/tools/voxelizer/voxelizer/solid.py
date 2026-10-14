"""Remplissage du volume, couleur de l'intérieur, et palette « pixel art »."""
import itertools
from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np
from PIL import Image
from scipy import ndimage as ndi
from scipy.spatial import cKDTree

from .config import VoxelizeConfig
from .lattice import exposed_masks, pack, unpack
from .refine import CenterInsideTester
from .scene import Scene3D, linear_to_srgb
from .surface import SurfaceVoxels

SURFACE, INTERIOR = 0, 1


class VoxelBudgetError(MemoryError):
    """Le modèle dépasse le budget mémoire. `ratio` = facteur (<1) à appliquer à l'échelle pour tenir."""

    def __init__(self, msg: str, ratio: Optional[float] = None):
        super().__init__(msg)
        self.ratio = ratio


class GridTooLargeError(VoxelBudgetError):
    pass


class TooManyVoxelsError(VoxelBudgetError):
    pass


@dataclass
class FilledVoxels:
    keys: np.ndarray      # (N,) int64 triées
    kind: np.ndarray      # (N,) uint8 : 0 surface, 1 intérieur
    rgb: np.ndarray       # (N,3) uint8 sRGB
    alpha: np.ndarray     # (N,) uint8
    trimmed: int = 0      # voxels de débord conservatif retirés (voir CenterInsideTester)
    material: Optional[np.ndarray] = None   # (N,) int16 : matériau (indice de primitive puis, après le pipeline, de matériau)


class SolidFiller:
    """Surface conservative -> volume plein.

    Remplissage par composantes connexes du VIDE (6-connexité) : tout vide non relié à l'extérieur
    est intérieur. Comme la surface est 6-séparante, un maillage fermé ne fuit jamais.
    Les maillages OUVERTS (toit, feuille, mur sans fond) n'ont pas d'intérieur : ils restent une
    coque d'un voxel. `seal_radius` > 0 comble les trous jusqu'à ~2r voxels avant de remplir.
    """

    def __init__(self, cfg: VoxelizeConfig):
        self.cfg = cfg

    def fill(self, s: SurfaceVoxels, scene: Optional[Scene3D] = None) -> FilledVoxels:
        cfg = self.cfg
        ix, iy, iz = unpack(s.keys)
        interior = np.empty((0, 3), np.int64)
        if cfg.fill == "solid":
            interior = self._interior_cells(ix, iy, iz)

        # --- couleurs : celles de la surface, propagées aux cellules sans échantillon et à l'intérieur
        surf_xyz = np.stack([ix, iy, iz], axis=1)
        colored = s.has_color
        if not colored.any():
            raise ValueError("Aucune cellule colorée : impossible de colorer le modèle.")
        tree, col_rgb = cKDTree(surf_xyz[colored]), s.rgb[colored]
        rgb_s = s.rgb.copy()
        mat0 = s.material if s.material is not None else np.zeros(len(s.keys), np.int16)
        mat_s, mat_c = mat0.copy(), mat0[colored]
        if (~colored).any():
            nn = tree.query(surf_xyz[~colored])[1]
            rgb_s[~colored], mat_s[~colored] = col_rgb[nn], mat_c[nn]
        if len(interior):
            nn = tree.query(interior)[1]
            rgb_i, mat_i = col_rgb[nn], mat_c[nn]
        else:
            rgb_i, mat_i = np.empty((0, 3), np.float32), np.empty(0, np.int16)
        keys_i = pack(interior[:, 0], interior[:, 1], interior[:, 2]) if len(interior) else np.empty(0, np.int64)

        # --- débord conservatif : on retire de la peau des solides fermés les voxels au centre hors maillage.
        #     (leurs couleurs restent dans `tree` : les voxels qui deviennent peau les héritent)
        drop = np.zeros(len(s.keys), bool)
        if cfg.trim_overshoot and scene is not None and len(keys_i):
            drop = self._overshoot(scene, s.keys, surf_xyz, keys_i)
        keep = ~drop

        keys = np.concatenate([s.keys[keep], keys_i])
        order = np.argsort(keys)
        keys = keys[order]
        rgb = np.concatenate([rgb_s[keep], rgb_i])[order]
        material = np.concatenate([mat_s[keep], mat_i])[order]
        alpha = np.concatenate([s.alpha[keep], np.ones(len(keys_i), np.float32)])[order]
        # nature = visibilité : SURFACE si au moins une face est exposée, INTERIOR si le voxel est enseveli
        kind = np.where(exposed_masks(keys) != 0, SURFACE, INTERIOR).astype(np.uint8)
        rgb[kind == INTERIOR] *= cfg.interior_shade
        rgb8 = np.rint(linear_to_srgb(rgb) * 255).astype(np.uint8)
        return FilledVoxels(keys, kind, rgb8, np.rint(alpha * 255).astype(np.uint8), trimmed=int(drop.sum()),
                            material=material)

    def _overshoot(self, scene: Scene3D, skeys: np.ndarray, sxyz: np.ndarray, ikeys: np.ndarray) -> np.ndarray:
        """Voxels de surface au contact (26-voisinage) d'un intérieur ET dont le centre est hors du maillage."""
        ik = np.sort(ikeys)
        near = np.zeros(len(skeys), bool)
        for dx, dy, dz in itertools.product((-1, 0, 1), repeat=3):
            if (dx, dy, dz) == (0, 0, 0):
                continue
            nk = skeys + ((dx << 42) + (dy << 21) + dz)
            near |= ik[np.minimum(np.searchsorted(ik, nk), len(ik) - 1)] == nk
        cand = np.nonzero(near)[0]
        drop = np.zeros(len(skeys), bool)
        if len(cand):
            centers = (sxyz[cand] + 0.5) * self.cfg.voxel_size
            # maillage fermé : vote majoritaire (2/3). Maillage rendu étanche par `seal` (donc ouvert) : 1 axe suffit
            votes = 1 if self.cfg.seal_radius > 0 else 2
            drop[cand[~CenterInsideTester(self.cfg, scene).inside(centers, votes)]] = True
        return drop

    def _interior_cells(self, ix, iy, iz) -> np.ndarray:
        cfg, r = self.cfg, self.cfg.seal_radius
        lo = np.array([ix.min(), iy.min(), iz.min()])
        dims = np.array([ix.max(), iy.max(), iz.max()]) - lo + 1 + 2 * (1 + r)
        if int(np.prod(dims)) > cfg.max_dense_cells:
            raise GridTooLargeError(
                f"Grille dense de {int(np.prod(dims)):,} cellules (> {cfg.max_dense_cells:,}) : "
                f"réduisez l'échelle, voxélisez par morceaux, ou utilisez fill='shell'.",
                (cfg.max_dense_cells / int(np.prod(dims))) ** (1 / 3))
        off = 1 + r - lo
        occ = np.zeros(dims, bool)
        occ[ix + off[0], iy + off[1], iz + off[2]] = True
        st = ndi.generate_binary_structure(3, 1)                      # 6-connexité
        labels, _ = ndi.label(~occ, structure=st)
        cavity = (~occ) & (labels != labels[0, 0, 0])                 # le coin (0,0,0) est forcément extérieur
        if r > 0:
            # (A) petit trou dans une coque fermée : on épaissit la barrière, on repère les cavités qui survivent
            sealed = ndi.binary_dilation(occ, st, iterations=r)
            lab, _ = ndi.label(~sealed, structure=st)
            cav_a = (~sealed) & (lab != lab[0, 0, 0])
            cav_a = (ndi.binary_dilation(cav_a, st, iterations=r) & sealed & ~occ) | cav_a
            # (B) écart étroit entre deux parois (dalle ouverte sur la tranche) : fermeture morphologique
            closed = ndi.binary_erosion(ndi.binary_dilation(occ, st, iterations=r), st, iterations=r, border_value=0) | occ
            lab2, _ = ndi.label(~closed, structure=st)
            cav_b = ((~closed) & (lab2 != lab2[0, 0, 0])) | (closed & ~occ)
            cavity = cavity | cav_a | cav_b
        cells = np.argwhere(cavity)
        return cells - off


class PaletteQuantizer:
    """Réduit les couleurs à une palette fixe (look pixel art). size=0 -> couleurs exactes."""

    def __init__(self, size: int):
        self.size = size

    def quantize(self, f: FilledVoxels) -> Tuple[np.ndarray, np.ndarray]:
        """-> (palette RGBA uint8 (K,4), indices (N,))."""
        rgb = f.rgb
        if self.size and len(np.unique(rgb, axis=0)) > self.size:
            im = Image.fromarray(rgb.reshape(-1, 1, 3)).quantize(
                colors=self.size, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
            pal = np.array(im.getpalette()[: 3 * self.size], np.uint8).reshape(-1, 3)
            ridx = np.asarray(im).reshape(-1).astype(np.int64)
        else:
            pal, ridx = np.unique(rgb, axis=0, return_inverse=True)
            ridx = ridx.reshape(-1).astype(np.int64)
        pair = ridx * 256 + f.alpha.astype(np.int64)                  # (couleur, alpha) -> entrée de palette
        up, inv = np.unique(pair, return_inverse=True)
        rgba = np.concatenate([pal[up // 256], (up % 256)[:, None].astype(np.uint8)], axis=1)
        return rgba.astype(np.uint8), inv.reshape(-1)
