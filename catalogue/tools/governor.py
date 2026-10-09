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

import math
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from schema import Catalogue  # noqa: E402

WRITES_PER_DECISION = 4


def _adult_age(cat) -> float:
    """Read the adult threshold from the catalogue (life_stage: '... teen < 18 ...'), never copy it."""
    m = re.search(r"teen < (\d+)", cat["variable"]["life_stage"].dynamics)
    return float(m.group(1)) if m else 18.0


ADULT_AGE = _adult_age(Catalogue.load())
SCALE_BOUNDS = {"bipolar10": (-100, 100), "unipolar10": (0, 100)}   # in tenths


def tenths(x: float) -> int:
    """Charter scale -> stored tenths (round half away from zero, like the C++ port)."""
    return int(x * 10 + (0.5 if x >= 0 else -0.5))


@dataclass
class Party:
    """One person involved in a gesture, an utterance or a record. DENY BY DEFAULT (review 10 Oct): an unknown age,
    a non-finite age or an unresolved mental file (known only by name or description) count as a minor."""
    real_age: float | None = None
    believed_age: float | None = None      # the actor's belief about this person's age (None = no belief)
    apparent_age: float | None = None      # what the actor perceives (ep_age)
    resolved: bool = False                 # True only when the mental file is tied to a seen, recognised person

    def may_be_minor(self) -> bool:
        if not self.resolved:
            return True
        for a in (self.real_age, self.believed_age, self.apparent_age):
            if a is None or not math.isfinite(a) or a < ADULT_AGE:
                return True
        return False


