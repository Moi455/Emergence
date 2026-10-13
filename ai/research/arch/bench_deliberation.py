"""bench_deliberation.py - cost of the "think more" ideas on this GPU (docs/09, section 4.5).

  python3 ai/research/arch/bench_deliberation.py        # ~3 min

Lots of 32 (8 for the reflecting NPCs), FP16, CUDA graph, real tok-2 interface (arch_common):
  looped     : 2 layers looped 4 times (shared weights in depth, TRM / Universal-Transformer style) vs 8 layers, at
               the base width (d 384): same FLOPs, 4x fewer parameters in the encoder
  film       : personality FiLM (per-NPC scale and shift on every block, precomputed once per game day from the
               static mind, O21) vs none
  moe        : two static-shape, neighbour-independent MoE forms (CUDA graphs and per-NPC determinism forbid
               data-dependent shapes): (a) top-1 of 4 experts computed densely then selected, (b) one expert per NPC
               gathered as weights (bmm). Against the dense FFN of the same active size
  critic     : imagination for the reflect mode: K = 8 candidate plans of 8 NPCs, each a 20-symbol proposition,
               encoded (bag) and scored by 2 cross-attention layers over the NPC's encoded records (a plan critic,
               Q(records, plan)); plus a latent world model rolled 5 steps for the 8 x 8 candidates
Results: ai/research/arch/results/deliberation.json
"""
import torch
import torch.nn as nn
import torch.nn.functional as F

from arch_common import (DIMS, SIZES, Block, Brain, BrainConfig, CudaTimer, GraphRunner, Tok2InputFactory,
                         save_result, truncate, warm_gpu)


class LoopedBrain(Brain):
    """Brain whose first `core` blocks are re-applied `loops` times (an iteration embedding is added each time)."""

    def __init__(self, cfg, core, loops):
        super().__init__(cfg)
        self.blocks = self.blocks[:core]
        self.loops = loops
        self.it = nn.Parameter(torch.zeros(loops, cfg.d))

    def forward(self, b, mem=None, fw=None):
        x, bias, mask = self.embed(b)
        for i in range(self.loops):
            x = x + self.it[i]
            for blk in self.blocks:
                x = blk(x, bias)
        x = self.ln(x)
        return self.heads(x, mask, b["feasible"], b["gumbel"])


class FiLMBrain(Brain):
    """Per-NPC FiLM on the residual stream before every block: (1 + gamma) * x + beta, gathered by NPC id from a
    table computed once per game day by a small hypernetwork of the static mind (precompute, not a decision cache)."""

    def __init__(self, cfg, n_npc=501):
        super().__init__(cfg)
        self.film = nn.Parameter(torch.zeros(n_npc, cfg.layers, 2, cfg.d))

    def forward(self, b, mem=None, fw=None):
        x, bias, mask = self.embed(b)
        f = self.film[b["npc"]]                                                   # [B, L, 2, d]
        for i, blk in enumerate(self.blocks):
            x = x * (1 + f[:, i, 0].unsqueeze(1)) + f[:, i, 1].unsqueeze(1)
            x = blk(x, bias)
        x = self.ln(x)
        return self.heads(x, mask, b["feasible"], b["gumbel"])


class DenseMoE(nn.Module):
    """(a) top-1 of E experts, computed for every token then selected: static shapes, E x the FFN FLOPs."""

    def __init__(self, d, ff, E=4):
        super().__init__()
        self.E = E
        self.router = nn.Linear(d, E)
        self.w1 = nn.Parameter(torch.randn(E, d, ff) / d ** 0.5)
        self.w2 = nn.Parameter(torch.randn(E, ff, d) / ff ** 0.5)

    def forward(self, x):
        B, T, D = x.shape
        sel = self.router(x).argmax(-1)                                            # [B, T]
        h = torch.einsum("btd,edf->ebtf", x, self.w1)
        y = torch.einsum("ebtf,efd->ebtd", F.gelu(h), self.w2)                     # [E, B, T, D]
        return torch.gather(y, 0, sel.view(1, B, T, 1).expand(1, B, T, D)).squeeze(0)


class NpcExpertMoE(nn.Module):
    """(b) one expert per NPC (chosen from his static mind), weights gathered per row: static, deterministic."""

    def __init__(self, d, ff, E=4):
        super().__init__()
        self.w1 = nn.Parameter(torch.randn(E, d, ff) / d ** 0.5)
        self.w2 = nn.Parameter(torch.randn(E, ff, d) / ff ** 0.5)

    def forward(self, x, expert):
        return torch.bmm(F.gelu(torch.bmm(x, self.w1[expert])), self.w2[expert])


class FFNOnly(nn.Module):
    def __init__(self, d, ff):
        super().__init__()
        self.ff = nn.Sequential(nn.Linear(d, ff), nn.GELU(), nn.Linear(ff, d))

    def forward(self, x):
        return self.ff(x)


