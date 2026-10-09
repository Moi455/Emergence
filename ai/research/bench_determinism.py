"""bench_determinism.py - "same inputs -> same output" for batched inference (docs/07_conception_ia.md, section 6).

  python3 ai/research/bench_determinism.py        # ~20 s

Question: does the decision of NPC #7 depend on WHO ELSE is in the batch, on its POSITION in the batch, or on the
batch SIZE? (cuBLAS / attention kernels are chosen per shape; a different kernel can change the rounding.)
Checks, FP16 and FP32, config small, T = 128:
  run_to_run      same batch twice                                  -> bitwise equal?
  neighbours      same batch size, other NPCs replaced              -> bitwise equal?
  position        same batch size, NPC moved to another row          -> bitwise equal?
  batch_size      B = 1, 16, 64, 200, 500                            -> bitwise equal? argmax equal?
  graph_vs_eager  CUDA graph replay vs eager                        -> bitwise equal?
Results: ai/research/results/determinism.json
"""
import torch

from common import CONFIGS, InputFactory, PolicyNet, save

KEYS = ("gesture_logits", "pointer_logits", "value")
DISCRETE = ("gesture", "pointers", "manner", "write_ptr", "write_var", "write_val", "wake")


class BatchInvarianceProbe:
    def __init__(self, dtype, T=128, probe_row=7):
        self.dtype, self.T, self.r = dtype, T, probe_row
        torch.manual_seed(0)
        self.model = PolicyNet(CONFIGS["small"], T).cuda().to(dtype).eval()
        self.pool = InputFactory(T, "cuda", dtype, seed=123).make(1000)
        self.target = {k: v[self.r:self.r + 1] for k, v in self.pool.items()}

    def batch_with_target(self, B, pos, neighbour_offset=0):
        idx = [(neighbour_offset + i) % 1000 for i in range(B)]
        idx = [i if i != self.r else (i + 500) % 1000 for i in idx]
        batch = {k: v[idx].clone() for k, v in self.pool.items()}
        for k in batch:
            batch[k][pos] = self.target[k][0]
        return batch

    def row_out(self, batch, pos):
        with torch.inference_mode():
            out = self.model(**batch)
        return {k: out[k][pos].clone() for k in KEYS + DISCRETE}

    @staticmethod
    def compare(a, b):
        cont = max((a[k].float() - b[k].float()).abs().max().item() for k in KEYS)
        bitwise = all(torch.equal(a[k], b[k]) for k in KEYS + DISCRETE)
        discrete = all(torch.equal(a[k], b[k]) for k in DISCRETE)
        return {"bitwise": bitwise, "max_abs_diff": cont, "discrete_equal": discrete}

    def run(self):
        res = {}
        ref = self.row_out(self.batch_with_target(64, 3), 3)
        res["run_to_run_B64"] = self.compare(ref, self.row_out(self.batch_with_target(64, 3), 3))
        res["neighbours_B64"] = self.compare(ref, self.row_out(self.batch_with_target(64, 3, 400), 3))
        res["position_B64"] = self.compare(ref, self.row_out(self.batch_with_target(64, 50), 50))
        for B in (1, 16, 64, 200, 500):
            res[f"batch_size_B{B}_vs_B64"] = self.compare(ref, self.row_out(self.batch_with_target(B, 0), 0))
        batch = self.batch_with_target(64, 3)
        from common import GraphRunner
        with torch.inference_mode():
            g = GraphRunner(self.model, batch)
            out = g.replay()
        res["graph_vs_eager_B64"] = self.compare(ref, {k: out[k][3].clone() for k in KEYS + DISCRETE})
        return res


class PopulationAgreement:
    """Fraction of 500 NPCs whose chosen gesture changes between two batch sizes (B=500 at once vs 25 x B=20)."""

    def __init__(self, dtype, T=128):
        torch.manual_seed(0)
        self.model = PolicyNet(CONFIGS["small"], T).cuda().to(dtype).eval()
        self.inp = InputFactory(T, "cuda", dtype, seed=9).make(500)

    def run(self):
        with torch.inference_mode():
            full = self.model(**self.inp)
            parts = [self.model(**{k: v[i:i + 20] for k, v in self.inp.items()}) for i in range(0, 500, 20)]
        chunked = {k: torch.cat([p[k] for p in parts]) for k in full}
        same_bits = (full["gesture_logits"] == chunked["gesture_logits"]).all(-1).float().mean().item()
        same_choice = (full["gesture"] == chunked["gesture"]).float().mean().item()
        return {"rows_bitwise_equal": same_bits, "rows_same_gesture": same_choice,
                "max_abs_diff": (full["gesture_logits"].float() - chunked["gesture_logits"].float()).abs().max().item()}


def main():
    out = {}
    for dtype in (torch.float16, torch.float32):
        name = str(dtype).split(".")[-1]
        out[name] = BatchInvarianceProbe(dtype).run()
        out[name]["population_B500_vs_25xB20"] = PopulationAgreement(dtype).run()
        for k, v in out[name].items():
            print(f"{name:>8} {k:<28} {v}")
    print("saved", save("determinism.json", out))


if __name__ == "__main__":
    main()
