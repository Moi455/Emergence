"""language_vectors.py - shared test vectors for the C++ inner-language validator (T13).

    python3 catalogue/tools/language_vectors.py [N]   # writes engine/social/src/language_tables.inc
                                                      #        engine/social/tests/language_vectors.inc

The Python validator (language.py) is the ORACLE. This script
  * dumps the vocabulary the validator derives from the catalogue (word categories, kinds, concepts, gestures) as
    C++ tables (language_tables.inc), so the C++ port reads no catalogue at run time;
  * maps every message of the oracle to a STABLE CODE (CODE_PATTERNS below; a message with no code, or with two,
    stops the script), so that the verdict compared is the list of codes, in order, not only ok / refused;
  * writes N vectors (default 50 000): the utterances and trace lines of catalogue/data/stories.toml, hand-written
    cases (one per code), typed random propositions and MUTATIONS of them (invalid ones), with their verdict.
Deterministic (fixed seed, sorted iteration). It generates no intimate content: the random generator never draws a
symbol flagged intimate (D10); intimate words only appear through the stories already in the catalogue.
"""
from __future__ import annotations

import random
import re
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(HERE))
from schema import Catalogue  # noqa: E402
import language as L  # noqa: E402
from language import Expression, Node, POINTER, Vocabulary  # noqa: E402

SOCIAL = ROOT.parent / "engine" / "social"
OUT_TABLES = SOCIAL / "src" / "language_tables.inc"
OUT_VECTORS = SOCIAL / "tests" / "language_vectors.inc"
SEED = 20261015
MAX_TEXT = 1000                       # as ai/tok2/proposition.py
CLEAN = re.compile(r"[\t\n\r\x20-\x7e]*")

# message regex -> stable code (first and only match). Order is irrelevant: exactly one must match.
CODE_PATTERNS = [
    (r"^trailing symbols", "parse_trailing"),
    (r"^an utterance is a parenthesised expression$", "parse_not_list"),
    (r"^unexpected end$", "parse_end"),
    (r"^unexpected '\)'$", "parse_close"),
    (r"^a list must start with a symbol$", "parse_head"),
    (r"^missing '\)'$", "parse_missing_close"),
    (r"^\d+ symbols > ", "too_many_symbols"),
    (r"^'the_one' only has a meaning", "hole_misplaced"),
    (r"^nesting depth ", "too_deep"),
    (r": an utterance is \(MOOD PROP\) or \(FORMULA \.\.\.\)$", "utt_not_list"),
    (r"^\(\S+ …\) takes exactly one proposition$", "mood_arity"),
    (r"only an answering formula", "formula_pointer"),
    (r"^\(\S+ …\) takes at most one utterance$", "formula_extra"),
    (r"^an utterance starts with a mood or a formula", "utt_head"),
    (r"' is not a proposition$", "not_proposition"),
    (r"^a second mood or formula ", "second_mood"),
    (r"^'described' is a reference", "described_as_prop"),
    (r"^\(\S+ …\) takes \d+ argument\(s\)$", "logic_arity"),
    (r"^\(that …\) points to one of my records", "that_target"),
    (r"^\(\S+ …\) wraps exactly one proposition$", "wrap_arity"),
    (r"^\(\S+ TIME PROP\) takes a time mark and a proposition$", "timeop_arity"),
    (r"' is not a predicate$", "not_predicate"),
    (r"^\(\S+ …\) takes \d+ argument\(s\), got \d+$", "pred_arity"),
    (r"^\(\S+ …\): argument \d+ is .* it must be ", "arg_class"),
    (r"^\(\S+ …\) takes a time mark, not \(", "time_mark_node"),
    (r"^\(span QUANTITY UNIT\)$", "span_shape"),
    (r"^\(span .* a count or a quantity word is expected$", "span_count"),
    (r"^\(span … .*a unit of time is expected", "span_unit"),
    (r"^\(for …\) takes a duration", "for_duration"),
    (r"^unknown symbol ", "unknown_symbol"),
    (r"^bad quantity in ", "bad_quantity"),
    (r"' is not a time mark$", "not_time_mark"),
    (r"^\(did AGENT GESTURE \[TARGET\] ROLE\*\)$", "did_shape"),
    (r"is not a gesture: social acts", "not_gesture"),
    (r"cannot be done to ", "gesture_target"),
    (r"^\d+ roles > ", "too_many_roles"),
    (r"^after the target of ", "role_bad"),
    (r"^role '.*' given twice$", "role_twice"),
    (r"^\(says …\) only in a speak or write frame$", "says_frame"),
    (r"^\(says PROP\)$", "says_shape"),
    (r"^\(how …\) takes one manner of ", "how_bad"),
    (r"^\(\S+ REF\)$", "role_shape"),
    (r"it is a manner: use how\)$", "role_manner"),
    (r"^'.*' has no '.*' role( for a thing)?$", "role_none"),
    (r"^\(\S+ …\) of '.*' takes ", "role_accept"),
    (r"is something held \(an item\) or a companion$", "role_held"),
    (r"\(a question hole\) outside", "wh_outside"),
    (r"^'[^']*' cannot stand for a ", "arg_cannot"),
    (r"^a \S+ was expected, not \(", "arg_node"),
    (r"^\(described WORD\+ \[CLAUSE\]\)$", "described_empty"),
    (r"^\(described …\) takes its words first", "described_order"),
    (r"^\(described …\) takes descriptive words only", "described_words"),
    (r"^a description cannot stand for a ", "described_expected"),
    (r"^a relative clause is a predicate or an event", "clause_head"),
    (r"^a relative clause holds exactly one ", "clause_holes"),
    (r"^a part of a group cannot stand for a ", "of_expected"),
    (r"^\(of QUANTITY GROUP\)$", "of_arity"),
    (r"^\(of QUANTITY …\): a count", "of_quantity"),
    (r"^\(of … GROUP\): a group, a person kind", "of_group_head"),
    (r"^\(of … .*\): not a group of people$", "of_not_group"),
    (r"^\(of … GROUP\)$", "of_bad"),
    (r"^\(\S+ …\) has \d+ pointers > ", "pointers_max"),
]
CODE_RES = [(re.compile(p, re.S), c) for p, c in CODE_PATTERNS]
WRAPPER_CODES = ["too_long", "charset"]


