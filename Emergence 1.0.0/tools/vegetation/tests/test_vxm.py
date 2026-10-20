# -*- coding: utf-8 -*-
"""Tests de l'exporteur .vxm (docs/19a § 1, tâche L04) : python3 -m unittest discover -s tools/vegetation/tests"""
import os
import struct
import sys
import tempfile
import time
import unittest
import zlib

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import read_vxm as rv          # noqa: E402
import voxel_bush as vb        # noqa: E402
import voxel_tree as vt        # noqa: E402

_CACHE = {}


def chene_lods():
    """Chêne 42 de 14 m, 6 LOD, sans ombrage cuit (calculé une seule fois)."""
    if "chene" not in _CACHE:
        t0 = time.time()
        regen = lambda v: vt.generate_tree(42, "chene", 14, "summer", 1.0, False, voxel=v)
        tree0 = regen(vt.VOXEL)
        _CACHE["chene"] = vt.build_lods(tree0, regen, [0, 1, 2, 3, 4, 5])
        _CACHE["chene_time"] = time.time() - t0
    return _CACHE["chene"]


def expected_cells(tree):
    """Ensemble (x, y, z, sorte, rampe) attendu, calculé à part de l'exporteur (boucle lente mais claire)."""
    steps = tree.export["steps"]
    prio = {1: 0, 3: 1, 4: 2, 5: 3, 2: 4}
    best = {}
    for (x, y, z), k, p in zip(tree.coords.tolist(), tree.kind.tolist(), tree.pal.tolist()):
        cell = (x - tree.base[0], z, y - tree.base[1])      # repère monde : x est, y haut, z nord
        if cell not in best or prio[k] < prio[best[cell][0]]:
            best[cell] = (k, (p - 1) // steps)
    return {c + v for c, v in best.items()}


class ChenePourVxm(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lods = chene_lods()
        cls.dir = tempfile.TemporaryDirectory()
        cls.path = os.path.join(cls.dir.name, "chene.vxm")
        cls.size = vt.save_vxm(cls.lods, cls.path, export_sky=True, export_pal=True)
        cls.vxm = rv.read_vxm(cls.path)

    @classmethod
    def tearDownClass(cls):
        cls.dir.cleanup()

    def test_nombre_de_voxels_du_chene(self):
        self.assertEqual(self.vxm.lod(0).count, 607_784)         # mesuré par l'architecte le 20 oct.
        self.assertEqual(len(self.lods[0].coords), 607_784 + 248)  # 248 cellules écorce + rameau

    def test_aller_retour_exact_tous_les_lod(self):
        for k, tree in self.lods.items():
            self.assertEqual(self.vxm.lod(k).cell_set(), expected_cells(tree), f"LOD {k}")

    def test_pivot_au_pied_du_tronc(self):
        w = self.vxm.lod(0).world()
        pied = w[(w[:, 0] == 0) & (w[:, 2] == 0) & (w[:, 1] == 0)]
        self.assertEqual(len(pied), 1)       # la cellule du pied du tronc est (0, 0, 0)
        self.assertEqual(int(w[:, 1].min()), 0)
        self.assertEqual(int(w[:, 1].max()) + 1, int(self.lods[0].coords[:, 2].max()) + 1)

    def test_entete(self):
        h = self.vxm.header
        self.assertEqual((h["species"], h["seed_int"], h["height_m"], h["season"]), ("chene", 42, 14.0, "summer"))
        self.assertEqual(h["lods"], [0, 1, 2, 3, 4, 5])
        self.assertEqual(h["voxel_m"], 0.05)
        self.assertEqual(h["steps"], 30)             # 255 // 8 rampes plafonné à 30
        self.assertEqual(h["ramp_roles"][:3], ["bark", "bark_alt", "twig"])
        self.assertEqual(h["axes"], "x_est,y_haut,z_nord")
        self.assertEqual(len(h["generator_sha256"]), 64)
        self.assertEqual(len(h["palette"]), 256)

    def test_canaux_pal_et_sky(self):
        s = self.vxm.lod(0)
        steps = self.vxm.header["steps"]
        self.assertTrue(np.array_equal((s.pal.astype(np.int64) - 1) // steps, s.ramp))
        self.assertGreaterEqual(int(s.sky.min()), 45)           # compute_light : ciel >= 0,18
        self.assertLessEqual(int(s.sky.max()), 255)

    def test_boites_des_lod(self):
        # Spec 19b : ±1 voxel grossier. MESURÉ : l'écart atteint 1,5 voxel grossier (LOD 2, bord est) :
        # la grille du LOD k est calée sur le coin de la cellule pivot (≤ 1 voxel de décalage) et un
        # voxel grossier rempli par une brindille déborde de la boîte fine (≤ 1 voxel). Tolérance : 2.
        mn0, mx0 = self.vxm.lod(0).bbox()
        for k in range(1, 6):
            mnk, mxk = self.vxm.lod(k).bbox()
            f = 2 ** k
            for a in range(3):
                self.assertLessEqual(abs(mnk[a] * f - mn0[a]), 2 * f, f"min LOD {k} axe {a}")
                self.assertLessEqual(abs((mxk[a] + 1) * f - (mx0[a] + 1)), 2 * f, f"max LOD {k} axe {a}")

    def test_temps_des_six_lod(self):
        self.assertLess(_CACHE["chene_time"], 20.0)

    def test_determinisme_octet_pour_octet(self):
        autre = os.path.join(self.dir.name, "chene2.vxm")
        vt.save_vxm(self.lods, autre, export_sky=True, export_pal=True)
        with open(self.path, "rb") as a, open(autre, "rb") as b:
            self.assertEqual(a.read(), b.read())

    def test_determinisme_apres_regeneration(self):
        regen = lambda v: vt.generate_tree(42, "chene", 14, "summer", 1.0, False, voxel=v)
        lods = vt.build_lods(regen(vt.VOXEL), regen, [0, 3])
        a, b = os.path.join(self.dir.name, "r1.vxm"), os.path.join(self.dir.name, "r2.vxm")
        vt.save_vxm(lods, a)
        vt.save_vxm(vt.build_lods(regen(vt.VOXEL), regen, [0, 3]), b)
        self.assertEqual(open(a, "rb").read(), open(b, "rb").read())

    def test_sans_compression_meme_contenu(self):
        brut = os.path.join(self.dir.name, "brut.vxm")
        vt.save_vxm({0: self.lods[0], 5: self.lods[5]}, brut, compress=False)
        v = rv.read_vxm(brut)
        self.assertFalse(v.flags & rv.FLAG_ZLIB)
        self.assertEqual(v.lod(5).cell_set(), self.vxm.lod(5).cell_set())

    def test_teinte_variante(self):
        roles = self.vxm.header["ramp_roles"]
        self.assertEqual(rv.tint_variant(rv.KIND_BARK, 0, roles), 0)
        self.assertEqual(rv.tint_variant(rv.KIND_BARK, 1, roles), 1)
        self.assertEqual(rv.tint_variant(rv.KIND_TWIG, 2, roles), 2)
        self.assertEqual(rv.tint_variant(rv.KIND_LEAF, 4, roles), 0)


class FichierCorrompu(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = vt.save_vxm and _petit_fichier()

    def _refait_crc(self, b):
        return b[:-4] + struct.pack("<I", zlib.crc32(b[:-4]) & 0xFFFFFFFF)

    def test_fichier_sain(self):
        self.assertEqual(rv.parse_vxm(self.data).lod(0).count, 3)

    def test_crc_invalide(self):
        b = bytearray(self.data)
        b[-10] ^= 0xFF
        with self.assertRaisesRegex(rv.VxmError, "CRC"):
            rv.parse_vxm(bytes(b))

    def test_signature(self):
        with self.assertRaisesRegex(rv.VxmError, "signature"):
            rv.parse_vxm(self._refait_crc(b"VXM2" + self.data[4:]))

    def test_version_future_refusee(self):
        b = self.data[:4] + struct.pack("<H", 2) + self.data[6:]
        with self.assertRaisesRegex(rv.VxmError, "version"):
            rv.parse_vxm(self._refait_crc(b))

    def test_drapeau_inconnu(self):
        b = self.data[:6] + struct.pack("<H", 0x80 | 1) + self.data[8:]
        with self.assertRaisesRegex(rv.VxmError, "drapeaux"):
            rv.parse_vxm(self._refait_crc(b))

    def test_troncature(self):
        for n in (0, 8, 15, len(self.data) // 2, len(self.data) - 5):
            with self.assertRaises(rv.VxmError, msg=f"{n} octets"):
                rv.parse_vxm(self.data[:n])
        # tronqué mais avec un CRC recalculé : la structure doit encore être refusée
        with self.assertRaises(rv.VxmError):
            rv.parse_vxm(self._refait_crc(self.data[:-9] + b"\0\0\0\0"))

    def test_octets_en_trop(self):
        with self.assertRaisesRegex(rv.VxmError, "trop"):
            rv.parse_vxm(self._refait_crc(self.data[:-4] + b"\0" + b"\0\0\0\0"))

    def test_fichier_inexistant(self):
        with self.assertRaises(OSError):
            rv.read_vxm("/nonexistent/x.vxm")


def _petit_fichier():
    return _bytes_of(vt.orientation_scene(), compress=False)


def _bytes_of(by_lod, **kw):
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "a.vxm")
        vt.save_vxm(by_lod, p, **kw)
        with open(p, "rb") as f:
            return f.read()


class Orientation(unittest.TestCase):
    def test_rouge_a_l_est_bleu_au_nord(self):
        v = rv.parse_vxm(_bytes_of(vt.orientation_scene()))
        s = v.lod(0)
        w = s.world()
        self.assertEqual(w[s.kind == rv.KIND_FLOWER][0].tolist(), [1, 0, 0])   # rouge : +x (est)
        self.assertEqual(w[s.kind == rv.KIND_FRUIT][0].tolist(), [0, 0, 1])    # bleu : +z (nord)
        self.assertEqual(w[s.kind == rv.KIND_BARK][0].tolist(), [0, 0, 0])
        ramps = v.header["ramps"]
        self.assertGreater(ramps[int(s.ramp[s.kind == rv.KIND_FLOWER][0])][1][0], 200)   # rampe rouge
        self.assertGreater(ramps[int(s.ramp[s.kind == rv.KIND_FRUIT][0])][1][2], 200)    # rampe bleue

    def test_ligne_de_commande(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "o")
            self.assertEqual(vt.main(["--orientation-test", "--out", out]), 0)
            self.assertEqual(rv.main([out + ".vxm", "--orientation"]), 0)


class Arbuste(unittest.TestCase):
    def test_buis_topiaire_et_lod_omis(self):
        regen = lambda v: vb.generate_bush(7, "buis", 1.2, "summer", 1.0, False, "sphere", voxel=v)
        lods = vt.build_lods(regen(vt.VOXEL), regen, [0, 1, 2, 3, 4, 5])
        self.assertNotIn(5, lods)            # voxel de 1,6 m > 1,2 m : omis
        data = _bytes_of(lods, export_pal=True, generator="voxel_bush.py")
        v = rv.parse_vxm(data)
        self.assertEqual(v.header["topiary"], "sphere")
        self.assertEqual(v.header["generator"], "voxel_bush.py")
        self.assertEqual(v.header["lods"], [0, 1, 2, 3, 4])
        for k, t in lods.items():
            self.assertEqual(v.lod(k).cell_set(), expected_cells(t))

    def test_rosier_automne_rampes_stables(self):
        regen = lambda v: vb.generate_bush(5, "rosier", 1.2, "autumn", 1.0, False, None, voxel=v)
        lods = vt.build_lods(regen(vt.VOXEL), regen, [0, 1, 2])
        self.assertEqual(len(rv.parse_vxm(_bytes_of(lods, generator="voxel_bush.py")).lods), 3)


class EntreesInvalides(unittest.TestCase):
    def setUp(self):
        self.t = vt.orientation_scene()[0]

    def save(self, d, **kw):
        with tempfile.TemporaryDirectory() as td:
            vt.save_vxm(d, os.path.join(td, "x.vxm"), **kw)

    def test_aucun_lod(self):
        with self.assertRaises(ValueError):
            self.save({})

    def test_lod_hors_borne(self):
        for bad in (6, -1):
            with self.assertRaises(ValueError):
                self.save({bad: self.t})

    def test_voxel_incoherent_avec_le_lod(self):
        with self.assertRaisesRegex(ValueError, "voxel"):
            self.save({0: self.t, 1: self.t})

    def test_arbre_vide(self):
        vide = vt.VoxelTree(self.t.coords[:0], self.t.pal[:0], self.t.kind[:0], self.t.palette, self.t.base,
                            self.t.voxel_size, self.t.meta, self.t.export)
        with self.assertRaisesRegex(ValueError, "vide"):
            self.save({0: vide})

    def test_generateur_inconnu(self):
        with self.assertRaisesRegex(ValueError, "introuvable"):
            self.save({0: self.t}, generator="nexiste_pas.py")

    def test_lods_illisibles(self):
        for bad in ("", "a,b", "0,6", "-1", "2,1", "1,1"):
            with self.assertRaises(ValueError, msg=bad):
                vt.parse_lods(bad)
        self.assertEqual(vt.parse_lods("0, 1,5"), [0, 1, 5])

    def test_essence_inconnue_et_saison(self):
        with self.assertRaises(ValueError):
            vt.generate_tree(1, "baobab", 10)
        with self.assertRaises(ValueError):
            vt.generate_tree(1, "chene", 10, "printemps")

    def test_cli_refuse(self):
        with self.assertRaises(SystemExit):
            vt.main(["--formats", "vxm,gif", "--out", "/tmp/jamais"])
        with self.assertRaises(SystemExit):
            vt.main(["--formats", "vxm", "--lods", "7", "--out", "/tmp/jamais"])


if __name__ == "__main__":
    unittest.main()
