"""builders.py - one builder per kind of record of the NPC's mind.

Each builder reads the TRUE scene and what the earlier builders wrote (BuildContext), adds its records, and never
decides anything for the NPC: it only gives him a plausible mind (what he perceives, believes, remembers, wants),
with noise, ignorance and error. D10 by construction: intimate fields only for an adult NPC toward clear adults,
gestures chosen with the governor, no physical quality said of a possible minor, nothing intimate in a proposition.
"""
from __future__ import annotations

import math
import random
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from tok2 import Record

from .body import BodyModel, Climate, daylight
from .draw import Draw, NumericPrior
from .gestures import REACH, YOUNG, GestureChooser
from .parties import PartyBook
from .pools import Pools
from .propositions import CHILD_TECHNIQUES, WORK_MIN_AGE, PropositionFactory, Refs
from .scene import ADULT, Person, Present, Scene, separation

# relation values (charter scale) a link makes plausible: field -> (low, high)
LINK_PROFILE = {
    "family": {"rel.affection": (2, 9), "rel.trust": (1, 9), "rel.familiarity": (7, 10), "rel.respect": (0, 8)},
    "partner": {"rel.affection": (3, 10), "rel.trust": (2, 10), "rel.familiarity": (8, 10), "rel.attraction": (2, 9)},
    "friend": {"rel.affection": (3, 9), "rel.trust": (2, 9), "rel.familiarity": (4, 10)},
    "enemy": {"rel.affection": (-10, -3), "rel.trust": (-10, -3), "rel.resentment": (4, 10), "rel.fear": (0, 7),
              "rel.familiarity": (3, 9)},
    "work": {"rel.trust": (-2, 7), "rel.respect": (-2, 8), "rel.familiarity": (3, 9)},
    "neighbor": {"rel.affection": (-3, 6), "rel.trust": (-3, 6), "rel.familiarity": (3, 9)},
    "stranger": {"rel.familiarity": (0, 1)},
}
LINK_KIND = {"parent": "family", "child": "family", "sibling": "family", "grandparent": "family",
             "grandchild": "family", "aunt_uncle": "family", "niece_nephew": "family", "cousin": "family",
             "in_law": "family", "spouse": "partner", "betrothed": "partner", "lover": "partner",
             "former_spouse": "neighbor", "friend": "friend", "enemy": "enemy", "colleague": "work",
             "employer": "work", "employee": "work", "master": "work", "apprentice": "work", "guest": "neighbor",
             "neighbor": "neighbor", "stranger": "stranger"}
INTIMATE_FIELDS = {"ENTITY": ("rel.attraction",), "SELF_MIND": ("attracted_to",), "SELF_STATE": ("drive.intimacy",)}

# how often each flag is true (a flag is not drawn at random): (type, field) -> rate
FLAG_RATES = {("BELIEF", "polarity"): 0.9, ("BELIEF", "secret"): 0.05, ("BELIEF", "contradicted"): 0.06,
              ("HEARD", "polarity"): 0.9, ("HEARD", "secret"): 0.03, ("HEARD", "contradicted"): 0.03,
              ("MEMORY", "defining"): 0.08, ("MEMORY", "secret"): 0.06}

POSTURE = {"standing": 0.42, "walking": 0.2, "sitting": 0.22, "kneeling": 0.025, "crouching": 0.03, "running": 0.025,
           "lying": 0.02, "prone": 0.004, "climbing": 0.008, "swimming": 0.004, "guard": 0.02, "carrying": 0.03}
EXPRESSION = {"neutral": 0.5, "smile": 0.13, "laugh": 0.04, "frown": 0.08, "anger": 0.04, "fear": 0.03, "sadness": 0.04,
              "crying": 0.01, "disgust": 0.015, "surprise": 0.03, "pain": 0.02, "contempt": 0.015, "boredom": 0.04,
              "tenderness": 0.02}
AMOUNT = {"none": 0.03, "few": 0.2, "some": 0.35, "many": 0.2, "unknown": 0.22}
DISPLAY = {"calm": 0.35, "grazing": 0.3, "alert": 0.14, "fleeing": 0.05, "growling": 0.03, "baring_teeth": 0.015,
           "charging": 0.01, "stalking": 0.02, "playing": 0.07}
ANIMAL_MOTION = {"still": 0.55, "approaching": 0.1, "leaving": 0.15, "falling": 0.0, "rolling": 0.0}
SOURCE = {"seen": 0.34, "told": 0.26, "heard": 0.18, "inferred": 0.1, "assumed": 0.06, "dreamt": 0.02, "read": 0.04}
CERTAINTY = {"seen": (8.0, 1.3), "told": (5.5, 1.8), "heard": (4.3, 1.8), "read": (6.5, 1.5), "inferred": (4.0, 1.8),
             "assumed": (2.5, 1.5), "dreamt": (1.3, 1.0)}
