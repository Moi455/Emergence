"""bench_contention.py - policy latency when the GPU is also rendering (docs/07_conception_ia.md, sections 2 and 6).

  python3 ai/research/bench_contention.py         # ~1 min

A second process stands in for the renderer: 30 frames/s, each frame a burst of FP16 matmuls calibrated to keep
the GPU busy `busy_ms` out of 33.3 ms, then idle until the next frame (two processes = two GPU contexts that the
driver time-slices, like a Vulkan renderer next to a CUDA inference context).
Meanwhile the main process runs the fast policy (config small, T = 128, B = 20, CUDA graph, host<->GPU copies
included) at 10 ticks/s = 200 decisions/s, and records the wall-clock latency of every tick.
Reported: policy tick latency p50 / p95 / max, and the renderer's burst time p50 / p95 with and without the NPC load.
Results: ai/research/results/contention.json
"""
import multiprocessing as mp
import statistics
import time

import torch

FRAME_MS = 1000 / 30


def percentile(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(q * len(xs)))]


def render_stand_in(busy_ms, seconds, ready, start, out):
    torch.cuda.init()
    a = torch.randn(2048, 2048, device="cuda", dtype=torch.float16)
    for _ in range(20):
        a @ a
    torch.cuda.synchronize()
    t0 = time.perf_counter()
    for _ in range(50):
        a @ a
    torch.cuda.synchronize()
    per = (time.perf_counter() - t0) / 50 * 1e3
    n = max(1, round(busy_ms / per))
    ready.set()
    start.wait()
    bursts, end = [], time.perf_counter() + seconds
    nxt = time.perf_counter()
    while time.perf_counter() < end:
        s = time.perf_counter()
        for _ in range(n):
            a @ a
        torch.cuda.synchronize()
        bursts.append((time.perf_counter() - s) * 1e3)
        nxt += FRAME_MS / 1e3
        time.sleep(max(0.0, nxt - time.perf_counter()))
    out.put({"busy_target_ms": busy_ms, "matmuls_per_frame": n, "burst_p50_ms": statistics.median(bursts),
             "burst_p95_ms": percentile(bursts, 0.95), "frames": len(bursts)})


class PolicyTicker:
    def __init__(self, B=20, T=128):
        from common import CONFIGS, GraphRunner, InputFactory, PolicyNet
        self.B = B
        self.model = PolicyNet(CONFIGS["small"], T).cuda().half().eval()
        inputs = InputFactory(T, "cuda", torch.float16).make(B)
        self.host = {k: v.cpu().pin_memory() for k, v in inputs.items()}
        with torch.inference_mode():
            self.runner = GraphRunner(self.model, inputs)

    def tick(self):
        s = time.perf_counter()
        with torch.inference_mode():
            self.runner.load(self.host)
            out = self.runner.replay()
            res = {k: v.to("cpu", non_blocking=True) for k, v in out.items()}
            torch.cuda.current_stream().synchronize()
        return (time.perf_counter() - s) * 1e3, res

    def run(self, seconds, hz=10):
        lat, end, nxt = [], time.perf_counter() + seconds, time.perf_counter()
        while time.perf_counter() < end:
            lat.append(self.tick()[0])
            nxt += 1 / hz
            time.sleep(max(0.0, nxt - time.perf_counter()))
        return {"ticks": len(lat), "p50_ms": statistics.median(lat), "p95_ms": percentile(lat, 0.95), "max_ms": max(lat)}


def with_renderer(busy_ms, seconds, ticker):
    ctx = mp.get_context("spawn")
    ready, start, q = ctx.Event(), ctx.Event(), ctx.Queue()
    p = ctx.Process(target=render_stand_in, args=(busy_ms, seconds, ready, start, q))
    p.start()
    ready.wait(60)
    start.set()
    pol = ticker.run(seconds - 0.5) if ticker else None
    r = q.get(timeout=120)
    p.join()
    return pol, r


def main():
    from common import save
    ticker = PolicyTicker()
    for _ in range(20):
        ticker.tick()
    rows = {"policy_alone": ticker.run(5)}
    print("policy alone          :", rows["policy_alone"], flush=True)
    for busy in (12, 24):
        _, r_alone = with_renderer(busy, 5, None)
        pol, r_load = with_renderer(busy, 8, ticker)
        rows[f"render_{busy}ms"] = {"render_alone": r_alone, "render_with_npcs": r_load, "policy": pol}
        print(f"render {busy} ms/frame alone : {r_alone}", flush=True)
        print(f"render {busy} ms/frame + NPC : {r_load}", flush=True)
        print(f"policy under {busy} ms render: {pol}", flush=True)
    print("saved", save("contention.json", rows))


if __name__ == "__main__":
    main()
