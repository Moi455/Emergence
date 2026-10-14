"""tok-2 refuses bad input with a TokenError, always (python3 -m unittest discover -s ai/tok2/tests -t ai)."""
from __future__ import annotations

import copy
import random
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tok2 import DecisionContext, Record, TokenError, Tokenizer  # noqa: E402
from tok2.tests.test_tok2 import base, ctx  # noqa: E402

TOK = Tokenizer()


class Refusals(unittest.TestCase):
    def refuses(self, *records, known=None):
        with self.assertRaises(TokenError):
            TOK.encode(base(*records, known=known))

    def accepts(self, *records, known=None):
        return TOK.encode(base(*records, known=known))

    # ---- M1: digits are ASCII, keys and numbers are canonical ---------------------------------------
    def test_non_ascii_digits_are_refused(self):
        self.refuses(Record("ENTITY", "@E٣", {}))                                   # Arabic-Indic three
        self.refuses(Record("BELIEF", "b:1", {"prop": "(owns me @T٣)"}), known=["me", "@PLACE", "b:1", "@T3"])
        self.refuses(Record("BELIEF", "b:1", {"prop": "(has me silver_coin:²)"}))
        self.refuses(Record("BELIEF", "b:1", {"prop": "(worth silver_coin ٣)"}))
        self.refuses(Record("BELIEF", "b:1", {"informant": "@E٣"}))

    def test_keys_are_canonical(self):
        self.refuses(Record("ENTITY", "@E01", {}))
        self.refuses(Record("BELIEF", "b:007", {}))
        self.refuses(Record("BELIEF", "b:1", {"prop": "(owns me @T07)"}), known=["me", "@PLACE", "b:1", "@T7"])
        self.refuses(Record("BELIEF", "b:1", {"prop": "(has me silver_coin:03)"}))
        self.refuses(Record("BELIEF", "b:1", {"prop": "(worth silver_coin 007)"}))
        self.refuses(Record("ENTITY", "@E1", {"name": "n:017"}))
        self.refuses(Record("ENTITY", "@E" + "9" * 13, {}))
        self.accepts(Record("ENTITY", "@E0", {"name": "n:0"}))
        self.accepts(Record("ENTITY", "@E" + "9" * 12, {}))

    def test_enormous_numbers_are_a_token_error(self):
        self.refuses(Record("BELIEF", "b:1", {"prop": "(has me silver_coin:" + "9" * 400 + ")"}))
        self.refuses(Record("ENTITY", "@E1", {"dist": 10 ** 400}))
        self.refuses(Record("ENTITY", "@E1", {"dist": 1e300}))
        self.refuses(Record("ENTITY", "@E1", {"dist": float("inf")}))
        self.refuses(Record("ENTITY", "@E1", {"rel.trust": 10 ** 400}))

    def test_wrong_shapes_are_a_token_error(self):
        self.refuses(Record("ENTITY", "@E1", {"dist": [1]}))
        self.refuses(Record("ENTITY", "@E1", {"dist": "3"}))
        self.refuses(Record("ENTITY", "@E1", {"link": ["friend"]}))
        self.refuses(Record("ENTITY", "@E1", {"link": 3}))
        self.refuses(Record("ENTITY", "@E1", {"look.attire": "tattered"}))
        self.refuses(Record("ENTITY", "@E1", {"look.attire": [["tattered"]]}))
        self.refuses(Record("ENTITY", "@E1", {"look.gaze": 4}))
        self.refuses(Record("ENTITY", "@E1", {"look.gaze": ["me"]}))
        self.refuses(Record("ENTITY", "@E1", {"dir": "up"}))
        self.refuses(Record("ENTITY", "@E1", {"dir": []}))                                # [] only for a list of vectors
        self.refuses(Record("ENTITY", "@E1", {"dir": {"sin": "x", "cos": 0}}))
        self.refuses(Record("BELIEF", "b:1", {"prop": 12}))
        self.refuses(Record("BELIEF", "b:1", {"prop": ["owns"]}))
        self.refuses(Record("BELIEF", "b:1", {"prop": "(" * 5000}))
        self.refuses(Record("BELIEF", "b:1", {"prop": "(not " * 400 + "(owns me @PLACE)" + ")" * 400}))
        self.refuses(Record("ENTITY", 5, {}))
        self.refuses(Record(5, "@E1", {}))
        with self.assertRaises(TokenError):
            TOK.encode(DecisionContext([Record("SELF", "me", None), Record("PLACE", "@PLACE", {})]))
        with self.assertRaises(TokenError):
            TOK.encode(DecisionContext("not a list"))
        with self.assertRaises(TokenError):
            TOK.encode(DecisionContext(base().records, known_keys=["nonsense"]))

    # ---- M2: numpy scalars are fine -----------------------------------------------------------------
    def test_numpy_scalars_are_accepted_and_give_the_same_arrays(self):
        plain = base(Record("ENTITY", "@E1", {"dist": 3.0, "rel.trust": -4, "present": True,
                                              "dir": {"sin": 0.5, "cos": 0.25}, "rep": {"honesty": 0.5}}))
        np_ = base(Record("ENTITY", "@E1", {"dist": np.float64(3.0), "rel.trust": np.int64(-4), "present": np.bool_(True),
                                            "dir": {"sin": np.float32(0.5), "cos": np.float16(0.25)},
                                            "rep": {"honesty": np.float32(0.5)}}))
        self.assertEqual(TOK.encode(plain).digest(), TOK.encode(np_).digest())
        self.refuses(Record("ENTITY", "@E1", {"dist": np.array([1.0, 2.0])}))
        self.refuses(Record("ENTITY", "@E1", {"present": np.int64(1)}))

    # ---- M5: names ------------------------------------------------------------------------------------
    def test_more_than_64_names_share_name_other(self):
        link = lambda a: f"(link n:{a} friend n:{a + 1000})"  # noqa: E731
        recs = [Record("BELIEF", f"b:{i + 1}", {"prop": link(i + 100)}) for i in range(12)]
        recs += [Record("MEMORY", f"m:{i + 1}", {"prop": f"(past (did n:{i + 200} give silver_coin (to n:{i + 300})))"}) for i in range(9)]
        recs += [Record("HEARD", f"h:{i + 1}", {"prop": link(i + 400)}) for i in range(2)]
        recs += [Record("GOAL", f"g:{i + 1}", {"prop": link(i + 500)}) for i in range(4)]
        recs += [Record("ENTITY", f"@E{i + 1}", {"name": f"n:{i + 600}"}) for i in range(10)]
        recs += [Record("COMMIT", f"c:{i + 1}", {"prop": f"(did me give silver_coin (to n:{i + 700}))"}) for i in range(3)]
        e = TOK.encode(base(*recs))
        self.assertEqual(len(e.names), 64)
        other = TOK.vocab.id("<name_other>")
        self.assertIn(other, set(int(x) for x in e.prop_sym.flat))

    # ---- M3 / L7: quantities --------------------------------------------------------------------------
    def test_quantities_are_not_negative_except_degrees(self):
        self.refuses(Record("ENTITY", "@E1", {"dist": -1.0}))
        self.refuses(Record("SELF", "me", {"age": -3}))
        self.refuses(Record("PLACE", "@PLACE", {"crowd": -1}))
        self.refuses(Record("SELF", "me", {"held": [{"mass": -1.0}]}))
        self.refuses(Record("ENTITY", "@E1", {"dist": 1.0e7 + 1}))
        self.refuses(Record("BELIEF", "b:1", {"age": -1.0}))
        e = TOK.encode(DecisionContext([Record("SELF", "me", {"held": [{"temperature": -12.0}]}),
                                        Record("PLACE", "@PLACE", {})]))
        c = TOK.layout.types["SELF"].columns["held"].col + TOK.interface.object_vector.index("temperature")
        self.assertLess(float(e.num[e.keys.index("me"), c]), 0)
        self.refuses(Record("SELF", "me", {"held": [{"temperature": -1.0e8}]}))

    # ---- L8 / charter units ---------------------------------------------------------------------------
    def test_records_are_in_the_units_of_the_charter(self):
        """Psychological scales -10..10 (unipolar 0..10), refused outside; the tokenizer divides by 10."""
        e = TOK.encode(base(Record("ENTITY", "@E1", {"rel.trust": 10, "rel.fear": 10, "rel.affection": -10})))
        r = e.keys.index("@E1")
        col = lambda f: TOK.layout.types["ENTITY"].columns[f].col  # noqa: E731
        self.assertEqual(float(e.num[r, col("rel.trust")]), 1.0)
        self.assertEqual(float(e.num[r, col("rel.affection")]), -1.0)
        self.refuses(Record("ENTITY", "@E1", {"rel.trust": 10.01}))
        self.refuses(Record("ENTITY", "@E1", {"rel.fear": 10.5}))
        self.refuses(Record("ENTITY", "@E1", {"rel.trust": -10.5}))
        self.refuses(Record("ENTITY", "@E1", {"rel.affection": 100}))               # a percentage

    # ---- M7: reserved symbols --------------------------------------------------------------------------
    def test_reserved_symbols_are_refused_in_word_fields(self):
        for bad in ("<pad>", "<unk>", "<num>", "<name0>", "<name_other>", "@E", "b:"):
            self.refuses(Record("THING", "@T1", {"kind": bad}))
            self.refuses(Record("ENTITY", "@E1", {"look.attire": [bad]}))
            self.refuses(Record("TASTE", "t:1", {"concept": bad}))
        self.refuses(Record("BELIEF", "b:1", {"prop": "(owns me <num>)"}))
        self.refuses(Record("BELIEF", "b:1", {"prop": "(owns me <pad>)"}))

    # ---- M9: SELF and PLACE are mandatory ---------------------------------------------------------------
    def test_self_and_place_are_mandatory(self):
        with self.assertRaises(TokenError):
            TOK.encode(DecisionContext([Record("PLACE", "@PLACE", {})]))
        with self.assertRaises(TokenError):
            TOK.encode(DecisionContext([Record("SELF", "me", {})]))
        with self.assertRaises(TokenError):
            TOK.encode(DecisionContext([]))

    # ---- L10: an absent person is not seen --------------------------------------------------------------
    def test_an_absent_person_has_no_distance_direction_or_appearance(self):
        self.accepts(Record("ENTITY", "@E1", {"present": False, "link": "friend", "rel.trust": 3}))
        for f, v in (("dist", 3.0), ("dir", {"sin": 0, "cos": 1}), ("look.sex", "male"), ("look.attire", ["tattered"]),
                     ("look.gaze", "me"), ("look.wounds", 1.0)):
            self.refuses(Record("ENTITY", "@E1", {"present": False, f: v}))
        self.accepts(Record("ENTITY", "@E1", {"present": True, "dist": 3.0, "look.sex": "male"}))
        self.accepts(Record("ENTITY", "@E1", {"present": False, "dist": None}))

    # ---- M7': propositions go through the grammar of the catalogue ----------------------------------------
    def test_propositions_are_typed_by_the_catalogue_grammar(self):
        self.accepts(Record("BELIEF", "b:1", {"prop": "(owns me @T1)"}), known=["me", "@PLACE", "b:1", "@T1"])
        self.refuses(Record("BELIEF", "b:1", {"prop": "(owns me)"}))                    # arity
        self.refuses(Record("BELIEF", "b:1", {"prop": "(link me friend silver_coin)"}))        # a kind is not a person
        self.refuses(Record("BELIEF", "b:1", {"prop": "(assert (owns me @T1))"}), known=["me", "@PLACE", "b:1", "@T1"])
        self.refuses(Record("BELIEF", "b:1", {"prop": "owns"}))
        self.refuses(Record("GOAL", "g:1", {"prop": "(request (did me give silver_coin (to me)))"}))
        self.accepts(Record("REQUEST", "q:1", {"prop": "(request (did me give silver_coin (to me)))"}))
        self.refuses(Record("REQUEST", "q:1", {"prop": "(owns me silver_coin)"}))        # a request is an utterance

    # ---- fuzz: whatever garbage, nothing but a TokenError ---------------------------------------------------
    def test_fuzz_only_token_errors(self):
        rng = random.Random(7)
        garbage = [None, True, False, 0, 1, -1, 3.5, -0.0, 1e300, float("nan"), float("inf"), 10 ** 30, "", "x", "me", "@E1",
                   "b:1", "n:3", "<pad>", "(", ")", "(owns me @T1)", "٣", "w_poor", "seen", [], [1], ["me"], {}, {"sin": 1},
                   {"mass": 2}, [{"mass": 1}], np.float32(2), np.int8(3), np.bool_(True), (1, 2), b"bytes", object()]
        good = ctx()
        raised = 0
        for _ in range(1500):
            c = copy.deepcopy(good)
            rec = rng.choice(c.records)
            spec = TOK.interface.token_types[rec.type]["fields"]
            field = rng.choice(sorted(spec))
            rec.fields[field] = rng.choice(garbage)
            if rng.random() < 0.1:
                rec.key = rng.choice(garbage) if isinstance(rng.choice(garbage), str) else 5
            try:
                TOK.encode(c)
            except TokenError:
                raised += 1
        self.assertGreater(raised, 300)

    def test_fuzz_propositions_only_token_errors(self):
        rng = random.Random(11)
        pieces = ["(", ")", "(", ")", "owns", "me", "you", "@T1", "@E1", "b:1", "n:3", "n:03", "silver_coin", "silver_coin:3",
                  "3", "03", "\u0663", "<num>", "<pad>", "not", "and", "past", "did", "give", "(to", "@PLACE", "x:y", ":", "::",
                  "ask", "request", "where", "\x00", "\u202e", "w_poor", "that", "(that b:1)"]
        known = ["me", "@PLACE", "b:1", "@T1", "@E1"]
        for kind, key in (("BELIEF", "b:1"), ("GOAL", "g:1"), ("REQUEST", "q:1")):
            ok = 0
            for _ in range(600):
                text = " ".join(rng.choice(pieces) for _ in range(rng.randint(1, 12)))
                try:
                    TOK.encode(base(Record(kind, key, {"prop": text}), known=known + [key]))
                    ok += 1
                except TokenError:
                    pass
            self.assertLess(ok, 600)


if __name__ == "__main__":
    unittest.main()
