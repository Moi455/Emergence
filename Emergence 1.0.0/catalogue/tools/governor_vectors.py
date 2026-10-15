"""governor_vectors.py - shared test vectors: the Python governor (oracle) decides, the C++ port must agree.

    python3 catalogue/tools/governor_vectors.py    # writes engine/social/tests/governor_vectors.inc

Deterministic (fixed seed, sorted iteration). The vectors compare the REASON CODE, not only allowed/refused.
  * writes: sequences on one ledger (game days and life-years advance, two targets, parties near the age of
    majority, things), one run per variable of every kind of writer / scale / holder;
  * check_writes: sparse writes with duplicates and more than four distinct keys;
  * gestures: random parameter combinations with adult, minor, unknown, name-only and non-person parties, the
    `executed` flag, and invalid values (an enum index == n_values, negative, a value for a missing param).
    An invalid value of a ref / qty / ... param (anything but index 0) has no Python equivalent (the Python side
    accepts any string there), so its expected reason is written directly: invalid_value.
  * an EXPRESSION param given (speak, write): the oracle checks its content (here a neutral "(help)") inside
    check_gesture; the C++ port has no language yet and refuses it (structured) until check_utterance is ported;
  * SPEECH (T14): check_utterance / check_record on utterances and records, with the speaker, the hearers (adult, minor,
    unknown, absent, none) and the symbols of the content bound to palette parties (real / believed / apparent ages,
    perceived or absent, name-only), a library of cited records (intimate acts, links, chains deeper than the limit,
    a self-cycle, an invalid copy, a missing copy) and expand given or not; P30: an intimate act or desire is never
    said to a possible minor, links and judgements are; a private thought is not a speech. The texts come from the
    catalogue's stories, from templates and from substitutions of intimate words; the oracle decides each one;
  * the ledger: days that go back and aberrant jumps (both ignored: time never goes back, review 11 and 13)
    and a ledger filled to LEDGER_CAPACITY live keys (the next new key: ledger_full).
"""
from __future__ import annotations

import random
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tools"))
from schema import Catalogue  # noqa: E402
from governor import LEDGER_CAPACITY, SELF_HOLDERS, Governor, Party, WriteLedger, age_tenths, tenths  # noqa: E402
import language  # noqa: E402
from gen_cpp import Orders, ident  # noqa: E402

OUT = ROOT.parent / "engine" / "social" / "tests" / "governor_vectors.inc"
OUT_SPEECH = ROOT.parent / "engine" / "social" / "tests" / "governor_speech_vectors.inc"
OUT_WORDS = ROOT.parent / "engine" / "social" / "src" / "governor_words.inc"
SPEECH_CASES = 9000
ORDERS = None   # gen_cpp.Orders: the C++ value index of an enum param is its position in the model's manner head
NAN = float("nan")
# Ages in YEARS, as the Python governor sees them; the C++ side gets them in tenths (floored, toward "minor")
# and Party::from_years is checked against the same numbers.
PALETTE = [
    Party(30, 30, 31, True),                          # 0 adult
    Party(9, 9, 9, True),                             # 1 child
    Party(25, 25, 16, True),                          # 2 looks young
    Party(25, 15, 25, True),                          # 3 believed young
    Party(25, None, 25, True),                        # 4 no belief about the age
    Party(25, 25, 25, False),                         # 5 known by name only
    Party(45, 44, 46, True),                          # 6 adult
    Party(17.94, 17.94, 17.94, True),                 # 7 just under (179.4 -> 179)
    Party(17.96, 17.96, 17.96, True),                 # 8 just under (179.6 floors to 179, never rounds to 180)
    Party(18.0, 18.0, 18.0, True),                    # 9 exactly of age
    Party(18.0, 18.0, 17.96, True),                   # 10 looks just under
    Party(25, NAN, 25, True),                         # 11 non-finite belief
    Party(resolved=True, person=False),               # 12 a thing
    Party(5, 5, 5, False, person=False),              # 13 a thing known by name only
    Party(18.04, 18.0, 18.0, True),                   # 14 of age (180.4 -> 180)
    Party(30, 30, None, True, perceived=False),       # 15 absent adult, believed adult (review 18)
    Party(9, 9, None, True, perceived=False),         # 16 absent child
    Party(30, None, None, True, perceived=False),     # 17 absent, no belief about the age
    Party(30, 30, None, False, perceived=False),      # 18 absent, known by name only
]
ADULTS = [i for i, p in enumerate(PALETTE) if p.person and not p.may_be_minor()]
TARGETS = (7, 9)
SEED = 20261011
SELF_EXTRAS = ["r_affection", "r_attraction", "r_fear", "assurance", "fear", "m_valence", "need_intimacy",
               "b_certainty", "pain", "self_regard", "grief", "g_priority", "b_weight", "g_desired", "attracted_to"]
