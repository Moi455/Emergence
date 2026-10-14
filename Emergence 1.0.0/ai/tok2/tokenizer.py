"""tokenizer.py - tok-2: the mind records of one decision -> fixed-shape arrays for the shared Transformer.

Oracle of the C++ tokenizer (D31): the C++ port must give the same arrays (Encoded.digest) on the same records.
Input: a DecisionContext, the records the context selector kept, plus the keys of everything else the NPC's mind
holds (`known_keys`). Nothing here reads the truth: the records ARE the NPC's mind (perceptions, beliefs, memories,
files), built by the engine. Output: Encoded, one row per token (type order = the registry order, then the order
given: it is the salience the engine chose, and it matters), max_tokens rows.
"""
from __future__ import annotations

import json
import struct
import zlib
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Iterable

import numpy as np

from .codecs import GHOST_BASE, GHOST_OVERFLOW, GHOST_SLOTS
from .errors import TokenError, listing, short
from .interface import InputVocabulary, ModelInterface, canonical_json
from .keys import is_key, is_name
from .layout import Layout
from .proposition import Grammar, PropositionEncoder, canonical_proposition

if TYPE_CHECKING:
    from .registry import Registry

CONTEXT_SCHEMA = "tok2-context-1"


MAX_NESTING = 32


def _plain(v, where: str, depth: int = 0):
    """A value as plain JSON (numpy scalars and tuples unwrapped, parsed propositions printed)."""
    from language import Node
    if depth > MAX_NESTING:
        raise TokenError(f"{where}: nested more than {MAX_NESTING} levels")
    if isinstance(v, np.generic):
        v = v.item()
    if v is None or isinstance(v, (bool, int, str)):
        return v
    if isinstance(v, float):
        if v != v or v in (float("inf"), float("-inf")):
            raise TokenError(f"{where}: a non-finite number cannot be serialized")
        return v
    if isinstance(v, Node):
        text = canonical_proposition(v)
        if not isinstance(text, str):
            raise TokenError(f"{where}: a proposition nested too deeply to print")
        return text
    if isinstance(v, (list, tuple)):
        return [_plain(x, where, depth + 1) for x in v]
    if isinstance(v, dict):
        if not all(isinstance(k, str) for k in v):
            raise TokenError(f"{where}: dict keys must be strings")
        return {k: _plain(x, where, depth + 1) if k != "prop" else canonical_proposition(_plain(x, where, depth + 1))
                for k, x in v.items()}
    raise TokenError(f"{where}: {type(v).__name__} cannot be serialized")


@dataclass
class Record:
    """One record of the NPC's mind. A field that is absent or None is UNKNOWN; "" (a pointer) is known:
    nobody; [] (a list) is known: empty. Numbers are in the units of the charter: -10..10 for the psychological
    scales, game hours for ages and deadlines, metres, kilograms, litres."""
    type: str                                     # token type (ENTITY, BELIEF...)
    key: str                                      # how it is designated: @E3, b:7, me... (unique per decision)
    fields: dict = field(default_factory=dict)    # field name -> value

    def to_dict(self) -> dict:
        """Plain JSON. A proposition (the field `prop`) is written in its canonical form: re-serialised from its
        tree, one space between symbols, so two spellings of the same proposition give the same text."""
        where = f"{short(self.type, 30)} {short(self.key, 40)}"
        if not isinstance(self.fields, dict):
            raise TokenError(f"{where}: fields must be a dict")
        try:
            return {"type": _plain(self.type, where), "key": _plain(self.key, where), "fields": _plain(self.fields, where)}
        except RecursionError:
            raise TokenError(f"{where}: nested too deeply") from None

    @classmethod
    def from_dict(cls, d: dict) -> "Record":
        if not isinstance(d, dict) or set(d) != {"type", "key", "fields"} or not isinstance(d["fields"], dict):
            raise TokenError("a record is {type, key, fields}")
        if not isinstance(d["type"], str) or not isinstance(d["key"], str):
            raise TokenError("a record's type and key are strings")
        return cls(d["type"], d["key"], d["fields"])


