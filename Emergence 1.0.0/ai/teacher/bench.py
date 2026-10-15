"""bench.py - the same small batch to every model, to compare the teachers (1 real request per model, free quota only).

    QualityBench   the same K situations (same seed, same indices) as ONE batch request per model, judged by the usual
                   validator + governor, WITHOUT the repair pass (the first-shot rate is what is measured)
    ModelScore     per model: valid decisions at the first shot, share of passive gestures, output length, latency, refusal codes

A request is never repeated and models are asked one after the other, `pause` seconds apart (at least the spacing of their own
requests-per-minute limit). The result goes outside the repository (default ~/.local/share/emergence/dataset/quality_models.json).

    cd ai && python3 -m teacher.bench --call --models gemma-4-31b-it,gemini-3.5-flash-lite
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
from .gemini import ApiKeyError, ApiKeyLoader, ApiResult, GeminiClient
from .phrasebook import PhraseBook
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

    @property
    def valid_rate(self) -> float:
        return round(self.valid_first / self.asked, 3) if self.asked else 0.0

    @property
    def passive_share(self) -> float | None:
        return round(self.passive_valid / self.valid_first, 3) if self.valid_first else None

    def to_dict(self) -> dict:
        return {"model": self.model, "strategy": self.strategy, "requests": self.requests, "asked": self.asked, "answered": self.answered,
                "valid_first": self.valid_first, "valid_rate": self.valid_rate, "passive_share_of_valid": self.passive_share,
                "output_tokens": self.output_tokens, "thought_tokens": self.thought_tokens, "prompt_tokens": self.prompt_tokens,
                "latency_s": round(self.latency_s, 2), "finish": self.finish, "http": self.http, "error": self.error,
                "reply_problem": self.problem, "refusal_codes": self.codes}

    def line(self) -> str:
        if self.http not in (0, 200) or self.error:
            return f"{self.model:<32} HTTP {self.http} {self.error[:100]}"
        share = "-" if self.passive_share is None else f"{self.passive_share:.0%}"
        return (f"{self.model:<32} valid {self.valid_first}/{self.asked} ({self.valid_rate:.0%}) passive {share} "
                f"out {self.output_tokens} (+{self.thought_tokens} thoughts) {self.latency_s:.1f}s {self.finish} {self.codes or ''}")


class QualityBench:
    def __init__(self, client, config: QuotaConfig, tk: Toolkit | None = None, k: int = 6, seed: int = 0, pause: float = 13.0,
                 temperature: float = 0.9, sleep=time.sleep, clock=time.monotonic, log=print, sampler_factory=None):
        self.client, self.config, self.k, self.seed, self.pause = client, config, k, seed, pause
        self.temperature, self.sleep, self.clock, self.log = temperature, sleep, clock, log
        self.tk = tk or Toolkit()
        self.instructions = BatchInstructions(self.tk, PhraseBook(self.tk))
        self.schema = BatchSchema(DecisionSchema(self.tk, "full"))
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
            if sc.http not in (0, 200) or sc.error:
                break
        return sc

    def _chunk(self, sc: ModelScore, spec, situations: list, pause: float) -> None:
        seen: list[ApiResult] = []

        def caller(system: str, user: str, schema: dict):
            if self._last is not None and self.clock() - self._last < pause:
                self.sleep(pause - (self.clock() - self._last))
            r = self.client.generate(spec.name, system, user, schema, self.temperature, 8192, spec.thinking_budget)
            self._last = self.clock()
            seen.append(r)
            return spec.name, r

        res: RoundResult | None = GroupedRound(self.instructions, self.schema, self.prompt, self.validator, caller,
                                               repair=False).run(situations)
        r = seen[-1]
        sc.http, sc.error, sc.finish = r.status, r.error, r.finish
        sc.latency_s += r.latency
        sc.prompt_tokens += r.usage.get("promptTokenCount", 0)
        sc.output_tokens += r.usage.get("candidatesTokenCount", 0)
        sc.thought_tokens += r.usage.get("thoughtsTokenCount", 0)
        if res is None:
            return
        sc.requests += 1
        sc.asked += len(res.slots)
        sc.problem = res.requests[0].answer.problem or sc.problem
        sc.answered += sum(1 for s in res.slots if s.raw_item is not None)
        sc.valid_first += sum(1 for s in res.slots if s.first is not None and s.first.ok)
        sc.passive_valid += sum(1 for s in res.slots if s.first is not None and s.first.ok and s.first.decision.gesture in PASSIVE_GESTURES)
        for s in res.slots:
            if s.first is not None and not s.first.ok:
                sc.codes[s.first.code] = sc.codes.get(s.first.code, 0) + 1

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
    try:
        key = ApiKeyLoader(path=a.key_file).load()
    except ApiKeyError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    client = GeminiClient(key)
    qc = QuotaConfig.load(a.quota_file).only([m.strip() for m in a.models.split(",") if m.strip()])
    qc.install(client)
    names = [s.name for s in qc.models]
    scores = QualityBench(LedgerGate.for_tool(client, names, a.quota_file, a.ledger), qc, k=a.k, seed=a.seed,
                          pause=a.pause).run(names)                        # every request is counted in the shared ledger
    print(f"written to {write_report(scores, a.out, a.seed, a.k)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
