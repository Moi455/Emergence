"""builders.py - one builder per kind of record of the NPC's mind.

Each builder reads the TRUE scene and what the earlier builders wrote (BuildContext), adds its records, and never
decides anything for the NPC: it only gives him a plausible mind (what he perceives, believes, remembers, wants),
with noise, ignorance and error. The reason he wakes (`BuildContext.cause`) is drawn first; the builders make the
situation that justifies it. D10 by construction: intimate fields only for an adult NPC toward clear adults he
sees (or, when absent, whose adult age he believes), gestures chosen with the governor, no physical quality said
of a possible minor, nothing intimate in a proposition.
"""
from __future__ import annotations

import math
from abc import ABC, abstractmethod

from tok2 import Record

from .body import BodyModel, Climate, daylight
from .context import BuildContext, stage_of
from .gestures import INFANT, REACH, YOUNG, Target
from .layout import Entry
from .memories import MemoryColour
from .plans import PlanTable
from .propositions import CHILD_TECHNIQUES, WORK_MIN_AGE
from .scene import ADULT, Person, separation

# the latent attitude toward a person, by kind of link: (mean, spread) on -1..+1. Feelings follow it together.
ATTITUDE = {"family": (0.55, 0.25), "partner": (0.7, 0.2), "friend": (0.5, 0.25), "enemy": (-0.7, 0.2),
            "work": (0.1, 0.3), "neighbor": (0.05, 0.3), "stranger": (0.0, 0.3)}
FAMILIARITY = {"family": (7, 10), "partner": (8, 10), "friend": (4, 10), "enemy": (3, 9), "work": (3, 9),
               "neighbor": (3, 9), "stranger": (0, 1)}
LINK_KIND = {"parent": "family", "child": "family", "sibling": "family", "grandparent": "family",
             "grandchild": "family", "aunt_uncle": "family", "niece_nephew": "family", "cousin": "family",
             "in_law": "family", "spouse": "partner", "betrothed": "partner", "lover": "partner",
             "former_spouse": "neighbor", "friend": "friend", "enemy": "enemy", "colleague": "work",
             "employer": "work", "employee": "work", "master": "work", "apprentice": "work", "guest": "neighbor",
             "neighbor": "neighbor", "stranger": "stranger"}
OBLIGED_TO = ("employer", "master", "parent", "grandparent", "aunt_uncle")         # he owes them
OWED_BY = ("employee", "apprentice", "child", "grandchild", "niece_nephew")        # they owe him
MISTAKEN_LINKS = {"neighbor": 3, "guest": 2, "friend": 2, "colleague": 2, "cousin": 1, "in_law": 1}

POSTURE = {"standing": 0.42, "walking": 0.2, "sitting": 0.22, "kneeling": 0.025, "crouching": 0.03, "running": 0.025,
           "lying": 0.02, "prone": 0.004, "climbing": 0.008, "swimming": 0.004, "guard": 0.02, "carrying": 0.03}
POSTURE_BABY = {"lying": 0.5, "sitting": 0.3, "carrying": 0.2}
EXPRESSION = {"neutral": 0.5, "smile": 0.13, "laugh": 0.04, "frown": 0.08, "anger": 0.04, "fear": 0.03, "sadness": 0.04,
              "crying": 0.01, "disgust": 0.015, "surprise": 0.03, "pain": 0.02, "contempt": 0.015, "boredom": 0.04,
              "tenderness": 0.02}
EXPRESSION_BABY = {"neutral": 0.4, "smile": 0.25, "laugh": 0.1, "crying": 0.2, "surprise": 0.05}
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
# what a gesture directed at the NPC stirs (emotion -> range), by family of the gesture
REACTION = {"force": {"emo.fear": (1.5, 5.5), "emo.anger": (1.5, 6.0), "emo.surprise": (1.0, 5.0), "emo.anxiety": (1.0, 4.0),
                      "stress": (2.0, 6.0)},
            "care": {"emo.tenderness": (1.0, 4.0), "emo.joy": (0.5, 3.0)},
            "grasp": {"emo.surprise": (0.5, 2.5)},
            "perceive": {"emo.anxiety": (0.0, 1.5)}}
REACH_BOOST = 40.0                                # what is within reach is this much likelier to be the target
NEEDS = ("need.hunger", "need.thirst", "need.sleep", "need.exhaustion", "body.pain")
NEED_CAP = 7.5                                    # unless his body is why he wakes, no need is extreme
# why he wakes: how the mode and the urgency are drawn
WAKE_MODES = {"request": ("act", "act", "listen"), "speech": ("listen", "listen", "reflect"),
              "perception": ("act", "act", "listen"), "timer": ("act",), "plan": ("act",), "body": ("act",),
              "routine": ("act", "reflect")}
