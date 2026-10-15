"""Tests of T11: the plan head, the decision-stop head, the versioned checkpoint and the partial loader. CPU, no network.

    python3 -m unittest discover -s ai/student2/tests -t ai
"""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import torch

from student2.data import LabelDataset
from student2.labels import LabelError, Targets
from student2.model import SIZES, StudentModel
from student2.output_registry import SCHEMA, OutputRegistry
from student2.partial import PartialLoader
from student2.runtime import Runtime
from student2.smoke import SmokeSet
from student2.spec import NO_LABEL
from student2.train import Checkpoint, CheckpointMismatch, Trainer

N = 64
RT: Runtime
TMP: tempfile.TemporaryDirectory
DS: LabelDataset


def setUpModule():
    global RT, TMP, DS
    RT = Runtime.build()
    TMP = tempfile.TemporaryDirectory()
    path = Path(TMP.name) / "smoke.jsonl"
    SmokeSet(3, plans=True).write(path, N)
    DS = LabelDataset([path], runtime=RT, allow_smoke=True, cache_dir=Path(TMP.name) / "cache", workers=1, keep_context=True)


def tearDownModule():
    TMP.cleanup()


def encode(decision: dict, i: int = 0) -> Targets:
    ex = DS[i]
    return RT.codec.encode(decision, ex.meta["enc"], ex.meta["records"])


def first_with_plan() -> tuple[int, dict]:
    for i in range(len(DS)):
        d = DS.record(i).decision
        if d.get("plan") and len(d["plan"]["steps"]) >= 2:
            return i, copy.deepcopy(d)
    raise AssertionError("the smoke set has no plan of 2 steps")


class PlanLabelTests(unittest.TestCase):
    def test_a_plan_and_a_stop_round_trip(self):
        n_plan = n_stop = 0
        for i in range(len(DS)):
            rec, ex = DS.record(i), DS[i]
            t = Targets(**{k: np.asarray(v).astype(np.int64) for k, v in ex.targets.items()})
            back = RT.codec.decode(t, ex.meta["enc"], ex.meta["records"])
            for key in ("plan", "stop"):
                self.assertEqual(back.get(key, "absent"), rec.decision.get(key, "absent"), f"line {i} {key}")
            n_plan += bool(rec.decision.get("plan"))
            n_stop += bool(rec.decision.get("stop"))
        self.assertGreater(n_plan, 20)
        self.assertGreater(n_stop, 10)

    def test_an_explicit_no_plan_and_no_stop_are_labels_too(self):
        i, d = first_with_plan()
        d["plan"], d["stop"] = None, None
        d["params"] = {k: v for k, v in d["params"].items()}
        try:
            t = encode(d, i)
        except LabelError:                                   # that gesture has an `until`: no decision stop
            d.pop("stop")
            t = encode(d, i)
        self.assertEqual(int(t.plan_gesture[0]), RT.space.plan.fin)
        self.assertTrue((t.plan_ref == NO_LABEL).all())
        self.assertIsNone(RT.codec.decode(t, DS[i].meta["enc"], DS[i].meta["records"])["plan"])

    def test_no_plan_key_means_no_label(self):
        i, d = first_with_plan()
        d.pop("plan"), d.pop("stop", None)
        t = encode(d, i)
        self.assertTrue((t.plan_gesture == NO_LABEL).all() and int(t.stop) == NO_LABEL)

    def test_what_the_heads_cannot_say_is_refused(self):
        i, d = first_with_plan()
        keys = DS[i].meta["enc"].keys
        step = d["plan"]["steps"][0]
        for name, mutate in (("too many steps", lambda p: p["steps"].extend([step] * 7)),
                             ("unknown gesture", lambda p: p["steps"][0].update(gesture="fly")),
                             ("a ghost", lambda p: p["steps"][0].update(target="@E999")),
                             ("bad repeat", lambda p: p.update(repeat="sometimes"))):
            bad = copy.deepcopy(d)
            mutate(bad["plan"])
            with self.assertRaises(LabelError, msg=name):
                encode(bad, i)
        belief = next((k for k in keys if k.startswith("b:")), None)
        if belief:                                           # a belief is not a record a step may point to
            bad = copy.deepcopy(d)
            bad["plan"]["steps"][0]["target"] = belief
            with self.assertRaises(LabelError):
                encode(bad, i)

    def test_the_output_registry_of_schema_1_is_read_and_upgraded(self):
        older = RT.space.registry.to_dict()
        older["schema"] = "student2-output-registry-1"
        older["capacity"].pop("plan_steps")
        older.pop("lists"), older.pop("plan_steps_used")
        reg = OutputRegistry(older)
        self.assertEqual(reg.d["schema"], SCHEMA)
        self.assertEqual(reg.capacity["plan_steps"], 8)
        self.assertEqual(RT.space.registry.compatible(older), [])
        self.assertEqual(RT.space.plan.cap, 8)
        self.assertEqual(RT.space.plan.used, 6)


