"""make_corpus.py - the corpus shared by the Python oracle and the C++ tokenizer (parity tests).

    python3 engine/social/tokenizer/make_corpus.py --out build/tok2_corpus.jsonl [--n 5000] [--seed 1] [--mutants 3000]
    python3 engine/social/tokenizer/make_corpus.py --pin       rewrite engine/social/tokenizer/tests/corpus.pin
    python3 engine/social/tokenizer/make_corpus.py --out F --reuse   skip when F is already up to date (CTest)

Each line is {name, context, expect} like ai/tok2/golden/cases.jsonl: `n` sampler situations (seed `seed`, index 0..n-1)
and `mutants` copies of the first situations with one deliberate fault each (a value out of range, a pointer to the
wrong kind, an unknown field, a bad proposition...). `expect` is what the ORACLE says: {digest, n, ghosts} or {error}.
Reproducible: the pin (seed, counts, crc32 of every expectation) is committed (tests/corpus.pin, < 1 KB); the 120 MB
corpus itself is rebuilt on demand. Read-only on ai/.
"""
from __future__ import annotations

import argparse
import copy
import json
import multiprocessing as mp
import random
import sys
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PIN = HERE / "tests" / "corpus.pin"
sys.path.insert(0, str(ROOT / "ai"))

_STATE = {}


def _setup():
    if "s" not in _STATE:
        from situations.sampler import SituationSampler
        from tok2 import DecisionContext, TokenError
        _STATE["s"] = SituationSampler(_STATE.get("seed", 1))
        _STATE["DC"], _STATE["TE"] = DecisionContext, TokenError
    return _STATE["s"]


def _init(seed):
    _STATE["seed"] = seed
    _setup()


def _expect(ctx_dict: dict) -> dict:
    s, DC, TE = _setup(), _STATE["DC"], _STATE["TE"]
    try:
        ctx = DC.loads(json.dumps(ctx_dict, separators=(",", ":")), s.tokenizer)
        enc = s.tokenizer.encode(ctx)
        return {"digest": f"{enc.digest():08x}", "n": enc.n, "ghosts": list(enc.ghosts)}
    except TE:
        return {"error": "TokenError"}


