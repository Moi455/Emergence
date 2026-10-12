"""scene.py - the TRUE situation: who and what is where, at what hour. The NPC's mind is built from it later
(mind.py), with noise, ignorance and error; the model never sees this truth.

People are drawn with ages that fit the link that binds them to the NPC (LinkRules): a sibling within 15 years,
a friend of a child is a child, an apprentice is at least 12, an intimate partner is well past the age of majority
(D10: the age comes from hard_rules.toml through the governor, the intimate links from the `intimate` flag of the
link concepts).
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field, replace

from .draw import Draw
from .pools import Pools

from governor import ADULT_AGE  # noqa: E402  (path set by pools)

ADULT = float(ADULT_AGE)
PARTNER_MARGIN = 3.0                            # an intimate partner is this far past the age of majority, both sides


@dataclass
class Person:
    pid: int
    age: float                                  # true age, years
    sex: str                                    # female | male
    name: str                                   # n:<id>, unique in a scene
    occupation: str = ""                        # an occupation word, or none (children)

    @property
    def minor(self) -> bool:
        return self.age < ADULT


# ---------------------------------------------------------------------------------------------------- people
class PersonFactory:
    BANDS = {"child": (3, 13.99), "teen": (14, 17.99), "adult": (18, 59.99), "elder": (60, 75)}
    WEIGHTS = {"child": 0.18, "teen": 0.1, "adult": 0.58, "elder": 0.14}

    def __init__(self, draw: Draw, pools: Pools):
        self.d, self.pools = draw, pools
        self.occupations = pools.concepts("occupation")
        self._next = 1
        self._names: set[str] = set()

    def make(self, lo: float = 0.0, hi: float = 99.0, bands: tuple[str, ...] | None = None) -> Person:
        """A person whose age lies in [lo, hi] (the bounds win over the demography)."""
        cands = {b: (max(a, lo), min(z, hi)) for b, (a, z) in self.BANDS.items() if bands is None or b in bands}
        cands = {b: span for b, span in cands.items() if span[0] <= span[1]}
        if cands:
            band = self.d.weighted(self.WEIGHTS, allowed=list(cands))
            a, z = cands[band]
        else:                                    # outside every band: clamp to the bounds
            a = z = min(hi, max(lo, 3.0))
        age = round(self.d.rng.uniform(a, z), 2)
        pid, self._next = self._next, self._next + 1
        occ = self.d.pick(self.occupations) if age >= 16 and self.occupations and self.d.chance(0.8) else ""
        return Person(pid, age, self.d.pick(("female", "male")), self._name(), occ)

    def _name(self) -> str:
        while True:
            name = f"n:{self.d.rng.randrange(1, 5000)}"
            if name not in self._names:
                self._names.add(name)
                return name


# ---------------------------------------------------------------------------------------------------- links
@dataclass(frozen=True)
class LinkSpec:
    """What the age of `other` can be when `other` is the NPC's <link> (ENTITY.link = what the person is to the NPC)."""
    offset: tuple[float, float]                 # other.age - me.age
    me_min: float = 0.0
    other_min: float = 0.0
    other_max: float = 90.0
    minor_offset: tuple[float, float] | None = None    # tighter when the NPC is a minor
    adult_with_adult: bool = False                     # an adult NPC's other is an adult too


