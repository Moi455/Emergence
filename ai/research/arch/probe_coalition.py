"""probe_coalition.py - coordination probe: "Pierre, Jacques and Jean go to the forest together to kill George"
(docs/09, section 5.2). Does iterated reflection, a ToM head, depth or latent looping help a small shared policy to
form a coalition, agree through messages on a place and an hour, and all be there? At (roughly) equal compute.

  python3 ai/research/arch/probe_coalition.py                     # 5 models x 2 seeds, ~1 h on the Quadro
  python3 ai/research/arch/probe_coalition.py --models direct4,reflect4 --seeds 0 --steps 600

THE WORLD (one episode = 24 game hours, generated on the GPU). 5 villagers + George. George wronged 3 villagers
(he slept with their wives). One villager (public: "he saw George at the mill") witnessed it. In the 10 hours
before, 10 private talks happened (public: who talked to whom, when; not what): a talk passes everything the teller
knows, so knowledge of the affair spreads along time-respecting chains of talks (0 to 4 hops). A villager who knows
also knows who was wronged. George goes to one of 3 places at a fixed hour each day (public routine).
The coalition C = the wronged who know. If |C| >= 2, its boldest member (boldness is public) leads: he proposes
"meet at <George's place> at <George's hour>" to each other member, one per hour, boldest first; each accepts the
next hour; all go there the hour before. Success: every member of C is at George's place at his hour, and nobody
outside C (George included) was ever invited (secrecy). If |C| < 2 (20 % of episodes), success = nobody moves.
Deciding who to invite needs theory of mind over chains: "who knows, given who talked to whom and when?".

WHAT AN AGENT READS (tok-2-like records, 31 tokens): 6 persons (boldness, me, George, wronged-as-known, knows-flag
written by reflection), 4 places, George's routine, the witness, 10 talks (pointers teller -> hearer, hour), the
proposal received, up to 3 acceptances received, up to 3 proposals sent, its commitment, a clock/self token.
Actions: NOOP, PROPOSE(person, place, hour), ACCEPT, GO(place); reflection adds WRITE knows(person, since hour), STOP.

THE MODELS (d 128, set-Transformer with pointer messages and pointer attention bias, as in docs/07):
  direct4   4 layers, one pass per decision
  direct8   8 layers (2x the compute of every decision)
  tom4      direct4 + a ToM head on person tokens (does he know? is he in the coalition?) trained as an auxiliary
  loop4     2 layers looped 4 times (weights shared in depth, Universal-Transformer / TRM-style latent recursion):
            the FLOPs of direct8 with the parameters of a 2-layer model
  reflect4  direct4 + ITERATED REFLECTION IN RECORDS: at hour 0, in WAKE mode 'reflect', up to 5 cheap decisions
            each write one belief "X knows since hour h" (a flag on X's record) or STOP; acting decisions read them
Training = imitation of the exact teacher (teacher forcing, NOOPs down-weighted). Evaluation = CLOSED LOOP: the
student plays all 5 villagers for 24 hours on 4 096 held-out episodes (its own reflections, proposals, acceptances).
Results: ai/research/arch/results/probe_coalition.json
"""
import argparse
import json
import math
import os
import time

import torch
import torch.nn as nn
import torch.nn.functional as F

from probe_belief import Block

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS = os.path.join(HERE, "results")

V, G = 5, 5                  # villagers 0..4, George = person 5
NP, NL = 6, 4                # persons, places (0 = village, 1..3 = forest, mill, river)
NTALK = 10                   # talks in the 10 hours before the episode (hour -10 .. -1)
HOURS = 24
MAXR = 5                     # reflection steps at most
NOOP, PROPOSE, ACCEPT, GO, WRITE, STOP = range(6)
# token kinds
K_PERSON, K_PLACE, K_ROUTINE, K_WITNESS, K_TALK, K_RXP, K_RXA, K_TXP, K_COMMIT, K_CLOCK, K_PAD = range(11)
# token slots
S_PERSON, S_PLACE, S_ROUTINE, S_WITNESS, S_TALK = 0, 6, 10, 11, 12
S_RXP, S_RXA, S_TXP, S_COMMIT, S_CLOCK = 22, 23, 26, 29, 30
T = 31
# hour vocabulary: 0 n/a, 1..24 = hours 0..23, 25..34 = hours -10..-1
def hcode(h):
    return torch.where(h >= 0, h + 1, h + 35)


