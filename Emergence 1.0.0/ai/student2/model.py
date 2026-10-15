"""model.py - the student: a Set Transformer over the records of one decision, factorised heads, an inner-language decoder.

    tokens (tok-2 arrays, compacted by the Collator) -> RecordEmbedder -> PointerGraph (bias per relation, ghosts as
    tokens) -> Trunk (L blocks) -> readout (SELF) -> heads. What each head is conditioned on (everything else is the
    trunk's output at SELF, `ctx`):
        gesture            ctx, feasibility mask
        pointers (<= 3)    ctx + the gesture; the k-th pointer of the gesture reads the k-th query; masks: NONE only if the
                           parameter is optional, only records of the types the parameter accepts, directions / forms
                           only if it accepts them
        manner (shared)    ctx + the gesture; the "none" level only for an optional parameter
        stop condition     ctx + the gesture; its arguments: ctx + gesture + the condition; masks by argument type
        n of writes        ctx + the gesture
        write i (i < 4)    ctx + the gesture + the CHAIN (the embedding of write i-1: its target and its variable);
                           target, then variable (masked by the kind of the target and by the order imposed: targets
                           non-decreasing, variables increasing on the same target), then the value
        speech / sentence  the decoder, started from the gesture (speech) or from the (target, variable) of a write
    Training is teacher-forced (`forward(batch)` conditions on the TRUE previous choice); inference (`predict`) on the
    model's own argmax and writes the sentences token by token. The two paths share every module and every mask.

Static shapes: given (B, n, K, ghosts) nothing in `forward` depends on the DATA (no nonzero, no data-dependent Python
branch, no atomic add): the Collator pre-compacts the word columns, the proposition rows and the graph edges to fixed
capacities. The forward is therefore deterministic and can be captured in a CUDA graph.

Reused from ai/research/arch/arch_common.py (measured there): FiLM-by-type number encoder, Graphormer-style bias per
(relation, direction, head) with learned ghost tokens, pre-LN blocks on SDPA with an additive bias, the memory slot (a
hook only). Rewritten against the live tok-2 sizes (not the golden layout) so that it follows the tokenizer.
"""
from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.utils.checkpoint

from .spec import MAX_ARITY, MAX_REFS, MAX_SLOTS, MAX_WRITES, NO_LABEL, NUM_BINS, STACK, OutputSpace, TargetKind, ValueKind

GHOSTS = 33                     # ghost tokens: 32 numbered + the overflow one (tok-2: pointers 129..161)
GHOST_ROWS = 40                 # padded to a multiple of 8
GHOST_BASE = 129
NEG = -1e4                      # a "forbidden" logit (float32 logits: finite, so a fully masked row stays finite)


def compute_dtype(device: torch.device) -> torch.dtype:
    """The dtype matmuls run in: the autocast dtype when autocast is on, else float32."""
    t = device.type
    return torch.get_autocast_dtype(t) if torch.is_autocast_enabled(t) else torch.float32


# ----------------------------------------------------------------------------------------------- configuration
XL_D, XL_LAYERS = 768, 16
@dataclass(frozen=True)
class StudentConfig:
    name: str
    d: int
    layers: int
    heads: int
    ff: int
    prop_d: int                 # width of the proposition encoder
    prop_heads: int
    dec_layers: int             # inner-language decoder
    dec_ff: int
    dropout: float = 0.0        # residual dropout of the trunk blocks (0 = none; only the training mode uses it)
    checkpoint: bool = False    # gradient checkpointing of the trunk blocks (memory for time; training only)

    def to_dict(self) -> dict:
        return dict(self.__dict__)


SIZES = {
    "tiny": StudentConfig("tiny", 64, 2, 4, 128, 32, 2, 1, 128),                 # tests, CPU
    "small": StudentConfig("small", 256, 6, 8, 1024, 128, 4, 2, 1024),            # docs/09: d256 x 6
    "base": StudentConfig("base", 384, 8, 8, 1536, 192, 4, 3, 1536),              # docs/09: d384 x 8
    # xl: a deliberately OVERSIZED yardstick (decision of 15 Oct.): too slow for the 25 % GPU budget on purpose, it is
    # quantised and compared with the small unquantised models (student2/compare.py). Sized to train in float16 on 6 GB.
    "xl": StudentConfig("xl", XL_D, XL_LAYERS, 12, 4 * XL_D, 256, 4, 4, 2048, dropout=0.1, checkpoint=True),
}


@dataclass(frozen=True)
class Dims:
    """Input sizes, read from the live tokenizer."""
    n_types: int
    num: int
    cat: int
    ptr: int
    prop_len: int
    vocab: int

    @classmethod
    def of(cls, space: OutputSpace) -> "Dims":
        lay = space.tokenizer.layout
        return cls(space.n_types, lay.width["num"], lay.width["cat"], lay.width["ptr"], lay.prop_len,
                   space.sequences.vocab_size)


# ----------------------------------------------------------------------------------------------- per-NPC memory hook
class NpcMemory(ABC):
    """Hook for the per-NPC memory docs/09 recommends (memory tokens carried from one decision to the next).

    The trunk asks `read(state, self_embedding)` for `n_tokens` extra tokens that it appends to the sequence, and
    gives `write(state, encoded, valid)` the trunk output to compute the state the NPC will carry to its next decision.
    The state lives outside the model (one row per NPC, saved with the NPC): it travels in `Batch.memory` and comes
    back as `Outputs.memory`. `n_tokens` must be a multiple of 8 (attention kernels)."""

    n_tokens: int = 0

    @abstractmethod
    def read(self, state, self_emb: torch.Tensor) -> torch.Tensor:
        """-> [B, n_tokens, d]"""

    @abstractmethod
    def write(self, state, encoded: torch.Tensor, valid: torch.Tensor):
        """-> the new state (same structure as `state`)"""


class NoMemory(NpcMemory):
    """The stateless policy (docs/07 baseline): no extra token, no state."""

    n_tokens = 0

    def read(self, state, self_emb):
        return self_emb.new_zeros(self_emb.shape[0], 0, self_emb.shape[-1])

    def write(self, state, encoded, valid):
        return state


# ----------------------------------------------------------------------------------------------- embedding of a record
class FieldBinder(nn.Module):
    """The word columns of a record -> d. A symbol is bound to the COLUMN of THE TYPE it sits in:
    sum_c E[id_c] * (1 + G_col[c] + G_type_col[type, c]) over the K filled columns the Collator kept. The same word in
    two fields (tok-2 has one id space) therefore does not look the same. A dense gather of [B, n, K, d]: no atomic add."""

    def __init__(self, d: int, dims: Dims):
        super().__init__()
        self.dims = dims
        self.emb = nn.Embedding(dims.vocab, d, padding_idx=0)
        self.col_gain = nn.Parameter(torch.zeros(dims.cat, d))
        self.type_col_gain = nn.Embedding(dims.n_types * dims.cat, d)

    def forward(self, cat_id, cat_col, type_id):
        cd = compute_dtype(cat_id.device)
        gain = (1 + self.col_gain.to(cd)[cat_col] + F.embedding(type_id.unsqueeze(-1) * self.dims.cat + cat_col,
                                                                  self.type_col_gain.weight.to(cd)))
        return (F.embedding(cat_id, self.emb.weight.to(cd), padding_idx=0) * gain).sum(2)


