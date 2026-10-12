"""plans.py - the step the NPC is on, consistent with the goal it serves.

A small table from the predicate of a goal to the gestures that plausibly serve it (has -> go, take; at -> go, wait;
thirst -> drink; ...). This is the BUILDING of a situation (what he was already doing), not a decision: the model
still chooses what to do now. A step is kept only if the target accepts it and the governor allows it bare.
"""
from __future__ import annotations

from dataclasses import dataclass

import language

from .draw import Draw
from .gestures import CATEGORIES, GestureChooser, Target
from .parties import PartyBook
from .pools import Pools

WORKABLE = CATEGORIES["work"]


@dataclass(frozen=True)
class PlanStep:
    step: str
    next: str
    target: str


class PlanTable:
    """goal predicate -> (step, next) pairs, tried in a random order against the targets of the scene."""

    NEEDS = {"thirst": ("drinkable", "drink"), "hunger": ("edible", "eat")}

    def __init__(self, pools: Pools, chooser: GestureChooser):
        self.pools, self.chooser, self.parser = pools, chooser, language.Parser()

    def make(self, d: Draw, goal: str, view: "SceneView", book: PartyBook) -> PlanStep | None:
        node = self.parser.parse(goal)
        options = list(self._options(node, view))
        d.rng.shuffle(options)
        me = book.party("me")
        for step, nxt, target in options:
            t, tp = view.target(target), book.party(target)
            if step != nxt and all(self.chooser.permits(g, None if self._targetless(g) else t, me,
                                                        None if self._targetless(g) else tp) for g in (step, nxt)):
                return PlanStep(step, nxt, target)
        return None

    def _targetless(self, g: str) -> bool:
        return self.chooser.affordances.first_ref[g] is None

    def _options(self, node, view: "SceneView"):
        h, a = node.head, node.args
        if h == "has" and a[0] == "me":
            base = a[1].partition(":")[0]
            for key in view.of_kind(base):
                yield "go", "take", key
                yield "go", "examine", key
            yield "search", "wait", "@PLACE"
        elif h == "at" and a[0] == "me":
            for nxt in ("wait", "rest", "set_posture"):
                yield "go", nxt, a[1]
        elif h == "owns" and a[0] == "me":
            yield "go", "take", a[1]
            yield "examine", "take", a[1]
            yield "go", "examine", a[1]
        elif h == "state" and a[0] == "me" and a[2] == "low":
            need = a[1]
            if need in self.NEEDS:
                prop, gesture = self.NEEDS[need]
                for key in view.having(prop):
                    if view.carried(key):
                        yield gesture, "rest", key
                    else:
                        yield "go", gesture, key
            elif need == "exhaustion":
                yield "set_posture", "rest", "me"
                for key in view.of_category(("furniture", "textile")):
                    yield "go", "sleep", key
            elif need == "pain":
                yield "rest", "set_posture", "me"
        elif h == "works_as" and a[0] == "me":
            for key in view.of_category(WORKABLE):
                yield "go", "work", key
                yield "examine", "work", key
        elif h == "knows_how" and a[0] == "me":
            for key in view.of_category(WORKABLE):
                yield "examine", "work", key
        elif h == "link" and a[2] == "me" and a[1] == "friend":
            yield "go", "look", a[0]
            yield "look", "wait", a[0]


class SceneView:
    """What the plan table may ask of the scene: the things he sees or carries, by kind, category or property."""

    def __init__(self, pools: Pools, thing_kinds: dict, animals: frozenset, carried: set):
        self.pools, self.kinds, self.animals, self._carried = pools, thing_kinds, animals, carried

    def items(self):
        return [k for k in self.kinds if k not in self.animals]

    def of_kind(self, base: str):
        return [k for k in self.items() if self.kinds[k] == base]

    def of_category(self, cats):
        return [k for k in self.items() if self.pools.category_of.get(self.kinds[k]) in cats]

    def having(self, prop: str):
        return [k for k in self.items() if self.pools.item_has(self.kinds[k], prop)]

    def carried(self, key: str) -> bool:
        return key in self._carried

    def target(self, key: str) -> Target | None:
        if key in ("me",) or key.startswith("@E"):
            return Target("agent")
        if key.startswith("@T"):
            return Target("animal" if key in self.animals else "item", self.kinds.get(key))
        return Target("place")
