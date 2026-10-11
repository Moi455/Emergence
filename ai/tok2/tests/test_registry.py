"""The registry is append-only; the interface fingerprint covers what tok-2 reads; contexts serialize canonically."""
from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tok2 import DecisionContext, InputVocabulary, Layout, ModelInterface, Record, TokenError, Tokenizer  # noqa: E402
from tok2.interface import INTERFACE_PATH  # noqa: E402
from tok2.registry import Registry  # noqa: E402
from tok2.tests.test_tok2 import base, ctx  # noqa: E402

RAW = json.loads(INTERFACE_PATH.read_text(encoding="utf-8"))


def changed(edit) -> dict:
    data = copy.deepcopy(RAW)
    edit(data)
    return data


def grow(d):
    d["input"]["token_types"]["ENTITY"]["fields"]["zeal"] = {
        "scale": "unipolar10", "values": [], "unit": "", "list_of": "", "components": [], "component_scales": []}
    d["input"]["token_types"]["ZED"] = {"count": 1, "key": "z:", "fields": {"weight": {
        "scale": "bipolar10", "values": [], "unit": "", "list_of": "", "components": [], "component_scales": []}}}
    d["output"]["speech"]["grammar_words"].append("zzword")
    del d["input"]["token_types"]["ENTITY"]["fields"]["rel.rivalry"]


class TestRegistry(unittest.TestCase):
    def setUp(self):
        self.reg = Registry.load()

    def test_the_committed_registry_is_up_to_date(self):
        self.assertEqual(self.reg.diff(ModelInterface()), ([], []))

    def test_updating_an_up_to_date_registry_changes_nothing(self):
        self.assertEqual(self.reg.updated(ModelInterface()).to_dict(), self.reg.to_dict())

    def test_a_new_element_is_refused_until_the_registry_is_updated(self):
        new = ModelInterface.from_dict(changed(grow))
        with self.assertRaises(TokenError) as cm:
            Tokenizer(new, self.reg)
        self.assertIn("python3 -m tok2.registry --update", str(cm.exception))

    def test_an_update_only_appends(self):
        new = ModelInterface.from_dict(changed(grow))
        up = self.reg.updated(new)
        # nothing already registered moved
        self.assertEqual(up.symbols[:len(self.reg.symbols)], self.reg.symbols)
        self.assertEqual(up.symbols[len(self.reg.symbols):], ["zzword"])
        for name, t in self.reg.types.items():
            self.assertEqual(up.types[name].id, t.id)
            for f, e in t.fields.items():
                u = up.types[name].fields[f]
                self.assertEqual((u.block, u.col, u.width, u.codec), (e.block, e.col, e.width, e.codec), f"{name}.{f}")
        # the new ones come after
        self.assertEqual(up.types["ZED"].id, max(t.id for t in self.reg.types.values()) + 1)
        zeal, old_end = up.types["ENTITY"].fields["zeal"], self.reg.types["ENTITY"].end("num")
        self.assertEqual(zeal.col, old_end)
        # what the interface lost stays reserved, not reused
        riv = up.types["ENTITY"].fields["rel.rivalry"]
        self.assertTrue(riv.retired)
        self.assertEqual(riv.col, self.reg.types["ENTITY"].fields["rel.rivalry"].col)
        self.assertNotEqual(zeal.col, riv.col)
        # the layout works with it and widths are the maximum used
        lay = Layout(new, InputVocabulary(new, up.symbols), up)
        self.assertNotIn("rel.rivalry", lay.types["ENTITY"].columns)
        self.assertEqual(lay.types["ZED"].type_id, up.types["ZED"].id)
        self.assertEqual(lay.width["num"], max(t.end("num") for t in up.types.values()))
        self.assertEqual(up.widths()["num"], lay.width["num"])

    def test_a_retired_symbol_keeps_its_id_but_is_no_longer_accepted(self):
        new = ModelInterface.from_dict(changed(lambda d: d["output"]["speech"]["grammar_words"].remove("owns")))
        up = self.reg.updated(new)
        self.assertEqual(up.symbols, self.reg.symbols)
        vocab = InputVocabulary(new, up.symbols)
        self.assertEqual(vocab.ids["owns"], InputVocabulary(ModelInterface(), self.reg.symbols).ids["owns"])
        self.assertFalse(vocab.is_word("owns"))
        self.assertNotIn("owns", vocab)

    def test_a_field_that_changes_shape_is_a_conflict(self):
        def edit(d):
            d["input"]["token_types"]["ENTITY"]["fields"]["rel.trust"]["scale"] = "enum"
        new = ModelInterface.from_dict(changed(edit))
        with self.assertRaises(TokenError) as cm:
            Tokenizer(new, self.reg)
        self.assertIn("rename", str(cm.exception))
        with self.assertRaises(TokenError):
            self.reg.updated(new)

    def test_ids_of_types_never_depend_on_the_name(self):
        new = ModelInterface.from_dict(changed(lambda d: d["input"]["token_types"].update(
            {"AAA": {"count": 1, "key": "a:", "fields": {}}})))
        up = self.reg.updated(new)
        self.assertEqual(up.types["AAA"].id, len(self.reg.types) + 1)           # last, although first alphabetically


