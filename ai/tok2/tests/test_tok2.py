"""Tests of tok-2 (python3 -m unittest discover -s ai/tok2/tests -t ai)."""
from __future__ import annotations

import math
import re
import sys
import tomllib
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tok2 import DecisionContext, Record, TokenError, Tokenizer  # noqa: E402
from tok2.interface import ROOT  # noqa: E402
from tok2.layout import OUT_OF_CONTEXT  # noqa: E402
from tok2.proposition import PropositionDecoder  # noqa: E402

TOK = Tokenizer()


def ctx() -> DecisionContext:
    """A small, plausible decision: a woman at the well sees a man she knows holding her bucket."""
    return DecisionContext([
        Record("THING", "@T1", {"kind": "bucket", "dist": 1.5, "dir": {"sin": 0.0, "cos": 1.0},
                                "owner": "me", "props": {"capacity": 10.0, "wetness": 6}}),
        Record("SELF", "me", {"age": 34, "age_stage": "adult", "sex": "female", "need.thirst": 6.5,
                              "body.pain": 0, "place": "@PLACE", "time": {"sin": 0.5, "cos": -0.86, "certainty": 0.9},
                              "held": [{"edge": 2}, {"mass": 1.0, "edge": 0}]}),
        Record("ENTITY", "@E1", {"name": "n:17", "known_by": "seen", "present": True, "dist": 3.0,
                                 "rel.trust": -4.5, "rel.familiarity": 8, "look.held": {"capacity": 10.0},
                                 "look.attire": ["w_poor"], "look.gaze": "@T1", "rep": {"honesty": -0.6}}),
        Record("BELIEF", "b:1", {"prop": "(owns me @T1)", "certainty": 9, "source": "seen", "polarity": True,
                                 "informant": None, "shared": ["@E1", "@E9"], "age": 200.0}),
        Record("BELIEF", "b:2", {"prop": "(owns @E1 silver_coin:3)", "certainty": 4, "source": "heard", "hops": 2}),
        Record("GOAL", "g:1", {"prop": "(at @E2 @PLACE)", "priority": 7, "mode": "achieve", "status": "active",
                               "origin_ref": "b:1"}),
        Record("PLACE", "@PLACE", {"indoors": False, "light": 8, "crowd": 2}),
        Record("REQUEST", "q:1", {"from": "@E1", "prop": "(request (did you give @T1 (to n:17)))", "age": 0.1}),
    ])


class TestLayout(unittest.TestCase):
    def test_every_interface_field_has_a_column(self):
        for name, spec in TOK.interface.token_types.items():
            self.assertEqual(set(spec["fields"]), set(TOK.layout.types[name].columns), name)

    def test_columns_fit_their_block_and_do_not_overlap(self):
        for t in TOK.layout.types.values():
            for block in ("num", "cat", "ptr"):
                cols = sorted((c.col, c.col + c.codec.width) for c in t.columns.values() if c.codec.block == block)
                for (a0, a1), (b0, _) in zip(cols, cols[1:]):
                    self.assertLessEqual(a1, b0, t.name)
                if cols:
                    self.assertLessEqual(cols[-1][1], TOK.layout.width[block], t.name)

    def test_fingerprints_are_deterministic(self):
        other = Tokenizer()
        self.assertEqual(other.layout.fingerprint, TOK.layout.fingerprint)
        self.assertEqual(other.vocab.fingerprint, TOK.vocab.fingerprint)
        self.assertEqual(TOK.vocab.symbols[:3], ["<pad>", "<unk>", "<num>"])


