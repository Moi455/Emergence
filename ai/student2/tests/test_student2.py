"""Tests of the student (CPU always, GPU when there is one). No network, no teacher: the data is the RANDOM smoke set.

    python3 -m unittest discover -s ai/student2/tests -t ai
"""
from __future__ import annotations

import dataclasses
import json
import tempfile
import unittest
from pathlib import Path

import torch

from student2.data import Collator, DatasetMismatch, LabelDataset
from student2.labels import LabelCodec, Targets, comparable, equivalent
from student2.losses import StudentLoss
from student2.model import SIZES, NoMemory, NpcMemory, StudentModel
from student2.runtime import Runtime
from student2.sequences import Steps
from student2.smoke import SMOKE_TEACHER, SmokeSet
from student2.train import Checkpoint, CheckpointMismatch, Trainer
from teacher.dataset import DatasetFile

N = 64
GPU = torch.cuda.is_available()
RT: Runtime
TMP: tempfile.TemporaryDirectory
PATH: Path
DS: LabelDataset


def setUpModule():
    global RT, TMP, PATH, DS
    RT = Runtime.build()
    TMP = tempfile.TemporaryDirectory()
    PATH = Path(TMP.name) / "smoke.jsonl"
    SmokeSet(3).write(PATH, N)
    DS = LabelDataset([PATH], runtime=RT, keep_context=True)


def tearDownModule():
    TMP.cleanup()


def batch(n=N, size=None):
    return Collator(RT.space.gestures.n, RT.space.self_type)([DS[i] for i in range(n)])


class SmokeFileTests(unittest.TestCase):
    def test_smoke_file_is_marked_and_valid(self):
        recs = list(DatasetFile(PATH))
        self.assertEqual(len(recs), N)
        self.assertTrue(all(r.source["teacher"] == SMOKE_TEACHER and r.verdict == "ok" for r in recs))

    def test_every_line_is_usable(self):
        self.assertEqual(DS.audit()["unusable"], 0)


class LabelTests(unittest.TestCase):
    def test_round_trip_and_idempotence(self):
        codec: LabelCodec = RT.codec
        for i in range(len(DS)):
            rec = DS.record(i)
            ex = DS.example(i)
            enc, records = ex.meta["enc"], ex.meta["records"]
            back = codec.decode(ex.targets, enc, records)
            self.assertTrue(equivalent(rec.decision, back, RT.space), f"line {i}:\n{comparable(rec.decision)}\n{comparable(back)}")
            self.assertEqual(codec.encode(back, enc, records), ex.targets, f"line {i}: encode(decode(t)) != t")

    def test_pointers_are_slots_and_ghosts_are_refused(self):
        ex = DS.example(0)
        enc, records = ex.meta["enc"], ex.meta["records"]
        ghost = next(g for g in enc.ghosts)
        bad = {"gesture": "look", "params": {"target": ghost, "mode": "glance", "stealth": "open"}, "speech": None, "writes": []}
        with self.assertRaises(Exception) as cm:
            RT.codec.encode(bad, enc, records)
        self.assertIn("not a record of this decision", str(cm.exception))

    def test_steps_depth_and_open(self):
        # (a (b c d) e): arity = 1 + number of arguments, so a:3 b:3 c:0 d:0 e:0
        s = Steps([1, 2, 3, 4, 5], [3, 3, 0, 0, 0], [0] * 5, [0] * 5)
        self.assertEqual(s.depths(), [0, 1, 2, 2, 1])
        self.assertEqual(s.open_after(), [True, True, True, True, False])

    def test_speech_text_survives(self):
        n = 0
        for i in range(len(DS)):
            rec = DS.record(i)
            if rec.decision["speech"]:
                ex = DS.example(i)
                back = RT.codec.decode(ex.targets, ex.meta["enc"], ex.meta["records"])
                self.assertEqual(comparable(back)["speech"], comparable(rec.decision)["speech"])
                n += 1
        self.assertGreater(n, 0)