@dataclass
class DecisionContext:
    """The records of one decision, and `known_keys`: the keys of EVERYTHING in the NPC's mind (default: the keys
    of the records). A pointer to a key that is known but not in the batch becomes a ghost (an identity the model
    can follow without its record); a pointer to an unknown key is refused."""
    records: list[Record]
    known_keys: Iterable[str] | None = None        # materialised into a frozenset at construction

    def __setattr__(self, name, value):
        """known_keys is a frozenset (or None) whenever it is assigned: at construction AND afterwards."""
        if name == "known_keys" and value is not None:
            if isinstance(value, (str, bytes)):
                raise TokenError("known_keys is a collection of keys, not a string")
            try:
                value = value if isinstance(value, frozenset) else frozenset(value)
            except TypeError:
                raise TokenError("known_keys must be a collection of strings") from None
        object.__setattr__(self, name, value)

    def mind_keys(self) -> frozenset[str]:
        if self.known_keys is None:
            if not isinstance(self.records, (list, tuple)) or not all(
                    isinstance(r, Record) and isinstance(r.key, str) for r in self.records):
                raise TokenError("a DecisionContext holds a list of Records with string keys")
            keys = frozenset(r.key for r in self.records)
        else:
            keys = self.known_keys
        bad = [k for k in keys if not is_key(k)]
        if bad:
            raise TokenError(f"known_keys: {listing(bad[:3])} are not record keys")
        return keys

    # ---- serialization: canonical JSON with a header that ties the file to the tokenizer that reads it ----
    def to_dict(self, tokenizer: "Tokenizer") -> dict:
        return {"header": tokenizer.header(),
                "records": [r.to_dict() for r in self.records],
                "known_keys": None if self.known_keys is None else sorted(self.mind_keys())}

    def dumps(self, tokenizer: "Tokenizer") -> str:
        """Canonical JSON (sorted keys, no spaces). Round trip: loads(dumps(c)) encodes to the same digest."""
        try:
            return canonical_json(self.to_dict(tokenizer)).decode("utf-8")
        except RecursionError:
            raise TokenError("cannot serialize: nested too deeply") from None
        except (TypeError, ValueError) as e:
            raise TokenError(f"cannot serialize: {e}") from None

    @classmethod
    def loads(cls, text: str, tokenizer: "Tokenizer") -> "DecisionContext":
        try:
            d = json.loads(text)
        except (ValueError, TypeError, RecursionError) as e:
            raise TokenError(f"not JSON: {type(e).__name__}") from None
        if not isinstance(d, dict) or set(d) != {"header", "records", "known_keys"}:
            raise TokenError("a serialized context is {header, records, known_keys}")
        if d["header"] != tokenizer.header():
            raise TokenError(f"this context was written for {d['header']}, the tokenizer is {tokenizer.header()}")
        if not isinstance(d["records"], list):
            raise TokenError("records must be a list")
        if d["known_keys"] is not None and not isinstance(d["known_keys"], list):
            raise TokenError("known_keys must be a list or null")
        return cls([Record.from_dict(r) for r in d["records"]], d["known_keys"])


class Encoded:
    """The arrays of one decision. Row r is token slot r + 1.

    Digest (C++ parity): zlib.crc32, chained over the little-endian bytes of `n` (uint32), then of every array of
    ARRAYS in this order, each in C order with its dtype: crc = crc32(pack('<I', n)); for a in ARRAYS:
    crc = crc32(bytes(a), crc). float16 is IEEE binary16."""

    ARRAYS = ("type_id", "num", "known", "cat", "cat_known", "ptr", "ptr_known", "prop_sym", "prop_arity",
              "prop_depth", "prop_slot", "prop_num")

    def __init__(self, layout: Layout):
        T, P = layout.max_tokens, layout.prop_len
        self.type_id = np.zeros(T, np.uint8)
        self.num = np.zeros((T, layout.width["num"]), np.float16)
        self.known = np.zeros((T, layout.width["num"]), np.uint8)
        self.cat = np.zeros((T, layout.width["cat"]), np.int16)
        self.cat_known = np.zeros((T, layout.width["cat"]), np.uint8)
        self.ptr = np.zeros((T, layout.width["ptr"]), np.uint8)
        self.ptr_known = np.zeros((T, layout.width["ptr"]), np.uint8)
        self.prop_sym = np.zeros((T, P), np.int16)
        self.prop_arity = np.zeros((T, P), np.uint8)
        self.prop_depth = np.zeros((T, P), np.uint8)
        self.prop_slot = np.zeros((T, P), np.uint8)
        self.prop_num = np.zeros((T, P), np.float16)
        self.keys: list[str] = []                 # slot - 1 -> key (to map pointer heads back to records)
        self.names: list[str] = []                # <name k> -> the name id it stands for in this decision
        self.ghosts: list[str] = []               # k -> the key of ghost 129 + k (never shown to the model)

    @property
    def n(self) -> int:
        return len(self.keys)

    @property
    def nbytes(self) -> int:
        return sum(getattr(self, a).nbytes for a in self.ARRAYS)

    def row(self, r: int) -> "Row":
        return Row(self, r, self.keys[r])

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
        crc = zlib.crc32(struct.pack("<I", self.n))
        for a in self.ARRAYS:
            arr = getattr(self, a)
            crc = zlib.crc32(np.ascontiguousarray(arr.astype(arr.dtype.newbyteorder("<"), copy=False)).tobytes(), crc)
        return crc


