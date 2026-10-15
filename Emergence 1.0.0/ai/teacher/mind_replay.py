"""mind_replay.py - replays the mind of an NPC step by step from a planner line (T11b, docs/14 10.1, docs/09 "pensée écrite").

A planner line (`--planner`, T36) carries the teacher's written trace `decision.thoughts` (0 to 5 thoughts, each ONE
record: belief, belief_about, goal, plan) and then the act. The student has no head for the trace as such; what it can
learn is the thing the game will ask of it: one `reflect` decision at a time, each writing ONE record and saying whether
to go on thinking, then the `act`. This module turns one planner line into those decisions, in the format of the labels
file (`emergence-labels-1`), so that `student2.data.LabelDataset` reads them as they are:

    state 0 ──thought 1──► state 1 ──thought 2──► state 2 ... ──► state n ──act
    (reflect, budget 5)    (reflect, budget 4)                      (act, budget 5 - n)

For a line with n >= 1 thoughts it writes n `reflect` lines and one `act` line (ids `<id>#r0` .. `<id>#r<n-1>`, `<id>#a`);
for n = 0 the line is kept as it is (`<id>#a`). Everything below follows the conventions of the project:

  * a reflect decision is the existing decision format: the gesture is the placeholder `stop` (the body does nothing while
    the mind thinks; the engine ignores the gesture in `reflect` mode), `writes` holds `think_more` on `me` (true except at
    the last thought) and the ONE record written: `b_proposition` / `g_desired` on `new` (or on the key of the record it
    revises) with the proposition as value, or nothing more for a plan, which is the `plan` label (steps, repeat, period,
    parent = the goal it serves; `g:new` becomes the key the goal got when it was written at an earlier step). Thoughts
    that are not a plan carry `plan: null` (an explicit "no plan"). The student's existing heads learn all of this: the
    write chain (target `new` + the sentence decoder) and the plan head. No catalogue, interface or registry change.
  * the next state is the context WITH the record the thought wrote (key = next free number of its kind; a pointer is a
    record KEY, never a slot; the new record is the first of its kind and, when the kind is full, the least salient
    record that nothing in the line mentions is evicted: its key stays in `known_keys`, so pointers to it become ghosts).
  * `WAKE.mode` is `reflect` and `WAKE.budget` decreases by one at each step (a fixed grant of 5, so that the number of
    thoughts of the line is NOT readable from the budget); the act state keeps the original mode (`reflect` becomes `act`).
  * nothing true enters the tokens: only the thought's own text (already checked against the keys of the mind) and
    fixed defaults for the fields the engine fills in (source `inferred`, certainty 5, importance 5, ...).
  * D10 and the governor at every step: each thought is re-checked by the REAL `ThoughtChecker` on the mind of the state it
    is written in (grammar, pointers, `check_record`, `check_gesture` for every plan step), the new state must tokenise, and
    the act is re-validated by the REAL `AnswerValidator` on the final state. A line any step of which fails is refused whole
    and counted with its reason: nothing is bent. (`situations.audit` needs the scene, which a labels line does not carry;
    it was run when the situation was sampled, and the only text added since goes through the governor.)

    cd ai && python3 -m teacher.mind_replay --in ~/.../dataset.jsonl --out /tmp/replay.jsonl      # never in place
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

from tok2 import DecisionContext, Record, Tokenizer
from tok2.errors import TokenError

from .dataset import DatasetError, LabelRecord
from .migrate import AgeTruth, Migration
from .toolkit import Toolkit
from .validate import AnswerValidator, Mind, ParamChecker, Refusal, SpeechChecker, ThoughtChecker, WriteChecker

REFLECT_GESTURE = "stop"             # placeholder gesture of a reflect decision (no parameter, no condition, no speech)
THINK_MORE = "think_more"            # the catalogue variable "go on thinking" (written on `me`)
BUDGET = 5                           # the grant of thinking steps the scheduler gives (= teacher spec max_thoughts)
KEY_IN_TEXT = re.compile(r"@[ETGLV][0-9]+|[bmghqcpkt]:[0-9]+")
PROPOSITION_VARIABLE = {"belief": "b_proposition", "belief_about": "b_proposition", "goal": "g_desired"}
RECORD_OF = {"belief": ("BELIEF", "b:"), "belief_about": ("BELIEF", "b:"), "goal": ("GOAL", "g:"), "plan": ("PLAN", "p:")}


class ReplayError(ValueError):
    """The line cannot be replayed; `code` is the reason it is counted under."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code, self.detail = code, detail