class PlanModelTests(unittest.TestCase):
    def test_predict_writes_at_most_six_steps_then_fin(self):
        m = StudentModel(SIZES["tiny"], RT.space).eval()
        b = DS.collator(False)([DS[i] for i in range(8)])
        p = m.predict(b)
        fin = RT.space.plan.fin
        g = p["plan_gesture"].numpy()
        self.assertEqual(g.shape, (8, 8))
        self.assertTrue((g[:, 6:] == fin).all())
        after_fin = np.maximum.accumulate(g == fin, axis=1)
        self.assertTrue((g[after_fin] == fin).all(), "nothing but FIN after FIN")
        self.assertTrue(((g < RT.space.gestures.cap) & RT.space.gestures.live[np.minimum(g, 63)] | (g == fin)).all())
        self.assertTrue((p["plan_ref"].numpy()[g == fin] == NO_LABEL).all())

    def test_200_steps_on_synthetic_plans_lower_the_loss(self):
        """Synthetic plans, learnable: step 1 is the decision's own gesture on its own first pointer, step 2 is `rest`."""
        torch.manual_seed(0)
        examples, fields = [], ("plan_gesture", "plan_ref", "plan_repeat", "plan_period", "plan_parent")
        for i in range(len(DS)):
            ex, d = DS[i], copy.deepcopy(DS.record(i).decision)
            shape = RT.space.gestures.shape(d["gesture"])
            first = d["params"].get(shape.refs[0].name) if shape.refs else None
            d["plan"] = {"steps": [{"gesture": d["gesture"], "target": first}, {"gesture": "rest", "target": None}],
                         "repeat": "each_day" if first else "once", "repeat_period": None, "parent": None}
            d.pop("stop", None)
            try:
                t = RT.codec.encode(d, ex.meta["enc"], ex.meta["records"])
            except LabelError:
                continue
            for f in fields:
                ex.targets[f] = np.asarray(getattr(t, f)).astype(np.int16)
            ex.targets["stop"] = np.asarray(NO_LABEL, np.int16)
            examples.append(ex)
        self.assertGreater(len(examples), 40)
        b = DS.collator(False)(examples)
        m = StudentModel(SIZES["tiny"], RT.space)
        tr = Trainer(m, "cpu", lr=2e-3, total_steps=200, warmup=10)
        first = tr.train_step(b)
        for _ in range(199):
            last = tr.train_step(b)
        plan = lambda r: sum(float(r["parts"][k]) for k in ("plan_gesture", "plan_ref", "plan_repeat"))      # noqa: E731
        self.assertLess(float(last["loss"]), 0.5 * float(first["loss"]), (float(first["loss"]), float(last["loss"])))
        self.assertLess(plan(last), 0.25 * plan(first), (plan(first), plan(last)))


