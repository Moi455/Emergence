"""common.py - shared pieces of the NPC-brain benchmarks (docs/07_conception_ia.md).

PolicyNet is a cost-faithful sketch of the proposed fast policy, not a trained model (random weights):
  * fixed slot layout grouped by token type (catalogue budget, ~84 slots, padded to T = 96 or 128): static shapes,
    so CUDA graphs / TensorRT / a custom kernel runtime can be used;
  * per-type projection of <= 48 scalars per token, <= 5 categorical slots per token (grammar words, kinds, enums);
  * 3 pointers per token (to the NPC's own records only), injected as input and as a learned attention bias per head
    (the ego-graph of the NPC's mental files: a Graphormer-style graph Transformer);
  * factored heads on the SELF token: gesture (64) -> pointers conditioned on the gesture (target, instrument)
    -> manner bins (5 params x 5 bins) ; 4 sparse state writes (pointer x variable x value bin) ; wake condition ; value.
Sampling is deterministic: the caller passes Gumbel noise derived from (world seed, npc id, decision counter).
Only cost, memory and numerical behaviour are measured with it.
"""
import json
import math
import os
import statistics
import subprocess
import time
from dataclasses import asdict, dataclass

import torch
import torch.nn as nn
import torch.nn.functional as F

RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")


@dataclass(frozen=True)
class PolicyConfig:
    name: str
    d: int
    layers: int
    heads: int
    ff: int


CONFIGS = {
    "xs": PolicyConfig("xs", 128, 4, 4, 512),
    "small": PolicyConfig("small", 256, 6, 8, 1024),
    "base": PolicyConfig("base", 384, 8, 8, 1536),
    "large": PolicyConfig("large", 512, 10, 8, 2048),
    "xl": PolicyConfig("xl", 768, 12, 12, 3072),
}

# Output sizes (catalogue/README.md budget table).
N_GESTURES = 64
N_PTR_ROLES = 2           # target, instrument
N_MANNER, N_BINS = 5, 5   # force, zone, repetition, stop condition, speed... in <= 5 bins
N_WRITES = 4
N_WRITE_VARS = 64         # variable id inside the pointed token's type (0 = no write)
N_VALUE_BINS = 21         # signed step, -10..+10 tenths of the allowed step
N_WAKE = 16               # wake / stop condition of the chosen gesture
VOCAB = 512 + 1024 + 16 + 64   # grammar words + kinds + symbols + specials
N_NUM = 48
N_CAT = 5
N_PTR = 3


class TokenLayout:
    """Fixed slots by token type. Segment order is fixed; empty slots are masked."""
    BASE = (("SELF", 1), ("SELF_MIND", 1), ("SELF_STATE", 1), ("TASTE", 2), ("ENTITY", 10), ("GROUP", 2),
            ("BELIEF", 12), ("HEARD", 2), ("MEMORY", 9), ("GOAL", 4), ("PLAN", 1), ("REQUEST", 2), ("COMMIT", 3),
            ("INV", 8), ("SKILL", 3), ("PLACE", 1), ("THING", 16), ("EVENT", 6))

    def __init__(self, length):
        base = sum(n for _, n in self.BASE)
        if length < base:
            raise ValueError(f"layout needs >= {base} slots")
        self.segments = list(self.BASE) + ([("SPARE", length - base)] if length > base else [])
        self.length = length
        self.types = [t for t, _ in self.segments]
        self.position_type = torch.tensor([i for i, (_, n) in enumerate(self.segments) for _ in range(n)])
        starts = [sum(n for _, n in self.segments[:i]) for i in range(len(self.segments))]
        self.spans = [(s, n) for s, (_, n) in zip(starts, self.segments)]

    @property
    def n_types(self):
        return len(self.segments)


