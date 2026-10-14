"""Représentation interne d'un modèle 3D d'entrée, indépendante du format de fichier."""
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np
from PIL import Image

WRAP_REPEAT, WRAP_CLAMP, WRAP_MIRROR = 10497, 33071, 33648   # constantes glTF


def srgb_to_linear(c: np.ndarray) -> np.ndarray:
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def linear_to_srgb(c: np.ndarray) -> np.ndarray:
    c = np.clip(c, 0.0, 1.0)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * np.power(c, 1 / 2.4) - 0.055)


class Texture:
    """Texture couleur en espace LINÉAIRE, alpha prémultiplié, avec chaîne de mipmaps.

    Pourquoi : un voxel de 2 cm couvre souvent des dizaines de texels. Moyenner en sRGB
    assombrit les couleurs, et échantillonner au niveau 0 crée du bruit (aliasing). On filtre
    donc dans le bon espace colorimétrique, au niveau de mip qui correspond à la taille du voxel.
    """

    def __init__(self, image: Image.Image, wrap_s=WRAP_REPEAT, wrap_t=WRAP_REPEAT, max_size=2048):
        img = image.convert("RGBA")
        while max(img.size) > max_size:                       # inutile de garder 4096 px pour du 2 cm
            img = img.resize((max(1, img.width // 2), max(1, img.height // 2)), Image.BOX)
        a = np.asarray(img, dtype=np.float32) / 255.0
        alpha = a[..., 3:4]
        level = np.concatenate([srgb_to_linear(a[..., :3]) * alpha, alpha], axis=-1).astype(np.float32)
        self.levels: List[np.ndarray] = [level]
        while min(level.shape[:2]) > 1:
            h2, w2 = level.shape[0] // 2, level.shape[1] // 2
            level = level[:h2 * 2, :w2 * 2].reshape(h2, 2, w2, 2, 4).mean(axis=(1, 3))
            self.levels.append(level)
        self.wrap_s, self.wrap_t = wrap_s, wrap_t

    @property
    def size(self) -> Tuple[int, int]:
        return self.levels[0].shape[1], self.levels[0].shape[0]      # (largeur, hauteur)

    @staticmethod
    def _wrap(i: np.ndarray, n: int, mode: int) -> np.ndarray:
        if mode == WRAP_CLAMP:
            return np.clip(i, 0, n - 1)
        if mode == WRAP_MIRROR:
            p = i % (2 * n)
            return np.where(p < n, p, 2 * n - 1 - p)
        return i % n

    def _bilinear(self, lvl: np.ndarray, uv: np.ndarray) -> np.ndarray:
        h, w = lvl.shape[:2]
        x, y = uv[:, 0] * w - 0.5, uv[:, 1] * h - 0.5            # glTF : (0,0) = coin haut-gauche
        x0, y0 = np.floor(x).astype(np.int64), np.floor(y).astype(np.int64)
        fx, fy = (x - x0)[:, None], (y - y0)[:, None]
        xa, xb = self._wrap(x0, w, self.wrap_s), self._wrap(x0 + 1, w, self.wrap_s)
        ya, yb = self._wrap(y0, h, self.wrap_t), self._wrap(y0 + 1, h, self.wrap_t)
        top = lvl[ya, xa] * (1 - fx) + lvl[ya, xb] * fx
        bot = lvl[yb, xa] * (1 - fx) + lvl[yb, xb] * fx
        return top * (1 - fy) + bot * fy

    def sample(self, uv: np.ndarray, lod: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """uv (N,2), lod (N,) -> (rgb linéaire non prémultiplié (N,3), alpha (N,))."""
        out = np.zeros((len(uv), 4), dtype=np.float32)
        lv = np.clip(np.rint(lod).astype(np.int64), 0, len(self.levels) - 1)
        for l in np.unique(lv):
            m = lv == l
            out[m] = self._bilinear(self.levels[l], uv[m])
        a = out[:, 3:4]
        rgb = np.divide(out[:, :3], a, out=np.zeros_like(out[:, :3]), where=a > 1e-6)
        return rgb, out[:, 3]


@dataclass
class Material:
    name: str = "default"
    base_color: Tuple[float, float, float, float] = (1.0, 1.0, 1.0, 1.0)   # facteur linéaire
    texture: Optional[Texture] = None
    tex_coord: int = 0
    alpha_mode: str = "OPAQUE"        # OPAQUE | MASK | BLEND
    alpha_cutoff: float = 0.5
    double_sided: bool = False


@dataclass
class MeshPrimitive:
    """Un lot de triangles partageant un matériau, déjà exprimé en coordonnées monde."""
    positions: np.ndarray                 # (V,3) float64
    indices: np.ndarray                   # (T,3) int
    material: Material
    uv: Optional[np.ndarray] = None       # (V,2)
    colors: Optional[np.ndarray] = None   # (V,4) couleurs de sommet, linéaires
    name: str = ""

    @property
    def triangle_count(self) -> int:
        return len(self.indices)


@dataclass
class Scene3D:
    primitives: List[MeshPrimitive] = field(default_factory=list)
    source: str = ""
    notes: List[str] = field(default_factory=list)      # avertissements de chargement (textures manquantes...)

    @property
    def triangle_count(self) -> int:
        return sum(p.triangle_count for p in self.primitives)

    def bounds(self) -> Tuple[np.ndarray, np.ndarray]:
        pts = [p.positions[np.unique(p.indices)] for p in self.primitives if p.triangle_count]
        if not pts:
            raise ValueError("Scène vide : aucun triangle.")
        return np.min([q.min(0) for q in pts], axis=0), np.max([q.max(0) for q in pts], axis=0)

    def transformed(self, m: np.ndarray) -> "Scene3D":
        """Nouvelle scène dont les positions sont multipliées par la matrice 4x4 `m`."""
        out = []
        for p in self.primitives:
            hom = np.c_[p.positions, np.ones(len(p.positions))] @ m.T
            out.append(MeshPrimitive(hom[:, :3], p.indices, p.material, p.uv, p.colors, p.name))
        return Scene3D(out, self.source, list(self.notes))