WAKE_URGENCY = {"request": (3, 8), "speech": (1, 7), "perception": (2, 9), "timer": (3, 8), "plan": (1, 6),
                "body": (3, 9), "routine": (0, 3)}
WAKE_CAUSES = {"perception": 0.30, "routine": 0.20, "body": 0.15, "speech": 0.10, "request": 0.10, "plan": 0.10,
               "timer": 0.05}


class RecordBuilder(ABC):
    @abstractmethod
    def build(self, c: BuildContext) -> None: ...


# ---------------------------------------------------------------------------------------------------- the NPC
class SelfBuilder(RecordBuilder):
    """SELF and SELF_MIND: his body, his needs, his hands, his temperament (SELF_STATE comes last)."""

    def build(self, c: BuildContext) -> None:
        me, d, sc = c.me, c.d, c.scene
        vectors = [c.pools.item_vector(k) for k in c.layout.carried]
        body, hurt = BodyModel(d).make(me.age, sc.hour, c.climate_index, sc.place.name == "tavern",
                                       sum(v.get("mass", 0.0) for v in vectors))
        self._cause(c, body)
        c.hurt = hurt or body["body.pain"] >= 2
        night = sc.hour < 5.5 or sc.hour >= 21.5
        posture = dict(POSTURE_BABY if me.age < INFANT else POSTURE)
        if night and sc.place.indoors:
            posture["lying"] = 0.3
        if body["need.sleep"] > 8:
            posture["lying"] = posture.get("lying", 0.0) + 0.2
        if sc.place.indoors:
            posture["swimming"] = posture["climbing"] = 0.0
        h = sc.hour / 24 * 2 * math.pi
        s = {"age": round(me.age, 1), "age_stage": stage_of(me.age, c.pools.enum("SELF", "age_stage")), "sex": me.sex,
             "season": sc.season, "place": "@PLACE", "posture": c.enum("SELF", "posture", posture),
             "time": {"sin": round(math.sin(h), 4), "cos": round(math.cos(h), 4),
                      "certainty": d.uniform(0.35, 0.8, 2) if sc.place.indoors else d.uniform(0.65, 1.0, 2)}}
        s.update(body)
        s["held"] = vectors[:2] if vectors and d.chance(0.6) else []         # [] = he knows his hands are empty
        if not c.hurt:
            s["wound"] = []                                                    # known: none
        c.add(Record("SELF", "me", c.fill("SELF", s)))
        c.add(Record("SELF_MIND", "me.mind", self._mind(c)))

    @staticmethod
    def _cause(c: BuildContext, body: dict) -> None:
        """If his body is why he wakes, one need is pressing; otherwise none is extreme."""
        if c.cause == "body":
            body[c.d.pick(NEEDS)] = c.d.uniform(NEED_CAP, 10.0)
        else:
            for k in NEEDS:
                body[k] = min(body[k], NEED_CAP)

    @staticmethod
    def _mind(c: BuildContext) -> dict:
        me, d = c.me, c.d
        mind = {}
        orientation = c.pools.intimate_fields.get("SELF_MIND", ())
        if me.age >= ADULT and "attracted_to" in orientation:
            mind["attracted_to"] = {"m": ["male"], "f": ["female"], "b": ["female", "male"]}[
                d.weighted({"m": 0.45, "f": 0.45, "b": 0.1})]
        for name, spec in c.filler.types["SELF_MIND"]["fields"].items():
            if name in orientation or spec["scale"] not in ("unipolar10", "bipolar10"):
                continue
            if spec["scale"] == "bipolar10":
                mind[name] = d.gauss(0, 3, -10.0, 10.0)
            else:                                                              # abilities and values: centred, a child less in control
                mind[name] = d.gauss(5.0 - (2.0 if name == "ability.self_control" and me.age < YOUNG else 0.0), 2.2)
        return mind


