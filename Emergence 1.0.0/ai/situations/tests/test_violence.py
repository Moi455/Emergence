"""Tests of the plots of force (T12b): share, diversity, groups, plans, determinism, and the PRUDENCE rule: the targets
of an aim of force are adults only (until the project owner explicitly allows minors; see violence.py and the README)."""
from __future__ import annotations

import json
import unittest

from situations.audit import D10Violation
from situations.sampler import SituationSampler
from situations.violence import MOTIVES, PlotSummary
from situations.violence_meter import ForceReader, ViolenceMeter

N = 1000
METER = ViolenceMeter(seed=5, n=N)
METER.run()                                                        # also runs the D10 audit on every situation
SAMPLER = METER.sampler


class TestShare(unittest.TestCase):
    def test_a_minority_but_measured_share_has_an_aim_of_force(self):
        share = METER.c["force_goal_or_group"] / N
        self.assertTrue(0.03 < share < 0.15, share)
        self.assertGreater(METER.by_structure["conflict"] / METER.structures["conflict"], 0.2)    # the family of it

    def test_groups_and_multi_step_plans_exist(self):
        self.assertGreater(METER.c["group_aim_of_force"] / N, 0.005)
        self.assertGreater(METER.c["plan_for_force_3plus"] / N, 0.01)
        self.assertGreater(METER.c["plot_dilemma"], 0)

    def test_the_motives_are_diverse(self):
        self.assertGreaterEqual(len(METER.motives), 8)
        self.assertGreater(METER.entropy(METER.motives), 2.8)
        self.assertLess(max(METER.motives.values()) / sum(METER.motives.values()), 0.25)    # no scenario repeated
        self.assertGreaterEqual(len(METER.forms), 6)
        self.assertEqual(set(METER.kinds), {"own", "witness", "hunted"})
        self.assertTrue(set(METER.motives) <= set(MOTIVES) | {"warning"} | {"justice", "rivalry"})


class TestAdultsOnly(unittest.TestCase):
    """Prudence: no aim of force (goal, group aim, plan step, plot target) at a person who is not an adult."""

    def test_no_target_of_force_is_a_minor(self):
        reader, n = ForceReader(), 0
        for i in range(N):
            sit = SAMPLER.sample(i)
            for r in sit.context.records:
                text = r.fields.get("prop") if r.type == "GOAL" else r.fields.get("goal") if r.type == "GROUP" else None
                for t in (reader.targets(text) if text else []):
                    n += 1
                    if t != "me":
                        self.assertGreaterEqual(sit.people[t].age, 18.0, (i, text))
                if r.type == "PLAN":
                    for g, t in zip([g for g in r.fields["steps"] if g in ("strike", "push", "grab", "pull")], [
                            t for g, t in zip(r.fields["steps"], r.fields["step_targets"]) if g in ("strike", "push", "grab", "pull")]):
                        if t != "me" and t.startswith("@E"):
                            self.assertGreaterEqual(sit.people[t].age, 18.0, (i, r.fields["steps"]))
            if sit.plot is not None and sit.plot.target not in ("me", ""):
                self.assertGreaterEqual(sit.people[sit.plot.target].age, 18.0)
        self.assertGreater(n, 50)
        self.assertEqual(METER.minor_targets, 0)

    def test_the_npc_with_a_plot_is_an_adult(self):
        for i in range(N):
            sit = SAMPLER.sample(i)
            if sit.plot is not None:
                self.assertGreaterEqual(sit.scene.self_.age, 18.0)


class TestDeterminism(unittest.TestCase):
    def test_same_seed_same_situations(self):
        other = SituationSampler(5)
        hit = 0
        for i in range(300):
            a, b = SAMPLER.sample(i), other.sample(i)
            self.assertEqual(json.dumps([r.to_dict() for r in a.context.records], sort_keys=True),
                             json.dumps([r.to_dict() for r in b.context.records], sort_keys=True))
            self.assertEqual(a.plot, b.plot)
            hit += a.plot is not None
        self.assertGreater(hit, 5)

    def test_structure_of_matches_sample(self):
        for i in range(60):
            self.assertEqual(SituationSampler.structure_of(5, i), SAMPLER.sample(i).structure)


class TestNoTruthInContext(unittest.TestCase):
    def test_the_plot_summary_is_not_in_the_records(self):
        for i in range(200):
            sit = SAMPLER.sample(i)
            if sit.plot:
                text = json.dumps([r.to_dict() for r in sit.context.records])
                for word in ("warning", "kin_revenge", "inheritance", "PlotSummary"):
                    self.assertNotIn(word, text)


if __name__ == "__main__":
    unittest.main()
