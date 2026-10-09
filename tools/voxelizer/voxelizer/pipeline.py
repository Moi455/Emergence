"""Orchestration : fichier 3D -> VoxelModel. Chaque étape est un objet remplaçable."""
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional

import numpy as np

from .config import VoxelizeConfig
from .loaders import load_scene
from .model import VoxelModel
from .scaling import ScaleController, ScaleReport
from .scene import Scene3D
from .solid import GridTooLargeError, PaletteQuantizer, SolidFiller, TooManyVoxelsError
from .style import ColorStyler, OklabQuantizer
from .surface import SurfaceVoxelizer


@dataclass
class VoxelizationReport:
    scale: ScaleReport
    triangles: int
    timings: Dict[str, float] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)

    def __str__(self) -> str:
        t = "  ".join(f"{k} {v:.1f}s" for k, v in self.timings.items())
        w = "".join(f"\n  /!\\ {x}" for x in self.warnings)
        return f"{self.triangles:,} triangles | {self.scale}\n  temps : {t}{w}"


@dataclass
class VoxelizationResult:
    model: VoxelModel
    report: VoxelizationReport


class VoxelizationPipeline:
    def __init__(self, cfg: Optional[VoxelizeConfig] = None, log: Callable[[str], None] = lambda m: None):
        self.cfg = cfg or VoxelizeConfig()
        self.log = log

    def run(self, source) -> VoxelizationResult:
        t0 = time.perf_counter()
        scene = load_scene(source, self.cfg.texture_dirs)
        res = self.run_scene(scene, name=Path(source).stem)
        res.report.timings = {"chargement": time.perf_counter() - t0 - sum(res.report.timings.values()),
                              **res.report.timings}
        return res

    def run_scene(self, scene: Scene3D, name: str = "model") -> VoxelizationResult:
        cfg, timings, warns = self.cfg, {}, []

        @contextmanager
        def stage(label):
            t = time.perf_counter(); self.log(f"- {label}…")
            yield
            timings[label] = time.perf_counter() - t

        # 1) orientation, échelle, pivot (tout en une transformation affine sur les sommets)
        if cfg.input_up == "z":                              # Z-haut -> Y-haut : (x,y,z) -> (x, z, -y)
            scene = scene.transformed(np.array([[1, 0, 0, 0], [0, 0, 1, 0], [0, -1, 0, 0], [0, 0, 0, 1.0]]))
        elif cfg.input_up != "y":
            raise ValueError("input_up doit valoir 'y' ou 'z'.")
        bmin, bmax = scene.bounds()
        srep = ScaleController(cfg.scale).resolve(bmin, bmax, cfg.voxel_size)
        scene = scene.transformed(ScaleController.matrix(srep.scale))
        bmin, bmax = scene.bounds()
        shift = {"keep": np.zeros(3),
                 "min": -bmin,
                 "center-bottom": -np.array([(bmin[0] + bmax[0]) / 2, bmin[1], (bmin[2] + bmax[2]) / 2])}.get(cfg.pivot)
        if shift is None:
            raise ValueError("pivot : keep | min | center-bottom")
        if shift.any():
            m = np.eye(4); m[:3, 3] = shift
            scene = scene.transformed(m)
        self.log(str(srep))
        warns += list(scene.notes)                                  # ex. textures introuvables

        # garde-fou PRÉCOCE : on prédit la taille avant le gros calcul (le nb de voxels croît en échelle^3)
        cells = float(np.prod(srep.size_voxels + 2))
        if cfg.fill == "solid" and cells > cfg.max_dense_cells:
            r = (cfg.max_dense_cells / cells) ** (1 / 3)
            raise GridTooLargeError(
                f"Boîte de {cells:,.0f} cellules à cette échelle (max {cfg.max_dense_cells:,}). Échelle maximale "
                f"conseillée : x{r:.2g} de l'échelle demandée, ou fill='shell' (surface seule, ~échelle^2).", r)

        # 2) voxélisation
        with stage("surface"):
            surf = SurfaceVoxelizer(cfg).voxelize(scene)
        with stage("remplissage"):
            filled = SolidFiller(cfg).fill(surf, scene)
        n = len(filled.keys)
        if n > cfg.max_entities:
            r = (cfg.max_entities / n) ** (1 / (3 if cfg.fill == "solid" else 2))
            raise TooManyVoxelsError(
                f"{n:,} voxels à cette échelle (max {cfg.max_entities:,} entités). Échelle maximale conseillée : "
                f"x{r:.2g} de l'échelle demandée (ou fill='shell').", r)
        with stage("couleurs"):
            filled = ColorStyler(cfg).apply(filled)
        names = [p.material.name for p in scene.primitives]
        uniq = list(dict.fromkeys(names))
        remap = np.array([uniq.index(n) for n in names] + [0], np.int64)          # -1 (inconnu) -> dernier = 0
        if filled.material is not None:
            filled.material = remap[filled.material.astype(np.int64)].astype(np.int16)
        with stage("palette"):
            quant = OklabQuantizer if cfg.palette_method == "oklab" else PaletteQuantizer
            palette, idx = quant(cfg.palette_size).quantize(filled)
        with stage("entités"):
            model = VoxelModel.from_filled(filled, palette, idx, cfg.voxel_size, name)
            model.materials = uniq

        n_int = int((filled.kind == 1).sum())
        if cfg.fill == "solid" and n_int == 0:
            warns.append("Aucun volume fermé détecté : le modèle est une coque ouverte (toit, feuille, mur sans fond…) "
                         "ou présente des trous. Il reste une coque d'un voxel ; essayez seal_radius=2..4 pour boucher.")
        warns += srep.warnings
        srep.warnings = []
        model.info = {"source": scene.source, "scale": srep.scale, "input_size_m": srep.size_m.round(4).tolist(),
                      "pivot": cfg.pivot, "palette_size": cfg.palette_size, "trimmed_overshoot": filled.trimmed}
        return VoxelizationResult(model, VoxelizationReport(srep, scene.triangle_count, timings, warns))