CPP_ONLY_REASONS = {"non_finite", "no_writer"}          # Python-only: a C++ int16 is always finite; no variable lacks a writer


def cpp_age(a):
    return age_tenths(a)


def cpp_double(x):
    if x is None:
        return "-1.0"
    if x != x:
        return "std::numeric_limits<double>::quiet_NaN()"
    return repr(float(x))


def reason(code: str) -> str:
    return f"em::social::Reason::{code}"


def party_ref(i: int):
    return None if i < 0 else PALETTE[i]


def pick_party(rng, adult_bias: float) -> int:
    """-1 (unknown) or a palette index; biased toward adults so that allowed branches are reached too."""
    if rng.random() < 0.08:
        return -1
    return rng.choice(ADULTS) if rng.random() < adult_bias else rng.randrange(len(PALETTE))


def write_variables(cat, g):
    """Two model-writable numeric variables per (scale, writers, self-held, intimate, engine-only) kind, one of
    every other kind (refusals), plus the hand-picked ones. Returns [(id, runs, steps)]."""
    kinds: dict[tuple, list] = {}
    for v in sorted(cat["variable"].values(), key=lambda v: v.id):
        comp = cat["component"].get(v.holder)
        key = (v.scale, tuple(sorted(v.writer)), v.holder in SELF_HOLDERS, bool(v.intimate), bool(comp and comp.engine_only))
        kinds.setdefault(key, []).append(v)
    out, seen = [], set()

    def add(vid, runs, steps):
        if vid not in seen:
            seen.add(vid); out.append((vid, runs, steps))
    for vid in SELF_EXTRAS:
        v = cat["variable"][vid]
        add(vid, 14 if v.intimate else 5, 25)
    for key, vs in sorted(kinds.items()):
        v = vs[0]
        writable = g._model_writable(v) and v.scale in ("bipolar10", "unipolar10", "qty", "ratio")
        for w in vs[:2 if writable else 1]:
            add(w.id, 4 if writable else 1, 20 if writable else 3)
    return out


