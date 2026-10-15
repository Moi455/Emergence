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
CITING = "bmghqc"                              # b: belief, m: memory, g: goal ; h: something HEARD, q: a REQUEST, c: a COMMITMENT
POINTER = re.compile(r"^(@E\d+|@T\d+|@G\d+|@L\d+|@V\d+|@PLACE|[bmghqc]:\d+|n:\d+)\Z", re.ASCII)   # ASCII digits only
NESTING_HEADS = {"believes", "wants", "intends", "says", "may", "owes", "norm", "custom", "recipe", "that", "knows"}
HOLE = "the_one"                               # the hole of a relative description: (described … (link the_one child @E3))
NAMEABLE_HOLDERS = {"mind_static", "relation"}
NAMEABLE_VARIABLES = {"pain", "hunger", "thirst", "sleepiness", "exhaustion", "sickness_felt", "intoxication",
                      "age_years", "strength", "wounds", "stress", "self_regard", "mood_valence", "pregnancy"}
REF_WORDS = {"me": {"agent", "entity"}, "you": {"agent", "entity"}, "us": {"group", "agent", "entity"},
             "someone": {"agent", "entity"},
             "anyone": {"agent", "entity"}, "everyone": {"agent", "entity", "group"}, "no_one": {"agent", "entity"},
             "this": {"entity", "item"}, "here": {"place"}, HOLE: {"agent", "entity", "item", "place", "group"},
             "somewhere": {"place"}, "nowhere": {"place"}, "something": {"entity", "item"}, "nothing": {"entity", "item"}}
