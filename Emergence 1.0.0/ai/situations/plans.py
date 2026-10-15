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
FORCE_STEPS = ("strike", "push", "grab", "pull")          # the gestures of force a violent aim is made of (family `force`, no `guard`)


@dataclass(frozen=True)
class PlanSketch:
    """A plan before it is written: the gestures in order, the target of each (None: it takes none), the target
    of the plan, and the person he means to speak to when a step is `speak` (the plan then carries his words)."""
    steps: tuple[str, ...]
    targets: tuple[str | None, ...]
    main: str
    speaks_to: str | None = None
    incites: str | None = None        # the person he means to harm, when a step is a word to an accomplice

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

    def make(self, d: Draw, goal: str, view: "SceneView", book: PartyBook, mode: str = "achieve") -> PlanSketch | None:
        node = self.parser.parse(goal)
        while node.head in self.TIME_MARKS and isinstance(node.args[-1], language.Node):
            node = node.args[-1]
        aim = ViolentAim.read(node, mode)
        chains = list(self._chains(node, view) if aim is None else aim.chains(view))
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
        incites = aim.person if aim is not None and aim.kind in ViolentAim.HARMFUL and speaks not in (None, aim.person) else None
        return PlanSketch(tuple(g for g, _ in chain), tuple(None if self._targetless(g) else t for g, t in chain),
                          main, speaks, incites)

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
                yield [("wait", "@PLACE"), ("go", a[1]), ("take", a[1])], a[1]
                yield [("search", "@PLACE"), ("wait", "@PLACE"), ("go", a[1]), ("take", a[1])], a[1]
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


