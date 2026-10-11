"""layout.py - how each field of each token type lands in the fixed-shape arrays of a decision.

A token is one RECORD of the NPC's mind (a person file, a belief, a thing he sees...). Its fields go into four
blocks, at columns fixed per token type (the model embeds (type, column) to know which field it reads):
  num   float  scalars (charter scales /10, ratio, bool, log quantities, log ages) and named or object vectors,
               with a `known` flag per column (unknown is not zero)
  cat   int    enum and word ids (one column), word lists (BAG_CAP columns): ids of the InputVocabulary
  ptr   int    pointers to other tokens of the same decision: 0 none, 1..128 slot, 129 exists out of context
  prop  5 x P  the one proposition of the record (belief, goal, memory, request, commitment, heard), prefix order:
               symbol id, arity (0 leaf, 1 + args for a list), depth, pointer slot, number (see proposition.py)
The widths of a block are the max over the token types; unused columns stay empty (0, unknown).
"""
from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass

from .interface import InputVocabulary, ModelInterface, fnv1a64

BAG_CAP = 6          # words per word list (the engine keeps the most salient: the 2 worst wounds = 6 words)
PTR_LIST_CAP = 4     # pointers per pointer list (to whom a belief was told, witnesses of a commitment)
NONE_SLOT, OUT_OF_CONTEXT = 0, 129


class TokenError(ValueError):
    """A record the tokenizer refuses: it never silently drops or invents information."""


def signed_log(x: float) -> float:
    return math.copysign(math.log1p(abs(x)), x)


class ScaleNorm:
    """Charter scales and units -> model inputs. Out of range is an engine bug: refused, never clipped."""

    @staticmethod
    def apply(scale: str, x, where: str) -> float:
        if isinstance(x, bool):
            if scale != "bool":
                raise TokenError(f"{where}: a bool for a {scale} field")
            return 1.0 if x else 0.0
        if scale == "bool":
            raise TokenError(f"{where}: bool expected, got {x!r}")
        if not isinstance(x, (int, float)) or not math.isfinite(x):
            raise TokenError(f"{where}: finite number expected, got {x!r}")
        if scale == "bipolar10":
            ScaleNorm._range(x, -10, 10, where)
            return x / 10
        if scale == "unipolar10":
            ScaleNorm._range(x, 0, 10, where)
            return x / 10
        if scale in ("ratio",):
            ScaleNorm._range(x, 0, 1, where)
            return float(x)
        if scale == "unit":                       # a named component, given normalised by the engine
            ScaleNorm._range(x, -1, 1, where)
            return float(x)
        if scale == "qty":
            return signed_log(x)
        if scale == "time":                       # age in game hours
            ScaleNorm._range(x, 0, math.inf, where)
            return math.log1p(x)
        raise TokenError(f"{where}: no numeric encoding for scale {scale}")

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

    @abstractmethod
    def write(self, value, row, col: int, state) -> None:
        """Write `value` (never None: absent fields are left empty) at columns col..col+width of `row`."""


class ScalarCodec(FieldCodec):
    block = "num"
    width = 1

    def write(self, value, row, col, state):
        row.num[col] = ScaleNorm.apply(self.spec["scale"], value, self.where)
        row.known[col] = 1


class VectorCodec(FieldCodec):
    """A qty or a list of qty with named components (sin/cos, reputation axes) or the object vector. Value: a dict
    component -> value (missing components stay unknown), a list in component order, or for a list of vectors
    (what is held in both hands) a list of dicts, pooled by max per component."""
    block = "num"

    def __init__(self, name, spec, where):
        super().__init__(name, spec, where)
        self.components: list[str] = spec["components"]
        self.scales: list[str] = spec["component_scales"]
        self.index = {c: i for i, c in enumerate(self.components)}

    @property
    def width(self):
        return len(self.components)

    def _as_dict(self, value) -> dict:
        if isinstance(value, dict):
            unknown = set(value) - set(self.index)
            if unknown:
                raise TokenError(f"{self.where}: unknown components {sorted(unknown)}")
            return value
        if isinstance(value, (list, tuple)) and value and all(isinstance(v, dict) for v in value):
            pooled: dict = {}
            for v in value:
                for c, x in self._as_dict(v).items():
                    pooled[c] = max(pooled.get(c, x), x)
            return pooled
        if isinstance(value, (list, tuple)) and len(value) == self.width:
            return dict(zip(self.components, value))
        raise TokenError(f"{self.where}: a dict of components, a list of {self.width} values or a list of dicts")

    def write(self, value, row, col, state):
        for c, x in self._as_dict(value).items():
            i = self.index[c]
            row.num[col + i] = ScaleNorm.apply(self.scales[i], x, f"{self.where}.{c}")
            row.known[col + i] = 1


