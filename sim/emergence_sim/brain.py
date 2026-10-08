"""The brain socket: who decides for an NPC.

The simulation never decides by itself. At each tick it gathers every NPC that
must decide (end of plan, interruption), asks the brain for all of them in ONE
batch, then executes the chosen options. Two brains plug in:

  TransformerBrain   the data thread's model (ai/student/student_model.py) on
                     tok-1 tokens built from the live state (live.py), over the
                     options the engine says are feasible (options.py).
  ReferenceBrain     the old utility rules (decide.candidates), kept frozen as a
                     measuring stick for A/B runs. It is not extended any more.

A brain returns, per NPC, the chosen option, a score per option, and optional
state deltas. The Governor applies deltas within the bounds of the catalogue
(docs/npc/variables_v0.3_catalogue_unique.md): an emotion may jump, everything
else moves by small steps, and what the engine owns (body, goods, coin) is
never written by the brain.
"""
import hashlib
import os
import sys
import time

from . import options as opts
from .model import AFF, TRUST, RESPECT, ROMANCE, FAM, GRUDGE, clamp
from .rng import hash_ints
from .rules import romance_ok


class Choice:
    __slots__ = ("index", "scores", "deltas")

    def __init__(self, index, scores, deltas=None):
        self.index = index
        self.scores = scores
        self.deltas = deltas


class Brain:
    name = "brain"

    def options(self, sim, n):
        raise NotImplementedError

    def choose(self, sim, batch):
        """batch: list of (npc, options) in id order -> list of Choice, same order."""
        raise NotImplementedError

    def stats(self):
        return {}


# ------------------------------------------------------------------ reference (frozen rules)
class ReferenceBrain(Brain):
    name = "reference"

    def options(self, sim, n):
        from .decide import candidates, MAX_CAND
        cands = candidates(sim, n)
        cands.sort(key=lambda c: (-c.u, c.key))
        return cands[:MAX_CAND]

    def choose(self, sim, batch):
        out = []
        for n, cands in batch:
            noise = 20 + (n.tr["impulsivity"] + 100) // 4
            scores = [c.u + sim.rng.below(noise) for c in cands]
            best = max(range(len(cands)), key=lambda i: (scores[i], -i))
            out.append(Choice(best, scores))
        return out


# ------------------------------------------------------------------ transformer
def _student_module():
    from .live import ai_path
    p = os.path.join(os.path.dirname(ai_path()), "student")
    if p not in sys.path:
        sys.path.insert(0, p)
    import student_model
    return student_model


class TransformerBrain(Brain):
    """Scores the engine's options with the Transformer, all waiting NPCs in one forward pass.

    checkpoint   path to a .pt written by ai/student/train_student.py; None = untrained weights (plumbing and timing only)
    temperature  0 = argmax; > 0 = deterministic Gumbel sampling from hash(seed, tick, npc), never the sim RNG
    cache        identical token sequences (same NPC situation, quantised) reuse the last scores
    """
    name = "transformer"

    def __init__(self, checkpoint=None, config="tiny", device="cpu", temperature=0.0, cache_size=8192, seed=0, threads=None):
        import torch
        from . import live
        self.torch = torch
        self.live = live
        sm = _student_module()
        enc, gs, sa, V = live.ai()
        if threads:
            torch.set_num_threads(threads)
        if checkpoint:
            ck = torch.load(checkpoint, map_location=device, weights_only=False)
            self.model = sm.Student(ck["vocab_size"], ck["F"], ck["config"])
            self.model.load_state_dict(ck["model"])
            self.config = ck["config"]
            if ck["vocab_size"] != len(V.table):
                raise ValueError(f"checkpoint vocabulary {ck['vocab_size']} != model_vocab.json {len(V.table)}")
        else:
            torch.manual_seed(seed)
            self.model = sm.Student(len(V.table), enc.F, config)
            self.config = config
        self.model.to(device).eval()
        self.trained = bool(checkpoint)
        self.device = device
        self.temperature = temperature
        self.cache_size = cache_size
        self.cache = {}
        self.n_params = sum(p.numel() for p in self.model.parameters())
        self.s = {"decisions": 0, "batches": 0, "forward": 0, "cache_hits": 0, "t_encode": 0.0, "t_model": 0.0,
                  "max_batch": 0, "tokens": 0}

    def options(self, sim, n):
        return opts.feasible(sim, n)

    def choose(self, sim, batch):
        torch = self.torch
        t0 = time.perf_counter()
        seqs, keys, todo = [], [], []
        for i, (n, o) in enumerate(batch):
            tk = self.live.tokens(sim, n, o)
            k = hashlib.blake2b(repr((tk["cat"], tk["num"])).encode(), digest_size=16).digest()
            seqs.append(tk)
            keys.append(k)
            if k not in self.cache:
                todo.append(i)
            self.s["tokens"] += len(tk["cat"])
        t1 = time.perf_counter()
        self.s["t_encode"] += t1 - t0
        if todo:
            B = len(todo)
            T = max(len(seqs[i]["cat"]) for i in todo)
            cat = torch.zeros((B, T, 9), dtype=torch.long)
            cat[..., 6:9] = -1
            num = torch.zeros((B, T, len(seqs[todo[0]]["num"][0])), dtype=torch.float32)
            mask = torch.zeros((B, T), dtype=torch.bool)
            for b, i in enumerate(todo):
                tk = seqs[i]
                nt = len(tk["cat"])
                cat[b, :nt] = torch.tensor(tk["cat"], dtype=torch.long)
                num[b, :nt] = torch.tensor(tk["num"], dtype=torch.float32) / 10.0
                mask[b, :nt] = True
            with torch.inference_mode():
                logits, drv = self.model(cat.to(self.device), num.to(self.device), mask.to(self.device))
            logits = logits.float().cpu()
            for b, i in enumerate(todo):
                tk = seqs[i]
                cf, nc = tk["cand_first"], tk["n_cands"]
                if len(self.cache) >= self.cache_size:
                    self.cache.pop(next(iter(self.cache)))
                self.cache[keys[i]] = [float(x) for x in logits[b, cf:cf + nc]]
            self.s["forward"] += B
            self.s["batches"] += 1
            self.s["max_batch"] = max(self.s["max_batch"], B)
        self.s["t_model"] += time.perf_counter() - t1
        self.s["cache_hits"] += len(batch) - len(todo)
        out = []
        for i, (n, o) in enumerate(batch):
            lg = self.cache[keys[i]]
            pick = lg
            if self.temperature > 0:
                pick = [l / self.temperature + gumbel(sim.seed, sim.t, n.id, j) for j, l in enumerate(lg)]
            best = max(range(len(pick)), key=lambda j: (pick[j], -j))
            out.append(Choice(best, [int(round(100 * l)) for l in lg]))
        self.s["decisions"] += len(batch)
        return out

    def stats(self):
        s = dict(self.s)
        s.update({"config": self.config, "params": self.n_params, "trained": self.trained, "device": self.device,
                  "cache_hit_rate": round(s["cache_hits"] / max(1, s["decisions"]), 3)})
        return s


