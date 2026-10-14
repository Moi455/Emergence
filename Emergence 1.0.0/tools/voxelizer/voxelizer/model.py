"""Le résultat de la voxélisation : une collection d'ENTITÉS `Voxel`, pas une grille de pixels.

Chaque voxel est un objet à part entière (identité stable, position monde, couleur, nature
surface/intérieur, faces exposées, voisins, destruction). C'est ce que le moteur de jeu
instancie : un voxel = une entité adressable, que l'on peut retirer, colorer ou interroger
individuellement.
"""
from enum import IntEnum
from typing import Dict, Iterator, List, Optional, Tuple

import numpy as np

from .lattice import FACES, FACE_NAMES, exposed_masks, face_delta, pack, unpack
from .solid import FilledVoxels


class VoxelKind(IntEnum):
    SURFACE = 0
    INTERIOR = 1


class Voxel:
    """Entité voxel. Cellule (ix, iy, iz) du réseau ; cube de `model.voxel_size` mètres de côté."""
    __slots__ = ("id", "ix", "iy", "iz", "color", "kind", "faces", "model", "material")

    def __init__(self, id: int, ix: int, iy: int, iz: int, color: Tuple[int, int, int, int],
                 kind: VoxelKind, faces: int, model: "VoxelModel", material: int = 0):
        self.id, self.ix, self.iy, self.iz = id, ix, iy, iz
        self.color = color              # RGBA 0-255 (n-uplet partagé avec la palette)
        self.kind = kind
        self.faces = faces              # masque de bits : face i exposée (voisin absent) -> bit i
        self.model = model
        self.material = material        # indice dans model.materials (nom du matériau d'origine)

    # -- géométrie
    @property
    def cell(self) -> Tuple[int, int, int]:
        return self.ix, self.iy, self.iz

    @property
    def position(self) -> Tuple[float, float, float]:
        """Centre du voxel, en mètres, dans l'espace du modèle."""
        s = self.model.voxel_size
        return (self.ix + 0.5) * s, (self.iy + 0.5) * s, (self.iz + 0.5) * s

    @property
    def aabb(self) -> Tuple[Tuple[float, float, float], Tuple[float, float, float]]:
        s = self.model.voxel_size
        return (self.ix * s, self.iy * s, self.iz * s), ((self.ix + 1) * s, (self.iy + 1) * s, (self.iz + 1) * s)

    # -- état
    @property
    def is_visible(self) -> bool:
        return self.faces != 0

    @property
    def exposed_faces(self) -> List[str]:
        return [FACE_NAMES[f] for f in range(6) if self.faces >> f & 1]

    # -- voisinage / comportement
    def neighbor(self, face: int) -> Optional["Voxel"]:
        dx, dy, dz = FACES[face]
        return self.model.get(self.ix + dx, self.iy + dy, self.iz + dz)

    def neighbors(self) -> List["Voxel"]:
        return [n for f in range(6) if (n := self.neighbor(f)) is not None]

    def destroy(self) -> None:
        self.model.remove(self)

    def to_dict(self) -> dict:
        return {"id": self.id, "cell": self.cell, "position": self.position, "color": self.color,
                "kind": self.kind.name.lower(), "exposed_faces": self.exposed_faces}

    def __repr__(self) -> str:
        return f"Voxel(id={self.id}, cell={self.cell}, color={self.color}, {self.kind.name.lower()})"


