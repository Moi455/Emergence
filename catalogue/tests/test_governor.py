"""Tests of the reference governor (catalogue/tools/governor.py): bounds and hard rule D10."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tools"))
from schema import Catalogue  # noqa: E402
from governor import THING, Governor, Party, WriteLedger  # noqa: E402
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

    def test_d10_described_or_unidentified_participants(self):
        vocab = language.Vocabulary(self.cat)
        for text in ("(offer (did me touch (described d_tall) (how romantic)))",
                     "(offer (future (link me spouse (described d_tall))))",
                     "(assert (attitude me r_attraction (described d_tall) high))",
                     "(offer (did me touch someone (how romantic)))"):
            e = language.Expression(text, vocab)
            self.assertTrue(e.ok, (text, e.problems))
            self.assertFalse(self.g.check_utterance(e, ADULT, {"me": ADULT}).allowed, text)

    def test_d10_hearers_do_not_matter(self):
        vocab = language.Vocabulary(self.cat)
        married = language.Expression("(assert (link me spouse @E2))", vocab)
        self.assertTrue(self.g.check_utterance(married, ADULT, {"me": ADULT, "@E2": ADULT2}, [CHILD]).allowed)
        parents = language.Expression("(assert (link @E1 spouse @E2))", vocab)
        self.assertTrue(self.g.check_utterance(parents, CHILD, {"me": CHILD, "@E1": ADULT, "@E2": ADULT2}).allowed)

    def test_d10_intimate_acts_are_not_told_to_a_possible_minor(self):
        """Review 11: an intimate act or desire between adults, said to a child or to unknown hearers, is refused;
        to adults it is allowed; a cited record is unfolded; a private record is not said."""
        vocab = language.Vocabulary(self.cat)
        act = language.Expression("(assert (past (did @E2 touch @E3 (how romantic))))", vocab)
        adults = {"me": ADULT, "@E2": ADULT2, "@E3": ADULT}
        self.assertEqual(self.g.check_utterance(act, ADULT, adults, [CHILD]).code, "d10_hearer")
        self.assertEqual(self.g.check_utterance(act, ADULT, adults).code, "d10_hearer")          # hearers unknown
        self.assertTrue(self.g.check_utterance(act, ADULT, adults, [ADULT2]).allowed)
        cite = language.Expression("(assert (that b:1))", vocab)
        self.assertEqual(self.g.check_utterance(cite, ADULT, adults, [CHILD], expand=lambda r: act).code, "d10_hearer")
        self.assertTrue(self.g.check_record("belief", language.Expression("(assert (past (did @E2 touch @E3 (how romantic))))",
                                                                          vocab), ADULT, adults).allowed)

    def test_d10_bare_citations_are_unfolded_too(self):
        """Review 13: b:1 said without `that` carries the record as well."""
        vocab = language.Vocabulary(self.cat)
        act = language.Expression("(assert (past (did @E2 touch @E3 (how romantic))))", vocab)
        adults = {"me": ADULT, "@E2": ADULT2, "@E3": ADULT}
        for text in ("(assert b:1)", "(assert (not b:1))", "(assert (believes @E2 b:1))", "(assert (and b:1 b:1))"):
            e = language.Expression(text, vocab)
            self.assertTrue(e.ok, (text, e.problems))
            self.assertEqual(self.g.check_utterance(e, ADULT, adults, [CHILD], expand=lambda r: act).code, "d10_hearer", text)
            self.assertEqual(self.g.check_utterance(e, ADULT, adults, [ADULT2]).code, "unexpanded", text)
            self.assertTrue(self.g.check_utterance(e, ADULT, adults, [ADULT2], expand=lambda r: act).allowed, text)
        broken = language.Expression("(assert (no_such_word))", vocab)
        e = language.Expression("(assert b:1)", vocab)
        self.assertEqual(self.g.check_utterance(e, ADULT, adults, [ADULT2], expand=lambda r: broken).code, "unexpanded")
        self.assertEqual(self.g.check_utterance(e, ADULT, adults, [ADULT2], expand=lambda r: "text").code, "unexpanded")

    def test_engine_hearers_and_passers_by(self):
        """Review 15: without the engine's list of hearers, anyone in earshot may hear (except a whisper); the
        addressee always hears."""
        act = "(assert (past (did @E2 touch @E3 (how romantic))))"
        content = {"me": ADULT, "@E2": ADULT2, "@E3": ADULT}
        base = dict(params={"content": act, "to": "@E2"}, actor=ADULT, parties={"to": ADULT2}, executed=False,
                    content_parties=content)
        whisper = dict(base, params={"content": act, "to": "@E2", "volume": "whisper"})
        self.assertTrue(self.g.check_gesture("speak", **whisper).allowed)
        self.assertEqual(self.g.check_gesture("speak", **base).code, "d10_hearer")              # passers-by unknown
        self.assertTrue(self.g.check_gesture("speak", **base, hearers=[ADULT2]).allowed)
        self.assertEqual(self.g.check_gesture("speak", **base, hearers=[ADULT2, CHILD]).code, "d10_hearer")
        to_child = dict(base, parties={"to": CHILD})
        self.assertEqual(self.g.check_gesture("speak", **to_child, hearers=[ADULT2]).code, "d10_hearer")

    def test_expand_is_called_once_and_may_fail(self):
        vocab = language.Vocabulary(self.cat)
        act = language.Expression("(assert (past (did @E2 touch @E3 (how romantic))))", vocab)
        calm = language.Expression("(assert (at @E2 @PLACE))", vocab)
        adults = {"me": ADULT, "@E2": ADULT2, "@E3": ADULT}
        e = language.Expression("(assert b:1)", vocab)
        answers = iter([calm, act])                                   # an impure expand: benign first, then not
        v = self.g.check_utterance(e, ADULT, adults, [CHILD], expand=lambda r: next(answers))
        self.assertTrue(v.allowed)                                    # the SAME copy was checked twice: calm
        self.assertEqual(self.g.check_utterance(e, ADULT, adults, [ADULT2], expand=lambda r: 1 / 0).code, "unexpanded")

    def test_a_perceived_event_is_unfolded_like_a_citation(self):
        vocab = language.Vocabulary(self.cat)
        e = language.Expression("(assert (caused @E2 @V4))", vocab)
        self.assertTrue(e.ok, e.problems)
        adults = {"me": ADULT, "@E2": ADULT2, "@E3": ADULT}
        self.assertEqual(self.g.check_utterance(e, ADULT, adults, [ADULT2]).code, "unexpanded")
        seen = language.Expression("(assert (past (did @E2 touch @E3 (how romantic))))", vocab)
        self.assertEqual(self.g.check_utterance(e, ADULT, adults, [CHILD], expand=lambda r: seen).code, "d10_hearer")

    def test_a_new_ledger_adopts_the_clock(self):
        led = WriteLedger()
        led.roll(1500, 120)                                           # an NPC whose ledger starts late
        self.assertEqual((led.day, led.life_year), (1500, 120))
        led.roll(1501, 120)
        self.assertEqual(led.day, 1501)
        late = WriteLedger.at(3000, 40)
        late.roll(3000 + 1001, 40)                                    # once synced, an aberrant jump is ignored
        self.assertEqual(late.day, 3000)

    def test_an_intimate_judgement_without_parties_is_refused_not_a_crash(self):
        self.assertFalse(self.g.check_value("m_interpretation", "adultery", ADULT, None).allowed)

    def test_an_aberrant_jump_of_the_clock_is_ignored(self):
        led = WriteLedger()
        led.roll(3, 1)
        led.roll(10 ** 9, 10 ** 6)
        self.assertEqual((led.day, led.life_year), (3, 1))
        led.roll(4, 2)
        self.assertEqual((led.day, led.life_year), (4, 2))

    def test_the_speaker_is_never_a_content_party(self):
        vocab = language.Vocabulary(self.cat)
        e = language.Expression("(offer (future (link me spouse @E2)))", vocab)
        self.assertFalse(self.g.check_utterance(e, CHILD, {"me": ADULT, "@E2": ADULT2}, [ADULT2]).allowed)

    def test_an_absent_param_that_cannot_be_a_person_is_not_an_unknown_person(self):
        """Review 11: put.where (a place) or tie.with (a cord) left out is not a possible minor."""
        vocab = language.Vocabulary(self.cat)
        for text in ("(assert (past (did @E1 put @T1)))", "(assert (past (did @E1 tie @E2)))"):
            e = language.Expression(text, vocab)
            self.assertTrue(e.ok, e.problems)
            self.assertTrue(self.g.check_utterance(e, ADULT, {"me": ADULT, "@E1": ADULT2, "@E2": ADULT, "@T1": THING},
                                                   [ADULT2]).allowed, text)

    def test_ages_that_are_not_numbers_are_unknown(self):
        from governor import age_tenths
        for x in (10 ** 400, "30", True, None, float("inf"), -0.5, 3276.8):
            self.assertEqual(age_tenths(x), -1, x)
        self.assertEqual(age_tenths(3276.7), 32767)
        self.assertEqual(age_tenths(17.96), 179)

    def test_time_never_goes_back(self):
        led = WriteLedger()
        self.g.check_write("r_affection", 0, 1, led, target="7")
        led.roll(5, 0)
        led.roll(3, 0)
        self.assertEqual(led.day, 5)

    def test_d10_cited_content_must_be_expanded(self):
        vocab = language.Vocabulary(self.cat)
        e = language.Expression("(offer (that g:1))", vocab)
        self.assertFalse(self.g.check_utterance(e, ADULT, {"me": ADULT}).allowed)          # no frozen copy
        benign = language.Expression("(assert (at me @L1))", vocab)
        self.assertTrue(self.g.check_utterance(e, ADULT, {"me": ADULT}, expand=lambda r: benign).allowed)
        bad = language.Expression("(offer (did me touch @E3 (how romantic)))", vocab)
        self.assertFalse(self.g.check_utterance(e, ADULT, {"me": ADULT, "@E3": CHILD}, expand=lambda r: bad).allowed)

    def test_gesture_validation_and_things(self):
        self.assertFalse(self.g.check_gesture("touch", {"manner": "romantic"}, ADULT, {}).allowed)   # person left out
        self.assertFalse(self.g.check_gesture("touch", {"duration": "forever"}, ADULT, {}).allowed)   # invalid value
        self.assertFalse(self.g.check_gesture("touch", {"Target": "@E1"}, ADULT, {}).allowed)          # unknown param
        stone = {"target": "@T1", "from": "ground", "hold": "in_hand", "stealth": "open"}
        self.assertTrue(self.g.check_gesture("take", stone, CHILD, {"target": THING}).allowed)
        bite = {"target": "@E1", "zone": "arms", "with": "mouth", "motion": "swing", "intensity": "faint"}
        self.assertFalse(self.g.check_gesture("strike", bite, ADULT, {"target": CHILD}).allowed)
        self.assertFalse(self.g.check_gesture("touch", {"target": "@E1"}, ADULT, {"target": ADULT2}, executed=True).allowed)

    def test_writes_details(self):
        self.assertEqual(len(self.g.check_writes([["f1", "r_trust", 1], ["f1", "r_trust", 2], ("f2", "r_trust", 3)])), 2)
        self.assertFalse(self.g.check_write("r_affection", 0, True, WriteLedger(), "f1").allowed)       # bool is not a number
        self.assertTrue(self.g.check_write("need_intimacy", 0, 0.5, WriteLedger(), "self", actor=ADULT).allowed)
        self.assertFalse(self.g.check_write("need_intimacy", 0, 0.5, WriteLedger(), "self", actor=CHILD).allowed)
        self.assertTrue(self.g.check_value("m_interpretation", "theft").allowed)
        self.assertFalse(self.g.check_value("m_interpretation", "adultery", parties={"@E1": CHILD}).allowed)
        self.assertFalse(self.g.check_value("g_mode", "conquer").allowed)
        self.assertTrue(self.g.check_value("g_mode", "achieve").allowed)

    def test_memory_is_free_at_creation_then_steps(self):
        led = WriteLedger()
        self.assertEqual(self.g.check_write("m_valence", 0, -9, led, "m1", creating=True).value, -9)
        self.assertEqual(self.g.check_write("m_valence", -9, 0, led, "m1").value, -8)


if __name__ == "__main__":
    unittest.main()
