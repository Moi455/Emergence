"""governor.py - step 15: the governor, reference implementation (the C++ port must reproduce its decisions).

It sits between the Transformer and the world. Whatever the model outputs, the governor:
  * refuses writes to engine-owned variables (engine_only components, writer without T_*);
  * bounds every write: a jump only for T_jump, otherwise per decision (step), per game day (rate) and per
    life-year (slow_rate);
  * keeps at most WRITES_PER_DECISION writes per decision (sparse writes);
  * enforces hard rule D10 on gestures and utterances: a minor by real, believed OR apparent age, or a target
    known only by name or description, refuses every intimate value and every value outside minor_whitelist.

It never decides anything: it only clips or refuses. Units are the charter scale (-10..+10); the engine stores
tenths.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from schema import Catalogue  # noqa: E402

WRITES_PER_DECISION = 4
ADULT_AGE = 18.0
SCALE_BOUNDS = {"bipolar10": (-10.0, 10.0), "unipolar10": (0.0, 10.0)}


@dataclass
class Party:
    """What the governor knows of one person involved in a gesture or an utterance (truth and the actor's view)."""
    real_age: float
    believed_age: float | None = None      # the actor's belief about this person's age (None = no belief)
    apparent_age: float | None = None      # what perception shows (look_age_seen)
    resolved: bool = True                  # False: known only by name or by description (r_known_by)

    def may_be_minor(self) -> bool:
        if not self.resolved:
            return True
        ages = [self.real_age, self.apparent_age, self.believed_age]
        if self.believed_age is None:      # no belief about the age counts as minor (D10)
            return True
        return any(a is not None and a < ADULT_AGE for a in ages)


@dataclass
class Verdict:
    allowed: bool
    value: float | None = None
    reason: str = ""


@dataclass
class WriteLedger:
    """Per-NPC memory of what the model already moved, to apply the per-day and per-life-year bounds."""
    day_moved: dict = field(default_factory=dict)     # (variable, target) -> |delta| moved during this game day
    year_moved: dict = field(default_factory=dict)    # (variable, target) -> |delta| moved during this life-year
    day: int = 0
    life_year: int = 0

    def roll(self, day: int, life_year: int):
        if day != self.day:
            self.day, self.day_moved = day, {}
        if life_year != self.life_year:
            self.life_year, self.year_moved = life_year, {}


class Governor:
    def __init__(self, cat: Catalogue):
        self.cat = cat

    # ---- variable writes ----------------------------------------------------------------------
    def _model_writable(self, v) -> bool:
        comp = self.cat["component"].get(v.holder)
        if comp is not None and comp.engine_only:
            return False
        return any(w.startswith("T_") for w in v.writer)

    def check_write(self, var_id: str, old: float, proposed: float, ledger: WriteLedger, target: str = "",
                    intimate_target: Party | None = None, actor: Party | None = None) -> Verdict:
        v = self.cat["variable"].get(var_id)
        if v is None:
            return Verdict(False, None, "unknown variable")
        if not self._model_writable(v):
            return Verdict(False, None, "engine-owned: the model acts through gestures")
        if v.intimate and proposed > old:
            if (actor is not None and actor.may_be_minor()) or (intimate_target is not None and intimate_target.may_be_minor()):
                return Verdict(False, None, "D10: no intimate increase toward or from a possible minor")
        lo, hi = SCALE_BOUNDS.get(v.scale, (float("-inf"), float("inf")))
        new = min(max(proposed, lo), hi)
        delta = new - old
        if "T_jump" in v.writer:
            return Verdict(True, new, "jump")
        key = (var_id, target)
        if "T_step" in v.writer:
            step = max(-v.step, min(v.step, delta))
            left = max(0.0, v.rate - ledger.day_moved.get(key, 0.0))
            step = max(-left, min(left, step))
            ledger.day_moved[key] = ledger.day_moved.get(key, 0.0) + abs(step)
            return Verdict(abs(step) > 0 or delta == 0, old + step, "step" if step == delta else "clipped")
        if "T_slow" in v.writer:
            step = max(-v.step, min(v.step, delta))
            left = max(0.0, v.slow_rate - ledger.year_moved.get(key, 0.0))
            step = max(-left, min(left, step))
            ledger.year_moved[key] = ledger.year_moved.get(key, 0.0) + abs(step)
            return Verdict(abs(step) > 0 or delta == 0, old + step, "slow" if step == delta else "clipped")
        return Verdict(False, None, "no model writer")

    def check_writes(self, writes: list) -> list:
        """Sparse writes: keep the first WRITES_PER_DECISION, refuse the rest (the model learns to choose)."""
        return writes[:WRITES_PER_DECISION]

    # ---- D10 on gestures and utterances -------------------------------------------------------
    def check_gesture(self, action_id: str, params: dict, actor: Party, target: Party | None) -> Verdict:
        a = self.cat["action"].get(action_id)
        if a is None:
            return Verdict(False, None, "unknown gesture")
        minor = actor.may_be_minor() or (target is not None and target.may_be_minor())
        for prm in a.params:
            val = params.get(prm.name)
            if val is None:
                continue
            if val in prm.intimate_values and minor:
                return Verdict(False, None, f"D10: '{val}' refused with a possible minor")
        if minor and a.contact and target is not None:
            for pn, allowed in a.minor_whitelist.items():
                if pn in params and params[pn] not in allowed:
                    return Verdict(False, None, f"D10: {pn}='{params[pn]}' outside minor_whitelist")
        return Verdict(True, None, "ok")

    def check_utterance(self, expression, speaker: Party, involved: list[Party]) -> Verdict:
        """expression: a language.Expression. Any intimate word with a possible minor involved is refused."""
        if expression.intimate_symbols() and (speaker.may_be_minor() or any(p.may_be_minor() for p in involved)):
            return Verdict(False, None, "D10: intimate words with a possible minor")
        return Verdict(True, None, "ok")
