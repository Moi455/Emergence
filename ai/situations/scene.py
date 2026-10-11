"""scene.py - the TRUE situation: who and what is where, at what hour. The NPC's mind is built from it later
(mind.py), with noise, ignorance and error; the model never sees this truth.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from .pools import Pools

ADULT = 18.0                                    # D10 (hard_rules.toml adult_age_years)
INTIMATE_LINKS = ("spouse", "betrothed", "lover", "former_spouse")


@dataclass
class Person:
    pid: int
    age: float                                  # true age, years
    sex: str                                    # female | male
    name: str                                   # n:<id>
    occupation: str = ""                        # an occupation word, or none (children)

    @property
    def minor(self) -> bool:
        return self.age < ADULT


class PersonFactory:
    BANDS = {"child": (3, 13), "teen": (14, 17), "adult": (18, 59), "elder": (60, 75)}
    WEIGHTS = {"child": 0.18, "teen": 0.1, "adult": 0.58, "elder": 0.14}

    def __init__(self, rng: random.Random, pools: Pools):
        self.rng, self.pools = rng, pools
        self.occupations = pools.concepts("occupation")
        self._next = 1

    def make(self, band: str | None = None, min_age: float = 0.0, max_age: float = 99.0) -> Person:
        band = band or self.rng.choices(list(self.WEIGHTS), weights=list(self.WEIGHTS.values()))[0]
        lo, hi = self.BANDS[band]
        lo, hi = max(lo, min_age), min(hi + 0.99, max_age)
        if lo > hi:                             # the band cannot satisfy the bounds: the bounds win
            lo = hi = min(max_age, max(min_age, lo))
        age = round(self.rng.uniform(lo, hi), 2)
        pid, self._next = self._next, self._next + 1
        occ = self.rng.choice(self.occupations) if age >= 16 and self.occupations and self.rng.random() < 0.8 else ""
        return Person(pid, age, self.rng.choice(("female", "male")), f"n:{self.rng.randrange(1, 5000)}", occ)


@dataclass(frozen=True)
class PlaceArchetype:
    """A kind of scene. The categories are item_type categories of the catalogue."""
    name: str
    indoors: bool
    items: tuple[str, ...]
    crowd: tuple[int, int]
    habitats: tuple[str, ...] = ()


PLACES = (
    PlaceArchetype("well", False, ("container", "cleaning", "household"), (0, 5), ("village",)),
    PlaceArchetype("tavern", True, ("drink", "dish", "tableware", "furniture", "game", "music", "light"), (2, 12)),
    PlaceArchetype("field", False, ("farming", "seed", "produce", "grain", "carry"), (0, 5), ("fields", "meadow")),
    PlaceArchetype("forest", False, ("forestry", "hunting", "raw_wood"), (0, 2), ("forest",)),
    PlaceArchetype("market", False, ("trade", "currency", "produce", "textile", "pottery", "bread", "meat"), (4, 20),
                   ("village",)),
    PlaceArchetype("home", True, ("household", "furniture", "kitchen", "tableware", "textile", "light", "toy"), (0, 5)),
    PlaceArchetype("workshop", True, ("smithing", "carpentry", "masonry", "metal_stock", "raw_wood", "leather"), (0, 4)),
    PlaceArchetype("road", False, ("carry", "vehicle"), (0, 3), ("meadow", "village")),
)


@dataclass
class Present:
    person: Person
    link: str                                   # link word of the NPC toward this person ("stranger" if none)
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

    def persons(self) -> list[Person]:
        return [self.self_] + [p.person for p in self.present] + [p for p, _ in self.absent]


class SceneFactory:
    def __init__(self, rng: random.Random, pools: Pools):
        self.rng, self.pools = rng, pools
        self.people = PersonFactory(rng, pools)
        self.links = [x for x in pools.concepts("link") if x != "stranger"]

    def make(self) -> Scene:
        rng = self.rng
        place = rng.choice(PLACES)
        self_ = self.people.make()
        scene = Scene(place, round(rng.uniform(0, 24), 2), rng.choice(("spring", "summer", "autumn", "winter")), self_)
        n = rng.randint(*place.crowd)
        for _ in range(min(n, 9)):
            other, link = self._related(self_)
            scene.present.append(Present(other, link, round(rng.uniform(0.5, 25), 1), rng.uniform(-3.14, 3.14),
                                         link != "stranger" or rng.random() < 0.2))
        for _ in range(rng.randint(0, 3)):
            other, link = self._related(self_, known=True)
            scene.absent.append((other, link))
        owners = [p.person.pid for p in scene.present] + [self_.pid]
        for _ in range(rng.randint(1, 10)):
            cat = rng.choice(place.items)
            kinds = self.pools.items_by_category.get(cat)
            if kinds:
                scene.things.append(Thing(rng.choice(kinds), round(rng.uniform(0.3, 20), 1), rng.uniform(-3.14, 3.14),
                                          rng.choice(owners + [None])))
        if place.habitats and rng.random() < 0.4:
            animals = self.pools.animals_of(place.habitats)
            if animals:
                scene.things.append(Thing(rng.choice(animals), round(rng.uniform(2, 40), 1), rng.uniform(-3.14, 3.14),
                                          animal=True))
        for _ in range(rng.randint(0, 4)):
            cat = rng.choice(("carry", "currency", "bread", "household", "blade"))
            kinds = self.pools.items_by_category.get(cat)
            if kinds:
                scene.carried.append(rng.choice(kinds))
        return scene

    def _related(self, me: Person, known: bool = False) -> tuple[Person, str]:
        """Another person and the NPC's link to him, consistent with both ages (D10: an intimate link only
        between two adults)."""
        rng = self.rng
        if not known and rng.random() < 0.45:
            return self.people.make(), "stranger"
        for _ in range(20):
            link = rng.choice(self.links)
            other = self._for_link(me, link)
            if other is not None:
                return other, link
        return self.people.make(), "neighbor"

    def _for_link(self, me: Person, link: str) -> Person | None:
        mk = self.people.make
        if link in INTIMATE_LINKS:
            # well clear of the age of majority on both sides (D10): a partner never looks or is believed a minor
            return mk("adult", min_age=max(ADULT + 3, me.age - 15), max_age=me.age + 15) if me.age >= ADULT + 3 else None
        if link in ("parent", "grandparent", "aunt_uncle"):
            gap = {"parent": 18, "grandparent": 40, "aunt_uncle": 16}[link]
            return mk("elder" if me.age + gap >= 60 else "adult", min_age=me.age + gap) if me.age + gap <= 75 else None
        if link in ("child", "grandchild", "niece_nephew", "apprentice"):
            gap = {"child": 18, "grandchild": 40, "niece_nephew": 16, "apprentice": 8}[link]
            top = me.age - gap
            if top < 3:
                return None
            band = "child" if top < 14 else ("teen" if top < 18 else "adult")
            return mk(band, max_age=top)
        if link in ("employer", "master", "employee", "colleague", "in_law"):
            return mk("adult") if me.age >= 14 else None
        return mk()
