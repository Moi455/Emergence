"""probe_belief.py - a small intelligence probe at (roughly) equal compute: false-belief tracking through pointers,
with information older than the context window (docs/09, section 4).

  python3 ai/research/arch/probe_belief.py                     # 6 models x 2 seeds, ~2 h 30 on the Quadro
  python3 ai/research/arch/probe_belief.py --models win16,mem8 --seeds 0 --steps 1500

THE TASK (ToMi / Sally-Anne style, generated on the fly). An observer NPC (ego, always present) watches a scene with
5 other persons, 4 objects and 5 places. 64 events: a person enters, leaves, or moves an object to a place (seen by
everyone present). Every 8 events the observer must answer one question: "where does person q believe object o is?"
(half the questions are FALSE beliefs: q was away when o last moved). The answer is a pointer to a place record.
What the model reads at a decision mirrors tok-2: record tokens (persons with a 'present now' flag, objects with a
pointer to where the observer saw them last, places), event records with pointers to those records and their age,
a query token, all with per-episode stable file handles (like an NPC's own file numbers; record slots are re-shuffled
at every decision, as salience order would). Nothing is true-but-unperceived: all events are perceived by the ego.

THE MODELS (same width d=128, 4 layers; same 32 tokens per decision except 'all'):
  win16   stateless set-Transformer with pointer bias, the 16 most recent events (docs/07 baseline, recency selector)
  ret16   same, but the 16 events are chosen by a PERFECT retriever (moves of o, enters/leaves of q): the upper bound
          of a learned context selector
  mem8    8 most recent events (each event seen once) + 8 recurrent memory tokens carried between decisions (RMT)
  mem8fw  mem8 + a per-NPC delta-rule fast-weight memory (64 x 64), 4 recall tokens
  gru     a 2-layer GRU (d 384, ~ same FLOPs per decision) over the event stream (no records, no attention),
          answers by scoring place handles
  all64   stateless with all past events (80 tokens: 2.5x the compute), the context upper bound
Supervision is the exact answer (a full-information teacher). Accuracy on 16 384 held-out episodes, by category.
Results: ai/research/arch/results/probe_belief.json
"""
import argparse
import json
import math
import os
import time

import torch
import torch.nn as nn
import torch.nn.functional as F

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS = os.path.join(HERE, "results")

P, O, L = 6, 4, 5            # persons (0 = ego), objects, places
R = P + O + L                # record tokens
E = 64                       # events per episode
EVERY = 8                    # a question every 8 events
D_POINTS = E // EVERY        # 8 decision points
HANDLES = 32
ENTER, LEAVE, MOVE = 0, 1, 2


