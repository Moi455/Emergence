"""Tests of the `xl` size (the oversized yardstick) and of compare.py. The mechanisms (dropout, gradient checkpointing)
are tested on `tiny`; xl itself is only built and counted (no forward of 175 M parameters in the tests)."""
from __future__ import annotations

import dataclasses
import tempfile
import unittest
from pathlib import Path

import torch

from student2.compare import gpu_share, table
from student2.data import LabelDataset
from student2.evaluate import Evaluator, Predictions
from student2.labels import NO_PLAN_LABEL, LabelCodec, Targets
from student2.losses import StudentLoss
from student2.spec import NO_LABEL
from student2.model import SIZES, StudentConfig, StudentModel
from student2.runtime import Runtime
from student2.smoke import SmokeSet

RT: Runtime
TMP: tempfile.TemporaryDirectory
BATCH = None


def setUpModule():
    global RT, TMP, BATCH
    RT = Runtime.build()
    TMP = tempfile.TemporaryDirectory()
    path = Path(TMP.name) / "smoke.jsonl"
    SmokeSet(3).write(path, 16)
    ds = LabelDataset([path], runtime=RT, allow_smoke=True, cache_dir=Path(TMP.name) / "cache", workers=1)
    BATCH = ds.collator(False)([ds[i] for i in range(8)])


def tearDownModule():
    TMP.cleanup()


def tiny(**kw) -> StudentModel:
    torch.manual_seed(0)
    return StudentModel(dataclasses.replace(SIZES["tiny"], **kw), RT.space)


def gradients(m: StudentModel) -> dict:
    torch.manual_seed(1)                                             # same dropout masks when dropout is on
    m.train()
    out = m(BATCH)
    loss, _, _ = StudentLoss()(out, BATCH)
    loss.backward()
    return {n: p.grad.clone() for n, p in m.named_parameters() if p.grad is not None}


class XlSizeTest(unittest.TestCase):
    def test_xl_is_between_100_and_200_million_parameters(self):
        self.assertIn("xl", SIZES)
        n = StudentModel(SIZES["xl"], RT.space).n_params()
        self.assertTrue(100e6 <= n <= 200e6, n)

    def test_xl_trains_with_checkpointing_and_dropout_by_default(self):
        self.assertTrue(SIZES["xl"].checkpoint)
        self.assertGreater(SIZES["xl"].dropout, 0)
        self.assertEqual(SIZES["xl"].d % SIZES["xl"].heads, 0)

    def test_old_config_without_new_fields_still_loads(self):
        old = {k: v for k, v in SIZES["small"].to_dict().items() if k not in ("dropout", "checkpoint")}
        cfg = StudentConfig(**old)
        self.assertEqual((cfg.dropout, cfg.checkpoint), (0.0, False))

    def test_other_sizes_are_unchanged(self):
        for s in ("tiny", "small", "base"):
            self.assertEqual((SIZES[s].dropout, SIZES[s].checkpoint), (0.0, False))


class MechanismTest(unittest.TestCase):
    def test_checkpointing_gives_the_same_gradients(self):
        a, b = gradients(tiny()), gradients(tiny(checkpoint=True))
        self.assertEqual(a.keys(), b.keys())
        for n in a:
            torch.testing.assert_close(a[n], b[n], rtol=1e-4, atol=1e-6, msg=n)

    def test_dropout_acts_in_training_only(self):
        m = tiny(dropout=0.5)
        m.eval()
        with torch.no_grad():
            e1, e2 = m(BATCH, teacher=False)["gesture"], m(BATCH, teacher=False)["gesture"]
        self.assertTrue(torch.equal(e1, e2))
        m.train()
        with torch.no_grad():
            t = m(BATCH, teacher=False)["gesture"]
        self.assertFalse(torch.equal(e1, t))

    def test_dropout_zero_is_the_old_model(self):
        a, b = tiny(), tiny(dropout=0.0)
        a.eval(), b.eval()
        with torch.no_grad():
            self.assertTrue(torch.equal(a(BATCH, teacher=False)["gesture"], b(BATCH, teacher=False)["gesture"]))


