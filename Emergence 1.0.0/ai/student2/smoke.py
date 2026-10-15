"""smoke.py - RANDOM answers that the validator accepts, to test the whole chain WITHOUT a teacher.

THIS IS NOT TRAINING DATA. The answers are random draws (a gesture, parameters of the right class, a condition, an
utterance rebuilt from the propositions already in the records, a few bounded writes): they carry no judgement, no
character, no plausibility. They exist so that the dataset reader, the tokeniser, the label codec, the model, the
losses and the checkpoint can be exercised end to end, and so that a batch can be over-fitted. Every answer is
checked by the REAL AnswerValidator (catalogue, governor, D10), exactly like a teacher's answer; the file is marked
`source.teacher = "smoke-random"` and must never be mixed into a training set.

    cd ai && python3 -m student2.smoke --n 200 --seed 0 --out /tmp/smoke.jsonl

No network call.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from situations.sampler import SituationSampler
from teacher.dataset import DatasetFile, LabelRecord
from teacher.toolkit import Toolkit
from teacher.validate import AnswerValidator, ConditionChecker, Mind, ParamChecker

SMOKE_TEACHER = "smoke-random"
QUANTITIES = ("5", "10", "15", "30", "60", "120", "240")
MOODS = ("assert", "ask", "request", "offer")
PROP_RECORDS = ("BELIEF", "MEMORY", "GOAL", "HEARD", "REQUEST")


class AnswerDrawer:
    """Draws one random JSON answer for a situation (it may be refused: the caller retries)."""

    def __init__(self, tk: Toolkit, rng: random.Random, layout=None, plans: bool = False):
        self.tk, self.rng, self.layout, self.plans = tk, rng, layout, plans
        self.plan_rng = random.Random(str(rng.getstate()[1][:4]))          # its own stream: the rest of the draw is the same with or without plans
        self.spec = tk.spec
        self.forms = sorted(tk.cat["form"])
        iface = tk.interface
        self.words = {"kind": [w for w in iface.kinds], "concept": [], "time": []}
        for w in iface.grammar_words:
            try:
                types = tk.vocab.types(w)
            except Exception:                                   # noqa: BLE001  (a word the vocabulary cannot type)
                continue
            if "time" in types:
                self.words["time"].append(w)
            if types & {"concept", "kind"}:
                self.words["concept"].append(w)

    # ---------------------------------------------------------------- one answer
    def draw(self, sit) -> str:
        r = self.rng
        mind = Mind(self.tk, sit.context.records, AnswerValidator(self.tk)._scene_truth(sit))
        checker = ParamChecker(self.tk, mind)
        gid = r.choice(self.spec.gesture_ids)
        g = self.spec.gestures[gid]
        params = []
        for p in g.params:
            if p.kind == "expression":
                continue
            if p.optional and r.random() < 0.5:
                continue
            value = self._param(p, mind, checker)
            if value is None:
                if p.optional:
                    continue
                return json.dumps({"gesture": "stop", "params": [], "speech": "", "writes": []})   # cannot fill: stop
            params.append({"name": p.name, "value": value})
        speech = self._utterance(mind) if g.expression_param else ""
        answer = {"why": "smoke", "gesture": gid, "params": params, "speech": speech, "writes": self._writes(mind, sit)}
        if self.plans:
            answer |= self._plan_fields(g, mind, checker)
        return json.dumps(answer)

    # ---------------------------------------------------------------- plans and stops (T11, random like the rest)
    def _plan_fields(self, g, mind: Mind, checker: ParamChecker) -> dict:
        """A random `plan` (absent, empty, or 1 to 6 steps) and, for a gesture without `until`, a random `stop`."""
        keep, self.rng = self.rng, self.plan_rng
        try:
            r = self.rng
            out = {}
            steps = []
            if r.random() < 0.8:
                for _ in range(r.randint(1, self.spec.max_plan_steps)):
                    gid = r.choice(self.spec.gesture_ids)
                    refs = [p for p in self.spec.gestures[gid].params if p.kind == "ref"]
                    pool = [rec.key for rec in mind.records if rec.type in self._step_types()
                            and refs and checker._targets(rec.key) & set(refs[0].accepts)]
                    if refs and not pool and not all(p.optional for p in refs):
                        continue
                    steps.append({"gesture": gid, "target": r.choice(pool) if (pool and (refs and r.random() < 0.9 or not refs[0].optional)) else ""})
            repeat = r.choice(self.spec.writes["i_repeat"].values) if steps else ""
            goals = [rec.key for rec in mind.records if rec.type == "GOAL"]
            out["plan"] = {"steps": steps, "repeat": repeat, "repeat_period": r.choice(("6", "24", "72")) if repeat == "every" else "",
                           "parent": r.choice(goals) if goals and r.random() < 0.4 else ""}
            if not any(p.kind == "condition" for p in g.params):
                out["stop"] = self._condition(mind) if r.random() < 0.5 else ""
            return out
        finally:
            self.rng = keep

    def _step_types(self) -> tuple:
        return tuple(self.tk.interface.token_types["PLAN"]["fields"]["step_targets"]["ref_types"])

    def _param(self, p, mind: Mind, checker: ParamChecker):
        r = self.rng
        if p.kind == "enum":
            return r.choice(list(p.values))
        if p.kind == "condition":
            return self._condition(mind)
        keys = [rec.key for rec in mind.records if checker._targets(rec.key) & set(p.accepts)]
        extra = list(self.spec.directions) if "direction" in p.accepts else []
        extra += self.forms if "form" in p.accepts else []
        pool = keys + extra
        return r.choice(pool) if pool else None

    def _condition(self, mind: Mind) -> str:
        r = self.rng
        cid = r.choice([c for c in self.spec.conditions if c != "c_time" or self.words["time"]])
        args = []
        for t in self.spec.conditions[cid]:
            if t == "quantity":
                args.append(r.choice(QUANTITIES))
            elif t in ("entity", "place"):
                accept = ConditionChecker.ACCEPT[t]
                keys = [rec.key for rec in mind.records if rec.type in ("ENTITY", "THING", "GROUP", "PLACE", "LOCUS", "INV")
                        and self.tk.vocab.types(rec.key) & accept]
                args.append(r.choice(keys or ["@PLACE"]))
            else:
                args.append(r.choice(self.words[t]))
        return f"({cid} {' '.join(args)})" if args else cid

    # ---------------------------------------------------------------- language
    def _props(self, mind: Mind) -> list[str]:
        return [rec.fields["prop"] for rec in mind.records if rec.type in PROP_RECORDS and rec.fields.get("prop")]

    def _utterance(self, mind: Mind) -> str:
        r = self.rng
        props = self._props(mind)
        if not props:
            return "(assert (has me bread_loaf))"
        body = r.choice(props)
        roll = r.random()
        if roll < 0.15 and len(props) > 1:
            body = f"(and {body} {r.choice(props)})"
        elif roll < 0.25:
            body = f"(not {body})"
        elif roll < 0.32:
            body = f"(believes me {body})"
        return f"({r.choice(MOODS)} {body})"

    def _proposition(self, mind: Mind) -> str:
        props = self._props(mind)
        return self.rng.choice(props) if props else "(has me bread_loaf)"

    # ---------------------------------------------------------------- writes
    def _writes(self, mind: Mind, sit) -> list:
        r = self.rng
        by_kind = {"entity": [x.key for x in mind.records if x.type in ("ENTITY", "GROUP")],
                   "belief": [x.key for x in mind.records if x.type in ("BELIEF", "HEARD")],
                   "goal": [x.key for x in mind.records if x.type == "GOAL"],
                   "memory": [x.key for x in mind.records if x.type == "MEMORY"],
                   "plan": [x.key for x in mind.records if x.type == "PLAN"]}
        out = []
        for _ in range(r.choice((0, 0, 1, 1, 2, 3, 4))):
            w = r.choice(list(self.spec.writes.values()))
            if w.target_kind == "self":
                target = "self"
            elif w.creatable and w.scale == "proposition" and r.random() < 0.5:
                target = "new"
            else:
                pool = by_kind.get(w.target_kind)
                if not pool:
                    continue
                target = r.choice(pool)
            value = self._value(w, mind, target)
            if value is not None:
                out.append({"target": target, "variable": w.id, "value": value})
        return out

    def _value(self, w, mind: Mind, target: str):
        r = self.rng
        if w.numeric:
            lo, hi = w.bounds or (0.0, 10.0)
            if w.mode == "jump":
                return f"{r.uniform(lo, hi):.1f}"
            key = "me" if target == "self" else target
            old = self._old(w, mind, key)
            if old is None:
                return None
            return f"{min(hi, max(lo, old + r.choice((-1, 1) ) * w.step * r.random())):.2f}"
        if w.scale == "bool":
            return r.choice(("true", "false"))
        if w.scale in ("enum", "word"):
            return r.choice(list(w.values))
        if w.scale in ("time", "time_until"):
            return r.choice(("1", "6", "24", "72"))
        if w.scale == "mref":
            keys = [x.key for x in mind.records if x.type in self._ref_types(w)]
            return r.choice(keys) if keys else None
        if w.scale == "proposition":
            return self._proposition(mind)
        return None

    def _ref_types(self, w) -> set:
        """The record types a record-valued variable may point to (the ref_types of its fields in the tok-2 layout)."""
        types = set()
        for t, f in w.fields:
            col = self.layout.types[t].columns.get(f) if self.layout is not None and t in self.layout.types else None
            types |= set(col.codec.spec.get("ref_types", ())) if col is not None else set()
        return types or {"ENTITY", "THING", "GOAL", "PLAN", "GROUP", "SELF"}

    @staticmethod
    def _old(w, mind: Mind, key: str):
        from .labels import RecordIndex
        return RecordIndex(mind.records).old(w, key)


class SmokeSet:
    """Writes `n` records the validator accepted, with statistics on how many draws it took."""

    def __init__(self, seed: int = 0, tk: Toolkit | None = None, max_tries: int = 40, plans: bool = False):
        self.tk = tk or Toolkit()
        self.plans = plans
        self.seed, self.max_tries = seed, max_tries
        self.sampler = SituationSampler(seed)
        self.validator = AnswerValidator(self.tk)
        self.stats: Counter = Counter()
        self.codes: Counter = Counter()

    def one(self, index: int):
        """-> (situation, Outcome) with the first accepted random answer, or (situation, None)."""
        sit = self.sampler.sample(index)
        drawer = AnswerDrawer(self.tk, random.Random(f"smoke:{self.seed}:{index}"), self.sampler.tokenizer.layout, self.plans)
        for _ in range(self.max_tries):
            self.stats["draws"] += 1
            o = self.validator.validate(drawer.draw(sit), sit)
            self.codes[o.code] += 1
            if o.ok:
                return sit, o
        return sit, None

    def write(self, path: Path, n: int, start: int = 0) -> dict:
        file = DatasetFile(path)
        now = datetime.now(timezone.utc)
        for i in range(start, start + n):
            sit, o = self.one(i)
            if o is None:
                self.stats["situations_without_answer"] += 1
                continue
            file.append(LabelRecord.build(self.sampler.tokenizer, sit, o, SMOKE_TEACHER, now, synthetic=True))
            self.stats["written"] += 1
        return {"written": self.stats["written"], "draws": self.stats["draws"], "codes": dict(self.codes.most_common()),
                "situations_without_answer": self.stats["situations_without_answer"]}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--plans", action="store_true", help="also draw random plans and stop conditions (T11)")
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    if a.out.exists():
        print(f"{a.out} exists: refusing to append smoke data to a file", file=sys.stderr)
        return 2
    print(json.dumps(SmokeSet(a.seed, plans=a.plans).write(a.out, a.n, a.start), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
