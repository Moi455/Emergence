"""golden.py - the golden files the C++ port (and the model code) are checked against.

    python3 -m tok2.golden            (from ai/)  what would change
    python3 -m tok2.golden --update               rewrite golden/layout.json and golden/cases.jsonl
    python3 -m tok2.golden --check                exit 1 when they are out of date

golden/layout.json  the contract: constants, arrays (dtype, shape), types (id, count, key), columns (block, column,
                    width, codec kind, normalisation formula, scale, unit, enum values, components), block widths,
                    the vocabulary id -> symbol, and the table speech word -> input id (to tie the embeddings of
                    the output speech head to the input embeddings).
golden/cases.jsonl  about 30 canonical decisions, one per line: {name, context, expect}. A context is the canonical
                    JSON of a DecisionContext (header included: it names the interface and the layout it was
                    written for); expect is {digest (crc32, 8 hex), n, ghosts} or {error: "TokenError"}. Twelve come
                    from the situations sampler at a fixed seed, the others are made by hand for the edges.
A port reads the context, encodes it, and must find the digest (the arrays are bit-identical) or the refusal.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from .codecs import (BAG_CAP, GHOST_BASE, GHOST_OVERFLOW, GHOST_SLOTS, NONE_SLOT, PTR_LIST_CAP, QTY_MAX,
                     SIGNED_UNITS, SUM_COMPONENTS)
from .errors import TokenError
from .interface import InputVocabulary
from .tokenizer import CONTEXT_SCHEMA, DecisionContext, Encoded, Record, Tokenizer

GOLDEN_DIR = Path(__file__).with_name("golden")
LAYOUT_PATH = GOLDEN_DIR / "layout.json"
CASES_PATH = GOLDEN_DIR / "cases.jsonl"
SAMPLER_SEED, SAMPLER_CASES = 0, 12


def dumps(obj, indent=None) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=False, indent=indent)


# ---- layout.json ---------------------------------------------------------------------------------------
class GoldenLayout:
    def __init__(self, tok: Tokenizer):
        self.tok = tok

    def build(self) -> dict:
        tok, lay = self.tok, self.tok.layout
        enc = Encoded(lay)
        types = {}
        for name, t in lay.types.items():
            cols = {}
            for fname, c in sorted(t.columns.items(), key=lambda kv: (kv[1].codec.block, kv[1].col, kv[0])):
                spec = c.codec.spec
                col = {"block": c.codec.block, "col": c.col, "width": c.codec.width, "codec": c.codec.kind,
                       "scale": spec.get("scale", ""), "normalisation": c.codec.normalisation()}
                if spec.get("unit"):
                    col["unit"] = spec["unit"]
                if spec.get("scale") == "enum" or spec.get("list_of") == "enum":
                    col["values"] = list(spec["values"])
                if spec.get("components"):
                    col["components"] = list(spec["components"])
                cols[fname] = col
            types[name] = {"id": t.type_id, "count": t.count, "key": t.key, "columns": cols}
        speech = {w: tok.vocab.ids[w] for w in sorted(set(tok.interface.grammar_words) | set(tok.interface.kinds),
                                                      key=lambda w: tok.vocab.ids[w])}
        return {
            "schema": "tok2-golden-layout-1",
            "fingerprints": tok.header() | {"vocabulary": f"{tok.vocab.fingerprint:016x}"},
            "constants": {"max_tokens": lay.max_tokens, "prop_len": lay.prop_len, "none_slot": NONE_SLOT,
                          "ghost_base": GHOST_BASE, "ghost_slots": GHOST_SLOTS, "ghost_overflow": GHOST_OVERFLOW,
                          "bag_cap": BAG_CAP, "ptr_list_cap": PTR_LIST_CAP, "name_slots": InputVocabulary.NAME_SLOTS,
                          "qty_max": QTY_MAX, "signed_units": sorted(SIGNED_UNITS), "pooled_by_sum": sorted(SUM_COMPONENTS),
                          "count_encoding": "log1p(n + 1) for a count n in a proposition; 0 = no count"},
            "digest": "zlib.crc32 chained over pack('<I', n) then each array of `arrays` in order, "
                      "C order, little endian, with its dtype; 8 lowercase hex digits",
            "arrays": [{"name": a, "dtype": str(getattr(enc, a).dtype), "shape": list(getattr(enc, a).shape)}
                       for a in Encoded.ARRAYS],
            "widths": dict(lay.width),
            "types": types,
            "vocabulary": list(tok.vocab.symbols),
            "retired_symbols": sorted(set(tok.vocab.symbols) - tok.vocab.words - set(InputVocabulary.reserved())),
            "speech_to_input": speech,
        }

    def text(self) -> str:
        return dumps(self.build(), indent=1) + "\n"


# ---- cases.jsonl ---------------------------------------------------------------------------------------
class HandCases:
    """Decisions made by hand for the edges of the contract. Each method returns a DecisionContext."""

    def __init__(self, tok: Tokenizer):
        self.tok = tok

    @staticmethod
    def base(*records, known=None) -> DecisionContext:
        return DecisionContext([Record("SELF", "me", {}), Record("PLACE", "@PLACE", {}), *records], known)

    def all(self) -> list[tuple[str, DecisionContext, bool]]:
        """(name, context, valid)."""
        out = []
        for name in sorted(n for n in dir(self) if n.startswith(("ok_", "bad_"))):
            out.append((name, getattr(self, name)(), name.startswith("ok_")))
        return out

    # ---- valid ----
    def ok_minimal(self):
        return self.base()

    def ok_well(self):
        b = self.base
        return DecisionContext([
            Record("THING", "@T1", {"kind": "bucket", "dist": 1.5, "dir": {"sin": 0.0, "cos": 1.0}, "owner": "me",
                                    "props": {"capacity": 10.0, "wetness": 6}}),
            Record("SELF", "me", {"age": 34, "age_stage": "adult", "sex": "female", "need.thirst": 6.5, "body.pain": 0,
                                  "place": "@PLACE", "time": {"sin": 0.5, "cos": -0.86, "certainty": 0.9},
                                  "held": [{"edge": 2}, {"mass": 1.0, "edge": 0}]}),
            Record("ENTITY", "@E1", {"name": "n:17", "known_by": "seen", "present": True, "dist": 3.0, "rel.trust": -4.5,
                                     "rel.familiarity": 8, "look.held": {"capacity": 10.0}, "look.attire": ["w_poor"],
                                     "look.gaze": "@T1", "rep": {"honesty": -0.6}}),
            Record("BELIEF", "b:1", {"prop": "(owns me @T1)", "certainty": 9, "source": "seen", "polarity": True,
                                     "informant": "", "shared": ["@E1", "@E9"], "age": 200.0}),
            Record("BELIEF", "b:2", {"prop": "(owns @E1 silver_coin:3)", "certainty": 4, "source": "heard", "hops": 2}),
            Record("GOAL", "g:1", {"prop": "(at @E2 @PLACE)", "priority": 7, "mode": "achieve", "status": "active",
                                   "origin_ref": "b:1", "deadline": -3.0}),
            Record("PLACE", "@PLACE", {"indoors": False, "light": 8, "crowd": 2}),
            Record("REQUEST", "q:1", {"from": "@E1", "prop": "(request (did you give @T1 (to n:17)))", "age": 0.1}),
        ], known_keys=["me", "@PLACE", "@T1", "@E1", "@E2", "@E9", "b:1", "b:2", "g:1", "q:1"])

    def _two(self, a, b):
        return self.base(Record("BELIEF", "b:1", {"prop": f"(owns {a} silver_coin)"}),
                         Record("BELIEF", "b:2", {"prop": f"(at {b} @PLACE)"}),
                         known=["me", "@PLACE", "b:1", "b:2", "@E7", "@E9"])

    def ok_ghost_same(self):
        return self._two("@E7", "@E7")

    def ok_ghost_different(self):
        return self._two("@E7", "@E9")

    def ok_ghost_order_pointer_before_proposition(self):
        return self.base(Record("BELIEF", "b:1", {"prop": "(at @E5 @PLACE)", "informant": "@E6"}),
                         known=["me", "@PLACE", "b:1", "@E5", "@E6"])

    def ok_ghost_overflow(self):
        known = ["me", "@PLACE", *(f"b:{i}" for i in range(1, 11)), *(f"@E{i}" for i in range(1, 41))]
        recs = [Record("BELIEF", f"b:{i + 1}", {"shared": [f"@E{4 * i + j + 1}" for j in range(4)]}) for i in range(10)]
        return self.base(*recs, known=known)

    def ok_known_versus_empty(self):
        return DecisionContext([
            Record("SELF", "me", {"held": []}), Record("PLACE", "@PLACE", {}),
            Record("ENTITY", "@E1", {"look.attire": [], "look.gaze": "", "present": True}),
            Record("BELIEF", "b:1", {"shared": [], "informant": ""}), Record("BELIEF", "b:2", {})])

    def ok_deadlines_signed(self):
        return self.base(Record("GOAL", "g:1", {"prop": "(has me silver_coin)", "deadline": 24.0}),
                         Record("GOAL", "g:2", {"prop": "(has me silver_coin)", "deadline": -24.0}),
                         Record("GOAL", "g:3", {"prop": "(has me silver_coin)", "deadline": 0}),
                         Record("COMMIT", "c:1", {"prop": "(did me give silver_coin (to me))", "deadline": -0.0}))

    def ok_half_rounding(self):
        return DecisionContext([Record("SELF", "me", {"body.load": 1 - 2.0 ** -12 - 2.0 ** -40, "need.thermal": -0.0,
                                                      "body.mobility": 0.1}), Record("PLACE", "@PLACE", {"light": 3.3})])

    def ok_counts(self):
        return self.base(Record("BELIEF", "b:1", {"prop": "(has me silver_coin)"}),
                         Record("BELIEF", "b:2", {"prop": "(has me silver_coin:0)"}),
                         Record("BELIEF", "b:3", {"prop": "(has me silver_coin:250)"}),
                         Record("BELIEF", "b:4", {"prop": "(worth silver_coin 40)"}),
                         Record("BELIEF", "b:5", {"prop": "(worth silver_coin 10000000)"}))

    def ok_names_beyond_64(self):
        link = lambda a: f"(link n:{a} friend n:{a + 1000})"  # noqa: E731
        recs = [Record("BELIEF", f"b:{i + 1}", {"prop": link(i + 100)}) for i in range(12)]
        recs += [Record("MEMORY", f"m:{i + 1}", {"prop": f"(past (did n:{i + 200} give silver_coin (to n:{i + 300})))"})
                 for i in range(9)]
        recs += [Record("GOAL", f"g:{i + 1}", {"prop": link(i + 500)}) for i in range(4)]
        recs += [Record("ENTITY", f"@E{i + 1}", {"name": f"n:{i + 600}"}) for i in range(10)]
        return self.base(*recs)

    def ok_held_pooling(self):
        return DecisionContext([Record("SELF", "me", {"held": [{"mass": 2.0, "edge": 3, "temperature": -5.0},
                                                               {"mass": 5.0, "edge": 7, "temperature": 20.0}]}),
                                Record("PLACE", "@PLACE", {})])

    def ok_wake_and_plan(self):
        return self.base(Record("GOAL", "g:1", {"prop": "(has me silver_coin)", "deadline": -5.0}),
                         Record("PLAN", "p:1", {"step": "walk", "next": "give", "goal": "g:1", "target": "me"}),
                         Record("WAKE", "wake", {"mode": "act", "cause": "timer", "trigger": "g:1", "urgency": 7.5}))

    def ok_absent_person(self):
        return self.base(Record("ENTITY", "@E1", {"present": False, "link": "friend", "rel.trust": 3, "name": "n:5"}))

    def ok_full_entities(self):
        n = self.tok.layout.types["ENTITY"].count
        return self.base(*[Record("ENTITY", f"@E{i + 1}", {"present": True, "dist": float(i + 1), "rel.trust": i - 5})
                           for i in range(n)])

    # ---- refused ----
    def bad_pointer_not_in_mind(self):
        return self.base(Record("BELIEF", "b:1", {"prop": "(owns me @T5)"}))

    def bad_negative_quantity(self):
        return self.base(Record("ENTITY", "@E1", {"dist": -1.0}))

    def bad_out_of_scale(self):
        return self.base(Record("ENTITY", "@E1", {"rel.trust": 10.5}))

    def bad_leading_zero_key(self):
        return self.base(Record("ENTITY", "@E01", {}))

    def bad_reserved_symbol(self):
        return self.base(Record("THING", "@T1", {"kind": "<pad>"}))

    def bad_missing_place(self):
        return DecisionContext([Record("SELF", "me", {})])

    def bad_absent_person_with_distance(self):
        return self.base(Record("ENTITY", "@E1", {"present": False, "dist": 3.0}))

    def bad_ungrammatical_proposition(self):
        return self.base(Record("BELIEF", "b:1", {"prop": "(owns me)"}))

    def bad_bool_for_number(self):
        return self.base(Record("ENTITY", "@E1", {"dist": True}))


class GoldenCases:
    def __init__(self, tok: Tokenizer):
        self.tok = tok

    def expect(self, ctx: DecisionContext, valid: bool) -> dict:
        try:
            e = self.tok.encode(ctx)
        except TokenError:
            if valid:
                raise
            return {"error": "TokenError"}
        if not valid:
            raise AssertionError("a case meant to be refused was accepted")
        return {"digest": f"{e.digest():08x}", "n": e.n, "ghosts": list(e.ghosts)}

    def line(self, name: str, ctx: DecisionContext, valid: bool) -> str:
        return dumps({"name": name, "context": ctx.to_dict(self.tok), "expect": self.expect(ctx, valid)})

    def hand_lines(self) -> list[str]:
        return [self.line(n, c, v) for n, c, v in HandCases(self.tok).all()]

    def sampler_lines(self) -> list[str]:
        from situations.sampler import SituationSampler            # only needed to (re)write the cases
        s = SituationSampler(SAMPLER_SEED)
        return [self.line(f"sampler_{SAMPLER_SEED}_{i}", sit.context, True) for i in range(SAMPLER_CASES)
                for sit in [s.sample(i)]]

    def text(self) -> str:
        return "\n".join(self.sampler_lines() + self.hand_lines()) + "\n"


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    tok = Tokenizer()
    GOLDEN_DIR.mkdir(exist_ok=True)
    layout = GoldenLayout(tok).text()
    cases = GoldenCases(tok).text()
    stale = [p.name for p, t in ((LAYOUT_PATH, layout), (CASES_PATH, cases))
             if not p.exists() or p.read_text(encoding="utf-8") != t]
    if "--update" in args:
        LAYOUT_PATH.write_text(layout, encoding="utf-8")
        CASES_PATH.write_text(cases, encoding="utf-8")
        print(f"écrit {LAYOUT_PATH.name} ({len(layout) // 1024} Ko) et {CASES_PATH.name} "
              f"({cases.count(chr(10))} cas, {len(cases) // 1024} Ko)")
        return 0
    print("à jour" if not stale else "périmé : " + ", ".join(stale))
    return 1 if stale and "--check" in args else 0


if __name__ == "__main__":
    sys.exit(main())