# ---------------------------------------------------------------------------------------------------- people
class PersonBuilder(RecordBuilder):
    """ENTITY: the persons he knows, present (seen: distance, looks) or absent (a name and feelings). What he thinks
    of them is not the truth: a person known by name only or by description is an uncertain file whose link may be
    wrong, a known one is sometimes not recognised, a stranger sometimes taken for somebody."""

    def build(self, c: BuildContext) -> None:
        for e in c.layout.entries:
            e.fields = self._entity(c, e)
            c.parties.add_person(e.key, e.person, e.fields, e.believed_age)
            c.add(Record("ENTITY", e.key, e.fields))
        for g in c.layout.ghosts:                                    # known but not filed: the governor knows nothing
            c.parties.add_person(g.key, g.person, None)
        c.refs.links = {e.key: e.fields["link"] for e in c.layout.entries}

    # ---- who he thinks this is ------------------------------------------------------------------------------
    def _alt_link(self, c: BuildContext, p: Person) -> str:
        """A believable link for a person he does not really know (never an intimate one)."""
        ok = {l: w for l, w in MISTAKEN_LINKS.items() if c.rules.fits(l, p.age, c.me.age) and l not in c.pools.intimate_links}
        return c.d.weighted(ok) if ok else "stranger"

    def _identity(self, c: BuildContext, e: Entry, known_by: str) -> tuple[str, bool, float, tuple[float, float] | None]:
        """-> (link shown, name known, id_certainty, cap on familiarity)."""
        d, p, intimate = c.d, e.person, e.link in c.pools.intimate_links
        if intimate:                                                 # a partner is never misread, never half known
            return e.link, True, d.uniform(8, 10), None
        if known_by == "name_only":
            return (e.link if d.chance(0.55) else self._alt_link(c, p)), True, d.uniform(0, 4), (0, 3.5)
        if known_by == "described":
            return ("stranger" if d.chance(0.5) else self._alt_link(c, p)), False, d.uniform(0, 3), (0, 2)
        if e.present is None:
            return e.link, True, d.uniform(5, 9), None
        if e.link != "stranger":
            if d.chance(0.06):                                       # he does not recognise a person he knows
                return "stranger", False, d.uniform(0, 4), None
            return e.link, True, d.uniform(3, 6) if d.chance(0.05) else d.uniform(6, 10), None
        if d.chance(0.07):                                           # he takes a stranger for somebody he knows
            return self._alt_link(c, p), False, d.uniform(4, 7), None
        return "stranger", False, d.uniform(4, 7) if d.chance(0.08) else d.uniform(0, 4), None

    def _entity(self, c: BuildContext, e: Entry) -> dict:
        d, me, p, x = c.d, c.me, e.person, e.present
        intimate = e.link in c.pools.intimate_links
        known_by = "seen" if (x is not None or intimate) else c.enum("ENTITY", "known_by", {"seen": 0.55, "name_only": 0.33, "described": 0.12})
        link, named, certainty, fam_cap = self._identity(c, e, known_by)
        if x is None and intimate:                                   # absent partner: he believes an adult age
            e.believed_age = float(max(ADULT + 3, round(p.age + d.rng.uniform(-1, 1))))
        f = {"link": link if link in c.pools.enum("ENTITY", "link") else "stranger", "present": x is not None,
             "known_by": known_by, "id_certainty": certainty}
        if named:
            f["name"] = p.name
        if x is not None:
            f.update(self._looks(c, e, intimate))
        rep = {k: d.uniform(-1, 1, 2) for k in ("honesty", "danger", "competence", "wealth", "piety") if d.chance(0.4)}
        f["rep"] = rep
        f.update(self._feelings(c, e, f, rep, fam_cap))
        clear = me.age >= ADULT and p.age >= ADULT and known_by == "seen" and f.get("look.age", ADULT) >= ADULT
        if not (clear and intimate and f["link"] == e.link):
            f.pop("rel.attraction", None)
        skip = tuple(n for n in c.filler.types["ENTITY"]["fields"] if n.startswith("look.")) if x is None else ()
        return c.fill("ENTITY", f, skip=skip)

    def _feelings(self, c: BuildContext, e: Entry, f: dict, rep: dict, fam_cap) -> dict:
        """What he feels, all from one latent attitude: who loves him trusts him and does not fear him."""
        d = c.d
        kind = LINK_KIND.get(f["link"], "neighbor")
        a = max(-1.0, min(1.0, d.rng.gauss(*ATTITUDE[kind])))
        lo, hi = FAMILIARITY[kind]
        if fam_cap:
            lo, hi = fam_cap
        fam = d.uniform(lo, hi)
        out = {"rel.familiarity": fam,
               "rel.affection": d.gauss(10 * a, 1.2, -10.0, 10.0),
               "rel.trust": d.gauss(6 * a + 0.1 * fam, 2.4, -10.0, 10.0),
               "rel.respect": d.gauss(4 * a + 1.5, 2.0, -10.0, 10.0),
               "rel.perceived_regard": d.gauss(5 * a, 2.0, -10.0, 10.0),
               "rel.resentment": d.clip(max(0.0, -a) * 9 + abs(d.rng.gauss(0, 0.8))),
               "rel.fear": d.clip(max(0.0, -a) * 3.5 + (2.0 if rep.get("danger", 0) > 0.3 else 0.0) + abs(d.rng.gauss(0, 0.8))),
               "rel.rivalry": d.clip(abs(d.rng.gauss(0, 1.5)) + (1.5 if kind == "enemy" else 0.0)),
               "rel.obligation": d.gauss(4 if f["link"] in OBLIGED_TO else -4 if f["link"] in OWED_BY else 0,
                                         1.5 if f["link"] in OBLIGED_TO + OWED_BY else 2.0, -10.0, 10.0)}
        if kind == "partner":
            out["rel.attraction"] = d.clip(0.6 * out["rel.affection"] + d.rng.gauss(2, 1.5))
        return out

    def _looks(self, c: BuildContext, e: Entry, intimate: bool) -> dict:
        d, x, p = c.d, e.present, e.person
        baby = p.age < INFANT
        condition = c.enum("ENTITY", "look.condition", {"active": 0.9, "hurt": 0.07, "down": 0.012, "motionless": 0.008,
                                                        "obviously_dead": 0.004})
        posture = c.enum("ENTITY", "look.posture", POSTURE_BABY if baby else POSTURE)
        if condition in ("down", "motionless", "obviously_dead"):
            posture = "prone" if d.chance(0.3) and not baby else "lying"
        moving = {"walking": {"approaching": 0.4, "leaving": 0.4, "still": 0.2}, "running": {"running": 1.0},
                  "standing": {"still": 0.88, "approaching": 0.05, "leaving": 0.07}}.get(posture, {"still": 1.0})
        motion = c.enum("ENTITY", "look.motion", moving)
        wounds = {"active": 0.0, "hurt": d.uniform(1, 6), "down": d.uniform(3, 8), "motionless": d.uniform(3, 9),
                  "obviously_dead": d.uniform(7, 10)}[condition]
        gaze_pool = ["me"] + [k for k in c.layout.here if k != e.key] + c.layout.tkeys
        gaze = "" if condition in ("down", "motionless", "obviously_dead") else d.weighted(
            {"me": max(1.0, 0.5 * len(gaze_pool))}, allowed=gaze_pool) if d.chance(0.9) else ""
        noise = 1.0 if p.age < ADULT else 4.0
        seen = max(0.5, p.age + c.rng.uniform(-noise, noise))
        return {"dist": x.dist, "dir": c.direction(x.bearing),
                "look.age": round(max(seen, ADULT + 1) if intimate else seen, 1),       # a partner looks an adult
                "look.sex": p.sex if d.chance(0.95) else "unclear", "look.posture": posture,
                "look.expression": c.enum("ENTITY", "look.expression", EXPRESSION_BABY if baby else EXPRESSION),
                "look.motion": motion, "look.condition": condition, "look.wounds": wounds, "look.gaze": gaze}


