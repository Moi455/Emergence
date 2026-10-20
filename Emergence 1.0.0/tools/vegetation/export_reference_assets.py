#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
export_reference_assets.py — jeu d'arbres de référence du laboratoire de style (tâche L04, docs/19b).

Génère les .vxm de référence HORS du dépôt (~/.local/share/emergence/lab_assets/trees/) et écrit leurs
empreintes dans reference_assets.txt (versionné). Le fichier .vxm change si zlib change d'implémentation ;
l'empreinte « contenu » (sha256 des tableaux décompressés) reste, elle, stable.

    python3 export_reference_assets.py            # génère et réécrit reference_assets.txt
    python3 export_reference_assets.py --check    # régénère en mémoire et compare à reference_assets.txt
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import read_vxm as rv          # noqa: E402
import voxel_bush as vb        # noqa: E402
import voxel_tree as vt        # noqa: E402

OUT_DIR = os.path.expanduser("~/.local/share/emergence/lab_assets/trees")
TABLE = os.path.join(HERE, "reference_assets.txt")
LODS = [0, 1, 2, 3, 4, 5]

# nom, kind, graine, essence, hauteur (m), saison, topiaire
ASSETS = [
    ("chene_42", "tree", 42, "chene", 14.0, "summer", None),
    ("epicea_7", "tree", 7, "epicea", 16.0, "summer", None),
    ("bouleau_3", "tree", 3, "bouleau", 10.0, "summer", None),
    ("peuplier_5", "tree", 5, "peuplier", 15.0, "summer", None),   # pas de saule dans voxel_tree.py
    ("buis_sphere_7", "bush", 7, "buis", 1.2, "summer", "sphere"),
    ("rosier_4", "bush", 4, "rosier", 1.2, "summer", None),
]


def build(kind, seed, species, height, season, topiary, path):
    if kind == "tree":
        regen = lambda v: vt.generate_tree(seed, species, height, season, 1.0, False, topiary=topiary, voxel=v)
        gen = "voxel_tree.py"
    else:
        regen = lambda v: vb.generate_bush(seed, species, height, season, 1.0, False, topiary, voxel=v)
        gen = "voxel_bush.py"
    by_lod = vt.build_lods(regen(vt.VOXEL), regen, LODS)
    vt.save_vxm(by_lod, path, export_sky=False, export_pal=True, generator=gen)


def content_sha(vxm: "rv.Vxm") -> str:
    h = hashlib.sha256()
    for s in vxm.lods:
        h.update(bytes([s.lod]))
        for a in (s.x, s.y, s.z, s.kind, s.ramp, s.pal):
            h.update(a.tobytes())
    return h.hexdigest()


def line_for(name, seed, species, height, season, topiary, path):
    with open(path, "rb") as f:
        raw = f.read()
    v = rv.parse_vxm(raw)
    return "\t".join([name, str(seed), species, f"{height:g}", season, topiary or "-", ",".join(str(s.lod) for s in v.lods),
                      str(v.lod(0).count), str(len(raw)), hashlib.sha256(raw).hexdigest(), content_sha(v)])


HEAD = ("# Arbres de référence du laboratoire (L04). Fichiers hors dépôt : ~/.local/share/emergence/lab_assets/trees/<nom>.vxm\n"
        "# Colonnes (tabulations) : nom, graine, essence, hauteur_m, saison, topiaire, lods, voxels_lod0, octets, sha256_fichier, sha256_contenu\n"
        "# sha256_contenu = tableaux décompressés (stable) ; sha256_fichier dépend aussi de zlib.\n")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="compare à reference_assets.txt sans rien écrire")
    a = ap.parse_args(argv)
    lines = []
    with tempfile.TemporaryDirectory() as tmp:
        for name, kind, seed, species, height, season, topiary in ASSETS:
            path = os.path.join(tmp if a.check else OUT_DIR, name + ".vxm")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            build(kind, seed, species, height, season, topiary, path)
            lines.append(line_for(name, seed, species, height, season, topiary, path))
            print(lines[-1].replace("\t", "  "))
    text = HEAD + "\n".join(lines) + "\n"
    if a.check:
        with open(TABLE, encoding="utf-8") as f:
            ok = f.read() == text
        print("IDENTIQUE à reference_assets.txt" if ok else "DIFFÉRENT de reference_assets.txt")
        return 0 if ok else 1
    with open(TABLE, "w", encoding="utf-8") as f:
        f.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
