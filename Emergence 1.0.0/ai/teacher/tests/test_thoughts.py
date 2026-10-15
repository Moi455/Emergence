"""Tests of the written trace of thoughts (T36): planner-mode instructions and schema, the validator's thoughts and its
`incoherent_trace`, the repair pass, and the strict backward compatibility of the default prompt. No network.

    python3 -m unittest discover -s ai/teacher/tests -t ai
"""
from __future__ import annotations

import copy
import hashlib
import json
import unittest
from types import SimpleNamespace

from tok2 import DecisionContext, Record

from teacher.batch import BatchInstructions, BatchSchema
from teacher.generator import build_parser
from teacher.phrasebook import PhraseBook
from teacher.planner_measure import PlannerMeasure
from teacher.schema import PLANNER_EXAMPLE, DecisionSchema
from teacher.tests.test_teacher import MINI, MINI_VALIDATOR, TK, answer
from teacher.validate import Codes

WAIT = (("until", "(c_elapsed 30)"),)
GO_STEP = {"gesture": "go", "target": "@L1"}


def with_thoughts(thoughts, gesture="wait", params=WAIT) -> str:
    d = json.loads(answer(gesture, params))
    d["thoughts"] = thoughts
    return json.dumps(d)


class DefaultUnchanged(unittest.TestCase):
    """The running generator restarts on any change of ai/teacher: the default prompt must stay byte for byte."""

    def test_pinned_fingerprints(self):
        self.assertEqual(DecisionSchema(TK).fingerprint(), "bc8a9fcb85c8d279")
        self.assertEqual(DecisionSchema(TK, plans=True).fingerprint(), "a70198c0d3aa35ec")
        text = BatchInstructions(TK, PhraseBook(TK, 30)).text()
        blob = text + json.dumps(BatchSchema(DecisionSchema(TK, "full")).response_schema(1), sort_keys=True)
        self.assertEqual(hashlib.sha256(blob.encode()).hexdigest()[:12], "67468d6500d9")

    def test_the_flag_is_off_by_default(self):
        self.assertFalse(build_parser().parse_args([]).planner)
        self.assertTrue(build_parser().parse_args(["--planner"]).planner)


class PlannerPrompt(unittest.TestCase):
    def test_the_instructions_describe_the_format_and_the_human_frame(self):
        text = DecisionSchema(TK, thoughts=True).instructions()
        for word in ("a human being", "== THOUGHTS", "belief_about", '"thoughts"'):
            self.assertIn(word, text)
        self.assertNotIn("Doing nothing is a choice", text)

    def test_schema_asks_the_trace_and_not_the_top_level_plan(self):
        s = DecisionSchema(TK, thoughts=True).response_schema()
        self.assertIn("thoughts", s["required"])
        self.assertNotIn("plan", s["properties"])
        self.assertEqual(s["propertyOrdering"][:2], ["why", "thoughts"])
        self.assertEqual(s["properties"]["thoughts"]["maxItems"], 5)
        item = BatchSchema(DecisionSchema(TK, thoughts=True)).item()
        self.assertIn("thoughts", item["properties"])

    def test_one_coherent_example_and_it_validates_whole(self):
        text = DecisionSchema(TK, thoughts=True).instructions()
        self.assertEqual(text.split("== EXAMPLES")[1].count('"why":'), 1)
        d = DecisionSchema.example_object(PLANNER_EXAMPLE, PLANNER_EXAMPLE["thoughts"])
        o = MINI_VALIDATOR.validate(json.dumps(d), MINI)
        self.assertTrue(o.ok, o.detail)
        self.assertEqual([t["kind"] for t in o.decision.thoughts], ["belief", "goal", "plan"])

    def test_no_max_items_removes_exactly_the_two_planner_limits(self):
        def count(sch):
            return json.dumps(sch).count("maxItems")
        on, off = DecisionSchema(TK, thoughts=True), DecisionSchema(TK, thoughts=True, max_items=False)
        self.assertEqual(count(on.response_schema()) - count(off.response_schema()), 2)
        self.assertEqual(count(DecisionSchema(TK).response_schema()), count(DecisionSchema(TK, max_items=False).response_schema()))
        self.assertTrue(build_parser().parse_args(["--no-max-items"]).no_max_items)


