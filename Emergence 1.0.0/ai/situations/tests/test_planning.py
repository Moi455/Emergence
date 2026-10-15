"""Tests of T12: plans, sub-goals, routines, groups and the new causes of waking (python3 -m unittest discover -s
ai/situations/tests -t ai).

The acceptance of the spec is measured here on the ~2200 situations of test_situations: the shares of causes, of
situations with two plans, of goals with a parent and of reflections; zero invalid proposition; the audit of D10
(which the sampler already runs on every situation) is also run again on the new fields with deliberately bad
records. The sampler only builds the context: nothing here says what the NPC should do.
"""
from __future__ import annotations

import collections
import unittest

from ..audit import D10Audit, D10Violation
from ..planning import STRUCTURES
from ..sampler import SituationSampler
from tok2 import Record

from .test_situations import ACTIONS, N, SAMPLER, SAMPLERS, SEEDS, SITS, by_key

CORE_CAUSES = ("plan", "timer", "routine", "goal_check", "occasion")
PLAN_STATUS = ("running", "suspended", "blocked", "done", "abandoned")


def records(sit, typ):
    return [r for r in sit.context.records if r.type == typ]


class TestAcceptance(unittest.TestCase):
    def share(self, pred) -> float:
        return sum(1 for s in SITS if pred(s)) / N

    def test_the_causes_that_serve_a_purpose_are_a_quarter_of_the_wakes(self):
        self.assertGreaterEqual(self.share(lambda s: by_key(s)["wake"].fields["cause"] in CORE_CAUSES), 0.25)

    def test_every_cause_of_the_interface_comes_up(self):
        seen = {by_key(s)["wake"].fields["cause"] for s in SITS}
        self.assertEqual(seen, set(SAMPLER.pools.enum("WAKE", "cause")))

    def test_two_plans_or_more_in_a_fifth_of_the_situations(self):
        self.assertGreaterEqual(self.share(lambda s: len(records(s, "PLAN")) >= 2), 0.20)

    def test_a_goal_in_seven_has_a_parent(self):
        goals = [g for s in SITS for g in records(s, "GOAL")]
        self.assertGreaterEqual(sum(1 for g in goals if g.fields.get("parent")) / len(goals), 0.15)

    def test_a_third_of_the_wakes_ask_him_to_reflect(self):
        self.assertGreaterEqual(self.share(lambda s: by_key(s)["wake"].fields["mode"] == "reflect"), 0.30)

    def test_plans_and_sub_goals_are_there_whatever_the_cause(self):
        by_cause = collections.defaultdict(lambda: [0, 0, 0])
        for s in SITS:
            c = by_key(s)["wake"].fields["cause"]
            by_cause[c][0] += 1
            by_cause[c][1] += len(records(s, "PLAN")) >= 2
            by_cause[c][2] += any(g.fields.get("parent") for g in records(s, "GOAL"))
        for cause, (n, two, parent) in by_cause.items():
            self.assertGreater(two / n, 0.1, cause)
            self.assertGreater(parent / n, 0.2, cause)

    def test_no_invalid_proposition_and_no_governor_refusal(self):
        for sampler in SAMPLERS.values():
            self.assertEqual(sampler.stats.invalid, 0)
            self.assertEqual(sampler.stats.refused, 0)

    def test_the_families_of_structure_follow_their_shares(self):
        c = collections.Counter(s.structure for s in SITS)
        for family, share in STRUCTURES.items():
            self.assertAlmostEqual(c[family] / N, share, delta=0.03, msg=family)

    def test_same_seed_same_situations(self):
        again = SituationSampler(seed=SEEDS[1][0])
        for i in (0, 5, 37, 400):
            a, b = SAMPLERS[SEEDS[1][0]].sample(i), again.sample(i)
            self.assertEqual(a.encoded.digest(), b.encoded.digest())
            self.assertEqual(a.structure, b.structure)


