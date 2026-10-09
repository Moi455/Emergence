"""bench_cpu.py - can the fast policy run on the CPU instead (GPU left to rendering, players without NVIDIA)?

  python3 ai/research/bench_cpu.py                # ~2 min

PyTorch CPU, FP32, and dynamic INT8 quantisation of the Linear layers (torch.ao quantize_dynamic), with 2, 4 and
8 threads, batches of 20 and 64 (200 decisions/s = e.g. 10 ticks of 20). Configs xs and small, T = 96 and 128.
Results: ai/research/results/cpu.json
"""
import os
import platform
import statistics
import time

import torch

from common import CONFIGS, InputFactory, PolicyNet, save


class CpuTimer:
    @staticmethod
    def measure(fn, iters=15, warmup=3, budget_s=6.0):
        for _ in range(warmup):
            fn()
        times, t0 = [], time.perf_counter()
        for _ in range(iters):
            s = time.perf_counter()
            fn()
            times.append((time.perf_counter() - s) * 1e3)
            if time.perf_counter() - t0 > budget_s and len(times) >= 3:
                break
        return statistics.median(times)


def cpu_model():
    try:
        with open("/proc/cpuinfo") as f:
            for line in f:
                if line.startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor()


def main():
    rows = []
    for cfg in ("xs", "small"):
        for T in (96, 128):
            base = PolicyNet(CONFIGS[cfg], T).eval()
            q8 = torch.ao.quantization.quantize_dynamic(base, {torch.nn.Linear}, dtype=torch.qint8)
            for threads in (2, 4, 8):
                torch.set_num_threads(threads)
                for B in (20, 64):
                    inp = InputFactory(T, "cpu", torch.float32, seed=B).make(B)
                    with torch.inference_mode():
                        for name, m in (("fp32", base), ("int8_dynamic", q8)):
                            ms = CpuTimer.measure(lambda: m(**inp))
                            row = {"config": cfg, "T": T, "threads": threads, "B": B, "kind": name, "ms": ms,
                                   "decisions_per_s": B / ms * 1e3}
                            rows.append(row)
                            print(f"cpu {cfg:>5} T={T:<4} threads={threads} B={B:<3} {name:>12}: {ms:8.2f} ms "
                                  f"-> {row['decisions_per_s']:7.0f} dec/s", flush=True)
    print("saved", save("cpu.json", {"rows": rows, "cpu": cpu_model(), "logical_cpus": os.cpu_count()}))


if __name__ == "__main__":
    main()
