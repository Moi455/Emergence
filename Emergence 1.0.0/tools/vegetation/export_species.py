#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
export_species.py : exporte les essences de voxel_tree.py et voxel_bush.py vers engine/data/species.toml (L30).

Les 7 arbres et les 9 arbustes du Python sont exportés TELS QUELS (aucune valeur retouchée), dans cet ordre ;
suivent les essences ajoutées par-dessus pour les recettes du registre (pommier, aubépine), dans le même style.
L'ordre fixe la CASE d'essence (5 bits de teinte) : on n'insère jamais, on ajoute à la fin.

    python3 export_species.py            # réécrit engine/data/species.toml
    python3 export_species.py --check    # compare sans écrire
"""
import dataclasses
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import voxel_bush as vb   # noqa: E402
import voxel_tree as vt   # noqa: E402
from voxel_tree import Species  # noqa: E402

OUT = os.path.join(HERE, "..", "..", "engine", "data", "species.toml")


def extras():
    """Essences ajoutées au-dessus du Python (même moteur, mêmes champs)."""
    pommier = Species(
        key="pommier", nom="Pommier", h_range=(4.0, 7.0), arch="decurrent",
        trunk_frac=(0.35, 0.48), bole=(0.20, 0.30), trunk_k=0.024, taper=0.06,
        crown_r=0.50, crown_shape="dome", stubs=0.6, max_order=4,
        density=(1.6, 1.6, 2.2, 2.4, 0.0), angle=(0, 55, 50, 46, 44),
        len_ratio=(0, 1.0, 0.62, 0.55, 0.50),
        wobble=(0.06, 0.22, 0.30, 0.34, 0.38), tropism=(0.02, 0.06, 0.04, 0.0, 0.0),
        crowd=(99, 99, 16, 14, 12),
        leaf_min_order=3, leaf_start=0.35, leaf_r=(0, 0, 0, 0.20, 0.17), leaf_dens=0.50,
        leaf_spacing=1.0, leaf_flat=0.75, leaf_big=0.30, spring_leaf=0.5, bark_rough=0.5,
        bark=((46, 38, 32), (88, 76, 66), (130, 116, 100)),
        bark_alt=((52, 62, 40), (92, 108, 62), (132, 148, 90)),
        leaves=(((24, 62, 22), (66, 118, 34), (140, 178, 60)),
                ((30, 72, 24), (82, 132, 36), (156, 190, 66)),
                ((18, 52, 22), (48, 98, 32), (108, 150, 54))),
        autumn=(((90, 44, 12), (180, 112, 28), (226, 170, 56)),
                ((100, 60, 14), (190, 140, 30), (232, 196, 70)),
                ((60, 60, 18), (120, 110, 32), (176, 156, 54))),
        flower_seasons=("spring",), flower_frac=0.75, flower_r=0.075, flower_off=0.04, flower_fill=1.8, flower_tip=0.2,
        flower_mix=True,
        flower_ramps=(((190, 150, 160), (250, 226, 232), (255, 250, 250)),
                      ((200, 110, 130), (246, 176, 196), (255, 226, 234))),
        fruit_seasons=("autumn",), fruit_frac=0.28, fruit_r=0.04, fruit_off=-0.02, fruit_fill=2.4, fruit_tip=0.3,
        fruit_mix=True,
        fruit_ramps=(((110, 14, 12), (196, 36, 28), (236, 96, 70)),
                     ((96, 110, 16), (160, 176, 36), (214, 220, 90))),
    )
    aubepine = vb._sp(
        key="aubepine", nom="Aubépine", h_range=(1.4, 2.0),
        multistem=(6, 11), stem_lean=(6.0, 20.0), stem_len=(0.9, 1.0), bole=(0.0, 0.06),
        trunk_k=0.014, crown_r=0.36, crown_shape="dome", max_order=3, bark_rough=0.3,
        density=(6, 7, 8, 0, 0), angle=(0, 48, 44, 40, 38), len_ratio=(0, 1.0, 0.55, 0.50, 0.50),
        wobble=(0.10, 0.24, 0.30, 0.34, 0.34), tropism=(0.06, 0.03, 0.0, 0.0, 0.0), min_dz=-0.25,
        crowd=(99, 99, 34, 30, 26), spring_leaf=0.45,
        leaf_min_order=2, leaf_start=0.12, leaf_r=(0, 0, 0.11, 0.09, 0.08), leaf_dens=0.55,
        leaf_spacing=0.9, leaf_stretch=1.2, leaf_flat=0.75, leaf_droop=0.05, leaf_big=0.30,
        bark=((54, 42, 34), (100, 84, 70), (146, 126, 104)),
        twig=((60, 44, 34), (104, 80, 60), (146, 116, 88)),
        leaves=(((18, 56, 22), (46, 108, 36), (110, 160, 62)),
                ((24, 64, 24), (60, 122, 38), (126, 172, 68)),
                ((14, 46, 22), (36, 88, 32), (92, 138, 54))),
        autumn=(((90, 50, 14), (160, 100, 30), (206, 150, 60)),
                ((80, 56, 16), (150, 116, 34), (200, 168, 64)),
                ((60, 60, 20), (116, 112, 40), (166, 160, 74))),
        flower_seasons=("spring",), flower_frac=0.8, flower_r=0.05, flower_off=0.03, flower_fill=1.8,
        flower_ramps=(((200, 190, 180), (248, 242, 236), (255, 255, 252)),),
        fruit_seasons=("autumn", "winter"), fruit_frac=0.5, fruit_r=0.03, fruit_off=0.04, fruit_fill=2.2, fruit_tip=0.3,
        fruit_ramps=(((100, 10, 14), (186, 24, 32), (236, 84, 76)),),
    )
    def cult(key, nom, leaves, autumn=None, bark=None, fruit=(), flower=()):
        """Pseudo-essence de culture (blé, chou, vigne, champignon, fougère) : porte seulement des rampes de couleur,
        la croissance n'est pas utilisée (les cultures sont des motifs de 2 cm, voir crops.rs)."""
        return Species(key=key, nom=nom, h_range=(0.1, 1.2), evergreen=True, roots=False, leaves=leaves,
                       autumn=autumn or leaves,
                       bark=bark or ((60, 50, 30), (120, 100, 60), (170, 150, 100)),
                       fruit_ramps=fruit, fruit_seasons=("summer",) if fruit else (),
                       flower_ramps=flower, flower_seasons=("summer",) if flower else ())
    ble = cult("ble", "Blé", (((70, 70, 20), (150, 140, 40), (212, 196, 80)), ((90, 80, 24), (170, 150, 50), (226, 206, 96))),
               fruit=(((120, 84, 20), (206, 160, 48), (244, 214, 110)), ((140, 100, 26), (222, 176, 60), (250, 226, 126))))
    chou = cult("chou", "Chou", (((24, 64, 40), (70, 128, 84), (140, 184, 140)), ((30, 70, 50), (84, 140, 96), (160, 200, 150))),
                fruit=(((120, 160, 110), (176, 206, 150), (222, 236, 196)), ((60, 24, 70), (120, 60, 130), (176, 120, 180))))
    vigne = cult("vigne", "Vigne", (((30, 70, 20), (70, 120, 30), (150, 184, 60)), ((44, 80, 20), (100, 140, 36), (176, 196, 70))),
                 autumn=(((120, 40, 20), (190, 80, 30), (230, 150, 50)), ((130, 90, 20), (206, 160, 40), (240, 210, 90))),
                 bark=((40, 30, 24), (84, 64, 48), (130, 104, 80)),
                 fruit=(((24, 10, 48), (70, 30, 100), (130, 90, 160)), ((70, 90, 30), (130, 160, 56), (196, 210, 110))))
    champignon = cult("champignon", "Champignon", (((70, 60, 40), (120, 100, 70), (170, 150, 110)),),
                      bark=((150, 140, 120), (214, 204, 184), (244, 236, 220)),
                      fruit=(((70, 36, 16), (130, 76, 36), (180, 120, 64)), ((120, 10, 10), (196, 24, 20), (236, 70, 50))),
                      flower=(((200, 196, 186), (240, 236, 226), (255, 255, 250)),))
    fougere = cult("fougere", "Fougère", (((20, 56, 24), (50, 112, 44), (110, 170, 80)), ((26, 64, 26), (64, 128, 50), (130, 184, 92)),
                                           ((16, 44, 22), (40, 92, 36), (96, 148, 70))),
                   autumn=(((90, 60, 20), (150, 100, 36), (200, 150, 70)),))
    return {"pommier": pommier, "aubepine": aubepine, "ble": ble, "chou": chou, "vigne": vigne,
            "champignon": champignon, "fougere": fougere}


