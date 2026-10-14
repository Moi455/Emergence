"""Paramètres du moteur : un seul objet, passé partout, aucune valeur « magique » dispersée."""
from dataclasses import dataclass, field
from typing import Optional, Tuple

from .lattice import VOXEL_SIZE_M

UNIT_TO_METERS = {"m": 1.0, "dm": 0.1, "cm": 0.01, "mm": 0.001, "inch": 0.0254, "ft": 0.3048}


@dataclass
class ScaleSpec:
    """Comment passer des unités du fichier d'entrée aux mètres réels.

    - `unit`   : unité du fichier (glTF = toujours "m" ; un OBJ n'a pas d'unité définie).
    - `factor` : correctif multiplicatif libre (ex. 0.5 si le modèle est 2x trop grand).
    - `fit_*`  : alternative -> impose une dimension finale en mètres (échelle uniforme).
                 Un seul `fit_*` à la fois ; il prime sur `unit` et `factor`.
    """
    unit: str = "m"
    factor: float = 1.0
    fit_height: Optional[float] = None    # axe Y
    fit_width: Optional[float] = None     # axe X
    fit_depth: Optional[float] = None     # axe Z
    fit_longest: Optional[float] = None   # plus grande dimension


@dataclass
class VoxelizeConfig:
    voxel_size: float = VOXEL_SIZE_M
    scale: ScaleSpec = field(default_factory=ScaleSpec)
    input_up: str = "y"             # "y" (glTF, Blender export par défaut) ou "z"
    pivot: str = "keep"             # keep | min | center-bottom
    # --- surface
    coarse_edge_ratio: float = 0.9  # arête max (en voxels) pour le test de recouvrement exact
    sample_edge_ratio: float = 0.45  # arête max (en voxels) des sous-triangles échantillonnés (couleur)
    alpha_cutoff: float = 0.5       # seuil de transparence pour les matériaux BLEND
    keep_glass: bool = False        # True : garde les voxels translucides (vitres) avec leur alpha
    # --- remplissage
    fill: str = "solid"             # solid | shell
    seal_radius: int = 0            # >0 : ferme les trous <= 2*r voxels avant de remplir (modèles ouverts)
    trim_overshoot: bool = True     # retire l'excès conservatif (<=1 voxel) de la peau des solides fermés
    interior_shade: float = 1.0     # <1 assombrit l'intérieur (visualiser une coupe)
    # --- style pixel art
    palette_size: int = 32          # 0 = vraies couleurs
    palette_method: str = "oklab"   # oklab (k-means perceptuel) | mediancut (ancien, RVB)
    color_mode: str = "dominant"    # dominant : le matériau majoritaire du voxel (frontières nettes) | average : mélange
    sharpen: float = 0.30           # netteté locale OKLab (0 = aucune) : redonne du « croquant » au pixel art
    saturation: float = 1.06
    contrast: float = 1.04
    bake_ao: float = 0.0            # 0..1 : cuit l'occlusion ambiante dans la couleur (rendu sans éclairage)
    texture_dirs: Tuple[str, ...] = ()   # dossiers supplémentaires de textures (OBJ/MTL)
    # --- garde-fous mémoire
    max_entities: int = 3_000_000   # nb max d'objets Voxel (chacun coûte ~0,4 Ko)
    max_dense_cells: int = 60_000_000
    chunk_triangles: int = 300_000
