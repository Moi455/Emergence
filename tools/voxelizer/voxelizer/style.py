"""Direction artistique de la couleur : tout se passe en OKLab (espace perceptuellement uniforme).

- `ColorStyler`  : netteté locale (reproduit le « croquant » du pixel art, que le moyennage de texture
                   a lissé), saturation, contraste, AO cuite (optionnelle).
- `OklabQuantizer` : palette par k-means pondéré en OKLab (teintes plus justes et moins de bandes que le
                   median-cut RGB ; les couleurs rares mais marquantes sont conservées).
"""
from typing import Tuple

import numpy as np

from .ao import voxel_ao
from .config import VoxelizeConfig
from .lattice import exposed_masks, face_delta
from .scene import linear_to_srgb, srgb_to_linear
from .solid import FilledVoxels

_M1 = np.array([[0.4122214708, 0.5363325363, 0.0514459929],
                [0.2119034982, 0.6806995451, 0.1073969566],
                [0.0883024619, 0.2817188376, 0.6299787005]], np.float32)
_M2 = np.array([[0.2104542553, 0.7936177850, -0.0040720468],
                [1.9779984951, -2.4285922050, 0.4505937099],
                [0.0259040371, 0.7827717662, -0.8086757660]], np.float32)
_M1I = np.array([[4.0767416621, -3.3077115913, 0.2309699292],
                 [-1.2684380046, 2.6097574011, -0.3413193965],
                 [-0.0041960863, -0.7034186147, 1.7076147010]], np.float32)
_M2I = np.array([[1.0, 0.3963377774, 0.2158037573],
                 [1.0, -0.1055613458, -0.0638541728],
                 [1.0, -0.0894841775, -1.2914855480]], np.float32)


def rgb8_to_oklab(rgb8: np.ndarray) -> np.ndarray:
    lin = srgb_to_linear(rgb8.astype(np.float32) / 255.0).astype(np.float32)
    return (np.cbrt(lin @ _M1.T) @ _M2.T).astype(np.float32)


def oklab_to_rgb8(lab: np.ndarray) -> np.ndarray:
    lms = (lab @ _M2I.T) ** 3
    lin = np.clip(lms @ _M1I.T, 0.0, 1.0)
    return np.rint(linear_to_srgb(lin) * 255).astype(np.uint8)


class ColorStyler:
    def __init__(self, cfg: VoxelizeConfig):
        self.cfg = cfg

    def apply(self, f: FilledVoxels) -> FilledVoxels:
        c = self.cfg
        if not (c.sharpen or c.saturation != 1 or c.contrast != 1 or c.bake_ao):
            return f
        lab = rgb8_to_oklab(f.rgb)
        masks = exposed_masks(f.keys)
        vis = masks != 0
        if c.sharpen:                                        # netteté : on s'écarte de la moyenne des voisins visibles
            s, n = np.zeros_like(lab), np.zeros(len(lab), np.float32)
            for face in range(6):
                nk = f.keys + face_delta(face)
                pos = np.minimum(np.searchsorted(f.keys, nk), len(f.keys) - 1)
                ok = (f.keys[pos] == nk) & vis[pos] & vis
                s[ok] += lab[pos[ok]]
                n[ok] += 1
            has = n > 0
            mean = s[has] / n[has, None]
            d = lab[has] - mean
            lab[has, 0] += c.sharpen * d[:, 0]
            lab[has, 1:] += 0.5 * c.sharpen * d[:, 1:]
        lab[:, 1:] *= c.saturation
        lab[:, 0] = np.clip(0.55 + (lab[:, 0] - 0.55) * c.contrast, 0.0, 1.0)
        if c.bake_ao:                                        # AO cuite : crevasses plus sombres, même sans éclairage
            ao = voxel_ao(f.keys, masks)
            lab[:, 0] *= 1.0 - c.bake_ao * (1.0 - ao)
        return FilledVoxels(f.keys, f.kind, oklab_to_rgb8(lab), f.alpha, f.trimmed, f.material)


def _kmeans(x: np.ndarray, w: np.ndarray, k: int, iters: int = 14, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    centers = [x[rng.choice(len(x), p=w / w.sum())]]
    d2 = ((x - centers[0]) ** 2).sum(1)
    for _ in range(1, k):                                    # k-means++ pondéré
        p = w * d2
        centers.append(x[rng.choice(len(x), p=p / p.sum())])
        d2 = np.minimum(d2, ((x - centers[-1]) ** 2).sum(1))
    C = np.array(centers, np.float32)
    x2 = (x ** 2).sum(1)[:, None]
    for _ in range(iters):
        a = (x2 - 2 * x @ C.T + (C ** 2).sum(1)[None, :]).argmin(1)
        wt = np.bincount(a, weights=w, minlength=k)
        for j in range(3):
            num = np.bincount(a, weights=w * x[:, j], minlength=k)
            C[:, j] = np.where(wt > 0, num / np.maximum(wt, 1e-12), C[:, j])
    return C


class OklabQuantizer:
    """Palette perceptuelle. size=0 -> couleurs exactes. Poids = effectif^0.7 : les grands aplats ne
    mangent pas toute la palette, les couleurs rares (reflets, ferrures) survivent."""

    def __init__(self, size: int):
        self.size = size

    def quantize(self, f: FilledVoxels) -> Tuple[np.ndarray, np.ndarray]:
        packed = (f.rgb[:, 0].astype(np.int64) << 16) | (f.rgb[:, 1].astype(np.int64) << 8) | f.rgb[:, 2]
        uniq, first, inv, cnt = np.unique(packed, return_index=True, return_inverse=True, return_counts=True)
        inv = inv.reshape(-1)
        cols = f.rgb[first]
        if self.size and len(uniq) > self.size:
            lab = rgb8_to_oklab(cols)
            C = _kmeans(lab, cnt.astype(np.float64) ** 0.7, self.size)
            assign = ((lab ** 2).sum(1)[:, None] - 2 * lab @ C.T + (C ** 2).sum(1)[None, :]).argmin(1)
            pal = oklab_to_rgb8(C)
            pal, remap = np.unique(pal, axis=0, return_inverse=True)
            ridx = remap.reshape(-1)[assign][inv]
        else:
            pal, ridx = cols, np.arange(len(uniq))[inv]
        pair = ridx.astype(np.int64) * 256 + f.alpha.astype(np.int64)
        up, pi = np.unique(pair, return_inverse=True)
        rgba = np.concatenate([pal[up // 256], (up % 256)[:, None].astype(np.uint8)], axis=1)
        return rgba.astype(np.uint8), pi.reshape(-1)
