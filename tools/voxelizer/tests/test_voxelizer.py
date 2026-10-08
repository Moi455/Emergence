"""Tests : chaque assertion compare à une vérité terrain calculée INDÉPENDAMMENT du moteur.
    python -m unittest discover -s tests -v   (depuis la racine du projet ; génère testdata/ si absent)
"""
import math
import sys
import tempfile
import unittest
import warnings
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from voxelizer import (GlbExporter, GltfLoader, JsonExporter, JsonImporter, LfsPointerError, Material, MeshPrimitive,
                       Scene3D, ScaleSpec, VoxelizationPipeline, VoxelizeConfig, VoxelKind, VoxelModel, load_scene)
from voxelizer.lattice import exposed_masks, pack
from voxelizer.scene import srgb_to_linear

TESTDATA = ROOT / "testdata"
VS = 0.02
FAITHFUL = dict(sharpen=0.0, saturation=1.0, contrast=1.0)       # aucune retouche artistique : mesures de fidélité


def _tris_to_scene(tris, rgb=(0.5, 0.5, 0.5), mat=None):
    t = np.asarray(tris, float).reshape(-1, 3)
    prim = MeshPrimitive(t, np.arange(len(t)).reshape(-1, 3), mat or Material("flat", (*rgb, 1.0)))
    return Scene3D([prim])


def box_tris(lo, hi, skip_top_hole=None):
    """Boîte fermée ; `skip_top_hole=(x0,x1,z0,z1)` perce la face du haut (maillage troué)."""
    (x0, y0, z0), (x1, y1, z1) = lo, hi
    def q(a, b, c, d):
        return [a, b, c, a, c, d]
    t = []
    t += q((x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1))                       # bas
    t += q((x0, y0, z0), (x0, y1, z0), (x1, y1, z0), (x1, y0, z0))                       # fond
    t += q((x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1))                       # devant
    t += q((x0, y0, z0), (x0, y0, z1), (x0, y1, z1), (x0, y1, z0))                       # gauche
    t += q((x1, y0, z0), (x1, y1, z0), (x1, y1, z1), (x1, y0, z1))                       # droite
    if skip_top_hole is None:
        t += q((x0, y1, z0), (x0, y1, z1), (x1, y1, z1), (x1, y1, z0))
    else:
        hx0, hx1, hz0, hz1 = skip_top_hole
        for (a, b, c, d) in [(x0, z0, hx0, z1), (hx1, z0, x1, z1), (hx0, z0, hx1, hz0), (hx0, hz1, hx1, z1)]:
            t += q((a, y1, b), (a, y1, d), (c, y1, d), (c, y1, b))
    return t


def sphere_tris(r, n=48):
    t = []
    P = lambda i, j: (r * math.sin(math.pi * i / n) * math.cos(2 * math.pi * j / (2 * n)),
                      r * math.cos(math.pi * i / n),
                      r * math.sin(math.pi * i / n) * math.sin(2 * math.pi * j / (2 * n)))
    for i in range(n):
        for j in range(2 * n):
            a, b, c, d = P(i, j), P(i + 1, j), P(i + 1, j + 1), P(i, j + 1)
            t += [a, b, c, a, c, d]
    return t


def run(scene, **kw):
    kw = {**FAITHFUL, **kw}
    cfg = VoxelizeConfig(palette_size=kw.pop("palette_size", 0), **kw)
    return VoxelizationPipeline(cfg).run_scene(scene)