class LinkRules:
    """Plausible ages per kind of link. Built from the link concepts of the catalogue (the intimate ones from their
    `intimate` flag); a link the table does not know is unconstrained."""

    TABLE = {
        "parent": LinkSpec((16, 45), other_max=85),
        "grandparent": LinkSpec((34, 70), other_max=90),
        "aunt_uncle": LinkSpec((10, 40), other_max=85),
        "child": LinkSpec((-45, -16)),
        "grandchild": LinkSpec((-70, -34)),
        "niece_nephew": LinkSpec((-40, -10)),
        "sibling": LinkSpec((-15, 15)),
        "cousin": LinkSpec((-20, 20)),
        "in_law": LinkSpec((-30, 30), me_min=ADULT, other_min=ADULT),
        "spouse": LinkSpec((-15, 15), me_min=ADULT + PARTNER_MARGIN, other_min=ADULT + PARTNER_MARGIN),
        "betrothed": LinkSpec((-12, 12), me_min=ADULT + PARTNER_MARGIN, other_min=ADULT + PARTNER_MARGIN),
        "lover": LinkSpec((-15, 15), me_min=ADULT + PARTNER_MARGIN, other_min=ADULT + PARTNER_MARGIN),
        "former_spouse": LinkSpec((-20, 20), me_min=ADULT + PARTNER_MARGIN, other_min=ADULT + PARTNER_MARGIN),
        "friend": LinkSpec((-15, 15), minor_offset=(-4, 4), adult_with_adult=True),
        "enemy": LinkSpec((-25, 25), me_min=8, other_min=8, minor_offset=(-6, 6), adult_with_adult=True),
        "colleague": LinkSpec((-25, 25), me_min=14, other_min=14),
        "employer": LinkSpec((0, 45), me_min=14, other_min=ADULT + 3),
        "employee": LinkSpec((-40, 10), me_min=ADULT + 3, other_min=14),
        "master": LinkSpec((8, 50), me_min=12, other_min=ADULT + 6),
        "apprentice": LinkSpec((-45, -8), me_min=ADULT + 4, other_min=12),
        "guest": LinkSpec((-40, 40)),
        "neighbor": LinkSpec((-50, 50)),
    }
    # how often a link is drawn (default 1): partners are not the commonest company
    WEIGHTS = {"spouse": 0.8, "betrothed": 0.35, "lover": 0.12, "former_spouse": 0.25, "guest": 0.6}
    # at most this many in one scene; spouse and betrothed share one place
    CAPS = {"spouse": 1, "betrothed": 1, "lover": 1, "former_spouse": 1, "parent": 2, "grandparent": 3,
            "master": 1, "employer": 1}
    EXCLUSIVE = (("spouse", "betrothed"),)

    def __init__(self, pools: Pools):
        self.intimate = frozenset(c.id for c in pools.cat["concept"].values() if c.category == "link" and c.intimate)
        self.links = [x for x in pools.concepts("link") if x != "stranger"]
        self.table = dict(self.TABLE)
        for link in self.intimate:                  # whatever the catalogue flags intimate is for clear adults only
            base = self.table.get(link, LinkSpec((-15, 15)))
            floor = ADULT + PARTNER_MARGIN
            self.table[link] = replace(base, me_min=max(base.me_min, floor), other_min=max(base.other_min, floor))

    def spec(self, link: str, me_age: float) -> tuple[float, float] | None:
        """The range of ages the other can have, or None when the NPC cannot have such a link."""
        s = self.table.get(link)
        if s is None:
            return 0.0, 90.0
        if me_age < s.me_min:
            return None
        off, other_min = s.offset, s.other_min
        if me_age < ADULT and s.minor_offset:
            off = s.minor_offset
        if me_age >= ADULT and s.adult_with_adult:
            other_min = max(other_min, ADULT)
        lo, hi = max(other_min, PersonFactory.BANDS["child"][0], me_age + off[0]), min(s.other_max, me_age + off[1])
        return (lo, hi) if lo <= hi else None

    def fits(self, link: str, other_age: float, me_age: float) -> bool:
        r = self.spec(link, me_age)
        return r is not None and r[0] <= other_age <= r[1]

    def allowed(self, link: str, counts: dict) -> bool:
        if counts.get(link, 0) >= self.CAPS.get(link, 99):
            return False
        return not any(link in grp and any(counts.get(o, 0) for o in grp if o != link) for grp in self.EXCLUSIVE)


# ---------------------------------------------------------------------------------------------------- places
@dataclass(frozen=True)
class PlaceArchetype:
    """A kind of scene. The categories are item_type categories of the catalogue."""
    name: str
    indoors: bool
    items: tuple[str, ...]
    crowd: tuple[int, int]
    habitats: tuple[str, ...] = ()
    night: float = 1.0                          # relative frequency at night (day: 1)


PLACES = (
    PlaceArchetype("well", False, ("container", "cleaning", "household"), (0, 5), ("village",), 0.05),
    PlaceArchetype("tavern", True, ("drink", "dish", "tableware", "furniture", "game", "music", "light"), (2, 12), (), 0.9),
    PlaceArchetype("field", False, ("farming", "seed", "produce", "grain", "carry"), (0, 5), ("fields", "meadow"), 0.03),
    PlaceArchetype("forest", False, ("forestry", "hunting", "raw_wood"), (0, 2), ("forest",), 0.08),
    PlaceArchetype("market", False, ("trade", "currency", "produce", "textile", "pottery", "bread", "meat"), (4, 20),
                   ("village",), 0.02),
    PlaceArchetype("home", True, ("household", "furniture", "kitchen", "tableware", "textile", "light", "toy"), (0, 5), (), 3.0),
    PlaceArchetype("workshop", True, ("smithing", "carpentry", "masonry", "metal_stock", "raw_wood", "leather"), (0, 4), (), 0.1),
    PlaceArchetype("road", False, ("carry", "vehicle"), (0, 3), ("meadow", "village"), 0.12),
)


@dataclass
class Present:
    person: Person
    link: str                                   # link word of the person toward the NPC ("stranger" if none)
    dist: float
    bearing: float                              # radians, relative to where the NPC looks
    known: bool                                 # the NPC has a file on this person


@dataclass
class Thing:
    kind: str
    dist: float
    bearing: float
    owner: int | None = None                    # person id (truth); the NPC may believe otherwise
    animal: bool = False
    seen_use: bool = False                      # the NPC has seen the owner hold or use it