class Row:
    """A view on one token row (what the codecs write into)."""

    def __init__(self, enc: Encoded, r: int, key: str):
        self.r, self.key = r, key
        self.num, self.known, self.cat, self.cat_known = enc.num[r], enc.known[r], enc.cat[r], enc.cat_known[r]
        self.ptr, self.ptr_known = enc.ptr[r], enc.ptr_known[r]
        self.prop_sym, self.prop_arity, self.prop_depth = enc.prop_sym[r], enc.prop_arity[r], enc.prop_depth[r]
        self.prop_slot, self.prop_num = enc.prop_slot[r], enc.prop_num[r]


class EncodeState:
    """Per-decision state: which key sits in which slot, the ghosts, and the per-decision name aliases."""

    def __init__(self, vocab: InputVocabulary, props: PropositionEncoder, recs: list[Record], known: frozenset[str],
                 enc: Encoded, layout: Layout):
        self.vocab, self.props, self.enc, self.known, self.layout = vocab, props, enc, known, layout
        self.slots = {r.key: i + 1 for i, r in enumerate(recs)}
        self.rtypes = {r.key: r.type for r in recs}
        self.pointer_kinds = {r.key: r.fields["kind"] for r in recs        # what a thing or a place IS, to type its pointers
                              if r.type in ("THING", "INV", "LOCUS") and isinstance(r.fields.get("kind"), str) and r.fields["kind"]}
        self._kinds: dict[str, list[str]] = {}
        self.aliases: dict[str, int] = {}
        self.pending: list[tuple[int, int, int, str]] = []        # (row, block order, column, ghost key)

    def pointer(self, key, where: str, row: Row, block: str, col: int, ref_types: list[str] | None = None) -> None:
        """Write the slot of `key` at (row, block, col). "" is 'nobody' (ptr only: the slot stays 0). A pointer
        field accepts only the record types of `ref_types`; a proposition never cites its own record."""
        target = row.ptr if block == "ptr" else row.prop_slot
        if isinstance(key, str) and key == "" and block == "ptr":
            return
        if not is_key(key):
            raise TokenError(f"{where}: {short(key, 40)} is not a record key")
        if block == "prop" and key == row.key:
            raise TokenError(f"{where}: the proposition of {key} cites {key} itself")
        if ref_types is not None:
            rtype = self.rtypes.get(key)
            if rtype is not None:
                allowed = rtype in ref_types
            else:                                              # a ghost: only the kind of its key is known
                kinds = self._kinds.get(key)
                if kinds is None:
                    kinds = self._kinds[key] = self.layout.kind_of(key)
                allowed = any(k in ref_types for k in kinds)
                rtype = "/".join(kinds)
            if not allowed:
                raise TokenError(f"{where}: {short(key, 40)} is a {rtype} record; this field points to {'/'.join(ref_types)}")
        slot = self.slots.get(key)
        if slot is not None:
            target[col] = slot
        elif key in self.known:
            target[col] = GHOST_BASE                              # numbered in finalize(), in a canonical order
            self.pending.append((row.r, 0 if block == "ptr" else 1, col, key))
        else:
            raise TokenError(f"{where}: {short(key, 40)} is not in the NPC's mind (known_keys)")

    def finalize(self) -> None:
        """Number the ghosts by first appearance: rows, then columns (ptr before proposition positions). The
        first 32 distinct ones get 129..160, any other 161."""
        ghost: dict[str, int | None] = {}
        for r, blk, col, key in sorted(self.pending):
            if key not in ghost:
                ghost[key] = len(self.enc.ghosts) if len(self.enc.ghosts) < GHOST_SLOTS else None
                if ghost[key] is not None:
                    self.enc.ghosts.append(key)
            k = ghost[key]
            (self.enc.ptr if blk == 0 else self.enc.prop_slot)[r, col] = GHOST_OVERFLOW if k is None else GHOST_BASE + k

    def name_id(self, name: str) -> int:
        k = self.aliases.get(name)
        if k is None:
            k = len(self.aliases)
            if k < InputVocabulary.NAME_SLOTS:
                self.aliases[name] = k
                self.enc.names.append(name)
        return self.vocab.name_id(k)

    def symbol_id(self, value, spec: dict, where: str) -> int:
        if not isinstance(value, str):
            raise TokenError(f"{where}: a symbol expected, got {type(value).__name__} {short(value, 40)}")
        if spec["scale"] == "enum" or spec.get("list_of") == "enum":
            if spec["values"] and value not in spec["values"]:
                raise TokenError(f"{where}: {short(value, 40)} is not one of {listing(spec['values'])}")
        elif is_name(value):
            return self.name_id(value)
        elif spec.get("words") and value not in spec["words"]:      # a declared, closed set of percept words (19a)
            raise TokenError(f"{where}: {short(value, 40)} is not one of {listing(spec['words'])}")
        if not self.vocab.is_word(value):
            raise TokenError(f"{where}: unknown word {short(value, 40)}")
        return self.vocab.ids[value]

    def encode_proposition(self, value, row: Row, where: str, utterance: bool = False) -> None:
        self.props.encode(value, row, self, where, utterance)


