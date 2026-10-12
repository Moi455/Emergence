"""mind.py - the NPC's mind in a scene: the records tok-2 reads (what he perceives, believes, remembers, wants).

Built from the TRUE scene with noise and ignorance: apparent ages are guessed, owners are believed, absent people
are remembered. A numeric field the scene says nothing about gets a plausible value drawn from its scale only
(NumericPrior): no meaning is invented. D10: intimate fields (attraction, drive for intimacy, sexual orientation)
exist only for an adult NPC, toward a person who is an adult by truth, appearance and belief.

One builder per kind of record (builders.py); MindBuilder runs them in order and returns a `Mind`.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from tok2 import Record

from .builders import (BeliefBuilder, BuildContext, EventBuilder, GoalBuilder, MemoryBuilder, PersonBuilder,
                       PlaceBuilder, SelfBuilder, SkillBuilder, SocialBuilder, StateBuilder, ThingBuilder,
                       WakeBuilder)
from .pools import Pools
from .propositions import PropositionFactory
from .scene import Person, Scene

# the order of the records in the context (the tokenizer groups them by type anyway)
TYPE_ORDER = ("SELF", "SELF_MIND", "SELF_STATE", "ENTITY", "THING", "INV", "PLACE", "LOCUS", "GROUP", "BELIEF", "HEARD",
              "MEMORY", "GOAL", "PLAN", "REQUEST", "COMMIT", "SKILL", "TASTE", "EVENT", "WAKE")


@dataclass
class Mind:
    """What a build returns: the records, the truth behind the keys (for the audit and the engine's governor), and
    the keys of the people he knows whose files the context selector left out."""
    records: list[Record]
    people: dict[str, Person] = field(default_factory=dict)      # 'me', @E keys (filed, then ghosts) -> the true person
    extra_known: list[str] = field(default_factory=list)         # ghost keys

    def known_keys(self) -> list[str]:
        return [r.key for r in self.records] + self.extra_known


class MindBuilder:
    # SELF_STATE needs the events and the body; WAKE needs everything: this is the order of construction
    PIPELINE = (SelfBuilder, PersonBuilder, ThingBuilder, PlaceBuilder, EventBuilder, BeliefBuilder, MemoryBuilder,
                SocialBuilder, GoalBuilder, SkillBuilder, StateBuilder, WakeBuilder)

    def __init__(self, pools: Pools, props: PropositionFactory):
        self.pools, self.props = pools, props
        self.builders = [b() for b in self.PIPELINE]                 # built once, reused for every situation

    def build(self, scene: Scene, rng: random.Random) -> Mind:
        c = BuildContext(rng, self.pools, self.props, self.props.chooser, scene)
        for b in self.builders:
            b.build(c)
        records = [r for t in TYPE_ORDER for r in c.of(t)]
        people = {"me": scene.self_} | {e.key: e.person for e in c.entries} | {g.key: g.person for g in c.ghosts}
        return Mind(records, people, [g.key for g in c.ghosts])