class TokenEmbedder(nn.Module):
    def __init__(self, layout, d, heads):
        super().__init__()
        self.layout, self.d, self.h = layout, d, heads
        self.register_buffer("ptype", layout.position_type.clone(), persistent=False)
        self.type_emb = nn.Embedding(layout.n_types, d)
        self.cat_emb = nn.Embedding(VOCAB, d, padding_idx=0)
        self.slot_emb = nn.Parameter(torch.zeros(N_CAT, d))
        self.num_w = nn.Parameter(torch.randn(layout.n_types, N_NUM, d) / math.sqrt(N_NUM))
        self.num_b = nn.Parameter(torch.zeros(layout.n_types, d))
        self.ptr_proj = nn.ModuleList([nn.Linear(d, d, bias=False) for _ in range(N_PTR)])
        self.ptr_bias = nn.Parameter(torch.randn(N_PTR, heads) * 0.5)

    def forward(self, cat, num, ptr, mask):
        B, T, _ = cat.shape
        x = self.type_emb(self.ptype).unsqueeze(0)
        x = x + (self.cat_emb(cat) + self.slot_emb * (cat > 0).unsqueeze(-1).to(self.slot_emb.dtype)).sum(-2)
        # per-type scalar projection: one GEMM per contiguous type segment of the fixed layout
        proj = [num[:, s:s + n] @ self.num_w[t] for t, (s, n) in enumerate(self.layout.spans)]
        x = x + torch.cat(proj, 1) + self.num_b[self.ptype]
        base = x
        valid = ptr >= 0
        idx = ptr.clamp(min=0)
        adj = torch.zeros(B, N_PTR, T, T, device=x.device, dtype=x.dtype)
        for k in range(N_PTR):
            g = torch.gather(base, 1, idx[..., k:k + 1].expand(B, T, self.d))
            x = x + self.ptr_proj[k](g) * valid[..., k:k + 1].to(x.dtype)
            adj[:, k].scatter_(2, idx[..., k:k + 1], valid[..., k:k + 1].to(x.dtype))
        adj = adj + adj.transpose(-1, -2)
        bias = torch.einsum("bkij,kh->bhij", adj, self.ptr_bias.to(x.dtype))
        neg = torch.finfo(x.dtype).min / 4
        bias = bias.masked_fill(~mask.view(B, 1, 1, T), neg)
        return x, bias