# --------------------------------------------------------------------------------------------------- world
class CoalitionWorld:
    """The truth of N episodes (never read by the agents, except through their records)."""

    def __init__(self, N, gen, device="cuda"):
        dev = device
        self.N = N
        ar = torch.arange(N, device=dev)
        r = lambda *s: torch.rand(*s, generator=gen, device=dev)
        perm = torch.argsort(r(N, V), 1)
        self.wronged = torch.zeros(N, NP, dtype=torch.bool, device=dev)
        self.wronged[ar.unsqueeze(1), perm[:, :3]] = True
        self.witness = torch.randint(0, V, (N,), generator=gen, device=dev)
        self.bold = torch.argsort(r(N, NP), 1)                                   # distinct boldness 0..5
        teller = torch.randint(0, V, (N, NTALK), generator=gen, device=dev)
        hearer = (teller + torch.randint(1, V, (N, NTALK), generator=gen, device=dev)) % V
        self.talk_teller, self.talk_hearer = teller, hearer                     # talk k happens at hour k - 10
        since = torch.full((N, NP), 99, dtype=torch.long, device=dev)           # hour from which one knows
        since[ar, self.witness] = -11
        hops = torch.zeros(N, NP, dtype=torch.long, device=dev)                 # talks between witness and him
        for k in range(NTALK):
            h = k - NTALK
            t_since = since[ar, teller[:, k]]
            learn = (t_since < h) & (since[ar, hearer[:, k]] > h)
            since[ar, hearer[:, k]] = torch.where(learn, torch.full_like(t_since, h), since[ar, hearer[:, k]])
            hops[ar, hearer[:, k]] = torch.where(learn, hops[ar, teller[:, k]] + 1, hops[ar, hearer[:, k]])
        self.since = since
        self.hops = hops
        self.knows = since < 99
        self.coalition = self.wronged & self.knows
        csize = self.coalition.sum(1)
        # resample a share of episodes so that 80 % have a coalition of >= 2 (keep generation simple: mark invalid)
        self.has_coalition = csize >= 2
        b = torch.where(self.coalition, self.bold, -1)
        self.leader = b.argmax(1)
        self.g_place = torch.randint(1, NL, (N,), generator=gen, device=dev)
        self.g_hour = torch.randint(6, 15, (N,), generator=gen, device=dev)
        # members other than the leader, boldest first (the order of the proposals)
        order = torch.argsort(torch.where(self.coalition, self.bold, -1), 1, descending=True)
        self.order = order                                                       # order[:, 0] = leader
        self.handles = torch.argsort(r(N, 16), 1)[:, :NP + NL]                  # stable file handles per episode

    def select(self, idx):
        out = CoalitionWorld.__new__(CoalitionWorld)
        out.N = idx.numel()
        for k, v in vars(self).items():
            if torch.is_tensor(v):
                setattr(out, k, v[idx])
        return out

    @staticmethod
    def sample(N, gen, coalition_share=0.8):
        """Draw episodes, keeping coalition_share with |C| >= 2 and the rest without."""
        big = CoalitionWorld(4 * N, gen)
        yes = torch.nonzero(big.has_coalition).squeeze(1)
        no = torch.nonzero(~big.has_coalition).squeeze(1)
        ny = int(N * coalition_share)
        idx = torch.cat([yes[:ny], no[:N - ny]])
        assert idx.numel() == N, "not enough episodes of each kind"
        return big.select(idx[torch.randperm(N, generator=gen, device=idx.device)])


