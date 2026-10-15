"""Corrections d'avant T09 (15 oct. 2026) : noms de symboles sans jugement (D28), temps rapportés à la durée d'une vie (D30)."""
import re
import statistics
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tools"))
from schema import Catalogue  # noqa: E402
import language  # noqa: E402

DAY = 86_400                       # a game day in game seconds (1 h 30 real x 16)
LIFE_DAYS = 100                    # 150 h of real life = 100 game days
REASONABLE_DAYS = 10               # a tenth of a life: beyond, it is declared and justified

# Every word added by T08a-c that names a manner, a plan state, a wake cause, an odour or an age (examined for D28).
T08_WORDS = {"rising", "trembling", "low_slow", "drawling", "growing", "twist", "hear", "wink", "cover_face", "trace_sign",
             "running", "suspended", "blocked", "done", "abandoned", "failed", "interrupted", "limit_reached", "once", "every",
             "goal_check", "occasion", "idle", "smoky", "sweet", "sour", "acrid", "musty", "putrid", "aromatic", "rancid",
             "new", "worn", "old"}
HEDONIC = {"bright", "grave", "foul", "fragrant", "timeout", "good", "bad", "nice", "pleasant", "unpleasant", "lovely", "fine",
           "stinking", "stinky", "delicious", "gross", "awful", "beautiful", "ugly", "cheerful", "gloomy", "solemn", "merry"}
HEDONIC_FR = re.compile(r"\b(bon|bonne|mauvais|mauvaise|beau|belle|laid|laide|agréable|désagréable|joli|dégoûtant|puant|"
                        r"délicieux|horrible|trop long)\b")


class TestT09Corrections(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cat = Catalogue.load()
        cls.vocab = language.Vocabulary(cls.cat)

    def test_renamed_symbols_are_gone_and_the_new_ones_are_there(self):
        tone = next(p for p in self.cat["action"]["speak"].params if p.name == "tone")
        self.assertTrue({"rising", "low_slow"} <= set(tone.values))
        self.assertFalse({"bright", "grave"} & set(tone.values))
        for new, old, cat in (("aromatic", "fragrant", "odor"), ("putrid", "foul", "odor"), ("limit_reached", "timeout", "plan_state")):
            self.assertTrue(self.vocab.is_(new, cat), new)
            self.assertNotIn(old, self.vocab.cats, old)
        self.assertIn("limit_reached", self.cat["variable"]["w_outcome"].values)
        self.assertNotIn("timeout", self.cat["variable"]["w_outcome"].values)

    def test_no_old_name_survives_in_the_data_the_tests_or_the_probes(self):
        old = re.compile(r"\b(bright|grave|foul|fragrant|timeout)\b")
        files = list((ROOT / "data").glob("*.toml")) + [p for p in (ROOT / "tests").glob("test_*.py") if p.name != Path(__file__).name]
        for f in files:
            for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                self.assertIsNone(old.search(line), f"{f.name}:{n}: {line[:120]}")

    def test_no_new_word_of_t08_is_hedonic_or_judging(self):
        for w in sorted(T08_WORDS):
            self.assertIn(w, self.vocab.cats, w)
            self.assertNotIn(w, HEDONIC, w)
        for w in T08_WORDS:
            for c in self.cat["concept"].values():
                if c.id == w:
                    self.assertIsNone(HEDONIC_FR.search(c.label_fr.lower()), f"{w}: {c.label_fr}")

    # ---- time (D30): 1 game day = 1 h 30 real; a life = 150 h = 100 game days ----------------------------------------------
    def test_germination_is_shorter_than_every_crop_maturity(self):
        germ = self.cat["process"]["germinate"].nominal_game_s
        self.assertEqual(germ, DAY // 2)
        crops = [s for s in self.cat["species"].values() if s.kingdom == "plant" and s.days_to_mature and s.harvest_window_days]
        self.assertTrue(crops)
        for s in crops:
            self.assertLess(germ, s.days_to_mature * DAY, s.id)

    def test_illness_course_matches_the_illness_table(self):
        courses = [i.course_days for i in self.cat["illness"].values()]
        nominal = self.cat["process"]["illness_course"].nominal_game_s
        self.assertEqual(nominal, int(statistics.median(courses)) * DAY)
        self.assertTrue(min(courses) * DAY <= nominal <= max(courses) * DAY)
        note = self.cat["process"]["illness_course"].note
        self.assertIn("lung_rot", self.cat["illness"])
        for ill in self.cat["illness"].values():
            if ill.course_days > REASONABLE_DAYS:
                self.assertEqual(ill.id, "lung_rot")                      # the one declared exception
                self.assertIn("h réelles", note)
                self.assertIn("20 %", note)                               # justified in real hours and in share of a life

    def test_durations_stay_a_reasonable_fraction_of_a_life(self):
        long_by_nature = {"grapevine", "cherry_tree", "apple_tree", "pear_tree", "walnut_tree", "date_palm", "olive_tree",
                          "horse", "camel"}      # orchards and big animals: a multi-year investment (a year = 4,7 game days)
        over = []
        for pid, p in self.cat["process"].items():
            if p.nominal_game_s > REASONABLE_DAYS * DAY:
                over.append(("process", pid))
        for sid, s in self.cat["species"].items():
            for name in ("days_to_mature", "harvest_window_days", "product_regrow_days"):
                if getattr(s, name) > REASONABLE_DAYS and sid not in long_by_nature:
                    over.append((sid, name))
        self.assertEqual(over, [])
        for sid in long_by_nature:
            self.assertGreater(self.cat["species"][sid].days_to_mature, REASONABLE_DAYS, sid)    # the list stays honest
            self.assertLessEqual(self.cat["species"][sid].days_to_mature, LIFE_DAYS // 2, sid)


if __name__ == "__main__":
    unittest.main()