class ViolentAim:
    """A goal of force, read from its proposition (T12b): to harm somebody (`(dead X)`, `(state X pain high)`, a gesture
    of force done to him, alone or at a place), to drive him out (`(not (at X _))`), to unseat him (`(not (leads X G))`),
    to burn a thing (`(state K burning high)`), or, in the mode `avoid`, to keep somebody from being harmed. It gives
    the chains of gestures that serve it: follow, wait, win accomplices over, arm himself, go there, strike. Only
    gestures of the catalogue; a step is kept only if the governor lets it through bare (plans.PlanTable)."""

    HARMFUL = ("harm", "expel", "depose")

    def __init__(self, kind: str, person: str | None, place: str | None = None):
        self.kind, self.person, self.place = kind, person, place

    @classmethod
    def read(cls, node, mode: str = "achieve") -> "ViolentAim | None":
        found = cls._find(node)
        if found is None:
            return None
        kind, person, place = found
        if mode == "avoid":
            return cls("protect", person) if kind == "harm" and person != "me" else None
        if kind == "harm" and person == "me":
            return None
        return cls(kind, person, place)

    @classmethod
    def _find(cls, node):
        h, a = node.head, node.args
        text = lambda i: a[i] if i < len(a) and isinstance(a[i], str) else ""  # noqa: E731
        if h == "dead" and text(0).startswith("@E"):
            return "harm", a[0], None
        if h == "state" and text(0).startswith("@E") and text(1) == "pain" and text(2) in ("high", "very_high"):
            return "harm", a[0], None
        if h == "state" and text(0).startswith(("@T", "@L")) and text(1) == "burning":
            return "burn", a[0], None
        if h == "did" and text(0) in ("me", "us") and text(1) in FORCE_STEPS and text(2).startswith("@E"):
            return ("expel" if text(1) == "push" else "harm"), a[2], None
        if h == "not" and a and isinstance(a[0], language.Node):
            inner = a[0]
            who = inner.args[0] if inner.args and isinstance(inner.args[0], str) else ""
            if inner.head == "at" and who.startswith("@E"):
                return "expel", who, None
            if inner.head == "leads" and who.startswith("@E"):
                return "depose", who, None
        if h == "leads" and text(0) == "me":
            return "lead", None, None
        if h == "and":                                                     # an ambush: be there, and strike
            place, aim = None, None
            for x in a:
                if not isinstance(x, language.Node):
                    continue
                if x.head == "at" and len(x.args) == 2 and x.args[0] in ("me", "us"):
                    place = x.args[1]
                else:
                    aim = cls._find(x)
            return (aim[0], aim[1], place) if aim is not None else None
        return None

    # ---- the chains ---------------------------------------------------------------------------------------------
    def chains(self, view: "SceneView"):
        make = getattr(self, f"_{self.kind}")
        yield from make(view)

    def _armed(self, view: "SceneView") -> list[str]:
        return view.of_category(tuple(sorted(view.pools.weapon_categories)))

    def _harm(self, view: "SceneView"):
        t, strike = self.person, ("strike", self.person)
        arms, mates = self._armed(view), view.mates()
        if t in view.here:
            yield [("look", t), ("go", t), strike], t
            yield [("go", t), strike], t
            yield [("wait", "@PLACE"), ("go", t), strike], t
            for w in arms:
                yield [("take", w), ("go", t), strike], t
                yield [("take", w), ("look", t), ("go", t), strike], t
            for m in mates:
                yield [("speak", m), ("go", t), strike], t
                yield [("speak", m), ("wait", "@PLACE"), ("go", t), strike], t
        for loc in [self.place] if self.place else view.loci[:2]:                # where he will be, though he is not here
            main = t if t in view.here else loc
            yield [("go", loc), ("wait", loc), strike], main
            yield [("search", "@PLACE"), ("go", loc), strike], main
            for w in arms:
                yield [("take", w), ("go", loc), ("wait", loc), strike], main
            for m in mates:
                yield [("speak", m), ("go", loc), ("wait", loc), strike], main
                yield [("speak", m), ("go", loc), strike], main

    def _expel(self, view: "SceneView"):
        t, push = self.person, ("push", self.person)
        if t in view.here:
            yield [("look", t), ("go", t), push], t
            yield [("go", t), ("speak", t), push], t
            for m in view.mates():
                yield [("speak", m), ("go", t), push], t
        else:
            for loc in view.loci[:2]:
                yield [("go", loc), ("wait", loc), push], loc

    def _depose(self, view: "SceneView"):
        t = self.person
        yield from self._expel(view)
        if t in view.here:
            for m in view.mates():
                yield [("speak", m), ("wait", "@PLACE"), ("go", t), ("push", t)], t

    def _burn(self, view: "SceneView"):
        k = self.person
        for torch in view.of_category(("light",)):
            yield [("take", torch), ("go", k), ("throw", torch)], k
            yield [("take", torch), ("wait", "@PLACE"), ("go", k), ("throw", torch)], k

    def _lead(self, view: "SceneView"):
        for m in view.mates():
            yield [("speak", m), ("wait", "@PLACE"), ("speak", m)], m

    def _protect(self, view: "SceneView"):
        t = self.person
        if t in view.here:
            yield [("go", t), ("speak", t)], t
            yield [("look", t), ("go", t), ("speak", t)], t
        for m in view.mates():
            yield [("go", m), ("speak", m)], m
            yield [("look", m), ("go", m), ("speak", m)], m


class SceneView:
    """What the plan table may ask of the scene: the things he sees or carries, by kind, category or property, the
    places he knows and, for a group, the person he believes leads it. `allies` are the persons he may win over."""

    def __init__(self, pools: Pools, thing_kinds: dict, animals: frozenset, carried: set, here: frozenset = frozenset(),
                 loci: tuple = (), leaders: dict | None = None, allies: tuple = ()):
        self.pools, self.kinds, self.animals, self._carried, self.here = pools, thing_kinds, animals, carried, here
        self.loci, self.leaders, self.allies = list(loci), leaders or {}, tuple(allies)

    def mates(self) -> list[str]:
        """The accomplices (or the people to warn) who are here: one speaks only to a person who is there."""
        return [k for k in self.allies if k in self.here]

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
