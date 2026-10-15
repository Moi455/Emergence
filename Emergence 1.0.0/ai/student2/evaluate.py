"""evaluate.py - per-head accuracy of a checkpoint against the teacher's labels (the validation split of data.py).

    cd ai && python3 -m student2.evaluate --ckpt runs/a1/last.pt --data runs/snap.jsonl --out report.json

The split is the same hash of (split seed, id) as the trainer's (`LabelDataset(split="val")`). The model decides GREEDILY
and FREE-RUNNING (`StudentModel.predict`: every head is conditioned on the model's own previous choice, as in the game),
then each head is compared with the label. Entries a label does not have (NO_LABEL: a pointer the gesture lacks, a write
that was not made) are ignored. `|g` figures count only the decisions whose gesture was right (a head conditioned on a
wrong gesture is not wrong by its own fault).

What is NOT computable cleanly, and is therefore not reported:
  * the gesture top-3 uses the gesture logits (feasibility mask is all ones, as in training), nothing else has a top-k;
  * a sentence is "exact" when its steps (symbol, arity, slot, count) equal the label's: two different trees can say the
    same thing, so this is a lower bound of semantic equality. It is also compared on the writes' propositions;
  * validity: the model's decision is decoded, turned back into the raw answer a teacher gives and run through the real
    `AnswerValidator` (grammar, pointers, governor) with the real ages stored in `source.ages` (offline, no network). A
    line without stored ages is validated with unknown real ages (the governor denies by default) and counted. The
    validator judges the WHOLE decision, so "speech valid" is the language grammar of the speech alone (`Toolkit.expression`)
    and the governor's verdict is given for the whole decision, by refusal code. The teacher's own labels are validated
    the same way (the ceiling: a label the current catalogue refuses is not the student's fault).
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import torch

from teacher.migrate import AgeTruth, Migration
from teacher.validate import AnswerValidator

from .data import Batch, LabelDataset
from .labels import Targets, comparable
from .model import StudentConfig, StudentModel
from .reflection import ReflectionScore
from .runtime import Runtime
from .spec import MAX_REFS, MAX_WRITES, NO_LABEL, ValueKind
from .train import Checkpoint


def load_model(path: Path, rt: Runtime, device: str = "cpu") -> StudentModel:
    """A checkpoint -> model. Tensors only (`weights_only=True`): nothing is unpickled; the fingerprints are checked as
    train.py does (`Checkpoint.check`)."""
    payload = torch.load(path, map_location=device, weights_only=True)
    Checkpoint.check(payload, rt)
    model = StudentModel(StudentConfig(**payload["config"]), rt.space).to(device)
    model.load_state_dict(payload["model"])
    return model.eval()


def stat(hit: np.ndarray, valid: np.ndarray | None = None) -> dict:
    """{"n": entries, "acc": mean of hit over them} (acc is None when there is no entry: not 0, not 1)."""
    hit = np.asarray(hit, bool)
    valid = np.ones_like(hit) if valid is None else np.asarray(valid, bool)
    n = int(valid.sum())
    return {"n": n, "acc": float((hit & valid).sum() / n) if n else None}


# ----------------------------------------------------------------------------------------------- predictions
@dataclass
class Predictions:
    """What a model decided on the evaluation set, one row per decision (numpy), next to the labels."""
    truth: dict                 # Targets field -> [N, ...]
    pred: dict                  # the same fields, the model's own greedy choice
    top3: np.ndarray            # [N, 3] gesture indices by decreasing logit
    meta: list                  # per decision: records, enc, source
    forced_eos: int = 0
    speech_overflow: int = 0

    @property
    def n(self) -> int:
        return len(self.meta)


class Evaluator:
    """Runs a model over the validation split and scores it. The batches are built once and reused for every model
    (a quantised one too), so two models see exactly the same inputs."""

    def __init__(self, rt: Runtime, ds: LabelDataset, batch: int = 32, limit: int | None = None, device: str | None = None):
        self.rt, self.ds, self.device = rt, ds, device or ("cuda" if torch.cuda.is_available() else "cpu")
        n = len(ds) if limit is None else min(limit, len(ds))
        col = ds.collator(False)
        self.batches: list[Batch] = [col([ds[i] for i in range(s, min(s + batch, n))]) for s in range(0, n, batch)]
        self.validator = AnswerValidator(rt.tk, truth_factory=lambda s: AgeTruth(s.ages))
        self.reflection = ReflectionScore(rt)

    @torch.no_grad()
    def predict(self, model: StudentModel) -> Predictions:
        model.to(self.device).eval()
        names = Targets.names()
        truth: dict[str, list] = {k: [] for k in names}
        pred: dict[str, list] = {k: [] for k in names}
        top3, meta, forced, overflow = [], [], 0, 0
        amp = self.device == "cuda"
        for b in self.batches:
            bd = b.to(self.device)
            with torch.autocast(self.device, dtype=torch.float16, enabled=amp):
                logits = model(bd, teacher=False)["gesture"]
                out = model.predict(bd, speech_capacity=max(8, int(bd.seq_ok.sum())))
            top3.append(logits.topk(3, -1).indices.cpu().numpy())
            for k in names:
                truth[k].append(b.targets[k].numpy())
                pred[k].append(out[k].cpu().numpy())
            forced += int(out["seq_forced"].sum())
            overflow += int(out["speech_overflow"])
            meta.extend(b.meta)
        cat = lambda d: {k: np.concatenate(v) for k, v in d.items()}                    # noqa: E731
        return Predictions(cat(truth), cat(pred), np.concatenate(top3), meta, forced, overflow)

    # ---- scoring
    def score(self, p: Predictions) -> dict:
        sp, T, P = self.rt.space, p.truth, p.pred
        N = p.n
        rep: dict = {"decisions": N, "forced_eos": p.forced_eos, "speech_overflow": p.speech_overflow}
        gok = P["gesture"] == T["gesture"]
        rep["gesture"] = {"top1": stat(gok), "top3": stat((p.top3 == T["gesture"][:, None]).any(1))}
        rep["pointers"] = self._pointers(T, P, gok)
        rep["manner"] = self._manner(T, P, gok)
        rep["stop_condition"] = self._condition(T, P, gok)
        rep["writes"] = self._writes(T, P, gok)
        rep["sequences"] = self._sequences(T, P, gok)
        rep["plans"] = self._plans(T, P)
        reflect = self.reflection.mask(T)
        if reflect.any():                                  # T11b: the lines of the written mind (teacher/mind_replay.py)
            decided = self.decisions(p)
            rep["reflection"] = self.reflection.run(p, decided, self.truth_decisions(p))
            rep["validity"] = self._validity(p, skip=reflect, decided=decided)
            rep["validity"]["reflect_rows_judged_in_reflection"] = int(reflect.sum())
        else:
            rep["validity"] = self._validity(p)
        return rep

    def truth_decisions(self, p: Predictions) -> list:
        """The labels decoded to decisions (None when one does not decode)."""
        out = []
        for i, m in enumerate(p.meta):
            try:
                out.append(self.rt.codec.decode(Targets(**{n: p.truth[n][i] for n in Targets.names()}), m["enc"], m["records"]))
            except Exception:                                                   # noqa: BLE001
                out.append(None)
        return out

    def _plans(self, T, P) -> dict:
        """Plan head (only the lines whose label carries a plan or an explicit 'no plan'): is there a plan at all, then the
        gesture and the pointer of each labelled step."""
        fin = self.rt.space.plan.fin
        labelled = T["plan_gesture"][:, 0] != NO_LABEL
        steps = (T["plan_gesture"] != NO_LABEL) & (T["plan_gesture"] != fin)
        ptr = steps & (T["plan_ref"] != NO_LABEL)
        return {"has_plan": stat((P["plan_gesture"][:, 0] != fin) == (T["plan_gesture"][:, 0] != fin), labelled),
                "step_gesture": stat(P["plan_gesture"] == T["plan_gesture"], steps),
                "step_target": stat(P["plan_ref"] == T["plan_ref"], ptr)}

    def _pointers(self, T, P, gok) -> dict:
        valid = T["ref"] != NO_LABEL
        hit = P["ref"] == T["ref"]
        every = ((hit | ~valid).all(1)) & valid.any(1)
        has = valid.any(1)
        return {"per_pointer": stat(hit, valid), "per_pointer|g": stat(hit, valid & gok[:, None]),
                "all_pointers_of_decision": stat(every[has]), "all_pointers_of_decision|g": stat(every[has & gok])}

    def _manner(self, T, P, gok) -> dict:
        valid = T["manner"] != NO_LABEL
        hit = P["manner"] == T["manner"]
        heads = self.rt.space.manner.heads
        out = {"per_value": stat(hit, valid), "per_value|g": stat(hit, valid & gok[:, None]),
               "all_manners_of_decision|g": stat(((hit | ~valid).all(1))[valid.any(1) & gok]),
               "by_head": {h: stat(hit[:, i], valid[:, i]) for i, h in enumerate(heads)}}
        return out

    def _condition(self, T, P, gok) -> dict:
        has = T["cond"] != NO_LABEL
        cond_hit = P["cond"] == T["cond"]
        out = {"condition": stat(cond_hit, has), "condition|g": stat(cond_hit, has & gok)}
        for k in ("cond_ref", "cond_num", "cond_word"):
            valid = T[k] != NO_LABEL
            hit = P[k] == T[k]
            out[k] = stat(hit, valid)
            out[k + "|g,cond"] = stat(hit, valid & (gok & cond_hit)[:, None])
        return out

    def _writes(self, T, P, gok) -> dict:
        sp = self.rt.space
        nw_t, nw_p = T["n_writes"], P["n_writes"]
        inside = np.arange(MAX_WRITES)[None] < nw_t[:, None]                          # the labelled writes
        tgt_hit, var_hit = P["w_target"] == T["w_target"], P["w_var"] == T["w_var"]
        key_hit = tgt_hit & var_hit
        out = {"n_writes": stat(nw_p == nw_t), "n_writes|g": stat(nw_p == nw_t, gok),
               "target": stat(tgt_hit, inside), "variable": stat(var_hit, inside), "target_and_variable": stat(key_hit, inside)}
        kind = np.asarray(sp.writes.kind)[np.clip(T["w_var"], 0, None)]
        value_hit = {ValueKind.NUM_ABS: P["w_num"] == T["w_num"], ValueKind.NUM_DELTA: P["w_num"] == T["w_num"],
                     ValueKind.ENUM: P["w_enum"] == T["w_enum"], ValueKind.QTY: P["w_qty"] == T["w_qty"],
                     ValueKind.PTR: P["w_ptr"] == T["w_ptr"]}
        near = np.abs(P["w_num"] - T["w_num"]) <= 1
        # proposition values are sentences: scored with the sequences
        prop = kind == ValueKind.PROP
        by_kind, value_ok = {}, np.zeros_like(key_hit)
        for k, name in enumerate(ValueKind.NAMES):
            m = inside & key_hit & (kind == k)
            if k == ValueKind.PROP:
                hit = self._seq_hit(T, P)[:, 1:]
            else:
                hit = value_hit[k]
            by_kind[name] = stat(hit, m)
            value_ok |= m & hit
        num = inside & key_hit & np.isin(kind, (ValueKind.NUM_ABS, ValueKind.NUM_DELTA))
        out["value|key"] = {"by_kind": by_kind, "numeric_within_1_level": stat(near, num)}
        out["write_exact"] = stat(value_ok, inside)
        ok_all = (value_ok | ~inside).all(1)
        has = nw_t > 0
        out["write_set_exact"] = stat(ok_all[has] & (nw_p == nw_t)[has])
        out["write_set_exact|g"] = stat((ok_all & (nw_p == nw_t))[has & gok])
        return out

    @staticmethod
    def _seq_hit(T, P) -> np.ndarray:
        """[N, S] a predicted sentence equals the label's, step for step (False where there is no label)."""
        tl, pl = T["seq_len"], P["seq_len"]
        L = T["seq_sym"].shape[-1]
        inside = np.arange(L)[None, None] < tl[..., None]
        eq = (P["seq_sym"] == T["seq_sym"]) & (P["seq_arity"] == T["seq_arity"])
        slot_valid = T["seq_slot"] != NO_LABEL
        count_valid = T["seq_count"] != NO_LABEL
        eq &= (P["seq_slot"] == T["seq_slot"]) | ~slot_valid
        eq &= (P["seq_count"] == T["seq_count"]) | ~count_valid
        return (tl >= 0) & (pl == tl) & (eq | ~inside).all(-1)

    def _sequences(self, T, P, gok) -> dict:
        hit = self._seq_hit(T, P)
        has = T["seq_len"] >= 0
        sym_hit = (P["seq_sym"] == T["seq_sym"])
        L = T["seq_sym"].shape[-1]
        inside = np.arange(L)[None, None] < T["seq_len"][..., None]
        speech, props = has[:, 0], has[:, 1:]
        return {"speech_exact": stat(hit[:, 0], speech), "speech_exact|g": stat(hit[:, 0], speech & gok),
                "proposition_exact": stat(hit[:, 1:], props),
                "speech_symbol_per_step": stat(sym_hit[:, 0], inside[:, 0] & speech[:, None]),
                "proposition_symbol_per_step": stat(sym_hit[:, 1:], inside[:, 1:] & props[..., None])}

    # ---- validity: the real validator, offline
    def decisions(self, p: Predictions) -> list[tuple[dict | None, str]]:
        """The model's decision of each row decoded to a dict (None and the reason when it does not decode)."""
        names, out = Targets.names(), []
        for i, m in enumerate(p.meta):
            t = Targets(**{n: p.pred[n][i].copy() for n in names})
            self.mask_unlabelled(t, p, i)
            try:
                out.append((self.rt.codec.decode(t, m["enc"], m["records"]), ""))
            except Exception as e:                                             # noqa: BLE001  (counted, never swallowed)
                out.append((None, f"{type(e).__name__}: {str(e)[:70]}"))
        return out

    @staticmethod
    def mask_unlabelled(t: Targets, p: Predictions, i: int) -> None:
        """A label that says nothing about plans / stops (NO_LABEL: older data, or an answer without a trace) does not
        judge them: the model's plan / stop for that line are dropped, as train.py's exact_match does. Without this a head
        that never saw a label (random weights) would be judged by the validator on every decision."""
        if p.truth["plan_gesture"][i][0] == NO_LABEL:
            for n in ("plan_gesture", "plan_ref", "plan_repeat", "plan_period", "plan_parent"):
                setattr(t, n, np.full_like(getattr(t, n), NO_LABEL))
        if p.truth["stop"][i] == NO_LABEL:
            for n in ("stop", "stop_ref", "stop_num", "stop_word"):
                setattr(t, n, np.full_like(getattr(t, n), NO_LABEL))

    def _verdict(self, decision: dict, meta: dict) -> str:
        ages = meta["source"].get("ages") if isinstance(meta["source"].get("ages"), dict) else {}
        sit = SimpleNamespace(context=SimpleNamespace(records=meta["records"]), ages=ages, scene=None)
        try:
            o = self.validator.validate(Migration.raw_answer(decision), sit)
        except Exception as e:                  # noqa: BLE001  (a crash of the validator itself is counted, not hidden)
            return f"validator_crash:{type(e).__name__}"
        return "ok" if o.ok else o.code

    def _validity(self, p: Predictions, skip: np.ndarray | None = None, decided: list | None = None) -> dict:
        """`skip`: rows left out (the reflect lines, scored by `reflection`; the validator judges an act)."""
        names = Targets.names()
        decided = decided if decided is not None else self.decisions(p)
        codes, errors = Counter(), Counter()
        speech_ok = speech_n = no_ages = 0
        teacher = Counter()
        for i, ((dec, why), m) in enumerate(zip(decided, p.meta)):
            if skip is not None and skip[i]:
                continue
            no_ages += not m["source"].get("ages")
            want = Targets(**{n: p.truth[n][i] for n in names})
            try:
                teacher[self._verdict(self.rt.codec.decode(want, m["enc"], m["records"]), m)] += 1
            except Exception:                                                   # noqa: BLE001
                teacher["undecodable label"] += 1
            if dec is None:
                codes["undecodable"] += 1
                errors[why] += 1
                continue
            codes[self._verdict(dec, m)] += 1
            if dec.get("speech"):
                speech_n += 1
                speech_ok += bool(self.rt.tk.expression(dec["speech"]).ok)
        n = max(1, p.n - (0 if skip is None else int(skip.sum())))
        return {"decision_valid": codes["ok"] / n, "refusal_codes": dict(codes.most_common()),
                "undecodable_reasons": dict(errors.most_common(5)),
                "speech_grammar_valid": {"n": speech_n, "acc": speech_ok / speech_n if speech_n else None},
                "teacher_labels_valid": teacher["ok"] / n, "teacher_label_codes": dict(teacher.most_common()),
                "lines_without_stored_ages": no_ages}

    def run(self, model: StudentModel) -> tuple[Predictions, dict]:
        p = self.predict(model)
        return p, self.score(p)

    # ---- decision identity (used by quantize.py)
    def keys(self, p: Predictions) -> list[tuple]:
        """(gesture, the pointers it actually has) of each decision: what 'same gesture AND same pointers' compares."""
        shapes = self.rt.space.gestures.shapes
        out = []
        for g, refs in zip(p.pred["gesture"], p.pred["ref"]):
            shape = shapes[int(g)]
            k = len(shape.refs) if shape is not None else 0
            out.append((int(g), tuple(int(x) for x in refs[:k])))
        return out

    def comparables(self, p: Predictions) -> list:
        return [None if d is None else json.dumps(comparable(d), sort_keys=True) for d, _ in self.decisions(p)]


