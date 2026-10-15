"""Tests of the student (CPU always, GPU when there is one). No network, no teacher: the data is the RANDOM smoke set.

    python3 -m unittest discover -s ai/student2/tests -t ai
"""
from __future__ import annotations

import dataclasses
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import torch

from student2 import data as D
from student2.data import Collator, DatasetMismatch, LabelDataset, SyntheticData
from student2.labels import LabelCodec, LabelError, Targets, comparable, equivalent
from student2.losses import StudentLoss
from student2.model import SIZES, NoMemory, NpcMemory, StudentModel
from student2.output_registry import Needs, OutputRegistry, RegistryError
from student2.runtime import Runtime
from student2.sequences import Steps
from student2.smoke import SMOKE_TEACHER, SmokeSet
from student2.spec import NO_LABEL, QuantityGrid
from student2.train import Checkpoint, CheckpointMismatch, Trainer
from teacher.dataset import DatasetFile, LabelRecord, LineMeta

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
    SmokeSet(3, plans=True).write(PATH, N)
    DS = opened(PATH, keep_context=True)


def tearDownModule():
    TMP.cleanup()


def opened(*paths, **kw) -> LabelDataset:
    kw.setdefault("allow_smoke", True)
    kw.setdefault("cache_dir", Path(TMP.name) / "cache")
    kw.setdefault("workers", 1)
    return LabelDataset(list(paths), runtime=RT, **kw)


def batch(n=N, fixed=False, ds=None, **pad):
    ds = ds or DS
    return ds.collator(fixed, **pad)([ds[i] for i in range(n)])


def write_lines(name: str, lines: list[str]) -> Path:
    p = Path(TMP.name) / name
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def raw_lines() -> list[str]:
    with open(PATH, encoding="utf-8") as f:
        return f.readlines()