class PlanCritic(nn.Module):
    """Q(records, plan): K candidate plans (20-symbol propositions, bag-encoded) cross-attend to the encoded records."""

    def __init__(self, d, layers=2, heads=8):
        super().__init__()
        self.sym = nn.Embedding(DIMS.vocab, d)
        self.pos = nn.Parameter(torch.zeros(DIMS.prop_len, d))
        self.layers = nn.ModuleList([nn.MultiheadAttention(d, heads, batch_first=True) for _ in range(layers)])
        self.ff = nn.ModuleList([nn.Sequential(nn.Linear(d, 4 * d), nn.GELU(), nn.Linear(4 * d, d))
                                 for _ in range(layers)])
        self.value = nn.Linear(d, 1)

    def forward(self, enc, plans):
        q = (self.sym(plans) * (1 + self.pos)).sum(2)                               # [B, K, d]
        for att, ff in zip(self.layers, self.ff):
            q = q + att(q, enc, enc, need_weights=False)[0]
            q = q + ff(q)
        return self.value(q).squeeze(-1)                                            # [B, K]


class LatentWorldModel(nn.Module):
    """Dreamer/MuZero-style latent dynamics at small scale: 16 latent tokens, rolled H steps per candidate."""

    def __init__(self, d, layers=2, heads=8, H=5):
        super().__init__()
        self.H = H
        self.blocks = nn.ModuleList([nn.TransformerEncoderLayer(d, heads, 4 * d, dropout=0.0, batch_first=True,
                                                                norm_first=True) for _ in range(layers)])
        self.reward = nn.Linear(d, 1)

    def forward(self, z):
        r = 0
        for _ in range(self.H):
            for blk in self.blocks:
                z = blk(z)
            r = r + self.reward(z[:, 0]).squeeze(-1)
        return r


class DeliberationBench:
    def __init__(self, iters=40):
        self.iters, self.rows = iters, []

    def t(self, fn, inputs):
        with torch.inference_mode():
            g = GraphRunner(fn, inputs)
            return CudaTimer.measure(g.replay, iters=self.iters)["median_ms"]

    def add(self, part, name, ms, **kw):
        self.rows.append(dict(part=part, name=name, graph_ms=ms, **kw))
        print(f"{part:>8} {name:>34}: {ms:7.2f} ms " + " ".join(f"{k}={v}" for k, v in kw.items()), flush=True)

    def run(self):
        base = SIZES["base"]
        f = Tok2InputFactory("cuda", seed=3)
        b32 = f.make(32)
        for T in (128, 64):
            bb = b32 if T == 128 else truncate(b32, T)
            deep = Brain(BrainConfig(name="base8", **base)).cuda().half().eval().prepare_inference()
            loop = LoopedBrain(BrainConfig(name="base2x4", **base), core=2, loops=4).cuda().half().eval()
            loop.prepare_inference()
            film = FiLMBrain(BrainConfig(name="base+film", **base)).cuda().half().eval().prepare_inference()
            enc_params = lambda m: sum(p.numel() for p in m.blocks.parameters()) / 1e6
            self.add("looped", f"8 layers, T={T}", self.t(lambda **x: deep(x), bb), encoder_params_M=round(enc_params(deep), 2))
            self.add("looped", f"2 layers x 4 loops, T={T}", self.t(lambda **x: loop(x), bb),
                     encoder_params_M=round(enc_params(loop), 2))
            self.add("film", f"base + per-NPC FiLM, T={T}", self.t(lambda **x: film(x), bb))
            del deep, loop, film
            torch.cuda.empty_cache()
        d, ff = 384, 1536
        x = torch.randn(32, 128, d, device="cuda", dtype=torch.float16)
        expert = torch.randint(0, 4, (32,), device="cuda")
        dense = FFNOnly(d, ff).cuda().half().eval()
        moe_a = DenseMoE(d, ff).cuda().half().eval()
        moe_b = NpcExpertMoE(d, ff).cuda().half().eval()
        self.add("moe", "dense FFN (one layer, lot 32 x 128)", self.t(lambda **k: dense(k["x"]), {"x": x}))
        self.add("moe", "(a) top-1 of 4, dense then select", self.t(lambda **k: moe_a(k["x"]), {"x": x}))
        self.add("moe", "(b) one expert per NPC, gathered", self.t(lambda **k: moe_b(k["x"], k["e"]),
                                                                  {"x": x, "e": expert}))
        crit = PlanCritic(d).cuda().half().eval()
        enc = torch.randn(8, 128, d, device="cuda", dtype=torch.float16)
        plans = torch.randint(1, DIMS.vocab, (8, 8, DIMS.prop_len), device="cuda")
        self.add("critic", "plan critic, 8 NPCs x 8 plans", self.t(lambda **k: crit(k["enc"], k["plans"]),
                                                                  {"enc": enc, "plans": plans}))
        wm = LatentWorldModel(d).cuda().half().eval()
        z = torch.randn(64, 16, d, device="cuda", dtype=torch.float16)
        self.add("critic", "latent world model, 64 rollouts x 5 steps", self.t(lambda **k: wm(k["z"]), {"z": z}))
        return self.rows


def main():
    torch.backends.cuda.matmul.allow_tf32 = False
    warm_gpu()
    rows = DeliberationBench().run()
    print("saved", save_result("deliberation.json", {"rows": rows}))


if __name__ == "__main__":
    main()