HOPS = {"seen": (0, 0), "told": (1, 3), "heard": (1, 4), "read": (1, 2), "inferred": (1, 2), "assumed": (1, 3), "dreamt": (1, 3)}
GOAL_STATUS = {"active": 0.86, "paused": 0.08, "achieved": 0.02, "failed": 0.02, "abandoned": 0.02}
GOAL_ORIGIN = {"self": 0.55, "asked": 0.15, "role": 0.1, "agreement": 0.08, "norm": 0.12}
COMMIT_STATUS = {"open": 0.85, "fulfilled": 0.05, "broken": 0.06, "released": 0.04}
EMOTION_DEATH = {"e_grief": 0.4, "e_sadness": 0.25, "e_anger": 0.08, "e_guilt": 0.08, "e_fear": 0.05, "e_anxiety": 0.04,
                 "e_shame": 0.02, "e_joy": 0.02, "e_surprise": 0.04, "e_confusion": 0.02}
POSITIVE = ("e_joy", "e_gratitude", "e_pride", "e_tenderness")
NEUTRAL = ("e_surprise", "e_confusion")
MEMORY_ROLE_DEFAULT = "witness"
# what a gesture directed at the NPC stirs (emotion -> range), by family of the gesture
REACTION = {"force": {"emo.fear": (1.5, 5.5), "emo.anger": (1.5, 6.0), "emo.surprise": (1.0, 5.0), "emo.anxiety": (1.0, 4.0),
                      "stress": (2.0, 6.0)},
            "care": {"emo.tenderness": (1.0, 4.0), "emo.joy": (0.5, 3.0)},
            "grasp": {"emo.surprise": (0.5, 2.5)},
            "perceive": {"emo.anxiety": (0.0, 1.5)}}


@dataclass
class Entry:
    """A person of the NPC's mind: his key, the truth about him, and his link to the NPC."""
    key: str
    person: Person
    link: str
    present: Present | None = None
    fields: dict = field(default_factory=dict)       # his ENTITY fields, once built (None for ghosts)


class BuildContext:
    """The shared state of one build: scene, draws, keys, parties and the records written so far."""

    def __init__(self, rng: random.Random, pools: Pools, props: PropositionFactory, chooser: GestureChooser, scene: Scene):
        self.rng, self.pools, self.props, self.chooser, self.scene = rng, pools, props, chooser, scene
        self.d = Draw(rng)
        self.prior = NumericPrior(self.d)
        self.me = scene.self_
        self.types = pools.interface.token_types
        self.cap = {t: spec["count"] for t, spec in self.types.items()}
        self.records: dict[str, list[Record]] = {}
        self.parties = PartyBook(self.me)
        self.rules = props.rules
        self.climate_index = Climate(self.d).index(scene.season, scene.hour, scene.place.indoors)
        # the layout of the mind: who is filed, who is a ghost (known but left out), which things, which pointers
        every = [(x.person, x.link, x) for x in scene.present if x.known or x.dist < 15] + [(p, l, None) for p, l in scene.absent]
        filed, overflow = every[:self.cap["ENTITY"]], every[self.cap["ENTITY"]:]
        self.entries = [Entry(f"@E{i + 1}", p, l, x) for i, (p, l, x) in enumerate(filed)]
        self.by_pid = {e.person.pid: e for e in self.entries}
        self.by_pid[self.me.pid] = Entry("me", self.me, "me")
        ghosts = [(p, l) for p, l, _ in overflow] + list(scene.ghosts)
        self.ghosts = [Entry(f"@E{len(self.entries) + 1 + i}", p, l) for i, (p, l) in enumerate(ghosts)]
        self.things = scene.things[:self.cap["THING"]]
        self.tkeys = [f"@T{i + 1}" for i in range(len(self.things))]
        self.carried = scene.carried[:self.cap["INV"]]
        self.ikeys = [f"@T{len(self.things) + i + 1}" for i in range(len(self.carried))]
        self.loci = [f"@L{i + 1}" for i in range(self.count("LOCUS", 0))]
        self.groups = [f"@G{i + 1}" for i in range(self.count("GROUP", 0))]
        self.pkeys = [e.key for e in self.entries]
        self.here = [e.key for e in self.entries if e.present is not None]
        self.refs = Refs(persons=self.pkeys + [g.key for g in self.ghosts],
                         absent=[e.key for e in self.entries if e.present is None] + [g.key for g in self.ghosts],
                         things=self.tkeys + self.ikeys, loci=self.loci, groups=self.groups, here=self.here)
        self.said: set[str] = set()                      # propositions already in his mind (no twice the same)
        self.events: list[Record] = []
        self.directed: list[Record] = []                # events directed at the NPC himself
        self.hurt = False
        props.arm(rng, self.parties, self.me.age)

    # ---- helpers shared by the builders -----------------------------------------------------------------
    def count(self, typ: str, lo: int, hi: int | None = None) -> int:
        """How many records of a type: a random number, but a long scene (30 %) fills each type close to its budget."""
        cap = self.cap[typ]
        if self.scene.long:
            return self.d.between(max(lo, math.ceil(0.8 * cap)), cap)
        return self.d.between(lo, min(cap, cap if hi is None else hi))

    def add(self, rec: Record) -> Record:
        self.records.setdefault(rec.type, []).append(rec)
        return rec

    def of(self, typ: str) -> list[Record]:
        return self.records.get(typ, [])

    def fill(self, typ: str, fields: dict, skip: tuple = ()) -> dict:
        """Complete the scalar fields nobody set: a flag at its own rate, a number from its scale alone."""
        for name, spec in self.types[typ]["fields"].items():
            if name in fields or name in skip or name in INTIMATE_FIELDS.get(typ, ()) or spec.get("components"):
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

    def direction(self, bearing: float) -> dict:
        return {"sin": round(math.sin(bearing), 4), "cos": round(math.cos(bearing), 4)}

    def hours_ago(self, lo: float, hi: float) -> float:
        return self.d.log_uniform(lo, hi)

    def until(self, lo: float, hi: float) -> float:
        """Hours until a deadline: mostly ahead, sometimes already overdue (negative)."""
        h = self.hours_ago(lo, hi)
        return -h if self.d.chance(0.2) else h

    @staticmethod
    def stage(age: float, values: list[str]) -> str:
        want = "infant" if age < 3 else "child" if age < 14 else "teen" if age < ADULT else "adult" if age < 60 else "elder"
        return want if want in values else values[-1]

    def perceived(self) -> list[str]:
        """Pointers to what the NPC perceives right now: the persons who are here and the things in view."""
        return self.here + self.tkeys

    def key_class(self, key: str) -> str | None:
        if key == "me" or key.startswith("@E"):
            return "agent"
        if key.startswith("@T"):
            return "animal" if key in self.refs.animals else "item"
        return None