# ------------------------------------------------------------------------------------------- environment
class CoalitionEnv:
    """The dynamic state of the 5 villagers (messages, commitments, positions, reflected beliefs) and the tokens of
    their decisions. The same code runs the teacher (to make training data) and the student (closed loop)."""

    def __init__(self, world: CoalitionWorld):
        self.w = world
        N, dev = world.N, world.bold.device
        z = lambda *s: torch.zeros(*s, dtype=torch.long, device=dev)
        self.rxp = z(N, V, 4) - 1            # received proposal: from, place, hour, visible_from (-1 = none)
        self.rxa = z(N, V, 3, 2) - 1         # acceptances received: from, visible_from
        self.txp = z(N, V, 3, 2) - 1         # proposals sent: to, visible_from
        self.commit = z(N, V, 3) - 1         # place, hour, visible_from
        self.loc = z(N, V)                   # everybody in the village
        self.flag = torch.full((N, V, NP), -99, dtype=torch.long, device=dev)   # reflected "knows since h"
        self.invited_outside = torch.zeros(N, dtype=torch.bool, device=dev)
        self.moved_to_g = torch.zeros(N, dtype=torch.bool, device=dev)
        self.at_g_hour = None
        self.n_decisions = 0

    # ---- tokens ------------------------------------------------------------------------------------------
    def tokens(self, hour, mode_reflect=False):
        """Tokens of the 5 villagers of every episode at this hour: dict of [N*V, T] tensors."""
        w, N = self.w, self.w.N
        dev = w.bold.device
        B = N * V
        me = torch.arange(V, device=dev).repeat(N)                               # [B]
        ep = torch.arange(N, device=dev).repeat_interleave(V)
        kind = torch.full((B, T), K_PAD, dtype=torch.long, device=dev)
        f = {k: torch.zeros(B, T, dtype=torch.long, device=dev) for k in ("handle", "bold", "me", "george", "wr",
                                                                            "kn", "hour", "mode")}
        ptr = torch.full((B, T, 3), -1, dtype=torch.long, device=dev)
        # persons
        kind[:, S_PERSON:S_PERSON + NP] = K_PERSON
        f["handle"][:, :NP] = w.handles[ep, :NP] + 1
        f["bold"][:, :NP] = w.bold[ep] + 1
        f["me"][:, :NP] = (torch.arange(NP, device=dev).unsqueeze(0) == me.unsqueeze(1)).long() + 1
        f["george"][:, :NP] = (torch.arange(NP, device=dev) == G).long().unsqueeze(0).expand(B, NP) + 1
        i_know = w.knows[ep, me]                                                  # a knower knows who was wronged
        f["wr"][:, :NP] = torch.where(i_know.unsqueeze(1), w.wronged[ep].long() + 2, torch.ones_like(w.wronged[ep]).long())
        fl = self.flag.view(B, NP)
        f["kn"][:, :NP] = torch.where(fl > -99, 2, 1)
        f["hour"][:, :NP] = torch.where(fl > -99, hcode(fl.clamp(min=-10)), 0)
        # places
        kind[:, S_PLACE:S_PLACE + NL] = K_PLACE
        f["handle"][:, S_PLACE:S_PLACE + NL] = w.handles[ep, NP:] + 1
        # routine: George goes to place p at hour h
        kind[:, S_ROUTINE] = K_ROUTINE
        ptr[:, S_ROUTINE, 0] = G
        ptr[:, S_ROUTINE, 1] = S_PLACE + w.g_place[ep]
        f["hour"][:, S_ROUTINE] = hcode(w.g_hour[ep])
        kind[:, S_WITNESS] = K_WITNESS
        ptr[:, S_WITNESS, 0] = w.witness[ep]
        # talks
        kind[:, S_TALK:S_TALK + NTALK] = K_TALK
        ptr[:, S_TALK:S_TALK + NTALK, 0] = w.talk_teller[ep]
        ptr[:, S_TALK:S_TALK + NTALK, 1] = w.talk_hearer[ep]
        f["hour"][:, S_TALK:S_TALK + NTALK] = hcode(torch.arange(NTALK, device=dev) - NTALK).unsqueeze(0)
        # received proposal
        rx = self.rxp.view(B, 4)
        vis = (rx[:, 3] >= 0) & (rx[:, 3] <= hour)
        kind[:, S_RXP] = torch.where(vis, K_RXP, K_PAD)
        ptr[:, S_RXP, 0] = torch.where(vis, rx[:, 0], -1)
        ptr[:, S_RXP, 1] = torch.where(vis, S_PLACE + rx[:, 1].clamp(min=0), -1)
        f["hour"][:, S_RXP] = torch.where(vis, hcode(rx[:, 2].clamp(min=0)), 0)
        # acceptances received, proposals sent
        for s0, k_kind, arr in ((S_RXA, K_RXA, self.rxa), (S_TXP, K_TXP, self.txp)):
            a = arr.view(B, 3, 2)
            vis = (a[..., 1] >= 0) & (a[..., 1] <= hour)
            kind[:, s0:s0 + 3] = torch.where(vis, k_kind, K_PAD)
            ptr[:, s0:s0 + 3, 0] = torch.where(vis, a[..., 0], -1)
        cm = self.commit.view(B, 3)
        vis = (cm[:, 2] >= 0) & (cm[:, 2] <= hour)
        kind[:, S_COMMIT] = torch.where(vis, K_COMMIT, K_PAD)
        ptr[:, S_COMMIT, 1] = torch.where(vis, S_PLACE + cm[:, 0].clamp(min=0), -1)
        f["hour"][:, S_COMMIT] = torch.where(vis, hcode(cm[:, 1].clamp(min=0)), 0)
        kind[:, S_CLOCK] = K_CLOCK
        f["hour"][:, S_CLOCK] = hour + 1
        f["mode"][:, S_CLOCK] = 2 if mode_reflect else 1
        return {"kind": kind, "ptr": ptr, **f}

    # ---- dynamics ----------------------------------------------------------------------------------------
    def apply(self, hour, act):
        """act: dict of [N, V] tensors: type, person, place, hour. Messages are seen the next hour."""
        w, N = self.w, self.w.N
        dev = w.bold.device
        ar = torch.arange(N, device=dev)
        typ = act["type"]
        self.n_decisions += N * V
        for a in range(V):
            t = typ[:, a]
            # PROPOSE
            y = act["person"][:, a]
            okp = (t == PROPOSE) & (y != a) & (y >= 0) & (y < NP)
            self.invited_outside |= okp & ~w.coalition[ar, y.clamp(0, NP - 1)]
            okp &= y < V                                                       # a proposal to George: no receiver
            n_sent = (self.txp[:, a, :, 0] >= 0).sum(1)
            slot = n_sent.clamp(max=2)
            can = okp & (n_sent < 3)
            self.txp[ar[can], a, slot[can]] = torch.stack([y[can], torch.full_like(y[can], hour + 1)], 1)
            yy = y.clamp(0, V - 1)
            free = self.rxp[ar, yy, 0] < 0
            rec = can & free
            self.rxp[ar[rec], yy[rec]] = torch.stack([torch.full_like(y[rec], a), act["place"][rec, a],
                                                     act["hour"][rec, a], torch.full_like(y[rec], hour + 1)], 1)
            nocom = can & (self.commit[:, a, 0] < 0)
            self.commit[ar[nocom], a] = torch.stack([act["place"][nocom, a], act["hour"][nocom, a],
                                                    torch.full_like(y[nocom], hour + 1)], 1)
            # ACCEPT the proposal received (if visible)
            rx = self.rxp[:, a]
            oka = (t == ACCEPT) & (rx[:, 3] >= 0) & (rx[:, 3] <= hour)
            frm = rx[:, 0].clamp(0, V - 1)
            n_acc = (self.rxa[ar, frm, :, 0] >= 0).sum(1)
            oka2 = oka & (n_acc < 3)
            self.rxa[ar[oka2], frm[oka2], n_acc[oka2]] = torch.stack([torch.full_like(frm[oka2], a),
                                                                      torch.full_like(frm[oka2], hour + 1)], 1)
            self.commit[ar[oka], a] = torch.stack([rx[oka, 1], rx[oka, 2], torch.full_like(frm[oka], hour + 1)], 1)
        # GO: position for the next hour
        go = typ == GO
        self.loc = torch.where(go, act["place"], self.loc)
        self.moved_to_g |= (go & (act["place"] == w.g_place.unsqueeze(1))).any(1)
        if hour + 1 == 0:
            pass

    def reflect_apply(self, act, active=None):
        """WRITE knows(person, since) on the villager's own records; STOP ends this villager's reflection.
        active [N, V]: villagers still reflecting (adaptive computation: only they pay a decision)."""
        N = self.w.N
        active = torch.ones(N, V, dtype=torch.bool, device=act["type"].device) if active is None else active
        self.n_decisions += int(active.sum())
        wr = (act["type"] == WRITE) & active
        y = act["person"].clamp(0, NP - 1)
        cur = torch.gather(self.flag, 2, y.unsqueeze(-1)).squeeze(-1)
        new = torch.where(wr, act["since"], cur)
        self.flag.scatter_(2, y.unsqueeze(-1), new.unsqueeze(-1))

    def success(self, at_hour_loc):
        """at_hour_loc [N, V] positions during George's hour."""
        w = self.w
        at = at_hour_loc == w.g_place.unsqueeze(1)
        all_there = ~(w.coalition[:, :V] & ~at).any(1)
        ok_c = w.has_coalition & all_there & ~self.invited_outside
        ok_n = ~w.has_coalition & ~self.invited_outside & ~self.moved_to_g
        return torch.where(w.has_coalition, ok_c, ok_n)