# ------------------------------------------------------------------------------------------------- episodes
class EpisodeBatch:
    """N episodes generated in parallel on the GPU, with the ground truth of every person's beliefs."""

    def __init__(self, N, gen: torch.Generator, device="cuda"):
        dev = device
        self.N = N
        r = lambda *s: torch.rand(*s, generator=gen, device=dev)
        ri = lambda hi, *s: torch.randint(0, hi, s, generator=gen, device=dev)
        present = torch.ones(N, P, dtype=torch.bool, device=dev)
        loc = ri(L, N, O)
        belief = loc.unsqueeze(1).expand(N, P, O).clone()
        last_seen_move = torch.full((N, P, O), -1, dtype=torch.long, device=dev)   # time of last witnessed move
        ar = torch.arange(N, device=dev)
        self.ev_type = torch.zeros(N, E, dtype=torch.long, device=dev)
        self.ev_actor = torch.zeros(N, E, dtype=torch.long, device=dev)
        self.ev_obj = torch.full((N, E), -1, dtype=torch.long, device=dev)
        self.ev_place = torch.full((N, E), -1, dtype=torch.long, device=dev)
        self.ev_from = torch.full((N, E), -1, dtype=torch.long, device=dev)
        self.present = torch.zeros(N, D_POINTS, P, dtype=torch.bool, device=dev)
        self.loc = torch.zeros(N, D_POINTS, O, dtype=torch.long, device=dev)
        self.q_person = torch.zeros(N, D_POINTS, dtype=torch.long, device=dev)
        self.q_obj = torch.zeros(N, D_POINTS, dtype=torch.long, device=dev)
        self.answer = torch.zeros(N, D_POINTS, dtype=torch.long, device=dev)
        self.false_belief = torch.zeros(N, D_POINTS, dtype=torch.bool, device=dev)
        self.decisive_age = torch.zeros(N, D_POINTS, dtype=torch.long, device=dev)   # events since the decisive one
        for t in range(E):
            is_move = r(N) < 0.5
            # toggle presence of a random non-ego person
            who = 1 + ri(P - 1, N)
            was = present[ar, who]
            # move: a present actor (ego is always present), an object, a new place
            pres_w = present.float() + 1e-9
            actor_m = torch.multinomial(pres_w, 1, generator=gen).squeeze(1)
            obj = ri(O, N)
            shift = 1 + ri(L - 1, N)
            new_place = (loc[ar, obj] + shift) % L
            self.ev_type[:, t] = torch.where(is_move, MOVE, torch.where(was, LEAVE, ENTER))
            self.ev_actor[:, t] = torch.where(is_move, actor_m, who)
            self.ev_obj[:, t] = torch.where(is_move, obj, -1)
            self.ev_place[:, t] = torch.where(is_move, new_place, -1)
            self.ev_from[:, t] = torch.where(is_move, loc[ar, obj], -1)                       # seen: from -> to
            # apply
            toggled = present.clone()
            toggled[ar, who] = ~was
            present = torch.where(is_move.unsqueeze(1), present, toggled)
            loc_new = loc.clone()
            loc_new[ar, obj] = new_place
            loc = torch.where(is_move.unsqueeze(1), loc_new, loc)
            witness = present & is_move.unsqueeze(1)                                          # [N, P]
            hit = witness.unsqueeze(2) & (torch.arange(O, device=dev).view(1, 1, O) == obj.view(N, 1, 1))
            belief = torch.where(hit, new_place.view(N, 1, 1), belief)
            last_seen_move = torch.where(hit, torch.full_like(last_seen_move, t), last_seen_move)
            if (t + 1) % EVERY == 0:
                d = (t + 1) // EVERY - 1
                self.present[:, d], self.loc[:, d] = present, loc
                fb = belief[:, 1:] != loc.unsqueeze(1)                                         # [N, P-1, O]
                want_fb = (r(N) < 0.5) & fb.flatten(1).any(1)
                w = torch.where(want_fb.view(N, 1, 1), fb, ~fb).flatten(1).float() + 1e-9
                pick = torch.multinomial(w, 1, generator=gen).squeeze(1)
                q, o = 1 + pick // O, pick % O
                self.q_person[:, d], self.q_obj[:, d] = q, o
                self.answer[:, d] = belief[ar, q, o]
                self.false_belief[:, d] = fb[ar, q - 1, o]
                ls = last_seen_move[ar, q, o]
                self.decisive_age[:, d] = torch.where(ls < 0, 999, t - ls)
        perm = torch.argsort(r(N, HANDLES), dim=1)
        self.handle = perm[:, :R]                                                             # stable file handles

    FIELDS = ("ev_type", "ev_actor", "ev_obj", "ev_place", "ev_from", "present", "loc", "q_person", "q_obj", "answer",
              "false_belief", "decisive_age", "handle")

    def slice(self, start, n):
        out = EpisodeBatch.__new__(EpisodeBatch)
        out.N = n
        for f in self.FIELDS:
            setattr(out, f, getattr(self, f)[start:start + n])
        return out


