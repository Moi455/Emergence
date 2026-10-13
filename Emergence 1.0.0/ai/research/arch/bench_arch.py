"""bench_arch.py - cost of the candidate NPC brains on this GPU, at the real tok-2 interface (docs/09, section 3).

  python3 ai/research/arch/bench_arch.py                 # full sweep, ~6 min
  python3 ai/research/arch/bench_arch.py --only brains --sizes small --batches 32

Parts (each one result file):
  brains   : the shared policy (stateless set-Transformer with pointer bias = docs/07 baseline) and its variants with
             per-NPC state (memory tokens, fast-weight delta-rule memory, both, per-NPC LoRA), proposition encoder
             bag vs attention; sizes small / base / large; lots of 8 / 16 / 32 / 64; FP16; one CUDA graph per lot
             size that includes the gather of the NPCs' state rows and the write-back (index_copy_).
  speech   : grammar-constrained decoder, 20 steps, KV cache, slot pointers, lots of 8 / 16 / 32.
  stream   : per-NPC event stream at 10 Hz: 500 NPCs x 4 perceived events per tick into a GRU (d 256) or a
             delta-rule memory (64 x 64); one CUDA graph per tick.
  llm      : a distilled small LLM in the loop instead (GPT-2-small-like 124 M and SmolLM2-135M-like shapes,
             random weights): prefill of 128 and 512 tokens per decision, lots of 8 / 32.
  online   : cost of in-game learning: one SGD step on per-NPC LoRA adapters (forward + backward, shared weights
             frozen) for a lot of 32 decisions.
  tick     : one 100 ms tick of the recommended pipeline: selector pass (2 layers, over all 128 tokens: an upper
             bound) + policy lot of 32 + speech lot of 8 (decoder width = policy width, 2 layers) + event stream.
  tick2    : same, selector pass A over 48 tokens (docs/07), policy on 128- and 64-token buckets (--only tick2).
  tick3    : the recommended stateless brain: selector, act lot 32 on 64 tokens, reflect lot 8 on 128 tokens, speech
             lot 8, plan critic (--only tick3).
Results: ai/research/arch/results/arch_<part>.json
"""
import argparse
import math

import torch
import torch.nn as nn
import torch.nn.functional as F

from arch_common import (DIMS, N_NPC, SIZES, Brain, BrainConfig, CudaTimer, GraphRunner, SpeechDecoder,
                         Tok2InputFactory, save_result, truncate, warm_gpu)

TICKS_PER_S = 10          # the scheduler serves one lot per 100 ms tick (docs/07, section 3.2)


class StatefulStep:
    """One decision lot: gather the NPCs' state rows, run the shared Brain, write the new rows back.
    Captured whole in a CUDA graph (static shapes: fixed lot size, padded rows point to the trash row N_NPC)."""

    def __init__(self, model: Brain, B, device="cuda"):
        c = model.cfg
        self.model = model
        self.mem = torch.zeros(N_NPC + 1, max(c.mem_tokens, 1), c.d, device=device, dtype=torch.float16)
        self.fw = torch.zeros(N_NPC + 1, max(c.fast_weight, 1), max(c.fast_weight, 1), device=device,
                              dtype=torch.float16)

    def __call__(self, **b):
        c = self.model.cfg
        npc = b["npc"]
        mem = self.mem[npc] if c.mem_tokens else None
        fw = self.fw[npc] if c.fast_weight else None
        out = self.model(b, mem=mem, fw=fw)
        if c.mem_tokens:
            self.mem.index_copy_(0, npc, out["mem"])
        if c.fast_weight:
            self.fw.index_copy_(0, npc, out["fw"])
        return {k: v for k, v in out.items() if k not in ("mem", "fw", "encoded")}


