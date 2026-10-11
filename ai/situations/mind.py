"""mind.py - the NPC's mind in a scene: the records tok-2 reads (what he perceives, believes, remembers, wants).

Built from the TRUE scene with noise and ignorance: apparent ages are guessed, owners are believed, absent people
are remembered. A numeric field the scene says nothing about gets a plausible value drawn from its scale only
(NumericPrior): no meaning is invented. D10: intimate fields (attraction, drive for intimacy, sexual orientation)
exist only for an adult NPC, toward a person who is an adult by truth, appearance and belief.
"""
from __future__ import annotations

import math
import random

from tok2 import Record

from .pools import Pools
from .propositions import PropositionFactory, Refs
from .scene import ADULT, INTIMATE_LINKS, Person, Scene

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


class NumericPrior:
    """A plausible value from the scale alone: most feelings and needs are low, attitudes centred."""

    def __init__(self, rng: random.Random):
        self.rng = rng

    def sample(self, spec: dict):
        r, scale = self.rng, spec["scale"]
        if scale == "bipolar10":
            return round(max(-10.0, min(10.0, r.gauss(0, 3))), 1)
        if scale == "unipolar10":
            return round(min(10.0, abs(r.gauss(0, 2.5))), 1)
        if scale == "ratio":
            return round(r.random(), 2)
        if scale == "bool":
            return r.random() < 0.2
        return None                                 # qty, time, vectors: the builder decides or leaves unknown


