"""T23: the percept rules (engine/act/perception) are checked against the catalogue. No rule reads an engine-only
variable (the truth never enters a percept), every target is a percept variable, and the generated table is the one
shipped. The C++ test (test_perception) re-checks the generated table and perturbs every engine-only variable."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tools"))
from schema import Catalogue  # noqa: E402
import gen_cpp  # noqa: E402


class TestPerceptRules(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cat = Catalogue.load()
        cls.gen = gen_cpp.PerceptionGenerator(cls.cat)

    def test_the_shipped_rules_are_clean(self):
        self.assertEqual(self.gen.problems(), [])

    def test_no_source_is_engine_only(self):
        V = self.cat["variable"]
        for tgt, src, *_ in gen_cpp.PERCEPT_RULES:
            for one in src.split(","):
                name = one.lstrip("~")
                if name in V:
                    self.assertNotEqual(V[name].visibility, "engine", f"{tgt} <- {src}")

    def test_targets_are_percept_variables(self):
        V = self.cat["variable"]
        for tgt, *_ in gen_cpp.PERCEPT_RULES:
            self.assertIn(V[tgt].holder, gen_cpp.PERCEPT_HOLDERS)
            self.assertNotEqual(V[tgt].visibility, "engine", tgt)

    def test_a_rule_reading_the_truth_is_refused(self):
        bad = gen_cpp.PERCEPT_RULES + [("ep_age", "life_clock", "Sight", 300, "Copy")]   # life_clock = the real age, engine-only
        saved = gen_cpp.PERCEPT_RULES
        try:
            gen_cpp.PERCEPT_RULES = bad
            problems = gen_cpp.PerceptionGenerator(self.cat).problems()
        finally:
            gen_cpp.PERCEPT_RULES = saved
        self.assertTrue(any("engine-only" in p for p in problems), problems)

    def test_a_tilde_source_cannot_hide_an_engine_variable(self):
        saved = gen_cpp.PERCEPT_RULES
        try:
            gen_cpp.PERCEPT_RULES = saved + [("ep_age", "~life_clock", "Sight", 300, "Computed")]
            problems = gen_cpp.PerceptionGenerator(self.cat).problems()
        finally:
            gen_cpp.PERCEPT_RULES = saved
        self.assertTrue(any("engine-only" in p for p in problems), problems)

    def test_non_perceptible_properties_are_flagged(self):
        text = self.gen.generate()
        for pid, pr in self.cat["property"].items():
            if not pr.perceptible:
                line = [ln for ln in text.splitlines() if ln.startswith(f'  {{"{pid}", PropCat')][0]
                self.assertRegex(line, r"PropCat::\w+, false, ", pid)

    def test_shipped_file_is_up_to_date(self):
        self.assertEqual(gen_cpp.PERCEPT_OUT.read_text(encoding="utf-8"), self.gen.generate())


if __name__ == "__main__":
    unittest.main()
