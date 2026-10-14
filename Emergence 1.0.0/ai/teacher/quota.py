"""quota.py - the free-tier quotas of every model, kept exactly: RPM, RPD, TPM, TPD.

    Limits         the four limits of one model (None = unknown, to be learned from the 429 answers)
    PacificDay     the quota day: it resets at midnight, America/Los_Angeles
    QuotaError     a 429 classified from its body (quotaMetric / quotaId): per minute or per day, requests or tokens
    QuotaBook      ONE model: sliding one-minute window, day counters, cooldowns, learned limits; persisted as a dict
    QuotaDesk      every model: which one can answer first, and when; load / save of quota.json

Nothing here sleeps or calls the network: the caller gives `now` (epoch seconds) and decides how to wait, so the whole
logic is tested with a fake clock.

What counts:
  * requests: each sent request, in a sliding 60 s window (RPM) and in the Pacific day (RPD). The spacing between two
    requests of a model is 60 / rpm x margin, so a burst never happens;
  * tokens: the INPUT tokens (promptTokenCount, cached ones included, as a safety); the estimate (characters x the
    ratio measured on this model) is reserved when the request is sent and replaced by the measured count when the
    answer arrives (TPM: sliding window, TPD: Pacific day).

A 429 is read from the error body, never guessed: `quotaId` ends in PerMinute... or PerDay...; `quotaMetric`/`quotaId`
mention requests or tokens; `quotaValue` is the limit, which is learned (and persisted). A per-minute 429 blocks the model
for the delay Google gives (3 in a row: 10 minutes); a per-day 429 exhausts the model until the next Pacific midnight.
"""
from __future__ import annotations

import json
import os
import re
import time
import tomllib
from collections import deque
from dataclasses import dataclass
from datetime import datetime, time as dtime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .gemini import STRUCTURED, ModelFamilies, ModelFamily, PromptOnlyStrategy, RequestStrategy