# ----------------------------------------------------------------------------------------------- display
def flatten(rep: dict, prefix: str = "") -> dict[str, dict]:
    """The leaves {"n", "acc"} of a report by dotted name."""
    out = {}
    for k, v in rep.items():
        if isinstance(v, dict):
            if set(v) == {"n", "acc"}:
                out[prefix + k] = v
            else:
                out.update(flatten(v, f"{prefix}{k}."))
    return out


def table(rep: dict) -> str:
    rows = [f"{'metric':<58}{'n':>7}{'accuracy':>10}"]
    flat = flatten(rep)
    empty = [k for k, s in flat.items() if s["n"] == 0]
    for name, s in flat.items():
        if s["n"] == 0:
            continue
        rows.append(f"{name:<58}{s['n']:>7}{'n/a' if s['acc'] is None else f'{100 * s['acc']:.1f} %':>10}")
    if empty:
        rows.append(f"(no entry in the evaluation set, not computable: {', '.join(empty)})")
    v = rep["validity"]
    rows.append(f"{'validator: decisions valid (real governor)':<58}{rep['decisions']:>7}{100 * v['decision_valid']:>9.1f}%")
    rows.append(f"{'validator: teacher labels valid (ceiling)':<58}{rep['decisions']:>7}{100 * v['teacher_labels_valid']:>9.1f}%")
    rows.append("refusal codes: " + json.dumps(v["refusal_codes"]))
    return "\n".join(rows)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--ckpt", type=Path, required=True)
    ap.add_argument("--data", type=Path, nargs="+", required=True)
    ap.add_argument("--smoke-test", action="store_true")
    ap.add_argument("--cache", type=Path, default=None)
    ap.add_argument("--batch", type=int, default=32)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--val-fraction", type=float, default=0.05)
    ap.add_argument("--out", type=Path, default=None, help="JSON report")
    ap.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    a = ap.parse_args(argv)
    rt = Runtime.build()
    ds = LabelDataset(a.data, split="val", val_fraction=a.val_fraction, runtime=rt, allow_smoke=a.smoke_test, cache_dir=a.cache,
                      keep_context=True)
    model = load_model(a.ckpt, rt, a.device)
    ev = Evaluator(rt, ds, a.batch, a.limit, a.device)
    _, rep = ev.run(model)
    rep["model"] = {"size": model.cfg.name, "params_M": round(model.n_params() / 1e6, 2), "checkpoint": str(a.ckpt)}
    print(table(rep))
    if a.out:
        a.out.write_text(json.dumps(rep, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
