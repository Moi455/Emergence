"""Tests of tok-2 (python3 -m unittest discover -s ai/tok2/tests -t ai)."""
from __future__ import annotations

import math
import re
import struct
import sys
import tomllib
import unittest
import zlib
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tok2 import DecisionContext, Record, TokenError, Tokenizer  # noqa: E402
from tok2.codecs import GHOST_BASE, GHOST_OVERFLOW  # noqa: E402
from tok2.interface import ROOT  # noqa: E402
from tok2.proposition import PropositionDecoder  # noqa: E402

TOK = Tokenizer()


def base(*records, known=None) -> DecisionContext:
    """The two records every decision has (SELF, PLACE), plus `records`."""
    recs = [Record("SELF", "me", {}), Record("PLACE", "@PLACE", {}), *records]
    return DecisionContext(recs, known)


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
                                 "look.attire": ["tattered"], "look.gaze": "@T1", "rep": {"honesty": -0.6}}),
        Record("BELIEF", "b:1", {"prop": "(owns me @T1)", "certainty": 9, "source": "seen", "polarity": True,
                                 "informant": "", "shared": ["@E1", "@E9"], "age": 200.0}),
        Record("BELIEF", "b:2", {"prop": "(owns @E1 silver_coin:3)", "certainty": 4, "source": "heard", "hops": 2}),
        Record("GOAL", "g:1", {"prop": "(at @E2 @PLACE)", "priority": 7, "mode": "achieve", "status": "active",
                               "origin_ref": "b:1", "deadline": -3.0}),
        Record("PLACE", "@PLACE", {"indoors": False, "light": 8, "crowd": 2}),
        Record("REQUEST", "q:1", {"from": "@E1", "prop": "(request (did you give @T1 (to n:17)))", "age": 0.1}),
    ], known_keys=["me", "@PLACE", "@T1", "@E1", "@E2", "@E9", "b:1", "b:2", "g:1", "q:1"])


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

    def test_ids_come_from_the_registry(self):
        for name, t in TOK.layout.types.items():
            self.assertEqual(t.type_id, TOK.registry.types[name].id)
            for f, c in t.columns.items():
                self.assertEqual(c.col, TOK.registry.types[name].fields[f].col)
        self.assertEqual(TOK.vocab.symbols, TOK.registry.symbols)

    def test_the_arrays_have_the_documented_types(self):
        e = TOK.encode(base())
        self.assertEqual([str(getattr(e, a).dtype) for a in e.ARRAYS],
                         ["uint8", "float16", "uint8", "int16", "uint8", "uint8", "uint8", "int16", "uint8", "uint8",
                          "uint8", "float16"])
        self.assertEqual(e.cat_known.shape, e.cat.shape)
        self.assertEqual(e.ptr_known.shape, e.ptr.shape)


