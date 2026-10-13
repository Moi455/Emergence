"""The registry is append-only; the interface fingerprint covers what tok-2 reads; contexts serialize canonically."""
from __future__ import annotations

import copy
import json
import sys
import tempfile
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


VECTOR_FIELDS = (("THING", "props"), ("INV", "props"), ("SELF", "held"), ("ENTITY", "look.held"))


def add_property(d, name="zzprop", scale="qty", unit="kg"):
    """A new perceptible property of objects: appended to every field that carries the object vector."""
    d["input"]["object_vector"].append(name)
    for t, f in VECTOR_FIELDS:
        spec = d["input"]["token_types"][t]["fields"][f]
        spec["components"].append(name)
        spec["component_scales"].append(scale)
        spec["component_units"].append(unit)


class TestVectorRegistry(unittest.TestCase):
    def setUp(self):
        self.reg = Registry.load()

    def test_every_vector_records_its_meaning(self):
        e = self.reg.types["THING"].fields["props"]
        self.assertEqual([c.name for c in e.components], ModelInterface().object_vector)
        self.assertEqual(e.components[0].unit, "kg")
        self.assertEqual(self.reg.types["ENTITY"].fields["dir"].components[0].scale, "unit")
        self.assertEqual(self.reg.types["GOAL"].fields["deadline"].scale, "time_until")
        for t in self.reg.types.values():
            for f in t.fields.values():
                self.assertNotEqual(f.scale, "")

    def test_swapped_components_are_a_conflict(self):
        def edit(d):
            for t, f in VECTOR_FIELDS:
                spec = d["input"]["token_types"][t]["fields"][f]
                for k in ("components", "component_scales", "component_units"):
                    spec[k][0], spec[k][1] = spec[k][1], spec[k][0]
        new = ModelInterface.from_dict(changed(edit))
        add, conflicts = self.reg.diff(new)
        self.assertTrue(any("reordered or swapped" in c for c in conflicts), conflicts)
        with self.assertRaises(TokenError):
            Tokenizer(new, self.reg)
        with self.assertRaises(TokenError):
            self.reg.updated(new)

    def test_a_changed_scale_or_unit_is_a_conflict(self):
        def scale(d):
            d["input"]["token_types"]["SELF"]["fields"]["held"]["component_scales"][1] = "unipolar10"
        def unit(d):
            d["input"]["token_types"]["SELF"]["fields"]["held"]["component_units"][0] = "g"
        def field_scale(d):
            d["input"]["token_types"]["GOAL"]["fields"]["deadline"]["scale"] = "time"
        for edit in (scale, unit, field_scale):
            _, conflicts = self.reg.diff(ModelInterface.from_dict(changed(edit)))
            self.assertTrue(conflicts, edit.__name__)

    def test_a_property_added_to_the_object_vector_is_an_update_not_a_conflict(self):
        new = ModelInterface.from_dict(changed(add_property))
        add, conflicts = self.reg.diff(new)
        self.assertEqual(conflicts, [])
        self.assertTrue(any("new components" in a for a in add))
        up = self.reg.updated(new)
        for t, f in VECTOR_FIELDS:                                  # the old columns did not move
            old, now = self.reg.types[t].fields[f], up.types[t].fields[f]
            self.assertEqual([(c.name, c.col) for c in now.components[:-1]], [(c.name, c.col) for c in old.components])
            self.assertEqual(now.components[-1].name, "zzprop")
            self.assertEqual(now.components[-1].col, self.reg.types[t].end("num"))      # the next free column
            self.assertEqual(now.width, old.width + 1)
        self.assertEqual(up.diff(new), ([], []))
        self.assertEqual(up.widths()["num"], max(t.end("num") for t in up.types.values()))
        # the layout reads it: same values in the old columns, the new component further on
        lay_old, lay_new = Tokenizer().layout, Layout(new, InputVocabulary(new, up.symbols), up)
        held_old, held_new = lay_old.types["SELF"].columns["held"], lay_new.types["SELF"].columns["held"]
        self.assertEqual(held_new.codec.cols[:-1], held_old.codec.cols)
        self.assertEqual(held_new.codec.cols[-1], self.reg.types["SELF"].end("num"))
        from tok2.tokenizer import Tokenizer as T
        tok_new = T(new, up)
        ctx0 = base(Record("THING", "@T1", {"props": {"mass": 3.0, "zzprop": 7.0}}))
        e_new = tok_new.encode(ctx0)
        r, c = e_new.keys.index("@T1"), lay_new.types["THING"].columns["props"].codec
        self.assertAlmostEqual(float(e_new.num[r, c.cols[0]]), np.log1p(3.0), places=2)
        self.assertAlmostEqual(float(e_new.num[r, c.cols[-1]]), np.log1p(7.0), places=2)
        self.assertEqual(e_new.known[r, c.cols[-1]], 1)
        # and a record that does not mention it is encoded exactly as before in the old columns
        ctx1 = base(Record("THING", "@T1", {"props": {"mass": 3.0}}))
        old, new_ = Tokenizer().encode(ctx1), tok_new.encode(ctx1)
        w = old.num.shape[1]
        self.assertTrue((old.num == new_.num[:, :w]).all() and (old.known == new_.known[:, :w]).all())

    def test_a_removed_component_stays_reserved_and_a_rename_never_reuses_its_column(self):
        def remove(d):
            for t, f in VECTOR_FIELDS:
                spec = d["input"]["token_types"][t]["fields"][f]
                for k in ("components", "component_scales", "component_units"):
                    spec[k].remove(spec[k][1]) if k == "components" else spec[k].pop(1)
        new = ModelInterface.from_dict(changed(remove))
        up = self.reg.updated(new)
        e = up.types["SELF"].fields["held"]
        gone = e.components[1]
        self.assertTrue(gone.retired)
        self.assertEqual(gone.col, self.reg.types["SELF"].fields["held"].components[1].col)
        lay = Layout(new, InputVocabulary(new, up.symbols), up)
        self.assertNotIn(gone.col, lay.types["SELF"].columns["held"].codec.cols)
        # renamed = retired + appended: the new name takes a fresh column
        def rename(d):
            for t, f in VECTOR_FIELDS:
                d["input"]["token_types"][t]["fields"][f]["components"][1] = "extent"
        up2 = self.reg.updated(ModelInterface.from_dict(changed(rename)))
        e2 = up2.types["SELF"].fields["held"]
        self.assertTrue(e2.components[1].retired and e2.components[1].name == "size")
        self.assertEqual(e2.components[-1].name, "extent")
        self.assertNotEqual(e2.components[-1].col, e2.components[1].col)

    def test_the_old_registry_format_is_completed_not_rejected(self):
        d = self.reg.to_dict()
        d["schema"] = "tok2-registry-1"
        del d["widths"]
        for t in d["types"].values():
            for f in t["fields"].values():
                for k in ("scale", "unit", "list_of", "components"):
                    f.pop(k, None)
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "r.json"
            p.write_text(json.dumps(d))
            old = Registry.load(p)
            add, conflicts = old.diff(ModelInterface())
            self.assertEqual(conflicts, [])
            self.assertEqual(old.updated(ModelInterface()).to_dict(), self.reg.to_dict())


