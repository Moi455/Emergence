"""make_context_corpus.py - the corpus of the ContextBuilder parity test (T28b).

    python3 engine/social/tokenizer/make_context_corpus.py --out build/context_corpus.jsonl [--n 3000] [--seed 1]
    python3 engine/social/tokenizer/make_context_corpus.py --out F --reuse     skip when F is already up to date (CTest)

Each line is {name, now, context, expect}: a situation of the sampler (ai/situations), QUANTISED to the grid of the NpcState
(tenths of a scale, thousandths of a unit, per-mille ratios, game seconds for the ages and deadlines, thousandths for the
components of a vector), and what the ORACLE (ai/tok2) says of that quantised context: {digest, n, ghosts}.

Why quantise. The state stores integers (docs/14 7.2): 3.77 on a charter scale is 38 tenths, an age of 0.1333 h is 480 s.
The C++ test builds an NpcState from the quantised context (a reverse loader), the ContextBuilder rebuilds the context from the
state, the Tokenizer encodes it, and the arrays must equal the oracle's for the SAME quantised context. Nothing else is changed:
keys, words, propositions, the presence of every field (known or not), the order of the records and of the lists stay as the
sampler wrote them. The quantisation error itself is measured here (largest relative change per scale) and printed.
Read-only on ai/.
"""
from __future__ import annotations

import argparse
import copy
import json
import multiprocessing as mp
import sys
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "ai"))

NOW = 100_000_000          # game seconds of the decision (the state stores absolute times)
QTY_LIMIT = 2_147_483.647  # an int32 of thousandths
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


class Grid:
    """The grid of the stored integers, per scale."""

    def __init__(self, token_types: dict):
        self.types = token_types
        self.worst = {}
        self.clamped = 0

    def snap(self, v: float, per: float, tag: str) -> float:
        q = round(v * per) / per
        e = abs(q - v) / max(abs(v), 1e-9) if abs(v) > 1e-9 else 0.0
        if e > self.worst.get(tag, (0, 0))[0]:
            self.worst[tag] = (e, v)
        return q

    def scalar(self, scale: str, v, tag: str):
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return v
        if scale in ("bipolar10", "unipolar10"):
            return self.snap(v, 10, tag)
        if scale == "ratio":
            return self.snap(v, 1000, tag)
        if scale in ("time", "time_until"):
            return self.snap(v, 3600, tag)
        if scale == "qty":
            q = self.snap(v, 1000, tag)
            if abs(q) > QTY_LIMIT:
                self.clamped += 1
                q = QTY_LIMIT if q > 0 else -QTY_LIMIT
            return q
        return v

    def vector(self, v, tag: str):
        def one(d):
            if not isinstance(d, dict):
                return d
            out = {}
            for k, x in d.items():
                if isinstance(x, bool) or not isinstance(x, (int, float)):
                    out[k] = x
                else:
                    q = self.snap(x, 1000, tag)
                    if abs(q) > QTY_LIMIT:
                        self.clamped += 1
                        q = QTY_LIMIT if q > 0 else -QTY_LIMIT
                    out[k] = q
            return out
        if isinstance(v, list):
            return [one(d) for d in v]
        return one(v)

    def record(self, rec: dict) -> None:
        spec = self.types[rec["type"]]["fields"]
        for name, v in list(rec["fields"].items()):
            sp = spec.get(name)
            if sp is None:
                continue
            tag = f"{rec['type']}.{name}"
            if sp["components"]:
                rec["fields"][name] = self.vector(v, tag)
            else:
                rec["fields"][name] = self.scalar(sp["scale"], v, tag)


def _one(args):
    seed, i = args
    s = _setup()
    DC, TE = _STATE["DC"], _STATE["TE"]
    sit = s.sample(i)
    ctx = json.loads(sit.context.dumps(s.tokenizer))
    g = Grid(s.tokenizer.interface.token_types)
    for rec in ctx["records"]:
        g.record(rec)
    try:
        dc = DC.loads(json.dumps(ctx, separators=(",", ":")), s.tokenizer)
        enc = s.tokenizer.encode(dc)
        expect = {"digest": f"{enc.digest():08x}", "n": enc.n, "ghosts": list(enc.ghosts)}
    except TE as e:
        expect = {"error": str(e)[:200]}
    line = json.dumps({"name": f"ctx_{seed}_{i}", "now": NOW, "context": ctx, "expect": expect}, separators=(",", ":"), ensure_ascii=False)
    return line, g.worst, g.clamped


def stamp() -> str:
    parts = []
    for d in (ROOT / "ai" / "tok2", ROOT / "ai" / "situations", ROOT / "catalogue" / "generated"):
        for p in sorted(d.rglob("*")):
            if p.suffix in (".py", ".json") and "__pycache__" not in p.parts and "tests" not in p.parts:
                st = p.stat()
                parts.append(f"{p.relative_to(ROOT)}:{st.st_size}:{int(st.st_mtime)}")
    parts.append(Path(__file__).read_text())
    return f"{zlib.crc32(chr(10).join(parts).encode()):08x}"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--n", type=int, default=3000)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--jobs", type=int, default=max(1, (mp.cpu_count() or 2) - 1))
    ap.add_argument("--reuse", action="store_true")
    a = ap.parse_args(argv)
    out = Path(a.out)
    st = Path(str(out) + ".stamp")
    key = f"{stamp()} {a.seed} {a.n}"
    if a.reuse and out.exists() and st.exists() and st.read_text() == key:
        print(f"corpus up to date: {out}")
        return 0
    with mp.Pool(a.jobs, initializer=_init, initargs=(a.seed,)) as pool:
        res = pool.map(_one, [(a.seed, i) for i in range(a.n)], chunksize=20)
    out.write_text("\n".join(r[0] for r in res) + "\n", encoding="utf-8")
    st.write_text(key)
    worst, clamped = {}, 0
    for _, w, c in res:
        clamped += c
        for k, v in w.items():
            if v[0] > worst.get(k, (0, 0))[0]:
                worst[k] = v
    refused = sum(1 for r in res if '"error"' in r[0][-300:])
    print(f"{len(res)} situations -> {out} ({refused} refused by the oracle, {clamped} quantities clamped to the int32 of thousandths)")
    top = sorted(worst.items(), key=lambda kv: -kv[1][0])[:6]
    print("largest relative quantisation changes: " + ", ".join(f"{k} {e:.2%} (at {v:g})" for k, (e, v) in top))
    return 0


if __name__ == "__main__":
    sys.exit(main())
