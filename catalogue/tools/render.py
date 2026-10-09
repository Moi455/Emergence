"""render.py - write catalogue/CATALOGUE.md (French, for Monsieur) from the TOML data.

    python3 catalogue/tools/render.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from schema import Catalogue  # noqa: E402

WRITER_FR = {"engine": "moteur", "T_jump": "T saut", "T_step": "T pas", "T_slow": "T lent",
             "birth": "naissance", "action": "action", "derived": "calculé"}
VIS_FR = {"private": "privé", "observable": "observable", "public": "public", "engine": "moteur seul"}
SECTIONS = [("story", "Histoires (tests d'acceptation)"), ("entity", "Types d'entités"),
            ("component", "Composants"), ("variable", "Variables d'état"), ("property", "Propriétés et affordances"),
            ("material", "Matières"), ("process", "Processus (lois de transformation, jamais choisis)"),
            ("form", "Formes de parties (la grammaire des objets)"), ("species", "Espèces vivantes (lois du moteur)"), ("item_type", "Types d'objets connus"),
            ("action", "Gestes physiques"), ("concept", "Langue intérieure : concepts"),
            ("grammar", "Langue intérieure : grammaire"), ("interpretation", "Interprétations (jamais des options)"),
            ("hard_rule", "Règles dures")]


def cell(x):
    if isinstance(x, list):
        x = ", ".join(str(i) for i in x)
    return str(x).replace("|", "\\|").replace("\n", " ")


def table(head, rows):
    out = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    out += ["| " + " | ".join(cell(c) for c in r) + " |" for r in rows]
    return out


def render(cat):
    cited = cat.citations()
    L = ["# Catalogue d'Emergence", "",
         "Généré par `catalogue/tools/render.py` depuis `catalogue/data/*.toml`. Ne pas éditer à la main.", "",
         "Compte : " + ", ".join(f"{k} {n}" for k, n in cat.count().items() if n), ""]
    for kind, title in SECTIONS:
        items = list(cat[kind].values())
        if not items:
            continue
        L += [f"## {title}", ""]
        if kind == "story":
            L += table(["id", "charte", "état", "histoire"], [[s.id, s.charter, s.status, s.text_fr] for s in items])
        elif kind == "variable":
            for holder in sorted({v.holder for v in items}):
                L += [f"### {holder}", ""]
                L += table(["id", "libellé", "échelle", "écrit par", "pas", "visibilité", "dynamique", "jeton", "histoires"],
                           [[v.id, v.label_fr, v.scale + (f" ({', '.join(v.values)})" if v.values else ""),
                             [WRITER_FR[w] for w in v.writer], v.step or "", VIS_FR.get(v.visibility, v.visibility),
                             v.dynamics, v.token, len(cited["variable"].get(v.id, []))]
                            for v in items if v.holder == holder])
                L.append("")
            continue
        elif kind == "action":
            L += table(["id", "famille", "libellé", "paramètres", "effets", "perception", "histoires"],
                       [[a.id, a.family, a.label_fr,
                         "; ".join(f"{p.name}:{p.type}" + (f"={'/'.join(p.values)}" if p.values else "") + ("?" if p.optional else "")
                                   for p in a.params), a.effects, a.perceptibility, len(cited["action"].get(a.id, []))]
                        for a in items])
        elif kind == "concept":
            L += table(["id", "catégorie", "arguments", "libellé", "renvoie à"], [[c.id, c.category, c.args, c.label_fr, c.refers] for c in items])
        elif kind == "interpretation":
            L += table(["id", "libellé", "faits objectifs", "normes"], [[i.id, i.label_fr, i.facts, i.norms] for i in items])
        elif kind == "entity":
            L += table(["id", "libellé", "composants", "piloté par"], [[e.id, e.label_fr, e.components, e.driven_by] for e in items])
        elif kind == "component":
            L += table(["id", "libellé", "porté par"], [[c.id, c.label_fr, c.holder] for c in items])
        elif kind == "property":
            for cat_ in ("intrinsic", "state", "affordance"):
                L += [f"### {dict(intrinsic='Intrinsèques', state='États', affordance='Affordances (calculées)')[cat_]}", ""]
                L += table(["id", "libellé", "s'applique à", "échelle", "calculée depuis", "règle physique"],
                           [[p.id, p.label_fr, p.applies_to, p.scale + (f" {p.unit}" if p.unit else ""), p.derived_from, p.rule]
                            for p in items if p.category == cat_])
                L.append("")
        elif kind == "material":
            L += table(["id", "n°", "catégorie", "densité", "dureté", "ténacité", "inflammabilité", "cohésion", "fusion °C", "nutrition"],
                       [[m.id, m.num if m.num >= 0 else "proposée", m.category, m.density_kg_m3, m.hardness,
                         m.toughness if m.toughness >= 0 else "", m.flammability, m.cohesion,
                         m.melting_c if m.melting_c >= 0 else "", m.edible or ""] for m in items])
        elif kind == "process":
            L += table(["id", "libellé", "entrées", "conditions", "effet"], [[x.id, x.label_fr, x.inputs, x.conditions, x.effect] for x in items])
        elif kind == "species":
            L += table(["id", "libellé", "règne", "habitat", "domestique", "produits (partie:matière)", "danger", "comportement"],
                       [[x.id, x.label_fr, x.kingdom, x.habitat, "oui" if x.domestic else "", x.products, x.danger or "", x.behavior] for x in items])
        elif kind == "form":
            L += table(["id", "forme", "donne", "règle"], [[x.id, x.label_fr, x.gives, x.rule] for x in items])
        elif kind == "item_type":
            L += ["Un type connu est un savoir commun, jamais une limite : le moteur accepte tout assemblage de parties.", ""]
            for fname in sorted({x.file for x in items}):
                L += [f"### {fname}", ""]
                L += table(["id", "libellé", "catégorie", "parties (forme:matière)", "kg", "propriétés déduites", "fait par"],
                           [[x.id, x.label_fr, x.category, x.parts, x.mass_kg,
                             sorted(cat.item_properties(x.parts, x.properties)), x.made_by] for x in items if x.file == fname])
                L.append("")
            continue
        elif kind == "grammar":
            L += table(["id", "règle", "libellé"], [[g.id, g.rule, g.label_fr] for g in items])
        elif kind == "hard_rule":
            L += table(["id", "règle", "s'applique à"], [[h.id, h.text_fr, h.applies_to] for h in items])
        L.append("")
    return "\n".join(L)


def main():
    cat = Catalogue.load()
    (ROOT / "CATALOGUE.md").write_text(render(cat), encoding="utf-8")
    print("écrit", ROOT / "CATALOGUE.md")


if __name__ == "__main__":
    main()