# --------------------------------------------------------------------------------------------- token builder
class TokenBuilder:
    """Builds the tokens of decision point d: records (slots re-shuffled within type), K events, a query token.
    Token fields: kind, handle, flag, age, and 4 pointer fields (slot index or -1): actor, object, from, to."""
    KINDS = {"person": 0, "object": 1, "place": 2, "enter": 3, "leave": 4, "move": 5, "query": 6, "pad": 7}

    def __init__(self, K, select, gen):
        self.K, self.select, self.gen = K, select, gen

    def build(self, ep: EpisodeBatch, d):
        N, dev = ep.N, ep.ev_type.device
        t_now = (d + 1) * EVERY
        ar = torch.arange(N, device=dev).unsqueeze(1)
        # slot permutation within each record type: slot_of[n, canonical record] -> slot
        slot_of = torch.empty(N, R, dtype=torch.long, device=dev)
        for base, n in ((0, P), (P, O), (P + O, L)):
            perm = torch.argsort(torch.rand(N, n, generator=self.gen, device=dev), 1)
            slot_of[:, base:base + n] = base + perm
        kind = torch.empty(N, R, dtype=torch.long, device=dev)
        handle = torch.empty(N, R, dtype=torch.long, device=dev)
        flag = torch.zeros(N, R, dtype=torch.long, device=dev)
        ptr = torch.full((N, R, 4), -1, dtype=torch.long, device=dev)
        canon_kind = torch.tensor([0] * P + [1] * O + [2] * L, device=dev)
        kind.scatter_(1, slot_of, canon_kind.expand(N, R))
        handle.scatter_(1, slot_of, ep.handle)
        flag.scatter_(1, slot_of[:, :P], ep.present[:, d].long())
        obj_place_slot = torch.gather(slot_of[:, P + O:], 1, ep.loc[:, d])                    # [N, O]
        ptr[:, :, 0].scatter_(1, slot_of[:, P:P + O], obj_place_slot)
        # events
        times = torch.arange(E, device=dev).expand(N, E)
        past = times < t_now
        if self.select == "recent":
            score = times.float()
        else:                                                                                # perfect retriever
            q, o = ep.q_person[:, d:d + 1], ep.q_obj[:, d:d + 1]
            rel = ((ep.ev_type == MOVE) & (ep.ev_obj == o)) | ((ep.ev_type != MOVE) & (ep.ev_actor == q))
            score = times.float() + 1000.0 * rel.float()
        score = torch.where(past, score, torch.full_like(score, -1e9))
        idx = score.topk(self.K, dim=1).indices                                              # [N, K]
        valid = torch.gather(past, 1, idx)
        et = torch.gather(ep.ev_type, 1, idx)
        ev_kind = torch.where(valid, 3 + et, 7)
        age = (t_now - 1 - idx).clamp(0, 63)
        a_slot = torch.gather(slot_of, 1, torch.gather(ep.ev_actor, 1, idx))
        o_raw = torch.gather(ep.ev_obj, 1, idx)
        p_raw = torch.gather(ep.ev_place, 1, idx)
        o_slot = torch.where(o_raw >= 0, torch.gather(slot_of, 1, P + o_raw.clamp(min=0)), -1)
        p_slot = torch.where(p_raw >= 0, torch.gather(slot_of, 1, P + O + p_raw.clamp(min=0)), -1)
        f_raw = torch.gather(ep.ev_from, 1, idx)
        f_slot = torch.where(f_raw >= 0, torch.gather(slot_of, 1, P + O + f_raw.clamp(min=0)), -1)
        ev_ptr = torch.stack([a_slot, o_slot, f_slot, p_slot], -1)
        ev_ptr = torch.where(valid.unsqueeze(-1), ev_ptr, -1)
        # query
        qp = torch.gather(slot_of, 1, ep.q_person[:, d:d + 1])
        qo = torch.gather(slot_of, 1, P + ep.q_obj[:, d:d + 1])
        q_ptr = torch.stack([qp, qo, torch.full_like(qp, -1), torch.full_like(qp, -1)], -1)
        tok = {
            "kind": torch.cat([kind, ev_kind, torch.full((N, 1), 6, device=dev)], 1),
            "handle": torch.cat([handle, torch.zeros(N, self.K + 1, dtype=torch.long, device=dev)], 1),
            "flag": torch.cat([flag, torch.zeros(N, self.K + 1, dtype=torch.long, device=dev)], 1),
            "age": torch.cat([torch.zeros(N, R, dtype=torch.long, device=dev), torch.where(valid, age, 0),
                              torch.zeros(N, 1, dtype=torch.long, device=dev)], 1),
            "ptr": torch.cat([ptr, ev_ptr, q_ptr], 1),
            "valid": torch.cat([torch.ones(N, R, dtype=torch.bool, device=dev), valid,
                                torch.ones(N, 1, dtype=torch.bool, device=dev)], 1),
        }
        answer_slot = torch.gather(slot_of, 1, P + O + ep.answer[:, d:d + 1]).squeeze(1)
        return tok, answer_slot