PACIFIC = ZoneInfo("America/Los_Angeles")
DEFAULT_CONFIG = Path(__file__).with_name("quota.toml")
WINDOW = 60.0
FORGET = 120.0                  # entries older than this leave the window
RESET_MARGIN = 3.0              # seconds after midnight before a model is used again
MINUTE_BLOCK = (2.0, 120.0)     # clamp of the delay Google asks for
LONG_BLOCK = 600.0              # 3 per-minute 429 in a row: something else is going on, leave the model alone for 10 min
FAR = float("inf")


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
    what the probe OBSERVED. enabled = False keeps the model listed (with its `note`, the reason) but out of the chain."""
    name: str
    limits: Limits
    thinking_budget: int | None = None
    system_instruction: bool | None = None
    json_schema: bool | None = None
    enabled: bool = True
    note: str = ""
    max_k: int | None = None            # a model that only takes SMALL batches (e.g. a tight tokens-per-minute limit): at most this many situations

    @property
    def family(self) -> ModelFamily:
        return ModelFamilies.of(self.name)

    def strategy(self) -> RequestStrategy:
        """Structured JSON when the model accepts systemInstruction and a response schema, else the prompt-only way."""
        fam = self.family
        system = fam.system_instruction if self.system_instruction is None else self.system_instruction
        schema = fam.json_schema if self.json_schema is None else self.json_schema
        if system and schema:
            return STRUCTURED
        return PromptOnlyStrategy(fold_system=not system, fold_schema=not schema, thinking_config=fam.thinking_config)


@dataclass(frozen=True)
class QuotaConfig:
    models: tuple                                   # the enabled models, in order of preference (the chain)
    margin: float = 1.05
    disabled: tuple = ()                            # listed but off (enabled = false), with their reason in `note`

    @classmethod
    def load(cls, path: Path | str = DEFAULT_CONFIG) -> "QuotaConfig":
        raw = tomllib.loads(Path(path).read_text(encoding="utf-8"))
        specs = [ModelSpec(m["name"], Limits.from_dict(m), m.get("thinking_budget"), m.get("system_instruction"),
                           m.get("json_schema"), bool(m.get("enabled", True)), str(m.get("note", "")), m.get("max_k")) for m in raw.get("model", [])]
        names = [s.name for s in specs]
        if len(set(names)) != len(names):
            raise ValueError(f"{path}: a model is listed twice")
        on = tuple(s for s in specs if s.enabled)
        if not on:
            raise ValueError(f"{path}: no enabled [[model]]")
        return cls(on, float(raw.get("margin", 1.05)), tuple(s for s in specs if not s.enabled))

    def only(self, names: list[str]) -> "QuotaConfig":
        """The listed models, in that order (a disabled model named here is used; an unlisted one gets the Flash Lite defaults)."""
        by = {s.name: s for s in (*self.models, *self.disabled)}
        return QuotaConfig(tuple(by.get(n) or ModelSpec(n, Limits(15, 500) if "lite" in n else Limits(5, 20)) for n in names),
                           self.margin)

    def install(self, client) -> None:
        """Teach the client how to ask each model (structured, or prompt-only)."""
        for s in (*self.models, *self.disabled):
            client.strategies[s.name] = s.strategy()


# ---------------------------------------------------------------------------------------------------- a 429
@dataclass(frozen=True)
class QuotaError:
    scope: str                  # "minute" | "day"
    kind: str                   # "requests" | "tokens"
    limit: float | None         # quotaValue, when Google says it
    retry_after: float          # seconds asked for (0 = not said)
    metric: str = ""

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
            found.append((scope, kind, limit, str(v.get("quotaMetric", "") or v.get("quotaId", ""))))
        m = message or ""
        msg_scope = "day" if re.search(r"per ?day|daily", m, re.I) else "minute" if re.search(r"per ?minute", m, re.I) else ""
        msg_kind = "tokens" if re.search(r"token", m, re.I) else "requests" if re.search(r"request", m, re.I) else ""
        if not retry_after:
            r = re.search(r"retry in (\d+(?:\.\d+)?)\s*s", m, re.I)
            retry_after = float(r.group(1)) if r else 0.0
        if found:
            found.sort(key=lambda f: (f[0] != "day", f[0] == ""))
            scope, kind, limit, metric = found[0]
        else:
            scope, kind, limit, metric = "", "", None, ""
        scope = scope or msg_scope or scope_hint or "minute"
        kind = kind or msg_kind or "requests"
        return cls(scope, kind, limit, retry_after, metric)


# ---------------------------------------------------------------------------------------------------- one model
class QuotaBook:
    """Everything known about one model's quota. All times are epoch seconds given by the caller."""

    def __init__(self, spec: ModelSpec, margin: float = 1.05):
        self.spec, self.margin = spec, margin
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
        if self.exhausted_until and now >= self.exhausted_until:
            self.exhausted_until, self.exhausted_why = 0.0, ""
        for e in self.window:
            if e[0] > now:
                e[0] = now
        self.last_sent = min(self.last_sent, now)
        while self.window and self.window[0][0] < now - FORGET:
            self.window.popleft()

    def estimate_input(self, chars: int) -> int:
        return int(chars * self.tokens_per_char) + 16

    # ---- when can the next request go?
    def available_at(self, now: float, est_tokens: int) -> float:
        """The epoch second from which a request of `est_tokens` input tokens respects every limit (>= now)."""
        self.roll(now)
        if self.exhausted_until > now:
            return self.exhausted_until
        lim = self.limits()
        if lim.rpd is not None and self.day_requests >= lim.rpd:
            self.exhaust(now, "rpd")
            return self.exhausted_until
        if lim.tpd is not None and self.day_tokens + est_tokens > lim.tpd and self.day_tokens > 0:
            self.exhaust(now, "tpd")
            return self.exhausted_until
        if lim.tpm and est_tokens > lim.tpm:              # this request alone is above the per-minute ceiling: waiting never helps
            return FAR
        t = max(now, self.blocked_until)
        if lim.rpm:
            t = max(t, self.last_sent + 60.0 / lim.rpm * self.margin)
            n = max(1, int(lim.rpm))
            if len(self.window) >= n:                     # the sliding minute, whatever the spacing was before a restart
                t = max(t, self.window[-n][0] + WINDOW + 0.5)
        if lim.tpm:
            live = [e for e in self.window if e[0] > t - WINDOW]
            total = sum(e[1] for e in live)
            for ts, tok in live:                          # oldest first: wait until enough of them have left the minute
                if total + est_tokens <= lim.tpm:
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

    def settle(self, entry: list, input_tokens: int | None, chars: int = 0) -> None:
        """The answer arrived: replace the estimate by the measured input tokens (None = the request failed early)."""
        real = entry[1] if input_tokens is None else int(input_tokens)
        self.day_tokens += real - entry[1]
        entry[1] = real
        if input_tokens and chars:
            self.tokens_per_char = 0.7 * self.tokens_per_char + 0.3 * (input_tokens / chars)
        self.minute_429 = 0 if input_tokens else self.minute_429
        if input_tokens:
            self.client_errors = 0

    # ---- errors
    def exhaust(self, now: float, why: str, until: float | None = None) -> None:
        self.exhausted_until = until if until is not None else PacificDay.next_reset(now)
        self.exhausted_why = why

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
        if err.scope == "day":
            self.learn("rpd" if err.kind == "requests" else "tpd", err.limit)
            self.exhaust(now, f"{err.kind}/day")
            return f"{err.kind} per day spent (limit {said}), until the Pacific midnight"
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
                "tokens_per_char": round(self.tokens_per_char, 5), "history": self.history}

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
            if not isinstance(history, dict) or tpc <= 0:
                raise QuotaFileError("history must be an object, tokens_per_char positive")
            for lim in learned.to_dict().values():
                _num(lim)
        except (TypeError, ValueError, AttributeError) as e:
            raise QuotaFileError(str(e)) from None
        self.learned, self.window, self.last_sent, self.day = learned, window, last_sent, day
        self.day_requests, self.day_tokens = day_requests, day_tokens
        self.exhausted_until, self.exhausted_why, self.blocked_until = exhausted_until, why, blocked_until
        self.minute_429, self.client_errors, self.tokens_per_char, self.history = minute_429, client_errors, tpc, dict(history)


