"""bench_policy.py - latency and throughput of the fast policy on this GPU (docs/07_conception_ia.md, section 2).

  python3 ai/research/bench_policy.py                       # full sweep (~2-4 min)
  python3 ai/research/bench_policy.py --configs small --seqs 128 --batches 16,200 --quick

For each config x sequence length x batch: eager latency, CUDA-graph latency (static shapes), CUDA-graph end-to-end
(pinned host -> GPU copy of the inputs + forward + copy of the outputs back), peak memory. Also an INT8 vs FP16
matmul micro-benchmark on the policy's GEMM shapes (torch._int_mm, Turing INT8 tensor cores).
Results: ai/research/results/policy.json
"""
import argparse
import time

import torch

from common import CONFIGS, CudaTimer, GraphRunner, InputFactory, PolicyNet, process_gpu_mib, save


class PolicyBenchmark:
    def __init__(self, dtype, quick):
        self.dtype, self.quick = dtype, quick
        self.rows = []

    def run_one(self, cfg_name, T, B):
        cfg = CONFIGS[cfg_name]
        model = PolicyNet(cfg, T).cuda().to(self.dtype).eval()
        inputs = InputFactory(T, "cuda", self.dtype, seed=B).make(B)
        host = {k: v.cpu().pin_memory() for k, v in inputs.items()}
        torch.cuda.reset_peak_memory_stats()
        iters = 20 if self.quick else 50
        with torch.inference_mode():
            eager = CudaTimer.measure(lambda: model(**inputs), iters=iters)
            runner = GraphRunner(model, inputs)
            graph = CudaTimer.measure(runner.replay, iters=iters)

            def end_to_end():
                runner.load(host)
                out = runner.replay()
                return {k: v.to("cpu", non_blocking=True) for k, v in out.items()}
            e2e = CudaTimer.measure(end_to_end, iters=iters)
        row = {
            "config": cfg_name, "dtype": str(self.dtype).split(".")[-1], "T": T, "B": B,
            "params_M": model.n_params() / 1e6, "compute_params_M": model.n_params(compute_only=True) / 1e6,
            "gflop_per_decision": model.flops_per_decision() / 1e9,
            "eager_ms": eager["median_ms"], "graph_ms": graph["median_ms"], "graph_p95_ms": graph["p95_ms"],
            "e2e_ms": e2e["median_ms"], "decisions_per_s": B / (graph["median_ms"] / 1e3),
            "peak_alloc_MiB": torch.cuda.max_memory_allocated() / 2**20,
        }
        row["achieved_tflops"] = row["gflop_per_decision"] * B / graph["median_ms"]  # GFLOP/ms == TFLOP/s
        self.rows.append(row)
        print(f"{cfg_name:>6} {row['dtype']:>8} T={T:<4} B={B:<4} params={row['params_M']:6.2f}M "
              f"{row['gflop_per_decision']:6.2f} GFLOP/dec | eager {row['eager_ms']:7.3f} ms | graph "
              f"{row['graph_ms']:7.3f} ms (p95 {row['graph_p95_ms']:.3f}) | e2e {row['e2e_ms']:7.3f} ms | "
              f"{row['decisions_per_s']:9.0f} dec/s | {row['achieved_tflops']:5.2f} TFLOP/s | "
              f"peak {row['peak_alloc_MiB']:6.0f} MiB", flush=True)
        del runner, model
        torch.cuda.empty_cache()


class Int8MatmulBenchmark:
    """FP16 matmul vs INT8 (int32 accumulate) on the GEMMs of one encoder layer."""

    def run(self, d, ff, M):
        rows = []
        for K, N in ((d, 3 * d), (d, ff), (ff, d)):
            a16 = torch.randn(M, K, device="cuda", dtype=torch.float16)
            b16 = torch.randn(K, N, device="cuda", dtype=torch.float16)
            a8 = torch.randint(-127, 127, (M, K), device="cuda", dtype=torch.int8)
            b8 = torch.randint(-127, 127, (K, N), device="cuda", dtype=torch.int8)
            t16 = CudaTimer.measure(lambda: a16 @ b16, iters=100)["median_ms"]
            t8 = CudaTimer.measure(lambda: torch._int_mm(a8, b8), iters=100)["median_ms"]
            fl = 2 * M * K * N
            rows.append({"M": M, "K": K, "N": N, "fp16_ms": t16, "int8_ms": t8,
                         "fp16_tflops": fl / t16 / 1e9, "int8_tops": fl / t8 / 1e9})
            print(f"  GEMM M={M:<6} K={K:<5} N={N:<5} fp16 {t16:.4f} ms ({fl / t16 / 1e9:5.1f} TFLOP/s) | "
                  f"int8 {t8:.4f} ms ({fl / t8 / 1e9:5.1f} TOP/s)", flush=True)
        return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--configs", default="xs,small,base,large,xl")
    ap.add_argument("--seqs", default="96,128")
    ap.add_argument("--batches", default="1,16,64,200,500")
    ap.add_argument("--fp32", default="small", help="configs also measured in FP32 (comparison)")
    ap.add_argument("--quick", action="store_true")
    a = ap.parse_args()
    torch.backends.cuda.matmul.allow_tf32 = False
    warm = torch.randn(4096, 4096, device="cuda", dtype=torch.float16)   # bring the laptop GPU to full clocks
    t0 = time.time()
    while time.time() - t0 < 3:
        warm @ warm
    torch.cuda.synchronize()
    del warm
    seqs = [int(s) for s in a.seqs.split(",")]
    batches = [int(b) for b in a.batches.split(",")]
    bench = PolicyBenchmark(torch.float16, a.quick)
    for c in a.configs.split(","):
        for T in seqs:
            for B in batches:
                bench.run_one(c, T, B)
    rows = bench.rows
    if a.fp32:
        b32 = PolicyBenchmark(torch.float32, a.quick)
        for c in a.fp32.split(","):
            for B in batches:
                b32.run_one(c, max(seqs), B)
        rows += b32.rows
    print("INT8 vs FP16 GEMM, config small (d=256, ff=1024):")
    gemm = []
    for B in (16, 200):
        gemm += Int8MatmulBenchmark().run(256, 1024, B * 128)
    print("process GPU memory (driver view, CUDA context included):", process_gpu_mib(), "MiB")
    path = save("policy.json", {"rows": rows, "int8_gemm": gemm, "process_gpu_MiB": process_gpu_mib()})
    print("saved", path)


if __name__ == "__main__":
    main()
