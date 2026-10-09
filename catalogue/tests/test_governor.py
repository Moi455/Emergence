"""Tests of the reference governor (catalogue/tools/governor.py): bounds and hard rule D10."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tools"))
from schema import Catalogue  # noqa: E402
from governor import Governor, Party, WriteLedger  # noqa: E402
import language  # noqa: E402

ADULT = Party(real_age=30, believed_age=30, apparent_age=31, resolved=True)
ADULT2 = Party(real_age=40, believed_age=38, apparent_age=41, resolved=True)
CHILD = Party(real_age=9, believed_age=9, apparent_age=9, resolved=True)


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
        looks_young = Party(real_age=25, believed_age=25, apparent_age=16, resolved=True)
        believed_young = Party(real_age=25, believed_age=15, apparent_age=25, resolved=True)
        unknown_age = Party(real_age=25, believed_age=None, apparent_age=25, resolved=True)
        name_only = Party(real_age=25, believed_age=25, apparent_age=25, resolved=False)
        nan_age = Party(real_age=25, believed_age=float("nan"), apparent_age=25, resolved=True)
        romantic = {"target": "@E1", "with": "lips", "contact_zone": "face", "manner": "romantic", "duration": "brief"}
        self.assertTrue(self.g.check_gesture("touch", romantic, ADULT, {"target": ADULT2}).allowed)
        for p in (CHILD, looks_young, believed_young, unknown_age, name_only, nan_age):
            self.assertFalse(self.g.check_gesture("touch", romantic, ADULT, {"target": p}).allowed)

    def test_d10_deny_by_default(self):
        romantic = {"target": "@E1", "with": "lips", "contact_zone": "face", "manner": "romantic"}
        self.assertFalse(self.g.check_gesture("touch", romantic, ADULT, {}).allowed)          # party not given
        self.assertFalse(self.g.check_gesture("touch", romantic, None, {"target": ADULT2}).allowed)
        self.assertFalse(self.g.check_write("r_attraction", 0, 0.5, WriteLedger(), "f9").allowed)   # no parties
        self.assertFalse(self.g.check_write("r_attraction", 0, float("nan"), WriteLedger(), "f9",
                                            intimate_target=ADULT2, actor=ADULT).allowed)

    def test_d10_whitelist_lets_care_through_and_needs_every_param(self):
        hold_hand = {"target": "@E1", "with": "hand", "contact_zone": "hands", "manner": "gentle", "duration": "a_while"}
        self.assertTrue(self.g.check_gesture("touch", hold_hand, ADULT, {"target": CHILD}).allowed)
        lips = dict(hold_hand, **{"with": "lips", "contact_zone": "face"})
        self.assertFalse(self.g.check_gesture("touch", lips, ADULT, {"target": CHILD}).allowed)
        missing_zone = {k: v for k, v in hold_hand.items() if k != "contact_zone"}
        self.assertFalse(self.g.check_gesture("touch", missing_zone, ADULT, {"target": CHILD}).allowed)
        self.assertFalse(self.g.check_gesture("search", {"target": "@E1", "thoroughness": "brief"}, ADULT, {"target": CHILD}).allowed)
        rub = {"target": "@E1", "motion": "rub", "intensity": "light", "duration": "long", "contact_zone": "back"}
        self.assertFalse(self.g.check_gesture("work", rub, ADULT, {"target": CHILD}).allowed)
        bandage = {"target": "@E1", "motion": "press", "intensity": "light", "duration": "brief", "contact_zone": "arms"}
        self.assertTrue(self.g.check_gesture("work", bandage, ADULT, {"target": CHILD}).allowed)
        undress = {"item": "@T1", "mode": "take_off", "on": "@E1", "contact_zone": "arms"}
        self.assertFalse(self.g.check_gesture("wear", undress, ADULT, {"on": CHILD}).allowed)

    def test_d10_every_party_param_is_checked(self):
        # tie (target, to): the minor is the 'to' party
        tie = {"target": "@T1", "to": "@E1", "mode": "bind", "with": "@T2", "tightness": "hard", "contact_zone": "body"}
        self.assertFalse(self.g.check_gesture("tie", tie, ADULT, {"to": CHILD}).allowed)

    def test_d10_utterance_and_described_gestures(self):
        vocab = language.Vocabulary(self.cat)
        e = language.Expression("(request (did you touch me (how romantic)))", vocab)
        self.assertFalse(self.g.check_utterance(e, ADULT, {"you": CHILD, "me": ADULT}, [CHILD]).allowed)
        self.assertTrue(self.g.check_utterance(e, ADULT, {"you": ADULT2, "me": ADULT}, [ADULT2]).allowed)
        # a refused gesture described without any intimate word (lips on a child's face)
        f = language.Expression("(request (did me touch you (how lips) (how face)))", vocab)
        self.assertFalse(self.g.check_utterance(f, ADULT, {"you": CHILD, "me": ADULT}, [CHILD]).allowed)

    def test_d10_records(self):
        vocab = language.Vocabulary(self.cat)
        goal = language.Expression("(offer (did me touch @E1 (how romantic)))", vocab)
        self.assertFalse(self.g.check_record("goal", goal, ADULT, {"@E1": CHILD, "me": ADULT}).allowed)
        self.assertFalse(self.g.check_record("goal", goal, ADULT, {"me": ADULT}).allowed)      # @E1 unknown
        self.assertTrue(self.g.check_record("goal", goal, ADULT, {"@E1": ADULT2, "me": ADULT}).allowed)

    def test_memory_is_free_at_creation_then_steps(self):
        led = WriteLedger()
        self.assertEqual(self.g.check_write("m_valence", 0, -9, led, "m1", creating=True).value, -9)
        self.assertEqual(self.g.check_write("m_valence", -9, 0, led, "m1").value, -8)


if __name__ == "__main__":
    unittest.main()
