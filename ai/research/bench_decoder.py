"""bench_decoder.py - grammar-constrained decoding of inner-language utterances (docs/07_conception_ia.md, section 3).

  python3 ai/research/bench_decoder.py            # ~30 s

Speech is a gesture whose content is an expression of the inner language (<= 512 grammar words, <= 1024 kinds,
<= 16 symbols). Because nesting is bounded (<= 2 levels, <= 3 arguments), the grammar is FINITE-DEPTH, hence
compilable into a deterministic finite automaton: the decoding mask is a table lookup allowed[state] on the GPU and
the next state is next_state[state, word]. No host round-trip per symbol: the whole 16-step loop is one CUDA graph.

The decoder (2 or 4 layers) cross-attends to the policy's encoder output (128 slots) of the speaking NPC and
recomputes its (<= 16 symbol) prefix each step with a causal mask: static shapes, no KV cache needed at this size.
The DFA here is random (S states, ~10 % allowed words per state); its cost, not its content, is what is measured.
Results: ai/research/results/decoder.json
"""
import math

import torch
import torch.nn as nn
import torch.nn.functional as F

from common import CudaTimer, GraphRunner, save

V = 512 + 1024 + 16 + 4   # grammar words + kinds + symbols + BOS/EOS/PAD/UNK
L_MAX = 16
BOS, EOS = 1, 2


class GrammarAutomaton:
    """Random stand-in for the compiled grammar: allowed[S, V] mask, next_state[S, V]. State 0 = start, 1 = done."""

    def __init__(self, n_states=512, density=0.10, seed=0):
        g = torch.Generator().manual_seed(seed)
        allowed = torch.rand(n_states, V, generator=g) < density
        allowed[:, EOS] = torch.rand(n_states, generator=g) < 0.3
        allowed[1] = False
        allowed[1, EOS] = True
        nxt = torch.randint(2, n_states, (n_states, V), generator=g)
        nxt[:, EOS] = 1
        self.allowed, self.next_state = allowed.cuda(), nxt.cuda()


class DecoderLayer(nn.Module):
    def __init__(self, d, h):
        super().__init__()
        self.h = h
        self.ln1, self.ln2, self.ln3 = nn.LayerNorm(d), nn.LayerNorm(d), nn.LayerNorm(d)
        self.qkv, self.o1 = nn.Linear(d, 3 * d), nn.Linear(d, d)
        self.q, self.kv, self.o2 = nn.Linear(d, d), nn.Linear(d, 2 * d), nn.Linear(d, d)
        self.ff = nn.Sequential(nn.Linear(d, 4 * d), nn.GELU(), nn.Linear(4 * d, d))

    def heads(self, x):
        B, T, D = x.shape
        return x.view(B, T, self.h, D // self.h).transpose(1, 2)

    def forward(self, y, mem, causal):
        B, L, D = y.shape
        q, k, v = self.qkv(self.ln1(y)).chunk(3, -1)
        a = F.scaled_dot_product_attention(self.heads(q), self.heads(k), self.heads(v), attn_mask=causal)
        y = y + self.o1(a.transpose(1, 2).reshape(B, L, D))
        k2, v2 = self.kv(mem).chunk(2, -1)
        a = F.scaled_dot_product_attention(self.heads(self.q(self.ln2(y))), self.heads(k2), self.heads(v2))
        y = y + self.o2(a.transpose(1, 2).reshape(B, L, D))
        return y + self.ff(self.ln3(y))


class UtteranceDecoder(nn.Module):
    def __init__(self, d=256, h=8, layers=2):
        super().__init__()
        self.emb = nn.Embedding(V, d)
        self.pos = nn.Parameter(torch.randn(L_MAX, d) * 0.02)
        self.layers = nn.ModuleList([DecoderLayer(d, h) for _ in range(layers)])
        self.ln = nn.LayerNorm(d)
        self.out = nn.Linear(d, V)
        self.register_buffer("causal", torch.ones(L_MAX, L_MAX, dtype=torch.bool).tril(), persistent=False)

    def decode(self, mem, gumbel, allowed, next_state):
        """mem [B, T, d] encoder states ; gumbel [B, L_MAX, V] per-NPC noise. Greedy+Gumbel, grammar-masked."""
        B = mem.shape[0]
        seq = torch.full((B, L_MAX), BOS, dtype=torch.long, device=mem.device)
        state = torch.zeros(B, dtype=torch.long, device=mem.device)
        for t in range(L_MAX - 1):
            y = self.emb(seq) + self.pos
            for layer in self.layers:
                y = layer(y, mem, self.causal)
            logits = self.out(self.ln(y[:, t])).float()
            logits = logits.masked_fill(~allowed[state], -1e9) + gumbel[:, t]
            tok = logits.argmax(-1)
            seq[:, t + 1] = tok
            state = next_state[state, tok]
        return seq


def main():
    grammar = GrammarAutomaton()
    rows = []
    for d, layers in ((256, 2), (384, 4)):
        dec = UtteranceDecoder(d=d, layers=layers).cuda().half().eval()
        n_par = sum(p.numel() for p in dec.parameters())
        for B in (1, 8, 32, 64):
            mem = torch.randn(B, 128, d, device="cuda", dtype=torch.float16)
            u = torch.rand(B, L_MAX, V, device="cuda").clamp(1e-6, 1 - 1e-6)
            inputs = {"mem": mem, "gumbel": -torch.log(-torch.log(u)),
                      "allowed": grammar.allowed, "next_state": grammar.next_state}
            with torch.inference_mode():
                eager = CudaTimer.measure(lambda: dec.decode(**inputs), iters=20)
                runner = GraphRunner(dec.decode, inputs)
                graph = CudaTimer.measure(runner.replay, iters=30)
                seq = runner.replay()
            # validity check of the automaton walk: every emitted word was allowed in its state
            state, ok = torch.zeros(B, dtype=torch.long, device="cuda"), True
            for t in range(1, L_MAX):
                ok &= bool(grammar.allowed[state, seq[:, t]].all())
                state = grammar.next_state[state, seq[:, t]]
            row = {"d": d, "layers": layers, "params_M": n_par / 1e6, "B": B, "eager_ms": eager["median_ms"],
                   "graph_ms": graph["median_ms"], "utterances_per_s": B / graph["median_ms"] * 1e3,
                   "all_words_grammatical": ok}
            rows.append(row)
            print(f"decoder d={d} L={layers} ({n_par / 1e6:.1f} M) B={B:<3} 16 symbols: eager {eager['median_ms']:7.2f} ms"
                  f" | graph {graph['median_ms']:6.2f} ms | {row['utterances_per_s']:8.0f} utt/s | grammatical={ok}",
                  flush=True)
    print("saved", save("decoder.json", {"rows": rows, "vocab": V, "max_len": L_MAX}))


if __name__ == "__main__":
    main()
