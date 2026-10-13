"""sampler.py - plausible situations (an NPC's mind at one moment) for the teacher pilot and the first training.

    python3 -m situations.sampler --n 500            (from ai/)  statistics: tokens per type, dropped propositions
    python3 -m situations.sampler --show 3           one situation, record by record

Deterministic: situation i of seed s is always the same. Every situation is tokenized by tok-2 and audited for
D10 before it is returned. It only builds what the NPC perceives, believes and wants: it never decides.
"""
from __future__ import annotations

import argparse
import random
import time
from collections import Counter
from dataclasses import dataclass, field

from tok2 import DecisionContext, Encoded, Tokenizer

from .audit import D10Audit
from .builders import WAKE_CAUSES
from .draw import Draw
from .gestures import INFANT
from .mind import MindBuilder
from .pools import Pools
from .propositions import PropositionGrammar
from .scene import Person, Scene, SceneFactory


NEEDS_COMPANY = ("perception", "speech", "request")      # words and gestures need somebody there


@dataclass
class Situation:
    seed: int
    index: int
    scene: Scene
    context: DecisionContext
    encoded: Encoded
    people: dict[str, Person] = field(default_factory=dict)    # key ('me', @E1…, ghosts) -> the TRUE person behind it


class SituationSampler:
    def __init__(self, seed: int = 0, pools: Pools | None = None):
        self.seed = seed
        self.pools = pools or Pools()
        self.grammar = PropositionGrammar(self.pools)               # the vocabulary and the chooser: built once
        self.tokenizer = Tokenizer(self.pools.interface, grammar=self.grammar.vocab)
        self.audit = D10Audit(self.pools)
        self.minds = MindBuilder(self.pools, self.grammar)          # builders are built once and reused
        self.stats = self.grammar.stats

    def sample(self, index: int) -> Situation:
        rng = random.Random(f"situation:{self.seed}:{index}")
        cause = Draw(rng).weighted(WAKE_CAUSES)                      # why he wakes comes first; the rest justifies it
        scene = SceneFactory(rng, self.pools, self.grammar.rules).make(needs_company=cause in NEEDS_COMPANY)
        if scene.self_.age < INFANT and cause in ("speech", "request"):    # a baby neither speaks nor is asked anything
            cause = "perception"
        mind = self.minds.build(scene, rng, cause)
        self.audit.check(scene.self_, mind.records, mind.people)
        ctx = DecisionContext(mind.records, known_keys=mind.known_keys())
        return Situation(self.seed, index, scene, ctx, self.tokenizer.encode(ctx), mind.people)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--show", type=int, default=None)
    a = ap.parse_args(argv)
    s = SituationSampler(a.seed)
    if a.show is not None:
        sit = s.sample(a.show)
        print(f"{sit.scene.place.name}, {sit.scene.hour:.1f} h, {sit.scene.season}; NPC {sit.scene.self_.age:.0f} ans")
        for r in sit.context.records:
            print(f"  {r.type:<10} {r.key:<9} " + ", ".join(f"{k}={v}" for k, v in r.fields.items() if v not in (None, [], {})))
        return
    per_type, tokens, t0 = Counter(), [], time.perf_counter()
    for i in range(a.n):
        sit = s.sample(i)
        tokens.append(sit.encoded.n)
        per_type.update(r.type for r in sit.context.records)
    dt = (time.perf_counter() - t0) / a.n
    made, dropped, refused = s.stats.made, s.stats.invalid, s.stats.refused
    print(f"{a.n} situations, {dt * 1000:.1f} ms each; tokens min {min(tokens)} mean {sum(tokens) / len(tokens):.1f} "
          f"max {max(tokens)}; propositions kept {made}, invalid {dropped} ({dropped / max(1, made + dropped + refused):.2%}), "
          f"refused by the governor {refused} ({refused / max(1, made + dropped + refused):.2%})")
    print("records per situation: " + ", ".join(f"{t} {c / a.n:.1f}" for t, c in sorted(per_type.items())))


if __name__ == "__main__":
    main()
