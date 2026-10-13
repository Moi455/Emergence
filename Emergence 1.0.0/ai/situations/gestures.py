"""gestures.py - which gesture an event or a told deed is made of, and with what manner.

Only what the catalogue allows, and what a person could really do:
  * the target is accepted by the gesture's first pointer AND fits its affordance (eaten: edible; drunk: drinkable;
    read: something written; thrown: throwable; worn: wearable; mounted: a mount...), see `Affordances`;
  * a gesture that holds or uses its target needs the two to be within reach (the object is in the hands, or within
    2 m); looking, listening and going do not;
  * each gesture has a frequency of its own (going, looking, taking and working are common, force is rare), a young
    child rarely strikes, throws or works, a baby only does what a baby does;
  * what is SEEN of it follows the gesture's own `perceptibility` (seen, heard, or both);
  * D10 is asked of the GOVERNOR (check_gesture with the parties of the scene): a gesture it refuses is never
    offered. With a person who may be a minor, a contact gesture carries exactly the manner values of its
    minor_whitelist, drawn toward hands, arms and shoulders.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from governor import Party

from .draw import Draw
from .pools import Pools

REACH = 2.0                                     # metres: a gesture that holds or uses its target needs this
YOUNG = 8.0                                     # years: below, the child strikes, throws and works rarely
INFANT = 3.0                                    # years: below, a baby looks, listens, sleeps, feeds and sits up
MOUNTS = ("horse", "donkey", "camel", "ox")     # domestic species one can ride (no `mountable` flag on species yet)

# how common each gesture is among the things people do in sight (no family weights: going and looking are not
# everything people do)
BASE_WEIGHT = {
    "go": 0.45, "look": 0.35, "listen": 0.2, "examine": 0.5, "search": 0.3, "read": 1.0,
    "take": 1.6, "put": 1.0, "give": 0.3, "throw": 0.4, "pour": 0.4, "wear": 0.4, "operate": 1.5,
    "strike": 0.03, "push": 0.025, "pull": 0.025, "grab": 0.02, "guard": 0.01,
    "scoop": 1.0, "work": 2.5, "tie": 1.0, "blow": 0.4, "shape": 1.0, "channel": 0.1,
    "eat": 3.0, "drink": 3.0, "sleep": 0.3, "rest": 0.4, "touch": 0.12,
    "speak": 0.2, "set_posture": 0.8, "mount": 0.15, "climb": 0.2, "jump": 0.2, "swim": 0.1, "wait": 0.3, "stop": 0.2,
}
YOUNG_FACTOR_FAMILY = {"tool": 0.05, "transform": 0.05, "force": 0.15}
YOUNG_FACTOR_GESTURE = {"throw": 0.15}
INFANT_GESTURES = ("look", "listen", "sleep", "rest", "set_posture", "eat", "drink")
SOCIAL_GESTURES = ("speak",)                    # said aloud: only in events (a person speaking within sight), never in a told deed
EARSHOT = 10.0                                  # metres: a speaker he can hear
# what a body can do in each posture (a person lying down does not walk away)
LYING_OK = ("look", "listen", "rest", "sleep", "set_posture", "eat", "drink", "wait", "stop")
MOBILE = ("go", "climb", "jump", "swim", "mount")
POSTURE_ALLOWED = {"lying": LYING_OK, "prone": LYING_OK, "swimming": ("swim", "look", "listen", "set_posture", "go"),
                   "climbing": ("climb", "look", "listen", "set_posture", "go")}
POSTURE_BLOCKED = {"sitting": MOBILE + ("strike", "push", "pull", "grab"), "kneeling": MOBILE, "crouching": ("jump", "swim", "mount")}
BODY_PARTS = frozenset(("head", "torso", "arms", "legs", "shoulder", "back", "hands", "hand", "arm", "collar", "hair"))
AGENT_FACTOR = {"take": 0.2, "put": 0.2, "wear": 0.3, "examine": 0.5, "go": 0.5, "look": 0.6, "listen": 0.6, "touch": 1.0}     # these are mostly done to things
# reaching a person or a thing: these need the two to be close
NEEDS_REACH_FAMILIES = ("grasp", "force", "tool", "transform", "consume", "care")
NEEDS_REACH = ("read", "mount", "climb", "write", "search", "examine", "sleep", "operate")
NO_REACH = ("guard",)
# item categories that make a target fit a gesture when the perceptible vector does not say it
CATEGORIES = {
    "read": ("writing",), "write": ("writing",),
    "wear": ("clothing", "headwear", "footwear", "armor", "jewel"),
    "operate": ("security", "fire", "pottery", "vehicle", "husbandry", "mining", "glass"),
    "scoop": ("grain", "seed", "produce", "raw_mineral", "raw_stone", "preserve"),
    "work": ("raw_wood", "raw_stone", "metal_stock", "leather", "fiber", "building", "pottery", "farming"),
    "tie": ("binding", "fiber", "vehicle", "container", "raw_wood"),
    "blow": ("fire", "glass"), "shape": ("raw_wood", "raw_stone", "metal_stock", "pottery", "fiber", "leather"),
    "channel": ("magic_stock", "magic_tool"), "sleep": ("textile", "furniture"),
}
# the gestures only done to things (not to persons or animals)
ONLY_ITEMS = ("eat", "drink", "read", "write", "wear", "operate", "scoop", "work", "shape", "channel", "blow", "pour",
              "throw", "sleep")
ZONE_WEIGHT = {"hands": 3.0, "hand": 3.0, "arms": 2.5, "arm": 2.5, "shoulder": 2.5, "back": 0.8, "head": 0.6,
               "legs": 0.3, "collar": 0.3, "hair": 0.3}              # an adult touching a child: hands, arms, shoulder


@dataclass(frozen=True)
class Target:
    """What a gesture is done to: its class (agent, animal, item, place) and, for a thing, its kind."""
    cls: str
    kind: str | None = None
    tags: frozenset = frozenset()               # "carried": a baby or a hurt person who can be lifted and put down


@dataclass(frozen=True)
class Choice:
    gesture: str
    manner: tuple[str, ...] = ()
    params: dict = field(default_factory=dict, compare=False)


class Affordances:
    """Whether a target can be the target of a gesture."""

    def __init__(self, pools: Pools):
        self.pools = pools
        self.actions = pools.cat["action"]
        self.first_ref = {g: next((p.name for p in a.params if p.type == "ref"), None) for g, a in self.actions.items()}
        # the catalogue's own requirement on the target (graspable, throwable, contains...)
        self.requires = {g: a.requires.get(self.first_ref[g]) for g, a in self.actions.items()}

    def ok(self, g: str, t: Target) -> bool:
        if t.cls == "agent":
            if g in ("take", "put"):                                    # a person is lifted only to be carried
                return "carried" in t.tags
            return g not in ONLY_ITEMS and g != "tie"
        if t.cls == "animal":
            return t.kind in MOUNTS if g == "mount" else g not in ONLY_ITEMS and g != "take"
        if t.cls != "item":
            return g not in ONLY_ITEMS
        kind, pools = t.kind, self.pools
        need = self.requires[g]
        if need and kind and not pools.item_has(kind, need):
            return False
        if g == "eat":
            return pools.item_has(kind, "edible")
        if g == "drink":
            return pools.item_has(kind, "drinkable")
        if g in CATEGORIES:
            return pools.category_of.get(kind) in CATEGORIES[g]
        if g in ("mount", "guard", "grab", "touch"):
            return False
        return True


class GestureChooser:
    ATTEMPTS = 14

    def __init__(self, pools: Pools):
        self.pools, self.gov = pools, pools.governor
        self.actions = pools.cat["action"]
        self.affordances = Affordances(pools)
        # class of target -> gestures whose first pointer accepts it; targetless ones apart
        self.by_class: dict[str, list[str]] = {}
        self.targetless: list[str] = []
        self.social: dict[str, list[str]] = {}
        for fam, ids in pools.gestures.items():
            for g in ids:
                if fam == "communicate":
                    ref = next((p for p in self.actions[g].params if p.type == "ref"), None)
                    for cls in (ref.accepts if (ref and g in SOCIAL_GESTURES) else []):
                        self.social.setdefault(cls, []).append(g)
                    continue
                ref = next((p for p in self.actions[g].params if p.type == "ref"), None)
                if ref is None:
                    self.targetless.append(g)
                for cls in (ref.accepts if ref else []):
                    self.by_class.setdefault(cls, []).append(g)

    # ---- what a gesture asks of the scene -------------------------------------------------------------------
    def needs_reach(self, g: str) -> bool:
        a = self.actions[g]
        return g not in NO_REACH and (a.contact or a.family in NEEDS_REACH_FAMILIES or g in NEEDS_REACH)

    def senses(self, g: str) -> dict[str, float]:
        """What is perceived of a gesture, from its `perceptibility` text (seen, heard, or both: the first named is
        the more likely)."""
        text = self.actions[g].perceptibility
        found = sorted((text.find(w), s) for w, s in (("vu", "seen"), ("entendu", "heard")) if w in text)
        if len(found) == 2:
            return {found[0][1]: 0.72, found[1][1]: 0.28}
        return {found[0][1]: 1.0} if found else {"seen": 1.0}

    # ---- the choice ---------------------------------------------------------------------------------------
    def pick(self, d: Draw, target: Target | None, actor: Party, target_party: Party | None, reach_ok: bool = True,
             age: float = 30.0, with_manner: bool = True, posture: str = "standing", social: bool = False,
             earshot: bool = True, only: tuple[str, ...] | None = None, exclude: tuple[str, ...] = ()) -> Choice | None:
        """A gesture (and the manner seen) done by `actor` (of this age, in this posture) to the target that the
        governor allows; None when nothing fits. with_manner=False: a bare gesture (a plan step has no manner);
        social=True: a person may also speak (an event, not a told deed); earshot: the actor is within hearing;
        only / exclude: restrict the gestures."""
        pool = self.targetless if target is None else self.by_class.get(target.cls, [])
        if social and target is not None and earshot:
            pool = pool + self.social.get(target.cls, [])
        if only is not None:
            pool = [g for g in pool if g in only]
        if exclude:
            pool = [g for g in pool if g not in exclude]
        for attempt in range(self.ATTEMPTS):
            reach = reach_ok and attempt < self.ATTEMPTS - 3                 # the last attempts renounce reaching
            g = self._draw(d, pool, target, reach, age, posture)
            if g is None:
                continue
            a = self.actions[g]
            person = target is not None and target.cls == "agent"
            restricted = person and (actor.may_be_minor() or bool(target_party is not None and target_party.may_be_minor()))
            body = target is not None and target.cls in ("agent", "animal")
            manner = self._manners(d, a, restricted, body) if with_manner else []
            params = dict(manner)
            ref = self.affordances.first_ref[g]
            parties = {ref: target_party} if ref is not None and target_party is not None else {}
            if self.gov.check_gesture(g, params, actor, parties).allowed:
                return Choice(g, tuple(v for _, v in manner), params)
        return None

    def permits(self, g: str, target: Target | None, actor: Party, target_party: Party | None) -> bool:
        """Can this bare gesture (no manner) be done to this target by this actor? Used for plan steps."""
        a = self.actions.get(g)
        if a is None:
            return False
        ref = next((p for p in a.params if p.type == "ref"), None)
        if target is not None and ref is not None and (target.cls not in ref.accepts or not self.affordances.ok(g, target)):
            return False
        parties = {ref.name: target_party} if ref is not None and target_party is not None else {}
        return self.gov.check_gesture(g, {}, actor, parties).allowed

    def _draw(self, d: Draw, pool: list[str], target: Target | None, reach: bool, age: float, posture: str) -> str | None:
        cands = [g for g in pool if (reach or not self.needs_reach(g)) and (target is None or self.affordances.ok(g, target))]
        if posture in POSTURE_ALLOWED:
            cands = [g for g in cands if g in POSTURE_ALLOWED[posture]]
        cands = [g for g in cands if g not in POSTURE_BLOCKED.get(posture, ())]
        if age < INFANT:
            cands = [g for g in cands if g in INFANT_GESTURES]
        weights = {}
        for g in cands:
            w = BASE_WEIGHT.get(g, 0.3)
            if age < YOUNG:
                w *= YOUNG_FACTOR_FAMILY.get(self.actions[g].family, 1.0) * YOUNG_FACTOR_GESTURE.get(g, 1.0)
            if target is not None and target.cls == "agent":
                w *= AGENT_FACTOR.get(g, 1.0)
            weights[g] = w
        return d.weighted(weights, allowed=cands) if cands else None

    @staticmethod
    def is_zone(p) -> bool:
        """A parameter that names a part of the body (contact_zone, zone, hold_zone…)."""
        return p.type == "enum" and len(BODY_PARTS & set(p.values)) >= 3

    def _manners(self, d: Draw, a, restricted: bool, body: bool = True) -> list[tuple[str, str]]:
        """(parameter, value) pairs as far as they are SEEN: at most one value per parameter, of at most two
        parameters. Never an intimate value; with a possible minor, a contact gesture shows its whitelisted values.
        A part of the body is only named when the target has a body (a person, an animal), not a thing."""
        enums = [p for p in a.params if p.type == "enum" and (body or not self.is_zone(p))]
        clean = lambda p: [v for v in p.values if v not in p.intimate_values]  # noqa: E731
        if restricted and a.contact and a.minor_whitelist:
            out = []
            for pn, allowed in a.minor_whitelist.items():
                p = next((x for x in enums if x.name == pn), None)
                vals = [v for v in (allowed if p is None else clean(p)) if p is None or v in allowed]
                if vals:
                    out.append((pn, d.weighted(ZONE_WEIGHT, allowed=vals)))
            return out
        out = []
        for p in d.sample(enums, 2):
            vals = clean(p)
            if vals and d.chance(0.7):
                out.append((p.name, d.pick(vals)))
        return out