# ---------------------------------------------------------------------------------------------------- reading a decision
def kind_of_decision(decision: dict) -> str | None:
    """Which thought a reflect decision writes: plan, goal, belief, belief_about (None: it writes nothing a thought is)."""
    if decision.get("plan"):
        return "plan"
    for w in decision.get("writes") or []:
        if w.get("variable") == "g_desired":
            return "goal"
        if w.get("variable") == "b_proposition":
            return "belief_about" if str(w.get("value", "")).lstrip("( ").startswith("believes") else "belief"
    return None


def thought_of_decision(decision: dict) -> dict | None:
    """A reflect decision (stored or predicted) as the thought the teacher format would carry (checked by ThoughtChecker)."""
    kind = kind_of_decision(decision)
    if kind is None:
        return None
    if kind == "plan":
        p = decision["plan"]
        return {"kind": "plan", "serves": p.get("parent") or "", "steps": [dict(s) for s in p.get("steps") or []],
                "repeat": p.get("repeat"), "repeat_period": p.get("repeat_period")}
    w = next(w for w in decision["writes"] if w["variable"] == PROPOSITION_VARIABLE[kind])
    return {"kind": kind, "target": w["target"], "prop": w["value"]}


def think_more_of(decision: dict) -> bool | None:
    for w in decision.get("writes") or []:
        if w.get("variable") == THINK_MORE:
            return bool(w["value"]) if not isinstance(w["value"], str) else w["value"] == "true"
    return None


def is_reflect(decision: dict) -> bool:
    return think_more_of(decision) is not None


# ---------------------------------------------------------------------------------------------------- the state of a mind
@dataclass
class MindState:
    """The records of one decision and the keys of the whole mind. Copies are cheap (records are copied on write)."""
    records: list
    known: set

    @classmethod
    def of(cls, ctx: dict, tokenizer: Tokenizer) -> "MindState":
        c = DecisionContext.loads(json.dumps(ctx), tokenizer)
        return cls([Record(r.type, r.key, copy.deepcopy(r.fields)) for r in c.records], set(c.mind_keys()))

    def copy(self) -> "MindState":
        return MindState([Record(r.type, r.key, copy.deepcopy(r.fields)) for r in self.records], set(self.known))

    def record(self, key: str) -> Record | None:
        return next((r for r in self.records if r.key == key), None)

    def of_type(self, type_: str) -> list:
        return [r for r in self.records if r.type == type_]

    def next_key(self, prefix: str) -> str:
        top = max([int(k[len(prefix):]) for k in self.known if k.startswith(prefix) and k[len(prefix):].isdigit()] or [0])
        return f"{prefix}{top + 1}"

    def wake(self) -> Record:
        w = self.record("wake")
        if w is None:
            raise ReplayError("no_wake", "the context has no WAKE record")
        return w

    def with_wake(self, mode: str, budget: int) -> "MindState":
        s = self.copy()
        s.wake().fields.update(mode=mode, budget=budget)
        return s

    def context(self, tokenizer: Tokenizer) -> dict:
        return DecisionContext(list(self.records), sorted(self.known)).to_dict(tokenizer)


