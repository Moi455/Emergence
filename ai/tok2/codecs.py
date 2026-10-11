"""codecs.py - how one field of a token type is written into the fixed-shape arrays of a decision.

A token is one RECORD of the NPC's mind (a person file, a belief, a thing he sees...). Its fields go into blocks:
  num   float16  scalars (charter scales /10, ratio, bool, log quantities, log ages) and named or object vectors
  cat   int16    enum and word ids (one column), word lists (BAG_CAP columns): ids of the InputVocabulary
  ptr   uint8    pointers to other tokens of the same decision: 0 none, 1..128 slot, 129 + k ghost (see layout.py)
  prop           the one proposition of the record (belief, goal, memory, request, commitment, heard), prefix order
and one flag array per block (num -> known, cat -> cat_known, ptr -> ptr_known): UNKNOWN IS NOT EMPTY.
  absent field or None   unknown (flag 0, value 0)
  pointer ""             known: nobody          list []   known: empty (every column of the list flagged)
  list-of-vectors []     known: every component 0

Numbers are normalised in double precision, then rounded ONCE to IEEE binary16 (round to nearest even), -0.0 -> 0.0.
A value outside its charter scale is an engine bug: refused (TokenError), never clipped.
"""
from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np

from .errors import TokenError

BAG_CAP = 6          # words per word list (the engine keeps the most salient: the 2 worst wounds = 6 words)
PTR_LIST_CAP = 4     # pointers per pointer list (to whom a belief was told, witnesses of a commitment)
QTY_MAX = 10_000_000                     # |quantity|, hours, counts
NONE_SLOT, GHOST_BASE, GHOST_SLOTS = 0, 129, 32
GHOST_OVERFLOW = GHOST_BASE + GHOST_SLOTS     # 161: a known record out of the batch, when 32 ghosts are already used
OUT_OF_CONTEXT = GHOST_BASE                   # compatibility name: the first ghost slot
SIGNED_UNITS = {"°C"}                         # the only units whose quantity may be negative
SUM_COMPONENTS = {"mass"}                     # pooled by sum when several objects are held; every other one by max


def signed_log(x: float) -> float:
    return math.copysign(math.log1p(abs(x)), x)


def to_half(x: float) -> np.float16:
    """One rounding, from the double: never through float32."""
    return np.float16(x)


class ScaleNorm:
    """Charter scales and units -> model inputs (the formulas are FORMULAS, pinned in golden/layout.json)."""

    FORMULAS = {
        "bipolar10": "x / 10, x in [-10, 10]",
        "unipolar10": "x / 10, x in [0, 10]",
        "ratio": "x, x in [0, 1]",
        "unit": "x, x in [-1, 1]",
        "bool": "1 if x else 0 (a real bool)",
        "qty": "log1p(x), x in [0, 1e7]",
        "qty_signed": "copysign(log1p(|x|), x), |x| <= 1e7 (unit degC only)",
        "time": "log1p(x), x in [0, 1e7] game hours since",
        "time_until": "copysign(log1p(|x|), x), |x| <= 1e7 game hours until (negative: overdue)",
    }

    @staticmethod
    def coerce(x, where: str):
        """A python bool, int or finite float from a python or numpy scalar; anything else is refused."""
        if isinstance(x, np.generic):
            x = x.item()
        if isinstance(x, (bool, int)):
            return x
        if isinstance(x, float):
            if not math.isfinite(x):
                raise TokenError(f"{where}: finite number expected, got {x!r}")
            return x
        raise TokenError(f"{where}: a number expected, got {type(x).__name__} {x!r:.40}")

    @staticmethod
    def formula(scale: str, unit: str = "") -> str:
        return ScaleNorm.FORMULAS["qty_signed" if scale == "qty" and unit in SIGNED_UNITS else scale]

    @staticmethod
    def apply(scale: str, x, where: str, unit: str = "") -> float:
        x = ScaleNorm.coerce(x, where)
        if isinstance(x, bool):
            if scale != "bool":
                raise TokenError(f"{where}: a bool for a {scale} field")
            return 1.0 if x else 0.0
        if scale == "bool":
            raise TokenError(f"{where}: bool expected, got {x!r}")
        if scale == "bipolar10":
            ScaleNorm._range(x, -10, 10, where)
            r = x / 10
        elif scale == "unipolar10":
            ScaleNorm._range(x, 0, 10, where)
            r = x / 10
        elif scale == "ratio":
            ScaleNorm._range(x, 0, 1, where)
            r = float(x)
        elif scale == "unit":                     # a named component, given normalised by the engine
            ScaleNorm._range(x, -1, 1, where)
            r = float(x)
        elif scale == "qty":
            signed = unit in SIGNED_UNITS
            ScaleNorm._range(x, -QTY_MAX if signed else 0, QTY_MAX, where)
            r = signed_log(x) if signed else math.log1p(x)
        elif scale == "time":                     # age in game hours
            ScaleNorm._range(x, 0, QTY_MAX, where)
            r = math.log1p(x)
        elif scale == "time_until":               # hours until a point in the future, negative when overdue
            ScaleNorm._range(x, -QTY_MAX, QTY_MAX, where)
            r = signed_log(x)
        else:
            raise TokenError(f"{where}: no numeric encoding for scale {scale}")
        return r + 0.0                            # -0.0 + 0.0 == 0.0

    @staticmethod
    def _range(x, lo, hi, where):
        if not lo <= x <= hi:
            raise TokenError(f"{where}: {x} outside [{lo}, {hi}]")