# ----------------------------------------------------------------------------------------------- teacher
class Teacher:
    """The exact policy (what the professor would label)."""

    @staticmethod
    def act(env: CoalitionEnv, hour):
        w, N = env.w, env.w.N
        dev = w.bold.device
        ar = torch.arange(N, device=dev)
        typ = torch.zeros(N, V, dtype=torch.long, device=dev)
        person = torch.zeros(N, V, dtype=torch.long, device=dev)
        place = w.g_place.unsqueeze(1).expand(N, V).clone()
        hr = w.g_hour.unsqueeze(1).expand(N, V).clone()
        L = w.leader
        csize = w.coalition.sum(1)
        # leader proposes to member order[hour + 1] at hours 0 .. |C| - 2
        k = hour + 1
        lead_now = w.has_coalition & (k < csize)
        tgt = w.order[:, min(k, NP - 1)]
        typ[ar[lead_now], L[lead_now]] = PROPOSE
        person[ar[lead_now], L[lead_now]] = tgt[lead_now]
        # members accept the hour after they were proposed to (proposal visible)
        rx = env.rxp
        acc = (rx[..., 3] == hour) & w.coalition[:, :V]
        typ = torch.where(acc, ACCEPT, typ)
        # members go the hour before George's hour
        go = w.coalition[:, :V] & w.has_coalition.unsqueeze(1) & (hour == w.g_hour - 1).unsqueeze(1)
        typ = torch.where(go, GO, typ)
        return {"type": typ, "person": person, "place": place, "hour": hr}

    @staticmethod
    def reflect(env: CoalitionEnv, step):
        """Write the knowers in the order they learned (the witness first), with the hour they learned."""
        w, N = env.w, env.w.N
        dev = w.bold.device
        since = torch.where(w.knows, w.since, torch.full_like(w.since, 999))
        order = torch.argsort(since * 8 + torch.arange(NP, device=dev), 1)       # stable order by learning hour
        nk = w.knows.sum(1)
        y = order[:, min(step, NP - 1)]
        write = step < nk
        typ = torch.where(write, WRITE, STOP).unsqueeze(1).expand(N, V).clone()
        s = torch.gather(w.since, 1, y.unsqueeze(1)).squeeze(1).clamp(min=-10)
        return {"type": typ, "person": y.unsqueeze(1).expand(N, V).clone(),
                "since": s.unsqueeze(1).expand(N, V).clone()}