def gen_writes(cat, g, rng, L, counts):
    L.append("struct WriteCase { int seq; int day; int life_year; em::social::gen::Var var; short old_v; short proposed;"
             " bool creating; int target; int intimate_target; int actor; bool allowed; em::social::Reason reason; short value; };")
    L.append("static constexpr WriteCase kWrites[] = {")
    seq = 0
    # unknown variable: the Python side gets a name that is not in the catalogue, the C++ side Var::kCount
    for _ in range(4):
        seq += 1
        v = g.check_write("no_such_variable", 0, 1, WriteLedger(), target="7")
        assert v.code == "unknown_variable"
        counts["write"][v.code] += 1
        L.append(f"  {{{seq}, 0, 0, em::social::gen::Var::kCount, 0, 10, false, 7, -1, -1, false, {reason(v.code)}, 0}},")
    # non-finite values exist only on the Python side (the C++ governor takes integer tenths)
    assert g.check_write("fear", 0, NAN, WriteLedger()).code == "non_finite"
    assert g.check_write("fear", NAN, 1, WriteLedger()).code == "non_finite"
    for vid, runs, steps in write_variables(cat, g):
        for _run in range(runs):
            seq += 1
            # most ledgers start with the world, some late (an NPC born on day 1500): the first roll adopts it
            led, day, life_year = (WriteLedger(), 1500, 120) if rng.random() < 0.15 else (WriteLedger(), 0, 0)
            held = {t: 0 for t in TARGETS}
            for _ in range(steps):
                r = rng.random()
                if r < 0.10:
                    day += 1
                elif r < 0.12:
                    day += rng.randint(2, 5)
                elif r < 0.13 and day > 0:
                    day -= 1                             # time going back: ignored by the ledger
                if rng.random() < 0.04:
                    life_year += 1
                roll_day = day + 10 ** 6 if rng.random() < 0.01 else day   # one aberrant jump: ignored
                led.roll(roll_day, life_year)
                target = rng.choice(TARGETS)
                x = held[target]
                r = rng.random()
                spread = 40 if r < 0.7 else 300 if r < 0.95 else 3000
                proposed = x + rng.randint(-spread, spread)
                creating = rng.random() < 0.15
                ti, ai = pick_party(rng, 0.5), pick_party(rng, 0.7)
                v = g.check_write(vid, x / 10, proposed / 10, led, target=str(target), intimate_target=party_ref(ti),
                                  actor=party_ref(ai), creating=creating)
                val = 0 if v.value is None else tenths(v.value)
                counts["write"][v.code] += 1
                L.append(f"  {{{seq}, {roll_day}, {life_year}, em::social::gen::Var::{ident(vid)}, {x}, {proposed}, {str(creating).lower()}, "
                         f"{target}, {ti}, {ai}, {str(v.allowed).lower()}, {reason(v.code)}, {val}}},")
                if v.allowed and v.value is not None:
                    held[target] = val
    # a ledger filled to capacity: every new key is refused (ledger_full) until the day changes
    vid = "r_affection"
    seq += 1
    led = WriteLedger()
    for day, targets in ((0, range(1, LEDGER_CAPACITY + 3)), (1, range(LEDGER_CAPACITY + 1, LEDGER_CAPACITY + 4))):
        led.roll(day, 0)
        for t in targets:
            v = g.check_write(vid, 0, 1, led, target=str(t))
            val = 0 if v.value is None else tenths(v.value)
            counts["write"][v.code] += 1
            L.append(f"  {{{seq}, {day}, 0, em::social::gen::Var::{ident(vid)}, 0, 10, false, {t}, -1, -1, "
                     f"{str(v.allowed).lower()}, {reason(v.code)}, {val}}},")
    assert counts["write"]["ledger_full"] == 2, counts["write"]
    L.append("};")


def gen_check_writes(g, rng, L, counts):
    L.append("struct WritesCase { int n; int target[10]; em::social::gen::Var var[10]; em::social::Reason reason[10]; };")
    L.append("static constexpr WritesCase kWritesCases[] = {")
    pool = ["r_affection", "r_trust", "fear", "assurance", "b_weight"]
    for n_case in range(300):
        n = rng.randint(0, 10)
        if n_case % 3 == 0:                              # many distinct keys: the cap of four bites
            keys = rng.sample([(str(t), v) for t in TARGETS for v in pool], n)
        else:                                            # a small pool: duplicates
            keys = [(str(rng.choice(TARGETS)), rng.choice(pool[:3])) for _ in range(n)]
        writes = [(t, v, i) if rng.random() < 0.5 else [t, v, i] for i, (t, v) in enumerate(keys)]
        kept = {w[2] for w in g.check_writes(writes)}
        codes, seen = [], set()
        for i, key in enumerate(keys):
            code = "ok" if i in kept else "duplicate" if key in seen else "too_many_writes"
            seen.add(key)
            codes.append(code)
            counts["writes"][code] += 1
        tg = ", ".join(t for t, _ in keys) or "0"
        vs = ", ".join(f"em::social::gen::Var::{ident(v)}" for _, v in keys) or "em::social::gen::Var{}"
        rs = ", ".join(reason(c) for c in codes) or reason("ok")
        L.append(f"  {{{n}, {{{tg}}}, {{{vs}}}, {{{rs}}}}},")
    L.append("};")


