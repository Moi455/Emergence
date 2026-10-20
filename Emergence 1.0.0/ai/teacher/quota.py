"""quota.py - the free-tier quotas of every model, kept exactly: RPM, RPD, TPM, TPD.

    Limits         the four limits of one model (None = unknown, to be learned from the 429 answers)
    PacificDay     the quota day: it resets at midnight, America/Los_Angeles
    QuotaError     a 429 classified from its body (quotaMetric / quotaId): per minute or per day, requests or tokens
    QuotaBook      ONE QUOTA POOL: sliding one-minute window, day counters, cooldowns, learned limits; persisted as a dict
    QuotaDesk      every model: which one can answer first, and when; the GLOBAL LEDGER (one file for the whole key)
    LedgerGate     for the one-shot tools (probe, bench, pilot): the same ledger, around a client's requests

Google counts a quota per KEY and per MODEL, not per series and not per name: `gemini-flash-lite-latest` and
`gemini-3.5-flash-lite` are ONE pool (measured 15 Oct.: the 500th request of the day was refused to both at the same second,
407 + 93 requests), as are `gemini-3.1-flash-lite-preview` and `gemini-3.1-flash-lite`. So:

  * a model name belongs to a POOL (quota.toml `pool = "..."`, or learned from the `quotaDimensions.model` of a 429, which
    names the real model: `gemini-pro-latest` -> `gemini-3.1-pro`); the books are per pool, the chain is per name;
  * the counters live in ONE file outside the repository (`quota_global.json`, next to the series folders), read and written
    under an exclusive flock by every process: a second generator on another series, a probe or a bench see the same
    spent requests and tokens. The first start migrates the old `<series>/quota.json` files, without loss (same pool, same
    Pacific day: the counts are added).

Nothing here sleeps or calls the network: the caller gives `now` (epoch seconds) and decides how to wait, so the whole
logic is tested with a fake clock.

What counts:
  * requests: each sent request, in a sliding 60 s window (RPM) and in the Pacific day (RPD). The spacing between two
    requests of a pool is 60 / rpm x margin, so a burst never happens;
  * tokens: the INPUT tokens (promptTokenCount, cached ones included, as a safety), plus by default the output and the
    thinking tokens (`tpm_counts = "all"`; Google's own metric is the INPUT one, `...InputTokensPerModelPerMinute`, so a
    pool whose answers are long can say `tpm_counts = "input"`); the estimate (characters x the ratio measured on this
    model, + the mean output seen) is reserved when the request is sent and replaced by the measured count when the
    answer arrives (TPM: sliding window, TPD: Pacific day);
  * the per-minute token ceiling aimed at is `tpm_target` (80 %) of the limit: measured 15 Oct., a local cap of 100 % let the
    real minute reach 110 % (276 758 input tokens against 250 000 on `gemini-3.5-flash-lite`). A request alone in the window
    may go up to 92 % (a small-batch model such as Gemma, whose 16 000 does not allow two requests in a minute anyway).

A 429 is read from the error body, never guessed: `quotaId` ends in PerMinute... or PerDay...; `quotaMetric`/`quotaId`
mention requests or tokens; `quotaValue` is the limit, which is learned (and persisted). A per-minute 429 blocks the model
for the delay Google gives (3 in a row: 10 minutes); a per-day 429 exhausts the model until the next Pacific midnight.
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import time
import tomllib
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, time as dtime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .gemini import STRUCTURED, ModelFamilies, ModelFamily, PromptOnlyStrategy, RequestStrategy
from .providers import JsonObjectStrategy, Providers

PACIFIC = ZoneInfo("America/Los_Angeles")
DEFAULT_CONFIG = Path(__file__).with_name("quota.toml")
WINDOW = 60.0
FORGET = 120.0                  # entries older than this leave the window
RESET_MARGIN = 3.0              # seconds after midnight before a model is used again
MINUTE_BLOCK = (2.0, 120.0)     # clamp of the delay Google asks for
LONG_BLOCK = 600.0              # 3 per-minute 429 in a row: something else is going on, leave the model alone for 10 min
FAR = float("inf")
TPM_TARGET = 0.80               # fraction of the per-minute token limit aimed at (see the module doc)
TPM_LONE = 0.92                 # a request ALONE in the minute may use up to this fraction
PROBE_STEPS = (600.0, 1200.0, 1800.0, 3600.0)   # a model refused for the DAY is tried again after 10, 20, 30, then every 60 minutes
OUT_ESTIMATE = 1500             # output + thinking tokens reserved for a request until the real mean is known
LEDGER_NAME = "quota_global.json"
DEFAULT_LEDGER = Path.home() / ".local" / "share" / "emergence" / "dataset" / LEDGER_NAME      # = series.DEFAULT_BASE / LEDGER_NAME
LEDGER_SCHEMA = 2
LOCK_TIMEOUT = 60.0             # seconds to wait for the ledger lock (it is held for milliseconds)


# ---------------------------------------------------------------------------------------------------- the clock
class PacificDay:
    """The quota day. `key(t)` names it, `next_reset(t)` is the epoch second of the next midnight there."""

    @staticmethod
    def key(t: float) -> str:
        return datetime.fromtimestamp(t, PACIFIC).strftime("%Y-%m-%d")

    @staticmethod
    def next_reset(t: float) -> float:
        d = datetime.fromtimestamp(t, PACIFIC).date() + timedelta(days=1)
        return datetime.combine(d, dtime(0, 0), tzinfo=PACIFIC).timestamp() + RESET_MARGIN


# ---------------------------------------------------------------------------------------------------- limits
@dataclass(frozen=True)
class Limits:
    rpm: float | None = None
    rpd: int | None = None
    tpm: int | None = None
    tpd: int | None = None

    NAMES = ("rpm", "rpd", "tpm", "tpd")

    def capped(self, learned: "Limits") -> "Limits":
        """self (the file) lowered by what a 429 taught: min(file, learned) per field, never above the file; a field the
        file does not know takes the learned one."""
        def pick(a, b):
            return b if a is None else a if b is None else min(a, b)
        return Limits(*(pick(getattr(self, n), getattr(learned, n)) for n in self.NAMES))

    def to_dict(self) -> dict:
        return {n: getattr(self, n) for n in self.NAMES if getattr(self, n) is not None}

    @classmethod
    def from_dict(cls, d: dict) -> "Limits":
        return cls(**{n: d[n] for n in cls.NAMES if d.get(n) is not None})


@dataclass(frozen=True)
class ModelSpec:
    """One model of quota.toml. system_instruction / json_schema: None = what its family accepts (gemini.ModelFamilies), else
    what the probe OBSERVED. enabled = False keeps the model listed (with its `note`, the reason) but out of the chain.
    pool: the name whose quota this name shares ("" = its own); the limits of a name with a pool are those of the pool.
    compact: the model gets the compact fixed instructions (batch.BatchInstructions, schema.compact) and the schema text without
    the lists already given in the instructions. tpm_counts: "input" or "all" (input + output + thinking). tpm_target: fraction of
    the per-minute token limit aimed at (None = the file's default)."""
    name: str
    limits: Limits
    thinking_budget: int | None = None
    system_instruction: bool | None = None
    json_schema: bool | None = None
    enabled: bool = True
    note: str = ""
    max_k: int | None = None            # a model that only takes SMALL batches (e.g. a tight tokens-per-minute limit): at most this many situations
    pool: str = ""
    compact: bool = False
    tpm_counts: str = "all"
    tpm_target: float | None = None
    # other providers (providers.py): the model is named `<provider>/<id>`; "" = Gemini
    provider: str = ""
    max_output: int | None = None       # tokens asked for the answer (a provider that counts the request against a per-minute limit)
    reasoning_effort: str = ""          # "low" / "none"... sent when set
    minimal: bool = False               # the LEAN instructions (batch.py): no WRITES, no WORDS, 8 sample sentences
    json_object: bool = False           # response_format json_object (a model without json_schema)

    @property
    def family(self) -> ModelFamily:
        return ModelFamilies.of(self.name)

    @property
    def pool_name(self) -> str:
        return self.pool or self.name

    def strategy(self) -> RequestStrategy:
        """Structured JSON when the model accepts systemInstruction and a response schema, else the prompt-only way."""
        fam = self.family
        system = fam.system_instruction if self.system_instruction is None else self.system_instruction
        schema = fam.json_schema if self.json_schema is None else self.json_schema
        if system and schema:
            return STRUCTURED
        if self.json_object:
            return JsonObjectStrategy(fold_system=not system, fold_schema=True, thinking_config=False, compact_schema=self.compact)
        return PromptOnlyStrategy(fold_system=not system, fold_schema=not schema, thinking_config=fam.thinking_config,
                                  compact_schema=self.compact)


@dataclass(frozen=True)
class QuotaConfig:
    models: tuple                                   # the enabled models, in order of preference (the chain)
    margin: float = 1.05
    disabled: tuple = ()                            # listed but off (enabled = false), with their reason in `note`
    tpm_target: float = TPM_TARGET
    catalogue: tuple = ()                           # every listed model (to find the spec of a pool target); () = models + disabled

    @classmethod
    def load(cls, path: Path | str = DEFAULT_CONFIG, provider: str = "gemini") -> "QuotaConfig":
        """`provider` picks the CHAIN of the run: the enabled models of that provider ("gemini" = those without a `provider`).
        Every model of every provider stays in `catalogue` (pools, tools). A run of one provider never waits for another's
        replies: Groq / OpenRouter models are slow, so they run in their own process, on the same shared ledger."""
        raw = tomllib.loads(Path(path).read_text(encoding="utf-8"))
        specs = [ModelSpec(m["name"], Limits.from_dict(m), m.get("thinking_budget"), m.get("system_instruction"),
                           m.get("json_schema"), bool(m.get("enabled", True)), str(m.get("note", "")), m.get("max_k"),
                           str(m.get("pool", "")), bool(m.get("compact", False)), str(m.get("tpm_counts", "all")),
                           m.get("tpm_target"), str(m.get("provider", "")), m.get("max_output"), str(m.get("reasoning_effort", "")),
                           bool(m.get("minimal", False)), bool(m.get("json_object", False))) for m in raw.get("model", [])]
        names = [s.name for s in specs]
        if len(set(names)) != len(names):
            raise ValueError(f"{path}: a model is listed twice")
        for s in specs:
            if s.tpm_counts not in ("input", "all"):
                raise ValueError(f"{path}: {s.name}: tpm_counts is 'input' or 'all'")
            if s.pool and s.pool not in names:
                raise ValueError(f"{path}: {s.name}: pool {s.pool!r} is not a listed model")
            if s.provider and (s.provider not in Providers.ALL or Providers.of(s.name) != s.provider):
                raise ValueError(f"{path}: {s.name}: provider {s.provider!r} must be groq or openrouter and prefix the name")
            if not s.provider and Providers.of(s.name) != "gemini":
                raise ValueError(f"{path}: {s.name}: a model named after a provider needs provider = \"{Providers.of(s.name)}\"")
        want = "" if provider == "gemini" else provider
        on = tuple(s for s in specs if s.enabled and s.provider == want)
        if not on:
            raise ValueError(f"{path}: no enabled [[model]] for provider {provider}")
        return cls(on, float(raw.get("margin", 1.05)), tuple(s for s in specs if not s.enabled and s.provider == want),
                   float(raw.get("tpm_target", TPM_TARGET)), tuple(specs))

    # ---- who shares whose quota
    def everything(self) -> tuple:
        return self.catalogue or (*self.models, *self.disabled)

    def spec_of(self, name: str) -> ModelSpec | None:
        return next((s for s in self.everything() if s.name == name), None)

    def pool_of(self, name: str, learned: dict | None = None) -> str:
        """The name of the quota pool of `name`: its `pool` in quota.toml, else the one learned from a 429, else itself."""
        seen = []
        while name not in seen and len(seen) < 4:
            seen.append(name)
            s = self.spec_of(name)
            nxt = (s.pool if s is not None else "") or (learned or {}).get(name, "")
            if not nxt or nxt == name:
                break
            name = nxt
        return name

    def pool_spec(self, pool: str, fallback: ModelSpec | None = None) -> ModelSpec:
        """The spec whose limits rule a pool: the model of that name, else the first name that points to it."""
        return (self.spec_of(pool) or fallback
                or next((s for s in self.everything() if s.pool == pool), None) or ModelSpec(pool, Limits()))

    def only(self, names: list[str]) -> "QuotaConfig":
        """The listed models, in that order (a disabled model named here is used; an unlisted one gets the Flash Lite defaults)."""
        by = {s.name: s for s in self.everything()}
        return QuotaConfig(tuple(by.get(n) or ModelSpec(n, Limits(15, 500) if "lite" in n else Limits(5, 20)) for n in names),
                           self.margin, (), self.tpm_target, self.everything())

    def install(self, client) -> None:
        """Teach the client how to ask each model (structured, or prompt-only)."""
        for s in self.everything():
            client.strategies[s.name] = s.strategy()
            if hasattr(client, "configure"):
                client.configure(s)


# ---------------------------------------------------------------------------------------------------- a 429
@dataclass(frozen=True)
class QuotaError:
    scope: str                  # "minute" | "day"
    kind: str                   # "requests" | "tokens"
    limit: float | None         # quotaValue, when Google says it
    retry_after: float          # seconds asked for (0 = not said)
    metric: str = ""
    reset_after: float = 0.0    # a day-quota whose reopening the provider states (Groq, OpenRouter: violation `resetAfter`); Gemini never does

    @classmethod
    def parse(cls, violations: list, message: str = "", scope_hint: str = "", retry_after: float = 0.0) -> "QuotaError":
        """From the QuotaFailure violations of a 429 (and its message). The worst violation wins: a day beats a minute."""
        found = []
        for v in violations or []:
            blob = f"{v.get('quotaId', '')} {v.get('quotaMetric', '')}".lower()
            scope = "day" if re.search(r"perday|per_day|daily", blob) else "minute" if re.search(r"perminute|per_minute", blob) else ""
            kind = "tokens" if "token" in blob else "requests" if "request" in blob else ""
            try:
                limit = float(v.get("quotaValue")) if v.get("quotaValue") not in (None, "") else None
            except (TypeError, ValueError):
                limit = None
            try:
                reset = float(v.get("resetAfter") or 0.0)
            except (TypeError, ValueError):
                reset = 0.0
            found.append((scope, kind, limit, str(v.get("quotaMetric", "") or v.get("quotaId", "")), reset))
        m = message or ""
        msg_scope = "day" if re.search(r"per ?day|daily", m, re.I) else "minute" if re.search(r"per ?minute", m, re.I) else ""
        msg_kind = "tokens" if re.search(r"token", m, re.I) else "requests" if re.search(r"request", m, re.I) else ""
        if not retry_after:
            r = re.search(r"retry in (\d+(?:\.\d+)?)\s*s", m, re.I)
            retry_after = float(r.group(1)) if r else 0.0
        if found:
            found.sort(key=lambda f: (f[0] != "day", f[0] == ""))
            scope, kind, limit, metric, reset_after = found[0]
        else:
            scope, kind, limit, metric, reset_after = "", "", None, "", 0.0
        scope = scope or msg_scope or scope_hint or "minute"
        kind = kind or msg_kind or "requests"
        return cls(scope, kind, limit, retry_after, metric, reset_after if scope == "day" else 0.0)


# ---------------------------------------------------------------------------------------------------- one model
class QuotaBook:
    """Everything known about one quota POOL (one model, or several names that share its quota). All times are epoch
    seconds given by the caller. `tpm_target` is the fraction of the per-minute token limit aimed at (1.0 = the limit itself)."""

    def __init__(self, spec: ModelSpec, margin: float = 1.05, tpm_target: float = 1.0):
        self.spec, self.margin = spec, margin
        self.target = spec.tpm_target if spec.tpm_target is not None else tpm_target
        self.counts_output = spec.tpm_counts == "all"
        # mean output + thinking tokens of one request; a model with a small `max_output` (Groq: the request counts against 8 000 tokens a
        # minute) starts from a quarter of it, then learns the real mean
        self.out_estimate = float(min(OUT_ESTIMATE, spec.max_output // 4 if spec.max_output else OUT_ESTIMATE)) if self.counts_output else 0.0
        self.learned = Limits()
        self.window: deque = deque()            # [time, input tokens] of the requests of the last minute
        self.last_sent = 0.0
        self.day = ""
        self.day_requests = 0
        self.day_tokens = 0
        self.exhausted_until = 0.0
        self.exhausted_why = ""
        self.blocked_until = 0.0
        self.minute_429 = 0                     # consecutive per-minute 429
        self.client_errors = 0                  # consecutive 400/403 on this model
        self.tokens_per_char = 0.27             # measured by settle(): input tokens / characters
        self.history: dict = {}                 # Pacific day -> {"requests", "tokens", "limited"} (small, kept 14 days)
        self.spent_at = 0.0                     # when Google first refused this pool for the day (0 = it is not refused)
        self.probe_step = 0                     # refusals since: the next retry waits PROBE_STEPS[step]
        self.probe_log: list = []               # [time, http code, step] of each day refusal and of the reopening (last 40)

    @property
    def name(self) -> str:
        return self.spec.name

    def limits(self) -> Limits:
        return self.spec.limits.capped(self.learned)

    # ---- the day
    def roll(self, now: float) -> None:
        """New Pacific day -> counters at zero. The day only moves FORWARD: a clock that jumps back never resets (nor
        un-spends) the counters, and window entries stamped in the "future" are brought back to now."""
        today = PacificDay.key(now)
        if today > self.day:
            if self.day:
                self.history[self.day] = {"requests": self.day_requests, "tokens": self.day_tokens}
                for old in sorted(self.history)[:-14]:
                    del self.history[old]
            self.day, self.day_requests, self.day_tokens = today, 0, 0
            self.spent_at, self.probe_step = 0.0, 0
        if self.exhausted_until > now and not self.spent_at and (self.exhausted_why.endswith("/day") or self.exhausted_why == "rpd"):
            self.exhausted_until = now                       # an old "out until midnight" that no 429 backs up: Google decides, by a try
        if self.exhausted_until and now >= self.exhausted_until:
            self.exhausted_until, self.exhausted_why = 0.0, ""
        for e in self.window:
            if e[0] > now:
                e[0] = now
        self.last_sent = min(self.last_sent, now)
        while self.window and self.window[0][0] < now - FORGET:
            self.window.popleft()

    def estimate_input(self, chars: int) -> int:
        """The tokens to reserve for a request of `chars` characters: the input estimate (+ the mean output when it counts)."""
        return int(chars * self.tokens_per_char) + 16 + int(self.out_estimate)

    def tpm_cap(self) -> float | None:
        """The per-minute token total aimed at (target x limit), None when the limit is unknown."""
        lim = self.limits().tpm
        return lim * self.target if lim else None

    def tpm_alone(self) -> float | None:
        """The most a request may weigh when it is ALONE in the minute: the limit itself without a target, else 92 %."""
        lim = self.limits().tpm
        return None if not lim else lim * (1.0 if self.target >= 1.0 else max(self.target, TPM_LONE))

    # ---- when can the next request go?
    def available_at(self, now: float, est_tokens: int) -> float:
        """The epoch second from which a request of `est_tokens` input tokens respects every limit (>= now)."""
        self.roll(now)
        if self.exhausted_until > now:
            return self.exhausted_until
        lim = self.limits()
        # The daily REQUEST count is never a wall here: a 15 Oct. test showed pools answering after their 500th request (the
        # console counted 777), so only Google's own 429 closes a pool (and the retries of `spend_day` reopen it).
        if lim.tpd is not None and self.day_tokens + est_tokens > lim.tpd and self.day_tokens > 0:
            self.exhaust(now, "tpd")
            return self.exhausted_until
        if lim.tpm and est_tokens > self.tpm_alone():     # this request alone is above the per-minute ceiling: waiting never helps
            return FAR
        t = max(now, self.blocked_until)
        if lim.rpm:
            t = max(t, self.last_sent + 60.0 / lim.rpm * self.margin)
            n = max(1, int(lim.rpm))
            if len(self.window) >= n:                     # the sliding minute, whatever the spacing was before a restart
                t = max(t, self.window[-n][0] + WINDOW + 0.5)
        if lim.tpm:
            cap = self.tpm_cap()
            live = [e for e in self.window if e[0] > t - WINDOW]
            total = sum(e[1] for e in live)
            for ts, tok in live:                          # oldest first: wait until enough of them have left the minute
                if total + est_tokens <= cap:
                    break
                total -= tok
                t = max(t, ts + WINDOW + 0.5)
        return t

    # ---- accounting
    def begin(self, now: float, est_tokens: int) -> list:
        """A request is sent: reserve its estimate. Returns the entry to hand back to settle()."""
        self.roll(now)
        entry = [now, int(est_tokens)]
        self.window.append(entry)
        self.last_sent = now
        self.day_requests += 1
        self.day_tokens += entry[1]
        return entry

    def settle(self, entry: list, input_tokens: int | None, chars: int = 0, extra_tokens: int = 0) -> None:
        """The answer arrived: replace the estimate by the measured tokens (None = the request failed early). The measured
        count is the input tokens, plus `extra_tokens` (output + thinking) when this pool counts them (`tpm_counts = "all"`).
        `entry` may be an entry of an earlier load of the ledger: it is found again in the window by its time."""
        extra = int(extra_tokens) if (self.counts_output and input_tokens) else 0
        real = entry[1] if input_tokens is None else int(input_tokens) + extra
        mine = next((e for e in self.window if e is entry), None) or next((e for e in self.window if e[0] == entry[0]), None)
        self.day_tokens = max(0, self.day_tokens + real - entry[1])
        if mine is not None:
            mine[1] = real
        entry[1] = real
        if input_tokens and chars:
            self.tokens_per_char = 0.7 * self.tokens_per_char + 0.3 * (input_tokens / chars)
        if input_tokens and self.counts_output:
            self.out_estimate = 0.9 * self.out_estimate + 0.1 * extra
        self.minute_429 = 0 if input_tokens else self.minute_429
        if input_tokens:
            self.client_errors = 0
            if self.spent_at:                                  # a request went through after a daily refusal: the pool is open again
                self.probe_log = (self.probe_log + [[round(entry[0], 1), 200, self.probe_step]])[-40:]
                self.spent_at, self.probe_step = 0.0, 0
                self.exhausted_until, self.exhausted_why = 0.0, ""

    # ---- errors
    def exhaust(self, now: float, why: str, until: float | None = None) -> None:
        self.exhausted_until = until if until is not None else PacificDay.next_reset(now)
        self.exhausted_why = why

    def spend_day(self, now: float, why: str, delay: float | None = None) -> float:
        """Google refused this pool for the day. It is not shut until midnight (a pool answered after its 500th request on
        15 Oct.): it is tried again after 10, 20, 30, then every 60 minutes, and reopens as soon as a request goes through.
        Each refusal is logged in `probe_log`, so the real reopening time can be read. -> the delay."""
        self.roll(now)
        if delay is None:
            delay = PROBE_STEPS[min(self.probe_step, len(PROBE_STEPS) - 1)]
        if not self.spent_at:
            self.spent_at = now
        self.probe_log = (self.probe_log + [[round(now, 1), 429, self.probe_step]])[-40:]
        self.probe_step += 1
        self.exhaust(now, why, until=now + delay)
        return delay

    def block(self, now: float, seconds: float) -> None:
        self.blocked_until = max(self.blocked_until, now + seconds)

    def learn(self, field: str, value: float | None) -> None:
        """A limit is learned ONLY from an explicit quotaValue, and only downwards (limits() takes min(file, learned))."""
        if value is None or value < 0:
            return
        learned = self.learned.to_dict()
        new = value if field == "rpm" else int(value)
        learned[field] = min(learned.get(field, new), new)
        self.learned = Limits.from_dict(learned)

    def on_quota_error(self, now: float, err: QuotaError) -> str:
        """A 429. Returns a short description of what was decided. Without an explicit limit nothing is learned: the
        model is only blocked for the delay Google gave (a day: until the Pacific midnight)."""
        self.roll(now)
        said = err.limit if err.limit is not None else "not said"
        if err.scope == "day" and err.limit == 0:               # a limit of ZERO is no free tier at all: that one is final for the day
            self.learn("rpd" if err.kind == "requests" else "tpd", 0)
            self.exhaust(now, f"{err.kind}/day")
            self.spent_at = self.spent_at or now                # (so that the old-state rule in roll() does not reopen it)
            return f"{err.kind} per day: limit 0 (not free), until the Pacific midnight"
        if err.scope == "day":
            delay = self.spend_day(now, f"{err.kind}/day", err.reset_after + 5.0 if err.reset_after else None)   # the limit Google names is shown, never trusted as a wall
            return f"{err.kind} per day refused (limit {said}); tried again in {delay / 60:.0f} min"
        self.minute_429 += 1
        self.learn("rpm" if err.kind == "requests" else "tpm", err.limit)
        wait = min(max(err.retry_after or WINDOW, MINUTE_BLOCK[0]), MINUTE_BLOCK[1]) + 1.0
        if self.minute_429 >= 3:
            wait = max(wait, LONG_BLOCK)
        self.block(now, wait)
        return f"{err.kind} per minute (limit {said}), wait {wait:.0f} s"

    # ---- persistence
    def to_dict(self) -> dict:
        return {"learned": self.learned.to_dict(), "window": [list(e) for e in self.window], "last_sent": self.last_sent,
                "day": self.day, "day_requests": self.day_requests, "day_tokens": self.day_tokens,
                "exhausted_until": self.exhausted_until, "exhausted_why": self.exhausted_why,
                "blocked_until": self.blocked_until, "minute_429": self.minute_429, "client_errors": self.client_errors,
                "tokens_per_char": round(self.tokens_per_char, 5), "out_estimate": round(self.out_estimate, 1),
                "history": self.history, "spent_at": self.spent_at, "probe_step": self.probe_step, "probe_log": self.probe_log}

    def load(self, d: dict) -> None:
        """Strictly typed: a badly typed field raises QuotaFileError and leaves the book untouched."""
        if not isinstance(d, dict):
            raise QuotaFileError("a book is an object")
        try:
            learned = Limits.from_dict(d.get("learned", {}))
            window = deque([_num(a), int(_num(b))] for a, b in d.get("window", []))
            last_sent = _num(d.get("last_sent", 0.0))
            day = d.get("day", "")
            if not isinstance(day, str):
                raise QuotaFileError("day must be a string")
            day_requests, day_tokens = int(_num(d.get("day_requests", 0))), int(_num(d.get("day_tokens", 0)))
            exhausted_until, blocked_until = _num(d.get("exhausted_until", 0.0)), _num(d.get("blocked_until", 0.0))
            why = d.get("exhausted_why", "")
            if not isinstance(why, str):
                raise QuotaFileError("exhausted_why must be a string")
            minute_429, client_errors = int(_num(d.get("minute_429", 0))), int(_num(d.get("client_errors", 0)))
            tpc = _num(d.get("tokens_per_char", self.tokens_per_char))
            history = d.get("history", {})
            out_est = _num(d.get("out_estimate", self.out_estimate))
            spent_at, probe_step = _num(d.get("spent_at", 0.0)), int(_num(d.get("probe_step", 0)))
            probe_log = [[_num(a), int(_num(b)), int(_num(c))] for a, b, c in d.get("probe_log", [])]
            if not isinstance(history, dict) or tpc <= 0 or out_est < 0:
                raise QuotaFileError("history must be an object, tokens_per_char positive")
            for lim in learned.to_dict().values():
                _num(lim)
        except (TypeError, ValueError, AttributeError) as e:
            raise QuotaFileError(str(e)) from None
        self.learned, self.window, self.last_sent, self.day = learned, window, last_sent, day
        self.day_requests, self.day_tokens = day_requests, day_tokens
        self.exhausted_until, self.exhausted_why, self.blocked_until = exhausted_until, why, blocked_until
        self.minute_429, self.client_errors, self.tokens_per_char, self.history = minute_429, client_errors, tpc, dict(history)
        self.out_estimate = out_est if self.counts_output else 0.0
        self.spent_at, self.probe_step, self.probe_log = spent_at, probe_step, probe_log


class QuotaFileError(ValueError):
    """quota.json (or one book of it) is damaged or badly typed."""


def _num(x) -> float:
    if isinstance(x, bool) or not isinstance(x, (int, float)) or x != x or abs(x) == float("inf"):
        raise QuotaFileError(f"{x!r} is not a finite number")
    return float(x)


# ---------------------------------------------------------------------------------------------------- merging old books
def merge_book_dicts(books: list[dict]) -> dict:
    """ONE persisted book from several (the old per-series quota.json files, the names of one pool): the requests and tokens of
    the same Pacific day are ADDED (they were spent on the same key), the learned limits are the lowest, the cooldowns the
    latest. Nothing is lost: the older days go to `history`."""
    days: dict = {}

    def add(day, requests, tokens):
        if isinstance(day, str) and day:
            r, t = days.get(day, (0, 0))
            days[day] = (r + int(requests or 0), t + int(tokens or 0))

    for d in books:
        add(d.get("day"), d.get("day_requests"), d.get("day_tokens"))
        for day, h in (d.get("history") or {}).items():
            add(day, (h or {}).get("requests"), (h or {}).get("tokens"))
    base = dict(max(books, key=lambda d: float(d.get("last_sent", 0) or 0)))
    current = max(days) if days else ""
    base["day"] = current
    base["day_requests"], base["day_tokens"] = days.pop(current, (0, 0)) if current else (0, 0)
    base["history"] = {day: {"requests": r, "tokens": t} for day, (r, t) in sorted(days.items())[-14:]}
    learned: dict = {}
    for d in books:
        for k, v in (d.get("learned") or {}).items():
            learned[k] = min(learned.get(k, v), v)
    base["learned"] = learned
    base["window"] = sorted(([float(a), int(b)] for d in books for a, b in d.get("window", [])), key=lambda e: e[0])
    for k in ("last_sent", "blocked_until", "minute_429", "client_errors"):
        base[k] = max(d.get(k, 0) or 0 for d in books)
    longest = max(books, key=lambda d: float(d.get("exhausted_until", 0) or 0))
    base["exhausted_until"], base["exhausted_why"] = longest.get("exhausted_until", 0.0), longest.get("exhausted_why", "")
    return base


# ---------------------------------------------------------------------------------------------------- all models
@dataclass
class Choice:
    model: str
    at: float                   # epoch second from which it can be used (<= now: right away)
    all_exhausted: bool = False  # every model is out until a reset


class QuotaDesk:
    """The books of all the models of the chain, in preference order, and the ledger file they live in.

    `books[name]` is the book of the POOL of that name: two names of one pool give the same object. With a `path` the books
    are those of a GLOBAL LEDGER shared by every process: any change goes through `with desk.transaction():` (flock, fresh
    read, change, atomic write); `choose` and `table` do it themselves. Without a `path` the desk lives in memory (tests)."""

    def __init__(self, config: QuotaConfig, path: Path | str | None = None, journal: Path | str | None = None,
                 now: float | None = None, legacy: list | None = None, journals: list | None = None, clock=time.time):
        self.config, self.clock = config, clock
        self.path = Path(path) if path else None
        self.journals = list(dict.fromkeys(Path(j).resolve() for j in [*(journals or []), *([journal] if journal else [])]))
        if self.path and legacy is None:
            legacy = sorted(self.path.parent.glob("*/quota.json"))
        self.legacy = [Path(p) for p in (legacy or [])]
        self.rebuilt: list[str] = []                 # the pools rebuilt from the journals because the file was damaged
        self.migrated: list[str] = []                # the old quota.json files whose counters were taken into the ledger
        self.aliases: dict = {}                      # name -> pool, learned from the quotaDimensions of 429 answers
        self.specs = {s.name: s for s in config.models}
        self.pools: dict = {}
        self.books: dict = {}
        self._depth = 0
        self._foreign: dict = {}                     # the pools of the file that this chain does not use: kept as they are
        self._text = ""
        self._build_books()
        if self.path:
            with self.transaction(now):
                pass

    # ---- the books
    def _build_books(self) -> None:
        pools, books = {}, {}
        for s in self.config.models:
            pool = self.config.pool_of(s.name, self.aliases)
            if pool not in pools:
                old = self.pools.get(pool)
                pools[pool] = old or QuotaBook(self.config.pool_spec(pool, s), self.config.margin, self.config.tpm_target)
            books[s.name] = pools[pool]
        self.pools, self.books = pools, books

    @property
    def order(self) -> list[str]:
        return [s.name for s in self.config.models]

    def spec(self, model: str) -> ModelSpec:
        """The spec of the NAME (strategy, max_k, compact...); its limits are those of its pool (`books[model].limits()`)."""
        return self.specs[model]

    def pool_of(self, model: str) -> str:
        return self.books[model].name

    def learn_pool(self, model: str, pool: str) -> bool:
        """A 429 named the model whose quota was spent (quotaDimensions.model): `model` is an alias of `pool`. Remembered in the
        ledger; the counters already kept under the alias are added to the pool. True when something changed."""
        pool = (pool or "").strip()
        if not pool or pool == model or self.config.pool_of(model, self.aliases) == pool:
            return False
        with self.transaction():
            lonely = self.books[model]
            self.aliases[model] = pool
            existed = pool in self.pools
            self._build_books()
            joined = self.books[model]
            if joined is not lonely:
                joined.load(merge_book_dicts([joined.to_dict(), lonely.to_dict()]) if existed else lonely.to_dict())
        return True

    def learn_from_violations(self, model: str, violations: list) -> str:
        """The pool named by the first violation of a 429 that carries a quotaDimensions.model; '' when none changed."""
        for v in violations or []:
            real = (v.get("quotaDimensions") or {}).get("model") if isinstance(v, dict) else None
            if real and self.learn_pool(model, str(real)):
                return str(real)
        return ""

    # ---- choosing
    def choose(self, now: float, chars: int, only: str | None = None, chars_for=None) -> Choice:
        """The model that can answer first (ties go to the preference order). `only` restricts the choice to one model.
        `chars_for(name)` gives the size of the request FOR THAT MODEL when it differs (compact instructions)."""
        with self.transaction(now):
            best, best_at = None, FAR
            for name in ([only] if only else self.order):
                b = self.books[name]
                at = b.available_at(now, b.estimate_input(chars_for(name) if chars_for else chars))
                if at < best_at - 0.25:
                    best, best_at = name, at
            exhausted = all(self.books[n].exhausted_until > now for n in ([only] if only else self.order))
            return Choice(best, best_at, exhausted)

    def next_reset(self, now: float) -> float:
        with self.transaction(now):
            return min((b.exhausted_until for b in self.books.values() if b.exhausted_until > now),
                       default=PacificDay.next_reset(now))

    # ---- the ledger file
    @contextmanager
    def transaction(self, now: float | None = None):
        """Exclusive access to the ledger: lock, read it fresh, let the caller change the books, write if anything moved,
        unlock. Re-entrant. In memory (no path) it does nothing."""
        if not self.path:
            yield self
            return
        if self._depth:
            self._depth += 1
            try:
                yield self
            finally:
                self._depth -= 1
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path.with_name(self.path.name + ".lock"), os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o644)
        try:
            waited = 0.0
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError:
                    if waited >= LOCK_TIMEOUT:
                        raise TimeoutError(f"the quota ledger {self.path} stayed locked for {LOCK_TIMEOUT:.0f} s") from None
                    time.sleep(0.02)
                    waited += 0.02
            self._read(self.clock() if now is None else now)
            self._depth = 1
            try:
                yield self
            finally:
                self._depth = 0
                self._write()
        finally:
            os.close(fd)                                  # closing the descriptor releases the flock

    def save(self) -> None:
        """Kept for the callers that used to write quota.json: with a ledger every change is already written when its
        transaction ends, so this only refreshes the books from the file."""
        if self.path:
            with self.transaction():
                pass

    def _read(self, now: float) -> None:
        text, fresh, doc = "", False, None
        try:
            text = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            fresh = True
        except OSError:
            text = ""
        if fresh:
            doc = {"pools": self._migrate()}
        else:
            try:
                doc = json.loads(text)
            except ValueError:
                doc = None
            if not isinstance(doc, dict) or not isinstance(doc.get("pools", {}), dict):
                doc = None                                   # damaged: nothing is trusted, today's counters come from the journals
        aliases = doc.get("aliases", {}) if doc else {}
        self.aliases = {k: v for k, v in aliases.items() if isinstance(k, str) and isinstance(v, str)} if isinstance(aliases, dict) else {}
        self._build_books()
        damaged = list(self.pools) if doc is None else []
        pools = doc.get("pools", {}) if doc else {}
        unknown = []                                        # a new ledger: the pools that no old file had are read from the journals
        for name, book in self.pools.items():
            if name in pools:
                try:
                    book.load(pools[name])
                except QuotaFileError:
                    damaged.append(name)
            elif fresh:
                unknown.append(name)
        if damaged:
            self.rebuild(damaged, now)
        if unknown:
            self.rebuild(unknown, now, report=False)
        self._foreign = {k: v for k, v in pools.items() if k not in self.pools}
        if doc and isinstance(doc.get("migrated"), list):
            self.migrated = [str(x) for x in doc["migrated"]]
        self._text = text

    def _document(self) -> dict:
        doc = {"schema": LEDGER_SCHEMA, "pools": {**self._foreign, **{n: b.to_dict() for n, b in self.pools.items()}}}
        if self.aliases:
            doc["aliases"] = dict(sorted(self.aliases.items()))
        if self.migrated:
            doc["migrated"] = list(self.migrated)
        return doc

    def _write(self) -> None:
        """temp file, fsync, rename, fsync of the folder: a power cut leaves the old file or the new one, never half.
        Nothing is written when nothing changed."""
        text = json.dumps(self._document(), indent=1)
        if text == self._text:
            return
        tmp = self.path.with_name(self.path.name + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.path)
        try:
            fd = os.open(self.path.parent, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        except OSError:
            pass
        self._text = text

    def _migrate(self) -> dict:
        """The ledger does not exist yet: the counters of every old <series>/quota.json, merged by pool (nothing is deleted)."""
        groups: dict = {}
        for p in self.legacy:
            try:
                doc = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            models = doc.get("models") if isinstance(doc, dict) else None
            if not isinstance(models, dict):
                continue
            taken = False
            for name, d in models.items():
                if isinstance(d, dict):
                    groups.setdefault(self.config.pool_of(name, self.aliases), []).append(d)
                    taken = True
            if taken:
                self.migrated.append(str(p))
        out = {}
        for pool, ds in groups.items():
            try:
                out[pool] = merge_book_dicts(ds)
            except (TypeError, ValueError, AttributeError):
                continue                                    # a badly typed old book is rebuilt from the journals below
        return out

    def rebuild(self, names: list[str], now: float, report: bool = True) -> None:
        """The books of these pools: today's counters rebuilt from the journals (`pday`) of every series."""
        today = PacificDay.key(now)
        for n in names:
            b = self.pools[n]
            b.day = today
            b.day_requests = b.day_tokens = 0
        want = set(names)
        for journal in self.journals:
            if not journal.exists():
                continue
            marker = f'"pday":"{today}"'
            with open(journal, encoding="utf-8", errors="replace") as f:
                for line in f:
                    if marker not in line:
                        continue
                    try:
                        r = json.loads(line)
                        model, kind = r["model"], r["kind"]
                    except (ValueError, KeyError, TypeError):
                        continue
                    pool = self.config.pool_of(model, self.aliases)
                    if pool not in want or kind not in ("batch", "repair", "error") or r.get("pday") != today:
                        continue
                    b = self.pools[pool]
                    u = r.get("usage", {}) if kind != "error" else {}
                    tokens = int(u.get("prompt", 0)) + (int(u.get("output", 0)) + int(u.get("thoughts", 0)) if b.counts_output else 0)
                    b.day_requests += 1
                    b.day_tokens += tokens
                    ts = float(r.get("ts", 0))
                    if ts > now - WINDOW:
                        b.window.append([min(ts, now), tokens])
                    b.last_sent = max(b.last_sent, min(ts, now))
        if report:
            self.rebuilt = sorted(set(self.rebuilt) | want)

    # ---- display
    def table(self, now: float) -> list[dict]:
        rows = []
        with self.transaction(now):
            for n in self.order:
                b = self.books[n]
                b.roll(now)
                lim = b.limits()
                rows.append({"model": n, "pool": b.name, "day": b.day, "requests": b.day_requests, "input_tokens": b.day_tokens,
                             "limits": lim.to_dict(), "learned": b.learned.to_dict(),
                             "exhausted_until": b.exhausted_until if b.exhausted_until > now else 0.0, "why": b.exhausted_why,
                             "blocked_for_s": round(max(0.0, b.blocked_until - now), 1),
                             "probe_log": [list(e) for e in b.probe_log], "spent_at": b.spent_at})
        return rows


# ---------------------------------------------------------------------------------------------------- the one-shot tools
class LedgerGate:
    """probe, bench and pilot send a few requests with their own pacing; this puts them in the SAME ledger as the generators.
    It wraps the client: `generate` / `post_generate` first wait (up to `max_wait` seconds) until the pool may answer, count the
    request before it leaves, and settle / classify the answer after. A pool that is out for the day is not asked: the call
    comes back as a local 429 (scope "day"), which every tool already knows how to read. Everything else is the client's."""

    def __init__(self, client, desk: QuotaDesk, clock=time.time, sleep=time.sleep, max_wait: float = 130.0, log=lambda s: None):
        self.client, self.desk, self.clock, self.sleep, self.max_wait, self.log = client, desk, clock, sleep, max_wait, log

    def __getattr__(self, name):
        return getattr(self.client, name)

    @classmethod
    def for_tool(cls, client, names, quota_file=DEFAULT_CONFIG, ledger=None, **kw):
        """The client put in the shared ledger for the models of `names` that quota.toml lists (the others go through uncounted).
        Without any listed model the client itself is returned."""
        qc = QuotaConfig.load(quota_file)
        known = [n for n in dict.fromkeys(names) if qc.spec_of(n)]
        if not known:
            return client
        return cls(client, QuotaDesk(qc.only(known), ledger or DEFAULT_LEDGER), **kw)

    def _enter(self, model: str, chars: int):
        """-> (entry, None) when the request may go, else (None, the local ApiResult to hand back)."""
        from .gemini import ApiResult
        book = self.desk.books.get(model)
        if book is None:
            return None, None                                   # a name the chain does not list: not counted
        waited = 0.0
        while True:
            now = self.clock()
            with self.desk.transaction(now):
                at = book.available_at(now, book.estimate_input(chars))
                if at <= now:
                    return book.begin(now, book.estimate_input(chars)), None
                out_for_day = book.exhausted_until > now
            if at == FAR or out_for_day or waited + (at - now) > self.max_wait:
                scope = "day" if (out_for_day or at == FAR) else "minute"
                return None, ApiResult(False, 429, error=f"LOCAL LEDGER {model}: not before {at - now:.0f} s ({book.exhausted_why or 'rate'})",
                                       quota_scope=scope, retry_after=max(0.0, at - now) if at != FAR else 0.0)
            self.sleep(at - now)
            waited += at - now

    def _leave(self, model: str, entry, status: int, usage: dict, chars: int, violations: list, message: str, retry: float) -> None:
        book = self.desk.books.get(model)
        if book is None or entry is None:
            return
        now = self.clock()
        with self.desk.transaction(now):
            if status == 200:
                extra = int(usage.get("candidatesTokenCount", 0) or 0) + int(usage.get("thoughtsTokenCount", 0) or 0)
                book.settle(entry, usage.get("promptTokenCount"), chars, extra)
                return
            book.settle(entry, 0)
            if status == 429:
                self.desk.learn_from_violations(model, violations)             # an alias joins the pool the 429 names
                self.desk.books[model].on_quota_error(now, QuotaError.parse(violations, message, "", retry))
            elif status == 404:
                book.exhaust(now, "not found", until=now + 24 * 3600)

    def generate(self, model, system, user, schema, *args, **kw):
        chars = len(system) + len(user) + len(json.dumps(schema))
        entry, local = self._enter(model, chars)
        if local is not None:
            return local
        r = self.client.generate(model, system, user, schema, *args, **kw)
        self._leave(model, entry, r.status, r.usage, chars, r.quota_violations, r.error, r.retry_after)
        return r

    def post_generate(self, model, body):
        chars = len(json.dumps(body))
        entry, local = self._enter(model, chars)
        if local is not None:
            return 429, {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "message": local.error}}, 0.0
        status, payload, latency = self.client.post_generate(model, body)
        err = payload.get("error", {}) if isinstance(payload, dict) and status == 429 else {}
        err = err if isinstance(err, dict) else {}
        violations = self.client.quota_violations(err) if status == 429 else []
        scope, retry = self.client.classify_quota(err) if status == 429 else ("", 0.0)
        usage = payload.get("usageMetadata", {}) if isinstance(payload, dict) else {}
        self._leave(model, entry, status, usage, chars, violations, str(err.get("message", "")), retry)
        return status, payload, latency
