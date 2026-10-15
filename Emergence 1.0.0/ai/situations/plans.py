"""plans.py - the step the NPC is on, consistent with the goal it serves.

A small table from the predicate of a goal to the chains of gestures that plausibly serve it (has -> go, take;
at -> go, wait; thirst -> go, drink; ...), 2 to 4 steps long. This is the BUILDING of a situation (what he was already
doing), not a decision: the model still chooses what to do now. A step is kept only if the target accepts it and the
governor allows it bare. A goal wrapped in a time mark (at_time, before, after) is served like the goal inside.
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
class PlanSketch:
    """A plan before it is written: the gestures in order, the target of each (None: it takes none), the target
    of the plan, and the person he means to speak to when a step is `speak` (the plan then carries his words)."""
    steps: tuple[str, ...]
    targets: tuple[str | None, ...]
    main: str
    speaks_to: str | None = None

    def step_targets(self) -> list[str]:
        """The targets of the steps that have one, in order (PLAN.step_targets keeps the first four)."""
        return [t for t in self.targets if t is not None]


class PlanTable:
    """goal predicate -> chains of (gesture, target), tried against the targets of the scene."""

    NEEDS = {"thirst": ("drinkable", "drink"), "hunger": ("edible", "eat")}
    TIME_MARKS = ("at_time", "before", "after")
    LENGTH_WEIGHT = {2: 0.5, 3: 0.35, 4: 0.15}            # how long a plan is: most are short

    def __init__(self, pools: Pools, chooser: GestureChooser):
        self.pools, self.chooser, self.parser = pools, chooser, language.Parser()

    def make(self, d: Draw, goal: str, view: "SceneView", book: PartyBook) -> PlanSketch | None:
        node = self.parser.parse(goal)
        while node.head in self.TIME_MARKS and isinstance(node.args[-1], language.Node):
            node = node.args[-1]
        chains = list(self._chains(node, view))
        d.rng.shuffle(chains)
        me, ok = book.party("me"), {}
        valid = []
        for chain, main in chains:
            if len({g for g, _ in chain}) < 2 or any(a[0] == b[0] for a, b in zip(chain, chain[1:])):
                continue                                          # a step is followed by a different one
            if all(ok.setdefault(s, self._permits(s, view, book, me)) for s in chain):
                valid.append((chain, main))
        if not valid:
            return None
        chain, main = d.rng.choices(valid, weights=[self.LENGTH_WEIGHT.get(len(c), 0.05) for c, _ in valid])[0]
        speaks = next((t for g, t in chain if g == "speak"), None)
        return PlanSketch(tuple(g for g, _ in chain), tuple(None if self._targetless(g) else t for g, t in chain),
                          main, speaks)

    def _permits(self, step: tuple[str, str], view: "SceneView", book: PartyBook, me) -> bool:
        g, key = step
        bare = self._targetless(g)
        return self.chooser.permits(g, None if bare else view.target(key), me, None if bare else book.party(key))

    def _targetless(self, g: str) -> bool:
        return self.chooser.affordances.first_ref[g] is None

    def _chains(self, node, view: "SceneView"):
        """-> (chain, main target): every chain of (gesture, target) that could serve the goal."""
        h, a = node.head, node.args
        if h == "has" and a[0] == "me":
            base = a[1].partition(":")[0]
            for key in view.of_kind(base):
                yield [("go", key), ("take", key)], key
                yield [("go", key), ("examine", key)], key
                yield [("look", key), ("go", key), ("take", key)], key
                yield [("search", "@PLACE"), ("go", key), ("take", key)], key
                yield [("go", key), ("examine", key), ("take", key)], key
                yield [("search", "@PLACE"), ("go", key), ("examine", key), ("take", key)], key
            yield [("search", "@PLACE"), ("wait", "@PLACE")], "@PLACE"
            for loc in view.loci[:2]:
                yield [("go", loc), ("search", "@PLACE")], loc
                yield [("go", loc), ("search", "@PLACE"), ("wait", "@PLACE")], loc
        elif h == "at" and a[0] == "me":
            for nxt in ("wait", "rest", "set_posture"):
                yield [("go", a[1]), (nxt, a[1])], a[1]
            yield [("go", a[1]), ("look", "@PLACE"), ("wait", a[1])], a[1]
            yield [("go", a[1]), ("look", "@PLACE"), ("wait", a[1]), ("rest", "me")], a[1]
        elif h == "at" and a[0] in view.here:                                    # to find a person who is here
            yield [("look", a[0]), ("go", a[0]), ("speak", a[0])], a[0]
        elif h == "at" and a[0].startswith("@E"):                                # a person to find, not here
            for loc in view.loci[:2]:
                yield [("go", loc), ("search", "@PLACE")], loc
                yield [("go", loc), ("search", "@PLACE"), ("wait", "@PLACE")], loc
        elif h == "owns" and a[0] == "me":
            if view.carried(a[1]):                                   # it is on him: nothing to walk to
                yield [("examine", a[1]), ("take", a[1])], a[1]
            else:
                yield [("go", a[1]), ("take", a[1])], a[1]
                yield [("examine", a[1]), ("take", a[1])], a[1]
                yield [("go", a[1]), ("examine", a[1])], a[1]
                yield [("look", a[1]), ("go", a[1]), ("take", a[1])], a[1]
                yield [("look", a[1]), ("go", a[1]), ("examine", a[1]), ("take", a[1])], a[1]
        elif h == "state" and a[0] == "me" and a[2] == "low":
            need = a[1]
            if need in self.NEEDS:
                prop, gesture = self.NEEDS[need]
                for key in view.having(prop):
                    if view.carried(key):
                        yield [(gesture, key), ("rest", "me")], key
                    else:
                        yield [("go", key), (gesture, key)], key
                        yield [("go", key), (gesture, key), ("rest", "me")], key
                        yield [("look", key), ("go", key), (gesture, key), ("rest", "me")], key
            elif need == "exhaustion":
                yield [("set_posture", "me"), ("rest", "me")], "me"
                for key in view.of_category(("furniture", "textile")):
                    yield [("go", key), ("sleep", key)], key
            elif need == "pain":
                yield [("rest", "me"), ("set_posture", "me")], "me"
        elif h == "works_as" and a[0] == "me":
            for key in view.of_category(WORKABLE):
                yield [("go", key), ("work", key)], key
                yield [("examine", key), ("work", key)], key
                yield [("go", key), ("work", key), ("rest", "me")], key
                yield [("look", key), ("go", key), ("work", key), ("rest", "me")], key
        elif h == "knows_how" and a[0] == "me":
            for key in view.of_category(WORKABLE):
                yield [("examine", key), ("work", key)], key
                yield [("go", key), ("examine", key), ("work", key)], key
        elif h == "link" and a[2] == "me" and a[1] == "friend" and a[0] in view.here:    # only a person who is here
            yield [("go", a[0]), ("look", a[0])], a[0]
            yield [("look", a[0]), ("wait", a[0])], a[0]
            yield [("go", a[0]), ("speak", a[0])], a[0]
        elif h == "did" and a[0] == "me" and a[1] == "give" and isinstance(a[-1], language.Node) and a[-1].head == "to":
            yield from self._give(a, view)

    @staticmethod
    def _give(a, view: "SceneView"):
        """(did me give K (to X)): walk to X (or to whoever leads the group, if he is here) and hand it over / speak."""
        to = a[-1].args[0]
        kind = a[2].partition(":")[0]
        who = view.leaders.get(to, to) if to.startswith("@G") else to
        if who not in view.here:                                         # only a person who is here
            return
        held = [k for k in view.of_kind(kind) if view.carried(k)]
        for key in held:
            yield [("go", who), ("give", key)], who
        yield [("go", who), ("speak", who)], who
        yield [("look", who), ("speak", who)], who


class SceneView:
    """What the plan table may ask of the scene: the things he sees or carries, by kind, category or property, the
    places he knows and, for a group, the person he believes leads it."""

    def __init__(self, pools: Pools, thing_kinds: dict, animals: frozenset, carried: set, here: frozenset = frozenset(),
                 loci: tuple = (), leaders: dict | None = None):
        self.pools, self.kinds, self.animals, self._carried, self.here = pools, thing_kinds, animals, carried, here
        self.loci, self.leaders = list(loci), leaders or {}

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