class RecordBuilder(ABC):
    @abstractmethod
    def build(self, c: BuildContext) -> None: ...


# ---------------------------------------------------------------------------------------------------- the NPC
class SelfBuilder(RecordBuilder):
    """SELF and SELF_MIND: his body, his needs, his hands, his temperament (SELF_STATE comes last)."""

    def build(self, c: BuildContext) -> None:
        me, d, sc = c.me, c.d, c.scene
        vectors = [c.pools.item_vector(k) for k in c.carried]
        body, hurt = BodyModel(d).make(me.age, sc.hour, c.climate_index, sc.place.name == "tavern",
                                       sum(v.get("mass", 0.0) for v in vectors))
        c.hurt = hurt
        night = sc.hour < 5.5 or sc.hour >= 21.5
        posture = dict(POSTURE)
        if night and sc.place.indoors:
            posture["lying"] = 0.3
        if body["need.sleep"] > 8:
            posture["lying"] += 0.2
        if sc.place.indoors:
            posture["swimming"] = posture["climbing"] = 0.0
        h = sc.hour / 24 * 2 * math.pi
        s = {"age": round(me.age, 1), "age_stage": c.stage(me.age, c.pools.enum("SELF", "age_stage")), "sex": me.sex,
             "season": sc.season, "place": "@PLACE", "posture": c.enum("SELF", "posture", posture),
             "time": {"sin": round(math.sin(h), 4), "cos": round(math.cos(h), 4),
                      "certainty": d.uniform(0.35, 0.8, 2) if sc.place.indoors else d.uniform(0.65, 1.0, 2)}}
        s.update(body)
        s["held"] = vectors[:2] if vectors and d.chance(0.6) else []         # [] = he knows his hands are empty
        if not hurt:
            s["wound"] = []                                                    # known: none
        c.add(Record("SELF", "me", c.fill("SELF", s)))
        mind = {}
        if me.age >= ADULT:
            mind["attracted_to"] = {"m": ["male"], "f": ["female"], "b": ["female", "male"]}[
                d.weighted({"m": 0.45, "f": 0.45, "b": 0.1})]
        for name, spec in c.types["SELF_MIND"]["fields"].items():
            if name in INTIMATE_FIELDS["SELF_MIND"] or spec["scale"] not in ("unipolar10", "bipolar10"):
                continue
            if spec["scale"] == "bipolar10":
                mind[name] = d.gauss(0, 3, -10.0, 10.0)
            else:                                                              # abilities and values: centred, a child less in control
                mind[name] = d.gauss(5.0 - (2.0 if name == "ability.self_control" and me.age < YOUNG else 0.0), 2.2)
        c.add(Record("SELF_MIND", "me.mind", mind))