def gen_gestures(cat, g, rng, L, counts):
    """GestureCase: value[i] = index of the value of param i (-1 absent, enum: index, other: 0 = given),
    party[i] = palette index of the person of param i (-1 none)."""
    L.append("struct GestureCase { em::social::gen::Gesture gesture; signed char value[6]; signed char party[6];"
             " int actor; bool executed; em::social::Reason reason; };")
    L.append("static constexpr GestureCase kGestureCases[] = {")

    def emit(gesture_cpp, vals, pidx, ai, executed, code, a=None):
        if a is not None and code != "invalid_value" and any(
                p.type == "expression" and vals[i] == 0 for i, p in enumerate(a.params)):
            code = "structured"                          # C++: content not checkable before the language port
        counts["gesture"][code] += 1
        L.append(f"  {{{gesture_cpp}, {{{', '.join(map(str, vals))}}}, {{{', '.join(map(str, pidx))}}}, {ai}, "
                 f"{str(executed).lower()}, {reason(code)}}},")

    def build(a, present_p):
        """A random call: python params / parties and the C++ value / party index arrays."""
        params, parties, vals, pidx = {}, {}, [-1] * 6, [-1] * 6
        for i, p in enumerate(a.params):
            given = rng.random() < present_p
            if given:
                if p.type == "enum":
                    k = rng.randrange(len(p.values)); vals[i] = ORDERS.value_index(a.id, p, p.values[k]); params[p.name] = p.values[k]
                elif p.type == "ref":
                    vals[i] = 0; params[p.name] = "@E1"
                elif p.type == "expression":
                    vals[i] = 0; params[p.name] = "(help)"
                else:
                    vals[i] = 0; params[p.name] = "x"
            if p.name in a.party_params and rng.random() < (0.85 if given else 0.12):
                pi = rng.randrange(len(PALETTE)); pidx[i] = pi; parties[p.name] = PALETTE[pi]
            elif p.name not in a.party_params and rng.random() < 0.03:
                pidx[i] = 0                              # a party for a param that designates nobody: ignored
        return params, parties, vals, pidx

    for a in sorted(cat["action"].values(), key=lambda a: a.id):
        gc = f"em::social::gen::Gesture::{ident(a.id)}"
        for _ in range(45):                              # plain
            params, parties, vals, pidx = build(a, 0.75)
            ai = pick_party(rng, 0.5)
            v = g.check_gesture(a.id, params, party_ref(ai), parties)
            emit(gc, vals, pidx, ai, False, v.code, a)
        for _ in range(30):                              # executed: the model's own output, params required
            params, parties, vals, pidx = build(a, 0.9)
            ai = pick_party(rng, 0.5)
            v = g.check_gesture(a.id, params, party_ref(ai), parties, executed=True)
            emit(gc, vals, pidx, ai, True, v.code, a)
        enum_idx = [i for i, p in enumerate(a.params) if p.type == "enum"]
        other_idx = [i for i, p in enumerate(a.params) if p.type != "enum"]
        for n in range(8):                               # invalid values (they win over everything else)
            params, parties, vals, pidx = build(a, 0.8)
            ai = pick_party(rng, 0.5)
            executed = n % 2 == 1
            kind = rng.choice(["enum_n", "enum_far", "enum_neg", "other_one", "other_neg", "extra"])
            if kind.startswith("enum") and enum_idx:
                i = rng.choice(enum_idx); p = a.params[i]
                vals[i] = {"enum_n": len(ORDERS.param_values(a.id, p)), "enum_far": 100, "enum_neg": -2}[kind]
                params[p.name] = "__invalid__"
                v = g.check_gesture(a.id, params, party_ref(ai), parties, executed=executed)
                assert v.code == "invalid_value", (a.id, p.name)
                emit(gc, vals, pidx, ai, executed, v.code, a)
            elif kind.startswith("other") and other_idx:
                i = rng.choice(other_idx)
                vals[i] = 1 if kind == "other_one" else -3
                emit(gc, vals, pidx, ai, executed, "invalid_value")          # no Python equivalent (see header)
            elif len(a.params) < 6:
                vals[len(a.params)] = rng.choice([0, 1, 5])
                params["__no_such_param__"] = "x"
                v = g.check_gesture(a.id, params, party_ref(ai), parties, executed=executed)
                assert v.code == "invalid_value"
                emit(gc, vals, pidx, ai, executed, v.code, a)
    for _ in range(5):                                   # a gesture that is not in the catalogue
        assert g.check_gesture("no_such_gesture", {}, None).code == "unknown_gesture"
        emit("em::social::gen::Gesture::kCount", [-1] * 6, [-1] * 6, -1, False, "unknown_gesture")
    L.append("};")

