"""planner_measure.py - T36 acceptance WITHOUT network: how many planner-mode answers are valid, with a trace.

    python3 -m teacher.planner_measure --n 120 --seed 0          # scripted stand-in answers: no network, no quota

A stand-in teacher (`ScriptedPlanner`) writes, for each situation of the sampler, an answer in the planner format built only
from keys and propositions of that situation's own records (so it is well formed), with a fixed share of deliberate defects.
It goes through the REAL path of the generator: BatchInstructions/BatchSchema (thoughts), GroupedRound, AnswerValidator,
the governor, and the repair pass. So the figures below measure the PLUMBING (format, validator, repair, accounting), and say
NOTHING about what Gemini will write: that is the real series (`--planner`, see the README).

    ScriptedPlanner    one scripted answer per situation (shapes: no trace, belief, goal+plan, plan on the act, defects)
    ScriptedCaller     the `caller(system, user, schema)` of GroupedRound, answering from the script; the repair gets a plain act
    PlannerMeasure     runs the rounds and counts: valid, valid with a trace, trace among non-urgent situations, passive share,
                       refusals by code (incoherent_trace included), repaired
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from dataclasses import dataclass, field

from .batch import BatchInstructions, BatchPrompt, BatchSchema, GroupedRound
from .gemini import ApiResult
from .phrasebook import PhraseBook
from .render import SituationRenderer
from .schema import DecisionSchema
from .spec import PASSIVE_GESTURES
from .toolkit import Toolkit
from .validate import AnswerValidator

URGENT = ("perception", "speech", "request")
SHAPES = ("plain", "belief", "goal_plan", "plan_on_act", "plain", "belief", "goal_plan", "plan_on_act", "incoherent", "bad_pointer")


class ScriptedPlanner:
    """Answer scripts keyed by the situation. The act is `wait` (always legal) or `go` to a known place when there is one."""

    def __init__(self, tk: Toolkit):
        self.tk = tk
        self.phrases = [p.text for p in PhraseBook(tk, 30).select()]

    @staticmethod
    def _keys(sit, type_name: str) -> list:
        return [r.key for r in sit.context.records if r.type == type_name]

    @staticmethod
    def _prop(sit, type_name: str) -> str | None:
        for r in sit.context.records:
            if r.type == type_name and r.fields.get("prop"):
                return r.fields["prop"]
        return None

    def answer(self, sit, shape: str) -> dict:
        place = (self._keys(sit, "LOCUS") or [None])[0]
        wait = {"gesture": "wait", "params": [{"name": "until", "value": "(c_elapsed 30)"}], "speech": "", "writes": []}
        go = {"gesture": "go", "params": [{"name": "target", "value": place}, {"name": "relation", "value": "toward"},
                                           {"name": "pace", "value": "walk"}, {"name": "stealth", "value": "open"}], "speech": "", "writes": []}
        act = go if place and shape in ("goal_plan", "plan_on_act") else wait
        thoughts: list = []
        belief = self._prop(sit, "BELIEF")
        if shape == "belief" and belief:
            thoughts = [{"kind": "belief", "target": "new", "prop": belief}]
        elif shape == "goal_plan" and place:
            goal = self._prop(sit, "GOAL") or "(has me bread_loaf)"
            thoughts = [{"kind": "goal", "target": "new", "prop": goal, "mode": "achieve", "deadline_h": "24"},
                        {"kind": "plan", "serves": "g:new", "steps": [{"gesture": "go", "target": place}], "repeat": "once"}]
        elif shape == "plan_on_act" and place:
            thoughts = [{"kind": "plan", "steps": [{"gesture": "go", "target": place}, {"gesture": "wait", "target": ""}]}]
        elif shape == "incoherent" and place:                         # a plan to go, and an act that has nothing to do with it
            thoughts = [{"kind": "plan", "steps": [{"gesture": "go", "target": place}]}]
        elif shape == "bad_pointer":
            thoughts = [{"kind": "belief", "target": "new", "prop": "(owns @E99 @T99)"}]
        return {"why": "scripted", "thoughts": thoughts, **act}


class ScriptedCaller:
    """caller(system, user, schema) -> (model, ApiResult). The first request answers from the script; a repair request
    (its text begins with REPAIR) answers every refused situation with a plain act and no thought."""

    def __init__(self, planner: ScriptedPlanner, plan: dict):
        self.planner, self.plan = planner, plan            # plan: label -> (situation, shape)
        self.requests = 0

    def __call__(self, system: str, user: str, schema: dict):
        self.requests += 1
        labels = re.findall(r"=== SITUATION (S\d+) ===", user)
        repair = user.startswith("REPAIR")
        out = []
        for label in labels:
            sit, shape = self.plan[label]
            item = self.planner.answer(sit, "plain" if repair else shape)
            if repair:
                item["thoughts"] = []
            out.append({"id": label, **item})
        return "scripted", ApiResult(True, 200, json.dumps({"decisions": out}), "STOP", {}, 0.0)


@dataclass
class Tally:
    asked: int = 0
    valid: int = 0
    valid_first: int = 0
    repaired: int = 0
    with_trace: int = 0
    non_urgent: int = 0
    non_urgent_trace: int = 0
    passive: int = 0
    refused: Counter = field(default_factory=Counter)

    def line(self) -> str:
        pc = lambda a, b: f"{100 * a / b:.1f}%" if b else "n/a"          # noqa: E731
        return "\n".join([
            f"situations asked              {self.asked}",
            f"valid (after repair)          {self.valid}  ({pc(self.valid, self.asked)})   at the first shot {self.valid_first} "
            f"({pc(self.valid_first, self.asked)}), repaired {self.repaired}",
            f"valid with a non-empty trace  {self.with_trace}  ({pc(self.with_trace, self.valid)} of the valid)",
            f"non-urgent valid, with trace  {self.non_urgent_trace} / {self.non_urgent}  ({pc(self.non_urgent_trace, self.non_urgent)})",
            f"passive gestures              {self.passive} / {self.valid}  ({pc(self.passive, self.valid)})",
            "first refusals by code        " + (", ".join(f"{k} {v}" for k, v in self.refused.most_common()) or "none")])


class PlannerMeasure:
    def __init__(self, n: int = 120, seed: int = 0, k: int = 6, tk: Toolkit | None = None):
        self.n, self.seed, self.k = n, seed, k
        self.tk = tk or Toolkit()

    def run(self) -> Tally:
        from situations.sampler import SituationSampler
        tk, sampler, planner = self.tk, SituationSampler(self.seed), ScriptedPlanner(self.tk)
        plan: dict = {}
        caller = ScriptedCaller(planner, plan)
        rnd = GroupedRound(BatchInstructions(tk, PhraseBook(tk, 30), thoughts=True),
                           BatchSchema(DecisionSchema(tk, "full", thoughts=True)), BatchPrompt(SituationRenderer(tk)),
                           AnswerValidator(tk), caller)
        tally = Tally()
        for start in range(0, self.n, self.k):
            sits = [sampler.sample(i) for i in range(start, min(start + self.k, self.n))]
            plan.clear()
            plan.update({f"S{j + 1}": (s, SHAPES[(start + j) % len(SHAPES)]) for j, s in enumerate(sits)})
            res = rnd.run(sits)
            for slot in res.slots:
                self._count(tally, slot)
        return tally

    @staticmethod
    def _count(t: Tally, slot) -> None:
        t.asked += 1
        if slot.first.ok:
            t.valid_first += 1
        else:
            t.refused[slot.first.code] += 1
        if not slot.ok:
            return
        t.valid += 1
        t.repaired += int(slot.repaired and not slot.first.ok)
        d = slot.final.decision
        traced = bool(d.thoughts)
        t.with_trace += int(traced)
        wake = next((r for r in slot.situation.context.records if r.type == "WAKE"), None)
        if not (wake and wake.fields.get("cause") in URGENT):
            t.non_urgent += 1
            t.non_urgent_trace += int(traced)
        t.passive += int(d.gesture in PASSIVE_GESTURES)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="teacher.planner_measure", description=__doc__.split("\n\n")[0])
    ap.add_argument("--n", type=int, default=120, help="situations")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--k", type=int, default=6, help="situations per request")
    a = ap.parse_args(argv)
    print("STAND-IN ANSWERS, NO NETWORK: this measures the plumbing, not the teacher.")
    print(PlannerMeasure(a.n, a.seed, a.k).run().line())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
