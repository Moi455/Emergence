"""bench.py - decisions per second of the student, in training and in inference, and GPU memory.

    cd ai && python3 -m student2.bench --data smoke.jsonl --smoke-test --sizes small base --batch 32 128 --end-to-end

The batches are real tok-2 batches of whatever file is given (use a smoke file for a pure speed test; the contexts
have the real lengths of the sampler). Timings: float16 autocast, GPU warmed first, median of 3 rounds, the same batch
each time except in the end-to-end figure. Reported:
  train_*         one optimisation step (forward, loss, backward, AdamW), eager
  policy_*        the policy heads (`forward(teacher=False)`), eager and replayed from a CUDA graph (static shapes)
  speech_*        the decoder writing 8 sentences of 21 steps with a static KV cache, eager and from a CUDA graph
  end_to_end_*    the whole loop with the cache, the loader (workers, pinned memory) and the optimisation step
`--fixed` pads to the buckets (64 or 128 records, 8 or 40 ghost tokens) the way the game would run.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import torch

from .data import LabelDataset
from .model import SIZES, StudentModel
from .runtime import Runtime
from .train import Trainer


def warm_gpu(seconds: float = 3.0) -> None:
    """The laptop GPU lowers its clock between bursts: bring it to its working clock before timing."""
    w = torch.randn(4096, 4096, device="cuda", dtype=torch.float16)
    t0 = time.time()
    while time.time() - t0 < seconds:
        w @ w
    torch.cuda.synchronize()


def timed(fn, n: int, warm: int = 5, rounds: int = 3) -> float:
    """Median over `rounds` of the mean time of `n` calls (seconds)."""
    for _ in range(warm):
        fn()
    means = []
    for _ in range(rounds):
        torch.cuda.synchronize()
        t0 = time.perf_counter()
        for _ in range(n):
            fn()
        torch.cuda.synchronize()
        means.append((time.perf_counter() - t0) / n)
    return sorted(means)[len(means) // 2]


def graphed(fn):
    """Capture fn (static inputs) in a CUDA graph -> a callable that replays it."""
    side = torch.cuda.Stream()
    side.wait_stream(torch.cuda.current_stream())
    with torch.cuda.stream(side):
        for _ in range(3):
            fn()
    torch.cuda.current_stream().wait_stream(side)
    g = torch.cuda.CUDAGraph()
    with torch.cuda.graph(g):
        fn()
    return g.replay


def measure(rt: Runtime, ds: LabelDataset, size: str, B: int, n: int, fixed: bool, end_to_end: bool, workers: int) -> dict:
    col = ds.collator(fixed)
    batch = col([ds[i % len(ds)] for i in range(B)]).to("cuda")
    torch.cuda.reset_peak_memory_stats()
    model = StudentModel(SIZES[size], rt.space)
    trainer = Trainer(model, "cuda", lr=1e-4, total_steps=100_000, warmup=10)
    train_s = timed(lambda: trainer.train_step(batch), n)
    peak_train = torch.cuda.max_memory_allocated() / 2**20
    model.eval()
    torch.cuda.reset_peak_memory_stats()

    def policy():
        with torch.no_grad(), torch.autocast("cuda", dtype=torch.float16):
            return model(batch, teacher=False)

    out = policy()
    pol_s, pol_g = timed(policy, n), timed(graphed(policy), n)
    C = 8
    init = torch.randn(C, model.cfg.d, device="cuda")
    enc, ok, pk = out["enc"][:C].clone(), out["ok"][:C].clone(), batch.slot_ptrkind[:C]

    def speech():
        with torch.no_grad(), torch.autocast("cuda", dtype=torch.float16):
            return model.decoder.generate(init, enc, ok, pk)

    sp_s, sp_g = timed(speech, max(3, n // 5), warm=2), timed(graphed(speech), n)
    peak_inf = torch.cuda.max_memory_allocated() / 2**20
    r = {"size": size, "params_M": round(model.n_params() / 1e6, 2), "batch": B, "records_padded": batch.n, "ghost_tokens": batch.ghosts,
         "fixed_shapes": fixed, "train_ms": round(train_s * 1e3, 1), "train_decisions_per_s": round(B / train_s),
         "policy_eager_ms": round(pol_s * 1e3, 2), "policy_graph_ms": round(pol_g * 1e3, 2),
         "policy_graph_decisions_per_s": round(B / pol_g), "speech8_eager_ms": round(sp_s * 1e3, 1),
         "speech8_graph_ms": round(sp_g * 1e3, 2), "peak_train_MiB": round(peak_train), "peak_inference_MiB": round(peak_inf)}
    if end_to_end:
        model.train()
        loader = ds.loader(B, shuffle=True, num_workers=workers, seed=1, drop_last=True, fixed=fixed)
        steps, t0 = 0, None
        for i, b in enumerate(loader):
            if i == 5:
                torch.cuda.synchronize()
                t0 = time.perf_counter()
            trainer.train_step(b)
            steps += 1
            if i >= 5 + n:
                break
        torch.cuda.synchronize()
        e2e = (steps - 5) * B / (time.perf_counter() - t0)
        r.update(end_to_end_decisions_per_s=round(e2e), workers=workers)
    return r


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--data", type=Path, required=True)
    ap.add_argument("--smoke-test", action="store_true", help="the data is the random smoke set (a speed test)")
    ap.add_argument("--cache", type=Path, default=None)
    ap.add_argument("--sizes", nargs="+", default=["small", "base"])
    ap.add_argument("--batch", type=int, nargs="+", default=[32])
    ap.add_argument("--iters", type=int, default=30)
    ap.add_argument("--fixed", action="store_true")
    ap.add_argument("--end-to-end", action="store_true")
    ap.add_argument("--workers", type=int, default=3)
    a = ap.parse_args(argv)
    if not torch.cuda.is_available():
        print("no GPU: nothing to measure", file=sys.stderr)
        return 2
    rt = Runtime.build()
    ds = LabelDataset([a.data], runtime=rt, allow_smoke=a.smoke_test, cache_dir=a.cache)
    print(json.dumps({"gpu": torch.cuda.get_device_name(0), "torch": torch.__version__, "examples": len(ds)}))
    warm_gpu()
    for size in a.sizes:
        for B in a.batch:
            warm_gpu(1.0)
            print(json.dumps(measure(rt, ds, size, B, a.iters, a.fixed, a.end_to_end, a.workers)), flush=True)
            torch.cuda.empty_cache()
    return 0


if __name__ == "__main__":
    sys.exit(main())
