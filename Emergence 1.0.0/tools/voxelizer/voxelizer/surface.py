"""Voxélisation de SURFACE avec couleur, entièrement vectorisée (numpy).

Principe, en deux niveaux de subdivision d'un même triangle :
  1. arêtes <= 0.9 voxel  -> chaque triangle touche au plus 2 cellules par axe, donc au plus 8
     candidates : test EXACT triangle/cube (Akenine-Möller) => couverture conservative, sans trou
     (surface "6-séparante" : indispensable pour que le remplissage ne fuie pas).
  2. arêtes <= 0.45 voxel -> ~4+ échantillons de texture par face de voxel ; chaque échantillon
     (centroïde d'un sous-triangle, pondéré par son aire) tombe dans une cellule : la couleur du
     voxel est la MOYENNE (en espace linéaire, au bon niveau de mipmap) de ce qu'il contient.
"""
import itertools
from dataclasses import dataclass
from typing import Iterator, List, Optional, Tuple

import numpy as np

from .config import VoxelizeConfig
from .lattice import pack
from .scene import MeshPrimitive, Material, Scene3D

# jitter déterministe (~µm) : évite que des plans exactement sur une frontière de voxel (très fréquent
# avec des kits modulaires alignés) soient classés de façon arbitraire.
_JITTER = np.array([1.3e-4, 2.9e-4, 4.1e-4])


# ----------------------------------------------------------------------------- géométrie
def bisect_triangles(v: np.ndarray, max_edge: float) -> np.ndarray:
    """v (T,3,K) : K attributs par sommet (les 3 premiers = position). Coupe en deux par la plus
    longue arête, jusqu'à ce que toutes les arêtes soient <= max_edge. Les attributs (UV, couleur)
    sont interpolés linéairement. Aucune boucle Python par triangle."""
    while True:
        p = v[:, :, :3]
        e = np.stack([np.linalg.norm(p[:, 1] - p[:, 0], axis=1),
                      np.linalg.norm(p[:, 2] - p[:, 1], axis=1),
                      np.linalg.norm(p[:, 0] - p[:, 2], axis=1)], axis=1)
        big = e.max(axis=1) > max_edge
        if not big.any():
            return v
        vb, k = v[big], e[big].argmax(axis=1)
        i = np.arange(len(vb))
        a, b, c = vb[i, k], vb[i, (k + 1) % 3], vb[i, (k + 2) % 3]
        m = 0.5 * (a + b)
        v = np.concatenate([v[~big], np.stack([a, m, c], 1), np.stack([m, b, c], 1)])


def tri_box_overlap(tri: np.ndarray, center: np.ndarray, half: float) -> np.ndarray:
    """Test exact triangle/cube axis-aligné par axes séparateurs (13 axes). tri (N,3,3), center (N,3)."""
    v = tri - center[:, None, :]
    f = np.stack([v[:, 1] - v[:, 0], v[:, 2] - v[:, 1], v[:, 0] - v[:, 2]], axis=1)
    eps = 1e-12
    ok = (v.min(axis=1) <= half + eps).all(axis=1) & (v.max(axis=1) >= -half - eps).all(axis=1)  # 3 axes du cube
    n = np.cross(f[:, 0], f[:, 1])                                                              # plan du triangle
    ok &= np.abs((n * v[:, 0]).sum(axis=1)) <= half * np.abs(n).sum(axis=1) + eps
    for i in range(3):                                                                           # 9 axes e_i x u_j
        for j in range(3):
            u = np.zeros(3); u[j] = 1.0
            ax = np.cross(f[:, i], u)
            p = np.einsum("nvk,nk->nv", v, ax)
            r = half * np.abs(ax).sum(axis=1) + eps
            ok &= (p.min(axis=1) <= r) & (p.max(axis=1) >= -r)
    return ok


