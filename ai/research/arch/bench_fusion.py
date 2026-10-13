"""bench_fusion.py - where the policy's time goes, and what a fused runtime would gain (docs/09, sections 2 and 6).

  python3 ai/research/arch/bench_fusion.py           # ~5 min (torch.compile autotuning included)

For the stateless policy (small, base) at lots of 8 and 32, CUDA graph, FP16:
  baseline     : PyTorch kernels (cuBLAS + one kernel per elementwise op), as in bench_arch.py
  embed_only   : layers = 0 (embedders + pointer graph + heads): the fixed cost of the real tok-2 interface
  fp16_acc     : baseline with FP16 accumulation in cuBLAS (allow_fp16_accumulation)
  compiled     : torch.compile(mode="max-autotune-no-cudagraphs") then captured in our CUDA graph: Inductor/Triton
                 fuses the elementwise ops; a stand-in for what TensorRT or a hand-fused runtime would get
  T64          : baseline on a 64-token bucket (the situation sampler gives 41 tokens on average, 21 to 60)
  selector48   : the selector's pass A as docs/07 describes it (2 layers, 48 tokens), stateless
Results: ai/research/arch/results/fusion.json
"""
import copy

import torch
import torch._dynamo

from arch_common import (SIZES, Brain, BrainConfig, CudaTimer, GraphRunner, Tok2InputFactory, save_result, truncate,
                         warm_gpu)


class FusionBench:
    def __init__(self, iters=40):
        self.iters, self.rows = iters, []

    def time_graph(self, fn, inputs):
        with torch.inference_mode():
            runner = GraphRunner(lambda **b: fn(b), inputs)
            return CudaTimer.measure(runner.replay, iters=self.iters)["median_ms"]

    def record(self, size, mode, B, ms, params):
        self.rows.append({"size": size, "mode": mode, "B": B, "graph_ms": ms, "params_M": params,
                          "gpu_share_at_200_per_s_lot32": 10 * ms / 1000 if B == 32 else None})
        print(f"{size:>6} {mode:>12} B={B:<3} {ms:7.2f} ms", flush=True)

    def run(self):
        for size in ("small", "base"):
            cfg = BrainConfig(name=size, **SIZES[size])
            torch.manual_seed(0)
            model = Brain(cfg).cuda().half().eval().prepare_inference()
            p = model.n_params() / 1e6
            for B in (8, 32):
                inputs = Tok2InputFactory("cuda", seed=B).make(B)
                self.record(size, "baseline", B, self.time_graph(model, inputs), p)
                self.record(size, "T64", B, self.time_graph(model, truncate(inputs, 64)), p)
                torch.backends.cuda.matmul.allow_fp16_accumulation = True
                self.record(size, "fp16_acc", B, self.time_graph(model, inputs), p)
                torch.backends.cuda.matmul.allow_fp16_accumulation = False
                emb = Brain(BrainConfig(name=size + "-embed", **{**SIZES[size], "layers": 0})).cuda().half().eval()
                emb.prepare_inference()
                self.record(size, "embed_only", B, self.time_graph(emb, inputs), emb.n_params() / 1e6)
                try:
                    torch._dynamo.reset()
                    comp = torch.compile(copy.deepcopy(model), mode="max-autotune-no-cudagraphs", dynamic=False)
                    with torch.inference_mode():
                        for _ in range(3):
                            comp(inputs)
                    self.record(size, "compiled", B, self.time_graph(comp, inputs), p)
                except Exception as e:                                       # report, never hide
                    print(f"  torch.compile failed: {type(e).__name__}: {str(e)[:200]}", flush=True)
                    self.rows.append({"size": size, "mode": "compiled", "B": B, "error": f"{type(e).__name__}"})
        sel = Brain(BrainConfig(name="selector", d=256, layers=2, heads=8, ff=1024)).cuda().half().eval()
        sel.prepare_inference()
        for B in (8, 32):
            inputs = truncate(Tok2InputFactory("cuda", seed=B).make(B), 48)
            self.record("sel", "selector48", B, self.time_graph(sel, inputs), sel.n_params() / 1e6)
        return self.rows


def main():
    torch.backends.cuda.matmul.allow_tf32 = False
    warm_gpu()
    rows = FusionBench().run()
    print("saved", save_result("fusion.json", {"rows": rows}))


if __name__ == "__main__":
    main()