# ------------------------------------------------------------------------------------------------ models
class CoalitionNet(nn.Module):
    """Set-Transformer with pointer messages and per-head pointer attention bias; heads on the clock token.
    loops > 1: the blocks are re-applied (shared weights in depth) with a per-iteration embedding."""

    def __init__(self, d=128, layers=4, heads=4, ff=512, loops=1, tom=False, tom_since=False):
        super().__init__()
        self.d, self.h, self.loops, self.tom, self.tom_since = d, heads, loops, tom, tom_since
        self.kind = nn.Embedding(11, d)
        sizes = {"handle": 17, "bold": 7, "me": 3, "george": 3, "wr": 4, "kn": 3, "hour": 35, "mode": 3}
        self.fields = nn.ModuleDict({k: nn.Embedding(n, d) for k, n in sizes.items()})
        self.msg = nn.ModuleList([nn.Linear(d, d, bias=False) for _ in range(3)])
        self.pbias = nn.Parameter(torch.randn(3, 2, heads) * 0.5)
        self.blocks = nn.ModuleList([Block(d, heads, ff) for _ in range(layers)])
        self.iter_emb = nn.Parameter(torch.zeros(loops, d))
        self.ln = nn.LayerNorm(d)
        self.type_head = nn.Linear(d, 6)
        self.q_person, self.q_place = nn.Linear(d, d), nn.Linear(d, d)
        self.k = nn.Linear(d, d)
        self.hour_head, self.since_head = nn.Linear(d, 24), nn.Linear(d, 11)
        if tom:                                          # knows (2) + in coalition (2) [+ since (11)], person tokens
            self.tom_head = nn.Linear(d, 4 + (11 if tom_since else 0))

    def forward(self, tok):
        kind, ptr = tok["kind"], tok["ptr"]
        B, Tn = kind.shape
        x = self.kind(kind)
        for k, emb in self.fields.items():
            x = x + emb(tok[k])
        base = x
        ok = ptr >= 0
        idx = ptr.clamp(min=0)
        bias = torch.zeros(B, self.h, Tn, Tn, device=x.device, dtype=x.dtype)
        for k in range(3):
            g = torch.gather(base, 1, idx[..., k:k + 1].expand(B, Tn, self.d))
            x = x + self.msg[k](g) * ok[..., k:k + 1]
            adj = torch.zeros(B, Tn, Tn + 1, device=x.device, dtype=x.dtype)
            adj.scatter_(2, torch.where(ok[..., k:k + 1], idx[..., k:k + 1], Tn), 1.0)
            adj = adj[..., :Tn]
            bias = bias + adj.unsqueeze(1) * self.pbias[k, 0].view(1, -1, 1, 1) \
                + adj.transpose(1, 2).unsqueeze(1) * self.pbias[k, 1].view(1, -1, 1, 1)
        bias = bias.masked_fill((kind == K_PAD).view(B, 1, 1, Tn), -1e4)
        for it in range(self.loops):
            x = x + self.iter_emb[it]
            for blk in self.blocks:
                x = blk(x, bias)
        x = self.ln(x)
        h = x[:, S_CLOCK]
        keys = self.k(x)
        out = {"type": self.type_head(h),
               "person": torch.einsum("bd,btd->bt", self.q_person(h), keys[:, S_PERSON:S_PERSON + NP]),
               "place": torch.einsum("bd,btd->bt", self.q_place(h), keys[:, S_PLACE:S_PLACE + NL]),
               "hour": self.hour_head(h), "since": self.since_head(h)}
        if self.tom:
            out["tom"] = self.tom_head(x[:, S_PERSON:S_PERSON + NP])
        return out

    def flops_per_decision(self):
        d, ff = self.d, self.blocks[0].ff[0].out_features
        per_layer = 2 * T * (4 * d * d + 2 * d * ff) + 4 * T * T * d
        return self.loops * len(self.blocks) * per_layer


