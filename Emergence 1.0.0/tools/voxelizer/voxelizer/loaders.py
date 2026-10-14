"""Chargeurs de modèles 3D -> Scene3D. Un chargeur par format, même interface."""
import base64
import io
import json
import struct
import warnings
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import unquote

import numpy as np
from PIL import Image

from .scene import Material, MeshPrimitive, Scene3D, Texture, srgb_to_linear, WRAP_REPEAT


class LfsPointerError(RuntimeError):
    """Le fichier est un pointeur Git LFS (~130 octets) et non le vrai contenu."""


def _check_lfs(head: bytes, name: str) -> None:
    if head[:40].startswith(b"version https://git-lfs"):
        raise LfsPointerError(
            f"« {name} » est un pointeur Git LFS, pas le vrai fichier. "
            f"Dans le dépôt, lancez `git lfs install && git lfs pull`."
        )


class SceneLoader(ABC):
    @abstractmethod
    def load(self, path) -> Scene3D: ...


# ----------------------------------------------------------------------------- glTF / GLB
_CT = {5120: np.int8, 5121: np.uint8, 5122: np.int16, 5123: np.uint16, 5125: np.uint32, 5126: np.float32}
_NC = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT2": 4, "MAT3": 9, "MAT4": 16}


class GltfLoader(SceneLoader):
    """glTF 2.0 (.gltf + .bin + images, ou .glb). Aplatit la hiérarchie de nœuds en monde."""

    def load(self, path) -> Scene3D:
        path = Path(path)
        raw = path.read_bytes()
        _check_lfs(raw, path.name)
        glb_bin = None
        if raw[:4] == b"glTF":
            self.doc, glb_bin = self._parse_glb(raw)
        else:
            self.doc = json.loads(raw.decode("utf-8"))
        self.dir = path.parent
        self._buffers = [self._read_buffer(b, glb_bin) for b in self.doc.get("buffers", [])]
        self._images: Dict[int, Optional[Image.Image]] = {}
        self._textures: Dict[tuple, Optional[Texture]] = {}
        self._materials: Dict[Optional[int], Material] = {}

        scene_idx = self.doc.get("scene", 0)
        roots = self.doc["scenes"][scene_idx]["nodes"] if self.doc.get("scenes") else \
            list(range(len(self.doc.get("nodes", []))))
        prims: List[MeshPrimitive] = []
        stack = [(r, np.eye(4)) for r in roots]
        while stack:
            ni, parent = stack.pop()
            node = self.doc["nodes"][ni]
            m = parent @ self._node_matrix(node)
            if "mesh" in node:
                mesh = self.doc["meshes"][node["mesh"]]
                for k, pr in enumerate(mesh["primitives"]):
                    p = self._primitive(pr, m, f'{node.get("name", ni)}/{mesh.get("name", "mesh")}.{k}')
                    if p is not None:
                        prims.append(p)
            stack.extend((c, m) for c in node.get("children", []))
        return Scene3D(prims, str(path))

    # -- conteneur
    @staticmethod
    def _parse_glb(raw: bytes):
        doc, binchunk, off = None, None, 12
        while off < len(raw):
            clen, ctype = struct.unpack_from("<II", raw, off)
            data = raw[off + 8: off + 8 + clen]
            off += 8 + clen
            if ctype == 0x4E4F534A:
                doc = json.loads(data.decode("utf-8"))
            elif ctype == 0x004E4942 and binchunk is None:
                binchunk = data
        return doc, binchunk

    def _read_uri(self, uri: str) -> bytes:
        if uri.startswith("data:"):
            return base64.b64decode(uri.split(",", 1)[1])
        f = self.dir / unquote(uri)
        data = f.read_bytes()
        _check_lfs(data, f.name)
        return data

    def _read_buffer(self, b: dict, glb_bin: Optional[bytes]) -> bytes:
        return glb_bin if "uri" not in b else self._read_uri(b["uri"])

    # -- accesseurs
    def _accessor(self, idx: int) -> np.ndarray:
        acc = self.doc["accessors"][idx]
        dt = np.dtype(_CT[acc["componentType"]]).newbyteorder("<")
        nc, count = _NC[acc["type"]], acc["count"]
        if "bufferView" not in acc:
            arr = np.zeros((count, nc), dt)
        else:
            bv = self.doc["bufferViews"][acc["bufferView"]]
            off = bv.get("byteOffset", 0) + acc.get("byteOffset", 0)
            stride = bv.get("byteStride") or dt.itemsize * nc
            arr = np.array(np.ndarray((count, nc), dt, buffer=self._buffers[bv["buffer"]],
                                      offset=off, strides=(stride, dt.itemsize)))
        if acc.get("normalized") and dt.kind in "iu":
            arr = np.maximum(arr.astype(np.float32) / np.iinfo(dt).max, -1.0)
        return arr

    # -- matériaux / textures
    def _image(self, src: int) -> Optional[Image.Image]:
        if src not in self._images:
            im = self.doc["images"][src]
            try:
                if "uri" in im:
                    data = self._read_uri(im["uri"])
                else:
                    bv = self.doc["bufferViews"][im["bufferView"]]
                    o = bv.get("byteOffset", 0)
                    data = self._buffers[bv["buffer"]][o:o + bv["byteLength"]]
                    _check_lfs(data, im.get("name", f"image{src}"))
                self._images[src] = Image.open(io.BytesIO(data))
                self._images[src].load()
            except FileNotFoundError:
                warnings.warn(f"Texture introuvable : {im.get('uri')} -> couleur unie utilisée.")
                self._images[src] = None
        return self._images[src]

    def _texture(self, ti: int) -> Optional[Texture]:
        t = self.doc["textures"][ti]
        sam = self.doc["samplers"][t["sampler"]] if "sampler" in t else {}
        ws, wt = sam.get("wrapS", WRAP_REPEAT), sam.get("wrapT", WRAP_REPEAT)
        key = (t.get("source"), ws, wt)
        if key not in self._textures:
            img = self._image(t["source"]) if "source" in t else None
            self._textures[key] = Texture(img, ws, wt) if img is not None else None
        return self._textures[key]

    def _material(self, i: Optional[int]) -> Material:
        if i in self._materials:
            return self._materials[i]
        if i is None:
            mat = Material()
        else:
            m = self.doc["materials"][i]
            pbr = m.get("pbrMetallicRoughness", {})
            mat = Material(m.get("name", f"mat{i}"), tuple(pbr.get("baseColorFactor", [1, 1, 1, 1])),
                           alpha_mode=m.get("alphaMode", "OPAQUE"), alpha_cutoff=m.get("alphaCutoff", 0.5),
                           double_sided=m.get("doubleSided", False))
            bct = pbr.get("baseColorTexture")
            if bct is not None:
                mat.texture, mat.tex_coord = self._texture(bct["index"]), bct.get("texCoord", 0)
        self._materials[i] = mat
        return mat

    # -- géométrie
    @staticmethod
    def _node_matrix(node: dict) -> np.ndarray:
        if "matrix" in node:
            return np.array(node["matrix"], dtype=np.float64).reshape(4, 4).T     # colonne-major
        x, y, z, w = node.get("rotation", [0, 0, 0, 1])
        r = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                      [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                      [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
        m = np.eye(4)
        m[:3, :3] = r * np.array(node.get("scale", [1, 1, 1]))
        m[:3, 3] = node.get("translation", [0, 0, 0])
        return m

    def _primitive(self, pr: dict, m: np.ndarray, name: str) -> Optional[MeshPrimitive]:
        mode = pr.get("mode", 4)
        if mode not in (4, 5, 6):
            warnings.warn(f"{name}: mode de primitive {mode} ignoré (seuls les triangles sont voxélisés).")
            return None
        at = pr["attributes"]
        pos = self._accessor(at["POSITION"]).astype(np.float64)
        pos = (np.c_[pos, np.ones(len(pos))] @ m.T)[:, :3]
        idx = self._accessor(pr["indices"]).reshape(-1).astype(np.int64) if "indices" in pr \
            else np.arange(len(pos))
        if mode == 5:       # strip
            i = np.arange(len(idx) - 2)
            tris = np.stack([idx[i], np.where(i % 2 == 0, idx[i + 1], idx[i + 2]),
                             np.where(i % 2 == 0, idx[i + 2], idx[i + 1])], axis=1)
        elif mode == 6:     # fan
            i = np.arange(1, len(idx) - 1)
            tris = np.stack([np.full_like(i, idx[0]), idx[i], idx[i + 1]], axis=1)
        else:
            tris = idx[: len(idx) // 3 * 3].reshape(-1, 3)
        mat = self._material(pr.get("material"))
        uv = None
        if f"TEXCOORD_{mat.tex_coord}" in at:
            uv = self._accessor(at[f"TEXCOORD_{mat.tex_coord}"]).astype(np.float64)
        col = None
        if "COLOR_0" in at:
            c = self._accessor(at["COLOR_0"]).astype(np.float64)
            col = c if c.shape[1] == 4 else np.c_[c, np.ones(len(c))]     # COLOR_0 est linéaire en glTF
        return MeshPrimitive(pos, tris, mat, uv, col, name)


# ----------------------------------------------------------------------------- OBJ / MTL
class ObjLoader(SceneLoader):
    def __init__(self, texture_dirs=()):
        self.texture_dirs = [Path(d) for d in texture_dirs]
        self.notes = []

    """Wavefront OBJ + MTL. Les chemins de texture du MTL (souvent absolus, Windows) sont
    résolus par nom de fichier dans les dossiers voisins (., Textures/, ../Textures/)."""

    def load(self, path) -> Scene3D:
        self.notes = []
        path = Path(path)
        text = path.read_text(errors="replace")
        _check_lfs(text[:60].encode(), path.name)
        verts, uvs = [], []
        groups: Dict[Optional[str], list] = {}
        mtl: Dict[str, Material] = {}
        cur: Optional[str] = None
        for line in text.splitlines():
            t = line.split()
            if not t:
                continue
            if t[0] == "v":
                verts.append([float(x) for x in t[1:4]])
            elif t[0] == "vt":
                uvs.append([float(t[1]), float(t[2]) if len(t) > 2 else 0.0])
            elif t[0] == "mtllib":
                mtl.update(self._read_mtl(path.parent / line.split(None, 1)[1].strip(), path.parent))
            elif t[0] == "usemtl":
                cur = line.split(None, 1)[1].strip()
            elif t[0] == "f":
                refs = []
                for c in t[1:]:
                    p = c.split("/")
                    vi = int(p[0]); vi = vi - 1 if vi > 0 else len(verts) + vi
                    ti = None
                    if len(p) > 1 and p[1]:
                        ti = int(p[1]); ti = ti - 1 if ti > 0 else len(uvs) + ti
                    refs.append((vi, ti))
                for a in range(1, len(refs) - 1):
                    groups.setdefault(cur, []).append((refs[0], refs[a], refs[a + 1]))
        v, vt = np.array(verts, dtype=np.float64), np.array(uvs, dtype=np.float64).reshape(-1, 2)
        prims = []
        for name, faces in groups.items():
            corners = [c for f in faces for c in f]
            pos = v[[c[0] for c in corners]]
            uv = np.array([[vt[c[1]][0], 1.0 - vt[c[1]][1]] if c[1] is not None else [0, 0] for c in corners])
            prims.append(MeshPrimitive(pos, np.arange(len(pos)).reshape(-1, 3), mtl.get(name, Material()), uv,
                                       None, name or "obj"))
        return Scene3D(prims, str(path), sorted(set(self.notes)))

    def _find_texture(self, ref: str, *dirs: Path) -> Optional[Path]:
        base = Path(ref.replace("\\", "/")).name
        for d in (*self.texture_dirs, *dirs):
            for cand in (d / base, d / "Textures" / base, d.parent / "Textures" / base):
                if cand.is_file():
                    return cand
        return None

    def _read_mtl(self, mtl_path: Path, obj_dir: Path) -> Dict[str, Material]:
        mats: Dict[str, Material] = {}
        if not mtl_path.is_file():
            warnings.warn(f"MTL introuvable : {mtl_path}")
            return mats
        cur = None
        info: Dict[str, dict] = {}
        for line in mtl_path.read_text(errors="replace").splitlines():
            t = line.split(None, 1)
            if not t:
                continue
            k, rest = t[0], (t[1].strip() if len(t) > 1 else "")
            if k == "newmtl":
                cur = rest
                info[cur] = {"kd": (1.0, 1.0, 1.0), "d": 1.0, "map_kd": None, "map_d": None}
            elif cur and k == "Kd":
                info[cur]["kd"] = tuple(float(x) for x in rest.split()[:3])
            elif cur and k == "d":
                info[cur]["d"] = float(rest.split()[-1])
            elif cur and k == "Tr":
                info[cur]["d"] = 1.0 - float(rest.split()[-1])
            elif cur and k in ("map_Kd", "map_d"):
                info[cur]["map_kd" if k == "map_Kd" else "map_d"] = rest
        for name, i in info.items():
            kd = i["kd"]
            if i["map_kd"] and (f := self._find_texture(i["map_kd"], mtl_path.parent, obj_dir)):
                mats[name] = Material(name, (1, 1, 1, i["d"]), Texture(Image.open(f)),
                                      alpha_mode="BLEND" if i["d"] < 1 else "OPAQUE")
            elif i["map_d"] and (f := self._find_texture(i["map_d"], mtl_path.parent, obj_dir)):
                im = Image.open(f)
                a = im.getchannel("A") if im.mode in ("RGBA", "LA") and im.getchannel("A").getextrema()[0] < 255 \
                    else im.convert("L")
                white = Image.new("RGBA", im.size, (255, 255, 255, 255))
                white.putalpha(a)
                mats[name] = Material(name, (*kd, i["d"]), Texture(white), alpha_mode="MASK")   # Kd traité comme linéaire
            else:
                if i["map_kd"] or i["map_d"]:
                    ref = Path((i["map_kd"] or i["map_d"]).replace("\\", "/")).name
                    self.notes.append(f"texture introuvable : {ref} (matériau {name} -> couleur unie)")
                mats[name] = Material(name, (*kd, i["d"]), None, alpha_mode="BLEND" if i["d"] < 1 else "OPAQUE")
        return mats


def load_scene(path, texture_dirs=()) -> Scene3D:
    """Choisit le chargeur selon l'extension. `texture_dirs` : dossiers où chercher les textures (OBJ/MTL)."""
    ext = Path(path).suffix.lower()
    loaders = {".gltf": GltfLoader, ".glb": GltfLoader, ".obj": ObjLoader}
    if ext not in loaders:
        raise ValueError(f"Format « {ext} » non géré. Formats : {', '.join(loaders)}")
    return (ObjLoader(texture_dirs) if ext == ".obj" else loaders[ext]()).load(path)