class BrainBench:
    VARIANTS = {
        "set_ptr": {},
        "set_ptr+prop_attn": dict(prop_encoder="attn"),
        "set_ptr+mem8": dict(mem_tokens=8),
        "set_ptr+fw64": dict(fast_weight=64, fw_reads=4),
        "set_ptr+mem8+fw64": dict(mem_tokens=8, fast_weight=64, fw_reads=4),
        "set_ptr+lora4": dict(lora_rank=4),
    }

    def __init__(self, sizes, batches, iters):
        self.sizes, self.batches, self.iters = sizes, batches, iters
        self.rows = []

    def run(self):
        for size in self.sizes:
            for vname, extra in self.VARIANTS.items():
                if size == "large" and vname not in ("set_ptr", "set_ptr+mem8+fw64"):
                    continue
                cfg = BrainConfig(name=f"{size}:{vname}", **SIZES[size], **extra)
                for B in self.batches:
                    self.one(cfg, B)
        return self.rows

    def one(self, cfg, B):
        torch.manual_seed(0)
        model = Brain(cfg).cuda().half().eval().prepare_inference()
        inputs = Tok2InputFactory("cuda", seed=B).make(B)
        step = StatefulStep(model, B)
        torch.cuda.reset_peak_memory_stats()
        with torch.inference_mode():
            eager = CudaTimer.measure(lambda: step(**inputs), iters=10, warmup=3)
            runner = GraphRunner(step, inputs)
            graph = CudaTimer.measure(runner.replay, iters=self.iters)
        row = {"config": cfg.name, "size": cfg.name.split(":")[0], "variant": cfg.name.split(":")[1], "B": B,
               "params_M": model.n_params() / 1e6, "per_npc_state_KiB": model.per_npc_bytes() / 1024,
               "eager_ms": eager["median_ms"], "graph_ms": graph["median_ms"], "graph_p95_ms": graph["p95_ms"],
               "decisions_per_s": B / graph["median_ms"] * 1e3,
               "gpu_share_at_200_per_s_lot32": None, "peak_alloc_MiB": torch.cuda.max_memory_allocated() / 2**20}
        if B == 32:
            row["gpu_share_at_200_per_s_lot32"] = TICKS_PER_S * graph["median_ms"] / 1000
        self.rows.append(row)
        print(f"{cfg.name:>26} B={B:<3} {row['params_M']:6.2f} M  state {row['per_npc_state_KiB']:6.1f} KiB/NPC | "
              f"eager {row['eager_ms']:7.2f} ms | graph {row['graph_ms']:6.2f} ms (p95 {row['graph_p95_ms']:.2f}) | "
              f"{row['decisions_per_s']:7.0f} dec/s | peak {row['peak_alloc_MiB']:5.0f} MiB", flush=True)
        del runner, model, step
        torch.cuda.empty_cache()


class SpeechBench:
    def run(self, iters):
        rows = []
        for d, layers in ((256, 2), (384, 3)):
            dec = SpeechDecoder(d, layers).cuda().half().eval()
            for B in (8, 16, 32):
                enc = torch.randn(B, DIMS.T, d, device="cuda", dtype=torch.float16)
                mask = torch.ones(B, DIMS.T, dtype=torch.bool, device="cuda")
                mask[:, 90:] = False
                u = torch.rand(B, DIMS.speech_steps, DIMS.speech_vocab, device="cuda").clamp(1e-6, 1 - 1e-6)
                inp = {"enc": enc, "mask": mask, "gumbel": -torch.log(-torch.log(u))}
                with torch.inference_mode():
                    runner = GraphRunner(dec.decode, inp)
                    t = CudaTimer.measure(runner.replay, iters=iters)
                    toks, _ = runner.replay()
                state, ok = torch.zeros(B, dtype=torch.long, device="cuda"), True
                for s in range(DIMS.speech_steps):
                    ok &= bool(dec.allowed[state, toks[:, s]].all())
                    state = dec.next_state[state, toks[:, s]]
                row = {"d": d, "layers": layers, "params_M": sum(p.numel() for p in dec.parameters()) / 1e6, "B": B,
                       "steps": DIMS.speech_steps, "vocab": DIMS.speech_vocab, "graph_ms": t["median_ms"],
                       "graph_p95_ms": t["p95_ms"], "utterances_per_s": B / t["median_ms"] * 1e3, "grammatical": ok}
                rows.append(row)
                print(f"speech d={d} L={layers} B={B:<3} 20 steps: {t['median_ms']:6.2f} ms (p95 {t['p95_ms']:.2f}) | "
                      f"{row['utterances_per_s']:6.0f} utt/s | grammatical={ok}", flush=True)
        return rows