class TestGeometry(unittest.TestCase):
    def test_cube_aligned_on_lattice_is_exactly_50_cubed(self):
        """Cube 1 m aligné sur la grille : 50x50x50 cellules, ni 51 (débord) ni creux."""
        m = run(_tris_to_scene(box_tris((0, 0, 0), (1, 1, 1)))).model
        self.assertEqual(len(m), 50 ** 3)
        lo, hi = m.cell_bounds()
        self.assertEqual(tuple(hi - lo + 1), (50, 50, 50))
        self.assertEqual(m.count_by_kind()["interior"], 48 ** 3)          # plein : peau d'un voxel + noyau

    def test_cube_unaligned_is_unbiased(self):
        """Cube décalé de 13 mm : voxel plein ssi son centre est dedans -> exactement 50 cellules par axe."""
        m = run(_tris_to_scene(box_tris((0.013,) * 3, (1.013,) * 3))).model
        self.assertEqual(len(m), 50 ** 3)

    def test_sphere_volume(self):
        r = 0.5
        m = run(_tris_to_scene(sphere_tris(r))).model
        exact = 4 / 3 * math.pi * r ** 3
        err = (m.volume_m3() - exact) / exact
        print(f"\n   sphère : {m.volume_m3():.5f} m³ vs {exact:.5f} m³ -> {err * 100:+.2f} %")
        self.assertLess(abs(err), 0.02)

    def test_no_holes_in_solid(self):
        """Aucune cellule vide entièrement enfermée dans le volume (remplissage complet)."""
        m = run(_tris_to_scene(sphere_tris(0.3))).model
        a = m.to_arrays()["cell"]
        occ = np.zeros(a.max(0) - a.min(0) + 3, bool)
        occ[tuple((a - a.min(0) + 1).T)] = True
        from scipy import ndimage as ndi
        lab, _ = ndi.label(~occ)
        self.assertEqual(len(np.unique(lab[lab > 0])), 1)                  # un seul vide : l'extérieur

    def test_up_axis_z(self):
        m = run(_tris_to_scene(box_tris((0, 0, 0), (0.2, 0.4, 0.6))), input_up="z").model     # Z-haut -> Y-haut
        lo, hi = m.cell_bounds()
        self.assertEqual(tuple(hi - lo + 1), (10, 30, 20))                 # hauteur (Y) = ancien Z = 0,6 m


class TestScale(unittest.TestCase):
    def setUp(self):
        self.sc = _tris_to_scene(box_tris((0, 0, 0), (100, 100, 100)))      # « 100 unités »

    def test_unit_cm(self):
        r = run(self.sc, scale=ScaleSpec(unit="cm"))
        self.assertEqual(len(r.model), 50 ** 3)                           # 100 cm = 1 m = 50 voxels

    def test_factor(self):
        r = run(self.sc, scale=ScaleSpec(unit="cm", factor=0.5))
        self.assertEqual(len(r.model), 25 ** 3)

    def test_fit_height(self):
        r = run(_tris_to_scene(box_tris((0, 0, 0), (3, 3, 3))), scale=ScaleSpec(fit_height=1.0))
        self.assertEqual(len(r.model), 50 ** 3)

    def test_fit_conflict_and_bad_unit(self):
        with self.assertRaises(ValueError):
            run(self.sc, scale=ScaleSpec(fit_height=1.0, fit_width=1.0))
        with self.assertRaises(ValueError):
            run(self.sc, scale=ScaleSpec(unit="parsec"))

    def test_diagnoses_absurd_size(self):
        r = run(_tris_to_scene(box_tris((0, 0, 0), (0.04, 0.04, 0.04))))
        self.assertTrue(any("minuscule" in w for w in r.report.warnings), r.report.warnings)