def mutate(ctx: dict, rng: random.Random) -> tuple[str, dict]:
    c = copy.deepcopy(ctx)
    recs = c["records"]
    kind = rng.choice(["range", "type", "unknown_field", "bad_prop", "ptr_kind", "ptr_unknown", "drop_self", "dup_key",
                       "bad_key", "bool_num", "bag_long", "absent_dist", "enum_bad", "empty_vec", "count_big", "known_drop",
                       "name_flood", "prop_selfcite", "ghost_flood"])
    r = rng.choice(recs)
    nums = [k for k, v in r["fields"].items() if isinstance(v, (int, float)) and not isinstance(v, bool)]
    ptrs = [k for k, v in r["fields"].items() if isinstance(v, str) and (v[:1] == "@" or v[1:2] == ":") and k != "prop"]
    if kind == "range" and nums:
        k = rng.choice(nums); r["fields"][k] = rng.choice([-1e8, 11, 10.0000000001, -1e-12, 1e9, 10.000001, -0.0, 1e7])
    elif kind == "type" and r["fields"]:
        k = rng.choice(list(r["fields"])); r["fields"][k] = rng.choice(["x", [], {}, True, None, [1], {"a": 1}])
    elif kind == "unknown_field":
        r["fields"]["zzz_unknown"] = 1
    elif kind == "bad_prop":
        for rr in recs:
            if "prop" in rr["fields"]:
                rr["fields"]["prop"] = rng.choice(["(owns me", "(nosuchword me)", "", "(owns me @T1) x", "(loves me you)", "((a))",
                                                   "(owns me @T01)", "(owns me silver_coin:01)", "(owns me silver_coin:99999999)"])
                break
    elif kind == "ptr_kind" and ptrs:
        k = rng.choice(ptrs); r["fields"][k] = rng.choice(["me", "wake", "@PLACE", "b:1", "@G1", "@L1"])
    elif kind == "ptr_unknown" and ptrs:
        r["fields"][rng.choice(ptrs)] = "@E999"
    elif kind == "drop_self":
        c["records"] = [x for x in recs if x["type"] != rng.choice(["SELF", "PLACE"])]
    elif kind == "dup_key":
        recs.append(copy.deepcopy(r))
    elif kind == "bad_key":
        r["key"] = rng.choice(["@E07", "@E", "x:1", "@E1234567890123", "b:-1"])
    elif kind == "bool_num" and nums:
        r["fields"][rng.choice(nums)] = True
    elif kind == "bag_long":
        for rr in recs:
            for k, v in rr["fields"].items():
                if isinstance(v, list) and v and all(isinstance(x, str) and ":" not in x and x[:1] != "@" for x in v):
                    rr["fields"][k] = v * 4
    elif kind == "absent_dist":
        for rr in recs:
            if rr["type"] == "ENTITY":
                rr["fields"]["present"] = False; rr["fields"]["dist"] = 3.0
                break
    elif kind == "enum_bad":
        for rr in recs:
            if rr["type"] == "SELF":
                rr["fields"]["posture"] = "levitating"
    elif kind == "empty_vec":
        for rr in recs:
            if rr["type"] == "SELF":
                rr["fields"]["time"] = []; break
    elif kind == "count_big":
        for rr in recs:
            if "prop" in rr["fields"]:
                rr["fields"]["prop"] = "(owns me silver_coin:10000001)"; break
    elif kind == "known_drop":
        if c["known_keys"]:
            c["known_keys"] = c["known_keys"][: len(c["known_keys"]) // 2]
    elif kind == "name_flood":
        for rr in recs:
            if rr["type"] == "BELIEF":
                rr["fields"]["prop"] = "(knows n:%d n:%d)" % (rng.randint(1, 999), rng.randint(1, 999)); break
    elif kind == "prop_selfcite":
        for rr in recs:
            if "prop" in rr["fields"] and rr["key"][:2] in ("b:", "m:", "g:"):
                rr["fields"]["prop"] = rr["key"]; break
    elif kind == "ghost_flood":
        c["known_keys"] = sorted(set(c["known_keys"]) | {f"@E{900 + i}" for i in range(40)})
        for rr in recs:
            if rr["type"] == "BELIEF":
                rr["fields"]["informant"] = "@E900"; break
    return kind, c


def _one(args):
    seed, i, mutants = args
    s = _setup()
    sit = s.sample(i)
    ctx = json.loads(sit.context.dumps(s.tokenizer))
    out = [{"name": f"sit_{seed}_{i}", "context": ctx, "expect": _expect(ctx)}]
    rng = random.Random(f"mut:{seed}:{i}")
    for m in range(mutants):
        kind, mc = mutate(ctx, rng)
        out.append({"name": f"mut_{seed}_{i}_{m}_{kind}", "context": mc, "expect": _expect(mc)})
    return [json.dumps(o, separators=(",", ":"), ensure_ascii=False) for o in out]


def build(seed: int, n: int, mutants: int, jobs: int) -> list[str]:
    per = max(1, mutants // max(1, min(n, mutants)))      # mutants per situation (spread on the first situations)
    work = [(seed, i, per if i * per < mutants else 0) for i in range(n)]
    with mp.Pool(jobs, initializer=_init, initargs=(seed,)) as pool:
        chunks = pool.map(_one, work, chunksize=20)
    return [l for ch in chunks for l in ch]


def stamp() -> str:
    parts = []
    for d in (ROOT / "ai" / "tok2", ROOT / "ai" / "situations", ROOT / "catalogue" / "generated"):
        for p in sorted(d.rglob("*")):
            if p.suffix in (".py", ".json") and "__pycache__" not in p.parts and "tests" not in p.parts:
                st = p.stat()
                parts.append(f"{p.relative_to(ROOT)}:{st.st_size}:{int(st.st_mtime)}")
    parts.append(Path(__file__).read_text())
    return f"{zlib.crc32(chr(10).join(parts).encode()):08x}"


def pin_of(lines: list[str], seed, n, mutants) -> dict:
    crc = 0
    for l in lines:
        o = json.loads(l)
        crc = zlib.crc32(f"{o['name']}={json.dumps(o['expect'], sort_keys=True)}\n".encode(), crc)
    return {"seed": seed, "situations": n, "mutants": mutants, "lines": len(lines), "expectations_crc32": f"{crc:08x}"}


def compare_pin(pin: dict) -> int:
    want = json.loads(PIN.read_text())
    if want != pin:
        print(f"PIN STALE (sampler or oracle changed): committed {want}, live {pin}; "
              "re-pin with make_corpus.py --pin once the sampler is stable")
        return 1
    print("pin matches")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out"); ap.add_argument("--n", type=int, default=5000); ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--mutants", type=int, default=3000); ap.add_argument("--jobs", type=int, default=max(1, (mp.cpu_count() or 2) - 1))
    ap.add_argument("--reuse", action="store_true"); ap.add_argument("--pin", action="store_true")
    ap.add_argument("--check-pin", action="store_true")
    a = ap.parse_args(argv)
    if a.out and a.reuse:
        out = Path(a.out); st = Path(str(out) + ".stamp")
        if out.exists() and st.exists() and st.read_text() == f"{stamp()} {a.seed} {a.n} {a.mutants}":
            print(f"corpus up to date: {out}")
            if a.check_pin:
                return compare_pin(pin_of(out.read_text(encoding="utf-8").splitlines(), a.seed, a.n, a.mutants))
            return 0
    lines = build(a.seed, a.n, a.mutants, a.jobs)
    pin = pin_of(lines, a.seed, a.n, a.mutants)
    if a.out:
        Path(a.out).write_text("\n".join(lines) + "\n", encoding="utf-8")
        Path(str(a.out) + ".stamp").write_text(f"{stamp()} {a.seed} {a.n} {a.mutants}")
        print(f"{len(lines)} cases -> {a.out}")
    if a.pin:
        PIN.write_text(json.dumps(pin, indent=1) + "\n"); print(f"pin written: {pin}")
    if a.check_pin:
        return compare_pin(pin)
    return 0


if __name__ == "__main__":
    sys.exit(main())
