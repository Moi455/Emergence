"""reflection.py - scores the student on the REFLECT decisions of the written mind (T11b; the lines `teacher.mind_replay` writes).

A reflect decision writes ONE record and says whether to go on thinking (`think_more`). A line is a reflect line when its
label writes `think_more`. For each one, the model's own greedy decision is compared with the teacher's:

  kind          the TYPE of the thought: belief / belief_about / goal / plan (from what was written: `kind_of_decision`)
  variable      the variable written (b_proposition / g_desired, or the plan head), whatever the target
  target        `new`, or the key of the record revised (thoughts that write a proposition)
  proposition   exact: the sentence equals the label's (canonical text); valid: the REAL ThoughtChecker accepts the predicted
                thought on the mind of the state (grammar, pointers, governor, D10), whether or not it equals the label
  plan          exact: same steps (gesture, target), repeat, period and goal served; valid: ThoughtChecker accepts it
  think_more    go on or act: equal to the label

`by_kind` repeats the figures for each type of thought of the LABEL (a prediction of another type counts as a miss there).
Entries a figure does not apply to are not counted (`n` says how many were). Nothing here is learned or tuned.
"""
from __future__ import annotations

import numpy as np

from teacher.mind_replay import StepJudge, kind_of_decision, think_more_of, thought_of_decision, THINK_MORE

from .sequences import canonical
from .spec import NO_LABEL

PROPOSITIONAL = ("belief", "belief_about", "goal")


def _stat(hits: list) -> dict:
    return {"n": len(hits), "acc": (sum(hits) / len(hits)) if hits else None}


def _variables(decision: dict) -> tuple:
    out = sorted(w["variable"] for w in decision.get("writes") or [] if w["variable"] != THINK_MORE)
    return tuple(out) + (("<plan>",) if decision.get("plan") else ())


def _written(decision: dict):
    kind = kind_of_decision(decision)
    if kind in PROPOSITIONAL:
        w = next(w for w in decision["writes"] if w["variable"] != THINK_MORE)
        return w["target"], canonical(str(w["value"]))
    return None


def _plan_key(decision: dict):
    p = decision.get("plan")
    if not p:
        return None
    return (tuple((s["gesture"], s.get("target") or None) for s in p["steps"]), p.get("repeat"), p.get("repeat_period"), p.get("parent"))


class ReflectionScore:
    def __init__(self, rt):
        self.rt = rt
        self.judge = StepJudge(rt.tk)
        self.think_more = rt.space.writes.index[THINK_MORE]

    def mask(self, truth: dict) -> np.ndarray:
        """[N] rows whose label is a reflect decision: it writes `think_more` AND carries a plan label (a plan, or the explicit
        "no plan" every reflect line has; an act line never does, whatever it writes)."""
        inside = np.arange(truth["w_var"].shape[1])[None] < truth["n_writes"][:, None]
        return ((truth["w_var"] == self.think_more) & inside).any(1) & (truth["plan_gesture"][:, 0] != NO_LABEL)

    def run(self, p, decided: list, truth_decisions: list) -> dict:
        rows = np.nonzero(self.mask(p.truth))[0]
        acc = {k: [] for k in ("kind", "variable", "target", "proposition_exact", "proposition_valid", "plan_exact", "plan_valid",
                               "thought_valid", "think_more", "decoded")}
        by = {k: {n: [] for n in acc} for k in ("belief", "belief_about", "goal", "plan")}
        for i in rows:
            want = truth_decisions[i]
            if want is None:
                continue
            got, _ = decided[i]
            kind = kind_of_decision(want)
            slot = by.get(kind)
            if slot is None:
                continue

            def put(name, hit):
                acc[name].append(bool(hit))
                slot[name].append(bool(hit))

            put("decoded", got is not None)
            g_kind = kind_of_decision(got) if got else None
            put("kind", g_kind == kind)
            put("variable", got is not None and _variables(got) == _variables(want))
            put("think_more", got is not None and think_more_of(got) == think_more_of(want))
            thought = thought_of_decision(got) if got else None
            ok = False
            if thought is not None:
                meta = p.meta[i]
                ages = meta["source"].get("ages") if isinstance(meta["source"].get("ages"), dict) else {}
                ok = self.judge.thought(meta["records"], ages, thought)[0] is not None
            put("thought_valid", ok)
            if kind in PROPOSITIONAL:
                put("target", got is not None and g_kind in PROPOSITIONAL and _written(got)[0] == _written(want)[0])
                put("proposition_exact", got is not None and g_kind in PROPOSITIONAL and _written(got) == _written(want))
                put("proposition_valid", ok and g_kind in PROPOSITIONAL)
            else:
                put("plan_exact", got is not None and _plan_key(got) == _plan_key(want))
                put("plan_valid", ok and g_kind == "plan")
        rep = {"examples": int(len(rows)), **{k: _stat(v) for k, v in acc.items()},
               "by_kind": {k: {n: _stat(v) for n, v in slot.items() if v} for k, slot in by.items() if any(slot.values())}}
        return rep