class DataIntegrityTests(unittest.TestCase):
    def test_smoke_lines_are_marked_and_refused_by_default(self):
        recs = list(DatasetFile(PATH))
        self.assertTrue(all(r.synthetic and r.teacher == SMOKE_TEACHER and r.verdict == "ok" for r in recs))
        self.assertIn('"synthetic":true', raw_lines()[0][:200])                  # readable from the start of the line
        with self.assertRaises(SyntheticData):
            LabelDataset([PATH], runtime=RT, cache_dir=Path(TMP.name) / "cache")
        # a teacher called smoke* is refused even without the flag on the line
        line = json.loads(raw_lines()[0])
        line.pop("synthetic")
        with self.assertRaises(SyntheticData):
            opened(write_lines("named.jsonl", [json.dumps(line)]), allow_smoke=False)

    def test_header_is_read_from_the_start_of_the_line(self):
        line = raw_lines()[0]
        meta = LineMeta.of(line)
        self.assertEqual(meta.hdr, LabelRecord.short_header(RT.tokenizer.header()))
        self.assertEqual(meta.id, f"{LabelRecord.from_line(line).source['seed']}:{LabelRecord.from_line(line).source['index']}")
        self.assertTrue(meta.smoke)

    def test_foreign_lines_are_excluded_and_counted_below_the_threshold_and_fail_above(self):
        lines = raw_lines()
        bad = json.loads(lines[0])
        bad["hdr"] = "00000000:00000000"
        path = write_lines("foreign1.jsonl", lines[:60] + [json.dumps(bad)])         # 1 of 61
        ds = opened(path)
        self.assertEqual((ds.stats["foreign"], len(ds)), (1, 60))
        many = write_lines("foreign2.jsonl", [json.dumps(bad)] * 10 + lines[:50])    # 10 of 60 = 17 %
        with self.assertRaises(DatasetMismatch):
            opened(many)

    def test_duplicates_are_kept_once_and_split_is_a_function_of_the_id(self):
        lines = raw_lines()
        ds = opened(write_lines("dup.jsonl", lines + lines[:5]))
        self.assertEqual((ds.stats["duplicates"], len(ds)), (5, N))
        tr, va = opened(PATH, split="train"), opened(PATH, split="val")
        self.assertEqual(len(tr) + len(va), N)
        shuffled = write_lines("rev.jsonl", lines[::-1])                              # the order of the lines does not matter
        tr2 = opened(shuffled, split="train")
        ids = lambda d: {d.record(i).id for i in range(len(d))}                      # noqa: E731
        self.assertEqual(ids(tr), ids(tr2))
        self.assertTrue(ids(tr).isdisjoint(ids(va)))

    def test_unusable_lines_are_excluded_not_substituted(self):
        lines = raw_lines()
        bad = json.loads(lines[1])
        bad["decision"]["gesture"] = "no_such_gesture"
        bad["source"]["index"] = 99999
        bad["id"] = bad["source"]["seed"].__str__() + ":99999"
        ds = opened(write_lines("unusable.jsonl", lines[:20] + [json.dumps(bad)]))
        self.assertEqual((ds.stats["unusable"], len(ds)), (1, 20))
        self.assertTrue(ds.stats["unusable_reasons"])
        ids = {ds.record(i).id for i in range(len(ds))}
        self.assertNotIn(bad["id"], ids)
        bads = write_lines("mostly_bad.jsonl", [json.dumps(bad | {"id": f"7:{i}"}) for i in range(8)] + lines[:4])
        with self.assertRaises(LabelError):
            opened(bads)

    def test_cache_is_built_once_and_matches_a_fresh_tokenisation(self):
        calls = []
        real = D.ChunkBuilder.build
        D.ChunkBuilder.build = classmethod(lambda cls, task: calls.append(1) or real.__func__(cls, task))
        try:
            path = write_lines("cache_once.jsonl", raw_lines()[:30])
            a = opened(path)
            n_first = len(calls)
            b = opened(path)
        finally:
            D.ChunkBuilder.build = real
        self.assertEqual((n_first, len(calls)), (1, 1))                               # the second open reads the cache
        ex = a[3]
        rec = a.record(3)
        enc = RT.tokenizer.encode(__import__("tok2").DecisionContext.loads(json.dumps(rec.context), RT.tokenizer))
        self.assertEqual(ex.meta["digest"], enc.digest() & 0xFFFFFFFF)
        self.assertEqual(ex.n, enc.n)
        for k in D.ARRAYS:
            self.assertTrue(np.array_equal(ex.arrays[k], getattr(enc, k)[:enc.n]), k)
        self.assertTrue(np.array_equal(b[3].arrays["num"], ex.arrays["num"]))

    def test_chunks_built_by_several_processes_equal_the_single_process_build(self):
        saved = D.CHUNK
        D.CHUNK = 16
        try:
            lines = raw_lines()
            multi = opened(write_lines("multi.jsonl", lines), cache_dir=Path(TMP.name) / "cache_multi", workers=3)
            single = opened(write_lines("single.jsonl", lines), cache_dir=Path(TMP.name) / "cache_single", workers=1)
        finally:
            D.CHUNK = saved
        self.assertEqual((len(multi), len(single)), (N, N))
        self.assertGreater(len({d for d, _ in multi.items}), 2)                       # four chunks
        for i in (0, 17, 40, 63):
            self.assertEqual(multi[i].meta["digest"], single[i].meta["digest"])
            self.assertTrue(all(np.array_equal(multi[i].targets[k], single[i].targets[k]) for k in multi[i].targets))

    def test_cache_is_keyed_by_the_catalogue_state(self):
        a = D.state_key(RT)
        saved = RT.fingerprints
        RT.fingerprints = lambda: dataclasses.replace(saved(), layout="f" * 16)
        try:
            self.assertNotEqual(a, D.state_key(RT))
        finally:
            RT.fingerprints = saved

    def test_rounding_over_5_percent_is_counted(self):
        grid = QuantityGrid()
        self.assertEqual(grid.error(256), 0.0)                                        # exact up to 256
        self.assertLess(max(grid.error(x) for x in range(257, 9_000_000, 997)), 0.125)
        self.assertGreater(grid.error(1_000_003), 0.0)
        self.assertEqual(DS.stats["rounding_over_5pct"], 0)                           # smoke numbers are small

    def test_epoch_order_depends_only_on_seed_and_epoch(self):
        a, b = list(D.EpochSampler(50, 1, 2, True)), list(D.EpochSampler(50, 1, 2, True))
        self.assertEqual(a, b)
        self.assertNotEqual(a, list(D.EpochSampler(50, 1, 3, True)))
        self.assertEqual(list(D.EpochSampler(50, 1, 2, True, skip=10)), a[10:])


