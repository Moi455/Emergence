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

    RECORD_LAYOUTS = {
        "HEARD": "same fields as BELIEF (prop, polarity, certainty=engine prior, source=told, informant, hops, age)",
        "INV": "same fields as THING (kind, props = object vector, state, amount, owner, file)",
        "TASTE": "concept (pointer to a word) + attitude (bipolar10)",
        "COMMIT": "counterparty (mref), mine_or_theirs, prop (expression), deadline_felt, status_believed, witnesses_believed",
        "PLAN": "steps (gesture + params), goal (mref), progress, commitment",
        "REQUEST": "from (mref), prop (expression), age",
        "SKILL": "technique (word), self_estimate",
    }
    ACCEPT_TOKENS = {"agent": "ENTITY", "animal": "THING", "item": "THING|INV", "structure": "THING", "terrain": "THING",
                     "voxel": "THING", "water": "THING", "fire": "THING", "trace": "THING", "plant": "THING",
                     "place": "PLACE (here) or a known place file (@L)", "belief": "BELIEF", "form": "kinds table (forms)",
                     "group": "GROUP", "direction": "relative_direction_head"}

    def _field_specs(self) -> dict:
        """token field -> encoding (scale, values, unit) from the variable that feeds it."""
        out = {}
        for v in sorted(self.cat["variable"].values(), key=lambda x: x.id):
            for part in v.token.split(";"):
                m = re.match(r"\s*([A-Z][A-Z_]*)(?:\.([a-z_][a-z0-9_.]*))?", part)
                if not m:
                    continue
                key = m.group(1) + ("." + m.group(2) if m.group(2) else "")
                values = v.values or sorted(c.id for c in self.cat["concept"].values() if v.values_from and c.category == v.values_from)
                out.setdefault(key, {"from": v.id, "scale": v.scale, "values": values, "unit": v.unit})
        return out

    def input_spec(self) -> dict:
        slots = budget.slots(self.cat)
        fields = self._field_specs()
        types = {}
        for typ, count in budget.TOKENS.items():
            names = sorted(slots.get(typ, []))
            types[typ] = {"count": count,
                          "fields": {n: fields.get(f"{typ}.{n}", fields.get(typ, {})) for n in names if n != typ},
                          "layout": self.RECORD_LAYOUTS.get(typ, "")}
        return {"max_tokens": budget.MAX_TOKENS, "token_types": types,
                "object_vector": self.cat.object_vector(),
                "encoding": "bipolar10 and unipolar10 read as int8 tenths / 100; qty log-scaled; enum and word as vocabulary ids; mref as a pointer to a token slot of the same decision; time as age in game hours (log)"}

    def output_spec(self) -> dict:
        # a manner head is SHARED when every gesture using that param name has the same values; otherwise every
        # use is named gesture.param (names never depend on declaration order)
        by_name: dict[str, set] = {}
        for a in self.cat["action"].values():
            for p in a.params:
                if p.type == "enum":
                    by_name.setdefault(p.name, set()).add(tuple(p.values))
        heads: dict[str, dict] = {}
        per_gesture = {}
        max_refs = 0
        for a in sorted(self.cat["action"].values(), key=lambda x: x.id):
            params = []
            refs = 0
            for p in a.params:
                if p.type == "enum":
                    key = p.name if len(by_name[p.name]) == 1 else f"{a.id}.{p.name}"
                    heads.setdefault(key, {"values": p.values, "ordinal": p.ordinal,
                                           "intimate": p.intimate_values})
                    params.append({"name": p.name, "head": key, "optional": p.optional})
                elif p.type == "ref":
                    refs += 1
                    params.append({"name": p.name, "pointer": p.accepts,
                                   "token": sorted({self.ACCEPT_TOKENS[t] for t in p.accepts}), "optional": p.optional})
                else:
                    params.append({"name": p.name, "type": p.type, "optional": p.optional})
            max_refs = max(max_refs, refs)
            per_gesture[a.id] = {"params": params, "contact": bool(a.contact), "party_params": a.party_params,
                                 "minor_person_ok": a.minor_person_ok, "minor_whitelist": a.minor_whitelist}
        conditions = sorted(c.id for c in self.cat["concept"].values() if c.category == "condition")
        writable = {}
        for v in self.cat["variable"].values():
            comp = self.cat["component"].get(v.holder)
            if comp is not None and comp.engine_only:
                continue
            if not any(w.startswith("T_") for w in v.writer):
                continue
            target = {"relation": "ENTITY|GROUP pointer", "belief": "BELIEF pointer or new record", "episode": "MEMORY pointer or new record",
                      "goal": "GOAL pointer or new record", "intention": "the current PLAN", "request": "REQUEST pointer"}.get(v.holder, "self")
            values = v.values or sorted(c.id for c in self.cat["concept"].values() if v.values_from and c.category == v.values_from)
            if v.id == "m_interpretation":
                values = sorted(self.cat["interpretation"])
            writable[v.id] = {"holder": v.holder, "target": target, "scale": v.scale, "values": values, "writer": v.writer,
                              "step": v.step, "rate_per_day": v.rate, "slow_per_life_year": v.slow_rate,
                              "intimate": bool(v.intimate), "structured": v.scale in ("proposition", "list", "enum", "mref", "word", "time", "bool", "id")}
        return {
            "gesture_head": sorted(self.cat["action"]),
            "manner_heads": dict(sorted(heads.items())),
            "gestures": per_gesture,
            "max_pointers_per_gesture": max_refs,
            "relative_direction_head": self.vocab.directions,
            "feasibility_mask": "computed on the NPC's percepts and beliefs, never on the world; a gesture that the world refuses fails physically and that failure is perceived",
            "condition_head": conditions,
            "speech": {"max_symbols": language.MAX_SYMBOLS, "max_depth": language.MAX_DEPTH,
                       "grammar_words": sorted(self.vocab.words), "kinds": sorted(self.vocab.kinds),
                       "pointers": ["@E<n>", "@T<n>", "@G<n>", "@L<n>", "@V<n>", "@PLACE", "b:<n>", "m:<n>", "g:<n>", "n:<name id>"]},
            "writes": {"max_per_decision": budget.WRITES_PER_DECISION,
                       "format": "(target, variable, value); a structured value (proposition) comes from the speech decoder; creating a record = one write",
                       "writable": dict(sorted(writable.items()))},
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
