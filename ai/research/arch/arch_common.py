"""arch_common.py - building blocks of the candidate NPC brains compared in docs/09_architecture_ia_rd.md.

Everything here is cost-faithful to the REAL interface (ai/tok2/golden/layout.json for the input, pinned by tok-2
review 12; catalogue/generated/model_interface.json for the outputs):
  input  : <= 128 record-tokens per decision, each with num (65) + known (65) floats, cat (38) word/enum ids over the
           1 444-symbol input vocabulary, ptr (5) slot pointers, and one proposition of <= 20 prefix symbols
           (symbol, arity, depth, slot pointer, number) ;
  output : 40 gestures (feasibility-masked), <= 3 pointers per gesture, 35 manner heads (149 logits), 10 directions,
           23 stop/wake conditions + argument, <= 4 bounded writes (target slot x 93 variables x 21 value bins),
           a value head, and the grammar-constrained speech decoder (1 312 symbols, <= 20 steps, slot pointers).
Weights are random: these modules measure COST (latency, memory), never intelligence (see probe_belief.py for that).

Candidates are assembled by Brain(BrainConfig): a stateless set-Transformer with pointer attention bias (the docs/07
baseline) plus optional per-NPC state: recurrent memory tokens (RMT-style), a fast-weight associative memory updated
by the delta rule (a test-time-trained linear memory, as in DeltaNet / TTT-linear / Titans), and per-NPC LoRA
adapters gathered by NPC id. Per-NPC state lives in GPU tables indexed by NPC id (row N_NPC = trash row for padding).
"""
from __future__ import annotations

import json
import math
import os
import sys
import time
from dataclasses import asdict, dataclass, field

import torch
import torch.nn as nn
import torch.nn.functional as F

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "ai"))
sys.path.insert(0, os.path.join(ROOT, "ai", "research"))

from common import CudaTimer, GraphRunner, process_gpu_mib  # noqa: E402  (docs/07 benchmark helpers, reused)

RESULTS = os.path.join(HERE, "results")
N_NPC = 500


# ----------------------------------------------------------------------------------------------------- interface
@dataclass(frozen=True)
class InterfaceDims:
    """Sizes read from the generated model interface and the tok-2 layout (single source of truth)."""
    T: int
    num: int
    cat: int
    ptr: int
    prop_len: int
    vocab: int
    n_types: int
    gestures: int
    manner_logits: int
    directions: int
    conditions: int
    writable: int
    max_writes: int
    ptr_per_gesture: int
    speech_vocab: int
    speech_steps: int

    @staticmethod
    def load() -> "InterfaceDims":
        # tok-2 after review 12 (registry ids, ghosts, known flags), read from the PINNED golden layout: the live
        # tokenizer may be mid-edit; the golden file is the contract the C++ port is checked against.
        gold = json.load(open(os.path.join(ROOT, "ai", "tok2", "golden", "layout.json")))
        c, w = gold["constants"], gold["widths"]
        n_types = max(t["id"] for t in gold["types"].values())
        out = json.load(open(os.path.join(ROOT, "catalogue", "generated", "model_interface.json")))["output"]
        manner = sum(len(v["values"]) for v in out["manner_heads"].values())
        sp = out["speech"]
        return InterfaceDims(
            T=c["max_tokens"], num=w["num"], cat=w["cat"], ptr=w["ptr"], prop_len=c["prop_len"],
            vocab=len(gold["vocabulary"]), n_types=n_types + 1, gestures=len(out["gesture_head"]), manner_logits=manner,
            directions=len(out["relative_direction_head"]), conditions=len(out["condition_head"]),
            writable=len(out["writes"]["writable"]), max_writes=out["writes"]["max_per_decision"],
            ptr_per_gesture=out["max_pointers_per_gesture"],
            speech_vocab=len(sp["grammar_words"]) + len(sp["kinds"]) + len(sp["pointers"]) + 4,
            speech_steps=sp["max_symbols"])


DIMS = InterfaceDims.load()
VALUE_BINS = 21
QTY_BINS = 16
PROP_TOKENS = 40      # static number of proposition-bearing slots per decision (budget: ~33 used)
GHOSTS = 33           # pointer values 129..161: records of the NPC's mind outside this decision (tok-2 ghosts)
FILLED = 88           # tok-2 budget after review 12 (WAKE token included)


