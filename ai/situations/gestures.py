"""gestures.py - which gesture an event or a told deed is made of, and with what manner.

Only what the catalogue allows: targets must be accepted by the gesture's first pointer, contact gestures need the
people to be within reach, families have a realistic frequency (looking, moving and taking are common, force is
rare), a young child rarely strikes or throws or works, and D10 is asked of the GOVERNOR (check_gesture with the
parties of the scene): a gesture it refuses is never offered. With a person who may be a minor, a contact gesture
carries exactly the manner values of its minor_whitelist.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from governor import Party

from .draw import Draw
from .pools import Pools

REACH = 2.0                                     # metres: a contact gesture needs the two to be this close
YOUNG = 8.0                                     # years: below, the child strikes, throws and works rarely


@dataclass(frozen=True)
class Choice:
    gesture: str
    manner: tuple[str, ...] = ()
    params: dict = field(default_factory=dict, compare=False)


class GestureChooser:
    FAMILY_WEIGHT = {"perceive": 5.0, "move": 5.0, "grasp": 4.0, "posture": 1.2, "consume": 1.8, "tool": 1.5,
                     "transform": 0.6, "care": 0.7, "force": 0.45, "meta": 0.3}
    YOUNG_FACTOR = {"tool": 0.05, "transform": 0.05, "force": 0.15}
    YOUNG_RARE = ("throw",)
    ATTEMPTS = 14

    def __init__(self, pools: Pools):
        self.pools, self.gov = pools, pools.governor
        self.actions = pools.cat["action"]
        # class of target -> family -> gestures whose first pointer accepts it; targetless ones apart
        self.by_class: dict[str, dict[str, list[str]]] = {}
        self.targetless: dict[str, list[str]] = {}
        for fam, ids in pools.gestures.items():
            if fam == "communicate":
                continue
            for g in ids:
                ref = next((p for p in self.actions[g].params if p.type == "ref"), None)
                if ref is None:
                    self.targetless.setdefault(fam, []).append(g)
                for cls in (ref.accepts if ref else []):
                    self.by_class.setdefault(cls, {}).setdefault(fam, []).append(g)

    # ---- the choice ---------------------------------------------------------------------------------------
    def pick(self, d: Draw, cls: str | None, actor: Party, target: Party | None, contact_ok: bool = True,
             young: bool = False, with_manner: bool = True) -> Choice | None:
        """A gesture (and the manner seen) done by `actor` to a target of class `cls` (None: no target) that the
        governor allows; None when nothing fits. with_manner=False: a bare gesture (a plan step has no manner)."""
        pool = self.targetless if cls is None else self.by_class.get(cls, {})
        for attempt in range(self.ATTEMPTS):
            ok_contact = contact_ok and attempt < self.ATTEMPTS - 3          # the last attempts renounce contact
            g = self._draw(d, pool, ok_contact, young)
            if g is None:
                continue
            a = self.actions[g]
            restricted = actor.may_be_minor() or bool(target is not None and target.may_be_minor())
            manner = self._manners(d, a, restricted) if with_manner else []
            params = dict(manner)
            ref = next((p.name for p in a.params if p.type == "ref"), None)
            parties = {ref: target} if ref is not None and target is not None else {}
            if self.gov.check_gesture(g, params, actor, parties).allowed:
                return Choice(g, tuple(v for _, v in manner), params)
        return None

    def _draw(self, d: Draw, pool: dict, contact_ok: bool, young: bool) -> str | None:
        fams = {f: gs for f, gs in pool.items() if (contact_ok or any(not self.actions[g].contact for g in gs))}
        if not fams:
            return None
        weights = {f: self.FAMILY_WEIGHT.get(f, 1.0) * (self.YOUNG_FACTOR.get(f, 1.0) if young else 1.0) for f in fams}
        fam = d.weighted(weights, allowed=list(fams))
        gs = [g for g in fams[fam] if contact_ok or not self.actions[g].contact]
        g = d.pick(gs)
        return None if young and g in self.YOUNG_RARE and d.chance(0.85) else g

    def _manners(self, d: Draw, a, restricted: bool) -> list[tuple[str, str]]:
        """(parameter, value) pairs as far as they are SEEN: at most one value per parameter, of at most two
        parameters. Never an intimate value; with a possible minor, a contact gesture shows its whitelisted values."""
        enums = [p for p in a.params if p.type == "enum"]
        clean = lambda p: [v for v in p.values if v not in p.intimate_values]  # noqa: E731
        if restricted and a.contact and a.minor_whitelist:
            out = []
            for pn, allowed in a.minor_whitelist.items():
                p = next((x for x in enums if x.name == pn), None)
                vals = [v for v in (allowed if p is None else clean(p)) if p is None or v in allowed]
                if vals:
                    out.append((pn, d.pick(vals)))
            return out
        out = []
        for p in d.sample(enums, 2):
            vals = clean(p)
            if vals and d.chance(0.7):
                out.append((p.name, d.pick(vals)))
        return out