class FieldCodec(ABC):
    """One field of a token type: its block, its width, and how a value is written there."""
    block: str = ""

    def __init__(self, name: str, spec: dict, where: str):
        self.name, self.spec, self.where = name, spec, where

    @property
    @abstractmethod
    def width(self) -> int: ...

    @property
    def kind(self) -> str:
        return type(self).__name__

    def normalisation(self) -> str:
        """What the C++ port must compute (golden/layout.json)."""
        return ""

    @abstractmethod
    def write(self, value, row, col: int, state) -> None:
        """Write `value` (never None: absent fields are left unknown) at columns col..col+width of `row`."""


class ScalarCodec(FieldCodec):
    block = "num"
    width = 1

    def normalisation(self):
        return ScaleNorm.formula(self.spec["scale"], self.spec.get("unit", ""))

    def write(self, value, row, col, state):
        row.num[col] = to_half(ScaleNorm.apply(self.spec["scale"], value, self.where, self.spec.get("unit", "")))
        row.known[col] = 1


class VectorCodec(FieldCodec):
    """A list of qty with named components (sin/cos, reputation axes) or the object vector. Value: a dict
    component -> value (a missing component stays unknown), a list in component order, or for a list of vectors
    (what is held in both hands) a list of dicts, pooled per component: SUM for `mass`, MAX for the others. An
    empty list is a known empty hand: every component known, 0."""
    block = "num"

    def __init__(self, name, spec, where):
        super().__init__(name, spec, where)
        self.components: list[str] = spec["components"]
        self.scales: list[str] = spec["component_scales"]
        self.units: list[str] = spec.get("component_units") or [""] * len(self.components)
        self.index = {c: i for i, c in enumerate(self.components)}

    @property
    def width(self):
        return len(self.components)

    def normalisation(self):
        return {c: ScaleNorm.formula(s, u) for c, s, u in zip(self.components, self.scales, self.units)} \
            if len(set(self.scales)) > 1 or len(set(self.units)) > 1 else ScaleNorm.formula(self.scales[0], self.units[0])

    def _one(self, value) -> dict:
        unknown = set(value) - set(self.index)
        if unknown:
            raise TokenError(f"{self.where}: unknown components {sorted(map(str, unknown))}")
        return {c: ScaleNorm.coerce(x, f"{self.where}.{c}") for c, x in value.items()}

    def _items(self, value) -> dict | None:
        if isinstance(value, dict):
            return self._one(value)
        if isinstance(value, (list, tuple)):
            if not value:
                if self.spec["scale"] != "list":
                    raise TokenError(f"{self.where}: an empty list is only meaningful for a list of vectors")
                return None                                   # known empty
            if all(isinstance(v, dict) for v in value):
                pooled: dict = {}
                for v in value:
                    one = self._one(v)
                    for c, x in one.items():                  # each item is checked on its own before pooling
                        i = self.index[c]
                        ScaleNorm.apply(self.scales[i], x, f"{self.where}.{c}", self.units[i])
                        if c not in pooled:
                            pooled[c] = x
                        else:
                            pooled[c] = pooled[c] + x if c in SUM_COMPONENTS else max(pooled[c], x)
                return pooled
            if len(value) == self.width:
                return self._one(dict(zip(self.components, value)))
        raise TokenError(f"{self.where}: a dict of components, a list of {self.width} values or a list of dicts")

    def write(self, value, row, col, state):
        items = self._items(value)
        if items is None:
            row.num[col:col + self.width] = 0
            row.known[col:col + self.width] = 1
            return
        for c, x in items.items():
            i = self.index[c]
            row.num[col + i] = to_half(ScaleNorm.apply(self.scales[i], x, f"{self.where}.{c}", self.units[i]))
            row.known[col + i] = 1


