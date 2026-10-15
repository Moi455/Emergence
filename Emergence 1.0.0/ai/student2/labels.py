"""labels.py - a normalised teacher Decision <-> the targets of the heads, for one decision.

    LabelCodec(space).encode(decision, enc, records) -> Targets      (training: records by KEY become slots)
    LabelCodec(space).decode(targets, enc, records)  -> decision     (the inverse: also reads the model's own output)

`decision` is `teacher.validate.Decision.to_dict()`: gesture, params {name: text}, speech, writes. `enc` is the
`Encoded` of the same context (`enc.keys`: slot - 1 -> key) and `records` its `Record`s (the current values a bounded
write is relative to). A pointer is a record KEY in the file and a SLOT here; a ghost (a record the decision does not
carry) cannot be a target and the example is refused with a `LabelError`.

How a value is coded (spec.py): a bounded number 21 levels (a jump variable: absolute over its scale; a stepped or
slow one: the CHANGE in tenths of its step, since the governor clips it to `step` anyway); an enum its index; a time
or a stop-condition number a QuantityGrid bin; a record reference a slot; a proposition a sequence for the decoder.
Quantisation is lossy by at most half a level; `decode(encode(d))` is exact when the values lie on the grids, and
`encode(decode(encode(d)))` always equals `encode(d)` (idempotent).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, fields

import numpy as np

from .sequences import SequenceCodec, SequenceError, Steps
from .spec import MAX_REFS, MAX_SLOTS, MAX_WRITES, NO_LABEL, NUM_BINS, OutputSpace, SpaceError, TargetKind, ValueKind


class LabelError(SpaceError):
    """This decision cannot be turned into targets (the example is skipped and counted, never silently bent)."""


def _i64(*shape, fill=NO_LABEL) -> np.ndarray:
    return np.full(shape, fill, np.int64)


@dataclass
class Targets:
    """Targets of ONE decision (numpy, fixed shapes). NO_LABEL (-100) = not applicable, ignored by the losses."""
    gesture: np.ndarray            # []
    ref: np.ndarray                # [MAX_REFS]       pointer candidate index (PointerSpace)
    manner: np.ndarray             # [H]              value index inside its head (NONE level for an optional absent one)
    cond: np.ndarray               # []               stop-condition id
    cond_ref: np.ndarray           # [2]              candidate index of a record argument
    cond_num: np.ndarray           # [2]              QuantityGrid bin
    cond_word: np.ndarray          # [2]              input-vocabulary id
    n_writes: np.ndarray           # []               0..4
    w_target: np.ndarray           # [4]              candidate index (slot or NEW)
    w_var: np.ndarray              # [4]
    w_enum: np.ndarray             # [4]              index into WriteTable.enum_values
    w_num: np.ndarray              # [4]              numeric level 0..20
    w_qty: np.ndarray              # [4]              QuantityGrid bin
    w_ptr: np.ndarray              # [4]              candidate index (slot)
    seq_len: np.ndarray            # [S]              symbols of sequence s (-1: no such sequence)
    seq_sym: np.ndarray            # [S, steps]       symbol, then the end class, then NO_LABEL
    seq_arity: np.ndarray          # [S, steps]
    seq_slot: np.ndarray           # [S, steps]       token slot of a pointer symbol (NO_LABEL for the other symbols)
    seq_count: np.ndarray          # [S, steps]
    seq_depth: np.ndarray          # [S, steps]       depth of the step (derived from the arities)
    seq_open: np.ndarray           # [S, steps]       a node still waits for children before this step (derived)
    plan_gesture: np.ndarray       # [PLAN_CAP]       gesture index, or FIN (= the gesture capacity); NO_LABEL: no plan labelled
    plan_ref: np.ndarray           # [PLAN_CAP]       candidate index of the step's pointer (NONE allowed when no pointer is required)
    plan_repeat: np.ndarray        # []               index in the registry's enum values (i_repeat)
    plan_period: np.ndarray        # []               QuantityGrid bin (i_repeat_period)
    plan_parent: np.ndarray        # []               candidate index of the parent goal (NONE = no parent)
    stop: np.ndarray               # []               decision stop condition id, or NONE (= the condition capacity)
    stop_ref: np.ndarray           # [2]
    stop_num: np.ndarray           # [2]
    stop_word: np.ndarray          # [2]

    @classmethod
    def empty(cls, space: OutputSpace) -> "Targets":
        S, L = space.sequences.MAX_SEQUENCES, space.sequences.steps
        return cls(gesture=_i64(), ref=_i64(MAX_REFS), manner=_i64(space.manner.cap_heads), cond=_i64(),
                   cond_ref=_i64(2), cond_num=_i64(2), cond_word=_i64(2), n_writes=_i64(fill=0),
                   w_target=_i64(MAX_WRITES), w_var=_i64(MAX_WRITES), w_enum=_i64(MAX_WRITES), w_num=_i64(MAX_WRITES),
                   w_qty=_i64(MAX_WRITES), w_ptr=_i64(MAX_WRITES), seq_len=_i64(S, fill=-1), seq_sym=_i64(S, L),
                   seq_arity=_i64(S, L), seq_slot=_i64(S, L), seq_count=_i64(S, L), seq_depth=_i64(S, L),
                   seq_open=_i64(S, L, fill=0), plan_gesture=_i64(space.plan.cap), plan_ref=_i64(space.plan.cap),
                   plan_repeat=_i64(), plan_period=_i64(), plan_parent=_i64(), stop=_i64(), stop_ref=_i64(2),
                   stop_num=_i64(2), stop_word=_i64(2))

    @classmethod
    def names(cls) -> list[str]:
        return [f.name for f in fields(cls)]

    def __eq__(self, other) -> bool:
        return isinstance(other, Targets) and all(np.array_equal(getattr(self, n), getattr(other, n)) for n in self.names())


class RecordIndex:
    """The records of a decision by key, and the current value of a variable (what a stepped write is relative to).
    The same lookup as the validator's `_old`."""

    def __init__(self, records):
        self.by_key = {r.key: r for r in records}
        self.records = list(records)

    def old(self, var, key: str) -> float | None:
        recs = [r for r in self.records if r.key in ("me", "me.mind", "me.state")] if key == "me" else \
            [self.by_key[key]] if key in self.by_key else []
        for tname, fname in var.fields:
            for r in recs:
                if r.type == tname and isinstance(r.fields.get(fname), (int, float)) and not isinstance(r.fields.get(fname), bool):
                    return float(r.fields[fname])
        return None


