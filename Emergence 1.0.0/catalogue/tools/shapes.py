"""shapes.py - what ELIZA's logic teaches the inner language (step 19a, Monsieur 13 Oct): NOT its conversation, its way of
handling words. Four small, passive tools (nothing here decides for an NPC, nothing here is offered to the model):

  Keyworder     ELIZA scans for KEYWORDS with a precedence number. Here the rank of a word comes from its category
                (`keyword_ranks` in language_grammar.toml); `topic()` is the word that says what an utterance is ABOUT.
  Pattern       ELIZA's DECOMPOSITION rule ("0 YOU 0 ME") applied to the S-expression: `_`, `?x`, `<category>`, `...`.
                The synonym classes of ELIZA (/FAMILY MOTHER FATHER…) are our word categories (<link>, <deontic>…).
  ShapeMatcher  the shapes of data/speech_shapes.toml: RECOGNISE promise, threat, recruitment, rendezvous… in an utterance
                (anywhere in it, like ELIZA scans the whole sentence); the highest rank wins.
  Perspective   ELIZA's first pass swaps I and YOU. Here the same swap is made when a speech is FROZEN for the hearer:
                `me` becomes the speaker's dossier in the hearer's mind, `you` becomes the hearer's `me`.

    python3 catalogue/tools/shapes.py "(offer (future (caused us (dead @E4))))"
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from schema import Catalogue  # noqa: E402
import language  # noqa: E402
from language import Node, POINTER, Parser, Vocabulary  # noqa: E402

CITE = language.re.compile(r"^([bmghqc]:|@V)[0-9]+$")


class Keyworder:
    """The ELIZA keyword stack: the words of an utterance that carry a rank, the highest first."""

    def __init__(self, cat: Catalogue, vocab: Vocabulary):
        self.vocab = vocab
        self.ranks: dict = dict(cat["grammar"]["keyword_ranks"].ranks)

    def rank(self, word: str) -> int:
        return max((self.ranks.get(c, 0) for c in self.vocab.cats.get(word, ())), default=0)

    def stack(self, root) -> list[tuple[int, str]]:
        """[(rank, word)] by decreasing rank, then by position (ELIZA keeps the first found among equals)."""
        syms = root.symbols() if isinstance(root, Node) else [root]
        found = [(self.rank(w), i, w) for i, w in enumerate(syms) if self.rank(w) > 0]
        return [(r, w) for r, _, w in sorted(found, key=lambda t: (-t[0], t[1]))]

    def topic(self, root) -> str | None:
        st = self.stack(root)
        return st[0][1] if st else None


@dataclass
class Match:
    bindings: dict = field(default_factory=dict)


class Pattern:
    """A decomposition pattern over an utterance tree. Symbols match themselves; `_` any single subtree; `?x` binds one
    subtree (a repeated `?x` must match the same text); `<category>` a word of that category (`<pointer>`, `<cite>`,
    `<number>` are structural); `...` as the last item of a list matches the remaining arguments, zero or more."""

    def __init__(self, text: str, vocab: Vocabulary):
        self.text, self.vocab = text, vocab
        self.root = Parser().parse(text)

    def match(self, node) -> Match | None:
        b: dict = {}
        return Match(b) if self._m(self.root, node, b) else None

    def find(self, node) -> list[Match]:
        """Every place where the pattern matches (the root or any subtree)."""
        out, stack = [], [node]
        while stack:
            n = stack.pop(0)
            m = self.match(n)
            if m:
                out.append(m)
            if isinstance(n, Node):
                stack += list(n.args)
        return out

    # ---- matching
    def _m(self, pat, node, b) -> bool:
        if isinstance(pat, Node):
            if not isinstance(node, Node) or not self._head(pat.head, node.head):
                return False
            return self._list(pat.args, node.args, b)
        if pat == "_":
            return True
        if pat.startswith("?"):
            key = self._text(node)
            if pat in b:
                return b[pat] == key
            b[pat] = key
            return True
        if pat.startswith("<") and pat.endswith(">"):
            return isinstance(node, str) and self._is(pat[1:-1], node)
        return isinstance(node, str) and node == pat

    def _head(self, pat: str, head: str) -> bool:
        if pat == "_":
            return True
        if pat.startswith("<") and pat.endswith(">"):
            return self._is(pat[1:-1], head)
        return pat == head

    def _list(self, pats, nodes, b) -> bool:
        if pats and pats[-1] == "...":
            head = pats[:-1]
            return len(nodes) >= len(head) and all(self._m(p, n, b) for p, n in zip(head, nodes))
        return len(pats) == len(nodes) and all(self._m(p, n, b) for p, n in zip(pats, nodes))

    def _is(self, cls: str, sym: str) -> bool:
        if cls == "pointer":
            return bool(POINTER.match(sym))
        if cls == "cite":
            return bool(CITE.match(sym))
        if cls == "number":
            return sym.isascii() and sym.isdigit()
        return self.vocab.is_(sym, cls)

    @staticmethod
    def _text(node) -> str:
        if isinstance(node, Node):
            return "(" + " ".join(Pattern._text(a) for a in [node.head, *node.args]) + ")"
        return node


@dataclass
class Reading:
    shape: str
    rank: int
    bindings: dict


class ShapeMatcher:
    """Recognises the shapes of data/speech_shapes.toml in an utterance (after the fact: it names, it never decides)."""

    def __init__(self, cat: Catalogue | None = None):
        self.cat = cat or Catalogue.load()
        self.vocab = Vocabulary(self.cat)
        self.keywords = Keyworder(self.cat, self.vocab)
        self.patterns = {s.id: (Pattern(s.pattern, self.vocab), s.rank) for s in self.cat["shape"].values()}

    def read(self, text: str, bare: bool = False) -> list[Reading]:
        e = language.Expression(text, self.vocab, bare=bare)
        if not e.ok:
            return []
        out = []
        for sid, (pat, rank) in self.patterns.items():
            for m in pat.find(e.root):
                out.append(Reading(sid, rank, m.bindings))
        return sorted(out, key=lambda r: (-r.rank, r.shape))

    def reading(self, text: str) -> str | None:
        """The shape that wins (the highest rank), or None."""
        r = self.read(text)
        return r[0].shape if r else None

    def topic(self, text: str) -> str | None:
        e = language.Expression(text, self.vocab)
        return self.keywords.topic(e.root) if e.ok else None


class Perspective:
    """The I <-> YOU pass of ELIZA, made when a speech is frozen for its hearer. `me` and `you` are relative to the
    speaker; for the hearer the speaker is a dossier of his own mind and `you` is himself."""

    def __init__(self, speaker_key: str, hearer_self: str = "me"):
        if not POINTER.match(speaker_key):
            raise ValueError(f"the speaker must be a pointer of the hearer's mind, not '{speaker_key}'")
        self.swap = {"me": speaker_key, "you": hearer_self}

    def to_hearer(self, node):
        if isinstance(node, Node):
            return Node(node.head, [self.to_hearer(a) for a in node.args])
        return self.swap.get(node, node)

    def text(self, text: str) -> str:
        return Pattern._text(self.to_hearer(Parser().parse(text)))


def main(argv) -> int:
    m = ShapeMatcher()
    for text in argv:
        print(text)
        print("   topic :", m.topic(text))
        for r in m.read(text):
            print(f"   {r.shape} (rang {r.rank}) {r.bindings or ''}")
        if not m.read(text):
            print("   (aucune forme reconnue)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