class TestInterface(unittest.TestCase):
    def test_only_what_tok2_reads_is_fingerprinted(self):
        ref = ModelInterface().fingerprint
        self.assertEqual(ModelInterface.from_dict(changed(lambda d: d["output"]["writes"].update(max_per_decision=9))).fingerprint, ref)
        self.assertEqual(ModelInterface.from_dict(changed(lambda d: d["output"].update(gesture_head=["x"]))).fingerprint, ref)
        self.assertNotEqual(ModelInterface.from_dict(changed(lambda d: d["output"]["speech"]["kinds"].append("zz"))).fingerprint, ref)
        self.assertNotEqual(ModelInterface.from_dict(changed(grow)).fingerprint, ref)
        self.assertNotEqual(ModelInterface.from_dict(changed(lambda d: d["input"].update(max_tokens=100))).fingerprint, ref)

    def test_the_schema_version_is_checked(self):
        with self.assertRaises(TokenError):
            ModelInterface.from_dict(changed(lambda d: d.update(schema_version="model-interface-99")))


class TestSerialization(unittest.TestCase):
    def setUp(self):
        self.tok = Tokenizer()

    def test_round_trip_gives_the_same_digest(self):
        c = ctx()
        text = c.dumps(self.tok)
        back = DecisionContext.loads(text, self.tok)
        self.assertEqual(self.tok.encode(back).digest(), self.tok.encode(c).digest())
        self.assertEqual(back.dumps(self.tok), text)

    def test_the_json_is_canonical(self):
        text = ctx().dumps(self.tok)
        d = json.loads(text)
        self.assertEqual(text, json.dumps(d, sort_keys=True, separators=(",", ":"), ensure_ascii=False))
        a = DecisionContext([Record("SELF", "me", {"age": 3, "sex": "male"}), Record("PLACE", "@PLACE", {})])
        b = DecisionContext([Record("SELF", "me", {"sex": "male", "age": 3}), Record("PLACE", "@PLACE", {})])
        self.assertEqual(a.dumps(self.tok), b.dumps(self.tok))
        self.assertEqual(d["header"], self.tok.header())
        self.assertEqual(set(d["header"]), {"schema", "interface", "layout"})

    def test_numpy_scalars_serialize_as_numbers(self):
        c = base(Record("ENTITY", "@E1", {"dist": np.float32(2.5), "present": np.bool_(True), "rel.trust": np.int64(3)}))
        back = DecisionContext.loads(c.dumps(self.tok), self.tok)
        self.assertEqual(self.tok.encode(back).digest(), self.tok.encode(c).digest())

    def test_a_context_for_another_interface_is_refused(self):
        d = json.loads(ctx().dumps(self.tok))
        d["header"]["interface"] = "0" * 16
        with self.assertRaises(TokenError):
            DecisionContext.loads(json.dumps(d), self.tok)
        with self.assertRaises(TokenError):
            DecisionContext.loads("not json", self.tok)
        with self.assertRaises(TokenError):
            DecisionContext.loads('{"header": {}}', self.tok)

    def test_known_keys_survive_and_default_stays_default(self):
        c = ctx()
        self.assertEqual(DecisionContext.loads(c.dumps(self.tok), self.tok).known_keys, sorted(c.known_keys))
        d = base()
        self.assertIsNone(DecisionContext.loads(d.dumps(self.tok), self.tok).known_keys)

    def test_unserializable_values_are_a_token_error(self):
        with self.assertRaises(TokenError):
            base(Record("ENTITY", "@E1", {"dist": object()})).dumps(self.tok)
        with self.assertRaises(TokenError):
            base(Record("ENTITY", "@E1", {"dist": float("nan")})).dumps(self.tok)


if __name__ == "__main__":
    unittest.main()
