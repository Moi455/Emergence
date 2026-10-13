"""The golden files are current and pin the digests (python3 -m unittest discover -s ai/tok2/tests -t ai).
To refresh them after an intended change: python3 -m tok2.golden --update (from ai/), and say why."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tok2 import DecisionContext, TokenError, Tokenizer  # noqa: E402
from tok2.golden import CASES_PATH, LAYOUT_PATH, READING_RULES, GoldenCases, GoldenLayout, HandCases  # noqa: E402

TOK = Tokenizer()
REFRESH = ("run `python3 -m tok2.golden --update` from ai/ (and `--update-sampler` to redraw the 12 frozen sampler "
           "cases when the layout changed), and say why the contract changed")


class TestGoldenLayout(unittest.TestCase):
    def test_layout_json_is_current(self):
        self.assertEqual(LAYOUT_PATH.read_text(encoding="utf-8"), GoldenLayout(TOK).text(), REFRESH)

    def test_layout_json_has_what_a_port_needs(self):
        g = json.loads(LAYOUT_PATH.read_text(encoding="utf-8"))
        self.assertEqual({k: g["constants"][k] for k in ("none_slot", "ghost_base", "ghost_overflow")},
                         {"none_slot": 0, "ghost_base": 129, "ghost_overflow": 161})
        self.assertEqual(len(g["vocabulary"]), len(TOK.vocab))
        self.assertEqual(g["vocabulary"][0], "<pad>")
        col = next(c for c in g["types"]["GOAL"]["columns"] if c["name"] == "deadline")
        self.assertEqual((col["codec"], col["scale"]), ("ScalarCodec", "time_until"))
        self.assertIn("copysign", col["normalisation"])
        mode = next(c for c in g["types"]["WAKE"]["columns"] if c["name"] == "mode")
        self.assertEqual(mode["values"], ["act", "listen", "reflect"])
        for word, i in g["speech_to_input"].items():                       # the tie between speech and input
            self.assertEqual(g["vocabulary"][i], word)
        self.assertEqual(set(g["speech_to_input"]), set(TOK.interface.grammar_words) | set(TOK.interface.kinds))
        names = [a["name"] for a in g["arrays"]]
        self.assertEqual(names, list(TOK.encode(HandCases.base()).ARRAYS))
        self.assertEqual({a["dtype"] for a in g["arrays"]}, {"uint8", "int16", "float16"})


    def test_the_layout_fingerprint_can_be_recomputed_from_the_file(self):
        """A port computes FNV-1a 64 of the canonical JSON of layout.json without its extra keys."""
        g = json.loads(LAYOUT_PATH.read_text(encoding="utf-8"))
        self.assertEqual(GoldenLayout.fingerprint_of(g), g["fingerprints"]["layout"])
        self.assertEqual(g["fingerprints"]["layout"], f"{TOK.layout.fingerprint:016x}")
        g["constants"]["bag_cap"] = 7
        self.assertNotEqual(GoldenLayout.fingerprint_of(g), f"{TOK.layout.fingerprint:016x}")
        # the grammar and the rules are NOT part of it (they do not change any array)
        h = json.loads(LAYOUT_PATH.read_text(encoding="utf-8"))
        h["grammar"]["limits"]["max_symbols"] = 99
        self.assertEqual(GoldenLayout.fingerprint_of(h), h["fingerprints"]["layout"])

    def test_columns_are_listed_in_write_order_with_their_own_columns(self):
        g = json.loads(LAYOUT_PATH.read_text(encoding="utf-8"))
        for name, t in g["types"].items():
            self.assertEqual([c["name"] for c in t["columns"]], list(TOK.layout.types[name].columns), name)
        held = next(c for c in g["types"]["SELF"]["columns"] if c["name"] == "held")
        self.assertEqual([c["name"] for c in held["components"]], TOK.interface.object_vector)
        self.assertEqual(held["components"][0]["unit"], "kg")
        self.assertIn("log1p", held["components"][0]["normalisation"])
        gaze = next(c for c in g["types"]["ENTITY"]["columns"] if c["name"] == "look.gaze")
        self.assertEqual(gaze["ref_types"], ["ENTITY", "THING", "INV", "SELF", "LOCUS", "PLACE"])
        self.assertTrue(held["multi"])
        self.assertEqual(held["components"][0]["pool"], "sum")
        self.assertEqual(held["components"][1]["pool"], "max")
        props = next(c for c in g["types"]["THING"]["columns"] if c["name"] == "props")
        self.assertFalse(props["multi"])

    def test_the_grammar_section_carries_the_tables_of_language_py(self):
        g = json.loads(LAYOUT_PATH.read_text(encoding="utf-8"))["grammar"]
        self.assertEqual(g["limits"], {"max_symbols": 20, "max_depth": 2, "max_pointers": 3, "max_roles": 3})
        self.assertEqual(g["predicates"]["owns"], ["entity", "entity"])
        self.assertIn("proposition", g["accepts"])
        self.assertIn("kind_qty", g["category_types"])
        self.assertEqual(g["word_categories"]["owns"], ["predicate"])
        self.assertIn("with", g["event_roles"])
        self.assertIn("give", g["gestures"])
        self.assertTrue(any(p["type"] == "ref" and p["accepts"] for p in g["gestures"]["give"]))
        self.assertEqual(set(g["ref_words"]["me"]), {"agent", "entity"})
        self.assertIn("believes", g["nesting_heads"])

    def test_the_reading_rules_are_written(self):
        g = json.loads(LAYOUT_PATH.read_text(encoding="utf-8"))
        self.assertEqual(g["reading_rules"], READING_RULES)
        text = " ".join(READING_RULES)
        for word in ("Bags", "pointer lists", "Write order", "SUM", "ghost", "binary16", "<pad>", "ref_types"):
            self.assertIn(word, text)


class TestGoldenCases(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = [json.loads(line) for line in CASES_PATH.read_text(encoding="utf-8").splitlines()]

    def test_about_thirty_cases_of_both_kinds(self):
        self.assertGreaterEqual(len(self.cases), 30)
        self.assertGreater(sum("error" in c["expect"] for c in self.cases), 5)
        self.assertEqual(len({c["name"] for c in self.cases}), len(self.cases))

    def test_every_digest_is_pinned(self):
        for c in self.cases:
            ctx = DecisionContext.loads(json.dumps(c["context"]), TOK)        # the header must match too
            if "error" in c["expect"]:
                with self.assertRaises(TokenError, msg=c["name"]):
                    TOK.encode(ctx)
                continue
            e = TOK.encode(ctx)
            self.assertEqual(f"{e.digest():08x}", c["expect"]["digest"], f"{c['name']}: {REFRESH}")
            self.assertEqual(e.n, c["expect"]["n"], c["name"])
            self.assertEqual(e.ghosts, c["expect"]["ghosts"], c["name"])

    def test_the_sampler_cases_are_frozen(self):
        """--update and --check never redraw them; only --update-sampler does."""
        names = [c["name"] for c in self.cases]
        self.assertEqual(sum(n.startswith("sampler_") for n in names), 12)
        self.assertEqual(GoldenCases(TOK).text(), CASES_PATH.read_text(encoding="utf-8"), REFRESH)

    def test_the_hand_made_cases_are_current(self):
        written = {json.loads(l)["name"]: l for l in CASES_PATH.read_text(encoding="utf-8").splitlines()}
        for line in GoldenCases(TOK).hand_lines():
            self.assertEqual(written[json.loads(line)["name"]], line, REFRESH)

    def test_the_edges_are_covered(self):
        names = {c["name"] for c in self.cases}
        for need in ("ok_zero_after_rounding", "ok_epsilon_at_the_bounds", "ok_empty_word_and_citation",
                     "ok_canonical_proposition", "ok_write_order_names", "ok_ref_kinds", "bad_pointer_of_the_wrong_kind",
                     "bad_proposition_cites_itself", "bad_non_ascii_space", "bad_key_with_newline", "bad_beyond_epsilon",
                     "ok_ghost_overflow", "ok_known_versus_empty", "ok_deadlines_signed", "ok_half_rounding",
                     "ok_counts", "ok_names_beyond_64", "ok_wake_and_plan", "ok_held_pooling", "bad_pointer_not_in_mind"):
            self.assertIn(need, names)
        self.assertGreaterEqual(sum(n.startswith("sampler_") for n in names), 10)

    def test_the_pairs_that_must_differ_do_differ(self):
        d = {c["name"]: c["expect"].get("digest") for c in self.cases}
        self.assertNotEqual(d["ok_ghost_same"], d["ok_ghost_different"])


if __name__ == "__main__":
    unittest.main()
