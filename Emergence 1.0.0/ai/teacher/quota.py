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
import tomllib
from collections import deque
from dataclasses import dataclass
from datetime import datetime, time as dtime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

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

    def over(self, other: "Limits") -> "Limits":
        """self, with every field that `other` knows replaced."""
        return Limits(*(getattr(other, n) if getattr(other, n) is not None else getattr(self, n) for n in self.NAMES))

    def to_dict(self) -> dict:
        return {n: getattr(self, n) for n in self.NAMES if getattr(self, n) is not None}

    @classmethod
    def from_dict(cls, d: dict) -> "Limits":
        return cls(**{n: d[n] for n in cls.NAMES if d.get(n) is not None})


@dataclass(frozen=True)
class ModelSpec:
    name: str
    limits: Limits
    thinking_budget: int | None = None


@dataclass(frozen=True)
class QuotaConfig:
    models: tuple
    margin: float = 1.05

    @classmethod
    def load(cls, path: Path | str = DEFAULT_CONFIG) -> "QuotaConfig":
        raw = tomllib.loads(Path(path).read_text(encoding="utf-8"))
        specs = [ModelSpec(m["name"], Limits.from_dict(m), m.get("thinking_budget")) for m in raw.get("model", [])]
        if not specs:
            raise ValueError(f"{path}: no [[model]]")
        names = [s.name for s in specs]
        if len(set(names)) != len(names):
            raise ValueError(f"{path}: a model is listed twice")
        return cls(tuple(specs), float(raw.get("margin", 1.05)))

    def only(self, names: list[str]) -> "QuotaConfig":
        """The listed models, in that order (an unlisted model gets the Flash Lite defaults)."""
        by = {s.name: s for s in self.models}
        return QuotaConfig(tuple(by.get(n) or ModelSpec(n, Limits(15, 500) if "lite" in n else Limits(5, 20)) for n in names),
                           self.margin)


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
        msg_limit = re.search(r"limit:\s*(\d+)", m)
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
        if limit is None and msg_limit:
            limit = float(msg_limit.group(1))
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
        return self.spec.limits.over(self.learned)

    # ---- the day
    def roll(self, now: float) -> None:
        today = PacificDay.key(now)
        if today != self.day:
            if self.day:
                self.history[self.day] = {"requests": self.day_requests, "tokens": self.day_tokens}
                for old in sorted(self.history)[:-14]:
                    del self.history[old]
            self.day, self.day_requests, self.day_tokens = today, 0, 0
        if self.exhausted_until and now >= self.exhausted_until:
            self.exhausted_until, self.exhausted_why = 0.0, ""
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

    def unsent(self, entry: list) -> None:
        """The request never left (network down before sending): give the reservation back."""
        self.day_tokens -= entry[1]
        self.day_requests = max(0, self.day_requests - 1)
        try:
            self.window.remove(entry)
        except ValueError:
            pass

    # ---- errors
    def exhaust(self, now: float, why: str, until: float | None = None) -> None:
        self.exhausted_until = until if until is not None else PacificDay.next_reset(now)
        self.exhausted_why = why

    def block(self, now: float, seconds: float) -> None:
        self.blocked_until = max(self.blocked_until, now + seconds)

    def on_quota_error(self, now: float, err: QuotaError) -> str:
        """A 429. Returns a short description of what was decided."""
        self.roll(now)
        learned = self.learned.to_dict()
        if err.scope == "day":
            if err.limit is not None:
                learned["rpd" if err.kind == "requests" else "tpd"] = int(err.limit)
            elif err.kind == "requests":
                learned.setdefault("rpd", max(1, self.day_requests - 1))
            else:
                learned.setdefault("tpd", max(1, self.day_tokens))
            self.learned = Limits.from_dict(learned)
            self.exhaust(now, f"{err.kind}/day")
            return f"{err.kind} per day spent (limit {err.limit if err.limit is not None else 'unknown'}), until the Pacific midnight"
        self.minute_429 += 1
        recent = [e for e in self.window if e[0] > now - WINDOW]
        if err.limit is not None:
            learned["rpm" if err.kind == "requests" else "tpm"] = err.limit if err.kind == "requests" else int(err.limit)
        elif err.kind == "requests":
            known = self.limits().rpm
            guess = max(1, len(recent) - 1)
            if known is None or guess < known:
                learned["rpm"] = float(guess)
        else:
            learned["tpm"] = max(1, sum(e[1] for e in recent) - (recent[-1][1] if recent else 0))
        self.learned = Limits.from_dict(learned)
        wait = min(max(err.retry_after or WINDOW, MINUTE_BLOCK[0]), MINUTE_BLOCK[1]) + 1.0
        if self.minute_429 >= 3:
            wait = max(wait, LONG_BLOCK)
        self.block(now, wait)
        return f"{err.kind} per minute (limit {err.limit if err.limit is not None else 'unknown'}), wait {wait:.0f} s"

    # ---- persistence
    def to_dict(self) -> dict:
        return {"learned": self.learned.to_dict(), "window": [list(e) for e in self.window], "last_sent": self.last_sent,
                "day": self.day, "day_requests": self.day_requests, "day_tokens": self.day_tokens,
                "exhausted_until": self.exhausted_until, "exhausted_why": self.exhausted_why,
                "blocked_until": self.blocked_until, "minute_429": self.minute_429, "client_errors": self.client_errors,
                "tokens_per_char": round(self.tokens_per_char, 5), "history": self.history}

    def load(self, d: dict) -> None:
        self.learned = Limits.from_dict(d.get("learned", {}))
        self.window = deque([float(a), int(b)] for a, b in d.get("window", []))
        self.last_sent = float(d.get("last_sent", 0.0))
        self.day, self.day_requests, self.day_tokens = d.get("day", ""), int(d.get("day_requests", 0)), int(d.get("day_tokens", 0))
        self.exhausted_until, self.exhausted_why = float(d.get("exhausted_until", 0.0)), d.get("exhausted_why", "")
        self.blocked_until, self.minute_429 = float(d.get("blocked_until", 0.0)), int(d.get("minute_429", 0))
        self.client_errors = int(d.get("client_errors", 0))
        self.tokens_per_char = float(d.get("tokens_per_char", self.tokens_per_char))
        self.history = dict(d.get("history", {}))