# what a word category can stand for as an argument
CATEGORY_TYPES = {
    "degree": {"quantity"}, "quantity": {"quantity"}, "number": {"quantity"},
    "gesture": {"gesture"}, "variable": {"variable"}, "property": {"variable"}, "emotion": {"emotion", "variable"},
    "interpretation": {"interpretation"}, "technique": {"technique", "concept"},
    "link": {"concept"}, "spatial": {"concept"}, "deontic": {"concept"}, "quality": {"concept"},
    "group_kind": {"kind", "concept"}, "lookalike": {"kind", "concept"}, "goal_mode": {"concept"},
    "plan_state": {"concept"}, "plan_repeat": {"concept"}, "wake_cause": {"concept"}, "odor": {"concept"}, "age": {"concept"},   # T08c
    "source": {"concept"}, "descriptor": {"concept"}, "role_word": {"concept", "role"},
    "occupation": {"concept"}, "manner": {"manner"}, "direction": {"place"}, "time": {"time"}, "fraction": {"quantity"},
    "daypart": {"time"}, "season": {"time"}, "time_mark": {"time"},                       # moments and seasons are time marks (step 19a)
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


# what a referring symbol can be, as a gesture target (REF_TARGETS of catalogue/schema.py)
def ref_targets(sym, vocab) -> set:
    if not isinstance(sym, str):
        if sym.head == "of":
            return {"agent", "group"}                         # a part of a group
        words = [x.partition(":")[0] for x in sym.args if isinstance(x, str)]
        if any(w in vocab.sites for w in words):        # (described house …): a place, a construction
            return {"place", "structure"}
        return {"agent", "animal", "item"}                    # (described …)
    if sym in ("somewhere", "nowhere"):
        return {"place", "terrain", "direction"}
    if sym in ("something", "nothing"):
        return {"animal", "item", "structure", "terrain", "plant"}
    if sym == HOLE:
        return {"agent", "animal", "item", "place", "structure", "group"}
    if sym.startswith("@E") or sym in ("me", "you", "someone", "anyone", "everyone", "no_one") or sym.startswith("n:"):
        return {"agent"} | ({"place", "group"} if sym.startswith("n:") else set())
    if sym == "us" or sym.startswith("@G"):
        return {"group", "agent"}
    if sym.startswith("@T") or sym == "this":
        return {"animal", "item", "structure", "terrain", "voxel", "water", "fire", "trace", "plant"}
    if sym.startswith("@L") or sym in ("@PLACE", "here"):
        return {"place", "water", "terrain"}
    if sym.startswith("@V"):
        return set()
    if sym.startswith(("b:", "g:", "m:")):
        return {"belief"}
    if sym.startswith(("h:", "q:", "c:")):
        return set()                                          # something heard, asked or agreed: not a gesture target
    if vocab.is_(sym, "direction"):
        return {"direction"}
    base = sym.partition(":")[0]
    if base in vocab.qualities:
        return set()                                          # a perceived quality is not something one points at
    if base in vocab.sites:
        site = vocab.cat["site"][base]
        if site.built:
            return {"place", "structure", "form"}             # a house: a place, a structure, a form to build INTO
        return {"place", "water"} if site.category == "water" else {"place", "direction"} if site.category == "sky" else {"place", "terrain"}
    if base in vocab.cat["species"]:
        out = {"animal", "plant"}
        if base in vocab.cat["item_type"] or base in vocab.cat["material"]:
            out |= {"item", "structure"}                        # beans, cabbage: the plant in the field, the thing in the hand
        return out
    if base in vocab.cat["form"]:
        return {"form"}
    if base in vocab.kinds or vocab.is_(base, "lookalike"):
        return {"item", "structure", "plant"}
    return set()


DESCRIPTION_CATEGORIES = {"descriptor", "role_word", "occupation", "quality", "lookalike", "group_kind"}


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
        self.sites: set[str] = set(cat["site"])                         # kinds of places and constructions (step 19a)
        self.qualities: set[str] = set(cat["percept_word"])             # words of what is perceived (a build, a colour…)
        self.kinds: set[str] = (set(cat["item_type"]) | set(cat["material"]) | set(cat["species"]) | set(cat["form"])
                                | self.sites | self.qualities)          # the whole `sortes` table (≤ 1 024)
        self.words = {w: "+".join(sorted(cs)) for w, cs in self.cats.items()}   # flat view (budget, interface)

    def types(self, sym: str) -> set[str]:
        """Argument types a bare symbol can stand for."""
        if POINTER.match(sym):
            if sym.startswith("@E"):
                return {"agent", "entity"}
            if sym.startswith("@T"):
                return {"item", "entity"}
            if sym.startswith("@G"):
                return {"group", "role", "entity", "agent"}                  # a group acts, wants, is spoken to
            if sym.startswith("@L") or sym == "@PLACE":
                return {"place"}
            if sym.startswith("@V"):
                return {"event"}                                          # a perceived event (EVENT token)
            if sym.startswith(("b:", "g:", "c:")):
                return {"proposition"}
            if sym.startswith(("m:", "h:", "q:")):
                return {"event", "proposition"}                          # a memory, something heard or asked: a said event
            return {"agent", "entity", "place", "group", "name"}          # n:<id>, a name
        if sym in REF_WORDS:
            return REF_WORDS[sym]
        base, _, qty = sym.partition(":")
        out: set[str] = set()
        if base in self.kinds or "lookalike" in self.cats.get(base, ()):
            if qty and not (qty.isascii() and qty.isdigit()):
                raise LanguageError(f"bad quantity in '{sym}'")
            if base in self.qualities:
                out |= {"concept"}                                      # a word of what is perceived: said, not pointed at
            elif base in self.sites:
                out |= {"kind", "concept", "entity", "place"} if not qty else {"kind", "entity", "place"}
            else:
                out |= CATEGORY_TYPES["kind_qty" if qty else "kind"]
        if sym.isascii() and sym.isdigit():
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
    """A validated utterance (or the proposition of a record written by the model).

    bare=True validates a BARE proposition, `(owns me @T1)`, as stored in a belief, a goal or a memory: no mood or
    formula around it (the content of a record is not an utterance), same predicates, arguments, pointer budget,
    symbol count and nesting limits."""

    def __init__(self, text: str, vocab: Vocabulary, bare: bool = False, pointer_kinds: dict | None = None):
        self.text = text
        self.vocab = vocab
        self.bare = bare
        # pointer -> the kind word of its record (@T1: knife, @L1: forest); anything that is not a pointer mapped to a
        # known kind word is ignored (an unknown record kind types nothing, as before)
        self.pointer_kinds = {k: x for k, x in (pointer_kinds or {}).items()
                              if isinstance(k, str) and POINTER.match(k) and isinstance(x, str) and x.partition(":")[0] in vocab.kinds}
        self.problems: list[str] = []
        self._clause_holes = 0
        if bare and POINTER.match(text.strip()) and text.strip()[0] in CITING:      # a bare citation: `(assert b:7)` -> `b:7`
            self.root = text.strip()
            self._validate()
            return
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
        syms = self.root.symbols() if isinstance(self.root, Node) else [self.root]
        if len(syms) > MAX_SYMBOLS:
            self.problems.append(f"{len(syms)} symbols > {MAX_SYMBOLS}")
        if self.bare:
            self._prop(self.root)
        else:
            self._utterance(self.root)
        if syms.count(HOLE) != self._clause_holes:
            self.problems.append(f"'{HOLE}' only has a meaning inside a relative clause of (described …)")
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
            args = list(node.args)
            if args and isinstance(args[0], str) and POINTER.match(args[0]):      # (yes h:2): an answer to ONE precise item
                c = v.cat["concept"].get(node.head)
                if not (c is not None and c.answers) or args[0][0] not in "hqc":
                    self.problems.append(f"({node.head} {args[0]}): only an answering formula (yes, no) points, to something heard (h:), asked (q:) or agreed (c:)")
                args = args[1:]
            if len(args) > 1:
                self.problems.append(f"({node.head} …) takes at most one utterance")
            for a in args:
                self._utterance(a)
        else:
            self.problems.append(f"an utterance starts with a mood or a formula, not '{node.head}'")

    def _prop(self, node, allow_wh=False):
        v = self.vocab
        if isinstance(node, str):
            if not (POINTER.match(node) and node[0] in CITING):
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
                if not (isinstance(args[0], str) and POINTER.match(args[0]) and args[0][0] in CITING):
                    self.problems.append("(that …) points to one of my records (b:, m:, g:, h:, q:, c:)")
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
        if v.is_(h, "time_op"):
            if len(args) != 2:
                self.problems.append(f"({h} TIME PROP) takes a time mark and a proposition")
                return
            self._time_mark(args[0], h)
            self._prop(args[1], allow_wh)
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
            self._arg(a, t, allow_wh or bool(c.wh_ok and t == "proposition"))      # « je ne sais pas où il est »
        for i, (a, allowed) in enumerate(zip(args, c.arg_classes)):
            known = self._classes(a)
            if allowed and known is not None and not known & set(allowed):
                self.problems.append(f"({h} …): argument {i + 1} is {'/'.join(sorted(known))}, it must be {'/'.join(allowed)}")

    def _time_mark(self, a, op: str):
        """A time mark (TE): a moment of the day, a season, today / tomorrow / yesterday, a remembered event, or a
        span. `for` takes a duration only: (span N UNIT)."""
        v = self.vocab
        if isinstance(a, Node):
            if a.head != "span":
                self.problems.append(f"({op} …) takes a time mark, not ({a.head} …)")
            elif len(a.args) != 2 or not all(isinstance(x, str) for x in a.args):
                self.problems.append("(span QUANTITY UNIT)")
            else:
                n, unit = a.args
                if not (n.isascii() and n.isdigit()) and not v.is_(n, "quantity"):
                    self.problems.append(f"(span {n} …): a count or a quantity word is expected")
                if not v.is_(unit, "time_unit"):
                    self.problems.append(f"(span … {unit}): a unit of time is expected (hour, day, season, year)")
            return
        if op == "for":
            self.problems.append("(for …) takes a duration (span N UNIT)")
            return
        try:
            types = v.types(a)
        except LanguageError as e:
            self.problems.append(str(e))
            return
        if not types & {"time", "event"}:
            self.problems.append(f"'{a}' is not a time mark")

    def _event(self, node, allow_wh):
        """(did AGENT GESTURE [TARGET] ROLE*). The roles are the PARAMETERS of the gesture (step 19a): its other ref
        params by name (give to; throw at, with; put where; pour from, into; pull toward; guard against; wear on;
        write on; channel into), `how` for a manner, `says` for a speech, and `with` also for a companion."""
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
        refs = [p for p in a.params if p.type == "ref"]
        if rest and (isinstance(rest[0], str) or (isinstance(rest[0], Node) and rest[0].head in ("described", "of"))):
            self._arg(rest[0], "entity", allow_wh)
            if refs and not (isinstance(rest[0], str) and v.is_(rest[0], "wh")):
                if not self._targets(rest[0]) & set(refs[0].accepts):
                    self.problems.append(f"'{g}' cannot be done to {rest[0] if isinstance(rest[0], str) else 'that'} "
                                         f"(it accepts {refs[0].accepts})")
            rest = rest[1:]
        if len(rest) > MAX_ROLES:
            self.problems.append(f"{len(rest)} roles > {MAX_ROLES}")
        params = {p.name: p for p in a.params}
        vals = {x for p in a.params for x in p.values}
        seen: set[str] = set()
        for r in rest:
            if not isinstance(r, Node) or not (r.head in ("says", "how", "with") or (r.head in params and r.head in v.cats)):
                names = sorted({"how", "says", "with"} | {p.name for p in refs})
                self.problems.append(f"after the target of '{g}' only roles ({', '.join(names)})")
                continue
            if r.head in seen and r.head != "how":                 # several manners are fine ((how discreet) (how away))
                self.problems.append(f"role '{r.head}' given twice")
            seen.add(r.head)
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
            elif len(r.args) != 1:
                self.problems.append(f"({r.head} REF)")
            else:
                self._role(g, r.head, params.get(r.head), r.args[0], allow_wh)

    def _role(self, g, name, param, ref, allow_wh):
        """One role `(name REF)` of gesture g, typed by the parameter of that name. `with` is the instrument when the
        parameter is an item (throw, work, tie, scoop, operate) or the word `held` of an enum (strike), and the companion
        when REF is a person or a group, with ANY gesture."""
        self._arg(ref, "entity", allow_wh)
        if isinstance(ref, str) and self.vocab.is_(ref, "wh"):
            return
        if name == "with" and self._companion(ref):
            return
        if param is None:
            self.problems.append(f"'{g}' has no '{name}' role" + (" for a thing" if name == "with" else ""))
        elif param.type == "ref":
            if not self._targets(ref) & set(param.accepts):
                self.problems.append(f"({name} …) of '{g}' takes {param.accepts}, not {ref if isinstance(ref, str) else 'that'}")
        elif param.type == "enum" and name == "with" and "held" in param.values:
            if "item" not in self._targets(ref):
                self.problems.append(f"(with …) of '{g}' is something held (an item) or a companion")
        else:
            self.problems.append(f"'{g}' has no '{name}' role (it is a manner: use how)")

    def _classes(self, a):
        """The classes (agent, animal, item, structure, plant, land, place, group…) of an argument when they are KNOWN: a
        person word, a pointer to a person (@E: a person or a beast), a kind word, or a pointer whose record kind the
        caller gave (`pointer_kinds`). None = unknown (@T1 or @L1 alone): no constraint."""
        v = self.vocab
        if isinstance(a, Node):
            return None
        if a in self.pointer_kinds:
            a = self.pointer_kinds[a]
        if a in ("me", "you", "someone", "anyone", "no_one") or a.startswith("n:"):
            return {"agent"}
        if a in ("us", "everyone") or a.startswith("@G"):
            return {"group", "agent"}
        if a.startswith("@E"):
            return {"agent", "animal"}
        if POINTER.match(a) or a in REF_WORDS:
            return None
        base = a.partition(":")[0]
        if base in v.cat["site"]:
            site = v.cat["site"][base]
            return {"structure", "place", "land"} if site.built else {"land", "place"} if site.category == "land" else {"place"}
        out = set()
        if base in v.cat["species"]:
            out.add(v.cat["species"][base].kingdom)
        if base in v.cat["item_type"] or base in v.cat["material"]:
            out |= {"item", "structure"}                  # beans, cabbage: both a plant and a thing
        return out or None

    def _targets(self, ref) -> set:
        """What a referring symbol can be as the target or role of a gesture. A pointer whose RECORD is known (the caller's
        `pointer_kinds`: @T1 is a 'knife', @L1 a 'forest') is typed by that kind: the validator types pointers."""
        if isinstance(ref, str) and ref in self.pointer_kinds:
            return ref_targets(self.pointer_kinds[ref], self.vocab)
        return ref_targets(ref, self.vocab)

    def _companion(self, ref) -> bool:
        """`(with REF)` names a companion when REF is a person or a group: any gesture is done WITH someone."""
        v = self.vocab
        if isinstance(ref, Node):
            return ref.head == "of" or (ref.head == "described"
                                        and not any(x.partition(":")[0] in v.kinds for x in ref.args if isinstance(x, str)))
        if not isinstance(ref, str):
            return False
        t = self._targets(ref)
        return bool({"agent", "group"} & t) and "item" not in t

    def _arg(self, a, expected, allow_wh):
        v = self.vocab
        if expected == "proposition":
            self._prop(a, allow_wh)
            return
        if expected == "event" and isinstance(a, Node) and a.head not in ("described", "of"):
            self._prop(a, allow_wh)                       # (caused X (dead Y)): an outcome is a fact that happened
            return
        if isinstance(a, Node):
            if a.head == "described":
                self._described(a, expected)
                return
            if a.head == "of":
                self._part_of(a, expected, allow_wh)
                return
            self.problems.append(f"a {expected} was expected, not ({a.head} …)")
            return
        if v.is_(a, "wh"):
            if not allow_wh:
                self.problems.append(f"'{a}' (a question hole) outside (ask …) and (knows …)")
            return
        try:
            types = v.types(a)
        except LanguageError as e:
            self.problems.append(str(e))
            return
        if not types & ACCEPTS.get(expected, {expected}):
            self.problems.append(f"'{a}' cannot stand for a {expected}")

    def _described(self, a, expected):
        """(described WORD+ [CLAUSE]): descriptive words, and at most one RELATIVE CLAUSE: a predicate or an event
        whose one hole is `the_one`, « la fille du chef » = (described d_woman (link the_one child @E3)),
        « quelqu'un de ce village » = (described (lives_at the_one @L3))."""
        v = self.vocab
        words = [x for x in a.args if isinstance(x, str)]
        clauses = [x for x in a.args if isinstance(x, Node)]
        if not a.args:
            self.problems.append("(described WORD+ [CLAUSE])")
        elif len(clauses) > 1 or any(isinstance(x, Node) for x in a.args[:-1]):
            self.problems.append("(described …) takes its words first and at most one relative clause, last")
        elif not all(v.cats.get(x, set()) & DESCRIPTION_CATEGORIES or x.partition(":")[0] in v.kinds for x in words):
            self.problems.append("(described …) takes descriptive words only (descriptor, role, occupation, quality, kind)")
        elif not ACCEPTS.get(expected, set()) & {"agent", "item", "entity", "place"}:
            self.problems.append(f"a description cannot stand for a {expected}")
        else:
            for x in words:
                try:
                    v.types(x)
                except LanguageError as e:
                    self.problems.append(str(e))
            for c in clauses:
                self._relative_clause(c)

    def _relative_clause(self, c):
        v = self.vocab
        if c.head != "did" and (v.cat["concept"].get(c.head) is None or v.cat["concept"][c.head].category != "predicate"):
            self.problems.append(f"a relative clause is a predicate or an event, not ({c.head} …)")
            return
        if c.head in ("believes", "wants", "intends", "knows"):
            pass                                              # « celui qui veut tuer George » is fine
        self._prop(c)
        holes = self._own_holes(c)
        self._clause_holes += holes
        if holes != 1:
            self.problems.append(f"a relative clause holds exactly one '{HOLE}', not {holes}")

    @staticmethod
    def _own_holes(node) -> int:
        """Holes of this clause, not those of the descriptions nested inside it (each has its own)."""
        if not isinstance(node, Node):
            return int(node == HOLE)
        if node.head == "described":
            return 0
        return sum(Expression._own_holes(a) for a in node.args)

    def _part_of(self, a, expected, allow_wh):
        """(of QUANTITY GROUP): some, most, three, half of a group."""
        v = self.vocab
        if not ACCEPTS.get(expected, set()) & {"agent", "entity", "group"}:
            self.problems.append(f"a part of a group cannot stand for a {expected}")
            return
        if len(a.args) != 2:
            self.problems.append("(of QUANTITY GROUP)")
            return
        q, g = a.args
        if not isinstance(q, str) or not (q.isascii() and q.isdigit() or v.is_(q, "quantity") or v.is_(q, "fraction")):
            self.problems.append("(of QUANTITY …): a count, a quantity word (few, many, most, all) or a fraction (half, third)")
        if isinstance(g, Node):
            if g.head != "described":
                self.problems.append("(of … GROUP): a group, a person kind or a description")
            else:
                self._described(g, "entity")
        elif isinstance(g, str):
            if not ref_targets(g, v) & {"group", "agent"}:
                self.problems.append(f"(of … {g}): not a group of people")
        else:
            self.problems.append("(of … GROUP)")

    def _pointer_budget(self, node):
        n = self._pointers(node)
        if n > MAX_POINTERS:
            self.problems.append(f"({node.head} …) has {n} pointers > {MAX_POINTERS}")

    @staticmethod
    def _pointers(node) -> int:
        """Pointers of a proposition token: its own arguments, those of the parts (of …) and of the relative clauses
        of its descriptions; the hole is not one."""
        n = 0
        for a in node.args:
            if isinstance(a, str):
                n += bool(POINTER.match(a) or (a in REF_WORDS and a != HOLE))
            elif isinstance(a, Node) and a.head in ("of", "described"):
                n += Expression._pointers(a)
        return n

    def _depth(self, node) -> int:
        if not isinstance(node, Node):
            return 0
        inner = max((self._depth(a) for a in node.args), default=0)
        clause = node.head == "described" and any(isinstance(a, Node) for a in node.args)      # a relative clause nests
        return inner + (1 if node.head in NESTING_HEADS or clause else 0)

    def intimate_symbols(self) -> list[str]:
        """Symbols flagged intimate (D10): the governor refuses them toward, from or about a possible minor."""
        out = []
        for s in (self.root.symbols() if isinstance(self.root, Node) else [self.root]):
            c = self.vocab.cat["concept"].get(s)
            var = self.vocab.cat["variable"].get(s)
            if (c is not None and c.intimate) or (var is not None and var.intimate) or s in self.vocab.manner_intimate:
                out.append(s)
        return out


class EnglishPrinter:
    """Rough English rendering, for debugging and for the teacher LLM (never shown as game text)."""

    TIME_OPS = {"at_time": "at", "before": "before", "after": "after", "until": "until", "for": "for"}

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
        if h in self.TIME_OPS and len(args) == 2:
            return f"[{self.TIME_OPS[h]} {args[0]}] {args[1]}"
        if h == "span" and len(args) == 2:
            return f"{args[0]} {args[1]}s" if args[0] != "1" else f"1 {args[1]}"
        if h == "of" and len(args) == 2:
            return f"{args[0]} of {args[1]}"
        if h == "described":
            return "someone/something " + " ".join(f"[{a}]" if "(" in a or ":" in a else a for a in args)
        if h == "knows" and len(args) == 2:
            return f"{args[0]} knows ({args[1]})"
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
