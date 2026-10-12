"""model.py - the student: a Set Transformer over the records of one decision, factorised heads, an inner-language decoder.

    tokens (tok-2 arrays) -> RecordEmbedder -> PointerGraph (bias per relation, ghosts as tokens) -> Trunk (L blocks)
        -> readout (SELF) -> heads, each conditioned on the choices before it:
           gesture (feasibility mask) -> pointers of that gesture -> shared manner heads -> stop condition (+ arguments)
           -> number of writes -> per write: target -> variable -> value -> speech / propositions by the SequenceDecoder.

Training is teacher-forced (`forward(batch)` conditions every head on the TRUE previous choice); inference
(`predict(batch)`) conditions on the model's own argmax and writes the sequences token by token. The two paths share
every module, so a head cannot be trained on something it will not see.

Reused from ai/research/arch/arch_common.py (measured there): FiLM-by-type number encoder, folded field binding,
Graphormer-style bias per (relation, direction, head) with learned ghost tokens, pre-LN blocks on SDPA with an
additive bias, the delta-rule memory slot (as a hook only). The blocks are re-written against the live tok-2 sizes
instead of the golden layout so they follow the tokenizer.
"""
from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

from .spec import MAX_ARITY, MAX_REFS, MAX_SLOTS, MAX_WRITES, NO_LABEL, NUM_BINS, OutputSpace, TargetKind, ValueKind

GHOSTS = 33                     # ghost tokens: 32 numbered + the overflow one (tok-2: pointers 129..161)
GHOST_ROWS = 40                 # padded to a multiple of 8
GHOST_BASE = 129
NEG = -1e4                      # a "forbidden" logit (float32 logits: finite, so a fully masked row stays finite)


# ----------------------------------------------------------------------------------------------- configuration
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

    def to_dict(self) -> dict:
        return dict(self.__dict__)


