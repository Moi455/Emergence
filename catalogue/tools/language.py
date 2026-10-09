"""language.py - the inner language: vocabulary, parser, TYPED validator, English printer (reference for the C++ port).

    python3 catalogue/tools/language.py "(offer (if (not (did you give silver_coin:3 (to me))) (did me speak (to @E2) (says (that b:7)))))"

An utterance is a prefix S-expression: (MOOD PROP) or (FORMULA [UTTERANCE]). Parentheses do not count; every
other symbol does (<= MAX_SYMBOLS). Every argument is type-checked against the catalogue: predicate argument
types (concept.args), the parameters of a described gesture (did agent gesture target role*), the roles allowed
in an event frame. Homonyms (saw, bow, point, open, low...) are told apart by the slot they fill. Judgements
(theft, murder, lie) are words one may say; only a GESTURE may never carry a social meaning.
Pointers into the speaker's context (@E3, @T5, @G1, @L2, @V4 = a perceived event, @PLACE, b:7, m:2, g:1, n:12) are frozen by the engine
at speaking time (see data/language_grammar.toml).
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from schema import Catalogue  # noqa: E402

MAX_SYMBOLS = 20
MAX_DEPTH = 2                                  # propositions nested as arguments (believes, wants, says, that...)
MAX_POINTERS = 3                               # per proposition
MAX_ROLES = 3                                  # per event frame: 2 inline (with, to, into, how) + says
POINTER = re.compile(r"^(@E\d+|@T\d+|@G\d+|@L\d+|@V\d+|@PLACE|[bmg]:\d+|n:\d+)$")
NESTING_HEADS = {"believes", "wants", "intends", "says", "may", "owes", "norm", "custom", "recipe", "that"}
NAMEABLE_HOLDERS = {"mind_static", "relation"}
NAMEABLE_VARIABLES = {"pain", "hunger", "thirst", "sleepiness", "exhaustion", "sickness_felt", "intoxication",
                      "age_years", "strength", "wounds", "stress", "self_regard", "mood_valence", "pregnancy"}
REF_WORDS = {"me": {"agent", "entity"}, "you": {"agent", "entity"}, "someone": {"agent", "entity"},
             "anyone": {"agent", "entity"}, "everyone": {"agent", "entity", "group"}, "no_one": {"agent", "entity"},
             "this": {"entity", "item"}, "here": {"place"}}
# what a word category can stand for as an argument
CATEGORY_TYPES = {
    "degree": {"quantity"}, "quantity": {"quantity"}, "number": {"quantity"},
    "gesture": {"gesture"}, "variable": {"variable"}, "property": {"variable"}, "emotion": {"emotion", "variable"},
    "interpretation": {"interpretation"}, "technique": {"technique", "concept"},
    "link": {"concept"}, "spatial": {"concept"}, "deontic": {"concept"}, "quality": {"concept"},
    "group_kind": {"kind", "concept"}, "lookalike": {"kind", "concept"}, "goal_mode": {"concept"},
    "source": {"concept"}, "descriptor": {"concept"}, "role_word": {"concept", "role"},
    "occupation": {"concept"}, "manner": {"manner"}, "direction": {"place"}, "time": {"time"},
    "kind": {"kind", "concept", "item", "entity"}, "kind_qty": {"item", "entity", "kind"},   # a bare kind = an indefinite one
}
# what an expected argument type accepts
ACCEPTS = {
    "entity": {"agent", "item", "entity", "group", "place"}, "agent": {"agent"}, "item": {"item", "entity"},
    "place": {"place"}, "group": {"group", "role"}, "role": {"group", "role"}, "agreement": {"proposition"},
    "event": {"event"}, "proposition": {"proposition"}, "concept": {"concept", "kind"}, "kind": {"kind"},
    "name": {"name"}, "quantity": {"quantity"}, "time": {"time"}, "gesture": {"gesture"},
    "variable": {"variable", "emotion"}, "emotion": {"emotion"}, "interpretation": {"interpretation"},
    "technique": {"technique"},
}


class LanguageError(ValueError):
    pass


class Vocabulary:
    """Grammar words (concepts, gestures, manners, interpretations, nameable variables and properties, directions)
    and kinds (a separate table). A word may have several categories (homonyms); the slot decides."""

    def __init__(self, cat: Catalogue):
        self.cat = cat
        self.cats: dict[str, set[str]] = {}
        add = lambda w, c: self.cats.setdefault(w, set()).add(c)  # noqa: E731
        for c in cat["concept"].values():
            add(c.id, c.category)
        for a in cat["action"]:
            add(a, "gesture")
        for i in cat["interpretation"]:
            add(i, "interpretation")
        for v in cat["variable"].values():
            if (v.token and v.holder in NAMEABLE_HOLDERS) or v.id in NAMEABLE_VARIABLES:
                add(v.id, "variable")
        for p in cat["property"]:
            add(p, "property")
        self.manner_intimate: set[str] = set()
        for a in cat["action"].values():
            for prm in a.params:
                for val in prm.values:
                    add(val, "manner")
                self.manner_intimate |= set(prm.intimate_values)
        self.directions = ["ahead", "ahead_right", "right", "behind_right", "behind", "behind_left", "left",
                           "ahead_left", "up", "down"]
        for d in self.directions:
            add(d, "direction")
        self.kinds: set[str] = set(cat["item_type"]) | set(cat["material"]) | set(cat["species"]) | set(cat["form"])
        self.words = {w: "+".join(sorted(cs)) for w, cs in self.cats.items()}   # flat view (budget, interface)

    def types(self, sym: str) -> set[str]:
        """Argument types a bare symbol can stand for."""
        if POINTER.match(sym):
            if sym.startswith("@E"):
                return {"agent", "entity"}
            if sym.startswith("@T"):
                return {"item", "entity"}
            if sym.startswith("@G"):
                return {"group", "role", "entity"}
            if sym.startswith("@L") or sym == "@PLACE":
                return {"place"}
            if sym.startswith("@V"):
                return {"event"}                                          # a perceived event (EVENT token)
            if sym.startswith(("b:", "g:")):
                return {"proposition"}
            if sym.startswith("m:"):
                return {"event", "proposition"}
            return {"agent", "entity", "place", "group", "name"}          # n:<id>, a name
        if sym in REF_WORDS:
            return REF_WORDS[sym]
        base, _, qty = sym.partition(":")
        out: set[str] = set()
        if base in self.kinds or "lookalike" in self.cats.get(base, ()):
            if qty and not qty.isdigit():
                raise LanguageError(f"bad quantity in '{sym}'")
            out |= CATEGORY_TYPES["kind_qty" if qty else "kind"]
        if sym.isdigit():
            out |= {"quantity"}
        for c in self.cats.get(sym, ()):
            out |= CATEGORY_TYPES.get(c, set())
        if not out and sym not in self.cats:
            raise LanguageError(f"unknown symbol '{sym}'")
        return out

    def is_(self, sym: str, category: str) -> bool:
        return category in self.cats.get(sym, ())


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
    """A validated utterance (or the proposition of a record written by the model)."""

    def __init__(self, text: str, vocab: Vocabulary):
        self.text = text
        self.vocab = vocab
        self.problems: list[str] = []
        try:
            self.root = Parser().parse(text)
        except LanguageError as e:
            self.root = Node("?")
            self.problems.append(str(e))
            return
        self._validate()

    @property
    def ok(self) -> bool:
        return not self.problems

    def _validate(self):
        syms = self.root.symbols()
        if len(syms) > MAX_SYMBOLS:
            self.problems.append(f"{len(syms)} symbols > {MAX_SYMBOLS}")
        self._utterance(self.root)
        depth = self._depth(self.root)
        if depth > MAX_DEPTH:
            self.problems.append(f"nesting depth {depth} > {MAX_DEPTH}")

    def _utterance(self, node):
        v = self.vocab
        if not isinstance(node, Node):
            self.problems.append(f"'{node}': an utterance is (MOOD PROP) or (FORMULA ...)")
            return
        if v.is_(node.head, "mood"):
            if len(node.args) != 1:
                self.problems.append(f"({node.head} …) takes exactly one proposition")
                return
            self._prop(node.args[0], allow_wh=node.head == "ask")
        elif v.is_(node.head, "formula"):
            if len(node.args) > 1:
                self.problems.append(f"({node.head} …) takes at most one utterance")
            for a in node.args:
                self._utterance(a)
        else:
            self.problems.append(f"an utterance starts with a mood or a formula, not '{node.head}'")

    def _prop(self, node, allow_wh=False):
        v = self.vocab
        if isinstance(node, str):
            if not (POINTER.match(node) and node[0] in "bmg"):
                self.problems.append(f"'{node}' is not a proposition")
            return
        h, args = node.head, node.args
        if v.is_(h, "mood") or v.is_(h, "formula"):
            self.problems.append(f"a second mood or formula '{h}' inside a proposition")
            return
        if h == "described":
            self.problems.append("'described' is a reference, not a proposition")
            return
        if v.is_(h, "logic"):
            n = {"not": 1, "that": 1}.get(h, 2)
            if len(args) != n:
                self.problems.append(f"({h} …) takes {n} argument(s)")
                return
            if h == "that":
                if not (isinstance(args[0], str) and POINTER.match(args[0]) and args[0][0] in "bmg"):
                    self.problems.append("(that …) points to one of my beliefs, memories or goals (b:, m:, g:)")
                return
            for a in args:
                self._prop(a, allow_wh)
            return
        if v.is_(h, "time") or v.is_(h, "evidential"):
            if len(args) != 1:
                self.problems.append(f"({h} …) wraps exactly one proposition")
                return
            self._prop(args[0], allow_wh)
            return
        if h == "did":
            self._event(node, allow_wh)
            return
        c = v.cat["concept"].get(h)
        if c is None or c.category != "predicate":
            self.problems.append(f"'{h}' is not a predicate")
            return
        if len(args) != len(c.args):
            self.problems.append(f"({h} …) takes {len(c.args)} argument(s), got {len(args)}")
            return
        self._pointer_budget(node)
        for a, t in zip(args, c.args):
            self._arg(a, t, allow_wh)

    def _event(self, node, allow_wh):
        v = self.vocab
        args = node.args
        if len(args) < 2:
            self.problems.append("(did AGENT GESTURE [TARGET] ROLE*)")
            return
        self._arg(args[0], "agent", allow_wh)
        g = args[1]
        a = v.cat["action"].get(g) if isinstance(g, str) else None
        if a is None:
            self.problems.append(f"'{g}' is not a gesture: social acts are said with words, not done (D28)")
            return
        rest = args[2:]
        if rest and (isinstance(rest[0], str) or (isinstance(rest[0], Node) and rest[0].head == "described")):
            self._arg(rest[0], "entity", allow_wh)
            rest = rest[1:]
        if len(rest) > MAX_ROLES:
            self.problems.append(f"{len(rest)} roles > {MAX_ROLES}")
        params = {p.name: p for p in a.params}
        vals = {x for p in a.params for x in p.values}
        for r in rest:
            if not isinstance(r, Node) or not v.is_(r.head, "event_role"):
                self.problems.append(f"after the target of '{g}' only roles (with, to, into, how, says)")
                continue
            if r.head == "says":
                if g not in ("speak", "write"):
                    self.problems.append("(says …) only in a speak or write frame")
                if len(r.args) != 1:
                    self.problems.append("(says PROP)")
                else:
                    self._prop(r.args[0], allow_wh)
            elif r.head == "how":
                if len(r.args) != 1 or not isinstance(r.args[0], str) or (r.args[0] not in vals and not v.is_(r.args[0], "degree")):
                    self.problems.append(f"(how …) takes one manner of '{g}'")
            else:
                if r.head not in params:
                    self.problems.append(f"'{g}' has no '{r.head}' role")
                if len(r.args) != 1:
                    self.problems.append(f"({r.head} REF)")
                else:
                    self._arg(r.args[0], "entity", allow_wh)

    def _arg(self, a, expected, allow_wh):
        v = self.vocab
        if expected == "proposition":
            self._prop(a, allow_wh)
            return
        if isinstance(a, Node):
            if a.head == "described":
                if not a.args or not all(isinstance(x, str) for x in a.args):
                    self.problems.append("(described WORD+)")
                elif not ACCEPTS.get(expected, set()) & {"agent", "item", "entity"}:
                    self.problems.append(f"a description cannot stand for a {expected}")
                else:
                    for x in a.args:
                        try:
                            v.types(x)
                        except LanguageError as e:
                            self.problems.append(str(e))
                return
            self.problems.append(f"a {expected} was expected, not ({a.head} …)")
            return
        if v.is_(a, "wh"):
            if not allow_wh:
                self.problems.append(f"'{a}' (a question hole) outside (ask …)")
            return
        try:
            types = v.types(a)
        except LanguageError as e:
            self.problems.append(str(e))
            return
        if not types & ACCEPTS.get(expected, {expected}):
            self.problems.append(f"'{a}' cannot stand for a {expected}")

    def _pointer_budget(self, node):
        n = sum(1 for a in node.args if isinstance(a, str) and (POINTER.match(a) or a in REF_WORDS))
        if n > MAX_POINTERS:
            self.problems.append(f"({node.head} …) has {n} pointers > {MAX_POINTERS}")

    def _depth(self, node) -> int:
        if not isinstance(node, Node):
            return 0
        inner = max((self._depth(a) for a in node.args), default=0)
        return inner + (1 if node.head in NESTING_HEADS else 0)

    def intimate_symbols(self) -> list[str]:
        """Symbols flagged intimate (D10): the governor refuses them toward, from or about a possible minor."""
        out = []
        for s in self.root.symbols():
            c = self.vocab.cat["concept"].get(s)
            var = self.vocab.cat["variable"].get(s)
            if (c is not None and c.intimate) or (var is not None and var.intimate) or s in self.vocab.manner_intimate:
                out.append(s)
        return out


class EnglishPrinter:
    """Rough English rendering, for debugging and for the teacher LLM (never shown as game text)."""

    def render(self, node) -> str:
        if not isinstance(node, Node):
            return node.replace("_", " ")
        args = [self.render(a) for a in node.args]
        h = node.head
        if h == "not" and args:
            return f"not ({args[0]})"
        if h in ("and", "or", "because") and len(args) == 2:
            return f"({args[0]}) {h} ({args[1]})"
        if h == "if" and len(args) == 2:
            return f"if ({args[0]}) then ({args[1]})"
        if h == "that" and args:
            return f"[content of {args[0]}]"
        if h in ("to", "with", "into", "how"):
            return f"{h} {' '.join(args)}"
        if h == "says" and args:
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
