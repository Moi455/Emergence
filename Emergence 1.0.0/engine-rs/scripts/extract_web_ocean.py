#!/usr/bin/env python3
"""Extrait le WGSL de `web-ocean` (modules JavaScript lus COMME DU TEXTE, jamais exécutés).

Usage (le dossier source est un téléchargement : interpréteur isolé) :
    python3 -I engine-rs/scripts/extract_web_ocean.py "/chemin/web-ocean-main/js/wgsl"

Pour chaque export WGSL listé dans EXPORTS, écrit un module assemblé (les concaténations du JS sont
résolues, les constantes de gabarit `${N}`, `${SKY_W}`… sont remplacées) dans
`crates/em_render/shaders/third_party/web-ocean/`, avec la notice MIT en tête, plus `MANIFEST.toml`
(fichier source, export, SHA-256 du fichier source, SHA-256 du module écrit, rustines appliquées).

Quatre adaptations, et quatre seulement, déclarées dans le manifeste :
  1. `FRAME_WGSL` (struct du JS) est remplacé par la ligne `//@FRAME_WGSL` : le code Rust y insère
     `shaders/sky/frame.wgsl`, la struct `Frame` réécrite pour le moteur (docs/19b L03) ;
  2. COMPOSITE : la sortie est linéarisée (`pow(x, 2.2)`, l'EOTF d'AgX) car la cible du labo est sRGB
     (le matériel ré-encode), alors que le canvas web était non sRGB ;
  3. ombre de la planète (`planetShadow`) dans `sky_render_funcs` et dans l'éclairage des nuages : sans elle,
     les nuages restent éclairés par un soleil situé sous l'horizon (web-ocean ne rend jamais de nuit) ;
  4. `cloudFbm` : sortie anticipée quand une octave est éteinte (coût, résultat identique).
"""
import hashlib
import pathlib
import re
import sys

RACINE = pathlib.Path(__file__).resolve().parent.parent
SORTIE = RACINE / "crates/em_render/shaders/third_party/web-ocean"

# (fichier, export) -> nom du module écrit.
EXPORTS = [
    ("common.js", "ATMO_CORE_WGSL", "atmo_core"),
    ("common.js", "NOISE_WGSL", "noise"),
    ("sky.js", "TRANS_LUT", "trans_lut"),
    ("sky.js", "MS_LUT", "ms_lut"),
    ("sky.js", "SKYVIEW_LUT", "skyview_lut"),
    ("sky.js", "SKY_RENDER_FUNCS", "sky_render_funcs"),
    ("sky.js", "SKY_CLOUD_FUNCS", "sky_cloud_funcs"),
    ("sky.js", "ENV_CUBE", "env_cube"),
    ("sky.js", "CUBE_MIPS", "cube_mips"),
    ("sky.js", "SUN_VIS", "sun_vis"),
    ("post.js", "BLOOM_DOWN", "bloom_down"),
    ("post.js", "BLOOM_UP", "bloom_up"),
    ("post.js", "COMPOSITE", "composite"),
]

RUSTINES = {
    "sky_render_funcs": [
        (
            "fn skyAtmo(dir: vec3f) -> vec3f {",
            "// [ADAPTATION EM] ombre de la planète : web-ocean n'éclaire jamais la nuit (nuages roses à minuit).\n"
            "// Le soleil sous l'horizon géométrique du point `r` (rayon depuis le centre, km) est éteint en douceur.\n"
            "fn planetShadow(r: f32, mu: f32) -> f32 {\n"
            "  let h = rhoOf(r) / r;\n"
            "  return smoothstep(-h - 0.006, -h + 0.002, mu);\n"
            "}\n\n"
            "fn skyAtmo(dir: vec3f) -> vec3f {",
        )
    ],
    "sky_cloud_funcs": [
        (
            "    let w = 1.0 - smoothstep(0.08, 0.28, fp * f);\n",
            "    let w = 1.0 - smoothstep(0.08, 0.28, fp * f);\n"
            "    if (w <= 0.0) { break; } // [ADAPTATION EM] octave déjà éteinte, les suivantes aussi : on ne les calcule plus\n",
        ),
        (
            "let sunC = sampleTrans(RG + hc, dot(h.up, F.sunDir.xyz)) * F.sunDir.w;",
            "let sunC = sampleTrans(RG + hc, dot(h.up, F.sunDir.xyz)) * F.sunDir.w * planetShadow(RG + hc, dot(h.up, F.sunDir.xyz)); // [ADAPTATION EM]",
        )
    ],
    "composite": [
        (
            "return vec4f(clamp(o, vec3f(0.0), vec3f(1.0)), 1.0);",
            "// [ADAPTATION EM] cible sRGB : le materiel ré-encode, on rend donc le signal linéaire (EOTF d'AgX).\n"
            "  return vec4f(pow(clamp(o, vec3f(0.0), vec3f(1.0)), vec3f(2.2)), 1.0);",
        )
    ]
}

