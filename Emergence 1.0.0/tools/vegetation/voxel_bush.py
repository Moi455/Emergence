#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Provenance : copie de « Codex (Copie)/emergence/Map/voxel_bush.py » (générateur validé par Monsieur) ;
# génération inchangée, ajout de l'option --formats vxm (docs/19a § 1, tâche L04 de docs/19b).
"""
voxel_bush.py — Générateur procédural d'ARBUSTES en voxels de 5 cm (2 m maximum), par graine.

S'appuie sur voxel_tree.py (à placer dans le même dossier) : même moteur de croissance, mêmes
exports (.npz / .vox / .obj), même aperçu. Différences propres aux arbustes :

  * TOUFFE MULTI-TIGES : plusieurs tiges partent du sol (inclinées, parfois arquées comme chez le
    forsythia, le rosier ou la ronce) au lieu d'un tronc unique ; pas d'empattement ni de racines.
  * FLEURS ET FRUITS selon la saison : roses, épis de lavande, grappes de lilas, têtes d'hortensia,
    corolles de forsythia, baies du houx, du genévrier, de la ronce, cynorrhodons du rosier…
  * TAILLE TOPIAIRE (--topiary sphere|dome|cube|cone) : le feuillage devient une coque lisse
    (boule de buis, cône, cube…), avec léger bruit de surface.

Essences : buis, rosier, lavande, lilas, hortensia, forsythia, houx, genevrier, ronce.

Utilisation
-----------
    python voxel_bush.py --seed 42 --species rosier --season summer --preview
    python voxel_bush.py --seed 7 --species buis --height 1.2 --topiary sphere --preview
    python voxel_bush.py --seed 3 --batch 6 --species auto --formats npz,vox --out haie/b

Un même (graine, essence, hauteur, saison, topiaire) redonne TOUJOURS le même arbuste.
"""
from __future__ import annotations

import argparse
import math
import os
import sys
import time
from typing import Dict

import numpy as np

import voxel_tree as vt
from voxel_tree import Species

MAX_BUSH_HEIGHT = 2.0
MIN_BUSH_HEIGHT = 0.3


class BushGrower(vt.Grower):
    """Même croissance que les arbres, mais plusieurs tiges partent du sol au lieu d'un tronc."""

    CELL = 0.2   # cellules d'encombrement plus fines (échelle d'un arbuste)

    def _seed_jobs(self):
        sp, rng, sk, H = self.sp, self.rng, self.sk, self.H
        root = sk.add((0.0, 0.0, 0.0), -1, 0, 0.0, (0.0, 0.0, 1.0))
        n = int(rng.integers(sp.multistem[0], sp.multistem[1] + 1))
        az0 = rng.uniform(0, 2 * math.pi)
        for k in range(n):
            az = az0 + 2 * math.pi * k / n + rng.normal(0, 0.35)
            lean = math.radians(rng.uniform(*sp.stem_lean))
            d0 = np.array([math.sin(lean) * math.cos(az), math.sin(lean) * math.sin(az), math.cos(lean)])
            L = H * rng.uniform(*sp.stem_len)
            start = root
            if n > 1:   # les tiges naissent sur un petit cercle autour du pied, pas toutes au même point
                rho = H * rng.uniform(0.02, 0.07)
                start = sk.add((rho * math.cos(az), rho * math.sin(az), 0.0), root, 0, 0.0, (0.0, 0.0, 1.0))
            self.queue[0].append((start, d0, L, 0, False))


# --------------------------------------------------------------------------------------
# Essences d'arbustes
# --------------------------------------------------------------------------------------
_BASE = dict(
    arch="multistem", roots=False, stubs=0.0, bole=(0.05, 0.10), taper=0.06,
    step=(0.12, 0.09, 0.07, 0.05, 0.04), min_len=(0, 0.10, 0.07, 0.05, 0.04),
    up_bias=(0, 0.20, 0.15, 0.10, 0.05), angle_var=0.20, leaders=(0, 0), alt_rule="none",
)


def _sp(**kw) -> Species:
    """Valeurs communes aux arbustes, surchargées par celles de l'essence."""
    return Species(**{**_BASE, **kw})