# ---------------------------------------------------------------------------------------------------- people
class PersonBuilder(RecordBuilder):
    """ENTITY: the persons he knows, present (seen: distance, looks) or absent (a name and feelings)."""

    def build(self, c: BuildContext) -> None:
        for e in c.entries:
            f = self._entity(c, e)
            e.fields = f
            c.parties.add_person(e.key, e.person, f)
            c.add(Record("ENTITY", e.key, f))
        for g in c.ghosts:                                           # known but not filed: the governor knows nothing
            c.parties.add_person(g.key, g.person, None)
        c.refs.links = {e.key: e.link for e in c.entries}

    def _seen_age(self, c: BuildContext, p: Person, intimate: bool) -> float:
        noise = 1.0 if p.age < ADULT else 4.0
        seen = max(0.5, p.age + c.rng.uniform(-noise, noise))
        return round(max(seen, ADULT + 1) if intimate else seen, 1)        # a partner is known to be an adult

    def _entity(self, c: BuildContext, e: Entry) -> dict:
        d, me, p, link, x = c.d, c.me, e.person, e.link, e.present
        intimate = link in c.rules.intimate
        f = {"link": link if link in c.pools.enum("ENTITY", "link") else "stranger", "present": x is not None,
             "known_by": "seen" if x is not None else c.enum("ENTITY", "known_by", {"seen": 0.55, "name_only": 0.33, "described": 0.12}),
             "id_certainty": d.uniform(6, 10) if (link != "stranger" and x is not None) else
             d.uniform(4, 9) if link != "stranger" else d.uniform(0, 4)}
        if link != "stranger":
            f["name"] = p.name
        if x is not None:
            f.update(self._looks(c, e, intimate))
        prof = LINK_PROFILE[LINK_KIND.get(link, "neighbor")]
        for name, (lo, hi) in prof.items():
            f[name] = d.uniform(lo, hi)
        clear_adult = me.age >= ADULT and p.age >= ADULT and f.get("look.age", ADULT) >= ADULT
        if not (clear_adult and intimate):
            f.pop("rel.attraction", None)
        f["rep"] = {k: d.uniform(-1, 1, 2) for k in ("honesty", "danger", "competence", "wealth", "piety") if d.chance(0.4)}
        skip = tuple(n for n in c.types["ENTITY"]["fields"] if n.startswith("look.")) if x is None else ()
        return c.fill("ENTITY", f, skip=skip)

    def _looks(self, c: BuildContext, e: Entry, intimate: bool) -> dict:
        d, x, p = c.d, e.present, e.person
        condition = c.enum("ENTITY", "look.condition", {"active": 0.9, "hurt": 0.07, "down": 0.012, "motionless": 0.008,
                                                        "obviously_dead": 0.004})
        posture = c.enum("ENTITY", "look.posture", POSTURE)
        if condition in ("down", "motionless", "obviously_dead"):
            posture = "prone" if d.chance(0.3) else "lying"
        moving = {"walking": {"approaching": 0.4, "leaving": 0.4, "still": 0.2}, "running": {"running": 1.0},
                  "standing": {"still": 0.88, "approaching": 0.05, "leaving": 0.07}}.get(posture, {"still": 1.0})
        motion = c.enum("ENTITY", "look.motion", moving)
        if posture in ("walking", "running") and condition != "active":
            motion = "still"
        wounds = {"active": 0.0, "hurt": d.uniform(1, 6), "down": d.uniform(3, 8), "motionless": d.uniform(3, 9),
                  "obviously_dead": d.uniform(7, 10)}[condition]
        gaze_pool = ["me"] + [k for k in c.here if k != e.key] + c.tkeys
        gaze = "" if condition in ("down", "motionless", "obviously_dead") else d.weighted(
            {"me": max(1.0, 0.5 * len(gaze_pool))}, allowed=gaze_pool) if d.chance(0.9) else ""
        return {"dist": x.dist, "dir": c.direction(x.bearing), "look.age": self._seen_age(c, p, intimate),
                "look.sex": p.sex if d.chance(0.95) else "unclear", "look.posture": posture,
                "look.expression": c.enum("ENTITY", "look.expression", EXPRESSION), "look.motion": motion,
                "look.condition": condition, "look.wounds": wounds, "look.gaze": gaze}


