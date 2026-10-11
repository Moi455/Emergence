"""interface.py - what tok-2 reads: catalogue/generated/model_interface.json, and the input vocabulary built from it.

The interface is generated from the catalogue (single source of truth); nothing here is written by hand except the
reserved symbols. The C++ tokenizer will be generated from the same file and must give the same ids (fingerprint).
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INTERFACE_PATH = ROOT / "catalogue" / "generated" / "model_interface.json"


def fnv1a64(data: bytes) -> int:
    h = 0xCBF29CE484222325
    for b in data:
        h = ((h ^ b) * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return h


class ModelInterface:
    """The input side of model_interface.json: token types (ordered by name), their fields and keys."""

    def __init__(self, path: Path = INTERFACE_PATH):
        raw = Path(path).read_bytes()
        self.fingerprint = fnv1a64(raw)
        data = json.loads(raw)
        self.schema_version: str = data["schema_version"]
        inp, out = data["input"], data["output"]
        self.max_tokens: int = inp["max_tokens"]
        self.object_vector: list[str] = list(inp["object_vector"])
        self.token_types: dict[str, dict] = dict(sorted(inp["token_types"].items()))
        speech = out["speech"]
        self.grammar_words: list[str] = list(speech["grammar_words"])
        self.kinds: list[str] = list(speech["kinds"])
        self.max_symbols: int = speech["max_symbols"]
        self.max_depth: int = speech["max_depth"]
        self.gestures: list[str] = sorted(out["gestures"])

    def enum_values(self) -> set[str]:
        return {x for t in self.token_types.values() for f in t["fields"].values() if f["scale"] == "enum"
                for x in f["values"]}


class InputVocabulary:
    """One id space for every symbol a token can hold: grammar words, kinds, gestures and enum values (the same
    string is the same id in every field: the field embedding tells the slot apart), the pointer kinds of the
    inner language, and NAME_SLOTS per-decision name aliases (names are an open set: the model only needs to
    know that two mentions are the same name, so the k-th distinct name of a decision is <name k>)."""

    PAD, UNK, NUM = "<pad>", "<unk>", "<num>"            # <num>: a bare number in a proposition (value in prop_num)
    POINTER_KINDS = ("@E", "@T", "@G", "@L", "@V", "@PLACE", "b:", "m:", "g:")
    NAME_SLOTS = 64

    def __init__(self, interface: ModelInterface):
        words = set(interface.grammar_words) | set(interface.kinds) | set(interface.gestures) | interface.enum_values()
        reserved = [self.PAD, self.UNK, self.NUM, *self.POINTER_KINDS, *(f"<name{k}>" for k in range(self.NAME_SLOTS))]
        clash = words & set(reserved)
        if clash:
            raise ValueError(f"catalogue words clash with reserved symbols: {sorted(clash)}")
        self.symbols: list[str] = reserved + sorted(words)
        self.ids: dict[str, int] = {s: i for i, s in enumerate(self.symbols)}
        self.fingerprint = fnv1a64("\n".join(self.symbols).encode("utf-8"))
        if len(self.symbols) > 32767:
            raise ValueError("the input vocabulary must fit int16")

    def __len__(self) -> int:
        return len(self.symbols)

    def __contains__(self, sym: str) -> bool:
        return sym in self.ids

    def id(self, sym: str) -> int:
        try:
            return self.ids[sym]
        except KeyError:
            raise KeyError(f"tok-2: unknown symbol '{sym}' (not in the catalogue vocabulary)") from None

    def name_id(self, k: int) -> int:
        if not 0 <= k < self.NAME_SLOTS:
            raise ValueError(f"tok-2: more than {self.NAME_SLOTS} distinct names in one decision")
        return self.ids[f"<name{k}>"]

    def pointer_kind(self, key: str) -> str:
        """'@E3' -> '@E', 'b:7' -> 'b:', '@PLACE' -> '@PLACE'."""
        if key == "@PLACE":
            return key
        for k in self.POINTER_KINDS:
            if key.startswith(k) and key[len(k):].isdigit():
                return k
        raise ValueError(f"tok-2: '{key}' is not a pointer of the inner language")