class LabelTests(unittest.TestCase):
    def test_round_trip_and_idempotence(self):
        codec: LabelCodec = RT.codec
        for i in range(len(DS)):
            rec, ex = DS.record(i), DS[i]
            enc, records = ex.meta["enc"], ex.meta["records"]
            t = Targets(**{k: np.asarray(v).astype(np.int64) for k, v in ex.targets.items()})
            back = codec.decode(t, enc, records)
            self.assertTrue(equivalent(rec.decision, back, RT.space), f"line {i}:\n{comparable(rec.decision)}\n{comparable(back)}")
            self.assertEqual(codec.encode(back, enc, records), t, f"line {i}: encode(decode(t)) != t")

    def test_ghosts_are_refused_as_targets(self):
        ex = next(DS[i] for i in range(len(DS)) if DS[i].meta["enc"].ghosts)
        enc, records = ex.meta["enc"], ex.meta["records"]
        ghost = enc.ghosts[0]
        bad = {"gesture": "look", "params": {"target": ghost, "mode": "glance", "stealth": "open"}, "speech": None, "writes": []}
        with self.assertRaises(LabelError) as cm:
            RT.codec.encode(bad, enc, records)
        self.assertIn("not a record of this decision", str(cm.exception))

    def test_a_label_the_masks_would_forbid_is_refused(self):
        ex = DS[0]
        enc, records = ex.meta["enc"], ex.meta["records"]
        sp = RT.space
        g = sp.gestures.index["look"]
        wrong = next(k for k, t in zip(enc.keys, enc.type_id) if not sp.gestures.ref_type_ok[g, 0, t])    # e.g. a belief
        with self.assertRaises(LabelError):
            RT.codec.encode({"gesture": "look", "params": {"target": wrong, "mode": "glance", "stealth": "open"},
                             "speech": None, "writes": []}, enc, records)

    def test_steps_depth_and_open(self):
        s = Steps([1, 2, 3, 4, 5], [3, 3, 0, 0, 0], [0] * 5, [0] * 5)           # (a (b c d) e)
        self.assertEqual(s.depths(), [0, 1, 2, 2, 1])
        self.assertEqual(s.open_after(), [True, True, True, True, False])

    def test_arity_tables_accept_every_sentence_of_the_data(self):
        ok = RT.space.sequences.arity_ok
        n = 0
        for i in range(len(DS)):
            t = DS[i].targets
            for s in range(t["seq_len"].shape[0]):
                for j in range(int(t["seq_len"][s])):
                    self.assertTrue(ok[int(t["seq_sym"][s, j]), int(t["seq_arity"][s, j])])
                    n += 1
        self.assertGreater(n, 15)

    def test_exact_quantities_up_to_256(self):
        g = RT.space.quantity
        self.assertGreater(len(g), 290)
        for x in (0, 1, 17, 100, 256):
            self.assertEqual(g.value_of(g.bin_of(x)), x)


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.reg = RT.space.registry
        self.need = Needs(RT.tk.spec, sorted(RT.tk.cat["form"]))

    def test_registry_covers_the_catalogue_and_is_stable(self):
        self.assertEqual(self.reg.diff(self.need), ([], []))
        self.assertEqual(self.reg.updated(self.need).to_dict(), self.reg.to_dict())      # --update is a no-op

    def test_growth_appends_and_keeps_every_index(self):
        need = Needs(RT.tk.spec, sorted(RT.tk.cat["form"]))
        need.gestures = dict(need.gestures, brand_new="ref:target:0:item")
        need.manner = dict(need.manner, intensity=need.manner["intensity"] + ["extreme"])
        grown = self.reg.updated(need)
        self.assertEqual(grown.names("gestures")[:len(self.reg.names("gestures"))], self.reg.names("gestures"))
        self.assertEqual(grown.names("gestures")[-1], "brand_new")
        self.assertEqual(grown.compatible(self.reg.to_dict()), [])                          # the old one is a prefix of the new
        self.assertTrue(self.reg.compatible(grown.to_dict()))                               # but not the other way round
        self.assertTrue(grown.compatible(dict(grown.to_dict(), gestures=list(reversed(grown.d["gestures"])))))
        self.assertEqual(grown.fingerprint, self.reg.fingerprint)                         # the shapes did not change

    def test_a_changed_signature_is_a_conflict_and_a_capacity_overflow_too(self):
        need = Needs(RT.tk.spec, sorted(RT.tk.cat["form"]))
        need.gestures = dict(need.gestures, go=need.gestures["go"] + "|expression:extra")
        with self.assertRaises(RegistryError):
            self.reg.updated(need)
        need = Needs(RT.tk.spec, sorted(RT.tk.cat["form"]))
        need.gestures = dict(need.gestures, **{f"g{i}": "" for i in range(40)})
        with self.assertRaises(RegistryError):
            self.reg.updated(need)

    def test_a_stale_registry_names_the_command(self):
        stale = OutputRegistry(dict(self.reg.to_dict(), gestures=self.reg.d["gestures"][:-1]))
        with self.assertRaises(RegistryError) as cm:
            stale.require(self.need)
        self.assertIn("--update", str(cm.exception))


