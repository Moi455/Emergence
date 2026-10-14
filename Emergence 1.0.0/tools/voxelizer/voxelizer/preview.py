"""Rendu isométrique logiciel (PIL) d'un VoxelModel : sert à contrôler visuellement le résultat."""
import math
from typing import Tuple

import numpy as np
from PIL import Image, ImageDraw

from .lattice import pack
from .model import VoxelModel

_SHADE = {"top": 1.00, "left": 0.78, "right": 0.58}      # +Y, +Z, +X : éclairage fixe, lisible en pixel art


class IsoRenderer:
    def __init__(self, target_width: int = 1100, background: Tuple[int, int, int] = (28, 30, 38)):
        self.target_width = target_width
        self.bg = background

    def render(self, model: VoxelModel, view: int = 0, interior_cutaway: bool = False) -> Image.Image:
        """view 0..3 : tourne le modèle de 90° autour de Y. interior_cutaway : coupe à mi-profondeur
        pour montrer l'intérieur plein."""
        a = model.to_arrays()
        cell, color, kind = a["cell"].copy(), a["color"], a["kind"]
        if interior_cutaway:
            keep = cell[:, 2] <= (cell[:, 2].min() + cell[:, 2].max()) // 2
            cell, color, kind = cell[keep], color[keep], kind[keep]
        for _ in range(view % 4):                                  # rotation 90° : (x,z) -> (z,-x)
            cell = np.stack([cell[:, 2], cell[:, 1], -cell[:, 0]], axis=1)
        cell = cell - cell.min(axis=0)
        x, y, z = cell[:, 0], cell[:, 1], cell[:, 2]
        keys = pack(x, y, z)
        order_k = np.sort(keys)

        def exposed(dx, dy, dz):                                   # face +axe visible si pas de voisin
            nk = keys + ((dx << 42) + (dy << 21) + dz)
            pos = np.minimum(np.searchsorted(order_k, nk), len(order_k) - 1)
            return order_k[pos] != nk
        vis = {"top": exposed(0, 1, 0), "left": exposed(0, 0, 1), "right": exposed(1, 0, 0)}
        draw_me = vis["top"] | vis["left"] | vis["right"]

        c30 = math.cos(math.radians(30))
        nx, nz, ny = int(x.max()) + 1, int(z.max()) + 1, int(y.max()) + 1
        s = max(1.0, self.target_width / ((nx + nz) * c30 + 4))
        w = int(((nx + nz) * c30 + 2) * s) + 8
        h = int(((nx + nz) * 0.5 + ny + 2) * s) + 8
        img = Image.new("RGB", (w, h), self.bg)
        d = ImageDraw.Draw(img)
        ox, oy = (nz * c30 + 1) * s + 4, (ny + 1) * s + 4

        def P(px, py, pz):
            return (ox + (px - pz) * c30 * s, oy + ((px + pz) * 0.5 - py) * s)

        palette = np.array([c[:3] for c in model.palette], np.float64)
        idx = np.nonzero(draw_me)[0]
        idx = idx[np.argsort((x + y + z)[idx], kind="stable")]     # du plus loin au plus proche
        for i in idx:
            px, py, pz = int(x[i]), int(y[i]), int(z[i])
            base = palette[color[i]]
            if vis["top"][i]:
                self._poly(d, [P(px, py + 1, pz), P(px + 1, py + 1, pz), P(px + 1, py + 1, pz + 1), P(px, py + 1, pz + 1)], base, "top")
            if vis["left"][i]:
                self._poly(d, [P(px, py, pz + 1), P(px + 1, py, pz + 1), P(px + 1, py + 1, pz + 1), P(px, py + 1, pz + 1)], base, "left")
            if vis["right"][i]:
                self._poly(d, [P(px + 1, py, pz), P(px + 1, py + 1, pz), P(px + 1, py + 1, pz + 1), P(px + 1, py, pz + 1)], base, "right")
        return img

    @staticmethod
    def _poly(d, pts, base, face):
        c = tuple(int(min(255, v * _SHADE[face])) for v in base)
        d.polygon(pts, fill=c, outline=c)
