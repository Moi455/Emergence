"""Tests of student2.evaluate (CPU, tiny model, the random smoke set: they test the scoring, not a behaviour).

    python3 -m unittest student2.tests.test_evaluate
"""
from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

import numpy as np
import torch

from student2.data import LabelDataset
from student2.evaluate import Evaluator, Predictions, flatten, load_model, stat, table
from student2.model import SIZES, StudentModel
from student2.runtime import Runtime
from student2.smoke import SmokeSet
from student2.train import Checkpoint

N = 40
RT: Runtime
TMP: tempfile.TemporaryDirectory
EV: Evaluator
MODEL: StudentModel


def setUpModule():
    global RT, TMP, EV, MODEL
    RT = Runtime.build()
    TMP = tempfile.TemporaryDirectory()
    path = Path(TMP.name) / "smoke.jsonl"
    SmokeSet(3).write(path, 64)
    ds = LabelDataset([path], split="val", val_fraction=0.5, runtime=RT, allow_smoke=True, keep_context=True,
                      cache_dir=Path(TMP.name) / "cache", workers=1)
    EV = Evaluator(RT, ds, batch=16, limit=N, device="cpu")
    torch.manual_seed(0)
    MODEL = StudentModel(SIZES["tiny"], RT.space).eval()


def tearDownModule():
    TMP.cleanup()


def oracle(ev: Evaluator) -> Predictions:
    """A 'model' that says exactly the labels."""
    truth = {k: v.copy() for k, v in EV_TRUTH.items()}
    meta = EV_META
    return Predictions(truth, {k: v.copy() for k, v in truth.items()}, np.repeat(truth["gesture"][:, None], 3, 1), meta)


class StatTest(unittest.TestCase):
    def test_empty_is_not_a_score(self):
        self.assertEqual(stat(np.zeros(3, bool), np.zeros(3, bool)), {"n": 0, "acc": None})

    def test_mask(self):
        self.assertEqual(stat([True, False, True, True], [1, 1, 0, 1]), {"n": 3, "acc": 2 / 3})


class ScoreTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        global EV_TRUTH, EV_META
        cls.p = EV.predict(MODEL)
        EV_TRUTH, EV_META = cls.p.truth, cls.p.meta

    def test_one_row_per_decision(self):
        self.assertEqual(self.p.n, len(EV.batches[0].meta) + sum(len(b.meta) for b in EV.batches[1:]))
        self.assertEqual(self.p.top3.shape, (self.p.n, 3))

    def test_oracle_scores_one_everywhere(self):
        rep = EV.score(oracle(EV))
        for name, s in flatten(rep).items():
            if s["n"]:
                self.assertEqual(s["acc"], 1.0, name)
        self.assertEqual(rep["validity"]["undecodable_reasons"], {})

    def test_wrong_gesture_is_counted(self):
        o = oracle(EV)
        o.pred["gesture"] = (o.pred["gesture"] + 1) % RT.space.gestures.n
        o.top3 = np.repeat(o.pred["gesture"][:, None], 3, 1)
        rep = EV.score(o)
        self.assertEqual(rep["gesture"]["top1"]["acc"], 0.0)
        self.assertEqual(rep["gesture"]["top3"]["acc"], 0.0)

    def test_top3_is_at_least_top1(self):
        rep = EV.score(self.p)
        self.assertGreaterEqual(rep["gesture"]["top3"]["acc"], rep["gesture"]["top1"]["acc"])

    def test_truncated_sentence_is_not_exact(self):
        o = oracle(EV)
        has = np.nonzero(o.truth["seq_len"][:, 0] > 1)[0]
        if not len(has):
            self.skipTest("no speech in this sample")
        o.pred["seq_len"][has[0], 0] -= 1
        s = EV.score(o)["sequences"]["speech_exact"]
        self.assertLess(s["acc"], 1.0)

    def test_report_and_table(self):
        rep = EV.score(self.p)
        text = table(rep)
        self.assertIn("gesture.top1", text)
        self.assertIn("refusal codes", text)

    def test_keys_have_gesture_and_pointers(self):
        keys = EV.keys(self.p)
        self.assertEqual(len(keys), self.p.n)
        self.assertTrue(all(isinstance(k[1], tuple) for k in keys))


class LoadTest(unittest.TestCase):
    def test_roundtrip_tensors_only(self):
        path = Path(TMP.name) / "tiny.pt"
        Checkpoint.save(path, MODEL, RT)
        m = load_model(path, RT, "cpu")
        for (k, a), (_, b) in zip(MODEL.state_dict().items(), m.state_dict().items()):
            self.assertTrue(torch.equal(a, b), k)
        EV2 = EV.predict(m)
        base = EV.predict(MODEL)
        self.assertTrue(np.array_equal(EV2.pred["gesture"], base.pred["gesture"]))


if __name__ == "__main__":
    unittest.main()