# ---------------------------------------------------------------------------------------------------- things
class ThingBuilder(RecordBuilder):
    """THING (seen) and INV (carried). An owner is BELIEVED: sure of his own things, often right about a known
    person's, right about a stranger's only if he saw him hold or use it, sometimes wrong."""

    def build(self, c: BuildContext) -> None:
        d, pools, lay = c.d, c.pools, c.layout
        for key, t in zip(lay.tkeys, lay.things):
            f = {"kind": t.kind, "dist": t.dist, "dir": c.direction(t.bearing),
                 "file_certainty": d.gauss(10.0 - 0.22 * t.dist, 1.0)}
            if t.animal:
                f.update({"display": c.enum("THING", "display", DISPLAY), "motion": c.enum("THING", "motion", ANIMAL_MOTION)})
            else:
                f.update({"props": pools.item_vector(t.kind), "amount": c.enum("THING", "amount", AMOUNT)})
                f["owner"] = self._believed_owner(c, t)
            c.add(Record("THING", key, f))
        for key, kind in zip(lay.ikeys, lay.carried):
            borrowed = lay.pkeys and d.chance(0.05)                        # a tool lent by somebody he knows
            c.add(Record("INV", key, {"kind": kind, "props": pools.item_vector(kind),
                                      "owner": d.pick(lay.pkeys) if borrowed else "me",
                                      "amount": c.enum("INV", "amount", AMOUNT)}))
        c.refs.owners = {r.key: r.fields["owner"] for r in c.of("THING") if r.fields.get("owner")}

    def _believed_owner(self, c: BuildContext, t) -> str | None:
        d = c.d
        if t.owner is not None and t.owner == c.me.pid:
            return "me" if d.chance(0.95) else None
        owner = c.layout.by_pid.get(t.owner) if t.owner is not None else None
        if owner is not None:
            f = owner.fields
            known = f["link"] != "stranger" and f["known_by"] == "seen" and "name" in f
            if known:
                p_true = min(0.95, 0.3 + 0.06 * f["id_certainty"] + (0.2 if t.seen_use else 0.0))
            elif f["known_by"] != "seen" or f["link"] != "stranger":
                p_true = 0.3 if f["known_by"] == "name_only" else 0.4
            else:
                p_true = 0.85 if t.seen_use else 0.0          # a stranger's: only if he saw him hold or use it
            if d.chance(p_true):
                return owner.key
        return self._wrong_owner(c, t.owner) if d.chance(0.35 if t.owner is not None else 0.08) else None

    @staticmethod
    def _wrong_owner(c: BuildContext, true_pid) -> str | None:
        """A plausible but wrong owner: somebody he knows, not the real one."""
        pool = [e.key for e in c.layout.entries if e.person.pid != true_pid and e.fields["link"] != "stranger"] + ["me"]
        return c.d.pick(pool)