class RecordWriter:
    """What the mind looks like after ONE thought: the record it writes (new, or a revision of an existing one)."""

    def __init__(self, tk: Toolkit):
        self.cap = {t: v["count"] for t, v in tk.interface.token_types.items()}

    def apply(self, state: MindState, thought: dict, protected: set) -> tuple[MindState, str]:
        """-> (next state, key of the record written). `thought` is the normalised one (ThoughtChecker's output) whose
        `serves` has been resolved to a real key. The input state is not modified."""
        s = state.copy()
        kind = thought["kind"]
        type_, prefix = RECORD_OF[kind]
        target = thought.get("target", "new")
        if kind != "plan" and target != "new":                       # a revision: same record, new content
            rec = s.record(target)
            if rec is None:
                raise ReplayError("revised_record_missing", target)
            rec.fields["prop"] = thought["prop"]
            if kind == "goal":
                self._goal_extras(rec.fields, thought, revise=True)
            return s, target
        key = s.next_key(prefix)
        fields = {"belief": self._belief, "belief_about": self._belief, "goal": self._goal, "plan": self._plan}[kind](thought)
        if kind == "plan":
            served = thought.get("serves") or ""
            for old in [r for r in s.of_type("PLAN") if served and r.fields.get("goal") == served and r.key not in protected]:
                s.records.remove(old)                                # a new plan for the same goal replaces the old memo
            goal = s.record(served) if served else None
            if goal is not None:
                goal.fields["has_plan"] = True
        self._make_room(s, type_, protected)
        first = next((i for i, r in enumerate(s.records) if r.type == type_), len(s.records))
        s.records.insert(first, Record(type_, key, fields))
        s.known.add(key)
        return s, key

    def _make_room(self, s: MindState, type_: str, protected: set) -> None:
        same = s.of_type(type_)
        if len(same) < self.cap[type_]:
            return
        for victim in reversed(same):                                # the least salient record nothing mentions
            if victim.key not in protected:
                s.records.remove(victim)
                return
        raise ReplayError("no_room", f"{type_} is full and every record of it is mentioned in the line")

    @staticmethod
    def _belief(t: dict) -> dict:
        return {"prop": t["prop"], "source": "inferred", "age": 0.0, "contradicted": False, "hops": 0, "certainty": 5.0,
                "informant": "", "shared": [], "importance": 5.0, "polarity": True, "secret": False, "weight": 0.0}

    @classmethod
    def _goal(cls, t: dict) -> dict:
        f = {"prop": t["prop"], "mode": t.get("mode") or "achieve", "status": "active", "origin": "self", "origin_ref": "",
             "age": 0.0, "progress": 0.0, "priority": 5.0, "has_plan": False}
        cls._goal_extras(f, t, revise=False)
        return f

    @staticmethod
    def _goal_extras(f: dict, t: dict, revise: bool) -> None:
        if t.get("mode"):
            f["mode"] = t["mode"]
        if t.get("parent"):
            f["parent"] = t["parent"]
        for name, field_ in (("deadline_h", "deadline"), ("when_h", "when")):
            if t.get(name) is not None:
                f[field_] = float(t[name])

    @staticmethod
    def _plan(t: dict) -> dict:
        steps = [s["gesture"] for s in t["steps"]]
        targets = [s["target"] for s in t["steps"] if s.get("target")]
        f = {"step": "", "next": steps[0], "goal": t.get("serves") or "", "target": t["steps"][0].get("target") or "",
             "steps": steps, "step_targets": targets[:4], "status": "running", "progress": 0.0, "attempts": 0,
             "repeat": t.get("repeat") or "once", "commitment": 5.0}
        if t.get("repeat_period") is not None:
            f["repeat_period"] = int(t["repeat_period"])
        if t.get("says"):
            f["says"] = t["says"]
        return f


# ---------------------------------------------------------------------------------------------------- judging
class StepJudge:
    """The real checkers, run on the mind of a state: is this thought allowed there? (also used by student2.evaluate)"""

    def __init__(self, tk: Toolkit):
        self.tk = tk
        self.validator = AnswerValidator(tk, truth_factory=lambda s: AgeTruth(s.ages))

    def mind(self, records: list, ages: dict) -> Mind:
        return Mind(self.tk, records, AgeTruth(ages or {}))

    def thought(self, records: list, ages: dict, thought: dict) -> tuple[dict | None, str]:
        """-> (the thought as the checker normalises it, "") or (None, refusal code)."""
        mind = self.mind(records, ages)
        speech = SpeechChecker(self.tk, mind)
        checker = ThoughtChecker(self.tk, mind, ParamChecker(self.tk, mind), WriteChecker(self.tk, mind, speech), speech)
        try:
            return checker.check([thought], mind.me_party())[0], ""
        except Refusal as r:
            return None, r.code
        except Exception as e:                                       # noqa: BLE001  (a crash is counted, never hidden)
            return None, f"crash:{type(e).__name__}"

    def act(self, records: list, ages: dict, decision: dict) -> str:
        sit = SimpleNamespace(context=SimpleNamespace(records=records), ages=ages or {}, scene=None)
        try:
            o = self.validator.validate(Migration.raw_answer(decision), sit)
        except Exception as e:                                       # noqa: BLE001
            return f"crash:{type(e).__name__}"
        return "ok" if o.ok else o.code