MODELS = {
    "direct4": dict(layers=4),
    # controls asked by the adversarial review (13 oct.)
    "tomsince4": dict(layers=4, tom=True, tom_since=True),   # the SAME intermediate supervision as reflect4
                                                             # (who knows, since when) but in one pass, not written
    "reflect4noisy": dict(layers=4, reflect=True, noise=0.2),  # reflect4 trained on a teacher trace with 20 % of
                                                               # its written beliefs wrong (an imperfect LLM teacher)
    "direct8long": dict(layers=8, steps_mult=2),             # direct8 trained twice as long
    "direct8": dict(layers=8),
    "tom4": dict(layers=4, tom=True),
    "loop4": dict(layers=2, loops=4),
    "reflect4": dict(layers=4, reflect=True),
}


# ---------------------------------------------------------------------------------------------- training
class Episodes:
    """Teacher rollouts -> (tokens, targets) of every decision, NOOPs down-weighted when sampling a batch."""

    def __init__(self, N, gen, reflect, noise=0.0):
        self.world = CoalitionWorld.sample(N, gen)
        env = CoalitionEnv(self.world)
        toks, tgts = [], []
        if reflect:
            for s in range(MAXR + 1):
                tk = env.tokens(0, mode_reflect=True)
                a = Teacher.reflect(env, s)
                if noise > 0:                                 # imperfect teacher: some written beliefs are wrong
                    bad = (torch.rand(N, generator=gen, device=tk["kind"].device) < noise).unsqueeze(1).expand(N, V)
                    rp = torch.randint(0, NP, (N, 1), generator=gen, device=bad.device).expand(N, V)
                    rs = torch.randint(-10, 0, (N, 1), generator=gen, device=bad.device).expand(N, V)
                    a = dict(a, person=torch.where(bad & (a["type"] == WRITE), rp, a["person"]),
                             since=torch.where(bad & (a["type"] == WRITE), rs, a["since"]))
                toks.append(tk)
                tgts.append(self._target(a, reflect=True))
                env.reflect_apply(a)
        for hour in range(HOURS):
            tk = env.tokens(hour)
            a = Teacher.act(env, hour)
            toks.append(tk)
            tgts.append(self._target(a, reflect=False))
            env.apply(hour, a)
        self.tok = {k: torch.cat([t[k] for t in toks]).to(torch.int8) for k in toks[0]}      # memory
        self.tgt = {k: torch.cat([t[k] for t in tgts]) for k in tgts[0]}
        ep = torch.arange(N, device=self.world.bold.device).repeat_interleave(V)
        self.ep = ep.repeat(len(toks))
        self.me = torch.arange(V, device=ep.device).repeat(N).repeat(len(toks))
        w = torch.where(self.tgt["type"] == NOOP, 0.08, 1.0)
        self.weight = w

    @staticmethod
    def _target(a, reflect):
        out = {"type": a["type"].reshape(-1), "person": a["person"].reshape(-1),
               "place": a.get("place", torch.zeros_like(a["type"])).reshape(-1),
               "hour": a.get("hour", torch.zeros_like(a["type"])).reshape(-1),
               "since": (a.get("since", torch.full_like(a["type"], -10)) + 10).clamp(0, 10).reshape(-1)}
        return out

    def batch(self, n, gen):
        idx = torch.multinomial(self.weight, n, replacement=True, generator=gen)
        return ({k: v[idx].long() for k, v in self.tok.items()}, {k: v[idx] for k, v in self.tgt.items()},
                self.ep[idx], self.me[idx])


def loss_fn(out, tgt, tom_target=None):
    typ = tgt["type"]
    loss = F.cross_entropy(out["type"].float(), typ)
    need_p = (typ == PROPOSE) | (typ == WRITE)
    need_place = (typ == PROPOSE) | (typ == GO)
    if need_p.any():
        loss = loss + F.cross_entropy(out["person"][need_p].float(), tgt["person"][need_p])
    if need_place.any():
        loss = loss + F.cross_entropy(out["place"][need_place].float(), tgt["place"][need_place])
    if (typ == PROPOSE).any():
        m = typ == PROPOSE
        loss = loss + F.cross_entropy(out["hour"][m].float(), tgt["hour"][m])
    if (typ == WRITE).any():
        m = typ == WRITE
        loss = loss + F.cross_entropy(out["since"][m].float(), tgt["since"][m])
    if tom_target is not None:
        kn, mem, mem_ok, since = tom_target
        lg = out["tom"].float()
        if lg.shape[-1] > 4:
            loss = loss + 0.5 * F.cross_entropy(lg[..., 4:].reshape(-1, 11), since.reshape(-1))
        loss = loss + 0.5 * F.cross_entropy(lg[..., :2].reshape(-1, 2), kn.reshape(-1).long())
        if mem_ok.any():
            loss = loss + 0.5 * F.cross_entropy(lg[..., 2:4][mem_ok].reshape(-1, 2), mem[mem_ok].reshape(-1).long())
    return loss