# ---------------------------------------------------------------------------------------------------- things
class ThingBuilder(RecordBuilder):
    """THING (seen) and INV (carried). An owner is BELIEVED: sure of his own things, often right about a known
    person's, right about a stranger's only if he saw him hold or use it, sometimes wrong."""

    def build(self, c: BuildContext) -> None:
        d, pools = c.d, c.pools
        animals = set()
        for key, t in zip(c.tkeys, c.things):
            f = {"kind": t.kind, "dist": t.dist, "dir": c.direction(t.bearing),
                 "file_certainty": d.gauss(10.0 - 0.22 * t.dist, 1.0)}
            if t.animal:
                animals.add(key)
                f.update({"display": c.enum("THING", "display", DISPLAY), "motion": c.enum("THING", "motion", ANIMAL_MOTION)})
            else:
                f.update({"props": pools.item_vector(t.kind), "amount": c.enum("THING", "amount", AMOUNT)})
                f["owner"] = self._believed_owner(c, t)
            c.add(Record("THING", key, f))
        c.refs.animals = frozenset(animals)
        for key, kind in zip(c.ikeys, c.carried):
            borrowed = c.pkeys and d.chance(0.05)                          # a tool lent by somebody he knows
            c.add(Record("INV", key, {"kind": kind, "props": pools.item_vector(kind),
                                      "owner": d.pick(c.pkeys) if borrowed else "me",
                                      "amount": c.enum("INV", "amount", AMOUNT)}))
        c.refs.owners = {r.key: r.fields["owner"] for r in c.of("THING") if r.fields.get("owner")}

    def _believed_owner(self, c: BuildContext, t) -> str | None:
        d = c.d
        owner = c.by_pid.get(t.owner) if t.owner is not None else None
        if t.owner is not None and t.owner == c.me.pid:
            return "me" if d.chance(0.95) else None
        if owner is not None:
            f = owner.fields
            known = owner.link != "stranger" and f.get("known_by") == "seen"
            if known:
                p_true = min(0.95, 0.3 + 0.06 * f.get("id_certainty", 5.0) + (0.2 if t.seen_use else 0.0))
            elif owner.link == "stranger":
                p_true = 0.85 if t.seen_use else 0.0          # a stranger's: only if he saw him hold or use it
            else:
                p_true = 0.3 if f.get("known_by") == "name_only" else 0.4
            if d.chance(p_true):
                return owner.key
        return self._wrong_owner(c, t.owner) if d.chance(0.35 if t.owner is not None else 0.08) else None

    def _wrong_owner(self, c: BuildContext, true_pid) -> str | None:
        """A plausible but wrong owner: somebody he knows, not the real one."""
        pool = [e.key for e in c.entries if e.person.pid != true_pid and e.link != "stranger"] + ["me"] * 1
        return c.d.pick(pool) if pool else None


# ---------------------------------------------------------------------------------------------------- the place
class PlaceBuilder(RecordBuilder):
    """PLACE (light, noise, air, the people PERCEIVED), LOCUS (places he knows), GROUP (groups he knows)."""

    def build(self, c: BuildContext) -> None:
        d, sc = c.d, c.scene
        day = daylight(sc.hour)
        lamps = set(c.pools.items_by_category.get("light", ()))
        lamp = any(t.kind in lamps for t in sc.things)
        if sc.place.indoors:
            light = d.gauss(1.6 + 4.0 * day + (2.5 if lamp else 0.0), 0.7)
        else:
            light = d.gauss(10 * day * d.rng.uniform(0.6, 1.0) + 0.5, 0.3)
        # crowd = the persons he PERCEIVES: those near, and most of those far (the truth may be larger)
        seen = sum(1 for x in sc.present if x.dist < 12 or d.chance(0.65))
        noise = d.gauss(0.6 * seen + (1.5 if sc.place.indoors else 0.0) + (1.5 if sc.place.name == "tavern" else 0.0), 0.8)
        values = c.pools.enum("PLACE", "air_felt")
        c.add(Record("PLACE", "@PLACE", c.fill("PLACE", {
            "indoors": sc.place.indoors, "crowd": seen, "light": light, "noise": noise,
            "air_felt": Climate.word(values, c.climate_index)})))
        for key in c.loci:
            owner = d.weighted({"me": 0.15, "": 0.55, "other": 0.3})
            if owner == "other":
                owner = d.pick(c.pkeys) if c.pkeys else ""
            c.add(Record("LOCUS", key, {"dist": d.uniform(20, 3000, 0), "dir": c.direction(d.uniform(-3.14, 3.14, 4)),
                                        "owner": owner}))
        for key in c.groups:
            c.add(Record("GROUP", key, c.fill("GROUP", {"known_by": c.enum("GROUP", "known_by", {
                "seen": 0.6, "name_only": 0.25, "described": 0.15})})))