# ---------------------------------------------------------------------------------------------------- the place
class PlaceBuilder(RecordBuilder):
    """PLACE (light, noise, air, the people PERCEIVED), LOCUS (places he knows), GROUP (groups he knows)."""

    def build(self, c: BuildContext) -> None:
        d, sc, lay = c.d, c.scene, c.layout
        day = daylight(sc.hour)
        lamps = set(c.pools.items_by_category.get("light", ()))
        lamp = any(t.kind in lamps for t in sc.things)
        if sc.place.indoors:
            light = d.gauss(1.6 + 4.0 * day + (2.5 if lamp else 0.0), 0.7)
        else:
            light = d.gauss(10 * day * d.rng.uniform(0.6, 1.0) + 0.5, 0.3)
        # crowd = the persons he PERCEIVES: those in his files, and most of the others far away (never fewer)
        filed = {e.person.pid for e in lay.entries if e.present is not None}
        seen = len(filed) + sum(1 for x in sc.present if x.person.pid not in filed and d.chance(0.65))
        noise = d.gauss(0.6 * seen + (1.5 if sc.place.indoors else 0.0) + (1.5 if sc.place.name == "tavern" else 0.0), 0.8)
        values = c.pools.enum("PLACE", "air_felt")
        c.add(Record("PLACE", "@PLACE", c.fill("PLACE", {
            "indoors": sc.place.indoors, "crowd": seen, "light": light, "noise": noise,
            "air_felt": Climate.word(values, c.climate_index)})))
        for key in lay.loci:
            owner = d.weighted({"me": 0.15, "": 0.55, "other": 0.3})
            if owner == "other":
                owner = d.pick(lay.pkeys) if lay.pkeys else ""
            c.add(Record("LOCUS", key, {"dist": d.uniform(20, 3000, 0), "dir": c.direction(d.uniform(-3.14, 3.14, 4)),
                                        "owner": owner}))
        for key in lay.groups:
            c.add(Record("GROUP", key, c.fill("GROUP", {"known_by": c.enum("GROUP", "known_by", {
                "seen": 0.6, "name_only": 0.25, "described": 0.15})})))


