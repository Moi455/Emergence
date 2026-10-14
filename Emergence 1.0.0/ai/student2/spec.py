"""spec.py - the OUTPUT space of the student: every head size, index and mask, derived from the catalogue and pinned by
the output registry (output_registry.py).

Nothing is typed by hand: gestures, parameters, manner heads, conditions and writable variables come from
`teacher.spec.OutputSpec` (catalogue/generated/model_interface.json "output"); their INDICES come from the append-only
output registry, and every head is sized by a fixed CAPACITY with the unused tail masked. A catalogue that grows inside
the capacities keeps the shapes, so an older checkpoint still loads (its registry must be a prefix of the current one).

Classes (each one answers one question about the heads):
  QuantityGrid   numbers of a stop condition, a deadline, a count in a proposition  -> classes (exact to 256)
  PointerSpace   what a pointer head can designate: nothing, a record slot, a direction, a form, "a new record"
  GestureTable   per gesture: its pointer parameters (<= 3), manner parameters, condition, expression, and the masks
                 that say which records / extras each pointer parameter accepts
  MannerLayout   the shared manner heads (one block of logits per scale; a "none" level for an optional absent one)
  ConditionTable the stop conditions, the type of their arguments and which records an argument accepts
  WriteTable     the writable variables, how their value is coded, which record kinds they can be written on
  SequenceSpace  the symbols of the inner-language decoder (the input vocabulary + end of sequence) and its grammar
                 masks: which arities a symbol can have (taken from the catalogue's language tables)
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from language import ref_targets
from teacher.spec import KEY_PREFIX, OutputSpec, WritableVar
from teacher.toolkit import Toolkit
from teacher.validate import ConditionChecker
from tok2.interface import InputVocabulary, canonical_json, fnv1a64
from tok2.keys import FIXED_KEYS

from .output_registry import MANNER_FLAT, MANNER_MAX, Needs, OutputRegistry

MAX_SLOTS = 128                      # tok-2 token slots (1..128)
NUM_BINS = 21                        # a bounded number: 21 levels (docs/07 3.4)
MAX_ARITY = 8                        # arity classes 0..7 (0 = leaf, 1 + n arguments for a head)
MAX_WRITES = 4
MAX_REFS = 3                         # pointers per gesture (interface: max_pointers_per_gesture)
MAX_COND_ARGS = 2
STACK = 10                           # deepest tree the decoder tracks (labels deeper than this are refused)
NO_LABEL = -100                      # ignored by cross-entropy
SCHEMA = "student2-output-2"


class SpaceError(ValueError):
    """The catalogue has something this student cannot represent yet."""


# ----------------------------------------------------------------------------------------------- numbers
class QuantityGrid:
    """Whole numbers the heads can say (a duration, a threshold, a number of hours, a count): EXACT up to 256, then a
    geometric ladder (x1.25, at most 11 % off) up to 10^7. A value is snapped to the nearest class in log space; a
    decoded class is always a whole number, so `(c_elapsed 30)` stays valid."""

    EXACT = 256
    TOP = 10_000_000
    RATIO = 1.25

    def __init__(self):
        levels = list(range(self.EXACT + 1))
        x = float(self.EXACT)
        while True:
            x *= self.RATIO
            if x >= self.TOP:
                break
            levels.append(int(round(x)))
        levels.append(self.TOP)
        self.levels = tuple(levels)
        self._log = np.log1p(np.array(self.levels, dtype=np.float64))

    def __len__(self) -> int:
        return len(self.levels)

    def bin_of(self, x: float) -> int:
        if not math.isfinite(x) or x < 0:
            raise SpaceError(f"a quantity is a finite number >= 0, got {x!r}")
        if x <= self.EXACT and float(x).is_integer():
            return int(x)
        return int(np.abs(self._log - math.log1p(min(x, self.TOP))).argmin())

    def value_of(self, b: int) -> int:
        return self.levels[b]

    def error(self, x: float) -> float:
        """Relative rounding error of x on this grid (0 when exact)."""
        v = self.levels[self.bin_of(x)]
        return abs(v - x) / max(abs(x), 1.0)


class CountGrid:
    """The count of a symbol inside a proposition (`silver_coin:3`, a bare `3`). Class 0 = no count (a bare
    `silver_coin`), 1 + class of the QuantityGrid otherwise (`silver_coin:0` is NOT `silver_coin`: tok-2)."""

    def __init__(self, grid: QuantityGrid):
        self.grid = grid

    def __len__(self) -> int:
        return 1 + len(self.grid)

    def class_of(self, n: int | None) -> int:
        return 0 if n is None else 1 + self.grid.bin_of(n)

    def count_of(self, c: int) -> int | None:
        return None if c == 0 else self.grid.value_of(c - 1)

    def error(self, n: int) -> float:
        return self.grid.error(n)


# ----------------------------------------------------------------------------------------------- pointers
class PointerSpace:
    """What a pointer head designates. Index 0 = nobody (an optional parameter left out), 1..128 = the token slot,
    then the directions (registry capacity), the forms (registry capacity) and "a new record". A ghost is never a
    target: the student points at records it can read."""

    def __init__(self, directions: list[str], forms: list[str], cap_dirs: int, cap_forms: int):
        self.directions, self.forms = tuple(directions), tuple(forms)
        self.cap_dirs, self.cap_forms = cap_dirs, cap_forms
        self.NONE = 0
        self.DIR0 = MAX_SLOTS + 1
        self.FORM0 = self.DIR0 + cap_dirs
        self.NEW = self.FORM0 + cap_forms
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
        """direction or form name of an extra candidate (None for none / slot / new / reserve)."""
        if self.DIR0 <= i < self.DIR0 + len(self.directions):
            return self.directions[i - self.DIR0]
        if self.FORM0 <= i < self.FORM0 + len(self.forms):
            return self.forms[i - self.FORM0]
        return None

    def extra_mask(self, none=False, dirs=False, forms=False, new=False) -> np.ndarray:
        """allowed[extra] over [none, directions (capacity), forms (capacity), new]; reserve entries are never allowed."""
        m = np.zeros(self.n_extra, bool)
        m[0] = none
        m[1:1 + len(self.directions)] = dirs
        m[1 + self.cap_dirs:1 + self.cap_dirs + len(self.forms)] = forms
        m[-1] = new
        return m


# ----------------------------------------------------------------------------------------------- record kinds
class TypeMasks:
    """Which record TYPES a class of references can designate, from the language tables (`ref_targets` of a sample key
    of each type). Coarse on purpose: a THING can be an item, an animal or a plant, the validator tells which."""

    def __init__(self, tk: Toolkit, tokenizer):
        self.tk, self.layout = tk, tokenizer.layout
        self.n_types = max(t.type_id for t in self.layout.types.values()) + 1
        self.sample = {}
        for name, t in self.layout.types.items():
            self.sample[t.type_id] = t.key if t.key in FIXED_KEYS else (t.key + "1")

    def classes(self, type_id: int) -> set:
        try:
            return set(ref_targets(self.sample[type_id], self.tk.vocab))
        except Exception:                                           # noqa: BLE001  (a key the language cannot point to)
            return set()

    def accepting(self, accepts) -> np.ndarray:
        """[n_types] : may a record of this type stand for something in `accepts` (classes of OutputSpec params)?"""
        m = np.zeros(self.n_types, bool)
        for tid in self.sample:
            m[tid] = bool(self.classes(tid) & set(accepts))
        return m

    def vocab_types(self, accept: set) -> np.ndarray:
        """Same for stop-condition arguments, which are typed by `Vocabulary.types` of the argument symbol."""
        m = np.zeros(self.n_types, bool)
        for tid, key in self.sample.items():
            try:
                m[tid] = bool(self.tk.vocab.types(key) & accept)
            except Exception:                                       # noqa: BLE001
                m[tid] = False
        return m

    def from_names(self, names) -> np.ndarray:
        m = np.zeros(self.n_types, bool)
        for n in names:
            if n in self.layout.types:
                m[self.layout.types[n].type_id] = True
        return m


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
    def __init__(self, spec: OutputSpec, reg: OutputRegistry, types: TypeMasks, pointers: PointerSpace):
        self.cap = reg.capacity["gestures"]
        self.names: list[str] = reg.names("gestures")                  # registry order, retired ones included
        self.index = {g: i for i, g in enumerate(self.names)}
        self.shapes: list[GestureShape | None] = [None] * self.cap
        self.live = np.zeros(self.cap, bool)
        self.ref_valid = np.zeros((self.cap, MAX_REFS), bool)
        self.ref_optional = np.zeros((self.cap, MAX_REFS), bool)
        self.has_condition = np.zeros(self.cap, bool)
        self.has_expression = np.zeros(self.cap, bool)
        self.ref_type_ok = np.ones((self.cap, MAX_REFS, types.n_types), bool)             # unused rows: no constraint
        self.ref_extra_ok = np.ones((self.cap, MAX_REFS, pointers.n_extra), bool)
        for gid, g in spec.gestures.items():
            i = self.index[gid]
            refs = tuple(RefParam(p.name, p.optional, p.accepts) for p in g.params if p.kind == "ref")
            enums = tuple(EnumParam(p.name, p.head, p.optional) for p in g.params if p.kind == "enum")
            conds = [p.name for p in g.params if p.kind == "condition"]
            exprs = [p.name for p in g.params if p.kind == "expression"]
            if len(refs) > MAX_REFS or len(conds) > 1 or len(exprs) > 1 or len({e.head for e in enums}) != len(enums):
                raise SpaceError(f"gesture {gid}: more than {MAX_REFS} pointers, or two conditions/expressions, or a "
                                 "manner head used twice: the heads must be widened")
            self.shapes[i] = GestureShape(gid, refs, enums, conds[0] if conds else None, exprs[0] if exprs else None, g.contact)
            self.live[i] = True
            self.has_condition[i], self.has_expression[i] = bool(conds), bool(exprs)
            for k, rp in enumerate(refs):
                self.ref_valid[i, k] = True
                self.ref_optional[i, k] = rp.optional
                self.ref_type_ok[i, k] = types.accepting(rp.accepts)
                self.ref_extra_ok[i, k] = pointers.extra_mask(none=rp.optional, dirs="direction" in rp.accepts,
                                                              forms="form" in rp.accepts)

    @property
    def n(self) -> int:
        """Size of the gesture head (the capacity)."""
        return self.cap

    def shape(self, gesture: str) -> GestureShape:
        return self.shapes[self.index[gesture]]


class MannerLayout:
    """The shared manner heads as one flat logit vector of fixed size. Head h owns `capacity_h + 1` logits: its values
    in registry order, the reserve (masked), and a last "none" level, allowed only for a gesture that leaves the
    parameter optional."""

    def __init__(self, spec: OutputSpec, reg: OutputRegistry, gestures: GestureTable):
        entries = reg.manner_heads()
        self.cap_heads = reg.capacity["manner_heads"]
        self.heads = [h["name"] for h in entries]
        self.values = {h["name"]: list(h["values"]) for h in entries}
        self.capacity = {h["name"]: h["capacity"] for h in entries}
        self.offset, total = {}, 0
        for h in self.heads:
            self.offset[h] = total
            total += self.capacity[h] + 1
        if total > MANNER_FLAT:
            raise SpaceError("manner logits exceed MANNER_FLAT")
        self.total = MANNER_FLAT
        self.head_index = {h: i for i, h in enumerate(self.heads)}
        self.max_width = MANNER_MAX + 1
        idx = np.zeros((self.cap_heads, self.max_width), np.int64)
        ok = np.zeros((self.cap_heads, self.max_width), bool)
        for h in self.heads:
            i = self.head_index[h]
            width = self.capacity[h] + 1
            idx[i, :width] = self.offset[h] + np.arange(width)
            ok[i, :len(self.values[h])] = True                                   # live values
            ok[i, self.capacity[h]] = True                                       # the none level (gated per gesture below)
        self.gather_index, self.gather_ok = idx, ok
        self.used = np.zeros((gestures.cap, self.cap_heads), bool)
        self.none_ok = np.zeros((gestures.cap, self.cap_heads), bool)
        for gi, s in enumerate(gestures.shapes):
            for e in (s.enums if s else ()):
                self.used[gi, self.head_index[e.head]] = True
                self.none_ok[gi, self.head_index[e.head]] = e.optional

    def value_index(self, head: str, value: str) -> int:
        try:
            return self.values[head].index(value)
        except ValueError:
            raise SpaceError(f"{value!r} is not a value of the manner head {head}") from None

    def none_index(self, head: str) -> int:
        return self.capacity[head]


# ----------------------------------------------------------------------------------------------- conditions
class ConditionTable:
    """Arguments of a stop condition are of three kinds: a record (entity, place), a number (quantity), a word (kind,
    concept, time). Each argument position has its own three small heads; the condition id says which one counts."""

    REF_TYPES = ("entity", "place")
    NUM_TYPES = ("quantity",)
    WORD_TYPES = ("kind", "concept", "time")

    def __init__(self, spec: OutputSpec, reg: OutputRegistry, types: TypeMasks):
        self.cap = reg.capacity["conditions"]
        self.ids = reg.names("conditions")
        self.index = {c: i for i, c in enumerate(self.ids)}
        self.args = {c: tuple(spec.conditions[c]) for c in self.ids if c in spec.conditions}
        self.live = np.zeros(self.cap, bool)
        self.arg_kind = np.zeros((self.cap, MAX_COND_ARGS), np.int64)            # 0 none, 1 ref, 2 number, 3 word
        self.arg_type_ok = np.ones((self.cap, MAX_COND_ARGS, types.n_types), bool)
        for c, a in self.args.items():
            if len(a) > MAX_COND_ARGS or any(t not in self.REF_TYPES + self.NUM_TYPES + self.WORD_TYPES for t in a):
                raise SpaceError(f"condition {c}: arguments {a} are not representable")
            self.live[self.index[c]] = True
            for j, t in enumerate(a):
                self.arg_kind[self.index[c], j] = self.kind_of(t)
                if t in self.REF_TYPES:
                    self.arg_type_ok[self.index[c], j] = types.vocab_types(ConditionChecker.ACCEPT[t])

    @property
    def n(self) -> int:
        return self.cap

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

    def __init__(self, spec: OutputSpec, reg: OutputRegistry, types: TypeMasks):
        self.cap = reg.capacity["write_vars"]
        self.ids = reg.names("write_vars")
        self.index = {v: i for i, v in enumerate(self.ids)}
        self.vars: list[WritableVar | None] = [spec.writes.get(v) for v in self.ids] + [None] * (self.cap - len(self.ids))
        self.live = np.array([v is not None for v in self.vars])
        self.enum_values = reg.names("enum_values")
        self.cap_enum = reg.capacity["enum_values"]
        self.kind = np.zeros(self.cap, np.int64)
        self.enum_mask = np.zeros((self.cap, self.cap_enum), bool)
        self.target_ok = np.zeros((len(TargetKind.NAMES), self.cap), bool)
        self.step = np.ones(self.cap, np.float64)
        self.lo, self.hi = np.zeros(self.cap), np.ones(self.cap)
        self.mref_type_ok = np.ones((self.cap, types.n_types), bool)
        for i, v in enumerate(self.vars):
            if v is None:
                continue
            self.kind[i] = self._kind(v)
            for x in self._values(v):
                self.enum_mask[i, self.enum_values.index(x)] = True
            self.target_ok[TargetKind.NAMES.index(v.target_kind), i] = True
            if v.creatable and v.scale == "proposition":
                self.target_ok[TargetKind.NEW, i] = True
            self.step[i] = v.step if v.step > 0 else 1.0
            self.lo[i], self.hi[i] = v.bounds or (0.0, 1.0)
            if v.scale == "mref":
                names = {t for t, f in v.fields}
                refs = set()
                for t, f in v.fields:
                    col = types.layout.types[t].columns.get(f) if t in types.layout.types else None
                    refs |= set(col.codec.spec.get("ref_types", ())) if col is not None else set()
                self.mref_type_ok[i] = types.from_names(refs) if refs else np.ones(types.n_types, bool)

    @property
    def n(self) -> int:
        return self.cap

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
    (symbol, arity, record slot for a pointer, count class). The symbols are the input vocabulary itself;
    `eos` is one extra output class, `bos` one extra input row. `arity_ok[sym, arity]` says which arities a symbol can
    have, from the language tables of the catalogue: a mood or a time word takes one proposition, `not` one, `and` two,
    a predicate its declared arguments, `did` an agent, a gesture and up to a target and 3 roles; every other word
    is a leaf."""

    MAX_SEQUENCES = 1 + MAX_WRITES          # the speech, then one proposition per write

    def __init__(self, tokenizer, spec: OutputSpec, tk: Toolkit):
        v = tokenizer.vocab
        self.vocab_size = len(v)
        self.eos, self.bos = self.vocab_size, self.vocab_size + 1
        self.max_symbols = spec.max_symbols
        self.steps = self.max_symbols + 1                # the symbols, then the end of sequence
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
        self.pointer_kind_of = np.full(self.vocab_size + 2, -1, np.int64)          # sym -> index in POINTER_KINDS
        for i, k in enumerate(self.pointer_kind_ids):
            self.pointer_kind_of[k] = i
        self.name_ids = np.array([v.name_id(k) for k in range(InputVocabulary.NAME_SLOTS)], np.int64)
        self.num_id = v.ids[InputVocabulary.NUM]
        self.arity_ok = self._arity_tables(v, tk)

    def _arity_tables(self, v, tk: Toolkit) -> np.ndarray:
        ok = np.zeros((self.vocab_size + 2, MAX_ARITY), bool)
        ok[:, 0] = True                                                  # everything can be a leaf unless it is a head only
        heads: dict[str, set] = {}
        concepts = tk.vocab.cat["concept"]
        for name, c in concepts.items():
            cat = c.category
            if cat == "mood":
                heads[name] = {2}
            elif cat == "formula":
                heads[name] = {1, 2, 3}                                  # (yes) (yes UTT) (yes h:2) (yes h:2 UTT)
            elif cat == "logic":
                heads[name] = {2} if name in ("not", "that") else {3}
            elif cat in ("time", "evidential"):
                heads[name] = {2}
            elif cat == "time_op":                                       # (at_time TIME PROP)
                heads[name] = {3}
            elif cat == "event_role":
                heads[name] = {2}
            elif cat == "predicate":
                heads[name] = {1 + len(c.args)}
        heads["did"] = set(range(3, 8))                              # agent, gesture, [target], <= 3 roles: 2..6 arguments
        heads["described"] = set(range(2, MAX_ARITY))
        for g in tk.vocab.cat["action"].values():                    # a role is named by a parameter of a gesture: (to X), (at X), (where X)
            for prm in g.params:
                if prm.type == "ref" and prm.name in v.ids:
                    heads.setdefault(prm.name, set()).add(2)
        heads["span"] = {3}                                          # (span N UNIT)
        heads["of"] = {3}                                            # (of QUANTITY GROUP)
        for name, arities in heads.items():
            if name not in v.ids:
                continue
            i = v.ids[name]
            cats = tk.vocab.cats.get(name, set())
            as_leaf = bool(cats - {"mood", "formula", "logic", "time", "evidential", "event_role", "predicate", "time_op", "time_form", "ref_node"})
            ok[i] = False
            ok[i, list(arities)] = True
            ok[i, 0] = as_leaf                                           # a word that is also a kind or a manner can be a leaf
        ok[self.eos] = False
        ok[self.eos, 0] = True
        ok[self.bos] = False
        ok[self.bos, 0] = True
        return ok