class MaskTests(unittest.TestCase):
    def setUp(self):
        torch.manual_seed(0)
        self.m = StudentModel(SIZES["tiny"], RT.space).eval()

    def test_no_label_is_ever_masked_out(self):
        """The masks of the heads and the labels agree on the whole data: every target logit is allowed."""
        b = batch()
        with torch.no_grad():
            out = self.m(b)
        T = b.targets
        for name in ("gesture", "ref", "manner", "cond", "cond_ref", "cond_word", "n_writes", "w_target", "w_var", "w_enum", "w_ptr"):
            logits, target = out[name], T[name]
            valid = target != NO_LABEL
            got = logits.gather(-1, target.clamp(min=0).unsqueeze(-1)).squeeze(-1)
            self.assertTrue(bool((got[valid] > -5000).all()), name)
        sp = out["speech"]
        for k, t in (("sym", "sym"), ("arity", "arity"), ("slot", "slot")):
            target = sp["targets"][t]
            if k == "slot":
                target = torch.where(target > 0, target - 1, target)
            valid = target != NO_LABEL
            got = sp[k].gather(-1, target.clamp(min=0).unsqueeze(-1)).squeeze(-1)
            self.assertTrue(bool((got[valid] > -5000).all()), "speech " + k)

    def test_none_only_for_an_optional_parameter(self):
        b = batch(8)
        sp = RT.space
        with torch.no_grad():
            o = self.m(b)
        g = o["gesture_choice"]
        for i in range(8):
            shape = sp.gestures.shapes[int(g[i])]
            for k, rp in enumerate(shape.refs):
                none_allowed = bool(o["ref"][i, k, 0] > -5000)
                self.assertEqual(none_allowed, rp.optional, f"{shape.id}.{rp.name}")

    def test_writes_are_ordered_and_variables_fit_their_target(self):
        b = batch(32)
        with torch.no_grad():
            o = self.m(b, teacher=False)
        p = self.m.predict(b)
        tgt, var, kind, nw = p["w_target"], p["w_var"], o["w_kind"], p["n_writes"]
        sp = RT.space
        made = 0
        for i in range(32):
            for j in range(int(nw[i])):
                made += 1
                self.assertTrue(sp.writes.target_ok[int(kind[i, j]), int(var[i, j])])
                if j:
                    self.assertTrue(int(tgt[i, j]) > int(tgt[i, j - 1]) or (int(tgt[i, j]) == int(tgt[i, j - 1]) and int(var[i, j]) > int(var[i, j - 1])))
        self.assertGreater(made, 5)

    def test_generated_sentences_respect_arity_pointer_kind_and_close(self):
        b = batch(16)
        sp = RT.space.sequences
        with torch.no_grad():
            o = self.m(b, teacher=False)
            init = torch.randn(16, self.m.cfg.d)
            gen = self.m.decoder.generate(init, o["enc"], o["ok"], b.slot_ptrkind)
        self.assertEqual(int(gen["forced"].sum()), 0)
        for i in range(16):
            n = int(gen["len"][i])
            self.assertGreater(n, 0)
            self.assertLessEqual(n, sp.max_symbols)
            for j in range(n):
                sym, ar, slot = (int(gen[k][i, j]) for k in ("sym", "arity", "slot"))
                self.assertTrue(sp.arity_ok[sym, ar])
                if sp.is_pointer[sym]:
                    self.assertEqual(int(b.slot_ptrkind[i, slot - 1]), int(sp.pointer_kind_of[sym]))
            self.assertEqual(int(gen["sym"][i, n]), sp.eos)                 # and the tree closes on its own

    def test_predict_writes_sentences_for_the_pairs_that_speak_within_the_capacity(self):
        b = batch(16)
        p = self.m.predict(b, speech_capacity=8)
        self.assertEqual(int((p["seq_len"] >= 0).sum()) + int(p["speech_overflow"]),
                         int(self.m.has_expr[p["gesture"]].sum()) + int(sum(
                             (self.m.var_kind[p["w_var"][i, :int(p["n_writes"][i])]] == 5).sum() for i in range(16))))


