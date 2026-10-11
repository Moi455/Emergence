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
        "WAKE": "why this decision happens now: mode, cause, trigger (the record that woke him), urgency",
        "SKILL": "technique (word), self_estimate",
    }
    # Record keys: the speaker's pointers of the inner language (@E3, b:7...), and private prefixes for records the
    # language cannot point to (h:, q:, c:, p:, k:, t:). "me" is the NPC himself (SELF); a key is unique per decision.
    KEYS = {"SELF": "me", "SELF_MIND": "me.mind", "SELF_STATE": "me.state", "TASTE": "t:", "ENTITY": "@E", "GROUP": "@G",
            "BELIEF": "b:", "HEARD": "h:", "MEMORY": "m:", "GOAL": "g:", "PLAN": "p:", "REQUEST": "q:", "COMMIT": "c:",
            "INV": "@T", "SKILL": "k:", "PLACE": "@PLACE", "THING": "@T", "EVENT": "@V", "LOCUS": "@L", "WAKE": "wake"}
    ALIASES = {"HEARD": "BELIEF", "INV": "THING"}
    # A deadline is a point in the FUTURE (hours until it; negative = overdue): the model reads a signed log. A
    # variable declared scale=time is an age (hours since); only these fields are rewritten.
    TIME_UNTIL_FIELDS = {"deadline"}
    EXPLICIT = {
        "TASTE": {"concept": {"scale": "word", "values": [], "unit": "", "list_of": "", "components": [], "component_scales": []},
                  "attitude": {"scale": "bipolar10", "values": [], "unit": "", "list_of": "", "components": [], "component_scales": []}},
        "COMMIT": {"counterparty": {"scale": "mref", "values": [], "unit": "", "list_of": "", "components": [], "component_scales": []},
                   "mine": {"scale": "bool", "values": [], "unit": "", "list_of": "", "components": [], "component_scales": []},
                   "prop": {"scale": "proposition", "values": [], "unit": "", "list_of": "", "components": [], "component_scales": []},
                   "deadline": {"scale": "time_until", "values": [], "unit": "", "list_of": "", "components": [], "component_scales": []},
                   "status": {"scale": "enum", "values": ["open", "fulfilled", "broken", "released"], "unit": "", "list_of": "", "components": [], "component_scales": []},
                   "witnesses": {"scale": "list", "values": [], "unit": "", "list_of": "mref", "components": [], "component_scales": []}},
        "PLAN": {"step": {"scale": "word", "values": [], "unit": "", "list_of": "", "components": [], "component_scales": []},
                 "goal": {"scale": "mref", "values": [], "unit": "", "list_of": "", "components": [], "component_scales": []},
                 "progress": {"scale": "ratio", "values": [], "unit": "", "list_of": "", "components": [], "component_scales": []},
                 "commitment": {"scale": "unipolar10", "values": [], "unit": "", "list_of": "", "components": [], "component_scales": []},
                 "target": {"scale": "mref", "values": [], "unit": "", "list_of": "", "components": [], "component_scales": []},
                 "next": {"scale": "word", "values": [], "unit": "", "list_of": "", "components": [], "component_scales": []}},
        "WAKE": {"mode": {"scale": "enum", "values": ["act", "listen", "reflect"], "unit": "", "list_of": "", "components": [], "component_scales": []},
                 "cause": {"scale": "enum", "values": ["perception", "speech", "request", "body", "plan", "timer", "routine"], "unit": "", "list_of": "", "components": [], "component_scales": []},
                 "trigger": {"scale": "mref", "values": [], "unit": "", "list_of": "", "components": [], "component_scales": []},
                 "urgency": {"scale": "unipolar10", "values": [], "unit": "", "list_of": "", "components": [], "component_scales": []}},
    }
    ACCEPT_TOKENS = {"agent": "ENTITY", "animal": "THING", "item": "THING|INV", "structure": "THING", "terrain": "THING",
                     "voxel": "THING", "water": "THING", "fire": "THING", "trace": "THING", "plant": "THING",
                     "place": "PLACE (here) or LOCUS (a known place, @L)", "belief": "BELIEF", "form": "kinds table (forms)",
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
                if v.components == ["@object_vector"]:            # each property on its own scale
                    comps = self.cat.object_vector()
                    scales = [self.cat["property"][c].scale for c in comps]
                else:                                             # named axes, given normalised in [-1, 1]
                    comps, scales = list(v.components), ["unit"] * len(v.components)
                scale = v.scale
                if scale == "time" and key.rpartition(".")[2] in self.TIME_UNTIL_FIELDS:
                    scale = "time_until"
                units = [self.cat["property"][c].unit for c in comps] if v.components == ["@object_vector"] else [""] * len(comps)
                out.setdefault(key, {"from": v.id, "scale": scale, "values": values, "unit": v.unit, "list_of": v.list_of,
                                     "components": comps, "component_scales": scales, "component_units": units})
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
        for typ, key in self.KEYS.items():                         # how a record of this type is designated
            types[typ]["key"] = key
        for typ, base in self.ALIASES.items():                     # same layout as another record type
            types[typ]["fields"] = dict(types[base]["fields"])
            types[typ]["alias_of"] = base
        for typ, flds in self.EXPLICIT.items():                     # record tokens fed by list variables
            types[typ]["fields"] = {k: dict(v) for k, v in flds.items()}
        return {"max_tokens": budget.MAX_TOKENS, "token_types": types,
                "object_vector": self.cat.object_vector(),
                "encoding": ("numbers are normalised in double precision and stored as float16: bipolar10 and unipolar10 as x / 10, ratio and unit as x, "
                             "qty as log1p(x) (signed log for degC), time (an age, hours since) as log1p(x), time_until (a deadline, hours until, "
                             "negative = overdue) as a signed log1p, bool as 0 or 1; every number, word and pointer has a known flag (unknown is "
                             "not zero, an empty list or 'nobody' is known); enum and word as vocabulary ids"),
                "pointer_encoding": ("an mref field holds the index of a token slot of the same decision (1..128); 0 = none (a known 'nobody', "
                                     "told apart from an unknown pointer by ptr_known); 129 + k = a GHOST: a record of the NPC's mind that this "
                                     "decision does not carry (k = 0..31, numbered by first appearance in the encoding order: rows, then "
                                     "columns, then proposition positions; two pointers to the same ghost give the same slot, two different "
                                     "ghosts give different slots); 161 = a ghost beyond the 32nd. A pointer to something the NPC's mind "
                                     "does not hold is refused (never encoded)")}

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
        condition_args = {c: self.cat["concept"][c].args for c in conditions}
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
            "condition_args": condition_args,
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