class TestPlans(unittest.TestCase):
    def test_a_plan_is_a_chain_of_two_to_six_gestures_with_their_targets(self):
        lengths = collections.Counter()
        for s in SITS:
            for p in records(s, "PLAN"):
                f = p.fields
                lengths[len(f["steps"])] += 1
                self.assertTrue(2 <= len(f["steps"]) <= 6)
                self.assertIn(f["step"], f["steps"])
                self.assertIn(f["next"], f["steps"])
                self.assertTrue(any(x == f["step"] and y == f["next"] for x, y in zip(f["steps"], f["steps"][1:])))
                self.assertTrue(len(f["step_targets"]) <= 4)
                # one pointer per step that takes a target, in order (the first four)
                takers = [g for g in f["steps"] if any(prm.type == "ref" for prm in ACTIONS[g].params)]
                self.assertEqual(len(f["step_targets"]), min(4, len(takers)))
        self.assertTrue(set(lengths) >= {2, 3, 4})

    def test_the_status_of_a_plan_is_a_fact_and_at_most_one_runs(self):
        seen = collections.Counter()
        for s in SITS:
            plans = records(s, "PLAN")
            self.assertLessEqual(len(plans), 2)
            self.assertLessEqual(sum(p.fields["status"] == "running" for p in plans), 1)
            for p in plans:
                f = p.fields
                seen[f["status"]] += 1
                self.assertIn(f["status"], PLAN_STATUS)
                self.assertNotEqual(f["status"], "abandoned")                    # only the model abandons
                if f["status"] == "blocked":
                    self.assertGreaterEqual(f["attempts"], 1)
                if f["status"] == "done":
                    self.assertEqual(f["progress"], 1.0)
        self.assertTrue(set(seen) >= {"running", "suspended", "blocked", "done"})

    def test_a_routine_has_its_period_and_only_then(self):
        seen = collections.Counter()
        for s in SITS:
            for p in records(s, "PLAN"):
                f = p.fields
                seen[f["repeat"]] += 1
                if f["repeat"] == "every":
                    self.assertIn(f["repeat_period"], range(1, 2001))
                else:
                    self.assertNotIn("repeat_period", f)
        self.assertEqual(set(seen), {"once", "each_day", "each_season", "each_year", "every"})
        self.assertGreater(seen["once"], seen["each_day"] + seen["every"])      # most plans are done once

    def test_a_plan_that_speaks_carries_what_he_means_to_say(self):
        said = 0
        for s in SITS:
            for p in records(s, "PLAN"):
                if "says" in p.fields:
                    said += 1
                    self.assertIn("speak", p.fields["steps"])
        self.assertGreater(said, 20)

    def test_a_goal_knows_whether_it_has_a_plan(self):
        for s in SITS:
            serves = {p.fields["goal"] for p in records(s, "PLAN")}
            for g in records(s, "GOAL"):
                self.assertEqual(g.fields["has_plan"], g.key in serves)

    def test_the_plan_that_wakes_him_has_just_ended_a_step(self):
        outcomes = collections.Counter()
        for s in SITS:
            w = by_key(s)["wake"].fields
            if w["cause"] == "plan":
                plan = by_key(s)[w["trigger"]]
                outcomes[w["outcome"]] += 1
                if w["outcome"] == "done":
                    self.assertGreaterEqual(plan.fields["progress"], 0.97)
                if w["outcome"] in ("blocked", "failed"):
                    self.assertGreaterEqual(plan.fields["attempts"], 1)
                if w["outcome"] == "blocked":
                    self.assertEqual(plan.fields["status"], "blocked")
                if w["outcome"] == "interrupted":
                    self.assertEqual(plan.fields["status"], "suspended")
            else:
                self.assertNotIn("outcome", w)
        self.assertEqual(set(outcomes), set(SAMPLER.pools.enum("WAKE", "outcome")))


class TestGoals(unittest.TestCase):
    def test_a_sub_goal_points_at_a_goal_and_the_chain_ends(self):
        n = 0
        for s in SITS:
            recs = by_key(s)
            for g in records(s, "GOAL"):
                key, hops = g.fields.get("parent"), 0
                while key:
                    n += 1
                    hops += 1
                    self.assertEqual(recs[key].type, "GOAL")
                    self.assertNotEqual(key, g.key)
                    self.assertLess(hops, 5)
                    key = recs[key].fields.get("parent")
        self.assertGreater(n, 1000)

    def test_a_long_pursuit_is_dated_ahead_and_matters(self):
        long_ones = 0
        for s in SITS:
            recs = by_key(s)
            parents = {g.fields["parent"] for g in records(s, "GOAL") if g.fields.get("parent")}
            for key in parents:
                f = recs[key].fields
                if f.get("deadline") is not None and f["deadline"] >= 48:
                    long_ones += 1
                    self.assertGreaterEqual(f["priority"], 3)
                    self.assertEqual(f["status"], "active")
        self.assertGreater(long_ones, 200)

    def test_a_goal_that_seems_reached_wakes_him_and_is_still_his_to_judge(self):
        n = 0
        for s in SITS:
            w = by_key(s)["wake"].fields
            if w["cause"] == "goal_check":
                n += 1
                goal = by_key(s)[w["trigger"]]
                self.assertEqual(goal.type, "GOAL")
                self.assertEqual(goal.fields["status"], "active")             # the engine never writes the verdict
        self.assertGreater(n, 50)

    def test_an_occasion_names_what_presents_itself(self):
        kinds = collections.Counter()
        for s in SITS:
            w = by_key(s)["wake"].fields
            if w["cause"] == "occasion":
                trig = by_key(s)[w["trigger"]]
                kinds[trig.type] += 1
                if trig.type == "GOAL":
                    self.assertTrue(trig.fields["prop"].startswith("(at_time") or trig.fields["prop"].startswith("(at @E"))
                    self.assertTrue("when" in trig.fields or trig.fields["prop"].startswith("(at @E"))
                if trig.type == "ENTITY":
                    self.assertTrue(trig.fields["present"])
                if trig.type == "GROUP":
                    self.assertGreaterEqual(trig.fields["present"], 1)
        self.assertEqual(set(kinds), {"GOAL", "ENTITY", "GROUP"})

    def test_a_goal_from_an_agreement_points_at_it(self):
        n = 0
        for s in SITS:
            recs = by_key(s)
            for g in records(s, "GOAL"):
                if g.fields["origin"] == "agreement" and g.fields["origin_ref"].startswith("c:"):
                    n += recs[g.fields["origin_ref"]].fields["prop"] == g.fields["prop"]     # the goal IS the promise
        self.assertGreater(n, 100)

    def test_the_idle_moment_is_quiet(self):
        for s in SITS:
            w = by_key(s)["wake"].fields
            if w["cause"] == "idle":
                self.assertEqual(w["trigger"], "")
                me = by_key(s)["me"].fields
                self.assertLessEqual(max(me[k] for k in ("need.hunger", "need.thirst", "need.sleep", "need.exhaustion", "body.pain")), 7.5)


