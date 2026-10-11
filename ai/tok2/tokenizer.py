"""tokenizer.py - tok-2: the mind records of one decision -> fixed-shape arrays for the shared Transformer.

Oracle of the C++ tokenizer (D31): the C++ port must give the same arrays (Encoded.digest) on the same records.
Input: a DecisionContext, the records the context selector kept (ordered by salience within a type). Nothing
here reads the truth: the records ARE the NPC's mind (perceptions, beliefs, memories, files), built by the engine.
Output: Encoded, one row per token (type order = the interface order, then the given order), max_tokens rows.
"""
from __future__ import annotations

import re
import struct
from dataclasses import dataclass, field

import numpy as np

from .interface import InputVocabulary, ModelInterface
from .layout import NONE_SLOT, OUT_OF_CONTEXT, Layout, TokenError
from .proposition import PropositionEncoder

NAME = re.compile(r"^n:\d+$")
KEY = re.compile(r"^(me|me\.mind|me\.state|@PLACE|@[ETGLV]\d+|[bmghqcpkt]:\d+)$")


@dataclass
class Record:
    type: str                                     # token type (ENTITY, BELIEF...)
    key: str                                      # how it is designated: @E3, b:7, me... (unique per decision)
    fields: dict = field(default_factory=dict)    # field name -> value; an absent field is unknown


@dataclass
class DecisionContext:
    records: list[Record]


class Encoded:
    """The arrays of one decision. Row r is token slot r + 1."""

    def __init__(self, layout: Layout):
        T, P = layout.max_tokens, layout.prop_len
        self.type_id = np.zeros(T, np.uint8)
        self.num = np.zeros((T, layout.width["num"]), np.float32)
        self.known = np.zeros((T, layout.width["num"]), np.uint8)
        self.cat = np.zeros((T, layout.width["cat"]), np.int16)
        self.ptr = np.zeros((T, layout.width["ptr"]), np.uint8)
        self.prop_sym = np.zeros((T, P), np.int16)
        self.prop_arity = np.zeros((T, P), np.uint8)
        self.prop_depth = np.zeros((T, P), np.uint8)
        self.prop_slot = np.zeros((T, P), np.uint8)
        self.prop_num = np.zeros((T, P), np.float32)
        self.keys: list[str] = []                 # slot - 1 -> key (to map pointer heads back to records)
        self.names: list[str] = []                # <name k> -> the name id it stands for in this decision

    ARRAYS = ("type_id", "num", "known", "cat", "ptr", "prop_sym", "prop_arity", "prop_depth", "prop_slot", "prop_num")

    @property
    def n(self) -> int:
        return len(self.keys)

    def row(self, r: int) -> "Row":
        return Row(self, r)

    def edges(self) -> list[tuple[int, int, str]]:
        """(from slot, to slot, kind) for every in-context pointer: the attention-bias graph the NPC believes."""
        out = []
        for r in range(self.n):
            for j in np.nonzero((self.ptr[r] > 0) & (self.ptr[r] <= len(self.keys)))[0]:
                out.append((r + 1, int(self.ptr[r, j]), f"ptr{j}"))
            for j in np.nonzero((self.prop_slot[r] > 0) & (self.prop_slot[r] <= len(self.keys)))[0]:
                out.append((r + 1, int(self.prop_slot[r, j]), "prop"))
        return out

    def digest(self) -> int:
        """FNV-1a 64 of the canonical little-endian bytes of every array, in ARRAYS order (C++ parity)."""
        from .interface import fnv1a64
        data = b"".join(np.ascontiguousarray(getattr(self, a)).astype(getattr(self, a).dtype.newbyteorder("<"))
                        .tobytes() for a in self.ARRAYS)
        return fnv1a64(struct.pack("<I", self.n) + data)


