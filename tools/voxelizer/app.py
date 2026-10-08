#!/usr/bin/env python3
"""Voxelizer : application locale.

    python app.py                 menu interactif dans le terminal
    python app.py web             interface web locale (s'ouvre dans le navigateur)
    python app.py web --folder ~/Emergence/OBJ --port 8765

Tout tourne sur votre machine (le serveur n'écoute que 127.0.0.1). Dépendances : numpy, scipy, Pillow.
"""
import argparse
import glob
import io
import json
import sys
import tempfile
import threading
import time
import traceback
import uuid
import warnings
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from voxelizer import (pack_model, GlbExporter, JsonExporter, LfsPointerError, PrettyRenderer, ScaleSpec, VoxelBudgetError,
                       VoxelizationPipeline, VoxelizeConfig, load_scene)
from voxelizer.scaling import ScaleController

EXTS = (".obj", ".gltf", ".glb")
LOOKS = {                                                  # directions artistiques prédéfinies
    "defaut": dict(sharpen=0.30, saturation=1.06, contrast=1.04, bake_ao=0.0),
    "fidele": dict(sharpen=0.0, saturation=1.0, contrast=1.0, bake_ao=0.0),
    "eclatant": dict(sharpen=0.45, saturation=1.16, contrast=1.08, bake_ao=0.25),
}


# ============================================================================ réglages -> configuration
def build_config(s: dict) -> VoxelizeConfig:
    look = dict(LOOKS.get(s.get("look", "defaut"), LOOKS["defaut"]))
    for k in ("sharpen", "saturation", "contrast", "bake_ao"):
        if s.get(k) not in (None, ""):
            look[k] = float(s[k])
    fit = {}
    if s.get("fit_axis") and s.get("fit_value") not in (None, ""):
        fit = {s["fit_axis"]: float(s["fit_value"])}
    spec = ScaleSpec(unit=s.get("unit", "m"), factor=float(s.get("factor") or 1),
                     fit_height=fit.get("height"), fit_width=fit.get("width"),
                     fit_depth=fit.get("depth"), fit_longest=fit.get("longest"))
    tex = tuple(t for t in [s.get("texture_dir", "")] if t)
    return VoxelizeConfig(
        voxel_size=float(s.get("voxel_cm") or 2) / 100.0, scale=spec, input_up=s.get("input_up", "y"),
        palette_size=int(s.get("palette", 32)), fill=s.get("fill", "solid"), seal_radius=int(s.get("seal") or 0),
        keep_glass=bool(s.get("keep_glass", False)), texture_dirs=tex,
        max_entities=int(s.get("max_entities") or 3_000_000), **look)


_SCENES: dict = {}


def get_scene(path: str, texdirs: tuple):
    key = (path, texdirs)
    if key not in _SCENES:
        if len(_SCENES) >= 2:
            _SCENES.pop(next(iter(_SCENES)))
        _SCENES[key] = load_scene(path, texdirs)
    return _SCENES[key]


def probe(s: dict) -> dict:
    """Prévision AVANT calcul : dimensions, boîte en cellules, avertissements, échelle maximale réaliste."""
    cfg = build_config(s)
    scene = get_scene(s["path"], cfg.texture_dirs)
    bmin, bmax = scene.bounds()
    raw = bmax - bmin
    if cfg.input_up == "z":
        raw = np.array([raw[0], raw[2], raw[1]])
    rep = ScaleController(cfg.scale).resolve(np.zeros(3), raw, cfg.voxel_size)
    cells = float(np.prod(rep.size_voxels + 2))
    return {"raw": raw.tolist(), "size_m": rep.size_m.tolist(), "cells": rep.size_voxels.tolist(),
            "box_cells": cells, "scale": rep.scale, "warnings": rep.warnings, "notes": scene.notes,
            "triangles": scene.triangle_count, "max_dense": cfg.max_dense_cells,
            "ratio_max": (cfg.max_dense_cells / cells) ** (1 / 3)}