# ---------------------------------------------------------------------------------------------------- events
class EventBuilder(RecordBuilder):
    """EVENT: gestures he has just perceived. Actor and target are PRESENT (persons here, things in view); a contact
    gesture only between two within reach; look, move and take are common, force is rare."""

    def build(self, c: BuildContext) -> None:
        if not c.here:
            return
        n = c.count("EVENT", 0, 4) if c.scene.long else c.d.weighted({0: 0.35, 1: 0.3, 2: 0.2, 3: 0.1, 4: 0.05})
        n = min(n, c.cap["EVENT"])
        for _ in range(n):
            self._one(c, len(c.events) + 1)

    def _target(self, c: BuildContext, actor: Entry) -> tuple[str, float | None]:
        """(key, distance between the two) of what the actor does it to; ('', None) for no target."""
        d, x = c.d, actor.present
        things = {k: t for k, t in zip(c.tkeys, c.things)}
        kind = d.weighted({"me": 0.3, "other": 0.25, "thing": 0.4, "none": 0.12 if not c.scene.long else 0.03})
        others = [e for e in c.entries if e.present is not None and e.key != actor.key]
        if kind == "me":
            return "me", x.dist
        if kind == "other" and others:
            o = d.pick(others)
            return o.key, separation(x, o.present)
        if kind == "thing" and things:
            k = d.pick(list(things))
            return k, separation(x, things[k])
        return "", None

    def _one(self, c: BuildContext, n: int) -> None:
        d = c.d
        actor = d.pick([e for e in c.entries if e.present is not None])
        target, gap = self._target(c, actor)
        young = actor.person.age < YOUNG
        pick = c.chooser.pick(d, c.key_class(target) if target else None, c.parties.party(actor.key),
                              c.parties.party(target) if target else None,
                              contact_ok=gap is not None and gap <= REACH, young=young)
        if pick is None:
            return
        contact = c.pools.cat["action"][pick.gesture].contact
        sense = d.weighted({"seen": 0.72, "heard": 0.23, "felt": 0.05 if (target == "me" and contact) else 0.0})
        rec = Record("EVENT", f"@V{n}", {"actor": actor.key, "gesture": pick.gesture, "target": target, "sense": sense,
                                         "age": c.hours_ago(0.0005, 0.05), "manner": list(pick.manner)})
        c.events.append(c.add(rec))
        if target == "me":
            c.directed.append(rec)


# ---------------------------------------------------------------------------------------------------- beliefs
class BeliefBuilder(RecordBuilder):
    """BELIEF (what he holds true, from a source) and HEARD (what was just said to him)."""

    def _source(self, c: BuildContext, can_tell: bool) -> str:
        w = dict(SOURCE)
        if c.me.age < 9:
            w["read"] = 0.0
        elif c.me.age < 14:
            w["read"] *= 0.3
        if not can_tell:
            w["told"] = w["heard"] = 0.0
        return c.d.weighted(w)

    def _certainty(self, c: BuildContext, source: str, contradicted: bool) -> float:
        mu, sd = CERTAINTY[source]
        v = c.d.gauss(mu, sd)
        return round(v * 0.4, 1) if contradicted else v

    def _informants(self, c: BuildContext) -> list[str]:
        return c.pkeys + [g.key for g in c.ghosts]

    def build(self, c: BuildContext) -> None:
        d, P = c.d, c.props
        informants = self._informants(c)
        beliefs = 0
        for i in range(c.count("BELIEF", 3)):
            prop = P.belief(c.refs)
            if prop is None or prop in c.said:
                continue
            c.said.add(prop)
            beliefs += 1
            key = f"b:{beliefs}"
            src = self._source(c, bool(informants))
            contradicted = d.chance(FLAG_RATES[("BELIEF", "contradicted")])
            told = src in ("told", "heard")
            c.add(Record("BELIEF", key, c.fill("BELIEF", {
                "prop": prop, "source": src, "age": c.hours_ago(0.1, 3000), "contradicted": contradicted,
                "hops": d.between(*HOPS[src]), "certainty": self._certainty(c, src, contradicted),
                "informant": d.pick(informants) if told else "",             # "" = nobody told him
                "shared": d.sample(c.pkeys, d.between(0, 2))})))
        n_heard = c.count("HEARD", 0, 2) if c.here else 0
        for i in range(n_heard):
            prop = P.belief(c.refs)
            if prop is None or prop in c.said:
                continue
            c.said.add(prop)
            src = d.weighted({"told": 0.65, "heard": 0.35})
            contradicted = d.chance(FLAG_RATES[("HEARD", "contradicted")])
            c.add(Record("HEARD", f"h:{i + 1}", c.fill("HEARD", {
                "prop": prop, "source": src, "hops": d.between(1, 2), "informant": d.pick(c.here),
                "age": c.hours_ago(0.001, 0.2), "contradicted": contradicted,
                "certainty": self._certainty(c, src, contradicted),
                "shared": d.sample(c.pkeys, 1) if d.chance(0.08) else []})))