class ModelTests(unittest.TestCase):
    def check_backward(self, device, size, amp):
        torch.manual_seed(0)
        m = StudentModel(SIZES[size], RT.space).to(device)
        b = batch(N).to(device)
        with torch.autocast(device, dtype=torch.float16, enabled=amp):
            out = m(b)
        loss, parts, _ = StudentLoss()(out, b)
        self.assertTrue(torch.isfinite(loss))
        loss.backward()
        bad = [n for n, p in m.named_parameters() if p.grad is not None and not torch.isfinite(p.grad).all()]
        self.assertEqual(bad, [])
        unused = [h for h in ("w_qty", "cond_num", "w_enum", "w_ptr", "cond_ref", "cond_word") if not bool((b.targets[h] != NO_LABEL).any())]
        if not bool((b.targets["w_target"] == RT.space.pointers.NEW).any()):         # no write creates a record in this draw
            unused.append("new_vec")
        dead = [n for n, p in m.named_parameters() if (p.grad is None or float(p.grad.abs().sum()) == 0.0)
                and not any(n.startswith(h) for h in unused)]
        self.assertEqual(dead, [], "parameters that no head ever uses")
        return m, b

    def test_forward_backward_cpu_and_no_dead_parameter(self):
        self.check_backward("cpu", "tiny", False)

    @unittest.skipUnless(GPU, "no GPU")
    def test_forward_backward_gpu_fp16_small(self):
        self.check_backward("cuda", "small", True)

    def test_predict_shapes_and_valid_indices(self):
        m = StudentModel(SIZES["tiny"], RT.space).eval()
        p = m.predict(batch(4))
        self.assertEqual(p["gesture"].shape, (4,))
        self.assertEqual(p["seq_sym"].shape[:2], (4, RT.space.sequences.MAX_SEQUENCES))
        self.assertTrue(bool(RT.space.gestures.live[p["gesture"].numpy()].all()))

    def test_memory_hook_noop_and_tokens(self):
        m0 = StudentModel(SIZES["tiny"], RT.space, NoMemory()).eval()
        self.assertIsInstance(m0.memory, NpcMemory)
        self.assertEqual(m0.memory.n_tokens, 0)

        class Eight(NpcMemory):
            n_tokens = 8

            def read(self, state, self_emb):
                return self_emb.unsqueeze(1).expand(-1, 8, -1) * 0.0 + 0.1

            def write(self, state, encoded, valid):
                return encoded[:, 0]

        m1 = StudentModel(SIZES["tiny"], RT.space, Eight()).eval()
        b = batch(4)
        with torch.no_grad():
            o = m1(b, teacher=False)
        self.assertEqual(o["memory"].shape[0], 4)
        self.assertEqual(o["enc"].shape[1], b.n)

    def test_bad_memory_size_is_refused(self):
        class Three(NoMemory):
            n_tokens = 3
        with self.assertRaises(ValueError):
            StudentModel(SIZES["tiny"], RT.space, Three())

    def test_weight_decay_by_module_type(self):
        from student2.train import make_optimizer
        m = StudentModel(SIZES["tiny"], RT.space)
        opt = make_optimizer(m, 1e-3)
        decayed = {id(p) for p in opt.param_groups[0]["params"]}
        for mod in m.modules():
            for name, p in mod.named_parameters(recurse=False):
                self.assertEqual(id(p) in decayed, isinstance(mod, torch.nn.Linear) and name == "weight", f"{type(mod).__name__}.{name}")


