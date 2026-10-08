"""Teste UNE pièce à plusieurs proportions d'entrée (échelle) et compare : voxels, temps, mémoire, rendu.
Chaque cas tourne dans un sous-processus -> mémoire de pointe mesurée par cas.

    python tools/scale_ladder.py village/OBJ Prop_Brick1 --scales 1 2 5 10 --out work/ladder
"""
import argparse
import json
import resource
import subprocess
import sys
import time
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def worker(path, scale, out, width):
    from voxelizer import PrettyRenderer, ScaleSpec, VoxelBudgetError, VoxelizationPipeline, VoxelizeConfig
    warnings.simplefilter("ignore")
    t0 = time.perf_counter()
    try:
        res = VoxelizationPipeline(VoxelizeConfig(scale=ScaleSpec(factor=scale))).run(path)
    except VoxelBudgetError as e:
        print(json.dumps({"status": "budget", "message": str(e), "ratio": e.ratio}))
        return
    m = res.model
    lo, hi = m.cell_bounds(); k = m.count_by_kind()
    png = ""
    if out:
        png = str(Path(out) / f"{Path(path).stem}_x{scale:g}.png")
        PrettyRenderer(width=width, supersample=1 if len(m) > 1_500_000 else 2).render(m).save(png)
    print(json.dumps({"status": "ok", "voxels": len(m), "surface": k["surface"], "interior": k["interior"],
                      "cells": [int(x) for x in hi - lo + 1], "size_m": [round(float(x), 3) for x in m.size_m()],
                      "seconds": round(time.perf_counter() - t0, 1), "stages": {a: round(b, 1) for a, b in res.report.timings.items()},
                      "rss_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024), "png": png,
                      "warnings": res.report.warnings}))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", nargs="?"); ap.add_argument("piece", nargs="?")
    ap.add_argument("--scales", type=float, nargs="+", default=[1, 2, 5, 10])
    ap.add_argument("--out", default="ladder"); ap.add_argument("--width", type=int, default=700)
    ap.add_argument("--worker", nargs=2, metavar=("PATH", "SCALE"))
    a = ap.parse_args()
    if a.worker:
        return worker(a.worker[0], float(a.worker[1]), a.out, a.width)
    Path(a.out).mkdir(parents=True, exist_ok=True)
    path = Path(a.folder) / f"{a.piece}.obj"
    print(f"\n### {a.piece}")
    print("| échelle | voxel équivalent | voxels | surface | boîte (cellules) | temps | RAM pointe |")
    print("|---|---|---|---|---|---|---|")
    results = []
    for s in a.scales:
        p = subprocess.run([sys.executable, "-W", "ignore", __file__, "--worker", str(path), str(s), "--out", a.out,
                            "--width", str(a.width)], capture_output=True, text=True)
        try:
            r = json.loads(p.stdout.strip().splitlines()[-1])
        except Exception:
            r = {"status": "crash", "message": (p.stderr or p.stdout)[-200:]}
        r["scale"] = s; results.append(r)
        eq = f"{2 / s:g} cm"
        if r["status"] == "ok":
            print(f"| x{s:g} | {eq} | {r['voxels']:,} | {r['surface']:,} | {'x'.join(map(str, r['cells']))} | {r['seconds']} s | {r['rss_mb']} Mo |", flush=True)
        else:
            print(f"| x{s:g} | {eq} | — {r['status']} : {r.get('message', '')[:110]} | | | | |", flush=True)
    json.dump(results, open(Path(a.out) / f"{a.piece}_ladder.json", "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