class TestEncode(unittest.TestCase):
    def setUp(self):
        self.enc = TOK.encode(ctx())
        self.slot = {k: i + 1 for i, k in enumerate(self.enc.keys)}

    def col(self, typ, field):
        return TOK.layout.types[typ].columns[field].col

    def test_rows_follow_the_registry_type_order(self):
        ids = [int(t) for t in self.enc.type_id[: self.enc.n]]
        self.assertEqual(ids, sorted(ids))
        self.assertEqual(self.enc.n, 8)
        self.assertTrue((self.enc.type_id[self.enc.n:] == 0).all())

    def test_numbers_are_normalised_and_flagged_known(self):
        r = self.slot["@E1"] - 1
        c = self.col("ENTITY", "rel.trust")
        self.assertAlmostEqual(float(self.enc.num[r, c]), -0.45, places=3)
        self.assertEqual(self.enc.known[r, c], 1)
        c = self.col("ENTITY", "rel.affection")                     # absent: unknown, not zero-and-known
        self.assertEqual(self.enc.known[r, c], 0)
        c = self.col("ENTITY", "dist")
        self.assertEqual(self.enc.num[r, c], np.float16(math.log1p(3.0)))

    def test_num_is_rounded_once_from_the_double(self):
        # 1 - 2^-12 - 2^-40 is just below the tie between two binary16 values: one rounding goes down, a
        # detour through float32 would land on the tie and go up
        v = 1 - 2.0 ** -12 - 2.0 ** -40
        c = base()
        c.records[0] = Record("SELF", "me", {"body.load": v})
        e = TOK.encode(c)
        got = e.num[e.keys.index("me"), self.col("SELF", "body.load")]
        self.assertEqual(got, np.float16(1 - 2.0 ** -11))
        self.assertNotEqual(np.float16(np.float32(v)), got)

    def test_negative_zero_is_zero(self):
        c = base()
        c.records[0] = Record("SELF", "me", {"need.thermal": -0.0, "age": 0})
        e = TOK.encode(c)
        bits = e.num[e.keys.index("me"), self.col("SELF", "need.thermal")].view(np.uint16)
        self.assertEqual(int(bits), 0)

    def test_object_vector_and_held_items_are_pooled_by_component(self):
        r, ov = self.slot["me"] - 1, TOK.interface.object_vector
        c = self.col("SELF", "held")
        self.assertAlmostEqual(float(self.enc.num[r, c + ov.index("edge")]), 0.2, places=3)   # max(2, 0) / 10
        self.assertEqual(self.enc.known[r, c + ov.index("point")], 0)
        self.assertEqual(self.enc.num[r, c + ov.index("mass")], np.float16(math.log1p(1.0)))

    def test_masses_of_held_objects_add_up_and_the_other_components_take_the_max(self):
        def held(*items):
            c = base()
            c.records[0] = Record("SELF", "me", {"held": list(items)})
            e = TOK.encode(c)
            ov = TOK.interface.object_vector
            c0 = self.col("SELF", "held")
            return e, lambda p: float(e.num[e.keys.index("me"), c0 + ov.index(p)])
        _, one = held({"mass": 2.0, "edge": 3})
        _, two = held({"mass": 2.0, "edge": 3}, {"mass": 5.0, "edge": 7})
        self.assertAlmostEqual(two("mass"), math.log1p(7.0), places=2)
        self.assertAlmostEqual(two("edge"), 0.7, places=3)
        self.assertAlmostEqual(one("mass"), math.log1p(2.0), places=2)
        with self.assertRaises(TokenError):                 # each item is checked before pooling
            held({"mass": -1.0}, {"mass": 5.0})

    def test_pointers_resolve_to_slots_or_ghosts(self):
        r = self.slot["b:1"] - 1
        c = self.col("BELIEF", "shared")
        self.assertEqual(list(self.enc.ptr[r, c:c + 2]), [self.slot["@E1"], GHOST_BASE])    # @E9: the first ghost
        self.assertEqual(self.enc.ptr[r, self.col("BELIEF", "informant")], 0)
        g = self.slot["g:1"] - 1
        self.assertIn(GHOST_BASE + 1, list(self.enc.prop_slot[g]))          # @E2: the second ghost
        self.assertEqual(self.enc.ghosts, ["@E9", "@E2"])
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

    def test_digest_is_the_crc32_of_the_little_endian_arrays(self):
        crc = zlib.crc32(struct.pack("<I", self.enc.n))
        for a in self.enc.ARRAYS:
            arr = getattr(self.enc, a)
            crc = zlib.crc32(arr.astype(arr.dtype.newbyteorder("<")).tobytes(), crc)
        self.assertEqual(self.enc.digest(), crc)
        self.assertLess(self.enc.digest(), 2 ** 32)

    def test_records_given_in_another_type_order_give_the_same_arrays(self):
        c = ctx()
        c.records.reverse()
        # same types, and within a type (two beliefs) the order is kept by swapping them back
        bel = [i for i, r in enumerate(c.records) if r.type == "BELIEF"]
        c.records[bel[0]], c.records[bel[1]] = c.records[bel[1]], c.records[bel[0]]
        self.assertEqual(TOK.encode(c).digest(), self.enc.digest())

    def test_the_order_within_a_type_is_the_salience_and_matters(self):
        c = ctx()
        bel = [i for i, r in enumerate(c.records) if r.type == "BELIEF"]
        c.records[bel[0]], c.records[bel[1]] = c.records[bel[1]], c.records[bel[0]]
        self.assertNotEqual(TOK.encode(c).digest(), self.enc.digest())