# Réglage des silhouettes lointaines (enveloppe, densité des disques), mesuré au niveau 3 par l'exemple sil_tune
SILHOUETTE = {"chene": (0.70, 1.0), "hetre": (0.80, 1.0), "bouleau": (0.80, 0.6), "epicea": (1.10, 2.5),
              "peuplier": (0.70, 0.6), "pin": (0.70, 1.5), "erable": (0.80, 1.0)}


def fmt(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return repr(v)
    if isinstance(v, str):
        return '"' + v.replace('"', '\\"') + '"'
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(fmt(x) for x in v) + "]"
    raise TypeError(type(v))


def ramp_list(rs):
    return "[" + ", ".join(fmt([list(c) for c in r]) for r in rs) + "]"


def dump(sp: Species, source: str) -> str:
    d = dataclasses.asdict(sp)
    env, dens = SILHOUETTE.get(sp.key, (0.80, 1.5))
    L = ["[[species]]", f'source = "{source}"', f"sil_env = {env}", f"sil_dens = {dens}"]
    skip = {"flower_ramps", "fruit_ramps", "bark", "bark_alt", "twig", "leaves", "autumn"}
    for k, v in d.items():
        if k in skip or k.startswith("flower_") or k.startswith("fruit_"):
            continue
        L.append(f"{k} = {fmt(v)}")
    for role in ("flower", "fruit"):
        L.append(f"[species.{role}]")
        for k in ("seasons", "frac", "r", "stretch", "off", "fill", "tip", "mix"):
            L.append(f"{k} = {fmt(d[f'{role}_{k}'])}")
        L.append(f"ramps = {ramp_list(d[f'{role}_ramps'])}")
    L.append("[species.colors]")
    L.append(f"bark = {fmt([list(c) for c in d['bark']])}")
    L.append(f"bark_alt = {fmt([list(c) for c in d['bark_alt']])}")
    L.append(f"twig = {fmt([list(c) for c in d['twig']])}")
    L.append(f"leaves = {ramp_list(d['leaves'])}")
    L.append(f"autumn = {ramp_list(d['autumn'])}")
    return "\n".join(L) + "\n"


def build() -> str:
    head = ("# Essences de végétation (L30-L32), exportées de tools/vegetation/voxel_tree.py et voxel_bush.py par\n"
            "# tools/vegetation/export_species.py (ne pas éditer à la main : relancer le script). Longueurs en mètres,\n"
            "# angles en degrés, rapports sans unité ; le port Rust les convertit en Q16. L'ORDRE fixe la case d'essence\n"
            "# (5 bits de teinte, 32 au plus) : on ajoute à la fin, on ne renumérote jamais.\n\n")
    parts = []
    for k, sp in vt.SPECIES.items():
        parts.append(dump(sp, "voxel_tree.py"))
    for k, sp in vb.BUSHES.items():
        parts.append(dump(sp, "voxel_bush.py"))
    for k, sp in extras().items():
        parts.append(dump(sp, "ajout"))
    return head + "\n".join(parts)


if __name__ == "__main__":
    text = build()
    if "--check" in sys.argv:
        with open(OUT, encoding="utf-8") as f:
            ok = f.read() == text
        print("IDENTIQUE" if ok else "DIFFÉRENT")
        sys.exit(0 if ok else 1)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(text)
    print("écrit", os.path.normpath(OUT), len(vt.SPECIES) + len(vb.BUSHES) + len(extras()), "essences")