# ------------------------------------------------------------------------------------------------------- configs
@dataclass(frozen=True)
class BrainConfig:
    name: str
    d: int = 256
    layers: int = 6
    heads: int = 8
    ff: int = 1024
    prop_encoder: str = "bag"          # "bag" (position-bound sum) or "attn" (1-layer transformer over the symbols)
    mem_tokens: int = 0                # RMT-style recurrent memory tokens per NPC (0 = stateless)
    fast_weight: int = 0               # dk = dv of the per-NPC delta-rule memory (0 = none)
    fw_reads: int = 4                  # recall tokens read from the fast-weight memory
    lora_rank: int = 0                 # per-NPC LoRA rank on q and v of every layer (0 = none)


SIZES = {"small": dict(d=256, layers=6, heads=8, ff=1024),
         "base": dict(d=384, layers=8, heads=8, ff=1536),
         "large": dict(d=512, layers=10, heads=8, ff=2048)}


# ------------------------------------------------------------------------------------------------------ embedders
class FieldBinder(nn.Module):
    """cat columns -> d, with the (column, value) binding kept: sum_c E[id_c] * (1 + G_c).
    The same symbol in two fields must not look the same (tok-2 uses one id space for every field). In inference the
    per-column tables are folded once from the weights (a pure function of the weights, not a cache of decisions)
    and read with one embedding_bag: no [B, T, 38, d] intermediate."""

    def __init__(self, d):
        super().__init__()
        self.emb = nn.Embedding(DIMS.vocab, d, padding_idx=0)
        self.gain = nn.Parameter(torch.zeros(DIMS.cat, d))
        self.register_buffer("offset", torch.arange(DIMS.cat) * DIMS.vocab, persistent=False)
        self.folded = None

    def fold(self):
        tab = self.emb.weight.unsqueeze(0) * (1 + self.gain).unsqueeze(1)          # [C, V, d]
        tab[:, 0] = 0
        self.folded = tab.reshape(-1, tab.shape[-1]).detach().contiguous()

    def forward(self, cat):
        B, T, C = cat.shape
        if self.folded is None:                                                     # training path
            e = self.emb(cat) * (1 + self.gain)
            return (e * (cat > 0).unsqueeze(-1).to(e.dtype)).sum(2)
        idx = torch.where(cat > 0, cat + self.offset, torch.zeros_like(cat)).view(B * T, C)
        return F.embedding_bag(idx, self.folded, mode="sum", padding_idx=0).view(B, T, -1)


class NumEncoder(nn.Module):
    """[num, known, cat_known, ptr_known] (65 + 65 + 38 + 5) -> d through a 2-layer MLP whose hidden layer is
    modulated by the token type (FiLM): the same column means a different field in each token type."""

    def __init__(self, d):
        super().__init__()
        self.l1, self.l2 = nn.Linear(2 * DIMS.num + DIMS.cat + DIMS.ptr, d), nn.Linear(d, d)
        self.film = nn.Embedding(DIMS.n_types, 2 * d)

    def forward(self, num, known, cat_known, ptr_known, type_id):
        s, b = self.film(type_id).chunk(2, -1)
        return self.l2(F.gelu(self.l1(torch.cat([num, known, cat_known, ptr_known], -1)) * (1 + s) + b))