class QuotaFileError(ValueError):
    """quota.json (or one book of it) is damaged or badly typed."""


def _num(x) -> float:
    if isinstance(x, bool) or not isinstance(x, (int, float)) or x != x or abs(x) == float("inf"):
        raise QuotaFileError(f"{x!r} is not a finite number")
    return float(x)


# ---------------------------------------------------------------------------------------------------- all models
@dataclass
class Choice:
    model: str
    at: float                   # epoch second from which it can be used (<= now: right away)
    all_exhausted: bool = False  # every model is out until a reset


class QuotaDesk:
    """The books of all the models, in preference order, and their file."""

    def __init__(self, config: QuotaConfig, path: Path | str | None = None, journal: Path | str | None = None,
                 now: float | None = None):
        self.config = config
        self.books = {s.name: QuotaBook(s, config.margin) for s in config.models}
        self.path = Path(path) if path else None
        self.journal = Path(journal) if journal else None
        self.rebuilt: list[str] = []                 # the books rebuilt from the journal because the file was damaged
        if self.path:
            self.load(time.time() if now is None else now)

    @property
    def order(self) -> list[str]:
        return [s.name for s in self.config.models]

    def spec(self, model: str) -> ModelSpec:
        return self.books[model].spec

    def choose(self, now: float, chars: int, only: str | None = None) -> Choice:
        """The model that can answer first (ties go to the preference order). `only` restricts the choice to one model."""
        best, best_at = None, FAR
        for name in ([only] if only else self.order):
            b = self.books[name]
            at = b.available_at(now, b.estimate_input(chars))
            if at < best_at - 0.25:
                best, best_at = name, at
        exhausted = all(self.books[n].exhausted_until > now for n in ([only] if only else self.order))
        return Choice(best, best_at, exhausted)

    def next_reset(self, now: float) -> float:
        return min((b.exhausted_until for b in self.books.values() if b.exhausted_until > now), default=PacificDay.next_reset(now))

    # ---- file
    def save(self) -> None:
        """temp file, fsync, rename, fsync of the folder: a power cut leaves the old file or the new one, never half."""
        if not self.path:
            return
        doc = {"schema": 1, "models": {n: b.to_dict() for n, b in self.books.items()}}
        tmp = self.path.with_name(self.path.name + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(json.dumps(doc, indent=1))
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

    def load(self, now: float) -> None:
        """A damaged file, or a badly typed book, is not trusted: that book's counters of TODAY are rebuilt from
        journal.jsonl (`pday`), so a corrupt quota.json cannot make the generator forget what it already spent."""
        doc = None
        if self.path.exists():
            try:
                doc = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                doc = None
            if not isinstance(doc, dict) or not isinstance(doc.get("models", {}), dict):
                doc = None
            damaged = list(self.books) if doc is None else []
        else:
            damaged = list(self.books) if self.journal and self.journal.exists() else []   # file lost, journal there
        if doc is not None:
            for name, d in doc["models"].items():
                if name in self.books:
                    try:
                        self.books[name].load(d)
                    except QuotaFileError:
                        damaged.append(name)
        if damaged:
            self.rebuild(damaged, now)

    def rebuild(self, names: list[str], now: float) -> None:
        today = PacificDay.key(now)
        for n in names:
            b = self.books[n]
            b.day = today
            b.day_requests = b.day_tokens = 0
        want = set(names)
        if self.journal and self.journal.exists():
            marker = f'"pday":"{today}"'
            with open(self.journal, encoding="utf-8", errors="replace") as f:
                for line in f:
                    if marker not in line:
                        continue
                    try:
                        r = json.loads(line)
                        model, kind = r["model"], r["kind"]
                    except (ValueError, KeyError, TypeError):
                        continue
                    if model not in want or kind not in ("batch", "repair", "error") or r.get("pday") != today:
                        continue
                    b = self.books[model]
                    tokens = int(r.get("usage", {}).get("prompt", 0)) if kind != "error" else 0
                    b.day_requests += 1
                    b.day_tokens += tokens
                    ts = float(r.get("ts", 0))
                    if ts > now - WINDOW:
                        b.window.append([min(ts, now), tokens])
                    b.last_sent = max(b.last_sent, min(ts, now))
        self.rebuilt = sorted(set(self.rebuilt) | want)

    # ---- display
    def table(self, now: float) -> list[dict]:
        rows = []
        for n in self.order:
            b = self.books[n]
            b.roll(now)
            lim = b.limits()
            rows.append({"model": n, "day": b.day, "requests": b.day_requests, "input_tokens": b.day_tokens,
                         "limits": lim.to_dict(), "learned": b.learned.to_dict(),
                         "exhausted_until": b.exhausted_until if b.exhausted_until > now else 0.0, "why": b.exhausted_why,
                         "blocked_for_s": round(max(0.0, b.blocked_until - now), 1)})
        return rows