class TestGhosts(unittest.TestCase):
    def two_beliefs(self, a, b):
        return DecisionContext(base().records + [
            Record("BELIEF", "b:1", {"prop": f"(owns {a} silver_coin)"}),
            Record("BELIEF", "b:2", {"prop": f"(at {b} @PLACE)"})], known_keys=["me", "@PLACE", "b:1", "b:2", "@E7", "@E9"])

    def test_the_same_ghost_twice_is_not_two_different_ghosts(self):
        same = TOK.encode(self.two_beliefs("@E7", "@E7"))
        diff = TOK.encode(self.two_beliefs("@E7", "@E9"))
        self.assertNotEqual(same.digest(), diff.digest())
        self.assertEqual(same.ghosts, ["@E7"])
        self.assertEqual(diff.ghosts, ["@E7", "@E9"])
        self.assertEqual(sorted(set(int(x) for x in same.prop_slot.flat if x >= GHOST_BASE)), [GHOST_BASE])
        self.assertEqual(sorted(set(int(x) for x in diff.prop_slot.flat if x >= GHOST_BASE)), [GHOST_BASE, GHOST_BASE + 1])

    def test_ghosts_are_numbered_by_encoding_order_not_by_key_or_by_field_order(self):
        a = TOK.encode(self.two_beliefs("@E9", "@E7"))
        self.assertEqual(a.ghosts, ["@E9", "@E7"])                          # first appearance, not the smaller key
        # swapping the two names in the whole decision gives the SAME arrays (the model never sees the numbers)
        b = TOK.encode(self.two_beliefs("@E7", "@E9"))
        self.assertEqual(a.digest(), b.digest())

    def test_a_ghost_in_a_pointer_column_comes_before_one_in_a_proposition_of_the_same_row(self):
        c = base(Record("BELIEF", "b:1", {"prop": "(at @E5 @PLACE)", "informant": "@E6"}),
                 known=["me", "@PLACE", "b:1", "@E5", "@E6"])
        e = TOK.encode(c)
        self.assertEqual(e.ghosts, ["@E6", "@E5"])

    def test_beyond_32_ghosts_the_slot_is_161(self):
        known = ["me", "@PLACE", *(f"b:{i}" for i in range(1, 12)), *(f"@E{i}" for i in range(1, 41))]
        recs = base().records + [Record("BELIEF", f"b:{i + 1}", {"shared": [f"@E{4 * i + j + 1}" for j in range(4)]})
                                 for i in range(10)]
        e = TOK.encode(DecisionContext(recs, known))
        c = TOK.layout.types["BELIEF"].columns["shared"].col
        slots = [int(x) for r in range(e.n) for x in e.ptr[r, c:c + 4] if x]
        self.assertEqual(len(e.ghosts), 32)
        self.assertEqual(slots[:32], [GHOST_BASE + k for k in range(32)])
        self.assertEqual(set(slots[32:]), {GHOST_OVERFLOW})
        self.assertLess(max(slots), 256)

    def test_a_pointer_the_mind_does_not_hold_is_refused(self):
        with self.assertRaises(TokenError):
            TOK.encode(base(Record("BELIEF", "b:1", {"prop": "(owns me @T5)"})))
        with self.assertRaises(TokenError):
            TOK.encode(base(Record("BELIEF", "b:1", {"informant": "@E2"})))
        with self.assertRaises(TokenError):                                  # a record outside known_keys
            TOK.encode(DecisionContext(base().records, known_keys=["me"]))

    def test_known_keys_default_to_the_keys_of_the_records(self):
        e = TOK.encode(base(Record("ENTITY", "@E1", {}), Record("BELIEF", "b:1", {"informant": "@E1"})))
        self.assertEqual(e.ghosts, [])

    def test_the_decoder_shows_ghosts_as_kind_and_number(self):
        e = TOK.encode(self.two_beliefs("@E9", "@E9"))
        dec = PropositionDecoder(TOK.vocab)
        self.assertEqual(dec.decode(e, e.keys.index("b:1")), "(owns @E~0 silver_coin)")
        self.assertEqual(dec.decode(e, e.keys.index("b:2")), "(at @E~0 @PLACE)")


