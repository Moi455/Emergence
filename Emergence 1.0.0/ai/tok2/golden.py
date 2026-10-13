"""golden.py - the golden files the C++ port (and the model code) are checked against.

    python3 -m tok2.golden                   (from ai/)  what would change
    python3 -m tok2.golden --update          rewrite golden/layout.json and the hand-made cases of golden/cases.jsonl;
                                             re-heads the frozen sampler cases by itself when the layout changed
    python3 -m tok2.golden --rehead          re-read the BODY of the frozen sampler cases, rewrite their header and
                                             digest, check that they still encode (nothing is redrawn)
    python3 -m tok2.golden --update-sampler  redraw the 12 cases from the situations sampler (a new draw)
    python3 -m tok2.golden --check           exit 1 when layout.json or the cases are out of date, or when a frozen
                                             case with a current header no longer gives the digest the file holds
                                             (--update and --rehead print a WARNING when a digest changes although the
                                             columns of the types of the case did not)
    (any other option is an error)

golden/layout.json  the contract, enough to write a port without reading Python:
                    - the layout document (Layout.document()): constants, arrays (dtype, shape), types (id, count, key),
                      their columns IN WRITE ORDER (block, column, width, codec kind, normalisation formula, scale, unit,
                      enum values, ref_types, vector components with their own columns), block widths, the vocabulary
                      id -> symbol, the table speech word -> input id (to tie the output speech embeddings to the input);
                    - `grammar`: the tables of catalogue/tools/language.py that type a proposition (word categories,
                      predicate arities and argument types, ACCEPTS, CATEGORY_TYPES, gesture parameters, event roles,
                      limits on symbols, nesting and pointers);
                    - `reading_rules`: the rules the tables do not say (bags, pointer lists, write order, pooling of
                      held objects, ghost numbering, names...);
                    - `fingerprints`. The LAYOUT fingerprint is the FNV-1a 64 (hex, 16 digits) of the canonical JSON
                      (sorted keys, separators , and :, UTF-8, no ASCII escapes) of this file WITHOUT the keys
                      `fingerprints`, `grammar` and `reading_rules`.
golden/cases.jsonl  about 30 canonical decisions, one per line: {name, context, expect}. A context is the canonical
                    JSON of a DecisionContext (header included: it names the interface and the layout it was
                    written for); expect is {digest (crc32, 8 hex), n, ghosts} or {error: "TokenError"}. Twelve come
                    from the situations sampler at a fixed seed and are FROZEN: their records are never redrawn by
                    --update or --check. When the layout changes their header and digest are renewed from the
                    SAME records (--rehead, called by --update; the encoding must still succeed). Only
                    --update-sampler draws new ones. The others are made by hand for the edges.
A port reads the context, encodes it, and must find the digest (the arrays are bit-identical) or the refusal.

Scope of the promise (also `scope` in layout.json): everything above is portable WITHOUT reading the Python, EXCEPT
the validation of propositions against the grammar of the catalogue, which is a port of catalogue/tools/language.py
fed with the tables of `grammar`. A port without that validation still produces the same arrays on valid contexts,
but does not refuse the propositions the grammar refuses (see the bad_prop_* cases).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from .errors import TokenError
from .interface import canonical_json, fnv1a64
from .layout import EXTRA_KEYS
from .tokenizer import DecisionContext, Record, Tokenizer

GOLDEN_DIR = Path(__file__).with_name("golden")
LAYOUT_PATH = GOLDEN_DIR / "layout.json"
CASES_PATH = GOLDEN_DIR / "cases.jsonl"
SAMPLER_SEED, SAMPLER_CASES = 0, 12
SAMPLER_PREFIX = "sampler_"


def dumps(obj, indent=None) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=False, indent=indent)


SCOPE = ("Portable without reading the Python: the columns, normalisations, vocabulary, key and name rules, "
         "ghost numbering, pooling, unknown flags, the digest and every refusal EXCEPT those of the grammar. NOT "
         "self-contained: the validation of propositions (types of arguments, arities, nesting depth, pointer budget, "
         "symbol count) is catalogue/tools/language.py (Expression), to be ported with the tables of `grammar`; "
         "the golden cases named bad_prop_* check that port.")

READING_RULES = [
    "Records: sort by type id (registry order), keep the given order within a type (the order is the salience the engine chose; never sort). SELF and PLACE are mandatory. Each key must be canonical and match its type's key; keys are unique; every key must be in known_keys (default: the keys of the records).",
    "Write order: for each row in order, for each column of its type in the order of types[T].columns (the registry's append order, NOT alphabetical), write the field if it is present and not null. This order fixes the numbering of the name aliases.",
    "Unknown versus empty: an absent or null field leaves value 0 and flag 0. A pointer '' writes 0 with ptr_known 1. A list [] sets the flag of every column of the list (bags: all 6 cat_known; pointer lists: all 4 ptr_known). A list-of-vectors [] writes 0 with known 1 on every component. A word field set to '' writes <pad> (id 0) with cat_known 1; '' is refused for enums and inside lists.",
    "Numbers: normalise in double precision with the column's `normalisation`, clamp to a bound if within epsilon of it (refuse beyond), round once to IEEE binary16 (nearest even), and write +0.0 whenever the half is zero (never -0.0). known=1.",
    "Vectors: a dict writes the named components (a missing one stays unknown); a list of values in the interface's component order writes all of them; a list of dicts pools per component before writing: SUM for the components in constants.pooled_by_sum (mass), MAX for the others; each item is validated on its own first. Every component has its own column (components[i].col): a vector that grew has its new components further on.",
    "Bags (lists of words or enum values): at most bag_cap items written in order from the bag's first column; pointer lists: at most ptr_list_cap items. Duplicates are kept.",
    "Words: a catalogue word of the interface (never a reserved <...> symbol or a pointer kind) -> its vocabulary id; a name n:<canonical int> -> <name k>, k = order of first appearance in the write order (0..63), then <name_other> for the 65th and later distinct names (the alias list is not extended). Enum fields accept only their `values`.",
    "Pointers: the slot (1-based row) of the record with that key. A key in known_keys but not in the batch is a ghost: 129 + k, k = rank of first appearance among ghosts when the arrays are scanned by row, then ptr columns in ascending order, then proposition positions in ascending order (ghosts are numbered AFTER writing, not while writing); the 33rd distinct ghost and later get 161. A key outside known_keys is refused. A pointer field accepts only the record types of its ref_types (for a ghost, the types its key can designate: @T is THING or INV). A proposition never cites its own record.",
    "Propositions: printable ASCII plus space, tab, newline and carriage return (CR) only, at most 1000 characters; validated by the `grammar` tables (a bare proposition, or for REQUEST.prop a full utterance with a mood); written in prefix order, one position per symbol: sym id, arity (0 leaf, 1 + number of arguments for a list head), depth, slot (pointers), num. A count n (silver_coin:3 or a bare 3) is log1p(n + 1) in binary16 (0 means no count); counts and numbers are canonical (ASCII digits, no leading zero, at most 1e7). A bare citation b:7 / m:7 / g:7 is a one-position proposition.",
    "Canonical text of a proposition (for serialization): re-print the tree, one space between symbols, no space inside parentheses.",
    "Digest: see `digest`; n is the number of rows written.",
]


# ---- layout.json ---------------------------------------------------------------------------------------
class GrammarExport:
    """The tables of catalogue/tools/language.py that a port needs to type a proposition."""

    def __init__(self, vocab):
        self.v = vocab

    def build(self) -> dict:
        import language
        v, cat = self.v, self.v.cat
        preds = {c.id: list(c.args) for c in sorted(cat["concept"].values(), key=lambda c: c.id) if c.category == "predicate"}
        gestures = {}
        for a in sorted(cat["action"].values(), key=lambda a: a.id):
            gestures[a.id] = [{"name": p.name, "type": p.type, **({"accepts": sorted(p.accepts)} if p.type == "ref" else {}),
                               **({"values": list(p.values)} if p.type == "enum" else {})} for p in a.params]
        return {
            "source": "catalogue/tools/language.py (Expression, Vocabulary.types, ref_targets): port those functions with these tables",
            "limits": {"max_symbols": language.MAX_SYMBOLS, "max_depth": language.MAX_DEPTH,
                       "max_pointers": language.MAX_POINTERS, "max_roles": language.MAX_ROLES},
            "pointer_regex": language.POINTER.pattern + " (ASCII digits; tok-2 additionally requires canonical numbers)",
            "nesting_heads": sorted(language.NESTING_HEADS),
            "description_categories": sorted(language.DESCRIPTION_CATEGORIES),
            "ref_words": {w: sorted(t) for w, t in sorted(language.REF_WORDS.items())},
            "category_types": {c: sorted(t) for c, t in sorted(language.CATEGORY_TYPES.items())},
            "accepts": {c: sorted(t) for c, t in sorted(language.ACCEPTS.items())},
            "word_categories": {w: sorted(cs) for w, cs in sorted(v.cats.items())},
            "directions": list(v.directions),
            "predicates": preds,
            "event_roles": sorted(w for w, cs in v.cats.items() if "event_role" in cs),
            "gestures": gestures,
            "species": sorted(cat["species"]), "forms": sorted(cat["form"]),
            "kinds": sorted(v.kinds),
        }


class GoldenLayout:
    def __init__(self, tok: Tokenizer):
        self.tok = tok

    def build(self) -> dict:
        tok = self.tok
        doc = dict(tok.layout.document())
        doc["fingerprints"] = tok.header() | {"vocabulary": f"{tok.vocab.fingerprint:016x}"}
        doc["grammar"] = GrammarExport(tok.props.grammar.vocab).build()
        doc["reading_rules"] = list(READING_RULES)
        doc["scope"] = SCOPE
        return doc

    @staticmethod
    def fingerprint_of(doc: dict) -> str:
        """What a port recomputes: the layout fingerprint of a layout.json document."""
        core = {k: v for k, v in doc.items() if k not in EXTRA_KEYS}
        return f"{fnv1a64(canonical_json(core)):016x}"

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

    def ok_zero_after_rounding(self):
        return DecisionContext([Record("SELF", "me", {"need.thermal": -1e-9, "body.pain": 1e-12}),
                                Record("PLACE", "@PLACE", {}),
                                Record("GOAL", "g:1", {"prop": "(has me silver_coin)", "deadline": -1e-9})])

    def ok_epsilon_at_the_bounds(self):
        return DecisionContext([Record("SELF", "me", {"need.thirst": 10.0000000001, "need.thermal": -10.0000000001,
                                                      "body.load": 1 + 1e-10, "age": -1e-10}),
                                Record("PLACE", "@PLACE", {"crowd": 0})])

    def ok_empty_word_and_citation(self):
        return self.base(Record("GOAL", "g:1", {"prop": "(has me silver_coin)"}),
                         Record("PLAN", "p:1", {"goal": "g:1", "step": "walk", "next": ""}),
                         Record("BELIEF", "b:1", {"prop": "g:1"}), Record("BELIEF", "b:2", {"prop": "(that b:1)"}),
                         Record("BELIEF", "b:3", {"prop": " m:7 "}), known=["me", "@PLACE", "g:1", "p:1", "b:1", "b:2", "b:3", "m:7"])

    def ok_canonical_proposition(self):
        return self.base(Record("THING", "@T1", {}), Record("BELIEF", "b:1", {"prop": "( owns\n  me\t@T1 )"}))

    def ok_write_order_names(self):
        return self.base(Record("MEMORY", "m:1", {"prop": "(past (did n:5 give silver_coin (to me)))", "interp": "n:9"}),
                         Record("ENTITY", "@E1", {"name": "n:5"}))

    def ok_ref_kinds(self):
        return self.base(Record("ENTITY", "@E1", {}), Record("THING", "@T1", {"owner": "@E1"}),
                         Record("THING", "@T2", {"owner": "me"}), Record("REQUEST", "q:1", {"from": "@E1"}),
                         Record("WAKE", "wake", {"trigger": "q:1", "cause": "request"}),
                         Record("SELF_STATE", "me.state", {"attention": "@T9"}), known=[
                             "me", "@PLACE", "me.state", "@E1", "@T1", "@T2", "@T9", "q:1", "wake"])

    def ok_epsilon_unit_components(self):
        return DecisionContext([
            Record("SELF", "me", {}), Record("PLACE", "@PLACE", {}),
            Record("ENTITY", "@E1", {"present": True, "dir": {"sin": 1 + 1e-10, "cos": -1 - 1e-10},
                                     "rep": {"honesty": 1 + 1e-10, "danger": -1 - 1e-10}})])

    def ok_time_until_bounds(self):
        return self.base(Record("GOAL", "g:1", {"prop": "(has me silver_coin)", "deadline": 10_000_000}),
                         Record("GOAL", "g:2", {"prop": "(has me silver_coin)", "deadline": -10_000_000}),
                         Record("COMMIT", "c:1", {"prop": "(did me give silver_coin (to me))", "deadline": 1e7}))

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

    def bad_pointer_of_the_wrong_kind(self):
        return self.base(Record("ENTITY", "@E1", {}), Record("WAKE", "wake", {"trigger": "@E1"}))

    def bad_ghost_of_the_wrong_kind(self):
        return self.base(Record("BELIEF", "b:1", {"informant": "@T9"}), known=["me", "@PLACE", "b:1", "@T9"])

    def bad_proposition_cites_itself(self):
        return self.base(Record("BELIEF", "b:1", {"prop": "(that b:1)"}))

    def bad_non_ascii_space(self):
        return self.base(Record("THING", "@T1", {}), Record("BELIEF", "b:1", {"prop": "(owns\u00a0me @T1)"}))

    def bad_key_with_newline(self):
        return self.base(Record("ENTITY", "@E1\n", {}))

    def bad_beyond_epsilon(self):
        return DecisionContext([Record("SELF", "me", {"need.thirst": 10.00000001}), Record("PLACE", "@PLACE", {})])

    def bad_time_until_beyond(self):
        # no tolerance window at 1e7: the spacing of doubles there (1.9e-9) is wider than epsilon (1e-9)
        return self.base(Record("GOAL", "g:1", {"prop": "(has me silver_coin)", "deadline": 1e7 + 1e-8}))

    def bad_prop_wrong_argument_type(self):
        return self.base(Record("BELIEF", "b:1", {"prop": "(link me friend silver_coin)"}))

    def bad_prop_depth_3(self):
        return self.base(Record("BELIEF", "b:1", {"prop": "(believes me (believes you (believes me (owns me @T1))))"}),
                         Record("THING", "@T1", {}))

    def bad_prop_four_pointers(self):
        # also ill-typed: the pointer budget (3 per predicate) is one of the problems the grammar reports
        return self.base(Record("ENTITY", "@E1", {}), Record("ENTITY", "@E2", {}), Record("ENTITY", "@E3", {}),
                         Record("ENTITY", "@E4", {}), Record("BELIEF", "b:1", {"prop": "(attitude @E1 @E2 @E3 @E4)"}))

    def bad_prop_too_many_symbols(self):
        return self.base(Record("BELIEF", "b:1", {"prop": "(and " * 18 + "(at me @PLACE)" + ")" * 18}))

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
        """Drawn from the situations sampler NOW (only --update-sampler does this)."""
        from situations.sampler import SituationSampler            # only needed to (re)write these cases
        s = SituationSampler(SAMPLER_SEED)
        return [self.line(f"{SAMPLER_PREFIX}{SAMPLER_SEED}_{i}", sit.context, True) for i in range(SAMPLER_CASES)
                for sit in [s.sample(i)]]

    @staticmethod
    def frozen_sampler_lines() -> list[str]:
        if not CASES_PATH.exists():
            return []
        return [l for l in CASES_PATH.read_text(encoding="utf-8").splitlines()
                if json.loads(l)["name"].startswith(SAMPLER_PREFIX)]

    def rehead_line(self, line: str) -> str:
        """The same records, a fresh header and digest. The encoding must still succeed."""
        case = json.loads(line)
        body = case["context"]
        try:
            ctx = DecisionContext([Record.from_dict(r) for r in body["records"]], body["known_keys"])
            return self.line(case["name"], ctx, True)
        except TokenError as e:
            raise TokenError(f"frozen case {case['name']} no longer encodes: {e}") from None

    def verify_line(self, line: str) -> None:
        """Re-encode a frozen case whose header is current: digest, n and ghosts must be what the file says."""
        case = json.loads(line)
        got = json.loads(self.rehead_line(line))["expect"]
        if got != case["expect"]:
            raise TokenError(f"frozen case {case['name']}: the header is current but the encoding changed "
                             f"(file {case['expect']}, now {got}). A regression of the tokenizer, or an intended change "
                             "that must be blessed with `python3 -m tok2.golden --rehead`")

    def frozen(self, rehead: bool = False) -> list[str]:
        """The frozen sampler cases: verbatim, unless their header is stale (the layout changed) or `rehead`.
        A case with a current header is re-encoded and must give the digest the file holds (it is never trusted)."""
        out = []
        for line in self.frozen_sampler_lines():
            stale = json.loads(line)["context"]["header"] != self.tok.header()
            if rehead or stale:
                out.append(self.rehead_line(line))
            else:
                self.verify_line(line)
                out.append(line)
        return out

    def text(self, regenerate_sampler: bool = False, rehead: bool = False) -> str:
        frozen = self.sampler_lines() if regenerate_sampler or not self.frozen_sampler_lines() else self.frozen(rehead)
        return "\n".join(frozen + self.hand_lines()) + "\n"


def suspicious_changes(old_cases: str, new_cases: str, old_layout: dict | None, new_layout: dict) -> list[str]:
    """Cases whose digest changed although every token type they use has exactly the same columns, ids, counts and
    keys as before: the layout did not explain it, so a regression may be about to be blessed."""
    if not old_cases or old_layout is None:
        return []
    old = {json.loads(l)["name"]: json.loads(l) for l in old_cases.splitlines()}
    out = []
    for line in new_cases.splitlines():
        new = json.loads(line)
        was = old.get(new["name"])
        if was is None or was["expect"] == new["expect"]:
            continue
        types = {r["type"] for r in new["context"]["records"]}
        if all(old_layout["types"].get(t) == new_layout["types"].get(t) for t in types):
            out.append(f"{new['name']}: {was['expect'].get('digest', was['expect'])} -> {new['expect'].get('digest', new['expect'])}")
    return out


FLAGS = {"--update", "--update-sampler", "--rehead", "--check"}


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    unknown = [a for a in args if a not in FLAGS]
    if unknown:
        print(f"option inconnue : {', '.join(unknown)} (options : {', '.join(sorted(FLAGS))})", file=sys.stderr)
        return 2
    tok = Tokenizer()
    GOLDEN_DIR.mkdir(exist_ok=True)
    gl = GoldenLayout(tok)
    layout = gl.text()
    try:
        cases = GoldenCases(tok).text(regenerate_sampler="--update-sampler" in args, rehead="--rehead" in args)
    except TokenError as e:
        print(f"ÉCHEC : {e}", file=sys.stderr)
        return 1
    stale = [p.name for p, t in ((LAYOUT_PATH, layout), (CASES_PATH, cases))
             if not p.exists() or p.read_text(encoding="utf-8") != t]
    writing = any(a in args for a in ("--update", "--update-sampler", "--rehead"))
    if writing:
        old_cases = CASES_PATH.read_text(encoding="utf-8") if CASES_PATH.exists() else ""
        old_layout = json.loads(LAYOUT_PATH.read_text(encoding="utf-8")) if LAYOUT_PATH.exists() else None
        for w in suspicious_changes(old_cases, cases, old_layout, gl.build()):
            print(f"ATTENTION : l'empreinte change alors que les colonnes des types du cas sont inchangées "
                  f"(régression possible, vérifier avant de valider) : {w}", file=sys.stderr)
    if "--update" in args or "--update-sampler" in args:
        LAYOUT_PATH.write_text(layout, encoding="utf-8")
        CASES_PATH.write_text(cases, encoding="utf-8")
        print(f"écrit {LAYOUT_PATH.name} ({len(layout) // 1024} Ko) et {CASES_PATH.name} "
              f"({cases.count(chr(10))} cas, {len(cases) // 1024} Ko)"
              + (" ; cas du sampler redessinés" if "--update-sampler" in args else " ; cas du sampler gelés (en-tête renouvelé si besoin)"))
        return 0
    if "--rehead" in args:
        CASES_PATH.write_text(cases, encoding="utf-8")
        print(f"en-tête et empreintes des cas gelés renouvelés dans {CASES_PATH.name} (rien n'est redessiné)")
        return 0
    print("à jour" if not stale else "périmé : " + ", ".join(stale))
    return 1 if stale and "--check" in args else 0


if __name__ == "__main__":
    sys.exit(main())
