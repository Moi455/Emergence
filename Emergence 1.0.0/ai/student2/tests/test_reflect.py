"""Tests of the written mind in the student (T11b): reflect lines made by `teacher.mind_replay` are read by the existing data
chain, learned by the existing heads (write chain with target `new`, sentence decoder, plan head, `think_more`) and scored by
`reflection.py`. A tiny model learns SYNTHETIC thoughts (a rule of the wake cause: this is a test of the chain, not of any
behaviour). CPU, no network.

    python3 -m unittest discover -s ai/student2/tests -t ai
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import torch

from student2.data import LabelDataset
from student2.evaluate import Evaluator
from student2.labels import Targets
from student2.model import SIZES, StudentModel
from student2.runtime import Runtime
from student2.smoke import SmokeSet
from student2.spec import NO_LABEL
from student2.train import Trainer
from teacher.dataset import LabelRecord
from teacher.mind_replay import MindReplay, MindState, think_more_of

N_SITUATIONS = 100
RT: Runtime
TMP: tempfile.TemporaryDirectory
PATH: Path
REPORT: dict


def thoughts_for(rec: LabelRecord, ctx) -> list:
    """A synthetic, deterministic trace: the kinds depend on the wake cause, the content on the first entity / thing."""
    cause = next(r for r in rec.context["records"] if r["type"] == "WAKE")["fields"]["cause"]
    ent = next((r.key for r in ctx.records if r.type == "ENTITY"), None)
    thing = next((r for r in ctx.records if r.type == "THING"), None)
    if ent is None or thing is None:
        return []
    belief = {"kind": "belief", "target": "new", "prop": f"(owns {ent} {thing.key})"}
    goal = {"kind": "goal", "target": "new", "mode": "achieve", "prop": f"(has me {thing.fields['kind']})", "parent": None,
            "deadline_h": None, "when_h": None}
    plan = {"kind": "plan", "serves": "g:new", "steps": [{"gesture": "examine", "target": thing.key}], "says": None, "repeat": "once",
            "repeat_period": None}
    if cause in ("perception", "speech", "request"):
        return [belief, goal]
    if cause in ("body", "plan", "idle"):
        return [goal]
    return [goal, plan]


def setUpModule():
    global RT, TMP, PATH, REPORT
    RT = Runtime.build()
    TMP = tempfile.TemporaryDirectory()
    smoke = Path(TMP.name) / "smoke.jsonl"
    SmokeSet(5).write(smoke, N_SITUATIONS)
    mr = MindReplay(RT.tk, RT.tokenizer)
    PATH = Path(TMP.name) / "replay.jsonl"
    kept = made = 0
    with open(smoke, encoding="utf-8") as f, open(PATH, "w", encoding="utf-8") as out:
        for line in f:
            rec = LabelRecord.from_line(line)
            ctx = MindState.of(rec.context, RT.tokenizer)
            rec.decision["thoughts"] = thoughts_for(rec, ctx)
            res = mr.replay(rec)
            made += 1
            if res.ok and rec.decision["thoughts"]:
                kept += 1
                out.writelines(s.record.to_line() + "\n" for s in res.steps)
    REPORT = {"situations": made, "replayed": kept}


def tearDownModule():
    TMP.cleanup()


class ReflectChain(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ds = LabelDataset([PATH], runtime=RT, allow_smoke=True, keep_context=True, cache_dir=Path(TMP.name) / "cache", workers=1)

    def test_enough_lines_were_replayed_and_none_is_lost_by_the_reader(self):
        self.assertGreater(REPORT["replayed"], 60, REPORT)
        a = self.ds.audit()
        self.assertEqual((a["foreign"], a["duplicates"], a["unusable"]), (0, 0, 0), a)

    def test_the_labels_say_reflect_think_more_and_an_explicit_plan_or_no_plan(self):
        sp = RT.space
        tm = sp.writes.index["think_more"]
        n_reflect = n_act = 0
        for i in range(len(self.ds)):
            t = self.ds[i].targets
            ws = [int(x) for x in t["w_var"][:int(t["n_writes"])]]
            if tm in ws and int(t["plan_gesture"][0]) != NO_LABEL:
                n_reflect += 1
                self.assertEqual(int(t["gesture"]), sp.gestures.index["stop"])
            else:
                n_act += 1
                self.assertEqual(int(t["plan_gesture"][0]), NO_LABEL)                       # the act says nothing about plans
        self.assertGreater(n_reflect, n_act)
        self.assertEqual(n_act, REPORT["replayed"])

    def test_decode_of_the_labels_gives_back_the_replayed_decisions(self):
        for i in range(0, len(self.ds), 5):
            ex, rec = self.ds[i], self.ds.record(i)
            back = RT.codec.decode(Targets(**{k: np.asarray(v).astype(np.int64) for k, v in ex.targets.items()}),
                                   ex.meta["enc"], ex.meta["records"])
            self.assertEqual(think_more_of(back), think_more_of(rec.decision))
            self.assertEqual(back.get("plan"), rec.decision.get("plan"))

    def test_a_split_keeps_all_the_steps_of_one_situation_on_the_same_side(self):
        tr = LabelDataset([PATH], split="train", val_fraction=0.05, runtime=RT, allow_smoke=True, cache_dir=Path(TMP.name) / "cache", workers=1)
        va = LabelDataset([PATH], split="val", val_fraction=0.05, runtime=RT, allow_smoke=True, keep_context=True,
                          cache_dir=Path(TMP.name) / "cache", workers=1)
        base = lambda ds: {ds.record(i).id.split("#")[0] for i in range(len(ds))}               # noqa: E731
        self.assertTrue(base(va))
        self.assertFalse(base(va) & base(tr))

    def test_a_tiny_model_learns_synthetic_thoughts_from_the_existing_heads(self):
        torch.manual_seed(0)
        model = StudentModel(SIZES["tiny"], RT.space)
        epochs, per = 40, -(-len(self.ds) // 32)
        tr = Trainer(model, "cpu", lr=2e-3, total_steps=epochs * per, warmup=20, seed=0)
        first = last = None
        for e in range(epochs):
            for b in self.ds.loader(32, shuffle=True, seed=0, epoch=e):
                r = tr.train_step(b)
            first = float(r["loss"]) if first is None else first
            last = float(r["loss"])
        self.assertLess(last, first / 2)
        ev = Evaluator(RT, self.ds, batch=32, device="cpu")
        _, rep = ev.run(model)
        r = rep["reflection"]
        self.assertEqual(r["examples"], r["kind"]["n"])
        self.assertGreater(r["kind"]["acc"], 0.85, json.dumps(r["kind"]))                         # the TYPE of thought
        self.assertGreater(r["think_more"]["acc"], 0.85, json.dumps(r["think_more"]))              # go on thinking or act
        self.assertGreater(r["variable"]["acc"], 0.85)
        self.assertIn("goal", r["by_kind"])
        self.assertGreater(r["plan_exact"]["acc"], 0.7)                                           # the plan head, in reflect mode
        self.assertIsNotNone(r["proposition_valid"]["acc"])                                      # validity is measured, not assumed
        self.assertIn("validity", rep)                                                           # the acts are still judged by the validator
        self.assertEqual(rep["validity"]["reflect_rows_judged_in_reflection"], r["examples"])


if __name__ == "__main__":
    unittest.main()