class DatasetTests(unittest.TestCase):
    def test_collate_shapes_are_fixed_and_multiples_of_8(self):
        b = batch(16)
        self.assertEqual(b.n % 8, 0)
        self.assertEqual(b.ghosts % 8, 0)
        self.assertEqual(b.arrays["cat"].shape[:2], (16, b.n))
        self.assertEqual(b.targets["gesture"].shape, (16,))
        self.assertTrue((b.arrays["type_id"][torch.arange(16), b.self_idx] == RT.space.self_type).all())
        self.assertTrue(b.feasible.all())

    def test_split_is_disjoint_and_stable(self):
        tr, va = LabelDataset([PATH], "train", runtime=RT), LabelDataset([PATH], "val", runtime=RT)
        self.assertEqual(len(tr) + len(va), N)
        self.assertTrue(set(tr.index).isdisjoint(va.index))

    def test_dataset_for_another_layout_is_refused(self):
        rec = DS.record(0)
        rec.context["header"]["layout"] = "0" * 16
        other = Path(TMP.name) / "other.jsonl"
        other.write_text(rec.to_line() + "\n")
        with self.assertRaises(DatasetMismatch):
            LabelDataset([other], runtime=RT)

    def test_on_the_fly_tokenisation_is_deterministic(self):
        self.assertEqual(DS.example(5).meta["digest"], DS.example(5).meta["digest"])


class ModelTests(unittest.TestCase):
    def check_backward(self, device, size, amp):
        torch.manual_seed(0)
        m = StudentModel(SIZES[size], RT.space).to(device)
        b = batch(8).to(device)
        with torch.autocast(device, dtype=torch.float16, enabled=amp):
            out = m(b)
        loss, parts, _ = StudentLoss()(out, b)
        self.assertTrue(torch.isfinite(loss))
        loss.backward()
        bad = [n for n, p in m.named_parameters() if p.grad is not None and not torch.isfinite(p.grad).all()]
        self.assertEqual(bad, [])
        self.assertGreater(sum(float(p.grad.abs().sum()) for p in m.parameters() if p.grad is not None), 0)
        return m, b

    def test_forward_backward_cpu(self):
        self.check_backward("cpu", "tiny", False)

    @unittest.skipUnless(GPU, "no GPU")
    def test_forward_backward_gpu_fp16_small(self):
        self.check_backward("cuda", "small", True)

    def test_predict_shapes_and_decodable_keys(self):
        m = StudentModel(SIZES["tiny"], RT.space).eval()
        b = batch(4)
        p = m.predict(b)
        self.assertEqual(p["gesture"].shape, (4,))
        self.assertEqual(p["seq_sym"].shape[:2], (4, RT.space.sequences.MAX_SEQUENCES))
        self.assertTrue((p["w_var"] >= 0).all() and (p["w_var"] < RT.space.writes.n).all())

    def test_write_masks_only_allow_variables_of_the_target_kind(self):
        m = StudentModel(SIZES["tiny"], RT.space).eval()
        b = batch(16)
        with torch.no_grad():
            o = m(b, teacher=False)
        ok = m.var_ok[o["w_kind"]]
        chosen = o["w_var_choice"]
        self.assertTrue(torch.gather(ok, 2, chosen.unsqueeze(-1)).all())

    def test_memory_hook_noop_and_tokens(self):
        m0 = StudentModel(SIZES["tiny"], RT.space, NoMemory()).eval()
        b = batch(4)
        self.assertIsInstance(m0.memory, NpcMemory)
        self.assertEqual(m0.memory.n_tokens, 0)

        class Eight(NpcMemory):
            n_tokens = 8

            def read(self, state, self_emb):
                return self_emb.unsqueeze(1).expand(-1, 8, -1) * 0.0 + 0.1

            def write(self, state, encoded, valid):
                return encoded[:, 0]

        m1 = StudentModel(SIZES["tiny"], RT.space, Eight()).eval()
        with torch.no_grad():
            o = m1(b, teacher=False)
        self.assertEqual(o["memory"].shape[0], 4)                      # the state to carry to the next decision
        self.assertEqual(o["enc"].shape[1], b.n)                        # extra tokens are not records

    def test_bad_memory_size_is_refused(self):
        class Three(NoMemory):
            n_tokens = 3
        with self.assertRaises(ValueError):
            StudentModel(SIZES["tiny"], RT.space, Three())


