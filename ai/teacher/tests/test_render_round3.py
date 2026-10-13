"""Round 3 of the sampler, seen from the teacher: the rendering says what it must (a plan is step -> next step on a
target, a gift shows who receives it, a belief held false says NOT the case, no doubled words) and the validator
builds the governor's parties as the engine does (an absent person is not perceived; the age believed comes from the
beliefs)."""
from __future__ import annotations

import unittest
from types import SimpleNamespace

from situations.sampler import SituationSampler
from tok2 import DecisionContext, Record

from teacher.render import SituationRenderer
from teacher.toolkit import Toolkit
from teacher.validate import AnswerValidator, Mind, SceneTruth

TK = Toolkit()
SAMPLER = SituationSampler(11)
RENDERER = SituationRenderer(TK)
SITS = [SAMPLER.sample(i) for i in range(500)]
TEXTS = [RENDERER.render(s) for s in SITS]


class RenderRound3(unittest.TestCase):
    def lines(self, prefix):
        return [ln for t in TEXTS for ln in t.splitlines() if ln.startswith(prefix)]

    def test_a_plan_reads_step_then_next_step_on_the_target(self):
        plans = self.lines("p:1")
        self.assertGreater(len(plans), 40)
        for sit, text in zip(SITS, TEXTS):
            for r in sit.context.records:
                if r.type == "PLAN":
                    line = next(ln for ln in text.splitlines() if ln.startswith(r.key + " "))
                    self.assertIn(f"{r.fields['step']} -> {r.fields['next']} on {r.fields['target']}", line)

    def test_a_gift_shows_who_receives_it(self):
        n = 0
        for sit, text in zip(SITS, TEXTS):
            for r in sit.context.records:
                if r.type == "EVENT" and r.fields["gesture"] == "give":
                    n += 1
                    line = next(ln for ln in text.splitlines() if ln.startswith(r.key + " "))
                    self.assertIn(f" to {r.fields['from_to']}", line)
        self.assertGreater(n, 5)

    def test_a_denied_belief_says_it_is_not_the_case(self):
        text = "\n".join(TEXTS)
        self.assertNotIn("you hold it FALSE", text)
        self.assertIn("you believe this is NOT the case", text)
        for sit, t in zip(SITS, TEXTS):
            for r in sit.context.records:
                if r.type in ("BELIEF", "HEARD") and r.fields.get("polarity") is False:
                    line = next(ln for ln in t.splitlines() if ln.startswith(r.key + " "))
                    self.assertIn("NOT the case", line)

    def test_no_word_is_said_twice_in_a_look(self):
        for t in TEXTS:
            for ln in t.splitlines():
                if "looks about" in ln:
                    parts = ln.split("|")[0].split(";")
                    words = [p.strip() for p in parts[1:]]
                    self.assertEqual(len(words), len(set(words)), ln)


class ValidatorRound3(unittest.TestCase):
    def test_the_party_of_an_absent_person_is_not_perceived_and_carries_the_age_he_is_believed_to_have(self):
        n = 0
        for sit in SITS:
            truth = SceneTruth(sit.scene, sit.context.records, 10, sit.people)
            mind = Mind(TK, sit.context.records, truth)
            for r in sit.context.records:
                if r.type == "ENTITY":
                    p = mind.party(r.key)
                    self.assertEqual(p.perceived, bool(r.fields["present"]))
                    if not r.fields["present"]:
                        self.assertIsNone(p.apparent_age)
                        n += 1
        self.assertGreater(n, 300)

    def test_an_absent_partner_with_a_believed_adult_age_is_not_a_possible_minor(self):
        found = 0
        for sit in SITS:
            truth = SceneTruth(sit.scene, sit.context.records, 10, sit.people)
            mind = Mind(TK, sit.context.records, truth)
            for r in sit.context.records:
                if r.type == "ENTITY" and not r.fields["present"] and r.fields["link"] in ("spouse", "betrothed", "lover"):
                    found += 1
                    self.assertFalse(mind.party(r.key).may_be_minor(), r.key)
        self.assertGreater(found, 3)


if __name__ == "__main__":
    unittest.main()
