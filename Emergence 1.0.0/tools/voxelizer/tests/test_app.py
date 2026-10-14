"""Tests de l'application : serveur HTTP réel (thread local) + menu terminal avec réponses simulées."""
import json
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tools"))
import app  # noqa: E402

TESTDATA = ROOT / "testdata"


class TestWeb(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (TESTDATA / "Wall_Window.gltf").exists():
            import make_test_assets
            make_test_assets.main(str(TESTDATA))
        app.Handler.default_dir = str(TESTDATA)
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        cls.srv.daemon_threads = True
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def call(self, path, body=None, raw=False):
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                data = r.read()
                return (r.status, data, r.headers) if raw else json.loads(data)
        except urllib.error.HTTPError as e:
            data = e.read()
            return (e.code, data, e.headers) if raw else json.loads(data)

    def run_job(self, **extra):
        job = self.call("/api/voxelize", {"path": str(TESTDATA / "Wall_Window.gltf"), "palette": 16, **extra})["id"]
        for _ in range(240):
            j = self.call("/api/job/" + job)
            if j["status"] in ("done", "error"):
                return job, j
            time.sleep(0.5)
        self.fail("tâche trop longue")

    def test_page_and_listing(self):
        code, body, _ = self.call("/", raw=True)
        self.assertEqual(code, 200)
        self.assertIn(b"VOXEL", body)
        self.assertNotIn(b"__DIR__", body)                       # le dossier de départ est bien injecté
        names = [f["name"] for f in self.call("/api/files")["files"]]
        self.assertIn("Wall_Window.gltf", names)

    def test_probe_predicts_size_and_budget(self):
        s = {"path": str(TESTDATA / "Wall_Window.gltf")}
        p = self.call("/api/probe", s)
        self.assertAlmostEqual(p["size_m"][0], 2.0, places=3)
        self.assertLess(p["box_cells"], p["max_dense"])
        big = self.call("/api/probe", {**s, "factor": 20})          # 20x -> boîte énorme, signalée avant calcul
        self.assertGreater(big["box_cells"], big["max_dense"])
        self.assertLess(big["ratio_max"], 1.0)
        fit = self.call("/api/probe", {**s, "fit_axis": "height", "fit_value": 1.0})
        self.assertAlmostEqual(fit["size_m"][1], 1.0, places=3)

    def test_full_flow_render_and_exports(self):
        job, j = self.run_job()
        self.assertEqual(j["status"], "done", j.get("error"))
        self.assertIn("84,000 voxels", j["summary"])
        code, png, hd = self.call(f"/api/render/{job}?az=40&el=30&w=500", raw=True)
        self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n")
        code, png2, _ = self.call(f"/api/render/{job}?az=130&el=30&w=500&cut=1", raw=True)
        self.assertNotEqual(png, png2)                          # une autre vue donne une autre image
        code, js, hd = self.call(f"/api/export/{job}?fmt=json", raw=True)
        self.assertEqual(js[:2], b"\x1f\x8b")                    # gzip
        self.assertIn(".voxels.json.gz", hd["Content-Disposition"])
        code, glb, _ = self.call(f"/api/export/{job}?fmt=glbs", raw=True)
        self.assertEqual(glb[:4], b"glTF")
        from voxelizer import VoxelPack
        code, vxp, _ = self.call(f"/api/export/{job}?fmt=vxps", raw=True)
        self.assertEqual(vxp[:4], b"VXP1")
        self.assertEqual(len(VoxelPack(vxp).arrays(fill=True)[0]), 84_000)       # sans perte, nombre de voxels identique

    def test_budget_error_is_reported_with_advice(self):
        _, j = self.run_job(max_entities=50_000)
        self.assertEqual(j["status"], "error")
        self.assertIn("Échelle maximale", j["error"])
        self.assertIsNotNone(j["ratio"])

    def test_bad_path_does_not_crash_server(self):
        r = self.call("/api/probe", {"path": "/nope/absent.obj"})
        self.assertIn("error", r)
        self.assertEqual(self.call("/api/files")["dir"], str(TESTDATA.resolve()))


class TestTerminal(unittest.TestCase):
    def test_scripted_session_writes_files(self):
        with tempfile.TemporaryDirectory() as out:
            answers = ["Wall_Window", "1", "", "1", "16", "1", out, "n", "n"]
            with mock.patch("builtins.input", side_effect=answers), mock.patch("builtins.print"):
                app.terminal_app(str(TESTDATA))
            files = sorted(p.name for p in Path(out).iterdir())
        self.assertEqual(files, ["Wall_Window.coupe.png", "Wall_Window.png", "Wall_Window.voxels.json.gz", "Wall_Window.vxp"])

    def test_quit(self):
        with mock.patch("builtins.input", side_effect=["q"]), mock.patch("builtins.print"):
            with self.assertRaises(SystemExit):
                app.terminal_app(str(TESTDATA))


if __name__ == "__main__":
    unittest.main(verbosity=2)