class EventStream(nn.Module):
    """Per-NPC recurrent integration of perceived events at every 10 Hz tick, for all 500 NPCs at once."""

    def __init__(self, kind, d=256, dk=64, ev_feat=96):
        super().__init__()
        self.kind, self.dk = kind, dk
        self.enc = nn.Sequential(nn.Linear(ev_feat, d), nn.GELU(), nn.Linear(d, d))
        if kind == "gru":
            self.cell = nn.GRUCell(d, d)
        else:
            self.kvb = nn.Linear(d, 2 * dk + 1)

    def forward(self, ev, valid, state):
        """ev [N, E, F] features of the events perceived this tick, valid [N, E]; state [N, d] or [N, dk, dk]."""
        x = self.enc(ev)
        for e in range(ev.shape[1]):
            v = valid[:, e:e + 1].to(x.dtype)
            if self.kind == "gru":
                state = v * self.cell(x[:, e], state) + (1 - v) * state
            else:
                p = self.kvb(x[:, e])
                k = F.normalize(p[:, :self.dk], dim=-1).unsqueeze(1)
                val = p[:, self.dk:2 * self.dk].unsqueeze(1)
                beta = torch.sigmoid(p[:, -1:]).unsqueeze(-1) * v.unsqueeze(-1)
                state = state + torch.bmm(k.transpose(1, 2), (val - torch.bmm(k, state)) * beta)
        return state


class StreamBench:
    def run(self, iters):
        rows = []
        N, E = N_NPC, 4
        for kind in ("gru", "delta"):
            m = EventStream(kind).cuda().half().eval()
            ev = torch.randn(N, E, 96, device="cuda", dtype=torch.float16)
            valid = torch.rand(N, E, device="cuda") < 0.5
            st = torch.zeros(N, 256, device="cuda", dtype=torch.float16) if kind == "gru" else \
                torch.zeros(N, 64, 64, device="cuda", dtype=torch.float16)
            with torch.inference_mode():
                runner = GraphRunner(m, {"ev": ev, "valid": valid, "state": st})
                t = CudaTimer.measure(runner.replay, iters=iters)
            rows.append({"kind": kind, "npcs": N, "events_per_tick": E, "graph_ms": t["median_ms"],
                         "gpu_share_at_10Hz": TICKS_PER_S * t["median_ms"] / 1000,
                         "state_KiB_per_npc": (256 if kind == "gru" else 64 * 64) * 2 / 1024})
            print(f"event stream {kind:>5}: 500 NPCs x 4 events per tick: {t['median_ms']:.3f} ms "
                  f"-> {rows[-1]['gpu_share_at_10Hz'] * 100:.2f} % GPU at 10 Hz", flush=True)
        return rows


class TinyLM(nn.Module):
    """Decoder-only LM with the shapes of a small open model (random weights): causal SDPA, GQA, SwiGLU."""

    def __init__(self, d, layers, heads, kv_heads, ff):
        super().__init__()
        self.h, self.kvh, self.hd = heads, kv_heads, d // heads
        self.layers = nn.ModuleList()
        for _ in range(layers):
            self.layers.append(nn.ModuleDict(dict(n1=nn.RMSNorm(d), q=nn.Linear(d, d, bias=False),
                                                  kv=nn.Linear(d, 2 * kv_heads * self.hd, bias=False),
                                                  o=nn.Linear(d, d, bias=False), n2=nn.RMSNorm(d),
                                                  up=nn.Linear(d, 2 * ff, bias=False),
                                                  down=nn.Linear(ff, d, bias=False))))
        self.n = nn.RMSNorm(d)
        self.head = nn.Linear(d, 256, bias=False)       # structured action head, not a text vocabulary

    def forward(self, x):
        B, T, D = x.shape
        for ly in self.layers:
            y = ly["n1"](x)
            q = ly["q"](y).view(B, T, self.h, self.hd).transpose(1, 2)
            k, v = ly["kv"](y).view(B, T, 2, self.kvh, self.hd).permute(2, 0, 3, 1, 4)
            rep = self.h // self.kvh
            k, v = k.repeat_interleave(rep, 1), v.repeat_interleave(rep, 1)
            a = F.scaled_dot_product_attention(q, k, v, is_causal=True)
            x = x + ly["o"](a.transpose(1, 2).reshape(B, T, D))
            g, u = ly["up"](ly["n2"](x)).chunk(2, -1)
            x = x + ly["down"](F.silu(g) * u)
        return self.head(self.n(x[:, -1]))