# ---------------------------------------------------------------------------------------------- speech (T14)
# Records cited by the contents: ref -> bare proposition. INVALID ones are copies that are not valid propositions
# (the governor must refuse them as unexpanded); MISSING refs have no copy at all.
RECORDS = {
    "b:1": "(dead @E1)", "b:2": "(owns me silver_coin:3)", "b:3": "(did @E1 touch @E2 (how gentle))",
    "b:4": "(did @E1 touch @E2 (how romantic))", "b:5": "(did @E1 touch @E2 (how intimate))",
    "b:6": "(link @E1 spouse @E2)", "b:7": "(wants @E1 (did @E1 touch @E3 (how romantic)))",
    "b:8": "(believes @E2 b:4)", "b:9": "(believes @E2 b:8)", "b:10": "(believes @E2 b:9)", "b:11": "(believes @E2 b:10)",
    "b:12": "(knows @E1 b:12)", "b:13": "(assert (dead @E1))", "b:14": "(state @E1 attracted_to 3)",
    "b:15": "(link @E1 lover @E3)", "b:16": "(believes @E2 b:3)", "b:17": "(believes @E2 b:16)", "b:18": "(knows @E1 b:6)",
    "m:1": "(did @E1 touch @E2 (how romantic))", "m:2": "(did @E1 touch @E2 (how gentle))",
    "m:3": "(did @E1 give silver_coin:3 (to @E2))", "m:4": "(did you touch me (how intimate))",
    "m:5": "(did n:3 touch n:12 (how romantic))", "m:6": "(did @G1 touch @E2 (how romantic))",
    "m:7": "(did @E1 go @L1)", "m:8": "(did @E1 speak (to @E2) (says b:4))",
    "g:1": "(dead @E3)", "g:2": "(did me touch @E2 (how romantic))", "g:3": "(wants me b:4)", "g:4": "(owns me silver_coin:3)",
    "h:2": "(did @E3 speak (to @E1) (says b:4))", "h:3": "(did @E3 speak (to @E1) (says b:3))", "h:4": "m:1",
    "q:1": "(did @E1 give silver_coin:3 (to @E2))", "q:2": "(did @E1 touch @E2 (how romantic))",
    "c:1": "(owes me @E2 b:3)", "c:2": "(owes me @E2 b:4)",
    "@V1": "(did @E1 touch @E2 (how romantic))", "@V2": "(did @E1 go @L1)", "@V3": "(past (did @E1 touch @E2 (how intimate)))",
}
INVALID = {"b:13"}
MISSING = ["b:99", "m:99", "g:99", "h:9", "q:9", "c:9", "@V9"]
SYMS = ["@E1", "@E2", "@E3", "@G1", "n:3", "n:12", "you", "us", "someone", "@T1", "@L1"]
INTIMATE_WORDS = ["romantic", "intimate", "spouse", "lover", "betrothed", "former_spouse", "adultery", "attracted_to"]
TEMPLATES = [
    "(assert (did {A} touch {B} (how romantic)))", "(assert (did {A} touch {B} (how intimate)))",
    "(assert (did {A} touch {B} (how gentle)))", "(offer (did {A} touch {B} (how romantic)))",
    "(ask (did {A} touch {B} (how intimate)))", "(assert (past (did {A} touch {B} (how romantic))))",
    "(assert (link {A} spouse {B}))", "(assert (link {A} lover {B}))", "(assert (link {A} betrothed {B}))",
    "(assert (link {A} former_spouse {B}))", "(assert (link {A} friend {B}))", "(assert (link {A} parent {B}))",
    "(assert (qualifies m:1 adultery))", "(assert (qualifies m:2 adultery))", "(assert (qualifies m:99 adultery))",
    "(assert (qualifies m:5 adultery))", "(assert (qualifies m:6 adultery))", "(assert (qualifies m:4 adultery))",
    "(assert (qualifies @V1 adultery))", "(assert (qualifies @V2 adultery))", "(assert (qualifies h:2 adultery))",
    "(assert (state {A} attracted_to 3))", "(assert (state {A} pain 3))",
    "(assert (wants {A} (did {A} touch {B} (how romantic))))", "(assert (wants {A} (dead {B})))",
    "(assert (believes {A} b:{N}))", "(assert (knows {A} b:{N}))", "(assert (knows {A} m:{M}))",
    "(assert (did {A} speak (to {B}) (says b:{N})))", "(assert (did {A} speak (to {B}) (says (that b:{N}))))",
    "(assert (did {A} speak (to {B}) (says (did {A} touch {B} (how romantic)))))",
    "(assert (did {A} speak (to {B}) (says (link {A} lover {B}))))",
    "(assert (did {A} speak (to {B}) (says (dead {B}))))", "(assert (did {A} speak (to {B}) (says m:{M})))",
    "(assert (did {A} touch {B} (how romantic) (to {A})))", "(assert (did {A} touch (described d_woman) (how romantic)))",
    "(assert (did {A} touch (of 2 @G1) (how romantic)))", "(assert (did {A} touch {B}))", "(assert (did {A} give silver_coin:3 (to {B})))",
    "(assert (did {A} touch {B} (how gentle) (with {B})))", "(assert (dead (described d_woman)))",
    "(assert (owes {A} {B} b:{N}))", "(assert (owes {A} {B} c:{C}))", "(assert (and b:{N} (dead {A})))",
    "(assert (norm forbidden (did anyone touch someone (how romantic))))", "(assert (b:{N}))",
    "(assert (caused h:2 (dead {A})))", "(assert (believes {A} (that b:{N})))",
    "b:{N}", "m:{M}", "g:{G}", "h:{H}", "q:{Q}", "c:{C}", "@V{V}", "(that b:{N})", "(wants {A} g:{G})", "(wants {A} (that q:{Q}))",
    "(link {A} spouse {B})", "(did {A} touch {B} (how romantic))", "(did {A} touch {B} (how intimate))",
    "(state {A} attracted_to 3)", "(believes {A} b:{N})", "(owes {A} {B} c:{C})", "(knows {A} h:{H})", "(dead {A})",
]
REF_POOL = ["@E1", "@E2", "@E3", "@G1", "n:3", "n:12", "me", "you", "us", "someone", "everyone", "@T1", "@L1", "here",
            "(described d_woman)", "(of 2 @G1)", "silver_coin:3", "knife", "@E4", "n:99", "3"]
