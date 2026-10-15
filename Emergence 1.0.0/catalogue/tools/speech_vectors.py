"""speech_vectors.py - shared test vectors of the SpeechRouter (T24): the Python oracle decides, the C++ must agree.

    python3 catalogue/tools/speech_vectors.py [--check]   # --check compares with the file and writes nothing; writes engine/social/tests/speech_vectors.inc  (about 1 MB, reproducible)

Oracle pieces: shapes.Perspective (the I/YOU swap of ELIZA), governor.Governor._unfold (the frozen copy of a cited
record, the very code that governor.check_utterance uses to judge) and language.Expression (the validity of the
hearer's version). Deterministic: fixed seed, sorted iteration, no clock.
  * PerspectiveCase: text, speaker key -> the swapped text (empty = the oracle raises: the key is not a pointer);
  * FreezeCase: an utterance the governor ALLOWS (adult speaker and hearers, so no intimate act is ever offered to a
    possible minor), the speaker's records, the translation of the speaker's pointers into the hearer's, the group
    that freezes `us`, the identity missed (`someone`) -> status (0 ok, 1 unexpanded, 2 untranslated, 3 invalid for the
    hearer) and the hearer's text;
  * MisheardCase: the identities (@E @G n:) a hearer may fail to catch, in order.
"""
from __future__ import annotations

import random
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tools"))
from schema import Catalogue  # noqa: E402
import language  # noqa: E402
from language import Node  # noqa: E402
from governor import Governor, CITE  # noqa: E402
from shapes import Perspective, Pattern  # noqa: E402
import governor_vectors as GV  # noqa: E402

OUT = ROOT.parent / "engine" / "social" / "tests" / "speech_vectors.inc"
SEED = 20261015
N_FREEZE = 3500
N_PERSP = 800
IDENT = re.compile(r"^(@E|@G)[0-9]+$|^n:[0-9]+$")
TRANSLATABLE = re.compile(r"^(@E|@G|@T|@L|@V)[0-9]+$")
KEYS = ["@E1", "@E7", "@E12", "@G3", "@T2", "@L4", "n:5", "me", "you", "someone", "b:3", "@PLACE", ""]
HEAR_KEYS = ["@E1", "@E7", "@E12", "@E40"]
KINDS = ["knife", "forest", "mill", "bread"]


class Fail(Exception):
    pass


def unfold(node, expand, depth):
    """governor.py _check_node: a cite is replaced by the content of its frozen copy, `(that X)` by the content of X."""
    if isinstance(node, str) and CITE.match(node):
        inner = Governor._unfold(node, expand, depth)
        if inner is None:
            raise Fail
        return unfold(inner.root, expand, depth + 1)
    if not isinstance(node, Node):
        return node
    if node.head == "that":
        if not node.args:
            raise Fail
        return unfold(node.args[0], expand, depth)
    return Node(node.head, [unfold(a, expand, depth) for a in node.args])


def freeze(text, vocab, expand, key, tmap, us_key, miss):
    e = language.Expression(text, vocab)
    try:
        root = unfold(e.root, expand, 0)
    except Fail:
        return 1, ""
    counter = [0]
    bad = [False]

    def leaf(s):
        if IDENT.match(s):
            i = counter[0]; counter[0] += 1
            if i == miss:
                return "someone"
        if s == "me":
            return key
        if s == "you":
            return "me"
        if s == "us":
            if us_key is None:
                return "us"
            if us_key == "":
                bad[0] = True
                return s
            return us_key
        if TRANSLATABLE.match(s):
            t = tmap.get(s)
            if t is None:
                bad[0] = True
                return s
            return t
        return s

    def walk(n):
        if isinstance(n, Node):
            return Node(n.head, [walk(a) for a in n.args])
        return leaf(n)

    out = walk(root)
    if bad[0]:
        return 2, ""
    t = Pattern._text(out)
    r = language.Expression(t, vocab)
    return (0, Pattern._text(r.root)) if r.ok else (3, "")