def _build_bushes() -> Dict[str, Species]:
    B: Dict[str, Species] = {}

    B["buis"] = _sp(
        key="buis", nom="Buis", h_range=(0.5, 1.6),
        multistem=(14, 24), stem_lean=(4.0, 24.0), stem_len=(0.75, 1.0),
        trunk_k=0.016, crown_r=0.55, crown_shape="dome", max_order=3, bark_rough=0.2,
        density=(9, 10, 12, 0, 0), angle=(0, 48, 46, 44, 40), len_ratio=(0, 1.0, 0.60, 0.55, 0.50),
        wobble=(0.15, 0.30, 0.35, 0.40, 0.40), tropism=(0.10, 0.05, 0.0, 0.0, 0.0), min_dz=-0.10,
        crowd=(99, 99, 40, 34, 30),
        leaf_min_order=2, leaf_start=0.15, leaf_r=(0, 0, 0.11, 0.09, 0.08), leaf_dens=0.9,
        leaf_spacing=0.8, leaf_stretch=1.1, leaf_flat=0.9, leaf_droop=0.0, leaf_big=0.10, evergreen=True,
        bark=((60, 52, 40), (112, 100, 78), (160, 146, 116)),
        twig=((40, 52, 28), (76, 92, 48), (112, 128, 70)),
        leaves=(((8, 36, 18), (24, 78, 34), (78, 128, 56)),
                ((10, 40, 20), (30, 88, 38), (94, 140, 64)),
                ((6, 28, 16), (18, 62, 30), (60, 104, 48))),
    )

    B["rosier"] = _sp(
        key="rosier", nom="Rosier", h_range=(0.8, 1.8),
        multistem=(5, 9), stem_lean=(8.0, 28.0), stem_len=(1.0, 1.3),
        trunk_k=0.012, taper=0.07, crown_r=0.42, crown_shape="ovale", max_order=3, bark_rough=0.2,
        density=(5, 6, 7, 0, 0), angle=(0, 50, 45, 42, 40), len_ratio=(0, 1.0, 0.55, 0.50, 0.50),
        wobble=(0.12, 0.25, 0.30, 0.35, 0.35), tropism=(-0.18, 0.0, 0.0, 0.0, 0.0), min_dz=-0.30,
        crowd=(99, 99, 30, 26, 22), spring_leaf=0.5,
        leaf_min_order=2, leaf_start=0.10, leaf_r=(0, 0, 0.11, 0.09, 0.08), leaf_dens=0.55,
        leaf_spacing=1.0, leaf_stretch=1.2, leaf_flat=0.7, leaf_droop=0.05, leaf_big=0.30,
        bark=((50, 60, 30), (92, 106, 52), (132, 144, 78)),
        twig=((70, 34, 26), (112, 60, 40), (150, 92, 64)),
        leaves=(((14, 48, 22), (36, 98, 40), (96, 150, 68)),
                ((20, 54, 24), (52, 112, 44), (116, 164, 76)),
                ((30, 44, 22), (70, 86, 40), (120, 128, 66))),
        flower_seasons=("spring", "summer", "autumn"), flower_frac=0.28, flower_r=0.075, flower_off=0.04,
        flower_ramps=(((90, 6, 16), (190, 20, 40), (240, 90, 110)),
                      ((150, 50, 90), (236, 120, 160), (255, 196, 214)),
                      ((170, 160, 140), (240, 232, 214), (255, 252, 240)),
                      ((150, 110, 10), (240, 196, 30), (255, 236, 110))),
        fruit_seasons=("autumn", "winter"), fruit_frac=0.35, fruit_r=0.03, fruit_off=0.05, fruit_tip=0.4,
        fruit_ramps=(((90, 20, 10), (200, 50, 20), (240, 110, 50)),),
    )

    B["lavande"] = _sp(
        key="lavande", nom="Lavande", h_range=(0.35, 0.9),
        multistem=(22, 38), stem_lean=(20.0, 50.0), stem_len=(0.85, 1.0), bole=(0.0, 0.05),
        trunk_k=0.007, taper=0.05, crown_r=0.70, crown_shape="dome", max_order=2, bark_rough=0.1,
        step=(0.08, 0.06, 0.05, 0.04, 0.04), min_len=(0, 0.06, 0.05, 0.04, 0.04),
        density=(4, 3, 0, 0, 0), angle=(0, 40, 36, 36, 36), len_ratio=(0, 1.0, 0.45, 0.4, 0.4),
        wobble=(0.10, 0.20, 0.25, 0.3, 0.3), tropism=(0.05, 0.05, 0.0, 0.0, 0.0), min_dz=0.0,
        crowd=(99, 99, 40, 40, 40),
        leaf_min_order=0, leaf_start=0.0, leaf_end=0.55, leaf_r=(0.07, 0.06, 0.05, 0, 0), leaf_dens=0.75,
        leaf_spacing=0.9, leaf_stretch=1.6, leaf_flat=1.0, leaf_droop=0.0, leaf_big=0.0, evergreen=True,
        bark=((60, 56, 44), (110, 104, 84), (156, 150, 124)),
        twig=((70, 80, 60), (116, 130, 96), (160, 172, 130)),
        leaves=(((50, 66, 52), (110, 130, 100), (170, 186, 150)),
                ((56, 74, 56), (124, 144, 108), (184, 198, 160)),
                ((44, 60, 48), (96, 116, 92), (150, 166, 136))),
        flower_seasons=("summer",), flower_frac=0.7, flower_r=0.018, flower_stretch=3.5,
        flower_off=0.0, flower_fill=2.2, flower_tip=0.72,
        flower_ramps=(((70, 40, 120), (130, 90, 190), (190, 160, 230)),
                      ((50, 50, 140), (100, 100, 200), (160, 160, 235)),
                      ((120, 90, 150), (180, 150, 205), (226, 210, 240))),
    )

    B["lilas"] = _sp(
        key="lilas", nom="Lilas", h_range=(1.3, 2.0),
        multistem=(6, 12), stem_lean=(3.0, 14.0), stem_len=(0.9, 1.0), bole=(0.0, 0.05),
        trunk_k=0.016, crown_r=0.30, crown_shape="dome", max_order=3, bark_rough=0.35,
        density=(5, 6, 6, 0, 0), angle=(0, 42, 40, 38, 36), len_ratio=(0, 1.0, 0.55, 0.50, 0.50),
        wobble=(0.10, 0.20, 0.25, 0.30, 0.30), tropism=(0.12, 0.08, 0.02, 0.0, 0.0),
        up_bias=(0, 0.25, 0.20, 0.10, 0.10), min_dz=-0.15, crowd=(99, 99, 30, 26, 22), spring_leaf=0.30,
        leaf_min_order=2, leaf_start=0.20, leaf_r=(0, 0, 0.13, 0.11, 0.10), leaf_dens=0.42,
        leaf_spacing=1.0, leaf_stretch=1.2, leaf_flat=0.7, leaf_droop=0.05, leaf_big=0.55,
        bark=((60, 50, 44), (108, 96, 84), (150, 138, 120)),
        twig=((70, 56, 40), (112, 94, 66), (150, 130, 92)),
        leaves=(((20, 58, 24), (56, 108, 38), (122, 160, 62)),
                ((26, 66, 26), (70, 122, 40), (140, 176, 66)),
                ((16, 48, 24), (42, 90, 34), (100, 140, 56))),
        autumn=(((100, 90, 14), (170, 150, 36), (212, 196, 82)),
                ((90, 70, 14), (160, 120, 30), (206, 164, 64)),
                ((60, 70, 20), (120, 128, 40), (170, 176, 76))),
        flower_seasons=("spring",), flower_frac=0.9, flower_r=0.07, flower_stretch=1.5, flower_off=0.10, flower_tip=0.55,
        flower_ramps=(((100, 50, 140), (170, 110, 200), (220, 180, 236)),
                      ((180, 176, 170), (240, 238, 232), (255, 255, 252)),
                      ((70, 30, 100), (130, 70, 160), (190, 130, 210))),
    )

    B["hortensia"] = _sp(
        key="hortensia", nom="Hortensia", h_range=(0.8, 1.6),
        multistem=(8, 16), stem_lean=(8.0, 25.0), stem_len=(0.7, 1.0), bole=(0.05, 0.12),
        trunk_k=0.014, crown_r=0.55, crown_shape="dome", max_order=2, bark_rough=0.2,
        density=(4, 5, 0, 0, 0), angle=(0, 48, 44, 40, 40), len_ratio=(0, 1.0, 0.5, 0.5, 0.5),
        wobble=(0.12, 0.22, 0.25, 0.3, 0.3), tropism=(0.05, 0.02, 0.0, 0.0, 0.0), min_dz=-0.15,
        crowd=(99, 99, 40, 36, 30), spring_leaf=0.55,
        leaf_min_order=1, leaf_start=0.15, leaf_r=(0, 0.17, 0.15, 0.13, 0.12), leaf_dens=0.6,
        leaf_spacing=0.9, leaf_stretch=1.1, leaf_flat=0.7, leaf_droop=0.05, leaf_big=0.60,
        bark=((70, 56, 44), (116, 98, 76), (160, 142, 112)),
        twig=((84, 70, 48), (128, 112, 72), (168, 150, 100)),
        leaves=(((18, 62, 26), (48, 118, 44), (110, 170, 72)),
                ((24, 70, 28), (62, 130, 48), (126, 180, 78)),
                ((14, 52, 24), (38, 98, 38), (92, 148, 62))),
        autumn=(((70, 60, 14), (140, 120, 30), (190, 170, 70)),
                ((84, 50, 16), (150, 100, 34), (196, 150, 70)),
                ((50, 56, 20), (104, 110, 40), (154, 160, 74))),
        flower_seasons=("summer", "autumn"), flower_frac=0.30, flower_r=0.11, flower_off=0.08, flower_fill=1.8,
        flower_ramps=(((40, 60, 150), (90, 120, 220), (170, 190, 250)),
                      ((170, 60, 110), (230, 120, 170), (250, 190, 215)),
                      ((190, 190, 180), (236, 238, 230), (255, 255, 250))),
    )

    B["forsythia"] = _sp(
        key="forsythia", nom="Forsythia", h_range=(1.2, 2.0),
        multistem=(10, 18), stem_lean=(10.0, 26.0), stem_len=(1.2, 1.5), bole=(0.0, 0.08),
        trunk_k=0.012, taper=0.07, crown_r=0.50, crown_shape="dome", max_order=3, bark_rough=0.2,
        density=(5, 6, 7, 0, 0), angle=(0, 40, 38, 36, 36), len_ratio=(0, 1.0, 0.50, 0.50, 0.50),
        wobble=(0.10, 0.20, 0.25, 0.30, 0.30), tropism=(-0.28, -0.05, 0.0, 0.0, 0.0), min_dz=-0.50,
        crowd=(99, 99, 30, 26, 22), spring_leaf=0.05,
        leaf_min_order=2, leaf_start=0.10, leaf_r=(0, 0, 0.10, 0.09, 0.08), leaf_dens=0.36,
        leaf_spacing=1.0, leaf_stretch=1.4, leaf_flat=0.8, leaf_droop=0.05, leaf_big=0.10,
        bark=((70, 56, 36), (118, 98, 62), (160, 138, 92)),
        twig=((84, 66, 36), (130, 106, 58), (172, 146, 90)),
        leaves=(((22, 60, 22), (60, 112, 36), (126, 164, 60)),
                ((28, 68, 24), (74, 126, 38), (142, 178, 64)),
                ((16, 50, 22), (46, 92, 32), (104, 140, 54))),
        autumn=(((90, 80, 14), (160, 140, 30), (206, 190, 70)),
                ((100, 60, 14), (170, 110, 30), (210, 150, 64)),
                ((60, 64, 20), (120, 120, 40), (170, 170, 74))),
        flower_seasons=("spring",), flower_frac=0.95, flower_r=0.055, flower_fill=1.8,
        flower_ramps=(((150, 110, 10), (240, 200, 20), (255, 240, 100)),),
    )

    B["houx"] = _sp(
        key="houx", nom="Houx", h_range=(1.2, 2.0),
        multistem=(2, 4), stem_lean=(2.0, 9.0), stem_len=(0.9, 1.0), bole=(0.0, 0.04),
        trunk_k=0.020, crown_r=0.32, crown_shape="dome", max_order=3, bark_rough=0.2,
        density=(6, 7, 8, 0, 0), angle=(0, 52, 48, 44, 40), len_ratio=(0, 1.0, 0.55, 0.50, 0.50),
        wobble=(0.08, 0.20, 0.25, 0.30, 0.30), tropism=(0.10, 0.05, 0.0, 0.0, 0.0), min_dz=-0.15,
        crowd=(99, 99, 34, 30, 26),
        leaf_min_order=2, leaf_start=0.15, leaf_r=(0, 0, 0.12, 0.10, 0.09), leaf_dens=0.55,
        leaf_spacing=0.8, leaf_stretch=1.1, leaf_flat=0.85, leaf_droop=0.0, leaf_big=0.10, evergreen=True,
        bark=((60, 56, 50), (110, 106, 96), (156, 152, 140)),
        twig=((56, 56, 40), (100, 100, 66), (140, 140, 92)),
        leaves=(((6, 34, 18), (20, 78, 36), (70, 130, 70)),
                ((10, 40, 20), (26, 92, 40), (90, 146, 76)),
                ((4, 28, 16), (14, 64, 30), (56, 108, 54))),
        fruit_seasons=("autumn", "winter"), fruit_frac=0.9, fruit_r=0.04, fruit_off=0.10, fruit_fill=2.5, fruit_tip=0.3,
        fruit_ramps=(((100, 10, 10), (200, 24, 24), (250, 90, 70)),),
    )

    B["genevrier"] = _sp(
        key="genevrier", nom="Genévrier", h_range=(1.0, 2.0),
        multistem=(3, 6), stem_lean=(1.0, 6.0), stem_len=(0.95, 1.0), bole=(0.0, 0.03),
        trunk_k=0.014, crown_r=0.17, crown_shape="colonne", max_order=3, bark_rough=0.3,
        density=(8, 9, 10, 0, 0), angle=(0, 32, 34, 34, 34), len_ratio=(0, 1.0, 0.50, 0.50, 0.50),
        wobble=(0.08, 0.18, 0.22, 0.25, 0.25), tropism=(0.20, 0.15, 0.05, 0.0, 0.0),
        up_bias=(0, 0.45, 0.30, 0.20, 0.10), min_dz=0.0, crowd=(99, 99, 34, 30, 26),
        leaf_min_order=1, leaf_start=0.10, leaf_r=(0, 0.11, 0.09, 0.08, 0.07), leaf_dens=0.9,
        leaf_spacing=0.8, leaf_stretch=1.6, leaf_flat=1.0, leaf_droop=0.0, leaf_big=0.0, evergreen=True,
        bark=((70, 50, 40), (120, 90, 72), (164, 130, 106)),
        twig=((60, 56, 44), (104, 100, 78), (146, 140, 110)),
        leaves=(((20, 50, 50), (60, 106, 100), (130, 170, 160)),
                ((26, 58, 50), (74, 120, 102), (146, 184, 164)),
                ((14, 42, 44), (46, 90, 88), (110, 152, 146))),
        fruit_seasons=("autumn", "winter"), fruit_frac=0.25, fruit_r=0.025, fruit_off=0.06, fruit_tip=0.3,
        fruit_ramps=(((30, 34, 70), (70, 80, 140), (130, 140, 190)),),
    )

    B["ronce"] = _sp(
        key="ronce", nom="Ronce", h_range=(0.8, 2.0),
        multistem=(4, 8), stem_lean=(16.0, 40.0), stem_len=(1.0, 1.4), bole=(0.0, 0.08),
        trunk_k=0.010, taper=0.04, crown_r=0.45, crown_shape="dome", max_order=3, bark_rough=0.2,
        density=(4, 5, 5, 0, 0), angle=(0, 55, 50, 45, 40), len_ratio=(0, 1.0, 0.50, 0.50, 0.50),
        wobble=(0.12, 0.25, 0.30, 0.35, 0.35), tropism=(-0.40, -0.10, 0.0, 0.0, 0.0), min_dz=-0.70,
        crowd=(99, 99, 20, 18, 16), spring_leaf=0.6,
        leaf_min_order=2, leaf_start=0.15, leaf_r=(0, 0, 0.10, 0.09, 0.08), leaf_dens=0.32,
        leaf_spacing=1.0, leaf_stretch=1.2, leaf_flat=0.8, leaf_droop=0.05, leaf_big=0.50,
        bark=((70, 30, 30), (112, 56, 50), (150, 86, 76)),
        twig=((80, 36, 34), (124, 62, 54), (160, 92, 80)),
        leaves=(((18, 52, 22), (44, 100, 38), (104, 152, 66)),
                ((24, 60, 24), (58, 114, 42), (120, 166, 72)),
                ((16, 44, 22), (36, 84, 32), (88, 130, 56))),
        autumn=(((90, 30, 14), (170, 70, 30), (214, 120, 56)),
                ((70, 44, 14), (140, 90, 30), (190, 140, 60)),
                ((60, 56, 20), (120, 110, 40), (170, 160, 76))),
        flower_seasons=("spring", "summer"), flower_frac=0.45, flower_r=0.045, flower_off=0.05, flower_tip=0.4,
        flower_ramps=(((200, 170, 180), (246, 230, 236), (255, 255, 255)),
                      ((190, 110, 140), (240, 180, 200), (255, 226, 236))),
        fruit_seasons=("summer", "autumn"), fruit_frac=0.55, fruit_r=0.035, fruit_off=0.05, fruit_tip=0.4, fruit_mix=True,
        fruit_ramps=(((110, 10, 20), (190, 30, 40), (235, 90, 80)),
                     ((14, 6, 24), (40, 16, 60), (90, 50, 110))),
    )
    return B