HAND_SPEECH = ["", "(", "(assert", "(assert (dead @E1)) extra", "hello", "(assert (no_such_word @E1))",
               "(assert (did me touch you (how romantic)", "(assert (link spouse))", "(assert (dead))"]


def speech_words(cat, v) -> list:
    """(word, flags): 1 = intimate in a node (concept, variable, interpretation, intimate manner), 2 = sensitive for
    the hearers (intimate manner, intimate gesture, intimate variable). Only the words with a flag."""
    out = {}
    for w in set(cat["concept"]) | set(cat["variable"]) | set(cat["interpretation"]) | set(cat["action"]) | v.manner_intimate:
        c, var, i, a = cat["concept"].get(w), cat["variable"].get(w), cat["interpretation"].get(w), cat["action"].get(w)
        f = 0
        if (c is not None and c.intimate) or (var is not None and var.intimate) or (i is not None and i.intimate) or w in v.manner_intimate:
            f |= 1
        if w in v.manner_intimate or (a is not None and a.intimate) or (var is not None and var.intimate):
            f |= 2
        if f:
            out[w] = f
    return sorted(out.items())


def emit_words(cat, v) -> None:
    L = ["// GENERATED by catalogue/tools/governor_vectors.py from the Python governor (oracle). Do not edit.",
         "// Words D10 looks at in a speech: 1 = intimate in a node (concept, variable, interpretation, manner),",
         "// 2 = an intimate act or desire (intimate manner, gesture or variable): never said to a possible minor.",
         "// Sorted by word (byte order), searched by binary search.",
         "constexpr WordFlag kWordFlags[] = {"]
    for w, f in speech_words(cat, v):
        L.append(f'  {{"{w}", {f}}},')
    L.append("};")
    OUT_WORDS.write_text("\n".join(L) + "\n", encoding="utf-8")