class PropEncoder(nn.Module):
    """The proposition of a record (<= 20 prefix symbols). 'bag': symbols bound to their position, arity and depth,
    summed. 'attn': the PROP_TOKENS proposition slots are gathered and read by a 1-layer transformer (d/2 wide),
    mean-pooled, projected and scattered back."""

    def __init__(self, d, kind):
        super().__init__()
        self.kind = kind
        dp = d if kind == "bag" else d // 2
        self.sym = nn.Embedding(DIMS.vocab, dp, padding_idx=0)
        self.pos = nn.Parameter(torch.zeros(DIMS.prop_len, dp))
        self.arity, self.depth = nn.Embedding(8, dp), nn.Embedding(4, dp)
        self.numw = nn.Parameter(torch.zeros(dp))
        if kind == "attn":
            self.block = nn.TransformerEncoderLayer(dp, 4, 2 * dp, dropout=0.0, batch_first=True, norm_first=True)
            self.out = nn.Linear(dp, d)

    def symbols(self, sym, arity, depth, pnum):
        x = self.sym(sym) * (1 + self.pos) + self.arity(arity) + self.depth(depth) + pnum.unsqueeze(-1) * self.numw
        return x * (sym > 0).unsqueeze(-1).to(x.dtype)

    def fold(self):
        """Inference: per-position symbol tables + arity + depth rows folded into one embedding_bag table."""
        if self.kind != "bag":
            return
        P, V = DIMS.prop_len, DIMS.vocab
        tab = self.sym.weight.unsqueeze(0) * (1 + self.pos).unsqueeze(1)          # [P, V, d]
        tab[:, 0] = 0
        self.folded = torch.cat([tab.reshape(P * V, -1), self.arity.weight, self.depth.weight]).detach().contiguous()
        self.register_buffer("p_off", (torch.arange(P, device=tab.device) * V).view(1, 1, P), persistent=False)
        self.register_buffer("folded_t", self.folded, persistent=False)

    def forward(self, sym, arity, depth, pnum, prop_rows):
        if self.kind == "bag":
            if getattr(self, "folded", None) is None:                                # training path
                return self.symbols(sym, arity, depth, pnum).sum(2)
            B, T, P = sym.shape
            on = sym > 0
            base = DIMS.prop_len * DIMS.vocab
            idx = torch.cat([torch.where(on, sym + self.p_off, 0), torch.where(on, base + arity, 0),
                             torch.where(on, base + 8 + depth, 0)], -1).view(B * T, 3 * P)
            out = F.embedding_bag(idx, self.folded_t, mode="sum", padding_idx=0).view(B, T, -1)
            return out + pnum.sum(-1, keepdim=True) * self.numw
        B, T, P = sym.shape
        g = prop_rows.unsqueeze(-1).expand(B, PROP_TOKENS, P)                      # [B, K, P] rows with a proposition
        s, a, dp_, n = (torch.gather(t, 1, g) for t in (sym, arity, depth, pnum))
        x = self.symbols(s, a, dp_, n).view(B * PROP_TOKENS, P, -1)
        pad = (s == 0).view(B * PROP_TOKENS, P)
        pad[:, 0] = False
        y = self.block(x, src_key_padding_mask=pad)
        y = self.out((y * (~pad).unsqueeze(-1).to(y.dtype)).sum(1) / (~pad).sum(1, keepdim=True).to(y.dtype))
        out = torch.zeros(B, T, y.shape[-1], device=y.device, dtype=y.dtype)
        return out.scatter_add(1, prop_rows.unsqueeze(-1).expand(B, PROP_TOKENS, y.shape[-1]),
                               y.view(B, PROP_TOKENS, -1))


class PointerGraph(nn.Module):
    """The ego-graph of the NPC's records: 5 pointer columns + the slot pointers inside propositions.
    Each relation gives a message (gather + projection) and a learned per-head attention bias on both directions:
    a Graphormer-style graph Transformer over the graph the NPC BELIEVES (never the true social graph)."""

    def __init__(self, d, heads):
        super().__init__()
        self.R = DIMS.ptr + 1
        self.msg = nn.Linear(d, d * DIMS.ptr, bias=False)
        self.ghost = nn.Parameter(torch.randn(GHOSTS, d) * 0.02)       # identity of out-of-context records
        self.bias = nn.Parameter(torch.randn(self.R, 2, heads) * 0.5)

    def forward(self, x, ptr, prop_slot, mask):
        B, T, D = x.shape
        valid = (ptr >= 1) & (ptr <= T)
        idx = (ptr - 1).clamp(0, T - 1)
        # messages from the pointed record: a slot of this decision, or a ghost (same ghost = same record)
        src = torch.cat([x, self.ghost.to(x.dtype).expand(B, GHOSTS, D)], 1)                    # [B, T + 33, D]
        gidx = torch.where(ptr <= T, ptr - 1, T + ptr - 129).clamp(0, T + GHOSTS - 1)
        has = ptr >= 1
        m = self.msg(src).view(B, T + GHOSTS, DIMS.ptr, D)
        for k in range(DIMS.ptr):
            g = torch.gather(m[:, :, k], 1, gidx[..., k:k + 1].expand(B, T, D))
            x = x + g * has[..., k:k + 1].to(x.dtype)
        # sparse edges -> per-head bias by scatter_add (column T = sink for "none"); both directions
        H = self.bias.shape[-1]
        pv = (prop_slot >= 1) & (prop_slot <= T)
        dst = torch.cat([torch.where(valid, idx, T), torch.where(pv, prop_slot - 1, T)], -1)       # [B, T, 5 + P]
        rel = torch.cat([torch.arange(DIMS.ptr, device=x.device),
                         torch.full((DIMS.prop_len,), DIMS.ptr, device=x.device)])
        w = self.bias.to(x.dtype)[rel]                                                            # [5 + P, 2, H]
        E = dst.shape[-1]
        fwd = torch.zeros(B, T, T + 1, H, device=x.device, dtype=x.dtype)
        fwd.scatter_add_(2, dst.unsqueeze(-1).expand(B, T, E, H), w[:, 0].expand(B, T, E, H))
        bwd = torch.zeros(B, T, T + 1, H, device=x.device, dtype=x.dtype)
        bwd.scatter_add_(2, dst.unsqueeze(-1).expand(B, T, E, H), w[:, 1].expand(B, T, E, H))
        bias = fwd[:, :, :T] + bwd[:, :, :T].transpose(1, 2)                                   # [B, Ti, Tj, H]
        neg = torch.finfo(x.dtype).min / 4
        bias = bias.masked_fill(~mask.view(B, 1, T, 1), neg)
        return x, bias.permute(0, 3, 1, 2).contiguous()


