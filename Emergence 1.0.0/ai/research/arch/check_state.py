"""check_state.py - per-NPC recurrent state: determinism and memory (docs/09, section 6).

  python3 ai/research/arch/check_state.py          # ~1 min, one fresh process per memory measurement

1. Determinism. The same NPC (same tok-2 input, same memory rows) decided in two different lots of 32 (other
   neighbours, another position in the lot), in eager mode and replayed in a CUDA graph: are its outputs AND its
   new memory rows bit-identical? (docs/07 measured it for the stateless policy; the state must not break it.)
2. Memory. GPU memory of a fresh process holding the base policy with memory tokens + fast weights, the 501-row
   state tables and one CUDA graph at a lot of 32: PyTorch peak and the driver's view (CUDA context included).
Results: ai/research/arch/results/state.json
"""
import json
import subprocess
import sys

import torch

from arch_common import SIZES, Brain, BrainConfig, GraphRunner, Tok2InputFactory, process_gpu_mib, save_result


def stateful_cfg(size):
    return BrainConfig(name=f"{size}:mem8+fw64", **SIZES[size], mem_tokens=8, fast_weight=64, fw_reads=4)


class DeterminismCheck:
    def __init__(self, size="small"):
        torch.manual_seed(0)
        self.model = Brain(stateful_cfg(size)).cuda().half().eval().prepare_inference()

    def run_lot(self, b, mem_table, fw_table, graph):
        npc = b["npc"]
        fn = lambda **x: self.model(x, mem=mem_table[x["npc"]], fw=fw_table[x["npc"]])
        with torch.inference_mode():
            if graph:
                out = GraphRunner(fn, b).replay()
            else:
                out = fn(**b)
        return {k: v.clone() for k, v in out.items()}

    def run(self):
        B = 32
        f = Tok2InputFactory("cuda", seed=11)
        lot_a, lot_b = f.make(B), f.make(B)
        # put row 3 of lot A at row 17 of lot B (same NPC id, same input), other rows different
        for k in lot_a:
            lot_b[k] = lot_b[k].clone()
            lot_b[k][17] = lot_a[k][3]
        g = torch.Generator(device="cuda").manual_seed(5)
        mem = (torch.randn(501, 8, self.model.cfg.d, device="cuda", generator=g) * 0.5).half()
        fw = (torch.randn(501, 64, 64, device="cuda", generator=g) * 0.1).half()
        res = {}
        for mode in ("eager", "graph"):
            oa = self.run_lot(lot_a, mem, fw, mode == "graph")
            ob = self.run_lot(lot_b, mem, fw, mode == "graph")
            res[mode] = {k: bool(torch.equal(oa[k][3], ob[k][17])) for k in oa}
        ea = self.run_lot(lot_a, mem, fw, False)
        ga = self.run_lot(lot_a, mem, fw, True)
        res["eager_vs_graph"] = {k: bool(torch.equal(ea[k], ga[k])) for k in ea}
        return res


def child(size):
    torch.manual_seed(0)
    model = Brain(stateful_cfg(size)).cuda().half().eval().prepare_inference()
    mem = torch.zeros(501, 8, model.cfg.d, device="cuda", dtype=torch.float16)
    fw = torch.zeros(501, 64, 64, device="cuda", dtype=torch.float16)
    b = Tok2InputFactory("cuda", seed=1).make(32)

    def step(**x):
        out = model(x, mem=mem[x["npc"]], fw=fw[x["npc"]])
        mem.index_copy_(0, x["npc"], out["mem"])
        fw.index_copy_(0, x["npc"], out["fw"])
        return out["gesture"]
    with torch.inference_mode():
        GraphRunner(step, b).replay()
    torch.cuda.synchronize()
    print(json.dumps({"config": model.cfg.name, "params_M": model.n_params() / 1e6,
                      "weights_MiB": sum(p.numel() for p in model.parameters()) * 2 / 2**20,
                      "state_tables_MiB": (mem.numel() + fw.numel()) * 2 / 2**20,
                      "torch_peak_MiB": torch.cuda.max_memory_allocated() / 2**20, "process_MiB": process_gpu_mib()}))


def main():
    if len(sys.argv) > 2 and sys.argv[1] == "--child":
        child(sys.argv[2])
        return
    det = DeterminismCheck().run()
    print("determinism:", json.dumps(det))
    mem = []
    for size in ("small", "base", "large"):
        out = subprocess.run([sys.executable, __file__, "--child", size], capture_output=True, text=True)
        line = [ln for ln in out.stdout.splitlines() if ln.startswith("{")]
        mem.append(json.loads(line[-1]) if line else {"config": size, "error": out.stderr[-300:]})
        print("memory:", mem[-1])
    print("saved", save_result("state.json", {"determinism": det, "memory": mem}))


if __name__ == "__main__":
    main()
