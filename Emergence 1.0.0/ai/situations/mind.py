"""mind.py - the NPC's mind in a scene: the records tok-2 reads (what he perceives, believes, remembers, wants).

Built from the TRUE scene with noise and ignorance: apparent ages are guessed, owners are believed, people are
mistaken, absent people are remembered. A numeric field the scene says nothing about gets a plausible value drawn
from its scale only (NumericPrior): no meaning is invented. D10: intimate fields (attraction, drive for intimacy,
sexual orientation) exist only for an adult NPC, toward a person he sees who is an adult by truth and appearance
(or whom he believes an adult, if absent).

One builder per kind of record (builders.py); MindBuilder runs them in order and returns a `Mind`.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from tok2 import Record

from .builders import (BeliefBuilder, EventBuilder, MemoryBuilder, PersonBuilder, PlaceBuilder, SelfBuilder,
                       SkillBuilder, SocialBuilder, StateBuilder, ThingBuilder, WakeBuilder)
from .context import BuildContext
from .planning import GoalBuilder, GroupBuilder, PlanBuilder
from .violence import PlotSummary, ViolenceBuilder
from .pools import Pools
from .propositions import PropositionGrammar
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
    structure: str = "ordinary"                                  # the family of structure it was built around
    plot: PlotSummary | None = None                              # the plot of force it carries, if any (never shown to the model)

    def known_keys(self) -> list[str]:
        return [r.key for r in self.records] + self.extra_known


class MindBuilder:
    # the order matters: SELF_STATE needs the events and the body, WAKE needs everything
    PIPELINE = (SelfBuilder, PersonBuilder, ThingBuilder, PlaceBuilder, EventBuilder, BeliefBuilder, MemoryBuilder,
                SocialBuilder, GroupBuilder, ViolenceBuilder, GoalBuilder, PlanBuilder, SkillBuilder, StateBuilder, WakeBuilder)

    def __init__(self, pools: Pools, grammar: PropositionGrammar):
        self.pools, self.grammar = pools, grammar
        self.builders = [b() for b in self.PIPELINE]                 # built once, reused for every situation

    def build(self, scene: Scene, rng: random.Random, cause: str = "routine", structure: str = "ordinary") -> Mind:
        c = BuildContext(rng, self.pools, self.grammar, scene, cause, structure)
        for b in self.builders:
            b.build(c)
        return Mind(c.records.ordered(TYPE_ORDER), c.layout.people(scene.self_), [g.key for g in c.layout.ghosts], structure, c.plot)