class SymbolCodec(FieldCodec):
    """enum (one of its values) or word (a catalogue word, or a name n:<id> aliased per decision)."""
    block = "cat"
    width = 1

    def write(self, value, row, col, state):
        row.cat[col] = state.symbol_id(value, self.spec, self.where)
        row.cat_known[col] = 1


class BagCodec(FieldCodec):
    """A list of words or enum values: at most BAG_CAP symbols, in the order the engine gave (salience first).
    Every column of the bag is flagged known, so [] is a known empty list."""
    block = "cat"
    width = BAG_CAP

    def write(self, value, row, col, state):
        if not isinstance(value, (list, tuple)):
            raise TokenError(f"{self.where}: a list expected")
        if len(value) > BAG_CAP:
            raise TokenError(f"{self.where}: {len(value)} words > {BAG_CAP} (the engine keeps the most salient)")
        for i, w in enumerate(value):
            row.cat[col + i] = state.symbol_id(w, self.spec, self.where)
        row.cat_known[col:col + self.width] = 1


class PointerCodec(FieldCodec):
    block = "ptr"
    width = 1

    def write(self, value, row, col, state):
        state.pointer(value, self.where, row, "ptr", col)
        row.ptr_known[col] = 1


class PointerListCodec(FieldCodec):
    block = "ptr"
    width = PTR_LIST_CAP

    def write(self, value, row, col, state):
        if not isinstance(value, (list, tuple)) or len(value) > PTR_LIST_CAP:
            raise TokenError(f"{self.where}: a list of at most {PTR_LIST_CAP} pointers expected")
        for i, k in enumerate(value):
            if k == "":
                raise TokenError(f"{self.where}: an empty pointer inside a list (leave it out)")
            state.pointer(k, self.where, row, "ptr", col + i)
        row.ptr_known[col:col + self.width] = 1


class PropositionCodec(FieldCodec):
    block = "prop"
    width = 1                                     # one proposition per record (its own block)
    UTTERANCE_FIELDS = frozenset({"REQUEST.prop"})  # what was said or asked: a full utterance; the others are bare

    def write(self, value, row, col, state):
        state.encode_proposition(value, row, self.where, utterance=self.where in self.UTTERANCE_FIELDS)


def make_codec(name: str, spec: dict, where: str) -> FieldCodec:
    scale, list_of = spec.get("scale"), spec.get("list_of", "")
    if spec.get("components"):
        return VectorCodec(name, spec, where)
    if scale in ("bipolar10", "unipolar10", "ratio", "bool", "qty", "time", "time_until"):
        return ScalarCodec(name, spec, where)
    if scale in ("enum", "word"):
        return SymbolCodec(name, spec, where)
    if scale == "mref":
        return PointerCodec(name, spec, where)
    if scale == "proposition":
        return PropositionCodec(name, spec, where)
    if scale == "list" and list_of in ("word", "enum"):
        return BagCodec(name, spec, where)
    if scale == "list" and list_of == "mref":
        return PointerListCodec(name, spec, where)
    raise TokenError(f"{where}: no encoding for scale={scale} list_of={list_of}")


@dataclass(frozen=True)
class Column:
    codec: FieldCodec
    col: int                                      # first column in its block
