"""bench_gemm_rate.py - FP16 tensor-core rate of this GPU, with FP32 and with FP16 accumulation (docs/09, section 2).

  python3 ai/research/arch/bench_gemm_rate.py          # ~40 s

Why: the dev machine (Quadro RTX 3000, Turing TU106, 30 SM) and the player target (GeForce RTX 3060 Laptop, Ampere
GA106, 30 SM) have the same SM count, the same 192-bit 14 Gbps bus (336 GB/s) and the same 3 MB L2. They differ in
the tensor cores: per SM and per clock, NVIDIA's whitepapers give Turing 8 x 64 FP16 FMA and Ampere GA10x 4 x 128
dense FP16 FMA, with FP32 accumulation at HALF rate on GeForce parts and at full rate on Quadro/RTX professional
parts. So whether a GEMM accumulates in FP32 (PyTorch default) or FP16 matters for the extrapolation.
This script measures, on this GPU: large and policy-shaped FP16 GEMMs with FP32 accumulation (default) and with
FP16 accumulation (torch.backends.cuda.matmul.allow_fp16_accumulation), and samples the SM clock meanwhile.
Results: ai/research/arch/results/gemm_rate.json
"""
import subprocess
import threading
import time

import torch

from arch_common import CudaTimer, save_result, warm_gpu


class ClockSampler(threading.Thread):
    """Samples the SM clock (MHz) and power (W) with nvidia-smi every 200 ms."""

    def __init__(self):
        super().__init__(daemon=True)
        self.samples, self.stop = [], threading.Event()

    def run(self):
        while not self.stop.is_set():
            try:
                out = subprocess.run(["nvidia-smi", "--query-gpu=clocks.sm,power.draw", "--format=csv,noheader,nounits"],
                                     capture_output=True, text=True, timeout=5).stdout.strip().split(",")
                self.samples.append((float(out[0]), float(out[1])))
            except Exception:
                pass
            time.sleep(0.2)

    def summary(self):
        if not self.samples:
            return {}
        clk = sorted(s[0] for s in self.samples)
        pw = sorted(s[1] for s in self.samples)
        return {"sm_clock_MHz_median": clk[len(clk) // 2], "sm_clock_MHz_min": clk[0], "power_W_median": pw[len(pw) // 2]}


class GemmRate:
    SHAPES = ((4096, 4096, 4096), (16384, 256, 1024), (16384, 1024, 256), (2560, 384, 1536), (25600, 512, 2048))

    def run(self, fp16_acc):
        torch.backends.cuda.matmul.allow_fp16_accumulation = fp16_acc
        rows = []
        for M, K, N in self.SHAPES:
            a = torch.randn(M, K, device="cuda", dtype=torch.float16)
            b = torch.randn(K, N, device="cuda", dtype=torch.float16)
            t = CudaTimer.measure(lambda: a @ b, iters=60, warmup=10)["median_ms"]
            tf = 2 * M * K * N / t / 1e9
            rows.append({"M": M, "K": K, "N": N, "fp16_accumulation": fp16_acc, "ms": t, "tflops": tf})
            print(f"  acc={'fp16' if fp16_acc else 'fp32'} M={M:<6} K={K:<5} N={N:<5} {t:8.4f} ms  {tf:6.1f} TFLOP/s",
                  flush=True)
        torch.backends.cuda.matmul.allow_fp16_accumulation = False
        return rows


def main():
    warm_gpu()
    sampler = ClockSampler()
    sampler.start()
    rows = GemmRate().run(False) + GemmRate().run(True)
    sampler.stop.set()
    sampler.join()
    clocks = sampler.summary()
    props = torch.cuda.get_device_properties(0)
    sm = props.multi_processor_count
    mhz = clocks.get("sm_clock_MHz_median", 0)
    peak_full = sm * 8 * 64 * 2 * mhz * 1e6 / 1e12 if mhz else None     # Turing: 8 TC/SM x 64 FMA x 2 FLOP
    print(f"SMs={sm} clocks={clocks} -> Turing full-rate FP16 peak at that clock = {peak_full:.1f} TFLOP/s")
    print("saved", save_result("gemm_rate.json", {"rows": rows, "clocks": clocks, "sm_count": sm,
                                                   "turing_full_rate_peak_tflops_at_clock": peak_full}))


if __name__ == "__main__":
    main()
