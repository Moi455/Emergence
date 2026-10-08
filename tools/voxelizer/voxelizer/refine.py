"""Test « le CENTRE du voxel est-il dans le maillage ? » par parité de rayons (3 axes, vote majoritaire).

Pourquoi : la surface conservative (indispensable comme barrière étanche pour le remplissage) déborde
jusqu'à 1 voxel sur chaque face. Pour un solide fermé, on retire ensuite les voxels de peau dont le
centre est hors du maillage : les dimensions deviennent justes à +-1/2 voxel, SANS biais, et des
pièces modulaires de 2 m font bien 100 cellules et s'emboîtent.

Indépendant de l'orientation des normales (on compte les traversées). Seuls les matériaux OPAQUES
participent : vitres et feuilles en alpha-cutout ne sont pas des parois.
"""
from typing import List

import numpy as np

from .config import VoxelizeConfig
from .lattice import _MASK, _OFF
from .scene import Scene3D
from .surface import SurfaceVoxelizer, bisect_triangles


class CenterInsideTester:
    def __init__(self, cfg: VoxelizeConfig, scene: Scene3D):
        self.cfg, self.scene = cfg, scene
        self.vs = cfg.voxel_size
        self._svx = SurfaceVoxelizer(cfg)          # réutilisé pour le MÊME jitter et le même découpage en lots

    def inside(self, centers: np.ndarray, min_votes: int = 2) -> np.ndarray:
        """centers (M,3) en mètres (repère après jitter implicite) -> bool (M,) : centre dans le solide."""
        votes = np.zeros(len(centers), np.int8)
        for ax in range(3):
            votes += self._parity(ax, centers)
        return votes >= min_votes

    def _parity(self, ax: int, centers: np.ndarray) -> np.ndarray:
        vs = self.vs
        b, c = [a for a in range(3) if a != ax]
        qb, qc = (np.floor(centers[:, k] / vs).astype(np.int64) for k in (b, c))
        ucols, qrank = np.unique(((qb + _OFF) << 21) | (qc + _OFF), return_inverse=True)
        ranks: List[np.ndarray] = []
        ts: List[np.ndarray] = []
        for prim in self.scene.primitives:
            if prim.material.alpha_mode != "OPAQUE":
                continue
            for chunk in self._svx._chunks(prim):
                tri = bisect_triangles(chunk, self._svx.coarse)[:, :, :3]
                self._hits(tri, ax, b, c, ucols, ranks, ts)
        ca = centers[:, ax]
        if not ranks:
            return np.zeros(len(centers), np.int8)
        r, t = np.concatenate(ranks), np.concatenate(ts)
        t0 = min(t.min(), ca.min()) - 1.0
        span = max(t.max(), ca.max()) - t0 + 1.0
        comp = np.sort(r + (t - t0) / span)                        # (colonne, position le long du rayon)
        q = qrank + (ca - t0) / span
        below = np.searchsorted(comp, q) - np.searchsorted(comp, qrank.astype(np.float64))
        return (below % 2).astype(np.int8)                         # impair = on est dans le solide

    def _hits(self, tri, ax, b, c, ucols, ranks, ts) -> None:
        vs = self.vs
        pb, pc, pa = tri[:, :, b], tri[:, :, c], tri[:, :, ax]
        lo_b, lo_c = np.floor(pb.min(1) / vs).astype(np.int64), np.floor(pc.min(1) / vs).astype(np.int64)
        hi_b, hi_c = np.floor(pb.max(1) / vs).astype(np.int64), np.floor(pc.max(1) / vs).astype(np.int64)
        for ob in (0, 1):
            for oc in (0, 1):
                ib, ic = lo_b + ob, lo_c + oc
                m = (ib <= hi_b) & (ic <= hi_c)
                key = ((ib + _OFF) << 21) | (ic + _OFF)
                pos = np.minimum(np.searchsorted(ucols, key), len(ucols) - 1)
                m &= ucols[pos] == key                              # on ne garde que les colonnes demandées
                if not m.any():
                    continue
                idx = np.nonzero(m)[0]
                x, y = (ib[idx] + 0.5) * vs, (ic[idx] + 0.5) * vs
                x1, x2, x3 = pb[idx, 0], pb[idx, 1], pb[idx, 2]
                y1, y2, y3 = pc[idx, 0], pc[idx, 1], pc[idx, 2]
                den = (y2 - y3) * (x1 - x3) + (x3 - x2) * (y1 - y3)
                ok = np.abs(den) > 1e-18                            # triangles vus par la tranche : pas de traversée
                den = np.where(ok, den, 1.0)
                l1 = ((y2 - y3) * (x - x3) + (x3 - x2) * (y - y3)) / den
                l2 = ((y3 - y1) * (x - x3) + (x1 - x3) * (y - y3)) / den
                l3 = 1.0 - l1 - l2
                hit = ok & (l1 >= 0) & (l2 >= 0) & (l3 >= 0)
                if hit.any():
                    h = idx[hit]
                    ranks.append(pos[h])
                    ts.append(l1[hit] * pa[h, 0] + l2[hit] * pa[h, 1] + l3[hit] * pa[h, 2])
