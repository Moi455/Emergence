#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Provenance : copie de « Codex (Copie)/emergence/Map/voxel_tree.py » (générateur validé par Monsieur) ;
# génération inchangée, ajout de l'exporteur .vxm (docs/19a § 1, tâche L04 de docs/19b).
"""
voxel_tree.py — Générateur procédural d'arbres en voxels de 5 cm, piloté par une graine.

Principe
--------
1. SQUELETTE : croissance stochastique ordre par ordre (tronc -> charpentières -> branches
   -> rameaux -> brindilles), avec phyllotaxie (angle d'or), tropismes (phototropisme /
   affaissement), enveloppe de couronne propre à chaque essence et auto-élagage
   (une branche qui pousse dans une zone déjà encombrée avorte, comme à l'ombre).
2. ÉPAISSEURS : modèle « pipe model » (Léonard de Vinci) — le rayon d'un nœud découle de la
   somme des sections de ses enfants (exposant 2,4) + effilement, puis étalonnage allométrique
   sur le rayon du tronc attendu pour la hauteur (empattement + contreforts racinaires).
3. FEUILLAGE : amas de feuilles (ellipsoïdes bruités) posés sur les rameaux terminaux, avec
   trouées, feuilles « doubles » (grandes feuilles) ou aiguilles retombantes (conifères).
4. VOXELISATION : tout est calculé en mètres puis rastérisé à 5 cm (capsules effilées pour le bois
   épais, tracé 3D continu pour les brindilles fines).
5. COULEURS : palette limitée (<= 255 couleurs, compatible MagicaVoxel) ; ombrage « cuit »
   (lumière du ciel + soleil estimés sur la densité de matière) + bruit d'écorce / de feuillage.

Un même (graine, essence, hauteur, saison) redonne TOUJOURS exactement le même arbre.

Utilisation
-----------
    python voxel_tree.py --seed 42 --species chene --height 18 --preview
    python voxel_tree.py --seed "mon arbre" --species auto --season autumn --formats npz,vox,obj
    python voxel_tree.py --seed 1 --batch 8 --species auto --out forets/arbre

Dépendances : numpy (obligatoire), Pillow (uniquement pour l'aperçu PNG).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import struct
import sys
import time
import zlib
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

# --------------------------------------------------------------------------------------
# Constantes
# --------------------------------------------------------------------------------------
VOXEL = 0.05          # taille d'un voxel en mètres (5 cm)
MAX_HEIGHT = 20.0     # hauteur maximale supportée (m)
MIN_HEIGHT = 2.0
STEPS = 30            # nuances par rampe de couleur
GOLDEN = 2.399963229728653   # angle d'or (rad)

KIND_BARK, KIND_LEAF, KIND_TWIG, KIND_FLOWER, KIND_FRUIT = 1, 2, 3, 4, 5

Ramp = Tuple[Tuple[int, int, int], Tuple[int, int, int], Tuple[int, int, int]]  # sombre, moyen, clair


# --------------------------------------------------------------------------------------
# Graine, bruit de valeur 3D (déterministe, vectorisé)
# --------------------------------------------------------------------------------------
def seed_to_int(seed) -> int:
    """Accepte un entier, une chaîne numérique ou un texte libre (haché en SHA-256)."""
    if isinstance(seed, (int, np.integer)):
        return int(seed) & 0xFFFFFFFFFFFFFFFF
    s = str(seed).strip()
    try:
        return int(s) & 0xFFFFFFFFFFFFFFFF
    except ValueError:
        return int.from_bytes(hashlib.sha256(s.encode("utf-8")).digest()[:8], "little")


def _hash01(ix, iy, iz, seed: int) -> np.ndarray:
    h = (ix.astype(np.uint32) * np.uint32(73856093)) \
        ^ (iy.astype(np.uint32) * np.uint32(19349663)) \
        ^ (iz.astype(np.uint32) * np.uint32(83492791))
    h ^= np.uint32((seed * 2654435761) & 0xFFFFFFFF)
    h ^= h >> np.uint32(15)
    h *= np.uint32(2246822519)
    h ^= h >> np.uint32(13)
    h *= np.uint32(3266489917)
    h ^= h >> np.uint32(16)
    return (h >> np.uint32(8)).astype(np.float32) * np.float32(1.0 / 16777216.0)


def value_noise(p: np.ndarray, freq, seed: int) -> np.ndarray:
    """Bruit de valeur 3D lissé, sortie dans [0,1]. p : (N,3) en mètres ; freq : scalaire ou (3,)."""
    q = p.astype(np.float32) * np.asarray(freq, dtype=np.float32)
    f0 = np.floor(q)
    f = q - f0
    u = f * f * (3.0 - 2.0 * f)
    i = f0.astype(np.int64)
    x0, y0, z0 = i[:, 0], i[:, 1], i[:, 2]
    x1, y1, z1 = x0 + 1, y0 + 1, z0 + 1
    ux, uy, uz = u[:, 0], u[:, 1], u[:, 2]
    c000 = _hash01(x0, y0, z0, seed); c100 = _hash01(x1, y0, z0, seed)
    c010 = _hash01(x0, y1, z0, seed); c110 = _hash01(x1, y1, z0, seed)
    c001 = _hash01(x0, y0, z1, seed); c101 = _hash01(x1, y0, z1, seed)
    c011 = _hash01(x0, y1, z1, seed); c111 = _hash01(x1, y1, z1, seed)
    a = c000 + (c100 - c000) * ux
    b = c010 + (c110 - c010) * ux
    c = c001 + (c101 - c001) * ux
    d = c011 + (c111 - c011) * ux
    e = a + (b - a) * uy
    g = c + (d - c) * uy
    return e + (g - e) * uz


# --------------------------------------------------------------------------------------
# Essences
# --------------------------------------------------------------------------------------
@dataclass
class Species:
    key: str
    nom: str
    h_range: Tuple[float, float]
    arch: str = "decurrent"                 # 'decurrent' (tronc qui se fourche) | 'excurrent' (flèche centrale)
    trunk_frac: Tuple[float, float] = (0.40, 0.50)   # (décurrent) part de H atteinte par le fût avant la fourche
    bole: Tuple[float, float] = (0.20, 0.28)         # part de H sans branches (fût dégagé)
    trunk_k: float = 0.020                  # rayon à la base ≈ k · H
    taper: float = 0.05                     # effilement par mètre de branche
    crown_r: float = 0.38                   # rayon max de couronne / H
    crown_shape: str = "dome"               # conique | dome | ovale | colonne
    max_order: int = 4
    # tableaux indexés par ordre (0 tronc, 1 charpentière, 2 branche, 3 rameau, 4 brindille)
    density: Tuple[float, ...] = (1.6, 1.3, 1.7, 2.0, 0.0)   # enfants par mètre, selon l'ordre du PARENT
    whorl: int = 1                          # nb de branches par verticille (conifères)
    angle: Tuple[float, ...] = (0, 58, 50, 46, 42)           # degrés, selon l'ordre de l'ENFANT
    angle_var: float = 0.18
    len_ratio: Tuple[float, ...] = (0, 1.0, 0.60, 0.55, 0.50)
    step: Tuple[float, ...] = (0.55, 0.42, 0.28, 0.20, 0.14)
    min_len: Tuple[float, ...] = (0, 0.9, 0.40, 0.28, 0.18)
    wobble: Tuple[float, ...] = (0.06, 0.20, 0.28, 0.32, 0.36)
    tropism: Tuple[float, ...] = (0.02, 0.10, 0.10, 0.05, 0.0)
    up_bias: Tuple[float, ...] = (0, 0.18, 0.14, 0.10, 0.08)
    min_dz: float = -0.12
    crowd: Tuple[int, ...] = (99, 99, 16, 14, 12)
    leaders: Tuple[int, int] = (2, 4)
    leader_angle: Tuple[float, float] = (24.0, 38.0)
    stubs: float = 0.0                      # chicots sur le fût (0 = aucun)
    # feuillage
    leaf_min_order: int = 3
    leaf_start: float = 0.15
    leaf_end: float = 1.0                    # le feuillage s'arrête à cette fraction de la branche
    leaf_r: Tuple[float, ...] = (0, 0, 0, 0.42, 0.36)
    leaf_dens: float = 0.9
    leaf_spacing: float = 0.8
    leaf_stretch: float = 1.3
    leaf_flat: float = 0.8
    leaf_droop: float = 0.10
    leaf_big: float = 0.30
    evergreen: bool = False
    # arbustes (touffes multi-tiges), floraison et fructification
    multistem: Tuple[int, int] = (0, 0)             # (min, max) de tiges issues du sol ; (0,0) = arbre à tronc
    stem_lean: Tuple[float, float] = (5.0, 25.0)    # inclinaison des tiges par rapport à la verticale (°)
    stem_len: Tuple[float, float] = (0.8, 1.0)      # longueur des tiges / H
    roots: bool = True
    spring_leaf: float = 0.62                       # densité du feuillage au printemps
    flower_seasons: Tuple[str, ...] = ()
    flower_frac: float = 0.3                        # part des bouquets de feuilles qui portent une fleur
    flower_r: float = 0.07                          # rayon d'une fleur / d'une inflorescence (m)
    flower_stretch: float = 1.0                     # allongement le long de la tige (épis)
    flower_off: float = 0.0                         # décalage vers l'extrémité (m)
    flower_fill: float = 1.6
    flower_tip: float = 0.0                         # fleurs seulement au-delà de cette fraction de la branche
    flower_mix: bool = False                        # False : une seule teinte par arbuste (tirée par la graine)
    flower_ramps: Tuple[Ramp, ...] = ()
    fruit_seasons: Tuple[str, ...] = ()
    fruit_frac: float = 0.3
    fruit_r: float = 0.03
    fruit_stretch: float = 1.0
    fruit_off: float = 0.0
    fruit_fill: float = 1.6
    fruit_tip: float = 0.0
    fruit_mix: bool = False
    fruit_ramps: Tuple[Ramp, ...] = ()
    # couleurs
    bark: Ramp = ((38, 30, 24), (84, 70, 58), (128, 112, 94))
    bark_alt: Ramp = ((40, 52, 30), (78, 92, 52), (120, 132, 84))
    alt_rule: str = "moss"                  # moss | marks | upper | none
    bark_rough: float = 0.5
    twig: Ramp = ((40, 28, 20), (76, 56, 40), (110, 86, 62))
    leaves: Tuple[Ramp, ...] = (
        ((20, 48, 16), (58, 102, 28), (130, 168, 52)),
        ((32, 64, 18), (86, 124, 30), (160, 186, 60)),
        ((16, 40, 20), (40, 82, 30), (96, 136, 50)),
    )
    autumn: Tuple[Ramp, ...] = (
        ((70, 30, 10), (150, 80, 24), (214, 140, 40)),
        ((80, 50, 12), (176, 128, 30), (228, 190, 70)),
        ((48, 52, 16), (110, 100, 30), (170, 150, 50)),
    )


def _build_species() -> Dict[str, Species]:
    S: Dict[str, Species] = {}

    S["chene"] = Species(
        key="chene", nom="Chêne", h_range=(10.0, 20.0), arch="decurrent",
        trunk_frac=(0.38, 0.50), bole=(0.17, 0.25), trunk_k=0.021, taper=0.05,
        crown_r=0.40, crown_shape="dome", stubs=1.0,
        density=(1.7, 1.4, 1.9, 2.2, 0.0), angle=(0, 58, 52, 48, 44),
        len_ratio=(0, 1.0, 0.62, 0.55, 0.50),
        wobble=(0.06, 0.22, 0.30, 0.34, 0.38), tropism=(0.02, 0.10, 0.10, 0.05, 0.0),
        crowd=(99, 99, 16, 14, 12),
        leaf_min_order=3, leaf_start=0.40,
        leaf_r=(0, 0, 0, 0.30, 0.26), leaf_dens=0.42, leaf_spacing=1.1, leaf_flat=0.75, leaf_big=0.30,
        bark_rough=0.65,
    )

    S["hetre"] = Species(
        key="hetre", nom="Hêtre", h_range=(10.0, 20.0), arch="decurrent",
        trunk_frac=(0.45, 0.58), bole=(0.22, 0.32), trunk_k=0.019, taper=0.045,
        crown_r=0.34, crown_shape="dome",
        density=(1.8, 1.6, 2.1, 2.4, 0.0), angle=(0, 52, 46, 42, 40),
        len_ratio=(0, 1.0, 0.60, 0.55, 0.50),
        wobble=(0.05, 0.14, 0.20, 0.24, 0.26), tropism=(0.02, 0.06, 0.06, 0.02, 0.0),
        crowd=(99, 99, 18, 15, 13),
        leaf_min_order=3, leaf_start=0.38,
        leaf_r=(0, 0, 0, 0.32, 0.28), leaf_dens=0.42, leaf_spacing=1.1, leaf_flat=0.55, leaf_stretch=1.25,
        leaf_big=0.22, bark_rough=0.12,
        bark=((70, 66, 60), (128, 124, 116), (178, 174, 162)),
        bark_alt=((52, 66, 44), (96, 112, 80), (140, 154, 112)),
        leaves=(((18, 52, 22), (48, 110, 34), (120, 170, 58)),
                ((24, 60, 20), (70, 126, 32), (150, 184, 60)),
                ((14, 44, 22), (36, 88, 34), (92, 140, 56))),
        autumn=(((80, 30, 10), (176, 82, 24), (222, 140, 50)),
                ((90, 44, 12), (190, 112, 26), (234, 178, 64)),
                ((60, 36, 12), (140, 82, 24), (196, 130, 44))),
    )

    S["bouleau"] = Species(
        key="bouleau", nom="Bouleau", h_range=(7.0, 17.0), arch="decurrent",
        trunk_frac=(0.62, 0.78), bole=(0.25, 0.35), trunk_k=0.0145, taper=0.06,
        crown_r=0.20, crown_shape="ovale", leaders=(1, 3), leader_angle=(10.0, 20.0),
        density=(1.5, 1.4, 2.0, 2.6, 0.0), angle=(0, 45, 40, 38, 36),
        len_ratio=(0, 1.0, 0.65, 0.60, 0.55),
        wobble=(0.07, 0.20, 0.26, 0.30, 0.32), tropism=(0.05, 0.05, -0.15, -0.45, -0.5),
        up_bias=(0, 0.25, 0.10, 0.0, 0.0), min_dz=-0.85,
        crowd=(99, 99, 14, 12, 11),
        leaf_min_order=3, leaf_start=0.20, leaf_r=(0, 0, 0, 0.24, 0.20), leaf_dens=0.38, leaf_spacing=1.1,
        leaf_flat=1.2, leaf_stretch=1.9, leaf_droop=0.45, leaf_big=0.08, bark_rough=0.1,
        bark=((150, 150, 146), (214, 212, 204), (246, 244, 238)),
        bark_alt=((20, 18, 16), (46, 42, 38), (86, 80, 72)), alt_rule="marks",
        twig=((60, 30, 24), (98, 52, 40), (130, 80, 60)),
        leaves=(((30, 70, 22), (84, 140, 40), (168, 200, 70)),
                ((38, 80, 24), (110, 160, 44), (190, 214, 84)),
                ((24, 60, 22), (66, 120, 38), (140, 180, 64))),
        autumn=(((120, 90, 10), (220, 180, 30), (248, 230, 90)),
                ((140, 100, 12), (232, 196, 40), (252, 238, 120)),
                ((100, 78, 10), (190, 150, 24), (230, 206, 70))),
    )

    S["epicea"] = Species(
        key="epicea", nom="Épicéa", h_range=(8.0, 20.0), arch="excurrent",
        bole=(0.04, 0.09), trunk_k=0.0125, taper=0.11,
        crown_r=0.17, crown_shape="conique", whorl=4,
        density=(1.8, 2.6, 3.0, 3.0, 0.0), angle=(0, 78, 62, 55, 50),
        len_ratio=(0, 1.0, 0.36, 0.40, 0.40), min_len=(0, 0.28, 0.30, 0.20, 0.15),
        wobble=(0.03, 0.10, 0.16, 0.20, 0.22), tropism=(0.35, -0.06, -0.10, -0.15, -0.1),
        up_bias=(0, 0.0, 0.0, 0.0, 0.0), min_dz=-0.65,
        crowd=(99, 99, 14, 11, 9),
        leaf_min_order=1, leaf_start=0.12, leaf_r=(0, 0.30, 0.24, 0.18, 0.15), leaf_dens=0.42,
        leaf_spacing=0.9, leaf_stretch=1.6, leaf_flat=0.55, leaf_droop=0.5, leaf_big=0.0,
        evergreen=True, bark_rough=0.45,
        bark=((50, 34, 28), (92, 66, 52), (130, 98, 78)),
        bark_alt=((60, 50, 40), (104, 92, 72), (146, 134, 108)),
        leaves=(((10, 34, 22), (26, 70, 44), (70, 116, 70)),
                ((14, 40, 24), (36, 86, 50), (90, 134, 84)),
                ((8, 28, 20), (20, 58, 38), (54, 98, 60))),
    )

    S["pin"] = Species(
        key="pin", nom="Pin sylvestre", h_range=(9.0, 20.0), arch="decurrent",
        trunk_frac=(0.66, 0.80), bole=(0.48, 0.58), trunk_k=0.0165, taper=0.07,
        crown_r=0.24, crown_shape="ovale", leaders=(1, 3), leader_angle=(18.0, 32.0),
        density=(2.2, 1.6, 2.6, 2.6, 0.0), angle=(0, 64, 52, 46, 44),
        len_ratio=(0, 1.0, 0.55, 0.45, 0.40), min_len=(0, 0.8, 0.40, 0.28, 0.18),
        wobble=(0.07, 0.26, 0.30, 0.32, 0.32), tropism=(0.06, 0.12, 0.06, 0.0, 0.0),
        up_bias=(0, 0.2, 0.1, 0.05, 0.0), min_dz=-0.25,
        crowd=(99, 99, 18, 14, 12),
        leaf_min_order=2, leaf_start=0.35, leaf_r=(0, 0, 0.46, 0.32, 0.26), leaf_dens=0.70,
        leaf_spacing=1.0, leaf_stretch=1.2, leaf_flat=0.5, leaf_droop=0.0, leaf_big=0.0,
        evergreen=True, bark_rough=0.6, alt_rule="upper",
        bark=((46, 34, 28), (92, 72, 58), (136, 112, 90)),
        bark_alt=((110, 50, 22), (184, 94, 40), (220, 138, 68)),
        leaves=(((22, 50, 30), (58, 92, 50), (112, 138, 76)),
                ((26, 56, 32), (70, 104, 54), (128, 150, 82)),
                ((16, 40, 26), (44, 78, 44), (90, 120, 64))),
    )

    S["peuplier"] = Species(
        key="peuplier", nom="Peuplier d'Italie", h_range=(10.0, 20.0), arch="excurrent",
        bole=(0.08, 0.14), trunk_k=0.0165, taper=0.07,
        crown_r=0.115, crown_shape="colonne",
        density=(2.6, 2.2, 2.6, 2.6, 0.0), angle=(0, 30, 38, 40, 40),
        len_ratio=(0, 1.0, 0.45, 0.50, 0.50), min_len=(0, 0.5, 0.30, 0.22, 0.16),
        wobble=(0.03, 0.10, 0.18, 0.24, 0.26), tropism=(0.30, 0.20, 0.10, 0.05, 0.0),
        up_bias=(0, 0.45, 0.25, 0.15, 0.1), min_dz=0.05,
        crowd=(99, 99, 20, 16, 14),
        leaf_min_order=2, leaf_start=0.10, leaf_r=(0, 0, 0.32, 0.30, 0.26), leaf_dens=0.95,
        leaf_spacing=0.8, leaf_stretch=1.5, leaf_flat=1.0, leaf_droop=0.0, leaf_big=0.20,
        bark_rough=0.5,
        bark=((60, 54, 44), (110, 102, 86), (160, 150, 128)),
        leaves=(((30, 72, 24), (76, 128, 40), (152, 188, 66)),
                ((38, 84, 26), (96, 144, 44), (172, 200, 76)),
                ((22, 60, 24), (58, 108, 36), (128, 166, 58))),
        autumn=(((150, 110, 10), (235, 196, 40), (250, 235, 110)),
                ((130, 96, 10), (214, 174, 30), (246, 222, 90)),
                ((110, 80, 10), (190, 150, 24), (230, 200, 70))),
    )

    S["erable"] = Species(
        key="erable", nom="Érable", h_range=(8.0, 20.0), arch="decurrent",
        trunk_frac=(0.38, 0.50), bole=(0.18, 0.26), trunk_k=0.019, taper=0.05,
        crown_r=0.36, crown_shape="dome",
        density=(1.8, 1.6, 2.0, 2.4, 0.0), angle=(0, 50, 46, 42, 40),
        len_ratio=(0, 1.0, 0.60, 0.55, 0.50),
        wobble=(0.05, 0.16, 0.22, 0.26, 0.28), tropism=(0.02, 0.08, 0.06, 0.02, 0.0),
        crowd=(99, 99, 18, 15, 13),
        leaf_min_order=3, leaf_start=0.38,
        leaf_r=(0, 0, 0, 0.30, 0.26), leaf_dens=0.40, leaf_spacing=1.1, leaf_flat=0.75, leaf_big=0.55,
        bark_rough=0.35,
        bark=((58, 50, 44), (104, 96, 86), (150, 142, 128)),
        leaves=(((22, 64, 24), (62, 120, 36), (138, 178, 60)),
                ((30, 76, 26), (80, 136, 38), (156, 192, 64)),
                ((16, 52, 24), (44, 98, 34), (104, 148, 54))),
        autumn=(((110, 18, 12), (190, 40, 22), (232, 100, 36)),
                ((140, 56, 10), (224, 120, 24), (250, 180, 50)),
                ((150, 110, 12), (232, 190, 40), (250, 228, 100))),
    )
    return S


SPECIES: Dict[str, Species] = _build_species()


def crown_profile(shape: str, h: float) -> float:
    """Longueur relative des charpentières selon la hauteur relative h dans la couronne (0 bas, 1 sommet)."""
    h = min(1.0, max(0.0, h))
    if shape == "conique":
        return 0.12 + 0.88 * (1.0 - h) ** 0.95
    if shape == "colonne":
        return 0.45 + 0.55 * math.sin(math.pi * (0.15 + 0.70 * h))
    if shape == "ovale":
        return 0.18 + 0.82 * math.sin(math.pi * (0.05 + 0.90 * h))
    return 0.30 + 0.70 * math.sin(math.pi * (0.10 + 0.80 * h) ** 0.85)   # dome


# --------------------------------------------------------------------------------------
# Squelette
# --------------------------------------------------------------------------------------
class Skeleton:
    def __init__(self):
        self.pos: List[np.ndarray] = []
        self.dir: List[np.ndarray] = []
        self.par: List[int] = []
        self.order: List[int] = []
        self.t: List[float] = []
        self.leafy: List[Tuple[int, float]] = []   # (nœud, rayon du bouquet de feuilles)
        self.bloom: List[int] = []                 # nœuds sans feuilles mais pouvant porter fleurs/fruits

    def add(self, p, par, order, t, d) -> int:
        self.pos.append(np.array(p, dtype=np.float64))
        self.dir.append(np.array(d, dtype=np.float64))
        self.par.append(par)
        self.order.append(order)
        self.t.append(t)
        return len(self.pos) - 1


def _perp_basis(d: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    a = np.array([1.0, 0.0, 0.0]) if abs(d[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    u = np.cross(d, a)
    u /= np.linalg.norm(u)
    v = np.cross(d, u)
    return u, v


def _clamp_dz(d: np.ndarray, min_dz: float) -> np.ndarray:
    if d[2] >= min_dz:
        return d
    hz = math.hypot(d[0], d[1])
    if hz < 1e-9:
        return np.array([0.0, 0.0, 1.0])
    s = math.sqrt(max(0.0, 1.0 - min_dz * min_dz)) / hz
    return np.array([d[0] * s, d[1] * s, min_dz])


class Grower:
    """Fait pousser le squelette ordre par ordre (parcours en largeur → arbitrage équitable de l'espace)."""

    CELL = 0.5

    def __init__(self, sp: Species, H: float, rng: np.random.Generator):
        self.sp, self.H, self.rng = sp, H, rng
        self.sk = Skeleton()
        self.occ: Dict[Tuple[int, int, int], int] = {}
        self.z_bole = H * rng.uniform(*sp.bole)
        self.crown_R = H * sp.crown_r * rng.uniform(0.85, 1.15)
        self.queue: List[list] = [[] for _ in range(sp.max_order + 2)]
        self.leaf_scale = float(min(1.0, max(0.6, math.sqrt(H / 12.0)))) if sp.multistem[1] == 0 else 1.0

    # --- utilitaires -----------------------------------------------------------------
    def _key(self, p) -> Tuple[int, int, int]:
        c = self.CELL
        return (int(p[0] // c), int(p[1] // c), int(p[2] // c))

    def _touch(self, p):
        k = self._key(p)
        self.occ[k] = self.occ.get(k, 0) + 1

    def _child_dir(self, d, theta, phi, upb, min_dz):
        u, v = _perp_basis(d)
        c = d * math.cos(theta) + (u * math.cos(phi) + v * math.sin(phi)) * math.sin(theta)
        c = c + np.array([0.0, 0.0, upb])
        c /= np.linalg.norm(c)
        return _clamp_dz(c, min_dz)

    # --- pousse d'une branche --------------------------------------------------------
    def _grow(self, start: int, d0, L: float, order: int, leader: bool):
        sp, rng, sk = self.sp, self.rng, self.sk
        n = max(2, int(round(L / sp.step[order])))
        ds = L / n
        d = np.array(d0, dtype=np.float64)
        pos = sk.pos[start].copy()
        wob = sp.wobble[order] * (0.55 if leader else 1.0) * math.sqrt(ds)
        trop = sp.tropism[order] + (0.18 if leader else 0.0)
        ids = [start]
        for k in range(n):
            t = (k + 1) / n
            d = d + rng.normal(size=3) * wob
            d[2] += trop * ds * (1.0 if order == 0 else (0.35 + 0.65 * t))
            d /= math.sqrt(float(d @ d))
            if order >= 1 or sp.multistem[1] > 0:
                d = _clamp_dz(d, sp.min_dz)
            pos = pos + d * ds
            nid = sk.add(pos, ids[-1], order, t, d)
            self._touch(pos)
            ids.append(nid)
        return ids, ds

    def _pick_leaves(self, ids: List[int], order: int, ds: float):
        sp, rng, sk = self.sp, self.rng, self.sk
        if order < sp.leaf_min_order or sp.leaf_r[order] <= 0:
            return
        R = sp.leaf_r[order] * self.leaf_scale
        spacing = max(0.10, R * sp.leaf_spacing)
        dist = rng.uniform(0, spacing)
        last = len(ids) - 1
        for j in range(1, len(ids)):
            nid = ids[j]
            dist += ds
            if sk.t[nid] > sp.leaf_end:
                sk.bloom.append(nid)
                continue
            if sk.t[nid] >= sp.leaf_start and (dist >= spacing or j == last):
                r = R * rng.uniform(0.8, 1.25) * (1.2 if j == last else 1.0)
                sk.leafy.append((nid, r))
                dist = 0.0

    def _spawn(self, ids: List[int], L: float, order: int, ds: float):
        sp, rng, sk = self.sp, self.rng, self.sk
        nxt = order + 1
        if order >= sp.max_order or sp.density[order] <= 0:
            return
        dens = sp.density[order]
        acc = rng.uniform(0, 1)
        phi = rng.uniform(0, 2 * math.pi)
        theta0 = math.radians(sp.angle[nxt])
        H = self.H
        for j in range(1, len(ids)):
            nid = ids[j]
            p, tj = sk.pos[nid], sk.t[nid]
            if order == 0:
                if p[2] < self.z_bole:
                    continue
                if sp.arch == "excurrent" and tj > 0.97:
                    continue
            elif tj < 0.10:
                continue
            acc += dens * ds
            while acc >= 1.0:
                acc -= 1.0
                phi += GOLDEN + rng.normal(0, 0.25)
                for w in range(sp.whorl):
                    ph = phi + 2 * math.pi * w / sp.whorl
                    th = theta0 * (1.0 + rng.uniform(-sp.angle_var, sp.angle_var))
                    cd = self._child_dir(sk.dir[nid], th, ph, sp.up_bias[nxt], sp.min_dz)
                    if order == 0:
                        h = (p[2] - self.z_bole) / max(0.5, H - self.z_bole)
                        Lc = self.crown_R * crown_profile(sp.crown_shape, h) * rng.uniform(0.75, 1.12)
                    else:
                        Lc = L * sp.len_ratio[nxt] * (1.0 - 0.55 * tj) * rng.uniform(0.75, 1.2)
                    if Lc >= sp.min_len[nxt]:
                        self.queue[nxt].append((nid, cd, Lc, nxt, False))
        # fourche du fût en charpentières maîtresses (feuillus)
        if order == 0 and sp.arch == "decurrent":
            end = ids[-1]
            n = int(rng.integers(sp.leaders[0], sp.leaders[1] + 1))
            az0 = rng.uniform(0, 2 * math.pi)
            z_end = sk.pos[end][2]
            for k in range(n):
                az = az0 + 2 * math.pi * k / n + rng.normal(0, 0.3)
                ang = math.radians(rng.uniform(*sp.leader_angle))
                cd = self._child_dir(sk.dir[end], ang, az, 0.2, -0.1)
                Lc = max(H - z_end, 1.0) / max(math.cos(ang), 0.55) * rng.uniform(0.9, 1.1)
                self.queue[1].append((end, cd, Lc, 1, True))

    def _seed_jobs(self):
        sp, rng, sk, H = self.sp, self.rng, self.sk, self.H
        root = sk.add((0.0, 0.0, 0.0), -1, 0, 0.0, (0.0, 0.0, 1.0))
        tilt, az = math.radians(rng.uniform(0, 3.0)), rng.uniform(0, 2 * math.pi)
        d0 = np.array([math.sin(tilt) * math.cos(az), math.sin(tilt) * math.sin(az), math.cos(tilt)])
        L0 = H if sp.arch == "excurrent" else H * rng.uniform(*sp.trunk_frac)
        self.queue[0].append((root, d0, L0, 0, False))

    def run(self) -> Skeleton:
        sp, rng, sk = self.sp, self.rng, self.sk
        self._seed_jobs()
        for order in range(sp.max_order + 1):
            jobs = self.queue[order]
            perm = rng.permutation(len(jobs))
            for ji in perm:
                start, d0, L, o, leader = jobs[ji]
                if o >= 2:
                    probe = sk.pos[start] + d0 * min(L, 0.9) * 0.7
                    if self.occ.get(self._key(probe), 0) >= sp.crowd[o]:
                        continue
                ids, ds = self._grow(start, d0, L, o, leader)
                self._pick_leaves(ids, o, ds)
                self._spawn(ids, L, o, ds)
        return sk


# --------------------------------------------------------------------------------------
# Rayons (pipe model), échelle de hauteur, extras (chicots / racines)
# --------------------------------------------------------------------------------------
@dataclass
class Segments:
    p0: np.ndarray
    p1: np.ndarray
    r0: np.ndarray
    r1: np.ndarray
    trunk: np.ndarray    # bool : segment du fût (bruit de relief)


def finalize_skeleton(sk: Skeleton, sp: Species, H: float, rng: np.random.Generator):
    n = len(sk.pos)
    pos = np.array(sk.pos)
    par = np.array(sk.par)
    order = np.array(sk.order)

    # mise à l'échelle uniforme pour atteindre EXACTEMENT la hauteur demandée (feuillage compris)
    top = pos[:, 2].max()
    if sk.leafy:
        ln = np.array([i for i, _ in sk.leafy])
        lr = np.array([r for _, r in sk.leafy])
        top = max(top, float((pos[ln, 2] + 0.85 * lr * sp.leaf_flat).max()))
    s = H / top
    pos *= s

    # rayons : pipe model + effilement
    multi = sp.multistem[1] > 0
    e = 2.4
    r_tip = 0.004 if multi else 0.007
    seglen = np.zeros(n)
    seglen[1:] = np.linalg.norm(pos[1:] - pos[par[1:]], axis=1)
    has_child = np.zeros(n, dtype=bool)
    has_child[par[1:]] = True
    acc = np.zeros(n)
    r = np.zeros(n)
    for i in range(n - 1, -1, -1):
        ri = (acc[i] ** (1.0 / e)) if has_child[i] else r_tip
        r[i] = ri
        if par[i] >= 0:
            acc[par[i]] += (ri * (1.0 + sp.taper * seglen[i])) ** e
    r_target = sp.trunk_k * H * rng.uniform(0.88, 1.14)
    if multi:   # arbuste : on étalonne la plus grosse tige, pas la somme des tiges
        first = np.where((par == 0) & (order == 0))[0]
        ref = float((r[first] * (1.0 + sp.taper * seglen[first])).max())
        r *= r_target / ref
    else:
        r *= r_target / r[0]

    r1 = r[1:].copy()
    r0 = np.minimum(r[par[1:]], r[1:] * (1.0 + sp.taper * seglen[1:]))
    trunk = (order[1:] == 0)
    fl_on = not multi

    # empattement du fût
    zc = pos[1:, 2]
    flare = np.where(trunk & fl_on, 1.0 + 0.60 * np.exp(-zc / 0.65), 1.0)
    zp = pos[par[1:], 2]
    flare0 = np.where(trunk & fl_on, 1.0 + 0.60 * np.exp(-zp / 0.65), 1.0)
    r1 = r1 * flare
    r0 = r0 * flare0

    P0 = pos[par[1:]]
    P1 = pos[1:]
    segs = [Segments(P0, P1, r0, r1, trunk)]

    # chicots sur le fût (feuillus âgés)
    z_bole = 0.0
    trunk_nodes = np.where(order == 0)[0]
    if sp.stubs > 0 and len(trunk_nodes) > 2:
        zt = pos[trunk_nodes, 2]
        z_bole = float(zt.max()) * 0.6
        cnt = int(max(0, z_bole * rng.uniform(0.8, 1.6) * sp.stubs))
        sp0, sp1, sr0, sr1 = [], [], [], []
        for _ in range(cnt):
            j = int(rng.integers(1, len(trunk_nodes)))
            nid = trunk_nodes[j]
            if pos[nid, 2] > z_bole or pos[nid, 2] < 0.5:
                continue
            a = rng.uniform(0, 2 * math.pi)
            out = np.array([math.cos(a), math.sin(a), 0.30])
            out /= np.linalg.norm(out)
            rr = float(r[nid]) * 1.0
            a0 = pos[nid] + np.array([math.cos(a), math.sin(a), 0.0]) * rr * 0.9
            ln_ = rng.uniform(0.12, 0.38)
            sp0.append(a0)
            sp1.append(a0 + out * ln_)
            rs = rng.uniform(0.022, 0.042)
            sr0.append(rs * 1.35)
            sr1.append(rs * 0.8)
        if sp0:
            segs.append(Segments(np.array(sp0), np.array(sp1), np.array(sr0), np.array(sr1),
                                 np.zeros(len(sp0), dtype=bool)))

    # racines de surface / contreforts
    r_base = float(r[0])
    nroots = int(rng.integers(5, 8)) if sp.roots else 0
    az0 = rng.uniform(0, 2 * math.pi)
    rp0, rp1, rr0, rr1 = [], [], [], []
    prof = [0.62, 0.50, 0.38, 0.27, 0.17, 0.09]
    for k in range(nroots):
        a = az0 + 2 * math.pi * k / nroots + rng.normal(0, 0.25)
        d = np.array([math.cos(a), math.sin(a), -0.10])
        p = np.array([0.0, 0.0, 0.45 * r_base])
        seg = (0.9 + 3.2 * r_base) / 5.0 * rng.uniform(0.7, 1.3)
        for q in range(5):
            d = d + rng.normal(size=3) * np.array([0.12, 0.12, 0.03])
            d[2] = min(d[2], -0.02)
            d /= np.linalg.norm(d)
            pn = p + d * seg
            rp0.append(p); rp1.append(pn)
            rr0.append(prof[q] * r_base * 1.0); rr1.append(prof[q + 1] * r_base)
            p = pn
    if rp0:
        segs.append(Segments(np.array(rp0), np.array(rp1), np.array(rr0), np.array(rr1),
                             np.zeros(len(rp0), dtype=bool)))

    # fusion
    seg = Segments(
        np.concatenate([x.p0 for x in segs]), np.concatenate([x.p1 for x in segs]),
        np.concatenate([x.r0 for x in segs]), np.concatenate([x.r1 for x in segs]),
        np.concatenate([x.trunk for x in segs]),
    )
    leaf_nodes = np.array([i for i, _ in sk.leafy], dtype=np.int64)
    leaf_R = np.array([x for _, x in sk.leafy], dtype=np.float64)
    leaf_pos = pos[leaf_nodes] if len(leaf_nodes) else np.zeros((0, 3))
    leaf_dir = np.array([sk.dir[i] for i in leaf_nodes]) if len(leaf_nodes) else np.zeros((0, 3))
    leaf_t = np.array([sk.t[i] for i in leaf_nodes]) if len(leaf_nodes) else np.zeros(0)
    bn = np.array(sk.bloom, dtype=np.int64)
    if len(bn):
        anchors = (np.concatenate([leaf_pos, pos[bn]]),
                   np.concatenate([leaf_dir, np.array([sk.dir[i] for i in bn])]),
                   np.concatenate([leaf_t, np.array([sk.t[i] for i in bn])]))
    else:
        anchors = (leaf_pos, leaf_dir, leaf_t)
    return seg, leaf_pos, leaf_dir, leaf_R, anchors, r_base


# --------------------------------------------------------------------------------------
# Voxelisation
# --------------------------------------------------------------------------------------
def rasterize_segments(seg: Segments, vs: float, noise_seed: int):
    """Retourne (coords int32 (N,3), kinds uint8). Tolère x,y négatifs ; ignore z < 0 (sol)."""
    P0, P1, R0, R1 = seg.p0, seg.p1, seg.r0, seg.r1
    rmax = np.maximum(R0, R1)
    k = vs / 0.05
    thin = rmax < 0.032 * k

    out_c: List[np.ndarray] = []
    out_k: List[np.ndarray] = []

    # ---- brindilles fines : tracé continu 1 voxel d'épaisseur --------------------------
    ti = np.nonzero(thin)[0]
    if len(ti):
        A, B = P0[ti], P1[ti]
        ln = np.linalg.norm(B - A, axis=1)
        ns = np.maximum(2, np.ceil(ln / (0.35 * vs)).astype(np.int64) + 1)
        sidx = np.repeat(np.arange(len(ti)), ns)
        starts = np.cumsum(ns) - ns
        local = np.arange(ns.sum()) - np.repeat(starts, ns)
        tt = (local / np.repeat(ns - 1, ns))[:, None]
        pts = A[sidx] + (B[sidx] - A[sidx]) * tt
        c = np.floor(pts / vs).astype(np.int32)
        c = c[c[:, 2] >= 0]
        out_c.append(c)
        out_k.append(np.full(len(c), KIND_TWIG, dtype=np.uint8))

    # ---- bois épais : capsules effilées ----------------------------------------------
    for i in np.nonzero(~thin)[0]:
        A, B = P0[i], P1[i]
        ra, rb = max(R0[i], 0.04 * k), max(R1[i], 0.04 * k)
        rm = max(ra, rb) * 1.25 + 0.5 * vs
        lo = np.floor((np.minimum(A, B) - rm) / vs).astype(np.int64)
        hi = np.floor((np.maximum(A, B) + rm) / vs).astype(np.int64)
        if hi[2] < 0:
            continue
        lo[2] = max(lo[2], 0)
        xs = ((np.arange(lo[0], hi[0] + 1) + 0.5) * vs)[:, None, None]
        ys = ((np.arange(lo[1], hi[1] + 1) + 0.5) * vs)[None, :, None]
        zs = ((np.arange(lo[2], hi[2] + 1) + 0.5) * vs)[None, None, :]
        AB = B - A
        L2 = float(AB @ AB) + 1e-12
        t = ((xs - A[0]) * AB[0] + (ys - A[1]) * AB[1] + (zs - A[2]) * AB[2]) / L2
        t = np.clip(t, 0.0, 1.0)
        dx = xs - (A[0] + t * AB[0])
        dy = ys - (A[1] + t * AB[1])
        dz = zs - (A[2] + t * AB[2])
        d2 = dx * dx + dy * dy + dz * dz
        rad = ra + t * (rb - ra)
        if seg.trunk[i] and max(ra, rb) > 0.10:
            X, Y, Z = np.broadcast_arrays(xs, ys, zs)
            q = np.stack([X * 2.4, Y * 2.4, Z * 0.55], axis=-1).reshape(-1, 3)
            nz = value_noise(q, 1.0, noise_seed).reshape(X.shape)
            rad = rad * (1.0 + 0.16 * (nz - 0.5))
        m = d2 <= rad * rad
        ix, iy, iz = np.nonzero(m)
        if len(ix):
            c = np.stack([ix + lo[0], iy + lo[1], iz + lo[2]], axis=1).astype(np.int32)
            out_c.append(c)
            out_k.append(np.full(len(c), KIND_BARK, dtype=np.uint8))

    coords = np.concatenate(out_c) if out_c else np.zeros((0, 3), np.int32)
    kinds = np.concatenate(out_k) if out_k else np.zeros(0, np.uint8)
    return coords, kinds


def make_leaf_voxels(leaf_pos, leaf_dir, leaf_R, sp: Species, rng: np.random.Generator,
                     dens_mult: float, vs: float, noise_seed: int) -> np.ndarray:
    M = len(leaf_pos)
    if M == 0 or dens_mult <= 0:
        return np.zeros((0, 3), np.int32)
    vol_vox = (4.0 / 3.0) * math.pi * leaf_R ** 3 * sp.leaf_stretch * sp.leaf_flat / vs ** 3
    gate = value_noise(leaf_pos, 0.55, noise_seed)             # trouées à grande échelle
    gate = np.where(gate < 0.38, 0.15 + 0.6 * gate, 1.0)
    counts = np.maximum(1, (vol_vox * sp.leaf_dens * dens_mult * gate).astype(np.int64))
    out: List[np.ndarray] = []
    lp = leaf_pos.astype(np.float32)
    ld = leaf_dir.astype(np.float32)
    lr = leaf_R.astype(np.float32)
    start = 0
    CH = 1_500_000
    while start < M:
        cs = np.cumsum(counts[start:])
        k = int(np.searchsorted(cs, CH)) + 1
        end = min(M, start + max(1, k))
        cnt = counts[start:end]
        idx = np.repeat(np.arange(start, end), cnt)
        T = len(idx)
        g = rng.normal(size=(T, 3)).astype(np.float32)
        g /= (np.linalg.norm(g, axis=1, keepdims=True) + 1e-9)
        rad = (rng.random(T).astype(np.float32) ** (1.0 / 3.0))
        u = g * rad[:, None]
        Dn = ld[idx]
        ua = (u * Dn).sum(axis=1)
        u = u + (sp.leaf_stretch - 1.0) * ua[:, None] * Dn
        u[:, 2] *= sp.leaf_flat
        R = lr[idx][:, None]
        pts = lp[idx] + u * R
        pts[:, 2] -= sp.leaf_droop * lr[idx]
        c = np.floor(pts / vs).astype(np.int32)
        out.append(c)
        if sp.leaf_big > 0:
            mk = rng.random(T) < sp.leaf_big
            if mk.any():
                e = c[mk].copy()
                ax = rng.integers(0, 3, size=len(e))
                sg = np.where(rng.random(len(e)) < 0.5, -1, 1).astype(np.int32)
                e[np.arange(len(e)), ax] += sg
                out.append(e)
        start = end
    c = np.concatenate(out)
    return c[c[:, 2] >= 0]


def make_feature_voxels(lpos, ldir, lt, frac, r, stretch, offset, fill, tip_min,
                        rng: np.random.Generator, vs: float) -> np.ndarray:
    """Fleurs / fruits : petits amas posés sur une fraction des bouquets de feuilles."""
    if len(lpos) == 0 or frac <= 0:
        return np.zeros((0, 3), np.int32)
    sel = (lt >= tip_min) & (rng.random(len(lpos)) < frac)
    P, D = lpos[sel], ldir[sel]
    n = len(P)
    if n == 0:
        return np.zeros((0, 3), np.int32)
    R = r * rng.uniform(0.75, 1.25, n)
    C = P + D * offset
    vol = (4.0 / 3.0) * math.pi * R ** 3 * stretch / vs ** 3
    counts = np.maximum(2, (vol * fill).astype(np.int64))
    idx = np.repeat(np.arange(n), counts)
    T = len(idx)
    g = rng.normal(size=(T, 3))
    g /= (np.linalg.norm(g, axis=1, keepdims=True) + 1e-9)
    u = g * (rng.random(T) ** (1.0 / 3.0))[:, None]
    Dn = D[idx]
    u = u + (stretch - 1.0) * (u * Dn).sum(axis=1)[:, None] * Dn
    pts = C[idx] + u * R[idx][:, None]
    c = np.floor(pts / vs).astype(np.int32)
    return c[c[:, 2] >= 0]


def topiary_shell(leaf_c: np.ndarray, shape: str, rng: np.random.Generator, seed: int,
                  vs: float = VOXEL, thick: float = 0.22):
    """Taille topiaire : remplace le feuillage par une coque lisse (sphere | dome | cube | cone)
    ajustée à l'emprise du feuillage naturel, avec un léger bruit de surface.
    Retourne (voxels de la coque, fonction « à l'intérieur de la forme » pour élaguer le bois)."""
    if len(leaf_c) == 0:
        return leaf_c, None
    lo, hi = leaf_c.min(axis=0), leaf_c.max(axis=0)
    size = (hi - lo + 1).astype(np.float64)

    def dist(gx, gy, gz):
        u = (gx + 0.5 - (lo[0] + size[0] / 2)) / (size[0] / 2)
        v = (gy + 0.5 - (lo[1] + size[1] / 2)) / (size[1] / 2)
        if shape == "dome":
            w = (gz + 0.5 - lo[2]) / size[2]
            return np.sqrt(u * u + v * v + w * w)
        if shape == "cone":
            zr = (gz + 0.5 - lo[2]) / size[2]
            return np.maximum(np.hypot(u, v) / np.maximum(1.0 - 0.96 * zr, 0.04), zr)
        w = (gz + 0.5 - (lo[2] + size[2] / 2)) / (size[2] / 2)
        if shape == "cube":
            return (np.abs(u) ** 8 + np.abs(v) ** 8 + np.abs(w) ** 8) ** (1.0 / 8.0)
        return np.sqrt(u * u + v * v + w * w)

    gx, gy, gz = np.meshgrid(*[np.arange(lo[i], hi[i] + 1) for i in range(3)], indexing="ij")
    d = dist(gx, gy, gz)
    q = np.stack([gx, gy, gz], axis=-1).reshape(-1, 3).astype(np.float32) * vs
    nz = value_noise(q, 4.0, seed).reshape(d.shape)
    d = d + (nz - 0.5) * 0.10
    shell = (d <= 1.0) & (d >= 1.0 - thick) & (rng.random(d.shape) > 0.05)
    ix, iy, iz = np.nonzero(shell)
    coords = np.stack([ix + lo[0], iy + lo[1], iz + lo[2]], axis=1).astype(np.int32)
    inside = lambda c: dist(c[:, 0], c[:, 1], c[:, 2]) <= 1.0
    return coords, inside


def _encode(coords: np.ndarray, lo: np.ndarray, dims: np.ndarray) -> np.ndarray:
    c = (coords - lo).astype(np.int64)
    return (c[:, 0] * dims[1] + c[:, 1]) * dims[2] + c[:, 2]


# --------------------------------------------------------------------------------------
# Lumière « cuite » + couleurs
# --------------------------------------------------------------------------------------
def _blur(a: np.ndarray, axes, passes: int) -> np.ndarray:
    for _ in range(passes):
        for ax in axes:
            a = (np.roll(a, 1, ax) + a + np.roll(a, -1, ax)) / 3.0
    return a


def compute_light(coords: np.ndarray, cell: int = 2):
    """Retourne (ciel, soleil) ∈ [0,1] par voxel, estimés sur la densité de matière."""
    c = coords - coords.min(axis=0)
    ci = (c // cell).astype(np.int64) + 1
    dims = ci.max(axis=0) + 2
    flat = (ci[:, 0] * dims[1] + ci[:, 1]) * dims[2] + ci[:, 2]
    D = np.bincount(flat, minlength=int(dims.prod())).reshape(dims).astype(np.float32) / float(cell ** 3)
    Dl = _blur(D, (0, 1), 2)
    above = np.cumsum(Dl[:, :, ::-1], axis=2)[:, :, ::-1] - Dl
    sky = 0.18 + 0.82 * np.exp(-0.30 * above)
    Dg = _blur(D, (0, 1, 2), 3)
    gx, gy, gz = np.gradient(Dg)
    gn = np.sqrt(gx * gx + gy * gy + gz * gz) + 1e-6
    sun = np.array([0.45, -0.35, 0.82], dtype=np.float32)
    sun /= np.linalg.norm(sun)
    lam = np.clip(-(gx * sun[0] + gy * sun[1] + gz * sun[2]) / gn, 0.0, 1.0)
    w = np.clip(gn / 0.03, 0.0, 1.0)
    sunl = 0.42 * (1.0 - w) + lam * w
    return sky[ci[:, 0], ci[:, 1], ci[:, 2]], sunl[ci[:, 0], ci[:, 1], ci[:, 2]]


def build_palette(ramps: List[Ramp], steps: int = STEPS) -> np.ndarray:
    pal = np.zeros((256, 3), np.uint8)
    for r, (d, m, l) in enumerate(ramps):
        d, m, l = np.array(d, float), np.array(m, float), np.array(l, float)
        for s in range(steps):
            u = s / (steps - 1)
            col = d + (m - d) * (u / 0.5) if u < 0.5 else m + (l - m) * ((u - 0.5) / 0.5)
            pal[1 + r * steps + s] = np.clip(col, 0, 255).astype(np.uint8)
    return pal


def ramp_table(sp: Species, season: str, flower_ramps=(), fruit_ramps=()):
    """Rampes de couleur dans l'ordre de colorize() : retourne (rampes, rôles, rampes de feuilles)."""
    leaf_ramps = list(sp.leaves)
    if season == "autumn" and not sp.evergreen:
        leaf_ramps = list(sp.autumn) + [sp.leaves[0]]
    elif season == "spring" and not sp.evergreen:
        fresh = (170, 205, 70)
        leaf_ramps = [tuple(tuple(int(c * 0.55 + f * 0.45) for c, f in zip(col, fresh)) for col in ramp)
                      for ramp in leaf_ramps]
    ramps = [sp.bark, sp.bark_alt, sp.twig] + leaf_ramps + list(flower_ramps) + list(fruit_ramps)
    roles = ["bark", "bark_alt", "twig"] + ["leaf"] * len(leaf_ramps) \
        + ["flower"] * len(flower_ramps) + ["fruit"] * len(fruit_ramps)
    return ramps, roles, leaf_ramps


def colorize(coords, kinds, sp: Species, season: str, H: float, base_xy,
             rng: np.random.Generator, seed_i: int, bake: bool, flower_ramps=(), fruit_ramps=(), vs: float = VOXEL):
    N = len(coords)
    p = (coords.astype(np.float32) + 0.5) * vs
    p[:, 0] -= base_xy[0] * vs
    p[:, 1] -= base_xy[1] * vs

    if bake:
        sky, sunl = compute_light(coords, cell=max(1, int(round(0.1 / vs))))
        light = 0.50 * sky + 0.50 * sunl
        light = np.clip(light, 0, 1)
    else:
        light = np.full(N, 0.6, np.float32)

    # rampes : 0 écorce, 1 écorce secondaire, 2 rameaux, 3.. feuillage
    ramps, roles, leaf_ramps = ramp_table(sp, season, flower_ramps, fruit_ramps)
    steps = min(STEPS, 255 // len(ramps))
    palette = build_palette(ramps, steps)
    f_off = 3 + len(leaf_ramps)
    u_off = f_off + len(flower_ramps)

    ramp_idx = np.zeros(N, np.int64)
    tval = np.zeros(N, np.float32)
    s1, s2, s3, s4 = (seed_i & 0xFFFFFFF) + 11, (seed_i & 0xFFFFFFF) + 23, (seed_i & 0xFFFFFFF) + 37, (seed_i & 0xFFFFFFF) + 51

    # --- feuilles ---
    lm = kinds == KIND_LEAF
    if lm.any():
        pl = p[lm]
        n_low = 0.65 * value_noise(pl, 0.55, s1) + 0.35 * value_noise(pl, 1.3, s2)
        jit = rng.random(len(pl)).astype(np.float32)
        K = 3 if (season == "autumn" and not sp.evergreen) else len(sp.leaves)
        sel = np.floor(np.clip((n_low - 0.25) / 0.50, 0, 0.999) * K + (jit - 0.5) * 0.8).astype(np.int64)
        sel = np.clip(sel, 0, K - 1)
        if season == "autumn" and not sp.evergreen:
            patch = value_noise(pl, 0.35, s3) > 0.78
            sel = np.where(patch, 3, sel)
        ramp_idx[lm] = 3 + sel
        hi = value_noise(pl, 5.0, s4) - 0.5
        tval[lm] = 0.10 + 0.80 * light[lm] + hi * 0.22 + (rng.random(len(pl)).astype(np.float32) - 0.5) * 0.14

    # --- écorce ---
    bm = kinds == KIND_BARK
    if bm.any():
        pb = p[bm]
        fis = value_noise(pb * np.array([1.0, 1.0, 0.28], np.float32), 4.0, s1 + 5)
        fis2 = value_noise(pb, 9.0, s2 + 5)
        rough = sp.bark_rough
        tval[bm] = 0.10 + 0.78 * light[bm] + (fis - 0.5) * rough * 0.9 + (fis2 - 0.5) * rough * 0.4
        alt = np.zeros(len(pb), bool)
        if sp.alt_rule == "moss":
            m = value_noise(pb, 0.8, s3 + 5)
            jm = (rng.random(len(pb)).astype(np.float32) - 0.5) * 0.14
            alt = (m + jm > 0.68) & (pb[:, 2] < 0.18 * H)
        elif sp.alt_rule == "marks":
            m = value_noise(pb * np.array([1.0, 1.0, 5.0], np.float32), 7.0, s3 + 5)
            alt = m > 0.66
        elif sp.alt_rule == "upper":
            m = value_noise(pb, 0.6, s3 + 5)
            alt = pb[:, 2] > (0.50 * H + (m - 0.5) * 0.15 * H)
        ramp_idx[bm] = np.where(alt, 1, 0)

    # --- rameaux ---
    tm = kinds == KIND_TWIG
    if tm.any():
        pt = p[tm]
        ramp_idx[tm] = 2
        tval[tm] = 0.20 + 0.65 * light[tm] + (value_noise(pt, 6.0, s2 + 9) - 0.5) * 0.25

    # --- fleurs et fruits ---
    for kmask, off, rr in ((kinds == KIND_FLOWER, f_off, flower_ramps), (kinds == KIND_FRUIT, u_off, fruit_ramps)):
        if kmask.any() and len(rr):
            pf = p[kmask]
            K = len(rr)
            if K > 1:
                nf = value_noise(pf, 1.5, s3 + 17)
                jf = rng.random(len(pf)).astype(np.float32)
                sel = np.floor(np.clip((nf - 0.25) / 0.50, 0, 0.999) * K + (jf - 0.5) * 0.6).astype(np.int64)
                sel = np.clip(sel, 0, K - 1)
            else:
                sel = np.zeros(len(pf), np.int64)
            ramp_idx[kmask] = off + sel
            tval[kmask] = 0.32 + 0.62 * light[kmask] + (rng.random(len(pf)).astype(np.float32) - 0.5) * 0.25

    tval = np.clip(tval, 0.0, 1.0)
    pal_idx = 1 + ramp_idx * steps + np.clip((tval * (steps - 1) + 0.5).astype(np.int64), 0, steps - 1)
    return pal_idx.astype(np.uint8), palette


# --------------------------------------------------------------------------------------
# Résultat + génération
# --------------------------------------------------------------------------------------
@dataclass
class VoxelTree:
    coords: np.ndarray            # (N,3) int32, >= 0, z vers le haut
    pal: np.ndarray               # (N,) uint8 : index de palette (1..255)
    kind: np.ndarray              # (N,) uint8 : 1 écorce, 2 feuille/aiguille, 3 rameau
    palette: np.ndarray           # (256,3) uint8
    base: Tuple[int, int]         # voxel (x,y) du pied du tronc
    voxel_size: float = VOXEL
    meta: dict = field(default_factory=dict)
    export: dict = field(default_factory=dict)   # rampes, rôles, nuances : données de l'exporteur .vxm

    @property
    def size(self) -> Tuple[int, int, int]:
        return tuple(int(v) for v in (self.coords.max(axis=0) + 1))

    @property
    def height_m(self) -> float:
        return float(self.coords[:, 2].max() + 1) * self.voxel_size


def generate_tree(seed=0, species: str = "auto", height: Optional[float] = None,
                  season: str = "summer", leaf_density: float = 1.0,
                  bake_light: bool = True, verbose: bool = False, *,
                  table: Optional[Dict[str, Species]] = None, grower_cls=None,
                  hmin: float = MIN_HEIGHT, hmax: float = MAX_HEIGHT,
                  topiary: Optional[str] = None, voxel: float = VOXEL) -> VoxelTree:
    """Génère un arbre (ou, avec `table`/`grower_cls`, un arbuste) en voxels de 5 cm.
    Mêmes arguments → même résultat."""
    vs = float(voxel)
    table = SPECIES if table is None else table
    grower_cls = Grower if grower_cls is None else grower_cls
    t0 = time.time()
    seed_i = seed_to_int(seed)
    ss = np.random.SeedSequence(seed_i)
    r_sp, r_grow, r_leaf, r_col, r_ext, r_flo = [np.random.default_rng(s) for s in ss.spawn(6)]

    keys = list(table.keys())
    pick = int(r_sp.integers(len(keys)))
    hr = float(r_sp.random())
    if species == "auto":
        sp = table[keys[pick]]
    elif species in table:
        sp = table[species]
    else:
        raise ValueError(f"Essence inconnue « {species} ». Choix : auto, {', '.join(keys)}")
    if height is None:
        H = sp.h_range[0] + hr * (sp.h_range[1] - sp.h_range[0])
    else:
        H = float(height)
    H = float(min(hmax, max(hmin, H)))
    if season not in ("summer", "spring", "autumn", "winter"):
        raise ValueError("Saison : summer, spring, autumn ou winter")
    if topiary not in (None, "sphere", "dome", "cube", "cone"):
        raise ValueError("Taille topiaire : sphere, dome, cube ou cone")

    def log(msg):
        if verbose:
            print(f"  [{time.time() - t0:5.1f}s] {msg}", flush=True)

    grower = grower_cls(sp, H, r_grow)
    sk = grower.run()
    log(f"squelette : {len(sk.pos)} nœuds, {len(sk.leafy)} bouquets de feuilles")
    seg, lpos, ldir, lR, anchors, r_base = finalize_skeleton(sk, sp, H, r_ext)
    log(f"rayon à la base : {r_base * 100:.0f} cm ; {len(seg.p0)} segments")

    bark_c, bark_k = rasterize_segments(seg, vs, (seed_i & 0xFFFFFF) + 3)
    log(f"bois : {len(bark_c):,} voxels (avant dédoublonnage)")

    leaf_mult = leaf_density
    if not sp.evergreen:
        leaf_mult *= {"summer": 1.0, "spring": sp.spring_leaf, "autumn": 0.85, "winter": 0.0}[season]
    leaf_c = make_leaf_voxels(lpos, ldir, lR, sp, r_leaf, leaf_mult, vs, (seed_i & 0xFFFFFF) + 9)
    log(f"feuillage : {len(leaf_c):,} voxels (avant dédoublonnage)")

    # fleurs / fruits selon la saison
    empty = np.zeros((0, 3), np.int32)
    flower_c, fruit_c = empty, empty
    flower_ramps: Tuple[Ramp, ...] = ()
    fruit_ramps: Tuple[Ramp, ...] = ()
    if topiary:
        leaf_c, inside = topiary_shell(leaf_c, topiary, r_flo, (seed_i & 0xFFFFFF) + 21, vs)
        if inside is not None:      # le bois qui sort de la forme est « taillé » lui aussi
            keep = inside(bark_c)
            bark_c, bark_k = bark_c[keep], bark_k[keep]
        log(f"taille topiaire « {topiary} » : {len(leaf_c):,} voxels")
    else:
        if season in sp.flower_seasons and sp.flower_ramps:
            flower_ramps = sp.flower_ramps if sp.flower_mix else \
                (sp.flower_ramps[int(r_flo.integers(len(sp.flower_ramps)))],)
            flower_c = make_feature_voxels(*anchors, sp.flower_frac, sp.flower_r, sp.flower_stretch,
                                           sp.flower_off, sp.flower_fill, sp.flower_tip, r_flo, vs)
        if season in sp.fruit_seasons and sp.fruit_ramps:
            fruit_ramps = sp.fruit_ramps if sp.fruit_mix else \
                (sp.fruit_ramps[int(r_flo.integers(len(sp.fruit_ramps)))],)
            fruit_c = make_feature_voxels(*anchors, sp.fruit_frac, sp.fruit_r, sp.fruit_stretch,
                                          sp.fruit_off, sp.fruit_fill, sp.fruit_tip, r_flo, vs)

    # plafond strict : aucun voxel au-dessus de la hauteur demandée
    zmax_vox = int(math.floor(H / vs + 1e-6))
    bark_k = bark_k[bark_c[:, 2] < zmax_vox]
    bark_c = bark_c[bark_c[:, 2] < zmax_vox]
    leaf_c = leaf_c[leaf_c[:, 2] < zmax_vox]
    flower_c = flower_c[flower_c[:, 2] < zmax_vox]
    fruit_c = fruit_c[fruit_c[:, 2] < zmax_vox]
    parts = [bark_c] + [x for x in (leaf_c, flower_c, fruit_c) if len(x)]
    allc = np.concatenate(parts)
    lo = allc.min(axis=0)
    dims = allc.max(axis=0) - lo + 1
    bark_key = np.unique(_encode(bark_c, lo, dims) * 4 + bark_k.astype(np.int64))
    bk = bark_key >> 2
    bkind = (bark_key & 3).astype(np.uint8)

    def _keys(c, excl):
        if len(c) == 0:
            return np.zeros(0, np.int64)
        k = np.unique(_encode(c, lo, dims))
        for e in excl:
            if len(e):
                k = k[~np.isin(k, e, assume_unique=True)]
        return k

    fk = _keys(flower_c, [bk])
    rk = _keys(fruit_c, [bk, fk])
    lk = _keys(leaf_c, [bk, fk, rk])
    keys_all = np.concatenate([bk, fk, rk, lk])
    kinds = np.concatenate([bkind, np.full(len(fk), KIND_FLOWER, np.uint8),
                            np.full(len(rk), KIND_FRUIT, np.uint8), np.full(len(lk), KIND_LEAF, np.uint8)])
    z = keys_all % dims[2]
    y = (keys_all // dims[2]) % dims[1]
    x = keys_all // (dims[2] * dims[1])
    coords = np.stack([x, y, z], axis=1).astype(np.int32) + lo.astype(np.int32)
    # recalage : coordonnées >= 0, pied du tronc mémorisé
    shift = np.array([coords[:, 0].min(), coords[:, 1].min(), 0], dtype=np.int32)
    coords = coords - shift
    base = (int(-shift[0]), int(-shift[1]))
    log(f"voxels finaux : {len(coords):,}")

    pal_idx, palette = colorize(coords, kinds, sp, season, H, base, r_col, seed_i, bake_light,
                                flower_ramps, fruit_ramps, vs)
    log("couleurs + lumière cuites")

    meta = dict(seed=str(seed), seed_int=seed_i, species=sp.key, nom=sp.nom, height_target=H,
                season=season, leaf_density=leaf_density, base_radius_m=r_base)
    ramps, roles, _ = ramp_table(sp, season, flower_ramps, fruit_ramps)
    export = dict(ramps=[[list(map(int, c)) for c in r] for r in ramps], ramp_roles=roles,
                  steps=min(STEPS, 255 // len(ramps)), topiary=topiary)
    return VoxelTree(coords, pal_idx, kinds, palette, base, vs, meta, export)


# --------------------------------------------------------------------------------------
# Exports
# --------------------------------------------------------------------------------------
def save_npz(tree: VoxelTree, path: str):
    np.savez_compressed(path, coords=tree.coords, palette_index=tree.pal, kind=tree.kind,
                        palette=tree.palette, base_xy=np.array(tree.base),
                        voxel_size=tree.voxel_size, **{k: np.array(str(v)) for k, v in tree.meta.items()})


def _vox_chunk(cid: bytes, content: bytes, children: bytes = b"") -> bytes:
    return cid + struct.pack("<ii", len(content), len(children)) + content + children


def _vox_dict(d: Dict[str, str]) -> bytes:
    out = struct.pack("<i", len(d))
    for k, v in d.items():
        kb, vb = k.encode(), v.encode()
        out += struct.pack("<i", len(kb)) + kb + struct.pack("<i", len(vb)) + vb
    return out


def save_vox(tree: VoxelTree, path: str):
    """MagicaVoxel .vox (v150) avec graphe de scène : découpage automatique en blocs de 256³."""
    c = tree.coords.astype(np.int64)
    tile = c // 256
    tkey = (tile[:, 0] * 1024 + tile[:, 1]) * 1024 + tile[:, 2]
    order = np.argsort(tkey, kind="stable")
    tkey_s = tkey[order]
    bounds = np.flatnonzero(np.diff(tkey_s)) + 1
    groups = np.split(order, bounds)

    models, nodes = b"", b""
    n_models = len(groups)
    child_ids = [2 + 2 * m for m in range(n_models)]
    nodes += _vox_chunk(b"nTRN", struct.pack("<i", 0) + _vox_dict({}) + struct.pack("<iiii", 1, -1, -1, 1)
                        + _vox_dict({"_t": "0 0 0"}))
    nodes += _vox_chunk(b"nGRP", struct.pack("<i", 1) + _vox_dict({}) + struct.pack("<i", n_models)
                        + b"".join(struct.pack("<i", i) for i in child_ids))
    for m, g in enumerate(groups):
        t0 = tile[g[0]] * 256
        loc = c[g] - t0
        size = loc.max(axis=0) + 1
        xyzi = np.column_stack([loc, tree.pal[g].astype(np.int64)]).astype(np.uint8)
        models += _vox_chunk(b"SIZE", struct.pack("<iii", *[int(s) for s in size]))
        models += _vox_chunk(b"XYZI", struct.pack("<i", len(g)) + xyzi.tobytes())
        trans = t0 + size // 2 - np.array([tree.base[0], tree.base[1], 0])
        nodes += _vox_chunk(b"nTRN", struct.pack("<i", child_ids[m]) + _vox_dict({})
                            + struct.pack("<iiii", child_ids[m] + 1, -1, -1, 1)
                            + _vox_dict({"_t": f"{trans[0]} {trans[1]} {trans[2]}"}))
        nodes += _vox_chunk(b"nSHP", struct.pack("<i", child_ids[m] + 1) + _vox_dict({})
                            + struct.pack("<i", 1) + struct.pack("<i", m) + _vox_dict({}))
    rgba = np.zeros((256, 4), np.uint8)
    rgba[:, 3] = 255
    rgba[:255, :3] = tree.palette[1:256]
    body = models + nodes + _vox_chunk(b"RGBA", rgba.tobytes())
    with open(path, "wb") as f:
        f.write(b"VOX " + struct.pack("<i", 150) + _vox_chunk(b"MAIN", b"", body))


def save_obj(tree: VoxelTree, path: str):
    """OBJ + MTL : faces visibles uniquement, sommets partagés, un matériau par couleur de palette.
    Unités : mètres, Z vers le haut, pied du tronc en (0,0,0)."""
    c = tree.coords.astype(np.int64)
    lo = np.array([-2, -2, -2])
    dims = c.max(axis=0) + 6
    keys = _encode(c, lo, dims)
    skeys = np.sort(keys)
    faces_v: List[np.ndarray] = []
    faces_m: List[np.ndarray] = []
    axes = [(0, 1, 2), (1, 2, 0), (2, 0, 1)]
    corner = np.array([[0, 0], [1, 0], [1, 1], [0, 1]])
    for a, (_, ua, va) in zip(range(3), axes):
        for sgn in (1, -1):
            nb = c.copy(); nb[:, a] += sgn
            nk = _encode(nb, lo, dims)
            pos = np.searchsorted(skeys, nk)
            pos[pos >= len(skeys)] = len(skeys) - 1
            vis = skeys[pos] != nk
            vc = c[vis]
            quad = np.empty((len(vc), 4, 3), np.int64)
            for q in range(4):
                v = vc.copy()
                if sgn > 0:
                    v[:, a] += 1
                v[:, ua] += corner[q][0]
                v[:, va] += corner[q][1]
                quad[:, q] = v
            if sgn < 0:
                quad = quad[:, ::-1]
            faces_v.append(quad)
            faces_m.append(tree.pal[vis])
    quad = np.concatenate(faces_v)
    mat = np.concatenate(faces_m)
    order = np.argsort(mat, kind="stable")
    quad, mat = quad[order], mat[order]
    flat = quad.reshape(-1, 3)
    vk = _encode(flat, lo, dims + 2)
    uk, inv = np.unique(vk, return_inverse=True)
    verts = flat[np.searchsorted(vk[np.argsort(vk, kind="stable")], uk)] if False else None
    first = np.zeros(len(uk), np.int64)
    first[inv[::-1]] = np.arange(len(vk) - 1, -1, -1)
    verts = flat[first]
    verts = (verts - np.array([tree.base[0], tree.base[1], 0])) * tree.voxel_size
    inv = inv.reshape(-1, 4) + 1
    mtl_path = os.path.splitext(path)[0] + ".mtl"
    used = np.unique(mat)
    with open(mtl_path, "w") as f:
        for u in used:
            r, g, b = tree.palette[u] / 255.0
            f.write(f"newmtl c{u}\nKd {r:.4f} {g:.4f} {b:.4f}\nKa 0 0 0\nKs 0 0 0\n\n")
    with open(path, "w") as f:
        f.write(f"# arbre voxel {tree.meta.get('nom', '')} graine={tree.meta.get('seed', '')}\n")
        f.write(f"mtllib {os.path.basename(mtl_path)}\n")
        CH = 200_000
        for i in range(0, len(verts), CH):
            f.write("\n".join("v %.3f %.3f %.3f" % tuple(v) for v in verts[i:i + CH]) + "\n")
        cur = -1
        for i in range(0, len(inv), CH):
            m = mat[i:i + CH]
            q = inv[i:i + CH]
            lines = []
            for mi, qi in zip(m, q):
                if mi != cur:
                    lines.append(f"usemtl c{mi}")
                    cur = mi
                lines.append("f %d %d %d %d" % tuple(qi))
            f.write("\n".join(lines) + "\n")
    return len(quad)


# --------------------------------------------------------------------------------------
# Export .vxm (docs/19a § 1) : pont Python -> Rust, plusieurs LOD, sans ombrage cuit
# --------------------------------------------------------------------------------------
VXM_MAGIC = b"VXM1"
VXM_VERSION = 1
VXM_FLAG_ZLIB, VXM_FLAG_SKY, VXM_FLAG_PAL = 1, 2, 4
VXM_MAX_LOD = 5
VXM_PRIORITY = {KIND_BARK: 0, KIND_TWIG: 1, KIND_FLOWER: 2, KIND_FRUIT: 3, KIND_LEAF: 4}


def parse_lods(text: str) -> List[int]:
    """« 0,1,2 » -> [0, 1, 2] ; refuse l'hors-borne, les doublons et le désordre."""
    try:
        lods = [int(t) for t in text.split(",") if t.strip()]
    except ValueError:
        raise ValueError(f"--lods illisible : « {text} »")
    if not lods or any(l < 0 or l > VXM_MAX_LOD for l in lods):
        raise ValueError(f"--lods : entiers de 0 à {VXM_MAX_LOD} attendus, reçu « {text} »")
    if lods != sorted(set(lods)):
        raise ValueError("--lods doit être strictement croissant, sans doublon")
    return lods


def _vxm_section(tree: VoxelTree, lod: int, export_sky: bool, export_pal: bool, compress: bool) -> bytes:
    """Une section de LOD (19a § 1.3). Repère monde (x est, y haut, z nord), pivot = pied du tronc."""
    steps = tree.export["steps"]
    c = tree.coords.astype(np.int64)
    wx, wy, wz = c[:, 0] - tree.base[0], c[:, 2], c[:, 1] - tree.base[1]
    prio = np.array([VXM_PRIORITY.get(k, 9) for k in range(8)], np.int64)[tree.kind]
    # tri (y, z, x) puis priorité : la première sorte de chaque cellule l'emporte
    order = np.lexsort((prio, wx, wz, wy))
    cell = np.stack([wy[order], wz[order], wx[order]], axis=1)
    first = np.ones(len(order), bool)
    first[1:] = np.any(cell[1:] != cell[:-1], axis=1)
    sel = order[first]
    wx, wy, wz = wx[sel], wy[sel], wz[sel]
    lo = np.array([wx.min(), wy.min(), wz.min()], np.int64)
    dims = np.array([wx.max(), wy.max(), wz.max()], np.int64) - lo + 1
    if dims.max() > 0xFFFF:
        raise ValueError(f"LOD {lod} : boîte trop grande pour des u16 ({dims.tolist()})")
    n = len(sel)
    pal = tree.pal[sel]
    parts = [(wx - lo[0]).astype("<u2").tobytes(), (wy - lo[1]).astype("<u2").tobytes(),
             (wz - lo[2]).astype("<u2").tobytes(), tree.kind[sel].astype(np.uint8).tobytes(),
             ((pal.astype(np.int64) - 1) // steps).astype(np.uint8).tobytes()]
    if export_pal:
        parts.append(pal.astype(np.uint8).tobytes())
    if export_sky:
        sky, _ = compute_light(tree.coords, cell=max(1, int(round(0.1 / tree.voxel_size))))
        parts.append(np.clip(np.floor(sky * 255.0 + 0.5), 0, 255).astype(np.uint8)[sel].tobytes())
    body = b"".join(parts)
    if compress:
        body = zlib.compress(body, 9)
    return struct.pack("<B3x3i3III", lod, *[int(v) for v in lo], *[int(v) for v in dims], n, len(body)) + body


def save_vxm(tree_by_lod: Dict[int, VoxelTree], path: str, export_sky: bool = False, export_pal: bool = False,
             *, generator: str = "voxel_tree.py", compress: bool = True) -> int:
    """Écrit un fichier .vxm v1 (docs/19a § 1) ; octets identiques à chaque exécution.
    tree_by_lod : {lod: arbre généré avec voxel = voxel_m × 2^lod, sans ombrage cuit}. Retourne la taille écrite."""
    if not tree_by_lod:
        raise ValueError("save_vxm : aucun LOD")
    lods = sorted(tree_by_lod)
    if any((not isinstance(l, int)) or l < 0 or l > VXM_MAX_LOD for l in lods):
        raise ValueError(f"save_vxm : LOD de 0 à {VXM_MAX_LOD} attendus, reçu {lods}")
    t0 = tree_by_lod[lods[0]]
    voxel_m = t0.voxel_size / (2 ** lods[0])
    for l in lods:
        t = tree_by_lod[l]
        if len(t.coords) == 0:
            raise ValueError(f"save_vxm : LOD {l} vide")
        if t.voxel_size != voxel_m * (2 ** l):
            raise ValueError(f"save_vxm : LOD {l} a un voxel de {t.voxel_size} m au lieu de {voxel_m * 2 ** l} m")
        if not t.export or t.export.get("ramps") != t0.export.get("ramps") or t.export["steps"] != t0.export["steps"]:
            raise ValueError(f"save_vxm : rampes du LOD {l} différentes de celles du LOD {lods[0]}")
        if t.meta.get("seed_int") != t0.meta.get("seed_int") or t.meta.get("species") != t0.meta.get("species"):
            raise ValueError("save_vxm : les LOD ne viennent pas de la même recette (graine, essence)")
    gen_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), generator)
    if not os.path.isfile(gen_path):
        raise ValueError(f"save_vxm : générateur « {generator} » introuvable à côté de voxel_tree.py")
    with open(gen_path, "rb") as f:
        gen_sha = hashlib.sha256(f.read()).hexdigest()
    m, ex = t0.meta, t0.export
    head = dict(format="vxm-1", generator=generator, generator_sha256=gen_sha, seed=m["seed"], seed_int=m["seed_int"],
                species=m["species"], nom=m["nom"], height_m=m["height_target"], season=m["season"],
                leaf_density=m["leaf_density"], topiary=ex.get("topiary"), voxel_m=voxel_m,
                axes="x_est,y_haut,z_nord", source_axes="python x -> est, python y -> nord, python z -> haut",
                lods=lods, steps=ex["steps"], ramps=ex["ramps"], ramp_roles=ex["ramp_roles"],
                base_radius_m=m["base_radius_m"])
    if export_pal:
        head["palette"] = [[int(v) for v in row] for row in t0.palette]
    js = json.dumps(head, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    flags = (VXM_FLAG_ZLIB if compress else 0) | (VXM_FLAG_SKY if export_sky else 0) | (VXM_FLAG_PAL if export_pal else 0)
    out = [VXM_MAGIC, struct.pack("<HHI", VXM_VERSION, flags, len(js)), js]
    out += [_vxm_section(tree_by_lod[l], l, export_sky, export_pal, compress) for l in lods]
    data = b"".join(out)
    data += struct.pack("<I", zlib.crc32(data) & 0xFFFFFFFF)
    with open(path, "wb") as f:
        f.write(data)
    return len(data)


def build_lods(tree0: VoxelTree, regenerate, lods: List[int]) -> Dict[int, VoxelTree]:
    """Régénère l'arbre à chaque LOD (même graine, voxel = voxel_m × 2^lod) ; `regenerate(voxel)` -> VoxelTree.
    Un LOD dont le voxel dépasse la hauteur de l'arbuste (plafond strict de generate_tree : aucun voxel)
    est omis, avec un avertissement : le moteur se replie alors sur le LOD plus fin (docs/19b, L08)."""
    vm = tree0.voxel_size
    H = tree0.meta["height_target"]
    out: Dict[int, VoxelTree] = {}
    for l in lods:
        vs = vm * (2 ** l)
        if l == 0:
            out[l] = tree0
        elif math.floor(H / vs + 1e-6) < 1:
            print(f"  Attention : LOD {l} omis (voxel {vs:g} m > hauteur {H:g} m)")
        else:
            out[l] = regenerate(vs)
    return out


def orientation_scene() -> Dict[int, VoxelTree]:
    """Scène d'orientation : pivot gris, voxel rouge à l'EST (+x python), bleu au NORD (+y python).
    Une fois exportée, le rouge doit être en +x et le bleu en +z (repère monde, docs/19 § 2.6)."""
    ramps = [[(90, 90, 90), (140, 140, 140), (200, 200, 200)], [(150, 0, 0), (230, 20, 20), (255, 90, 90)],
             [(0, 0, 150), (20, 40, 230), (90, 120, 255)]]
    steps = 255 // 3
    base = (2, 2)
    coords = np.array([[2, 2, 0], [3, 2, 0], [2, 3, 0]], np.int32)
    kind = np.array([KIND_BARK, KIND_FLOWER, KIND_FRUIT], np.uint8)
    pal = np.array([1 + r * steps + steps // 2 for r in range(3)], np.uint8)
    meta = dict(seed="0", seed_int=0, species="orientation", nom="Orientation", height_target=VOXEL,
                season="summer", leaf_density=1.0, base_radius_m=0.0)
    export = dict(ramps=[[list(c) for c in r] for r in ramps], ramp_roles=["bark", "flower", "fruit"],
                  steps=steps, topiary=None)
    return {0: VoxelTree(coords, pal, kind, build_palette(ramps, steps), base, VOXEL, meta, export)}


def render_preview(tree: VoxelTree, path: str, views=((30.0, 8.0), (125.0, 8.0)), target_px: int = 900,
                   ruler_step: float = 1.0, ruler_every: int = 5):
    """Aperçu orthographique (z-buffer par peintre) avec règle graduée en mètres."""
    from PIL import Image, ImageDraw  # import tardif : Pillow n'est requis que pour l'aperçu

    vs = tree.voxel_size
    c = (tree.coords.astype(np.float32) + 0.5) * vs
    c[:, 0] -= tree.base[0] * vs
    c[:, 1] -= tree.base[1] * vs
    rgb = tree.palette[tree.pal]
    Hm = float(c[:, 2].max())
    sc = target_px / (Hm * 1.06)                  # px par mètre
    vox_px = max(1, int(math.ceil(sc * vs)))
    rad = float(np.hypot(c[:, 0], c[:, 1]).max())
    half = max(rad, 0.25 * Hm, 0.15) * 1.08
    extra = int(rad * sc * math.sin(math.radians(max(el for _, el in views)))) + 8
    pw, ph = int(2 * half * sc) + 80, int(target_px * 1.10) + 40 + extra
    ground_y = ph - 24 - extra
    panels = []
    for az, el in views:
        a, e = math.radians(az), math.radians(el)
        xr = c[:, 0] * math.cos(a) - c[:, 1] * math.sin(a)
        yr = c[:, 0] * math.sin(a) + c[:, 1] * math.cos(a)
        u = xr
        v = c[:, 2] * math.cos(e) + yr * math.sin(e)
        depth = yr * math.cos(e) - c[:, 2] * math.sin(e)
        order = np.argsort(-depth, kind="stable")
        px = ((u[order] + half) * sc).astype(np.int32) + 40
        py = (ground_y - v[order] * sc).astype(np.int32)
        col = rgb[order]
        img = np.zeros((ph, pw, 3), np.uint8)
        gy = np.linspace(0, 1, ph)[:, None, None]
        img[:] = (np.array([120, 170, 220]) * (1 - gy) + np.array([214, 232, 244]) * gy).astype(np.uint8)
        pil = Image.fromarray(img)
        dr = ImageDraw.Draw(pil)
        ry = max(18, int(half * sc * math.sin(e)))
        dr.ellipse([40, ground_y - ry, pw - 40, ground_y + ry], fill=(92, 120, 68))
        img = np.array(pil)
        if vox_px >= 6 and len(px) <= 250_000:
            # gros voxels : vrais cubes (dessus + côtés visibles, ombrés)
            h = vs / 2.0
            gd = np.array([math.sin(a) * math.cos(e), math.cos(a) * math.cos(e), -math.sin(e)])
            light = np.array([0.45, -0.35, 0.82]); light /= np.linalg.norm(light)
            faces = [((1, 0, 0), [(h, -h, -h), (h, h, -h), (h, h, h), (h, -h, h)]),
                     ((-1, 0, 0), [(-h, -h, -h), (-h, h, -h), (-h, h, h), (-h, -h, h)]),
                     ((0, 1, 0), [(-h, h, -h), (h, h, -h), (h, h, h), (-h, h, h)]),
                     ((0, -1, 0), [(-h, -h, -h), (h, -h, -h), (h, -h, h), (-h, -h, h)]),
                     ((0, 0, 1), [(-h, -h, h), (h, -h, h), (h, h, h), (-h, h, h)])]
            draw_faces = []
            for n, corners in faces:
                nv = np.array(n, float)
                if float(nv @ gd) < -1e-6:
                    offs = [((ox * math.cos(a) - oy * math.sin(a)) * sc,
                             -((oz * math.cos(e) + (ox * math.sin(a) + oy * math.cos(a)) * math.sin(e)) * sc))
                            for ox, oy, oz in corners]
                    mult = 0.72 + 0.40 * max(0.0, float(nv @ light))
                    draw_faces.append((offs, mult))
            pil2 = Image.fromarray(img)
            d2 = ImageDraw.Draw(pil2)
            pxl, pyl = px.tolist(), py.tolist()
            shaded = [np.clip(col.astype(np.float32) * m, 0, 255).astype(np.uint8).tolist() for _, m in draw_faces]
            for i in range(len(pxl)):
                cx, cy = pxl[i], pyl[i]
                for (offs, _), sc_col in zip(draw_faces, shaded):
                    d2.polygon([(cx + ox, cy + oy) for ox, oy in offs], fill=tuple(sc_col[i]))
            img = np.array(pil2)
        else:
            for dy in range(vox_px):
                for dx in range(vox_px):
                    xi, yi = px + dx - vox_px // 2, py + dy - vox_px // 2
                    ok = (xi >= 0) & (xi < pw) & (yi >= 0) & (yi < ph)
                    img[yi[ok], xi[ok]] = col[ok]
        panels.append(img)
    full = Image.fromarray(np.concatenate(panels, axis=1))
    dr = ImageDraw.Draw(full)
    for m in range(0, int(Hm / ruler_step + 1e-6) + 1):
        y = int(ground_y - m * ruler_step * sc * math.cos(math.radians(views[0][1])))
        ln = 14 if m % ruler_every == 0 else 6
        dr.line([(6, y), (6 + ln, y)], fill=(20, 20, 20), width=1)
        if m % ruler_every == 0:
            dr.text((24, y - 5), f"{round(m * ruler_step, 2):g} m", fill=(20, 20, 20))
    dr.text((8, 6), f"{tree.meta.get('nom', '')} - graine {tree.meta.get('seed', '')} - "
                    f"{Hm:.2f} m - {len(tree.coords):,} voxels de {vs * 100:g} cm", fill=(20, 20, 20))
    full.save(path)


# --------------------------------------------------------------------------------------
# Ligne de commande
# --------------------------------------------------------------------------------------
def write_orientation(out: str, compress: bool = True, export_sky: bool = False, export_pal: bool = False) -> int:
    """Écrit la scène d'orientation <out>.vxm (rouge à l'est, bleu au nord)."""
    d = os.path.dirname(out)
    if d:
        os.makedirs(d, exist_ok=True)
    n = save_vxm(orientation_scene(), out + ".vxm", export_sky, export_pal, compress=compress)
    print(f"  → {out}.vxm ({n} octets) : rouge à l'est (+x), bleu au nord (+z)")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Générateur d'arbres en voxels de 5 cm (jusqu'à 20 m).")
    ap.add_argument("--seed", default="0", help="graine : entier ou texte libre")
    ap.add_argument("--species", default="auto", help="auto | " + " | ".join(SPECIES))
    ap.add_argument("--height", type=float, default=None, help=f"hauteur en m ({MIN_HEIGHT:g}–{MAX_HEIGHT:g}) ; défaut : tirée selon l'essence")
    ap.add_argument("--season", default="summer", choices=["summer", "spring", "autumn", "winter"])
    ap.add_argument("--leaf-density", type=float, default=1.0, help="multiplicateur de densité du feuillage")
    ap.add_argument("--no-bake", action="store_true", help="ne pas cuire l'ombrage dans les couleurs")
    ap.add_argument("--out", default="arbre", help="préfixe des fichiers de sortie")
    ap.add_argument("--formats", default="npz,vox", help="liste parmi npz,vox,obj,vxm")
    ap.add_argument("--lods", default="0", help="LOD du .vxm : liste croissante de 0 à 5 (voxel = 0,05 × 2^lod)")
    ap.add_argument("--export-pal", action="store_true", help=".vxm : ajoute le canal pal (palette Python)")
    ap.add_argument("--export-sky", action="store_true", help=".vxm : ajoute le canal sky (part de ciel vue)")
    ap.add_argument("--no-compress", action="store_true", help=".vxm : corps non compressés")
    ap.add_argument("--orientation-test", action="store_true",
                    help="écrit <out>.vxm : un voxel rouge à l'est et un bleu au nord du pivot, puis s'arrête")
    ap.add_argument("--preview", nargs="?", const="auto", default=None, help="écrit un aperçu PNG")
    ap.add_argument("--batch", type=int, default=1, help="génère N arbres (graines seed, seed+1, …) ; nécessite une graine entière")
    ap.add_argument("--list", action="store_true", help="liste les essences")
    a = ap.parse_args(argv)

    if a.list:
        for k, s in SPECIES.items():
            print(f"{k:9s} {s.nom:18s} {s.h_range[0]:.0f}–{s.h_range[1]:.0f} m")
        return 0

    fmts = [f.strip() for f in a.formats.split(",") if f.strip()]
    bad = [f for f in fmts if f not in ("npz", "vox", "obj", "vxm")]
    if bad:
        ap.error(f"format inconnu : {', '.join(bad)}")
    try:
        lods = parse_lods(a.lods)
    except ValueError as e:
        ap.error(str(e))
    if a.orientation_test:
        return write_orientation(a.out, not a.no_compress, a.export_sky, a.export_pal)
    if "vxm" in fmts and not a.no_bake:
        print("  .vxm : ombrage cuit désactivé (le moteur éclaire lui-même, docs/19a § 1)")
    bake = not a.no_bake and "vxm" not in fmts
    for i in range(a.batch):
        seed = a.seed if a.batch == 1 else str(seed_to_int(a.seed) + i)
        t0 = time.time()
        tree = generate_tree(seed, a.species, a.height, a.season, a.leaf_density, bake, verbose=True)
        sx, sy, sz = tree.size
        base = a.out if a.batch == 1 else f"{a.out}_{seed}"
        d = os.path.dirname(base)
        if d:
            os.makedirs(d, exist_ok=True)
        print(f"{tree.meta['nom']} (graine {seed}) : {tree.height_m:.2f} m, {len(tree.coords):,} voxels, "
              f"emprise {sx * VOXEL:.1f} × {sy * VOXEL:.1f} m, {time.time() - t0:.1f} s")
        if "npz" in fmts:
            save_npz(tree, base + ".npz"); print("  →", base + ".npz")
        if "vox" in fmts:
            save_vox(tree, base + ".vox"); print("  →", base + ".vox")
        if "obj" in fmts:
            nf = save_obj(tree, base + ".obj"); print(f"  → {base}.obj ({nf:,} faces)")
        if "vxm" in fmts:
            by_lod = build_lods(tree, lambda v: generate_tree(seed, a.species, a.height, a.season, a.leaf_density,
                                                              False, voxel=v), lods)
            n = save_vxm(by_lod, base + ".vxm", a.export_sky, a.export_pal, compress=not a.no_compress)
            print(f"  → {base}.vxm ({n:,} octets, LOD {','.join(map(str, by_lod))}, "
                  f"{sum(len(t.coords) for t in by_lod.values()):,} voxels bruts)")
        if a.preview is not None:
            pth = base + ".png" if a.preview == "auto" else a.preview
            render_preview(tree, pth); print("  →", pth)
    return 0


if __name__ == "__main__":
    sys.exit(main())