UNKNOWN = Party()


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
                    intimate_target: Party | None = None, actor: Party | None = None, creating: bool = False) -> Verdict:
        """Values on the charter scale; computed in integer TENTHS exactly like the C++ engine (stored tenths)."""
        v = self.cat["variable"].get(var_id)
        if v is None:
            return Verdict(False, None, "unknown variable")
        if not self._model_writable(v):
            return Verdict(False, None, "engine-owned: the model acts through gestures")
        if v.scale not in ("bipolar10", "unipolar10", "qty", "ratio"):
            return Verdict(False, None, "structured value: use check_record")
        if not all(isinstance(x, (int, float)) and math.isfinite(x) for x in (old, proposed)):
            return Verdict(False, None, "non-finite value refused")
        o, want = tenths(old), tenths(proposed)
        if v.intimate and want > o:
            for party in (actor or UNKNOWN, intimate_target or UNKNOWN):
                if party.may_be_minor():
                    return Verdict(False, None, "D10: no intimate increase toward or from a possible minor (or unknown)")
        lo, hi = SCALE_BOUNDS.get(v.scale, (-32768, 32767))
        want = min(max(want, lo), hi)
        delta = want - o
        key = (var_id, target)                # target = the PERSISTENT id of the mental file, never a token slot
        if "T_jump" in v.writer and (creating or "T_step" not in v.writer):
            return Verdict(True, want / 10, "jump")   # free at creation (a new memory's valence), else jump only
        if "T_step" in v.writer:
            limit, used, book = tenths(v.rate), ledger.day_moved, "step"
        elif "T_slow" in v.writer:
            limit, used, book = tenths(v.slow_rate), ledger.year_moved, "slow"
        else:
            return Verdict(False, None, "no model writer")
        step = tenths(v.step)
        d = max(-step, min(step, delta))
        left = max(0, limit - used.get(key, 0))
        d = max(-left, min(left, d))
        used[key] = used.get(key, 0) + abs(d)
        return Verdict(d != 0 or delta == 0, (o + d) / 10, book if d == delta else "clipped")

    def check_writes(self, writes: list) -> list:
        """Sparse writes: one per (variable, target), the first WRITES_PER_DECISION kept, the rest refused."""
        seen, out = set(), []
        for w in writes:
            key = (w[0], w[1]) if isinstance(w, tuple) and len(w) >= 2 else w
            if key in seen:
                continue
            seen.add(key)
            out.append(w)
        return out[:WRITES_PER_DECISION]

    # ---- D10 on gestures, utterances and records (deny by default) ---------------------------
    def check_gesture(self, action_id: str, params: dict, actor: Party | None, parties: dict | None = None) -> Verdict:
        """params: param name -> value; parties: param name -> Party for every param that designates a person.
        A party param given without its Party counts as an unknown person (a possible minor)."""
        a = self.cat["action"].get(action_id)
        if a is None:
            return Verdict(False, None, "unknown gesture")
        parties = parties or {}
        involved = [actor or UNKNOWN]
        for pn in a.party_params:
            if pn in params or pn in parties:
                involved.append(parties.get(pn, UNKNOWN))
        minor = any(p.may_be_minor() for p in involved)
        if not minor:
            return Verdict(True, None, "ok")
        if a.intimate:
            return Verdict(False, None, "D10: intimate gesture with a possible minor")
        for prm in a.params:
            if params.get(prm.name) in prm.intimate_values:
                return Verdict(False, None, f"D10: '{params[prm.name]}' refused with a possible minor")
        touched = len(involved) > 1
        if a.contact and touched:
            if not a.minor_person_ok:
                return Verdict(False, None, f"D10: {a.id} on a possible minor is refused")
            for pn, allowed in a.minor_whitelist.items():
                if params.get(pn) not in allowed:
                    return Verdict(False, None, f"D10: {pn}={params.get(pn)!r} missing or outside minor_whitelist")
        return Verdict(True, None, "ok")

    def _gesture_frames(self, node, vocab):
        """Yield (gesture, params, party symbols) for every (did agent gesture target role*) in an expression."""
        from language import Node
        if not isinstance(node, Node):
            return
        if node.head == "did" and len(node.args) >= 2 and isinstance(node.args[1], str) and node.args[1] in self.cat["action"]:
            a = self.cat["action"][node.args[1]]
            params, syms = {}, {}
            ref_names = [p.name for p in a.params if p.type == "ref"]
            if len(node.args) >= 3 and isinstance(node.args[2], str) and ref_names:
                params[ref_names[0]] = node.args[2]; syms[ref_names[0]] = node.args[2]
            for r in node.args[3:]:
                if isinstance(r, Node) and r.args and isinstance(r.args[0], str):
                    if r.head == "how":
                        for p in a.params:
                            if r.args[0] in p.values:
                                params[p.name] = r.args[0]
                    elif r.head in ref_names:
                        params[r.head] = r.args[0]; syms[r.head] = r.args[0]
            yield a.id, params, syms
        for x in node.args:
            yield from self._gesture_frames(x, vocab)

    def check_utterance(self, expression, speaker: Party | None, parties: dict | None = None,
                        addressees: list | None = None) -> Verdict:
        """parties: symbol (me, you, @E2, n:7...) -> Party. Involved = speaker, addressees (all present when none is
        named) and every person the utterance points to; an unknown symbol is an unknown person."""
        parties = parties or {}
        involved = [speaker or UNKNOWN] + list(addressees if addressees is not None else [UNKNOWN])
        for sym in expression.root.symbols():
            if sym.startswith("@E") or sym.startswith("n:") or sym in ("you", "someone"):
                involved.append(parties.get(sym, UNKNOWN))
        minor = any(p.may_be_minor() for p in involved)
        if minor and expression.intimate_symbols():
            return Verdict(False, None, "D10: intimate words with a possible minor involved")
        for gid, params, syms in self._gesture_frames(expression.root, None):
            actor = parties.get("me", speaker or UNKNOWN)
            gp = {pn: parties.get(sym, UNKNOWN) for pn, sym in syms.items()}
            v = self.check_gesture(gid, params, actor if not minor else UNKNOWN, gp)
            if not v.allowed:
                return Verdict(False, None, "described gesture refused: " + v.reason)
        return Verdict(True, None, "ok")

    def check_record(self, kind: str, expression, owner: Party | None, parties: dict | None = None) -> Verdict:
        """A goal, a belief, a memory or an agreement written by the model: valid expression, and D10 like speech."""
        if kind not in ("goal", "belief", "memory", "agreement", "plan"):
            return Verdict(False, None, "unknown record kind")
        if not expression.ok:
            return Verdict(False, None, "invalid expression: " + "; ".join(expression.problems))
        return self.check_utterance(expression, owner, parties, addressees=[])
