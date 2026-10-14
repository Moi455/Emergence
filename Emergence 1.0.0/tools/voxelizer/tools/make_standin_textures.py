"""Textures de SUBSTITUTION pour le kit Emergence (les vrais PNG sont en Git LFS, absents du zip OBJ).

Génère dans <dossier>/ les 9 fichiers que les MTL référencent (T_Brick_BaseColor.png, ...) avec des motifs
PROCÉDURAUX. Ce ne sont PAS les textures d'origine : couleurs et échelle de motif sont inventées. Pour de
vrais résultats, écrasez ces fichiers par les originaux (même nom) : aucun changement de code nécessaire.

    python tools/make_standin_textures.py village/Textures
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
import make_test_assets as mta


def _save(a, p):
    Image.fromarray(np.clip(a, 0, 255).astype(np.uint8)).save(p)


def main(out="Textures"):
    d = Path(out); d.mkdir(parents=True, exist_ok=True)
    tmp = d / "_tmp"; tmp.mkdir(exist_ok=True)
    mta.make_textures(tmp)
    rng = np.random.default_rng(11)
    for src, dst in [("brick", "T_Brick_BaseColor"), ("plaster", "T_Plaster_BaseColor"),
                     ("wood", "T_WoodTrim_BaseColor"), ("tiles", "T_RoundTiles_BaseColor"), ("leaf", "T_VineLeaf")]:
        (tmp / f"{src}.png").replace(d / f"{dst}.png")
    # briques irrégulières : même motif, teintes beaucoup plus dispersées
    b = np.asarray(Image.open(d / "T_Brick_BaseColor.png").convert("RGB"), float)
    _save(b * rng.uniform(0.7, 1.25, (8, 4))[np.arange(256)[:, None] // 32, np.arange(256)[None, :] // 64][..., None], d / "T_UnevenBrick_BaseColor.png")
    _save(b * np.array([0.78, 0.62, 0.6]), d / "T_RedBrick_BaseColor.png")
    n = 256                                                       # pierre : gros blocs gris, joints sombres
    yy, xx = np.mgrid[0:n, 0:n]
    blk = (yy // 64) * 4 + (xx // 64)
    shade = rng.uniform(0.8, 1.15, 16)[blk]
    joint = ((yy % 64) < 4) | ((xx % 64) < 4)
    _save(np.where(joint[..., None], 70, (128 * shade + rng.normal(0, 6, (n, n)))[..., None] * np.array([1, 1, 1.04])), d / "T_RockTrim_BaseColor.png")
    _save(np.array([58, 58, 66])[None, None] + rng.normal(0, 4, (128, 128, 1)), d / "T_MetalOrnaments_BaseColor.png")
    for f in tmp.iterdir():
        f.unlink()
    tmp.rmdir()
    (d / "STANDIN_TEXTURES.txt").write_text(
        "Textures de SUBSTITUTION generees par tools/make_standin_textures.py.\n"
        "Ce ne sont PAS les textures du kit Emergence. Remplacez-les par les originaux (meme nom de fichier).\n")
    print("Textures de substitution :", ", ".join(sorted(p.name for p in d.glob("T_*.png"))))


if __name__ == "__main__":
    main(*sys.argv[1:2])