def text_pool(cat, v, rng) -> list:
    """[(text, bare)]: story texts, templates over many pointers, substitutions of intimate words, a few invalid ones."""
    import language_vectors as LV
    from probes import BARE, FULL
    seeds = []
    for s in cat["story"].values():
        seeds += [(u, False) for u in s.utterances]
        for line in s.trace:
            parts = [x.strip() for x in line.split("|", 2)]
            if len(parts) == 3 and parts[1] in BARE:
                seeds.append((parts[2], True))
            elif len(parts) == 3 and parts[1] in FULL:
                seeds.append((parts[2], False))
    gen = LV.Gen(cat, v, rng, allow_intimate=True)
    for _ in range(500):
        seeds.append((LV.unparse(gen.utterance()), False))
        seeds.append((LV.unparse(gen.prop(0)), True))
    pool = list(seeds)
    for t in TEMPLATES:
        for _ in range(12):
            a, b = rng.choice(REF_POOL), rng.choice(REF_POOL)
            ids = {"N": rng.choice([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 99]),
                   "M": rng.randint(1, 8) if rng.random() < 0.9 else 99, "G": rng.randint(1, 4), "H": rng.choice([2, 3, 4, 9]),
                   "Q": rng.choice([1, 2, 9]), "C": rng.choice([1, 2, 9]), "V": rng.choice([1, 2, 3, 9])}
            txt = t.format(A=a, B=b, **ids)
            pool.append((txt, not txt.startswith(("(assert", "(offer", "(ask"))))
    pool += [(h, False) for h in HAND_SPEECH]
    # substitutions: a symbol of a valid text becomes an intimate word, a pointer, a description or another cite
    toks = re.compile(r"[^()\s]+")
    for text, bare in list(seeds):
        for _ in range(2):
            ms = list(toks.finditer(text))
            if not ms:
                continue
            m = rng.choice(ms)
            repl = rng.choice(INTIMATE_WORDS + REF_POOL[:14] + ["b:4", "m:1", "b:8", "b:99", "@V1", "h:2"])
            pool.append((text[:m.start()] + repl + text[m.end():], bare))
    seen, out = set(), []
    for t in pool:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def gen_speech(cat, g, rng, counts):
    v = g.vocab
    emit_words(cat, v)
    lib = {}
    for ref, txt in RECORDS.items():
        e = language.Expression(txt, v, bare=True)
        assert e.ok == (ref not in INVALID), (ref, txt, e.problems)
        lib[ref] = e
    pool = text_pool(cat, v, rng)
    exprs = {}
    valid = 0
    for text, bare in pool:
        e = language.Expression(text, v, bare=bare)
        exprs[(text, bare)] = e
        valid += e.ok
    assert len(pool) > 2000 and valid > 1000, (len(pool), valid)
    # keep every valid text reachable, and the invalid ones in small number
    good = [k for k in pool if exprs[k].ok]
    bad = [k for k in pool if not exprs[k].ok]
    ops = ["said", "unsaid", "goal", "belief", "memory", "agreement", "plan", "bad_kind"]
    L = ["// GENERATED by catalogue/tools/governor_vectors.py from the Python governor (oracle). Do not edit.",
         "// Speech and record vectors (T14). The palette is that of governor_vectors.inc (party index, -1 = none).",
         "struct SpeechRecord { const char* ref; const char* text; };", "static constexpr SpeechRecord kSpeechRecords[] = {"]
    for ref, txt in RECORDS.items():
        L.append(f'  {{"{ref}", "{txt}"}},')
    L.append("};")
    L.append("struct SpeechBinding { const char* symbol; signed char party; };")
    L.append("// op: 0 said utterance, 1 unsaid utterance, 2..6 record goal/belief/memory/agreement/plan, 7 an unknown record kind")
    L.append("struct SpeechCase { const char* text; bool bare; signed char op; signed char speaker; signed char n_hearers;"
             " signed char hearers[4]; signed char n_parties; SpeechBinding parties[5]; bool expand; em::social::Reason reason; };")
    L.append("static constexpr SpeechCase kSpeechCases[] = {")
    for n in range(SPEECH_CASES):
        text, bare = rng.choice(bad) if rng.random() < 0.03 else rng.choice(good)
        e = exprs[(text, bare)]
        op = rng.choices(range(8), weights=[55, 8, 6, 8, 5, 5, 5, 1] if not bare else [30, 6, 12, 16, 10, 12, 12, 2])[0]
        speaker = pick_party(rng, 0.7)
        nh = rng.choice([0, 1, 1, 1, 2, 2, 3, 4])
        hearers = [pick_party(rng, 0.55) for _ in range(nh)]
        np_ = rng.randint(0, 5)
        bound = [(sym, pick_party(rng, 0.6)) for sym in rng.sample(SYMS, np_)]
        if rng.random() < 0.5:                         # the usual cast: @E1 and @E2 are adults the speaker knows
            bound = [b for b in bound if b[0] not in ("@E1", "@E2")] + [("@E1", rng.choice(ADULTS)), ("@E2", rng.choice(ADULTS))]
            bound = bound[:5]
        use_expand = rng.random() < 0.88
        expand = (lambda ref: lib.get(ref)) if use_expand else None
        parties = {sym: party_ref(i) for sym, i in bound}     # None: "malformed party", an UNKNOWN person
        addressed = [party_ref(i) for i in hearers]
        sp = party_ref(speaker)
        if op < 2:
            r = g.check_utterance(e, sp, parties, addressees=addressed, expand=expand, said=(op == 0))
        elif op < 7:
            r = g.check_record(["goal", "belief", "memory", "agreement", "plan"][op - 2], e, sp, parties, expand=expand)
        else:
            r = g.check_record("no_such_kind", e, sp, parties, expand=expand)
        counts["speech"][r.code] += 1
        hs = ", ".join(map(str, hearers + [-1] * (4 - len(hearers))))
        bs = ", ".join(f'{{"{s}", {i}}}' for s, i in bound[:5]) or '{"", -1}'
        t = text.replace("\\", "\\\\").replace('"', '\\"')
        L.append(f'  {{"{t}", {str(bare).lower()}, {op}, {speaker}, {nh}, {{{hs}}}, {len(bound[:5])}, {{{bs}}}, '
                 f'{str(use_expand).lower()}, {reason(r.code)}}},')
    L.append("};")
    OUT_SPEECH.write_text("\n".join(L) + "\n", encoding="utf-8")


