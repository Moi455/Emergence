"""Ligne de commande : python -m voxelizer MODELE.gltf -o sortie/ [options]"""
import argparse
import sys
import warnings
from pathlib import Path

from . import (pack_model, GlbExporter, IsoRenderer, PrettyRenderer, JsonExporter, ScaleSpec, VoxelizationPipeline, VoxelizeConfig,
               LfsPointerError, VoxelBudgetError)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="voxelizer", description="Modèle 3D texturé -> voxels de 2 cm (1 voxel = 1 entité).")
    ap.add_argument("input", nargs="+", help="fichier(s) .gltf / .glb / .obj")
    ap.add_argument("-o", "--out", default="out", help="dossier de sortie")
    g = ap.add_argument_group("échelle (le moteur travaille en mètres réels)")
    g.add_argument("--unit", default="m", help="unité du fichier : m, dm, cm, mm, inch, ft (défaut m)")
    g.add_argument("--scale", type=float, default=1.0, help="facteur correctif (ex. 0.5 = moitié moins grand)")
    g.add_argument("--fit-height", type=float, metavar="M", help="impose la hauteur finale (axe Y) en mètres")
    g.add_argument("--fit-width", type=float, metavar="M", help="impose la largeur finale (axe X) en mètres")
    g.add_argument("--fit-depth", type=float, metavar="M", help="impose la profondeur finale (axe Z) en mètres")
    g.add_argument("--fit-longest", type=float, metavar="M", help="impose la plus grande dimension en mètres")
    ap.add_argument("--texture-dir", action="append", default=[], metavar="DIR", help="dossier de textures (répétable)")
    ap.add_argument("--max-entities", type=int, default=3_000_000, help="budget d'objets Voxel (défaut 3 000 000)")
    ap.add_argument("--voxel-size", type=float, default=0.02, help="côté du voxel en mètres (défaut 0.02 = 2 cm)")
    ap.add_argument("--input-up", choices=["y", "z"], default="y", help="axe haut du fichier d'entrée")
    ap.add_argument("--pivot", choices=["keep", "min", "center-bottom"], default="keep")
    ap.add_argument("--palette", type=int, default=32, help="taille de palette pixel art (0 = vraies couleurs)")
    s = ap.add_argument_group("direction artistique")
    s.add_argument("--palette-method", choices=["oklab", "mediancut"], default="oklab")
    s.add_argument("--color-mode", choices=["dominant", "average"], default="dominant")
    s.add_argument("--sharpen", type=float, default=0.30); s.add_argument("--saturation", type=float, default=1.06)
    s.add_argument("--contrast", type=float, default=1.04); s.add_argument("--bake-ao", type=float, default=0.0)
    s.add_argument("--legacy-preview", action="store_true", help="ancien rendu à ombrage plat")
    ap.add_argument("--shell", action="store_true", help="ne pas remplir l'intérieur")
    ap.add_argument("--seal", type=int, default=0, metavar="R", help="comble les trous jusqu'à ~2R voxels (modèles ouverts)")
    ap.add_argument("--keep-glass", action="store_true", help="garder les voxels translucides (vitres)")
    ap.add_argument("--glb", action="store_true", help="exporte aussi un .glb (1 nœud glTF par voxel)")
    ap.add_argument("--glb-surface-only", action="store_true", help="GLB sans les voxels intérieurs (plus léger)")
    ap.add_argument("--vxp", action="store_true", help="écrit un .vxp ultra-léger (coque seule + compression par blocs)")
    ap.add_argument("--no-json", action="store_true")
    ap.add_argument("--no-preview", action="store_true")
    a = ap.parse_args(argv)

    cfg = VoxelizeConfig(
        voxel_size=a.voxel_size, input_up=a.input_up, pivot=a.pivot, palette_size=a.palette,
        palette_method=a.palette_method, color_mode=a.color_mode, sharpen=a.sharpen, saturation=a.saturation,
        contrast=a.contrast, bake_ao=a.bake_ao,
        fill="shell" if a.shell else "solid", seal_radius=a.seal, keep_glass=a.keep_glass,
        texture_dirs=tuple(a.texture_dir), max_entities=a.max_entities,
        scale=ScaleSpec(unit=a.unit, factor=a.scale, fit_height=a.fit_height, fit_width=a.fit_width,
                        fit_depth=a.fit_depth, fit_longest=a.fit_longest))
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    rc = 0
    for src in a.input:
        print(f"\n=== {src}")
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("always")
                res = VoxelizationPipeline(cfg, log=print).run(src)
        except LfsPointerError as e:
            print(f"ERREUR : {e}", file=sys.stderr); rc = 2; continue
        except VoxelBudgetError as e:
            print(f"TROP GROS : {e}", file=sys.stderr); rc = 3; continue
        m, stem = res.model, Path(src).stem
        print(res.report)
        print("  ->", m.summary())
        if not a.no_json:
            JsonExporter().write(m, out / f"{stem}.voxels.json.gz")
        if a.vxp:
            data = pack_model(m, shell_only=True, compress="lzma")
            (out / f"{stem}.vxp").write_bytes(data)
            print(f"  vxp : {len(data):,} octets = {len(data) * 8 / len(m):.2f} bit/voxel")
        if a.glb:
            n_nodes = len(m) if not a.glb_surface_only else m.count_by_kind()['surface']
            if n_nodes > 200_000:
                print(f"  /!\\ GLB de {n_nodes:,} nœuds (~{n_nodes * 130 / 1e6:.0f} Mo de JSON) : pensez à --glb-surface-only.")
            GlbExporter(include_interior=not a.glb_surface_only).write(m, out / f"{stem}.voxels.glb")
        if not a.no_preview:
            if a.legacy_preview:
                r = IsoRenderer(); r.render(m, 0).save(out / f"{stem}.iso.png")
                if m.count_by_kind()["interior"]:
                    r.render(m, 0, interior_cutaway=True).save(out / f"{stem}.cutaway.png")
            else:
                r = PrettyRenderer(); r.render(m).save(out / f"{stem}.iso.png")
                if m.count_by_kind()["interior"]:
                    r.render(m, cutaway=True).save(out / f"{stem}.cutaway.png")
    return rc
