"""layout.py - how each field of each token type lands in the fixed-shape arrays of a decision.

The columns, the type ids and the symbol ids come from the append-only registry (registry.py): the model embeds
(type, column), so they never move. See codecs.py for how a value is written and for the unknown-versus-empty
convention, tokenizer.py for the arrays and the pointer slots.

Pointer slots (ptr and prop_slot): 0 none, 1..128 the token of this decision, 129 + k (k = 0..31) a GHOST (a
record of the NPC's mind that this decision does not carry, numbered by first appearance in the encoding order),
161 a ghost beyond the 32nd.

`Layout.document()` is the contract with the C++ port (golden/layout.json is this document plus the grammar and the
reading rules): the layout fingerprint is the FNV-1a 64 of its canonical JSON (sorted keys, no spaces, UTF-8).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from .codecs import (BAG_CAP, EPSILON, GHOST_BASE, GHOST_OVERFLOW, GHOST_SLOTS, NONE_SLOT, PTR_LIST_CAP, QTY_MAX,  # noqa: F401
                     SIGNED_UNITS, SUM_COMPONENTS, Column, ScaleNorm, VectorCodec, make_codec)
from .errors import TokenError
from .interface import InputVocabulary, ModelInterface, canonical_json, fnv1a64
from .keys import COUNT_MAX, FIXED_KEYS, is_key

if TYPE_CHECKING:
    from .registry import Registry

MANDATORY_TYPES = ("SELF", "PLACE")          # a decision always has a body and a place
LAYOUT_SCHEMA = "tok2-layout-2"
# the document's keys that are NOT part of the layout fingerprint (golden/layout.json adds them)
EXTRA_KEYS = ("fingerprints", "grammar", "reading_rules")


class TypeLayout:
    """The columns of one token type, in WRITE ORDER: the order of the fields in the registry (append order)."""

    def __init__(self, type_id: int, name: str, spec: dict, entry):
        self.type_id, self.name = type_id, name
        self.count: int = spec["count"]
        self.key: str = spec["key"]
        self.columns: dict[str, Column] = {}
        for fname, e in entry.fields.items():
            if e.retired or fname not in spec["fields"]:
                continue
            codec = make_codec(fname, spec["fields"][fname], f"{name}.{fname}")
            if isinstance(codec, VectorCodec):
                where = {c.name: c.col for c in e.components}
                codec.bind([where[c] for c in codec.components])
            self.columns[fname] = Column(codec, e.col)
        self.widths = {b: entry.end(b) for b in ("num", "cat", "ptr", "prop")}

    def key_ok(self, key) -> bool:
        if not is_key(key):
            return False
        if self.key in FIXED_KEYS:
            return key == self.key
        return key.startswith(self.key)


class Layout:
    """All token types (type id 0 = empty slot, row order = registry order), the block widths, a fingerprint."""

    def __init__(self, interface: ModelInterface, vocab: InputVocabulary, registry: "Registry"):
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
        self._document = self.document()
        self.fingerprint = fnv1a64(canonical_json(self._document))

    # ---- the contract ----------------------------------------------------------------------------
    def kind_of(self, key: str) -> list[str]:
        """The record types a key can designate (@T: THING or INV)."""
        return [n for n, t in self.types.items() if t.key_ok(key)]

    def document(self) -> dict:
        """Everything a port needs to build the arrays, as plain JSON (ints and strings only)."""
        from .tokenizer import Encoded
        enc = Encoded(self)
        types = {}
        for name, t in self.types.items():
            cols = []
            for fname, c in t.columns.items():
                spec = c.codec.spec
                col = {"name": fname, "block": c.codec.block, "col": c.col, "width": c.codec.width, "codec": c.codec.kind,
                       "scale": spec.get("scale", ""), "normalisation": c.codec.normalisation()}
                if spec.get("unit"):
                    col["unit"] = spec["unit"]
                if spec.get("scale") == "enum" or spec.get("list_of") == "enum":
                    col["values"] = list(spec["values"])
                if spec.get("ref_types"):
                    col["ref_types"] = list(spec["ref_types"])
                if isinstance(c.codec, VectorCodec):
                    col["components"] = [{"name": n, "col": j, "scale": s, "unit": u,
                                          "normalisation": ScaleNorm.formula(s, u)}
                                         for n, j, s, u in zip(c.codec.components, c.codec.cols, c.codec.scales, c.codec.units)]
                    col["col"] = c.codec.cols[0]
                cols.append(col)
            types[name] = {"id": t.type_id, "count": t.count, "key": t.key, "columns": cols}
        iface, vocab = self.interface, self.vocab
        speech = {w: vocab.ids[w] for w in sorted(set(iface.grammar_words) | set(iface.kinds), key=lambda w: vocab.ids[w])}
        return {
            "schema": LAYOUT_SCHEMA,
            "constants": {
                "max_tokens": self.max_tokens, "prop_len": self.prop_len, "none_slot": NONE_SLOT,
                "ghost_base": GHOST_BASE, "ghost_slots": GHOST_SLOTS, "ghost_overflow": GHOST_OVERFLOW,
                "bag_cap": BAG_CAP, "ptr_list_cap": PTR_LIST_CAP, "name_slots": InputVocabulary.NAME_SLOTS,
                "pad_id": vocab.ids[InputVocabulary.PAD], "num_id": vocab.ids[InputVocabulary.NUM],
                "name_other_id": vocab.ids[InputVocabulary.NAME_OTHER],
                "epsilon": f"{EPSILON:g}", "qty_max": QTY_MAX, "count_max": COUNT_MAX,
                "signed_units": sorted(SIGNED_UNITS), "pooled_by_sum": sorted(SUM_COMPONENTS),
                "count_encoding": "log1p(n + 1) for a count n in a proposition; 0 = no count",
                "proposition_chars": "printable ASCII and space/tab/newline/CR only"},
            "digest": "zlib.crc32 chained over pack('<I', n) then each array of `arrays` in order, "
                      "C order, little endian, with its dtype; 8 lowercase hex digits",
            "arrays": [{"name": a, "dtype": str(getattr(enc, a).dtype), "shape": list(getattr(enc, a).shape)}
                       for a in enc.ARRAYS],
            "widths": dict(self.width),
            "types": types,
            "vocabulary": list(vocab.symbols),
            "retired_symbols": sorted(set(vocab.symbols) - vocab.words - set(InputVocabulary.reserved())),
            "speech_to_input": speech,
        }
