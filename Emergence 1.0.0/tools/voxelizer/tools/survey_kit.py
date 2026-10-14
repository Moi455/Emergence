"""Inventaire : voxélise TOUTES les pièces d'un dossier à une échelle donnée et consigne les métriques (CSV).

    python tools/survey_kit.py village/OBJ --scale 1 --out survey_x1.csv
"""
import argparse
import csv
import sys
import time
import warnings
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from voxelizer import ScaleSpec, VoxelBudgetError, VoxelizationPipeline, VoxelizeConfig, load_scene


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("folder"); ap.add_argument("--scale", type=float, default=1.0)
    ap.add_argument("--out", default="survey.csv"); ap.add_argument("--only", default="", help="sous-chaîne de nom")
    ap.add_argument("--max-entities", type=int, default=3_000_000)
    ap.add_argument("--skip-over-cells", type=float, default=0, help="ignore (en le consignant) les pièces dont la boîte dépasse N cellules")
    a = ap.parse_args(argv)
    files = sorted(p for p in Path(a.folder).glob("*.obj") if a.only in p.stem)
    cols = ["piece", "scale", "mesh_x_m", "mesh_y_m", "mesh_z_m", "triangles", "cells_x", "cells_y", "cells_z",
            "voxels", "surface", "interior", "seconds", "status", "note"]
    out = Path(a.out)
    done = {}
    if out.exists():                                                   # reprise : on ne refait pas ce qui est fait
        done = {r["piece"]: r for r in csv.DictReader(open(out))}
    fh = open(out, "a", newline="")
    wr = csv.DictWriter(fh, cols)
    if not done:
        wr.writeheader()
    rows, t_all = [], time.perf_counter()
    for i, f in enumerate(files, 1):
        if f.stem in done:
            continue
        scene = load_scene(f)
        mn, mx = scene.bounds(); size = (mx - mn) * a.scale
        row = dict(piece=f.stem, scale=a.scale, mesh_x_m=round(size[0], 3), mesh_y_m=round(size[1], 3),
                   mesh_z_m=round(size[2], 3), triangles=scene.triangle_count)
        t0 = time.perf_counter(); status = "ok"; note = ""
        box = float(np.prod(size / 0.02))
        if a.skip_over_cells and box > a.skip_over_cells:
            row.update(seconds=0, status="ignoré (boîte trop grande pour le crible)", note=f"{box / 1e6:.0f} M cellules")
            rows.append(row); wr.writerow({c: row.get(c, "") for c in cols}); fh.flush()
            print(f"[{i:3d}/{len(files)}] {f.stem:34s} ignoré : {box / 1e6:.0f} M cellules", flush=True); continue
        for fill in ("solid", "shell"):
            cfg = VoxelizeConfig(scale=ScaleSpec(factor=a.scale), fill=fill, max_entities=a.max_entities)
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    res = VoxelizationPipeline(cfg).run_scene(scene, f.stem)
                m = res.model
                lo, hi = m.cell_bounds(); k = m.count_by_kind()
                row.update(cells_x=int(hi[0]-lo[0]+1), cells_y=int(hi[1]-lo[1]+1), cells_z=int(hi[2]-lo[2]+1),
                           voxels=len(m), surface=k["surface"], interior=k["interior"])
                if fill == "shell":
                    status = "coque (grille dense trop grande)"
                elif k["interior"] == 0:
                    status = "ouvert (coque)"
                break
            except VoxelBudgetError as e:
                if fill == "solid" and "Boîte" in str(e) or (fill == "solid" and "Grille" in str(e)):
                    continue                                              # on retente en coque
                status, note = "TROP GROS", str(e)[:90]; break
            except Exception as e:                                         # robustesse : on consigne, on continue
                status, note = "ERREUR", f"{type(e).__name__}: {e}"[:90]; break
        row.update(seconds=round(time.perf_counter() - t0, 1), status=status, note=note)
        rows.append(row); wr.writerow({c: row.get(c, "") for c in cols}); fh.flush()
        print(f"[{i:3d}/{len(files)}] {f.stem:34s} {row.get('voxels', 0):>9,} vox  {row['seconds']:6.1f}s  {status} {note}", flush=True)
    print(f"FIN en {time.perf_counter() - t_all:.0f}s -> {a.out}", flush=True)


if __name__ == "__main__":
    main()