# ------------------------------------------------------------------------------------------------- models
NPTR = 4


class Block(nn.Module):
    """Pre-LN Transformer block with an additive attention bias [N, h, T, T] (same code in training and eval)."""

    def __init__(self, d, h, ff):
        super().__init__()
        self.h = h
        self.ln1, self.ln2 = nn.LayerNorm(d), nn.LayerNorm(d)
        self.qkv, self.o = nn.Linear(d, 3 * d), nn.Linear(d, d)
        self.ff = nn.Sequential(nn.Linear(d, ff), nn.GELU(), nn.Linear(ff, d))

    def forward(self, x, bias):
        N, T, D = x.shape
        q, k, v = self.qkv(self.ln1(x)).view(N, T, 3, self.h, D // self.h).permute(2, 0, 3, 1, 4)
        a = F.scaled_dot_product_attention(q, k, v, attn_mask=bias.to(q.dtype))
        x = x + self.o(a.transpose(1, 2).reshape(N, T, D))
        return x + self.ff(self.ln2(x))


class SetPointerNet(nn.Module):
    """Set-Transformer with pointer messages + per-head pointer attention bias (the docs/07 policy, small), optional
    recurrent memory tokens and a delta-rule fast-weight memory. Answer = pointer from the query token to a place."""

    def __init__(self, d=128, layers=4, heads=4, ff=512, mem=0, fw=0, fw_reads=4):
        super().__init__()
        self.d, self.h, self.mem, self.fw, self.fw_reads = d, heads, mem, fw, fw_reads
        self.kind = nn.Embedding(8, d)
        self.handle = nn.Embedding(HANDLES, d)
        self.flag = nn.Embedding(2, d)
        self.age = nn.Embedding(64, d)
        self.msg = nn.ModuleList([nn.Linear(d, d, bias=False) for _ in range(NPTR)])
        self.pbias = nn.Parameter(torch.randn(NPTR, 2, heads) * 0.5)
        self.layers = nn.ModuleList([Block(d, heads, ff) for _ in range(layers)])
        self.ln = nn.LayerNorm(d)
        self.q, self.k = nn.Linear(d, d), nn.Linear(d, d)
        if mem:
            self.mem_init = nn.Parameter(torch.randn(mem, d) * 0.02)
            self.mem_gate = nn.Linear(2 * d, d)
        if fw:
            self.fw_q = nn.Linear(d, fw_reads * fw)
            self.fw_out = nn.Linear(fw, d)
            self.fw_kvb = nn.Linear(d, 4 * (2 * fw + 1))
            self.fw_decay = nn.Parameter(torch.tensor(5.0))

    def init_state(self, N, dev):
        st = {}
        if self.mem:
            st["mem"] = self.mem_init.unsqueeze(0).expand(N, -1, -1)
        if self.fw:
            st["W"] = torch.zeros(N, self.fw, self.fw, device=dev)
        return st

    def forward(self, tok, state):
        kind, ptr, valid = tok["kind"], tok["ptr"], tok["valid"]
        N, T = kind.shape
        x = self.kind(kind) + self.handle(tok["handle"]) * (kind <= 2).unsqueeze(-1) + self.flag(tok["flag"]) \
            + self.age(tok["age"]) * ((kind >= 3) & (kind <= 5)).unsqueeze(-1)
        base = x
        ok = ptr >= 0
        idx = ptr.clamp(min=0)
        bias = torch.zeros(N, self.h, T, T, device=x.device, dtype=x.dtype)
        for k in range(NPTR):
            g = torch.gather(base, 1, idx[..., k:k + 1].expand(N, T, self.d))
            x = x + self.msg[k](g) * ok[..., k:k + 1]
            adj = torch.zeros(N, T, T + 1, device=x.device, dtype=x.dtype)
            adj.scatter_(2, torch.where(ok[..., k:k + 1], idx[..., k:k + 1], T), 1.0)
            adj = adj[..., :T]
            bias = bias + adj.unsqueeze(1) * self.pbias[k, 0].view(1, -1, 1, 1) \
                + adj.transpose(1, 2).unsqueeze(1) * self.pbias[k, 1].view(1, -1, 1, 1)
        extra = []
        if self.mem:
            extra.append(state["mem"])
        if self.fw:
            qv = F.normalize(self.fw_q(x[:, -1]).view(N, self.fw_reads, self.fw), dim=-1)
            extra.append(self.fw_out(torch.bmm(qv, state["W"])))
        Ex = 0
        if extra:
            ex = torch.cat(extra, 1)
            Ex = ex.shape[1]
            x = torch.cat([ex, x], 1)
            bias = F.pad(bias, (Ex, 0, Ex, 0))
            valid = torch.cat([torch.ones(N, Ex, dtype=torch.bool, device=x.device), valid], 1)
        neg = -1e4
        attn = bias.masked_fill(~valid.view(N, 1, 1, -1), neg)
        for layer in self.layers:
            x = layer(x, attn)
        x = self.ln(x)
        new = {}
        if self.mem:
            m_out = x[:, :self.mem]
            gate = torch.sigmoid(self.mem_gate(torch.cat([m_out, state["mem"]], -1)))
            new["mem"] = gate * m_out + (1 - gate) * state["mem"]
        if self.fw:
            p = self.fw_kvb(x[:, -1]).view(N, 4, 2 * self.fw + 1)
            kk, vv = F.normalize(p[..., :self.fw], dim=-1), p[..., self.fw:2 * self.fw]
            bb = torch.sigmoid(p[..., -1:])
            W = state["W"] * torch.sigmoid(self.fw_decay)
            for i in range(4):
                ki, vi = kk[:, i:i + 1], vv[:, i:i + 1]
                W = W + torch.bmm(ki.transpose(1, 2), (vi - torch.bmm(ki, W)) * bb[:, i:i + 1])
            new["W"] = W
        h = x[:, Ex:]
        logits = torch.einsum("nd,ntd->nt", self.q(h[:, -1]), self.k(h)) / math.sqrt(self.d)
        place = (tok["kind"] == 2)
        return logits.masked_fill(~place, neg), new


class GRUStreamNet(nn.Module):
    """Event stream into a 2-layer GRU (handles as identities). At a decision: hidden + query -> score the places."""

    def __init__(self, d=384):
        super().__init__()
        self.d = d
        self.kind, self.handle, self.age = nn.Embedding(8, d), nn.Embedding(HANDLES + 1, d), nn.Embedding(64, d)
        self.gru = nn.GRU(d, d, num_layers=2, batch_first=True)
        self.q = nn.Sequential(nn.Linear(3 * d, d), nn.GELU(), nn.Linear(d, d))
        self.k = nn.Linear(d, d)
        self.from_ = nn.Embedding(HANDLES + 1, d)

    def forward_episode(self, ep: EpisodeBatch):
        N = ep.N
        h_of = lambda canon: torch.gather(ep.handle, 1, canon.clamp(min=0)) + 1
        ev = self.kind(3 + ep.ev_type) + self.handle(h_of(ep.ev_actor)) \
            + self.handle(torch.where(ep.ev_obj >= 0, h_of(P + ep.ev_obj), 0)) \
            + self.handle(torch.where(ep.ev_place >= 0, h_of(P + O + ep.ev_place), 0)) \
            + self.from_(torch.where(ep.ev_from >= 0, h_of(P + O + ep.ev_from), 0))
        out, _ = self.gru(ev)                                                   # [N, E, d]
        hs = out[:, EVERY - 1::EVERY]                                           # [N, D, d]
        qh = self.handle(torch.gather(ep.handle, 1, ep.q_person) + 1)
        oh = self.handle(torch.gather(ep.handle, 1, P + ep.q_obj) + 1)
        qv = self.q(torch.cat([hs, qh, oh], -1))                                # [N, D, d]
        places = self.k(self.handle(ep.handle[:, P + O:] + 1))                  # [N, L, d]
        return torch.einsum("ndk,nlk->ndl", qv, places)                         # logits over canonical places


# ------------------------------------------------------------------------------------------------ training
MODELS = {
    "win16": dict(K=16, select="recent", mem=0, fw=0),
    "win8": dict(K=8, select="recent", mem=0, fw=0),          # control (review 13 oct.): mem8 without its memory
    "ret16": dict(K=16, select="retrieve", mem=0, fw=0),
    "mem8": dict(K=8, select="recent", mem=8, fw=0),
    "mem8fw": dict(K=8, select="recent", mem=8, fw=64),
    "gru": dict(gru=True),
    "all64": dict(K=64, select="recent", mem=0, fw=0, micro=2),
}


class Experiment:
    def __init__(self, name, seed, steps, batch, lr):
        self.name, self.seed, self.steps, self.batch, self.lr = name, seed, steps, batch, lr
        self.spec = MODELS[name]
        torch.manual_seed(seed)
        if self.spec.get("gru"):
            self.model = GRUStreamNet().cuda()
        else:
            self.model = SetPointerNet(mem=self.spec["mem"], fw=self.spec["fw"]).cuda()
        self.gen = torch.Generator(device="cuda").manual_seed(1000 + seed)

    def n_params(self):
        return sum(p.numel() for p in self.model.parameters())

    def episode_logits(self, ep, builder):
        """[N, D, slots] logits and [N, D] targets (slot indices; canonical place index for the GRU)."""
        if self.spec.get("gru"):
            return self.model.forward_episode(ep), ep.answer
        state = self.model.init_state(ep.N, "cuda")
        logits, targets = [], []
        for d in range(D_POINTS):
            tok, ans = builder.build(ep, d)
            lg, new = self.model(tok, state)
            if self.spec["mem"] or self.spec["fw"]:
                state = new
            logits.append(lg[:, :R])
            targets.append(ans)
        return torch.stack(logits, 1), torch.stack(targets, 1)

    def train(self):
        opt = torch.optim.AdamW(self.model.parameters(), lr=self.lr, weight_decay=0.01)
        scaler = torch.amp.GradScaler("cuda")
        sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=self.lr, total_steps=self.steps, pct_start=0.05)
        builder = None if self.spec.get("gru") else TokenBuilder(self.spec["K"], self.spec["select"], self.gen)
        t0, log = time.time(), []
        self.model.train()
        pool, pool_left = None, 0
        for step in range(self.steps):
            if pool_left == 0:                                    # generate 16 batches at once (Python-loop bound)
                pool, pool_left = EpisodeBatch(16 * self.batch, self.gen), 16
            pool_left -= 1
            ep = pool.slice(pool_left * self.batch, self.batch)
            opt.zero_grad(set_to_none=True)
            micro = self.spec.get("micro", 1)                     # gradient accumulation (memory), same batch
            mb = self.batch // micro
            for i in range(micro):
                with torch.autocast("cuda", dtype=torch.float16):
                    lg, tg = self.episode_logits(ep.slice(i * mb, mb), builder)
                loss = F.cross_entropy(lg.float().flatten(0, 1), tg.flatten())
                scaler.scale(loss / micro).backward()
            scaler.unscale_(opt)
            torch.nn.utils.clip_grad_norm_(self.model.parameters(), 1.0)
            scaler.step(opt)
            scaler.update()
            sched.step()
            if step % 250 == 0 or step == self.steps - 1:
                acc = (lg.argmax(-1) == tg).float().mean().item()
                log.append({"step": step, "loss": loss.item(), "train_acc": acc, "s": time.time() - t0})
                print(f"  [{self.name} s{self.seed}] step {step:5d} loss {loss.item():.3f} acc {acc:.3f} "
                      f"({time.time() - t0:.0f} s)", flush=True)
        return log, time.time() - t0

    @torch.no_grad()
    def evaluate(self, n_eval=16384, chunk=1024):
        self.model.eval()
        gen = torch.Generator(device="cuda").manual_seed(999_999)                # same held-out set for every model
        bgen = torch.Generator(device="cuda").manual_seed(4242)
        builder = None if self.spec.get("gru") else TokenBuilder(self.spec["K"], self.spec["select"], bgen)
        cats = {}
        for _ in range(n_eval // chunk):
            ep = EpisodeBatch(chunk, gen)
            lg, tg = self.episode_logits(ep, builder)
            ok = (lg.argmax(-1) == tg)
            fb, age = ep.false_belief, ep.decisive_age
            buckets = {"recent(<8)": age < 8, "mid(8-15)": (age >= 8) & (age < 16), "old(16+)": (age >= 16) & (age < 999),
                       "initial": age == 999}
            for bname, bm in buckets.items():
                for fname, fm in (("true", ~fb), ("false", fb)):
                    m = bm & fm
                    c = cats.setdefault(f"{fname}-belief/{bname}", [0, 0])
                    c[0] += int(ok[m].sum())
                    c[1] += int(m.sum())
            c = cats.setdefault("ALL", [0, 0])
            c[0] += int(ok.sum())
            c[1] += ok.numel()
            for fname, fm in (("true", ~fb), ("false", fb)):
                c = cats.setdefault(f"{fname}-belief", [0, 0])
                c[0] += int(ok[fm].sum())
                c[1] += int(fm.sum())
        return {k: {"acc": v[0] / max(v[1], 1), "n": v[1]} for k, v in cats.items()}


def flops_per_decision(name):
    """Rough matmul FLOPs per decision (transformer: tokens x layers x per-token cost + attention)."""
    s = MODELS[name]
    d, ff, Ly = 128, 512, 4
    if s.get("gru"):
        dg = 384                                           # 2 layers x 3 gates x (input + recurrent) per event
        return EVERY * 2 * 3 * 2 * (dg * dg + dg * dg) + 2 * (3 * dg * dg + L * dg * dg)
    T = R + s["K"] + 1 + s["mem"] + (4 if s["fw"] else 0)
    return Ly * (2 * T * (4 * d * d + 2 * d * ff) + 4 * T * T * d)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default="win16,ret16,mem8,mem8fw,gru,all64")
    ap.add_argument("--seeds", default="0,1")
    ap.add_argument("--steps", type=int, default=2500)
    ap.add_argument("--batch", type=int, default=512)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--out", default="probe_belief.json")
    a = ap.parse_args()
    path = os.path.join(RESULTS, a.out)
    results = json.load(open(path)) if os.path.exists(path) else {"runs": []}
    # chance-level and trivial-policy references on the held-out set
    gen = torch.Generator(device="cuda").manual_seed(999_999)
    ep = EpisodeBatch(4096, gen)
    ref = {"answer_current_location": float((ep.answer == torch.gather(ep.loc, 2, ep.q_obj.unsqueeze(-1)).squeeze(-1))
                                            .float().mean()), "chance": 1 / L,
           "false_belief_share": float(ep.false_belief.float().mean())}
    results["references"] = ref
    print("references:", ref)
    for name in a.models.split(","):
        for seed in [int(s) for s in a.seeds.split(",")]:
            exp = Experiment(name, seed, a.steps, a.batch, a.lr)
            print(f"== {name} seed {seed}: {exp.n_params() / 1e6:.2f} M params, "
                  f"{flops_per_decision(name) / 1e6:.0f} MFLOP/decision", flush=True)
            log, secs = exp.train()
            ev = exp.evaluate()
            print(f"   eval {name} s{seed}: " + ", ".join(f"{k} {v['acc']:.3f}" for k, v in ev.items()), flush=True)
            results["runs"] = [r for r in results["runs"] if not (r["model"] == name and r["seed"] == seed)]
            results["runs"].append({"model": name, "seed": seed, "params": exp.n_params(),
                                    "mflop_per_decision": flops_per_decision(name) / 1e6, "steps": a.steps,
                                    "batch": a.batch, "lr": a.lr, "train_s": secs, "log": log, "eval": ev})
            results.update(gpu=torch.cuda.get_device_name(0), torch=torch.__version__,
                           date=time.strftime("%Y-%m-%d %H:%M"))
            os.makedirs(RESULTS, exist_ok=True)
            json.dump(results, open(path, "w"), indent=1)
    print("saved", path)


if __name__ == "__main__":
    main()