NOTICE = """\
// web-ocean : MIT License, Copyright (c) 2026 Maksymilian Dendura (voir LICENSE à côté de ce fichier).
// Module généré par engine-rs/scripts/extract_web_ocean.py : NE PAS ÉDITER à la main.
// Source : {fichier} (export {export}), SHA-256 du fichier source {sha}.
"""


def sha256(octets: bytes) -> str:
    return hashlib.sha256(octets).hexdigest()


def lire_constantes(texte: str) -> dict:
    """Constantes numériques `export const N = 256;` (pour les `${N}` des gabarits)."""
    return {m.group(1): m.group(2) for m in re.finditer(r"^export const (\w+)\s*=\s*(\d+)\s*;", texte, re.M)}


def decouper_instructions(texte: str):
    """Génère (nom, termes) pour chaque `const NOM = a + b + `gabarit`;` de haut niveau.
    Un terme est ('id', nom) ou ('tpl', texte brut du gabarit)."""
    i, n = 0, len(texte)
    motif = re.compile(r"^(?:export\s+)?const\s+(\w+)\s*=\s*", re.M)
    while True:
        m = motif.search(texte, i)
        if not m:
            return
        j = m.end()
        termes = []
        ok = True
        while j < n:
            while j < n and texte[j] in " \t\r\n":
                j += 1
            if texte.startswith("/*", j):
                j = texte.index("*/", j) + 2
                continue
            if texte[j] == "`":
                k = j + 1
                profondeur = 0
                while k < n:
                    c = texte[k]
                    if c == "\\":
                        k += 2
                        continue
                    if c == "$" and texte.startswith("${", k):
                        profondeur += 1
                        k += 2
                        continue
                    if c == "}" and profondeur:
                        profondeur -= 1
                    elif c == "`" and not profondeur:
                        break
                    k += 1
                termes.append(("tpl", texte[j + 1 : k]))
                j = k + 1
            elif re.match(r"[A-Za-z_]", texte[j]):
                mm = re.compile(r"\w+").match(texte, j)
                termes.append(("id", mm.group(0)))
                j = mm.end()
            else:
                ok = False
                break
            while j < n and texte[j] in " \t\r\n":
                j += 1
            if j < n and texte[j] == "+":
                j += 1
                continue
            break
        if ok and termes:
            yield m.group(1), termes
        i = max(j, m.end())


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    source = pathlib.Path(sys.argv[1])
    textes = {}
    constantes = {}
    definitions = {}
    empreintes = {}
    for f in sorted({e[0] for e in EXPORTS}):
        brut = (source / f).read_bytes()
        empreintes[f] = sha256(brut)
        textes[f] = brut.decode("utf-8")
        constantes.update(lire_constantes(textes[f]))
        for nom, termes in decouper_instructions(textes[f]):
            definitions[nom] = termes

    def assembler(nom: str) -> str:
        morceaux = []
        for genre, valeur in definitions[nom]:
            if genre == "tpl":
                morceaux.append(substituer(valeur))
            elif valeur == "FRAME_WGSL":
                morceaux.append("\n//@FRAME_WGSL\n")
            else:
                morceaux.append(assembler(valeur))
        return "".join(morceaux)

    def substituer(gabarit: str) -> str:
        def remplace(m):
            nom = m.group(1).strip()
            if nom in constantes:
                return constantes[nom]
            mm = re.fullmatch(r"(\w+)\s*-\s*(\d+)", nom)
            if mm and mm.group(1) in constantes:
                return str(int(constantes[mm.group(1)]) - int(mm.group(2)))
            raise SystemExit(f"constante de gabarit inconnue : ${{{nom}}}")

        return re.sub(r"\$\{([^}]*)\}", remplace, gabarit)

    SORTIE.mkdir(parents=True, exist_ok=True)
    manifeste = [
        "# Généré par engine-rs/scripts/extract_web_ocean.py. Source : web-ocean (MIT, © 2026 Maksymilian Dendura).",
        "",
    ]
    for fichier, export, nom in EXPORTS:
        corps = assembler(export)
        rustines = []
        for ancien, nouveau in RUSTINES.get(nom, []):
            if ancien not in corps:
                raise SystemExit(f"rustine introuvable dans {export} : {ancien!r}")
            corps = corps.replace(ancien, nouveau)
            rustines.append(ancien)
        contenu = NOTICE.format(fichier=fichier, export=export, sha=empreintes[fichier]) + corps
        (SORTIE / f"{nom}.wgsl").write_text(contenu, encoding="utf-8")
        manifeste += [
            "[[module]]",
            f'fichier_source = "{fichier}"',
            f'export = "{export}"',
            f'module = "{nom}.wgsl"',
            f'sha256_source = "{empreintes[fichier]}"',
            f'sha256_module = "{sha256(contenu.encode("utf-8"))}"',
            f"utilise_frame = {str('//@FRAME_WGSL' in corps).lower()}",
            f"rustines = {len(rustines)}",
            "",
        ]
    (SORTIE / "MANIFEST.toml").write_text("\n".join(manifeste), encoding="utf-8")
    print(f"{len(EXPORTS)} modules écrits dans {SORTIE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