class TestAssets(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (TESTDATA / "Wall_Window.gltf").exists():
            import make_test_assets
            make_test_assets.main(str(TESTDATA))

    def test_wall_with_window_is_exact(self):
        """Mur 2x2x0,2 m, fenêtre 0,8x0,8 : (4 - 0,64) x 0,2 = 0,672 m³ = 84 000 voxels, au voxel près."""
        r = VoxelizationPipeline(VoxelizeConfig(**FAITHFUL, palette_size=0)).run(TESTDATA / "Wall_Window.gltf")
        m = r.model
        lo, hi = m.cell_bounds()
        self.assertEqual(tuple(hi - lo + 1), (100, 100, 10))
        self.assertEqual(len(m), 84_000)
        self.assertIsNone(m.get(50, 55, 5), "la fenêtre doit rester vide (vitre exclue par défaut)")

    def test_glass_kept_with_alpha(self):
        m = VoxelizationPipeline(VoxelizeConfig(**FAITHFUL, palette_size=0, keep_glass=True)).run(TESTDATA / "Wall_Window.gltf").model
        glass = [v for v in m if v.color[3] < 255]
        self.assertTrue(1400 < len(glass) < 1800, len(glass))              # ~ 40x40 cellules, 1 couche
        self.assertTrue(all(abs(v.color[3] - 0.095 * 255) <= 1 for v in glass))

    def test_texture_color_fidelity(self):
        """Face avant en brique : chaque voxel vs la MOYENNE D'AIRE de la texture sur son empreinte de 2x2 cm
        (8x8 sous-points, floor), calculée en numpy pur, indépendamment de Texture/mipmaps du moteur.
        Zone « brique pure » : on exclut bords du mur et embrasure (bois/enduit, autres matériaux)."""
        m = VoxelizationPipeline(VoxelizeConfig(**FAITHFUL, palette_size=0)).run(TESTDATA / "Wall_Window.gltf").model
        pure = [v for v in m if v.iz == 9 and 3 <= v.ix <= 96 and 3 <= v.iy <= 96
                and not (27 <= v.ix <= 72 and 32 <= v.iy <= 77)]
        tex = srgb_to_linear(np.asarray(Image.open(TESTDATA / "brick.png").convert("RGB"), float) / 255.0)
        h, w = tex.shape[:2]
        sub = (np.arange(8) + .5) / 8

        def area_avg(v):
            x = (v.ix + sub[:, None] * np.ones((1, 8))) * VS
            y = (v.iy + np.ones((8, 1)) * sub[None, :]) * VS
            return tex[np.floor((1 - y / 0.52) * h).astype(int) % h, np.floor(x / 1.0 * w).astype(int) % w].reshape(-1, 3).mean(0)

        exp = np.array([area_avg(v) for v in pure])
        got = srgb_to_linear(np.array([v.color[:3] for v in pure]) / 255.0)
        mean_err = np.abs(got.mean(0) - exp.mean(0)) / exp.mean(0)
        lum = lambda c: c @ np.array([.2126, .7152, .0722])
        corr = np.corrcoef(lum(got), lum(exp))[0, 1]
        med = np.median(np.abs(lum(got) - lum(exp)) / lum(exp))
        print(f"\n   {len(pure)} voxels : écart de moyenne {mean_err.max() * 100:.2f} %, corrélation {corr:.4f}, "
              f"erreur médiane par voxel {med * 100:.1f} %")
        self.assertLess(mean_err.max(), 0.01)       # non biaisé
        self.assertGreater(corr, 0.98)              # le motif de briques est reproduit voxel par voxel
        self.assertLess(med, 0.05)

    def test_leaf_alpha_cutout(self):
        m = VoxelizationPipeline(VoxelizeConfig(**FAITHFUL, palette_size=0)).run(TESTDATA / "Prop_VineLeaf.gltf").model
        self.assertTrue(200 <= len(m) <= 280, len(m))                      # ellipse ~ 34,5 % du carré 26x26
        for v in m:                                                       # aucun voxel hors de l'ellipse (+1 cellule)
            x, y, _ = v.position
            self.assertLessEqual(((x - .25) / (.25 * 30 / 64 + .02)) ** 2 + ((y - .25) / (.25 + .02)) ** 2, 1.0)

    def test_open_roof_stays_a_shell(self):
        r = VoxelizationPipeline(VoxelizeConfig(**FAITHFUL, palette_size=0)).run(TESTDATA / "Roof_Tiles.gltf")
        self.assertEqual(r.model.count_by_kind()["interior"], 0)
        self.assertTrue(any("coque ouverte" in w for w in r.report.warnings))

    def test_barrel_volume(self):
        """Volume du profil de révolution : pi*int r(y)^2 dy = 0,19520 m³ (x0,9959 pour 40 facettes)."""
        m = VoxelizationPipeline(VoxelizeConfig(**FAITHFUL, palette_size=0)).run(TESTDATA / "Prop_Barrel.gltf").model
        exact = math.pi * 0.036 * (2 - 0.44 * 2 / 3 + 0.0484 * 2 / 5) * 0.9959
        err = (m.volume_m3() - exact) / exact
        print(f"\n   tonneau : {m.volume_m3():.5f} m³ vs {exact:.5f} m³ -> {err * 100:+.2f} %")
        self.assertLess(abs(err), 0.03)

    def test_palette_limits_colors(self):
        m = VoxelizationPipeline(VoxelizeConfig(palette_size=16)).run(TESTDATA / "Prop_Barrel.gltf").model
        self.assertLessEqual(len(m.palette), 16)
        self.assertTrue(all(v.color in m.palette for v in m))


class TestSealing(unittest.TestCase):
    def test_leaky_box_needs_seal(self):
        sc = _tris_to_scene(box_tris((0, 0, 0), (0.5, 0.5, 0.5), skip_top_hole=(0.2, 0.26, 0.2, 0.26)))
        leak = run(sc).model
        self.assertEqual(leak.count_by_kind()["interior"], 0)             # le trou fait fuir le remplissage
        sealed = run(sc, seal_radius=4).model
        exact = 0.5 ** 3
        err = (sealed.volume_m3() - exact) / exact
        print(f"\n   boîte trouée scellée : {sealed.volume_m3():.5f} m³ vs {exact:.5f} -> {err * 100:+.1f} %")
        self.assertLess(abs(err), 0.12)


class TestEntities(unittest.TestCase):
    def setUp(self):
        self.m = run(_tris_to_scene(box_tris((0, 0, 0), (0.2, 0.2, 0.2)))).model       # 10x10x10

    def _faces_consistent(self):
        keys = np.sort(np.array([int(pack(*v.cell)) for v in self.m]))
        ref = dict(zip(keys.tolist(), exposed_masks(keys).tolist()))
        for v in self.m:
            self.assertEqual(v.faces, ref[int(pack(*v.cell))], v)

    def test_every_voxel_is_a_distinct_entity(self):
        ids = [v.id for v in self.m]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(id(a) != id(b) for a, b in zip(list(self.m)[:50], list(self.m)[1:51])))
        v = self.m.get(0, 0, 0)
        self.assertEqual(v.position, (0.01, 0.01, 0.01))
        self.assertEqual(len(v.neighbors()), 3)                           # un coin n'a que 3 voisins
        self._faces_consistent()

    def test_destroy_exposes_neighbours(self):
        inner = self.m.get(5, 5, 5)
        self.assertEqual(inner.kind, VoxelKind.INTERIOR)
        self.assertFalse(inner.is_visible)
        n = len(self.m)
        for f in range(6):                                                # on creuse un tunnel autour de l'intérieur
            inner.neighbor(f).destroy()
        self.assertEqual(len(self.m), n - 6)
        self.assertTrue(inner.is_visible)
        self.assertEqual(inner.kind, VoxelKind.SURFACE)
        self._faces_consistent()

    def test_add_updates_faces(self):
        v = self.m.get(9, 9, 9); v.destroy(); self._faces_consistent()
        self.m.add(9, 9, 9, (1, 2, 3, 255)); self._faces_consistent()
        with self.assertRaises(ValueError):
            self.m.add(9, 9, 9, (1, 2, 3, 255))

    def test_json_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            p = JsonExporter().write(self.m, Path(d) / "m.voxels.json.gz")
            m2 = JsonImporter.read(p)
        self.assertEqual(len(m2), len(self.m))
        self.assertEqual(m2.voxel_size, self.m.voxel_size)
        for v in self.m:
            w = m2.get(*v.cell)
            self.assertIsNotNone(w)
            self.assertEqual((w.id, w.color, w.kind, w.faces), (v.id, v.color, v.kind, v.faces))

    def test_glb_has_one_node_per_voxel(self):
        """Relecture du .glb avec le chargeur glTF du projet : 1 voxel = 1 nœud = 12 triangles, bien placé."""
        small = run(_tris_to_scene(box_tris((0, 0, 0), (0.1, 0.1, 0.1)))).model            # 5x5x5
        with tempfile.TemporaryDirectory() as d:
            p = GlbExporter().write(small, Path(d) / "s.glb")
            scene = GltfLoader().load(p)
        self.assertEqual(len(scene.primitives), len(small))
        self.assertEqual(scene.triangle_count, 12 * len(small))
        centers = np.array([p_.positions.mean(0) for p_ in scene.primitives])
        expect = np.array([v.position for v in small])
        a = centers[np.lexsort(centers.T)]
        b = expect[np.lexsort(expect.T)]
        self.assertTrue(np.allclose(a, b, atol=1e-6))
        sizes = scene.primitives[0].positions.max(0) - scene.primitives[0].positions.min(0)
        self.assertTrue(np.allclose(sizes, VS))