class LLMBench:
    SHAPES = {"gpt2-small-like (85 M non-emb.)": (768, 12, 12, 12, 3072),
              "SmolLM2-135M-like (106 M non-emb.)": (576, 30, 9, 3, 1536)}

    def run(self, iters):
        rows = []
        for name, (d, L, h, kvh, ff) in self.SHAPES.items():
            m = TinyLM(d, L, h, kvh, ff).cuda().half().eval()
            npar = sum(p.numel() for p in m.parameters()) / 1e6
            for T in (128, 512):
                for B in (8, 32):
                    x = torch.randn(B, T, d, device="cuda", dtype=torch.float16)
                    with torch.inference_mode():
                        runner = GraphRunner(m, {"x": x})
                        t = CudaTimer.measure(runner.replay, iters=iters)
                    dps = B / t["median_ms"] * 1e3
                    rows.append({"model": name, "params_M": npar, "T": T, "B": B, "graph_ms": t["median_ms"],
                                 "decisions_per_s": dps, "gpu_share_at_200_per_s": 200 / dps})
                    print(f"{name:>36} T={T:<4} B={B:<3} {t['median_ms']:8.2f} ms | {dps:7.0f} dec/s | "
                          f"GPU at 200/s: {200 / dps * 100:6.1f} %", flush=True)
            del m
            torch.cuda.empty_cache()
        return rows


class OnlineBench:
    """In-game learning, per-NPC LoRA: one SGD step (fwd + bwd, shared weights frozen) for one lot of 32."""

    def run(self, iters):
        rows = []
        for size in ("small", "base"):
            cfg = BrainConfig(name=f"{size}:lora4", **SIZES[size], lora_rank=4)
            model = Brain(cfg).cuda().half()
            for n, p in model.named_parameters():
                p.requires_grad_(n.startswith("lora"))
            inputs = Tok2InputFactory("cuda", seed=1).make(32)
            target = torch.randint(0, DIMS.gestures, (32,), device="cuda")
            opt = torch.optim.SGD([p for p in model.parameters() if p.requires_grad], lr=1e-3)

            def sgd_step():
                out = model(inputs)
                loss = F.cross_entropy(out["gesture_logits"].float(), target)
                opt.zero_grad(set_to_none=True)
                loss.backward()
                opt.step()
            t = CudaTimer.measure(sgd_step, iters=iters, warmup=3)
            fwd = None
            with torch.inference_mode():
                fwd = CudaTimer.measure(lambda: model(inputs), iters=iters, warmup=3)
            rows.append({"config": cfg.name, "B": 32, "sgd_step_ms_eager": t["median_ms"],
                         "forward_ms_eager": fwd["median_ms"], "adapter_KiB_per_npc": model.per_npc_bytes() / 1024})
            print(f"online LoRA step {cfg.name}: fwd+bwd+SGD {t['median_ms']:.2f} ms (eager) vs forward "
                  f"{fwd['median_ms']:.2f} ms (eager) | adapter {model.per_npc_bytes() / 1024:.1f} KiB/NPC", flush=True)
            del model, opt
            torch.cuda.empty_cache()
        return rows