def separation(a, b) -> float:
    """Distance in metres between two things placed by (dist, bearing) around the NPC."""
    ax, ay = a.dist * math.cos(a.bearing), a.dist * math.sin(a.bearing)
    bx, by = b.dist * math.cos(b.bearing), b.dist * math.sin(b.bearing)
    return math.hypot(ax - bx, ay - by)


@dataclass
class Scene:
    place: PlaceArchetype
    hour: float
    season: str
    self_: Person
    present: list[Present] = field(default_factory=list)
    absent: list[tuple[Person, str]] = field(default_factory=list)     # known persons not here, with their link
    things: list[Thing] = field(default_factory=list)
    carried: list[str] = field(default_factory=list)                   # kinds the NPC carries
    ghosts: list[tuple[Person, str]] = field(default_factory=list)     # known persons whose files the selector left out
    long: bool = False                                                 # a crowded, loaded scene (long contexts)

    def persons(self) -> list[Person]:
        return [self.self_] + [p.person for p in self.present] + [p for p, _ in self.absent] + [p for p, _ in self.ghosts]


class SceneFactory:
    def __init__(self, rng: random.Random, pools: Pools, rules: LinkRules | None = None):
        self.rng, self.pools = rng, pools
        self.d = Draw(rng)
        self.people = PersonFactory(self.d, pools)
        self.rules = rules or LinkRules(pools)
        self.counts: dict[str, int] = {}

    # ---- the scene -----------------------------------------------------------------------------------
    def make(self) -> Scene:
        rng, d = self.rng, self.d
        long = d.chance(0.3)
        hour = round(rng.uniform(0, 24), 2)
        night = hour < 5.5 or hour >= 21.5
        place = d.weighted({p.name: (p.night if night else 1.0) for p in PLACES}, allowed=[p.name for p in PLACES])
        place = next(p for p in PLACES if p.name == place)
        self_ = self.people.make(lo=12 if long else 0)
        scene = Scene(place, hour, d.pick(("spring", "summer", "autumn", "winter")), self_, long=long)
        n = rng.randint(8, 12) if long else rng.randint(*place.crowd)
        for _ in range(min(n, 9)):
            other, link = self._related(self_)
            scene.present.append(Present(other, link, self._distance(), rng.uniform(-3.14, 3.14),
                                         link != "stranger" or d.chance(0.2)))
        for _ in range(rng.randint(3, 5) if long else rng.randint(0, 3)):
            scene.absent.append(self._related(self_, known=True))
        for _ in range(rng.randint(1, 3)):
            scene.ghosts.append(self._related(self_, known=True))
        self._things(scene, long)
        return scene

    def _distance(self) -> float:
        d = self.d
        return d.uniform(0.5, 2.5) if d.chance(0.28) else d.log_uniform(2.5, 25.0, 1)

    def _things(self, scene: Scene, long: bool) -> None:
        rng, d, place, self_ = self.rng, self.d, scene.place, scene.self_
        owners = [p.person.pid for p in scene.present] + [self_.pid]
        for _ in range(rng.randint(12, 16) if long else rng.randint(1, 10)):
            kinds = self.pools.items_by_category.get(d.pick(place.items))
            if not kinds:
                continue
            owner = d.pick(owners + [None])
            dist = d.uniform(0.3, 3.0) if d.chance(0.35) else d.uniform(3.0, 20.0)
            seen = owner is not None and owner != self_.pid and d.chance(0.55 if dist < 3 else 0.3)
            scene.things.append(Thing(d.pick(kinds), dist, rng.uniform(-3.14, 3.14), owner, seen_use=seen))
        if place.habitats and (long or d.chance(0.4)):
            animals = self.pools.animals_of(place.habitats)
            if animals:
                scene.things.append(Thing(d.pick(animals), d.uniform(2, 40), rng.uniform(-3.14, 3.14), animal=True))
        for _ in range(rng.randint(5, 8) if long else rng.randint(0, 4)):
            kinds = self.pools.items_by_category.get(d.pick(("carry", "currency", "bread", "household", "blade")))
            if kinds:
                scene.carried.append(d.pick(kinds))

    # ---- people bound to the NPC by a link ----------------------------------------------------------------
    def _related(self, me: Person, known: bool = False) -> tuple[Person, str]:
        """Another person and what he is to the NPC, consistent with both ages and with who is already around."""
        d = self.d
        if not known and d.chance(0.45):
            return self.people.make(), "stranger"
        weights = {k: self.rules.WEIGHTS.get(k, 1.0) for k in self.rules.links}
        for _ in range(30):
            link = d.weighted(weights)
            if not self.rules.allowed(link, self.counts):
                continue
            span = self.rules.spec(link, me.age)
            if span is None:
                continue
            self.counts[link] = self.counts.get(link, 0) + 1
            return self.people.make(lo=span[0], hi=span[1]), link
        return self.people.make(), "stranger"