class DeterminismTests(unittest.TestCase):
    def logits(self, m, b):
        with torch.no_grad(), torch.autocast(b.self_idx.device.type, dtype=torch.float16, enabled=b.self_idx.device.type == "cuda"):
            return m(b, teacher=False)

    def test_same_batch_twice_gives_identical_logits(self):
        device = "cuda" if GPU else "cpu"
        torch.manual_seed(0)
        m = StudentModel(SIZES["tiny"], RT.space).to(device).eval()
        b = batch(16, fixed=True).to(device)
        a, c = self.logits(m, b), self.logits(m, b)
        for k in ("gesture", "ref", "manner", "w_target", "w_var", "w_num", "enc"):
            self.assertTrue(torch.equal(a[k], c[k]), k)

    def test_an_example_alone_or_in_a_batch_gets_the_same_logits(self):
        device = "cuda" if GPU else "cpu"
        torch.manual_seed(0)
        m = StudentModel(SIZES["tiny"], RT.space).to(device).eval()
        pad = dict(pad_to=128, pad_ghosts=40)
        full = batch(16, fixed=True, **pad).to(device)
        a = self.logits(m, full)
        for i in (0, 5, 11):
            one = batch(1, fixed=True, ds=_Single(DS, i), **pad).to(device)
            b = self.logits(m, one)
            self.assertEqual(one.n, full.n)
            self.assertEqual(int(b["gesture_choice"][0]), int(a["gesture_choice"][i]))
            for k in ("gesture", "ref", "manner", "w_target", "w_num"):
                self.assertLess(float((a[k][i] - b[k][0]).abs().max()), 5e-3, k)           # same shapes, other batch size: kernels differ in the last bits

    @unittest.skipUnless(GPU, "no GPU")
    def test_forward_and_speech_are_capturable_in_a_cuda_graph(self):
        torch.manual_seed(0)
        m = StudentModel(SIZES["tiny"], RT.space).cuda().eval()
        b = batch(16, fixed=True).to("cuda")

        def policy():
            with torch.no_grad(), torch.autocast("cuda", dtype=torch.float16):
                return m(b, teacher=False)

        def run_graph(fn):
            side = torch.cuda.Stream()
            side.wait_stream(torch.cuda.current_stream())
            with torch.cuda.stream(side):
                for _ in range(2):
                    fn()
            torch.cuda.current_stream().wait_stream(side)
            g = torch.cuda.CUDAGraph()
            with torch.cuda.graph(g):                 # a data-dependent shape, a sync or an atomic op would fail here
                out = fn()
            g.replay()
            torch.cuda.synchronize()
            return out

        out = run_graph(policy)
        ref = policy()
        self.assertTrue(torch.equal(out["gesture"], ref["gesture"]) and torch.equal(out["ref"], ref["ref"]))
        init = torch.randn(8, m.cfg.d, device="cuda")
        enc, ok, pk = ref["enc"][:8].clone(), ref["ok"][:8].clone(), b.slot_ptrkind[:8]

        def speech():
            with torch.no_grad(), torch.autocast("cuda", dtype=torch.float16):
                return m.decoder.generate(init, enc, ok, pk)

        s_graph, s_eager = run_graph(speech), speech()
        self.assertTrue(torch.equal(s_graph["sym"], s_eager["sym"]))


class _Single:
    """A one-example view of a dataset, to collate a decision alone."""

    def __init__(self, ds, i):
        self.ds, self.i = ds, i

    def __getitem__(self, j):
        return self.ds[self.i]

    def collator(self, fixed, **pad):
        return self.ds.collator(fixed, **pad)


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
        self.assertLess(last, 0.7, f"loss {first:.1f} -> {last:.3f}")        # the soft ordinal targets leave an entropy floor
        ev = tr.evaluate(_Eval(opened(PATH, keep_context=True)), RT)
        self.assertGreaterEqual(ev["exact_decision"], 0.9, ev)              # the model's OWN greedy decisions, token by token
        self.assertEqual(ev["decode_errors"], 0)
        self.assertEqual(ev["forced_eos"], 0)


class _Eval:
    """The first 64 examples as ONE batch with their records (what `evaluate` needs)."""

    def __init__(self, ds):
        self.ds = ds

    def __iter__(self):
        yield batch(N, ds=self.ds)