def main():
    global ORDERS
    cat = Catalogue.load()
    ORDERS = Orders(cat)
    g = Governor(cat)
    rng = random.Random(SEED)
    counts = {k: Counter() for k in ("write", "writes", "gesture", "speech")}
    L = ["// GENERATED by catalogue/tools/governor_vectors.py from the Python governor (oracle). Do not edit.",
         "// Party palette: {real, believed, apparent (tenths of years, floored, -1 unknown), resolved, person, perceived} and the",
         "// same ages in YEARS (what Party::from_years must turn into those tenths; -1 = none, NaN = non-finite).",
         "static constexpr em::social::Party kPalette[] = {"]
    for p in PALETTE:
        L.append(f"  {{{cpp_age(p.real_age)}, {cpp_age(p.believed_age)}, {cpp_age(p.apparent_age)}, "
                 f"{str(p.resolved).lower()}, {str(p.person).lower()}, {str(p.perceived).lower()}}},")
    L.append("};")
    L.append("static constexpr double kPaletteYears[][3] = {")
    for p in PALETTE:
        L.append(f"  {{{cpp_double(p.real_age)}, {cpp_double(p.believed_age)}, {cpp_double(p.apparent_age)}}},")
    L.append("};")
    gen_writes(cat, g, rng, L, counts)
    gen_check_writes(g, rng, L, counts)
    gen_gestures(cat, g, rng, L, counts)
    gen_speech(cat, g, random.Random(SEED + 14), counts)
    # every reason the C++ governor can give must be covered by at least one vector
    covered = counts["write"] + counts["writes"] + counts["gesture"] + counts["speech"]
    expected = {"ok", "jump", "step", "slow", "clipped", "unknown_variable", "engine_owned", "structured",
                "unknown_gesture", "invalid_value", "d10_intimate", "d10_value", "d10_person", "d10_whitelist",
                "duplicate", "too_many_writes", "d10_hearer", "unexpanded", "invalid_value"}
    missing = sorted(expected - set(covered))
    if missing:
        raise SystemExit(f"no vector for the reasons: {missing}")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"écrit {OUT}")
    for k in ("write", "writes", "gesture", "speech"):
        print(f"  {k:8s} {sum(counts[k].values()):5d}  " + ", ".join(f"{c}={n}" for c, n in sorted(counts[k].items())))


if __name__ == "__main__":
    main()
