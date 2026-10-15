"""Tests of the replay of the written mind (T11b): a planner line -> reflect lines + the act line. No network.

    python3 -m unittest discover -s ai/teacher/tests -t ai
"""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from tok2 import DecisionContext, Record, Tokenizer

from teacher.dataset import LabelRecord
from teacher.mind_replay import (BUDGET, REFLECT_GESTURE, MindReplay, MindState, ReplayError, is_reflect, kind_of_decision,
                                 replay_file, think_more_of, thought_of_decision)
from teacher.tests.test_teacher import MINI, TK

AGES = {"me": 30.0, "@E1": 35.0, "@E2": 11.0, "@E3": 40.0}
GO = {"gesture": "go", "target": "@L1"}
TOK = Tokenizer(TK.interface, grammar=TK.vocab)
MR = MindReplay(TK, TOK)


def line(thoughts, gesture="wait", params=None, mode="act", budget=0, index=0, writes=()) -> LabelRecord:
    recs = [Record(r.type, r.key, copy.deepcopy(r.fields)) for r in MINI.context.records]
    recs.append(Record("WAKE", "wake", {"mode": mode, "cause": "idle", "urgency": 2.0, "budget": budget, "temperament": 5.0}))
    ctx = DecisionContext(recs).to_dict(TOK)
    decision = {"gesture": gesture, "params": params if params is not None else {"until": "(c_elapsed 30)"}, "speech": None,
                "writes": list(writes), "notes": [], "thoughts": thoughts}
    return LabelRecord(ctx, decision, "ok", {"teacher": "test", "seed": 1, "index": index, "ages": AGES})


THREE = [{"kind": "belief", "target": "new", "prop": "(owns @E1 @T1)"},
         {"kind": "goal", "target": "new", "mode": "achieve", "prop": "(has me wooden_bowl)", "parent": "g:1", "deadline_h": 24.0,
          "when_h": None},
         {"kind": "plan", "serves": "g:new", "steps": [GO, {"gesture": "wait", "target": ""}], "says": None, "repeat": "once",
          "repeat_period": None}]


class ReplayShape(unittest.TestCase):
    def setUp(self):
        self.res = MR.replay(line(THREE))

    def test_n_thoughts_make_n_reflect_lines_and_one_act(self):
        self.assertTrue(self.res.ok, self.res.error)
        self.assertEqual([s.kind for s in self.res.steps], ["reflect", "reflect", "reflect", "act"])
        self.assertEqual([s.thought_kind for s in self.res.steps[:3]], ["belief", "goal", "plan"])

    def test_think_more_is_true_except_at_the_last_thought_and_the_budget_decreases(self):
        wakes = []
        for s in self.res.steps:
            w = next(r for r in s.record.context["records"] if r["type"] == "WAKE")["fields"]
            wakes.append((w["mode"], w["budget"]))
        self.assertEqual(wakes, [("reflect", BUDGET), ("reflect", BUDGET - 1), ("reflect", BUDGET - 2), ("act", BUDGET - 3)])
        self.assertEqual([think_more_of(s.record.decision) for s in self.res.steps[:3]], [True, True, False])
        self.assertIsNone(think_more_of(self.res.steps[3].record.decision))

    def test_a_reflect_decision_writes_one_record_with_the_existing_heads_vocabulary(self):
        d = [s.record.decision for s in self.res.steps]
        self.assertEqual(d[0]["gesture"], REFLECT_GESTURE)
        self.assertEqual([w["variable"] for w in d[0]["writes"]], ["think_more", "b_proposition"])
        self.assertEqual(d[0]["writes"][1]["target"], "new")
        self.assertEqual([w["variable"] for w in d[1]["writes"]], ["think_more", "g_desired"])
        self.assertEqual([w["variable"] for w in d[2]["writes"]], ["think_more"])       # a plan is the plan head's label
        self.assertIsNone(d[0]["plan"])
        self.assertEqual(d[2]["plan"]["parent"], "g:2")                                  # g:new became the key the goal got
        self.assertEqual([kind_of_decision(x) for x in d], ["belief", "goal", "plan", None])
        self.assertEqual(thought_of_decision(d[0])["prop"], "(owns @E1 @T1)")
        self.assertTrue(all(is_reflect(x) for x in d[:3]) and not is_reflect(d[3]))

    def test_the_states_grow_one_record_at_a_time_and_pointers_are_keys(self):
        ctxs = [MindState.of(s.record.context, TOK) for s in self.res.steps]
        keys = [sorted(r.key for r in c.records if r.type in ("BELIEF", "GOAL", "PLAN")) for c in ctxs]
        self.assertEqual(keys[0], ["b:1", "g:1"])
        self.assertEqual(keys[1], ["b:1", "b:2", "g:1"])
        self.assertEqual(keys[2], ["b:1", "b:2", "g:1", "g:2"])
        self.assertEqual(keys[3], ["b:1", "b:2", "g:1", "g:2", "p:1"])
        plan = ctxs[3].record("p:1").fields
        self.assertEqual((plan["goal"], plan["next"], plan["steps"], plan["step_targets"]), ("g:2", "go", ["go", "wait"], ["@L1"]))
        self.assertTrue(ctxs[3].record("g:2").fields["has_plan"])
        self.assertEqual(ctxs[3].record("g:2").fields["parent"], "g:1")
        self.assertEqual(ctxs[2].record("g:2").fields["prop"], "(has me wooden_bowl)")
        self.assertNotIn("thoughts", self.res.steps[3].record.decision)                  # the act no longer carries the trace
        for s in self.res.steps:
            text = json.dumps(s.record.decision)
            self.assertNotIn("slot", text)

    def test_every_line_is_a_label_line_with_a_unique_id_that_keeps_the_situation(self):
        ids = [s.record.id for s in self.res.steps]
        self.assertEqual(len(set(ids)), 4)
        self.assertEqual({i.split("#")[0] for i in ids}, {"1:0"})
        for s in self.res.steps:
            back = LabelRecord.from_line(s.record.to_line())
            self.assertEqual(back.context["header"], s.record.context["header"])