def code_of(msg: str) -> str:
    hits = {c for r, c in CODE_RES if r.search(msg)}
    if len(hits) != 1:
        raise SystemExit(f"message without exactly one code: {msg!r} -> {sorted(hits)}")
    return hits.pop()


def all_codes() -> list[str]:
    return [c for _, c in CODE_PATTERNS] + WRAPPER_CODES


# ---------------------------------------------------------------- tables for C++
def cq(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def emit_tables(cat: Catalogue, v: Vocabulary) -> None:
    ident = lambda s: re.sub(r"\W", "_", s)  # noqa: E731
    cats = sorted({c for cs in v.cats.values() for c in cs})
    types = set()
    for s in L.CATEGORY_TYPES.values():
        types |= s
    for k, s in L.ACCEPTS.items():
        types |= {k} | s
    for x in L.REF_WORDS.values():
        types |= x
    types |= {"agent", "entity", "item", "group", "place", "role", "event", "proposition", "name", "quantity", "kind",
              "concept"}
    for c in cat["concept"].values():
        types |= set(c.args)
    types = sorted(types)
    tags = {"agent", "animal", "item", "structure", "plant", "land", "place", "group", "water", "direction", "terrain",
            "voxel", "fire", "trace", "form", "belief", "sky"}
    for a in cat["action"].values():
        for p in a.params:
            tags |= set(p.accepts)
    for c in cat["concept"].values():
        for ac in c.arg_classes:
            tags |= set(ac or [])
    tags = sorted(tags)
    assert len(cats) <= 64 and len(types) <= 64 and len(tags) <= 64, (len(cats), len(types), len(tags))
    mask = lambda names, order: sum(1 << order.index(n) for n in set(names))  # noqa: E731
    out = ["// GENERATED by catalogue/tools/language_vectors.py from catalogue/ - do not edit (T13).",
           "// Vocabulary of the inner language as the Python validator (catalogue/tools/language.py) derives it.",
           "namespace lang_tables {", ""]
    for name, order in (("Cat", cats), ("Ty", types), ("Tag", tags)):
        for i, n in enumerate(order):
            out.append(f"inline constexpr std::uint64_t k{name}_{ident(n)} = 1ull << {i};")
        out.append("")
    # words (homonyms: several categories)
    intimate_words = set(v.manner_intimate)
    for w in v.cats:
        c = cat["concept"].get(w); var = cat["variable"].get(w)
        if (c is not None and c.intimate) or (var is not None and var.intimate):
            intimate_words.add(w)
    out.append("struct WordRow { const char* word; std::uint64_t cats; bool intimate; };")
    out.append(f"inline constexpr WordRow kWords[{len(v.cats)}] = {{")
    for w in sorted(v.cats):
        out.append(f"  {{{cq(w)}, {mask(v.cats[w], cats)}ull, {'true' if w in intimate_words else 'false'}}},")
    out += ["};", ""]
    # kinds
    out.append("enum KindFlag : std::uint16_t { kQuality = 1, kSite = 2, kBuilt = 4, kSpecies = 8, kItemOrMaterial = 16, kForm = 32,"
               " kPlant = 64, kAnimal = 128, kLand = 256, kWater = 512, kSky = 1024 };")
    out.append("struct KindRow { const char* name; std::uint16_t flags; };")
    out.append(f"inline constexpr KindRow kKinds[{len(v.kinds)}] = {{")
    for k in sorted(v.kinds):
        f = 0
        if k in v.qualities: f |= 1
        if k in v.sites:
            f |= 2
            s = cat["site"][k]
            f |= 4 if s.built else 0
            f |= {"land": 256, "water": 512, "sky": 1024}.get(s.category, 0)
        if k in cat["species"]:
            f |= 8 | (64 if cat["species"][k].kingdom == "plant" else 128 if cat["species"][k].kingdom == "animal" else 0)
        if k in cat["item_type"] or k in cat["material"]: f |= 16
        if k in cat["form"]: f |= 32
        out.append(f"  {{{cq(k)}, {f}}},")
    out += ["};", ""]
    # concepts
    cons = sorted(cat["concept"].values(), key=lambda c: c.id)
    maxa = max(len(c.args) for c in cons)
    out.append(f"inline constexpr int kMaxConceptArgs = {maxa};")
    out.append("struct ConceptRow { const char* id; std::uint64_t cat; int nargs; std::uint64_t argty[kMaxConceptArgs];"
               " std::uint64_t argclass[kMaxConceptArgs]; bool wh_ok, answers; };")
    out.append(f"inline constexpr ConceptRow kConcepts[{len(cons)}] = {{")
    for c in cons:
        ac = [mask(ac or [], tags) for ac in c.arg_classes] + [0] * maxa
        at = [1 << types.index(t) for t in c.args] + [0] * maxa
        out.append(f"  {{{cq(c.id)}, kCat_{ident(c.category)}, {len(c.args)}, {{{', '.join(str(x) + 'ull' for x in at[:maxa])}}},"
                   f" {{{', '.join(str(x) + 'ull' for x in ac[:maxa])}}}, {'true' if c.wh_ok else 'false'},"
                   f" {'true' if c.answers else 'false'}}},")
    out += ["};", ""]
    # actions
    acts = sorted(cat["action"].values(), key=lambda a: a.id)
    vals: list[str] = []
    maxp = max(len(a.params) for a in acts)
    out.append(f"inline constexpr int kMaxParams = {maxp};")
    out.append("struct ParamRow { const char* name; int type; std::uint64_t accepts; int first_value, n_values; };")
    out.append("struct ActionRow { const char* id; int nparams; ParamRow params[kMaxParams]; };")
    rows = []
    for a in acts:
        ps = []
        for p in a.params:
            first = len(vals); vals += list(p.values)
            t = {"ref": 0, "enum": 1, "expression": 2, "condition": 3}[p.type]
            ps.append(f"{{{cq(p.name)}, {t}, {mask(p.accepts, tags)}ull, {first}, {len(p.values)}}}")
        ps += ["{\"\", 0, 0ull, 0, 0}"] * (maxp - len(ps))
        rows.append(f"  {{{cq(a.id)}, {len(a.params)}, {{{', '.join(ps)}}}}},")
    out.append(f"inline constexpr const char* kValues[{max(1, len(vals))}] = {{")
    out += [f"  {cq(x)}," for x in vals] or ['  "",']
    out += ["};", f"inline constexpr ActionRow kActions[{len(acts)}] = {{"] + rows + ["};", ""]
    tm = lambda names: " | ".join(f"kTy_{ident(n)}" for n in sorted(names)) or "0"  # noqa: E731
    out.append("struct CatTypesRow { std::uint64_t cat, types; };")
    ct = [(c, t) for c, t in sorted(L.CATEGORY_TYPES.items()) if c in cats]
    out.append(f"inline constexpr CatTypesRow kCategoryTypes[{len(ct)}] = {{")
    out += [f"  {{kCat_{ident(c)}, {tm(t)}}}," for c, t in ct] + ["};"]
    out.append(f"inline constexpr std::uint64_t kKindTypes = {tm(L.CATEGORY_TYPES['kind'])}, kKindQtyTypes = {tm(L.CATEGORY_TYPES['kind_qty'])};")
    out.append("struct AcceptsRow { std::uint64_t expected, accepts; };")
    out.append(f"inline constexpr AcceptsRow kAccepts[{len(L.ACCEPTS)}] = {{")
    out += [f"  {{kTy_{ident(k)}, {tm(a)}}}," for k, a in sorted(L.ACCEPTS.items())] + ["};"]
    out.append("struct RefWordRow { const char* word; std::uint64_t types; };")
    out.append(f"inline constexpr RefWordRow kRefWords[{len(L.REF_WORDS)}] = {{")
    out += [f"  {{{cq(w)}, {tm(t)}}}," for w, t in sorted(L.REF_WORDS.items())] + ["};"]
    dc = [c for c in sorted(L.DESCRIPTION_CATEGORIES) if c in cats]
    out.append(f"inline constexpr std::uint64_t kDescriptionCats = {' | '.join('kCat_' + ident(c) for c in dc)};")
    out += ["}  // namespace lang_tables", ""]
    OUT_TABLES.write_text("\n".join(out))


# ---------------------------------------------------------------- oracle verdict
def unparse(node):
    return "(" + " ".join(unparse(a) if isinstance(a, Node) else a for a in [node.head, *node.args]) + ")" \
        if isinstance(node, Node) else str(node)


def verdict(text, vocab, bare, pk):
    if len(text) > MAX_TEXT:
        return ["too_long"], [], None
    if CLEAN.fullmatch(text) is None:
        return ["charset"], [], None
    e = Expression(text, vocab, bare=bare, pointer_kinds=pk)
    codes = [code_of(p) for p in e.problems]
    if codes:
        return codes, [], None
    return [], e.intimate_symbols(), unparse(e.root)


# ---------------------------------------------------------------- generation
class Gen:
    def __init__(self, cat: Catalogue, v: Vocabulary, rng: random.Random, allow_intimate: bool = False):
        self.cat, self.v, self.r = cat, v, rng
        bad = set(v.manner_intimate)
        for w in v.cats:
            c = cat["concept"].get(w); var = cat["variable"].get(w)
            if (c is not None and c.intimate) or (var is not None and var.intimate):
                bad.add(w)
        self.intimate = set(bad) | {a for a, x in cat["action"].items() if x.intimate}
        if allow_intimate:
            bad = set()
        self.bad = bad
        self.ptrs = ["@E1", "@E2", "@E3", "@T1", "@T2", "@G1", "@L1", "@L2", "@V1", "@PLACE", "b:1", "b:7", "m:2", "g:1",
                     "h:2", "q:1", "c:1", "n:3", "n:12"]
        cands = [w for w in sorted(v.cats) if w not in bad] + [k for k in sorted(v.kinds) if k not in bad]
        cands += [f"{k}:{n}" for k in sorted(v.kinds)[::7] if k not in bad for n in (1, 3)]
        cands += list(L.REF_WORDS) + self.ptrs + ["1", "2", "3", "12"]
        self.pool: dict[str, list[str]] = {}
        for exp in sorted(set(L.ACCEPTS)):
            self.pool[exp] = []
            for s in dict.fromkeys(cands):
                try:
                    if v.types(s) & L.ACCEPTS[exp] and not v.is_(s, "wh"):
                        self.pool[exp].append(s)
                except L.LanguageError:
                    pass
        self.preds = sorted(c.id for c in cat["concept"].values() if c.category == "predicate" and c.id not in bad)
        self.moods = sorted(w for w in v.cats if v.is_(w, "mood"))
        self.formulas = sorted(w for w in v.cats if v.is_(w, "formula"))
        self.times = sorted(w for w in v.cats if v.is_(w, "time") and w not in ("span",))
        self.timeops = sorted(w for w in v.cats if v.is_(w, "time_op"))
        self.evid = sorted(w for w in v.cats if v.is_(w, "evidential"))
        self.marks = [w for w in v.cats if (v.is_(w, "time_mark") or v.is_(w, "daypart") or v.is_(w, "season"))]
        self.gest = sorted(a for a in cat["action"] if not cat["action"][a].intimate and a not in bad)
        self.wh = sorted(w for w in v.cats if v.is_(w, "wh"))
        self.desc = sorted(w for w in v.cats if v.cats[w] & L.DESCRIPTION_CATEGORIES and w not in bad)
        self.degree = sorted(w for w in v.cats if v.is_(w, "degree"))
        self.units = sorted(w for w in v.cats if v.is_(w, "time_unit"))

    def pick(self, seq):
        return self.r.choice(seq) if seq else "x"

    def arg(self, t: str, d: int):
        r = self.r
        if t == "proposition" or t == "agreement":
            return self.prop(d + 1) if t == "proposition" and r.random() < 0.9 else self.pick(self.pool.get(t, ["c:1"]))
        if t == "event":
            x = r.random()
            return self.pick(self.pool["event"]) if x < 0.5 else self.event(d + 1)
        if r.random() < 0.06 and t in ("entity", "agent", "item"):
            return Node("described", [self.pick(self.desc)] + ([self.clause()] if r.random() < 0.3 else []))
        if r.random() < 0.04 and t in ("agent", "entity", "group"):
            return Node("of", [self.pick(["2", "few", "most", "half"]), self.pick(["@G1", "us", "everyone"])])
        return self.pick(self.pool.get(t, [t]))

    def clause(self):
        return Node("link", ["the_one", self.pick(["child", "parent"]), "@E3"]) if "link" in self.cat["concept"] and False else \
            Node(self.pick(self.preds[:1] or ["dead"]), ["the_one"])

    def event(self, d: int):
        r, a = self.r, None
        g = self.pick(self.gest)
        a = self.cat["action"][g]
        args = [self.arg("agent", d), g]
        refs = [p for p in a.params if p.type == "ref"]
        if refs and r.random() < 0.8:
            targets = [s for s in self.pool["entity"] if s in self.pool["entity"]]
            cand = [s for s in targets if L.ref_targets(s, self.v) & set(refs[0].accepts)]
            if cand:
                args.append(r.choice(cand))
        for _ in range(r.randint(0, 2)):
            k = r.random()
            if k < 0.4:
                vals = [x for p in a.params for x in p.values]
                if vals:
                    args.append(Node("how", [r.choice(vals)]))
            elif k < 0.6 and g in ("speak", "write") and d < 2:
                args.append(Node("says", [self.prop(d + 1)]))
            elif len(refs) > 1:
                p = r.choice(refs[1:])
                cand = [s for s in self.pool["entity"] if L.ref_targets(s, self.v) & set(p.accepts)]
                if cand:
                    args.append(Node(p.name, [r.choice(cand)]))
            else:
                args.append(Node("with", [self.pick(["@E2", "@G1", "us"])]))
        return Node("did", args)

    def prop(self, d: int = 0):
        r = self.r
        x = r.random()
        if d >= 2:
            x = 0.99
        if x < 0.55:
            h = self.pick(self.preds)
            c = self.cat["concept"][h]
            return Node(h, [self.arg(t, d) for t in c.args])
        if x < 0.7:
            return self.event(d)
        if x < 0.8:
            h = self.pick(["and", "or", "if", "because", "not"])
            n = 1 if h == "not" else 2
            return Node(h, [self.prop(d + 1) for _ in range(n)])
        if x < 0.9:
            return Node(self.pick(self.times + self.evid), [self.prop(d + 1)])
        if x < 0.96:
            op = self.pick(self.timeops)
            mark = Node("span", [self.pick(["1", "3", "few"]), self.pick(self.units)]) if op == "for" else self.pick(self.marks or ["night"])
            return Node(op, [mark, self.prop(d + 1)])
        h = self.pick(self.preds)
        c = self.cat["concept"][h]
        return Node(h, [self.arg(t, 2) for t in c.args])

    def utterance(self):
        r = self.r
        if r.random() < 0.15:
            f = self.pick(self.formulas)
            return Node(f, ([self.utterance()] if r.random() < 0.3 else []))
        m = self.pick(self.moods)
        p = self.prop(0)
        if m == "ask" and r.random() < 0.4 and self.wh:
            p = Node("knows", ["me", Node("at", ["@E9", self.pick(self.wh)])])
        return Node(m, [p])


def mutate(text: str, rng: random.Random, words: list[str]) -> str:
    toks = re.findall(r"\(|\)|[^\s()]+", text)
    if not toks:
        return text
    for _ in range(rng.choice((1, 1, 1, 2, 3))):
        if not toks:
            break
        op = rng.randrange(9)
        i = rng.randrange(len(toks))
        if op == 0:
            del toks[i]
        elif op == 1:
            toks.insert(i, rng.choice(words))
        elif op == 2:
            toks[i] = rng.choice(words)
        elif op == 3 and len(toks) > 1:
            j = rng.randrange(len(toks)); toks[i], toks[j] = toks[j], toks[i]
        elif op == 4:
            toks.insert(i, rng.choice("()"))
        elif op == 5:
            toks = toks[:max(1, i)]
        elif op == 6:
            toks.insert(i, "(" + rng.choice(words) + ")")
        elif op == 7:
            toks[i] = toks[i] + rng.choice([":3", ":", ":x", "2", ":007"])
        else:
            toks.insert(i, rng.choice(["the_one", "where", "who", "@E9", "b:1", "h:2", "n:5", "12", "@PLACE", "@V1"]))
    return " ".join(toks).replace("( ", "(").replace(" )", ")")


HAND = [  # (text, bare) - one or more cases per code and the traps of the brief (quantities, citations, holes)
    ("(offer (if (not (did you give silver_coin:3 (to me))) (did me speak (to @E2) (says (that b:7)))))", False),
    ("(assert b:7)", False), ("b:7", True), (" m:2 ", True), ("n:7", True), ("@E1", True), ("b:07x", True), ("b:7 b:8", True),
    ("(b:7)", True), ("", False), ("hello", False), ("(", False), (")", False), ("()", False), ("(assert", False),
    ("(assert (dead @E1)) extra", False), ("(assert (dead @E1)", False), ("(assert (dead @E1)))", False),
    ("(assert (owns me silver_coin:))", False), ("(assert (owns me silver_coin:x))", False), ("(assert (owns me silver_coin:007))", False),
    ("(assert (owns me silver_coin:²))", False), ("(assert (owns me @T٣))", False), ("(assert (owns me @T1)) ", False),
    ("(assert (owns me no_such_word))", False), ("(assert (owns me))", False), ("(assert (dead @E1 @E2))", False),
    ("(yes h:2)", False), ("(yes q:1)", False), ("(yes b:1)", False), ("(hello h:2)", False), ("(yes)", False), ("(yes (assert (dead @E1)))", False),
    ("(yes (assert (dead @E1)) (assert (dead @E2)))", False), ("(assert (assert (dead @E1)))", False),
    ("(assert (that b:7))", False), ("(assert (that @E1))", False), ("(assert (that b:7 b:8))", False),
    ("(assert (not))", False), ("(assert (and (dead @E1)))", False), ("(assert (past))", False),
    ("(assert (described d_woman))", False), ("(assert (past (dead the_one)))", False),
    ("(assert (dead (described d_woman (dead the_one))))", False), ("(assert (dead (described d_woman (dead @E1))))", False),
    ("(assert (dead (described d_woman (dead the_one) (dead the_one))))", False), ("(assert (dead (described)))", False),
    ("(assert (dead (described silver_coin d_woman)))", False), ("(assert (dead (of few @G1)))", False),
    ("(assert (dead (of few)))", False), ("(assert (dead (of zzz @G1)))", False), ("(assert (dead (of 3 (dead @E1))))", False),
    ("(assert (dead (of 3 silver_coin)))", False), ("(assert (dead (of 3 (described d_woman))))", False),
    ("(assert (for (span 3 hour) (dead @E1)))", False), ("(assert (for night (dead @E1)))", False),
    ("(assert (for (span 3 zzz) (dead @E1)))", False), ("(assert (for (span zzz hour) (dead @E1)))", False),
    ("(assert (for (span 3) (dead @E1)))", False), ("(assert (at_time (foo) (dead @E1)))", False),
    ("(assert (at_time zzz (dead @E1)))", False), ("(assert (at_time night))", False),
    ("(assert (did me))", False), ("(assert (did me kill @E1))", False), ("(assert (did me strike @E1 (with held)))", False),
    ("(assert (did me strike @E1 (how hard) (how hard)))", False), ("(assert (did me speak (says (dead @E1)) (says (dead @E1))))", False),
    ("(assert (did me go (says (dead @E1))))", False), ("(assert (did me speak (says)))", False),
    ("(assert (did me speak (says (dead @E1)) (to @E2) (with @E3) (how loud)))", False),
    ("(assert (did me go @L1 (how fast)))", False), ("(assert (did me go @E1 (to @E2)))", False),
    ("(ask (knows me (at @E9 where)))", False), ("(assert (at @E9 where))", False), ("(assert (dead where))", False),
    ("(ask (dead (foo)))", False), ("(assert (dead @T1))", False), ("(assert (owns me @L1))", False),
    ("(assert (dead @T1))", False), ("(assert (until))", False),
    ("(assert (owes (of @E1 @E2) @E3 b:7))", False), ("(assert (owes (of me you) us b:7))", False),
    ("(assert (owes me you b:7))", False), ("(assert (at_time @E1 (dead @E1)))", False),
    ("(assert (state @E1 pain (described d_woman)))", False), ("(assert (state @E1 pain (of 2 @G1)))", False),
    ("(assert (state @E1 pain 3))", False), ("(assert (did me speak (says (dead @E1) extra)))", False),
    ("(assert (" + "and " * 12 + "(dead @E1) " + "(dead @E2)) " * 12 + ")", False),
    ("(assert (dead " + "a" * 1000 + "))", False), ("(assert (dead (of 2 x y)))", False), ("(assert (dead (of 2)))", False),
    ("(assert (dead (of)))", False),
]


def main() -> int:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 50000
    cat = Catalogue.load()
    v = Vocabulary(cat)
    emit_tables(cat, v)
    rng = random.Random(SEED)
    gen = Gen(cat, v, rng)
    sys.path.insert(0, str(HERE))
    from probes import BARE, FULL  # noqa: E402
    vecs: list[tuple[str, bool, dict | None]] = []
    seen = set()

    def add(text, bare=False, pk=None):
        key = (text, bare, tuple(sorted((pk or {}).items())))
        if key not in seen:
            seen.add(key)
            vecs.append((text, bare, pk))

    for s in cat["story"].values():
        for u in s.utterances:
            add(u, False)
        for line in s.trace:
            parts = [p.strip() for p in line.split("|", 2)]
            if len(parts) == 3 and parts[1] in BARE + FULL:
                add(parts[2], parts[1] in BARE)
    n_stories = len(vecs)
    for g, a in sorted(cat["action"].items()):          # roles of every gesture: manner, none, accept, held, wh
        for p in a.params:
            for x in ("@E2", "@T1", "silver_coin", "@L1", "where", "us"):
                add(f"(assert (did me {g} ({p.name} {x})))", False)
        for x in ("@E2", "@T1", "@L1", "d_woman", "knife", "where"):
            add(f"(assert (did me {g} {x}))", False)
            add(f"(assert (did me {g} @E2 (with {x})))", False)
    for t, b in HAND:
        add(t, b)
    # pointer kinds: the typing of @T / @L
    kinds = sorted(k for k in v.kinds if k not in gen.bad)
    for _ in range(300):
        add(f"(assert ({rng.choice(['dead', 'owns', 'at'])} {rng.choice(['me', '@E1', '@T1'])} {rng.choice(['@T1', '@L1'])}))",
            False, {"@T1": rng.choice(kinds), "@L1": rng.choice(kinds), "@E1": rng.choice(kinds), "zz": "bogus"})
    # D10 REFUSAL / DETECTION coverage: symbols the catalogue flags intimate, in propositions built only to test that
    # the validator reports them (intimate_symbols) and refuses the malformed ones. Nothing here is played or labelled.
    igen = Gen(cat, v, random.Random(SEED + 1), allow_intimate=True)
    ints = sorted(igen.intimate)
    for w in ints:
        for tpl in ("(assert ({w} @E1 @E2))", "(assert (believes @E1 ({w} @E2)))", "(assert (did me {w} @E2))",
                    "(assert (did me go @E2 (how {w})))", "(assert (wants me ({w} @E1 @E2)))", "(assert (state @E1 {w} 3))",
                    "(ask (knows me (at @E9 {w})))", "(assert (did me speak (says (and ({w} @E1 @E2) (dead @E1)))))"):
            add(tpl.format(w=w), False)
    for w in ints:                                      # well-typed uses: a predicate with its own argument types
        c = cat["concept"].get(w)
        if c is not None and c.category == "predicate":
            for _ in range(3):
                add("(assert " + unparse(Node(w, [igen.arg(t, 1) for t in c.args])) + ")", False)
        for tpl in ("(assert (link @E1 {w} @E2))", "(assert (qualifies m:2 {w}))", "(assert (state @E1 {w} 3))",
                    "(assert (past (did @E1 go @E2 (how {w}))))", "(assert (believes @E1 (link @E2 {w} @E3)))"):
            add(tpl.format(w=w), False)
    for g in sorted(a for a, x in cat["action"].items() if x.intimate):
        for p in cat["action"][g].params:
            for val in p.intimate_values:
                add(f"(assert (did me {g} @E2 (how {val})))", False)
                add(f"(assert (did me {g} @E2 ({p.name} {val})))", False)
    n_int, tries = 0, 0
    while n_int < 400 and tries < 60000:
        tries += 1
        u = igen.utterance()
        t = unparse(u)
        if any(x in igen.intimate for x in u.symbols()):
            n_int += 1
            add(t, False)
            add(mutate(t, rng, words_i := sorted(v.cats) + ["(", ")", "@E1", "b:7", "3"]), False)
    words = sorted(v.cats) + kinds[:200] + ["(", ")", "@E1", "@T1", "@L1", "b:7", "3"]
    base = []
    while len(vecs) < n:
        u = gen.utterance()
        bare_t = unparse(u.args[0]) if u.args and rng.random() < 0.35 and isinstance(u.args[0], Node) else None
        t, bare = (bare_t, True) if bare_t else (unparse(u), False)
        add(t, bare)
        base.append((t, bare))
        if rng.random() < 0.55 and len(vecs) < n:
            add(mutate(t, rng, words), bare)
    # verdicts
    lines, count, ok = [], Counter(), 0
    for text, bare, pk in vecs:
        codes, intim, canon = verdict(text, v, bare, pk)
        ok += not codes
        count.update(codes)
        pks = ";".join(f"{k}={x}" for k, x in sorted((pk or {}).items()))
        lines.append((text, bare, pks, ",".join(codes), ",".join(intim), canon if canon not in (None, text) else ""))
    out = ["// GENERATED by catalogue/tools/language_vectors.py - do not edit (T13). Verdicts of the Python oracle.",
           f"// {len(lines)} vectors ({ok} valid, {len(lines) - ok} refused; {n_stories} from stories.toml). Codes seen:",
           "// " + ", ".join(f"{c}={count[c]}" for c in sorted(count)),
           "struct LangVector { const char* text; bool bare; const char* pointer_kinds; const char* codes; const char* intimate; const char* canonical; };",
           f"inline constexpr int kLangVectorCount = {len(lines)};",
           "inline constexpr LangVector kLangVectors[] = {"]
    for t, b, pks, cs, im, cn in lines:
        out.append(f"  {{{cq(t)}, {'true' if b else 'false'}, {cq(pks)}, {cq(cs)}, {cq(im)}, {cq(cn)}}},")
    out.append("};")
    OUT_VECTORS.write_text("\n".join(out) + "\n")
    missing = [c for c in all_codes() if not count[c]]
    print(f"{len(lines)} vectors, {ok} valid; codes never produced: {missing}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
