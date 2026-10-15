"""measure_arena.py - T06: how long are the propositions the sampler really builds, and how full would the 20 KiB arena be?

    cd ai && python3 ../catalogue/tools/measure_arena.py --n 2000

Every string field of a sampled situation that parses as an inner-language expression counts: its length is the number
of symbols (parentheses do not count), which is what one arena word holds (docs/14 7.4). The fill rate is the symbols
of the propositions of ONE situation (what an NPC holds at one moment) over the 5120 words of the arena.
"""
from __future__ import annotations

import argparse
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ai"))
sys.path.insert(0, str(ROOT / "catalogue" / "tools"))
from language import LanguageError, Parser  # noqa: E402

ARENA_WORDS = 20 * 1024 // 4


def walk(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, (list, tuple)):
        for v in value:
            yield from walk(v)
    elif isinstance(value, dict):
        for v in value.values():
            yield from walk(v)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args(argv)
    from situations.sampler import SituationSampler
    sampler, parser = SituationSampler(a.seed), Parser()
    lengths: list = []
    per_situation: list = []
    failed = 0
    for i in range(a.n):
        try:
            sit = sampler.sample(i)
        except Exception:      # a sampler under repair must not hide the others: counted and reported
            failed += 1
            continue
        total = 0
        for rec in sit.context.records:
            for text in walk(list(rec.fields.values())):
                if not text.startswith("("):
                    continue
                try:
                    n = len(parser.parse(text).symbols())
                except LanguageError:
                    continue
                lengths.append(n)
                total += n
        per_situation.append(total)
    per_situation.sort()
    n = len(per_situation)
    mean = statistics.fmean(lengths)
    print(f"{n} situations measured ({failed} failed to build), {len(lengths)} propositions ({len(lengths) / n:.1f} per situation)")
    print(f"length in symbols: mean {mean:.2f}, median {statistics.median(lengths)}, max {max(lengths)}")
    print(f"symbols held per situation: mean {statistics.fmean(per_situation):.0f}, p99 {per_situation[int(0.99 * (n - 1))]}, "
          f"max {per_situation[-1]}; arena fill: mean {statistics.fmean(per_situation) / ARENA_WORDS:.1%}, max {per_situation[-1] / ARENA_WORDS:.1%}")
    print(f"625 slots all full at the mean length: {625 * mean:.0f} symbols = {625 * mean / ARENA_WORDS:.1%} of the arena")
    return 0


if __name__ == "__main__":
    sys.exit(main())
