"""Tests du format VXP : sans perte, accès aléatoire, matériaux, dédup, coque seule exacte (avec poches), entités."""
import sys
import unittest
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE.parent))
from test_voxelizer import _tris_to_scene, box_tris, run  # noqa: E402
from voxelizer import Material, MeshPrimitive, Scene3D, VoxelPack, pack_model  # noqa: E402
from voxelizer.compact import encode, morton3, pack_bits, put_varints, read_varints, unmorton3, unpack_bits  # noqa: E402


def structured_volume(seed=0):
    """Volume creux strié, avec 3 matériaux : de quoi exercer palettes, runs et valeurs uniques."""
    rng = np.random.default_rng(seed)
    g = np.indices((40, 30, 24)).reshape(3, -1).T
    keep = ((g[:, 0] - 20) ** 2 + (g[:, 1] - 15) ** 2 + (g[:, 2] - 12) ** 2 < 150) | (g[:, 2] < 3)
    c = g[keep]
    col = (c[:, 0] // 5 + (rng.random(len(c)) < 0.1) * 3) % 17
    mat = (c[:, 2] // 8).astype(int)
    return c, col, mat


class TestPrimitives(unittest.TestCase):
    def test_morton(self):
        a = np.random.default_rng(0).integers(0, 1 << 20, (3, 4000))
        x, y, z = unmorton3(morton3(*a))
        self.assertTrue((x == a[0]).all() and (y == a[1]).all() and (z == a[2]).all())

    def test_varint_extremes(self):
        v = np.array([0, 1, 127, 128, 16383, 16384, 2 ** 40, 2 ** 63 - 1], dtype=np.uint64)
        self.assertEqual(read_varints(memoryview(put_varints(v)), 0, len(v))[0], v.tolist())

    def test_bitpack(self):
        rng = np.random.default_rng(1)
        for b in (1, 2, 3, 5, 8, 11):
            w = rng.integers(0, 1 << b, 997)
            self.assertTrue((unpack_bits(pack_bits(w, b), len(w), b) == w).all())


class TestVXP(unittest.TestCase):
    def setUp(self):
        self.c, self.col, self.mat = structured_volume()
        self.ref = {tuple(p): (int(a), int(b)) for p, a, b in zip(self.c.tolist(), self.col, self.mat)}

    def test_lossless_every_config(self):
        for brick in (4, 8, 16):
            for comp in (None, "zlib", "lzma"):
                p = VoxelPack(encode(*self.c.T, self.col, self.mat, brick=brick, compress=comp, chunk=8))
                x, y, z, c, m = p.arrays()
                got = {(int(i), int(j), int(k)): (int(a), int(b)) for i, j, k, a, b in zip(x, y, z, c, m)}
                self.assertEqual(got, self.ref, (brick, comp))

    def test_random_access_matches(self):
        p = VoxelPack(encode(*self.c.T, self.col, self.mat, brick=8, compress="zlib", chunk=4))
        rng = np.random.default_rng(3)
        for q in map(tuple, rng.integers(-3, 45, (1500, 3)).tolist()):
            self.assertEqual(p.get(*q), self.ref.get(q), q)
        for q in list(self.ref)[:300]:
            self.assertEqual(p.get(*q), self.ref[q])

    def test_negative_and_offset_coordinates(self):
        p = VoxelPack(encode(*(self.c - [100, 7, -50]).T, self.col, self.mat, brick=8))
        self.assertEqual(p.get(*(self.c[10] - [100, 7, -50]).tolist()), self.ref[tuple(self.c[10])])

    def test_identical_bricks_are_deduplicated(self):
        base = np.argwhere(np.random.default_rng(5).random((8, 8, 8)) < 0.5)
        cells = np.vstack([base, base + [16, 0, 0], base + [0, 24, 8]])
        col = np.tile(np.arange(len(base)) % 5, 3)
        p = VoxelPack(encode(*cells.T, col, None, brick=8))
        self.assertEqual(len(p._keys), 3)
        self.assertEqual(len(p._off) - 1, 1)                 # une seule charge utile pour 3 bricks identiques

    def test_uniform_regions_are_tiny(self):
        cube = np.argwhere(np.ones((32, 32, 32), bool))
        data = encode(*cube.T, np.zeros(len(cube), np.int64), None, brick=8)
        self.assertLess(len(data), 260)                      # 32768 voxels -> ~200 o (dont ~2 o de répertoire par brick)
        self.assertEqual(len(VoxelPack(data)._off) - 1, 1)   # une seule charge utile partagée par les 64 bricks

    def test_shell_only_is_exactly_lossless_even_with_enclosed_pockets(self):
        solid = np.argwhere(np.ones((20, 20, 20), bool))
        pocket = (np.abs(solid - 10) <= 1).all(axis=1)       # vide clos au centre (3x3x3)
        cells = solid[~pocket]
        exposed_empty = np.array([[x, y, z] for x in (9, 10, 11) for y in (9, 10, 11) for z in (9, 10, 11)])
        # la coque = voxels ayant au moins une face exposée (le contour de la poche en fait partie)
        from voxelizer.lattice import exposed_masks, pack
        keys = pack(*cells.T); o = np.argsort(keys); cells = cells[o]; keys = keys[o]
        shell = cells[exposed_masks(keys) != 0]
        from voxelizer.compact import _pockets
        pk = _pockets(cells, shell)
        self.assertEqual(len(pk), 27)                         # sans correction, la poche serait comblée
        col = np.zeros(len(shell), np.int64)
        p = VoxelPack(encode(*shell.T, col, None, brick=8, shell_only=True, holes=(pk[:, 0], pk[:, 1], pk[:, 2])))
        x, y, z, _, _ = p.arrays(fill=True)
        self.assertEqual(set(zip(x.tolist(), y.tolist(), z.tolist())), set(map(tuple, cells.tolist())))

    def test_model_roundtrip_keeps_color_material_and_entities(self):
        def quad(x0, x1, name):
            t = box_tris((x0, 0, 0), (x1, 0.3, 0.3))
            return MeshPrimitive(np.array(t, float).reshape(-1, 3), np.arange(36).reshape(-1, 3), Material(name, (0.7, 0.3, 0.2, 1.0) if name == "A" else (0.2, 0.4, 0.8, 1.0)))
        m = run(Scene3D([quad(0, 0.3, "A"), quad(0.3, 0.6, "B")]), palette_size=8).model
        self.assertEqual(m.materials, ["A", "B"])
        for shell in (False, True):
            m2 = VoxelPack(pack_model(m, shell_only=shell, compress="lzma")).to_model()
            self.assertEqual(len(m2), len(m))
            self.assertEqual(m2.materials, m.materials)
            for v in m:
                w = m2.get(*v.cell)
                self.assertIsNotNone(w)
                self.assertEqual((w.kind, w.faces), (v.kind, v.faces))                  # géométrie : toujours exacte
                if not shell or v.is_visible:                                          # couleur+matériau : exacts pour tout voxel visible
                    self.assertEqual((w.color, w.material), (v.color, v.material))     # (intérieur en coque seule : approché)
        self.assertEqual(len({v.material for v in m}), 2)    # les deux matériaux sont bien présents dans les voxels

    def test_vxp_is_much_smaller_than_a_naive_list(self):
        data = encode(*self.c.T, self.col, self.mat, brick=8, compress="zlib")
        self.assertLess(len(data), len(self.c) * 7 / 4)       # < 1,75 octet/voxel contre 7 pour x,y,z,couleur naïfs


if __name__ == "__main__":
    unittest.main(verbosity=2)
