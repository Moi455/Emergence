#!/usr/bin/env python3
"""gold_tool.py - hand-label a few situations BLIND, then measure how far the Gemini labels agree with YOU.
The pilot only measures the teacher's consistency; this measures whether it matches your idea of the characters.

  python3 gold_tool.py make --n 100     # writes data/gold_todo.txt (situations without any teacher score)
  gedit data/gold_todo.txt              # on each ANSWER line, write the number(s) of the acceptable option(s): 3   or   3,5
  python3 gold_tool.py score            # agreement report
"""
import argparse
import json
import os
import random
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import teacher_run as tr  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["make", "score"])
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--config", default="config.json")
    a = ap.parse_args()
    env = tr.Env(tr.load_cfg(a.config))
    todo = os.path.join(env.data, "gold_todo.txt")
    if a.cmd == "make":
        labelled = [r["id"] for r in env.iter_jsonl("labels")]
        if len(labelled) < a.n:
            sys.exit(f"only {len(labelled)} labelled situations: run the pilot or the labelling first")
        ids = set(random.Random(42).sample(labelled, a.n))
        with open(todo, "w", encoding="utf-8") as f:
            f.write("# For each situation, write after ANSWER the number(s) of the option(s) you consider acceptable for THIS character.\n"
                    "# One number (3) or several (3,5). Leave '?' to skip. Do not look at any teacher output.\n\n")
            for s in env.iter_jsonl("states"):
                if s["id"] in ids:
                    f.write(f"### {s['id']}  [{s['family']}]\n{s['text']}\nANSWER {s['id']}: ?\n\n")
        print(f"wrote {todo}: edit it with  gedit {todo}")
        return
    text = open(todo, encoding="utf-8").read()
    gold = {}
    for sid, ans in re.findall(r"^ANSWER (\w+):\s*(.*)$", text, re.M):
        nums = [int(x) for x in re.findall(r"\d+", ans)]
        if nums:
            gold[sid] = set(nums)
    labels = {r["id"]: r for r in env.iter_jsonl("labels")}
    fam = {s["id"]: s["family"] for s in env.iter_jsonl("states") if s["id"] in gold}
    n = hit = 0
    rank_sum = 0.0
    by_fam = {}
    for sid, g in gold.items():
        lab = labels.get(sid)
        if not lab:
            continue
        sc = lab["scores"]
        top = max(sc)
        best = {i for i, x in enumerate(sc) if x == top}
        ok = bool(best & g)
        n += 1
        hit += ok
        # how highly does the teacher rate your choice, relative to the options
        mine = max(sc[i] for i in g if i < len(sc))
        rank_sum += sum(1 for x in sc if x > mine)
        d = by_fam.setdefault(fam.get(sid, "?"), [0, 0])
        d[0] += 1
        d[1] += ok
    if not n:
        sys.exit("no answered situations found")
    print(f"answered {n}   teacher's top choice contains yours: {hit}/{n} = {hit / n:.0%}   "
          f"mean number of options the teacher rates ABOVE yours: {rank_sum / n:.2f}")
    print("by family (n, agreement):")
    for k, (m, h) in sorted(by_fam.items(), key=lambda kv: kv[1][1] / kv[1][0]):
        print(f"  {k:22s} {m:3d}   {h / m:.0%}")
    print("\nReading: below about 60% on a family, rewrite the prompt for that family or write rules for it instead of trusting the teacher.")


if __name__ == "__main__":
    main()
