"""Tests of the reference governor (catalogue/tools/governor.py): bounds and hard rule D10."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tools"))
from schema import Catalogue  # noqa: E402
from governor import Governor, Party, WriteLedger  # noqa: E402
import language  # noqa: E402

ADULT = Party(real_age=30, believed_age=30, apparent_age=31)
CHILD = Party(real_age=9, believed_age=9, apparent_age=9)


class TestGovernor(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cat = Catalogue.load()
        cls.g = Governor(cls.cat)

    def test_body_is_engine_owned(self):
        self.assertFalse(self.g.check_write("pain", 2, 0, WriteLedger()).allowed)

    def test_emotion_may_jump(self):
        v = self.g.check_write("fear", 0, 9, WriteLedger())
        self.assertTrue(v.allowed); self.assertEqual(v.value, 9)

    def test_relation_steps_and_daily_rate(self):
        led = WriteLedger()
        v = self.g.check_write("r_affection", 0, 5, led, target="E1")
        self.assertEqual(v.value, 0.5)
        x = 0.5
        for _ in range(10):
            x = self.g.check_write("r_affection", x, x + 1, led, target="E1").value
        self.assertLessEqual(x, 2.0 + 1e-9)          # rate 2 per game day
        led.roll(day=1, life_year=0)
        self.assertGreater(self.g.check_write("r_affection", x, x + 1, led, target="E1").value, x)

    def test_trait_moves_slowly(self):
        led = WriteLedger()
        x = 0.0
        for _ in range(100):
            x = self.g.check_write("assurance", x, x + 5, led).value
        self.assertLessEqual(x, 1.0 + 1e-9)           # 1 per life-year

    def test_sparse_writes(self):
        self.assertEqual(len(self.g.check_writes(list(range(9)))), 4)

    def test_d10_attraction_never_rises_toward_a_minor(self):
        self.assertFalse(self.g.check_write("r_attraction", 0, 0.5, WriteLedger(), target="E2",
                                            intimate_target=CHILD, actor=ADULT).allowed)
        self.assertTrue(self.g.check_write("r_attraction", 0, 0.5, WriteLedger(), target="E2",
                                           intimate_target=ADULT, actor=ADULT).allowed)

    def test_d10_any_of_real_believed_apparent_or_unresolved(self):
        looks_young = Party(real_age=25, believed_age=25, apparent_age=16)
        believed_young = Party(real_age=25, believed_age=15, apparent_age=25)
        unknown_age = Party(real_age=25, believed_age=None, apparent_age=25)
        name_only = Party(real_age=25, believed_age=25, apparent_age=25, resolved=False)
        romantic = {"with": "lips", "zone": "face", "manner": "romantic", "duration": "brief"}
        self.assertTrue(self.g.check_gesture("touch", romantic, ADULT, ADULT).allowed)
        for p in (CHILD, looks_young, believed_young, unknown_age, name_only):
            self.assertFalse(self.g.check_gesture("touch", romantic, ADULT, p).allowed)

    def test_d10_whitelist_lets_care_through(self):
        hold_hand = {"with": "hand", "zone": "hand", "manner": "gentle", "duration": "a_while"}
        self.assertTrue(self.g.check_gesture("touch", hold_hand, ADULT, CHILD).allowed)
        lips = {"with": "lips", "zone": "face", "manner": "gentle", "duration": "brief"}
        self.assertFalse(self.g.check_gesture("touch", lips, ADULT, CHILD).allowed)

    def test_d10_utterance(self):
        vocab = language.Vocabulary(self.cat)
        e = language.Expression("(request (did you touch me (how romantic)))", vocab)
        self.assertFalse(self.g.check_utterance(e, ADULT, [CHILD]).allowed)
        self.assertTrue(self.g.check_utterance(e, ADULT, [ADULT]).allowed)


if __name__ == "__main__":
    unittest.main()
