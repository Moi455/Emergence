"""bench.py - decisions per second of the student, in training and in inference, and GPU memory.

    cd ai && python3 -m student2.bench --data smoke.jsonl --sizes small base --batch 32

The batches are real tok-2 batches of whatever file is given (use a smoke file for a pure speed test; the contexts
have the real lengths of the sampler). Timings: float16 autocast, GPU warmed first, median of 3 rounds, the same batch each
time (no data loading in the figure). Inference = the policy heads (`forward(teacher=False)`), what the game runs at
200 decisions/s; `predict` adds the inner-language decoder written token by token WITHOUT a KV cache (a slow reference
loop, not the optimised decoder of docs/09). Nothing is compiled and no CUDA graph is used.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import torch

from .data import Collator, LabelDataset
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


def measure(rt: Runtime, ds: LabelDataset, size: str, B: int, n: int) -> dict:
    col = Collator(rt.space.gestures.n, rt.space.self_type)
    batch = col([ds[i % len(ds)] for i in range(B)]).to("cuda")
    torch.cuda.reset_peak_memory_stats()
    model = StudentModel(SIZES[size], rt.space)
    trainer = Trainer(model, "cuda", lr=1e-4, total_steps=10_000, warmup=10)
    train_s = timed(lambda: trainer.train_step(batch), n)
    peak_train = torch.cuda.max_memory_allocated() / 2**20
    model.eval()
    torch.cuda.reset_peak_memory_stats()

    def policy():
        with torch.no_grad(), torch.autocast("cuda", dtype=torch.float16):
            model(batch, teacher=False)

    with torch.no_grad(), torch.autocast("cuda", dtype=torch.float16):
        enc, ok = model.encode(batch)[1:]

    def speech(k):
        init = torch.randn(k, model.cfg.d, device="cuda")
        idx = torch.arange(k, device="cuda") % B

        def run():
            with torch.no_grad(), torch.autocast("cuda", dtype=torch.float16):
                model.decoder.generate(init, enc[idx], ok[idx])
        return run

    pol_s, sp8_s, sp32_s = timed(policy, n), timed(speech(8), max(3, n // 5), warm=2), timed(speech(32), max(3, n // 5), warm=2)
    peak_inf = torch.cuda.max_memory_allocated() / 2**20
    return {"size": size, "params_M": round(model.n_params() / 1e6, 2), "batch": B, "tokens_padded": batch.n,
            "ghost_tokens": batch.ghosts, "train_ms_per_step": round(train_s * 1e3, 1),
            "train_decisions_per_s": round(B / train_s), "policy_ms": round(pol_s * 1e3, 2),
            "policy_decisions_per_s": round(B / pol_s), "speech_8_sentences_ms": round(sp8_s * 1e3, 1),
            "speech_32_sentences_ms": round(sp32_s * 1e3, 1), "peak_train_MiB": round(peak_train),
            "peak_inference_MiB": round(peak_inf)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--data", type=Path, required=True)
    ap.add_argument("--sizes", nargs="+", default=["small", "base"])
    ap.add_argument("--batch", type=int, nargs="+", default=[32])
    ap.add_argument("--iters", type=int, default=30)
    a = ap.parse_args(argv)
    if not torch.cuda.is_available():
        print("no GPU: nothing to measure", file=sys.stderr)
        return 2
    rt = Runtime.build()
    ds = LabelDataset([a.data], runtime=rt)
    print(json.dumps({"gpu": torch.cuda.get_device_name(0), "torch": torch.__version__, "examples": len(ds)}))
    warm_gpu()
    for size in a.sizes:
        warm_gpu(1.0)
        for B in a.batch:
            print(json.dumps(measure(rt, ds, size, B, a.iters)), flush=True)
            torch.cuda.empty_cache()
    return 0


if __name__ == "__main__":
    sys.exit(main())
