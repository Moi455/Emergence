"""Réseau cubique de voxels aligné sur le monde, et clés entières compactes.

Convention : la cellule (i, j, k) occupe [i, i+1) x [j, j+1) x [k, k+1) fois `voxel_size`
dans l'espace du modèle (repère Y-haut, comme glTF). Le centre du voxel est donc
((i+.5)*vs, (j+.5)*vs, (k+.5)*vs). Deux modèles voxélisés dans le même repère monde
s'emboîtent donc exactement sur la grille de 2 cm.
"""
import numpy as np

VOXEL_SIZE_M = 0.02          # 2 cm, valeur imposée par le cahier des charges
_OFF = 1 << 20               # décalage pour des indices négatifs (+-1 048 576 cellules = +-20 km)
_MASK = (1 << 21) - 1

# 6 faces d'un voxel : +X, -X, +Y, -Y, +Z, -Z
FACES = ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1))
FACE_NAMES = ("+X", "-X", "+Y", "-Y", "+Z", "-Z")


def pack(ix, iy, iz):
    """(ix, iy, iz) -> clé int64 unique, triable (tableaux numpy ou scalaires)."""
    ix, iy, iz = (np.asarray(a, dtype=np.int64) for a in (ix, iy, iz))
    return ((ix + _OFF) << 42) | ((iy + _OFF) << 21) | (iz + _OFF)


def unpack(keys):
    keys = np.asarray(keys, dtype=np.int64)
    return (keys >> 42) - _OFF, ((keys >> 21) & _MASK) - _OFF, (keys & _MASK) - _OFF


def face_delta(face: int) -> int:
    """Décalage à ajouter à une clé pour obtenir la clé du voisin par `face`."""
    dx, dy, dz = FACES[face]
    return (dx << 42) + (dy << 21) + dz


def exposed_masks(keys: np.ndarray) -> np.ndarray:
    """keys triées -> masque 6 bits des faces SANS voisin (bit i = face FACES[i] exposée), vectorisé."""
    mask = np.zeros(len(keys), np.uint8)
    for face in range(6):
        nk = keys + face_delta(face)
        pos = np.minimum(np.searchsorted(keys, nk), len(keys) - 1)
        mask |= (keys[pos] != nk).astype(np.uint8) << face
    return mask