class NumberEncoder(nn.Module):
    """[num, known, cat_known, ptr_known] -> d, an MLP whose hidden layer is modulated by the token TYPE (FiLM): the
    same column is a different field in each type. Unknown stays unknown: the flags go in beside the values."""

    def __init__(self, d: int, dims: Dims):
        super().__init__()
        self.l1 = nn.Linear(2 * dims.num + dims.cat + dims.ptr, d)
        self.l2 = nn.Linear(d, d)
        self.film = nn.Embedding(dims.n_types, 2 * d)

    def forward(self, num, known, cat_known, ptr_known, type_id):
        s, b = self.film(type_id).chunk(2, -1)
        x = torch.cat([num, known.to(num.dtype), cat_known.to(num.dtype), ptr_known.to(num.dtype)], -1).to(self.l1.weight.dtype)
        return self.l2(F.gelu(self.l1(x) * (1 + s) + b))


class Block(nn.Module):
    """Pre-LN Transformer block on scaled_dot_product_attention with an additive bias (already in the compute dtype)."""

    def __init__(self, d: int, h: int, ff: int, dropout: float = 0.0):
        super().__init__()
        self.h = h
        self.drop = nn.Dropout(dropout)
        self.ln1, self.ln2 = nn.LayerNorm(d), nn.LayerNorm(d)
        self.qkv, self.o = nn.Linear(d, 3 * d), nn.Linear(d, d)
        self.ff = nn.Sequential(nn.Linear(d, ff), nn.GELU(), nn.Linear(ff, d))

    def forward(self, x, bias):
        B, N, D = x.shape
        q, k, v = self.qkv(self.ln1(x)).view(B, N, 3, self.h, D // self.h).permute(2, 0, 3, 1, 4)
        a = F.scaled_dot_product_attention(q, k, v, attn_mask=bias)
        x = x + self.drop(self.o(a.transpose(1, 2).reshape(B, N, D)))
        return x + self.drop(self.ff(self.ln2(x)))


class PropositionEncoder(nn.Module):
    """A small Transformer over the <= 20 prefix symbols of a record's proposition, for the R record rows the Collator
    gathered (padded rows are zeroed). Each position carries: the symbol, its place in the sentence, its arity, its depth
    in the tree, the slot it designates (a pointer: which record, or which ghost - the same identity the trunk sees) and
    its count. Mean-pooled and projected into the token; scattered back to the records by UNIQUE indices (padded rows
    get their own distinct sink), so the result does not depend on any order of addition."""

    def __init__(self, d: int, dp: int, heads: int, dims: Dims):
        super().__init__()
        self.sym = nn.Embedding(dims.vocab, dp, padding_idx=0)
        self.pos = nn.Embedding(dims.prop_len, dp)
        self.arity = nn.Embedding(MAX_ARITY, dp)
        self.depth = nn.Embedding(8, dp)
        self.slot = nn.Embedding(GHOST_BASE + GHOSTS, dp, padding_idx=0)
        self.count = nn.Linear(1, dp, bias=False)
        self.block = Block(dp, heads, 2 * dp)
        self.out = nn.Linear(dp, d)

    def forward(self, a: dict, n: int):
        sym = a["prop_sym"].long()
        B, R, P = sym.shape
        valid = sym > 0
        valid = valid.clone()
        valid[..., 0] = True                                           # a padded row still attends to something
        pos = torch.arange(P, device=sym.device)
        x = (self.sym(sym) + self.pos(pos) + self.arity(a["prop_arity"].long().clamp(max=MAX_ARITY - 1))
             + self.depth(a["prop_depth"].long().clamp(max=7)) + self.slot(a["prop_slot"].long())
             + self.count(a["prop_num"].unsqueeze(-1).to(self.count.weight.dtype)))
        cd = compute_dtype(sym.device)
        bias = torch.zeros(B * R, 1, 1, P, dtype=cd, device=sym.device).masked_fill(~valid.view(B * R, 1, 1, P), -16384.0)
        h = self.block(x.view(B * R, P, -1), bias)
        v = (sym > 0).unsqueeze(-1).to(h.dtype).view(B * R, P, 1)
        pooled = self.out((h * v).sum(1) / v.sum(1).clamp(min=1)).view(B, R, -1)
        pooled = pooled * a["prop_row_ok"].unsqueeze(-1).to(pooled.dtype)
        out = torch.zeros(B, n + R, pooled.shape[-1], dtype=pooled.dtype, device=sym.device)
        out = out.scatter(1, a["prop_row"].long().unsqueeze(-1).expand(-1, -1, pooled.shape[-1]), pooled)
        return out[:, :n]


class RecordEmbedder(nn.Module):
    """type + words + numbers + proposition -> one vector per record; the ghosts get their own learned vectors."""

    def __init__(self, cfg: StudentConfig, dims: Dims):
        super().__init__()
        d = cfg.d
        self.type_emb = nn.Embedding(dims.n_types, d, padding_idx=0)
        self.cat = FieldBinder(d, dims)
        self.num = NumberEncoder(d, dims)
        self.prop = PropositionEncoder(d, cfg.prop_d, cfg.prop_heads, dims)
        self.ln = nn.LayerNorm(d)
        self.ghost = nn.Parameter(torch.randn(GHOST_ROWS, d) * 0.02)           # 33 used, padded to a multiple of 8

    def forward(self, a: dict):
        tid = a["type_id"].long()
        n = tid.shape[1]
        x = (self.type_emb(tid) + self.cat(a["cat_id"].long(), a["cat_col"].long(), tid)
             + self.num(a["num"], a["known"], a["cat_known"], a["ptr_known"], tid) + self.prop(a, n))
        return self.ln(x) * (tid > 0).unsqueeze(-1).to(x.dtype)


# ----------------------------------------------------------------------------------------------- the graph
class PointerGraph(nn.Module):
    """The ego-graph of what the NPC believes: the 5 pointer columns of a record and the slots inside its proposition.
    Per (type, column) relation and direction a learned bias per head biases the attention (Graphormer), and the
    pointed record sends a message to the pointer (first-layer message passing). A pointer to a record that is not in
    the decision goes to a GHOST: a learned token appended to the sequence, attendable, whose identity is the
    identity of that record (two pointers to the same record meet at the same ghost). The bias is built by a dense
    contraction with the one-hot of each edge's destination (deterministic, unlike an atomic scatter-add)."""

    def __init__(self, cfg: StudentConfig, dims: Dims):
        super().__init__()
        self.dims, self.heads, self.n_ptr = dims, cfg.heads, dims.ptr
        self.bias = nn.Embedding(dims.n_types * (dims.ptr + 1), 2 * cfg.heads)
        self.msg = nn.Linear(cfg.d, cfg.d * dims.ptr, bias=False)

    def forward(self, x, ghost_emb, a: dict, ghost_used, extra: int):
        """x [B, n, d] -> (extended sequence [B, N, d] with messages, bias [B, H, N, N], valid [B, N])."""
        B, n, d = x.shape
        g = ghost_used.shape[1]
        N = n + g + extra
        cd = compute_dtype(x.device)
        ptr_t = a["ptr_dst"].long()                                                   # [B, n, 5], -1 = nothing
        ext = torch.cat([x, ghost_emb[:g].unsqueeze(0).expand(B, g, d).to(x.dtype)], 1)         # [B, n+g, d]
        m = self.msg(ext).view(B, n + g, self.n_ptr, d)
        add = torch.zeros_like(x)
        for k in range(self.n_ptr):
            idx = ptr_t[..., k]
            sel = torch.gather(m[:, :, k], 1, idx.clamp(min=0).unsqueeze(-1).expand(B, n, d))
            add = add + sel * (idx >= 0).unsqueeze(-1).to(sel.dtype)
        x = x + add
        ext = torch.cat([x, ext[:, n:]], 1)
        if extra:
            ext = torch.cat([ext, x.new_zeros(B, extra, d)], 1)                        # memory tokens are filled by the trunk
        H = self.heads
        dst = torch.where(a["edge_dst"] < 0, N, a["edge_dst"].long())                  # [B, n, E]; N never equals a position
        onehot = (dst.unsqueeze(-1) == torch.arange(N, device=x.device)).to(cd)         # [B, n, E, N]
        w = self.bias(a["edge_rel"].long()).to(cd)                                     # [B, n, E, 2H]
        fwd = torch.einsum("bnej,bneh->bnjh", onehot, w[..., :H])
        bwd = torch.einsum("bnej,bneh->bnjh", onehot, w[..., H:])
        bias = F.pad(fwd, (0, 0, 0, 0, 0, N - n)) + F.pad(bwd.transpose(1, 2), (0, 0, 0, N - n))
        valid = torch.cat([a["type_id"] > 0, ghost_used, torch.ones(B, extra, dtype=torch.bool, device=x.device)], 1)
        return ext, bias.permute(0, 3, 1, 2).contiguous(), valid


class Trunk(nn.Module):
    def __init__(self, cfg: StudentConfig):
        super().__init__()
        self.blocks = nn.ModuleList(Block(cfg.d, cfg.heads, cfg.ff, cfg.dropout) for _ in range(cfg.layers))
        self.ln = nn.LayerNorm(cfg.d)
        self.checkpoint = cfg.checkpoint

    def forward(self, x, bias):
        for b in self.blocks:
            if self.checkpoint and self.training and torch.is_grad_enabled():
                x = torch.utils.checkpoint.checkpoint(b, x, bias, use_reentrant=False)
            else:
                x = b(x, bias)
        return self.ln(x)


# ----------------------------------------------------------------------------------------------- pointer heads
class PointerHead(nn.Module):
    """A pointer network over the tokens of the decision (Vinyals 2015) plus learned vectors for the candidates that
    are not tokens: nobody, the directions, the forms, "a new record". Output: logits over `PointerSpace` indices.
    The scale is applied to the query BEFORE the product (a float16 product of unscaled vectors can overflow)."""

    def __init__(self, d: int, space: OutputSpace, extra_ok: np.ndarray, extras: bool = True):
        super().__init__()
        self.P = space.pointers
        self.key = nn.Linear(d, d)
        self.use_extra = extras                                                 # a head that only points at records has no extras
        self.extra = nn.Parameter(torch.randn(self.P.n_extra, d) * 0.02) if self.use_extra else None   # none, dirs, forms, new
        self.register_buffer("extra_ok", torch.as_tensor(extra_ok), persistent=False)
        self.scale = d ** -0.5

    def keys(self, enc: torch.Tensor) -> torch.Tensor:
        return self.key(enc)

    def score(self, q: torch.Tensor, keys: torch.Tensor, slot_ok: torch.Tensor, extra_ok: torch.Tensor | None = None) -> torch.Tensor:
        """q [B, Q, d]; keys [B, n, d]; slot_ok [B, n] or [B, Q, n]; extra_ok [E] or [B, Q, E] -> logits [B, Q, size] (float32)."""
        B, Q, _ = q.shape
        n = keys.shape[1]
        q = q * self.scale
        slots = torch.einsum("bqd,bnd->bqn", q, keys).float()
        if slot_ok.dim() == 2:
            slot_ok = slot_ok.unsqueeze(1)
        slots = slots.masked_fill(~slot_ok, NEG)
        if self.use_extra:
            extra = (q @ self.extra.t().to(q.dtype)).float().masked_fill(~(self.extra_ok if extra_ok is None else extra_ok), NEG)
        else:
            extra = torch.full((B, Q, self.P.n_extra), NEG, dtype=torch.float32, device=q.device)
        pad = torch.full((B, Q, MAX_SLOTS - n), NEG, dtype=torch.float32, device=q.device)
        return torch.cat([extra[:, :, :1], slots, pad, extra[:, :, 1:]], -1)

    def forward(self, q, enc, slot_ok, extra_ok=None):
        return self.score(q, self.keys(enc), slot_ok, extra_ok)


# ----------------------------------------------------------------------------------------------- plan and stop heads (T11)
class PlanHead(nn.Module):
    """The plan the NPC writes (`i_steps` + `i_step_targets` + `i_repeat` + `i_repeat_period` + `g_parent`): a chain of
    `cap` steps (the registry capacity, 8; only the first 6 can be anything but FIN). Step k reads the context, its
    position and the embedding of step k-1 (its gesture and what it points at): a gesture of the registry or FIN, then
    ONE pointer among the records of the types of `PLAN.step_targets`. After FIN everything is FIN. Then the repeat mode,
    its period and the parent goal, conditioned on the whole plan. Same masks in training (the true previous step) and
    in inference (the argmax)."""

    def __init__(self, d: int, space: OutputSpace):
        super().__init__()
        P, sp = space.plan, space
        self.P, self.d = P, d
        self.pos = nn.Embedding(P.cap, d)
        self.chain_start = nn.Parameter(torch.zeros(d))
        self.chain = nn.Linear(d, d)
        self.gesture = nn.Linear(d, P.n_classes)
        self.g_emb = nn.Embedding(P.n_classes, d)
        self.q = nn.Linear(d, d)
        self.ptr = PointerHead(d, space, sp.pointers.extra_mask(none=True))
        self.no_target = nn.Parameter(torch.zeros(d))
        self.summary = nn.Linear(d, d)
        self.repeat = nn.Linear(d, sp.writes.cap_enum)
        self.rep_emb = nn.Embedding(sp.writes.cap_enum, d)
        self.period = nn.Linear(d, len(sp.quantity))
        self.parent_q = nn.Linear(d, d)
        self.parent = PointerHead(d, space, sp.pointers.extra_mask(none=True))
        fin_only = np.full((1, P.n_classes), NEG, np.float32)
        fin_only[0, P.fin] = 0.0
        for name, arr in (("only_fin", fin_only), ("gesture_ok", P.gesture_ok), ("none_ok", P.none_ok), ("step_type_ok", P.step_type_ok),
                          ("repeat_mask", P.repeat_mask), ("parent_type_ok", P.parent_type_ok)):
            self.register_buffer(name, torch.as_tensor(arr), persistent=False)

    def forward(self, hq, enc, ok, tid, T=None) -> dict:
        P = self.P
        B, n, d = enc.shape
        keys, pkeys = self.ptr.keys(enc), self.parent.keys(enc)
        slot_ok = self.step_type_ok[tid] & ok
        prev = self.chain_start.expand(B, d).to(enc.dtype)
        total = torch.zeros_like(prev)
        only_fin = self.only_fin
        fin_prev = torch.zeros(B, dtype=torch.bool, device=enc.device)
        E = self.ptr.P.n_extra
        res = {k: [] for k in ("gesture", "ref", "gesture_choice", "ref_choice")}
        for k in range(P.cap):
            qk = hq + self.chain(prev) + self.pos.weight[k].to(hq.dtype)
            gl = self.gesture(qk).float()
            gl = gl.masked_fill(~self.gesture_ok, NEG) if P.position_ok[k] else only_fin.expand_as(gl)
            gl = torch.where(fin_prev.unsqueeze(1), only_fin.expand_as(gl), gl)
            g = self._pick(gl, None if T is None else T["plan_gesture"][:, k])
            extra_ok = F.pad(self.none_ok[g].view(B, 1, 1), (0, E - 1))
            rl = self.ptr.score(self.q(qk + self.g_emb(g)).unsqueeze(1), keys, slot_ok, extra_ok)[:, 0]
            r = self._pick(rl, None if T is None else T["plan_ref"][:, k])
            is_slot = (r >= 1) & (r <= MAX_SLOTS)
            picked = torch.gather(enc, 1, (r.clamp(1, n) - 1).view(B, 1, 1).expand(-1, 1, d))[:, 0]
            prev = self.g_emb(g) + torch.where(is_slot.unsqueeze(-1), picked, self.no_target.to(picked.dtype).expand_as(picked))
            total = total + prev
            fin_prev = fin_prev | (g == P.fin)
            for name, v in (("gesture", gl), ("ref", rl), ("gesture_choice", g), ("ref_choice", r)):
                res[name].append(v)
        out = {f"plan_{k}": torch.stack(v, 1) for k, v in res.items()}
        hp = hq + self.summary(total)
        rep = self.repeat(hp).float().masked_fill(~self.repeat_mask, NEG)
        rc = self._pick(rep, None if T is None else T["plan_repeat"])
        out["plan_repeat"], out["plan_repeat_choice"] = rep, rc
        out["plan_period"] = self.period(hp + self.rep_emb(rc)).float()
        out["plan_parent"] = self.parent.score(self.parent_q(hp).unsqueeze(1), pkeys, self.parent_type_ok[tid] & ok)[:, 0]
        return out

    @staticmethod
    def _pick(logits, label):
        return logits.argmax(-1) if label is None else label.clamp(min=0)


class StopHead(nn.Module):
    """The stop condition of the DECISION (docs/14 4.3 (2)): the same condition table as `until`, for a gesture that has
    no `until`. One extra class, NONE (= the condition capacity): no condition, the gesture ends by itself. Its own
    weights (the meaning of `until` is tied to a gesture; this one is valid for any gesture that lasts)."""

    def __init__(self, d: int, space: OutputSpace):
        super().__init__()
        C = space.conditions.cap
        self.C, self.d = C, d
        self.cond = nn.Linear(d, C + 1)
        self.emb = nn.Embedding(C + 1, d)
        self.q = nn.Linear(d, 2 * d)
        self.ptr = PointerHead(d, space, space.pointers.extra_mask(), extras=False)
        self.num = nn.Linear(d, 2 * len(space.quantity))
        self.word = nn.Linear(d, 2 * d)
        self.register_buffer("live", torch.as_tensor(np.concatenate([space.conditions.live, [True]])), persistent=False)
        self.register_buffer("type_ok", torch.as_tensor(space.conditions.arg_type_ok), persistent=False)

    def forward(self, hq, enc, ok, tid, word_weight, word_ok, label=None) -> dict:
        B = hq.shape[0]
        cl = self.cond(hq).float().masked_fill(~self.live, NEG)
        c = cl.argmax(-1) if label is None else label.clamp(min=0)
        hc = hq + self.emb(c)
        t = self.type_ok[c.clamp(max=self.C - 1)]                                    # [B, 2, n_types]
        by_type = torch.gather(t, 2, tid.unsqueeze(1).expand(-1, t.shape[1], -1))
        wq = self.word(hc).view(B, 2, -1)
        return {"stop": cl, "stop_choice": c,
                "stop_ref": self.ptr(self.q(hc).view(B, 2, -1), enc, by_type & ok.unsqueeze(1)),
                "stop_num": self.num(hc).float().view(B, 2, -1),
                "stop_word": ((wq * self.d ** -0.5) @ word_weight.t().to(wq.dtype)).float().masked_fill(~word_ok, NEG)}


# ----------------------------------------------------------------------------------------------- the decoder
class SequenceDecoder(nn.Module):
    """Writes a proposition or an utterance as prefix steps (symbol, arity, slot, count). A causal Transformer with
    cross-attention to the trunk output. At step t it reads the previous step (symbol, arity, count, the record the
    pointer designated) and the depth t has reached, and starts from a conditioning vector (what is being written, by
    whom, with which gesture or variable). Masks, the same in training and in inference: the end only when the tree is
    closed, only legal symbols, the arities a symbol can have (language tables of the catalogue), a pointer symbol
    designates only a record of its kind (@E an entity, b: a belief...). In generation, also: the tree must be able to
    close within the symbol budget and the stack is bounded. The grammar AUTOMATON (argument types) is not applied."""

    def __init__(self, cfg: StudentConfig, space: OutputSpace, dims: Dims):
        super().__init__()
        d, S = cfg.d, space.sequences
        self.S, self.steps = S, S.steps
        self.d, self.h = d, cfg.heads
        self.sym = nn.Embedding(S.vocab_size + 2, d)                         # + end class, + start
        self.arity = nn.Embedding(MAX_ARITY, d)
        self.count = nn.Embedding(len(space.counts), d)
        self.depth = nn.Embedding(8, d)
        self.pos = nn.Embedding(S.steps, d)
        self.slot_key = nn.Linear(d, d)
        self.layers = nn.ModuleList(
            nn.ModuleDict(dict(ln1=nn.LayerNorm(d), qkv=nn.Linear(d, 3 * d), o1=nn.Linear(d, d), ln2=nn.LayerNorm(d),
                               q=nn.Linear(d, d), kv=nn.Linear(d, 2 * d), o2=nn.Linear(d, d), ln3=nn.LayerNorm(d),
                               ff=nn.Sequential(nn.Linear(d, cfg.dec_ff), nn.GELU(), nn.Linear(cfg.dec_ff, d))))
            for _ in range(cfg.dec_layers))
        self.ln = nn.LayerNorm(d)
        self.to_sym = nn.Linear(d, d)
        self.arity_head = nn.Linear(d, MAX_ARITY)
        self.count_head = nn.Linear(d, len(space.counts))
        self.slot_q = nn.Linear(d, d)
        for name, arr in (("allowed", S.allowed), ("is_pointer", S.is_pointer), ("pointer_kind_of", S.pointer_kind_of),
                          ("arity_ok", S.arity_ok)):
            self.register_buffer(name, torch.as_tensor(arr), persistent=False)

    # ---- shared pieces
    def step_input(self, prev: dict, depth, pos, init, enc):
        slot_vec = torch.gather(enc, 1, (prev["slot"].clamp(min=1) - 1).unsqueeze(-1).expand(-1, -1, self.d))
        slot_vec = self.slot_key(slot_vec) * (prev["slot"] > 0).unsqueeze(-1).to(slot_vec.dtype)
        return (self.sym(prev["sym"]) + self.arity(prev["arity"]) + self.count(prev["count"]) + slot_vec
                + self.depth(depth.clamp(max=7)) + self.pos(pos) + init.unsqueeze(1))

    def symbol_logits(self, h, step_open, first) -> torch.Tensor:
        """Legal symbols only; the end class when the tree is closed (never before the first symbol)."""
        V = self.S.vocab_size
        logits = (self.to_sym(h) @ self.sym.weight[:V + 1].t().to(h.dtype)).float()
        legal = self.allowed.view(1, 1, -1).expand_as(logits)
        closed = (~step_open) & (~first)
        legal = torch.cat([legal[..., :V] & ~closed.unsqueeze(-1), closed.unsqueeze(-1)], -1)     # end only when closed
        return logits.masked_fill(~legal, NEG)

    def conditioned(self, h, sym, enc, enc_ok, slot_ptrkind, arity_extra=None):
        """Arity, count and slot logits for the symbol chosen at each step. sym [S, T]; slot_ptrkind [S, n]."""
        z = h + self.sym(sym)
        slot = torch.einsum("std,snd->stn", self.slot_q(z) * self.d ** -0.5, self.slot_key(enc)).float()
        kind = self.pointer_kind_of[sym]                                                  # [S, T] -1 for a non-pointer
        same = (slot_ptrkind.unsqueeze(1) == kind.unsqueeze(-1)) | (kind < 0).unsqueeze(-1)
        slot = slot.masked_fill(~(same & enc_ok.unsqueeze(1)), NEG)
        ok = self.arity_ok[sym]
        if arity_extra is not None:
            ok = ok & arity_extra
        return self.arity_head(z).float().masked_fill(~ok, NEG), self.count_head(z).float(), slot

    def _cross(self, enc, ly):
        k, v = ly["kv"](enc).view(enc.shape[0], -1, 2, self.h, self.d // self.h).permute(2, 0, 3, 1, 4)
        return k, v

    # ---- training: all steps at once
    def teacher_forced(self, t: dict, init, enc, enc_ok, slot_ptrkind):
        """t: seq_* targets of the S sequences [S, steps]. -> logits for sym / arity / count / slot."""
        Sn, T = init.shape[0], t["sym"].shape[1]
        start = lambda fill: torch.full((Sn, 1), fill, dtype=torch.long, device=init.device)           # noqa: E731
        sym = t["sym"].clamp(min=0)
        prev = {"sym": torch.cat([start(self.S.bos), sym[:, :-1]], 1),
                "arity": torch.cat([start(0), t["arity"].clamp(min=0)[:, :-1]], 1),
                "count": torch.cat([start(0), t["count"].clamp(min=0)[:, :-1]], 1),
                "slot": torch.cat([start(0), t["slot"].clamp(min=0)[:, :-1]], 1)}
        x = self.step_input(prev, t["depth"].clamp(min=0), torch.arange(T, device=init.device), init, enc)
        cross_mask = enc_ok.view(Sn, 1, 1, -1)
        for ly in self.layers:
            q, k, v = ly["qkv"](ly["ln1"](x)).view(Sn, T, 3, self.h, self.d // self.h).permute(2, 0, 3, 1, 4)
            a = F.scaled_dot_product_attention(q, k, v, is_causal=True)
            x = x + ly["o1"](a.transpose(1, 2).reshape(Sn, T, self.d))
            q = ly["q"](ly["ln2"](x)).view(Sn, T, self.h, self.d // self.h).transpose(1, 2)
            ck, cv = self._cross(enc, ly)
            a = F.scaled_dot_product_attention(q, ck, cv, attn_mask=cross_mask)
            x = x + ly["o2"](a.transpose(1, 2).reshape(Sn, T, self.d))
            x = x + ly["ff"](ly["ln3"](x))
        h = self.ln(x)
        first = torch.zeros_like(t["open"], dtype=torch.bool)
        first[:, 0] = True
        arity, count, slot = self.conditioned(h, sym, enc, enc_ok, slot_ptrkind)
        return {"sym": self.symbol_logits(h, t["open"].bool(), first), "arity": arity, "count": count, "slot": slot}

    # ---- inference: static KV cache, the steps unrolled, fixed shapes
    @torch.no_grad()
    def generate(self, init, enc, enc_ok, slot_ptrkind):
        """Greedy decoding of S sentences with a static KV cache (the 21 steps are unrolled with a fixed shape: no
        data-dependent branch, capturable in a CUDA graph). The stack of open nodes is tracked from the arities (bounded
        by STACK). -> dict of [S, steps] tensors, 'len' [S], 'forced' [S] (the tree did not close on its own)."""
        Sn, dev = init.shape[0], init.device
        L, dh = self.steps, self.d // self.h
        max_symbols = L - 1
        cross = [self._cross(enc, ly) for ly in self.layers]
        cmask = enc_ok.view(Sn, 1, 1, -1)
        kc = [torch.zeros(Sn, self.h, L, dh, dtype=cross[0][0].dtype, device=dev) for _ in self.layers]
        vc = [torch.zeros_like(k) for k in kc]
        z = lambda dt=torch.long: torch.zeros(Sn, dtype=dt, device=dev)                                  # noqa: E731
        prev_sym, prev_ar, prev_ct, prev_sl = torch.full((Sn,), self.S.bos, dtype=torch.long, device=dev), z(), z(), z()
        pending = torch.zeros(Sn, STACK + 1, dtype=torch.long, device=dev)       # children still to come, per open node
        top, done, forced, length = z(), z(torch.bool), z(torch.bool), z()
        rows = torch.arange(Sn, device=dev)
        arities = torch.arange(MAX_ARITY, device=dev)
        positions = torch.arange(L, device=dev)
        outs = {k: [] for k in ("sym", "arity", "count", "slot", "depth")}
        for t in range(L):
            x = self.step_input({"sym": prev_sym[:, None], "arity": prev_ar[:, None], "count": prev_ct[:, None], "slot": prev_sl[:, None]},
                                top[:, None], positions[t:t + 1], init, enc)
            for li, ly in enumerate(self.layers):
                q, k, v = ly["qkv"](ly["ln1"](x)).view(Sn, 1, 3, self.h, dh).permute(2, 0, 3, 1, 4)
                kc[li][:, :, t:t + 1] = k
                vc[li][:, :, t:t + 1] = v
                a = F.scaled_dot_product_attention(q, kc[li][:, :, :t + 1], vc[li][:, :, :t + 1])
                x = x + ly["o1"](a.transpose(1, 2).reshape(Sn, 1, self.d))
                q = ly["q"](ly["ln2"](x)).view(Sn, 1, self.h, dh).transpose(1, 2)
                a = F.scaled_dot_product_attention(q, cross[li][0], cross[li][1], attn_mask=cmask)
                x = x + ly["o2"](a.transpose(1, 2).reshape(Sn, 1, self.d))
                x = x + ly["ff"](ly["ln3"](x))
            h = self.ln(x)
            first = torch.full((Sn, 1), t == 0, dtype=torch.bool, device=dev)
            # the tree must be able to close inside the symbol budget, and the stack stays bounded
            consumed = (top > 0).long()
            after = pending.sum(1, keepdim=True) - consumed.unsqueeze(1) + (arities.unsqueeze(0) - 1).clamp(min=0)
            fits = (after <= (max_symbols - 1 - t)) & ((arities.unsqueeze(0) <= 1) | (top.unsqueeze(1) < STACK))
            # a symbol none of whose arities fits cannot be chosen: near the budget only leaves remain (review 22)
            feasible = (self.arity_ok[:self.S.vocab_size].unsqueeze(0) & fits.unsqueeze(1)).any(-1)
            lg = self.symbol_logits(h, (top > 0).view(Sn, 1), first)[:, 0]
            lg = torch.cat([lg[:, :self.S.vocab_size].masked_fill(~feasible, NEG), lg[:, self.S.vocab_size:]], -1)
            sym = lg.argmax(-1)
            if t == L - 1:
                sym = torch.full_like(sym, self.S.eos)                                   # the last step is the end
            is_end = sym == self.S.eos
            sym_in = sym.clamp(max=self.S.vocab_size - 1)
            ar_l, ct_l, sl_l = self.conditioned(h, sym_in[:, None], enc, enc_ok, slot_ptrkind, fits[:, None, :])
            ar, ct, sl = ar_l[:, 0].argmax(-1), ct_l[:, 0].argmax(-1), sl_l[:, 0].argmax(-1) + 1
            pointer = self.is_pointer[sym_in] & ~is_end
            ar, ct = torch.where(is_end, z(), ar), torch.where(is_end, z(), ct)
            sl = torch.where(pointer, sl, z())
            active = ~done
            for name, v in (("sym", torch.where(active, sym, torch.full_like(sym, self.S.eos))), ("arity", torch.where(active, ar, z())),
                            ("count", torch.where(active, ct, z())), ("slot", torch.where(active, sl, z())), ("depth", top)):
                outs[name].append(v)
            live = active & ~is_end
            length = length + live.long()
            forced = forced | (active & is_end & (top > 0))
            done = done | is_end
            # the stack: this node is a child of the innermost open node ; a head opens a node of its own
            idx = (top - 1).clamp(min=0)
            pending[rows, idx] = pending[rows, idx] - (live & (top > 0)).long()
            push = live & (ar > 1)
            at = top.clamp(max=STACK)
            pending[rows, at] = torch.where(push, ar - 1, pending[rows, at])
            top = top + push.long()
            for _ in range(STACK):                                                     # close the nodes that got their last child
                finished = live & (top > 0) & (pending[rows, (top - 1).clamp(min=0)] == 0)
                top = top - finished.long()
            prev_sym, prev_ar, prev_ct, prev_sl = torch.where(active, sym, prev_sym), ar, ct, sl
        out = {k: torch.stack(v, 1) for k, v in outs.items()}
        out["len"], out["forced"] = length, forced
        return out


# ----------------------------------------------------------------------------------------------- the model
class Outputs(dict):
    """Logits and, in inference, the choices. Attribute access for readability."""

    __getattr__ = dict.__getitem__


class StudentModel(nn.Module):
    def __init__(self, cfg: StudentConfig, space: OutputSpace, memory: NpcMemory | None = None):
        super().__init__()
        self.cfg, self.space = cfg, space
        self.dims = Dims.of(space)
        self.memory = memory or NoMemory()
        if self.memory.n_tokens % 8:
            raise ValueError("a memory hook gives a multiple of 8 tokens (attention kernels)")
        d, sp = cfg.d, space
        self.embed = RecordEmbedder(cfg, self.dims)
        self.graph = PointerGraph(cfg, self.dims)
        self.trunk = Trunk(cfg)
        self.readout_mean = nn.Linear(d, d)
        self.readout_ln = nn.LayerNorm(d)
        P = sp.pointers
        # gesture, pointers, manner
        G = sp.gestures.n
        self.gesture = nn.Linear(d, G)
        self.g_emb = nn.Embedding(G, d)
        self.ref_q = nn.Linear(d, MAX_REFS * d)
        self.ref_pos = nn.Embedding(G * MAX_REFS, d)
        self.ref_ptr = PointerHead(d, sp, P.extra_mask())
        self.manner = nn.Linear(d, sp.manner.total)
        # stop condition
        self.cond = nn.Linear(d, sp.conditions.n)
        self.c_emb = nn.Embedding(sp.conditions.n, d)
        self.cond_q = nn.Linear(d, 2 * d)
        self.cond_ptr = PointerHead(d, sp, P.extra_mask(), extras=False)
        self.cond_num = nn.Linear(d, 2 * len(sp.quantity))
        self.cond_word = nn.Linear(d, 2 * d)
        self.stop = StopHead(d, sp)                                  # T11: the decision's stop condition
        self.plan = PlanHead(d, sp)                                  # T11: the plan the NPC writes
        # writes
        self.n_writes = nn.Linear(d, MAX_WRITES + 1)
        self.chain_start = nn.Parameter(torch.zeros(d))
        self.chain = nn.Linear(d, d)
        self.w_q = nn.Linear(d, d)
        self.w_slot = nn.Embedding(MAX_WRITES, d)
        self.w_ptr = PointerHead(d, sp, P.extra_mask(new=True))
        self.new_vec = nn.Parameter(torch.randn(d) * 0.02)
        self.w_var = nn.Linear(d, sp.writes.n)
        self.v_emb = nn.Embedding(sp.writes.n, d)
        self.w_num = nn.Linear(d, NUM_BINS)
        self.w_enum = nn.Linear(d, sp.writes.cap_enum)
        self.w_qty = nn.Linear(d, len(sp.quantity))
        self.w_val_q = nn.Linear(d, d)
        self.w_val_ptr = PointerHead(d, sp, P.extra_mask(), extras=False)
        # sentences
        self.decoder = SequenceDecoder(cfg, sp, self.dims)
        self.seq_init = nn.Linear(d, d)
        self.seq_role = nn.Embedding(2, d)
        m = sp.manner
        none_col = np.zeros(m.cap_heads, np.int64)
        for h in m.heads:
            none_col[m.head_index[h]] = m.none_index(h)
        cell = np.arange(m.max_width)[None, :]
        for name, arr in (("var_ok", sp.writes.target_ok), ("var_live", sp.writes.live), ("enum_ok", sp.writes.enum_mask),
                          ("var_kind", sp.writes.kind), ("manner_idx", m.gather_index), ("manner_ok", m.gather_ok),
                          ("manner_none_ok", m.none_ok), ("manner_is_none", cell == none_col[:, None]), ("manner_used", m.used),
                          ("cond_live", sp.conditions.live), ("cond_type_ok", sp.conditions.arg_type_ok),
                          ("has_cond", sp.gestures.has_condition), ("has_expr", sp.gestures.has_expression),
                          ("g_live", sp.gestures.live), ("ref_type_ok", sp.gestures.ref_type_ok),
                          ("ref_extra_ok", sp.gestures.ref_extra_ok), ("mref_type_ok", sp.writes.mref_type_ok),
                          ("word_ok", sp.sequences.allowed[:-1]), ("repeat_every", self._repeat_every(sp)), ("kind_last_var", self._last_var(sp))):
            self.register_buffer(name, torch.as_tensor(arr), persistent=False)
        self.reset_parameters()

    @staticmethod
    def _repeat_every(sp: OutputSpace) -> np.ndarray:
        """[enum values] : is this enum value the repeat mode that takes a period ("every")?"""
        return np.array([v == sp.plan.period_mode for v in sp.writes.enum_values], bool)

    @staticmethod
    def _last_var(sp: OutputSpace) -> np.ndarray:
        """For each target kind, the largest variable index that can be written on it (-1 if none)."""
        ok = sp.writes.target_ok & sp.writes.live[None]
        return np.array([int(np.nonzero(row)[0].max()) if row.any() else -1 for row in ok], np.int64)

    def reset_parameters(self) -> None:
        for mod in self.modules():
            if isinstance(mod, nn.Linear):
                nn.init.trunc_normal_(mod.weight, std=0.02)
                if mod.bias is not None:
                    nn.init.zeros_(mod.bias)
            elif isinstance(mod, nn.Embedding):
                nn.init.normal_(mod.weight, std=0.02)
                if mod.padding_idx is not None:
                    mod.weight.data[mod.padding_idx].zero_()
        nn.init.zeros_(self.embed.cat.type_col_gain.weight)
        nn.init.zeros_(self.embed.num.film.weight)
        nn.init.normal_(self.graph.bias.weight, std=0.1)
        for blk in self.trunk.blocks:                              # small residual branches at the start
            nn.init.trunc_normal_(blk.o.weight, std=0.02 / math.sqrt(2 * self.cfg.layers))
            nn.init.trunc_normal_(blk.ff[2].weight, std=0.02 / math.sqrt(2 * self.cfg.layers))

    def n_params(self) -> int:
        return sum(p.numel() for p in self.parameters())

    # ------------------------------------------------------------------------------ encoding
    def encode(self, b):
        a = b.arrays
        x = self.embed(a)
        n = x.shape[1]
        E = self.memory.n_tokens
        ext, bias, valid = self.graph(x, self.embed.ghost, a, b.ghost_used, E)
        if E:
            self_emb = x[torch.arange(b.size, device=x.device), b.self_idx]
            mem = self.memory.read(b.memory, self_emb)
            ext = torch.cat([ext[:, :-E], mem.to(ext.dtype)], 1)
        bias = bias.masked_fill(~valid.view(b.size, 1, 1, -1), -16384.0)               # in the compute dtype, converted once
        h = self.trunk(ext, bias)
        return h, h[:, :n], (a["type_id"] > 0)

    def readout(self, enc, ok, self_idx):
        self_vec = enc[torch.arange(enc.shape[0], device=enc.device), self_idx]
        okf = ok.unsqueeze(-1).to(enc.dtype)
        mean = (enc * okf).sum(1) / okf.sum(1).clamp(min=1)
        return self.readout_ln(self_vec + self.readout_mean(mean))

    @staticmethod
    def _pick(logits, label):
        """Teacher forcing: the label (a safe 0 where there is none). Inference: the argmax."""
        return logits.argmax(-1) if label is None else label.clamp(min=0)

    def _by_type(self, table, index, tid):
        """table[index] is [B, Q, n_types] : the per-record answer for the type of each record -> [B, Q, n]."""
        t = table[index]
        return torch.gather(t, 2, tid.unsqueeze(1).expand(-1, t.shape[1], -1))

    # ------------------------------------------------------------------------------ forward
    def forward(self, b, teacher: bool = True) -> Outputs:
        """teacher=True: every head is conditioned on the true previous choice (targets in `b.targets`) and the
        sentences are scored. teacher=False: conditioned on the model's own argmax (what `predict` does); no sentence."""
        T = b.targets if teacher else None
        sp = self.space
        B = b.size
        h_all, enc, ok = self.encode(b)
        tid = b.arrays["type_id"].long()
        ctx = self.readout(enc, ok, b.self_idx)
        out = Outputs()
        # ---- gesture
        gl = self.gesture(ctx).float().masked_fill(~(b.feasible & self.g_live), NEG)
        g = self._pick(gl, None if T is None else T["gesture"])
        hq = ctx + self.g_emb(g)
        out["gesture"], out["gesture_choice"] = gl, g
        # ---- pointers of the gesture (the k-th pointer parameter reads the k-th query); masks from the gesture table
        q = self.ref_q(hq).view(B, MAX_REFS, -1) + self.ref_pos(g.unsqueeze(-1) * MAX_REFS + torch.arange(MAX_REFS, device=g.device))
        out["ref"] = self.ref_ptr(q, enc, self._by_type(self.ref_type_ok, g, tid) & ok.unsqueeze(1), self.ref_extra_ok[g])
        # ---- manner: the "none" level only for an optional parameter of this gesture
        flat = self.manner(hq).float()
        cells = flat[:, self.manner_idx]                                                            # [B, H, W]
        allowed = self.manner_ok.unsqueeze(0) & (~self.manner_is_none.unsqueeze(0) | self.manner_none_ok[g].unsqueeze(-1))
        out["manner"] = cells.masked_fill(~allowed, NEG)
        # ---- stop condition and its arguments
        cl = self.cond(hq).float().masked_fill(~self.cond_live, NEG)
        c = self._pick(cl, None if T is None else T["cond"])
        hc = hq + self.c_emb(c)
        out["cond"], out["cond_choice"] = cl, c
        out["cond_ref"] = self.cond_ptr(self.cond_q(hc).view(B, 2, -1), enc, self._by_type(self.cond_type_ok, c, tid) & ok.unsqueeze(1))
        out["cond_num"] = self.cond_num(hc).float().view(B, 2, -1)
        wq = self.cond_word(hc).view(B, 2, -1)
        out["cond_word"] = ((wq * self.cfg.d ** -0.5) @ self.embed.cat.emb.weight.t().to(wq.dtype)).float().masked_fill(~self.word_ok, NEG)
        out.update(self.stop(hq, enc, ok, tid, self.embed.cat.emb.weight, self.word_ok, None if T is None else T["stop"]))
        out.update(self.plan(hq, enc, ok, tid, T))
        # ---- writes: a chain of 4 steps, each conditioned on the (target, variable) of the one before
        nw = self.n_writes(hq).float()
        n_w = T["n_writes"] if T is not None else nw.argmax(-1)
        out["n_writes"] = nw
        out.update(self._writes(b, enc, ok, tid, hq, n_w, T))
        out["hq"], out["enc"], out["ok"] = hq, enc, ok
        if self.memory.n_tokens or b.memory is not None:
            out["memory"] = self.memory.write(b.memory, h_all, ok)
        if teacher:
            out["speech"] = self._speech_teacher(b, hq, out["hv"], enc, ok)
        return out

    def _writes(self, b, enc, ok, tid, hq, n_w, T) -> dict:
        sp = self.space
        B, n, d = enc.shape
        W, P = MAX_WRITES, sp.pointers
        keys = self.w_ptr.keys(enc)
        slot_ok = (b.slot_kind > 0) & ok
        prev = self.chain_start.expand(B, d).to(enc.dtype)
        prev_tgt = torch.zeros(B, dtype=torch.long, device=enc.device)
        prev_var = torch.full((B,), -1, dtype=torch.long, device=enc.device)
        prev_kind = torch.zeros(B, dtype=torch.long, device=enc.device)
        cols = torch.arange(P.size, device=enc.device)
        vcols = torch.arange(sp.writes.n, device=enc.device)
        res = {k: [] for k in ("w_target", "w_var", "w_num", "w_enum", "w_qty", "w_ptr", "w_kind", "w_target_choice",
                               "w_var_choice", "hv")}
        for i in range(W):
            active = i < n_w
            qi = self.w_q(hq + self.chain(prev)) + self.w_slot.weight[i]
            tl = self.w_ptr.score(qi.unsqueeze(1), keys, slot_ok)[:, 0]
            if i:
                tl = tl.masked_fill(cols.unsqueeze(0) < prev_tgt.unsqueeze(1), NEG)               # targets do not decrease
                spent = self.kind_last_var[prev_kind] <= prev_var                                   # no variable left on the same target
                tl = tl.masked_fill((cols.unsqueeze(0) == prev_tgt.unsqueeze(1)) & spent.unsqueeze(1), NEG)
            tgt = self._pick(tl, None if T is None else T["w_target"][:, i])
            is_slot = (tgt >= 1) & (tgt <= MAX_SLOTS)
            at = (tgt.clamp(1, n) - 1)
            picked = torch.gather(enc, 1, at.view(B, 1, 1).expand(-1, 1, d))[:, 0]
            sel = torch.where(is_slot.unsqueeze(-1), picked, self.new_vec.to(picked.dtype).expand_as(picked))
            kind = torch.where(is_slot, torch.gather(b.slot_kind, 1, at.unsqueeze(1))[:, 0], torch.full_like(tgt, TargetKind.NEW))
            hw = sel + qi
            vl = self.w_var(hw).float().masked_fill(~(self.var_ok[kind] & self.var_live), NEG)
            if i:                                                                                  # same target: variables increase
                vl = vl.masked_fill((tgt == prev_tgt).unsqueeze(1) & (vcols.unsqueeze(0) <= prev_var.unsqueeze(1)), NEG)
            quiet = torch.full_like(vl, NEG)
            quiet[:, 0] = 0.0
            vl = torch.where(active.unsqueeze(1), vl, quiet)                                       # no write: a fixed, inert choice
            var = self._pick(vl, None if T is None else T["w_var"][:, i])
            hv = hw + self.v_emb(var)
            vq = self.w_val_q(hv)
            res["w_target"].append(tl)
            res["w_var"].append(vl)
            res["w_num"].append(self.w_num(hv).float())
            res["w_enum"].append(self.w_enum(hv).float().masked_fill(~self.enum_ok[var], NEG))
            res["w_qty"].append(self.w_qty(hv).float())
            res["w_ptr"].append(self.w_val_ptr.score(vq.unsqueeze(1), self.w_val_ptr.keys(enc),
                                                      self.mref_type_ok[var].gather(1, tid) & ok)[:, 0])
            res["w_kind"].append(kind)
            res["w_target_choice"].append(tgt)
            res["w_var_choice"].append(var)
            res["hv"].append(hv)
            prev = torch.where(active.unsqueeze(1), hv, prev)
            prev_tgt = torch.where(active, tgt, prev_tgt)
            prev_var = torch.where(active, var, prev_var)
            prev_kind = torch.where(active, kind, prev_kind)
        return {k: torch.stack(v, 1) for k, v in res.items()}

    # ------------------------------------------------------------------------------ sentences
    def _speech_init(self, hq, hv, bi, si):
        base = torch.where((si == 0).unsqueeze(-1), hq[bi], hv[bi, (si - 1).clamp(min=0)])
        return self.seq_init(base) + self.seq_role(torch.clamp(si, max=1))

    def _speech_teacher(self, b, hq, hv, enc, ok):
        T = b.targets
        bi, si, row_ok = b.seq_b, b.seq_s, b.seq_ok
        init = self._speech_init(hq, hv, bi, si)
        pick = lambda name: torch.where(row_ok.view(-1, 1), T[name][bi, si], torch.full_like(T[name][bi, si], NO_LABEL))   # noqa: E731
        t = {"sym": pick("seq_sym"), "arity": pick("seq_arity"), "count": pick("seq_count"), "slot": pick("seq_slot"),
             "depth": T["seq_depth"][bi, si], "open": T["seq_open"][bi, si]}
        logits = self.decoder.teacher_forced(t, init, enc[bi], ok[bi], b.slot_ptrkind[bi])
        logits["targets"] = t
        return logits

    @torch.no_grad()
    def predict(self, b, speech_capacity: int = 8) -> dict:
        """Greedy decision of the model (no targets used). -> dict of tensors shaped like the Targets fields, ready for
        `LabelCodec.decode` (one row per decision). The sentences are written for at most `speech_capacity` (decision,
        sequence) pairs per call, on a fixed-shape buffer (8, 16 or 32); the others are reported in 'speech_overflow'."""
        sp = self.space
        o = self.forward(b, teacher=False)
        B = b.size
        dev = o["gesture"].device
        res = {"gesture": o["gesture_choice"], "ref": o["ref"].argmax(-1)}
        man = o["manner"].argmax(-1)
        res["manner"] = torch.where(self.manner_used[res["gesture"]], man, torch.full_like(man, NO_LABEL))
        res["cond"] = torch.where(self.has_cond[res["gesture"]], o["cond_choice"], torch.full_like(o["cond_choice"], NO_LABEL))
        res["cond_ref"], res["cond_num"], res["cond_word"] = (o[k].argmax(-1) for k in ("cond_ref", "cond_num", "cond_word"))
        has_cond = self.has_cond[res["gesture"]]
        res["stop"] = torch.where(has_cond, torch.full_like(o["stop_choice"], NO_LABEL), o["stop_choice"])
        for k in ("stop_ref", "stop_num", "stop_word"):
            res[k] = o[k].argmax(-1)
        fin = sp.plan.fin
        res["plan_gesture"] = o["plan_gesture_choice"]
        res["plan_ref"] = torch.where(res["plan_gesture"] == fin, torch.full_like(o["plan_ref_choice"], NO_LABEL), o["plan_ref_choice"])
        res["plan_repeat"] = o["plan_repeat_choice"]
        every = self.repeat_every[res["plan_repeat"]]
        res["plan_period"] = torch.where(every, o["plan_period"].argmax(-1), torch.full_like(res["plan_repeat"], NO_LABEL))
        res["plan_parent"] = o["plan_parent"].argmax(-1)
        res["w_target"], res["w_var"] = o["w_target_choice"], o["w_var_choice"]
        # a write whose target or variable had nothing legal left (the mask left only forbidden logits) is not made
        legal = (o["w_var"].gather(-1, res["w_var"].unsqueeze(-1)).squeeze(-1) > -5000) & \
                (o["w_target"].gather(-1, res["w_target"].unsqueeze(-1)).squeeze(-1) > -5000)
        res["n_writes"] = torch.minimum(o["n_writes"].argmax(-1), legal.long().cumprod(1).sum(1))
        res["w_enum"], res["w_num"], res["w_qty"], res["w_ptr"] = (o[k].argmax(-1) for k in ("w_enum", "w_num", "w_qty", "w_ptr"))
        S, L = sp.sequences.MAX_SEQUENCES, sp.sequences.steps
        want = torch.zeros(B, S, dtype=torch.bool, device=dev)
        want[:, 0] = self.has_expr[res["gesture"]]
        is_prop = (self.var_kind[res["w_var"]] == ValueKind.PROP) & (torch.arange(MAX_WRITES, device=dev) < res["n_writes"].unsqueeze(1))
        want[:, 1:] = is_prop
        flat = want.view(-1)
        order = torch.argsort((~flat).to(torch.int8), stable=True)[:speech_capacity]               # the pairs that speak, first
        row_ok = flat[order]
        bi, si = order // S, order % S
        gen = self.decoder.generate(self._speech_init(o["hq"], o["hv"], bi, si), o["enc"][bi], o["ok"][bi], b.slot_ptrkind[bi])
        full = lambda fill, *shape: torch.full((B * S,) + shape, fill, dtype=torch.long, device=dev)   # noqa: E731
        for dst, src in (("seq_sym", "sym"), ("seq_arity", "arity"), ("seq_count", "count"), ("seq_slot", "slot"), ("seq_depth", "depth")):
            buf = full(NO_LABEL, L)
            buf[order] = torch.where(row_ok.unsqueeze(1), gen[src], torch.full_like(gen[src], NO_LABEL))
            res[dst] = buf.view(B, S, L)
        length = full(-1)
        length[order] = torch.where(row_ok, gen["len"], torch.full_like(gen["len"], -1))
        res["seq_len"] = length.view(B, S)
        res["seq_open"] = torch.full((B, S, L), NO_LABEL, dtype=torch.long, device=dev)
        forced = torch.zeros(B * S, dtype=torch.bool, device=dev)
        forced[order] = gen["forced"] & row_ok
        res["seq_forced"] = forced.view(B, S)
        res["speech_overflow"] = want.sum() - row_ok.sum()
        return res
