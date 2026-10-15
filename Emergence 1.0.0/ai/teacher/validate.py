"""validate.py - the teacher's JSON answer + the situation -> a normalised Decision, or a refusal with a stable code.

Order of the checks (the first failure is the code returned):
  invalid_json        not JSON at all
  bad_shape           JSON, but not the expected object (missing field, wrong type)
  unknown_gesture     gesture id not in the catalogue
  too_many_writes     more than 4 writes
  bad_param           unknown / duplicate / missing / invalid parameter, or a pointer of a class the parameter refuses
  bad_pointer         a key that is not among the records of the situation (also inside the speech)
  bad_speech          speech is not a valid utterance, is missing for speak/write, or given to another gesture
  bad_write           a write whose target, variable or value is malformed
  unknown_old         a bounded write on a variable whose current value is not in the records
  truth_error         the engine-side map from keys to real ages is inconsistent with the records (a bug upstream)
  governor:<code>     the governor refused (bounds, engine-owned variable, hard rule D10...)

An optional `plan` (T11) is checked after the writes; its own codes, in this order: bad_shape (not the expected object),
too_many_steps (more than 6), bad_plan (no step, a step with no target where one is needed, a repeat that is not an
i_repeat value, a period without `every`, a parent that is not a goal), unknown_gesture (a step), bad_pointer (a step
target that is not among the records, of a type PLAN.step_targets refuses, or that the gesture's first pointer cannot take),
governor:<code> (each step goes through check_gesture: D10). An optional `stop` (the decision's stop condition, for a
gesture without `until`) is a condition checked like `until` (bad_param / bad_pointer). Both are absent from the answer
unless the schema asks (DecisionSchema(plans=True)): an answer without them is exactly what it always was.

The governor runs on the ENGINE's view: the real ages come from the true scene (the governor lives engine-side and
knows the truth), the apparent and believed ages from the NPC's own records. Unresolved or unknown people count
as possible minors (deny by default).
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field

from governor import UNKNOWN, Party, WriteLedger
from language import POINTER, Node, ref_targets

from .spec import KEY_PREFIX, PROPOSITION_KIND, ParamSpec, WritableVar
from .toolkit import Toolkit


NUMBER = re.compile(r"^-?\d+(\.\d+)?$")
MAX_HOURS = 1.0e6


# ---------------------------------------------------------------------------------------------------- result types
class Codes:
    INVALID_JSON = "invalid_json"
    BAD_SHAPE = "bad_shape"
    UNKNOWN_GESTURE = "unknown_gesture"
    TOO_MANY_WRITES = "too_many_writes"
    BAD_PARAM = "bad_param"
    BAD_POINTER = "bad_pointer"
    BAD_SPEECH = "bad_speech"
    BAD_WRITE = "bad_write"
    UNKNOWN_OLD = "unknown_old"
    TRUTH_ERROR = "truth_error"
    TOO_MANY_STEPS = "too_many_steps"
    BAD_PLAN = "bad_plan"
    TOO_MANY_THOUGHTS = "too_many_thoughts"
    BAD_THOUGHT = "bad_thought"
    INCOHERENT_TRACE = "incoherent_trace"
    GOVERNOR = "governor:"
    ALL = (INVALID_JSON, BAD_SHAPE, UNKNOWN_GESTURE, TOO_MANY_WRITES, BAD_PARAM, BAD_POINTER, BAD_SPEECH, BAD_WRITE, UNKNOWN_OLD,
           TRUTH_ERROR, TOO_MANY_STEPS, BAD_PLAN, TOO_MANY_THOUGHTS, BAD_THOUGHT, INCOHERENT_TRACE)


class Refusal(Exception):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}")
        self.code, self.detail = code, detail


@dataclass
class Write:
    target: str
    variable: str
    value: object            # float | bool | str (the value the governor accepted, possibly clipped)
    verdict: str = "ok"      # the governor's code: ok, jump, step, slow, clipped...


@dataclass
class Decision:
    gesture: str
    params: dict                       # name -> str (enum, key, condition text)
    speech: str | None                 # canonical S-expression, or None
    writes: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    family: str = ""
    plan: dict | None = None           # {"steps": [{"gesture", "target"}], "repeat", "repeat_period", "parent"}; None: no plan
    plan_given: bool = False           # the answer carried a `plan` field (None then means "no plan", explicitly)
    stop: str | None = None            # the decision's stop condition (a gesture without `until`)
    stop_given: bool = False
    thoughts: list | None = None       # the written trace (T36), normalised; None: the answer carried none
    thoughts_given: bool = False

    def to_dict(self) -> dict:
        d = {"gesture": self.gesture, "params": self.params, "speech": self.speech,
             "writes": [{"target": w.target, "variable": w.variable, "value": w.value, "verdict": w.verdict}
                        for w in self.writes], "notes": self.notes}
        if self.plan_given:                                   # absent for every answer that did not carry them (older data)
            d["plan"] = self.plan
        if self.stop_given:
            d["stop"] = self.stop
        if self.thoughts_given:                               # absent for every answer that did not carry a trace (older data)
            d["thoughts"] = self.thoughts or []
        return d


@dataclass
class Outcome:
    decision: Decision | None
    code: str = "ok"
    detail: str = ""
    why: str = ""            # the teacher's own words: logged, never part of the decision

    @property
    def ok(self) -> bool:
        return self.decision is not None


# ---------------------------------------------------------------------------------------------------- truth
class TruthError(RuntimeError):
    pass


class TruthSource:
    """The engine's knowledge of the real age of the people the NPC's keys stand for."""

    def real_age(self, key: str) -> float | None:
        return None


class SceneTruth(TruthSource):
    """Maps the NPC's keys to the true people of the scene. The key -> person table is the sampler's own
    (`Situation.people`); it is cross-checked against the names and the apparent ages in the records, so a drift
    between the table and the files is detected instead of silently giving wrong ages. Without a table (a scene
    built by hand) the old order is rebuilt: present (known or near), then absent, cut at the ENTITY budget."""

    AGE_TOLERANCE = 5.0         # the sampler blurs a seen age by at most 4 years

    def __init__(self, scene, records, entity_budget: int, people: dict | None = None):
        if people is None:
            order = [x.person for x in scene.present if x.known or x.dist < 15] + [p for p, _ in scene.absent]
            people = {"me": scene.self_} | {f"@E{i + 1}": p for i, p in enumerate(order[:entity_budget])}
        self.people: dict[str, object] = dict(people)
        self.ages: dict[str, float] = {k: p.age for k, p in self.people.items()}
        for key, person in self.people.items():
            rec = next((r for r in records if r.key == key), None)
            if rec is None or rec.type != "ENTITY":
                continue
            if rec.fields.get("name") not in (None, person.name):
                raise TruthError(f"{key}: record name {rec.fields.get('name')} != scene name {person.name}")
            seen = rec.fields.get("look.age")
            if seen is not None and abs(seen - person.age) > self.AGE_TOLERANCE:      # strangers carry no name to compare
                raise TruthError(f"{key}: looks {seen} but the scene person is {person.age}: the key map drifted")

    def real_age(self, key: str) -> float | None:
        return self.ages.get(key)


# ---------------------------------------------------------------------------------------------------- mind index
class Mind:
    """The records of the situation, indexed, with the parties the governor needs."""

    def __init__(self, tk: Toolkit, records, truth: TruthSource):
        self.tk, self.records, self.truth = tk, list(records), truth
        self.by_key = {r.key: r for r in self.records}
        self.names = {r.fields["name"]: r.key for r in self.records if r.type == "ENTITY" and r.fields.get("name")}
        self._exprs: dict[str, object] = {}
        self._believed = self._believed_ages()

    # ---- keys
    def has(self, key: str) -> bool:
        return key in self.by_key

    def known_name(self, name: str) -> bool:
        return name in self.names

    # ---- parties
    def _believed_ages(self) -> dict:
        out = {}
        for r in self.records:
            if r.type in ("BELIEF", "HEARD") and r.fields.get("prop") and r.fields.get("polarity") is not False:
                try:
                    node = self.tk.parser.parse(r.fields["prop"])
                except Exception:   # noqa: BLE001  (records are the engine's; a bad one just gives no age)
                    continue
                for n in self._walk(node):
                    a = n.args
                    if n.head == "state" and len(a) == 3 and a[1] == "age_years" and isinstance(a[2], str) and a[2].isdigit():
                        out.setdefault(a[0], float(a[2]))
        return out

    def _walk(self, node):
        if isinstance(node, Node):
            yield node
            for a in node.args:
                yield from self._walk(a)

    def me_party(self) -> Party:
        me = self.by_key.get("me")
        age = me.fields.get("age") if me is not None else None
        return Party(real_age=self.truth.real_age("me"), believed_age=age, apparent_age=age, resolved=True)

    def party(self, key: str) -> Party:
        if key == "me":
            return self.me_party()
        rec = self.by_key.get(key)
        if rec is None:
            return UNKNOWN
        if rec.type == "ENTITY":
            seen = rec.fields.get("look.age")
            here = bool(rec.fields.get("present"))
            return Party(real_age=self.truth.real_age(key), believed_age=self._believed.get(key, seen if here else None),
                         apparent_age=seen, resolved=rec.fields.get("known_by") == "seen", perceived=here)
        if rec.type == "GROUP":
            return UNKNOWN                                        # a group may hold a minor: deny by default
        return Party(resolved=True, person=False)                 # THING, INV, LOCUS, PLACE...

    def content_parties(self, you: Party | None = None) -> dict:
        out = {r.key: self.party(r.key) for r in self.records if r.type in ("ENTITY", "GROUP")}
        out.update({name: out[key] for name, key in self.names.items() if key in out})
        if you is not None:
            out["you"] = you
        return out

    # ---- cited records
    def expand(self, key: str):
        """b:/m:/g: -> the frozen Expression of that record (a proposition validated as an assertion)."""
        if key in self._exprs:
            return self._exprs[key]
        rec = self.by_key.get(key)
        e = None
        if rec is not None and rec.type in ("BELIEF", "MEMORY", "GOAL") and rec.fields.get("prop"):
            e = self.tk.expression(f"(assert {rec.fields['prop']})")
            e = e if e.ok else None
        self._exprs[key] = e
        return e


# ---------------------------------------------------------------------------------------------------- parameters
class ConditionChecker:
    """until = c_done  or  (c_elapsed 30): the head and arity are those of the catalogue, arguments typed."""

    ACCEPT = {"quantity": {"quantity"}, "entity": {"agent", "item", "entity", "group", "place"}, "place": {"place"},
              "kind": {"kind"}, "concept": {"concept", "kind"}, "time": {"time"}}

    def __init__(self, tk: Toolkit, mind: Mind):
        self.tk, self.mind = tk, mind

    def check(self, text: str) -> str:
        s = " ".join(text.split())
        try:
            node = self.tk.parser.parse(s) if s.startswith("(") else Node(s)
        except Exception as e:   # noqa: BLE001
            raise Refusal(Codes.BAD_PARAM, f"condition {text!r}: {e}") from None
        if node.head not in self.tk.spec.conditions:
            raise Refusal(Codes.BAD_PARAM, f"unknown condition {node.head!r}")
        want = self.tk.spec.conditions[node.head]
        if len(node.args) != len(want):
            raise Refusal(Codes.BAD_PARAM, f"({node.head} ...) takes {len(want)} argument(s)")
        for a, t in zip(node.args, want):
            if not isinstance(a, str):
                raise Refusal(Codes.BAD_PARAM, f"{node.head}: argument must be a symbol")
            if a.startswith("n:") and POINTER.match(a):
                if not self.mind.known_name(a):
                    raise Refusal(Codes.BAD_POINTER, f"name {a} is not printed in your records")
            elif POINTER.match(a):
                if not self.mind.has(a):
                    raise Refusal(Codes.BAD_POINTER, f"{a} is not among your records")
            try:
                types = self.tk.vocab.types(a)
            except Exception as e:   # noqa: BLE001
                raise Refusal(Codes.BAD_PARAM, f"{node.head}: {e}") from None
            if not types & self.ACCEPT.get(t, {t}):
                raise Refusal(Codes.BAD_PARAM, f"{node.head}: {a!r} cannot stand for a {t}")
        return s if node.args else node.head


class ParamChecker:
    """The parameters of one gesture: complete, valid, pointing at real records of an accepted class."""

    def __init__(self, tk: Toolkit, mind: Mind):
        self.tk, self.mind, self.conditions = tk, mind, ConditionChecker(tk, mind)

    def check(self, gesture, raw: list) -> tuple[dict, dict]:
        """-> (params name -> str, parties name -> Party)"""
        params: dict[str, str] = {}
        parties: dict[str, Party] = {}
        for item in raw:
            name, value = item["name"], item["value"]
            p = gesture.param(name)
            if p is None or p.kind == "expression":
                why = " (the content goes in the speech field)" if p is not None else ""
                raise Refusal(Codes.BAD_PARAM, f"{gesture.id} has no parameter {name!r}{why}")
            if name in params:
                raise Refusal(Codes.BAD_PARAM, f"parameter {name!r} given twice")
            params[name] = value
        for p in gesture.params:
            if p.kind != "expression" and not p.optional and p.name not in params:
                raise Refusal(Codes.BAD_PARAM, f"{gesture.id}: missing parameter {p.name!r}")
        for name in list(params):
            p = gesture.param(name)
            if p.kind == "enum":
                if params[name] not in p.values:
                    raise Refusal(Codes.BAD_PARAM, f"{name}={params[name]!r} is not in <{p.head}>")
            elif p.kind == "condition":
                params[name] = self.conditions.check(params[name])
            else:
                parties[name] = self._ref(gesture, p, params[name])
        return params, parties

    def _ref(self, g, p: ParamSpec, value: str) -> Party:
        spec = self.tk.spec
        if value in spec.directions:
            targets, party = {"direction"}, Party(resolved=True, person=False)
        elif value == "me" or POINTER.match(value) or value == "@PLACE":
            if value.startswith("n:"):
                raise Refusal(Codes.BAD_PARAM, f"{p.name}: designate a person by its @E key, not by name")
            if value != "me" and not self.mind.has(value):
                raise Refusal(Codes.BAD_POINTER, f"{p.name}={value!r} is not among your records")
            targets, party = self._targets(value), self.mind.party(value)
        elif value in self.tk.cat["form"] and "form" in p.accepts:
            targets, party = {"form"}, Party(resolved=True, person=False)
        else:
            raise Refusal(Codes.BAD_PARAM, f"{g.id}.{p.name}={value!r}: expected a key of your records")
        if not targets & set(p.accepts):
            raise Refusal(Codes.BAD_PARAM, f"{g.id}.{p.name}={value!r} is a {sorted(targets)}, accepted: {list(p.accepts)}")
        return party

    def _targets(self, key: str) -> set:
        targets = set(ref_targets(key, self.tk.vocab))
        rec = self.mind.by_key.get(key)
        if rec is not None and rec.type in ("THING", "INV"):
            sp = self.tk.cat["species"].get(str(rec.fields.get("kind", "")).partition(":")[0])
            if sp is not None:
                targets &= {"animal"} if sp.kingdom == "animal" else {"plant"}
            else:
                targets -= {"animal", "plant"}
        return targets


# ---------------------------------------------------------------------------------------------------- speech
class SpeechChecker:
    def __init__(self, tk: Toolkit, mind: Mind):
        self.tk, self.mind = tk, mind

    def check(self, text: str, wrap: str = ""):
        """text -> Expression. wrap='assert' wraps a proposition (records) into an utterance for validation."""
        s = " ".join(text.split())
        e = self.tk.expression(f"({wrap} {s})" if wrap else s)
        if not e.ok:
            raise Refusal(Codes.BAD_SPEECH, "; ".join(e.problems))
        for sym in e.root.symbols():
            if POINTER.match(sym):
                if sym.startswith("n:"):
                    if not self.mind.known_name(sym):
                        raise Refusal(Codes.BAD_POINTER, f"name {sym} is not printed in your records")
                elif not self.mind.has(sym):
                    raise Refusal(Codes.BAD_POINTER, f"{sym} is not among your records")
        return e


# ---------------------------------------------------------------------------------------------------- writes
class WriteChecker:
    """Each write {target, variable, value}: shaped here, bounded by the governor on a fresh ledger."""

    FIELD_HOLDERS = {"self": ("SELF", "SELF_MIND", "SELF_STATE"), "entity": ("ENTITY", "GROUP"),
                     "belief": ("BELIEF", "HEARD"), "goal": ("GOAL",), "memory": ("MEMORY",), "plan": ("PLAN",)}

    def __init__(self, tk: Toolkit, mind: Mind, speech: SpeechChecker):
        self.tk, self.mind, self.speech = tk, mind, speech
        self.gov = tk.governor
        self._ref_types: dict[str, tuple] = {}

    def check(self, raw: list, actor: Party) -> tuple[list, list]:
        ledger, out, notes, seen = WriteLedger(), [], [], set()
        for w in raw:
            target, var, value = ("me" if w["target"] == "self" else w["target"]), w["variable"], w["value"]
            if (target, var) in seen:
                notes.append(f"duplicate write {target}/{var} dropped")
                continue
            seen.add((target, var))
            out.append(self._one(target, var, value, ledger, actor))
        return out, notes

    def _one(self, target, var, value, ledger, actor) -> Write:
        wv = self.tk.spec.writes.get(var)
        if wv is None:
            v = self.gov.check_write(var, 0.0, 0.0, ledger)
            if not v.allowed and v.code != "structured":          # unknown or engine-owned: the governor's word
                raise Refusal(Codes.GOVERNOR + v.code, v.reason)
            raise Refusal(Codes.BAD_WRITE, f"{var!r} cannot be written by the teacher")
        key = self._target(wv, target)
        if not value.isascii():
            raise Refusal(Codes.BAD_WRITE, f"{wv.id}: value must be plain ASCII")
        if wv.numeric:
            return self._numeric(wv, target, key, value, ledger, actor)
        if wv.scale == "proposition":
            return self._proposition(wv, target, key, value, actor)
        return self._structured(wv, target, key, value, actor)

    # ---- targets
    def _target(self, wv: WritableVar, target: str) -> str:
        kind = wv.target_kind
        if kind == "self":
            if target not in ("self", "me"):
                raise Refusal(Codes.BAD_WRITE, f"{wv.id} is written on yourself: target 'self'")
            return "me"
        if target == "new":
            if not (wv.creatable and wv.scale == "proposition"):
                raise Refusal(Codes.BAD_WRITE, f"{wv.id} cannot create a record (only b_proposition, g_desired, m_content)")
            return "new"
        if not target.startswith(KEY_PREFIX[kind]):
            raise Refusal(Codes.BAD_WRITE, f"{wv.id} is written on a {kind} key ({'/'.join(KEY_PREFIX[kind])}), not {target!r}")
        if not self.mind.has(target):
            raise Refusal(Codes.BAD_POINTER, f"write target {target!r} is not among your records")
        return target

    def _old(self, wv: WritableVar, key: str):
        rec = self.mind.by_key.get(key)
        if rec is None:
            return None
        if key == "me":
            recs = [r for r in self.mind.records if r.key in ("me", "me.mind", "me.state")]
        else:
            recs = [rec]
        for tname, fname in wv.fields:
            for r in recs:
                if r.type == tname and isinstance(r.fields.get(fname), (int, float)):
                    return float(r.fields[fname])
        return None

    # ---- numeric
    def _numeric(self, wv, target, key, value, ledger, actor) -> Write:
        if not NUMBER.match(value):
            raise Refusal(Codes.BAD_WRITE, f"{wv.id}: {value!r} is not a number")
        x = float(value)
        if not math.isfinite(x):
            raise Refusal(Codes.BAD_WRITE, f"{wv.id}: {value!r} is not finite")
        old = self._old(wv, key)
        if old is None and wv.mode != "jump" and key != "new":
            raise Refusal(Codes.UNKNOWN_OLD, f"{wv.id} on {target}: no current value in your records, a bounded change cannot be judged")
        v = self.gov.check_write(wv.id, 0.0 if old is None else old, x, ledger, target=key,
                                 intimate_target=self.mind.party(key) if wv.target_kind == "entity" else None,
                                 actor=actor, creating=key == "new")
        if not v.allowed:
            raise Refusal(Codes.GOVERNOR + v.code, v.reason)
        return Write(target, wv.id, v.value, v.code)

    TOKEN_FIELD = re.compile(r"^(\w+)\.([\w.]+)")

    def ref_types(self, wv: WritableVar) -> tuple:
        """The record types a pointer variable may aim at: read from the variable's token in the catalogue
        ("SELF_STATE.attention (pointeur)") and `ref_types` of that field in model_interface.json. Empty = unconstrained."""
        if wv.id in self._ref_types:
            return self._ref_types[wv.id]
        slots = list(wv.fields)
        var = self.tk.cat["variable"].get(wv.id)
        m = self.TOKEN_FIELD.match(getattr(var, "token", "") or "")
        if m:
            slots.insert(0, (m.group(1), m.group(2)))
        types: set = set()
        for tname, fname in slots:
            f = self.tk.interface.token_types.get(tname, {}).get("fields", {}).get(fname, {})
            types.update(f.get("ref_types", ()))
        self._ref_types[wv.id] = out = tuple(sorted(types))
        return out

    # ---- enum, word, bool, mref, time
    def _structured(self, wv, target, key, value, actor) -> Write:
        parsed: object = value
        if wv.scale == "bool":
            if value not in ("true", "false"):
                raise Refusal(Codes.BAD_WRITE, f"{wv.id}: expected true or false")
            parsed = value == "true"
        elif wv.scale in ("time", "time_until"):         # time_until: hours from now; a deadline written is not in the past
            if not NUMBER.match(value) or not 0 <= float(value) <= MAX_HOURS:
                raise Refusal(Codes.BAD_WRITE, f"{wv.id}: {value!r} is not a number of hours in 0..{MAX_HOURS:g}")
            parsed = float(value)
        elif wv.scale == "mref":
            if not self.mind.has(value):
                raise Refusal(Codes.BAD_POINTER, f"{wv.id}={value!r} is not among your records")
            allowed = self.ref_types(wv)
            actual = self.mind.by_key[value].type
            if allowed and actual not in allowed:
                raise Refusal(Codes.BAD_POINTER, f"{wv.id}={value!r} is a {actual}, accepted: {list(allowed)}")
        parties = None
        if wv.id == "m_interpretation":
            rec = self.mind.by_key.get(key)
            syms = self.tk.parser.parse(rec.fields["prop"]).symbols() if rec is not None and rec.fields.get("prop") else []
            known = self.mind.content_parties()
            parties = {"me": actor}                       # every person the memory names, plus the one who judges
            for sym in syms:
                if POINTER.match(sym) and sym != "@PLACE" and sym[0] in "@n" and not sym.startswith(("@T", "@L", "@V")):
                    parties[sym] = known.get(sym, UNKNOWN)
        v = self.gov.check_value(wv.id, parsed, actor, parties)
        if not v.allowed:
            raise Refusal(Codes.GOVERNOR + v.code, v.reason)
        return Write(target, wv.id, parsed, v.code)

    # ---- propositions (a new or replaced belief, goal, memory)
    def _proposition(self, wv, target, key, value, actor) -> Write:
        e = self.speech.check(value, wrap="assert")
        kind = PROPOSITION_KIND.get(wv.target_kind)
        if kind is None:
            raise Refusal(Codes.BAD_WRITE, f"{wv.id}: no proposition record of kind {wv.target_kind!r}")
        v = self.gov.check_record(kind, e, actor, self.mind.content_parties(),
                                  expand=self.mind.expand)
        if not v.allowed:
            raise Refusal(Codes.GOVERNOR + v.code, v.reason)
        return Write(target, wv.id, " ".join(value.split()), v.code)


# ---------------------------------------------------------------------------------------------------- plans
class PlanChecker:
    """A plan the teacher writes (the model's `i_steps`, `i_step_targets`, `i_repeat`, `i_repeat_period`, `g_parent`):
    {"steps": [{"gesture", "target"}], "repeat", "repeat_period", "parent"}. Every step is a known gesture on ONE record
    of a type PLAN.step_targets accepts, and passes `check_gesture` like a gesture of its own (D10: a possible minor with
    an intimate or contact gesture is refused; a step that leaves out a manner is judged without it, i.e. strictly)."""

    def __init__(self, tk: Toolkit, mind: Mind, params: ParamChecker, writes: "WriteChecker"):
        self.tk, self.mind, self.params, self.writes = tk, mind, params, writes
        field = tk.interface.token_types["PLAN"]["fields"]["step_targets"]
        self.step_types = tuple(field["ref_types"])

    def check(self, raw: dict, actor: Party) -> dict | None:
        steps = raw.get("steps") or []
        if not steps:
            return None                                       # an explicit "no plan"
        spec = self.tk.spec
        if len(steps) > spec.max_plan_steps:
            raise Refusal(Codes.TOO_MANY_STEPS, f"{len(steps)} > {spec.max_plan_steps}")
        out = [self._step(i, st, actor) for i, st in enumerate(steps)]
        repeat = raw.get("repeat") or "once"
        if repeat not in spec.writes["i_repeat"].values:
            raise Refusal(Codes.BAD_PLAN, f"repeat={repeat!r} is not one of {list(spec.writes['i_repeat'].values)}")
        period = raw.get("repeat_period")
        if period in (None, ""):
            period = None
        else:
            text = str(period)
            if repeat != "every":
                raise Refusal(Codes.BAD_PLAN, "repeat_period only goes with repeat=every")
            if not text.isascii() or not text.isdigit() or not 0 < int(text) <= MAX_HOURS:
                raise Refusal(Codes.BAD_PLAN, f"repeat_period={period!r} is not a whole number of hours > 0")
            period = int(text)
        return {"steps": out, "repeat": repeat, "repeat_period": period, "parent": self._parent(raw.get("parent"))}

    def _parent(self, key):
        if key in (None, ""):
            return None
        if not self.mind.has(key):
            raise Refusal(Codes.BAD_POINTER, f"plan parent {key!r} is not among your records")
        allowed = self.writes.ref_types(self.tk.spec.writes["g_parent"])
        if allowed and self.mind.by_key[key].type not in allowed:
            raise Refusal(Codes.BAD_PLAN, f"plan parent {key!r} is a {self.mind.by_key[key].type}, accepted: {list(allowed)}")
        return key

    def _step(self, i: int, st: dict, actor: Party) -> dict:
        g = self.tk.spec.gestures.get(st["gesture"])
        if g is None:
            raise Refusal(Codes.UNKNOWN_GESTURE, f"plan step {i + 1}: {st['gesture']!r}")
        refs = [p for p in g.params if p.kind == "ref"]
        target = st.get("target") or None
        if target is None:
            if any(not p.optional for p in refs):
                raise Refusal(Codes.BAD_PLAN, f"plan step {i + 1}: {g.id} needs a target")
            call, parties = {}, {}
        else:
            if not self.mind.has(target):
                raise Refusal(Codes.BAD_POINTER, f"plan step {i + 1}: {target!r} is not among your records")
            actual = self.mind.by_key[target].type
            if actual not in self.step_types:
                raise Refusal(Codes.BAD_POINTER, f"plan step {i + 1}: {target!r} is a {actual}, accepted: {list(self.step_types)}")
            kinds = self.params._targets(target)
            prm = refs[0] if refs and kinds & set(refs[0].accepts) else None          # a step points at the gesture's FIRST pointer
            if prm is None:
                raise Refusal(Codes.BAD_POINTER, f"plan step {i + 1}: {g.id} cannot act on {target!r}")
            call, parties = {prm.name: target}, {prm.name: self.mind.party(target)}
        v = self.tk.governor.check_gesture(g.id, call, actor, parties, executed=False, content_parties=self.mind.content_parties(),
                                           expand=self.mind.expand)
        if not v.allowed:
            raise Refusal(Codes.GOVERNOR + v.code, f"plan step {i + 1}: {v.reason}")
        return {"gesture": g.id, "target": target}


# ---------------------------------------------------------------------------------------------------- thoughts
class ThoughtChecker:
    """The written trace of a decision (T36): up to MAX_THOUGHTS thoughts, each ONE record the mind writes before the act.
    Every thought is a form the validator already knows, checked by the same code as the same thing written elsewhere:

      belief / belief_about   {kind, target: new|b:N, prop}              a proposition (belief_about: (believes ...)); b_proposition
      goal                    {kind, target: new|g:N, prop, mode, parent, deadline_h, when_h}   g_desired, g_mode, g_parent, g_deadline, g_when
      plan                    {kind, serves: g:N|g:new, steps, says, repeat, repeat_period}     the steps as a `plan`; says = i_speech

    The result is the normalised list; nothing here judges what the person thinks, only that it is well formed, bounded,
    pointed at real records and allowed (D10 through the same governor calls)."""

    KINDS = ("belief", "belief_about", "goal", "plan")
    MODE_WORDS = ("achieve", "maintain", "avoid")

    def __init__(self, tk: Toolkit, mind: Mind, params: ParamChecker, writes: "WriteChecker", speech: SpeechChecker):
        self.tk, self.mind, self.writes, self.speech = tk, mind, writes, speech
        self.plans = PlanChecker(tk, mind, params, writes)
        self.max = tk.spec.max_thoughts

    def check(self, raw: list, actor: Party) -> list:
        if len(raw) > self.max:
            raise Refusal(Codes.TOO_MANY_THOUGHTS, f"{len(raw)} > {self.max}")
        out, new_goal = [], False
        for i, t in enumerate(raw):
            kind = t.get("kind")
            if kind not in self.KINDS:
                raise Refusal(Codes.BAD_THOUGHT, f"thought {i + 1}: kind {kind!r} is not one of {list(self.KINDS)}")
            try:
                if kind == "plan":
                    one = self._plan(t, actor, new_goal)
                else:
                    one = self._record(kind, t, actor)
                    new_goal = new_goal or (kind == "goal" and one["target"] == "new")
            except Refusal as r:
                raise Refusal(r.code, f"thought {i + 1} ({kind}): {r.detail}") from None
            out.append(one)
        return out

    def _text(self, t: dict, name: str, required: bool = False) -> str:
        v = t.get(name, "")
        if v is None:
            v = ""
        if not isinstance(v, str):
            raise Refusal(Codes.BAD_SHAPE, f"{name} must be a string")
        if required and not v.strip():
            raise Refusal(Codes.BAD_THOUGHT, f"{name} is required")
        return v.strip()

    def _hours(self, t: dict, name: str):
        v = t.get(name)
        if v in (None, ""):
            return None
        if isinstance(v, bool) or not isinstance(v, (int, float, str)):
            raise Refusal(Codes.BAD_SHAPE, f"{name} must be a number of hours")
        return str(v)

    def _record(self, kind: str, t: dict, actor: Party) -> dict:
        target = self._text(t, "target") or "new"
        prop = self._text(t, "prop", required=True)
        out = {"kind": kind, "target": target}
        if kind == "goal":
            mode = self._text(t, "mode")
            head = prop[1:].split(None, 1)[0] if prop.startswith("(") else ""
            if head in self.MODE_WORDS:                       # "(achieve P)": the mode written as the head of the goal
                mode, prop = head, self._unwrap(prop, head)
            if mode and mode not in self.MODE_WORDS:
                raise Refusal(Codes.BAD_THOUGHT, f"mode {mode!r} is not one of {list(self.MODE_WORDS)}")
            out["mode"] = mode or None
        elif kind == "belief_about" and not prop.startswith("(believes"):
            raise Refusal(Codes.BAD_THOUGHT, "belief_about is a proposition (believes PERSON PROP)")
        var = "g_desired" if kind == "goal" else "b_proposition"
        w = self.writes._one(target, var, prop, None, actor)
        out["prop"] = w.value
        if kind == "goal":
            if out["mode"]:
                self._aux("g_mode", target, out["mode"], actor)
            parent = self._text(t, "parent")
            if parent:
                self._aux("g_parent", target, parent, actor)
            out["parent"] = parent or None
            for name, var2 in (("deadline_h", "g_deadline"), ("when_h", "g_when")):
                hours = self._hours(t, name)
                if hours is not None:
                    self._aux(var2, target, hours, actor)
                out[name] = float(hours) if hours is not None else None
        return out

    def _aux(self, var: str, target: str, value: str, actor: Party) -> None:
        """A companion field of a goal (mode, parent, deadline, start): checked as the write it stands for."""
        self.writes._structured(self.tk.spec.writes[var], target, target, value, actor)

    @staticmethod
    def _unwrap(prop: str, head: str) -> str:
        inner = prop.strip()[1:-1].strip() if prop.strip().endswith(")") else prop.strip()[1:]
        return inner[len(head):].strip()

    def _plan(self, t: dict, actor: Party, new_goal: bool) -> dict:
        steps = t.get("steps")
        if not isinstance(steps, list) or not steps:
            raise Refusal(Codes.BAD_PLAN, "a plan thought needs steps")
        if not all(isinstance(st, dict) and isinstance(st.get("gesture"), str) and isinstance(st.get("target", ""), (str, type(None)))
                   for st in steps):
            raise Refusal(Codes.BAD_SHAPE, "steps must be [{gesture, target}]")
        repeat, period = t.get("repeat"), t.get("repeat_period")
        for name, v in (("repeat", repeat), ("repeat_period", period)):
            if v is not None and (isinstance(v, bool) or not isinstance(v, (str, int))):
                raise Refusal(Codes.BAD_SHAPE, f"{name} must be a string or a whole number")
        plan = self.plans.check({"steps": steps, "repeat": repeat, "repeat_period": period}, actor)
        serves = self._text(t, "serves")
        if serves == "g:new":
            if not new_goal:
                raise Refusal(Codes.BAD_THOUGHT, "serves g:new, but no earlier thought creates a goal")
        elif serves:
            self.plans._parent(serves)
        says = self._text(t, "says")
        if says:                                              # a planned word is judged like a spoken one (D10: hearer, intimacy)
            expr = self.speech.check(says)
            v = self.tk.governor.check_utterance(expr, actor, self.mind.content_parties(None), addressees=None,
                                                 expand=self.mind.expand, said=True)
            if not v.allowed:
                raise Refusal(Codes.GOVERNOR + v.code, f"says: {v.reason}")
        return {"kind": "plan", "serves": serves or None, "steps": plan["steps"], "says": " ".join(says.split()) or None,
                "repeat": plan["repeat"], "repeat_period": plan["repeat_period"]}


class TraceChecker:
    """`incoherent_trace`: only a FORMAL contradiction (docs/14 10.1). The answer writes a plan, its act is not the first
    step of that plan, neither the act's gesture nor its target appears in any thought of the same answer, and the wake is
    not P0 or P1 (cause perception, speech, request). Whether the act really serves the goal is measured elsewhere (M2), never
    refused here."""

    URGENT = ("perception", "speech", "request")

    def __init__(self, tk: Toolkit, mind: Mind):
        self.tk, self.mind = tk, mind

    def check(self, thoughts: list, top_plan: dict | None, gesture, params: dict) -> None:
        plans = [t for t in thoughts if t["kind"] == "plan"] + ([top_plan] if top_plan else [])
        if not plans:
            return
        wake = self.mind.by_key.get("wake")
        if wake is not None and wake.fields.get("cause") in self.URGENT:
            return
        refs = [p for p in gesture.params if p.kind == "ref"]
        target = params.get(refs[0].name) if refs else None
        for p in plans:                                       # the act is the first step of a plan
            first = p["steps"][0]
            if first["gesture"] == gesture.id and (first["target"] or None) in (None, target):
                return
        if any(st["gesture"] == gesture.id for p in plans for st in p["steps"]):
            return
        if target is not None and target in self._keys(thoughts):
            return
        raise Refusal(Codes.INCOHERENT_TRACE, f"you wrote a plan, but {gesture.id}" + (f" on {target}" if target else "") +
                      " appears in none of your thoughts and is not its first step")

    @staticmethod
    def _keys(thoughts: list) -> set:
        text = []
        for t in thoughts:
            for k in ("prop", "says", "target", "serves", "parent"):
                if isinstance(t.get(k), str):
                    text.append(t[k])
            text += [st["target"] for st in t.get("steps", []) if st.get("target")]
        return set(re.findall(r"[@\w:.]+", " ".join(text).replace("(", " ").replace(")", " ")))


# ---------------------------------------------------------------------------------------------------- the validator
class AnswerValidator:
    """validate(raw JSON text, situation) -> Outcome."""

    def __init__(self, tk: Toolkit | None = None, truth_factory=None):
        self.tk = tk or Toolkit()
        self.truth_factory = truth_factory or self._scene_truth

    def _scene_truth(self, situation) -> TruthSource:
        return SceneTruth(situation.scene, situation.context.records, self.tk.interface.token_types["ENTITY"]["count"],
                          getattr(situation, "people", None) or None)

    def validate(self, text: str, situation) -> Outcome:
        why = ""
        try:
            data = self._load(text)
            why = data["why"] if isinstance(data.get("why"), str) else ""
            try:
                mind = Mind(self.tk, situation.context.records, self.truth_factory(situation))
            except TruthError as e:
                raise Refusal(Codes.TRUTH_ERROR, str(e)) from None
            return Outcome(self._decide(data, mind), why=why)
        except Refusal as r:
            return Outcome(None, r.code, r.detail, why)

    # ---- raw answer
    def _load(self, text: str) -> dict:
        s = text.strip()
        if s.startswith("```"):
            s = s.strip("`")
            s = s[4:] if s.lower().startswith("json") else s
        try:
            data = json.loads(s)
        except (TypeError, ValueError) as e:
            raise Refusal(Codes.INVALID_JSON, str(e)) from None
        if not isinstance(data, dict):
            raise Refusal(Codes.BAD_SHAPE, "the answer must be a JSON object")
        if not isinstance(data.get("gesture"), str):
            raise Refusal(Codes.BAD_SHAPE, "gesture must be a string")
        if not isinstance(data.get("speech", ""), str):
            raise Refusal(Codes.BAD_SHAPE, "speech must be a string")
        if "stop" in data and not isinstance(data["stop"], (str, type(None))):
            raise Refusal(Codes.BAD_SHAPE, "stop must be a string")
        plan = data.get("plan")
        if plan is not None:
            steps = plan.get("steps", []) if isinstance(plan, dict) else None
            if not isinstance(steps, list) or not all(
                    isinstance(st, dict) and isinstance(st.get("gesture"), str) and isinstance(st.get("target", ""), (str, type(None)))
                    for st in steps):
                raise Refusal(Codes.BAD_SHAPE, "plan must be {steps: [{gesture, target}], repeat, repeat_period, parent}")
            for k in ("repeat", "parent"):
                if not isinstance(plan.get(k, ""), (str, type(None))):
                    raise Refusal(Codes.BAD_SHAPE, f"plan.{k} must be a string")
            if not isinstance(plan.get("repeat_period", ""), (str, int, type(None))) or isinstance(plan.get("repeat_period"), bool):
                raise Refusal(Codes.BAD_SHAPE, "plan.repeat_period must be a string or a whole number")
        thoughts = data.get("thoughts")
        if thoughts is not None and (not isinstance(thoughts, list) or not all(isinstance(t, dict) for t in thoughts)):
            raise Refusal(Codes.BAD_SHAPE, "thoughts must be a list of objects")
        for name, keys in (("params", ("name", "value")), ("writes", ("target", "variable", "value"))):
            lst = data.get(name, [])
            if not isinstance(lst, list):
                raise Refusal(Codes.BAD_SHAPE, f"{name} must be a list")
            for item in lst:
                if not isinstance(item, dict) or not all(isinstance(item.get(k), str) for k in keys):
                    raise Refusal(Codes.BAD_SHAPE, f"every item of {name} needs string fields {list(keys)}")
        return data

    # ---- decision
    def _decide(self, data: dict, mind: Mind) -> Decision:
        tk = self.tk
        gesture = tk.spec.gestures.get(data["gesture"])
        if gesture is None:
            raise Refusal(Codes.UNKNOWN_GESTURE, repr(data["gesture"]))
        raw_writes = data.get("writes", [])
        if len(raw_writes) > tk.spec.max_writes:
            raise Refusal(Codes.TOO_MANY_WRITES, f"{len(raw_writes)} > {tk.spec.max_writes}")
        params, parties = ParamChecker(tk, mind).check(gesture, data.get("params", []))
        speech_checker = SpeechChecker(tk, mind)
        speech_text = data.get("speech", "").strip()
        expr_param, expression = gesture.expression_param, None
        if expr_param is not None:
            if not speech_text:
                raise Refusal(Codes.BAD_SPEECH, f"{gesture.id} needs a speech")
            expression = speech_checker.check(speech_text)
        elif speech_text:
            raise Refusal(Codes.BAD_SPEECH, f"{gesture.id} takes no speech")
        actor = mind.me_party()
        # the governor on the gesture (the content is part of the gesture)
        call = dict(params)
        if expression is not None:
            call[expr_param.name] = expression
        you = parties.get("to") if gesture.id == "speak" else None
        v = tk.governor.check_gesture(gesture.id, call, actor, parties, executed=True,
                                      content_parties=mind.content_parties(you), expand=mind.expand)
        if not v.allowed:
            raise Refusal(Codes.GOVERNOR + v.code, v.reason)
        write_checker = WriteChecker(tk, mind, speech_checker)
        writes, notes = write_checker.check(raw_writes, actor)
        stop = None
        if "stop" in data:
            text = (data["stop"] or "").strip()
            if text and gesture.params and any(p.kind == "condition" for p in gesture.params):
                raise Refusal(Codes.BAD_PARAM, f"{gesture.id} has its own stop parameter: no separate decision stop")
            stop = ParamChecker(tk, mind).conditions.check(text) if text else None
        plan = None
        if data.get("plan") is not None:
            plan = PlanChecker(tk, mind, ParamChecker(tk, mind), write_checker).check(data["plan"], actor)
        thoughts = None
        if data.get("thoughts") is not None:
            thoughts = ThoughtChecker(tk, mind, ParamChecker(tk, mind), write_checker, speech_checker).check(data["thoughts"], actor)
            TraceChecker(tk, mind).check(thoughts, plan, gesture, params)
        return Decision(gesture.id, params, " ".join(speech_text.split()) if expression is not None else None, writes,
                        notes, gesture.family, plan, "plan" in data, stop, "stop" in data, thoughts, "thoughts" in data)