class TestKnownVersusEmpty(unittest.TestCase):
    def enc(self, **fields):
        c = base(Record("ENTITY", "@E1", fields))
        return TOK.encode(c), c

    def cols(self, typ, f):
        c = TOK.layout.types[typ].columns[f]
        return c.col, c.col + c.codec.width

    def test_absent_and_none_are_unknown(self):
        e, _ = self.enc(**{"look.attire": None, "look.gaze": None})
        r = e.keys.index("@E1")
        a, b = self.cols("ENTITY", "look.attire")
        self.assertEqual(int(e.cat_known[r, a:b].sum()), 0)
        a, b = self.cols("ENTITY", "look.gaze")
        self.assertEqual(int(e.ptr_known[r, a:b].sum()), 0)

    def test_an_empty_list_is_known_empty_and_differs_from_unknown(self):
        known, _ = self.enc(**{"look.attire": []})
        unknown, _ = self.enc()
        r = known.keys.index("@E1")
        a, b = self.cols("ENTITY", "look.attire")
        self.assertEqual(list(known.cat_known[r, a:b]), [1] * (b - a))
        self.assertEqual(int(known.cat[r, a:b].sum()), 0)
        self.assertNotEqual(known.digest(), unknown.digest())

    def test_an_empty_pointer_is_known_nobody_and_differs_from_unknown(self):
        nobody, _ = self.enc(**{"look.gaze": ""})
        unknown, _ = self.enc()
        r = nobody.keys.index("@E1")
        a, _b = self.cols("ENTITY", "look.gaze")
        self.assertEqual((nobody.ptr[r, a], nobody.ptr_known[r, a]), (0, 1))
        self.assertEqual((unknown.ptr[r, a], unknown.ptr_known[r, a]), (0, 0))
        self.assertNotEqual(nobody.digest(), unknown.digest())

    def test_an_empty_pointer_list_is_known_empty(self):
        c = base(Record("BELIEF", "b:1", {"shared": []}))
        e = TOK.encode(c)
        a, b = self.cols("BELIEF", "shared")
        r = e.keys.index("b:1")
        self.assertEqual(list(e.ptr_known[r, a:b]), [1] * (b - a))

    def test_nothing_in_the_hands_is_known_zero_not_unknown(self):
        ov = TOK.interface.object_vector
        c = base()
        c.records[0] = Record("SELF", "me", {"held": []})
        e = TOK.encode(c)
        a, b = self.cols("SELF", "held")
        r = e.keys.index("me")
        self.assertEqual(list(e.known[r, a:b]), [1] * len(ov))
        self.assertEqual(float(e.num[r, a:b].sum()), 0.0)
        c.records[0] = Record("SELF", "me", {})
        self.assertNotEqual(TOK.encode(c).digest(), e.digest())

    def test_a_word_in_a_cat_column_is_flagged_known(self):
        e, _ = self.enc(**{"known_by": "seen"})
        a, _b = self.cols("ENTITY", "known_by")
        self.assertEqual(e.cat_known[e.keys.index("@E1"), a], 1)