SIZES = {
    "tiny": StudentConfig("tiny", 64, 2, 4, 128, 32, 2, 1, 128),                 # tests, CPU
    "small": StudentConfig("small", 256, 6, 8, 1024, 128, 4, 2, 1024),            # docs/09: d256 x 6
    "base": StudentConfig("base", 384, 8, 8, 1536, 192, 4, 3, 1536),              # docs/09: d384 x 8
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

    The trunk asks `read(state, self_embedding)` for `n_tokens` extra tokens that it prepends to the sequence, and
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
    sum_c E[id_c] * (1 + G_col[c] + G_type_col[type, c]) over the columns that are known and non-empty. The same word in
    two fields (tok-2 has one id space) therefore does not look the same. Only the filled entries are computed
    (about 8 of 38 per record): a gather, not a [B, T, 38, d] tensor."""

    def __init__(self, d: int, dims: Dims):
        super().__init__()
        self.dims = dims
        self.emb = nn.Embedding(dims.vocab, d, padding_idx=0)
        self.col_gain = nn.Parameter(torch.zeros(dims.cat, d))
        self.type_col_gain = nn.Embedding(dims.n_types * dims.cat, d)
        nn.init.zeros_(self.type_col_gain.weight)

    def forward(self, cat, cat_known, type_id):
        B, n, C = cat.shape
        on = (cat > 0) & (cat_known > 0)
        b, t, c = on.nonzero(as_tuple=True)
        ids = cat[b, t, c]
        gain = 1 + self.col_gain[c] + self.type_col_gain(type_id[b, t] * C + c)
        e = self.emb(ids) * gain
        out = torch.zeros(B * n, e.shape[-1], dtype=e.dtype, device=cat.device)
        out.index_add_(0, b * n + t, e)
        return out.view(B, n, -1)


class NumberEncoder(nn.Module):
    """[num, known, cat_known, ptr_known] -> d, an MLP whose hidden layer is modulated by the token TYPE (FiLM): the
    same column is a different field in each type. Unknown stays unknown: the flags go in beside the values."""

    def __init__(self, d: int, dims: Dims):
        super().__init__()
        self.l1 = nn.Linear(2 * dims.num + dims.cat + dims.ptr, d)
        self.l2 = nn.Linear(d, d)
        self.film = nn.Embedding(dims.n_types, 2 * d)
        nn.init.zeros_(self.film.weight)

    def forward(self, num, known, cat_known, ptr_known, type_id):
        s, b = self.film(type_id).chunk(2, -1)
        x = torch.cat([num, known.to(num.dtype), cat_known.to(num.dtype), ptr_known.to(num.dtype)], -1).to(self.l1.weight.dtype)
        return self.l2(F.gelu(self.l1(x) * (1 + s) + b))


class PropositionEncoder(nn.Module):
    """A small Transformer over the <= 20 prefix symbols of a record's proposition. Each position carries: the symbol,
    its place in the sentence, its arity, its depth in the tree, the slot it designates (a pointer: which record, or
    which ghost - the same identity the trunk sees) and its count. Mean-pooled and projected into the token."""

    def __init__(self, d: int, dp: int, heads: int, dims: Dims):
        super().__init__()
        self.sym = nn.Embedding(dims.vocab, dp, padding_idx=0)
        self.pos = nn.Embedding(dims.prop_len, dp)
        self.arity = nn.Embedding(MAX_ARITY, dp)
        self.depth = nn.Embedding(8, dp)
        self.slot = nn.Embedding(GHOST_BASE + GHOSTS, dp, padding_idx=0)
        self.count = nn.Linear(1, dp, bias=False)
        self.block = nn.TransformerEncoderLayer(dp, heads, 2 * dp, dropout=0.0, batch_first=True, norm_first=True)
        self.out = nn.Linear(dp, d)

    def forward(self, prop_sym, prop_arity, prop_depth, prop_slot, prop_num):
        B, n, P = prop_sym.shape
        rows = (prop_sym[..., 0] > 0).nonzero(as_tuple=True)            # records that carry a proposition
        if rows[0].numel() == 0:
            return prop_sym.new_zeros(B, n, self.out.out_features, dtype=torch.float32)
        s = prop_sym[rows]
        valid = s > 0
        pos = torch.arange(P, device=s.device)
        x = (self.sym(s) + self.pos(pos) + self.arity(prop_arity[rows].clamp(max=MAX_ARITY - 1))
             + self.depth(prop_depth[rows].clamp(max=7)) + self.slot(prop_slot[rows])
             + self.count(prop_num[rows].unsqueeze(-1).to(self.count.weight.dtype)))
        h = self.block(x, src_key_padding_mask=~valid)
        v = valid.unsqueeze(-1).to(h.dtype)
        pooled = self.out((h * v).sum(1) / v.sum(1))
        out = torch.zeros(B * n, pooled.shape[-1], dtype=pooled.dtype, device=s.device)
        out.index_copy_(0, rows[0] * n + rows[1], pooled)
        return out.view(B, n, -1)


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
        x = (self.type_emb(tid) + self.cat(a["cat"].long(), a["cat_known"], tid)
             + self.num(a["num"], a["known"], a["cat_known"], a["ptr_known"], tid)
             + self.prop(a["prop_sym"].long(), a["prop_arity"].long(), a["prop_depth"].long(), a["prop_slot"].long(),
                         a["prop_num"]))
        return self.ln(x) * (tid > 0).unsqueeze(-1).to(x.dtype)


# ----------------------------------------------------------------------------------------------- the graph
class PointerGraph(nn.Module):
    """The ego-graph of what the NPC believes: the 5 pointer columns of a record and the slots inside its proposition.
    Per (type, column) relation and direction a learned bias per head biases the attention (Graphormer), and the
    pointed record sends a message to the pointer (first-layer message passing). A pointer to a record that is not in
    the decision goes to a GHOST: a learned token appended to the sequence, attendable, whose identity is the
    identity of that record (two pointers to the same record meet at the same ghost)."""

    def __init__(self, cfg: StudentConfig, dims: Dims):
        super().__init__()
        self.dims, self.heads = dims, cfg.heads
        self.n_ptr = dims.ptr
        self.rel_ptr = dims.n_types * dims.ptr
        self.bias = nn.Embedding(dims.n_types * (dims.ptr + 1), 2 * cfg.heads)
        nn.init.normal_(self.bias.weight, std=0.1)
        self.msg = nn.Linear(cfg.d, cfg.d * dims.ptr, bias=False)

    def target_index(self, slots: torch.Tensor, n: int, sink: int) -> torch.Tensor:
        """tok-2 slot (0 none, 1..128 token, 129..161 ghost) -> position in [tokens | ghosts], `sink` for none."""
        s = slots.long()
        ghost = n + (s - GHOST_BASE).clamp(0, GHOSTS - 1)
        return torch.where(s == 0, torch.full_like(s, sink), torch.where(s <= MAX_SLOTS, s - 1, ghost))

    def forward(self, x, ghost_emb, a: dict, ghost_used, extra: int):
        """x [B, n, d] -> (x with messages, extended sequence [B, N, d], bias [B, H, N, N], valid [B, N])."""
        B, n, d = x.shape
        g = ghost_used.shape[1]
        N = n + g + extra
        tid = a["type_id"].long()
        ptr_t = self.target_index(a["ptr"], n, N)                                      # [B, n, 5], N = nothing
        prop_t = self.target_index(a["prop_slot"], n, N)                               # [B, n, 20]
        ext = torch.cat([x, ghost_emb[:g].unsqueeze(0).expand(B, g, d).to(x.dtype)], 1)       # [B, n+g, d]
        # messages from the pointed record (or ghost) into the pointer
        m = self.msg(ext).view(B, n + g, self.n_ptr, d)
        add = x.new_zeros(B, n, d)
        for k in range(self.n_ptr):
            has = ptr_t[..., k] < N
            idx = ptr_t[..., k].clamp(max=n + g - 1)
            sel = torch.gather(m[:, :, k], 1, idx.unsqueeze(-1).expand(B, n, d))
            add = add + sel * has.unsqueeze(-1).to(sel.dtype)
        x = x + add
        ext = torch.cat([x, ext[:, n:]], 1)
        if extra:
            ext = torch.cat([ext, x.new_zeros(B, extra, d)], 1)                        # memory tokens are filled by the trunk
        # attention bias: edge (i -> target) in relation (type of i, column), forward and backward
        H = self.heads
        rel_p = tid.unsqueeze(-1) * self.n_ptr + torch.arange(self.n_ptr, device=x.device)          # [B, n, 5]
        rel_q = self.rel_ptr + tid.unsqueeze(-1).expand(B, n, prop_t.shape[-1])                     # [B, n, 20]
        rel = torch.cat([rel_p, rel_q], -1)
        dst = torch.cat([ptr_t, prop_t], -1)                                                       # [B, n, E]
        w = self.bias(rel).float()                                                                  # [B, n, E, 2H]
        fwd = x.new_zeros(B, n, N + 1, H, dtype=torch.float32)
        bwd = x.new_zeros(B, n, N + 1, H, dtype=torch.float32)
        fwd.scatter_add_(2, dst.unsqueeze(-1).expand(-1, -1, -1, H), w[..., :H])
        bwd.scatter_add_(2, dst.unsqueeze(-1).expand(-1, -1, -1, H), w[..., H:])
        bias = x.new_zeros(B, N, N, H, dtype=torch.float32)
        bias[:, :n] += fwd[:, :, :N]
        bias[:, :, :n] += bwd[:, :, :N].transpose(1, 2)
        valid = torch.cat([tid > 0, ghost_used, torch.ones(B, extra, dtype=torch.bool, device=x.device)], 1)
        bias = bias.permute(0, 3, 1, 2).contiguous()
        return ext, bias, valid


# ----------------------------------------------------------------------------------------------- trunk
class Block(nn.Module):
    """Pre-LN Transformer block on scaled_dot_product_attention with an additive bias."""

    def __init__(self, d: int, h: int, ff: int):
        super().__init__()
        self.h = h
        self.ln1, self.ln2 = nn.LayerNorm(d), nn.LayerNorm(d)
        self.qkv, self.o = nn.Linear(d, 3 * d), nn.Linear(d, d)
        self.ff = nn.Sequential(nn.Linear(d, ff), nn.GELU(), nn.Linear(ff, d))

    def forward(self, x, bias):
        B, N, D = x.shape
        q, k, v = self.qkv(self.ln1(x)).view(B, N, 3, self.h, D // self.h).permute(2, 0, 3, 1, 4)
        a = F.scaled_dot_product_attention(q, k, v, attn_mask=bias.to(q.dtype))
        x = x + self.o(a.transpose(1, 2).reshape(B, N, D))
        return x + self.ff(self.ln2(x))


class Trunk(nn.Module):
    def __init__(self, cfg: StudentConfig):
        super().__init__()
        self.blocks = nn.ModuleList(Block(cfg.d, cfg.heads, cfg.ff) for _ in range(cfg.layers))
        self.ln = nn.LayerNorm(cfg.d)

    def forward(self, x, bias):
        for b in self.blocks:
            x = b(x, bias)
        return self.ln(x)


# ----------------------------------------------------------------------------------------------- pointer heads
class PointerHead(nn.Module):
    """A pointer network over the tokens of the decision (Vinyals 2015) plus learned vectors for the candidates that
    are not tokens: nobody, the directions, the forms, "a new record". Output: logits over `PointerSpace` indices."""

    def __init__(self, d: int, space: OutputSpace, extra_ok: np.ndarray):
        super().__init__()
        self.P = space.pointers
        self.key = nn.Linear(d, d)
        self.extra = nn.Parameter(torch.randn(self.P.size - MAX_SLOTS, d) * 0.02)       # none, dirs, forms, new
        self.register_buffer("extra_ok", torch.as_tensor(extra_ok), persistent=False)
        self.scale = d ** -0.5

    def forward(self, q: torch.Tensor, enc: torch.Tensor, slot_ok: torch.Tensor) -> torch.Tensor:
        """q [B, Q, d]; enc [B, n, d]; slot_ok [B, n] or [B, Q, n] -> logits [B, Q, size] (float32)."""
        B, Q, _ = q.shape
        n = enc.shape[1]
        slots = torch.einsum("bqd,bnd->bqn", q, self.key(enc)).float() * self.scale
        extra = (q @ self.extra.t().to(q.dtype)).float() * self.scale                      # [B, Q, E]
        if slot_ok.dim() == 2:
            slot_ok = slot_ok.unsqueeze(1)
        slots = slots.masked_fill(~slot_ok, NEG)
        extra = extra.masked_fill(~self.extra_ok, NEG)
        out = q.new_full((B, Q, self.P.size), NEG, dtype=torch.float32)
        out[:, :, 0] = extra[:, :, 0]
        out[:, :, 1:1 + n] = slots
        out[:, :, MAX_SLOTS + 1:] = extra[:, :, 1:]
        return out


# ----------------------------------------------------------------------------------------------- the decoder
class SequenceDecoder(nn.Module):
    """Writes a proposition or an utterance as prefix steps (symbol, arity, slot, count). A causal Transformer with
    cross-attention to the trunk output. At step t it reads the previous step (symbol, arity, count, the record the
    pointer designated) and the depth t has reached, and starts from a conditioning vector (what is being written, by
    whom, with which gesture or variable). Structural masks (end only when the tree is closed, only legal symbols)
    are the same in training and in inference; the grammar automaton of the catalogue is NOT applied yet."""

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
        self.role = nn.Embedding(2, d)                                       # 0 speech, 1 proposition written
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
        self.register_buffer("allowed", torch.as_tensor(S.allowed), persistent=False)       # [V + 1]
        self.register_buffer("is_pointer", torch.as_tensor(S.is_pointer), persistent=False)  # [V + 2]

    # ---- the stack of decoded steps -> the inputs of the step
    def hidden(self, prev: dict, depth, init, enc, enc_ok):
        """prev: sym/arity/count/slot of the step BEFORE each position [S, T]; depth [S, T]; init [S, d];
        enc [S, n, d] (keys of the cross-attention); enc_ok [S, n]. -> hidden [S, T, d]."""
        Sn, T = prev["sym"].shape
        pos = torch.arange(T, device=init.device)
        slot_vec = torch.gather(enc, 1, (prev["slot"].clamp(min=1) - 1).unsqueeze(-1).expand(-1, -1, self.d))
        slot_vec = self.slot_key(slot_vec) * (prev["slot"] > 0).unsqueeze(-1).to(slot_vec.dtype)
        x = (self.sym(prev["sym"]) + self.arity(prev["arity"]) + self.count(prev["count"]) + slot_vec
             + self.depth(depth.clamp(max=7)) + self.pos(pos) + init.unsqueeze(1))
        cross_mask = enc_ok.view(Sn, 1, 1, -1)
        for ly in self.layers:
            q, k, v = ly["qkv"](ly["ln1"](x)).view(Sn, T, 3, self.h, self.d // self.h).permute(2, 0, 3, 1, 4)
            a = F.scaled_dot_product_attention(q, k, v, is_causal=True)
            x = x + ly["o1"](a.transpose(1, 2).reshape(Sn, T, self.d))
            q = ly["q"](ly["ln2"](x)).view(Sn, T, self.h, self.d // self.h).transpose(1, 2)
            k, v = ly["kv"](enc).view(Sn, -1, 2, self.h, self.d // self.h).permute(2, 0, 3, 1, 4)
            a = F.scaled_dot_product_attention(q, k, v, attn_mask=cross_mask)
            x = x + ly["o2"](a.transpose(1, 2).reshape(Sn, T, self.d))
            x = x + ly["ff"](ly["ln3"](x))
        return self.ln(x)

    def symbol_logits(self, h, step_open, first) -> torch.Tensor:
        """Legal symbols only; the end class when the tree is closed (never before the first symbol)."""
        V = self.S.vocab_size
        logits = (self.to_sym(h) @ self.sym.weight[:V + 1].t().to(h.dtype)).float()
        legal = self.allowed.view(1, 1, -1).expand_as(logits).clone()
        closed = (~step_open) & (~first)
        legal[..., V] = closed                                                   # end: only when closed (and not at step 0)
        legal[..., :V] &= ~closed.unsqueeze(-1)                                  # a closed tree takes nothing more
        return logits.masked_fill(~legal, NEG)

    def conditioned(self, h, sym, enc, enc_ok):
        """Arity, count and slot logits for the symbol chosen at each step."""
        z = h + self.sym(sym)
        slot = torch.einsum("std,snd->stn", self.slot_q(z), self.slot_key(enc)).float() * self.d ** -0.5
        return self.arity_head(z).float(), self.count_head(z).float(), slot.masked_fill(~enc_ok.unsqueeze(1), NEG)

    def teacher_forced(self, t: dict, init, enc, enc_ok):
        """t: seq_* targets of the S sequences [S, steps]. -> logits for sym / arity / count / slot."""
        Sn = init.shape[0]
        start = lambda fill, dt: torch.full((Sn, 1), fill, dtype=dt, device=init.device)           # noqa: E731
        sym = t["sym"].clamp(min=0)
        prev = {"sym": torch.cat([start(self.S.bos, torch.long), sym[:, :-1]], 1),
                "arity": torch.cat([start(0, torch.long), t["arity"].clamp(min=0)[:, :-1]], 1),
                "count": torch.cat([start(0, torch.long), t["count"].clamp(min=0)[:, :-1]], 1),
                "slot": torch.cat([start(0, torch.long), t["slot"].clamp(min=0)[:, :-1]], 1)}
        h = self.hidden(prev, t["depth"].clamp(min=0), init, enc, enc_ok)
        first = torch.zeros_like(t["open"], dtype=torch.bool)
        first[:, 0] = True
        sym_logits = self.symbol_logits(h, t["open"].bool(), first)
        arity, count, slot = self.conditioned(h, sym, enc, enc_ok)
        return {"sym": sym_logits, "arity": arity, "count": count, "slot": slot}

    @torch.no_grad()
    def generate(self, init, enc, enc_ok):
        """Greedy decoding with the stack tracked from the arities. -> dict of [S, steps] tensors + 'len' [S]."""
        Sn, dev = init.shape[0], init.device
        L = self.steps
        out = {k: torch.zeros(Sn, L, dtype=torch.long, device=dev) for k in ("sym", "arity", "count", "slot", "depth")}
        out["sym"].fill_(self.S.eos)
        prev = {"sym": torch.full((Sn, 1), self.S.bos, dtype=torch.long, device=dev), "arity": torch.zeros(Sn, 1, dtype=torch.long, device=dev),
                "count": torch.zeros(Sn, 1, dtype=torch.long, device=dev), "slot": torch.zeros(Sn, 1, dtype=torch.long, device=dev)}
        depth = torch.zeros(Sn, 1, dtype=torch.long, device=dev)
        pending = torch.zeros(Sn, L + 1, dtype=torch.long, device=dev)   # children still to come per open node (<= one per step)
        top = torch.zeros(Sn, dtype=torch.long, device=dev)               # number of open nodes
        done = torch.zeros(Sn, dtype=torch.bool, device=dev)
        lengths = torch.zeros(Sn, dtype=torch.long, device=dev)
        rows = torch.arange(Sn, device=dev)
        for t in range(L):
            h = self.hidden({k: v for k, v in prev.items()}, depth, init, enc, enc_ok)[:, -1:]
            is_open = (top > 0).view(Sn, 1)
            first = torch.full((Sn, 1), t == 0, dtype=torch.bool, device=dev)
            sym = self.symbol_logits(h, is_open, first)[:, 0].argmax(-1)
            if t == L - 1:
                sym = torch.full_like(sym, self.S.eos)                    # the last step is the end
            sym_in = sym.clamp(max=self.S.vocab_size - 1)
            ar, ct, sl = self.conditioned(h, sym_in.unsqueeze(1), enc, enc_ok)
            ar, ct, sl = ar[:, 0].argmax(-1), ct[:, 0].argmax(-1), sl[:, 0].argmax(-1) + 1
            is_end = sym == self.S.eos
            ptr = self.is_pointer[sym_in] & ~is_end
            ar = torch.where(is_end, torch.zeros_like(ar), ar)
            ct = torch.where(is_end, torch.zeros_like(ct), ct)
            sl = torch.where(ptr, sl, torch.zeros_like(sl))
            active = ~done
            out["sym"][:, t] = torch.where(active, sym, torch.full_like(sym, self.S.eos))
            for k, v in (("arity", ar), ("count", ct), ("slot", sl)):
                out[k][:, t] = torch.where(active, v, torch.zeros_like(v))
            out["depth"][:, t] = top
            lengths = lengths + (active & ~is_end).long()
            done = done | is_end
            # the stack: this node is a child of the innermost open node ; a head opens a node of its own
            live = active & ~is_end
            idx = (top - 1).clamp(min=0)
            pending[rows, idx] = pending[rows, idx] - (live & (top > 0)).long()
            push = live & (ar > 1)
            slot_at = top.clamp(max=pending.shape[1] - 1)
            pending[rows, slot_at] = torch.where(push, ar - 1, pending[rows, slot_at])
            top = top + push.long()
            for _ in range(MAX_ARITY):                                     # close the nodes that got their last child
                finished = live & (top > 0) & (pending[rows, (top - 1).clamp(min=0)] == 0)
                top = top - finished.long()
            prev = {k: torch.cat([prev[k], v[:, t:t + 1]], 1) for k, v in
                    (("sym", out["sym"]), ("arity", out["arity"]), ("count", out["count"]), ("slot", out["slot"]))}
            depth = torch.cat([depth, top.view(Sn, 1)], 1)
        out["len"] = lengths
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
        masks = sp.pointers.masks()
        # heads
        G = sp.gestures.n
        self.gesture = nn.Linear(d, G)
        self.g_emb = nn.Embedding(G, d)
        self.ref_q = nn.Linear(d, MAX_REFS * d)
        self.ref_pos = nn.Embedding(G * MAX_REFS, d)
        self.ref_ptr = PointerHead(d, sp, masks["ref"])
        self.manner = nn.Linear(d, sp.manner.total)
        self.cond = nn.Linear(d, sp.conditions.n)
        self.c_emb = nn.Embedding(sp.conditions.n, d)
        self.cond_q = nn.Linear(d, 2 * d)
        self.cond_ptr = PointerHead(d, sp, masks["slot_only"])
        self.cond_num = nn.Linear(d, 2 * len(sp.quantity))
        self.cond_word = nn.Linear(d, 2 * d)
        self.n_writes = nn.Linear(d, MAX_WRITES + 1)
        self.w_q = nn.Linear(d, d)
        self.w_slot = nn.Embedding(MAX_WRITES, d)
        self.w_ptr = PointerHead(d, sp, masks["write_target"])
        self.new_vec = nn.Parameter(torch.randn(d) * 0.02)
        self.w_var = nn.Linear(d, sp.writes.n)
        self.v_emb = nn.Embedding(sp.writes.n, d)
        self.w_num = nn.Linear(d, NUM_BINS)
        self.w_enum = nn.Linear(d, len(sp.writes.enum_values))
        self.w_qty = nn.Linear(d, len(sp.quantity))
        self.w_val_q = nn.Linear(d, d)
        self.w_val_ptr = PointerHead(d, sp, masks["slot_only"])
        self.decoder = SequenceDecoder(cfg, sp, self.dims)
        self.seq_init = nn.Linear(d, d)
        self.seq_role = nn.Embedding(2, d)
        for name, arr in (("var_ok", sp.writes.target_ok), ("enum_ok", sp.writes.enum_mask),
                          ("var_kind", sp.writes.kind), ("manner_idx", sp.manner.gather_index),
                          ("manner_ok", sp.manner.gather_ok), ("cond_kind", sp.conditions.arg_kind),
                          ("has_cond", sp.gestures.has_condition), ("has_expr", sp.gestures.has_expression),
                          ("ref_valid", sp.gestures.ref_valid)):
            self.register_buffer(name, torch.as_tensor(arr), persistent=False)
        self.reset_parameters()

    def reset_parameters(self) -> None:
        for m in self.modules():
            if isinstance(m, nn.Linear):
                nn.init.trunc_normal_(m.weight, std=0.02)
                if m.bias is not None:
                    nn.init.zeros_(m.bias)
        for m in self.modules():
            if isinstance(m, nn.Embedding):
                nn.init.normal_(m.weight, std=0.02)
                if m.padding_idx is not None:
                    m.weight.data[m.padding_idx].zero_()
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
        neg = torch.finfo(torch.float16).min / 4
        bias = bias.masked_fill(~valid.view(b.size, 1, 1, -1), neg)
        h = self.trunk(ext, bias)
        enc = h[:, :n]
        return h, enc, (a["type_id"] > 0)

    def readout(self, enc, ok, self_idx):
        self_vec = enc[torch.arange(enc.shape[0], device=enc.device), self_idx]
        okf = ok.unsqueeze(-1).to(enc.dtype)
        mean = (enc * okf).sum(1) / okf.sum(1).clamp(min=1)
        return self.readout_ln(self_vec + self.readout_mean(mean))

    @staticmethod
    def _pick(logits, label):
        """Teacher forcing: the label (a safe 0 where there is none). Inference: the argmax."""
        if label is None:
            return logits.argmax(-1)
        return label.clamp(min=0)

    # ------------------------------------------------------------------------------ forward
    def forward(self, b, teacher: bool = True) -> Outputs:
        """teacher=True: every head is conditioned on the true previous choice (targets in `b.targets`).
        teacher=False: on the model's own argmax (what `predict` does); the speech is then NOT run here."""
        T = b.targets if teacher else None
        sp = self.space
        B = b.size
        h_all, enc, ok = self.encode(b)
        ctx = self.readout(enc, ok, b.self_idx)
        out = Outputs()
        # ---- gesture
        gl = self.gesture(ctx).float().masked_fill(~b.feasible, NEG)
        g = self._pick(gl, None if T is None else T["gesture"])
        hq = ctx + self.g_emb(g)
        out["gesture"] = gl
        out["gesture_choice"] = g
        # ---- pointers of the gesture (the k-th pointer parameter reads the k-th query)
        q = self.ref_q(hq).view(B, MAX_REFS, -1) + self.ref_pos(g.unsqueeze(-1) * MAX_REFS + torch.arange(MAX_REFS, device=g.device))
        out["ref"] = self.ref_ptr(q, enc, ok)
        # ---- manner
        flat = self.manner(hq).float()
        out["manner"] = flat[:, self.manner_idx].masked_fill(~self.manner_ok, NEG)           # [B, H, Wmax]
        # ---- stop condition and its arguments
        cl = self.cond(hq).float()
        c = self._pick(cl, None if T is None else T["cond"])
        hc = hq + self.c_emb(c)
        qa = self.cond_q(hc).view(B, 2, -1)
        out["cond"] = cl
        out["cond_choice"] = c
        out["cond_ref"] = self.cond_ptr(qa, enc, ok)
        out["cond_num"] = self.cond_num(hc).float().view(B, 2, -1)
        wq = self.cond_word(hc).view(B, 2, -1)
        words = (wq @ self.embed.cat.emb.weight.t().to(wq.dtype)).float()                         # tied with the input words
        out["cond_word"] = words.masked_fill(~self.decoder.allowed[:-1].view(1, 1, -1), NEG)
        # ---- writes
        nw = self.n_writes(hq).float()
        out["n_writes"] = nw
        qw = self.w_q(hq).unsqueeze(1) + self.w_slot.weight.unsqueeze(0)                        # [B, W, d]
        tgt_ok = b.slot_kind > 0
        tl = self.w_ptr(qw, enc, tgt_ok)
        tgt = self._pick(tl, None if T is None else T["w_target"])
        out["w_target"] = tl
        is_slot = (tgt >= 1) & (tgt <= MAX_SLOTS)
        picked = torch.gather(enc, 1, (tgt.clamp(1, enc.shape[1]) - 1).unsqueeze(-1).expand(-1, -1, enc.shape[-1]))
        sel = torch.where(is_slot.unsqueeze(-1), picked, self.new_vec.to(picked.dtype).expand_as(picked))
        kind = torch.where(is_slot, torch.gather(b.slot_kind, 1, (tgt.clamp(1, enc.shape[1]) - 1)),
                           torch.full_like(tgt, TargetKind.NEW))
        hw = sel + qw
        vl = self.w_var(hw).float().masked_fill(~self.var_ok[kind], NEG)
        var = self._pick(vl, None if T is None else T["w_var"])
        out["w_var"] = vl
        hv = hw + self.v_emb(var)
        out["w_num"] = self.w_num(hv).float()
        out["w_enum"] = self.w_enum(hv).float().masked_fill(~self.enum_ok[var], NEG)
        out["w_qty"] = self.w_qty(hv).float()
        out["w_ptr"] = self.w_val_ptr(self.w_val_q(hv), enc, ok)
        out["w_kind"] = kind
        out["w_var_choice"] = var
        out["w_target_choice"] = tgt
        out["hv"] = hv
        out["hq"] = hq
        out["enc"] = enc
        out["ok"] = ok
        if self.memory.n_tokens or b.memory is not None:
            out["memory"] = self.memory.write(b.memory, h_all, ok)
        if teacher:
            out.update(self._speech_teacher(b, hq, hv, enc, ok))
        return out

    # ------------------------------------------------------------------------------ speech
    def _speech_init(self, hq, hv, sel, role):
        base = torch.where(role.unsqueeze(-1) == 0, hq[sel[0]], hv[sel[0], (sel[1] - 1).clamp(min=0)])
        return self.seq_init(base) + self.seq_role(torch.clamp(role, max=1))

    def _speech_teacher(self, b, hq, hv, enc, ok):
        T = b.targets
        present = T["seq_len"] >= 0                                   # [B, S]
        bi, si = present.nonzero(as_tuple=True)
        if bi.numel() == 0:
            return {"speech": None}
        init = self._speech_init(hq, hv, (bi, si), si)
        t = {"sym": T["seq_sym"][bi, si], "arity": T["seq_arity"][bi, si], "count": T["seq_count"][bi, si],
             "slot": T["seq_slot"][bi, si], "depth": T["seq_depth"][bi, si], "open": T["seq_open"][bi, si]}
        logits = self.decoder.teacher_forced(t, init, enc[bi], ok[bi])
        logits["index"] = (bi, si)
        return {"speech": logits}

    @torch.no_grad()
    def predict(self, b) -> dict:
        """Greedy decision of the model (no targets used). -> dict of tensors shaped like the Targets fields, ready for
        `LabelCodec.decode` (one row per decision)."""
        sp = self.space
        o = self.forward(b, teacher=False)
        B = b.size
        dev = o["gesture"].device
        res = {"gesture": o["gesture_choice"]}
        res["ref"] = o["ref"].argmax(-1)
        man = o["manner"].argmax(-1)
        res["manner"] = torch.where(self.manner_used(res["gesture"]), man, torch.full_like(man, NO_LABEL))
        res["cond"] = torch.where(self.has_cond[res["gesture"]], o["cond_choice"], torch.full_like(o["cond_choice"], NO_LABEL))
        res["cond_ref"], res["cond_num"], res["cond_word"] = o["cond_ref"].argmax(-1), o["cond_num"].argmax(-1), o["cond_word"].argmax(-1)
        res["n_writes"] = o["n_writes"].argmax(-1)
        res["w_target"], res["w_var"] = o["w_target_choice"], o["w_var_choice"]
        res["w_enum"], res["w_num"], res["w_qty"], res["w_ptr"] = (o[k].argmax(-1) for k in ("w_enum", "w_num", "w_qty", "w_ptr"))
        # sequences: the speech if the gesture has an expression, one proposition per proposition-valued write
        S = sp.sequences.MAX_SEQUENCES
        want = torch.zeros(B, S, dtype=torch.bool, device=dev)
        want[:, 0] = self.has_expr[res["gesture"]]
        is_prop = (self.var_kind[res["w_var"]] == ValueKind.PROP) & (torch.arange(MAX_WRITES, device=dev) < res["n_writes"].unsqueeze(1))
        want[:, 1:] = is_prop
        bi, si = want.nonzero(as_tuple=True)
        L = sp.sequences.steps
        for k in ("seq_sym", "seq_arity", "seq_slot", "seq_count", "seq_depth", "seq_open"):
            res[k] = torch.full((B, S, L), NO_LABEL, dtype=torch.long, device=dev)
        res["seq_len"] = torch.full((B, S), -1, dtype=torch.long, device=dev)
        if bi.numel():
            init = self._speech_init(o["hq"], o["hv"], (bi, si), si)
            gen = self.decoder.generate(init, o["enc"][bi], o["ok"][bi])
            res["seq_len"][bi, si] = gen["len"]
            for dst, src in (("seq_sym", "sym"), ("seq_arity", "arity"), ("seq_count", "count"), ("seq_slot", "slot"), ("seq_depth", "depth")):
                res[dst][bi, si] = gen[src]
        return res

    def manner_used(self, gesture):
        return torch.as_tensor(self.space.manner.used, device=gesture.device)[gesture]
