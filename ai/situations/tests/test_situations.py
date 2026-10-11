"""Tests of the situation sampler (python3 -m unittest discover -s ai/situations/tests -t ai)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from situations.audit import D10Audit, D10Violation  # noqa: E402
from situations.sampler import SituationSampler  # noqa: E402
from situations.scene import ADULT, INTIMATE_LINKS  # noqa: E402
from tok2 import Record  # noqa: E402

SAMPLER = SituationSampler(seed=7)
N = 300
SITS = [SAMPLER.sample(i) for i in range(N)]


class TestSituations(unittest.TestCase):
    def test_deterministic(self):
        other = SituationSampler(seed=7)
        for i in (0, 5, 123):
            self.assertEqual(other.sample(i).encoded.digest(), SITS[i].encoded.digest())
        self.assertNotEqual(SituationSampler(seed=8).sample(0).encoded.digest(), SITS[0].encoded.digest())

    def test_every_situation_fits_the_budget(self):
        for s in SITS:
            self.assertLessEqual(s.encoded.n, SAMPLER.tokenizer.layout.max_tokens)
            self.assertGreater(s.encoded.n, 5)

    def test_few_propositions_are_dropped(self):
        made, dropped = SAMPLER.props.made, SAMPLER.props.dropped
        self.assertLess(dropped / (made + dropped), 0.15)

    def test_intimate_fields_only_between_adults(self):
        """D10, checked again from the records (the audit already ran on each situation)."""
        partners = minors = 0
        for s in SITS:
            me = s.scene.self_
            recs = {r.key: r for r in s.context.records}
            if me.age < ADULT:
                minors += 1
                self.assertNotIn("attracted_to", recs["me.mind"].fields)
                self.assertNotIn("drive.intimacy", recs["me.state"].fields)
            for r in s.context.records:
                if r.type == "ENTITY" and (r.fields.get("link") in INTIMATE_LINKS or "rel.attraction" in r.fields):
                    partners += 1
                    self.assertGreaterEqual(me.age, ADULT)
                    self.assertGreaterEqual(r.fields.get("look.age", ADULT), ADULT)
        self.assertGreater(partners, 10)                   # adults do have partners
        self.assertGreater(minors, 10)                     # and children are NPCs too

    def test_the_audit_refuses_an_orientation_field_on_a_young_npc(self):
        s = next(x for x in SITS if x.scene.self_.age < ADULT)
        recs = [Record(r.type, r.key, dict(r.fields)) for r in s.context.records]
        next(r for r in recs if r.type == "SELF_MIND").fields["attracted_to"] = ["male"]
        with self.assertRaises(D10Violation):
            D10Audit(SAMPLER.pools).check(s.scene.self_, recs, {})


if __name__ == "__main__":
    unittest.main()
