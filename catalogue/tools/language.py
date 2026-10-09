"""language.py - the inner language: vocabulary, parser, validator, English printer (reference for the C++ port).

    python3 catalogue/tools/language.py "(offer (if (not (did you give silver_coin:3 (to me))) (did me speak (to @E2) (says (that b:7)))))"

An utterance is a prefix S-expression: (MOOD PROP) or (FORMULA ...). Parentheses do not count; every other
symbol does (<= MAX_SYMBOLS). Pointers into the speaker's context (@E3, @T5, @G1, @PLACE, b:7, m:2, g:1)
are resolved by the engine for each hearer (see data/language_grammar.toml).
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from schema import Catalogue, FORBIDDEN_ACTION_IDS  # noqa: E402

MAX_SYMBOLS = 20
MAX_DEPTH = 2                                  # propositions nested as arguments (believes, wants, says, that)
POINTER = re.compile(r"^(@E\d+|@T\d+|@G\d+|@L\d+|@PLACE|[bmg]:\d+|n:\d+)$")
NESTING_HEADS = {"believes", "wants", "intends", "says", "may", "owes", "norm", "custom", "recipe", "that"}
SOCIAL_VERBS = set(FORBIDDEN_ACTION_IDS) | {"promise", "threaten", "blackmail", "lie", "insult", "flatter",
                                            "seduce", "betray", "steal", "murder", "bribe", "apologize"}
NAMEABLE_HOLDERS = {"mind_static", "relation"}
NAMEABLE_VARIABLES = {"pain", "hunger", "thirst", "sleepiness", "exhaustion", "sickness_felt", "intoxication",
                      "age_years", "strength", "wounds", "stress", "self_regard", "mood_valence"}
CONTEXT_WORDS = {"me", "you", "this", "here", "someone", "anyone", "everyone", "no_one"}


class LanguageError(ValueError):
    pass


class Vocabulary:
    """Grammar words (concepts, gestures, nameable variables and properties) and kinds (a separate table)."""

    def __init__(self, cat: Catalogue):
        self.cat = cat
        self.words: dict[str, str] = {}
        for c in cat["concept"].values():
            self.words[c.id] = c.category
        for a in cat["action"]:
            self.words.setdefault(a, "gesture")
        for i in cat["interpretation"]:                      # judgements are words (qualifies), never options
            self.words.setdefault(i, "interpretation")
        for v in cat["variable"].values():                   # what one talks about: traits, values, attitudes,
            if v.token and (v.holder in NAMEABLE_HOLDERS or v.id in NAMEABLE_VARIABLES):   # felt body states
                self.words.setdefault(v.id, "variable")
        for p in cat["property"]:
            self.words.setdefault(p, "property")
        self.directions = ["ahead", "ahead_right", "right", "behind_right", "behind", "behind_left", "left",
                           "ahead_left", "up", "down"]
        for d in self.directions:
            self.words.setdefault(d, "direction")
        self.kinds: set[str] = set(cat["item_type"]) | set(cat["material"]) | set(cat["species"]) | set(cat["form"])
        self.manner_intimate: set[str] = set()
        for a in cat["action"].values():                     # manner values are words too (how ...)
            for prm in a.params:
                for val in prm.values:
                    self.words.setdefault(val, "manner")
                self.manner_intimate |= set(prm.intimate_values)

    def category(self, sym: str) -> str:
        if POINTER.match(sym):
            return "pointer"
        base, _, qty = sym.partition(":")
        if base in self.kinds and (not qty or qty.isdigit()):
            return "kind"
        if sym.isdigit():
            return "number"
        if sym in self.words:
            return self.words[sym]
        raise LanguageError(f"unknown symbol '{sym}'")


@dataclass
class Node:
    head: str
    args: list = field(default_factory=list)       # Node | str

    def symbols(self) -> list[str]:
        out = [self.head]
        for a in self.args:
            out += a.symbols() if isinstance(a, Node) else [a]
        return out


class Parser:
    TOKEN = re.compile(r"\(|\)|[^\s()]+")

    def parse(self, text: str) -> Node:
        toks = self.TOKEN.findall(text)
        node, rest = self._expr(toks)
        if rest:
            raise LanguageError(f"trailing symbols {rest}")
        if not isinstance(node, Node):
            raise LanguageError("an utterance is a parenthesised expression")
        return node

    def _expr(self, toks):
        if not toks:
            raise LanguageError("unexpected end")
        t, toks = toks[0], toks[1:]
        if t == ")":
            raise LanguageError("unexpected ')'")
        if t != "(":
            return t, toks
        if not toks or toks[0] in "()":
            raise LanguageError("a list must start with a symbol")
        node = Node(toks[0]); toks = toks[1:]
        while toks and toks[0] != ")":
            arg, toks = self._expr(toks)
            node.args.append(arg)
        if not toks:
            raise LanguageError("missing ')'")
        return node, toks[1:]


class Expression:
    """A validated utterance."""

    def __init__(self, text: str, vocab: Vocabulary):
        self.text = text
        self.vocab = vocab
        self.root = Parser().parse(text)
        self.problems: list[str] = []
        self._validate()

    @property
    def ok(self) -> bool:
        return not self.problems

    def _validate(self):
        syms = self.root.symbols()
        if len(syms) > MAX_SYMBOLS:
            self.problems.append(f"{len(syms)} symbols > {MAX_SYMBOLS}")
        for s in syms:
            if s in SOCIAL_VERBS:
                self.problems.append(f"'{s}' names a social act: say it with words, not with a verb (D28)")
            try:
                self.vocab.category(s)
            except LanguageError as e:
                self.problems.append(str(e))
        head_cat = self.vocab.words.get(self.root.head)
        if head_cat not in ("mood", "formula"):
            self.problems.append(f"an utterance starts with a mood or a formula, not '{self.root.head}'")
        depth = self._depth(self.root)
        if depth > MAX_DEPTH:
            self.problems.append(f"nesting depth {depth} > {MAX_DEPTH}")

    def _depth(self, node) -> int:
        if not isinstance(node, Node):
            return 0
        inner = max((self._depth(a) for a in node.args), default=0)
        return inner + (1 if node.head in NESTING_HEADS else 0)

    def intimate_symbols(self) -> list[str]:
        """Symbols flagged intimate (D10): the governor refuses them toward or from a minor."""
        out = []
        for s in self.root.symbols():
            c = self.vocab.cat["concept"].get(s)
            v = self.vocab.cat["variable"].get(s)
            if (c is not None and c.intimate) or (v is not None and v.intimate) or s in self.vocab.manner_intimate:
                out.append(s)
        return out


class EnglishPrinter:
    """Rough English rendering, for debugging and for the teacher LLM (never shown as game text)."""

    def render(self, node) -> str:
        if not isinstance(node, Node):
            return node.replace("_", " ")
        args = [self.render(a) for a in node.args]
        h = node.head
        if h == "not":
            return f"not ({args[0]})"
        if h in ("and", "or", "because"):
            return f"({args[0]}) {h} ({args[1]})"
        if h == "if":
            return f"if ({args[0]}) then ({args[1]})"
        if h == "that":
            return f"[content of {args[0]}]"
        if h in ("to", "with", "into", "how"):
            return f"{h} {' '.join(args)}"
        if h == "says":
            return f'saying "{args[0]}"'
        return f"{h.replace('_', ' ')}: " + ", ".join(args) if args else h


def main(argv):
    vocab = Vocabulary(Catalogue.load())
    for text in argv:
        e = Expression(text, vocab)
        print(("OK  " if e.ok else "BAD ") + f"{len(e.root.symbols())} symboles : " + EnglishPrinter().render(e.root))
        for p in e.problems:
            print("   -", p)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
