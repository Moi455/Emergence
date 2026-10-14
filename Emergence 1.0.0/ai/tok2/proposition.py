"""proposition.py - a proposition of the inner language inside ONE token.

The record's proposition (a belief, a goal, a memory, what was heard or asked, a commitment) is written in prefix
order, one position per symbol (parentheses do not count, <= max_symbols, as in catalogue/tools/language.py):
  sym    symbol id (InputVocabulary): word, kind, gesture, pointer kind (@E, b:...), <nameK>, <name_other>, <num>
  arity  0 for a leaf, 1 + number of arguments for a list head ("(no)" is 1, "no" is 0): prefix order + arity
         rebuilds the tree exactly
  depth  depth in the tree (root 0)
  slot   for a pointer, the token it designates in this decision (0 none, 1..128, 129 + k ghost, 161 overflow)
  num    for a count (silver_coin:3, a bare 3), log1p(n + 1) = log(n + 2); 0 for a leaf without a count, so
         `silver_coin:0` (0 owned) is not `silver_coin` (some)
The proposition is validated by the grammar of the catalogue (catalogue/tools/language.py): a bare proposition
(Expression bare=True) for beliefs, goals, memories, commitments; a full utterance (mood) for REQUEST.prop.
The model encodes this short sequence into the token (a small encoder shared by all record types).
"""
from __future__ import annotations

import math
import re
import sys

import numpy as np

from .codecs import to_half
from .errors import TokenError, clip, short
from .interface import ROOT, InputVocabulary, ModelInterface
from .keys import is_count, is_key, is_name

sys.path.insert(0, str(ROOT / "catalogue")); sys.path.insert(0, str(ROOT / "catalogue" / "tools"))
from language import POINTER, Expression, LanguageError, Node, Parser, Vocabulary  # noqa: E402

MAX_TEXT = 1000                                   # characters of a proposition (20 symbols never need more)


_CLEAN = re.compile(r"[\t\n\r\x20-\x7e]*")
_CITATION = re.compile(r"[bmghqc]:(?:0|[1-9][0-9]{0,11})", re.ASCII)


def unparse(node) -> str:
    return "(" + " ".join(unparse(a) if isinstance(a, Node) else a for a in [node.head, *node.args]) + ")" \
        if isinstance(node, Node) else str(node)


def canonical_proposition(value):
    """The canonical text of a proposition: re-serialised from its tree, one space between symbols, no spaces
    around parentheses. A text that does not parse is returned unchanged (the encoder refuses it)."""
    try:
        if isinstance(value, Node):
            return unparse(value)
        if not isinstance(value, str) or _CLEAN.fullmatch(value) is None:
            return value
        s = value.strip()
        if _CITATION.fullmatch(s):
            return s
        return unparse(Parser().parse(s))
    except (LanguageError, RecursionError):
        return value


def count_value(n: int) -> float:
    return math.log1p(n + 1)


class Grammar:
    """The catalogue vocabulary used to validate propositions, built on first use and checked against the
    interface (a stale model_interface.json is refused)."""

    def __init__(self, interface: ModelInterface, vocab: Vocabulary | None = None):
        self.interface, self._vocab, self._checked = interface, vocab, False

    @property
    def vocab(self) -> Vocabulary:
        if self._vocab is None:
            from schema import Catalogue
            self._vocab = Vocabulary(Catalogue.load())
        v = self._vocab
        if not self._checked:
            if set(v.words) != set(self.interface.grammar_words) or set(v.kinds) != set(self.interface.kinds):
                raise TokenError("model_interface.json is out of date with the catalogue: run "
                                 "`python3 catalogue/tools/model_interface.py`")
            self._checked = True
        return v


