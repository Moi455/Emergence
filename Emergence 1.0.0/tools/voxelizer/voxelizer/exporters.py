"""Exporteurs. Dans les deux formats, CHAQUE voxel reste une entité distincte et identifiable."""
import gzip
import json
import struct
from abc import ABC, abstractmethod
from pathlib import Path

import numpy as np

from .model import Voxel, VoxelKind, VoxelModel
from .scene import srgb_to_linear

FORMAT_ID = "voxel-entities"


class Exporter(ABC):
    @abstractmethod
    def write(self, model: VoxelModel, path) -> Path: ...


class JsonExporter(Exporter):
    """Format « moteur » : une ligne par entité [id, ix, iy, iz, couleur(palette), kind, faces].
    Extension .gz => compressé. Se relit avec JsonImporter en objets Voxel."""

    def write(self, model: VoxelModel, path) -> Path:
        path = Path(path)
        lo, hi = model.cell_bounds()
        doc = {
            "format": FORMAT_ID, "version": 1, "name": model.name,
            "voxel_size_m": model.voxel_size, "up_axis": model.up_axis,
            "lattice": "la cellule (i,j,k) occupe [i,i+1)x[j,j+1)x[k,k+1) fois voxel_size_m dans l'espace du modèle",
            "bounds_cells": {"min": lo.tolist(), "max": hi.tolist()},
            "palette_rgba": [list(c) for c in model.palette],
            "kinds": {"0": "surface", "1": "interior"},
            "faces_bits": ["+X", "-X", "+Y", "-Y", "+Z", "-Z"],
            "fields": ["id", "ix", "iy", "iz", "color", "kind", "faces", "material"], "materials": model.materials,
            "info": model.info,
        }
        a = model.to_arrays()
        rows = np.column_stack([a["id"], a["cell"], a["color"], a["kind"], a["faces"], a["material"]]).tolist()
        head = json.dumps(doc, separators=(",", ":"), default=str)
        body = json.dumps(rows, separators=(",", ":"))
        text = head[:-1] + ',"voxels":' + body + "}"
        (gzip.open(path, "wt", encoding="utf-8") if path.suffix == ".gz" else open(path, "w", encoding="utf-8")).write(text)
        return path


class JsonImporter:
    @staticmethod
    def read(path) -> VoxelModel:
        path = Path(path)
        opener = gzip.open if path.suffix == ".gz" else open
        with opener(path, "rt", encoding="utf-8") as f:
            doc = json.load(f)
        if doc.get("format") != FORMAT_ID:
            raise ValueError("Ce fichier n'est pas au format voxel-entities.")
        m = VoxelModel(doc["voxel_size_m"], [tuple(c) for c in doc["palette_rgba"]], doc.get("name", ""),
                       doc.get("up_axis", "Y"))
        m.info = doc.get("info", {})
        from .lattice import pack
        m.materials = doc.get("materials", [])
        for row in doc["voxels"]:
            vid, ix, iy, iz, ci, kind, faces = row[:7]
            m._cells[int(pack(ix, iy, iz))] = Voxel(vid, ix, iy, iz, m.palette[ci], VoxelKind(kind), faces, m,
                                                     row[7] if len(row) > 7 else 0)
        m._next_id = max((v.id for v in m), default=-1) + 1
        return m