class Student:
    """Greedy decoding of the trained model in the closed-loop environment."""

    def __init__(self, model):
        self.model = model

    @torch.no_grad()
    def act(self, env, hour, reflect=False):
        tok = env.tokens(hour, mode_reflect=reflect)
        rows = tok["kind"].shape[0]
        parts = []
        for i in range(0, rows, 4096):                                          # chunks: GPU memory
            with torch.autocast("cuda", dtype=torch.float16):
                o = self.model({k: v[i:i + 4096] for k, v in tok.items()})
            parts.append({k: v.float() for k, v in o.items() if k != "tom"})
        out = {k: torch.cat([p[k] for p in parts]) for k in parts[0]}
        N = env.w.N
        typ = out["type"].argmax(-1)
        if reflect:
            typ = torch.where(typ == WRITE, WRITE, STOP)
        else:
            typ = torch.where(typ >= WRITE, NOOP, typ)
        return {"type": typ.view(N, V), "person": out["person"].argmax(-1).view(N, V),
                "place": out["place"].argmax(-1).view(N, V), "hour": out["hour"].argmax(-1).view(N, V),
                "since": (out["since"].argmax(-1) - 10).view(N, V)}


class Experiment:
    def __init__(self, name, seed, steps, batch, lr):
        self.name, self.seed, self.steps, self.batch, self.lr = name, seed, steps, batch, lr
        spec = dict(MODELS[name])
        self.reflect = spec.pop("reflect", False)
        self.noise = spec.pop("noise", 0.0)
        self.steps = steps * spec.pop("steps_mult", 1)
        torch.manual_seed(seed)
        self.model = CoalitionNet(**spec).cuda()
        self.gen = torch.Generator(device="cuda").manual_seed(2000 + seed)

    def tom_targets(self, ep_world, ep, me):
        w = ep_world
        kn = w.knows[ep]                                                          # [n, NP]
        mem = w.coalition[ep]
        mem_ok = w.knows[ep, me].unsqueeze(1).expand_as(mem)                      # only a knower can tell
        since = torch.where(kn, (w.since[ep].clamp(min=-10) + 10).clamp(0, 9), torch.full_like(w.since[ep], 10))
        return kn, mem, mem_ok, since

    def train(self):
        opt = torch.optim.AdamW(self.model.parameters(), lr=self.lr, weight_decay=0.01)
        sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=self.lr, total_steps=self.steps, pct_start=0.05)
        scaler = torch.amp.GradScaler("cuda")
        t0, log, pool, left = time.time(), [], None, 0
        self.model.train()
        for step in range(self.steps):
            if left == 0:
                pool, left = Episodes(2048, self.gen, self.reflect, self.noise), 20
            left -= 1
            tok, tgt, ep, me = pool.batch(self.batch, self.gen)
            with torch.autocast("cuda", dtype=torch.float16):
                out = self.model(tok)
                tt = self.tom_targets(pool.world, ep, me) if self.model.tom else None
                loss = loss_fn(out, tgt, tt)
            opt.zero_grad(set_to_none=True)
            scaler.scale(loss).backward()
            scaler.unscale_(opt)
            torch.nn.utils.clip_grad_norm_(self.model.parameters(), 1.0)
            scaler.step(opt)
            scaler.update()
            sched.step()
            if step % 250 == 0 or step == self.steps - 1:
                acc = (out["type"].argmax(-1) == tgt["type"]).float().mean().item()
                log.append({"step": step, "loss": loss.item(), "type_acc": acc, "s": time.time() - t0})
                print(f"  [{self.name} s{self.seed}] step {step:5d} loss {loss.item():.3f} type acc {acc:.3f} "
                      f"({time.time() - t0:.0f} s)", flush=True)
        return log, time.time() - t0

    @torch.no_grad()
    def evaluate(self, n=4096):
        self.model.eval()
        gen = torch.Generator(device="cuda").manual_seed(777_777)               # same held-out episodes for all
        world = CoalitionWorld.sample(n, gen)
        env = CoalitionEnv(world)
        st = Student(self.model)
        res = {}
        if self.reflect:
            active = torch.ones(n, V, dtype=torch.bool, device="cuda")
            for s in range(MAXR + 1):
                a = st.act(env, 0, reflect=True)
                env.reflect_apply(a, active)
                active &= a["type"] == WRITE
            fl = env.flag > -99                                                    # [N, V, NP]
            truth = world.knows.unsqueeze(1).expand_as(fl)
            res["reflected_knows_exact"] = float((fl == truth).all(-1).float().mean())
        loc_at = torch.zeros(n, V, dtype=torch.long, device="cuda")
        first_tx = None
        for hour in range(HOURS):
            env.apply(hour, st.act(env, hour))
            hit = (hour + 1) == world.g_hour                                       # position during George's hour
            loc_at = torch.where(hit.unsqueeze(1), env.loc, loc_at)
        succ = env.success(loc_at)
        hc = world.has_coalition
        # who did the student invite (any proposal sent), vs the coalition minus the leader
        sent = torch.zeros(n, NP, dtype=torch.bool, device="cuda")
        for a in range(V):
            to = env.txp[:, a, :, 0]
            for s in range(3):
                okk = to[:, s] >= 0
                sent[torch.arange(n, device="cuda")[okk], to[okk, s]] = True
        want = world.coalition.clone()
        want[torch.arange(n, device="cuda"), world.leader] = False
        exact_inv = (sent == want).all(1)
        # chain length of the farthest member: talks between the witness and him
        depth = torch.where(world.coalition, world.hops, 0).amax(1)
        res.update({"success": float(succ.float().mean()), "success_coalition": float(succ[hc].float().mean()),
                    "success_no_coalition": float(succ[~hc].float().mean()),
                    "exact_invites": float(exact_inv[hc].float().mean()),
                    "secrecy_violation": float(env.invited_outside.float().mean()),
                    "decisions_per_episode_per_villager": env.n_decisions / (n * V)})
        # success by "late knowledge" of the coalition (talk hour of the last member to learn: proxy of chain length)
        for lo, hi, nm in ((0, 2, "hops<=1"), (2, 3, "hops=2"), (3, 99, "hops>=3")):
            m = hc & (depth >= lo) & (depth < hi)
            res[f"success/{nm}"] = float(succ[m].float().mean()) if m.any() else None
            res[f"n/{nm}"] = int(m.sum())
        return res


