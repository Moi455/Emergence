"""bench_memory.py - GPU memory of the policy as it would run in the game (docs/07_conception_ia.md, section 6).

  python3 ai/research/bench_memory.py             # ~30 s, one fresh process per measurement

FP16 weights + one CUDA graph at a fixed batch bucket (32 nominal, 64 burst), T = 128. Reports the PyTorch peak
allocation and the driver's view of the whole process (CUDA context, cuBLAS workspaces and allocator included).
Results: ai/research/results/memory.json
"""
import json
import subprocess
import sys


def child(cfg, B):
    import torch
    from common import CONFIGS, GraphRunner, InputFactory, PolicyNet, process_gpu_mib
    model = PolicyNet(CONFIGS[cfg], 128).cuda().half().eval()
    inputs = InputFactory(128, "cuda", torch.float16).make(B)
    with torch.inference_mode():
        GraphRunner(model, inputs).replay()
    torch.cuda.synchronize()
    print(json.dumps({"config": cfg, "B": B, "weights_MiB": sum(p.numel() for p in model.parameters()) * 2 / 2**20,
                      "torch_peak_MiB": torch.cuda.max_memory_allocated() / 2**20,
                      "torch_reserved_MiB": torch.cuda.memory_reserved() / 2**20,
                      "process_MiB": process_gpu_mib()}))


def main():
    from common import save
    rows = []
    for cfg in ("small", "base", "large"):
        for B in (32, 64):
            out = subprocess.run([sys.executable, __file__, "--child", cfg, str(B)], capture_output=True, text=True)
            row = json.loads(out.stdout.strip().splitlines()[-1])
            rows.append(row)
            print(row, flush=True)
    print("saved", save("memory.json", {"rows": rows}))


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--child":
        child(sys.argv[2], int(sys.argv[3]))
    else:
        main()