class TickBench:
    """One 100 ms tick of the recommended pipeline (graph each): selector pass, policy lot 32, speech lot 8, stream."""

    def run(self, iters, size="base", variant=None, T=128, sel_T=48):
        """T = token bucket of the policy (128, or 64: the situation sampler gives 41 tokens on average).
        sel_T = tokens read by the selector's pass A (2 layers): 48 as docs/07 describes it, 128 = upper bound."""
        variant = variant or dict(mem_tokens=8, fast_weight=64, fw_reads=4)
        rows = []
        sel_cfg = BrainConfig(name="selector", d=256, layers=2, heads=8, ff=1024)
        pol_cfg = BrainConfig(name=f"{size}:mem8+fw64", **SIZES[size], **variant)
        sel = Brain(sel_cfg).cuda().half().eval().prepare_inference()
        pol = Brain(pol_cfg).cuda().half().eval().prepare_inference()
        dec = SpeechDecoder(pol_cfg.d, 2).cuda().half().eval()
        stream = EventStream("delta").cuda().half().eval()
        fac = Tok2InputFactory("cuda", seed=7)
        b32 = fac.make(32)
        sel_in = truncate(b32, sel_T) if sel_T != DIMS.T else b32
        if T != DIMS.T:
            b32 = truncate(b32, T)
        step = StatefulStep(pol, 32)
        u = torch.rand(8, DIMS.speech_steps, DIMS.speech_vocab, device="cuda").clamp(1e-6, 1 - 1e-6)
        sp_in = {"enc": torch.randn(8, DIMS.T, pol_cfg.d, device="cuda", dtype=torch.float16),
                 "mask": torch.ones(8, DIMS.T, dtype=torch.bool, device="cuda"), "gumbel": -torch.log(-torch.log(u))}
        st_in = {"ev": torch.randn(N_NPC, 4, 96, device="cuda", dtype=torch.float16),
                 "valid": torch.rand(N_NPC, 4, device="cuda") < 0.5,
                 "state": torch.zeros(N_NPC, 64, 64, device="cuda", dtype=torch.float16)}
        with torch.inference_mode():
            g_sel = GraphRunner(lambda **b: sel(b), sel_in)
            g_pol = GraphRunner(step, b32)
            g_dec = GraphRunner(dec.decode, sp_in)
            g_st = GraphRunner(stream, st_in)

            def tick():
                g_st.replay()
                g_sel.replay()
                g_pol.replay()
                g_dec.replay()
            parts = {k: CudaTimer.measure(g.replay, iters=iters)["median_ms"]
                     for k, g in (("stream", g_st), ("selector", g_sel), ("policy", g_pol), ("speech", g_dec))}
            t = CudaTimer.measure(tick, iters=iters)
        row = {"policy": pol_cfg.name, "T": T, "selector_T": sel_T, "params_M": pol.n_params() / 1e6, "parts_ms": parts, "tick_ms": t["median_ms"],
               "tick_p95_ms": t["p95_ms"], "gpu_share_at_200_per_s": TICKS_PER_S * t["median_ms"] / 1000}
        rows.append(row)
        print(f"tick {pol_cfg.name} T={T}: {parts} -> total {t['median_ms']:.2f} ms (p95 {t['p95_ms']:.2f}) "
              f"-> {row['gpu_share_at_200_per_s'] * 100:.1f} % GPU at 200 decisions/s", flush=True)
        return rows