class VersionedCheckpointTests(unittest.TestCase):
    """A checkpoint of before T11 / T09 is built here by REDUCING the tables of a current tiny model: the vocabulary 36
    symbols shorter (the end rows of the decoder sit just after the symbols), no plan or stop head, an input matrix of
    another width, an older registry (schema 1)."""

    DROP = 36

    def old_payload(self) -> tuple[dict, StudentModel]:
        torch.manual_seed(1)
        m = StudentModel(SIZES["tiny"], RT.space)
        V, v = m.dims.vocab, m.dims.vocab - self.DROP
        state = {k: x.clone() for k, x in m.state_dict().items() if not k.startswith(("plan.", "stop."))}
        state["embed.cat.emb.weight"] = state["embed.cat.emb.weight"][:v].clone()
        state["embed.prop.sym.weight"] = state["embed.prop.sym.weight"][:v].clone()
        sym = state["decoder.sym.weight"]
        state["decoder.sym.weight"] = torch.cat([sym[:v], sym[V:V + 2]]).clone()
        state["embed.num.l1.weight"] = state["embed.num.l1.weight"][:, :-4].clone()          # another input width
        state["ghost_head.weight"] = torch.zeros(3, 3)                                       # a tensor the model no longer has
        older = RT.space.registry.to_dict()
        older.update(schema="student2-output-registry-1")
        older["capacity"].pop("plan_steps"), older.pop("lists"), older.pop("plan_steps_used")
        fp = {k: "0123456789abcdef" for k in ("interface", "layout", "registry", "vocabulary", "output")}
        payload = {"version": 2, "config": m.cfg.to_dict(), "fingerprints": {"schema": "student2-2", **fp},
                   "output_registry": older, "model": state, "step": 5}
        return payload, m

    def test_an_old_checkpoint_does_not_load_as_is_but_loads_partially(self):
        payload, full = self.old_payload()
        path = Path(TMP.name) / "old.pt"
        torch.save(payload, path)
        with self.assertRaises(CheckpointMismatch) as cm:
            Checkpoint.load(path, RT)
        self.assertIn("partial", str(cm.exception))
        model, loaded = Checkpoint.load(path, RT, partial=True)
        rep = loaded["load_report"]
        V, v = model.dims.vocab, model.dims.vocab - self.DROP
        heads = sorted(k for k in full.state_dict() if k.startswith(("plan.", "stop.")))
        self.assertGreater(len(heads), 20)
        self.assertEqual(sorted(rep["new"]), heads)
        self.assertEqual(sorted(rep["reset"]), ["embed.num.l1.weight"])
        self.assertEqual(rep["reset"]["embed.num.l1.weight"]["old"][1] + 4, rep["reset"]["embed.num.l1.weight"]["new"][1])
        self.assertEqual(sorted(rep["remapped"]), ["decoder.sym.weight", "embed.cat.emb.weight", "embed.prop.sym.weight"])
        self.assertEqual(rep["dropped"], ["ghost_head.weight"])
        self.assertEqual(sorted(rep["copied"] + rep["new"] + list(rep["reset"]) + list(rep["remapped"])), sorted(full.state_dict()))
        self.assertEqual(PartialLoader.reinitialized_of(rep),
                         sorted(heads + ["embed.num.l1.weight", "decoder.sym.weight", "embed.cat.emb.weight", "embed.prop.sym.weight"]))
        self.assertEqual(loaded["step"], 5)
        self.assertIn("vocabulary", loaded["fingerprint_diff"])
        # what was copied is bit for bit the old weights, the old symbols keep their rows, the end rows MOVED
        old, new = payload["model"], model.state_dict()
        for name in rep["copied"]:
            self.assertTrue(torch.equal(old[name], new[name]), name)
        for name in ("embed.cat.emb.weight", "embed.prop.sym.weight"):
            self.assertTrue(torch.equal(old[name], new[name][:v]), name)
        self.assertTrue(torch.equal(old["decoder.sym.weight"][:v], new["decoder.sym.weight"][:v]))
        self.assertTrue(torch.equal(old["decoder.sym.weight"][v:], new["decoder.sym.weight"][V:V + 2]))
        # the rows of the new symbols and the new heads are the fresh initial weights, not the old values nor zeros
        fresh = StudentModel(SIZES["tiny"], RT.space).state_dict()
        self.assertFalse(torch.equal(new["embed.cat.emb.weight"][v:], full.state_dict()["embed.cat.emb.weight"][v:]))
        self.assertTrue(torch.isfinite(new["embed.cat.emb.weight"]).all() and float(new["embed.cat.emb.weight"][v:].abs().sum()) > 0)
        self.assertEqual(fresh["plan.gesture.weight"].shape, new["plan.gesture.weight"].shape)
        # and the reloaded model runs
        with torch.no_grad():
            model.eval()(DS.collator(False)([DS[i] for i in range(4)]), teacher=False)

    def test_a_vocabulary_larger_than_the_current_one_is_reset_not_guessed(self):
        payload, _ = self.old_payload()
        payload["model"]["embed.cat.emb.weight"] = torch.zeros(RT.space.sequences.vocab_size + 5, SIZES["tiny"].d)
        path = Path(TMP.name) / "old2.pt"
        torch.save(payload, path)
        _, loaded = Checkpoint.load(path, RT, partial=True)
        self.assertIn("embed.cat.emb.weight", loaded["load_report"]["reset"])

    def test_checkpoints_carry_their_schema_and_shapes(self):
        m = StudentModel(SIZES["tiny"], RT.space)
        path = Path(TMP.name) / "v3.pt"
        Checkpoint.save(path, m, RT, {"step": 1})
        payload = torch.load(path, weights_only=False)
        self.assertEqual(payload["version"], 3)
        self.assertEqual(payload["registry_schema"], SCHEMA)
        self.assertEqual(payload["shapes"]["plan.gesture.weight"], list(m.plan.gesture.weight.shape))
        self.assertEqual(set(payload["shapes"]), set(m.state_dict()))
        _, again = Checkpoint.load(path, RT, partial=True)             # a current checkpoint, loaded partially: all copied
        rep = again["load_report"]
        self.assertEqual((rep["new"], rep["reset"], rep["remapped"], rep["dropped"]), ([], {}, {}, []))
        Checkpoint.load(path, RT)                                      # strict still works


if __name__ == "__main__":
    unittest.main()