# ----------------------------------------------------------------------------------------------- the whole space
class OutputSpace:
    """All output heads of the student for one catalogue state. Built from a Toolkit (catalogue, output spec), the tok-2
    Tokenizer (input vocabulary, layout) and the output registry."""

    def __init__(self, tk: Toolkit, tokenizer, registry: OutputRegistry | None = None):
        self.tk, self.tokenizer = tk, tokenizer
        spec = tk.spec
        self.spec = spec
        self.registry = registry or OutputRegistry.load()
        self.registry.require(Needs(spec, sorted(tk.cat["form"])))
        self.types = TypeMasks(tk, tokenizer)
        self.quantity = QuantityGrid()
        self.counts = CountGrid(self.quantity)
        reg = self.registry
        self.pointers = PointerSpace(reg.names("directions"), reg.names("forms"), reg.capacity["directions"], reg.capacity["forms"])
        self.gestures = GestureTable(spec, reg, self.types, self.pointers)
        self.manner = MannerLayout(spec, reg, self.gestures)
        self.conditions = ConditionTable(spec, reg, self.types)
        self.writes = WriteTable(spec, reg, self.types)
        self.sequences = SequenceSpace(tokenizer, spec, tk)
        self.max_symbols = spec.max_symbols
        self.n_types = self.types.n_types
        self.self_type = tokenizer.layout.types["SELF"].type_id
        self.fingerprint = self._fingerprint()

    def _fingerprint(self) -> int:
        """Of what fixes the shapes and the meaning of the grids: stable while the catalogue grows inside the
        registry capacities (the growth itself is checked by `OutputRegistry.compatible`)."""
        grids = {"schema": SCHEMA, "quantity": [QuantityGrid.EXACT, QuantityGrid.RATIO, QuantityGrid.TOP], "max_slots": MAX_SLOTS,
                 "num_bins": NUM_BINS, "max_arity": MAX_ARITY, "stack": STACK, "registry": f"{self.registry.fingerprint:016x}"}
        return fnv1a64(canonical_json(grids))
