"""governor.py - step 15: the governor, reference implementation (the C++ port must reproduce its decisions).

It sits between the Transformer and the world. Whatever the model outputs, the governor:
  * refuses writes to engine-owned variables (engine_only components, writer without T_*);
  * bounds every numeric write: a jump only for T_jump, otherwise per decision (step), per game day (rate) and
    per life-year (slow_rate); checks every structured write (enum, word, bool, pointer, proposition);
  * keeps at most WRITES_PER_DECISION writes per decision, one per (target, variable);
  * enforces hard rule D10 on gestures, utterances and records, DENY BY DEFAULT: a minor by real, believed OR
    apparent age, an unknown age, or a person known only by name or description counts as a minor. D10 looks at
    the PARTICIPANTS of an intimate act or link; the hearers matter only when an intimate act or desire is SAID
    (P30). Every cited record (b:, m:, g:, bare or in `that`) is unfolded and checked as said.

It never decides anything: it only clips or refuses. Values on the charter scale (-10..+10), computed in integer
TENTHS like the C++ port (the engine stores tenths).
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
LEDGER_CAPACITY = 512          # live (target, variable) entries per NPC; beyond, a NEW key is refused (ledger_full)
MAX_AGE_TENTHS = 32767         # an age beyond this (int16 tenths) is absurd: it reads as UNKNOWN (a possible minor)
MAX_DAY_JUMP, MAX_YEAR_JUMP = 1000, 100   # a larger jump of the clock in one roll is aberrant: ignored (review 13)
CITE = re.compile(r"^([bmg]:|@V)[0-9]+$")  # a cited record or perceived event: its frozen content is what is said
_CAT = Catalogue.load()
ADULT_AGE = float(_CAT["hard_rule"]["D10_minors"].adult_age_years)   # pinned in hard_rules.toml (18)
SCALE_BOUNDS = {"bipolar10": (-100, 100), "unipolar10": (0, 100)}     # in tenths
SELF_HOLDERS = ("mind_static", "mind_dynamic", "needs", "body")        # variables of the actor himself


def tenths(x: float) -> int:
    """Charter scale -> stored tenths (round half away from zero, like the C++ port)."""
    return int(x * 10 + (0.5 if x >= 0 else -0.5))


def age_tenths(years: float | None) -> int:
    """Years -> tenths of years, rounded DOWN (toward 'minor'): 17.96 years stays a minor."""
    if years is None or isinstance(years, bool) or not isinstance(years, (int, float)):
        return -1                                   # unknown or not a number: deny by default
    try:
        if not math.isfinite(years) or years < 0 or years * 10 >= MAX_AGE_TENTHS + 1:
            return -1                               # non-finite, negative or absurd
        return math.floor(years * 10)
    except OverflowError:
        return -1


@dataclass
class Party:
    """One participant. DENY BY DEFAULT: unknown, unresolved or non-finite ages count as a minor.
    person=False marks a thing (a stone, a house): it is never a minor and never a party of D10."""
    real_age: float | None = None
    believed_age: float | None = None      # what the actor believes (None = no belief)
    apparent_age: float | None = None      # what the actor perceives (ep_age)
    resolved: bool = False                 # tied to a seen, recognised person
    person: bool = True
    perceived: bool = True                 # False: not perceived now (absent): there is no apparent age to check,
                                           # the real age (engine) and the believed age must still be adult (review 18)

    def may_be_minor(self) -> bool:
        if not self.person:
            return False
        if not self.resolved:
            return True
        ages = (self.real_age, self.believed_age, self.apparent_age) if self.perceived else (self.real_age, self.believed_age)
        for a in ages:
            t = age_tenths(a)
            if t < 0 or t < ADULT_AGE * 10:
                return True
        return False


UNKNOWN = Party()
THING = Party(resolved=True, person=False)


@dataclass
class Verdict:
    allowed: bool
    value: object = None
    reason: str = ""
    code: str = "ok"        # stable reason code, shared with the C++ port (em::social::Reason)


def ok(value=None, code="ok"):
    return Verdict(True, value, code, code)


def no(code: str, reason: str = ""):
    return Verdict(False, None, reason or code, code)


@dataclass
class WriteLedger:
    """Per-NPC memory of what the model already moved, for the per-day and per-life-year bounds.
    The target is the PERSISTENT id of a mental file, never a token slot."""
    day_moved: dict = field(default_factory=dict)
    year_moved: dict = field(default_factory=dict)
    day: int = 0
    life_year: int = 0
    synced: bool = False         # the first roll adopts the engine's clock whatever the jump (review 15)

    @classmethod
    def at(cls, day: int, life_year: int) -> "WriteLedger":
        return cls(day=day, life_year=life_year, synced=True)

    def live(self) -> int:
        return sum(1 for x in self.day_moved.values() if x) + sum(1 for x in self.year_moved.values() if x)

    def can_record(self, key) -> bool:
        """A key already moving this day / life-year, or a free place (LEDGER_CAPACITY live entries at most)."""
        return bool(self.day_moved.get(key) or self.year_moved.get(key)) or self.live() < LEDGER_CAPACITY

    def roll(self, day: int, life_year: int):
        """Time never goes back: an earlier day or life-year is ignored (review 11: an oscillating clock must not
        refill the daily bounds), and so is an aberrant jump (review 13). The FIRST roll of a new ledger adopts the
        clock whatever its value: an NPC born late is not stuck on day 0 (review 15)."""
        if not self.synced:
            self.synced = True
            if (day, life_year) != (self.day, self.life_year):
                self.day, self.life_year, self.day_moved, self.year_moved = day, life_year, {}, {}
            return
        if self.day < day <= self.day + MAX_DAY_JUMP:
            self.day, self.day_moved = day, {}
        if self.life_year < life_year <= self.life_year + MAX_YEAR_JUMP:
            self.life_year, self.year_moved = life_year, {}


class PartyResolver:
    """Maps a symbol or a node of an utterance to a Party. Listed symbols use the caller's map; things (@T, @L,
    @PLACE, here, this, kinds, numbers) are THING; everything else (descriptions, quantifiers, names, unknown
    pointers) is UNKNOWN."""

    THING_PREFIXES = ("@T", "@L", "@PLACE", "@V")

    def __init__(self, parties: dict | None, vocab=None):
        self.parties = parties or {}
        self.vocab = vocab

    def __call__(self, ref) -> Party:
        if not isinstance(ref, str):
            return UNKNOWN                                    # (described …) or any node: not identified
        if ref in self.parties:
            p = self.parties[ref]
            return p if isinstance(p, Party) else UNKNOWN          # a missing or malformed party: deny by default
        if ref.startswith(self.THING_PREFIXES) or ref in ("here", "this") or ref.isdigit():
            return THING
        if self.vocab is not None:
            base = ref.partition(":")[0]
            if base in self.vocab.kinds:
                return THING
        return UNKNOWN


class Governor:
    def __init__(self, cat: Catalogue | None = None):
        self.cat = cat or _CAT
        self._vocab = None

    @property
    def vocab(self):
        if self._vocab is None:
            import language
            self._vocab = language.Vocabulary(self.cat)
        return self._vocab

    # ---- writes ---------------------------------------------------------------------------------
    def _model_writable(self, v) -> bool:
        comp = self.cat["component"].get(v.holder)
        if comp is not None and comp.engine_only:
            return False
        return any(w.startswith("T_") for w in v.writer)

    def _intimate_refused(self, v, actor, intimate_target) -> bool:
        if v.holder in SELF_HOLDERS:                         # one's own drive: only the actor matters
            return (actor or UNKNOWN).may_be_minor()
        return (actor or UNKNOWN).may_be_minor() or (intimate_target or UNKNOWN).may_be_minor()

    def check_write(self, var_id: str, old, proposed, ledger: WriteLedger, target: str = "",
                    intimate_target: Party | None = None, actor: Party | None = None, creating: bool = False) -> Verdict:
        v = self.cat["variable"].get(var_id)
        if v is None:
            return no("unknown_variable")
        if not self._model_writable(v):
            return no("engine_owned", "engine-owned: the model acts through gestures")
        if v.scale not in ("bipolar10", "unipolar10", "qty", "ratio"):
            return no("structured", "structured value: use check_value or check_record")
        for x in (old, proposed):
            if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x):
                return no("non_finite", "non-finite or non-numeric value refused")
        o, want = tenths(old), tenths(proposed)
        if v.intimate and want > (0 if creating else o) and self._intimate_refused(v, actor, intimate_target):
            return no("d10_intimate", "D10: no intimate increase toward or from a possible minor")
        lo, hi = SCALE_BOUNDS.get(v.scale, (-32768, 32767))
        want = min(max(want, lo), hi)
        delta = want - o
        key = (target, var_id)
        if "T_jump" in v.writer and (creating or "T_step" not in v.writer):
            return ok(want / 10, "jump")
        if "T_step" in v.writer:
            limit, used, book = tenths(v.rate), ledger.day_moved, "step"
        elif "T_slow" in v.writer:
            limit, used, book = tenths(v.slow_rate), ledger.year_moved, "slow"
        else:
            return no("no_writer")
        step = tenths(v.step)
        d = max(-step, min(step, delta))
        left = max(0, limit - used.get(key, 0))
        d = max(-left, min(left, d))
        if d != 0 and not ledger.can_record(key):
            return Verdict(False, o / 10, "ledger full: no new (target, variable) this day", "ledger_full")
        used[key] = used.get(key, 0) + abs(d)
        return Verdict(d != 0 or delta == 0, (o + d) / 10, book, book if d == delta else "clipped")

    def check_value(self, var_id: str, value, actor: Party | None = None, parties: dict | None = None) -> Verdict:
        """A structured (non-numeric) write: enum, word, bool, pointer. Propositions go through check_record."""
        v = self.cat["variable"].get(var_id)
        if v is None:
            return no("unknown_variable")
        if not self._model_writable(v):
            return no("engine_owned")
        if v.scale == "bool":
            return ok(value) if isinstance(value, bool) else no("invalid_value")
        if v.scale == "enum":
            values = v.values or [c.id for c in self.cat["concept"].values() if c.category == v.values_from]
            return ok(value) if value in values else no("invalid_value")
        if v.scale == "word":
            if var_id == "m_interpretation":
                interp = self.cat["interpretation"].get(value)
                if interp is None:
                    return no("invalid_value")
                if interp.intimate and (not parties or any(PartyResolver(parties)(r).may_be_minor() for r in parties)):
                    return no("d10_intimate", "D10: an intimate judgement about a possible minor")
                return ok(value)
            return ok(value) if isinstance(value, str) and value in self.vocab.cats else no("invalid_value")
        if v.scale == "mref":
            return ok(value) if isinstance(value, str) and value else no("invalid_value")   # the store checks existence
        if v.scale == "time":
            return ok(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else no("invalid_value")
        return no("structured", "use check_record for a proposition or a plan")

    def check_writes(self, writes: list) -> list:
        """Sparse writes, each (target, variable, value): one per (target, variable), the first WRITES_PER_DECISION
        kept. Lists (decoded from JSON) are accepted as tuples."""
        seen, out = set(), []
        for w in writes:
            w = tuple(w) if isinstance(w, (list, tuple)) else (w,)
            key = w[:2]
            if key in seen:
                continue
            seen.add(key)
            out.append(w)
        return out[:WRITES_PER_DECISION]

    # ---- gestures ---------------------------------------------------------------------------------
    def check_gesture(self, action_id: str, params: dict, actor: Party | None, parties: dict | None = None,
                      executed: bool = False, content_parties: dict | None = None, expand=None,
                      hearers: list | None = None) -> Verdict:
        """params: param name -> value; parties: param name -> Party for every param that designates someone or
        something. executed=True (the model's own output): every non-optional param must be present.
        An expression param (speak, write) is checked here with check_utterance (review 10): the content is part of
        the gesture. content_parties / expand are those of check_utterance (None: deny by default). hearers: every
        person in earshot as the ENGINE knows them (a group as a Party that may be a minor if any member may be);
        None: the addressee (`to`), plus unknown hearers when it is absent or when one speaks loud or shouts."""
        a = self.cat["action"].get(action_id)
        if a is None:
            return no("unknown_gesture")
        parties = parties or {}
        known = {p.name: p for p in a.params}
        for name, val in params.items():
            p = known.get(name)
            if p is None or (p.type == "enum" and val not in p.values):
                return no("invalid_value", f"invalid value {name}={val!r}")
        if executed:
            for p in a.params:
                if not p.optional and p.name not in params:
                    return no("invalid_value", f"missing param {p.name}")
        for p in a.params:
            if p.type == "expression" and p.name in params:
                import language
                e = params[p.name]
                e = e if isinstance(e, language.Expression) else language.Expression(str(e), self.vocab)
                addressed = [parties.get(q.name, UNKNOWN) for q in a.params
                             if q.type == "ref" and "agent" in q.accepts and q.name not in a.party_params
                             and (q.name in params or q.name in parties)]
                if hearers is not None:                       # the engine knows who is in earshot
                    heard = list(hearers) + addressed         # ... and the addressee always hears (review 15)
                else:
                    heard = addressed or [UNKNOWN]
                    if params.get("volume") != "whisper":
                        heard.append(UNKNOWN)                 # passers-by in earshot (deny by default, review 15)
                v = self.check_utterance(e, actor, content_parties, addressees=heard or None, expand=expand)
                if not v.allowed:
                    return v
        persons = [actor or UNKNOWN]
        for pn in a.party_params:
            prm = known[pn]
            if pn in params or pn in parties:
                party = parties.get(pn, UNKNOWN)
            elif a.contact and not prm.optional and "agent" in prm.accepts:
                party = UNKNOWN                               # a contact gesture with its person left out
            else:
                continue
            if party.person:
                persons.append(party)
        if not any(p.may_be_minor() for p in persons):
            return ok()
        if a.intimate:
            return no("d10_intimate", "D10: intimate gesture with a possible minor")
        for prm in a.params:
            if params.get(prm.name) in prm.intimate_values:
                return no("d10_value", f"D10: '{params[prm.name]}' refused with a possible minor")
        if a.contact and len(persons) > 1:
            if not a.minor_person_ok:
                return no("d10_person", f"D10: {a.id} on a possible minor is refused")
            for pn, allowed in a.minor_whitelist.items():
                if params.get(pn) not in allowed:
                    return no("d10_whitelist", f"D10: {pn}={params.get(pn)!r} missing or outside minor_whitelist")
        return ok()

    # ---- utterances and records --------------------------------------------------------------------
    def _is_intimate(self, sym) -> bool:
        if not isinstance(sym, str):
            return False
        c = self.cat["concept"].get(sym)
        v = self.cat["variable"].get(sym)
        i = self.cat["interpretation"].get(sym)
        return bool((c is not None and c.intimate) or (v is not None and v.intimate) or (i is not None and i.intimate)
                    or sym in self.vocab.manner_intimate)

    @staticmethod
    def _participants(node):
        """The referring arguments of a node: pointers, deictics, quantifiers, names and descriptions."""
        from language import POINTER, REF_WORDS
        out = []
        for x in node.args:
            if isinstance(x, str) and (POINTER.match(x) or x in REF_WORDS):
                out.append(x)
            elif hasattr(x, "head") and x.head == "described":
                out.append(x)
            elif hasattr(x, "head") and x.head in ("to", "with", "into") and x.args:
                out.append(x.args[0])
        return out

    @staticmethod
    def _once(expand):
        """expand called at most once per reference; an exception is a missing copy (review 15)."""
        if expand is None:
            return None
        memo: dict = {}

        def unfold(ref):
            if ref not in memo:
                try:
                    memo[ref] = expand(ref)
                except Exception:                     # noqa: BLE001  (any failure: refused as unexpanded)
                    memo[ref] = None
            return memo[ref]
        return unfold

    @staticmethod
    def _unfold(ref, expand, depth):
        """The frozen copy of a cited record (b:, m:, g:) or perceived event (@V), or None: refused as unexpanded
        (no copy, too deep, or not a valid Expression - an utterance or a bare proposition)."""
        import language
        if expand is None or depth > 2 or not isinstance(ref, str):
            return None
        inner = expand(ref)
        return inner if isinstance(inner, language.Expression) and inner.ok else None

    def _check_node(self, node, resolve, expand, depth=0) -> Verdict:
        from language import Node
        if isinstance(node, str) and CITE.match(node):         # a bare citation says the record too (review 13)
            inner = self._unfold(node, expand, depth)
            if inner is None:
                return no("unexpanded", "the content of a cited belief/memory/goal must be checked (frozen copy)")
            return self._check_node(inner.root, resolve, expand, depth + 1)
        if not isinstance(node, Node):
            return ok()
        if node.head == "that":
            return self._check_node(node.args[0] if node.args else None, resolve, expand, depth) if node.args \
                else no("unexpanded")
        if node.head == "did" and len(node.args) >= 2 and isinstance(node.args[1], str) and node.args[1] in self.cat["action"]:
            a = self.cat["action"][node.args[1]]
            params, parties = {}, {}
            refs = [p.name for p in a.params if p.type == "ref"]
            rest = node.args[2:]
            if rest and not (hasattr(rest[0], "head") and rest[0].head in ("with", "to", "into", "how", "says")):
                if refs:
                    params[refs[0]] = "?"; parties[refs[0]] = resolve(rest[0])
                rest = rest[1:]
            for r in rest:
                if hasattr(r, "head") and r.args:
                    if r.head == "how":
                        for p in a.params:
                            if r.args[0] in p.values:
                                params[p.name] = r.args[0]
                    elif r.head in refs:
                        params[r.head] = "?"; parties[r.head] = resolve(r.args[0])
            v = self.check_gesture(a.id, params, resolve(node.args[0]), parties)
            if not v.allowed:
                return Verdict(False, None, "described gesture refused: " + v.reason, v.code)
        # an intimate word in this node: every participant (its referring arguments) is checked
        if any(self._is_intimate(x) for x in [node.head] + node.args):
            for r in self._participants(node):
                if resolve(r).may_be_minor():
                    return no("d10_intimate", "D10: an intimate act or link with a possible minor")
        for x in node.args:
            v = self._check_node(x, resolve, expand, depth)
            if not v.allowed:
                return v
        return ok()

    def check_utterance(self, expression, speaker: Party | None, parties: dict | None = None,
                        addressees: list | None = None, expand=None, said: bool = True) -> Verdict:
        """parties: symbol (me, you, @E2, n:7...) -> Party; expand: b:/m:/g: -> the frozen Expression of that record.
        D10 looks at the participants of an intimate act or link. The hearers matter only for an intimate ACT or
        DESIRE (an intimate gesture or manner, an intimate variable): never said to a possible minor (review 11;
        links such as spouse or lover remain social facts a child may hear). addressees None = unknown hearers."""
        if not expression.ok:
            return no("invalid_value", "invalid expression: " + "; ".join(expression.problems))
        expand = self._once(expand)                   # one frozen copy per citation, shared by both checks
        if said and any(self._hearer_sensitive(x) for x in self._said_symbols(expression.root, expand)):
            hearers = list(addressees) if addressees else [UNKNOWN]
            if any((h or UNKNOWN).may_be_minor() for h in hearers):
                return no("d10_hearer", "D10: an intimate act or desire told to a possible minor")
        p = dict(parties or {})
        p["me"] = speaker or UNKNOWN                  # the speaker is who the engine says, never a content party
        return self._check_node(expression.root, PartyResolver(p, self.vocab), expand)

    def _said_symbols(self, node, expand, depth=0) -> list:
        """Every symbol the hearer receives, cited records (that b:7) unfolded."""
        from language import Node
        if isinstance(node, str) and CITE.match(node):
            inner = self._unfold(node, expand, depth)
            return self._said_symbols(inner.root, expand, depth + 1) if inner is not None else [node]
        if not isinstance(node, Node):
            return [node]
        if node.head == "that" and node.args:
            return self._said_symbols(node.args[0], expand, depth)
        out = [node.head]
        for a in node.args:
            out += self._said_symbols(a, expand, depth)
        return out

    def _hearer_sensitive(self, sym) -> bool:
        a = self.cat["action"].get(sym)
        v = self.cat["variable"].get(sym)
        return bool(sym in self.vocab.manner_intimate or (a is not None and a.intimate) or (v is not None and v.intimate))

    def check_record(self, kind: str, expression, owner: Party | None, parties: dict | None = None, expand=None) -> Verdict:
        """A goal, a belief, a memory, an agreement or a plan written by the model."""
        if kind not in ("goal", "belief", "memory", "agreement", "plan"):
            return no("invalid_value", "unknown record kind")
        return self.check_utterance(expression, owner, parties, expand=expand, said=False)   # a record is not said