def c_str(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def main(check: bool = False) -> int:
    cat = Catalogue.load()
    g = Governor(cat)
    vocab = g.vocab
    rng = random.Random(SEED)
    lib = {}
    for ref, txt in GV.RECORDS.items():
        lib[ref] = language.Expression(txt, vocab, bare=True)
    pool = GV.text_pool(cat, vocab, random.Random(SEED + 1))
    texts = sorted({t for t, bare in pool if not bare})
    adult = GV.PALETTE[0]
    adults = {s: GV.PALETTE[0] for s in ("@E1", "@E2", "@E3", "@E4")}
    good = []
    for t in texts:
        e = language.Expression(t, vocab)
        if not e.ok:
            continue
        v = g.check_utterance(e, adult, dict(adults), addressees=[adult], expand=lambda r: lib.get(r), said=True)
        if v.allowed:
            good.append(t)
    # cited and relayed speeches (a rumour is spoken by citing what one believes)
    extra = []
    for ref in ["b:1", "b:2", "b:3", "b:6", "m:2", "m:3", "m:7", "g:1", "g:4", "h:3", "q:1", "b:8", "b:99", "c:1"]:
        extra += [f"(assert {ref})", f"(assert (that {ref}))", f"(assert (believes @E2 (that {ref})))", f"(offer {ref})",
                  f"(assert (did me speak (to you) (says (that {ref}))))"]
    extra += ["(offer (future (caused us (dead @E4))))", "(request (intends us (dead @E3)))", "(request (not (did you speak ...)))"[:0] or
              "(request (not (future (did you speak (to @E3)))))", "(assert (at @E3 @L1))", "(assert (owns @E1 @T1))",
              "(offer (future (did me give silver_coin:3 (to you))))", "(assert (named @E1 n:3))", "(ask (dead @E1))",
              "(assert (dead (described d_woman)))", "(assert (at @E1 @PLACE))"]
    for t in extra:
        e = language.Expression(t, vocab)
        if e.ok and g.check_utterance(e, adult, dict(adults), addressees=[adult], expand=lambda r: lib.get(r), said=True).allowed:
            good.append(t)
    assert len(good) > 300, len(good)

    L = ["// GENERATED by catalogue/tools/speech_vectors.py from the Python oracle (shapes.Perspective, governor._unfold, language). Do not edit.",
         "struct PerspectiveCase { const char* text; const char* key; const char* expected; };",
         "struct MapEntry { const char* from; const char* to; };",
         "// status: 0 ok, 1 unexpanded, 2 untranslated, 3 invalid for the hearer. us_key: null = `us` stays, \"\" = untranslatable.",
         "struct FreezeCase { const char* text; const char* key; const char* us_key; int miss; bool expand; int n_map; MapEntry map[8]; int status; const char* expected; };",
         "struct MisheardCase { const char* text; int n; const char* ids[8]; };",
         "static constexpr const char* kSpeechLibrary[][2] = {"]
    for ref, txt in GV.RECORDS.items():
        L.append(f"  {{{c_str(ref)}, {c_str(txt)}}},")
    L.append("};")

    L.append("static constexpr PerspectiveCase kPerspectiveCases[] = {")
    for _ in range(N_PERSP):
        t = rng.choice(good)
        key = rng.choice(KEYS)
        try:
            exp = Perspective(key).text(t)
        except ValueError:
            exp = ""
        L.append(f"  {{{c_str(t)}, {c_str(key)}, {c_str(exp)}}},")
    L.append("};")

    L.append("static constexpr FreezeCase kFreezeCases[] = {")
    stats = {0: 0, 1: 0, 2: 0, 3: 0}
    for _ in range(N_FREEZE):
        t = rng.choice(good)
        key = rng.choice(HEAR_KEYS)
        syms = sorted({s for s in re.findall(r"[^\s()]+", t) if TRANSLATABLE.match(s)} | {"@E1", "@E2", "@E3", "@E4", "@G1", "@T1", "@L1"})
        tmap = {}
        for s in syms:
            r = rng.random()
            if r < 0.07:
                continue                                  # untranslatable
            if s.startswith("@T") or s.startswith("@L"):
                tmap[s] = rng.choice(KINDS)
            elif s.startswith("@G"):
                tmap[s] = f"@G{rng.randint(20, 29)}"
            else:
                tmap[s] = f"@E{rng.randint(20, 59)}"
        use_expand = rng.random() < 0.9
        us_key = rng.choice([None, None, f"@G{rng.randint(60, 69)}", ""])
        cand = [s for s in re.findall(r"[^\s()]+", t) if IDENT.match(s)]
        miss = rng.choice([-1, -1, 0, 1, 2, 5]) if True else -1
        expand = (lambda r: lib.get(r)) if use_expand else None
        status, exp = freeze(t, vocab, expand, key, tmap, us_key, miss)
        stats[status] += 1
        ents = list(tmap.items())[:8]
        # a map larger than 8 entries would be cut: keep the case honest by recomputing with the cut map
        if len(tmap) > 8:
            tmap = dict(ents)
            status, exp = freeze(t, vocab, expand, key, tmap, us_key, miss)
        ms = ", ".join(f"{{{c_str(a)}, {c_str(b)}}}" for a, b in ents) or '{"", ""}'
        uk = "nullptr" if us_key is None else c_str(us_key)
        L.append(f"  {{{c_str(t)}, {c_str(key)}, {uk}, {miss}, {str(use_expand).lower()}, {len(ents)}, {{{ms}}}, {status}, {c_str(exp)}}},")
    L.append("};")

    L.append("static constexpr MisheardCase kMisheardCases[] = {")
    for t in good[:400]:
        e = language.Expression(t, vocab)
        try:
            root = unfold(e.root, lambda r: lib.get(r), 0)
        except Fail:
            continue
        syms = [s for s in Pattern._text(root).replace("(", " ").replace(")", " ").split() if IDENT.match(s)][:8]
        L.append(f"  {{{c_str(t)}, {len(syms)}, {{{', '.join(c_str(s) for s in syms) or chr(34)*2}}}}},")
    L.append("};")
    content = "\n".join(L) + "\n"
    if check:
        same = OUT.exists() and OUT.read_text(encoding="utf-8") == content
        print(f"{OUT.name}: {'identical to the oracle' if same else 'DIFFERS from the oracle (regenerate without --check)'}")
        return 0 if same else 1
    OUT.write_text(content, encoding="utf-8")
    print(f"{OUT.name}: {OUT.stat().st_size} bytes; {len(good)} allowed texts; freeze statuses {stats}")
    return 0


if __name__ == "__main__":
    sys.exit(main(check="--check" in sys.argv[1:]))
