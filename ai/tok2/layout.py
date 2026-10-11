"""layout.py - how each field of each token type lands in the fixed-shape arrays of a decision.

The columns, the type ids and the symbol ids come from the append-only registry (registry.py): the model embeds
(type, column), so they never move. See codecs.py for how a value is written and for the unknown-versus-empty
convention, tokenizer.py for the arrays and the pointer slots.

Pointer slots (ptr and prop_slot): 0 none, 1..128 the token of this decision, 129 + k (k = 0..31) a GHOST (a
record of the NPC's mind that this decision does not carry, numbered by first appearance in the encoding order),
161 a ghost beyond the 32nd.
"""
from __future__ import annotations

from .codecs import (BAG_CAP, GHOST_BASE, GHOST_OVERFLOW, GHOST_SLOTS, NONE_SLOT, OUT_OF_CONTEXT, PTR_LIST_CAP,  # noqa: F401
                     Column, make_codec)
from .errors import TokenError
from .interface import InputVocabulary, ModelInterface, fnv1a64
from .keys import FIXED_KEYS, KEY
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .registry import Registry

MANDATORY_TYPES = ("SELF", "PLACE")          # a decision always has a body and a place


class TypeLayout:
    """The columns of one token type."""

    def __init__(self, type_id: int, name: str, spec: dict, entry):
        self.type_id, self.name = type_id, name
        self.count: int = spec["count"]
        self.key: str = spec["key"]
        self.columns: dict[str, Column] = {}
        for fname in sorted(spec["fields"]):
            codec = make_codec(fname, spec["fields"][fname], f"{name}.{fname}")
            e = entry.fields[fname]
            self.columns[fname] = Column(codec, e.col)
        self.widths = {b: entry.end(b) for b in ("num", "cat", "ptr", "prop")}

    def key_ok(self, key) -> bool:
        if not isinstance(key, str) or KEY.match(key) is None:
            return False
        if self.key in FIXED_KEYS:
            return key == self.key
        return key.startswith(self.key) and key[len(self.key):].isdigit()


class Layout:
    """All token types (type id 0 = empty slot, row order = registry order), the block widths, a fingerprint."""

    def __init__(self, interface: ModelInterface, vocab: InputVocabulary, registry: Registry):
        registry.require(interface)
        self.interface, self.vocab, self.registry = interface, vocab, registry
        self.max_tokens = interface.max_tokens
        self.prop_len = interface.max_symbols
        self.types: dict[str, TypeLayout] = {
            name: TypeLayout(entry.id, name, interface.token_types[name], entry)
            for name, entry in sorted(registry.types.items(), key=lambda kv: kv[1].id) if name in interface.token_types}
        self.width = {b: w for b, w in registry.widths().items() if b != "prop"}
        budget = sum(t.count for t in self.types.values())
        if budget > self.max_tokens:
            raise TokenError(f"token counts sum to {budget} > {self.max_tokens}")
        missing = [t for t in MANDATORY_TYPES if t not in self.types]
        if missing:
            raise TokenError(f"the interface has no {missing} token type")
        self.fingerprint = fnv1a64(self.describe().encode("utf-8"))

    def describe(self) -> str:
        """One line per column: the contract the C++ tokenizer and the model share."""
        lines = [f"tok-2 interface={self.interface.fingerprint:016x} vocab={self.vocab.fingerprint:016x} "
                 f"T={self.max_tokens} num={self.width['num']} cat={self.width['cat']} ptr={self.width['ptr']} "
                 f"prop={self.prop_len}"]
        for t in self.types.values():
            lines.append(f"{t.type_id} {t.name} count={t.count} key={t.key}")
            for fname, c in sorted(t.columns.items(), key=lambda kv: (kv[1].codec.block, kv[1].col)):
                lines.append(f"  {c.codec.block}[{c.col}:{c.col + c.codec.width}] {fname} {c.codec.kind} "
                             f"{c.codec.normalisation()}")
        return "\n".join(lines)