class ThoughtValidator(unittest.TestCase):
    def check(self, thoughts, **kw):
        return MINI_VALIDATOR.validate(with_thoughts(thoughts, **kw), MINI)

    def refused(self, thoughts, code, **kw):
        o = self.check(thoughts, **kw)
        self.assertFalse(o.ok, o.detail)
        self.assertEqual(o.code, code, o.detail)

    def test_no_thoughts_field_is_exactly_what_it_was(self):
        o = MINI_VALIDATOR.validate(answer("wait", WAIT), MINI)
        self.assertTrue(o.ok)
        self.assertNotIn("thoughts", o.decision.to_dict())

    def test_an_empty_trace_is_valid_and_recorded(self):
        o = self.check([])
        self.assertTrue(o.ok)
        self.assertEqual(o.decision.to_dict()["thoughts"], [])

    def test_the_four_kinds(self):
        o = self.check([
            {"kind": "belief", "target": "new", "prop": "(owns @E1 @T1)"},
            {"kind": "belief_about", "target": "new", "prop": "(believes @E1 (owns @E1 @T1))"},
            {"kind": "goal", "target": "new", "prop": "(has me bread_loaf)", "mode": "achieve", "parent": "g:1",
             "deadline_h": "24", "when_h": 6},
            {"kind": "plan", "serves": "g:new", "steps": [GO_STEP, {"gesture": "wait", "target": ""}], "repeat": "once"}])
        self.assertTrue(o.ok, o.detail)
        kinds = [t["kind"] for t in o.decision.to_dict()["thoughts"]]
        self.assertEqual(kinds, ["belief", "belief_about", "goal", "plan"])

    def test_a_goal_may_be_written_with_its_mode_as_head(self):
        o = self.check([{"kind": "goal", "target": "new", "prop": "(achieve (has me bread_loaf))"}])
        self.assertTrue(o.ok, o.detail)
        t = o.decision.thoughts[0]
        self.assertEqual((t["mode"], t["prop"]), ("achieve", "(has me bread_loaf)"))

    def test_refusals_are_stable(self):
        self.refused([{"kind": "belief", "target": "new", "prop": "(owns @E1 @T1)"}] * 6, Codes.TOO_MANY_THOUGHTS)
        self.refused([{"kind": "dream", "prop": "(owns @E1 @T1)"}], Codes.BAD_THOUGHT)
        self.refused([{"kind": "belief", "target": "new"}], Codes.BAD_THOUGHT)
        self.refused([{"kind": "belief_about", "target": "new", "prop": "(owns @E1 @T1)"}], Codes.BAD_THOUGHT)
        self.refused([{"kind": "belief", "target": "new", "prop": "(owns @E99 @T1)"}], Codes.BAD_POINTER)
        self.refused([{"kind": "belief", "target": "new", "prop": "(owns @E1 flies)"}], Codes.BAD_SPEECH)
        self.refused([{"kind": "goal", "target": "new", "prop": "(has me bread_loaf)", "parent": "b:1"}], Codes.BAD_POINTER)
        self.refused([{"kind": "goal", "target": "new", "prop": "(has me bread_loaf)", "mode": "dream"}], Codes.BAD_THOUGHT)
        self.refused([{"kind": "plan", "steps": []}], Codes.BAD_PLAN)
        self.refused([{"kind": "plan", "serves": "g:new", "steps": [GO_STEP]}], Codes.BAD_THOUGHT)
        self.refused([{"kind": "plan", "steps": [GO_STEP] * 7}], Codes.TOO_MANY_STEPS)
        self.refused([{"kind": "plan", "steps": [{"gesture": "go", "target": "b:1"}]}], Codes.BAD_POINTER)
        self.refused("not a list", Codes.BAD_SHAPE)

    def test_d10_still_holds_inside_a_planned_step(self):
        self.refused([{"kind": "plan", "steps": [GO_STEP, {"gesture": "search", "target": "@E2"}]}], "governor:d10_person")

    def test_a_planned_word_is_judged_like_a_spoken_one(self):
        plan = lambda says: [{"kind": "plan", "steps": [{"gesture": "wait", "target": ""}], "says": says}]   # noqa: E731
        self.refused(plan("(request (did me touch @E2 (how intimate)))"), "governor:d10_hearer")
        self.refused(plan("(request (did me touch @E2))"), "governor:d10_whitelist")
        self.assertTrue(self.check(plan("(request (did you give bread_loaf (to me)))")).ok)

    def test_the_detail_names_the_thought(self):
        o = self.check([{"kind": "belief", "target": "new", "prop": "(owns @E99 @T1)"}])
        self.assertIn("thought 1 (belief)", o.detail)


