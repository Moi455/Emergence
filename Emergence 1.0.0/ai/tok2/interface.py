"""interface.py - what tok-2 reads: catalogue/generated/model_interface.json, and the input vocabulary built from it.

The interface is generated from the catalogue (single source of truth); nothing here is written by hand except the
reserved symbols. The C++ tokenizer will be generated from the same file and must give the same ids (fingerprint).

The interface fingerprint covers ONLY what tok-2 reads (canonical JSON of the `input` subtree and of the parts of
`output` tok-2 uses: the speech words, kinds and limits, and the gesture ids): a change of the output heads does
not invalidate the data already tokenized.
"""
from __future__ import annotations

import json
from pathlib import Path

from .errors import TokenError

ROOT = Path(__file__).resolve().parents[2]
INTERFACE_PATH = ROOT / "catalogue" / "generated" / "model_interface.json"
SUPPORTED_SCHEMAS = ("model-interface-2",)


def fnv1a64(data: bytes) -> int:
    h = 0xCBF29CE484222325
    for b in data:
        h = ((h ^ b) * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return h


def canonical_json(obj) -> bytes:
    """Sorted keys, no spaces, UTF-8 (not ASCII-escaped): the byte string every fingerprint is taken on."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


class ModelInterface:
    """The input side of model_interface.json: token types (ordered by name), their fields and keys."""

    def __init__(self, path: Path = INTERFACE_PATH):
        self._load(json.loads(Path(path).read_bytes()))

    @classmethod
    def from_dict(cls, data: dict) -> "ModelInterface":
        self = cls.__new__(cls)
        self._load(data)
        return self

    def _load(self, data: dict) -> None:
        if data.get("schema_version") not in SUPPORTED_SCHEMAS:
            raise TokenError(f"model_interface.json has schema_version {data.get('schema_version')!r}; tok-2 reads "
                             f"{list(SUPPORTED_SCHEMAS)}")
        inp, out = data["input"], data["output"]
        speech = out["speech"]
        self.schema_version: str = data["schema_version"]
        self.max_tokens: int = inp["max_tokens"]
        self.object_vector: list[str] = list(inp["object_vector"])
        self.token_types: dict[str, dict] = dict(sorted(inp["token_types"].items()))
        self.grammar_words: list[str] = list(speech["grammar_words"])
        self.kinds: list[str] = list(speech["kinds"])
        self.max_symbols: int = speech["max_symbols"]
        self.max_depth: int = speech["max_depth"]
        self.gestures: list[str] = sorted(out["gestures"])
        read = {"schema_version": self.schema_version, "input": inp,
                "speech": {"grammar_words": speech["grammar_words"], "kinds": speech["kinds"],
                           "max_symbols": self.max_symbols, "max_depth": self.max_depth},
                "gestures": self.gestures}
        self.fingerprint = fnv1a64(canonical_json(read))

    def enum_values(self) -> set[str]:
        return {x for t in self.token_types.values() for f in t["fields"].values() if f["scale"] == "enum"
                for x in f["values"]}


class InputVocabulary:
    """One id space for every symbol a token can hold: grammar words, kinds, gestures and enum values (the same
    string is the same id in every field: the field embedding tells the slot apart), the pointer kinds of the
    inner language, and NAME_SLOTS per-decision name aliases (names are an open set: the model only needs to
    know that two mentions are the same name, so the k-th distinct name of a decision is <name k>; the names
    after the 64th all share <name_other>).

    The ids come from the append-only registry (registry.py): `required()` is the default order for a new
    registry, `registered` the order an existing one gives. A symbol the interface no longer has keeps its id
    (reserved) but is no longer accepted."""

    PAD, UNK, NUM, NAME_OTHER = "<pad>", "<unk>", "<num>", "<name_other>"   # <num>: a bare number in a proposition
    POINTER_KINDS = ("@E", "@T", "@G", "@L", "@V", "@PLACE", "b:", "m:", "g:", "h:", "q:", "c:")   # h: heard, q: request, c: commitment (19a)
    NAME_SLOTS = 64

    @classmethod
    def reserved(cls) -> list[str]:
        return [cls.PAD, cls.UNK, cls.NUM, *cls.POINTER_KINDS, *(f"<name{k}>" for k in range(cls.NAME_SLOTS)),
                cls.NAME_OTHER]

    @classmethod
    def words_of(cls, interface: ModelInterface) -> set[str]:
        words = set(interface.grammar_words) | set(interface.kinds) | set(interface.gestures) | interface.enum_values()
        clash = words & set(cls.reserved())
        if clash:
            raise TokenError(f"catalogue words clash with reserved symbols: {sorted(clash)}")
        bad = sorted(w for w in words if not w or w[0] == "<" or w[-1] == ">" or any(c.isspace() or c in "()" for c in w))
        if bad:
            raise TokenError(f"catalogue words that cannot be symbols: {bad[:5]}")
        return words

    @classmethod
    def required(cls, interface: ModelInterface) -> list[str]:
        """Default order (a registry created from scratch): reserved symbols, then the catalogue words sorted."""
        return cls.reserved() + sorted(cls.words_of(interface))

    def __init__(self, interface: ModelInterface, registered: list[str] | None = None):
        self.words: frozenset[str] = frozenset(self.words_of(interface))
        self._reserved = frozenset(self.reserved())
        self.symbols: list[str] = list(registered) if registered is not None else self.required(interface)
        missing = (set(self.reserved()) | self.words) - set(self.symbols)
        if missing or len(set(self.symbols)) != len(self.symbols):
            raise TokenError(f"the registered symbols do not cover the interface: {sorted(missing)[:5]}")
        self.ids: dict[str, int] = {s: i for i, s in enumerate(self.symbols)}
        self.fingerprint = fnv1a64("\n".join(self.symbols).encode("utf-8"))
        if self.ids.get(self.PAD) != 0:
            raise TokenError("<pad> must be symbol 0 (a word field set to '' is known: none)")
        if len(self.symbols) > 32767:
            raise TokenError("the input vocabulary must fit int16")

    def __len__(self) -> int:
        return len(self.symbols)

    def __contains__(self, sym) -> bool:
        """A symbol the model can read: reserved, or a catalogue word of the current interface."""
        return isinstance(sym, str) and (sym in self.words or sym in self._reserved)

    def is_word(self, sym) -> bool:
        """A catalogue word (a word field, a proposition head or leaf): never a reserved `<...>` symbol."""
        return isinstance(sym, str) and sym in self.words

    def id(self, sym: str) -> int:
        if sym not in self:
            raise TokenError(f"unknown symbol '{sym}' (not in the catalogue vocabulary)")
        return self.ids[sym]

    def name_id(self, k: int) -> int:
        return self.ids[f"<name{k}>"] if 0 <= k < self.NAME_SLOTS else self.ids[self.NAME_OTHER]

    def pointer_kind(self, key: str) -> str:
        """'@E3' -> '@E', 'b:7' -> 'b:', '@PLACE' -> '@PLACE'."""
        if key == "@PLACE":
            return key
        for k in self.POINTER_KINDS:
            if key.startswith(k) and key[len(k):].isascii() and key[len(k):].isdigit():
                return k
        raise TokenError(f"'{key}' is not a pointer of the inner language")