class TestSignedDeadlines(unittest.TestCase):
    def deadline(self, typ, key, fields, value):
        c = base(Record(typ, key, {**fields, "deadline": value}))
        e = TOK.encode(c)
        return float(e.num[e.keys.index(key), TOK.layout.types[typ].columns["deadline"].col])

    def test_goal_and_commit_deadlines_are_hours_until_with_a_signed_log(self):
        for typ, key in (("GOAL", "g:1"), ("COMMIT", "c:1")):
            fields = {"prop": "(has me silver_coin)"} if typ == "GOAL" else {"prop": "(did me give silver_coin (to me))"}
            ahead, late, now = (self.deadline(typ, key, fields, h) for h in (10.0, -10.0, 0.0))
            self.assertAlmostEqual(ahead, math.log1p(10.0), places=2)
            self.assertAlmostEqual(late, -ahead, places=3)
            self.assertEqual(now, 0.0)

    def test_the_interface_says_so(self):
        for t in ("GOAL", "COMMIT"):
            self.assertEqual(TOK.interface.token_types[t]["fields"]["deadline"]["scale"], "time_until")
        self.assertEqual(TOK.interface.token_types["GOAL"]["fields"]["age"]["scale"], "time")   # an age stays an age


class TestNewTokens(unittest.TestCase):
    def test_wake_token(self):
        c = base(Record("ENTITY", "@E1", {}),
                 Record("REQUEST", "q:1", {"from": "@E1", "prop": "(request (did me give silver_coin (to me)))"}),
                 Record("WAKE", "wake", {"mode": "act", "cause": "request", "trigger": "q:1", "urgency": 6.5}))
        e = TOK.encode(c)
        r = e.keys.index("wake")
        t = TOK.layout.types["WAKE"]
        self.assertEqual(e.cat[r, t.columns["cause"].col], TOK.vocab.id("request"))
        self.assertEqual(e.ptr[r, t.columns["trigger"].col], e.keys.index("q:1") + 1)
        self.assertEqual(TOK.layout.types["WAKE"].count, 1)
        self.assertEqual(TOK.interface.token_types["WAKE"]["fields"]["mode"]["values"], ["act", "listen", "reflect"])
        with self.assertRaises(TokenError):
            TOK.encode(base(Record("WAKE", "wake", {"mode": "sleep"})))

    def test_plan_has_a_target_and_a_next_gesture(self):
        c = base(Record("GOAL", "g:1", {"prop": "(has me silver_coin)"}),
                 Record("PLAN", "p:1", {"step": "walk", "next": "give", "goal": "g:1", "target": "me"}))
        e = TOK.encode(c)
        r, t = e.keys.index("p:1"), TOK.layout.types["PLAN"]
        self.assertEqual(e.cat[r, t.columns["next"].col], TOK.vocab.id("give"))
        self.assertEqual(e.ptr[r, t.columns["target"].col], e.keys.index("me") + 1)