# ============================================================================ tâches (web)
class Job:
    def __init__(self, settings: dict):
        self.id = uuid.uuid4().hex[:10]
        self.settings, self.status, self.log = settings, "queued", []
        self.model = self.summary = self.report = self.error = None
        self.ratio = None
        self.renders: dict = {}


JOBS: dict = {}
LOCK = threading.Lock()                                    # un seul calcul lourd à la fois (mémoire)


def run_job(job: Job) -> None:
    with LOCK:
        job.status = "running"
        try:
            cfg = build_config(job.settings)
            scene = get_scene(job.settings["path"], cfg.texture_dirs)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                res = VoxelizationPipeline(cfg, log=job.log.append).run_scene(scene, Path(job.settings["path"]).stem)
            job.model, job.summary, job.report = res.model, res.model.summary(), str(res.report)
            job.status = "done"
        except VoxelBudgetError as e:
            job.status, job.error, job.ratio = "error", str(e), e.ratio
        except LfsPointerError as e:
            job.status, job.error = "error", str(e)
        except Exception as e:
            job.status, job.error = "error", f"{type(e).__name__}: {e}"
            job.log.append(traceback.format_exc())


def render_png(job: Job, q: dict) -> bytes:
    key = tuple(sorted(q.items()))
    if key in job.renders:
        return job.renders[key]
    with LOCK:
        r = PrettyRenderer(width=int(q.get("w", 1000)), azimuth=float(q.get("az", 40)), elevation=float(q.get("el", 30)),
                           ao=q.get("ao", "1") == "1", shadows=q.get("sh", "1") == "1", ground=q.get("gr", "1") == "1",
                           supersample=1 if len(job.model) > 1_500_000 else 2)
        im = r.render(job.model, cutaway=q.get("cut", "0") == "1")
        buf = io.BytesIO()
        im.save(buf, "PNG")
    if len(job.renders) > 30:
        job.renders.pop(next(iter(job.renders)))
    job.renders[key] = buf.getvalue()
    return job.renders[key]


def export_bytes(job: Job, fmt: str):
    with tempfile.TemporaryDirectory() as d:
        name = job.model.name or "model"
        if fmt in ("vxp", "vxps"):
            return f"{name}.vxp", pack_model(job.model, shell_only=(fmt == "vxps"), compress="lzma")
        if fmt == "json":
            p = JsonExporter().write(job.model, Path(d) / f"{name}.voxels.json.gz")
        else:
            surface_only = fmt == "glbs"
            n = job.model.count_by_kind()["surface"] if surface_only else len(job.model)
            if n > 1_200_000:
                raise ValueError(f"GLB de {n:,} nœuds : trop lourd. Choisissez « surface seule » ou une échelle plus basse.")
            p = GlbExporter(include_interior=not surface_only).write(job.model, Path(d) / f"{name}.voxels.glb")
        return p.name, p.read_bytes()


