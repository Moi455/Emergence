"""T08b : buts, plans, organisations. Le moteur ne juge jamais (P35, P50)."""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tools"))
from schema import Catalogue  # noqa: E402
import budget  # noqa: E402
import model_interface  # noqa: E402


class TestT08b(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cat = Catalogue.load()
        cls.var = cls.cat["variable"]

    def test_no_engine_writer_on_g_status(self):
        self.assertEqual(self.var["g_status"].writer, ["T_jump"])

    def test_no_engine_writer_on_a_verdict_variable(self):
        # aucune variable enum écrite par le moteur ne porte un verdict : atteint, tenu, rompu
        for v in self.var.values():
            if "engine" in v.writer and v.scale == "enum":
                bad = {"achieved", "fulfilled", "broken", "kept"} & set(v.values)
                self.assertFalse(bad, f"{v.id}: le moteur écrirait {bad}")

    def test_failed_expired_blocked_only_when_they_are_facts(self):
        """failed / expired / blocked peuvent venir d'un jugement (le résultat comparé au but, un engagement tenu) ou d'un
        fait (un geste sans effet perçu, une date passée, un passage fermé). Écrites par le moteur, elles doivent être
        déclarées comme des FAITS (dynamics) dont la cause est perçue ou datée, jamais comparées au but."""
        judging = ("échec", "raté", "réussi", "non tenu", "rempli", "rompu", "atteint le but", "résultat visé")
        facts = {"failed": ("sans effet", "c_blocked"), "blocked": ("sans effet", "c_blocked", "fermé", "empêché"),
                 "expired": ("échéance", "date")}
        seen = set()
        for v in self.var.values():
            if "engine" not in v.writer or v.scale != "enum":
                continue
            text = (v.label_fr + " " + v.dynamics).lower()
            for word in set(v.values) & set(facts):
                seen.add((v.id, word))
                self.assertIn("fait", text, f"{v.id}.{word}: pas déclaré comme un fait")
                self.assertTrue(any(m in text for m in facts[word]), f"{v.id}.{word}: cause de fait non dite {facts[word]}")
                self.assertFalse([j for j in judging if re.search(r"\b" + j, v.label_fr.lower())], f"{v.id}.{word}: libellé de jugement")
                self.assertFalse([j for j in ("raté", "réussi", "résultat visé", "atteint le but") if j in v.dynamics.lower()],
                                 f"{v.id}.{word}: jugement dans la dynamique")
        self.assertEqual(seen, {("w_outcome", "failed"), ("w_outcome", "blocked"), ("i_status", "blocked"), ("a_status", "expired")})
        # le texte de la langue dit la même chose
        words = self.cat["concept"]
        for w in ("failed", "blocked"):
            label = words[w].label_fr.lower()
            self.assertIn("sans effet perçu", label)
            self.assertFalse([j for j in judging if re.search(r"\b" + j, label)], w)

    def test_engine_never_writes_abandoned(self):
        self.assertIn("abandoned", self.var["i_status"].values)
        self.assertIn("T_jump", self.var["i_status"].writer)
        self.assertIn("jamais le moteur", self.var["i_status"].dynamics)

    def test_agreement_status_is_facts_only(self):
        self.assertEqual(self.var["a_status"].values, ["open", "expired", "released", "void"])
        self.assertFalse(self.var["a_status"].token)          # jamais montré

    def test_reserve_of_four_intentions(self):
        self.assertEqual(self.cat["component"]["intention"].max_count, 4)
        self.assertEqual(budget.TOKENS["PLAN"], 2)

    def test_repeat_and_plan_variables(self):
        self.assertEqual(self.var["i_repeat"].values, ["once", "each_day", "each_season", "each_year", "every"])
        self.assertEqual(self.var["i_repeat_period"].scale, "qty")
        for vid in ("i_steps", "i_step_targets", "i_speech", "i_repeat", "i_repeat_period", "g_parent"):
            self.assertIn("T_jump", self.var[vid].writer, vid)

    def test_wake_causes_are_appended_and_triggers_widened(self):
        cause = model_interface.ModelInterface.EXPLICIT["WAKE"]["cause"]["values"]
        self.assertEqual(cause[:7], ["perception", "speech", "request", "body", "plan", "timer", "routine"])
        self.assertEqual(cause[7:], ["goal_check", "occasion", "idle"])
        trig = model_interface.ModelInterface.REF_TYPES["WAKE.trigger"]
        for t in ("COMMIT", "ENTITY", "GROUP"):
            self.assertIn(t, trig)

    def test_group_fields_are_believed_not_true(self):
        for vid in ("r_group_my_task", "r_group_tasks_open", "r_group_present"):
            v = self.var[vid]
            self.assertEqual(v.writer, ["derived"])
            self.assertEqual(v.visibility, "private")
            for r in v.reads:                              # ne lit que croyances et perceptions
                self.assertIn(self.cat._channel(self.var[r].holder), ("belief", "perception"), f"{vid} lit {r}")
        self.assertFalse(self.var["s_last_believed"].token)   # un fait du moteur, jamais un jeton

    def test_budget_within_limits(self):
        s = budget.counted_slots(self.cat)
        for typ in ("GOAL", "PLAN", "GROUP", "WAKE"):
            self.assertLessEqual(len(s[typ]), budget.BUDGET[typ], typ)
        self.assertLessEqual(sum(budget.TOKENS.values()), budget.MAX_TOKENS)


if __name__ == "__main__":
    unittest.main()