class SymbolCodec(FieldCodec):
    """enum (one of its values) or word (a catalogue word, or a name n:<id> aliased per decision)."""
    block = "cat"
    width = 1

    def write(self, value, row, col, state):
        row.cat[col] = state.symbol_id(value, self.spec, self.where)


class BagCodec(FieldCodec):
    """A list of words or enum values: an unordered bag of at most BAG_CAP symbols."""
    block = "cat"
    width = BAG_CAP

    def write(self, value, row, col, state):
        if not isinstance(value, (list, tuple)):
            raise TokenError(f"{self.where}: a list expected")
        if len(value) > BAG_CAP:
            raise TokenError(f"{self.where}: {len(value)} words > {BAG_CAP} (the engine keeps the most salient)")
        for i, w in enumerate(value):
            row.cat[col + i] = state.symbol_id(w, self.spec, self.where)


class PointerCodec(FieldCodec):
    block = "ptr"
    width = 1

    def write(self, value, row, col, state):
        row.ptr[col] = state.slot(value, self.where)


class PointerListCodec(FieldCodec):
    block = "ptr"
    width = PTR_LIST_CAP

    def write(self, value, row, col, state):
        if not isinstance(value, (list, tuple)) or len(value) > PTR_LIST_CAP:
            raise TokenError(f"{self.where}: a list of at most {PTR_LIST_CAP} pointers expected")
        for i, k in enumerate(value):
            row.ptr[col + i] = state.slot(k, self.where)


class PropositionCodec(FieldCodec):
    block = "prop"
    width = 1                                     # one proposition per record (its own block)

    def write(self, value, row, col, state):
        state.encode_proposition(value, row, self.where)


def make_codec(name: str, spec: dict, where: str) -> FieldCodec:
    scale, list_of = spec["scale"], spec.get("list_of", "")
    if spec.get("components"):
        return VectorCodec(name, spec, where)
    if scale in ("bipolar10", "unipolar10", "ratio", "bool", "qty", "time"):
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


class TypeLayout:
    """The columns of one token type."""

    def __init__(self, type_id: int, name: str, spec: dict):
        self.type_id, self.name = type_id, name
        self.count: int = spec["count"]
        self.key: str = spec["key"]
        self.columns: dict[str, Column] = {}
        used = {"num": 0, "cat": 0, "ptr": 0, "prop": 0}
        for fname in sorted(spec["fields"]):
            codec = make_codec(fname, spec["fields"][fname], f"{name}.{fname}")
            self.columns[fname] = Column(codec, used[codec.block])
            used[codec.block] += codec.width
        if used["prop"] > 1:
            raise TokenError(f"{name}: more than one proposition field")
        self.widths = used

    def key_ok(self, key: str) -> bool:
        if self.key in ("me", "me.mind", "me.state", "@PLACE"):
            return key == self.key
        return key.startswith(self.key) and key[len(self.key):].isdigit()


class Layout:
    """All token types (type id 0 = empty slot), the block widths, and a fingerprint for the C++ port."""

    def __init__(self, interface: ModelInterface, vocab: InputVocabulary):
        self.interface, self.vocab = interface, vocab
        self.max_tokens = interface.max_tokens
        self.prop_len = interface.max_symbols
        self.types: dict[str, TypeLayout] = {
            name: TypeLayout(i + 1, name, spec) for i, (name, spec) in enumerate(interface.token_types.items())}
        self.width = {b: max(t.widths[b] for t in self.types.values()) for b in ("num", "cat", "ptr")}
        budget = sum(t.count for t in self.types.values())
        if budget > self.max_tokens:
            raise TokenError(f"token counts sum to {budget} > {self.max_tokens}")
        self.fingerprint = fnv1a64(self.describe().encode("utf-8"))

    def describe(self) -> str:
        """One line per column: the contract the C++ tokenizer and the model share."""
        lines = [f"tok-2 interface={self.interface.fingerprint:016x} vocab={self.vocab.fingerprint:016x} "
                 f"T={self.max_tokens} num={self.width['num']} cat={self.width['cat']} ptr={self.width['ptr']} "
                 f"prop={self.prop_len}"]
        for t in self.types.values():
            lines.append(f"{t.type_id} {t.name} count={t.count} key={t.key}")
            for fname, c in t.columns.items():
                lines.append(f"  {c.codec.block}[{c.col}:{c.col + c.codec.width}] {fname} {type(c.codec).__name__}")
        return "\n".join(lines)
