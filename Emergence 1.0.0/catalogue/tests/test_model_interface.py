"""Tests of the generated model interface (python3 -m unittest discover -s catalogue/tests)."""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tools"))
from schema import Catalogue  # noqa: E402
import budget  # noqa: E402
import model_interface  # noqa: E402


class TestModelInterface(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cat = Catalogue.load()
        cls.mi = model_interface.ModelInterface(cls.cat)
        cls.spec = cls.mi.build()

    def test_the_generated_file_is_up_to_date(self):
        self.assertEqual((ROOT / "generated" / "model_interface.json").read_text(encoding="utf-8"), self.mi.text())

    def test_schema_version_3(self):
        self.assertEqual(self.spec["schema_version"], "model-interface-3")

    def test_every_mref_field_declares_the_record_types_it_accepts(self):
        types = self.spec["input"]["token_types"]
        seen = 0
        for t, s in types.items():
            for f, spec in s["fields"].items():
                if spec["scale"] == "mref" or (spec["scale"] == "list" and spec["list_of"] == "mref"):
                    seen += 1
                    self.assertTrue(spec.get("ref_types"), f"{t}.{f}")
                    self.assertTrue(set(spec["ref_types"]) <= set(types), f"{t}.{f}")
        self.assertGreaterEqual(seen, 20)
        self.assertEqual(types["WAKE"]["fields"]["trigger"]["ref_types"], ["EVENT", "HEARD", "REQUEST", "GOAL", "PLAN", "COMMIT", "ENTITY", "GROUP"])

    def test_a_new_mref_field_without_ref_types_is_refused(self):
        class Bad(model_interface.ModelInterface):
            REF_TYPES = {k: v for k, v in model_interface.ModelInterface.REF_TYPES.items() if k != "PLAN.goal"}
        with self.assertRaises(ValueError):
            Bad(self.cat).build()

    def test_deadlines_are_hours_until_in_the_input_and_in_the_writes(self):
        f = self.spec["input"]["token_types"]
        self.assertEqual(f["GOAL"]["fields"]["deadline"]["scale"], "time_until")
        self.assertEqual(f["COMMIT"]["fields"]["deadline"]["scale"], "time_until")
        self.assertEqual(f["GOAL"]["fields"]["age"]["scale"], "time")
        w = self.spec["output"]["writes"]["writable"]
        self.assertEqual(w["g_deadline"]["scale"], "time_until")
        self.assertEqual(w["g_priority"]["scale"], self.cat["variable"]["g_priority"].scale)

    def test_plan_layout_describes_the_fields(self):
        text = self.spec["input"]["token_types"]["PLAN"]["layout"]
        for word in ("step", "next", "goal", "target", "progress", "commitment"):
            self.assertIn(word, text)

    def test_two_vectors_are_multi_and_the_counter_ignores_pseudo_fields(self):
        f = self.spec["input"]["token_types"]
        self.assertTrue(f["SELF"]["fields"]["held"]["multi"] and f["ENTITY"]["fields"]["look.held"]["multi"])
        self.assertNotIn("multi", f["THING"]["fields"]["props"])
        counted = budget.counted_slots(self.cat)
        for typ, fields in counted.items():
            self.assertNotIn(typ, fields, f"{typ}: the type's own name is not a field")

    def test_gaze_and_attention_reach_events_and_places(self):
        f = self.spec["input"]["token_types"]
        self.assertTrue({"LOCUS", "PLACE"} <= set(f["ENTITY"]["fields"]["look.gaze"]["ref_types"]))
        self.assertTrue({"EVENT", "HEARD"} <= set(f["SELF_STATE"]["fields"]["attention"]["ref_types"]))

    def test_the_budget_counts_the_hand_written_types_too(self):
        counted = budget.counted_slots(self.cat)
        for typ, fields in model_interface.ModelInterface.EXPLICIT.items():
            self.assertTrue(set(fields) <= counted[typ], typ)
        self.assertIn("WAKE", budget.BUDGET)
        for typ, b in budget.BUDGET.items():
            self.assertLessEqual(len(counted.get(typ, ())), b, typ)
        self.assertEqual(set(self.spec["input"]["token_types"]["WAKE"]["fields"]), set(counted["WAKE"]))


if __name__ == "__main__":
    unittest.main()