class GlbExporter(Exporter):
    """glTF binaire : un NŒUD par voxel (nom `voxel_<id>`, extras = cellule + nature), tous reliés à un
    nœud racine. Le cube (2 cm) est un seul maillage partagé par couleur de palette : ce sont des
    instances, donc des entités distinctes, pas un gros mesh fusionné."""

    def __init__(self, include_interior: bool = True, max_materials: int = 1024):
        self.include_interior = include_interior
        self.max_materials = max_materials

    def write(self, model: VoxelModel, path) -> Path:
        path = Path(path)
        if len(model.palette) > self.max_materials:
            raise ValueError(f"Palette de {len(model.palette)} couleurs > {self.max_materials} : "
                             f"quantifiez (palette_size) avant l'export glTF.")
        h = model.voxel_size / 2
        # cube de 24 sommets (normales plates), 36 indices
        pos, nrm, idx = [], [], []
        for n, (ax, sgn) in enumerate([(0, 1), (0, -1), (1, 1), (1, -1), (2, 1), (2, -1)]):
            u, v = [a for a in range(3) if a != ax]
            for su, sv in [(-1, -1), (1, -1), (1, 1), (-1, 1)]:
                p = [0.0] * 3
                p[ax], p[u], p[v] = sgn * h, su * h, sv * h
                pos.append(p); nrm.append([sgn if a == ax else 0 for a in range(3)])
            b = 4 * n
            idx += [b, b + 1, b + 2, b, b + 2, b + 3] if sgn > 0 else [b, b + 2, b + 1, b, b + 3, b + 2]
        pos, nrm = np.array(pos, np.float32), np.array(nrm, np.float32)
        idx = np.array(idx, np.uint16)

        blob = bytearray()
        views, accs = [], []

        def add(data: np.ndarray, target: int, **acc):
            while len(blob) % 4:
                blob.append(0)
            views.append({"buffer": 0, "byteOffset": len(blob), "byteLength": data.nbytes, "target": target})
            blob.extend(data.tobytes())
            accs.append({"bufferView": len(views) - 1, "byteOffset": 0, **acc})
            return len(accs) - 1

        a_idx = add(idx, 34963, componentType=5123, count=len(idx), type="SCALAR")
        a_pos = add(pos, 34962, componentType=5126, count=len(pos), type="VEC3",
                    min=pos.min(0).tolist(), max=pos.max(0).tolist())
        a_nrm = add(nrm, 34962, componentType=5126, count=len(nrm), type="VEC3")

        materials, meshes = [], []
        for ci, (r, g, b, a) in enumerate(model.palette):
            lin = srgb_to_linear(np.array([r, g, b]) / 255.0).tolist()
            m = {"name": f"c{ci}", "pbrMetallicRoughness": {"baseColorFactor": [*lin, a / 255.0],
                                                               "metallicFactor": 0.0, "roughnessFactor": 1.0}}
            if a < 255:
                m["alphaMode"] = "BLEND"
            materials.append(m)
            meshes.append({"name": f"voxel_c{ci}", "primitives": [
                {"attributes": {"POSITION": a_pos, "NORMAL": a_nrm}, "indices": a_idx, "material": ci}]})

        s = model.voxel_size
        pal_index = {c: i for i, c in enumerate(model.palette)}
        nodes = [{"name": model.name or "VoxelModel", "children": []}]
        for v in model:
            if v.kind is VoxelKind.INTERIOR and not self.include_interior:
                continue
            nodes.append({"name": f"voxel_{v.id}", "mesh": pal_index[v.color],
                          "translation": [round((v.ix + .5) * s, 6), round((v.iy + .5) * s, 6), round((v.iz + .5) * s, 6)],
                          "extras": {"id": v.id, "cell": [v.ix, v.iy, v.iz], "kind": v.kind.name.lower()}})
        nodes[0]["children"] = list(range(1, len(nodes)))

        gltf = {"asset": {"version": "2.0", "generator": "voxelizer"}, "scene": 0, "scenes": [{"nodes": [0]}],
                "nodes": nodes, "meshes": meshes, "materials": materials, "accessors": accs, "bufferViews": views,
                "buffers": [{"byteLength": len(blob)}]}
        js = json.dumps(gltf, separators=(",", ":")).encode()
        js += b" " * (-len(js) % 4)
        blob.extend(b"\0" * (-len(blob) % 4))
        total = 12 + 8 + len(js) + 8 + len(blob)
        with open(path, "wb") as f:
            f.write(struct.pack("<4sII", b"glTF", 2, total))
            f.write(struct.pack("<II", len(js), 0x4E4F534A)); f.write(js)
            f.write(struct.pack("<II", len(blob), 0x004E4942)); f.write(bytes(blob))
        return path