# ---------------------------------------------------------------------------------------------------- all models
@dataclass
class Choice:
    model: str
    at: float                   # epoch second from which it can be used (<= now: right away)
    all_exhausted: bool = False  # every model is out until a reset


class QuotaDesk:
    """The books of all the models, in preference order, and their file."""

    def __init__(self, config: QuotaConfig, path: Path | str | None = None):
        self.config = config
        self.books = {s.name: QuotaBook(s, config.margin) for s in config.models}
        self.path = Path(path) if path else None
        if self.path and self.path.exists():
            self.load()

    @property
    def order(self) -> list[str]:
        return [s.name for s in self.config.models]

    def spec(self, model: str) -> ModelSpec:
        return self.books[model].spec

    def choose(self, now: float, chars: int) -> Choice:
        """The model that can answer first (ties go to the preference order)."""
        best, best_at = None, FAR
        for name in self.order:
            b = self.books[name]
            at = b.available_at(now, b.estimate_input(chars))
            if at < best_at - 0.25:
                best, best_at = name, at
        exhausted = all(self.books[n].exhausted_until > now for n in self.order)
        return Choice(best, best_at, exhausted)

    def next_reset(self, now: float) -> float:
        return min((b.exhausted_until for b in self.books.values() if b.exhausted_until > now), default=PacificDay.next_reset(now))

    # ---- file
    def save(self) -> None:
        if not self.path:
            return
        doc = {"schema": 1, "models": {n: b.to_dict() for n, b in self.books.items()}}
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps(doc, indent=1), encoding="utf-8")
        os.replace(tmp, self.path)

    def load(self) -> None:
        try:
            doc = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return                                   # a damaged file is only a cache of counters: start again from the config
        for name, d in doc.get("models", {}).items():
            if name in self.books and isinstance(d, dict):
                self.books[name].load(d)

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
