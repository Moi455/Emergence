"""spec.py - the OUTPUT space of the student: every head size, index and mask, derived from the catalogue.

Nothing is typed by hand: gestures, parameters, manner heads, conditions and writable variables come from
`teacher.spec.OutputSpec` (read from catalogue/generated/model_interface.json "output"), the input vocabulary from the
tok-2 tokenizer. Adding a gesture or a variable to the catalogue changes the sizes here and the fingerprint, so a
checkpoint trained on the old interface is refused (see fingerprints.py).

Classes (each one answers one question about the heads):
  QuantityGrid   numbers of a stop condition or a deadline  -> bins
  CountGrid      counts inside a proposition (silver_coin:3) -> classes
  PointerSpace   what a pointer head can designate: nothing, a record slot, a direction, a form, "a new record"
  GestureTable   per gesture: its pointer parameters (<= 3), manner parameters, condition, expression
  MannerLayout   the shared manner heads (one block of logits per scale, "none" for an optional absent one)
  ConditionTable the 23 stop conditions and the type of their arguments
  WriteTable     the writable variables, how their value is coded, which record kinds they can be written on
  SequenceSpace  the symbols of the inner-language decoder (the input vocabulary + end of sequence)
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass

import numpy as np

from teacher.spec import KEY_PREFIX, OutputSpec, WritableVar
from teacher.toolkit import Toolkit
from tok2.interface import INTERFACE_PATH, InputVocabulary, canonical_json, fnv1a64

MAX_SLOTS = 128                      # tok-2 token slots (1..128)
NUM_BINS = 21                        # a bounded number: 21 levels (docs/07 3.4)
MAX_ARITY = 8                        # arity classes 0..7 (0 = leaf, 1 + n arguments for a head)
MAX_WRITES = 4
MAX_REFS = 3                         # pointers per gesture (interface: max_pointers_per_gesture)
NO_LABEL = -100                      # ignored by cross-entropy


class SpaceError(ValueError):
    """The catalogue has something this student cannot represent yet."""


# ----------------------------------------------------------------------------------------------- numbers
class QuantityGrid:
    """Whole numbers the heads can say (a duration, a threshold, a number of hours): exact up to 12, then a
    1-2-3-5 ladder up to 10^7. A value is snapped to the nearest level in log space; a decoded level is always a
    whole number, so a stop condition `(c_elapsed 30)` stays valid."""

    LEVELS = tuple(sorted({*range(0, 13), 15, 16, 20, 24, 25, 30, 36, 40, 45, 48, 50, 60, 72, 75, 90, 100, 120, 150, 168,
                           200, 240, 300, 360, 480, 500, 600, 720, 900, 1000, 1500, 2000, 3000, 5000, 10_000, 30_000,
                           100_000, 1_000_000, 10_000_000}))

    def __init__(self):
        self._log = np.log1p(np.array(self.LEVELS, dtype=np.float64))

    def __len__(self) -> int:
        return len(self.LEVELS)

    def bin_of(self, x: float) -> int:
        if not math.isfinite(x) or x < 0:
            raise SpaceError(f"a quantity is a finite number >= 0, got {x!r}")
        return int(np.abs(self._log - math.log1p(min(x, self.LEVELS[-1]))).argmin())

    def value_of(self, b: int) -> int:
        return self.LEVELS[b]


class CountGrid:
    """The count of a symbol inside a proposition (`silver_coin:3`, a bare `3`). Class 0 = no count (a bare
    `silver_coin`), 1 + n for n in 0..31 (`silver_coin:0` is NOT `silver_coin`: tok-2), then a ladder to 10^7."""

    EXACT = 32
    LADDER = (40, 50, 64, 80, 100, 128, 160, 200, 256, 500, 1000, 5000, 10_000, 100_000, 1_000_000, 10_000_000)

    def __init__(self):
        self.values = (None, *range(self.EXACT), *self.LADDER)
        self._log = np.log1p(np.array(self.values[1:], dtype=np.float64))

    def __len__(self) -> int:
        return len(self.values)

    def class_of(self, n: int | None) -> int:
        if n is None:
            return 0
        if n < 0 or n > 10_000_000:
            raise SpaceError(f"count {n} out of range")
        if n < self.EXACT:
            return 1 + n
        return 1 + int(np.abs(self._log - math.log1p(n)).argmin())

    def count_of(self, c: int) -> int | None:
        return self.values[c]


# ----------------------------------------------------------------------------------------------- pointers
class PointerSpace:
    """What a pointer head designates. Index 0 = nobody (an optional parameter left out), 1..128 = the token slot,
    then the 10 relative directions, the forms (blade, hook...) and "a new record" (creating a belief, a goal).
    A ghost is never a target: the student points at records it can read."""

    def __init__(self, directions: tuple, forms: list[str]):
        self.directions, self.forms = tuple(directions), tuple(forms)
        self.NONE = 0
        self.SLOT0 = 1                                    # slot s is index s
        self.DIR0 = MAX_SLOTS + 1
        self.FORM0 = self.DIR0 + len(self.directions)
        self.NEW = self.FORM0 + len(self.forms)
        self.size = self.NEW + 1
        self._dir = {d: self.DIR0 + i for i, d in enumerate(self.directions)}
        self._form = {f: self.FORM0 + i for i, f in enumerate(self.forms)}

    @property
    def n_extra(self) -> int:
        """Candidates that are not slots: none + directions + forms + new (learned vectors, not tokens)."""
        return self.size - MAX_SLOTS

    def of_direction(self, name: str) -> int | None:
        return self._dir.get(name)

    def of_form(self, name: str) -> int | None:
        return self._form.get(name)

    def is_slot(self, i: int) -> bool:
        return 1 <= i <= MAX_SLOTS

    def name_of(self, i: int) -> str | None:
        """direction or form name of an extra candidate (None for none / slot / new)."""
        if self.DIR0 <= i < self.FORM0:
            return self.directions[i - self.DIR0]
        if self.FORM0 <= i < self.NEW:
            return self.forms[i - self.FORM0]
        return None

    def masks(self) -> dict[str, np.ndarray]:
        """Which extras each head may point at: allowed[extra] over [none, dirs..., forms..., new]."""
        def m(none=False, dirs=False, forms=False, new=False):
            return np.array([none, *[dirs] * len(self.directions), *[forms] * len(self.forms), new], dtype=bool)
        return {"ref": m(none=True, dirs=True, forms=True), "write_target": m(new=True), "slot_only": m(),
                "slot_or_none": m(none=True)}


# ----------------------------------------------------------------------------------------------- gestures
@dataclass(frozen=True)
class RefParam:
    name: str
    optional: bool
    accepts: tuple


@dataclass(frozen=True)
class EnumParam:
    name: str
    head: str
    optional: bool


@dataclass(frozen=True)
class GestureShape:
    id: str
    refs: tuple                  # RefParam, in catalogue order: the k-th one is read by pointer query k
    enums: tuple                 # EnumParam
    condition: str | None        # name of the stop-condition parameter ('until'), or None
    expression: str | None       # name of the expression parameter ('content'), or None
    contact: bool


class GestureTable:
    def __init__(self, spec: OutputSpec):
        self.ids = list(spec.gesture_ids)
        self.index = {g: i for i, g in enumerate(self.ids)}
        self.shapes: list[GestureShape] = []
        for gid in self.ids:
            g = spec.gestures[gid]
            refs = tuple(RefParam(p.name, p.optional, p.accepts) for p in g.params if p.kind == "ref")
            enums = tuple(EnumParam(p.name, p.head, p.optional) for p in g.params if p.kind == "enum")
            conds = [p.name for p in g.params if p.kind == "condition"]
            exprs = [p.name for p in g.params if p.kind == "expression"]
            if len(refs) > MAX_REFS or len(conds) > 1 or len(exprs) > 1 or len({e.head for e in enums}) != len(enums):
                raise SpaceError(f"gesture {gid}: more than {MAX_REFS} pointers, or two conditions/expressions, or a "
                                 "manner head used twice: the heads must be widened")
            self.shapes.append(GestureShape(gid, refs, enums, conds[0] if conds else None, exprs[0] if exprs else None,
                                            g.contact))
        self.n = len(self.ids)
        # ref_valid[g, k] : gesture g has a k-th pointer parameter ; ref_optional[g, k]
        self.ref_valid = np.zeros((self.n, MAX_REFS), bool)
        self.has_condition = np.array([s.condition is not None for s in self.shapes])
        self.has_expression = np.array([s.expression is not None for s in self.shapes])
        for i, s in enumerate(self.shapes):
            self.ref_valid[i, :len(s.refs)] = True

    def shape(self, gesture: str) -> GestureShape:
        return self.shapes[self.index[gesture]]


class MannerLayout:
    """The shared manner heads as one flat logit vector: for each scale (intensity, go.pace, contact_zone...) a block
    of its values, plus one "none" level when some gesture leaves that parameter optional (go.stop_at)."""

    def __init__(self, spec: OutputSpec, gestures: GestureTable):
        self.heads = sorted(spec.manner_heads)
        self.values = {h: list(spec.manner_heads[h]["values"]) for h in self.heads}
        optional = {e.head for s in gestures.shapes for e in s.enums if e.optional}
        self.has_none = {h: h in optional for h in self.heads}
        self.width = {h: len(self.values[h]) + int(self.has_none[h]) for h in self.heads}
        self.offset: dict[str, int] = {}
        total = 0
        for h in self.heads:
            self.offset[h] = total
            total += self.width[h]
        self.total = total
        self.head_index = {h: i for i, h in enumerate(self.heads)}
        self.max_width = max(self.width.values())
        # gather table [H, max_width] into the flat logits, and the validity of each cell
        idx = np.zeros((len(self.heads), self.max_width), np.int64)
        ok = np.zeros((len(self.heads), self.max_width), bool)
        for i, h in enumerate(self.heads):
            idx[i, :self.width[h]] = self.offset[h] + np.arange(self.width[h])
            ok[i, :self.width[h]] = True
        self.gather_index, self.gather_ok = idx, ok
        # used[g, h] : gesture g has a parameter on head h
        self.used = np.zeros((gestures.n, len(self.heads)), bool)
        for i, s in enumerate(gestures.shapes):
            for e in s.enums:
                self.used[i, self.head_index[e.head]] = True

    def value_index(self, head: str, value: str) -> int:
        try:
            return self.values[head].index(value)
        except ValueError:
            raise SpaceError(f"{value!r} is not a value of the manner head {head}") from None

    def none_index(self, head: str) -> int:
        if not self.has_none[head]:
            raise SpaceError(f"head {head} has no 'none' level")
        return len(self.values[head])


# ----------------------------------------------------------------------------------------------- conditions
class ConditionTable:
    """Arguments of a stop condition are of three kinds: a record (entity, place), a number (quantity), a word (kind,
    concept, time). Each argument position has its own three small heads; the condition id says which one counts."""

    REF_TYPES = ("entity", "place")
    NUM_TYPES = ("quantity",)
    WORD_TYPES = ("kind", "concept", "time")
    MAX_ARGS = 2

    def __init__(self, spec: OutputSpec):
        self.ids = sorted(spec.conditions)
        self.index = {c: i for i, c in enumerate(self.ids)}
        self.args = {c: tuple(spec.conditions[c]) for c in self.ids}
        for c, a in self.args.items():
            if len(a) > self.MAX_ARGS or any(t not in self.REF_TYPES + self.NUM_TYPES + self.WORD_TYPES for t in a):
                raise SpaceError(f"condition {c}: arguments {a} are not representable")
        n = len(self.ids)
        self.arg_kind = np.zeros((n, self.MAX_ARGS), np.int64)         # 0 none, 1 ref, 2 number, 3 word
        for c, a in self.args.items():
            for j, t in enumerate(a):
                self.arg_kind[self.index[c], j] = 1 if t in self.REF_TYPES else 2 if t in self.NUM_TYPES else 3
        self.n = n

    def kind_of(self, arg_type: str) -> int:
        return 1 if arg_type in self.REF_TYPES else 2 if arg_type in self.NUM_TYPES else 3


# ----------------------------------------------------------------------------------------------- writes
class ValueKind:
    NUM_ABS, NUM_DELTA, ENUM, QTY, PTR, PROP = range(6)
    NAMES = ("num_abs", "num_delta", "enum", "qty", "ptr", "prop")


class TargetKind:
    """The record kind a write is addressed to (0 = a record nothing can be written on)."""
    OTHER, SELF, ENTITY, BELIEF, GOAL, MEMORY, PLAN, NEW = range(8)
    NAMES = ("other", "self", "entity", "belief", "goal", "memory", "plan", "new")

    @classmethod
    def of_key(cls, key: str) -> int:
        if key == "me":
            return cls.SELF
        for kind, prefixes in KEY_PREFIX.items():
            if key.startswith(prefixes):
                return cls.NAMES.index(kind)
        return cls.OTHER


class WriteTable:
    """The variables the student may write (the teacher-writable ones: list variables are left out), how each
    value is coded, and which kinds of record each can be written on."""

    def __init__(self, spec: OutputSpec):
        self.vars: list[WritableVar] = [spec.writes[v] for v in sorted(spec.writes)]
        self.ids = [v.id for v in self.vars]
        self.index = {v: i for i, v in enumerate(self.ids)}
        self.n = len(self.vars)
        self.kind = np.zeros(self.n, np.int64)
        enum_values: list[str] = []
        for v in self.vars:
            for x in self._values(v):
                if x not in enum_values:
                    enum_values.append(x)
        self.enum_values = enum_values                              # the union of every enumerated value
        self.enum_mask = np.zeros((self.n, len(enum_values)), bool)  # which of them each variable accepts
        for i, v in enumerate(self.vars):
            self.kind[i] = self._kind(v)
            for x in self._values(v):
                self.enum_mask[i, enum_values.index(x)] = True
        # target_ok[target kind, var]: may var be written on a record of this kind ?
        self.target_ok = np.zeros((len(TargetKind.NAMES), self.n), bool)
        for i, v in enumerate(self.vars):
            self.target_ok[TargetKind.NAMES.index(v.target_kind), i] = True
            if v.creatable and v.scale == "proposition":
                self.target_ok[TargetKind.NEW, i] = True
        self.step = np.array([v.step for v in self.vars], np.float64)
        self.lo = np.array([(v.bounds or (0.0, 0.0))[0] for v in self.vars], np.float64)
        self.hi = np.array([(v.bounds or (0.0, 0.0))[1] for v in self.vars], np.float64)

    @staticmethod
    def _values(v: WritableVar) -> tuple:
        if v.scale == "bool":
            return ("false", "true")
        return v.values if v.scale in ("enum", "word") else ()

    @staticmethod
    def _kind(v: WritableVar) -> int:
        if v.scale in ("bipolar10", "unipolar10", "ratio"):
            return ValueKind.NUM_ABS if v.mode == "jump" else ValueKind.NUM_DELTA
        if v.scale in ("bool", "enum", "word"):
            if not WriteTable._values(v):
                raise SpaceError(f"{v.id}: an enumerated variable without values")
            return ValueKind.ENUM
        if v.scale in ("time", "time_until"):
            return ValueKind.QTY
        if v.scale == "mref":
            return ValueKind.PTR
        if v.scale == "proposition":
            return ValueKind.PROP
        raise SpaceError(f"{v.id}: scale {v.scale!r} (quantities and lists are not written by the student yet)")

    def var(self, name: str) -> WritableVar:
        return self.vars[self.index[name]]


# ----------------------------------------------------------------------------------------------- sequences
class SequenceSpace:
    """The inner-language decoder writes prefix symbols with their arity, like the tok-2 proposition columns:
    (symbol, arity, record slot for a pointer, count class). The symbols are the input vocabulary itself (so the
    embeddings are shared with what the model reads); `eos` is one extra output class, `bos` one extra input row."""

    MAX_SEQUENCES = 1 + MAX_WRITES          # the speech, then one proposition per write

    def __init__(self, tokenizer, spec: OutputSpec, writes: WriteTable):
        v = tokenizer.vocab
        self.vocab_size = len(v)
        self.eos, self.bos = self.vocab_size, self.vocab_size + 1
        self.max_symbols = spec.max_symbols
        self.steps = self.max_symbols + 1                # the symbols, then the end of sequence
        self.max_depth = spec.max_depth
        iface = tokenizer.interface
        words = set(iface.grammar_words) | set(iface.kinds)
        allowed = np.zeros(self.vocab_size + 1, bool)    # structural: which output classes are ever legal
        for w in words:
            allowed[v.ids[w]] = True
        for k in InputVocabulary.POINTER_KINDS:
            allowed[v.ids[k]] = True
        allowed[v.ids[InputVocabulary.NUM]] = True
        for k in range(InputVocabulary.NAME_SLOTS):
            allowed[v.name_id(k)] = True
        allowed[self.eos] = True
        self.allowed = allowed
        self.pointer_kind_ids = np.array([v.ids[k] for k in InputVocabulary.POINTER_KINDS], np.int64)
        self.is_pointer = np.zeros(self.vocab_size + 2, bool)
        self.is_pointer[self.pointer_kind_ids] = True
        self.name_ids = np.array([v.name_id(k) for k in range(InputVocabulary.NAME_SLOTS)], np.int64)
        self.num_id = v.ids[InputVocabulary.NUM]
        self.speech_roles = 1 + writes.n                  # role 0 = speech, 1 + variable index = a written proposition


# ----------------------------------------------------------------------------------------------- the whole space
class OutputSpace:
    """All output heads of the student for one catalogue state. Built from a Toolkit (catalogue, output spec) and
    the tok-2 Tokenizer (input vocabulary): `OutputSpace(toolkit, tokenizer)`."""

    SCHEMA = "student2-output-1"

    def __init__(self, tk: Toolkit, tokenizer):
        self.tk, self.tokenizer = tk, tokenizer
        spec = tk.spec
        self.spec = spec
        self.quantity, self.counts = QuantityGrid(), CountGrid()
        self.pointers = PointerSpace(spec.directions, sorted(tk.cat["form"]))
        self.gestures = GestureTable(spec)
        self.manner = MannerLayout(spec, self.gestures)
        self.conditions = ConditionTable(spec)
        self.writes = WriteTable(spec)
        self.sequences = SequenceSpace(tokenizer, spec, self.writes)
        self.max_symbols = spec.max_symbols
        self.n_types = max(t.type_id for t in tokenizer.layout.types.values()) + 1
        self.self_type = tokenizer.layout.types["SELF"].type_id
        self.fingerprint = self._fingerprint()

    def _fingerprint(self) -> int:
        """Of the OUTPUT subtree of model_interface.json (every head size) and of this module's grids."""
        out = json.loads(INTERFACE_PATH.read_bytes())["output"]
        grids = {"schema": self.SCHEMA, "quantity": list(QuantityGrid.LEVELS), "counts": [CountGrid.EXACT, *CountGrid.LADDER],
                 "forms": list(self.pointers.forms), "max_slots": MAX_SLOTS, "num_bins": NUM_BINS, "max_arity": MAX_ARITY,
                 "enum_values": self.writes.enum_values, "write_vars": self.writes.ids}
        return fnv1a64(canonical_json({"output": out, "student": grids}))
