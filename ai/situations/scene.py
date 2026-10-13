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

from governor import ADULT_AGE

from .draw import Draw
from .pools import Pools

ADULT = float(ADULT_AGE)
CHILD_WEAPON_AGE = 12.0                         # under this age a weapon is rare
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
    BANDS = {"infant": (0.0, 2.99), "child": (3, 13.99), "teen": (14, 17.99), "adult": (18, 59.99), "elder": (60, 92)}
    WEIGHTS = {"infant": 0.035, "child": 0.16, "teen": 0.1, "adult": 0.56, "elder": 0.145}
    MODE = {"elder": 68.0}                      # the old are mostly in their sixties and seventies, a few past ninety

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
        mode = self.MODE.get(band) if cands else None
        age = round(self.d.rng.triangular(a, z, min(max(mode, a), z)) if mode else self.d.rng.uniform(a, z), 1)   # a tenth of a year
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
    other_max: float = 95.0
    minor_offset: tuple[float, float] | None = None    # tighter when the NPC is a minor
    adult_with_adult: bool = False                     # an adult NPC's other is an adult too


class LinkRules:
    """Plausible ages per kind of link. Built from the link concepts of the catalogue (the intimate ones from their
    `intimate` flag); a link the table does not know is unconstrained."""

    TABLE = {
        "parent": LinkSpec((16, 45), other_max=90),
        "grandparent": LinkSpec((34, 70), other_max=95),
        "aunt_uncle": LinkSpec((10, 40), other_max=90),
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
            return 0.0, 95.0
        if me_age < s.me_min:
            return None
        off, other_min = s.offset, s.other_min
        if me_age < ADULT and s.minor_offset:
            off = s.minor_offset
        if me_age >= ADULT and s.adult_with_adult:
            other_min = max(other_min, ADULT)
        lo, hi = max(other_min, me_age + off[0]), min(s.other_max, me_age + off[1])
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
    strangers: float = 0.3                      # share of the people around who are strangers to the NPC


PLACES = (
    PlaceArchetype("well", False, ("container", "cleaning", "household", "drink"), (0, 5), ("village",), 0.05, 0.25),
    PlaceArchetype("tavern", True, ("drink", "dish", "tableware", "furniture", "game", "music", "light"), (2, 12), (), 0.35, 0.45),
    PlaceArchetype("field", False, ("farming", "seed", "produce", "grain", "carry"), (0, 5), ("fields", "meadow"), 0.03, 0.25),
    PlaceArchetype("forest", False, ("forestry", "hunting", "raw_wood"), (0, 2), ("forest",), 0.08, 0.4),
    PlaceArchetype("market", False, ("trade", "currency", "produce", "textile", "pottery", "bread", "meat", "drink"), (4, 20),
                   ("village",), 0.02, 0.7),
    PlaceArchetype("home", True, ("household", "furniture", "kitchen", "tableware", "textile", "light", "toy", "bread",
                                  "dish", "drink", "clothing"), (0, 5), (), 3.0, 0.05),
    PlaceArchetype("workshop", True, ("smithing", "carpentry", "masonry", "metal_stock", "raw_wood", "leather"), (0, 4), (), 0.1, 0.15),
    PlaceArchetype("road", False, ("carry", "vehicle"), (0, 3), ("meadow", "village"), 0.12, 0.6),
)

# what a person carries: by trade, by place, by age (a baby carries nothing of the adults)
OCC_CARRY = {
    "o_farmer": ("farming", "seed"), "o_fisher": ("fishing",), "o_smith": ("smithing", "metal_stock"),
    "o_baker": ("bread", "kitchen"), "o_miller": ("grain",), "o_weaver": ("fiber", "textile"), "o_mason": ("masonry",),
    "o_carpenter": ("carpentry",), "o_miner": ("mining",), "o_hunter": ("hunting", "ranged", "blade"),
    "o_shepherd": ("husbandry",), "o_merchant": ("trade", "currency"), "o_healer": ("healing", "medicine"),
    "o_brewer": ("drink", "kitchen"), "o_potter": ("pottery",), "o_builder": ("building", "masonry", "carpentry"),
    "o_innkeeper": ("drink", "tableware", "kitchen"), "o_scribe": ("writing",), "o_woodcutter": ("forestry",),
    "o_tanner": ("leather",)}
PLACE_CARRY = {"well": ("container",), "tavern": ("drink", "currency", "game"), "field": ("farming", "carry", "seed"),
               "forest": ("forestry", "hunting", "carry"), "market": ("currency", "trade", "carry", "produce"),
               "home": ("household", "clothing"), "workshop": ("carpentry", "smithing"), "road": ("carry", "currency")}
ALWAYS_CARRY = ("currency", "carry", "bread")
BABY_CARRY, SMALL_CARRY, CHILD_CARRY = ("toy",), ("toy", "bread", "produce"), ("toy", "bread", "produce", "carry", "currency")
NIGHT_START, NIGHT_END = 20.0, 6.0               # children are not alone at the tavern between these hours
CHILD_AGE = 14.0


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
    held_by: int | None = None                  # person id who holds it in his hands (the thing is where he is)


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
    # the other people of a family: age of a new relative from the ones already drawn (age = other + offset)
    KIN = {"grandparent": (("parent", 16, 45), ("aunt_uncle", 16, 45)),
           "parent": (("grandparent", -45, -16), ("aunt_uncle", -15, 15), ("sibling", 16, 45)),
           "aunt_uncle": (("grandparent", -45, -16), ("parent", -15, 15), ("cousin", 16, 45)),
           "sibling": (("parent", -45, -16), ("niece_nephew", 16, 45)),
           "cousin": (("aunt_uncle", -45, -16),), "child": (("grandchild", 16, 45),), "grandchild": (("child", -45, -16),),
           "niece_nephew": (("sibling", -45, -16),)}

    def __init__(self, rng: random.Random, pools: Pools, rules: LinkRules | None = None):
        self.rng, self.pools = rng, pools
        self.d = Draw(rng)
        self.people = PersonFactory(self.d, pools)
        self.rules = rules or LinkRules(pools)
        self.counts: dict[str, int] = {}
        self.family: list[tuple[str, float]] = []           # (link, age) of the relatives already drawn

    # ---- the scene -----------------------------------------------------------------------------------
    def make(self, needs_company: bool = False) -> Scene:
        """`needs_company`: somebody fit is there, close enough to speak to him (a request, words or a gesture to be
        heard or seen need a person)."""
        rng, d = self.rng, self.d
        long = d.chance(0.3)
        hour = round(rng.uniform(0, 24), 2)
        self_ = self.people.make()
        place = self._place(self_, hour)
        scene = Scene(place, hour, d.pick(("spring", "summer", "autumn", "winter")), self_, long=long)
        n = rng.randint(8, 12) if long else rng.randint(*place.crowd)
        for _ in range(min(max(n, 1) if needs_company else n, 9)):
            other, link = self._related(self_, stranger=place.strangers)
            scene.present.append(Present(other, link, self._distance(), rng.uniform(-3.14, 3.14),
                                         link != "stranger" or d.chance(0.2)))
        for _ in range(rng.randint(3, 5) if long else rng.randint(0, 3)):
            scene.absent.append(self._related(self_, known=True))
        self._things(scene, long)
        self._carry(scene, long)
        self._cluster(scene)
        if self_.age < 8:                                       # after the crowd has settled: these two stay where put
            self._referent(scene)
        if needs_company and not any((x.known or x.dist < 15) and x.dist <= 10 for x in scene.present):
            self._put(scene, scene.present[0], d.uniform(1.0, 10.0), scene.present[0].bearing)
            scene.present[0].known = True
        return scene

    @staticmethod
    def _put(scene: Scene, x: Present, dist: float, bearing: float) -> None:
        """Move a person, and what he holds with him."""
        x.dist, x.bearing = round(dist, 1), bearing
        for t in scene.things:
            if t.held_by == x.person.pid:
                t.dist, t.bearing = x.dist, x.bearing

    def _place(self, me: Person, hour: float) -> PlaceArchetype:
        """Where he is: by the hour, and a child is not alone at the tavern at night."""
        d = self.d
        night = hour < 5.5 or hour >= 21.5
        weights = {p.name: (p.night if night else 1.0) for p in PLACES}
        if me.age < CHILD_AGE and (hour >= NIGHT_START or hour < NIGHT_END):
            weights["tavern"] = 0.0
        name = d.weighted(weights, allowed=[p.name for p in PLACES])
        return next(p for p in PLACES if p.name == name)

    def _referent(self, scene: Scene) -> None:
        """A child under 8 is never without a grown-up: a relative (else a neighbour) is there, near, known."""
        me = scene.self_
        if any(x.person.age >= ADULT and x.known and x.dist < 15 for x in scene.present):
            return
        for link in ("parent", "parent", "aunt_uncle", "grandparent", "neighbor"):
            span = self._family_range(link, me.age) if self.rules.allowed(link, self.counts) else None
            if span is not None:
                lo = max(span[0], ADULT)
                if lo <= span[1]:
                    self.counts[link] = self.counts.get(link, 0) + 1
                    p = self.people.make(lo=lo, hi=span[1])
                    self.family.append((link, p.age))
                    scene.present.insert(0, Present(p, link, self.d.uniform(0.8, 8.0), self.rng.uniform(-3.14, 3.14), True))
                    return
        p = self.people.make(lo=ADULT, hi=70)
        scene.present.insert(0, Present(p, "neighbor", self.d.uniform(1.0, 8.0), self.rng.uniform(-3.14, 3.14), True))

    def _distance(self) -> float:
        d = self.d
        return d.uniform(0.5, 2.5) if d.chance(0.28) else d.log_uniform(2.5, 25.0, 1)

    def _things(self, scene: Scene, long: bool) -> None:
        rng, d, place, self_ = self.rng, self.d, scene.place, scene.self_
        by_pid = {p.person.pid: p for p in scene.present}
        owners = list(by_pid) + [self_.pid]
        pool = self.pools.place_items(place.items)               # every item counts once, whatever its category
        for _ in range(rng.randint(12, 16) if long else rng.randint(1, 10)):
            owner = d.pick(owners + [None])
            dist, bearing = (d.uniform(0.3, 3.0) if d.chance(0.35) else d.uniform(3.0, 20.0)), rng.uniform(-3.14, 3.14)
            seen = owner is not None and owner != self_.pid and d.chance(0.55 if dist < 3 else 0.3)
            held = None
            if seen and owner in by_pid and d.chance(0.6):           # in his hands: where he is
                held, dist, bearing = owner, by_pid[owner].dist, by_pid[owner].bearing
            scene.things.append(Thing(d.pick(pool), dist, bearing, owner, seen_use=seen, held_by=held))
        if place.habitats and (long or d.chance(0.4)):
            animals = self.pools.animals_of(place.habitats)
            if animals:
                scene.things.append(Thing(d.pick(animals), d.uniform(2, 40), rng.uniform(-3.14, 3.14), animal=True))

    def _carry(self, scene: Scene, long: bool) -> None:
        """What he carries: tied to his age, his trade and where he is; each kind once; no arms under 12; nothing of
        the adults on a baby."""
        me, d = scene.self_, self.d
        if me.age < 3:
            cats, n = BABY_CARRY, d.between(0, 1)
        elif me.age < 8:
            cats, n = SMALL_CARRY, d.between(0, 2)
        elif me.age < CHILD_AGE:
            cats, n = CHILD_CARRY, d.between(0, 3)
        else:
            cats = ALWAYS_CARRY + OCC_CARRY.get(me.occupation, ()) + PLACE_CARRY.get(scene.place.name, ())
            n = d.between(5, 8) if long else d.between(0, 4)
            if d.chance(0.08):
                cats += ("blade",)
        arms = self.pools.weapon_categories
        pool = [k for k in dict.fromkeys(self.pools.place_items(cats)) if me.age >= 12 or self.pools.category_of[k] not in arms]
        scene.carried = d.sample(pool, n) if pool else []

    def _cluster(self, scene: Scene) -> None:
        """People stand together and things lie within reach of somebody: some persons are moved next to another
        (or next to the NPC), some things next to a person, so that things are done between people who are close."""
        d, rng = self.d, self.rng
        spots = [(0.0, 0.0)]                                                  # the NPC
        for i, x in enumerate(scene.present):
            spots.append((x.dist * math.cos(x.bearing), x.dist * math.sin(x.bearing)))
            if i and d.chance(0.6):
                spots[-1] = self._near(spots[rng.randrange(len(spots) - 1)])
                x.dist, x.bearing = self._polar(spots[-1])
        for t in scene.things:
            if t.held_by is None and d.chance(0.6):
                t.dist, t.bearing = self._polar(self._near(d.pick(spots)))

    def _near(self, spot: tuple[float, float]) -> tuple[float, float]:
        a, r = self.rng.uniform(-math.pi, math.pi), self.d.uniform(0.3, 1.4, 2)
        return spot[0] + r * math.cos(a), spot[1] + r * math.sin(a)

    @staticmethod
    def _polar(spot: tuple[float, float]) -> tuple[float, float]:
        return round(max(0.3, math.hypot(*spot)), 1), math.atan2(spot[1], spot[0])

    # ---- people bound to the NPC by a link ----------------------------------------------------------------
    def _family_range(self, link: str, me_age: float) -> tuple[float, float] | None:
        """The ages a new <link> can have: the rule for this link, and a consistent family (a grandparent is older
        than the parent already drawn by 16 to 45 years, and so on)."""
        span = self.rules.spec(link, me_age)
        if span is None:
            return None
        lo, hi = span
        for other, a, b in self.KIN.get(link, ()):
            for l, age in self.family:
                if l == other:
                    lo, hi = max(lo, age + a), min(hi, age + b)
        return (lo, hi) if lo <= hi else None

    def _related(self, me: Person, known: bool = False, stranger: float = 0.45) -> tuple[Person, str]:
        """Another person and what he is to the NPC, consistent with both ages and with who is already around."""
        d = self.d
        if not known and d.chance(stranger):
            return self.people.make(), "stranger"
        weights = {k: self.rules.WEIGHTS.get(k, 1.0) for k in self.rules.links}
        for _ in range(30):
            link = d.weighted(weights)
            if not self.rules.allowed(link, self.counts):
                continue
            span = self._family_range(link, me.age)
            if span is None:
                continue
            self.counts[link] = self.counts.get(link, 0) + 1
            p = self.people.make(lo=span[0], hi=span[1])
            if link in self.KIN:
                self.family.append((link, p.age))
            return p, link
        return self.people.make(), "stranger"