# ---------------------------------------------------------------------------------------------------- events
class EventBuilder(RecordBuilder):
    """EVENT: gestures he has just perceived. Actor and target are PRESENT (persons here, things in view); a gesture
    that holds or uses its target only between two within reach and on a target that fits it; what is seen follows
    the gesture's perceptibility; going, looking and listening are a third of it at most."""

    def build(self, c: BuildContext) -> None:
        lay = c.layout
        if not lay.here:
            return
        n = c.count("EVENT", 0, 4) if c.scene.long else c.d.weighted({0: 0.35, 1: 0.3, 2: 0.2, 3: 0.1, 4: 0.05})
        n = min(n, c.cap["EVENT"])
        if c.cause == "perception":
            n = max(n, 1)
        for i in range(n):
            first = i == 0 and c.cause == "perception"
            for _ in range(12 if first else 1):                        # the event that wakes him must exist
                if self._one(c, len(c.events) + 1, first):
                    break

    def _pairs(self, c: BuildContext, towards_me: bool):
        """Every (actor, target key, target class and kind, gap, weight) that could be seen. Whoever and whatever is
        within reach is much likelier: people do things with what is at hand."""
        lay = c.layout
        here = [e for e in lay.entries if e.present is not None]
        out = []
        for actor in here:
            x = actor.present
            share = 1.0 / len(here)
            cands = [("me", Target("agent"), x.dist, 0.22)]
            if not towards_me:
                others = [e for e in here if e is not actor]
                cands += [(o.key, Target("agent"), separation(x, o.present), 0.13 / len(others)) for o in others]
                cands += [(k, Target("animal" if t.animal else "item", t.kind), separation(x, t), 0.6 / len(lay.things))
                          for k, t in zip(lay.tkeys, lay.things)]
                cands.append(("", None, None, 0.05))
            for key, info, gap, w in cands:
                out.append((actor, key, info, gap, share * w * (REACH_BOOST if gap is not None and gap <= REACH else 1.0)))
        return out

    def _one(self, c: BuildContext, n: int, first: bool) -> bool:
        d = c.d
        pairs = self._pairs(c, first and d.chance(0.55))
        actor, target, info, gap, _ = c.rng.choices(pairs, weights=[p[4] for p in pairs])[0]
        pick = c.grammar.chooser.pick(d, info, c.parties.party(actor.key), c.parties.party(target) if target else None,
                                      reach_ok=gap is not None and gap <= REACH, age=actor.person.age)
        if pick is None:
            return False
        chooser = c.grammar.chooser
        senses = chooser.senses(pick.gesture)
        if target == "me" and chooser.needs_reach(pick.gesture):
            senses = senses | {"felt": 0.15}
        age = c.hours_ago(0.0005, 0.02) if first else c.hours_ago(0.03, 2.0)
        rec = Record("EVENT", f"@V{n}", {"actor": actor.key, "gesture": pick.gesture, "target": target,
                                         "sense": d.weighted(senses), "age": age, "manner": list(pick.manner)})
        c.events.append(c.add(rec))
        if target == "me":
            c.directed.append(rec)
        return True


# ---------------------------------------------------------------------------------------------------- beliefs
class BeliefBuilder(RecordBuilder):
    """BELIEF (what he holds true, from a source) and HEARD (what was just said to him, only when words wake him)."""

    @staticmethod
    def _source(c: BuildContext, can_tell: bool) -> str:
        w = dict(SOURCE)
        if c.me.age < 9:
            w["read"] = 0.0
        elif c.me.age < 14:
            w["read"] *= 0.3
        if not can_tell:
            w["told"] = w["heard"] = 0.0
        return c.d.weighted(w)

    @staticmethod
    def _certainty(c: BuildContext, source: str, contradicted: bool) -> float:
        mu, sd = CERTAINTY[source]
        v = c.d.gauss(mu, sd)
        return round(v * 0.4, 1) if contradicted else v

    def build(self, c: BuildContext) -> None:
        d, lay = c.d, c.layout
        informants = lay.pkeys + [g.key for g in lay.ghosts]
        n = 0
        for e in lay.entries:                  # the age he believes of an absent partner: the model sees it too
            if e.believed_age is not None:
                prop = c.session.validate(f"(state {e.key} age_years {int(e.believed_age)})", "belief")
                if prop is not None:
                    n += 1
                    c.said.add(prop)
                    c.add(Record("BELIEF", f"b:{n}", c.fill("BELIEF", {
                        "prop": prop, "source": "seen", "age": c.hours_ago(1, 3000), "contradicted": False, "hops": 0,
                        "certainty": d.gauss(8, 1), "informant": "", "shared": [], "polarity": True, "secret": False})))
        for _ in range(c.count("BELIEF", 3)):
            if n >= c.cap["BELIEF"]:
                break
            prop = c.session.belief()
            if prop is None or prop in c.said:
                continue
            c.said.add(prop)
            n += 1
            src = self._source(c, bool(informants))
            contradicted = d.chance(0.06)
            c.add(Record("BELIEF", f"b:{n}", c.fill("BELIEF", {
                "prop": prop, "source": src, "age": c.hours_ago(0.1, 3000), "contradicted": contradicted,
                "hops": d.between(*HOPS[src]), "certainty": self._certainty(c, src, contradicted),
                "informant": d.pick(informants) if src in ("told", "heard") else "",       # "" = nobody told him
                "shared": d.sample(lay.pkeys, d.between(0, 2))})))
        if c.cause != "speech":
            return
        k = 0
        for _ in range(c.count("HEARD", 1, 2)):                     # the words that wake him
            prop = c.session.belief()
            if prop is None or prop in c.said:
                continue
            c.said.add(prop)
            k += 1
            src = d.weighted({"told": 0.65, "heard": 0.35})
            contradicted = d.chance(0.03)
            c.add(Record("HEARD", f"h:{k}", c.fill("HEARD", {
                "prop": prop, "source": src, "hops": d.between(1, 2), "informant": d.pick(lay.here),
                "age": c.hours_ago(0.001, 0.2), "contradicted": contradicted,
                "certainty": self._certainty(c, src, contradicted),
                "shared": d.sample(lay.pkeys, 1) if d.chance(0.08) else []})))