class IncoherentTrace(unittest.TestCase):
    def check(self, thoughts, wake=None, **kw):
        sit = MINI
        if wake:
            sit = SimpleNamespace(scene=None, context=DecisionContext(
                list(MINI.context.records) + [Record("WAKE", "wake", {"mode": "act", "cause": wake, "urgency": 1.0})]))
        return MINI_VALIDATOR.validate(with_thoughts(thoughts, **kw), sit)

    PLAN_GO = [{"kind": "plan", "steps": [GO_STEP]}]

    def test_a_plan_and_an_act_with_no_link_is_refused(self):
        o = self.check(self.PLAN_GO)
        self.assertEqual(o.code, Codes.INCOHERENT_TRACE, o.detail)

    def test_the_act_is_the_first_step(self):
        o = self.check(self.PLAN_GO, gesture="go", params=(("target", "@L1"), ("relation", "toward"), ("pace", "walk"),
                                                           ("stealth", "open")))
        self.assertTrue(o.ok, o.detail)

    def test_the_act_is_a_later_step_or_its_target_is_thought_of(self):
        later = [{"kind": "plan", "steps": [GO_STEP, {"gesture": "wait", "target": ""}]}]
        self.assertTrue(self.check(later).ok)
        about = self.PLAN_GO + [{"kind": "belief", "target": "new", "prop": "(owns @E1 @T1)"}]
        o = self.check(about, gesture="take", params=(("target", "@T1"), ("from", "ground"), ("hold", "in_hand"),
                                                      ("stealth", "open"), ("contact_zone", "hands")))
        self.assertTrue(o.ok, o.detail)

    def test_an_urgent_wake_is_never_refused_for_it(self):
        for cause in ("perception", "speech", "request"):
            self.assertTrue(self.check(self.PLAN_GO, wake=cause).ok, cause)
        self.assertEqual(self.check(self.PLAN_GO, wake="routine").code, Codes.INCOHERENT_TRACE)

    def test_no_plan_no_refusal_whatever_the_act(self):
        self.assertTrue(self.check([{"kind": "belief", "target": "new", "prop": "(owns @E1 @T1)"}]).ok)

    def test_a_top_level_plan_without_thoughts_is_not_judged(self):
        d = json.loads(answer("wait", WAIT))
        d["plan"] = {"steps": [GO_STEP]}
        self.assertTrue(MINI_VALIDATOR.validate(json.dumps(d), MINI).ok)

    def test_the_refusal_is_repairable(self):
        from teacher.batch import NOT_REPAIRED
        self.assertFalse(Codes.INCOHERENT_TRACE.startswith(NOT_REPAIRED))


class SeriesMode(unittest.TestCase):
    def test_migrate_keeps_thoughts_and_plan(self):
        from teacher.migrate import Migration
        o = MINI_VALIDATOR.validate(with_thoughts([{"kind": "plan", "steps": [GO_STEP, {"gesture": "wait", "target": ""}]}]), MINI)
        raw = json.loads(Migration.raw_answer(o.decision.to_dict()))
        self.assertEqual(len(raw["thoughts"]), 1)
        again = MINI_VALIDATOR.validate(json.dumps(raw), MINI)
        self.assertTrue(again.ok, again.detail)
        self.assertEqual(again.decision.thoughts, o.decision.thoughts)

    def test_a_series_never_changes_mode(self):
        import tempfile
        from pathlib import Path
        from teacher.caller import FatalError
        from teacher.generator import Generator
        from teacher.gemini import GeminiClient
        from teacher.quota import QuotaConfig
        from teacher.series import SeriesDirectory
        with tempfile.TemporaryDirectory() as tmp:
            def make(planner):
                return Generator(SeriesDirectory("s", Path(tmp)), GeminiClient("k"), QuotaConfig.load(), planner=planner)
            make(True)                                              # a new series becomes a planner series
            with self.assertRaises(FatalError):
                make(False)
            make(True)
        with tempfile.TemporaryDirectory() as tmp:
            g = Generator(SeriesDirectory("d", Path(tmp)), GeminiClient("k"), QuotaConfig.load())
            self.assertNotIn("mode", g.state.extra)                  # a default series' state.json is unchanged
            g.state.requests = 1
            g.state.save(g.series.state)
            with self.assertRaises(FatalError):
                Generator(SeriesDirectory("d", Path(tmp)), GeminiClient("k"), QuotaConfig.load(), planner=True)


class StandInMeasure(unittest.TestCase):
    def test_the_whole_path_with_repair_and_deliberate_defects(self):
        t = PlannerMeasure(n=30, seed=0, k=6).run()
        self.assertEqual(t.asked, 30)
        self.assertEqual(t.valid, 30)                     # the repair pass recovers every stand-in defect
        self.assertGreater(t.valid_first, 20)
        self.assertGreater(t.with_trace, 0)
        self.assertIn("bad_pointer", t.refused)


if __name__ == "__main__":
    unittest.main()