class Row:
    """A view on one token row (what the codecs write into)."""

    def __init__(self, enc: Encoded, r: int):
        self.num, self.known, self.cat, self.ptr = enc.num[r], enc.known[r], enc.cat[r], enc.ptr[r]
        self.prop_sym, self.prop_arity, self.prop_depth = enc.prop_sym[r], enc.prop_arity[r], enc.prop_depth[r]
        self.prop_slot, self.prop_num = enc.prop_slot[r], enc.prop_num[r]


class EncodeState:
    """Per-decision state: which key sits in which slot, and the per-decision name aliases."""

    def __init__(self, vocab: InputVocabulary, props: PropositionEncoder, keys: list[str], enc: Encoded):
        self.vocab, self.props, self.enc = vocab, props, enc
        self.slots = {k: i + 1 for i, k in enumerate(keys)}
        self.aliases: dict[str, int] = {}

    def slot(self, key, where: str) -> int:
        if key is None or key == "":
            return NONE_SLOT
        if not isinstance(key, str) or not KEY.match(key):
            raise TokenError(f"{where}: '{key}' is not a record key")
        return self.slots.get(key, OUT_OF_CONTEXT)

    def name_id(self, name: str) -> int:
        if name not in self.aliases:
            self.aliases[name] = len(self.aliases)
            self.enc.names.append(name)
        return self.vocab.name_id(self.aliases[name])

    def symbol_id(self, value, spec: dict, where: str) -> int:
        if not isinstance(value, str):
            raise TokenError(f"{where}: a symbol expected, got {value!r}")
        if spec["scale"] == "enum" or spec.get("list_of") == "enum":
            if spec["values"] and value not in spec["values"]:
                raise TokenError(f"{where}: '{value}' is not one of {spec['values']}")
        elif NAME.match(value):
            return self.name_id(value)
        if value not in self.vocab:
            raise TokenError(f"{where}: unknown word '{value}'")
        return self.vocab.id(value)

    def encode_proposition(self, value, row: Row, where: str) -> None:
        self.props.encode(value, row, self, where)


class Tokenizer:
    def __init__(self, interface: ModelInterface | None = None):
        self.interface = interface or ModelInterface()
        self.vocab = InputVocabulary(self.interface)
        self.layout = Layout(self.interface, self.vocab)
        self.props = PropositionEncoder(self.vocab, self.layout.prop_len)

    def order(self, ctx: DecisionContext) -> list[Record]:
        """Type order of the interface, then the given order; checks keys and per-type counts."""
        by_type: dict[str, list[Record]] = {}
        seen: set[str] = set()
        for rec in ctx.records:
            t = self.layout.types.get(rec.type)
            if t is None:
                raise TokenError(f"unknown token type '{rec.type}'")
            if not t.key_ok(rec.key):
                raise TokenError(f"{rec.type}: key '{rec.key}' does not match '{t.key}'")
            if rec.key in seen:
                raise TokenError(f"key '{rec.key}' used twice in one decision")
            seen.add(rec.key)
            by_type.setdefault(rec.type, []).append(rec)
        out = []
        for name, t in self.layout.types.items():
            recs = by_type.get(name, [])
            if len(recs) > t.count:
                raise TokenError(f"{name}: {len(recs)} records > {t.count} tokens (the selector keeps the most salient)")
            out += recs
        return out

    def encode(self, ctx: DecisionContext) -> Encoded:
        recs = self.order(ctx)
        enc = Encoded(self.layout)
        enc.keys = [r.key for r in recs]
        state = EncodeState(self.vocab, self.props, enc.keys, enc)
        for r, rec in enumerate(recs):
            t = self.layout.types[rec.type]
            enc.type_id[r] = t.type_id
            unknown = set(rec.fields) - set(t.columns)
            if unknown:
                raise TokenError(f"{rec.type} {rec.key}: unknown fields {sorted(unknown)}")
            row = enc.row(r)
            for fname, col in t.columns.items():
                value = rec.fields.get(fname)
                if value is not None:
                    col.codec.write(value, row, col.col, state)
        return enc