@torch.no_grad()
def teacher_check(n=4096):
    """The exact teacher plays the held-out episodes in the same closed loop: it must succeed everywhere."""
    gen = torch.Generator(device="cuda").manual_seed(777_777)
    w = CoalitionWorld.sample(n, gen)
    env = CoalitionEnv(w)
    for s in range(MAXR + 1):
        env.reflect_apply(Teacher.reflect(env, s))
    loc_at = torch.zeros(n, V, dtype=torch.long, device="cuda")
    for h in range(HOURS):
        env.apply(h, Teacher.act(env, h))
        loc_at = torch.where(((h + 1) == w.g_hour).unsqueeze(1), env.loc, loc_at)
    succ = env.success(loc_at)
    return {"success": float(succ.float().mean()), "secrecy_violation": float(env.invited_outside.float().mean()),
            "reflected_knows_exact": float(((env.flag > -99) == w.knows.unsqueeze(1)).all(-1).float().mean())}


def hops_stats(gen):
    """How many talks a knower is away from the witness (chain length), on held-out episodes."""
    w = CoalitionWorld.sample(4096, gen)
    return {"coalition_share": float(w.has_coalition.float().mean()),
            "mean_knowers": float(w.knows.float().sum(1).mean()), "mean_coalition": float(w.coalition.float().sum(1).mean())}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default="direct4,direct8,tom4,loop4,reflect4")
    ap.add_argument("--seeds", default="0,1")
    ap.add_argument("--steps", type=int, default=3000)
    ap.add_argument("--batch", type=int, default=1024)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--out", default="probe_coalition.json")
    a = ap.parse_args()
    path = os.path.join(RESULTS, a.out)
    results = json.load(open(path)) if os.path.exists(path) else {"runs": []}
    results["world"] = hops_stats(torch.Generator(device="cuda").manual_seed(1))
    results["teacher_closed_loop"] = teacher_check()
    print("teacher in closed loop:", results["teacher_closed_loop"])
    print("world:", results["world"])
    for name in a.models.split(","):
        for seed in [int(s) for s in a.seeds.split(",")]:
            exp = Experiment(name, seed, a.steps, a.batch, a.lr)
            npar = sum(p.numel() for p in exp.model.parameters())
            fl = exp.model.flops_per_decision()
            print(f"== {name} seed {seed}: {npar / 1e6:.2f} M params, {fl / 1e6:.0f} MFLOP/decision", flush=True)
            log, secs = exp.train()
            ev = exp.evaluate()
            print(f"   eval {name} s{seed}: " + ", ".join(f"{k} {v:.3f}" if isinstance(v, float) else f"{k} {v}"
                                                      for k, v in ev.items()), flush=True)
            results["runs"] = [r for r in results["runs"] if not (r["model"] == name and r["seed"] == seed)]
            results["runs"].append({"model": name, "seed": seed, "params": npar, "mflop_per_decision": fl / 1e6,
                                    "steps": exp.steps, "batch": a.batch, "train_s": secs, "log": log, "eval": ev})
            results.update(gpu=torch.cuda.get_device_name(0), torch=torch.__version__,
                           date=time.strftime("%Y-%m-%d %H:%M"))
            os.makedirs(RESULTS, exist_ok=True)
            json.dump(results, open(path, "w"), indent=1)
    print("saved", path)


if __name__ == "__main__":
    main()
