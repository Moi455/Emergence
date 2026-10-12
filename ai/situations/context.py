"""context.py - the state shared by the builders of one situation: the layout of the mind, the records written so
far, the parties of the scene, the propositions session, and the few draws everybody needs."""
from __future__ import annotations

import math
import random

from tok2 import Record

from .draw import Draw, NumericPrior
from .body import Climate
from .layout import Layout
from .parties import PartyBook
from .plans import SceneView
from .pools import Pools
from .propositions import PropositionGrammar, Refs
from .scene import ADULT, Scene

# how often each flag is true (a flag is never drawn at random): (type, field) -> rate
FLAG_RATES = {("BELIEF", "polarity"): 0.9, ("BELIEF", "secret"): 0.05, ("BELIEF", "contradicted"): 0.06,
              ("HEARD", "polarity"): 0.9, ("HEARD", "secret"): 0.03, ("HEARD", "contradicted"): 0.03,
              ("MEMORY", "defining"): 0.08, ("MEMORY", "secret"): 0.06}
CHILD_WEAPON_AGE = 12.0


class RecordBook:
    """The records written so far, by type."""

    def __init__(self):
        self._by_type: dict[str, list[Record]] = {}

    def add(self, rec: Record) -> Record:
        self._by_type.setdefault(rec.type, []).append(rec)
        return rec

    def of(self, typ: str) -> list[Record]:
        return self._by_type.get(typ, [])

    def first(self, typ: str) -> Record | None:
        return next(iter(self.of(typ)), None)

    def ordered(self, order: tuple[str, ...]) -> list[Record]:
        return [r for t in order for r in self.of(t)]


class Filler:
    """Completes the fields a builder did not set, and draws enumerations."""

    def __init__(self, pools: Pools, d: Draw):
        self.pools, self.d, self.prior = pools, d, NumericPrior(d)
        self.types = pools.interface.token_types
        self.intimate = pools.intimate_fields

    def fill(self, typ: str, fields: dict, skip: tuple = ()) -> dict:
        """A flag at its own rate, a number from its scale alone. Intimate fields are never filled here."""
        for name, spec in self.types[typ]["fields"].items():
            if name in fields or name in skip or name in self.intimate.get(typ, ()) or spec.get("components"):
                continue
            if spec["scale"] == "bool":
                rate = FLAG_RATES.get((typ, name))
                if rate is not None:
                    fields[name] = self.d.chance(rate)
                continue
            v = self.prior.sample(spec)
            if v is not None:
                fields[name] = v
        return fields

    def enum(self, typ: str, name: str, weights: dict | None = None) -> str:
        """A value of an enumeration: uniform, or weighted (a value the weights do not list never comes out)."""
        values = self.pools.enum(typ, name)
        if not weights:
            return self.d.pick(values)
        return self.d.weighted(weights, allowed=[v for v in values if weights.get(v, 0.0) > 0])


def stage_of(age: float, values: list[str]) -> str:
    want = "infant" if age < 3 else "child" if age < 14 else "teen" if age < ADULT else "adult" if age < 60 else "elder"
    return want if want in values else values[-1]


class BuildContext:
    """Everything a builder reads or writes. `cause` is why he wakes (drawn first, the situation justifies it)."""

    def __init__(self, rng: random.Random, pools: Pools, grammar: PropositionGrammar, scene: Scene, cause: str):
        self.rng, self.pools, self.grammar, self.scene, self.cause = rng, pools, grammar, scene, cause
        self.d = Draw(rng)
        self.me = scene.self_
        self.filler = Filler(pools, self.d)
        self.cap = {t: spec["count"] for t, spec in pools.interface.token_types.items()}
        self.layout = Layout(scene, self.cap, self.count("LOCUS", 0), self.count("GROUP", 0))
        self.records = RecordBook()
        self.parties = PartyBook(self.me)
        self.rules = grammar.rules
        self.climate_index = Climate(self.d).index(scene.season, scene.hour, scene.place.indoors)
        lay = self.layout
        self.refs = Refs(persons=lay.pkeys + [g.key for g in lay.ghosts],
                         absent=[e.key for e in lay.entries if e.present is None] + [g.key for g in lay.ghosts],
                         things=lay.tkeys + lay.ikeys, loci=lay.loci, groups=lay.groups, here=lay.here,
                         kinds=self.place_kinds())
        self.refs.thing_kinds = ({k: t.kind for k, t in zip(lay.tkeys, lay.things)}
                                 | dict(zip(lay.ikeys, lay.carried)))
        self.refs.animals = frozenset(k for k, t in zip(lay.tkeys, lay.things) if t.animal)
        self.session = grammar.session(rng, self.parties, self.me, self.refs)
        self.said: set[str] = set()                      # propositions already in his mind (no twice the same)
        self.events: list[Record] = []
        self.directed: list[Record] = []                # events directed at the NPC himself
        self.hurt = False

    # ---- what belongs here ---------------------------------------------------------------------------------
    def place_kinds(self) -> list[str]:
        """Item kinds that belong to this place and this scene (the place's categories, what is lying around, what
        he carries); a weapon on a small child is rare."""
        sc, pools = self.scene, self.pools
        kinds = {k for cat in sc.place.items for k in pools.items_by_category.get(cat, ())}
        kinds |= {t.kind for t in sc.things if not t.animal} | set(sc.carried)
        kinds |= set(pools.items_by_category.get("currency", ()))
        out = sorted(k for k in kinds if k in self.grammar.valid_kinds)
        if self.me.age < CHILD_WEAPON_AGE:
            out = [k for k in out if pools.category_of.get(k) not in pools.weapon_categories or self.rng.random() < 0.05]
        return out or sorted(self.grammar.valid_kinds)[:20]

    def scene_view(self) -> SceneView:
        lay = self.layout
        return SceneView(self.pools, self.refs.thing_kinds, self.refs.animals, set(lay.ikeys))

    # ---- shared draws --------------------------------------------------------------------------------------
    def count(self, typ: str, lo: int, hi: int | None = None) -> int:
        """How many records of a type: a random number, but a long scene (30 %) fills each type close to its budget."""
        cap = self.cap[typ]
        if self.scene.long:
            return self.d.between(max(lo, math.ceil(0.8 * cap)), cap)
        return self.d.between(lo, min(cap, cap if hi is None else hi))

    def fill(self, typ: str, fields: dict, skip: tuple = ()) -> dict:
        return self.filler.fill(typ, fields, skip)

    def enum(self, typ: str, name: str, weights: dict | None = None) -> str:
        return self.filler.enum(typ, name, weights)

    def add(self, rec: Record) -> Record:
        return self.records.add(rec)

    def of(self, typ: str) -> list[Record]:
        return self.records.of(typ)

    @staticmethod
    def direction(bearing: float) -> dict:
        return {"sin": round(math.sin(bearing), 4), "cos": round(math.cos(bearing), 4)}

    def hours_ago(self, lo: float, hi: float) -> float:
        return self.d.log_uniform(lo, hi)

    def until(self, lo: float, hi: float, overdue: float = 0.12) -> float:
        """Hours until a deadline: mostly ahead, sometimes already overdue (negative)."""
        h = self.hours_ago(lo, hi)
        return -h if self.d.chance(overdue) else h

    def perceived(self) -> list[str]:
        """Pointers to what the NPC perceives right now: the persons who are here and the things in view."""
        return self.layout.here + self.layout.tkeys