class EncoderBlock(nn.Module):
    def __init__(self, d, h, ff):
        super().__init__()
        self.h = h
        self.ln1, self.ln2 = nn.LayerNorm(d), nn.LayerNorm(d)
        self.qkv, self.o = nn.Linear(d, 3 * d), nn.Linear(d, d)
        self.ff = nn.Sequential(nn.Linear(d, ff), nn.GELU(), nn.Linear(ff, d))

    def forward(self, x, bias):
        B, T, D = x.shape
        q, k, v = self.qkv(self.ln1(x)).view(B, T, 3, self.h, D // self.h).permute(2, 0, 3, 1, 4)
        a = F.scaled_dot_product_attention(q, k, v, attn_mask=bias)
        x = x + self.o(a.transpose(1, 2).reshape(B, T, D))
        return x + self.ff(self.ln2(x))


class FactoredHeads(nn.Module):
    """Gesture -> pointers conditioned on the gesture -> manner ; sparse writes ; wake condition ; value."""

    def __init__(self, d):
        super().__init__()
        self.d = d
        self.gesture = nn.Linear(d, N_GESTURES)
        self.gesture_emb = nn.Embedding(N_GESTURES, d)
        self.ptr_q = nn.Linear(d, N_PTR_ROLES * d)
        self.ptr_k = nn.Linear(d, d)
        self.manner = nn.Linear(d, N_MANNER * N_BINS)
        self.write_slots = nn.Parameter(torch.randn(N_WRITES, d) * 0.02)
        self.write_q = nn.Linear(d, d)
        self.write_var = nn.Linear(d, N_WRITE_VARS)
        self.write_val = nn.Linear(d, N_VALUE_BINS)
        self.wake = nn.Linear(d, N_WAKE)
        self.value = nn.Linear(d, 1)

    def forward(self, x, mask, feasible, gumbel):
        B, T, D = x.shape
        h0 = x[:, 0]
        neg = torch.finfo(x.dtype).min / 4
        g_logits = self.gesture(h0).masked_fill(~feasible, neg)
        g = (g_logits.float() + gumbel).argmax(-1)                     # deterministic per-NPC sampling
        hq = h0 + self.gesture_emb(g)
        keys = self.ptr_k(x)                                           # [B, T, D]
        q = self.ptr_q(hq).view(B, N_PTR_ROLES, D)
        ptr_logits = torch.einsum("brd,btd->brt", q, keys) / math.sqrt(D)
        ptr_logits = ptr_logits.masked_fill(~mask.unsqueeze(1), neg)
        manner = self.manner(hq).view(B, N_MANNER, N_BINS)
        wq = self.write_q(h0).unsqueeze(1) + self.write_slots.unsqueeze(0)   # [B, 4, D]
        w_ptr = torch.einsum("bwd,btd->bwt", wq, keys) / math.sqrt(D)
        w_ptr = w_ptr.masked_fill(~mask.unsqueeze(1), neg)
        sel = torch.gather(x, 1, w_ptr.argmax(-1).unsqueeze(-1).expand(B, N_WRITES, D)) + wq
        return {
            "gesture_logits": g_logits, "gesture": g, "pointer_logits": ptr_logits,
            "pointers": ptr_logits.argmax(-1), "manner": manner.argmax(-1),
            "write_ptr": w_ptr.argmax(-1), "write_var": self.write_var(sel).argmax(-1),
            "write_val": self.write_val(sel).argmax(-1), "wake": self.wake(hq).argmax(-1),
            "value": self.value(h0).squeeze(-1),
        }


class PolicyNet(nn.Module):
    def __init__(self, cfg, length=128):
        super().__init__()
        self.cfg = cfg
        self.layout = TokenLayout(length)
        self.embed = TokenEmbedder(self.layout, cfg.d, cfg.heads)
        self.blocks = nn.ModuleList([EncoderBlock(cfg.d, cfg.heads, cfg.ff) for _ in range(cfg.layers)])
        self.ln = nn.LayerNorm(cfg.d)
        self.heads = FactoredHeads(cfg.d)

    def encode(self, cat, num, ptr, mask, depth=None):
        x, bias = self.embed(cat, num, ptr, mask)
        for blk in self.blocks[: depth or len(self.blocks)]:
            x = blk(x, bias)
        return self.ln(x)

    def forward(self, cat, num, ptr, mask, feasible, gumbel):
        x = self.encode(cat, num, ptr, mask)
        return self.heads(x, mask, feasible, gumbel)

    def n_params(self, compute_only=False):
        skip = ("embed.cat_emb", "embed.type_emb") if compute_only else ()
        return sum(p.numel() for n, p in self.named_parameters() if not n.startswith(skip))

    def flops_per_decision(self):
        """Matmul FLOPs (2 x MAC) of one decision, analytic."""
        c, T = self.cfg, self.layout.length
        layer = 2 * T * c.d * 3 * c.d + 2 * T * c.d * c.d + 2 * 2 * T * c.d * c.ff + 2 * 2 * T * T * c.d
        embed = 2 * T * N_NUM * c.d + N_PTR * 2 * T * c.d * c.d
        heads = 2 * T * c.d * c.d + 2 * c.d * (N_GESTURES + 2 * c.d + N_MANNER * N_BINS + N_WAKE) \
            + 2 * (N_PTR_ROLES + N_WRITES) * T * c.d + 2 * N_WRITES * c.d * (N_WRITE_VARS + N_VALUE_BINS)
        return c.layers * layer + embed + heads


class InputFactory:
    """Random but well-formed inputs: ~85 % of slots filled, ~half of the pointer slots used."""

    def __init__(self, length, device, dtype, seed=0):
        self.T, self.device, self.dtype = length, device, dtype
        self.gen = torch.Generator().manual_seed(seed)

    def make(self, B):
        g, T = self.gen, self.T
        cat = torch.randint(1, VOCAB, (B, T, N_CAT), generator=g)
        cat = cat * (torch.rand(B, T, N_CAT, generator=g) < 0.6)
        num = torch.randn(B, T, N_NUM, generator=g).clamp(-1, 1)
        ptr = torch.randint(0, T, (B, T, N_PTR), generator=g)
        ptr = torch.where(torch.rand(B, T, N_PTR, generator=g) < 0.5, ptr, torch.full_like(ptr, -1))
        mask = torch.rand(B, T, generator=g) < 0.85
        mask[:, 0] = True
        feasible = torch.rand(B, N_GESTURES, generator=g) < 0.5
        feasible[:, 0] = True
        u = torch.rand(B, N_GESTURES, generator=g).clamp(1e-6, 1 - 1e-6)
        gumbel = -torch.log(-torch.log(u))
        out = dict(cat=cat, num=num.to(self.dtype), ptr=ptr, mask=mask, feasible=feasible, gumbel=gumbel)
        return {k: v.to(self.device) for k, v in out.items()}


class CudaTimer:
    """Median / p95 latency of a callable, measured with CUDA events."""

    @staticmethod
    def measure(fn, iters=50, warmup=10, budget_s=3.0):
        for _ in range(warmup):
            fn()
        torch.cuda.synchronize()
        times, t_start = [], time.perf_counter()
        for _ in range(iters):
            s, e = torch.cuda.Event(enable_timing=True), torch.cuda.Event(enable_timing=True)
            s.record()
            fn()
            e.record()
            e.synchronize()
            times.append(s.elapsed_time(e))
            if time.perf_counter() - t_start > budget_s and len(times) >= 5:
                break
        times.sort()
        return {"median_ms": statistics.median(times), "p95_ms": times[min(len(times) - 1, int(0.95 * len(times)))],
                "n": len(times)}


class GraphRunner:
    """Captures one forward pass in a CUDA graph with static input buffers (no launch overhead)."""

    def __init__(self, fn, inputs):
        self.fn = fn
        self.static = {k: v.clone() for k, v in inputs.items()}
        s = torch.cuda.Stream()
        s.wait_stream(torch.cuda.current_stream())
        with torch.cuda.stream(s):
            for _ in range(3):
                fn(**self.static)
        torch.cuda.current_stream().wait_stream(s)
        self.graph = torch.cuda.CUDAGraph()
        with torch.cuda.graph(self.graph):
            self.out = fn(**self.static)

    def load(self, inputs):
        for k, v in inputs.items():
            self.static[k].copy_(v, non_blocking=True)

    def replay(self):
        self.graph.replay()
        return self.out


def gpu_name():
    return torch.cuda.get_device_name(0) if torch.cuda.is_available() else "cpu"


def process_gpu_mib():
    """GPU memory of this process as seen by the driver (CUDA context included), or None."""
    try:
        q = subprocess.run(["nvidia-smi", "--query-compute-apps=pid,used_memory", "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=10).stdout
        for line in q.strip().splitlines():
            pid, mib = [s.strip() for s in line.split(",")]
            if int(pid) == os.getpid():
                return int(mib)
    except Exception:
        return None
    return None


def save(name, payload):
    os.makedirs(RESULTS, exist_ok=True)
    payload = dict(payload, gpu=gpu_name(), torch=torch.__version__, date=time.strftime("%Y-%m-%d %H:%M"))
    path = os.path.join(RESULTS, name)
    with open(path, "w") as f:
        json.dump(payload, f, indent=1, default=lambda o: asdict(o) if hasattr(o, "__dataclass_fields__") else str(o))
    return path