class LabelCodec:
    def __init__(self, space: OutputSpace):
        self.space = space
        self.seq = SequenceCodec(space)
        self.vocab = space.tokenizer.vocab
        self.rounding = 0.0              # worst relative rounding of a quantity or a count in the LAST encode

    # ================================================================================== decision -> targets
    def encode(self, d: dict, enc, records) -> Targets:
        sp, t = self.space, Targets.empty(self.space)
        self.rounding = self.seq.rounding = 0.0
        book = RecordIndex(records)
        gid = d.get("gesture")
        if gid not in sp.gestures.index:
            raise LabelError(f"unknown gesture {gid!r}")
        shape = sp.gestures.shape(gid)
        t.gesture[...] = sp.gestures.index[gid]
        params = dict(d.get("params") or {})
        known = {r.name for r in shape.refs} | {e.name for e in shape.enums} | {shape.condition}
        extra = set(params) - known
        if extra:
            raise LabelError(f"{gid}: parameters {sorted(extra)} are not in the catalogue")
        for k, rp in enumerate(shape.refs):
            v = params.get(rp.name)
            if v is None and not rp.optional:
                raise LabelError(f"{gid}: missing {rp.name}")
            t.ref[k] = sp.pointers.NONE if v is None else self._reference(v, enc, f"{gid}.{rp.name}")
        for e in shape.enums:
            v = params.get(e.name)
            h = sp.manner.head_index[e.head]
            if v is None:
                if not e.optional:
                    raise LabelError(f"{gid}: missing {e.name}")
                t.manner[h] = sp.manner.none_index(e.head)
            else:
                t.manner[h] = self._enum(e.head, v)
        if shape.condition:
            if params.get(shape.condition) is None:
                raise LabelError(f"{gid}: missing {shape.condition}")
            self._condition(params[shape.condition], enc, t)
        speech = d.get("speech")
        if shape.expression:
            if not speech:
                raise LabelError(f"{gid} needs a speech")
            self._sequence(t, 0, speech, enc)
        elif speech:
            raise LabelError(f"{gid} takes no speech")
        self._writes(d.get("writes") or [], enc, book, t)
        if "plan" in d:                                  # labelled only when the teacher wrote (or refused to write) a plan
            self._plan(d["plan"], enc, t)
        if "stop" in d:
            self._stop(shape, d["stop"], enc, t)
        self.rounding = max(self.rounding, self.seq.rounding)
        self._conform(t, enc)
        return t

    def _conform(self, t: Targets, enc) -> None:
        """The masks of the heads (which records / extras a pointer accepts) and the labels must agree: an example the
        masks would forbid is refused here, counted, instead of being learned with an impossible target."""
        sp = self.space
        g = int(t.gesture)
        types = np.asarray(enc.type_id)

        def record_ok(i: int, table) -> bool:
            return 1 <= i <= len(types) and bool(table[types[i - 1]])

        for k in range(MAX_REFS):
            i = int(t.ref[k])
            if int(t.ref[k]) == NO_LABEL:
                continue
            if sp.pointers.is_slot(i):
                if not record_ok(i, sp.gestures.ref_type_ok[g, k]):
                    raise LabelError(f"{sp.gestures.names[g]}: pointer {k} cannot designate a {enc.keys[i - 1]} (type not accepted)")
            elif not sp.gestures.ref_extra_ok[g, k, self._extra_index(i)]:
                raise LabelError(f"{sp.gestures.names[g]}: pointer {k} cannot be {sp.pointers.name_of(i) or 'nobody'}")
        if int(t.cond) != NO_LABEL:
            for j in range(2):
                if int(t.cond_ref[j]) != NO_LABEL and not record_ok(int(t.cond_ref[j]), sp.conditions.arg_type_ok[int(t.cond), j]):
                    raise LabelError(f"condition {sp.conditions.ids[int(t.cond)]}: argument {j} is a record of a type it does not accept")
        P = sp.plan
        for k in range(P.cap):
            gi = int(t.plan_gesture[k])
            if gi == NO_LABEL or gi == P.fin:
                continue
            i = int(t.plan_ref[k])
            if sp.pointers.is_slot(i) and not record_ok(i, P.step_type_ok):
                raise LabelError(f"plan step {k}: {enc.keys[i - 1]} is not a record a plan step may point to")
            if sp.pointers.is_slot(i) and not record_ok(i, sp.gestures.ref_type_ok[gi, 0] & sp.gestures.ref_valid[gi, 0]):
                raise LabelError(f"plan step {k}: {sp.gestures.names[gi]} cannot act on {enc.keys[i - 1]}")
            if i == sp.pointers.NONE and not P.none_ok[gi]:
                raise LabelError(f"plan step {k}: {sp.gestures.names[gi]} needs a target")
        if int(t.plan_parent) > 0 and not record_ok(int(t.plan_parent), P.parent_type_ok):
            raise LabelError("plan parent is not a goal")
        if int(t.stop) != NO_LABEL and int(t.stop) < len(sp.conditions.live):
            for j in range(2):
                if int(t.stop_ref[j]) != NO_LABEL and not record_ok(int(t.stop_ref[j]), sp.conditions.arg_type_ok[int(t.stop), j]):
                    raise LabelError(f"stop {sp.conditions.ids[int(t.stop)]}: argument {j} is a record of a type it does not accept")
        for i in range(int(t.n_writes)):
            v = int(t.w_var[i])
            if int(t.w_ptr[i]) != NO_LABEL and not record_ok(int(t.w_ptr[i]), sp.writes.mref_type_ok[v]):
                raise LabelError(f"{sp.writes.ids[v]}: its value is a record of a type it does not accept")

    def _extra_index(self, i: int) -> int:
        P = self.space.pointers
        return 0 if i == P.NONE else i - MAX_SLOTS

    def _reference(self, v, enc, where: str) -> int:
        P = self.space.pointers
        if not isinstance(v, str):
            raise LabelError(f"{where}: {v!r} is not a key")
        if v in enc.keys:
            return enc.keys.index(v) + 1
        for found in (P.of_direction(v), P.of_form(v)):
            if found is not None:
                return found
        raise LabelError(f"{where}: {v!r} is not a record of this decision (a ghost, a name or an unknown form)")

    def _enum(self, head: str, v) -> int:
        try:
            return self.space.manner.value_index(head, v)
        except SpaceError as e:
            raise LabelError(str(e)) from None

    def _condition(self, text: str, enc, t: Targets, names=("cond", "cond_ref", "cond_num", "cond_word")) -> None:
        sp = self.space
        c_id, c_ref, c_num, c_word = (getattr(t, n) for n in names)
        parts = text.replace("(", " ").replace(")", " ").split()
        if not parts or parts[0] not in sp.conditions.index:
            raise LabelError(f"unknown condition {text!r}")
        head, args = parts[0], parts[1:]
        if len(args) != len(sp.conditions.args[head]):
            raise LabelError(f"condition {text!r}: {len(sp.conditions.args[head])} argument(s) expected")
        c_id[...] = sp.conditions.index[head]
        for j, (a, typ) in enumerate(zip(args, sp.conditions.args[head])):
            kind = sp.conditions.kind_of(typ)
            if kind == 1:
                c_ref[j] = self._slot_of(a, enc, f"{head} argument {j}")
            elif kind == 2:
                if not (a.isascii() and a.isdigit()):
                    raise LabelError(f"condition {text!r}: {a!r} is not a whole number")
                c_num[j] = sp.quantity.bin_of(float(a))
                self.rounding = max(self.rounding, sp.quantity.error(float(a)))
            else:
                if not self.vocab.is_word(a):
                    raise LabelError(f"condition {text!r}: {a!r} is not a plain word")
                c_word[j] = self.vocab.ids[a]

    def _stop(self, shape, value, enc, t: Targets) -> None:
        """The decision's stop condition (T11): for a gesture WITHOUT an `until` parameter. None = the decision has none."""
        sp = self.space
        if shape.condition:
            raise LabelError(f"{shape.id} has its own stop parameter {shape.condition}: no decision stop")
        if value is None or value == "":
            t.stop[...] = sp.conditions.cap
            return
        self._condition(value, enc, t, ("stop", "stop_ref", "stop_num", "stop_word"))

    def _plan(self, plan, enc, t: Targets) -> None:
        """plan = None (no plan) or {"steps": [{"gesture", "target"}], "repeat", "repeat_period", "parent"}."""
        sp = self.space
        P = sp.plan
        steps = [] if plan is None else list(plan.get("steps") or [])
        if plan is not None and not steps:
            raise LabelError("a plan has at least one step")
        if len(steps) > P.used:
            raise LabelError(f"{len(steps)} plan steps > {P.used}")
        for k in range(P.cap):
            if k >= len(steps):
                t.plan_gesture[k] = P.fin
                continue
            st = steps[k]
            gid = st.get("gesture")
            if gid not in sp.gestures.index:
                raise LabelError(f"plan step {k}: unknown gesture {gid!r}")
            t.plan_gesture[k] = sp.gestures.index[gid]
            target = st.get("target")
            if target in (None, ""):
                t.plan_ref[k] = sp.pointers.NONE
            else:
                t.plan_ref[k] = self._slot_of(target, enc, f"plan step {k}")
        if plan is None:
            return
        repeat = plan.get("repeat") or "once"
        if repeat not in P.repeat_values:
            raise LabelError(f"plan repeat {repeat!r}")
        t.plan_repeat[...] = sp.writes.enum_values.index(repeat)
        period = plan.get("repeat_period")
        if period not in (None, ""):
            t.plan_period[...] = sp.quantity.bin_of(float(period))
            self.rounding = max(self.rounding, sp.quantity.error(float(period)))
        parent = plan.get("parent")
        t.plan_parent[...] = sp.pointers.NONE if parent in (None, "") else self._slot_of(parent, enc, "plan parent")

    def _slot_of(self, key: str, enc, where: str) -> int:
        if key not in enc.keys:
            raise LabelError(f"{where}: {key!r} is not a record of this decision")
        return enc.keys.index(key) + 1

    def _sequence(self, t: Targets, s: int, text: str, enc) -> None:
        sp = self.space.sequences
        try:
            steps = self.seq.encode(text, enc)
        except SequenceError as e:
            raise LabelError(str(e)) from None
        n = len(steps)
        t.seq_len[s] = n
        t.seq_sym[s, :n], t.seq_arity[s, :n], t.seq_count[s, :n] = steps.sym, steps.arity, steps.count
        t.seq_slot[s, :n] = np.where(sp.is_pointer[np.array(steps.sym)], steps.slot, NO_LABEL)
        t.seq_sym[s, n] = sp.eos
        t.seq_arity[s, n] = 0
        t.seq_count[s, n] = 0
        t.seq_depth[s, :n + 1] = steps.depths() + [0]
        t.seq_open[s, :n] = [0, *steps.open_after()[:-1]] if n else []
        t.seq_open[s, n] = 0

    def _writes(self, writes: list, enc, book: RecordIndex, t: Targets) -> None:
        sp = self.space
        if len(writes) > MAX_WRITES:
            raise LabelError(f"{len(writes)} writes > {MAX_WRITES}")
        coded = []
        for w in writes:
            var = w.get("variable")
            if var not in sp.writes.index:
                raise LabelError(f"unknown variable {var!r}")
            target = "me" if w["target"] == "self" else w["target"]
            tgt = sp.pointers.NEW if target == "new" else self._slot_of(target, enc, f"write {var}")
            coded.append((tgt, sp.writes.index[var], target, w["value"]))
        coded.sort(key=lambda c: (c[0], c[1]))                                   # a canonical order (target, variable): a set, not a story
        t.n_writes[...] = len(coded)
        for i, (tgt, v, target, value) in enumerate(coded):
            var = sp.writes.vars[v]
            kind = sp.writes.kind[v]
            t.w_var[i], t.w_target[i] = v, tgt
            kind_of_target = TargetKind.NEW if tgt == sp.pointers.NEW else TargetKind.of_key(target)
            if not sp.writes.target_ok[kind_of_target, v]:
                raise LabelError(f"{var.id} cannot be written on {target!r}")
            if kind == ValueKind.NUM_ABS:
                t.w_num[i] = self._num_abs(var, v, value)
            elif kind == ValueKind.NUM_DELTA:
                old = book.old(var, target)
                if old is None:
                    raise LabelError(f"{var.id} on {target}: no current value in the records")
                t.w_num[i] = self._num_delta(var, v, value, old)
            elif kind == ValueKind.ENUM:
                name = ("true" if value else "false") if isinstance(value, bool) else value
                if name not in sp.writes.enum_values or not sp.writes.enum_mask[v, sp.writes.enum_values.index(name)]:
                    raise LabelError(f"{var.id}: {value!r} is not one of its values")
                t.w_enum[i] = sp.writes.enum_values.index(name)
            elif kind == ValueKind.QTY:
                t.w_qty[i] = sp.quantity.bin_of(float(value))
                self.rounding = max(self.rounding, sp.quantity.error(float(value)))
            elif kind == ValueKind.PTR:
                t.w_ptr[i] = self._slot_of(value, enc, f"{var.id} value")
            else:
                self._sequence(t, 1 + i, value, enc)

    def _num_abs(self, var, v: int, value) -> int:
        lo, hi = self.space.writes.lo[v], self.space.writes.hi[v]
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise LabelError(f"{var.id}: {value!r} is not a number")
        return int(np.clip(round((float(value) - lo) / (hi - lo) * (NUM_BINS - 1)), 0, NUM_BINS - 1))

    def _num_delta(self, var, v: int, value, old: float) -> int:
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise LabelError(f"{var.id}: {value!r} is not a number")
        tenths = round((float(value) - old) / self.space.writes.step[v] * 10)
        return int(np.clip(tenths, -10, 10)) + 10

    # ================================================================================== targets -> decision
    def decode(self, t: Targets, enc, records) -> dict:
        sp = self.space
        book = RecordIndex(records)
        g = int(t.gesture)
        shape = sp.gestures.shapes[g]
        if shape is None:
            raise LabelError(f"gesture index {g} is not registered")
        params: dict[str, str] = {}
        for k, rp in enumerate(shape.refs):
            i = int(t.ref[k])
            if i != sp.pointers.NONE:
                params[rp.name] = self._name_of(i, enc, f"{shape.id}.{rp.name}")
            elif not rp.optional:
                raise LabelError(f"{shape.id}.{rp.name} is required but points at nothing")
        for e in shape.enums:
            j = int(t.manner[sp.manner.head_index[e.head]])
            values = sp.manner.values[e.head]
            if j == sp.manner.none_index(e.head):
                if not e.optional:
                    raise LabelError(f"{shape.id}.{e.name} is required")
                continue
            if not 0 <= j < len(values):
                raise LabelError(f"{shape.id}.{e.name}: level {j} is not a value of {e.head}")
            params[e.name] = values[j]
        if shape.condition:
            params[shape.condition] = self._condition_text(t, enc)
        speech = None
        if shape.expression:
            speech = self._text(t, 0, enc)
        writes = [self._write(t, i, enc, book) for i in range(int(t.n_writes))]
        out = {"gesture": shape.id, "params": params, "speech": speech, "writes": writes}
        if int(t.plan_gesture[0]) != NO_LABEL:
            out["plan"] = self._plan_dict(t, enc)
        if int(t.stop) != NO_LABEL:
            out["stop"] = self._stop_text(t, enc)
        return out

    def _plan_dict(self, t: Targets, enc) -> dict | None:
        sp = self.space
        P = sp.plan
        steps = []
        for k in range(P.cap):
            g = int(t.plan_gesture[k])
            if g == P.fin:
                break
            if not 0 <= g < sp.gestures.cap or not sp.gestures.live[g]:
                raise LabelError(f"plan step {k}: gesture index {g} is not registered")
            i = int(t.plan_ref[k])
            steps.append({"gesture": sp.gestures.names[g],
                          "target": None if i == sp.pointers.NONE else self._name_of(i, enc, f"plan step {k}")})
        if not steps:
            return None
        if len(steps) > P.used:
            raise LabelError(f"{len(steps)} plan steps > {P.used}")
        r = int(t.plan_repeat)
        if not 0 <= r < len(sp.writes.enum_values) or not P.repeat_mask[r]:
            raise LabelError(f"plan repeat index {r}")
        repeat = sp.writes.enum_values[r]
        period = int(t.plan_period)
        parent = int(t.plan_parent)
        return {"steps": steps, "repeat": repeat,
                "repeat_period": None if period == NO_LABEL else sp.quantity.value_of(period),
                "parent": None if parent in (NO_LABEL, sp.pointers.NONE) else self._name_of(parent, enc, "plan parent")}

    def _stop_text(self, t: Targets, enc) -> str | None:
        c = int(t.stop)
        if c == self.space.conditions.cap:
            return None
        return self._condition_text(t, enc, ("stop", "stop_ref", "stop_num", "stop_word"))

    def _name_of(self, i: int, enc, where: str) -> str:
        P = self.space.pointers
        if P.is_slot(i):
            if i > len(enc.keys):
                raise LabelError(f"{where}: slot {i} is empty")
            return enc.keys[i - 1]
        name = P.name_of(i)
        if name is None:
            raise LabelError(f"{where}: candidate {i} is not a reference")
        return name

    def _condition_text(self, t: Targets, enc, names=("cond", "cond_ref", "cond_num", "cond_word")) -> str:
        sp = self.space
        c_id, c_ref, c_num, c_word = (getattr(t, n) for n in names)
        c = int(c_id)
        if not 0 <= c < len(sp.conditions.ids) or not sp.conditions.live[c]:
            raise LabelError(f"condition {c}")
        head = sp.conditions.ids[c]
        out = [head]
        for j, typ in enumerate(sp.conditions.args[head]):
            kind = sp.conditions.kind_of(typ)
            if kind == 1:
                out.append(self._name_of(int(c_ref[j]), enc, f"{head} argument {j}"))
            elif kind == 2:
                out.append(str(sp.quantity.value_of(int(c_num[j]))))
            else:
                out.append(self.vocab.symbols[int(c_word[j])])
        return f"({' '.join(out)})" if len(out) > 1 else head

    def _text(self, t: Targets, s: int, enc) -> str:
        n = int(t.seq_len[s])
        if n <= 0:
            raise LabelError(f"sequence {s} is empty")
        steps = Steps(list(map(int, t.seq_sym[s, :n])), list(map(int, t.seq_arity[s, :n])),
                      [max(0, int(x)) for x in t.seq_slot[s, :n]], list(map(int, t.seq_count[s, :n])))
        try:
            return self.seq.decode(steps, enc)
        except SequenceError as e:
            raise LabelError(str(e)) from None

    def _write(self, t: Targets, i: int, enc, book: RecordIndex) -> dict:
        sp = self.space
        v = int(t.w_var[i])
        var = sp.writes.vars[v]
        if var is None:
            raise LabelError(f"variable index {v} is not registered")
        tgt = int(t.w_target[i])
        target = "new" if tgt == sp.pointers.NEW else self._name_of(tgt, enc, f"write {var.id}")
        kind = sp.writes.kind[v]
        if kind == ValueKind.NUM_ABS:
            lo, hi = sp.writes.lo[v], sp.writes.hi[v]
            value = round(float(lo + int(t.w_num[i]) * (hi - lo) / (NUM_BINS - 1)), 6)
        elif kind == ValueKind.NUM_DELTA:
            old = book.old(var, target)
            if old is None:
                raise LabelError(f"{var.id} on {target}: no current value")
            value = round(float(np.clip(old + (int(t.w_num[i]) - 10) * sp.writes.step[v] / 10, sp.writes.lo[v],
                                        sp.writes.hi[v])), 6)                        # a plain float, not a numpy scalar
        elif kind == ValueKind.ENUM:
            name = sp.writes.enum_values[int(t.w_enum[i])]
            value = (name == "true") if var.scale == "bool" else name
        elif kind == ValueKind.QTY:
            value = float(sp.quantity.value_of(int(t.w_qty[i])))
        elif kind == ValueKind.PTR:
            value = self._name_of(int(t.w_ptr[i]), enc, f"{var.id} value")
        else:
            value = self._text(t, 1 + i, enc)
        return {"target": target, "variable": var.id, "value": value}