def covered_cells(tri: np.ndarray, vs: float) -> np.ndarray:
    """Cellules (M,3) touchées par des triangles dont les arêtes sont <= ~1 voxel."""
    lo = np.floor(tri.min(axis=1) / vs).astype(np.int64)
    hi = np.floor(tri.max(axis=1) / vs).astype(np.int64)
    ids, cells = [], []
    for off in itertools.product((0, 1), repeat=3):
        c = lo + np.array(off)
        m = (c <= hi).all(axis=1)
        if m.any():
            ids.append(np.nonzero(m)[0]); cells.append(c[m])
    ids, cells = np.concatenate(ids), np.concatenate(cells)
    ok = (hi == lo).all(axis=1)[ids]                  # triangle entièrement dans une cellule : trivial
    need = ~ok
    if need.any():
        ok[need] = tri_box_overlap(tri[ids[need]], (cells[need] + 0.5) * vs, vs / 2)
    return cells[ok]


# ----------------------------------------------------------------------------- résultat
@dataclass
class SurfaceVoxels:
    keys: np.ndarray        # (N,) int64 triées, clés de cellules occupées par la surface
    rgb: np.ndarray         # (N,3) float32 linéaire ; NaN si la cellule n'a reçu aucun échantillon
    alpha: np.ndarray       # (N,) float32
    material: Optional[np.ndarray] = None   # (N,) int16 : indice de primitive dominante (-1 = inconnu)

    @property
    def has_color(self) -> np.ndarray:
        return np.isfinite(self.rgb[:, 0])