class CompareReportTest(unittest.TestCase):
    ENTRY = {"size_MiB": 1.0, "decision_valid": 0.9, "agreement_with_fp16": None,
             "report": {"gesture": {"top1": {"n": 10, "acc": 0.5}, "top3": {"n": 10, "acc": 0.8}}},
             "bench": {"batch32": {"policy_graph_ms": 16.0, "weights_MiB": 1, "peak_inference_MiB": 2, "policy_graph_decisions_per_s": 2000},
                       "batch128": {"policy_graph_ms": 128.0, "weights_MiB": 1, "peak_inference_MiB": 3, "policy_graph_decisions_per_s": 1000}}}

    def test_gpu_share_is_rate_times_time_per_decision(self):
        s = gpu_share(self.ENTRY, 200, (32, 128))
        self.assertAlmostEqual(s["batch32"], 200 * 0.016 / 32, places=3)       # 0.1
        self.assertAlmostEqual(s["batch128"], 200 * 0.128 / 128, places=3)     # 0.2

    def test_gpu_share_without_measure_is_none(self):
        self.assertIsNone(gpu_share({"bench": {"batch32": {"error": "oom"}}}, 200, (32,))["batch32"])

    def test_table_flags_the_budget(self):
        xl = dict(self.ENTRY, bench={"batch32": {"policy_graph_ms": 640.0}, "batch128": {"policy_graph_ms": 2560.0}})
        res = {"small": {"fp16": self.ENTRY}, "xl": {"fp16": xl}}
        t = table(res, (32, 128), 200)
        self.assertIn("(dépasse)", t)
        self.assertIn("(tient)", t)


class ThoughtsPlanTest(unittest.TestCase):
    """T36 lines carry the plan inside `thoughts`; it must reach the plan head (and no-plan must be explicit)."""
    PLAN = {"kind": "plan", "serves": "g:1", "steps": [{"gesture": "go", "target": "@T1"}], "says": None, "repeat": "once", "repeat_period": None}

    def test_plan_thought_becomes_the_plan_label(self):
        d = {"gesture": "go", "thoughts": [{"kind": "goal", "target": "new"}, self.PLAN]}
        self.assertEqual(LabelCodec.plan_of(d), {"steps": self.PLAN["steps"], "repeat": "once", "repeat_period": None, "parent": "g:1"})

    def test_new_goal_has_no_parent(self):
        self.assertIsNone(LabelCodec.plan_of({"thoughts": [dict(self.PLAN, serves="g:new")]})["parent"])

    def test_trace_without_plan_is_an_explicit_no_plan(self):
        self.assertIsNone(LabelCodec.plan_of({"thoughts": [{"kind": "belief"}]}))
        self.assertIsNone(LabelCodec.plan_of({"thoughts": []}))

    def test_no_trace_no_plan_key_says_nothing(self):
        self.assertIs(LabelCodec.plan_of({"gesture": "go"}), NO_PLAN_LABEL)

    def test_top_level_plan_wins(self):
        self.assertEqual(LabelCodec.plan_of({"plan": None, "thoughts": [self.PLAN]}), None)

    def test_unlabelled_plan_and_stop_of_the_model_are_not_judged(self):
        names = Targets.names()
        t = Targets(**{n: __import__("numpy").zeros(2, int) for n in names})
        truth = {n: __import__("numpy").full((1, 2), NO_LABEL) for n in ("plan_gesture", "plan_ref", "plan_repeat", "plan_period", "plan_parent")}
        truth.update(stop=__import__("numpy").array([NO_LABEL]))
        for n in ("stop_ref", "stop_num", "stop_word"):
            truth[n] = __import__("numpy").zeros((1, 1), int)
        p = Predictions(truth, {}, None, [])
        Evaluator.mask_unlabelled(t, p, 0)
        self.assertTrue((t.plan_gesture == NO_LABEL).all())
        self.assertTrue((t.plan_parent == NO_LABEL).all())
        self.assertTrue((t.stop_ref == NO_LABEL).all())


if __name__ == "__main__":
    unittest.main()