def comparable(decision: dict) -> dict:
    """A decision reduced to what the heads can say: canonical speech and proposition texts, sorted writes, the
    governor's verdict and the notes left out. Two decisions with the same `comparable` are the same for the student."""
    from .sequences import canonical
    out = {"gesture": decision["gesture"], "params": dict(decision.get("params") or {}),
           "speech": canonical(decision["speech"]) if decision.get("speech") else None, "writes": []}
    out["params"] = {k: " ".join(v.split()) if isinstance(v, str) else v for k, v in out["params"].items()}
    for k in ("plan", "stop"):                                # only what the decision carries (older data has neither)
        if k in decision:
            out[k] = decision[k]
    for w in decision.get("writes") or []:
        val = w["value"]
        if isinstance(val, str) and (val.strip().startswith("(") or val[:2] in ("b:", "m:", "g:", "h:", "q:", "c:")):
            val = canonical(val)                                  # a proposition; a key such as b:7 is its own canonical text
        out["writes"].append({"target": "me" if w["target"] == "self" else w["target"], "variable": w["variable"], "value": val})
    out["writes"].sort(key=lambda w: (w["variable"], w["target"]))
    return out


def equivalent(a: dict, b: dict, space: OutputSpace) -> bool:
    """Same decision up to the quantisation of the numbers (half a level), the notes and the governor's verdicts."""
    a, b = comparable(a), comparable(b)
    if {k: v for k, v in a.items() if k != "writes"} != {k: v for k, v in b.items() if k != "writes"}:
        return False
    if len(a["writes"]) != len(b["writes"]):
        return False
    for x, y in zip(a["writes"], b["writes"]):
        if (x["target"], x["variable"]) != (y["target"], y["variable"]):
            return False
        v = space.writes.var(x["variable"])
        if isinstance(x["value"], float) and not isinstance(x["value"], bool) and v.numeric:
            half = (space.writes.hi[space.writes.index[v.id]] - space.writes.lo[space.writes.index[v.id]]) / (NUM_BINS - 1) / 2 \
                if v.mode == "jump" else v.step / 20
            if abs(x["value"] - y["value"]) > half + 1e-6:
                return False
        elif v.scale in ("time", "time_until"):
            if abs(math.log1p(float(x["value"])) - math.log1p(float(y["value"]))) > 0.5:
                return False
        elif x["value"] != y["value"]:
            return False
    return True