class SurfaceVoxelizer:
    def __init__(self, cfg: VoxelizeConfig):
        if not 0.05 <= cfg.sample_edge_ratio <= cfg.coarse_edge_ratio <= 0.95:
            raise ValueError("Il faut 0.05 <= sample_edge_ratio <= coarse_edge_ratio <= 0.95.")
        self.cfg = cfg
        self.vs = cfg.voxel_size
        self.coarse = cfg.coarse_edge_ratio * self.vs
        self.fine = cfg.sample_edge_ratio * self.vs

    # -- API
    def voxelize(self, scene: Scene3D) -> SurfaceVoxels:
        cover: List[np.ndarray] = []
        acc: List[Tuple[np.ndarray, ...]] = []
        for pid, prim in enumerate(scene.primitives):
            for chunk in self._chunks(prim):
                n0 = len(acc)
                self._process(chunk, prim.material, cover, acc)
                for j in range(n0, len(acc)):                       # étiquette de matériau (mode « dominant »)
                    acc[j] = (*acc[j], np.full(len(acc[j][0]), pid, np.int32))
        if not cover and not acc:
            raise ValueError("Aucun voxel produit (tout est transparent ou hors-scène ?).")
        ck = np.concatenate([a[0] for a in acc]) if acc else np.empty(0, np.int64)
        keys = np.unique(np.concatenate(cover + [ck]))
        rgb = np.full((len(keys), 3), np.nan, np.float32)
        alpha = np.ones(len(keys), np.float32)
        material = np.full(len(keys), -1, np.int16)
        if acc:
            allk, allp = np.concatenate([a[0] for a in acc]), np.concatenate([a[6] for a in acc])
            cols = [np.concatenate([a[j] for a in acc]) for j in range(1, 6)]          # r, g, b, alpha, poids
            order = np.lexsort((allp, allk))
            ks, ps = allk[order], allp[order]
            new_grp = np.r_[True, (ks[1:] != ks[:-1]) | (ps[1:] != ps[:-1])]            # groupe = (cellule, matériau)
            gid = np.cumsum(new_grp) - 1
            g = [np.bincount(gid, weights=c[order], minlength=int(gid[-1]) + 1) for c in cols]
            gk = ks[new_grp]
            cell_start = np.r_[True, gk[1:] != gk[:-1]]
            cid = np.cumsum(cell_start) - 1
            uk = gk[cell_start]
            o2 = np.lexsort((g[4], cid))
            win = o2[np.r_[cid[o2][1:] != cid[o2][:-1], True]]                         # groupe le plus étendu par cellule
            gp = ps[new_grp]                                                           # primitive de chaque groupe
            if self.cfg.color_mode == "dominant":                                      # le matériau le plus étendu gagne
                sel = [x[win] for x in g]
            else:                                                                      # mélange pondéré par l'aire
                sel = [np.bincount(cid, weights=x, minlength=len(uk)) for x in g]
            w = np.maximum(sel[4], 1e-30)
            at = np.searchsorted(keys, uk)
            rgb[at] = np.stack([sel[0] / w, sel[1] / w, sel[2] / w], axis=1)
            alpha[at] = sel[3] / w
            material[at] = gp[win].astype(np.int16)
        return SurfaceVoxels(keys, rgb, alpha, material)

    # -- découpage mémoire
    def _chunks(self, prim: MeshPrimitive) -> Iterator[np.ndarray]:
        n = len(prim.positions)
        pos = prim.positions + _JITTER * self.vs
        uv = prim.uv if prim.uv is not None else np.zeros((n, 2))
        col = prim.colors if prim.colors is not None else np.ones((n, 4))
        idx = prim.indices
        v = np.concatenate([pos[idx], uv[idx], col[idx]], axis=2)         # (T,3,9)
        v = v[np.isfinite(v).all(axis=(1, 2))]
        if not len(v):
            return
        v = bisect_triangles(v, 64 * self.vs)                              # pas de triangle géant
        p = v[:, :, :3]
        area = 0.5 * np.linalg.norm(np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0]), axis=1)
        cum = np.cumsum(np.maximum(1.0, 4 * area / self.fine ** 2))      # nb de sous-triangles estimé
        start = 0
        while start < len(v):
            base = cum[start - 1] if start else 0.0
            end = max(int(np.searchsorted(cum, base + self.cfg.chunk_triangles, side="right")), start + 1)
            yield v[start:end]
            start = end

    # -- un lot de triangles
    def _process(self, v: np.ndarray, mat: Material, cover: list, acc: list) -> None:
        cfg, vs = self.cfg, self.vs
        v1 = bisect_triangles(v, self.coarse)
        if mat.alpha_mode == "OPAQUE":                    # couverture exacte uniquement pour les surfaces pleines
            c = covered_cells(v1[:, :, :3], vs)
            cover.append(np.unique(pack(c[:, 0], c[:, 1], c[:, 2])))
        v2 = bisect_triangles(v1, self.fine)
        p = v2[:, :, :3]
        area = 0.5 * np.linalg.norm(np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0]), axis=1)
        centroid = p.mean(axis=1)
        uv, vcol = v2[:, :, 3:5].mean(axis=1), v2[:, :, 5:9].mean(axis=1)

        if mat.texture is not None:                       # niveau de mip ~ taille de l'échantillon en texels
            w0, h0 = mat.texture.size
            d1, d2 = v2[:, 1, 3:5] - v2[:, 0, 3:5], v2[:, 2, 3:5] - v2[:, 0, 3:5]
            uv_area = 0.5 * np.abs(d1[:, 0] * d2[:, 1] - d1[:, 1] * d2[:, 0]) * w0 * h0
            lod = np.log2(np.maximum(np.sqrt(2 * uv_area), 1.0))
            rgb, a = mat.texture.sample(uv, lod)
        else:
            rgb, a = np.ones((len(uv), 3), np.float32), np.ones(len(uv), np.float32)
        bc = np.asarray(mat.base_color, dtype=np.float64)
        rgb = rgb * bc[:3] * vcol[:, :3]
        alpha = a * bc[3] * vcol[:, 3]

        if mat.alpha_mode == "OPAQUE":
            alpha = np.ones_like(alpha); keep = np.ones(len(alpha), bool)
        elif mat.alpha_mode == "MASK":
            keep = alpha >= mat.alpha_cutoff; alpha = np.ones_like(alpha)
        else:                                              # BLEND
            keep = alpha >= (1e-3 if cfg.keep_glass else cfg.alpha_cutoff)
            if not cfg.keep_glass:
                alpha = np.ones_like(alpha)
        if not keep.any():
            return
        cells = np.floor(centroid[keep] / vs).astype(np.int64)
        keys = pack(cells[:, 0], cells[:, 1], cells[:, 2])
        w = np.maximum(area[keep], 1e-12)
        uk, inv = np.unique(keys, return_inverse=True)
        bc_ = lambda x: np.bincount(inv, weights=w * x[keep], minlength=len(uk))
        acc.append((uk, bc_(rgb[:, 0]), bc_(rgb[:, 1]), bc_(rgb[:, 2]), bc_(alpha),
                    np.bincount(inv, weights=w, minlength=len(uk))))
