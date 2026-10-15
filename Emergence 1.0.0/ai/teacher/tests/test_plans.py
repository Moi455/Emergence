"""Tests of the plans the teacher can write (T11): the validator, its stable codes, the optional schema. No network.

    python3 -m unittest discover -s ai/teacher/tests -t ai
"""
from __future__ import annotations

import json
import unittest

from teacher.schema import DecisionSchema
from teacher.tests.test_teacher import MINI, MINI_VALIDATOR, TK, answer
from teacher.validate import Codes


def with_plan(plan, stop=None, gesture="wait", params=(("until", "(c_elapsed 30)"),)) -> str:
    d = json.loads(answer(gesture, params))
    d["plan"] = plan
    if stop is not None:
        d["stop"] = stop
    return json.dumps(d)


GO = {"gesture": "go", "target": "@L1"}
TAKE = {"gesture": "take", "target": "@T1"}


class PlanValidatorTests(unittest.TestCase):
    def check(self, plan, **kw):
        return MINI_VALIDATOR.validate(with_plan(plan, **kw), MINI)

    def refused(self, plan, code, **kw):
        o = self.check(plan, **kw)
        self.assertFalse(o.ok, o.detail)
        self.assertEqual(o.code, code, o.detail)

    def test_a_valid_plan_is_accepted_and_normalised(self):
        o = self.check({"steps": [GO, TAKE], "repeat": "every", "repeat_period": "24", "parent": "g:1"})
        self.assertTrue(o.ok, o.detail)
        self.assertEqual(o.decision.to_dict()["plan"],
                         {"steps": [GO, TAKE], "repeat": "every", "repeat_period": 24, "parent": "g:1"})

    def test_six_steps_pass_seven_do_not(self):
        self.assertTrue(self.check({"steps": [GO] * 6}).ok)
        self.refused({"steps": [GO] * 7}, Codes.TOO_MANY_STEPS)

    def test_an_unknown_gesture(self):
        self.refused({"steps": [GO, {"gesture": "fly", "target": "@L1"}]}, Codes.UNKNOWN_GESTURE)

    def test_a_pointer_of_the_wrong_type(self):
        self.refused({"steps": [{"gesture": "go", "target": "b:1"}]}, Codes.BAD_POINTER)          # a belief
        self.refused({"steps": [{"gesture": "go", "target": "g:1"}]}, Codes.BAD_POINTER)          # a goal
        self.refused({"steps": [{"gesture": "go", "target": "@E99"}]}, Codes.BAD_POINTER)         # not in the records
        self.refused({"steps": [{"gesture": "eat", "target": "@E1"}]}, Codes.BAD_POINTER)         # a person is not food

    def test_a_step_refused_by_check_gesture_is_d10(self):
        # @E2 looks 25 but is really 11: the governor knows, the plan must not reach a contact gesture on a child
        self.refused({"steps": [GO, {"gesture": "search", "target": "@E2"}]}, "governor:d10_person")
        # a hand-built minor as the actor: nothing intimate in a plan either
        self.assertTrue(self.check({"steps": [{"gesture": "search", "target": "@E1"}]}).ok)

    def test_the_other_plan_rules(self):
        self.refused({"steps": [{"gesture": "go"}]}, Codes.BAD_PLAN)                                  # go needs a target
        self.refused({"steps": [GO], "repeat": "sometimes"}, Codes.BAD_PLAN)
        self.refused({"steps": [GO], "repeat_period": "3"}, Codes.BAD_PLAN)                           # a period needs `every`
        self.refused({"steps": [GO], "repeat": "every", "repeat_period": "x"}, Codes.BAD_PLAN)
        self.refused({"steps": [GO], "parent": "b:1"}, Codes.BAD_PLAN)                                # a parent is a goal
        self.refused({"steps": [GO], "parent": "g:9"}, Codes.BAD_POINTER)
        self.refused("nonsense", Codes.BAD_SHAPE)
        self.refused({"steps": [{"target": "@L1"}]}, Codes.BAD_SHAPE)

    def test_no_plan_is_explicit_when_the_field_is_there(self):
        o = self.check({"steps": []})
        self.assertTrue(o.ok)
        self.assertIsNone(o.decision.to_dict()["plan"])
        o = self.check(None)
        self.assertTrue(o.ok and "plan" in o.decision.to_dict())

    def test_an_answer_without_a_plan_is_what_it_always_was(self):
        o = MINI_VALIDATOR.validate(answer("wait", (("until", "(c_elapsed 30)"),)), MINI)
        self.assertTrue(o.ok)
        self.assertEqual(set(o.decision.to_dict()), {"gesture", "params", "speech", "writes", "notes"})

    def test_the_decision_stop(self):
        go = dict(gesture="go", params=(("target", "@L1"), ("relation", "toward"), ("pace", "walk"), ("stealth", "open")))
        raw = json.loads(answer(go["gesture"], go["params"]))
        raw["stop"] = "(c_elapsed 30)"
        o = MINI_VALIDATOR.validate(json.dumps(raw), MINI)
        self.assertTrue(o.ok, o.detail)
        self.assertEqual(o.decision.to_dict()["stop"], "(c_elapsed 30)")
        raw["stop"] = "(c_nonsense)"
        self.assertEqual(MINI_VALIDATOR.validate(json.dumps(raw), MINI).code, Codes.BAD_PARAM)
        raw["stop"] = ""
        self.assertIsNone(MINI_VALIDATOR.validate(json.dumps(raw), MINI).decision.to_dict()["stop"])
        self.refused(None, Codes.BAD_PARAM, stop="(c_elapsed 30)")                                   # `wait` has its own until


class PlanSchemaTests(unittest.TestCase):
    def test_the_default_schema_is_unchanged_and_plans_are_opt_in(self):
        default, plans = DecisionSchema(TK), DecisionSchema(TK, plans=True)
        self.assertNotIn("plan", default.response_schema()["properties"])
        self.assertNotIn("== PLAN", default.instructions())
        self.assertEqual(default.fingerprint(), "bc8a9fcb85c8d279")          # pinned: the running generator keeps its prompt
        rs = plans.response_schema()
        self.assertIn("plan", rs["properties"])
        self.assertEqual(rs["required"], default.response_schema()["required"])
        self.assertIn("== PLAN", plans.instructions())
        self.assertEqual(rs["properties"]["plan"]["properties"]["steps"]["maxItems"], 6)


if __name__ == "__main__":
    unittest.main()