class MemoryBuilder(RecordBuilder):
    """MEMORY: what he lived, saw or was told, with the feeling it left."""

    def build(self, c: BuildContext) -> None:
        d, P = c.d, c.props
        interps = [x for x in c.pools.interpretations if x not in c.pools.intimate_symbols]
        k = 0
        for _ in range(c.count("MEMORY", 1)):
            got = P.memory(c.refs)
            if got is None:
                continue
            prop, role = got
            if prop in c.said:
                continue
            c.said.add(prop)
            k += 1
            emotion = c.enum("MEMORY", "emotion", EMOTION_DEATH if "(dead" in prop else None)
            age = c.hours_ago(1, 5000)
            valence = (d.uniform(1, 9) if emotion in POSITIVE else d.gauss(0, 2, -4.0, 4.0) if emotion in NEUTRAL
                       else -d.uniform(1, 9))
            c.add(Record("MEMORY", f"m:{k}", c.fill("MEMORY", {
                "prop": prop, "age": age, "emotion": emotion, "valence": valence, "role": role,
                "vividness": d.gauss(9.0 - 0.75 * math.log(age), 1.2),
                "interp": d.pick(interps) if d.chance(0.4) else None,
                "place": d.pick(c.loci + ["@PLACE"]) if d.chance(0.7) else None})))


class SocialBuilder(RecordBuilder):
    """REQUEST (a request just heard) and COMMIT (what he owes or is owed). A child has no formal engagement."""

    def build(self, c: BuildContext) -> None:
        d, P = c.d, c.props
        if c.here:
            for i in range(c.count("REQUEST", 0, 2)):
                asker = d.pick(c.here)
                prop = P.request(c.refs, asker)
                if prop is not None:
                    c.add(Record("REQUEST", f"q:{len(c.of('REQUEST')) + 1}",
                                 {"from": asker, "prop": prop, "age": c.hours_ago(0.001, 2)}))
        if c.me.age < 12 or not c.pkeys:
            return
        for i in range(c.count("COMMIT", 0, 2)):
            who = d.pick(c.pkeys)
            kind = d.pick(P.kinds)
            mine = d.chance(0.5)
            prop = P.validate(f"(did {'me' if mine else who} give {kind} (to {who if mine else 'me'}))", "belief")
            if prop is not None:
                c.add(Record("COMMIT", f"c:{len(c.of('COMMIT')) + 1}", {
                    "counterparty": who, "mine": mine, "prop": prop, "deadline": c.until(1, 300),
                    "status": c.enum("COMMIT", "status", COMMIT_STATUS), "witnesses": d.sample(c.pkeys, d.between(0, 2))}))


class GoalBuilder(RecordBuilder):
    """GOAL (what he wants) and PLAN (the step he is on)."""

    def build(self, c: BuildContext) -> None:
        d, P = c.d, c.props
        beliefs = [r.key for r in c.of("BELIEF")]
        memories = [r.key for r in c.of("MEMORY")]
        asked = [r.key for r in c.of("REQUEST")]
        deals = [r.key for r in c.of("COMMIT")]
        k = 0
        for _ in range(c.count("GOAL", 1)):
            got = P.goal(c.refs)
            if got is None:
                continue
            prop, mode = got
            if prop in c.said:
                continue
            c.said.add(prop)
            origin = c.enum("GOAL", "origin", GOAL_ORIGIN)
            if (origin == "asked" and not asked) or (origin == "agreement" and not deals):
                origin = "self"
            ref = {"asked": asked, "agreement": deals}.get(origin) or beliefs + memories
            status = c.enum("GOAL", "status", GOAL_STATUS)
            k += 1
            c.add(Record("GOAL", f"g:{k}", c.fill("GOAL", {
                "prop": prop, "mode": mode, "status": status, "origin": origin,
                "origin_ref": d.pick(ref) if ref and d.chance(0.8) else "", "age": c.hours_ago(0.1, 500),
                "progress": 1.0 if status == "achieved" else d.uniform(0, 0.9, 2),
                "deadline": c.until(1, 500) if d.chance(0.4) else None})))
        goals = [r.key for r in c.of("GOAL")]
        if goals and d.chance(0.6):
            self._plan(c, goals)

    def _plan(self, c: BuildContext, goals: list[str]) -> None:
        d = c.d
        target = d.pick(["me"] + c.perceived())
        cls = c.key_class(target)
        young = c.me.age < YOUNG
        me, tgt = c.parties.party("me"), c.parties.party(target)
        step = c.chooser.pick(d, cls, me, tgt, young=young, with_manner=False)
        nxt = c.chooser.pick(d, cls, me, tgt, young=young, with_manner=False)
        if step is None or nxt is None or step.gesture == nxt.gesture:
            return
        c.add(Record("PLAN", "p:1", c.fill("PLAN", {"step": step.gesture, "next": nxt.gesture, "goal": d.pick(goals),
                                                    "target": target})))