class ReplayRules(unittest.TestCase):
    def test_no_thought_keeps_the_line_as_an_act(self):
        r = MR.replay(line([]))
        self.assertTrue(r.ok)
        self.assertEqual([s.kind for s in r.steps], ["act"])
        self.assertEqual(MindState.of(r.steps[0].record.context, TOK).wake().fields["budget"], 0)

    def test_the_original_wake_mode_reflect_becomes_act_at_the_end_and_listen_stays(self):
        r = MR.replay(line(THREE[:1], mode="reflect", budget=3))
        self.assertEqual(MindState.of(r.steps[-1].record.context, TOK).wake().fields["mode"], "act")
        r = MR.replay(line(THREE[:1], mode="listen"))
        self.assertEqual(MindState.of(r.steps[-1].record.context, TOK).wake().fields["mode"], "listen")

    def test_a_revision_rewrites_the_record_it_points_at(self):
        r = MR.replay(line([{"kind": "goal", "target": "g:1", "mode": "achieve", "prop": "(has me wooden_bowl)", "parent": None,
                             "deadline_h": None, "when_h": None}]))
        self.assertTrue(r.ok, r.error)
        self.assertEqual(r.steps[0].record.decision["writes"][1]["target"], "g:1")
        end = MindState.of(r.steps[1].record.context, TOK)
        self.assertEqual(end.record("g:1").fields["prop"], "(has me wooden_bowl)")
        self.assertEqual(len(end.of_type("GOAL")), 1)

    def test_a_full_kind_evicts_the_least_salient_record_nothing_mentions_and_keeps_its_key_known(self):
        base = line(THREE[:1])
        st = MindState.of(base.context, TOK)
        cap = TK.interface.token_types["BELIEF"]["count"]
        for k in range(2, cap + 1):                                                 # fill the BELIEF budget
            st.records.append(Record("BELIEF", f"b:{k}", {"prop": f"(owns @E1 @T{1 + k % 3})", "source": "seen", "age": 2.0,
                                                          "certainty": 5.0, "polarity": True}))
            st.known.add(f"b:{k}")
        base.context = st.context(TOK)
        r = MR.replay(base)
        self.assertTrue(r.ok, r.error)
        after = MindState.of(r.steps[1].record.context, TOK)
        self.assertEqual(len(after.of_type("BELIEF")), cap)
        self.assertIsNotNone(after.record(f"b:{cap + 1}"))
        self.assertIn(f"b:{cap}", after.known)
        self.assertIsNone(after.record(f"b:{cap}"))                                 # the last (least salient) one left the batch

    def test_what_the_checkers_refuse_refuses_the_whole_line_and_nothing_is_bent(self):
        for bad, code in (([{"kind": "belief", "target": "new", "prop": "(owns @E9 @T1)"}], "thought_refused:bad_pointer"),
                          ([{"kind": "plan", "steps": [GO, {"gesture": "search", "target": "@E2"}]}], "thought_refused:governor:d10_person"),
                          ([{"kind": "plan", "serves": "g:new", "steps": [GO]}], "serves_unwritten_goal"),
                          ([{"kind": "belief", "target": "new", "prop": "(owns @E1"}], "thought_refused")):
            r = MR.replay(line(bad))
            self.assertFalse(r.ok)
            self.assertTrue(r.error.code.startswith(code.split(":")[0]), (r.error.code, code))
            if ":" in code:
                self.assertEqual(r.error.code, code if code != "thought_refused" else r.error.code)
        self.assertEqual(MR.replay(line([THREE[0]] * 6)).error.code, "too_many_thoughts")

    def test_the_act_is_revalidated_on_the_final_state(self):
        r = MR.replay(line(THREE[:1], gesture="take", params={"target": "@T1", "from": "ground", "hold": "in_hand", "stealth": "open",
                                                              "contact_zone": "hands"}))
        self.assertTrue(r.ok, r.error)
        bad = line(THREE[:1], gesture="take", params={"target": "@T9", "from": "ground", "hold": "in_hand", "stealth": "open",
                                                      "contact_zone": "hands"})
        self.assertEqual(MR.replay(bad).error.code, "act_refused:bad_pointer")

    def test_the_input_is_never_rewritten_in_place(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "dataset.jsonl"
            src.write_text(line(THREE).to_line() + "\n" + line([], index=1).to_line() + "\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                replay_file(src, src)
            dst = Path(d) / "replay.jsonl"
            rep = replay_file(src, dst, replay=MR)
            self.assertEqual((rep.lines, rep.valid_before, rep.replayed), (2, 2, 2))
            self.assertEqual(len(dst.read_text().splitlines()), 4 + 1)
            self.assertEqual(rep.to_dict()["reflect_by_kind"], {"belief": 1, "goal": 1, "plan": 1})
            self.assertEqual(rep.valid_rate, 1.0)


if __name__ == "__main__":
    unittest.main()