# --------------------------------------------------------------------------------------------- per-NPC state
class NpcLoRA(nn.Module):
    """Per-NPC low-rank adapters on q and v of every layer, gathered by NPC id (batched multi-LoRA, as Punica/S-LoRA).
    The shared weights never move; an NPC's adapter is part of its save (rank r: L x 2 x 2 x d x r fp16)."""

    def __init__(self, layers, d, r):
        super().__init__()
        self.A = nn.Parameter(torch.randn(N_NPC + 1, layers, 2, d, r) * 0.01)
        self.Bm = nn.Parameter(torch.zeros(N_NPC + 1, layers, 2, r, d))

    def delta(self, x, npc, layer, which):
        a = self.A[npc, layer, which]                                               # [B, d, r]
        b = self.Bm[npc, layer, which]                                              # [B, r, d]
        return torch.bmm(torch.bmm(x, a), b)


class FastWeightMemory(nn.Module):
    """Per-NPC associative matrix W [dk, dv] updated by the delta rule W += beta (v - W k) k^T at each write:
    one gradient step of a linear regression memory (DeltaNet = TTT-linear; Titans adds momentum and decay).
    Read: R recall queries from the SELF embedding -> R extra tokens. Write: from the encoder output."""

    def __init__(self, d, dk, reads, writes=4):
        super().__init__()
        self.dk, self.R, self.Wn = dk, reads, writes
        self.q = nn.Linear(d, reads * dk)
        self.out = nn.Linear(dk, d)
        self.kvb = nn.Linear(d, writes * (2 * dk + 1))
        self.decay = nn.Parameter(torch.tensor(4.0))

    def read(self, W, self_emb):
        B = self_emb.shape[0]
        q = F.normalize(self.q(self_emb).view(B, self.R, self.dk), dim=-1)
        return self.out(torch.bmm(q, W))                                            # [B, R, d]

    def write(self, W, h):
        """h [B, n, d] encoder outputs chosen to write (SELF + event/heard tokens). Returns the new W."""
        B = h.shape[0]
        p = self.kvb(h[:, 0]).view(B, self.Wn, 2 * self.dk + 1)
        k, v, beta = F.normalize(p[..., :self.dk], dim=-1), p[..., self.dk:2 * self.dk], torch.sigmoid(p[..., -1:])
        W = W * torch.sigmoid(self.decay)
        for i in range(self.Wn):                                                    # sequential delta-rule steps
            ki, vi, bi = k[:, i:i + 1], v[:, i:i + 1], beta[:, i:i + 1]
            err = vi - torch.bmm(ki, W)                                             # [B, 1, dv]
            W = W + torch.bmm(ki.transpose(1, 2), err * bi)
        return W