# ---------------------------------------------------------------------------------------------------- the replay
@dataclass
class ReplayStep:
    kind: str                       # "reflect" or "act"
    thought_kind: str | None        # belief | belief_about | goal | plan (reflect steps)
    record: LabelRecord


@dataclass
class ReplayResult:
    steps: list = field(default_factory=list)
    error: ReplayError | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


class MindReplay:
    """Planner line -> reflect lines + the act line. See the module docstring."""

    def __init__(self, tk: Toolkit | None = None, tokenizer: Tokenizer | None = None, budget: int = BUDGET):
        self.tk = tk or Toolkit()
        self.tok = tokenizer or Tokenizer(self.tk.interface, grammar=self.tk.vocab)
        self.budget = budget
        self.writer = RecordWriter(self.tk)
        self.judge = StepJudge(self.tk)

    # ---- one line
    def replay(self, rec: LabelRecord) -> ReplayResult:
        try:
            return ReplayResult(self._steps(rec))
        except ReplayError as e:
            return ReplayResult(error=e)
        except TokenError as e:
            return ReplayResult(error=ReplayError("token_error", str(e)[:120]))

    def _steps(self, rec: LabelRecord) -> list:
        d = rec.decision
        thoughts = list(d.get("thoughts") or [])
        ages = rec.source.get("ages") if isinstance(rec.source.get("ages"), dict) else {}
        act = {k: copy.deepcopy(v) for k, v in d.items() if k != "thoughts"}
        state = MindState.of(rec.context, self.tok)
        if not thoughts:
            return [self._act_step(rec, state, act, ages, n=0, mode=None)]
        if len(thoughts) > self.budget:
            raise ReplayError("too_many_thoughts", f"{len(thoughts)} > {self.budget}")
        protected = set(KEY_IN_TEXT.findall(json.dumps(d))) | {"me", "me.mind", "me.state", "wake", "@PLACE"}
        out, last_goal = [], None
        for k, raw in enumerate(thoughts):
            here = state.with_wake("reflect", self.budget - k)
            t = copy.deepcopy(raw)
            if t.get("kind") == "plan" and t.get("serves") == "g:new":
                if last_goal is None:
                    raise ReplayError("serves_unwritten_goal", "g:new but no earlier thought wrote a goal")
                t["serves"] = last_goal
            checked, code = self.judge.thought(here.records, ages, t)
            if checked is None:
                raise ReplayError(f"thought_refused:{code}", f"thought {k + 1} ({t.get('kind')})")
            nxt, key = self.writer.apply(here, checked, protected)
            if checked["kind"] == "goal" and checked["target"] == "new":
                last_goal = key
            more = k < len(thoughts) - 1
            out.append(ReplayStep("reflect", checked["kind"], self._reflect_line(rec, here, checked, more, k, len(thoughts))))
            self._must_tokenise(nxt)
            state = nxt.with_wake(state.wake().fields["mode"], self.budget - k - 1)
        mode = "act" if rec_mode(rec) == "reflect" else rec_mode(rec)
        out.append(self._act_step(rec, state.with_wake(mode, max(0, self.budget - len(thoughts))), act, ages, len(thoughts), mode))
        return out

    def _must_tokenise(self, state: MindState) -> None:
        try:
            self.tok.encode(DecisionContext(list(state.records), sorted(state.known)))
        except TokenError as e:
            raise ReplayError("token_error", str(e)[:120]) from None

    # ---- the lines
    def _line(self, rec: LabelRecord, state: MindState, decision: dict, tag: str, info: dict) -> LabelRecord:
        source = copy.deepcopy(rec.source)
        source["index"] = f"{source.get('index')}#{tag}"
        source["replay"] = info | {"of": rec.id}
        return LabelRecord(state.context(self.tok), decision, rec.verdict, source, rec.synthetic)

    def _reflect_line(self, rec: LabelRecord, state: MindState, thought: dict, more: bool, k: int, n: int) -> LabelRecord:
        kind = thought["kind"]
        writes = [{"target": "me", "variable": THINK_MORE, "value": more, "verdict": "ok"}]
        plan = None
        if kind == "plan":
            plan = {"steps": [{"gesture": s["gesture"], "target": s["target"]} for s in thought["steps"]],
                    "repeat": thought["repeat"], "repeat_period": thought["repeat_period"], "parent": thought.get("serves")}
        else:
            writes.append({"target": thought["target"], "variable": PROPOSITION_VARIABLE[kind], "value": thought["prop"],
                           "verdict": "ok"})
        decision = {"gesture": REFLECT_GESTURE, "params": {}, "speech": None, "writes": writes, "notes": [], "plan": plan,
                    "mode": "reflect"}
        return self._line(rec, state, decision, f"r{k}", {"step": k, "steps": n, "kind": kind,
                                                          "budget": int(state.wake().fields["budget"])})

    def _act_step(self, rec: LabelRecord, state: MindState, act: dict, ages: dict, n: int, mode) -> ReplayStep:
        code = self.judge.act(state.records, ages, act)
        if code != "ok":
            raise ReplayError(f"act_refused:{code}", "the act no longer validates after the thoughts")
        self._must_tokenise(state)
        decision = act | {"mode": rec_mode(rec) if mode is None else mode}
        return ReplayStep("act", None, self._line(rec, state, decision, "a", {"step": n, "steps": n, "kind": "act",
                                                                               "budget": int(state.wake().fields["budget"])}))


