"""The golden files are current and pin the digests (python3 -m unittest discover -s ai/tok2/tests -t ai).
To refresh them after an intended change: python3 -m tok2.golden --update (from ai/), and say why."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tok2 import DecisionContext, TokenError, Tokenizer  # noqa: E402
from tok2.golden import CASES_PATH, LAYOUT_PATH, GoldenCases, GoldenLayout, HandCases  # noqa: E402

TOK = Tokenizer()
REFRESH = "run `python3 -m tok2.golden --update` from ai/ (and say why the contract changed)"


class TestGoldenLayout(unittest.TestCase):
    def test_layout_json_is_current(self):
        self.assertEqual(LAYOUT_PATH.read_text(encoding="utf-8"), GoldenLayout(TOK).text(), REFRESH)

    def test_layout_json_has_what_a_port_needs(self):
        g = json.loads(LAYOUT_PATH.read_text(encoding="utf-8"))
        self.assertEqual({k: g["constants"][k] for k in ("none_slot", "ghost_base", "ghost_overflow")},
                         {"none_slot": 0, "ghost_base": 129, "ghost_overflow": 161})
        self.assertEqual(len(g["vocabulary"]), len(TOK.vocab))
        self.assertEqual(g["vocabulary"][0], "<pad>")
        col = g["types"]["GOAL"]["columns"]["deadline"]
        self.assertEqual((col["codec"], col["scale"]), ("ScalarCodec", "time_until"))
        self.assertIn("copysign", col["normalisation"])
        self.assertEqual(g["types"]["WAKE"]["columns"]["mode"]["values"], ["act", "listen", "reflect"])
        for word, i in g["speech_to_input"].items():                       # the tie between speech and input
            self.assertEqual(g["vocabulary"][i], word)
        self.assertEqual(set(g["speech_to_input"]), set(TOK.interface.grammar_words) | set(TOK.interface.kinds))
        names = [a["name"] for a in g["arrays"]]
        self.assertEqual(names, list(TOK.encode(HandCases.base()).ARRAYS))
        self.assertEqual({a["dtype"] for a in g["arrays"]}, {"uint8", "int16", "float16"})


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

    def test_the_hand_made_cases_are_current(self):
        written = {json.loads(l)["name"]: l for l in CASES_PATH.read_text(encoding="utf-8").splitlines()}
        for line in GoldenCases(TOK).hand_lines():
            self.assertEqual(written[json.loads(line)["name"]], line, REFRESH)

    def test_the_edges_are_covered(self):
        names = {c["name"] for c in self.cases}
        for need in ("ok_ghost_overflow", "ok_known_versus_empty", "ok_deadlines_signed", "ok_half_rounding",
                     "ok_counts", "ok_names_beyond_64", "ok_wake_and_plan", "ok_held_pooling", "bad_pointer_not_in_mind"):
            self.assertIn(need, names)
        self.assertGreaterEqual(sum(n.startswith("sampler_") for n in names), 10)

    def test_the_pairs_that_must_differ_do_differ(self):
        d = {c["name"]: c["expect"].get("digest") for c in self.cases}
        self.assertNotEqual(d["ok_ghost_same"], d["ok_ghost_different"])


if __name__ == "__main__":
    unittest.main()