class VoxelModel:
    """Ensemble d'entités voxel sur un réseau de `voxel_size` mètres (2 cm par défaut)."""

    def __init__(self, voxel_size: float, palette: List[Tuple[int, int, int, int]], name: str = "",
                 up_axis: str = "Y"):
        self.voxel_size = voxel_size
        self.palette = [tuple(int(c) for c in p) for p in palette]
        self.name = name
        self.up_axis = up_axis
        self.info: Dict[str, object] = {}
        self.materials: List[str] = []
        self._cells: Dict[int, Voxel] = {}
        self._next_id = 0

    # -- construction
    @classmethod
    def from_filled(cls, f: FilledVoxels, palette: np.ndarray, color_idx: np.ndarray, voxel_size: float,
                    name: str = "") -> "VoxelModel":
        m = cls(voxel_size, [tuple(p) for p in palette], name)
        ix, iy, iz = (a.tolist() for a in unpack(f.keys))
        faces = exposed_masks(f.keys).tolist()
        pal, kinds, idx = m.palette, f.kind.tolist(), color_idx.tolist()
        mats = f.material.tolist() if f.material is not None else [0] * len(f.keys)
        keys = f.keys.tolist()
        for n, key in enumerate(keys):
            m._cells[key] = Voxel(n, ix[n], iy[n], iz[n], pal[idx[n]], VoxelKind(kinds[n]), faces[n], m, mats[n])
        m._next_id = len(keys)
        return m

    # -- accès
    def get(self, ix: int, iy: int, iz: int) -> Optional[Voxel]:
        return self._cells.get(int(pack(ix, iy, iz)))

    def at_position(self, x: float, y: float, z: float) -> Optional[Voxel]:
        s = self.voxel_size
        return self.get(int(np.floor(x / s)), int(np.floor(y / s)), int(np.floor(z / s)))

    def __len__(self) -> int:
        return len(self._cells)

    def __iter__(self) -> Iterator[Voxel]:
        return iter(self._cells.values())

    def __contains__(self, cell) -> bool:
        return self.get(*cell) is not None

    def surface(self) -> Iterator[Voxel]:
        return (v for v in self if v.is_visible)

    # -- modification (comportement d'entité)
    def add(self, ix: int, iy: int, iz: int, color: Tuple[int, int, int, int],
            kind: VoxelKind = VoxelKind.SURFACE, material: int = 0) -> Voxel:
        key = int(pack(ix, iy, iz))
        if key in self._cells:
            raise ValueError(f"Cellule {(ix, iy, iz)} déjà occupée.")
        color = tuple(int(c) for c in color)
        if color not in self.palette:                    # garde l'export (palette -> matériaux glTF) cohérent
            self.palette.append(color)
        faces = 0
        v = Voxel(self._next_id, ix, iy, iz, color, kind, 0, self, material)
        self._next_id += 1
        self._cells[key] = v
        for f in range(6):                               # met à jour les deux côtés de chaque contact
            n = v.neighbor(f)
            if n is None:
                faces |= 1 << f
            else:
                n.faces &= ~(1 << (f ^ 1))
        v.faces = faces
        return v

    def remove(self, v: Voxel) -> None:
        """Retire le voxel ; ses voisins exposent la face qui le touchait (et deviennent surface)."""
        if self._cells.pop(int(pack(v.ix, v.iy, v.iz)), None) is None:
            return
        for f in range(6):
            n = v.neighbor(f)
            if n is not None:
                n.faces |= 1 << (f ^ 1)                  # f ^ 1 : face opposée (+X<->-X, ...)
                if n.kind is VoxelKind.INTERIOR:
                    n.kind = VoxelKind.SURFACE

    # -- mesures
    def cell_bounds(self) -> Tuple[np.ndarray, np.ndarray]:
        a = np.array([v.cell for v in self])
        return a.min(0), a.max(0)

    def size_m(self) -> np.ndarray:
        lo, hi = self.cell_bounds()
        return (hi - lo + 1) * self.voxel_size

    def volume_m3(self) -> float:
        return len(self) * self.voxel_size ** 3

    def count_by_kind(self) -> Dict[str, int]:
        c = {"surface": 0, "interior": 0}
        for v in self:
            c[v.kind.name.lower()] += 1
        return c

    def to_arrays(self) -> Dict[str, np.ndarray]:
        """Vue structurée (cells, couleur (palette idx), kind, faces) pour les exporteurs/rendus."""
        vs = list(self)
        pal_index = {c: i for i, c in enumerate(self.palette)}
        return {"id": np.array([v.id for v in vs], np.int64),
                "cell": np.array([v.cell for v in vs], np.int64).reshape(-1, 3),
                "color": np.array([pal_index.get(v.color, 0) for v in vs], np.int64),
                "kind": np.array([int(v.kind) for v in vs], np.uint8),
                "faces": np.array([v.faces for v in vs], np.uint8),
                "material": np.array([v.material for v in vs], np.int64)}

    def summary(self) -> str:
        k = self.count_by_kind()
        lo, hi = self.cell_bounds()
        return (f"{len(self):,} voxels de {self.voxel_size * 100:g} cm "
                f"({k['surface']:,} surface, {k['interior']:,} intérieur), "
                f"{len(self.palette)} couleurs, boîte {tuple(int(x) for x in hi - lo + 1)} cellules "
                f"= {tuple(round(float(x), 3) for x in self.size_m())} m, volume {self.volume_m3():.4f} m³")
