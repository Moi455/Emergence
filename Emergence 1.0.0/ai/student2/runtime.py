"""runtime.py - everything the student needs from the catalogue, built once per process.

`Runtime.build()` loads the catalogue toolkit, the tok-2 tokenizer (interface, registry, layout), the output space
(every head size) and the label codec. `fingerprints()` is what a checkpoint carries and what a dataset header is
compared with: if any of them differs, the weights or the data were made for another catalogue state.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

from teacher.toolkit import Toolkit
from tok2 import Tokenizer
from tok2.interface import canonical_json, fnv1a64

from .labels import LabelCodec
from .spec import OutputSpace

SCHEMA = "student2-2"


@dataclass(frozen=True)
class Fingerprints:
    """Hex strings. `layout` and `interface` are tok-2's own (input side), `registry` pins every type, column and
    symbol id, `vocabulary` the input symbols, `output` every head of the output interface."""
    schema: str
    interface: str
    layout: str
    registry: str
    vocabulary: str
    output: str

    def diff(self, other: "Fingerprints") -> dict:
        a, b = asdict(self), asdict(other)
        return {k: (a[k], b[k]) for k in a if a[k] != b[k]}


class Runtime:
    def __init__(self, tk: Toolkit, tokenizer: Tokenizer):
        self.tk, self.tokenizer = tk, tokenizer
        self.space = OutputSpace(tk, tokenizer)
        self.codec = LabelCodec(self.space)

    @classmethod
    def build(cls) -> "Runtime":
        tk = Toolkit()
        return cls(tk, Tokenizer(tk.interface, grammar=tk.vocab))

    def fingerprints(self) -> Fingerprints:
        tok = self.tokenizer
        h = tok.header()
        return Fingerprints(SCHEMA, h["interface"], h["layout"], f"{fnv1a64(canonical_json(tok.registry.to_dict())):016x}",
                            f"{tok.vocab.fingerprint:016x}", f"{self.space.fingerprint:016x}")
