"""model_interface.py - step 16: the exact model interface, generated from the catalogue (single source of truth).

    python3 catalogue/tools/model_interface.py          # writes catalogue/generated/model_interface.json

Input token types and their fields, output heads (gesture, shared manner heads, pointers, conditions, speech
vocabulary), and the writable variables with their governor bounds. The training code (ai/) and the C++
headers generator (D31) both read this file; a test checks it is up to date.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tools"))
from schema import Catalogue  # noqa: E402
import budget  # noqa: E402
import language  # noqa: E402

OUT = ROOT / "generated" / "model_interface.json"
SCHEMA_VERSION = "model-interface-1"


class ModelInterface:
    def __init__(self, cat: Catalogue):
        self.cat = cat
        self.vocab = language.Vocabulary(cat)

    def input_spec(self) -> dict:
        slots = budget.slots(self.cat)
        types = {}
        for typ, count in budget.TOKENS.items():
            types[typ] = {"count": count, "fields": sorted(slots.get(typ, []))}
        return {"max_tokens": budget.MAX_TOKENS, "token_types": types,
                "object_vector": self.cat.object_vector()}

    def output_spec(self) -> dict:
        heads: dict[str, list[str]] = {}
        per_gesture = {}
        max_refs = 0
        for a in self.cat["action"].values():
            params = []
            refs = 0
            for p in a.params:
                if p.type == "enum":
                    key = p.name if p.name not in heads or heads[p.name] == p.values else f"{a.id}.{p.name}"
                    heads.setdefault(key, p.values)
                    params.append({"name": p.name, "head": key, "optional": p.optional})
                elif p.type == "ref":
                    refs += 1
                    params.append({"name": p.name, "pointer": p.accepts, "optional": p.optional})
                else:
                    params.append({"name": p.name, "type": p.type, "optional": p.optional})
            max_refs = max(max_refs, refs)
            per_gesture[a.id] = params
        conditions = sorted(c.id for c in self.cat["concept"].values() if c.category == "condition")
        writable = {}
        for v in self.cat["variable"].values():
            comp = self.cat["component"].get(v.holder)
            if comp is not None and comp.engine_only:
                continue
            if not any(w.startswith("T_") for w in v.writer):
                continue
            writable[v.id] = {"holder": v.holder, "scale": v.scale, "writer": v.writer, "step": v.step,
                              "rate_per_day": v.rate, "slow_per_life_year": v.slow_rate, "intimate": bool(v.intimate)}
        return {
            "gesture_head": sorted(self.cat["action"]),
            "manner_heads": dict(sorted(heads.items())),
            "gestures": per_gesture,
            "max_pointers_per_gesture": max_refs,
            "direction_head": self.vocab.directions,
            "feasibility_mask": "computed on the NPC's percepts and beliefs, never on the world; a gesture that the world refuses fails physically and that failure is perceived",
            "condition_head": conditions,
            "speech": {"max_symbols": language.MAX_SYMBOLS, "max_depth": language.MAX_DEPTH,
                       "grammar_words": sorted(self.vocab.words), "kinds": sorted(self.vocab.kinds),
                       "pointers": ["@E<n>", "@T<n>", "@G<n>", "@L<n>", "@PLACE", "b:<n>", "m:<n>", "g:<n>", "n:<name>"]},
            "writes": {"max_per_decision": budget.WRITES_PER_DECISION, "writable": dict(sorted(writable.items()))},
        }

    def build(self) -> dict:
        return {"schema_version": SCHEMA_VERSION, "input": self.input_spec(), "output": self.output_spec()}

    def text(self) -> str:
        return json.dumps(self.build(), ensure_ascii=False, indent=1, sort_keys=True) + "\n"


def main():
    mi = ModelInterface(Catalogue.load())
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(mi.text(), encoding="utf-8")
    spec = mi.build()["output"]
    print(f"écrit {OUT}")
    print(f"  {len(spec['gesture_head'])} gestes, {len(spec['manner_heads'])} têtes de manière, "
          f"{spec['max_pointers_per_gesture']} pointeurs au plus par geste, {len(spec['condition_head'])} conditions, "
          f"{len(spec['speech']['grammar_words'])} mots + {len(spec['speech']['kinds'])} sortes, "
          f"{len(spec['writes']['writable'])} variables écrivables (≤ {spec['writes']['max_per_decision']} par décision)")


if __name__ == "__main__":
    main()