class CommandLineTests(unittest.TestCase):
    def args(self, out, epochs, *more):
        return ["--data", str(PATH), "--smoke-test", "--cache", str(Path(TMP.name) / "cache"), "--size", "tiny", "--batch", "16",
                "--workers", "0", "--device", "cpu", "--out", str(out), "--log-every", "1", "--eval-every", "0", "--save-every", "0",
                "--epochs", str(epochs), *more]

    def test_train_refuses_smoke_data_without_the_flag(self):
        from student2.train import main
        args = [a for a in self.args(Path(TMP.name) / "r0", 1) if a != "--smoke-test"]
        with self.assertRaises(SyntheticData):
            main(args)

    def test_train_cli_saves_and_resumes_to_the_total_number_of_epochs(self):
        from student2.train import main
        out = Path(TMP.name) / "run"
        self.assertEqual(main(self.args(out, 1)), 0)
        ck = torch.load(out / "last.pt", weights_only=False)
        per_epoch = ck["step"]
        self.assertTrue({"optimizer", "scaler", "step", "total_steps", "epoch", "epochs", "output_registry"} <= set(ck))
        self.assertEqual(ck["total_steps"], per_epoch)
        self.assertEqual(main(self.args(out, 3, "--resume", str(out / "last.pt"))), 0)         # --epochs is the TOTAL
        ck2 = torch.load(out / "last.pt", weights_only=False)
        self.assertEqual(ck2["step"], 3 * per_epoch)
        self.assertEqual(ck2["total_steps"], per_epoch)                                          # the schedule keeps its plan
        self.assertEqual(main(self.args(out, 3, "--resume", str(out / "last.pt"))), 0)         # nothing left to do
        self.assertEqual(torch.load(out / "last.pt", weights_only=False)["step"], 3 * per_epoch)
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
        Checkpoint.save(self.path, self.m, RT, {"step": 7})
        m2, payload = Checkpoint.load(self.path, RT)
        self.assertEqual(payload["step"], 7)
        for (n, a), (_, b) in zip(self.m.state_dict().items(), m2.state_dict().items()):
            self.assertTrue(torch.equal(a, b), n)

    def test_checkpoint_with_other_fingerprints_is_refused(self):
        for key in ("layout", "interface", "registry", "vocabulary", "output"):
            Checkpoint.save(self.path, self.m, RT)
            payload = torch.load(self.path, weights_only=False)
            payload["fingerprints"][key] = "deadbeefdeadbeef"
            torch.save(payload, self.path)
            with self.assertRaises(CheckpointMismatch) as cm:
                Checkpoint.load(self.path, RT)
            self.assertIn(key, str(cm.exception))

    def test_other_version_is_refused(self):
        Checkpoint.save(self.path, self.m, RT)
        payload = torch.load(self.path, weights_only=False)
        payload["version"] = 99
        torch.save(payload, self.path)
        with self.assertRaises(CheckpointMismatch):
            Checkpoint.load(self.path, RT)

    def test_a_catalogue_that_grew_inside_the_capacities_still_loads_and_a_foreign_registry_does_not(self):
        Checkpoint.save(self.path, self.m, RT)
        payload = torch.load(self.path, weights_only=False)
        # the checkpoint was made when the registry had one gesture fewer: still a prefix of the current one
        older = RT.space.registry.to_dict()
        older["gestures"] = older["gestures"][:-1]
        payload["output_registry"] = older
        torch.save(payload, self.path)
        Checkpoint.load(self.path, RT)
        # a registry in which the order differs is another meaning of the same indices
        other = RT.space.registry.to_dict()
        other["gestures"] = list(reversed(other["gestures"]))
        payload["output_registry"] = other
        torch.save(payload, self.path)
        with self.assertRaises(CheckpointMismatch):
            Checkpoint.load(self.path, RT)


class OverfitHelper(unittest.TestCase):
    def test_collator_has_no_dropped_edges_and_fixed_buckets(self):
        b = batch(N)
        self.assertEqual(b.dropped_edges, 0)
        f = batch(N, fixed=True)
        self.assertIn(f.n, (64, 128))
        self.assertIn(f.ghosts, (8, 40))
        self.assertEqual(f.arrays["cat_id"].shape[2] in D.K_BUCKETS, True)


if __name__ == "__main__":
    unittest.main()
