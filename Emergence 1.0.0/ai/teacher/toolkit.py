"""toolkit.py - the catalogue tools every part of the teacher format shares (loaded once, lazily).

The teacher never keeps its own copy of the catalogue: gestures, variables, words and bounds come from
catalogue/generated/model_interface.json (the contract) and from the catalogue itself (types, D10 flags).
"""
from __future__ import annotations

import sys
from functools import cached_property
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "catalogue", ROOT / "catalogue" / "tools", ROOT / "ai"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import language  # noqa: E402  (catalogue/tools)
from governor import Governor  # noqa: E402
from schema import Catalogue  # noqa: E402
from tok2 import ModelInterface  # noqa: E402

from .spec import OutputSpec  # noqa: E402


class Toolkit:
    """Catalogue, input interface, vocabulary, parser, governor: one instance serves a whole run."""

    def __init__(self, cat: Catalogue | None = None):
        self._cat = cat

    @cached_property
    def cat(self) -> Catalogue:
        return self._cat or Catalogue.load()

    @cached_property
    def interface(self) -> ModelInterface:
        return ModelInterface()

    @cached_property
    def spec(self) -> OutputSpec:
        return OutputSpec.load({a.id: a.family for a in self.cat["action"].values()})

    @cached_property
    def vocab(self) -> language.Vocabulary:
        return language.Vocabulary(self.cat)

    @cached_property
    def governor(self) -> Governor:
        return Governor(self.cat)

    @cached_property
    def parser(self) -> language.Parser:
        return language.Parser()

    @cached_property
    def printer(self) -> language.EnglishPrinter:
        return language.EnglishPrinter()

    def expression(self, text: str) -> language.Expression:
        return language.Expression(text, self.vocab)

    def estimate_tokens(self, text: str) -> int:
        """A rough estimate (characters / 4), NOT a measured count: the real count comes from countTokens."""
        return (len(text) + 3) // 4
