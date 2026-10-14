"""Occlusion ambiante (AO) de voxels : la méthode classique « 3 voisins par coin de face ».

Pour chaque coin d'une face exposée, on regarde les 2 voisins latéraux et le voisin diagonal situés
juste devant la face : niveau 0 (coin très enfermé) à 3 (dégagé). Utilisé par le rendu (interpolé
dans la face) et, en option, « cuit » dans la couleur des voxels (`bake_ao`).
"""
from typing import Dict

import numpy as np

TANGENTS = {0: (1, 2), 1: (0, 2), 2: (0, 1)}               # axes tangents d'une face d'axe a
AO_BRIGHT = np.array([0.40, 0.60, 0.80, 1.00], np.float32)  # luminosité par niveau d'occlusion


def _delta(d) -> int:
    return (int(d[0]) << 42) + (int(d[1]) << 21) + int(d[2])


def occupied(skeys: np.ndarray, k: np.ndarray) -> np.ndarray:
    pos = np.minimum(np.searchsorted(skeys, k), len(skeys) - 1)
    return skeys[pos] == k


def corner_levels(skeys: np.ndarray, keys: np.ndarray, face: int) -> np.ndarray:
    """(n,4) niveaux 0..3 pour les coins (du,dv) = (0,0), (1,0), (0,1), (1,1) de la face `face`
    des voxels `keys` (skeys : toutes les clés triées)."""
    a, sgn = face // 2, (1 if face % 2 == 0 else -1)
    b, c = TANGENTS[a]
    n = np.zeros(3, int); n[a] = sgn
    out = np.empty((len(keys), 4), np.uint8)
    for corner in range(4):
        sb = np.zeros(3, int); sb[b] = 1 if corner & 1 else -1
        sc = np.zeros(3, int); sc[c] = 1 if corner >> 1 else -1
        s1 = occupied(skeys, keys + _delta(n + sb))
        s2 = occupied(skeys, keys + _delta(n + sc))
        co = occupied(skeys, keys + _delta(n + sb + sc))
        out[:, corner] = np.where(s1 & s2, 0, 3 - (s1.astype(int) + s2 + co))
    return out


def voxel_ao(skeys: np.ndarray, masks: np.ndarray) -> np.ndarray:
    """Luminosité d'AO moyenne par voxel (1 = dégagé), moyenne sur ses faces exposées."""
    total = np.zeros(len(skeys), np.float32)
    count = np.zeros(len(skeys), np.float32)
    for f in range(6):
        idx = np.nonzero((masks >> f) & 1)[0]
        if len(idx):
            total[idx] += AO_BRIGHT[corner_levels(skeys, skeys[idx], f)].mean(axis=1)
            count[idx] += 1
    return np.where(count > 0, total / np.maximum(count, 1), 1.0)
