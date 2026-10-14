"""Tests of student2.quantize (tiny model, random weights, CPU; the int8 kernel test runs only with a GPU).

    python3 -m unittest student2.tests.test_quantize
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import torch
import torch.nn as nn

from student2.data import LabelDataset
from student2.evaluate import Evaluator
from student2.model import SIZES, StudentModel
from student2.quantize import (Comparison, DynamicInt8, DynamicInt8Linear, Fp16Reference, Int8Linear, Scope, WeightOnlyInt8,
                               agreement, markdown, model_bytes, quantize_weight)
from student2.runtime import Runtime
from student2.smoke import SmokeSet

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
    EV = Evaluator(RT, ds, batch=16, limit=24, device="cpu")
    torch.manual_seed(0)
    MODEL = StudentModel(SIZES["tiny"], RT.space).eval()


def tearDownModule():
    TMP.cleanup()


class WeightTest(unittest.TestCase):
    def test_per_channel_error_is_half_a_step(self):
        w = torch.randn(32, 64) * torch.linspace(0.01, 3, 32)[:, None]
        q, scale = quantize_weight(w)
        self.assertEqual(q.dtype, torch.int8)
        err = (q.float() * scale.float()[:, None] - w).abs()
        self.assertTrue(bool((err <= scale.float()[:, None] / 2 + 1e-6).all()))

    def test_zero_row_does_not_divide_by_zero(self):
        q, scale = quantize_weight(torch.zeros(4, 8))
        self.assertTrue(bool(torch.isfinite(scale.float()).all()) and not q.any())


class LayerTest(unittest.TestCase):
    def setUp(self):
        torch.manual_seed(1)
        self.lin = nn.Linear(64, 48)
        self.x = torch.randn(3, 20, 64)

    def rel(self, y):
        ref = self.lin(self.x)
        return float((y - ref).detach().norm() / ref.detach().norm())

    def test_weight_only_close(self):
        self.assertLess(self.rel(Int8Linear(self.lin)(self.x)), 0.02)

    def test_w8a8_close_and_uses_the_int_path(self):
        layer = DynamicInt8Linear(self.lin)
        self.assertLess(self.rel(layer(self.x)), 0.03)
        self.assertEqual((layer.int_mm_calls, layer.fallback_calls), (1, 0))

    def test_few_rows_fall_back(self):
        layer = DynamicInt8Linear(self.lin)
        layer(self.x[:1, :8])
        self.assertEqual((layer.int_mm_calls, layer.fallback_calls), (0, 1))

    def test_odd_width_falls_back(self):
        layer = DynamicInt8Linear(nn.Linear(64, 5))
        layer(torch.randn(40, 64))
        self.assertEqual((layer.int_mm_calls, layer.fallback_calls), (0, 1))

    def test_many_rows_are_cut_in_chunks(self):
        layer = DynamicInt8Linear(self.lin)
        layer.CHUNK_ROWS = 64
        y = layer(self.x)                                                # 60 rows -> padded to 64 -> one chunk
        x2 = torch.randn(5, 40, 64)                                      # 200 rows -> 224 -> 4 chunks of 64 (last one 32)
        y2 = layer(x2)
        ref = self.lin(x2).detach()
        self.assertLess(float((y2 - ref).norm() / ref.norm()), 0.03)

    def test_rows_not_multiple_of_32_are_padded(self):
        layer = DynamicInt8Linear(self.lin)
        y = layer(self.x[0, :19])
        self.assertEqual(y.shape, (19, 48))
        self.assertEqual(layer.int_mm_calls, 1)

    @unittest.skipUnless(torch.cuda.is_available(), "needs a GPU")
    def test_int_mm_on_the_gpu_matches_the_emulation(self):
        a = torch.randint(-127, 127, (64, 64), dtype=torch.int8, device="cuda")
        w = torch.randint(-127, 127, (64, 48), dtype=torch.int8, device="cuda")
        self.assertTrue(torch.equal(DynamicInt8Linear.int_matmul(a, w).cpu(), DynamicInt8Linear.int_matmul(a.cpu(), w.cpu())))


class QuantizerTest(unittest.TestCase):
    def linears(self, m):
        return {n for n, x in m.named_modules() if isinstance(x, nn.Linear)}

    def test_original_is_untouched(self):
        before = self.linears(MODEL)
        WeightOnlyInt8("all").quantize(MODEL, torch.float32)
        self.assertEqual(self.linears(MODEL), before)

    def test_scopes(self):
        body = WeightOnlyInt8("body").quantize(MODEL, torch.float32)
        full = WeightOnlyInt8("all").quantize(MODEL, torch.float32)
        self.assertIsInstance(body.gesture, nn.Linear)                       # a head stays float
        self.assertIsInstance(full.gesture, Int8Linear)
        self.assertIsInstance(body.trunk.blocks[0].qkv, Int8Linear)
        self.assertIsInstance(body.decoder.layers[0]["ff"][0], Int8Linear)    # nested in a ModuleDict / Sequential
        for m in (body, full):
            self.assertIsInstance(m.embed.num.l1, nn.Linear)                 # never quantised
            self.assertIsInstance(m.embed.prop.count, nn.Linear)

    def test_scope_rejects_unknown(self):
        with self.assertRaises(ValueError):
            Scope("trunk")

    def test_smaller(self):
        ref = model_bytes(Fp16Reference().quantize(MODEL, torch.float32))
        self.assertLess(model_bytes(WeightOnlyInt8("all").quantize(MODEL, torch.float32)), ref * 0.8)

    def test_state_dict_roundtrip_keeps_int8(self):
        m = WeightOnlyInt8("body").quantize(MODEL, torch.float32)
        sd = m.state_dict()
        self.assertEqual(sd["trunk.blocks.0.qkv.qweight"].dtype, torch.int8)

    def test_reference_agrees_with_itself(self):
        p = EV.predict(Fp16Reference().quantize(MODEL, torch.float32))
        a = agreement(EV, p, p)
        self.assertEqual((a["gesture_and_pointers"], a["whole_decision"]), (1.0, 1.0))


class ComparisonTest(unittest.TestCase):
    def test_runs_end_to_end_without_gpu(self):
        res = Comparison(MODEL, EV, [WeightOnlyInt8("body"), DynamicInt8("all")], bench=None).run()
        self.assertIn("fp16", res)
        self.assertIn("int8-w8a8/all", res)
        self.assertIsNone(res["fp16"]["agreement_with_fp16"])
        a = res["int8-weights/body"]["agreement_with_fp16"]
        self.assertTrue(0.0 <= a["gesture_and_pointers"] <= 1.0)
        self.assertGreater(res["int8-w8a8/all"]["counters"]["int8_layers"], res["int8-weights/body"]["counters"]["int8_layers"])
        wide = Comparison(MODEL, EV, [WeightOnlyInt8("body")], bench=None, wide=EV).run()
        self.assertEqual(wide["int8-weights/body"]["agreement_wide"]["decisions"], 24)
        text = markdown(res, {"size": "tiny", "params_M": 0.0, "batches": [32]})
        self.assertIn("int8-w8a8/all", text)


if __name__ == "__main__":
    unittest.main()