class RecommendedTick:
    """docs/09 section 6: one 100 ms tick of the recommended brain, stateless (no latent memory): selector pass A
    (48 tokens, lot 32), act/listen lot of 32 on the 64-token bucket, reflect lot of 8 on the 128-token bucket, speech
    lot of 8 (d 256, 2 layers), plan critic (8 NPCs x 8 candidate plans). Same shared weights for act and reflect."""

    def run(self, iters, size="base"):
        from bench_deliberation import PlanCritic
        cfg = BrainConfig(name=size, **SIZES[size])
        sel = Brain(BrainConfig(name="selector", d=256, layers=2, heads=8, ff=1024)).cuda().half().eval()
        pol = Brain(cfg).cuda().half().eval()
        sel.prepare_inference()
        pol.prepare_inference()
        dec = SpeechDecoder(256, 2).cuda().half().eval()
        crit = PlanCritic(cfg.d).cuda().half().eval()
        fac = Tok2InputFactory("cuda", seed=9)
        b32, b8 = fac.make(32), fac.make(8)
        u = torch.rand(8, DIMS.speech_steps, DIMS.speech_vocab, device="cuda").clamp(1e-6, 1 - 1e-6)
        sp_in = {"enc": torch.randn(8, DIMS.T, 256, device="cuda", dtype=torch.float16),
                 "mask": torch.ones(8, DIMS.T, dtype=torch.bool, device="cuda"), "gumbel": -torch.log(-torch.log(u))}
        cr_in = {"enc": torch.randn(8, DIMS.T, cfg.d, device="cuda", dtype=torch.float16),
                 "plans": torch.randint(1, DIMS.vocab, (8, 8, DIMS.prop_len), device="cuda")}
        with torch.inference_mode():
            g = {"selector": GraphRunner(lambda **b: sel(b), truncate(b32, 48)),
                 "act_T64_lot32": GraphRunner(lambda **b: pol(b), truncate(b32, 64)),
                 "reflect_T128_lot8": GraphRunner(lambda **b: pol(b), b8),
                 "speech_lot8": GraphRunner(dec.decode, sp_in),
                 "critic": GraphRunner(lambda **k: crit(k["enc"], k["plans"]), cr_in)}
            parts = {k: CudaTimer.measure(r.replay, iters=iters)["median_ms"] for k, r in g.items()}

            def tick():
                for r in g.values():
                    r.replay()
            t = CudaTimer.measure(tick, iters=iters)
        row = {"policy": cfg.name, "params_M": pol.n_params() / 1e6, "parts_ms": parts, "tick_ms": t["median_ms"],
               "tick_p95_ms": t["p95_ms"], "gpu_share_at_200_per_s": TICKS_PER_S * t["median_ms"] / 1000,
               "capacity_per_s": {"act": 320, "reflect": 80, "utterances": 80}}
        print(f"recommended tick {cfg.name}: {parts} -> {t['median_ms']:.2f} ms (p95 {t['p95_ms']:.2f}) -> "
              f"{row['gpu_share_at_200_per_s'] * 100:.1f} % GPU", flush=True)
        return [row]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="brains,speech,stream,llm,online,tick")
    ap.add_argument("--sizes", default="small,base,large")
    ap.add_argument("--batches", default="8,16,32,64")
    ap.add_argument("--iters", type=int, default=40)
    a = ap.parse_args()
    torch.backends.cuda.matmul.allow_tf32 = False
    warm_gpu()
    parts = a.only.split(",")
    if "brains" in parts:
        rows = BrainBench(a.sizes.split(","), [int(x) for x in a.batches.split(",")], a.iters).run()
        print("saved", save_result("arch_brains.json", {"rows": rows, "dims": DIMS}))
    if "speech" in parts:
        print("saved", save_result("arch_speech.json", {"rows": SpeechBench().run(a.iters)}))
    if "stream" in parts:
        print("saved", save_result("arch_stream.json", {"rows": StreamBench().run(a.iters)}))
    if "llm" in parts:
        print("saved", save_result("arch_llm.json", {"rows": LLMBench().run(a.iters)}))
    if "online" in parts:
        print("saved", save_result("arch_online.json", {"rows": OnlineBench().run(a.iters)}))
    if "tick" in parts:
        rows = [r for size in ("small", "base", "large") for r in TickBench().run(a.iters, size, sel_T=128)]
        print("saved", save_result("arch_tick.json", {"rows": rows}))
    if "tick3" in parts:                         # the recommended brain (docs/09 section 6)
        rows = RecommendedTick().run(a.iters, "small") + RecommendedTick().run(a.iters, "base")
        print("saved", save_result("arch_tick3.json", {"rows": rows}))
    if "tick2" in parts:                         # selector pass A at 48 tokens; policy buckets 128 and 64
        rows = [r for size in ("small", "base", "large") for T in (128, 64) for r in TickBench().run(a.iters, size, T=T)]
        print("saved", save_result("arch_tick2.json", {"rows": rows}))


if __name__ == "__main__":
    main()