class TestPropositions(unittest.TestCase):
    def test_round_trip_of_every_probe_utterance(self):
        """Prefix order + arity rebuilds the tree; a pointer to a record the batch lacks becomes a ghost @E~k."""
        stories = tomllib.loads((ROOT / "catalogue" / "data" / "stories.toml").read_text(encoding="utf-8"))["story"]
        utterances = [u for s in stories for u in s.get("utterances", [])]
        self.assertGreater(len(utterances), 150)
        dec = PropositionDecoder(TOK.vocab)
        ptr = re.compile(r"(?<![\w])(@[ETGLV]\d+|[bmghqc]:\d+)")
        for u in utterances:
            keys = list(dict.fromkeys(ptr.findall(u)))
            enc = TOK.encode(base(Record("REQUEST", "q:1", {"prop": u}), known=["me", "@PLACE", "q:1", *keys]))
            want = u
            ghosts = [k for k in keys if k not in ("@PLACE", "me")]
            for k, key in enumerate(ghosts):
                kind = re.match(r"@[ETGLV]|[bmghqc]:", key).group(0)
                want = re.sub(rf"(?<![\w]){re.escape(key)}(?!\d)", f"{kind}~{k}", want)
            self.assertEqual(dec.decode(enc, enc.keys.index("q:1")), want, u)

    def test_in_context_pointers_come_back_as_their_keys(self):
        enc = TOK.encode(ctx())
        r = enc.keys.index("b:1")
        self.assertEqual(PropositionDecoder(TOK.vocab).decode(enc, r), "(owns me @T1)")
        r = enc.keys.index("b:2")
        self.assertEqual(PropositionDecoder(TOK.vocab).decode(enc, r), "(owns @E1 silver_coin:3)")

    def test_a_zero_count_is_not_the_absence_of_a_count(self):
        def enc(p):
            e = TOK.encode(base(Record("BELIEF", "b:1", {"prop": p})))
            return e, PropositionDecoder(TOK.vocab).decode(e, e.keys.index("b:1"))
        some, t1 = enc("(has me silver_coin)")
        none, t2 = enc("(has me silver_coin:0)")
        three, t3 = enc("(has me silver_coin:3)")
        self.assertEqual((t1, t2, t3), ("(has me silver_coin)", "(has me silver_coin:0)", "(has me silver_coin:3)"))
        self.assertEqual(len({some.digest(), none.digest(), three.digest()}), 3)
        r = some.keys.index("b:1")
        self.assertEqual(float(some.prop_num[r].max()), 0.0)
        self.assertAlmostEqual(float(none.prop_num[r].max()), math.log1p(1), places=3)
        self.assertAlmostEqual(float(three.prop_num[r].max()), math.log1p(4), places=3)

    def test_prop_num_is_binary16(self):
        e = TOK.encode(base(Record("BELIEF", "b:1", {"prop": "(has me silver_coin:100)"})))
        self.assertEqual(e.prop_num.dtype, np.float16)
        self.assertEqual(float(e.prop_num[e.keys.index("b:1")].max()), float(np.float16(math.log1p(101))))


class TestRefusals(unittest.TestCase):
    def refuses(self, *records, known=None):
        with self.assertRaises(TokenError):
            TOK.encode(base(*records, known=known))

    def test_out_of_range_values(self):
        self.refuses(Record("ENTITY", "@E1", {"rel.trust": 11}))
        self.refuses(Record("ENTITY", "@E1", {"rel.fear": -1}))
        self.refuses(Record("ENTITY", "@E1", {"rel.trust": float("nan")}))
        self.refuses(Record("ENTITY", "@E1", {"present": 1}))
        self.refuses(Record("ENTITY", "@E1", {"rep": {"honesty": 2}}))

    def test_unknown_fields_words_and_values(self):
        self.refuses(Record("ENTITY", "@E1", {"no_such_field": 1}))
        self.refuses(Record("ENTITY", "@E1", {"link": "no_such_link"}))
        self.refuses(Record("THING", "@T1", {"kind": "no_such_kind"}))
        self.refuses(Record("THING", "@T1", {"props": {"no_such_property": 1}}))
        self.refuses(Record("BELIEF", "b:1", {"prop": "(owns me no_such_word)"}))
        self.refuses(Record("BELIEF", "b:1", {"prop": "(owns me"}))
        self.refuses(Record("NO_SUCH_TYPE", "@E1", {}))

    def test_keys_and_counts(self):
        self.refuses(Record("ENTITY", "b:1", {}))
        self.refuses(Record("SELF", "@E1", {}))
        self.refuses(Record("ENTITY", "@E1", {}), Record("ENTITY", "@E1", {}))
        self.refuses(*[Record("ENTITY", f"@E{i}", {}) for i in range(TOK.layout.types["ENTITY"].count + 1)])
        self.refuses(Record("BELIEF", "b:1", {"informant": "Bob"}))

    def test_caps(self):
        self.refuses(Record("ENTITY", "@E1", {"look.attire": ["tattered"] * 7}))
        self.refuses(Record("BELIEF", "b:1", {"shared": [f"@E{i}" for i in range(5)]}))
        long = "(and " * 18 + "(at me @PLACE)" + ")" * 18          # 21 symbols
        self.refuses(Record("BELIEF", "b:1", {"prop": long}))


if __name__ == "__main__":
    unittest.main()