class OverfitTests(unittest.TestCase):
    def test_overfits_a_batch_of_64(self):
        device = "cuda" if GPU else "cpu"
        torch.manual_seed(0)
        b = batch(N)
        m = StudentModel(SIZES["tiny"], RT.space)
        steps = 260
        tr = Trainer(m, device, lr=2e-3, total_steps=steps, warmup=20)
        first = float(tr.train_step(b)["loss"])
        for _ in range(steps - 1):
            r = tr.train_step(b)
        last = float(r["loss"])
        self.assertGreater(first, 10.0)
        self.assertLess(last, 0.5, f"loss {first:.1f} -> {last:.3f}")
        ev = tr.evaluate([b], RT)
        self.assertGreaterEqual(ev["exact_decision"], 0.9, ev)          # the model's OWN greedy decisions, written token by token
        self.assertEqual(ev["gesture_acc"], 1.0)


class CommandLineTests(unittest.TestCase):
    def test_train_cli_runs_saves_and_resumes_on_cpu(self):
        from student2.train import main
        out = Path(TMP.name) / "run"
        args = ["--data", str(PATH), "--size", "tiny", "--batch", "16", "--workers", "0", "--device", "cpu",
                "--out", str(out), "--log-every", "1", "--eval-every", "0", "--save-every", "0"]
        self.assertEqual(main(args + ["--epochs", "1"]), 0)
        self.assertTrue((out / "last.pt").exists() and (out / "log.jsonl").exists())
        self.assertEqual(main(args + ["--epochs", "1", "--resume", str(out / "last.pt")]), 0)
        log = [json.loads(line) for line in open(out / "log.jsonl")]
        self.assertTrue(any("eval" in r for r in log))

    def test_schedule_warms_up_then_decays(self):
        from student2.train import Schedule
        s = Schedule(1.0, 10, 110)
        self.assertLess(s(0), s(9))
        self.assertAlmostEqual(s(10), 1.0, places=2)
        self.assertAlmostEqual(s(110), 0.1, places=2)


class CheckpointTests(unittest.TestCase):
    def setUp(self):
        self.m = StudentModel(SIZES["tiny"], RT.space)
        self.path = Path(TMP.name) / "ck.pt"

    def test_round_trip_keeps_weights(self):
        Checkpoint.save(self.path, self.m, RT.fingerprints(), {"step": 7})
        m2, payload = Checkpoint.load(self.path, RT)
        self.assertEqual(payload["step"], 7)
        for (n, a), (_, b) in zip(self.m.state_dict().items(), m2.state_dict().items()):
            self.assertTrue(torch.equal(a, b), n)

    def test_checkpoint_with_other_fingerprints_is_refused(self):
        for key in ("layout", "interface", "registry", "vocabulary", "output"):
            other = dataclasses.replace(RT.fingerprints(), **{key: "deadbeefdeadbeef"})
            Checkpoint.save(self.path, self.m, other)
            with self.assertRaises(CheckpointMismatch) as cm:
                Checkpoint.load(self.path, RT)
            self.assertIn(key, str(cm.exception))

    def test_other_version_is_refused(self):
        Checkpoint.save(self.path, self.m, RT.fingerprints())
        payload = torch.load(self.path, weights_only=False)
        payload["version"] = 99
        torch.save(payload, self.path)
        with self.assertRaises(CheckpointMismatch):
            Checkpoint.load(self.path, RT)


if __name__ == "__main__":
    unittest.main()