def rec_mode(rec: LabelRecord) -> str:
    for r in rec.context["records"]:
        if r["type"] == "WAKE":
            return r["fields"].get("mode", "act")
    return "act"


# ---------------------------------------------------------------------------------------------------- a file
@dataclass
class ReplayReport:
    lines: int = 0
    with_thoughts: int = 0
    valid_before: int = 0                     # lines the validator accepted whole, thoughts included (the baseline)
    replayed: int = 0                         # of those, lines replayed without a refusal
    thought_steps: Counter = field(default_factory=Counter)      # reflect lines written, by thought kind
    act_steps: int = 0
    refused: Counter = field(default_factory=Counter)

    @property
    def valid_rate(self) -> float | None:
        return self.replayed / self.valid_before if self.valid_before else None

    def to_dict(self) -> dict:
        return {"lines": self.lines, "lines_with_thoughts": self.with_thoughts, "valid_before": self.valid_before,
                "replayed_ok": self.replayed, "valid_rate": self.valid_rate, "reflect_examples": sum(self.thought_steps.values()),
                "reflect_by_kind": dict(self.thought_steps), "act_examples": self.act_steps,
                "refused_by_reason": dict(self.refused.most_common())}


def replay_file(src: Path, dst: Path, limit: int | None = None, replay: MindReplay | None = None) -> ReplayReport:
    """`src` is only read (the series may be alive); `dst` is written whole, atomically."""
    if Path(src).resolve() == Path(dst).resolve():
        raise ValueError("mind_replay never rewrites its input in place")
    mr = replay or MindReplay()
    base = AnswerValidator(mr.tk, truth_factory=lambda s: AgeTruth(s.ages))
    rep = ReplayReport()
    tmp = Path(str(dst) + ".tmp")
    with open(src, encoding="utf-8") as f, open(tmp, "w", encoding="utf-8") as out:
        for n, line in enumerate(f):
            if limit is not None and n >= limit:
                break
            if not line.strip():
                continue
            try:
                rec = LabelRecord.from_line(line)
            except DatasetError:
                rep.refused["not_a_label_line"] += 1
                continue
            rep.lines += 1
            thoughts = rec.decision.get("thoughts") or []
            rep.with_thoughts += bool(thoughts)
            ages = rec.source.get("ages") if isinstance(rec.source.get("ages"), dict) else {}
            ok_before = mr.judge.act(MindState.of(rec.context, mr.tok).records, ages, rec.decision) == "ok"
            rep.valid_before += ok_before
            res = mr.replay(rec)
            if not res.ok:
                rep.refused[res.error.code] += 1
                continue
            rep.replayed += ok_before
            for st in res.steps:
                out.write(st.record.to_line() + "\n")
                if st.kind == "act":
                    rep.act_steps += 1
                else:
                    rep.thought_steps[st.thought_kind] += 1
        out.flush()
    tmp.replace(dst)
    return rep


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--in", dest="src", type=Path, required=True, help="a planner dataset.jsonl (read only: copy it first if the series is alive)")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--report", type=Path, default=None)
    a = ap.parse_args(argv)
    rep = replay_file(a.src, a.out, a.limit).to_dict()
    print(json.dumps(rep, indent=1))
    if a.report:
        a.report.write_text(json.dumps(rep, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
