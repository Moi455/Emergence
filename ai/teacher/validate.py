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
    GOVERNOR = "governor:"
    ALL = (INVALID_JSON, BAD_SHAPE, UNKNOWN_GESTURE, TOO_MANY_WRITES, BAD_PARAM, BAD_POINTER, BAD_SPEECH, BAD_WRITE, UNKNOWN_OLD, TRUTH_ERROR)


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

    def to_dict(self) -> dict:
        return {"gesture": self.gesture, "params": self.params, "speech": self.speech,
                "writes": [{"target": w.target, "variable": w.variable, "value": w.value, "verdict": w.verdict}
                           for w in self.writes], "notes": self.notes}


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
    """Maps @E keys to the true ages of the scene. situations.mind assigns @E<i> in the order present(known or
    near) then absent, cut at the ENTITY budget; the mapping is rebuilt here and cross-checked against the names in
    the records (names, and the apparent age against the true one), so a change in the sampler is detected instead
    of silently giving wrong ages."""

    AGE_TOLERANCE = 5.0         # the sampler blurs a seen age by at most 4 years

    def __init__(self, scene, records, entity_budget: int):
        self.people: dict[str, object] = {"me": scene.self_}
        self.ages: dict[str, float] = {"me": scene.self_.age}
        people = [x.person for x in scene.present if x.known or x.dist < 15] + [p for p, _ in scene.absent]
        for i, person in enumerate(people[:entity_budget]):
            key = f"@E{i + 1}"
            rec = next((r for r in records if r.key == key), None)
            if rec is not None and rec.fields.get("name") not in (None, person.name):
                raise TruthError(f"{key}: record name {rec.fields.get('name')} != scene name {person.name}")
            seen = rec.fields.get("look.age") if rec is not None else None
            if seen is not None and abs(seen - person.age) > self.AGE_TOLERANCE:      # strangers carry no name to compare
                raise TruthError(f"{key}: looks {seen} but the scene person is {person.age}: the key map drifted")
            self.ages[key] = person.age
            self.people[key] = person

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
            return Party(real_age=self.truth.real_age(key), believed_age=self._believed.get(key, seen), apparent_age=seen,
                         resolved=rec.fields.get("known_by") == "seen")
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

    # ---- enum, word, bool, mref, time
    def _structured(self, wv, target, key, value, actor) -> Write:
        parsed: object = value
        if wv.scale == "bool":
            if value not in ("true", "false"):
                raise Refusal(Codes.BAD_WRITE, f"{wv.id}: expected true or false")
            parsed = value == "true"
        elif wv.scale == "time":
            if not NUMBER.match(value) or not 0 <= float(value) <= MAX_HOURS:
                raise Refusal(Codes.BAD_WRITE, f"{wv.id}: {value!r} is not a number of hours in 0..{MAX_HOURS:g}")
            parsed = float(value)
        elif wv.scale == "mref":
            if not self.mind.has(value):
                raise Refusal(Codes.BAD_POINTER, f"{wv.id}={value!r} is not among your records")
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
        v = self.gov.check_record(PROPOSITION_KIND[wv.target_kind], e, actor, self.mind.content_parties(),
                                  expand=self.mind.expand)
        if not v.allowed:
            raise Refusal(Codes.GOVERNOR + v.code, v.reason)
        return Write(target, wv.id, " ".join(value.split()), v.code)


# ---------------------------------------------------------------------------------------------------- the validator
class AnswerValidator:
    """validate(raw JSON text, situation) -> Outcome."""

    def __init__(self, tk: Toolkit | None = None, truth_factory=None):
        self.tk = tk or Toolkit()
        self.truth_factory = truth_factory or self._scene_truth

    def _scene_truth(self, situation) -> TruthSource:
        return SceneTruth(situation.scene, situation.context.records, self.tk.interface.token_types["ENTITY"]["count"])

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
        writes, notes = WriteChecker(tk, mind, speech_checker).check(raw_writes, actor)
        return Decision(gesture.id, params, " ".join(speech_text.split()) if expression is not None else None, writes,
                        notes, gesture.family)