def list_dir(d: str) -> dict:
    p = Path(d or ".").expanduser()
    if not p.is_dir():
        p = Path(".").resolve()
    p = p.resolve()
    dirs = sorted(x.name for x in p.iterdir() if x.is_dir() and not x.name.startswith("."))
    files = sorted((x for x in p.iterdir() if x.is_file() and x.suffix.lower() in EXTS), key=lambda x: x.name.lower())
    return {"dir": str(p), "parent": str(p.parent), "dirs": dirs,
            "files": [{"name": f.name, "kb": f.stat().st_size // 1024} for f in files]}


# ============================================================================ serveur HTTP
class Handler(BaseHTTPRequestHandler):
    default_dir = "."

    def log_message(self, *a):
        pass

    def _send(self, body: bytes, ctype="application/json", code=200, extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(json.dumps(obj).encode(), "application/json", code)

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        parts = [p for p in u.path.split("/") if p]
        try:
            if not parts:
                return self._send(INDEX_HTML.replace("__DIR__", json.dumps(self.default_dir)).encode(), "text/html; charset=utf-8")
            if parts[:2] == ["api", "files"]:
                return self._json(list_dir(q.get("dir", self.default_dir)))
            if parts[:2] == ["api", "job"]:
                j = JOBS.get(parts[2])
                if not j:
                    return self._json({"error": "tâche inconnue"}, 404)
                return self._json({"status": j.status, "log": j.log[-60:], "error": j.error, "ratio": j.ratio,
                                   "summary": j.summary, "report": j.report})
            if parts[:2] == ["api", "render"]:
                j = JOBS.get(parts[2])
                if not j or j.status != "done":
                    return self._json({"error": "pas de modèle"}, 404)
                return self._send(render_png(j, q), "image/png")
            if parts[:2] == ["api", "export"]:
                j = JOBS.get(parts[2])
                if not j or j.status != "done":
                    return self._json({"error": "pas de modèle"}, 404)
                name, data = export_bytes(j, q.get("fmt", "json"))
                return self._send(data, "application/octet-stream", extra={"Content-Disposition": f'attachment; filename="{name}"'})
            self._json({"error": "introuvable"}, 404)
        except Exception as e:
            self._json({"error": f"{type(e).__name__}: {e}"}, 400)

    def do_POST(self):
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            if self.path == "/api/probe":
                try:
                    return self._json(probe(body))
                except LfsPointerError as e:
                    return self._json({"error": str(e)}, 400)
            if self.path == "/api/voxelize":
                job = Job(body)
                JOBS[job.id] = job
                threading.Thread(target=run_job, args=(job,), daemon=True).start()
                return self._json({"id": job.id})
            self._json({"error": "introuvable"}, 404)
        except Exception as e:
            self._json({"error": f"{type(e).__name__}: {e}"}, 400)


def serve(folder: str, port: int, open_browser: bool):
    Handler.default_dir = str(Path(folder).expanduser().resolve())
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    srv.daemon_threads = True
    url = f"http://127.0.0.1:{port}/"
    print(f"Voxelizer web : {url}   (Ctrl+C pour arrêter)")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nArrêt.")


# ============================================================================ menu terminal
def _ask(prompt, default=None, choices=None):
    while True:
        suffix = f" [{default}]" if default not in (None, "") else ""
        try:
            v = input(f"{prompt}{suffix} : ").strip()
        except EOFError:
            raise SystemExit(0)
        v = v or (str(default) if default is not None else "")
        if v.lower() in ("q", "quitter", "exit"):
            raise SystemExit(0)
        if choices and v not in choices:
            print(f"   -> choix possibles : {', '.join(choices)}")
            continue
        return v


def _pick_files(folder: Path):
    while True:
        files = sorted(p for p in folder.glob("*") if p.suffix.lower() in EXTS)
        flt = _ask(f"\nDossier : {folder}  ({len(files)} modèles)\nFiltre sur le nom (Entrée = tout afficher, « .. » = dossier parent, ou un chemin)", "")
        if flt == "..":
            folder = folder.parent
            continue
        if flt and Path(flt).expanduser().exists():
            p = Path(flt).expanduser()
            if p.is_dir():
                folder = p
                continue
            return folder, [p]
        shown = [f for f in files if flt.lower() in f.stem.lower()]
        for i, f in enumerate(shown[:60], 1):
            print(f"  {i:3d}. {f.name}")
        if len(shown) > 60:
            print(f"  … {len(shown) - 60} autres (affinez le filtre)")
        if not shown:
            print("  (aucun modèle ne correspond)")
            continue
        sel = _ask("Numéro(s) à voxéliser (ex. 3  ou  1,4,7  ou  « tout »), Entrée pour refiltrer", "")
        if not sel:
            continue
        if sel == "tout":
            return folder, shown
        try:
            return folder, [shown[int(x) - 1] for x in sel.replace(" ", "").split(",")]
        except (ValueError, IndexError):
            print("   -> numéro invalide")


def terminal_app(folder: str):
    print("=" * 62 + "\n  VOXELIZER : modèle 3D texturé -> voxels de 2 cm, remplis\n" + "=" * 62)
    print("  (tapez q à tout moment pour quitter)")
    folder = Path(folder).expanduser().resolve()
    while True:
        folder, files = _pick_files(folder)
        s = {"look": _ask("\nStyle visuel : defaut / fidele / eclatant", "defaut", list(LOOKS))}
        mode = _ask("Échelle du modèle : 1 = telle quelle, 2 = facteur (ex. 10 pour des voxels 10x plus petits), "
                    "3 = unité du fichier (cm, mm...), 4 = imposer une taille", "1", ["1", "2", "3", "4"])
        if mode == "2":
            s["factor"] = _ask("  Facteur multiplicatif", "2")
        elif mode == "3":
            s["unit"] = _ask("  Unité du fichier", "cm", ["m", "dm", "cm", "mm", "inch", "ft"])
        elif mode == "4":
            s["fit_axis"] = _ask("  Quelle dimension", "height", ["height", "width", "depth", "longest"])
            s["fit_value"] = _ask("  Valeur finale en mètres", "1.0")
        s["palette"] = _ask("Nombre de couleurs de la palette (0 = couleurs exactes)", "32")
        s["fill"] = {"1": "solid", "2": "shell"}[_ask("Intérieur : 1 = plein, 2 = coque vide", "1", ["1", "2"])]
        out = Path(_ask("Dossier de sortie", "voxel_out")).expanduser()
        out.mkdir(parents=True, exist_ok=True)
        want_glb = _ask("Exporter aussi un .glb (1 nœud glTF par voxel) ? o/n", "n", ["o", "n"]) == "o"
        for f in files:
            print(f"\n=== {f.name}")
            try:
                cfg = build_config({**s, "path": str(f)})
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    res = VoxelizationPipeline(cfg, log=print).run(f)
                m = res.model
                print(res.report)
                print("  ->", m.summary())
                JsonExporter().write(m, out / f"{f.stem}.voxels.json.gz")
                vxp = pack_model(m, shell_only=True, compress="lzma")
                (out / f"{f.stem}.vxp").write_bytes(vxp)
                print(f"  vxp ultra-léger : {len(vxp):,} octets ({len(vxp) * 8 / len(m):.2f} bit/voxel)")
                r = PrettyRenderer(width=1200)
                r.render(m).save(out / f"{f.stem}.png")
                if m.count_by_kind()["interior"]:
                    r.render(m, cutaway=True).save(out / f"{f.stem}.coupe.png")
                if want_glb:
                    n = m.count_by_kind()["surface"]
                    GlbExporter(include_interior=False).write(m, out / f"{f.stem}.surface.glb")
                    print(f"  glb : surface seule ({n:,} nœuds)")
                print(f"  fichiers écrits dans {out.resolve()}")
            except VoxelBudgetError as e:
                print(f"  TROP GROS : {e}")
            except LfsPointerError as e:
                print(f"  ERREUR : {e}")
            except Exception as e:
                print(f"  ERREUR : {type(e).__name__}: {e}")
        if _ask("\nAutre modèle ? o/n", "o", ["o", "n"]) == "n":
            return


# ============================================================================ page web
INDEX_HTML = r"""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Voxelizer</title>
<style>
:root{--bg:#12141b;--p:#1a1d27;--p2:#222633;--line:#2c3142;--tx:#e8e9ee;--mut:#8f95aa;--ac:#e9a23b;--ac2:#f6c36b;--bad:#ff7a7a;--ok:#7fd99a}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--tx);font:14px/1.45 system-ui,Segoe UI,Roboto,sans-serif}
header{padding:14px 22px;border-bottom:1px solid var(--line);display:flex;align-items:baseline;gap:14px}
header h1{font-size:19px;margin:0;letter-spacing:.3px}header h1 b{color:var(--ac)}header span{color:var(--mut)}
main{display:grid;grid-template-columns:400px 1fr;gap:16px;padding:16px;align-items:start}
@media(max-width:980px){main{grid-template-columns:1fr}}
.card{background:var(--p);border:1px solid var(--line);border-radius:12px;padding:14px 16px;margin-bottom:14px}
.card h2{font-size:12px;text-transform:uppercase;letter-spacing:1.2px;color:var(--ac);margin:0 0 10px}
label{display:block;color:var(--mut);font-size:12px;margin:9px 0 3px}
input,select,button{font:inherit;color:var(--tx);background:var(--p2);border:1px solid var(--line);border-radius:8px;padding:7px 9px;width:100%}
input[type=range]{padding:0;accent-color:var(--ac)}input[type=checkbox]{width:auto;margin-right:6px}
.row{display:grid;grid-template-columns:1fr 1fr;gap:10px}.chk{display:flex;align-items:center;margin:8px 0;color:var(--tx)}
button{cursor:pointer;font-weight:600}button:hover{border-color:var(--ac)}
button.go{background:var(--ac);color:#1b1304;border:0;padding:11px;font-size:15px;margin-top:6px}button.go:disabled{opacity:.5;cursor:wait}
button.sm{width:auto;padding:5px 11px}.files{max-height:230px;overflow:auto;border:1px solid var(--line);border-radius:8px;background:var(--p2)}
.files div{padding:5px 10px;cursor:pointer;display:flex;justify-content:space-between;gap:8px;border-bottom:1px solid #00000033}
.files div:hover{background:#2c3142}.files div.sel{background:#3a2f17;color:var(--ac2)}.files .d{color:var(--ac2)}.files small{color:var(--mut)}
.mut{color:var(--mut);font-size:12px}pre{white-space:pre-wrap;margin:0;font:12px/1.4 ui-monospace,Consolas,monospace;color:#b8bed3;max-height:170px;overflow:auto}
.warn{color:var(--bad)}.okc{color:var(--ok)}
#stage{position:relative;background:#0d0f14;border-radius:10px;min-height:340px;display:flex;align-items:center;justify-content:center;overflow:hidden}
#view{max-width:100%;display:none}#ph{color:var(--mut);padding:80px 20px;text-align:center}
#spin{position:absolute;top:10px;right:12px;color:var(--ac2);display:none}
.ctl{display:grid;grid-template-columns:auto 1fr auto 1fr;gap:6px 14px;align-items:center;margin-top:12px}
.dl{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}.dl a{background:var(--p2);border:1px solid var(--line);border-radius:8px;padding:7px 12px;color:var(--tx);text-decoration:none}
.dl a:hover{border-color:var(--ac)}
</style></head><body>
<header><h1><b>VOXEL</b>IZER</h1><span>modèle 3D texturé &rarr; voxels pleins, 1 voxel = 1 entité</span></header>
<main>
<div>
 <div class="card"><h2>1 · Modèle</h2>
  <div class="mut" id="cwd"></div>
  <div class="row" style="margin:8px 0"><button class="sm" id="up">&uarr; dossier parent</button><input id="dirin" placeholder="chemin d'un dossier…"></div>
  <div class="files" id="files"></div>
  <div class="mut" id="chosen" style="margin-top:8px">Aucun modèle choisi.</div>
  <label>Dossier de textures (optionnel, sinon détecté automatiquement)</label><input id="texture_dir" placeholder="ex. ~/Emergence/Textures">
 </div>
 <div class="card"><h2>2 · Échelle</h2>
  <div class="row"><div><label>Unité du fichier</label><select id="unit"><option>m</option><option>dm</option><option>cm</option><option>mm</option><option>inch</option><option>ft</option></select></div>
  <div><label>Facteur (×10 = voxels 10× plus petits)</label><input id="factor" type="number" value="1" step="any" min="0.01"></div></div>
  <div class="row"><div><label>…ou imposer une taille</label><select id="fit_axis"><option value="">— non —</option><option value="height">hauteur</option><option value="width">largeur</option><option value="depth">profondeur</option><option value="longest">plus grande dim.</option></select></div>
  <div><label>valeur finale (m)</label><input id="fit_value" type="number" step="any" placeholder="ex. 3.0"></div></div>
  <div class="mut" id="probe" style="margin-top:10px">—</div>
 </div>
 <div class="card"><h2>3 · Style</h2>
  <div class="row"><div><label>Direction artistique</label><select id="look"><option value="defaut">Défaut (pixel art net)</option><option value="fidele">Fidèle (sans retouche)</option><option value="eclatant">Éclatant (relief + couleurs)</option></select></div>
  <div><label>Palette : <b id="palv">32</b> couleurs</label><input id="palette" type="range" min="0" max="128" value="32"></div></div>
  <div class="row"><div><label>Netteté <b id="shv"></b></label><input id="sharpen" type="range" min="0" max="1" step="0.05"></div>
  <div><label>Saturation <b id="sav"></b></label><input id="saturation" type="range" min="0.6" max="1.5" step="0.02"></div></div>
  <div class="row"><div><label>Contraste <b id="cov"></b></label><input id="contrast" type="range" min="0.8" max="1.3" step="0.02"></div>
  <div><label>AO cuite <b id="aov"></b></label><input id="bake_ao" type="range" min="0" max="0.8" step="0.05"></div></div>
 </div>
 <div class="card"><h2>4 · Avancé</h2>
  <div class="row"><div><label>Intérieur</label><select id="fill"><option value="solid">plein</option><option value="shell">coque vide</option></select></div>
  <div><label>Boucher les trous (rayon)</label><input id="seal" type="number" value="0" min="0" max="12"></div></div>
  <div class="row"><div><label>Axe haut du fichier</label><select id="input_up"><option value="y">Y (glTF, OBJ Blender)</option><option value="z">Z</option></select></div>
  <div><label>Taille du voxel (cm)</label><input id="voxel_cm" type="number" value="2" step="any" min="0.05"></div></div>
  <label>Budget d'entités (nb max de voxels)</label><input id="max_entities" type="number" value="3000000" step="100000">
  <div class="chk"><input type="checkbox" id="keep_glass"><span>Garder les vitres translucides</span></div>
 </div>
 <button class="go" id="go">Voxéliser</button>
</div>
<div>
 <div class="card"><h2>Aperçu</h2>
  <div id="stage"><div id="ph">Choisissez un modèle puis « Voxéliser ».</div><img id="view" alt=""><div id="spin">rendu…</div></div>
  <div class="ctl">
   <span class="mut">Rotation</span><input id="az" type="range" min="0" max="360" value="40"><span class="mut">Hauteur</span><input id="el" type="range" min="8" max="75" value="30">
  </div>
  <div class="row" style="margin-top:8px"><div class="chk"><input type="checkbox" id="ao" checked><span>Occlusion ambiante</span></div><div class="chk"><input type="checkbox" id="sh" checked><span>Ombres portées</span></div>
  <div class="chk"><input type="checkbox" id="gr" checked><span>Sol</span></div><div class="chk"><input type="checkbox" id="cut"><span>Coupe (intérieur plein)</span></div></div>
  <div class="row"><div><label>Résolution du rendu</label><select id="w"><option value="700">700 px</option><option value="1000" selected>1000 px</option><option value="1500">1500 px</option><option value="2200">2200 px</option></select></div>
  <div style="display:flex;align-items:end"><button id="play">▶ Tourner</button></div></div>
  <div class="dl" id="dl"></div>
 </div>
 <div class="card"><h2>Résultat</h2><div id="stats" class="mut">—</div><div id="err" class="warn"></div></div>
 <div class="card"><h2>Journal</h2><pre id="log">—</pre></div>
</div>
</main>
<script>
const $=s=>document.querySelector(s);
const LOOKS={defaut:{sharpen:.30,saturation:1.06,contrast:1.04,bake_ao:0},fidele:{sharpen:0,saturation:1,contrast:1,bake_ao:0},eclatant:{sharpen:.45,saturation:1.16,contrast:1.08,bake_ao:.25}};
const st={path:null,dir:__DIR__,job:null,playing:false,busy:false};
async function api(url,body){const r=await fetch(url,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:undefined);return r.json();}
function settings(){return {path:st.path,unit:$('#unit').value,factor:$('#factor').value,fit_axis:$('#fit_axis').value,fit_value:$('#fit_value').value,
 palette:$('#palette').value,look:$('#look').value,sharpen:$('#sharpen').value,saturation:$('#saturation').value,contrast:$('#contrast').value,bake_ao:$('#bake_ao').value,
 fill:$('#fill').value,seal:$('#seal').value,keep_glass:$('#keep_glass').checked,texture_dir:$('#texture_dir').value,voxel_cm:$('#voxel_cm').value,
 input_up:$('#input_up').value,max_entities:$('#max_entities').value};}
function syncSliders(){$('#palv').textContent=$('#palette').value==0?'exactes':$('#palette').value;
 for(const [k,id] of [['sharpen','shv'],['saturation','sav'],['contrast','cov'],['bake_ao','aov']])$('#'+id).textContent=(+$('#'+k).value).toFixed(2);}
function applyLook(){const l=LOOKS[$('#look').value];for(const k in l)$('#'+k).value=l[k];syncSliders();}
async function loadDir(d){const r=await api('/api/files?dir='+encodeURIComponent(d));st.dir=r.dir;$('#cwd').textContent=r.dir;$('#dirin').value=r.dir;
 const box=$('#files');box.innerHTML='';
 for(const x of r.dirs){const e=document.createElement('div');e.innerHTML='<span class="d">📁 '+x+'</span>';e.onclick=()=>loadDir(r.dir.replace(/[\\/]$/,'')+'/'+x);box.appendChild(e);}
 for(const f of r.files){const e=document.createElement('div');e.innerHTML='<span>'+f.name+'</span><small>'+f.kb+' Ko</small>';
  e.onclick=()=>{document.querySelectorAll('.files .sel').forEach(n=>n.classList.remove('sel'));e.classList.add('sel');st.path=r.dir.replace(/[\\/]$/,'')+'/'+f.name;$('#chosen').textContent='Choisi : '+f.name;doProbe();};box.appendChild(e);}
 if(!r.dirs.length&&!r.files.length)box.innerHTML='<div><small>(dossier vide)</small></div>';
 $('#up').onclick=()=>loadDir(r.parent);}
let pt=null;function doProbe(){clearTimeout(pt);pt=setTimeout(async()=>{if(!st.path)return;$('#probe').textContent='calcul…';const p=await api('/api/probe',settings());
 if(p.error){$('#probe').innerHTML='<span class="warn">'+p.error+'</span>';return;}
 const f=a=>a.map(x=>(+x).toFixed(2)).join(' × ');let h='Taille finale : <b>'+f(p.size_m)+' m</b><br>Boîte : '+p.cells.map(x=>Math.round(x)).join(' × ')+' cellules ('+(p.box_cells/1e6).toFixed(2)+' M)<br>'+p.triangles.toLocaleString()+' triangles';
 if(p.box_cells>p.max_dense)h+='<br><span class="warn">Trop grand pour le remplissage plein. Échelle max conseillée : ×'+p.ratio_max.toPrecision(2)+' de l\'échelle actuelle, ou « coque vide ».</span>';
 for(const w of p.warnings)h+='<br><span class="warn">⚠ '+w+'</span>';for(const n of p.notes)h+='<br><span class="warn">⚠ '+n+'</span>';$('#probe').innerHTML=h;},350);}
function setBusy(b){st.busy=b;$('#go').disabled=b;$('#go').textContent=b?'Calcul en cours…':'Voxéliser';}
async function run(){if(!st.path){alert('Choisissez d\'abord un modèle.');return;}setBusy(true);$('#err').textContent='';$('#log').textContent='';st.playing=false;$('#play').textContent='▶ Tourner';
 const r=await api('/api/voxelize',settings());if(r.error){setBusy(false);$('#err').textContent=r.error;return;}st.job=r.id;poll();}
async function poll(){const j=await api('/api/job/'+st.job);$('#log').textContent=j.log.join('\n')||'…';$('#log').scrollTop=1e9;
 if(j.status==='queued'||j.status==='running'){setTimeout(poll,600);return;}setBusy(false);
 if(j.status==='error'){$('#err').innerHTML=j.error+(j.ratio?'<br>Essayez une échelle ×'+j.ratio.toPrecision(2)+' de l\'actuelle.':'');return;}
 $('#stats').innerHTML='<span class="okc">✔ terminé</span><br>'+j.summary+'<pre style="margin-top:8px">'+j.report+'</pre>';
 $('#dl').innerHTML='<a href="/api/export/'+st.job+'?fmt=vxps">⬇ VXP ultra-léger (coque + compression)</a><a href="/api/export/'+st.job+'?fmt=vxp">⬇ VXP complet</a><a href="/api/export/'+st.job+'?fmt=json">⬇ JSON entités (.gz)</a><a href="/api/export/'+st.job+'?fmt=glbs">⬇ GLB surface seule</a><a href="/api/export/'+st.job+'?fmt=glb">⬇ GLB complet (1 nœud/voxel)</a>';
 refresh();}
let rt=null;function refresh(){clearTimeout(rt);rt=setTimeout(()=>{if(!st.job)return;$('#spin').style.display='block';
 const q=new URLSearchParams({az:$('#az').value,el:$('#el').value,cut:$('#cut').checked?1:0,ao:$('#ao').checked?1:0,sh:$('#sh').checked?1:0,gr:$('#gr').checked?1:0,w:$('#w').value});
 $('#view').src='/api/render/'+st.job+'?'+q;},180);}
$('#view').onload=()=>{$('#view').style.display='block';$('#ph').style.display='none';$('#spin').style.display='none';
 if(st.playing)setTimeout(()=>{if(!st.playing)return;$('#az').value=(+$('#az').value+14)%360;refresh();},30);};
$('#view').onerror=()=>{$('#spin').style.display='none';};
$('#play').onclick=()=>{st.playing=!st.playing;$('#play').textContent=st.playing?'⏸ Pause':'▶ Tourner';if(st.playing)refresh();};
$('#look').onchange=()=>{applyLook();doProbe();};
for(const id of ['palette','sharpen','saturation','contrast','bake_ao'])$('#'+id).oninput=syncSliders;
for(const id of ['unit','factor','fit_axis','fit_value','input_up','voxel_cm','texture_dir'])$('#'+id).oninput=doProbe;
for(const id of ['az','el','cut','ao','sh','gr','w'])$('#'+id).oninput=refresh;
$('#dirin').onchange=()=>loadDir($('#dirin').value);$('#go').onclick=run;applyLook();loadDir(st.dir);
</script></body></html>
"""


def main():
    ap = argparse.ArgumentParser(description="Voxelizer : application locale (terminal ou web).")
    sub = ap.add_subparsers(dest="mode")
    w = sub.add_parser("web", help="interface web locale")
    w.add_argument("--folder", default=".", help="dossier de modèles affiché au démarrage")
    w.add_argument("--port", type=int, default=8765)
    w.add_argument("--no-browser", action="store_true")
    t = sub.add_parser("terminal", help="menu interactif (défaut)")
    t.add_argument("--folder", default=".")
    a = ap.parse_args()
    if a.mode == "web":
        serve(a.folder, a.port, not a.no_browser)
    else:
        terminal_app(getattr(a, "folder", "."))


if __name__ == "__main__":
    main()