class RecordRule(ABC):
    """A consistency rule between the fields of one record."""

    @abstractmethod
    def check(self, rec: Record) -> None: ...


class AbsentEntityRule(RecordRule):
    """A person who is not here has no distance, direction or appearance: a remembered face is another record."""

    def check(self, rec):
        present = rec.fields.get("present")
        if rec.type == "ENTITY" and isinstance(present, (bool, np.bool_)) and not present:
            bad = sorted(f for f, v in rec.fields.items() if v is not None and (f in ("dist", "dir") or f.startswith("look.")))
            if bad:
                raise TokenError(f"ENTITY {short(rec.key, 40)}: present=False but carries {listing(bad)} (an absent person is not seen)")


class Tokenizer:
    def __init__(self, interface: ModelInterface | None = None, registry: Registry | None = None, grammar=None):
        """`grammar`: a language.Vocabulary to validate propositions with (default: built from the catalogue)."""
        from .registry import Registry              # imported here so that `python3 -m tok2.registry` runs clean
        self.interface = interface or ModelInterface()
        self.registry = registry or Registry.load()
        self.registry.require(self.interface)       # an element the registry lacks is an error with the remedy
        self.vocab = InputVocabulary(self.interface, self.registry.symbols)
        self.layout = Layout(self.interface, self.vocab, self.registry)
        self.props = PropositionEncoder(self.vocab, self.layout.prop_len, Grammar(self.interface, grammar))
        self.rules: list[RecordRule] = [AbsentEntityRule()]

    def header(self) -> dict:
        return {"schema": CONTEXT_SCHEMA, "interface": f"{self.interface.fingerprint:016x}",
                "layout": f"{self.layout.fingerprint:016x}"}

    def order(self, ctx: DecisionContext, known: frozenset[str] | None = None) -> list[Record]:
        """Type order of the registry, then the given order; checks types, keys, counts, SELF and PLACE."""
        if not isinstance(ctx, DecisionContext) or not isinstance(ctx.records, (list, tuple)):
            raise TokenError("a DecisionContext with a list of records is expected")
        known = ctx.mind_keys() if known is None else known
        by_type: dict[str, list[Record]] = {}
        seen: set[str] = set()
        for rec in ctx.records:
            if not isinstance(rec, Record) or not isinstance(rec.type, str) or not isinstance(rec.fields, dict):
                raise TokenError(f"not a record: {short(rec, 60)}")
            t = self.layout.types.get(rec.type)
            if t is None:
                raise TokenError(f"unknown token type {short(rec.type, 40)}")
            if not t.key_ok(rec.key):
                raise TokenError(f"{rec.type}: key {short(rec.key, 40)} does not match '{t.key}'")
            if rec.key in seen:
                raise TokenError(f"key {short(rec.key, 40)} used twice in one decision")
            if rec.key not in known:
                raise TokenError(f"{rec.type}: key {short(rec.key, 40)} is not in known_keys")
            seen.add(rec.key)
            by_type.setdefault(rec.type, []).append(rec)
        out = []
        for name, t in self.layout.types.items():
            recs = by_type.get(name, [])
            if len(recs) > t.count:
                raise TokenError(f"{name}: {len(recs)} records > {t.count} tokens (the selector keeps the most salient)")
            out += recs
        for name in ("SELF", "PLACE"):
            if name not in by_type:
                raise TokenError(f"a decision needs a {name} record")
        return out

    def encode(self, ctx: DecisionContext) -> Encoded:
        known = ctx.mind_keys() if isinstance(ctx, DecisionContext) else None
        recs = self.order(ctx, known)
        enc = Encoded(self.layout)
        enc.keys = [r.key for r in recs]
        state = EncodeState(self.vocab, self.props, recs, known, enc, self.layout)
        for r, rec in enumerate(recs):
            t = self.layout.types[rec.type]
            enc.type_id[r] = t.type_id
            unknown = set(rec.fields) - set(t.columns)
            if unknown:
                raise TokenError(f"{rec.type} {short(rec.key, 40)}: unknown fields {listing(sorted(short(u, 30) for u in unknown))}")
            for rule in self.rules:
                rule.check(rec)
            row = enc.row(r)
            for fname, col in t.columns.items():
                value = rec.fields.get(fname)
                if value is not None:
                    col.codec.write(value, row, col.col, state)
        state.finalize()
        return enc