class MindBuilder:
    def __init__(self, rng: random.Random, pools: Pools, props: PropositionFactory):
        self.rng, self.pools, self.props = rng, pools, props
        self.prior = NumericPrior(rng)
        self.types = pools.interface.token_types

    # ---- helpers ------------------------------------------------------------------------------------
    def _fill(self, typ: str, fields: dict, skip: tuple = ()) -> dict:
        """Complete the scalar fields the scene said nothing about with the prior."""
        for name, spec in self.types[typ]["fields"].items():
            if name in fields or name in skip or name in INTIMATE_FIELDS.get(typ, ()) or spec.get("components"):
                continue
            v = self.prior.sample(spec)
            if v is not None:
                fields[name] = v
        return fields

    def _enum(self, typ: str, field: str) -> str:
        return self.rng.choice(self.pools.enum(typ, field))

    def _dir(self, bearing: float) -> dict:
        return {"sin": round(math.sin(bearing), 4), "cos": round(math.cos(bearing), 4)}

    def _hours_ago(self, lo: float, hi: float) -> float:
        return round(math.exp(self.rng.uniform(math.log(lo), math.log(hi))), 3)

    @staticmethod
    def stage(age: float, values: list[str]) -> str:
        want = "infant" if age < 3 else "child" if age < 14 else "teen" if age < ADULT else "adult" if age < 60 else "elder"
        return want if want in values else values[-1]

    def _seen_age(self, p: Person, intimate_link: bool) -> float:
        noise = 1.0 if p.age < ADULT else 4.0
        seen = max(0.5, p.age + self.rng.uniform(-noise, noise))
        return round(max(seen, ADULT + 1) if intimate_link else seen, 1)    # a partner is known to be an adult

    # ---- the NPC himself ----------------------------------------------------------------------------
    def _self(self, sc: Scene, carried_vectors: list[dict]) -> list[Record]:
        me, r = sc.self_, self.rng
        adult = me.age >= ADULT
        h = sc.hour / 24 * 2 * math.pi
        s = {"age": round(me.age, 1), "age_stage": self.stage(me.age, self.pools.enum("SELF", "age_stage")),
             "sex": me.sex, "season": sc.season, "place": "@PLACE",
             "posture": r.choice(["standing", "walking", "sitting"]),
             "time": {"sin": round(math.sin(h), 4), "cos": round(math.cos(h), 4),
                      "certainty": 0.5 if sc.place.indoors else 0.9},
             "body.consciousness": 10.0, "body.breath": round(r.uniform(8, 10), 1), "body.bleeding": 0.0,
             "body.pain": round(min(10.0, abs(r.gauss(0, 1.5))), 1), "body.load": round(r.uniform(0, 0.5), 2),
             "body.mobility": 1.0, "body.manipulation": 1.0}
        if carried_vectors:
            s["held"] = carried_vectors[:2]
        mind = {}
        if adult:
            mind["attracted_to"] = r.choice([["male"], ["female"], ["female", "male"]])
        state = {"attention": None}
        if adult:
            state["drive.intimacy"] = round(min(10.0, abs(r.gauss(0, 2.5))), 1)
        return [Record("SELF", "me", self._fill("SELF", s)), Record("SELF_MIND", "me.mind", self._fill("SELF_MIND", mind)),
                Record("SELF_STATE", "me.state", self._fill("SELF_STATE", state))]

    # ---- people -------------------------------------------------------------------------------------
    def _person(self, key: str, sc: Scene, p: Person, link: str, present, keys: list[str]) -> Record:
        r, me = self.rng, sc.self_
        intimate = link in INTIMATE_LINKS
        f = {"link": link if link in self.pools.enum("ENTITY", "link") else "stranger",
             "present": present is not None,
             "known_by": "seen" if present is not None else r.choice(["seen", "name_only"]),
             "id_certainty": round(r.uniform(6, 10), 1) if link != "stranger" else round(r.uniform(0, 4), 1)}
        if link != "stranger":
            f["name"] = p.name
        if present is not None:
            f.update({"dist": present.dist, "dir": self._dir(present.bearing), "look.age": self._seen_age(p, intimate),
                      "look.sex": p.sex if r.random() < 0.95 else "unclear",
                      "look.posture": self._enum("ENTITY", "look.posture"),
                      "look.expression": self._enum("ENTITY", "look.expression"),
                      "look.motion": self._enum("ENTITY", "look.motion"),
                      "look.condition": "active", "look.wounds": 0.0,
                      "look.gaze": r.choice(["me"] + keys)})
        prof = LINK_PROFILE[LINK_KIND.get(link, "neighbor")]
        for field_, (lo, hi) in prof.items():
            f[field_] = round(r.uniform(lo, hi), 1)
        clear_adult = me.age >= ADULT and p.age >= ADULT and f.get("look.age", ADULT) >= ADULT
        if not (clear_adult and intimate):
            f.pop("rel.attraction", None)
        f["rep"] = {c: round(r.uniform(-1, 1), 2) for c in ("honesty", "danger", "competence", "wealth", "piety")
                    if r.random() < 0.4}
        skip = tuple(n for n in self.types["ENTITY"]["fields"] if n.startswith("look.")) if present is None else ()
        return Record("ENTITY", key, self._fill("ENTITY", f, skip=skip))

    # ---- the whole mind -----------------------------------------------------------------------------
    def build(self, sc: Scene) -> list[Record]:
        r, P = self.rng, self.props
        T = {t: spec["count"] for t, spec in self.types.items()}
        people = [(x.person, x.link, x) for x in sc.present if x.known or x.dist < 15] + [(p, l, None) for p, l in sc.absent]
        people = people[:T["ENTITY"]]
        pkeys = [f"@E{i + 1}" for i in range(len(people))]
        self.people = {k: p for k, (p, _, _) in zip(pkeys, people)}       # truth, for the D10 audit only
        things = sc.things[:T["THING"]]
        tkeys = [f"@T{i + 1}" for i in range(len(things))]
        carried = sc.carried[:T["INV"]]
        ikeys = [f"@T{len(things) + i + 1}" for i in range(len(carried))]
        loci = [f"@L{i + 1}" for i in range(r.randint(0, T["LOCUS"]))]
        groups = [f"@G{i + 1}" for i in range(r.randint(0, T["GROUP"]))]
        refs = Refs(pkeys, tkeys + ikeys, loci, groups, [k for k, (_, _, x) in zip(pkeys, people) if x is None])
        owner_key = {p.pid: k for (p, _, _), k in zip(people, pkeys)} | {sc.self_.pid: "me"}

        out: list[Record] = []
        carried_vectors = [self.pools.item_vector(k) for k in carried[:2]]
        out += self._self(sc, carried_vectors)
        out[2].fields["attention"] = r.choice(pkeys + tkeys) if pkeys + tkeys else None
        for key, (p, link, present) in zip(pkeys, people):
            out.append(self._person(key, sc, p, link, present, [k for k in pkeys if k != key] + tkeys))
        for key, t in zip(tkeys, things):
            f = {"kind": t.kind, "dist": t.dist, "dir": self._dir(t.bearing), "file_certainty": round(r.uniform(5, 10), 1)}
            if t.animal:
                f.update({"display": self._enum("THING", "display"), "motion": self._enum("THING", "motion")})
            else:
                f.update({"props": self.pools.item_vector(t.kind), "amount": self._enum("THING", "amount")})
                believed = owner_key.get(t.owner) if t.owner is not None and r.random() < 0.8 else None
                f["owner"] = believed
            out.append(Record("THING", key, f))
        for key, kind in zip(ikeys, carried):
            out.append(Record("INV", key, {"kind": kind, "props": self.pools.item_vector(kind), "owner": "me",
                                           "amount": self._enum("INV", "amount")}))
        out.append(Record("PLACE", "@PLACE", self._fill("PLACE", {
            "indoors": sc.place.indoors, "crowd": len(sc.present),
            "light": round(5.0 if sc.place.indoors else max(0.0, 10 * math.sin(math.pi * (sc.hour - 6) / 12)), 1),
            "air_felt": self._enum("PLACE", "air_felt")})))
        for key in loci:
            out.append(Record("LOCUS", key, {"dist": round(r.uniform(20, 3000), 0), "dir": self._dir(r.uniform(-3.14, 3.14)),
                                             "owner": r.choice(["me", None] + pkeys)}))
        for key in groups:
            out.append(Record("GROUP", key, self._fill("GROUP", {"known_by": "seen"})))
        bkeys = []
        for i in range(r.randint(3, T["BELIEF"])):
            prop = P.belief(refs)
            if prop is None:
                continue
            key = f"b:{i + 1}"
            bkeys.append(key)
            src = self._enum("BELIEF", "source")
            out.append(Record("BELIEF", key, self._fill("BELIEF", {
                "prop": prop, "source": src, "age": self._hours_ago(0.1, 3000), "contradicted": False,
                "hops": 0 if src == "seen" else r.randint(1, 4),
                "informant": r.choice(pkeys) if src in ("told", "heard") and pkeys else None,
                "shared": r.sample(pkeys, min(len(pkeys), r.randint(0, 2)))})))
        present_keys = [k for k, (_, _, x) in zip(pkeys, people) if x is not None]
        for i in range(r.randint(0, T["HEARD"]) if present_keys else 0):
            prop = P.belief(refs)
            if prop is not None:
                out.append(Record("HEARD", f"h:{i + 1}", self._fill("HEARD", {
                    "prop": prop, "source": "told", "hops": 1, "informant": r.choice(present_keys),
                    "age": self._hours_ago(0.001, 0.2), "contradicted": False, "shared": []})))
        mkeys = []
        for i in range(r.randint(1, T["MEMORY"])):
            prop = P.memory(refs)
            if prop is None:
                continue
            key = f"m:{i + 1}"
            mkeys.append(key)
            interp = [x for x in self.pools.interpretations if x not in self.pools.intimate_symbols]
            out.append(Record("MEMORY", key, self._fill("MEMORY", {
                "prop": prop, "age": self._hours_ago(1, 5000), "emotion": self._enum("MEMORY", "emotion"),
                "interp": r.choice(interp) if r.random() < 0.4 else None, "role": self._enum("MEMORY", "role"),
                "place": r.choice(loci + ["@PLACE", None])})))
        gkeys = []
        for i in range(r.randint(1, T["GOAL"])):
            prop = P.goal(refs)
            if prop is None:
                continue
            key = f"g:{i + 1}"
            gkeys.append(key)
            out.append(Record("GOAL", key, self._fill("GOAL", {
                "prop": prop, "mode": "achieve", "status": "active", "origin": self._enum("GOAL", "origin"),
                "origin_ref": r.choice(bkeys + mkeys + [None]), "age": self._hours_ago(0.1, 500),
                "deadline": self._hours_ago(1, 500) if r.random() < 0.4 else None})))
        if gkeys and r.random() < 0.6:
            steps = [g for fam, gs in self.pools.gestures.items() if fam != "communicate" for g in gs]
            out.append(Record("PLAN", "p:1", self._fill("PLAN", {"step": r.choice(steps), "goal": r.choice(gkeys)})))
        for i in range(r.randint(0, T["REQUEST"]) if present_keys else 0):
            asker = r.choice(present_keys)
            prop = P.request(refs, asker)
            if prop is not None:
                out.append(Record("REQUEST", f"q:{i + 1}", {"from": asker, "prop": prop, "age": self._hours_ago(0.001, 2)}))
        for i in range(r.randint(0, T["COMMIT"]) if pkeys else 0):
            who = r.choice(pkeys)
            kind = r.choice(self.props.kinds)
            mine = r.random() < 0.5
            prop = f"(did {'me' if mine else who} give {kind} (to {who if mine else 'me'}))"
            if P._ok(prop) is not None:
                out.append(Record("COMMIT", f"c:{i + 1}", {
                    "counterparty": who, "mine": mine, "prop": prop, "deadline": self._hours_ago(1, 300),
                    "status": "open", "witnesses": r.sample(pkeys, min(len(pkeys), r.randint(0, 2)))}))
        techs = self.pools.enum("SKILL", "technique")
        for i, t in enumerate(r.sample(techs, r.randint(0, min(T["SKILL"], len(techs))))):
            out.append(Record("SKILL", f"k:{i + 1}", {"technique": t, "self_estimate": round(r.uniform(0, 10), 1)}))
        tastes = self.props.kinds + self.props.words["quality"]
        for i in range(r.randint(0, T["TASTE"])):
            out.append(Record("TASTE", f"t:{i + 1}", {"concept": r.choice(tastes), "attitude": round(r.uniform(-10, 10), 1)}))
        eid = 0
        for key, (p, _, x) in zip(pkeys, people):
            if x is None or eid >= T["EVENT"] or r.random() < 0.5:
                continue
            target = r.choice(["me"] + tkeys + [k for k in pkeys if k != key])
            kind = "item" if target.startswith("@T") else "agent"
            g = r.choice(self.props.gestures_for.get(kind) or self.props.gestures)
            a = self.pools.cat["action"][g]
            # what is seen of the manner: at most one value per parameter, of at most two parameters
            manners = []
            for prm in r.sample([p for p in a.params if p.type == "enum"], min(2, sum(p.type == "enum" for p in a.params))):
                vals = [v for v in prm.values if v not in self.pools.intimate_symbols]
                if vals and r.random() < 0.7:
                    manners.append(r.choice(vals))
            eid += 1
            out.append(Record("EVENT", f"@V{eid}", {
                "actor": key, "gesture": g, "target": target,
                "sense": "seen", "age": self._hours_ago(0.0005, 0.05),
                "manner": manners}))
        return out
