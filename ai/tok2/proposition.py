"""proposition.py - a proposition of the inner language inside ONE token.

The record's proposition (a belief, a goal, a memory, what was heard or asked, a commitment) is written in prefix
order, one position per symbol (parentheses do not count, <= max_symbols, as in catalogue/tools/language.py):
  sym    symbol id (InputVocabulary): word, kind, gesture, pointer kind (@E, b:...), <nameK>, <num>
  arity  0 for a leaf, 1 + number of arguments for a list head ("(no)" is 1, "no" is 0): prefix order + arity
         rebuilds the tree exactly
  depth  depth in the tree (root 0)
  slot   for a pointer, the token it designates in this decision (0 none, 1..128, 129 out of context)
  num    for a count (silver_coin:3, a bare 3), log(1 + n); 0 otherwise
The model encodes this short sequence into the token (a small encoder shared by all record types).
"""
from __future__ import annotations

import math
import sys

from .interface import ROOT, InputVocabulary
from .layout import TokenError

sys.path.insert(0, str(ROOT / "catalogue")); sys.path.insert(0, str(ROOT / "catalogue" / "tools"))
from language import POINTER, LanguageError, Node, Parser  # noqa: E402


class PropositionEncoder:
    def __init__(self, vocab: InputVocabulary, max_symbols: int):
        self.vocab, self.max_symbols = vocab, max_symbols
        self.parser = Parser()

    def encode(self, value, row, state, where: str) -> None:
        try:
            root = value if isinstance(value, Node) else self.parser.parse(str(value))
        except LanguageError as e:
            raise TokenError(f"{where}: {e}") from None
        seq: list[tuple[int, int, int, int, float]] = []
        self._walk(root, 0, seq, state, where)
        if len(seq) > self.max_symbols:
            raise TokenError(f"{where}: {len(seq)} symbols > {self.max_symbols}")
        for i, (sym, arity, depth, slot, num) in enumerate(seq):
            row.prop_sym[i], row.prop_arity[i], row.prop_depth[i] = sym, arity, depth
            row.prop_slot[i], row.prop_num[i] = slot, num

    def _walk(self, node, depth, seq, state, where):
        if isinstance(node, Node):
            seq.append((self._word(node.head, where), len(node.args) + 1, depth, 0, 0.0))
            for a in node.args:
                self._walk(a, depth + 1, seq, state, where)
            return
        seq.append(self._leaf(node, depth, state, where))

    def _leaf(self, sym: str, depth: int, state, where):
        if POINTER.match(sym):
            if sym.startswith("n:"):
                return state.name_id(sym), 0, depth, 0, 0.0
            return self.vocab.id(self.vocab.pointer_kind(sym)), 0, depth, state.slot(sym, where), 0.0
        if sym.isdigit():
            return self.vocab.id(InputVocabulary.NUM), 0, depth, 0, math.log1p(int(sym))
        base, sep, qty = sym.partition(":")
        if sep and qty.isdigit():
            return self._word(base, where), 0, depth, 0, math.log1p(int(qty))
        return self._word(sym, where), 0, depth, 0, 0.0

    def _word(self, sym: str, where: str) -> int:
        if sym not in self.vocab:
            raise TokenError(f"{where}: unknown symbol '{sym}'")
        return self.vocab.id(sym)


class PropositionDecoder:
    """Rebuilds the text of a token's proposition (debugging, teacher prompts, round-trip tests). A pointer in
    context gives its record key; out of context, its kind with '?' (@E?): the model never sees the number."""

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

    def _node(self, enc, r, i):
        sym = self.vocab.symbols[int(enc.prop_sym[r, i])]
        arity, slot, num = int(enc.prop_arity[r, i]), int(enc.prop_slot[r, i]), float(enc.prop_num[r, i])
        if sym in InputVocabulary.POINTER_KINDS:
            word = enc.keys[slot - 1] if 0 < slot <= len(enc.keys) else (sym if sym == "@PLACE" else sym + "?")
        elif sym.startswith("<name"):
            word = enc.names[int(sym[5:-1])]
        elif sym == InputVocabulary.NUM:
            word = str(round(math.expm1(num)))
        else:
            word = sym + (f":{round(math.expm1(num))}" if num else "")
        if arity == 0:
            return word, i + 1
        parts, j = [word], i + 1
        for _ in range(arity - 1):
            part, j = self._node(enc, r, j)
            parts.append(part)
        return "(" + " ".join(parts) + ")", j
