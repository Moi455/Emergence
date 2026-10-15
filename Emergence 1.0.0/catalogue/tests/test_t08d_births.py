"""T08d (P53): births. The catalogue holds conceive and gestate_birth; the trigger of conceive is the existing
touch(manner=intimate) already authorised by the governor between two fertile ADULTS. D10 REFUSAL tests: they
generate no content (a verdict is checked, nothing is written or labelled)."""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tools"))
from schema import Catalogue  # noqa: E402
from governor import CrossedTouch, Governor, Party  # noqa: E402

A = Party(real_age=30, believed_age=30, apparent_age=31, resolved=True)
B = Party(real_age=28, believed_age=28, apparent_age=27, resolved=True)
TOUCH = {"manner": "intimate", "with": "arms", "contact_zone": "body", "duration": "a_while"}


def gate(g, actor=A, partner=B, a_sees=B, b_sees=A, fertile=True, params=TOUCH, params_ba=None, dt=60, third=False):
    """Two crossed touches A->B and B->A, dt game seconds apart (a third person: B's gesture goes to C)."""
    ab = CrossedTouch("A", "B", params, 1000)
    ba = CrossedTouch("B", "C" if third else "A", params if params_ba is None else params_ba, 1000 + dt)
    return g.conception_gate(ab, ba, actor, partner, a_sees, b_sees, fertile)


