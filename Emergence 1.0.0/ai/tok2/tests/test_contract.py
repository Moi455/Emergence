"""Round 2 of the review: strict keys, tolerance at the bounds, -0, write order, ref_types, empty words, citations,
canonical propositions, every error a TokenError (python3 -m unittest discover -s ai/tok2/tests -t ai)."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tok2 import DecisionContext, ModelInterface, Record, TokenError, Tokenizer  # noqa: E402
from tok2.keys import is_count, is_key, is_name  # noqa: E402
from tok2.proposition import PropositionDecoder, canonical_proposition  # noqa: E402
from tok2.tests.test_tok2 import base, ctx  # noqa: E402

TOK = Tokenizer()


def cell(enc, key, typ, field, i=0, arr="num"):
    r = enc.keys.index(key)
    c = TOK.layout.types[typ].columns[field]
    j = c.codec.cols[i] if hasattr(c.codec, "cols") and c.codec.cols else c.col + i
    return getattr(enc, arr)[r, j]


class Base(unittest.TestCase):
    def refuses(self, *records, known=None):
        with self.assertRaises(TokenError):
            TOK.encode(base(*records, known=known))


class TestStrictKeys(Base):
    def test_a_trailing_newline_is_not_a_key(self):
        for k in ("@E1\n", "me\n", "b:1\n", "@PLACE\n", "wake\n", "\n@E1"):
            self.assertFalse(is_key(k), repr(k))
        self.assertFalse(is_name("n:1\n"))
        self.assertFalse(is_count("12\n"))
        self.assertTrue(is_key("@E1") and is_name("n:0") and is_count("0"))

    def test_the_tokenizer_refuses_them_everywhere(self):
        self.refuses(Record("ENTITY", "@E1\n", {}))
        self.refuses(Record("BELIEF", "b:1", {"informant": "@E1\n"}), known=["me", "@PLACE", "b:1", "@E1"])
        self.refuses(Record("ENTITY", "@E1", {"name": "n:1\n"}))
        with self.assertRaises(TokenError):
            DecisionContext(base().records, known_keys=["me\n"]).mind_keys()


class TestRoundingAndBounds(Base):
    def test_zero_after_rounding_is_positive_zero(self):
        for field, v in (("need.thermal", -1e-9), ("need.thermal", -0.0), ("body.load", 1e-12)):
            c = base()
            c.records[0] = Record("SELF", "me", {field: v})
            e = TOK.encode(c)
            bits = int(cell(e, "me", "SELF", field).view(np.uint16))
            self.assertEqual(bits, 0, (field, v))
        # a tiny negative really below the half range (-1e-9 / 10 rounds to -0.0) and a tiny deadline
        e = TOK.encode(base(Record("GOAL", "g:1", {"prop": "(has me silver_coin)", "deadline": -1e-9})))
        self.assertEqual(int(cell(e, "g:1", "GOAL", "deadline").view(np.uint16)), 0)
        # a small but representable negative keeps its sign
        e = TOK.encode(base(Record("GOAL", "g:1", {"prop": "(has me silver_coin)", "deadline": -1e-3})))
        self.assertLess(float(cell(e, "g:1", "GOAL", "deadline")), 0)

    def test_epsilon_at_the_bounds(self):
        def enc(field, v, typ="SELF"):
            recs = [Record("SELF", "me", {field: v}), Record("PLACE", "@PLACE", {})] if typ == "SELF" else None
            return TOK.encode(DecisionContext(recs))
        top = float(cell(enc("need.thirst", 10), "me", "SELF", "need.thirst"))
        self.assertEqual(top, 1.0)
        self.assertEqual(float(cell(enc("need.thirst", 10.0000000001), "me", "SELF", "need.thirst")), 1.0)
        self.assertEqual(float(cell(enc("need.thirst", -1e-12), "me", "SELF", "need.thirst")), 0.0)
        self.assertEqual(float(cell(enc("need.thermal", -10.0000000001), "me", "SELF", "need.thermal")), -1.0)
        self.assertEqual(float(cell(enc("body.load", 1 + 1e-10), "me", "SELF", "body.load")), 1.0)
        self.assertEqual(float(cell(enc("age", -1e-10), "me", "SELF", "age")), 0.0)
        for field, v in (("need.thirst", 10.00000001), ("need.thirst", -1e-8), ("body.load", 1.000001), ("age", -1e-6),
                         ("need.thermal", 10.01)):
            with self.assertRaises(TokenError, msg=(field, v)):
                enc(field, v)
        # same digest at the bound and within epsilon of it
        self.assertEqual(enc("need.thirst", 10).digest(), enc("need.thirst", 10 + 1e-10).digest())


class TestWriteOrder(Base):
    def test_fields_are_written_in_the_registry_order_not_the_alphabetical_one(self):
        order = list(TOK.layout.types["MEMORY"].columns)
        self.assertEqual(order, list(TOK.registry.types["MEMORY"].fields))
        self.assertLess(order.index("interp"), order.index("prop"))            # registry order (append order)
        a = base(Record("MEMORY", "m:1", {"interp": "n:9", "prop": "(past (did n:5 give silver_coin (to me)))"}))
        b = base(Record("MEMORY", "m:1", {"prop": "(past (did n:5 give silver_coin (to me)))", "interp": "n:9"}))
        ea, eb = TOK.encode(a), TOK.encode(b)
        self.assertEqual(ea.names, ["n:9", "n:5"])
        self.assertEqual(ea.digest(), eb.digest())                              # the record's dict order is irrelevant

    def test_the_alias_order_follows_rows_then_columns(self):
        e = TOK.encode(base(Record("ENTITY", "@E1", {"name": "n:7"}), Record("ENTITY", "@E2", {"name": "n:3"}),
                            Record("MEMORY", "m:1", {"prop": "(past (did n:3 give silver_coin (to n:7)))"})))
        self.assertEqual(e.names, ["n:7", "n:3"])


class TestRefTypes(Base):
    def test_every_mref_field_declares_its_types(self):
        n = 0
        for t, spec in TOK.interface.token_types.items():
            for f, s in spec["fields"].items():
                if s["scale"] == "mref" or (s["scale"] == "list" and s["list_of"] == "mref"):
                    self.assertTrue(s.get("ref_types"), f"{t}.{f}")
                    self.assertTrue(set(s["ref_types"]) <= set(TOK.interface.token_types))
                    n += 1
        self.assertGreaterEqual(n, 20)

    def test_the_kinds_the_review_listed(self):
        ft = TOK.interface.token_types
        self.assertEqual(ft["WAKE"]["fields"]["trigger"]["ref_types"],
                         ["EVENT", "HEARD", "REQUEST", "GOAL", "PLAN", "COMMIT", "ENTITY", "GROUP"])      # T08b widened it
        self.assertEqual(ft["PLAN"]["fields"]["goal"]["ref_types"], ["GOAL"])
        self.assertEqual(ft["REQUEST"]["fields"]["from"]["ref_types"], ["ENTITY"])
        self.assertEqual(ft["BELIEF"]["fields"]["informant"]["ref_types"], ["ENTITY"])
        self.assertEqual(ft["COMMIT"]["fields"]["counterparty"]["ref_types"], ["ENTITY", "GROUP"])        # 19a: a commitment can bind a group
        self.assertEqual(ft["SELF"]["fields"]["place"]["ref_types"], ["PLACE", "LOCUS"])
        self.assertEqual(ft["HEARD"]["fields"]["informant"]["ref_types"], ["ENTITY"])        # an alias inherits
        self.assertEqual(set(ft["SELF_STATE"]["fields"]["attention"]["ref_types"]),
                         {"ENTITY", "THING", "INV", "SELF", "EVENT", "HEARD"})
        self.assertEqual(set(ft["ENTITY"]["fields"]["look.gaze"]["ref_types"]), {"ENTITY", "THING", "INV", "SELF", "LOCUS", "PLACE"})

    def test_a_pointer_of_the_wrong_kind_is_refused(self):
        ent = Record("ENTITY", "@E1", {})
        self.refuses(Record("THING", "@T1", {}), Record("WAKE", "wake", {"trigger": "@T1"}))        # ENTITY is valid since T08b
        self.refuses(Record("BELIEF", "b:1", {}), Record("PLAN", "p:1", {"goal": "b:1"}))
        self.refuses(Record("THING", "@T1", {}), Record("BELIEF", "b:1", {"informant": "@T1"}))
        self.refuses(Record("THING", "@T1", {}), Record("THING", "@T2", {"owner": "@T1"}))
        self.refuses(Record("SELF_STATE", "me.state", {"attention": "b:1"}), Record("BELIEF", "b:1", {}))
        self.refuses(Record("REQUEST", "q:1", {"from": "me"}))                                  # the asker is a person file
        ok = TOK.encode(base(ent, Record("THING", "@T1", {"owner": "@E1"}), Record("THING", "@T2", {"owner": "me"}),
                             Record("REQUEST", "q:1", {"from": "@E1"}), Record("WAKE", "wake", {"trigger": "q:1"})))
        self.assertEqual(ok.n, 7)

    def test_a_ghost_is_checked_by_the_kind_of_its_key(self):
        known = ["me", "@PLACE", "b:1", "wake", "me.state", "@E9", "@T9", "g:9", "@V9"]
        self.refuses(Record("BELIEF", "b:1", {"informant": "@T9"}), known=known)
        self.refuses(Record("BELIEF", "b:1", {"informant": "g:9"}), known=known)
        e = TOK.encode(base(Record("BELIEF", "b:1", {"informant": "@E9"}), known=known))
        self.assertEqual(e.ghosts, ["@E9"])
        e = TOK.encode(base(Record("WAKE", "wake", {"trigger": "@V9"}), known=known))      # a dropped event
        self.assertEqual(e.ghosts, ["@V9"])
        self.refuses(Record("WAKE", "wake", {"trigger": "@T9"}), known=known)
        # @T9 may be a THING or an INV: both accepted where both are
        TOK.encode(base(Record("SELF_STATE", "me.state", {"attention": "@T9"}), known=known))

    def test_pointer_lists_are_checked_item_by_item(self):
        self.refuses(Record("ENTITY", "@E1", {}), Record("THING", "@T1", {}),
                     Record("COMMIT", "c:1", {"witnesses": ["@E1", "@T1"]}))
        self.refuses(Record("ENTITY", "@E1", {}), Record("GROUP", "@G1", {}),
                     Record("COMMIT", "c:1", {"witnesses": ["@G1"]}))
        TOK.encode(base(Record("ENTITY", "@E1", {}), Record("GROUP", "@G1", {}),
                        Record("BELIEF", "b:1", {"shared": ["@E1", "@G1"]})))


class TestEmptyWord(Base):
    def test_a_word_set_to_empty_is_known_none(self):
        none = TOK.encode(base(Record("GOAL", "g:1", {}), Record("PLAN", "p:1", {"goal": "g:1", "next": ""})))
        unknown = TOK.encode(base(Record("GOAL", "g:1", {}), Record("PLAN", "p:1", {"goal": "g:1"})))
        word = TOK.encode(base(Record("GOAL", "g:1", {}), Record("PLAN", "p:1", {"goal": "g:1", "next": "give"})))
        self.assertEqual((int(cell(none, "p:1", "PLAN", "next", arr="cat")), int(cell(none, "p:1", "PLAN", "next", arr="cat_known"))), (0, 1))
        self.assertEqual((int(cell(unknown, "p:1", "PLAN", "next", arr="cat")), int(cell(unknown, "p:1", "PLAN", "next", arr="cat_known"))), (0, 0))
        self.assertEqual(int(cell(word, "p:1", "PLAN", "next", arr="cat_known")), 1)
        self.assertNotEqual(none.digest(), unknown.digest())
        self.assertNotEqual(none.digest(), word.digest())
        self.assertEqual(TOK.vocab.ids["<pad>"], 0)

    def test_empty_is_only_for_word_fields(self):
        self.refuses(Record("ENTITY", "@E1", {"link": ""}))                                    # an enum
        self.refuses(Record("ENTITY", "@E1", {"look.attire": [""]}))                           # inside a bag
        self.refuses(Record("ENTITY", "@E1", {"dist": ""}))


class TestCitations(Base):
    def test_a_bare_citation_is_a_proposition(self):
        e = TOK.encode(base(Record("BELIEF", "b:1", {}), Record("BELIEF", "b:2", {"prop": "b:1"}),
                            Record("GOAL", "g:1", {"prop": " m:7 "}), known=["me", "@PLACE", "b:1", "b:2", "g:1", "m:7"]))
        dec = PropositionDecoder(TOK.vocab)
        self.assertEqual(dec.decode(e, e.keys.index("b:2")), "b:1")
        self.assertEqual(dec.decode(e, e.keys.index("g:1")), "m:~0")
        self.assertEqual(e.ghosts, ["m:7"])

    def test_a_record_may_not_cite_itself(self):
        self.refuses(Record("BELIEF", "b:1", {"prop": "b:1"}))
        self.refuses(Record("BELIEF", "b:1", {"prop": "(believes me (that b:1))"}))
        self.refuses(Record("GOAL", "g:1", {"prop": "(that g:1)"}))
        TOK.encode(base(Record("BELIEF", "b:1", {}), Record("BELIEF", "b:2", {"prop": "(that b:1)"})))

    def test_citation_garbage(self):
        for bad in ("b:1 b:2", "b:", "b:01", "e:1", "@E1", "n:3"):
            self.refuses(Record("BELIEF", "b:2", {"prop": bad}), known=["me", "@PLACE", "b:2", "b:1", "b:01", "@E1"])


class TestCanonicalPropositions(Base):
    def test_to_dict_and_dumps_store_the_canonical_text(self):
        messy = "(owns\n   me  @T1 )"
        r = Record("BELIEF", "b:1", {"prop": messy})
        self.assertEqual(r.to_dict()["fields"]["prop"], "(owns me @T1)")
        c = base(Record("THING", "@T1", {}), r)
        text = c.dumps(TOK)
        self.assertIn('"prop":"(owns me @T1)"', text)
        self.assertEqual(TOK.encode(DecisionContext.loads(text, TOK)).digest(), TOK.encode(c).digest())
        self.assertEqual(canonical_proposition(" b:7 "), "b:7")
        self.assertEqual(canonical_proposition("(a  (b c)\t)"), "(a (b c))")
        self.assertEqual(canonical_proposition("(unbalanced"), "(unbalanced")          # left for the encoder to refuse

    def test_two_spellings_give_the_same_json_and_the_same_arrays(self):
        a = base(Record("THING", "@T1", {}), Record("BELIEF", "b:1", {"prop": "(owns me @T1)"}))
        b = base(Record("THING", "@T1", {}), Record("BELIEF", "b:1", {"prop": "( owns   me\t@T1 )"}))
        self.assertEqual(a.dumps(TOK), b.dumps(TOK))
        self.assertEqual(TOK.encode(a).digest(), TOK.encode(b).digest())

    def test_non_ascii_space_and_control_characters_are_refused(self):
        for bad in ("(owns me @T1)", "(owns me @T1)", "(owns me　@T1)", "(owns\x1cme @T1)", "(owns\x00me @T1)",
                    "(owns me @T1)​", "(owns\x0bme @T1)", "(owns\x7fme @T1)"):
            self.refuses(Record("THING", "@T1", {}), Record("BELIEF", "b:1", {"prop": bad}))
        TOK.encode(base(Record("THING", "@T1", {}), Record("BELIEF", "b:1", {"prop": "(owns\tme\n@T1)"})))


class TestEveryErrorIsATokenError(Base):
    def test_loads_with_bad_records(self):
        h = TOK.header()
        for body in ({"header": h, "records": "x", "known_keys": None}, {"header": h, "records": [1], "known_keys": None},
                     {"header": h, "records": [{"type": 1, "key": "me", "fields": {}}], "known_keys": None},
                     {"header": h, "records": [], "known_keys": "abc"}, {"header": h, "records": {}, "known_keys": None},
                     {"header": h, "records": [{"type": "SELF", "key": "me", "fields": []}], "known_keys": None},
                     {"header": h, "records": [], "known_keys": [1, 2]}):
            with self.assertRaises(TokenError, msg=str(body)[:60]):
                TOK.encode(DecisionContext.loads(json.dumps(body), TOK))
        with self.assertRaises(TokenError):
            DecisionContext.loads("[" * 100000, TOK)

    def test_numpy_arrays_in_any_field(self):
        arr = np.array([1.0, 2.0])
        known = ["me", "@PLACE", "b:1"]
        for rec in (Record("BELIEF", "b:1", {"informant": arr}), Record("BELIEF", "b:1", {"shared": arr}),
                    Record("BELIEF", "b:1", {"shared": [arr]}), Record("ENTITY", "@E1", {"link": arr}),
                    Record("ENTITY", "@E1", {"name": arr}), Record("ENTITY", "@E1", {"present": arr}),
                    Record("ENTITY", "@E1", {"dist": arr}), Record("ENTITY", "@E1", {"dir": arr}),
                    Record("SELF", "me", {"held": arr}), Record("SELF", "me", {"held": [arr]}),
                    Record("BELIEF", "b:1", {"prop": arr}), Record("PLAN", "p:1", {"next": arr})):
            recs = [r for r in base().records if r.type != rec.type] + [rec]
            with self.assertRaises(TokenError, msg=str(rec)[:80]):
                TOK.encode(DecisionContext(recs, known + [rec.key]))

    def test_deep_nesting_is_a_token_error_not_a_recursion_error(self):
        from language import Node
        node = Node("not", [])
        cur = node
        for _ in range(5000):
            nxt = Node("not", [])
            cur.args.append(nxt)
            cur = nxt
        self.refuses(Record("BELIEF", "b:1", {"prop": node}))
        deep: object = 1
        for _ in range(5000):
            deep = [deep]
        with self.assertRaises(TokenError):
            base(Record("ENTITY", "@E1", {"look.attire": deep})).dumps(TOK)
        with self.assertRaises(TokenError):
            Record("BELIEF", "b:1", {"prop": node}).to_dict()
        with self.assertRaises(TokenError):
            base(Record("ENTITY", "@E1", {"rep": {"a": deep}})).dumps(TOK)
        self.refuses(Record("ENTITY", "@E1", {"look.attire": deep}))

    def test_unusual_key_and_type_values(self):
        for k in (None, 5, b"me", ("me",), ["me"], np.str_("x")):
            with self.assertRaises(TokenError):
                TOK.encode(DecisionContext([Record("SELF", k, {}), Record("PLACE", "@PLACE", {})]))
        with self.assertRaises(TokenError):
            TOK.encode(DecisionContext([Record(["SELF"], "me", {}), Record("PLACE", "@PLACE", {})]))


class TestContextConstruction(Base):
    def test_known_keys_are_materialised_at_construction(self):
        c = DecisionContext(base().records, (k for k in ("me", "@PLACE", "@E5")))
        self.assertIsInstance(c.known_keys, frozenset)
        self.assertEqual(TOK.encode(c).digest(), TOK.encode(c).digest())            # a generator would be spent
        self.assertIsNone(base().known_keys)
        with self.assertRaises(TokenError):
            DecisionContext([], "abc")
        with self.assertRaises(TokenError):
            DecisionContext([], [["unhashable"]])
        with self.assertRaises(TokenError):
            DecisionContext([], 5)

    def test_the_out_of_context_alias_is_gone(self):
        import tok2.codecs
        import tok2.layout
        self.assertFalse(hasattr(tok2.codecs, "OUT_OF_CONTEXT") or hasattr(tok2.layout, "OUT_OF_CONTEXT"))

    def test_the_schema_is_model_interface_3(self):
        self.assertEqual(TOK.interface.schema_version, "model-interface-3")
        raw = json.loads(Path(__file__).resolve().parents[3].joinpath("catalogue/generated/model_interface.json").read_text())
        raw["schema_version"] = "model-interface-1"
        with self.assertRaises(TokenError):
            ModelInterface.from_dict(raw)


if __name__ == "__main__":
    unittest.main()