class TestRegistryFileIntegrity(unittest.TestCase):
    def broken(self, edit):
        d = Registry.load().to_dict()
        edit(d)
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "r.json"
            p.write_text(json.dumps(d))
            with self.assertRaises(TokenError):
                Registry.load(p)

    def test_duplicate_type_ids(self):
        self.broken(lambda d: d["types"]["WAKE"].update(id=d["types"]["BELIEF"]["id"]))

    def test_overlapping_columns(self):
        def edit(d):
            f = d["types"]["BELIEF"]["fields"]
            f["certainty"]["col"] = f["age"]["col"]
        self.broken(edit)

    def test_a_vector_component_on_another_field(self):
        def edit(d):
            d["types"]["SELF"]["fields"]["held"]["components"][0]["col"] = d["types"]["SELF"]["fields"]["age"]["col"]
        self.broken(edit)

    def test_duplicate_symbols(self):
        self.broken(lambda d: d["symbols"].append(d["symbols"][10]))

    def test_declared_widths_must_match_the_columns(self):
        self.broken(lambda d: d["widths"].update(num=d["widths"]["num"] - 1))
        self.broken(lambda d: d["types"]["BELIEF"]["fields"]["age"].update(col=500))

    def test_unknown_block_and_duplicate_components(self):
        self.broken(lambda d: d["types"]["BELIEF"]["fields"]["age"].update(block="zzz"))
        self.broken(lambda d: d["types"]["SELF"]["fields"]["held"]["components"][1].update(
            name=d["types"]["SELF"]["fields"]["held"]["components"][0]["name"]))

    def test_malformed_and_wrong_schema(self):
        self.broken(lambda d: d.update(schema="nope"))
        self.broken(lambda d: d["types"]["BELIEF"].pop("id"))

    def test_the_committed_registry_passes(self):
        Registry.load().validate()


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
        self.assertEqual(DecisionContext.loads(c.dumps(self.tok), self.tok).known_keys, frozenset(c.known_keys))
        d = base()
        self.assertIsNone(DecisionContext.loads(d.dumps(self.tok), self.tok).known_keys)

    def test_unserializable_values_are_a_token_error(self):
        with self.assertRaises(TokenError):
            base(Record("ENTITY", "@E1", {"dist": object()})).dumps(self.tok)
        with self.assertRaises(TokenError):
            base(Record("ENTITY", "@E1", {"dist": float("nan")})).dumps(self.tok)


if __name__ == "__main__":
    unittest.main()