class TestBirths(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cat = Catalogue.load()
        cls.g = Governor(cls.cat)

    # ---- the catalogue ----
    def test_the_two_laws_exist_and_no_new_gesture_or_value(self):
        for pid in ("conceive", "gestate_birth"):
            self.assertIn(pid, self.cat["process"])
        self.assertEqual(len(self.cat["action"]), 40)
        touch = self.cat["action"]["touch"]
        manner = next(p for p in touch.params if p.name == "manner")
        self.assertEqual(manner.values, ["gentle", "firm", "playful", "romantic", "intimate"])
        self.assertEqual(manner.intimate_values, ["romantic", "intimate"])

    def test_gestation_is_in_real_hours_on_the_life_clock(self):
        pc = self.cat["process"]["gestate_birth"]
        self.assertEqual(pc.clock, "life")
        game_day_s = 86400                                  # 1 game day = 1 h 30 real (D30)
        real_hours = pc.nominal_game_s / game_day_s * 1.5
        self.assertAlmostEqual(real_hours, 11 / 6, places=3)  # 1 h 50
        self.assertEqual(self.cat["process"]["conceive"].clock, "real")

    def test_no_truth_in_tokens_for_the_birth_variables(self):
        for vid in ("fecundity", "pregnancy", "biological_parents"):
            v = self.cat["variable"][vid]
            self.assertEqual(v.visibility, "engine", vid)
            self.assertFalse(v.token, vid)
            self.assertFalse(any(w.startswith("T_") for w in v.writer), vid)
        self.assertEqual(self.cat["component"]["lifecycle"].engine_only, True)

    def test_nothing_explicit_in_the_wording(self):
        bad = re.compile(r"sexuel|coït|coit|pénétr|\bnu\b|\bnue\b|orgasm|copul|accoupl|éjacul|érot|baiser", re.I)
        for pid in ("conceive", "gestate_birth"):
            pc = self.cat["process"][pid]
            for text in (pc.label_fr, pc.effect, pc.inputs, pc.trigger, pc.note):
                self.assertIsNone(bad.search(text), (pid, text))
        for sid in ("marriage_and_children", "pregnancy_birth"):
            st = self.cat["story"][sid]
            self.assertEqual(st.status, "expressible")
            self.assertIsNone(bad.search(st.note + st.text_fr), sid)

    # ---- the opening of the trigger: two known fertile adults ----
    def test_two_adults_open_the_trigger(self):
        self.assertTrue(gate(self.g).allowed)

    def test_infertile_or_not_the_gesture_stays_closed(self):
        self.assertEqual(gate(self.g, fertile=False).code, "not_fertile")
        self.assertFalse(gate(self.g, params={**TOUCH, "manner": "gentle"}).allowed)
        self.assertFalse(gate(self.g, params={**TOUCH, "manner": "romantic"}).allowed)

    # ---- RECIPROCITY: "if TWO NPCs did the act" (Monsieur) ----
    def test_a_one_sided_gesture_is_refused(self):
        self.assertEqual(self.g.conception_gate(CrossedTouch("A", "B", TOUCH, 0), None, A, B, B, A, True).code, "not_reciprocal")
        self.assertEqual(self.g.conception_gate(None, None, A, B, B, A, True).code, "not_reciprocal")
        same = self.g.conception_gate(CrossedTouch("A", "B", TOUCH, 0), CrossedTouch("A", "B", TOUCH, 5), A, B, B, A, True)
        self.assertEqual(same.code, "not_reciprocal")                      # the same person twice is not two persons
        self.assertEqual(gate(self.g, params_ba={**TOUCH, "manner": "gentle"}).code, "not_conception_gesture")

    def test_the_window_is_in_game_seconds(self):
        w = self.g.CONCEIVE_WINDOW_S
        self.assertEqual(w, 1800)
        self.assertTrue(gate(self.g, dt=w).allowed)
        self.assertEqual(gate(self.g, dt=w + 1).code, "window_exceeded")
        self.assertEqual(gate(self.g, dt=-(w + 1)).code, "window_exceeded")
        for bad in (float("nan"), float("inf")):
            self.assertFalse(gate(self.g, dt=bad).allowed)

    def test_a_crossing_with_a_third_person_is_refused(self):
        self.assertEqual(gate(self.g, third=True).code, "not_reciprocal")

    def test_no_couple_or_marriage_is_required(self):
        self.assertTrue(gate(self.g).allowed)      # strangers: the gate looks at ages and reciprocity only

    # ---- REFUSALS D10 (no content generated) ----
    def test_refused_for_a_real_minor(self):
        for age in (0, 2, 9, 14, 17, 17.96):
            kid = Party(real_age=age, believed_age=30, apparent_age=30, resolved=True)   # real age alone
            self.assertFalse(gate(self.g, partner=kid, a_sees=kid).allowed, age)
            self.assertFalse(gate(self.g, actor=kid, b_sees=kid).allowed, age)

    def test_refused_for_a_believed_minor(self):
        believed = Party(real_age=30, believed_age=15, apparent_age=30, resolved=True)
        self.assertFalse(gate(self.g, partner=B, a_sees=believed).allowed)
        self.assertFalse(gate(self.g, actor=A, b_sees=believed).allowed)

    def test_refused_for_an_apparent_minor(self):
        looks = Party(real_age=30, believed_age=30, apparent_age=16, resolved=True)
        self.assertFalse(gate(self.g, a_sees=looks).allowed)
        self.assertFalse(gate(self.g, b_sees=looks).allowed)

    def test_refused_for_an_unknown_age_by_default(self):
        for weak in (Party(real_age=30, believed_age=None, apparent_age=30, resolved=True),
                     Party(real_age=30, believed_age=30, apparent_age=None, resolved=True),
                     Party(real_age=None, believed_age=30, apparent_age=30, resolved=True),
                     Party(real_age=30, believed_age=30, apparent_age=30, resolved=False),
                     Party(real_age=float("nan"), believed_age=30, apparent_age=30, resolved=True),
                     Party()):
            self.assertFalse(gate(self.g, a_sees=weak).allowed)
            self.assertFalse(gate(self.g, b_sees=weak).allowed)
            self.assertFalse(gate(self.g, partner=weak).allowed)
            self.assertFalse(gate(self.g, actor=weak).allowed)
        ab, ba = CrossedTouch("A", "B", TOUCH, 0), CrossedTouch("B", "A", TOUCH, 0)
        self.assertFalse(self.g.conception_gate(ab, ba, A, B, None, None, True).allowed)    # views missing
        self.assertFalse(self.g.conception_gate(ab, ba, None, None, None, None, True).allowed)

    def test_refused_for_a_person_out_of_sight(self):
        out = Party(real_age=30, believed_age=30, apparent_age=30, resolved=True, perceived=False)
        self.assertFalse(out.may_be_minor())                 # real and believed are adults, but not PERCEIVED now
        self.assertFalse(gate(self.g, a_sees=out).allowed)
        self.assertFalse(gate(self.g, b_sees=out).allowed)

    def test_the_other_direction_alone_is_not_enough(self):
        young = Party(real_age=30, believed_age=30, apparent_age=15, resolved=True)
        self.assertFalse(gate(self.g, a_sees=B, b_sees=young).allowed)

    def test_the_existing_refusals_of_the_gesture_are_untouched(self):
        kid = Party(real_age=9, believed_age=9, apparent_age=9, resolved=True)
        self.assertFalse(self.g.check_gesture("touch", TOUCH, A, {"target": kid}).allowed)
        self.assertTrue(self.g.check_gesture("touch", {"manner": "gentle", "with": "hand", "contact_zone": "hands"},
                                             A, {"target": kid}).allowed)


if __name__ == "__main__":
    unittest.main()
