#!/usr/bin/env python3
"""teacher_tools.py - prepare teacher requests and validate/convert answers.

  python3 teacher_tools.py batch --states states.jsonl --out requests.jsonl --per-call 8
  python3 teacher_tools.py parse --states states.jsonl --answers answers.jsonl --out labels.jsonl

answers.jsonl: one JSON object per line: {"custom_id": "...", "content": "<model text>"}
(adapt the two small readers below to the exact format your provider returns).

The prompt text is read from teacher_prompt.md, the block between
<!-- SYSTEM START --> and <!-- SYSTEM END -->.
"""
import argparse, json, math, re, sys
from collections import Counter

import os
PROMPT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "teacher_prompt.md")


DRIVERS = {"need", "fear", "anger", "kin", "trust", "desire", "debt", "norm", "habit", "curiosity"}


def load_system(variant):
    txt = open(PROMPT_FILE, encoding="utf-8").read()
    m = re.search(r"<!-- SYSTEM START -->(.*?)<!-- SYSTEM END -->", txt, re.S)
    v = re.search(r"<!-- VARIANT %s START -->(.*?)<!-- VARIANT %s END -->" % (variant, variant), txt, re.S)
    if not m or not v:
        sys.exit("prompt block or variant not found in " + PROMPT_FILE)
    return m.group(1).replace("{{OUTPUT}}", v.group(1).strip()).strip()


def read_states(path):
    return [json.loads(l) for l in open(path, encoding="utf-8")]


def cmd_batch(a):
    system = load_system(a.variant)
    rows = read_states(a.states)
    out = open(a.out, "w", encoding="utf-8")
    n = 0
    for i in range(0, len(rows), a.per_call):
        chunk = rows[i:i + a.per_call]
        user = "\n\n".join(f"### {r['id']}\n{r['text']}" for r in chunk)
        req = {"custom_id": f"req{n:06d}:" + ",".join(r["id"] for r in chunk),
               "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
               "temperature": a.temperature, "max_tokens": 90 * len(chunk) + 60,
               "response_format": {"type": "json_object"}}
        out.write(json.dumps(req, ensure_ascii=False) + "\n")
        n += 1
    out.close()
    print(f"{n} requests for {len(rows)} situations", file=sys.stderr)


def softmax(xs, t):
    m = max(xs)
    e = [math.exp((x - m) / t) for x in xs]
    z = sum(e)
    return [x / z for x in e]


def parse_answer(content, expected):
    """Return (dict id -> label, list of error strings)."""
    errs = []
    try:
        d = json.loads(content)
    except Exception:
        m = re.search(r"\{.*\}", content, re.S)
        if not m:
            return {}, ["json_invalid"]
        try:
            d = json.loads(m.group(0))
        except Exception:
            return {}, ["json_invalid"]
    items = d.get("r") if isinstance(d, dict) else None
    if not isinstance(items, list):
        return {}, ["no_r_list"]
    got = {}
    for it in items:
        sid = it.get("id")
        if sid not in expected:
            errs.append("unknown_id")
            continue
        s = it.get("s")
        n = expected[sid]
        if not isinstance(s, list) or len(s) != n:
            errs.append("bad_length")
            continue
        if not all(isinstance(x, int) and 0 <= x <= 4 for x in s):
            errs.append("bad_score")
            continue
        k = it.get("k")
        if k is not None and (not isinstance(k, list) or not all(x in DRIVERS for x in k) or not 1 <= len(k) <= 3):
            errs.append("bad_drivers")
            k = None
        got[sid] = {"why": str(it.get("why", ""))[:160], "k": k, "s": s, "alt": it.get("alt")}
    for sid in expected:
        if sid not in got:
            errs.append("missing_id")
    return got, errs


def cmd_parse(a):
    states = {r["id"]: r for r in read_states(a.states)}
    out = open(a.out, "w", encoding="utf-8")
    errc, ok, total = Counter(), 0, 0
    flat_scores = Counter()
    for line in open(a.answers, encoding="utf-8"):
        rec = json.loads(line)
        ids = rec["custom_id"].split(":", 1)[1].split(",")
        expected = {i: len(states[i]["cands"]) for i in ids if i in states}
        total += len(expected)
        got, errs = parse_answer(rec["content"], expected)
        errc.update(errs)
        for sid, lab in got.items():
            s = lab["s"]
            if len(set(s)) == 1 and len(s) > 3:        # label with no information
                errc["flat_scores"] += 1
                continue
            flat_scores.update(s)
            out.write(json.dumps({"id": sid, "scores": s, "soft": [round(p, 4) for p in softmax(s, a.temp)],
                                  "alt": lab["alt"], "drivers": lab["k"], "why": lab["why"]}, ensure_ascii=False) + "\n")
            ok += 1
    out.close()
    print(f"labelled {ok}/{total} situations; errors: {dict(errc) if errc else 'none'}", file=sys.stderr)
    if flat_scores:
        tot = sum(flat_scores.values())
        print("score distribution:", {k: round(v / tot, 3) for k, v in sorted(flat_scores.items())}, file=sys.stderr)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("batch")
    b.add_argument("--states", required=True); b.add_argument("--out", required=True)
    b.add_argument("--variant", required=True, choices=["none", "text", "codes"])
    b.add_argument("--per-call", type=int, default=8); b.add_argument("--temperature", type=float, default=0.2)
    p = sub.add_parser("parse")
    p.add_argument("--states", required=True); p.add_argument("--answers", required=True)
    p.add_argument("--out", required=True); p.add_argument("--temp", type=float, default=1.0)
    a = ap.parse_args()
    cmd_batch(a) if a.cmd == "batch" else cmd_parse(a)