class MemoryBuilder(RecordBuilder):
    """MEMORY: what he lived, saw or was told, with the feeling it left (from what happened and his part in it)."""

    def build(self, c: BuildContext) -> None:
        d, lay = c.d, c.layout
        actions = c.pools.cat["action"]
        colour = MemoryColour(set(c.pools.interpretations) - set(c.pools.intimate_symbols), c.pools.enum("MEMORY", "emotion"))
        k = 0
        for _ in range(c.count("MEMORY", 1)):
            got = c.session.memory()
            if got is None or got.prop in c.said:
                continue
            c.said.add(got.prop)
            k += 1
            family = actions[got.gesture].family if got.gesture else None
            emotion, valence, interp = colour(d, got, family)
            c.add(Record("MEMORY", f"m:{k}", c.fill("MEMORY", {
                "prop": got.prop, "age": got.age, "emotion": emotion, "valence": valence, "role": got.role,
                "vividness": d.gauss(9.0 - 0.75 * math.log(got.age), 1.2), "interp": interp,
                "place": d.pick(lay.loci + ["@PLACE"]) if d.chance(0.7) else None})))


class SocialBuilder(RecordBuilder):
    """REQUEST (a request just heard: only when it wakes him) and COMMIT (what he owes or is owed)."""

    def build(self, c: BuildContext) -> None:
        d, lay = c.d, c.layout
        if c.cause == "request" and lay.here:
            for _ in range(c.count("REQUEST", 1, 2)):
                asker = d.pick(lay.here)
                prop = c.session.request(asker)
                if prop is not None:
                    c.add(Record("REQUEST", f"q:{len(c.of('REQUEST')) + 1}",
                                 {"from": asker, "prop": prop, "age": c.hours_ago(0.001, 2)}))
            if not c.of("REQUEST"):                          # the request that wakes him must exist
                asker = d.pick(lay.here)
                c.add(Record("REQUEST", "q:1", {"from": asker, "age": c.hours_ago(0.001, 2), "prop": c.session.validate(
                    f"(request (did me give {c.session.kind(gift=True)} (to {asker})))", "request")
                    or f"(ask (at {asker} where))"}))
        if c.me.age < 12 or not lay.pkeys:
            return
        for _ in range(c.count("COMMIT", 0, 2)):
            who = d.pick(lay.pkeys)
            mine = d.chance(0.5)
            prop = c.session.validate(f"(did {'me' if mine else who} give {c.session.kind(gift=True)} (to {who if mine else 'me'}))", "belief")
            if prop is not None:
                c.add(Record("COMMIT", f"c:{len(c.of('COMMIT')) + 1}", {
                    "counterparty": who, "mine": mine, "prop": prop, "deadline": c.until(1, 300),
                    "status": c.enum("COMMIT", "status", COMMIT_STATUS), "witnesses": d.sample(lay.pkeys, d.between(0, 2))}))