class TestEncode(unittest.TestCase):
    def setUp(self):
        self.enc = TOK.encode(ctx())
        self.slot = {k: i + 1 for i, k in enumerate(self.enc.keys)}

    def col(self, typ, field):
        return TOK.layout.types[typ].columns[field].col

    def test_rows_follow_the_interface_type_order(self):
        order = list(TOK.layout.types)
        types = [order[t - 1] for t in self.enc.type_id[: self.enc.n]]
        self.assertEqual(types, sorted(types, key=order.index))
        self.assertEqual(self.enc.n, 8)
        self.assertTrue((self.enc.type_id[self.enc.n:] == 0).all())

    def test_numbers_are_normalised_and_flagged_known(self):
        r = self.slot["@E1"] - 1
        c = self.col("ENTITY", "rel.trust")
        self.assertAlmostEqual(float(self.enc.num[r, c]), -0.45, places=6)
        self.assertEqual(self.enc.known[r, c], 1)
        c = self.col("ENTITY", "rel.affection")                     # absent: unknown, not zero-and-known
        self.assertEqual(self.enc.known[r, c], 0)
        c = self.col("ENTITY", "dist")
        self.assertAlmostEqual(float(self.enc.num[r, c]), math.log1p(3.0), places=6)

    def test_object_vector_and_held_items_are_pooled_by_component(self):
        r, ov = self.slot["me"] - 1, TOK.interface.object_vector
        c = self.col("SELF", "held")
        self.assertAlmostEqual(float(self.enc.num[r, c + ov.index("edge")]), 0.2, places=6)   # max(2, 0) / 10
        self.assertEqual(self.enc.known[r, c + ov.index("point")], 0)

    def test_pointers_resolve_to_slots_or_out_of_context(self):
        r = self.slot["b:1"] - 1
        c = self.col("BELIEF", "shared")
        self.assertEqual(list(self.enc.ptr[r, c:c + 2]), [self.slot["@E1"], OUT_OF_CONTEXT])
        self.assertEqual(self.enc.ptr[r, self.col("BELIEF", "informant")], 0)
        g = self.slot["g:1"] - 1
        self.assertIn(OUT_OF_CONTEXT, list(self.enc.prop_slot[g]))          # @E2 is not in this decision
        self.assertIn((self.slot["g:1"], self.slot["b:1"], "ptr0"), self.enc.edges())

    def test_a_name_is_the_same_alias_in_a_field_and_in_a_proposition(self):
        e, q = self.slot["@E1"] - 1, self.slot["q:1"] - 1
        name_id = self.enc.cat[e, self.col("ENTITY", "name")]
        self.assertIn(name_id, list(self.enc.prop_sym[q]))
        self.assertEqual(self.enc.names, ["n:17"])

    def test_digest_is_deterministic_and_sensitive(self):
        self.assertEqual(TOK.encode(ctx()).digest(), self.enc.digest())
        c = ctx()
        c.records[2].fields["rel.trust"] = -4.4
        self.assertNotEqual(TOK.encode(c).digest(), self.enc.digest())

    def test_records_given_in_another_type_order_give_the_same_arrays(self):
        c = ctx()
        c.records.reverse()
        # same types, and within a type (two beliefs) the order is kept by swapping them back
        bel = [i for i, r in enumerate(c.records) if r.type == "BELIEF"]
        c.records[bel[0]], c.records[bel[1]] = c.records[bel[1]], c.records[bel[0]]
        self.assertEqual(TOK.encode(c).digest(), self.enc.digest())


class TestPropositions(unittest.TestCase):
    def test_round_trip_of_every_probe_utterance(self):
        """Prefix order + arity rebuilds the tree; out-of-context pointers lose only their number."""
        stories = tomllib.loads((ROOT / "catalogue" / "data" / "stories.toml").read_text(encoding="utf-8"))["story"]
        utterances = [u for s in stories for u in s.get("utterances", [])]
        self.assertGreater(len(utterances), 150)
        dec = PropositionDecoder(TOK.vocab)
        for u in utterances:
            enc = TOK.encode(DecisionContext([Record("REQUEST", "q:1", {"prop": u})]))
            want = re.sub(r"(?<![\w])(@[ETGLV]|[bmg]:)\d+", r"\1?", u)   # names come back as they were
            self.assertEqual(dec.decode(enc, 0), want)

    def test_in_context_pointers_come_back_as_their_keys(self):
        enc = TOK.encode(ctx())
        r = enc.keys.index("b:1")
        self.assertEqual(PropositionDecoder(TOK.vocab).decode(enc, r), "(owns me @T1)")
        r = enc.keys.index("b:2")
        self.assertEqual(PropositionDecoder(TOK.vocab).decode(enc, r), "(owns @E1 silver_coin:3)")


class TestRefusals(unittest.TestCase):
    def refuses(self, records):
        with self.assertRaises(TokenError):
            TOK.encode(DecisionContext(records))

    def test_out_of_range_values(self):
        self.refuses([Record("ENTITY", "@E1", {"rel.trust": 11})])
        self.refuses([Record("ENTITY", "@E1", {"rel.fear": -1})])
        self.refuses([Record("ENTITY", "@E1", {"rel.trust": float("nan")})])
        self.refuses([Record("ENTITY", "@E1", {"present": 1})])
        self.refuses([Record("ENTITY", "@E1", {"rep": {"honesty": 2}})])

    def test_unknown_fields_words_and_values(self):
        self.refuses([Record("ENTITY", "@E1", {"no_such_field": 1})])
        self.refuses([Record("ENTITY", "@E1", {"link": "no_such_link"})])
        self.refuses([Record("THING", "@T1", {"kind": "no_such_kind"})])
        self.refuses([Record("THING", "@T1", {"props": {"no_such_property": 1}})])
        self.refuses([Record("BELIEF", "b:1", {"prop": "(owns me no_such_word)"})])
        self.refuses([Record("BELIEF", "b:1", {"prop": "(owns me"})])
        self.refuses([Record("NO_SUCH_TYPE", "@E1", {})])

    def test_keys_and_counts(self):
        self.refuses([Record("ENTITY", "b:1", {})])
        self.refuses([Record("SELF", "@E1", {})])
        self.refuses([Record("ENTITY", "@E1", {}), Record("ENTITY", "@E1", {})])
        self.refuses([Record("ENTITY", f"@E{i}", {}) for i in range(TOK.layout.types["ENTITY"].count + 1)])
        self.refuses([Record("BELIEF", "b:1", {"informant": "Bob"})])

    def test_caps(self):
        self.refuses([Record("ENTITY", "@E1", {"look.attire": ["w_poor"] * 7})])
        self.refuses([Record("BELIEF", "b:1", {"shared": [f"@E{i}" for i in range(5)]})])
        long = "(and " * 18 + "(at me @PLACE)" + ")" * 18          # 21 symbols
        self.refuses([Record("BELIEF", "b:1", {"prop": long})])


if __name__ == "__main__":
    unittest.main()
