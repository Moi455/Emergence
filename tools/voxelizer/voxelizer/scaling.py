"""Mise à l'échelle du modèle d'entrée vers des mètres réels (1 voxel = 2 cm)."""
from dataclasses import dataclass, field
from typing import List

import numpy as np

from .config import ScaleSpec, UNIT_TO_METERS


@dataclass
class ScaleReport:
    raw_size: np.ndarray            # dimensions brutes du fichier (unités du fichier)
    scale: float                    # facteur total appliqué (unités fichier -> mètres)
    size_m: np.ndarray              # dimensions finales en mètres
    size_voxels: np.ndarray         # dimensions finales en voxels
    warnings: List[str] = field(default_factory=list)

    def __str__(self) -> str:
        r, m, v = self.raw_size, self.size_m, self.size_voxels
        s = (f"échelle x{self.scale:g} : brut {r[0]:.4g} x {r[1]:.4g} x {r[2]:.4g} -> "
             f"{m[0]:.3f} x {m[1]:.3f} x {m[2]:.3f} m  =  {int(v[0])} x {int(v[1])} x {int(v[2])} voxels")
        return s + "".join(f"\n  /!\\ {w}" for w in self.warnings)


class ScaleController:
    """Calcule le facteur d'échelle, et DIAGNOSTIQUE les tailles aberrantes (cm pris pour des m...)."""

    def __init__(self, spec: ScaleSpec):
        self.spec = spec

    def resolve(self, bmin: np.ndarray, bmax: np.ndarray, voxel_size: float) -> ScaleReport:
        sp = self.spec
        raw = bmax - bmin
        fits = [(sp.fit_width, 0), (sp.fit_height, 1), (sp.fit_depth, 2)]
        chosen = [(t, ax) for t, ax in fits if t is not None]
        if sp.fit_longest is not None:
            chosen.append((sp.fit_longest, int(np.argmax(raw))))
        if len(chosen) > 1:
            raise ValueError("Un seul des paramètres fit_* peut être utilisé à la fois.")
        if sp.unit not in UNIT_TO_METERS:
            raise ValueError(f"Unité inconnue « {sp.unit} ». Valeurs : {', '.join(UNIT_TO_METERS)}")
        if chosen:
            target, axis = chosen[0]
            if raw[axis] <= 0:
                raise ValueError("Dimension nulle sur l'axe demandé : impossible d'ajuster l'échelle.")
            scale = target / raw[axis]
        else:
            scale = UNIT_TO_METERS[sp.unit] * sp.factor
        size_m = raw * scale
        rep = ScaleReport(raw, scale, size_m, np.ceil(size_m / voxel_size) + 1)
        big = size_m.max()
        if big < 0.10:
            rep.warnings.append(f"Plus grande dimension = {big * 100:.1f} cm : modèle minuscule. "
                                f"Unité réelle en cm/mm ? Essayez --unit cm ou --fit-longest.")
        elif big > 300:
            rep.warnings.append(f"Plus grande dimension = {big:.0f} m : modèle gigantesque. "
                                f"Unité réelle en cm/mm ? Essayez --unit cm (ou mm).")
        if np.prod(rep.size_voxels) > 4e9:
            rep.warnings.append("Volume > 4 milliards de cellules : voxélisez par morceaux ou réduisez l'échelle.")
        return rep

    @staticmethod
    def matrix(scale: float) -> np.ndarray:
        m = np.eye(4)
        m[:3, :3] *= scale
        return m