BUSHES: Dict[str, Species] = _build_bushes()


def generate_bush(seed=0, species: str = "auto", height=None, season: str = "summer",
                  leaf_density: float = 1.0, bake_light: bool = True, topiary=None,
                  verbose: bool = False, voxel: float = vt.VOXEL) -> vt.VoxelTree:
    """Génère un arbuste voxel de 5 cm (0,3 à 2 m). Mêmes arguments → même arbuste."""
    return vt.generate_tree(seed, species, height, season, leaf_density, bake_light, verbose,
                            table=BUSHES, grower_cls=BushGrower,
                            hmin=MIN_BUSH_HEIGHT, hmax=MAX_BUSH_HEIGHT, topiary=topiary, voxel=voxel)


# --------------------------------------------------------------------------------------
# Ligne de commande
# --------------------------------------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser(description="Générateur d'arbustes en voxels de 5 cm (2 m maximum).")
    ap.add_argument("--seed", default="0", help="graine : entier ou texte libre")
    ap.add_argument("--species", default="auto", help="auto | " + " | ".join(BUSHES))
    ap.add_argument("--height", type=float, default=None,
                    help=f"hauteur en m ({MIN_BUSH_HEIGHT:g}–{MAX_BUSH_HEIGHT:g}) ; défaut : tirée selon l'essence")
    ap.add_argument("--season", default="summer", choices=["summer", "spring", "autumn", "winter"])
    ap.add_argument("--leaf-density", type=float, default=1.0, help="multiplicateur de densité du feuillage")
    ap.add_argument("--topiary", default=None, choices=["sphere", "dome", "cube", "cone"],
                    help="taille topiaire : feuillage lisse en coque (sans fleurs ni fruits)")
    ap.add_argument("--voxel", type=float, default=vt.VOXEL,
                    help="taille d'un voxel en m (défaut 0.05 = 5 cm ; 0.02–0.1 accepté)")
    ap.add_argument("--no-bake", action="store_true", help="ne pas cuire l'ombrage dans les couleurs")
    ap.add_argument("--out", default="arbuste", help="préfixe des fichiers de sortie")
    ap.add_argument("--formats", default="npz,vox", help="liste parmi npz,vox,obj,vxm")
    ap.add_argument("--lods", default="0", help="LOD du .vxm : liste croissante de 0 à 5 (voxel = --voxel × 2^lod)")
    ap.add_argument("--export-pal", action="store_true", help=".vxm : ajoute le canal pal (palette Python)")
    ap.add_argument("--export-sky", action="store_true", help=".vxm : ajoute le canal sky (part de ciel vue)")
    ap.add_argument("--no-compress", action="store_true", help=".vxm : corps non compressés")
    ap.add_argument("--orientation-test", action="store_true",
                    help="écrit <out>.vxm : un voxel rouge à l'est et un bleu au nord du pivot, puis s'arrête")
    ap.add_argument("--preview", nargs="?", const="auto", default=None, help="écrit un aperçu PNG")
    ap.add_argument("--batch", type=int, default=1, help="génère N arbustes (graines seed, seed+1, …)")
    ap.add_argument("--list", action="store_true", help="liste les essences")
    a = ap.parse_args(argv)

    if a.list:
        for k, s in BUSHES.items():
            print(f"{k:10s} {s.nom:11s} {s.h_range[0]:.1f}–{s.h_range[1]:.1f} m")
        return 0
    if a.height is not None and not (MIN_BUSH_HEIGHT <= a.height <= MAX_BUSH_HEIGHT):
        print(f"Attention : hauteur ramenée dans [{MIN_BUSH_HEIGHT:g} ; {MAX_BUSH_HEIGHT:g}] m.")

    if not (0.01 <= a.voxel <= 0.1):
        ap.error("--voxel doit être compris entre 0.01 et 0.1 m")
    fmts = [f.strip() for f in a.formats.split(",") if f.strip()]
    bad = [f for f in fmts if f not in ("npz", "vox", "obj", "vxm")]
    if bad:
        ap.error(f"format inconnu : {', '.join(bad)}")
    try:
        lods = vt.parse_lods(a.lods)
    except ValueError as e:
        ap.error(str(e))
    if a.orientation_test:
        return vt.write_orientation(a.out, not a.no_compress, a.export_sky, a.export_pal)
    if "vxm" in fmts and not a.no_bake:
        print("  .vxm : ombrage cuit désactivé (le moteur éclaire lui-même, docs/19a § 1)")
    bake = not a.no_bake and "vxm" not in fmts
    for i in range(a.batch):
        seed = a.seed if a.batch == 1 else str(vt.seed_to_int(a.seed) + i)
        t0 = time.time()
        tree = generate_bush(seed, a.species, a.height, a.season, a.leaf_density, bake,
                             a.topiary, verbose=False, voxel=a.voxel)
        sx, sy, sz = tree.size
        base = a.out if a.batch == 1 else f"{a.out}_{seed}"
        d = os.path.dirname(base)
        if d:
            os.makedirs(d, exist_ok=True)
        print(f"{tree.meta['nom']} (graine {seed}) : {tree.height_m:.2f} m, {len(tree.coords):,} voxels, "
              f"emprise {sx * a.voxel:.2f} × {sy * a.voxel:.2f} m, {time.time() - t0:.1f} s")
        if "npz" in fmts:
            vt.save_npz(tree, base + ".npz"); print("  →", base + ".npz")
        if "vox" in fmts:
            vt.save_vox(tree, base + ".vox"); print("  →", base + ".vox")
        if "obj" in fmts:
            nf = vt.save_obj(tree, base + ".obj"); print(f"  → {base}.obj ({nf:,} faces)")
        if "vxm" in fmts:
            by_lod = vt.build_lods(tree, lambda v: generate_bush(seed, a.species, a.height, a.season, a.leaf_density,
                                                                 False, a.topiary, voxel=v), lods)
            n = vt.save_vxm(by_lod, base + ".vxm", a.export_sky, a.export_pal, generator="voxel_bush.py",
                            compress=not a.no_compress)
            print(f"  → {base}.vxm ({n:,} octets, LOD {','.join(map(str, by_lod))})")
        if a.preview is not None:
            pth = base + ".png" if a.preview == "auto" else a.preview
            vt.render_preview(tree, pth, views=((25.0, 25.0), (115.0, 25.0)), target_px=640,
                              ruler_step=0.1, ruler_every=5)
            print("  →", pth)
    return 0


if __name__ == "__main__":
    sys.exit(main())