class TestWakeToken(unittest.TestCase):
    def test_the_think_budget_and_the_village_temperament(self):
        for s in SITS:
            w = by_key(s)["wake"].fields
            self.assertTrue(0.0 <= w["temperament"] <= 10.0)
            if w["mode"] == "reflect":
                self.assertGreaterEqual(w["budget"], 1)
            else:
                self.assertLessEqual(w["budget"], 2)


class TestGroups(unittest.TestCase):
    def test_a_group_known_by_sight_has_members_a_leader_and_a_part(self):
        full = thin = tasks = 0
        for s in SITS:
            recs = by_key(s)
            for g in records(s, "GROUP"):
                f = g.fields
                if f["known_by"] != "seen":
                    thin += 1
                    self.assertNotIn("members", f)
                    continue
                full += 1
                self.assertTrue(len(f["members"]) <= 4)
                self.assertGreaterEqual(f["size"], len(f["members"]))
                self.assertLessEqual(f["present"], len(f["members"]))
                self.assertTrue(all(k == "me" or recs[k].type == "ENTITY" for k in f["members"]))
                if f["leader"]:
                    self.assertTrue(f["leader"] == "me" and "me" in f["members"] or f["leader"] in f["members"])
                if f["my_task"]:
                    tasks += 1
                    self.assertEqual(recs[f["my_task"]].fields["counterparty"], g.key)
                    self.assertTrue(recs[f["my_task"]].fields["mine"])
                self.assertEqual(f["tasks_open"], sum(1 for c in records(s, "COMMIT")
                                                       if c.fields["counterparty"] == g.key and c.fields["status"] == "open"))
                if "goal" in f:
                    self.assertNotIn(g.key, f["goal"])                      # the record is the group
        self.assertGreater(full, 1000)
        self.assertGreater(thin, 300)
        self.assertGreater(tasks, 100)

    def test_a_child_belongs_to_a_household_a_lineage_or_a_community(self):
        for s in SITS:
            if s.scene.self_.age < 14:
                for g in records(s, "GROUP"):
                    self.assertIn(g.fields["kind"], ("g_household", "g_lineage", "g_community"))

    def test_an_agreement_can_be_with_a_group(self):
        n = sum(1 for s in SITS for c in records(s, "COMMIT") if c.fields["counterparty"].startswith("@G"))
        self.assertGreater(n, 100)


class TestAuditOfThePlanningFields(unittest.TestCase):
    """The audit sees the new fields: a refusal is raised, never repaired. The bad records only use a symbol flagged
    intimate or a broken structure; none is an act."""

    @classmethod
    def setUpClass(cls):
        cls.audit = D10Audit(SAMPLER.pools)
        cls.sit = next(s for s in SITS if s.scene.self_.age >= 30 and len(records(s, "PLAN")) == 2 and records(s, "GROUP")
                       and any(g.fields.get("parent") for g in records(s, "GOAL")))

    def copy(self):
        return [Record(r.type, r.key, dict(r.fields)) for r in self.sit.context.records]

    def refuses(self, recs):
        with self.assertRaises(D10Violation):
            self.audit.check(self.sit.scene.self_, recs, self.sit.people)

    def test_the_situation_itself_passes(self):
        self.audit.check(self.sit.scene.self_, self.copy(), self.sit.people)

    def test_a_step_of_the_chain_is_checked_on_its_own(self):
        recs = self.copy()
        next(r for r in recs if r.type == "PLAN").fields["steps"] = ["go", "intimate"]
        self.refuses(recs)

    def test_what_a_plan_means_to_say_is_checked(self):
        recs = self.copy()
        next(r for r in recs if r.type == "PLAN").fields["says"] = "(offer (link me lover me))"
        self.refuses(recs)

    def test_the_aim_of_a_group_is_checked(self):
        recs = self.copy()
        next(r for r in recs if r.type == "GROUP").fields["goal"] = "(link me lover me)"
        self.refuses(recs)

    def test_a_parent_must_be_a_goal_and_must_not_loop(self):
        recs = self.copy()
        goal = next(r for r in recs if r.type == "GOAL")
        goal.fields["parent"] = goal.key
        self.refuses(recs)
        recs = self.copy()
        next(r for r in recs if r.type == "GOAL").fields["parent"] = "wake"
        self.refuses(recs)


if __name__ == "__main__":
    unittest.main()