class TestStyle(unittest.TestCase):
    def test_oklab_roundtrip(self):
        from voxelizer.style import oklab_to_rgb8, rgb8_to_oklab
        rgb = np.random.default_rng(0).integers(0, 256, (5000, 3)).astype(np.uint8)
        self.assertLessEqual(int(np.abs(oklab_to_rgb8(rgb8_to_oklab(rgb)).astype(int) - rgb).max()), 1)

    def test_oklab_palette_respects_size_and_keeps_rare_colors(self):
        from voxelizer.solid import FilledVoxels
        from voxelizer.style import OklabQuantizer
        rng = np.random.default_rng(1)
        rgb = np.concatenate([rng.normal([120, 80, 40], 6, (5000, 3)), rng.normal([60, 90, 140], 6, (4000, 3)),
                              np.tile([250, 240, 60], (30, 1))]).clip(0, 255).astype(np.uint8)       # 30 voxels jaunes « rares »
        f = FilledVoxels(np.arange(len(rgb), dtype=np.int64), np.zeros(len(rgb), np.uint8), rgb, np.full(len(rgb), 255, np.uint8))
        pal, idx = OklabQuantizer(6).quantize(f)
        self.assertLessEqual(len(pal), 6)
        self.assertTrue(((idx >= 0) & (idx < len(pal))).all())
        self.assertTrue(any(c[0] > 200 and c[1] > 200 and c[2] < 120 for c in pal), "la couleur rare doit survivre")

    def test_dominant_material_keeps_boundaries_crisp(self):
        """Deux matériaux (rouge | bleu) se touchent DANS une rangée de voxels : 'average' crée du violet, 'dominant' non."""
        def quad(x0, x1, rgb):
            t = [(x0, 0, 0.3), (x1, 0, 0.3), (x1, 0.2, 0.3), (x0, 0, 0.3), (x1, 0.2, 0.3), (x0, 0.2, 0.3)]
            p = MeshPrimitive(np.array(t, float), np.arange(6).reshape(2, 3), Material("m", (*rgb, 1.0)))
            return p
        sc = Scene3D([quad(0.0, 0.507, (1, 0, 0)), quad(0.507, 1.0, (0, 0, 1))])
        def purple(mode):
            m = run(sc, color_mode=mode, fill="shell").model
            return sum(1 for v in m if v.color[0] > 90 and v.color[2] > 90)
        self.assertGreater(purple("average"), 0)
        self.assertEqual(purple("dominant"), 0)

    def test_ao_levels(self):
        from voxelizer.ao import corner_levels
        m = VoxelModel(VS, [(1, 1, 1, 255)])
        for c in [(0, 0, 0), (1, 0, 0), (1, 1, 0)]:                  # sol de 2 voxels + 1 voxel posé : angle rentrant
            m.add(*c, (1, 1, 1, 255))
        keys = np.sort(np.array([int(pack(*v.cell)) for v in m]))
        k = np.array([int(pack(0, 0, 0))])
        lv = corner_levels(keys, k, 2)[0]                             # face +Y du voxel (0,0,0) ; corners (du,dv)
        self.assertEqual(int(lv[0]), 3)                               # côté dégagé
        self.assertEqual(int(lv[1]), 2)                               # côté du petit mur : occlus
        lone = np.array([int(pack(5, 5, 5))])
        self.assertTrue((corner_levels(lone, lone, 2) == 3).all())    # voxel isolé : tout dégagé


