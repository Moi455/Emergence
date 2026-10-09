"""budget.py - what the Transformer sees, counted from the catalogue (the AI-budget check).

    python3 catalogue/tools/budget.py

Groups model-visible variables by token type (SELF, ENTITY, INV...) from the 'token' field.
A variable without a token is engine-only: it acts on the world but the model never reads it.
"""
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from schema import Catalogue  # noqa: E402

BUDGET = {"SELF": 64, "SELF_MIND": 64, "SELF_STATE": 64, "ENTITY": 40, "BELIEF": 16, "MEMORY": 16, "GOAL": 16,
          "GROUP": 16, "COMMIT": 16, "REQUEST": 8, "PLAN": 8, "THING": 16, "PLACE": 16, "SKILL": 8}   # fields per token type (proposal, checked at step 16)
# how many tokens of each type one decision may hold; the perception tokens (place, things, dangers,
# events) are defined at step 11-12 and reserved here
TOKENS = {"SELF": 1, "SELF_MIND": 1, "SELF_STATE": 1, "TASTE": 2, "ENTITY": 10, "GROUP": 2, "BELIEF": 12,
          "HEARD": 2, "MEMORY": 9, "GOAL": 4, "PLAN": 1, "REQUEST": 2, "COMMIT": 3, "INV": 8, "SKILL": 3,
          "PLACE": 1, "THING": 16, "EVENT (réservé, étape 12)": 6}
GRAMMAR_WORDS_MAX = 512    # predicates, links, modes, emotions, techniques... (concepts)
KINDS_MAX = 1024           # item types, materials, species, forms: a separate, factored table
OBJECT_VECTOR_MAX = 48     # perceptible properties and affordances of a thing
MAX_TOKENS = 128
WRITES_PER_DECISION = 4                       # sparse writes (pointer, variable, value) besides the gesture


def slots(cat):
    out = defaultdict(set)
    for v in cat["variable"].values():
        for part in v.token.split(";"):
            m = re.match(r"\s*([A-Z_]+)(?:\.([\w.]+))?", part)
            if m:
                out[m.group(1)].add(m.group(2) or m.group(1))
    return out


def main():
    cat = Catalogue.load()
    s = slots(cat)
    hidden = [v.id for v in cat["variable"].values() if not v.token]
    print(f"variables : {len(cat['variable'])}, vues par l'IA : {len(cat['variable']) - len(hidden)}, moteur seul : {len(hidden)}")
    for typ in sorted(s):
        b = BUDGET.get(typ)
        flag = "" if b is None else ("  OK" if len(s[typ]) <= b else f"  DÉPASSE {b}")
        print(f"  {typ:8s} {len(s[typ]):3d} champs{flag}  " + ", ".join(sorted(s[typ])))
    print("  moteur seul : " + ", ".join(hidden))
    total = sum(TOKENS.values())
    words = len(cat["concept"])
    kinds = sum(len(cat[k]) for k in ("item_type", "material", "species", "form"))
    vec = len(cat.object_vector())
    print(f"vocabulaire : {words} mots de grammaire / {GRAMMAR_WORDS_MAX}, {kinds} sortes / {KINDS_MAX} ; "
          f"vecteur d'un objet : {vec} propriétés perceptibles / {OBJECT_VECTOR_MAX}")
    print(f"écritures par décision : ≤ {WRITES_PER_DECISION} (+ le geste)")
    print(f"jetons par décision : {total} / {MAX_TOKENS}  " + ", ".join(f"{k} {n}" for k, n in TOKENS.items()))
    ok = (all(len(s[t]) <= b for t, b in BUDGET.items() if t in s) and total <= MAX_TOKENS
          and words <= GRAMMAR_WORDS_MAX and kinds <= KINDS_MAX and vec <= OBJECT_VECTOR_MAX)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