class PropositionEncoder:
    def __init__(self, vocab: InputVocabulary, max_symbols: int, grammar: Grammar):
        self.vocab, self.max_symbols, self.grammar = vocab, max_symbols, grammar

    def encode(self, value, row, state, where: str, utterance: bool = False) -> None:
        root = self._validated(value, where, utterance, state.pointer_kinds)
        seq: list[tuple] = []
        self._walk(root, 0, seq, state, where)
        if len(seq) > self.max_symbols:
            raise TokenError(f"{where}: {len(seq)} symbols > {self.max_symbols}")
        for i, (sym, arity, depth, key, num) in enumerate(seq):
            row.prop_sym[i], row.prop_arity[i], row.prop_depth[i] = sym, arity, depth
            row.prop_num[i] = to_half(num) if num else 0
            if key is not None:
                state.pointer(key, where, row, "prop", i)

    def _validated(self, value, where: str, utterance: bool, pointer_kinds: dict | None = None) -> Node:
        """Parse and type-check with the grammar of the catalogue; the tree comes from the validator's own parse."""
        try:
            text = unparse(value) if isinstance(value, Node) else value
        except RecursionError:
            raise TokenError(f"{where}: nested too deeply") from None
        if not isinstance(text, str):
            raise TokenError(f"{where}: a proposition (text) expected, got {type(value).__name__}")
        if len(text) > MAX_TEXT:
            raise TokenError(f"{where}: {len(text)} characters > {MAX_TEXT}")
        if _CLEAN.fullmatch(text) is None:
            raise TokenError(f"{where}: only printable ASCII, space, tab and newline are allowed in a proposition "
                             "(no non-ASCII space, no control character)")
        try:
            e = Expression(text, self.grammar.vocab, bare=not utterance, pointer_kinds=pointer_kinds)
        except RecursionError:
            raise TokenError(f"{where}: nested too deeply") from None
        if not e.ok:
            raise TokenError(f"{where}: {clip('; '.join(e.problems[:3]))}")
        return e.root

    def _walk(self, node, depth, seq, state, where):
        if isinstance(node, Node):
            seq.append((self._word(node.head, where), len(node.args) + 1, depth, None, 0.0))
            for a in node.args:
                self._walk(a, depth + 1, seq, state, where)
            return
        seq.append(self._leaf(node, depth, state, where))

    def _leaf(self, sym: str, depth: int, state, where):
        if POINTER.match(sym):
            if sym.startswith("n:"):
                if not is_name(sym):
                    raise TokenError(f"{where}: {short(sym, 40)} is not a canonical name (no leading zero, at most 12 digits)")
                return state.name_id(sym), 0, depth, None, 0.0
            if not is_key(sym):
                raise TokenError(f"{where}: {short(sym, 40)} is not a canonical pointer (no leading zero, at most 12 digits)")
            return self.vocab.id(self.vocab.pointer_kind(sym)), 0, depth, sym, 0.0
        if sym.isascii() and sym.isdigit():
            return self.vocab.id(InputVocabulary.NUM), 0, depth, None, self._count(sym, where)
        base, sep, qty = sym.partition(":")
        if sep:
            return self._word(base, where), 0, depth, None, self._count(qty, where)
        return self._word(sym, where), 0, depth, None, 0.0

    @staticmethod
    def _count(text: str, where: str) -> float:
        if not is_count(text):
            raise TokenError(f"{where}: {short(text, 40)} is not a canonical count (ASCII digits, no leading zero, <= 1e7)")
        return count_value(int(text))

    def _word(self, sym: str, where: str) -> int:
        if not self.vocab.is_word(sym):
            raise TokenError(f"{where}: unknown symbol {short(sym, 40)}")
        return self.vocab.id(sym)


class PropositionDecoder:
    """Rebuilds the text of a token's proposition (debugging, teacher prompts, round-trip tests). A pointer in
    context gives its record key; a ghost gives its kind with '~k' (@E~0, the k-th ghost of the decision); beyond
    the 32nd ghost, '?' (@E?): the model never sees the number. Counts come back exact up to ~250 (binary16)."""

    def __init__(self, vocab: InputVocabulary):
        self.vocab = vocab

    def decode(self, enc, r: int) -> str:
        n = int(next((i for i in range(enc.prop_sym.shape[1]) if enc.prop_sym[r, i] == 0), enc.prop_sym.shape[1]))
        if n == 0:
            return ""
        text, end = self._node(enc, r, 0)
        if end != n:
            raise TokenError(f"row {r}: {n - end} symbols left after the tree")
        return text

    @staticmethod
    def _count(num: float) -> int:
        return round(math.expm1(num)) - 1

    def _node(self, enc, r, i):
        from .codecs import GHOST_BASE, GHOST_OVERFLOW
        sym = self.vocab.symbols[int(enc.prop_sym[r, i])]
        arity, slot, num = int(enc.prop_arity[r, i]), int(enc.prop_slot[r, i]), float(enc.prop_num[r, i])
        if sym in InputVocabulary.POINTER_KINDS:
            if 0 < slot <= len(enc.keys):
                word = enc.keys[slot - 1]
            elif GHOST_BASE <= slot < GHOST_OVERFLOW:
                word = f"{sym}~{slot - GHOST_BASE}"
            else:
                word = sym + "?"
        elif sym.startswith("<name") and sym != InputVocabulary.NAME_OTHER:
            word = enc.names[int(sym[5:-1])]
        elif sym == InputVocabulary.NAME_OTHER:
            word = "n:?"
        elif sym == InputVocabulary.NUM:
            word = str(self._count(num))
        else:
            word = sym + (f":{self._count(num)}" if num else "")
        if arity == 0:
            return word, i + 1
        parts, j = [word], i + 1
        for _ in range(arity - 1):
            part, j = self._node(enc, r, j)
            parts.append(part)
        return "(" + " ".join(parts) + ")", j
