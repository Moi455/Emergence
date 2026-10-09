"""Génère des pièces de test glTF (+ .bin + PNG) qui imitent la STRUCTURE du kit Emergence :
multi-matériaux, textures REPEAT, vitre translucide, feuille en alpha-cutout, vertex colors.
Les textures sont procédurales : on connaît leurs couleurs, donc on peut vérifier la fidélité.

    python tools/make_test_assets.py testdata/
"""
import json
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image

# ----------------------------------------------------------------------------- textures procédurales
BRICK_RGB, MORTAR_RGB = (165, 62, 46), (205, 198, 185)
PLASTER_RGB, WOOD_RGB = (222, 205, 170), (112, 76, 46)
TILE_RGB, TILE_LINE_RGB = (178, 84, 52), (110, 45, 30)


def _png(arr, path):
    Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8)).save(path)


def make_textures(d: Path):
    rng = np.random.default_rng(3)
    n = 256
    yy, xx = np.mgrid[0:n, 0:n]
    bh, bw, m = n // 8, n // 4, 5
    row = yy // bh
    xs = (xx + (row % 2) * (bw // 2))
    mortar = ((xs % bw) < m) | ((yy % bh) < m)
    shade = 0.88 + 0.24 * ((((xs // bw) * 7 + row * 13) % 10) / 10.0)
    brick = np.array(BRICK_RGB)[None, None, :] * shade[..., None] + rng.normal(0, 4, (n, n, 1))
    _png(np.where(mortar[..., None], np.array(MORTAR_RGB), brick), d / "brick.png")
    _png(np.array(PLASTER_RGB) + rng.normal(0, 5, (128, 128, 1)), d / "plaster.png")
    yy, xx = np.mgrid[0:128, 0:128]
    _png(np.array(WOOD_RGB)[None, None] * (0.86 + 0.14 * np.sin(xx * 0.55 + rng.normal(0, .2, (128, 128))))[..., None],
         d / "wood.png")
    xs, ys = xx % 32, yy % 32                                   # écailles : cercles décalés d'une rangée sur deux
    xs = (xx + ((yy // 16) % 2) * 16) % 32
    dist = np.hypot(xs - 16, (yy % 16) * 1.0)
    line = (np.abs(dist - 15) < 1.6) | (xs < 1)
    _png(np.where(line[..., None], np.array(TILE_LINE_RGB), np.array(TILE_RGB)), d / "tiles.png")
    yy, xx = np.mgrid[0:128, 0:128]
    inside = ((xx - 64) / 30.0) ** 2 + ((yy - 64) / 60.0) ** 2 <= 1.0
    leaf = np.zeros((128, 128, 4))
    leaf[..., 0], leaf[..., 1], leaf[..., 2] = 60 + yy * 0.3, 150 + yy * 0.3, 45
    leaf[np.abs(xx - 64) < 2, :3] *= 0.6                         # nervure
    leaf[..., 3] = np.where(inside, 255, 0)
    _png(leaf, d / "leaf.png")


# ----------------------------------------------------------------------------- mini-éditeur glTF
class MeshData:
    def __init__(self):
        self.pos, self.uv, self.col, self.idx = [], [], [], []

    def quad(self, p0, p1, p2, p3, uv):
        b = len(self.pos)
        self.pos += [p0, p1, p2, p3]
        self.uv += [uv(p) for p in (p0, p1, p2, p3)] if callable(uv) else list(uv)
        self.idx += [(b, b + 1, b + 2), (b, b + 2, b + 3)]

    def arrays(self):
        return (np.array(self.pos, np.float32), np.array(self.uv, np.float32), np.array(self.idx, np.uint16))


class GltfBuilder:
    def __init__(self, outdir: Path, name: str):
        self.dir, self.name = outdir, name
        self.blob, self.views, self.accs = bytearray(), [], []
        self.mats, self.texs, self.imgs, self.prims, self._tex = [], [], [], [], {}

    def _add(self, arr, comp, typ, target, minmax=False):
        while len(self.blob) % 4:
            self.blob.append(0)
        self.views.append({"buffer": 0, "byteOffset": len(self.blob), "byteLength": arr.nbytes, "target": target})
        self.blob.extend(arr.tobytes())
        a = {"bufferView": len(self.views) - 1, "componentType": comp, "count": len(arr), "type": typ}
        if minmax:
            a["min"], a["max"] = arr.min(0).astype(float).tolist(), arr.max(0).astype(float).tolist()
        self.accs.append(a)
        return len(self.accs) - 1

    def material(self, name, color=(1, 1, 1, 1), tex=None, alpha="OPAQUE", cutoff=0.5, double=False):
        pbr = {"baseColorFactor": list(color), "metallicFactor": 0.0, "roughnessFactor": 1.0}
        if tex:
            if tex not in self._tex:
                self.imgs.append({"uri": tex})
                self.texs.append({"source": len(self.imgs) - 1, "sampler": 0})
                self._tex[tex] = len(self.texs) - 1
            pbr["baseColorTexture"] = {"index": self._tex[tex]}
        m = {"name": name, "pbrMetallicRoughness": pbr, "doubleSided": double}
        if alpha != "OPAQUE":
            m["alphaMode"] = alpha
            if alpha == "MASK":
                m["alphaCutoff"] = cutoff
        self.mats.append(m)
        return len(self.mats) - 1

    def primitive(self, md: MeshData, mat: int, colors=None):
        pos, uv, idx = md.arrays()
        at = {"POSITION": self._add(pos, 5126, "VEC3", 34962, True), "TEXCOORD_0": self._add(uv, 5126, "VEC2", 34962)}
        if colors is not None:
            at["COLOR_0"] = self._add(np.array(colors, np.float32), 5126, "VEC4", 34962)
        self.prims.append({"attributes": at, "indices": self._add(idx.reshape(-1), 5123, "SCALAR", 34963), "material": mat})

    def write(self):
        while len(self.blob) % 4:
            self.blob.append(0)
        doc = {"asset": {"version": "2.0", "generator": "make_test_assets"}, "scene": 0, "scenes": [{"nodes": [0]}],
               "nodes": [{"name": self.name, "mesh": 0}], "meshes": [{"name": self.name, "primitives": self.prims}],
               "materials": self.mats, "textures": self.texs, "images": self.imgs,
               "samplers": [{"magFilter": 9729, "minFilter": 9987, "wrapS": 10497, "wrapT": 10497}],
               "accessors": self.accs, "bufferViews": self.views,
               "buffers": [{"uri": f"{self.name}.bin", "byteLength": len(self.blob)}]}
        (self.dir / f"{self.name}.bin").write_bytes(bytes(self.blob))
        (self.dir / f"{self.name}.gltf").write_text(json.dumps(doc))


# ----------------------------------------------------------------------------- pièces
def wall_window(d: Path):
    """Mur 2 x 2 x 0,2 m, fenêtre traversante 0,8 x 0,8 m + vitre à 9,5 % d'opacité. Volume FERMÉ,
    3 matériaux (brique devant, enduit derrière, bois sur la tranche), comme Wall_Plaster_Window_*."""
    W, H, T = 2.0, 2.0, 0.2
    x0, x1, y0, y1 = 0.6, 1.4, 0.7, 1.5
    b = GltfBuilder(d, "Wall_Window")
    mb = b.material("MI_Brick", tex="brick.png")
    mp = b.material("MI_Plaster", tex="plaster.png")
    mw = b.material("MI_WoodTrim", tex="wood.png")
    mg = b.material("MI_WindowGlass", (0.8, 0.8, 0.8, 0.095), alpha="BLEND", double=True)
    front, back, trim, glass = MeshData(), MeshData(), MeshData(), MeshData()
    for (a, bb, c, e) in [(0, 0, x0, H), (x1, 0, W, H), (x0, 0, x1, y0), (x0, y1, x1, H)]:
        front.quad((a, bb, T), (c, bb, T), (c, e, T), (a, e, T), lambda p: (p[0] / 1.0, 1 - p[1] / 0.52))
        back.quad((c, bb, 0), (a, bb, 0), (a, e, 0), (c, e, 0), lambda p: (p[0] / 1.0, 1 - p[1] / 1.0))
    sides = [((0, 0, 0), (W, 0, 0), (W, 0, T), (0, 0, T)), ((0, H, T), (W, H, T), (W, H, 0), (0, H, 0)),
             ((0, 0, T), (0, H, T), (0, H, 0), (0, 0, 0)), ((W, 0, 0), (W, H, 0), (W, H, T), (W, 0, T)),
             ((x0, y0, 0), (x0, y1, 0), (x0, y1, T), (x0, y0, T)), ((x1, y0, T), (x1, y1, T), (x1, y1, 0), (x1, y0, 0)),
             ((x0, y0, T), (x1, y0, T), (x1, y0, 0), (x0, y0, 0)), ((x0, y1, 0), (x1, y1, 0), (x1, y1, T), (x0, y1, T))]
    for q in sides:
        L = np.linalg.norm(np.subtract(q[1], q[0]))
        trim.quad(*q, [(0, 0), (L / 0.5, 0), (L / 0.5, 1), (0, 1)])
    glass.quad((x0, y0, T / 2), (x1, y0, T / 2), (x1, y1, T / 2), (x0, y1, T / 2), [(0, 0)] * 4)
    for md, m in [(front, mb), (back, mp), (trim, mw), (glass, mg)]:
        b.primitive(md, m)
    b.write()


def roof_tiles(d: Path):
    """Nappe de toit 3 x 2 m inclinée à 35°, surface ouverte et mince (comme Roof_RoundTiles_*)."""
    b = GltfBuilder(d, "Roof_Tiles")
    m = b.material("MI_RoundTiles", tex="tiles.png", double=True)
    c, s = math.cos(math.radians(35)), math.sin(math.radians(35))
    md = MeshData()
    md.quad((0, 0, 0), (3, 0, 0), (3, 2 * s, 2 * c), (0, 2 * s, 2 * c),
            [(0, 4), (6, 4), (6, 0), (0, 0)])                      # 6 x 4 tuiles (UV > 1 : REPEAT)
    b.primitive(md, m)
    b.write()


def barrel(d: Path):
    """Tonneau fermé : texture bois x couleurs de sommet (cerclages) -> teste la multiplication."""
    N, M, Hh = 40, 40, 0.8
    r = lambda y: 0.3 * (1 - 0.22 * ((y - Hh / 2) / (Hh / 2)) ** 2)
    pos, uv, col = [], [], []
    for j in range(M + 1):
        y = Hh * j / M
        band = 0.12 <= y <= 0.18 or 0.62 <= y <= 0.68
        for i in range(N + 1):
            t = 2 * math.pi * i / N
            pos.append((r(y) * math.cos(t), y, r(y) * math.sin(t)))
            uv.append((3.0 * i / N, 1 - y / Hh))
            col.append((0.22, 0.22, 0.25, 1) if band else (1, 1, 1, 1))
    md, idx = MeshData(), []
    for j in range(M):
        for i in range(N):
            a = j * (N + 1) + i
            idx += [(a, a + 1, a + N + 2), (a, a + N + 2, a + N + 1)]
    for yc, flip in ((0.0, True), (Hh, False)):                    # bouchons
        c = len(pos); pos.append((0, yc, 0)); uv.append((0.5, 0.5)); col.append((1, 1, 1, 1))
        base = (0 if flip else M) * (N + 1)
        for i in range(N):
            idx.append((c, base + i + 1, base + i) if flip else (c, base + i, base + i + 1))
    md.pos, md.uv, md.idx = pos, uv, idx
    b = GltfBuilder(d, "Prop_Barrel")
    b.primitive(md, b.material("MI_WoodTrim", tex="wood.png"), colors=col)
    b.write()


def vine_leaf(d: Path):
    """Carte 0,5 x 0,5 m, texture RGBA, alphaMode MASK : seule la forme de la feuille doit devenir voxels."""
    b = GltfBuilder(d, "Prop_VineLeaf")
    m = b.material("MI_Vine", tex="leaf.png", alpha="MASK", cutoff=0.5, double=True)
    md = MeshData()
    md.quad((0, 0, 0.25), (0.5, 0, 0.25), (0.5, 0.5, 0.25), (0, 0.5, 0.25), [(0, 1), (1, 1), (1, 0), (0, 0)])
    b.primitive(md, m)
    b.write()


def main(out="testdata"):
    d = Path(out)
    d.mkdir(parents=True, exist_ok=True)
    make_textures(d)
    for f in (wall_window, roof_tiles, barrel, vine_leaf):
        f(d)
    print("Pièces générées dans", d.resolve(), ":", ", ".join(sorted(p.name for p in d.glob("*.gltf"))))


if __name__ == "__main__":
    main(*sys.argv[1:2])
