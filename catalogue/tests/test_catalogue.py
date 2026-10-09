"""Tests of the catalogue: loading, validation, and the layer rules (python3 -m unittest discover -s catalogue/tests)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from schema import Catalogue  # noqa: E402


class TestCatalogue(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cat = Catalogue.load()

    def test_valid(self):
        self.assertEqual(self.cat.validate(), [])

    def test_stories_exist(self):
        self.assertGreaterEqual(len(self.cat["story"]), 100)

    def test_every_component_is_used(self):
        used = {c for e in self.cat["entity"].values() for c in e.components}
        used |= {c.id for c in self.cat["component"].values() if c.part_of in used}
        self.assertEqual(sorted(set(self.cat["component"]) - used), [])

    def test_engine_materials_are_read_not_copied(self):
        engine = [m for m in self.cat["material"].values() if m.num >= 0]
        self.assertGreaterEqual(len(engine), 34)
        self.assertTrue(all(m.file == "engine/data/materials.csv" for m in engine))

    def test_only_agents_have_a_transformer(self):
        self.assertEqual([e.id for e in self.cat["entity"].values() if e.driven_by == "transformer"], ["agent"])

    def test_unplanned_assembly_has_properties(self):
        # a knife lashed to a stick: no archetype needed for it to cut, pierce and reach
        props = self.cat.item_properties(["blade:iron", "point:iron", "shaft:oak_raw", "cord:rope_fiber"])
        self.assertTrue({"edge", "point", "handle", "reach", "binds"} <= props)

    def test_every_form_is_used_by_a_known_type(self):
        used = {p.partition(":")[0] for it in self.cat["item_type"].values() for p in it.parts}
        self.assertEqual(sorted(set(self.cat["form"]) - used), [])

    def test_many_known_types(self):
        self.assertGreaterEqual(len(self.cat["item_type"]), 400)

    def test_engine_only_component_refuses_model_writer(self):
        cat = Catalogue()
        cat._add("component", {"id": "body", "engine_only": True}, "test")
        cat._add("variable", {"id": "pain", "holder": "body", "writer": ["T_jump"]}, "test")
        self.assertTrue(any("engine-only" in p for p in cat.validate()))

    def test_ai_budget(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
        import budget
        s = budget.slots(self.cat)
        for typ, b in budget.BUDGET.items():
            self.assertLessEqual(len(s.get(typ, ())), b, typ)
        self.assertLessEqual(sum(budget.TOKENS.values()), budget.MAX_TOKENS)

    def test_forbidden_action_is_caught(self):
        cat = Catalogue()
        cat._add("action", {"id": "blackmail", "family": "communicate"}, "test")
        self.assertTrue(any("social scheme" in p for p in cat.validate()))

    def test_unknown_field_is_caught(self):
        cat = Catalogue()
        cat._add("variable", {"id": "x", "writer": ["engine"], "colour": 3}, "test")
        self.assertTrue(any("unknown fields" in p for p in cat.validate()))


if __name__ == "__main__":
    unittest.main()
