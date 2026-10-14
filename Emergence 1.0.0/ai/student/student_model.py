"""student_model.py - the student: a small Transformer that scores candidate options (format tok-1).

Input  : a sequence of tokens (see ai/npc_pipeline/encode.py): cat [B, T, 9] int64, num [B, T, 33] float, mask [B, T] bool.
Output : one logit per token (only CAND tokens are used), plus an auxiliary 10-driver head on the SELF token.

Design choices
  * no positional encoding: the sequence is a SET (entities, events and options are unordered, options are shuffled);
    structure comes from the token type, the categories and the POINTERS.
  * scalar slots mean different things per token type, so the scalar projection is per type: W[type] (33 x d).
  * pointers (event -> agent, option -> target entity / event / memory, memory -> third party...) are injected twice:
    the pointed token's input embedding is added (one hop), and attention gets a learned bias on (token, pointed token).
  * everything is integer-friendly (LayerNorm, GELU, Linear) so it can be quantised later (I-BERT style, roadmap M12/S7).
"""
import math

import torch
import torch.nn as nn
import torch.nn.functional as F_

CONFIGS = {
    # name: (d_model, layers, heads, ff)        parameters (approx.)
    "tiny": (128, 3, 4, 512),                    # ~0.8 M   CPU smoke tests
    "small": (256, 6, 8, 1024),                  # ~5 M     default on a 6 GB RTX 3000 laptop
    "base": (384, 8, 8, 1536),                   # ~15 M    if 'small' underfits
    "large": (512, 10, 8, 2048),                 # ~33 M    upper end of the 5-30 M target
}
N_TYPES = 14
N_PTR = 3
N_DRIVERS = 10


class Block(nn.Module):
    def __init__(self, d, h, ff, drop):
        super().__init__()
        self.h = h
        self.ln1 = nn.LayerNorm(d)
        self.qkv = nn.Linear(d, 3 * d)
        self.o = nn.Linear(d, d)
        self.ln2 = nn.LayerNorm(d)
        self.ff = nn.Sequential(nn.Linear(d, ff), nn.GELU(), nn.Linear(ff, d))
        self.drop = nn.Dropout(drop)

    def forward(self, x, bias):
        B, T, D = x.shape
        q, k, v = self.qkv(self.ln1(x)).view(B, T, 3, self.h, D // self.h).permute(2, 0, 3, 1, 4)
        a = F_.scaled_dot_product_attention(q, k, v, attn_mask=bias)
        x = x + self.drop(self.o(a.transpose(1, 2).reshape(B, T, D)))
        return x + self.drop(self.ff(self.ln2(x)))


class Student(nn.Module):
    def __init__(self, vocab_size, n_num=33, config="small", drop=0.1):
        super().__init__()
        d, L, h, ff = CONFIGS[config]
        self.config, self.d, self.h = config, d, h
        self.type_emb = nn.Embedding(N_TYPES, d)
        self.cat_emb = nn.Embedding(vocab_size, d, padding_idx=0)
        self.slot_emb = nn.Parameter(torch.zeros(5, d))            # which category slot (c0..c4)
        self.num_w = nn.Parameter(torch.randn(N_TYPES, n_num, d) * (1 / math.sqrt(n_num)))
        self.num_b = nn.Parameter(torch.zeros(N_TYPES, d))
        self.ptr_proj = nn.ModuleList([nn.Linear(d, d, bias=False) for _ in range(N_PTR)])
        self.ptr_bias = nn.Parameter(torch.zeros(N_PTR, h))        # attention bias toward / from pointed tokens
        self.blocks = nn.ModuleList([Block(d, h, ff, drop) for _ in range(L)])
        self.ln = nn.LayerNorm(d)
        self.score = nn.Sequential(nn.Linear(d, d), nn.GELU(), nn.Linear(d, 1))
        self.drivers = nn.Linear(d, N_DRIVERS)

    def forward(self, cat, num, mask):
        B, T, _ = cat.shape
        typ = cat[..., 0]
        x = self.type_emb(typ)
        cats = cat[..., 1:6]
        x = x + (self.cat_emb(cats) + self.slot_emb * (cats > 0).unsqueeze(-1)).sum(-2)
        x = x + torch.einsum("btf,btfd->btd", num, self.num_w[typ]) + self.num_b[typ]
        base = x
        ptr = cat[..., 6:9]                                       # [B, T, 3], -1 = none
        valid = ptr >= 0
        idx = ptr.clamp(min=0)
        bias = torch.zeros(B, self.h, T, T, device=x.device, dtype=x.dtype)
        for k in range(N_PTR):
            g = torch.gather(base, 1, idx[..., k:k + 1].expand(B, T, self.d))
            x = x + self.ptr_proj[k](g) * valid[..., k:k + 1]
            onehot = F_.one_hot(idx[..., k], T).to(x.dtype) * valid[..., k:k + 1].to(x.dtype)   # [B, T, T]
            sym = onehot + onehot.transpose(1, 2)
            bias = bias + sym.unsqueeze(1) * self.ptr_bias[k].view(1, -1, 1, 1)
        neg = torch.finfo(x.dtype).min / 4
        bias = bias.masked_fill(~mask.view(B, 1, 1, T), neg)
        for blk in self.blocks:
            x = blk(x, bias)
        x = self.ln(x)
        logits = self.score(x).squeeze(-1)                        # [B, T]
        drv = self.drivers(x[:, 0])                               # SELF token is always first
        return logits, drv


def n_params(m):
    return sum(p.numel() for p in m.parameters())
