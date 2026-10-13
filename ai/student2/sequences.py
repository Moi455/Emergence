"""sequences.py - the inner language as the decoder writes it: S-expression text <-> prefix steps.

A proposition or an utterance is a tree. The decoder writes it in prefix order, one step per symbol, exactly like the
tok-2 proposition columns read it (so the model writes what it reads):

    step = (symbol, arity, slot, count)
      symbol  an id of the INPUT vocabulary: a word, a kind, a pointer kind (@E, @T, b:...), <num>, <nameK>
      arity   0 for a leaf, 1 + number of arguments for a list head  ("(no)" is 1, "no" is 0)
      slot    for a pointer kind, the token slot (1..128) it designates in THIS decision, else 0
      count   a CountGrid class: `silver_coin:3`, a bare `3` (class 0 = no count)
    then the end-of-sequence class. Parentheses do not exist at this level: prefix order + arity rebuild the tree.

A name (`n:11`) is written as its per-decision alias <nameK> (Encoded.names[K]); a pointer to a record the decision
does not carry (a ghost) cannot be written: the teacher is only allowed to cite records it was shown.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from language import POINTER, LanguageError, Node, Parser
from tok2.errors import TokenError
from tok2.interface import InputVocabulary
from tok2.keys import is_count
from tok2.proposition import canonical_proposition

from .spec import MAX_ARITY, STACK, OutputSpace, SpaceError

_COUNT_WORD = re.compile(r"^([^:]+):([0-9]+)\Z", re.ASCII)


class SequenceError(SpaceError):
    """A text the student cannot write as steps (too long, unknown symbol, pointer outside the decision...)."""


@dataclass
class Steps:
    """The steps of one sequence WITHOUT the end class (it is implied by the length)."""
    sym: list = field(default_factory=list)
    arity: list = field(default_factory=list)
    slot: list = field(default_factory=list)
    count: list = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.sym)

    def depths(self) -> list[int]:
        """Depth of each step, from the arities alone (the decoder tracks the same stack)."""
        out, pending = [], []                # pending[i] = children still to come of the open node i
        for a in self.arity:
            out.append(len(pending))
            if pending:
                pending[-1] -= 1
            if a > 1:
                pending.append(a - 1)
            while pending and pending[-1] == 0:
                pending.pop()
        return out

    def open_after(self) -> list[bool]:
        """After each step: is a node still waiting for children (so the sequence cannot end yet)?"""
        out, pending = [], []
        for a in self.arity:
            if pending:
                pending[-1] -= 1
            if a > 1:
                pending.append(a - 1)
            while pending and pending[-1] == 0:
                pending.pop()
            out.append(bool(pending))
        return out


class SequenceCodec:
    def __init__(self, space: OutputSpace):
        self.space, self.vocab = space, space.tokenizer.vocab
        self.parser = Parser()
        self.rounding = 0.0                  # worst relative rounding of a count since the last reset (see LabelCodec)

    # ---- text -> steps
    def encode(self, text: str, enc) -> Steps:
        root = self._parse(text)
        steps = Steps()
        self._walk(root, enc, steps)
        if len(steps) > self.space.sequences.max_symbols:
            raise SequenceError(f"{len(steps)} symbols > {self.space.sequences.max_symbols}")
        ok = self.space.sequences.arity_ok
        for sym, a in zip(steps.sym, steps.arity):
            if not ok[sym, a]:
                raise SequenceError(f"{self.vocab.symbols[sym]!r} with arity {a} is not allowed by the grammar tables")
        if max(steps.depths(), default=0) >= STACK:
            raise SequenceError(f"a tree deeper than {STACK}")
        return steps

    def _parse(self, text: str):
        s = text.strip()
        if not s:
            raise SequenceError("an empty text")
        if "(" not in s and ")" not in s and len(s.split()) == 1:         # a bare citation (b:7) is a proposition
            return s
        try:
            return self.parser.parse(s)
        except LanguageError as e:
            raise SequenceError(f"cannot parse {s[:60]!r}: {e}") from None

    def _walk(self, node, enc, steps: Steps) -> None:
        if isinstance(node, Node):
            if len(node.args) + 1 >= MAX_ARITY:
                raise SequenceError(f"({node.head} ...) has {len(node.args)} arguments; the arity classes stop at {MAX_ARITY - 2}")
            self._put(steps, self._word(node.head), len(node.args) + 1)
            for a in node.args:
                self._walk(a, enc, steps)
            return
        sym = str(node)
        if POINTER.match(sym):
            if sym.startswith("n:"):
                if sym not in enc.names or enc.names.index(sym) >= InputVocabulary.NAME_SLOTS:
                    raise SequenceError(f"the name {sym} is not printed in the records of this decision")
                self._put(steps, self.vocab.name_id(enc.names.index(sym)), 0)
                return
            if sym not in enc.keys:
                raise SequenceError(f"{sym} is not a record of this decision (a ghost cannot be written)")
            self._put(steps, self.vocab.id(self.vocab.pointer_kind(sym)), 0, slot=enc.keys.index(sym) + 1)
            return
        if sym.isascii() and sym.isdigit():
            self._put(steps, self.space.sequences.num_id, 0, count=self._count(sym))
            return
        m = _COUNT_WORD.match(sym)
        if m:
            self._put(steps, self._word(m.group(1)), 0, count=self._count(m.group(2)))
            return
        self._put(steps, self._word(sym), 0)

    def _word(self, w: str) -> int:
        if not self.vocab.is_word(w) or not self.space.sequences.allowed[self.vocab.ids[w]]:
            raise SequenceError(f"{w!r} is not a word of the inner language")
        return self.vocab.ids[w]

    def _count(self, digits: str) -> int:
        if not is_count(digits):
            raise SequenceError(f"{digits!r} is not a canonical count")
        self.rounding = max(self.rounding, self.space.counts.error(int(digits)))
        return self.space.counts.class_of(int(digits))

    @staticmethod
    def _put(steps: Steps, sym: int, arity: int, slot: int = 0, count: int = 0) -> None:
        steps.sym.append(sym)
        steps.arity.append(arity)
        steps.slot.append(slot)
        steps.count.append(count)

    # ---- steps -> text
    def decode(self, steps: Steps, enc) -> str:
        """The canonical text, or raises SequenceError when the steps are not a complete tree."""
        try:
            text, end = self._node(steps, 0, enc)
        except (IndexError, TokenError) as e:
            raise SequenceError(f"not a complete tree: {e}") from None
        if end != len(steps):
            raise SequenceError(f"{len(steps) - end} steps left after the tree")
        return text

    def _node(self, steps: Steps, i: int, enc):
        word = self._symbol(steps, i, enc)
        a = steps.arity[i]
        if a == 0:
            return word, i + 1
        parts, j = [word], i + 1
        for _ in range(a - 1):
            part, j = self._node(steps, j, enc)
            parts.append(part)
        return "(" + " ".join(parts) + ")", j

    def _symbol(self, steps: Steps, i: int, enc) -> str:
        sym, slot, cls = steps.sym[i], steps.slot[i], steps.count[i]
        s = self.space.sequences
        name = self.vocab.symbols[sym]
        n = self.space.counts.count_of(cls)
        if s.is_pointer[sym]:
            if not 1 <= slot <= len(enc.keys):
                raise SequenceError(f"pointer {name} to slot {slot}: not a record of this decision")
            return enc.keys[slot - 1]
        if name.startswith("<name") and name != InputVocabulary.NAME_OTHER:
            k = int(name[5:-1])
            if k >= len(enc.names):
                raise SequenceError(f"alias {name} has no name in this decision")
            return enc.names[k]
        if sym == s.num_id:
            if n is None:
                raise SequenceError("a bare number needs a count")
            return str(n)
        if not s.allowed[sym] or sym == s.eos:
            raise SequenceError(f"symbol {name!r} cannot be written")
        return name if n is None else f"{name}:{n}"


def canonical(text: str) -> str:
    """The canonical spelling used to compare two texts of the language (tok-2: one space, no space by parentheses)."""
    return canonical_proposition(text.strip())