# ------------------------------------------------------------------------------------------------------ encoder
class Block(nn.Module):
    def __init__(self, d, h, ff):
        super().__init__()
        self.h = h
        self.ln1, self.ln2 = nn.LayerNorm(d), nn.LayerNorm(d)
        self.qkv, self.o = nn.Linear(d, 3 * d), nn.Linear(d, d)
        self.ff = nn.Sequential(nn.Linear(d, ff), nn.GELU(), nn.Linear(ff, d))

    def forward(self, x, bias, lora=None, npc=None, layer=0):
        B, T, D = x.shape
        y = self.ln1(x)
        qkv = self.qkv(y)
        if lora is not None:
            q, k, v = qkv.split(D, -1)
            q = q + lora.delta(y, npc, layer, 0)
            v = v + lora.delta(y, npc, layer, 1)
            qkv = torch.cat([q, k, v], -1)
        q, k, v = qkv.view(B, T, 3, self.h, D // self.h).permute(2, 0, 3, 1, 4)
        a = F.scaled_dot_product_attention(q, k, v, attn_mask=bias)
        x = x + self.o(a.transpose(1, 2).reshape(B, T, D))
        return x + self.ff(self.ln2(x))


class PolicyHeads(nn.Module):
    """Real output sizes. Gesture first (Gumbel-argmax with per-NPC deterministic noise), the rest conditioned on it."""

    def __init__(self, d):
        super().__init__()
        n = DIMS
        self.gesture = nn.Linear(d, n.gestures)
        self.g_emb = nn.Embedding(n.gestures, d)
        self.ptr_q = nn.Linear(d, n.ptr_per_gesture * d)
        self.key = nn.Linear(d, d)
        self.manner = nn.Linear(d, n.manner_logits)
        self.direction = nn.Linear(d, n.directions)
        self.cond = nn.Linear(d, n.conditions)
        self.cond_ptr = nn.Linear(d, d)
        self.cond_qty = nn.Linear(d, QTY_BINS)
        self.w_slots = nn.Parameter(torch.randn(n.max_writes, d) * 0.02)
        self.w_q = nn.Linear(d, d)
        self.w_var, self.w_val = nn.Linear(d, n.writable), nn.Linear(d, VALUE_BINS)
        self.value = nn.Linear(d, 1)

    def forward(self, x, mask, feasible, gumbel):
        B, T, D = x.shape
        h0 = x[:, 0]
        neg = torch.finfo(x.dtype).min / 4
        gl = self.gesture(h0).masked_fill(~feasible, neg)
        g = (gl.float() + gumbel).argmax(-1)
        hq = h0 + self.g_emb(g)
        keys = self.key(x)
        km = ~mask.unsqueeze(1)
        pl = torch.einsum("brd,btd->brt", self.ptr_q(hq).view(B, -1, D), keys).masked_fill(km, neg)
        cl = torch.einsum("bd,btd->bt", self.cond_ptr(hq), keys).masked_fill(~mask, neg)
        wq = self.w_q(h0).unsqueeze(1) + self.w_slots
        wl = torch.einsum("bwd,btd->bwt", wq, keys).masked_fill(km, neg)
        wp = wl.argmax(-1)
        sel = torch.gather(x, 1, wp.unsqueeze(-1).expand(B, DIMS.max_writes, D)) + wq
        return {"gesture": g, "gesture_logits": gl, "pointers": pl.argmax(-1), "manner": self.manner(hq),
                "direction": self.direction(hq).argmax(-1), "cond": self.cond(hq).argmax(-1), "cond_ptr": cl.argmax(-1),
                "cond_qty": self.cond_qty(hq).argmax(-1), "write_ptr": wp, "write_var": self.w_var(sel).argmax(-1),
                "write_val": self.w_val(sel).argmax(-1), "value": self.value(h0).squeeze(-1)}


class Brain(nn.Module):
    """One shared model for every NPC. Per-NPC state (memory tokens, fast weights) is passed in and returned:
    the caller owns the [N_NPC + 1, ...] tables and writes the new rows back (index_copy_, deterministic)."""

    def __init__(self, cfg: BrainConfig):
        super().__init__()
        self.cfg = cfg
        d = cfg.d
        self.type_emb = nn.Embedding(DIMS.n_types, d)
        self.cat = FieldBinder(d)
        self.num = NumEncoder(d)
        self.prop = PropEncoder(d, cfg.prop_encoder)
        self.graph = PointerGraph(d, cfg.heads)
        self.blocks = nn.ModuleList([Block(d, cfg.heads, cfg.ff) for _ in range(cfg.layers)])
        self.ln = nn.LayerNorm(d)
        self.heads = PolicyHeads(d)
        self.extra = cfg.mem_tokens + (cfg.fw_reads if cfg.fast_weight else 0)
        if cfg.mem_tokens:
            self.mem_pos = nn.Parameter(torch.randn(cfg.mem_tokens, d) * 0.02)
            self.mem_gate = nn.Linear(2 * d, d)
        if cfg.fast_weight:
            self.fw = FastWeightMemory(d, cfg.fast_weight, cfg.fw_reads)
        self.lora = NpcLoRA(cfg.layers, d, cfg.lora_rank) if cfg.lora_rank else None

    def prepare_inference(self):
        self.cat.fold()
        self.prop.fold()
        return self

    def embed(self, b):
        x = self.type_emb(b["type_id"]) + self.cat(b["cat"]) + self.num(b["num"], b["known"], b["cat_known"], b["ptr_known"], b["type_id"]) \
            + self.prop(b["prop_sym"], b["prop_arity"], b["prop_depth"], b["prop_num"], b["prop_rows"])
        mask = b["type_id"] > 0
        x, bias = self.graph(x, b["ptr"], b["prop_slot"], mask)
        return x, bias, mask

    def forward(self, b, mem=None, fw=None):
        x, bias, mask = self.embed(b)
        B, T, D = x.shape
        pre = []
        if self.cfg.mem_tokens:
            pre.append(mem + self.mem_pos)
        if self.cfg.fast_weight:
            pre.append(self.fw.read(fw, x[:, 0]))
        if pre:
            pre = torch.cat(pre, 1)
            E = pre.shape[1]
            x = torch.cat([pre, x], 1)
            bias = F.pad(bias, (E, 0, E, 0))                                         # extra tokens: no pointer bias
            mask = torch.cat([torch.ones(B, E, dtype=torch.bool, device=x.device), mask], 1)
        for i, blk in enumerate(self.blocks):
            x = blk(x, bias, self.lora, b.get("npc"), i)
        x = self.ln(x)
        E = self.extra
        out = self.heads(x[:, E:], mask[:, E:], b["feasible"], b["gumbel"])
        out["encoded"] = x[:, E:]
        if self.cfg.mem_tokens:
            new = x[:, :self.cfg.mem_tokens]
            gate = torch.sigmoid(self.mem_gate(torch.cat([new, mem], -1)))
            out["mem"] = gate * new + (1 - gate) * mem
        if self.cfg.fast_weight:
            out["fw"] = self.fw.write(fw, x[:, E:E + 1])
        return out

    def n_params(self):
        """Shared parameters (per-NPC adapters excluded)."""
        return sum(p.numel() for n, p in self.named_parameters() if not n.startswith("lora"))

    def per_npc_bytes(self):
        """fp16 bytes of the per-NPC state (memory tokens, fast weights, adapters)."""
        c, n = self.cfg, 0
        n += c.mem_tokens * c.d
        n += c.fast_weight * c.fast_weight
        n += c.layers * 2 * 2 * c.d * c.lora_rank
        return 2 * n


# ----------------------------------------------------------------------------------------------- speech decoder
class SpeechDecoder(nn.Module):
    """Grammar-constrained decoder of the inner language: <= 20 steps, KV cache (static shapes, unrolled loop in one
    CUDA graph), cross-attention to the speaker's encoded records, a slot-pointer head for @E/@T/b:/m:/g: symbols.
    The automaton is random (allowed[S, V], next[S, V]); its cost, not its content, is measured."""

    def __init__(self, d, layers=2, heads=8, n_states=1024, seed=0):
        super().__init__()
        V, L = DIMS.speech_vocab, DIMS.speech_steps
        self.h, self.L, self.V = heads, L, V
        self.emb = nn.Embedding(V, d)
        self.pos = nn.Parameter(torch.randn(L + 1, d) * 0.02)
        self.layers = nn.ModuleList()
        for _ in range(layers):
            self.layers.append(nn.ModuleDict(dict(ln1=nn.LayerNorm(d), qkv=nn.Linear(d, 3 * d), o1=nn.Linear(d, d),
                                                  ln2=nn.LayerNorm(d), q=nn.Linear(d, d), kv=nn.Linear(d, 2 * d),
                                                  o2=nn.Linear(d, d), ln3=nn.LayerNorm(d),
                                                  ff=nn.Sequential(nn.Linear(d, 4 * d), nn.GELU(), nn.Linear(4 * d, d)))))
        self.ln = nn.LayerNorm(d)
        self.out = nn.Linear(d, V)
        self.ptr = nn.Linear(d, d)
        g = torch.Generator().manual_seed(seed)
        allowed = torch.rand(n_states, V, generator=g) < 0.08
        allowed[:, 2] = torch.rand(n_states, generator=g) < 0.3
        allowed[1] = False
        allowed[1, 2] = True
        nxt = torch.randint(2, n_states, (n_states, V), generator=g)
        nxt[:, 2] = 1
        self.register_buffer("allowed", allowed, persistent=False)
        self.register_buffer("next_state", nxt, persistent=False)

    def split(self, x):
        B, T, D = x.shape
        return x.view(B, T, self.h, D // self.h).transpose(1, 2)

    def decode(self, enc, mask, gumbel):
        B, T, D = enc.shape
        cross = [ly["kv"](enc).chunk(2, -1) for ly in self.layers]
        cross = [(self.split(k), self.split(v)) for k, v in cross]
        cmask = mask.view(B, 1, 1, T)
        kc = [torch.zeros(B, self.h, self.L + 1, D // self.h, device=enc.device, dtype=enc.dtype) for _ in self.layers]
        vc = [torch.zeros_like(k) for k in kc]
        keys = self.ptr(enc)
        tok = torch.ones(B, dtype=torch.long, device=enc.device)
        state = torch.zeros(B, dtype=torch.long, device=enc.device)
        outs, ptrs = [], []
        for t in range(self.L):
            y = (self.emb(tok) + self.pos[t]).unsqueeze(1)
            for li, ly in enumerate(self.layers):
                q, k, v = ly["qkv"](ly["ln1"](y)).chunk(3, -1)
                kc[li][:, :, t:t + 1] = self.split(k)
                vc[li][:, :, t:t + 1] = self.split(v)
                a = F.scaled_dot_product_attention(self.split(q), kc[li][:, :, :t + 1], vc[li][:, :, :t + 1])
                y = y + ly["o1"](a.transpose(1, 2).reshape(B, 1, D))
                a = F.scaled_dot_product_attention(self.split(ly["q"](ly["ln2"](y))), cross[li][0], cross[li][1],
                                                   attn_mask=cmask)
                y = y + ly["o2"](a.transpose(1, 2).reshape(B, 1, D))
                y = y + ly["ff"](ly["ln3"](y))
            hfin = self.ln(y[:, 0])
            logits = self.out(hfin).float().masked_fill(~self.allowed[state], -1e9) + gumbel[:, t]
            tok = logits.argmax(-1)
            state = self.next_state[state, tok]
            ptrs.append(torch.einsum("bd,btd->bt", hfin, keys).masked_fill(~mask, -1e4).argmax(-1))
            outs.append(tok)
        return torch.stack(outs, 1), torch.stack(ptrs, 1)


# ------------------------------------------------------------------------------------------------------- inputs
class Tok2InputFactory:
    """Random but well-formed tok-2 batches (review 12): 88 of 128 tokens filled (catalogue budget, WAKE included),
    ~33 with a proposition of ~8 symbols, ~half of the pointer columns used (10 % of them ghosts 129..161), ~8 of the
    38 cat columns per token, known flags for num, cat and ptr."""

    def __init__(self, device, seed=0):
        self.device = device
        self.g = torch.Generator().manual_seed(seed)

    def make(self, B, npc=None):
        g, n, T = self.g, DIMS, DIMS.T
        filled = FILLED
        type_id = torch.randint(1, n.n_types, (B, T), generator=g)
        type_id[:, 0] = 1
        type_id[:, filled:] = 0
        num = (torch.rand(B, T, n.num, generator=g) * 2 - 1)
        known = (torch.rand(B, T, n.num, generator=g) < 0.4).float()
        num = num * known
        cat_known = (torch.rand(B, T, n.cat, generator=g) < 0.25)
        cat = torch.randint(1, n.vocab, (B, T, n.cat), generator=g) * (torch.rand(B, T, n.cat, generator=g) < 0.8) \
            * cat_known
        ptr_known = (torch.rand(B, T, n.ptr, generator=g) < 0.6)
        ptr = torch.randint(1, filled + 1, (B, T, n.ptr), generator=g)
        ghost = torch.randint(129, 129 + GHOSTS, (B, T, n.ptr), generator=g)
        ptr = torch.where(torch.rand(B, T, n.ptr, generator=g) < 0.1, ghost, ptr)
        ptr = ptr * ptr_known * (torch.rand(B, T, n.ptr, generator=g) < 0.85)
        prop_rows = torch.stack([torch.randperm(filled, generator=g)[:PROP_TOKENS] for _ in range(B)])
        plen = torch.zeros(B, T, dtype=torch.long)
        plen.scatter_(1, prop_rows[:, :33], torch.randint(3, 14, (B, 33), generator=g))
        pos = torch.arange(n.prop_len).view(1, 1, -1)
        on = pos < plen.unsqueeze(-1)
        prop_sym = torch.randint(1, n.vocab, (B, T, n.prop_len), generator=g) * on
        prop_arity = torch.randint(0, 4, (B, T, n.prop_len), generator=g) * on
        prop_depth = torch.randint(0, 3, (B, T, n.prop_len), generator=g) * on
        prop_slot = torch.randint(1, filled + 1, (B, T, n.prop_len), generator=g) * on * \
            (torch.rand(B, T, n.prop_len, generator=g) < 0.15)
        prop_num = torch.randn(B, T, n.prop_len, generator=g) * on
        feasible = torch.rand(B, n.gestures, generator=g) < 0.5
        feasible[:, 0] = True
        u = torch.rand(B, n.gestures, generator=g).clamp(1e-6, 1 - 1e-6)
        if npc is None:
            npc = torch.randperm(N_NPC, generator=g)[:B]
        b = dict(type_id=type_id, num=num.half(), known=known.half(), cat=cat, cat_known=cat_known.half(), ptr=ptr,
                 ptr_known=ptr_known.half(), prop_rows=prop_rows,
                 prop_sym=prop_sym, prop_arity=prop_arity, prop_depth=prop_depth, prop_slot=prop_slot,
                 prop_num=prop_num.half(), feasible=feasible, gumbel=-torch.log(-torch.log(u)), npc=npc)
        return {k: v.to(self.device) for k, v in b.items()}


# --------------------------------------------------------------------------------------------------------- utils
def truncate(b, T):
    """Keep the first T tokens of a tok-2 batch (pointers beyond T become 'none')."""
    out = dict(b)
    for k in ("type_id", "num", "known", "cat", "cat_known", "ptr", "ptr_known", "prop_sym", "prop_arity", "prop_depth",
              "prop_slot", "prop_num"):
        out[k] = b[k][:, :T].contiguous()
    keep = (out["ptr"] <= T) | (out["ptr"] >= 129)                                   # ghosts stay ghosts
    out["ptr"] = torch.where(keep, out["ptr"], torch.zeros_like(out["ptr"]))
    out["prop_slot"] = torch.where(out["prop_slot"] <= T, out["prop_slot"], torch.zeros_like(out["prop_slot"]))
    B = b["type_id"].shape[0]
    g = torch.Generator().manual_seed(T)
    out["prop_rows"] = torch.stack([torch.randperm(T, generator=g)[:PROP_TOKENS] for _ in range(B)]).to(b["ptr"].device)
    return out


def warm_gpu(seconds=3.0):
    """Bring the laptop GPU to its boost clock before timing."""
    w = torch.randn(4096, 4096, device="cuda", dtype=torch.float16)
    t0 = time.time()
    while time.time() - t0 < seconds:
        w @ w
    torch.cuda.synchronize()


def save_result(name, payload):
    os.makedirs(RESULTS, exist_ok=True)
    payload = dict(payload, gpu=torch.cuda.get_device_name(0), torch=torch.__version__,
                   date=time.strftime("%Y-%m-%d %H:%M"))
    path = os.path.join(RESULTS, name)
    with open(path, "w") as f:
        json.dump(payload, f, indent=1, default=lambda o: asdict(o) if hasattr(o, "__dataclass_fields__") else str(o))
    return path


__all__ = ["DIMS", "N_NPC", "BrainConfig", "SIZES", "Brain", "SpeechDecoder", "Tok2InputFactory", "CudaTimer",
           "GraphRunner", "process_gpu_mib", "warm_gpu", "save_result", "truncate", "PROP_TOKENS"]
