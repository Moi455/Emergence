"""quantize.py - int8 versions of the student, and the report that compares them with float16.

    cd ai && python3 -m student2.quantize --ckpt runs/a1/last.pt --data runs/snap.jsonl --out report.json

A `Quantizer` turns a model into another model (a deep copy: the original is untouched). Each one replaces the
`nn.Linear` layers a `Scope` lets through by a module of its own; the masks, the embeddings, the norms and every layer
the scope keeps stay in float16. Methods:

  Fp16Reference      the float16 model (weights stored in half). What the other methods are compared with.
  WeightOnlyInt8     int8 weights, one scale per output channel, DEQUANTISED at run time (int8 x scale -> float16 ->
                     the usual matmul). Saves memory and bandwidth, not arithmetic.
  DynamicInt8        W8A8: int8 weights per output channel and int8 activations quantised per row (absmax) at run time,
                     the product done by `torch._int_mm` on the int8 tensor cores (works on Turing, sm_75: measured).
                     `torch._int_mm` wants M > 16 rows (a multiple of 32 and < 65536, measured: padded and cut in chunks) and K, N multiples of 8; a layer or a call that does not fit
                     takes the weight-only path (counted in `int_mm_calls` / `fallback_calls`).
                     `torch.ao.quantization.quantize_dynamic` is NOT used: it is a CPU (fbgemm) path, there is no
                     CUDA kernel behind it.

Which layers (`Scope`): "all" every layer that can be; "body" all but the layers whose output IS a logit or a pointer
score (gesture, manner, condition, writes, number heads, the decoder's symbol / arity / count heads, the pointer
queries and keys), which stay float16. Two layers are never quantised whatever the scope: `embed.num.l1` and
`embed.prop.count`, whose `.weight.dtype` the model reads (and whose input is raw numbers).
The report measures what each choice costs; nothing here is decided by guess.
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from abc import ABC, abstractmethod
from pathlib import Path

import torch
import torch.nn as nn
import torch.nn.functional as F

from .evaluate import Evaluator, Predictions, flatten, load_model
from .model import StudentModel
from .runtime import Runtime

# ----------------------------------------------------------------------------------------------- which layers
NEVER = ("embed.num.l1", "embed.prop.count")                      # the model reads their .weight.dtype
LOGIT_LAYERS = re.compile(r"^(gesture|manner|cond|cond_num|cond_word|n_writes|w_var|w_num|w_enum|w_qty|ref_q|cond_q|w_q|w_val_q"
                          r"|ref_ptr\.key|cond_ptr\.key|w_ptr\.key|w_val_ptr\.key"
                          r"|decoder\.(to_sym|arity_head|count_head|slot_q|slot_key))$")


class Scope:
    """Which Linear layers a quantiser may touch."""
    NAMES = ("all", "body")

    def __init__(self, name: str = "body"):
        if name not in self.NAMES:
            raise ValueError(f"scope is one of {self.NAMES}")
        self.name = name

    def allows(self, path: str) -> bool:
        if path in NEVER:
            return False
        return self.name == "all" or not LOGIT_LAYERS.match(path)


# ----------------------------------------------------------------------------------------------- int8 layers
def quantize_weight(w: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
    """w [out, in] -> (int8 [out, in], float16 scale [out]) : symmetric, one scale per output channel."""
    w = w.detach().float()
    scale = (w.abs().amax(1) / 127.0).clamp(min=1e-8)
    q = torch.round(w / scale[:, None]).clamp(-127, 127).to(torch.int8)
    return q, scale


class Int8Linear(nn.Module):
    """Weight-only int8, per-channel. The weight is dequantised on every call (a float16 temporary)."""

    def __init__(self, lin: nn.Linear):
        super().__init__()
        q, scale = quantize_weight(lin.weight)
        dt = lin.weight.dtype
        self.in_features, self.out_features = lin.in_features, lin.out_features
        self.register_buffer("qweight", q)
        self.register_buffer("scale", scale.to(dt))
        self.register_buffer("bias", None if lin.bias is None else lin.bias.detach().to(dt))

    def dequantised(self) -> torch.Tensor:
        return self.qweight.to(self.scale.dtype) * self.scale[:, None]

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return F.linear(x.to(self.scale.dtype), self.dequantised(), self.bias)


class DynamicInt8Linear(Int8Linear):
    """W8A8: activations quantised per row at run time, int8 x int8 -> int32 on the tensor cores, rescaled by
    (row scale x channel scale). Falls back to the weight-only path when `torch._int_mm` cannot take the shape."""

    MIN_ROWS = 16                      # torch._int_mm: M > 16 ...
    CHUNK_ROWS = 32768                 # ... and fewer than 65536 (measured: 65536 rows fail with CUBLAS_STATUS_NOT_SUPPORTED)
    ROW_MULTIPLE = 32                  # ... and, measured on this Turing GPU, a multiple of 32 (24, 40, 48, 72, 1000 fail): rows are padded

    def __init__(self, lin: nn.Linear):
        super().__init__(lin)
        self.fits = self.in_features % 8 == 0 and self.out_features % 8 == 0
        self.int_mm_calls = 0
        self.fallback_calls = 0

    @staticmethod
    def int_matmul(a: torch.Tensor, w_t: torch.Tensor) -> torch.Tensor:
        if a.is_cuda:
            return torch._int_mm(a, w_t)
        return (a.float() @ w_t.float()).round().to(torch.int32)               # exact below 2^24: a test path, not a speed path

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = x.to(self.scale.dtype)
        lead, M = x.shape[:-1], x.numel() // self.in_features
        if not self.fits or M <= self.MIN_ROWS:
            self.fallback_calls += 1
            return F.linear(x, self.dequantised(), self.bias)
        self.int_mm_calls += 1
        flat = x.reshape(M, self.in_features)
        a_scale = flat.abs().amax(1, keepdim=True).clamp(min=1e-5) / 127.0          # [M, 1], in the activation dtype
        a = torch.round(flat / a_scale).clamp_(-127, 127).to(torch.int8)            # |x / scale| <= 127: exact in float16
        pad = (-M) % self.ROW_MULTIPLE
        if pad:
            a = F.pad(a, (0, 0, 0, pad))
        w_t = self.qweight.t()                                          # a view: no second copy of the weight
        parts = [self.int_matmul(a[i:i + self.CHUNK_ROWS], w_t) for i in range(0, a.shape[0], self.CHUNK_ROWS)]
        acc = (parts[0] if len(parts) == 1 else torch.cat(parts))[:M]
        out = acc.float().mul_(a_scale.float()).mul_(self.scale.float())
        if self.bias is not None:
            out.add_(self.bias.float())
        return out.to(self.scale.dtype).reshape(*lead, self.out_features)


# ----------------------------------------------------------------------------------------------- quantisers
class Quantizer(ABC):
    """model -> a quantised COPY of the model. A subclass says which module replaces a Linear (`wrap`)."""

    name: str = "?"

    def __init__(self, scope: str | Scope = "body"):
        self.scope = scope if isinstance(scope, Scope) else Scope(scope)

    @property
    def label(self) -> str:
        return f"{self.name}/{self.scope.name}"

    @abstractmethod
    def wrap(self, lin: nn.Linear) -> nn.Module | None:
        """The replacement of a Linear, or None to keep it."""

    def quantize(self, model: StudentModel, dtype: torch.dtype = torch.float16) -> StudentModel:
        """`dtype` is what the layers kept are stored in: float16 on the GPU, float32 only for tests on the CPU."""
        out = copy.deepcopy(model).cpu().eval().to(dtype)
        todo = [(p, m) for p, m in out.named_modules() if isinstance(m, nn.Linear) and self.scope.allows(p)]
        for path, lin in todo:
            new = self.wrap(lin)
            if new is None:
                continue
            parent = out
            *head, leaf = path.split(".")
            for part in head:
                parent = parent[int(part)] if part.isdigit() and isinstance(parent, (nn.ModuleList, nn.Sequential)) else getattr(parent, part)
            if leaf.isdigit() and isinstance(parent, (nn.ModuleList, nn.Sequential)):
                parent[int(leaf)] = new
            else:
                setattr(parent, leaf, new)
        return out

    def counters(self, model: nn.Module) -> dict:
        mods = [m for m in model.modules() if isinstance(m, Int8Linear)]
        return {"int8_layers": len(mods), "int_mm_calls": sum(getattr(m, "int_mm_calls", 0) for m in mods),
                "fallback_calls": sum(getattr(m, "fallback_calls", 0) for m in mods)}


class Fp16Reference(Quantizer):
    name = "fp16"

    def wrap(self, lin):
        return None

    @property
    def label(self) -> str:
        return "fp16"


class WeightOnlyInt8(Quantizer):
    name = "int8-weights"

    def wrap(self, lin):
        return Int8Linear(lin)


class DynamicInt8(Quantizer):
    name = "int8-w8a8"

    def wrap(self, lin):
        return DynamicInt8Linear(lin)


# ----------------------------------------------------------------------------------------------- measures
def model_bytes(model: nn.Module) -> int:
    """Bytes of what the model stores: parameters and persistent buffers (the masks recomputed at load are not counted)."""
    persistent = set(model.state_dict().keys())
    total = 0
    for name, t in list(model.named_parameters()) + list(model.named_buffers()):
        if name in persistent:
            total += t.numel() * t.element_size()
    return total


def agreement(ev: Evaluator, ref: Predictions, other: Predictions) -> dict:
    """Same decision as the reference: gesture AND pointers (the ones the gesture has), and the whole comparable decision."""
    a, b = ev.keys(ref), ev.keys(other)
    ca, cb = ev.comparables(ref), ev.comparables(other)
    n = max(1, len(a))
    return {"gesture_and_pointers": sum(x == y for x, y in zip(a, b)) / n,
            "gesture": sum(x[0] == y[0] for x, y in zip(a, b)) / n,
            "whole_decision": sum(x == y for x, y in zip(ca, cb)) / n, "decisions": len(a)}


class Bench:
    """Latency and GPU memory of one model, the way bench.py does it: float16 autocast, GPU warmed, median of 3 series."""

    def __init__(self, ev: Evaluator, batches=(32, 128), iters: int = 30):
        self.ev, self.batches, self.iters = ev, batches, iters
        col = ev.ds.collator(False)
        self.inputs = {B: col([ev.ds[i % len(ev.ds)] for i in range(B)]) for B in batches}

    def run(self, model: StudentModel) -> dict:
        from .bench import graphed, timed, warm_gpu
        out = {}
        for B, host in self.inputs.items():
            batch = host.to("cuda")
            torch.cuda.synchronize()
            torch.cuda.empty_cache()
            before = torch.cuda.memory_allocated()
            m = model.to("cuda").eval()
            torch.cuda.synchronize()
            weights = torch.cuda.memory_allocated() - before
            torch.cuda.reset_peak_memory_stats()

            def policy():
                with torch.no_grad(), torch.autocast("cuda", dtype=torch.float16):
                    return m(batch, teacher=False)

            r = {}
            try:
                o = policy()
                torch.cuda.synchronize()
                r["peak_inference_MiB"] = round((torch.cuda.max_memory_allocated() - before) / 2**20, 1)
                r["weights_MiB"] = round(weights / 2**20, 2)
                warm_gpu(1.0)
                r["policy_eager_ms"] = round(timed(policy, self.iters) * 1e3, 2)
                try:
                    r["policy_graph_ms"] = round(timed(graphed(policy), self.iters) * 1e3, 2)
                    r["policy_graph_decisions_per_s"] = round(B / (r["policy_graph_ms"] / 1e3))
                except Exception as e:                                       # noqa: BLE001  (reported, not hidden)
                    r["policy_graph_error"] = f"{type(e).__name__}: {str(e)[:80]}"
                r["policy_eager_decisions_per_s"] = round(B / (r["policy_eager_ms"] / 1e3))
                del o
            except Exception as e:                                           # noqa: BLE001
                r["error"] = f"{type(e).__name__}: {str(e)[:120]}"
            out[f"batch{B}"] = r
            m.cpu()
            del batch
            torch.cuda.empty_cache()
        return out


class Comparison:
    """fp16 vs each quantiser: size, GPU memory, speed, every metric of evaluate.py and the agreement of decisions."""

    def __init__(self, model: StudentModel, ev: Evaluator, quantizers: list[Quantizer], bench: Bench | None = None,
                 wide: Evaluator | None = None):
        """`wide`: an evaluator over MORE decisions (the whole file, training split included) used only for the agreement
        of decisions with fp16, which needs no label: a tighter figure than the validation split can give."""
        self.model, self.ev, self.quantizers, self.bench, self.wide = model, ev, quantizers, bench, wide
        self.dtype = torch.float16 if ev.device == "cuda" else torch.float32

    def run(self) -> dict:
        ref_q = Fp16Reference()
        ref_model = ref_q.quantize(self.model, self.dtype)
        ref_preds, ref_rep = self.ev.run(ref_model)
        ref_model.cpu()
        ref_wide = self.wide.predict(ref_model) if self.wide else None
        ref_model.cpu()
        base = flatten(ref_rep)
        results = {"fp16": self.entry(ref_q, ref_model, ref_rep, None, base)}
        if self.bench:
            results["fp16"]["bench"] = self.bench.run(ref_model)
        for q in self.quantizers:
            qm = q.quantize(self.model, self.dtype)
            preds, rep = self.ev.run(qm)
            qm.cpu()
            e = self.entry(q, qm, rep, agreement(self.ev, ref_preds, preds), base)
            e["counters"] = q.counters(qm)
            if self.wide:
                e["agreement_wide"] = agreement(self.wide, ref_wide, self.wide.predict(qm))
                qm.cpu()
            if self.bench:
                e["bench"] = self.bench.run(qm)
            results[q.label] = e
        results["_fp16_decision_agreement_with_fp32_autocast"] = None
        fp32_preds = self.ev.predict(copy.deepcopy(self.model))
        results["_fp16_decision_agreement_with_fp32_autocast"] = agreement(self.ev, fp32_preds, ref_preds)
        return results

    def entry(self, q: Quantizer, model: StudentModel, rep: dict, agree: dict | None, base: dict) -> dict:
        flat = flatten(rep)
        delta = {k: (None if s["acc"] is None or base[k]["acc"] is None else round(s["acc"] - base[k]["acc"], 4))
                 for k, s in flat.items() if k in base}
        return {"label": q.label, "size_MiB": round(model_bytes(model) / 2**20, 2), "report": rep, "delta_vs_fp16": delta,
                "agreement_with_fp16": agree, "decision_valid": rep["validity"]["decision_valid"]}


def markdown(results: dict, meta: dict) -> str:
    """The comparison as tables (the numbers of the JSON, nothing else)."""
    labels = [k for k in results if not k.startswith("_")]
    out = [f"Modèle `{meta['size']}` ({meta['params_M']} M paramètres), {results['fp16']['report']['decisions']} décisions de validation.\n"]
    out.append("| variante | taille (Mo) | " + " | ".join(f"poids GPU / pic lot {b} (Mo)" for b in meta["batches"]) + " | "
               + " | ".join(f"politique lot {b} eager / graphe (ms)" for b in meta["batches"]) + " | accord geste+pointeurs | accord décision entière | accord geste+pointeurs, toutes les lignes |")
    out.append("|" + "---|" * (5 + 2 * len(meta["batches"])))
    for k in labels:
        e = results[k]
        cells = [k, f"{e['size_MiB']}"]
        for key in ("w_peak", "ms"):
            for b in meta["batches"]:
                r = (e.get("bench") or {}).get(f"batch{b}", {})
                if "error" in r:
                    cells.append("erreur : " + r["error"])
                elif key == "w_peak":
                    cells.append(f"{r.get('weights_MiB', '?')} / {r.get('peak_inference_MiB', '?')}")
                else:
                    cells.append(f"{r.get('policy_eager_ms', '?')} / {r.get('policy_graph_ms', r.get('policy_graph_error', '?'))}")
        a = e["agreement_with_fp16"]
        cells += ["(réf.)", "(réf.)"] if a is None else [f"{100 * a['gesture_and_pointers']:.1f} %", f"{100 * a['whole_decision']:.1f} %"]
        w = e.get("agreement_wide")
        cells.append("(réf.)" if k == "fp16" else "non mesuré" if w is None else f"{100 * w['gesture_and_pointers']:.1f} % ({w['decisions']})")
        out.append("| " + " | ".join(cells) + " |")
    shown = ["gesture.top1", "gesture.top3", "pointers.per_pointer", "pointers.all_pointers_of_decision", "manner.per_value",
             "stop_condition.condition", "writes.n_writes", "writes.target_and_variable", "writes.write_exact",
             "writes.write_set_exact", "sequences.speech_exact", "sequences.proposition_exact"]
    flat0 = flatten(results["fp16"]["report"])
    out.append("\nExactitude contre le professeur (points de pourcentage de variation par rapport à fp16 entre parenthèses) :\n")
    out.append("| métrique (n) | " + " | ".join(labels) + " |")
    out.append("|" + "---|" * (len(labels) + 1))
    for m in shown:
        if m not in flat0 or flat0[m]["n"] == 0:
            continue
        cells = [f"{m} ({flat0[m]['n']})"]
        for k in labels:
            s = flatten(results[k]["report"])[m]
            d = results[k]["delta_vs_fp16"].get(m)
            cells.append("n/a" if s["acc"] is None else f"{100 * s['acc']:.1f} %" + ("" if k == "fp16" or d is None else f" ({100 * d:+.1f})"))
        out.append("| " + " | ".join(cells) + " |")
    cells = ["décision valide pour le validateur (gouverneur)"] + [f"{100 * results[k]['decision_valid']:.1f} %" for k in labels]
    out.append("| " + " | ".join(cells) + " |")
    return "\n".join(out)


def main(argv=None) -> int:
    from .data import LabelDataset
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--ckpt", type=Path, required=True)
    ap.add_argument("--data", type=Path, nargs="+", required=True)
    ap.add_argument("--cache", type=Path, default=None)
    ap.add_argument("--batch", type=int, nargs="+", default=[32, 128], help="batch sizes of the speed / memory measure")
    ap.add_argument("--eval-batch", type=int, default=32)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--iters", type=int, default=30)
    ap.add_argument("--scopes", nargs="+", default=["body", "all"], choices=Scope.NAMES)
    ap.add_argument("--no-bench", action="store_true")
    ap.add_argument("--wide", action="store_true", help="also measure the agreement with fp16 on ALL lines (labels not needed)")
    ap.add_argument("--out", type=Path, required=True, help="JSON results (a .md with the tables is written beside it)")
    a = ap.parse_args(argv)
    if not torch.cuda.is_available():
        print("no GPU: the int8 kernels and the speed measure need one", file=sys.stderr)
        return 2
    rt = Runtime.build()
    ds = LabelDataset(a.data, split="val", runtime=rt, cache_dir=a.cache, keep_context=True)
    model = load_model(a.ckpt, rt, "cpu")
    ev = Evaluator(rt, ds, a.eval_batch, a.limit, "cuda")
    qs = [c(s) for s in a.scopes for c in (WeightOnlyInt8, DynamicInt8)]
    bench = None if a.no_bench else Bench(ev, tuple(a.batch), a.iters)
    wide = None
    if a.wide:
        wide = Evaluator(rt, LabelDataset(a.data, split=None, runtime=rt, cache_dir=a.cache, keep_context=True), a.eval_batch, a.limit, "cuda")
    results = Comparison(model, ev, qs, bench, wide).run()
    meta = {"size": model.cfg.name, "params_M": round(model.n_params() / 1e6, 2), "batches": a.batch, "checkpoint": str(a.ckpt),
            "gpu": torch.cuda.get_device_name(0), "torch": torch.__version__}
    a.out.write_text(json.dumps({"meta": meta, "results": results}, indent=1), encoding="utf-8")
    a.out.with_suffix(".md").write_text(markdown(results, meta), encoding="utf-8")
    print(markdown(results, meta))
    return 0


if __name__ == "__main__":
    sys.exit(main())