class SkillBuilder(RecordBuilder):
    """SKILL (what he knows how to do, as he estimates it) and TASTE (what he likes or dislikes)."""

    def build(self, c: BuildContext) -> None:
        d, me = c.d, c.me
        techs = c.pools.enum("SKILL", "technique")
        if me.age < YOUNG:
            techs = []
        elif me.age < WORK_MIN_AGE:
            techs = [t for t in techs if t in CHILD_TECHNIQUES]
        for i, t in enumerate(d.sample(techs, c.count("SKILL", 0) if techs else 0)):
            level = 2.5 + min(me.age, 40) * 0.1
            c.add(Record("SKILL", f"k:{i + 1}", {"technique": t, "self_estimate": d.gauss(level, 2.2)}))
        words = c.props.kinds + [w for w in c.props.words["quality"] if me.age >= ADULT or w not in ("w_beautiful", "w_ugly")]
        for i in range(c.count("TASTE", 0)):
            c.add(Record("TASTE", f"t:{i + 1}", {"concept": d.pick(words), "attitude": d.gauss(0, 5, -10.0, 10.0)}))


# ---------------------------------------------------------------------------------------------------- state and wake
class StateBuilder(RecordBuilder):
    """SELF_STATE: what he attends to, his drives and feelings, raised by what is done to him."""

    def build(self, c: BuildContext) -> None:
        d, me = c.d, c.me
        s = {}
        for name, spec in c.types["SELF_STATE"]["fields"].items():
            if name == "attention" or name in INTIMATE_FIELDS["SELF_STATE"] or spec["scale"] not in ("unipolar10", "bipolar10"):
                continue
            s[name] = d.clip(abs(d.rng.gauss(0, 1.6))) if name.startswith("emo.") else c.prior.sample(spec)
        body = c.of("SELF")[0].fields
        s["mood.energy"] = d.gauss(8.0 - 0.5 * body["need.sleep"] - 0.15 * body["need.exhaustion"], 1.2)
        base = c.of("SELF_MIND")[0].fields.get("temper.baseline_mood", 0.0)
        s["mood.valence"] = d.gauss(base * 0.6 - 0.5 * body["body.pain"] - 0.2 * body["need.hunger"], 1.5, -10.0, 10.0)
        for ev in c.directed:
            fam = c.pools.cat["action"][ev.fields["gesture"]].family
            for emo, (lo, hi) in REACTION.get(fam, {}).items():
                s[emo] = d.clip(s.get(emo, 0.0) + d.rng.uniform(lo, hi))
        attention = (d.pick([e.fields["actor"] for e in c.directed]) if c.directed and d.chance(0.7)
                     else d.pick(c.perceived()) if c.perceived() else None)
        s["attention"] = attention
        if me.age >= ADULT:
            drive = d.clip(abs(d.rng.gauss(0, 2.5)))
            if attention and attention.startswith("@E") and c.parties.may_be_minor(attention):
                drive = min(drive, d.uniform(0, 2))                          # D10: attention on a possible minor
            s["drive.intimacy"] = drive
        c.add(Record("SELF_STATE", "me.state", s))


class WakeBuilder(RecordBuilder):
    """WAKE: a coherent reason why he decides now. A request he has heard, then words he has heard, then an event
    he has perceived, then a goal whose deadline has passed, his plan, his body or his routine. The trigger is the
    record that woke him (@V, h:, q:, g:, p:); a body or a routine has none ("" = known: nobody)."""

    def build(self, c: BuildContext) -> None:
        r, first = c.rng, lambda typ: next((x.key for x in c.of(typ)), None)  # noqa: E731
        late = [x.key for x in c.of("GOAL") if (x.fields.get("deadline") or 0) < 0]
        directed = c.directed[0].key if c.directed else None
        if first("REQUEST"):
            cause, trigger, mode, urgency = "request", first("REQUEST"), r.choice(["listen", "act", "act"]), r.uniform(3, 8)
        elif first("HEARD"):
            cause, trigger, mode, urgency = "speech", first("HEARD"), r.choice(["listen", "listen", "reflect"]), r.uniform(1, 7)
        elif first("EVENT"):
            cause, trigger, mode, urgency = "perception", directed or first("EVENT"), r.choice(["act", "act", "listen"]), r.uniform(2, 9)
        elif late:
            cause, trigger, mode, urgency = "timer", late[0], "act", r.uniform(3, 8)
        elif first("PLAN"):
            cause, trigger, mode, urgency = "plan", first("PLAN"), "act", r.uniform(1, 6)
        elif r.random() < 0.5:
            cause, trigger, mode, urgency = "body", "", "act", r.uniform(3, 9)
        else:
            cause, trigger, mode, urgency = "routine", "", r.choice(["act", "reflect"]), r.uniform(0, 3)
        c.add(Record("WAKE", "wake", {"mode": mode, "cause": cause, "trigger": trigger, "urgency": round(urgency, 1)}))