class TestRender(unittest.TestCase):
    def setUp(self):
        self.m = run(_tris_to_scene(box_tris((0, 0, 0), (0.3, 0.3, 0.3)), rgb=(0.8, 0.5, 0.3)), palette_size=8).model

    def test_renders_are_valid_and_deterministic(self):
        from voxelizer import PrettyRenderer
        r = PrettyRenderer(width=300)
        a, b = r.render(self.m), r.render(self.m)
        self.assertEqual(a.size, b.size)
        self.assertTrue(np.array_equal(np.asarray(a), np.asarray(b)))
        self.assertGreater(a.size[0], 100)
        self.assertGreater(np.asarray(a).std(), 5)                     # pas une image vide

    def test_shadows_darken_the_ground(self):
        from voxelizer import PrettyRenderer
        with_s = np.asarray(PrettyRenderer(width=300, shadows=True, supersample=1).render(self.m)).astype(float).sum()
        without = np.asarray(PrettyRenderer(width=300, shadows=False, supersample=1).render(self.m)).astype(float).sum()
        self.assertLess(with_s, without)

    def test_cutaway_and_views_do_not_crash(self):
        from voxelizer import PrettyRenderer
        r = PrettyRenderer(width=240, supersample=1)
        for az in (0, 90, 200, 300):
            self.assertGreater(r.render(self.m, azimuth=az).size[0], 50)
        self.assertGreater(r.render(self.m, cutaway=True).size[0], 50)


class TestRobustness(unittest.TestCase):
    def test_git_lfs_pointer_is_reported(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "Fake.gltf"
            p.write_text("version https://git-lfs.github.com/spec/v1\noid sha256:abc\nsize 5964\n")
            with self.assertRaises(LfsPointerError):
                load_scene(p)

    def test_unknown_format(self):
        with self.assertRaises(ValueError):
            load_scene("x.fbx")


if __name__ == "__main__":
    warnings.simplefilter("ignore")
    unittest.main(verbosity=2)