def gumbel(seed, t, npc, j):
    import math
    u = (hash_ints(seed, 91, t, npc, j) % 1000000 + 0.5) / 1000000.0
    return -math.log(-math.log(u))


def make_brain(kind="reference", **kw):
    if kind == "reference":
        return ReferenceBrain()
    if kind == "transformer":
        return TransformerBrain(**kw)
    raise ValueError(kind)


# ------------------------------------------------------------------ governor
# Bounds per variable group, from the catalogue (column "Écriture"). None = the brain may not write it.
EMOTIONS = {"fear": (0, 100), "anger": (0, 100), "joy": (-100, 100), "stress": (0, 100)}
REL_IDX = {"affection": AFF, "trust": TRUST, "respect": RESPECT, "romance": ROMANCE, "familiarity": FAM, "grudge": GRUDGE}
STEP = {"rel": 5, "drive": 5, "grief": 10, "trait": 1, "value": 1}


class Governor:
    """Applies a brain's state deltas: an emotion may jump, the rest moves by bounded steps,
    traits and values by at most 1 per game day, engine-owned variables are refused."""

    def __init__(self):
        self.last_slow = {}            # (npc, var) -> day of the last trait/value change
        self.s = {"applied": 0, "clipped": 0, "refused": 0}

    def apply(self, sim, n, deltas):
        for key, d in sorted(deltas.items()):
            d = int(d)
            parts = key.split(".")
            grp = parts[0]
            if grp == "state" and parts[1] in EMOTIONS:
                lo, hi = EMOTIONS[parts[1]]
                setattr(n, parts[1], clamp(getattr(n, parts[1]) + d, lo, hi))
            elif grp == "state" and parts[1] == "grief":
                n.grief = clamp(n.grief + self._step(d, STEP["grief"]), 0, 100)
            elif grp == "rel" and len(parts) == 3 and parts[2] in REL_IDX:
                o = int(parts[1].lstrip("E"))
                if o not in n.rel:
                    self.s["refused"] += 1
                    continue
                i = REL_IDX[parts[2]]
                if i == ROMANCE and d > 0 and not romance_ok(sim, n, sim.npcs[o]):
                    self.s["refused"] += 1          # hard rule: no romance with a minor or kin, whatever the model says
                    continue
                n.rel[o][i] = clamp(n.rel[o][i] + self._step(d, STEP["rel"]), 0 if i in (FAM, GRUDGE) else -100, 100)
            elif grp == "drive" and parts[1] in n.drv:
                n.drv[parts[1]] = clamp(n.drv[parts[1]] + self._step(d, STEP["drive"]), 0, 100)
            elif grp in ("trait", "value") and (parts[1] in n.tr or parts[1] in n.val):
                k = (n.id, key)
                if self.last_slow.get(k) == sim.day:
                    self.s["refused"] += 1
                    continue
                self.last_slow[k] = sim.day
                tab, lo = (n.tr, -100) if grp == "trait" else (n.val, 0)
                tab[parts[1]] = clamp(tab[parts[1]] + self._step(d, STEP[grp]), lo, 100)
            else:
                self.s["refused"] += 1             # body, needs, goods, coin, skills: the engine's, not the brain's
                continue
            self.s["applied"] += 1

    def _step(self, d, m):
        if d > m or d < -m:
            self.s["clipped"] += 1
            return m if d > 0 else -m
        return d
