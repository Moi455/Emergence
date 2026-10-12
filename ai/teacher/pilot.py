"""pilot.py - the teacher pilot: render N situations, (optionally) ask Gemini, validate, summarise.

    cd ai
    python3 -m teacher.pilot --n 20 --seed 0          DRY RUN (default): no network. Writes the prompts, the schema and the
                                                      grammar to ~/.local/share/emergence/teacher/<timestamp>/ and prints sizes.
    python3 -m teacher.pilot --call --list-models     lists the models the key can use (network, free)
    python3 -m teacher.pilot --call --n 20            REAL CALLS (quota of the free tier; needs Monsieur's agreement)

A real run writes responses.jsonl (everything) and dataset.jsonl (valid answers only: the student's labels, see
teacher/dataset.py). Outputs go OUTSIDE the repository. The key is read from GEMINI_API_KEY, else ~/.config/emergence/API_Keys, and is
never printed, logged or written.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from situations.sampler import SituationSampler

from .dataset import FILE_NAME as DATASET_FILE, LabelRecord
from .gemini import (ApiKeyError, ApiKeyLoader, ApiResult, GeminiClient, ModelCatalog, QuotaBook, QuotaTable,
                     RateLimiter, Redactor)
from .render import SituationRenderer
from .schema import EXAMPLES, DecisionSchema
from .toolkit import ROOT, Toolkit
from .validate import AnswerValidator, Outcome

DEFAULT_OUT = Path.home() / ".local" / "share" / "emergence" / "teacher"


# ---------------------------------------------------------------------------------------------------- output folder
class RunDirectory:
    """A timestamped folder outside the repository."""

    def __init__(self, base: Path | None = None, stamp: str | None = None):
        base = Path(base) if base else DEFAULT_OUT
        stamp = stamp or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self.path = (base / stamp).resolve()
        if self.path == ROOT or ROOT in self.path.parents:
            raise SystemExit(f"refusing to write inside the repository ({self.path}): pass --out outside {ROOT}")
        self.path.mkdir(parents=True, exist_ok=True)

    def write(self, name: str, text: str) -> Path:
        p = self.path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p

    def append(self, name: str, line: str) -> None:
        with open(self.path / name, "a", encoding="utf-8") as f:
            f.write(line + "\n")


# ---------------------------------------------------------------------------------------------------- dry run
class DryRun:
    """Renders the prompts and measures them. Token counts here are ESTIMATES (characters / 4)."""

    def __init__(self, tk: Toolkit, schema: DecisionSchema, renderer: SituationRenderer, sampler: SituationSampler):
        self.tk, self.schema, self.renderer, self.sampler = tk, schema, renderer, sampler

    def self_check_examples(self) -> list[str]:
        """The examples printed in the system text must pass the validator's own language rules."""
        bad = []
        for e in EXAMPLES:
            if e["speech"] and not self.tk.expression(e["speech"]).ok:
                bad.append(e["speech"])
        return bad

    def run(self, n: int, out: RunDirectory) -> dict:
        system = self.schema.instructions()
        out.write("system.txt", system)
        out.write("schema.gemini.json", json.dumps(self.schema.response_schema(), indent=1))
        out.write("schema.json", json.dumps(self.schema.json_schema(), indent=1))
        out.write("grammar.gbnf", self.schema.gbnf())
        sizes = []
        for i in range(n):
            text = self.renderer.render(self.sampler.sample(i))
            out.write(f"prompts/{i:04d}.txt", text)
            sizes.append(len(text))
        est = self.tk.estimate_tokens
        info = {"system_chars": len(system), "system_tokens_estimate": est(system),
                "situation_chars": {"min": min(sizes), "mean": round(statistics.mean(sizes)), "max": max(sizes)},
                "situation_tokens_estimate": {"min": (min(sizes) + 3) // 4, "mean": (round(statistics.mean(sizes)) + 3) // 4,
                                              "max": (max(sizes) + 3) // 4},
                "schema_chars": len(json.dumps(self.schema.response_schema())), "fingerprint": self.schema.fingerprint(),
                "bad_examples": self.self_check_examples(), "n": n, "path": str(out.path)}
        out.write("sizes.json", json.dumps(info, indent=1))
        return info


# ---------------------------------------------------------------------------------------------------- real run
class ModelPool:
    """Which model answers next: the chain in order, skipping the spent ones, at each model's own pace."""

    def __init__(self, chain: list[str], book: QuotaBook | None = None, clock=time.monotonic, sleep=time.sleep):
        self.chain, self.book = chain, book or QuotaBook()
        self.limiters = {m: RateLimiter(QuotaTable.for_model(m).rpm, clock, sleep) for m in chain}

    def current(self) -> str | None:
        left = self.book.available(self.chain)
        return left[0] if left else None

    def pace(self, model: str) -> float:
        self.book.count(model)
        return self.limiters[model].wait()


class PilotRun:
    def __init__(self, client: GeminiClient, tk: Toolkit, schema: DecisionSchema, renderer: SituationRenderer,
                 sampler: SituationSampler, validator: AnswerValidator, pool: ModelPool, out: RunDirectory,
                 temperature: float = 0.9, thinking_budget: int | None = None, max_output_tokens: int = 2048, log=print):
        self.client, self.tk, self.schema, self.renderer, self.sampler = client, tk, schema, renderer, sampler
        self.validator, self.pool, self.out, self.log = validator, pool, out, log
        self.temperature, self.thinking, self.max_output_tokens = temperature, thinking_budget, max_output_tokens
        self.unusable = 0
        self.redactor = client.redactor
        self.records: list[dict] = []

    MAX_MINUTE_429 = 3          # consecutive per-minute rate limits tolerated on one model
    MAX_UNUSABLE = 3            # consecutive answers without usable JSON before the run stops (protects the quota)

    def thinking_for(self, model: str) -> int | None:
        """Gemini 2.5 Flash thinks by default and the thoughts eat the output budget: switch it off unless asked."""
        if self.thinking is not None:
            return self.thinking
        return 0 if model.startswith("gemini-2.5-flash") else None

    # ---- one call with retries and model fallback
    def ask(self, system: str, user: str, schema: dict) -> tuple[str, ApiResult | None]:
        bad_requests = transient = slow = 0
        while True:
            model = self.pool.current()
            if model is None:
                return "", None
            self.pool.pace(model)
            r = self.client.generate(model, system, user, schema, self.temperature, self.max_output_tokens,
                                     self.thinking_for(model))
            if r.ok:
                return model, r
            if r.status == 429 and r.quota_scope == "day":
                self.log(f"  {model}: daily quota spent, next model")
                self.pool.book.spend(model)
            elif r.status == 429:
                slow += 1
                if slow > self.MAX_MINUTE_429:                 # misclassified daily quota, or a stuck limiter: stop hammering
                    self.log(f"  {model}: {slow} rate limits in a row, treated as spent")
                    self.pool.book.spend(model)
                    slow = 0
                    continue
                wait = min(max(r.retry_after, 5.0), 90.0)
                self.log(f"  {model}: rate limited, waiting {wait:.0f} s")
                time.sleep(wait)
            elif r.status in (500, 502, 503, 504, 0):
                self.log(f"  {model}: HTTP {r.status} {r.error[:80]}, pausing")
                transient += 1
                if transient >= 4:
                    raise RuntimeError(f"HTTP {r.status} repeated {transient} times: {r.error[:160]}")
                time.sleep(5.0 * transient)
            elif r.status == 404:
                self.pool.book.spend(model)
            elif r.status == 200:                                  # empty answer (blocked, truncated): count it
                return model, r
            else:                                                  # 400 and others: the request itself is wrong
                bad_requests += 1
                self.log(f"  {model}: HTTP {r.status} {r.error[:160]}")
                if bad_requests >= 2:
                    raise RuntimeError(f"HTTP {r.status}: {r.error[:200]} (stopped to protect the quota)")

    # ---- the loop
    def run(self, n: int, start: int = 0) -> list[dict]:
        system = self.schema.instructions()
        schema = self.schema.response_schema()
        for i in range(start, start + n):
            sit = self.sampler.sample(i)
            user = self.renderer.render(sit)
            model, r = self.ask(system, user, schema)
            if r is None:
                self.log("all models spent for today: stopping")
                break
            rec = {"index": i, "seed": self.sampler.seed, "model": model, "latency_s": round(r.latency, 3),
                   "usage": r.usage, "finish": r.finish, "http": r.status}
            if r.text and r.finish == "MAX_TOKENS":
                rec.update(raw=self.redactor.clean(r.text), code="truncated", detail="finishReason MAX_TOKENS", why="",
                           decision=None, gesture="", family="")
            elif r.text:
                o: Outcome = self.validator.validate(r.text, sit)
                rec.update(raw=self.redactor.clean(r.text), code=o.code, detail=self.redactor.clean(o.detail),
                           why=o.why, decision=o.decision.to_dict() if o.ok else None,
                           gesture=o.decision.gesture if o.ok else self._gesture(r.text),
                           family=o.decision.family if o.ok else "")
            else:
                rec.update(raw="", code="no_text", detail=r.finish, why="", decision=None, gesture="", family="")
            self.records.append(rec)
            self.out.append("responses.jsonl", json.dumps(rec, ensure_ascii=False))
            if rec["code"] == "ok":                               # the training file: only valid answers, records by key
                self.out.append(DATASET_FILE, LabelRecord.build(self.sampler.tokenizer, sit, o, model).to_line())
            self.log(f"[{i}] {model} {rec['latency_s']}s -> {rec['code']} {rec['gesture']}")
            self.unusable = self.unusable + 1 if rec["code"] in ("no_text", "truncated", "invalid_json") else 0
            if self.unusable >= self.MAX_UNUSABLE:
                raise RuntimeError(f"{self.unusable} answers in a row without usable JSON (last: {rec['code']}); stopped")
        return self.records

    @staticmethod
    def _gesture(text: str) -> str:
        try:
            g = json.loads(text).get("gesture", "")
            return g if isinstance(g, str) else ""
        except (ValueError, AttributeError):
            return ""


class RunSummary:
    """What the pilot tells Monsieur: how often the teacher is valid, why it is refused, how passive it is."""

    def __init__(self, records: list[dict], tk: Toolkit):
        self.records, self.tk = records, tk

    def compute(self) -> dict:
        recs = self.records
        n = len(recs)
        valid = [r for r in recs if r["code"] == "ok"]
        codes = Counter(r["code"] for r in recs)
        fam = defaultdict(lambda: Counter())
        for r in recs:
            f = (self.tk.spec.gestures[r["gesture"]].family if r["gesture"] in self.tk.spec.gestures else "?")
            fam[f][r["code"]] += 1
        passive_all = sum(1 for r in recs if r["gesture"] in self._passive())
        passive_ok = sum(1 for r in valid if r["gesture"] in self._passive())
        usage = [r["usage"] for r in recs if r["usage"]]
        mean = lambda k: round(statistics.mean(u.get(k, 0) for u in usage), 1) if usage else None   # noqa: E731
        return {"answers": n, "valid": len(valid), "valid_rate": round(len(valid) / n, 3) if n else None,
                "codes": dict(codes.most_common()), "by_family": {f: dict(c) for f, c in sorted(fam.items())},
                "passive_share_of_answers": round(passive_all / n, 3) if n else None,
                "passive_share_of_valid": round(passive_ok / len(valid), 3) if valid else None,
                "models": dict(Counter(r["model"] for r in recs)),
                "latency_mean_s": round(statistics.mean(r["latency_s"] for r in recs), 2) if n else None,
                "tokens_mean": {"prompt": mean("promptTokenCount"), "output": mean("candidatesTokenCount"),
                                "thoughts": mean("thoughtsTokenCount")},
                "gestures": dict(Counter(r["gesture"] for r in recs if r["gesture"]).most_common())}

    def _passive(self):
        from .spec import PASSIVE_GESTURES
        return PASSIVE_GESTURES

    def text(self) -> str:
        s = self.compute()
        lines = [f"{s['answers']} answers, {s['valid']} valid ({s['valid_rate']:.0%})" if s["answers"] else "no answer",
                 "refusal codes: " + json.dumps(s["codes"])]
        for f, c in s["by_family"].items():
            lines.append(f"  family {f:<10} " + json.dumps(c))
        lines.append(f"passive gestures (wait, look, listen, rest, sleep, stop): {s['passive_share_of_answers']} of answers, "
                     f"{s['passive_share_of_valid']} of valid ones (a high share hints that the teacher is too gentle)")
        lines.append(f"models {s['models']}, mean latency {s['latency_mean_s']} s, mean tokens {s['tokens_mean']}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------------------------------- command line
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="teacher.pilot", description=__doc__.split("\n\n")[0])
    ap.add_argument("--n", type=int, default=20, help="number of situations")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--start", type=int, default=0, help="index of the first situation")
    ap.add_argument("--out", type=Path, default=None, help=f"base folder (default {DEFAULT_OUT}); must be outside the repository")
    ap.add_argument("--vocab", choices=("full", "grammar", "none"), default="full", help="words listed in the system text")
    ap.add_argument("--call", action="store_true", help="REAL network calls to Gemini (default: dry run)")
    ap.add_argument("--list-models", action="store_true", help="with --call: list the usable models and exit")
    ap.add_argument("--models", default="", help="with --call: comma-separated model names, overriding the automatic chain")
    ap.add_argument("--temperature", type=float, default=0.9)
    ap.add_argument("--thinking-budget", type=int, default=None, help="thinkingConfig.thinkingBudget (omitted by default)")
    ap.add_argument("--max-output-tokens", type=int, default=2048)
    ap.add_argument("--key-file", type=Path, default=None, help="key file (default ~/.config/emergence/API_Keys)")
    return ap


def main(argv=None) -> int:
    a = build_parser().parse_args(argv)
    tk = Toolkit()
    schema = DecisionSchema(tk, a.vocab)
    renderer = SituationRenderer(tk)
    sampler = SituationSampler(a.seed)
    out = RunDirectory(a.out)
    if not a.call:
        info = DryRun(tk, schema, renderer, sampler).run(a.n, out)
        print(f"DRY RUN (no network). Written to {info['path']}")
        print(f"system text      : {info['system_chars']} characters, about {info['system_tokens_estimate']} tokens (estimate: characters / 4)")
        sc, st = info["situation_chars"], info["situation_tokens_estimate"]
        print(f"situation text   : min {sc['min']} / mean {sc['mean']} / max {sc['max']} characters; "
              f"about {st['min']} / {st['mean']} / {st['max']} tokens (estimate)")
        print(f"response schema  : {info['schema_chars']} characters; schema+instructions fingerprint {info['fingerprint']}")
        print("examples valid   : " + ("yes" if not info["bad_examples"] else f"NO {info['bad_examples']}"))
        print("real token counts need --call (countTokens).")
        return 0
    try:
        key = ApiKeyLoader(path=a.key_file).load()
    except ApiKeyError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    client = GeminiClient(key)
    if a.list_models or not a.models:
        chain = ModelCatalog(client.list_models()).chain()
        if a.list_models:
            print("usable models, in the order they would be tried:\n  " + "\n  ".join(chain))
            return 0
    if a.models:
        chain = [m.strip() for m in a.models.split(",") if m.strip()]
    if not chain:
        print("error: no usable Flash / Flash Lite model", file=sys.stderr)
        return 2
    first = renderer.render(sampler.sample(a.start))
    system = schema.instructions()
    try:
        total = client.count_tokens(chain[0], system, first, schema.response_schema())
        print(f"countTokens ({chain[0]}): system + first situation = {total} tokens (measured)")
    except RuntimeError as e:
        print(f"countTokens failed: {Redactor(key).clean(str(e))}")
    run = PilotRun(client, tk, schema, renderer, sampler, AnswerValidator(tk), ModelPool(chain), out, a.temperature,
                   a.thinking_budget, a.max_output_tokens, log=lambda s: print(Redactor(key).clean(s), flush=True))
    out.write("system.txt", system)
    out.write("schema.gemini.json", json.dumps(schema.response_schema(), indent=1))
    try:
        records = run.run(a.n, a.start)
    except RuntimeError as e:
        print(f"stopped: {Redactor(key).clean(str(e))}", file=sys.stderr)
        records = run.records
    summary = RunSummary(records, tk)
    out.write("summary.json", json.dumps(summary.compute(), indent=1))
    print(summary.text())
    print(f"details in {out.path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
