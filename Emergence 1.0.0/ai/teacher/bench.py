"""bench.py - the same small batch to every model, to compare the teachers (1 real request per model, free quota only).

    QualityBench   the same K situations (same seed, same indices) as ONE batch request per model, judged by the usual
                   validator + governor, WITHOUT the repair pass (the first-shot rate is what is measured)
    ModelScore     per model: valid decisions at the first shot, share of passive gestures, output length, latency, refusal codes

A request is never repeated and models are asked one after the other, `pause` seconds apart (at least the spacing of their own
requests-per-minute limit). The result goes outside the repository (default ~/.local/share/emergence/dataset/quality_models.json).

    cd ai && python3 -m teacher.bench --call --models gemma-4-31b-it,gemini-3.5-flash-lite

Other providers (Groq, OpenRouter): `--planner` asks the 'human planner' format, `--repair` adds the repair pass (the score then
tells the validity at the first shot AND after the repair), `--name essai_providers` writes the report (`bench.json`) and every
raw reply (`bench_raw.jsonl`, key-free) in the series folder of that name. A model that REFUSES the content (finish_reason
content_filter, a `refusal` field, a stock "I can't help" reply) is COUNTED as such: the refusal is never worked around.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .batch import BatchInstructions, BatchPrompt, BatchSchema, GroupedRound, RoundResult
from .caller import ModelCaller
from .gemini import ApiKeyError, ApiKeyLoader, ApiResult, GeminiClient, Redactor
from .phrasebook import PhraseBook
from .providers import ProviderRouter, Providers, RefusalDetector
from .quota import DEFAULT_CONFIG, LedgerGate, QuotaConfig
from .render import SituationRenderer
from .schema import DecisionSchema
from .spec import PASSIVE_GESTURES
from .toolkit import ROOT, Toolkit
from .validate import AnswerValidator

DEFAULT_OUT = Path.home() / ".local" / "share" / "emergence" / "dataset" / "quality_models.json"


@dataclass
class ModelScore:
    model: str
    requests: int = 0
    asked: int = 0
    answered: int = 0              # situations with a decision in the reply (valid or not)
    valid_first: int = 0
    passive_valid: int = 0
    output_tokens: int = 0
    thought_tokens: int = 0
    prompt_tokens: int = 0
    latency_s: float = 0.0
    finish: str = ""
    http: int = 0
    error: str = ""
    problem: str = ""
    codes: dict = field(default_factory=dict)
    strategy: str = ""
    valid_final: int = 0           # valid decisions after the repair pass (= valid_first when the repair is off)
    repaired_ok: int = 0
    traced: int = 0                # valid decisions whose trace of thoughts is not empty (planner mode)
    refusals: dict = field(default_factory=dict)       # the model's own refusal of the content, by kind (counted, never worked around)
    empty_replies: int = 0
    reply_chars: int = 0
    rate_limit: dict = field(default_factory=dict)
    all_requests: int = 0          # requests sent, repairs included
    too_big: int = 0               # situations whose request alone exceeds the per-minute token limit (never sent)

    @property
    def valid_rate(self) -> float:
        return round(self.valid_first / self.asked, 3) if self.asked else 0.0

    @property
    def final_rate(self) -> float:
        return round(self.valid_final / self.asked, 3) if self.asked else 0.0

    @property
    def passive_share(self) -> float | None:
        return round(self.passive_valid / self.valid_first, 3) if self.valid_first else None

    def to_dict(self) -> dict:
        return {"model": self.model, "strategy": self.strategy, "requests": self.requests, "asked": self.asked, "answered": self.answered,
                "valid_first": self.valid_first, "valid_rate": self.valid_rate, "passive_share_of_valid": self.passive_share,
                "output_tokens": self.output_tokens, "thought_tokens": self.thought_tokens, "prompt_tokens": self.prompt_tokens,
                "latency_s": round(self.latency_s, 2), "finish": self.finish, "http": self.http, "error": self.error,
                "reply_problem": self.problem, "refusal_codes": self.codes, "valid_final": self.valid_final,
                "final_rate": self.final_rate, "repaired_ok": self.repaired_ok, "traced": self.traced,
                "content_refusals": self.refusals, "empty_replies": self.empty_replies, "reply_chars": self.reply_chars,
                "requests_sent": self.all_requests, "rate_limit": self.rate_limit, "too_big_for_tpm": self.too_big}

    def line(self) -> str:
        if self.http not in (0, 200) or self.error:
            return f"{self.model:<32} HTTP {self.http} {self.error[:100]}"
        share = "-" if self.passive_share is None else f"{self.passive_share:.0%}"
        more = (f" after repair {self.valid_final}/{self.asked} ({self.final_rate:.0%}) traced {self.traced}"
                f"{f' content-refusals {self.refusals}' if self.refusals else ''}") if self.all_requests else ""
        return (f"{self.model:<32} valid {self.valid_first}/{self.asked} ({self.valid_rate:.0%}) passive {share}{more} "
                f"out {self.output_tokens} (+{self.thought_tokens} thoughts) {self.latency_s:.1f}s {self.finish} {self.codes or ''}")


class QualityBench:
    def __init__(self, client, config: QuotaConfig, tk: Toolkit | None = None, k: int = 6, seed: int = 0, pause: float = 13.0,
                 temperature: float = 0.9, sleep=time.sleep, clock=time.monotonic, log=print, sampler_factory=None,
                 planner: bool = False, repair: bool = False, raw_path: Path | None = None):
        self.client, self.config, self.k, self.seed, self.pause = client, config, k, seed, pause
        self.temperature, self.sleep, self.clock, self.log = temperature, sleep, clock, log
        self.planner, self.repair, self.raw_path = planner, repair, raw_path
        self.tk = tk or Toolkit()
        self.instructions = BatchInstructions(self.tk, PhraseBook(self.tk), thoughts=planner,
                                              compact_phrasebook=PhraseBook(self.tk, 12), lean_phrasebook=PhraseBook(self.tk, 8))
        self.schema = BatchSchema(DecisionSchema(self.tk, "full", thoughts=planner, max_items=not planner))      # as the running planner series
        self.prompt = BatchPrompt(SituationRenderer(self.tk))
        self.validator = AnswerValidator(self.tk)
        self._sampler_factory = sampler_factory
        self._last = None

    def situations(self) -> list:
        if self._sampler_factory:
            sampler = self._sampler_factory(self.seed)
        else:
            from situations.sampler import SituationSampler
            sampler = SituationSampler(self.seed)
        return [sampler.sample(i) for i in range(self.k)]

    def score(self, model: str, situations: list) -> ModelScore:
        """One request per model; a model with `max_k` gets the same situations in chunks of that size (several requests)."""
        spec = next(s for s in (*self.config.models, *self.config.disabled) if s.name == model)
        sc = ModelScore(model, strategy=spec.strategy().name)
        size = spec.max_k or len(situations)
        pause = max(self.pause, 65.0) if spec.max_k else self.pause          # a tight tokens-per-minute limit needs a whole minute
        for i in range(0, len(situations), size):
            self._chunk(sc, spec, situations[i:i + size], pause)
            if (sc.error.startswith("LOCAL LEDGER") and " inf s" in sc.error) or sc.http == 413:     # alone above the per-minute token limit
                sc.too_big += len(situations[i:i + size])
                sc.http, sc.error = 200, ""
                continue
            if sc.http not in (0, 200) or sc.error:
                break
        return sc

    def _chunk(self, sc: ModelScore, spec, situations: list, pause: float) -> None:
        seen: list[ApiResult] = []

        def caller(system: str, user: str, schema: dict):
            if self._last is not None and self.clock() - self._last < pause:
                self.sleep(pause - (self.clock() - self._last))
            text = ModelCaller.system_for(system, spec)              # the full, compact or lean text, as the generator would send
            r = self.client.generate(spec.name, text, user, schema, self.temperature, spec.max_output or 8192, spec.thinking_budget)
            self._last = self.clock()
            seen.append(r)
            self._keep_raw(spec.name, r, len(seen))
            return spec.name, r

        res: RoundResult | None = GroupedRound(self.instructions, self.schema, self.prompt, self.validator, caller,
                                               repair=self.repair).run(situations)
        for i, r in enumerate(seen):
            sc.all_requests += 1
            sc.http, sc.error, sc.finish = r.status, r.error, r.finish
            sc.latency_s += r.latency
            sc.prompt_tokens += r.usage.get("promptTokenCount", 0)
            sc.output_tokens += r.usage.get("candidatesTokenCount", 0)
            sc.thought_tokens += r.usage.get("thoughtsTokenCount", 0)
            sc.reply_chars += len(r.text)
            sc.rate_limit = r.rate_limit or sc.rate_limit
            kind = RefusalDetector.of(r)
            if kind:
                sc.refusals[kind] = sc.refusals.get(kind, 0) + 1
            elif r.status == 200 and not r.text:
                sc.empty_replies += 1
        if res is None:
            return
        sc.requests += 1
        sc.asked += len(res.slots)
        sc.problem = res.requests[0].answer.problem or sc.problem
        sc.answered += sum(1 for s in res.slots if s.raw_item is not None)
        sc.valid_first += sum(1 for s in res.slots if s.first is not None and s.first.ok)
        sc.valid_final += sum(1 for s in res.slots if s.ok)
        sc.repaired_ok += sum(1 for s in res.slots if s.repaired and s.ok)
        sc.traced += sum(1 for s in res.slots if s.ok and getattr(s.final.decision, "thoughts", None))
        sc.passive_valid += sum(1 for s in res.slots if s.first is not None and s.first.ok and s.first.decision.gesture in PASSIVE_GESTURES)
        for s in res.slots:
            if s.first is not None and not s.first.ok:
                sc.codes[s.first.code] = sc.codes.get(s.first.code, 0) + 1

    def _keep_raw(self, model: str, r: ApiResult, n: int) -> None:
        """Every raw reply, key-free, for a human to read afterwards (outside the repository)."""
        if self.raw_path is None:
            return
        clean = getattr(self.client, "redactor", Redactor("")).clean
        rec = {"t": datetime.now(timezone.utc).isoformat(timespec="seconds"), "model": model, "n": n, "http": r.status,
               "finish": r.finish, "latency_s": round(r.latency, 2), "usage": r.usage, "rate_limit": r.rate_limit,
               "refusal": clean(r.refusal), "error": clean(r.error), "text": clean(r.text)}
        self.raw_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.raw_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def run(self, models: list[str]) -> list[ModelScore]:
        sits = self.situations()
        out = []
        for m in models:
            self.log(f"bench {m} ...")
            sc = self.score(m, sits)
            self.log("  " + sc.line())
            out.append(sc)
        return out


def write_report(scores: list[ModelScore], path: Path, seed: int, k: int) -> Path:
    path = Path(path).resolve()
    if path == ROOT or ROOT in path.parents:
        raise SystemExit(f"refusing to write inside the repository ({path})")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        rows = {r["model"]: r for r in json.loads(path.read_text(encoding="utf-8")).get("models", [])}
    except (OSError, ValueError, AttributeError):
        rows = {}
    rows.update({s.model: s.to_dict() for s in scores})
    path.write_text(json.dumps({"when": datetime.now(timezone.utc).isoformat(timespec="seconds"), "seed": seed, "situations": k,
                                "models": list(rows.values())}, indent=1, ensure_ascii=False), encoding="utf-8")
    return path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="teacher.bench", description=__doc__.split("\n\n")[0])
    ap.add_argument("--call", action="store_true", help="REAL requests (one per model, free quota)")
    ap.add_argument("--models", required=True)
    ap.add_argument("--planner", action="store_true", help="the 'human planner' format (trace of thoughts before the act)")
    ap.add_argument("--repair", action="store_true", help="add the repair pass: validity at the first shot AND after the repair")
    ap.add_argument("--name", default="", help="series folder where bench.json and bench_raw.jsonl are written (e.g. essai_providers)")
    ap.add_argument("--out-base", type=Path, default=DEFAULT_OUT.parent, help="base folder of the series")
    ap.add_argument("--k", type=int, default=6)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--pause", type=float, default=13.0)
    ap.add_argument("--quota-file", type=Path, default=DEFAULT_CONFIG)
    ap.add_argument("--ledger", type=Path, default=None, help="the shared quota ledger (default ~/.local/share/emergence/dataset/quota_global.json)")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--key-file", type=Path, default=None)
    a = ap.parse_args(argv)
    if not a.call:
        print("dry run: nothing is sent")
        return 0
    qc = QuotaConfig.load(a.quota_file).only([m.strip() for m in a.models.split(",") if m.strip()])
    names = [s.name for s in qc.models]
    try:
        client = ProviderRouter.build(list(dict.fromkeys(Providers.of(n) for n in names)), a.key_file)   # one key per provider
    except ApiKeyError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    qc.install(client)
    out, raw = a.out, None
    if a.name:
        folder = Path(a.out_base) / a.name
        out, raw = folder / "bench.json", folder / "bench_raw.jsonl"
    scores = QualityBench(LedgerGate.for_tool(client, names, a.quota_file, a.ledger), qc, k=a.k, seed=a.seed, pause=a.pause,
                          planner=a.planner, repair=a.repair, raw_path=raw).run(names)      # every request is counted in the shared ledger
    print(f"written to {write_report(scores, out, a.seed, a.k)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