class GoalBuilder(RecordBuilder):
    """GOAL (what he wants) and PLAN (the step he is on, consistent with the goal)."""

    def build(self, c: BuildContext) -> None:
        d = c.d
        beliefs = [r.key for r in c.of("BELIEF")]
        memories = [r.key for r in c.of("MEMORY")]
        asked = [r.key for r in c.of("REQUEST")]
        deals = [r.key for r in c.of("COMMIT")]
        k = 0
        for _ in range(c.count("GOAL", 1)):
            got = c.session.goal()
            if got is None or got[0] in c.said:
                continue
            prop, mode = got
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
        goals = c.of("GOAL")
        if c.cause == "timer":                                      # a deadline that has passed is why he wakes
            if not goals:
                goals = [self._need_goal(c, 0)]
            late = d.pick(goals)
            late.fields["deadline"] = -c.hours_ago(0.05, 60)
            late.fields["status"] = "active"
        if goals and (c.cause == "plan" or d.chance(0.6)):
            self._plan(c, c.cause == "plan")

    @staticmethod
    def _need_goal(c: BuildContext, k: int) -> Record:
        text = c.session.need_goal(c.d.pick(("exhaustion", "pain"))) or "(state me exhaustion low)"
        goals = c.of("GOAL")
        if len(goals) >= c.cap["GOAL"]:                              # no room: the need takes the place of the last goal
            goals[-1].fields.update(prop=text, mode="achieve", status="active", deadline=None)
            return goals[-1]
        return c.add(Record("GOAL", f"g:{k + 1}", c.fill("GOAL", {
            "prop": text, "mode": "achieve", "status": "active", "origin": "self", "origin_ref": "",
            "age": c.hours_ago(0.1, 50), "progress": c.d.uniform(0, 0.5, 2)})))

    def _plan(self, c: BuildContext, required: bool) -> None:
        table = PlanTable(c.pools, c.grammar.chooser)
        view = c.scene_view()
        goals = list(c.of("GOAL"))
        c.rng.shuffle(goals)
        for attempt in range(2 if required else 1):
            for g in goals:
                got = table.make(c.d, g.fields["prop"], view, c.parties)
                if got is not None:
                    c.add(Record("PLAN", "p:1", c.fill("PLAN", {"step": got.step, "next": got.next, "goal": g.key,
                                                                "target": got.target})))
                    return
            if required and attempt == 0:                           # no goal can be served: he has a need to serve
                goals = [self._need_goal(c, len(c.of("GOAL")))]


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
            c.add(Record("SKILL", f"k:{i + 1}", {"technique": t, "self_estimate": d.gauss(2.5 + min(me.age, 40) * 0.1, 2.2)}))
        words = c.grammar.kinds + [w for w in c.grammar.words["quality"] if me.age >= ADULT or w not in ("w_beautiful", "w_ugly")]
        for i in range(c.count("TASTE", 0)):
            c.add(Record("TASTE", f"t:{i + 1}", {"concept": d.pick(words), "attitude": d.gauss(0, 5, -10.0, 10.0)}))


# ---------------------------------------------------------------------------------------------------- state and wake
class StateBuilder(RecordBuilder):
    """SELF_STATE: what he attends to, his drives and feelings, raised by what is done to him."""

    def build(self, c: BuildContext) -> None:
        d, me = c.d, c.me
        intimate = c.pools.intimate_fields.get("SELF_STATE", ())
        s = {}
        for name, spec in c.filler.types["SELF_STATE"]["fields"].items():
            if name == "attention" or name in intimate or spec["scale"] not in ("unipolar10", "bipolar10"):
                continue
            s[name] = d.clip(abs(d.rng.gauss(0, 1.6))) if name.startswith("emo.") else c.filler.prior.sample(spec)
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
        if me.age >= ADULT and "drive.intimacy" in intimate:
            drive = d.clip(abs(d.rng.gauss(0, 2.5)))
            if attention and attention.startswith("@E") and c.parties.may_be_minor(attention):
                drive = min(drive, d.uniform(0, 2))                          # D10: attention on a possible minor
            s["drive.intimacy"] = drive
        c.add(Record("SELF_STATE", "me.state", s))


class WakeBuilder(RecordBuilder):
    """WAKE: why he decides now (the cause was drawn first; the other builders made the situation that justifies it).
    The trigger is the record that woke him (@V, h:, q:, g:, p:); a body or a routine has none ("" = known: nobody)."""

    def build(self, c: BuildContext) -> None:
        r = c.rng
        key = lambda typ: (c.records.first(typ).key if c.records.first(typ) else "")  # noqa: E731
        late = [x.key for x in c.of("GOAL") if (x.fields.get("deadline") or 0) < 0]
        triggers = {"request": key("REQUEST"), "speech": key("HEARD"),
                    "perception": min(c.events, key=lambda e: e.fields["age"]).key if c.events else "",
                    "timer": late[0] if late else "", "plan": key("PLAN"), "body": "", "routine": ""}
        cause = c.cause
        if cause not in ("body", "routine") and not triggers[cause]:    # the situation could not justify it
            cause = "routine"
        lo, hi = WAKE_URGENCY[cause]
        c.add(Record("WAKE", "wake", {"mode": r.choice(WAKE_MODES[cause]), "cause": cause, "trigger": triggers[cause],
                                      "urgency": round(r.uniform(lo, hi), 1)}))
