"""caller.py - one request at a time, to the model that can answer first, at the exact pace of its quota.

    Pacer         waits in short slices so a stop request (SIGTERM) or an idle task (code change?) is heard at once
    ModelCaller   asks the QuotaDesk which model may go, waits, sends, settles the accounting, reads the errors:

        429 per minute  the model is blocked for the delay Google gives; another model goes on meanwhile
        429 per day     the model is out until the Pacific midnight; the next one goes on
        all models out  sleep until the earliest reset, then go on
        5xx / network   exponential pause (the request is not counted against the quota)
        404             the model is gone: out for a day
        400 / 401 / 403 the request is wrong for that model: 2 in a row -> out for a day; 3 models in a row -> FatalError
                        (a wrong key or a broken schema must not eat the quota nor loop for ever)

The client, the desk and the clock are injected, so every branch is tested without the network.
"""
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from typing import Callable

from .gemini import ApiResult
from .quota import PacificDay, QuotaDesk, QuotaError

IDLE_SLICE = 30.0               # longest sleep without looking at the stop flag and the idle task


class FatalError(RuntimeError):
    """The run cannot go on without a human (exit code 3: the service is not restarted)."""


class Pacer:
    """Interruptible waits on an injectable clock (epoch seconds)."""

    def __init__(self, clock: Callable[[], float] = time.time, waiter: Callable[[float], None] | None = None,
                 idle: Callable[[], None] | None = None):
        self.clock = clock
        self.stop = threading.Event()
        self._wait = waiter or (lambda s: self.stop.wait(s))
        self.idle = idle

    @property
    def stopped(self) -> bool:
        return self.stop.is_set()

    def request_stop(self) -> None:
        self.stop.set()

    def wait_until(self, t: float) -> bool:
        """Sleep until epoch second `t`, in slices. True when the time came, False when a stop was requested."""
        while not self.stopped:
            left = t - self.clock()
            if left <= 0:
                return True
            self._wait(min(left, IDLE_SLICE))
            if self.idle:
                self.idle()
        return False

    def sleep(self, seconds: float) -> bool:
        return self.wait_until(self.clock() + seconds)


@dataclass
class CallStats:
    requests: int = 0
    errors_429: int = 0
    errors_other: int = 0
    waited_s: float = 0.0


class ModelCaller:
    def __init__(self, client, desk: QuotaDesk, pacer: Pacer, log: Callable[[str], None] = print,
                 event: Callable[[dict], None] = lambda e: None, temperature: float = 0.9, max_output_tokens: int = 8192,
                 max_requests: int | None = None):
        self.client, self.desk, self.pacer, self.log, self.event = client, desk, pacer, log, event
        self.temperature, self.max_output_tokens, self.max_requests = temperature, max_output_tokens, max_requests
        self.stats = CallStats()
        self._transient = 0
        self._client_error_models: set = set()

    # ---- the cap
    def can_call(self) -> bool:
        return self.max_requests is None or self.stats.requests < self.max_requests

    # ---- one request
    def __call__(self, system: str, user: str, schema: dict):
        """-> (model, ApiResult) for an answer with HTTP 200 (even without text), None when stopped or capped."""
        chars = len(system) + len(user) + len(json.dumps(schema))
        while not self.pacer.stopped:
            if not self.can_call():
                return None
            now = self.pacer.clock()
            choice = self.desk.choose(now, chars)
            if choice.at > now:
                self.wait_for(choice, now)
                continue
            r = self.send(choice.model, system, user, schema, chars)
            if r is None:
                continue
            return choice.model, r
        return None

    def wait_for(self, choice, now: float) -> None:
        seconds = choice.at - now
        if choice.all_exhausted or seconds > 120:
            self.log(f"waiting {seconds / 60:.0f} min for {choice.model} ({'every model is out for today' if choice.all_exhausted else 'cooldown'}; "
                     f"{PacificDay.key(choice.at)} Pacific)")
        self.pacer.wait_until(choice.at)
        self.stats.waited_s += max(0.0, choice.at - now)

    def send(self, model: str, system: str, user: str, schema: dict, chars: int) -> ApiResult | None:
        """Send one request; returns the result on HTTP 200, None when the error was handled and the choice must be redone."""
        book, spec = self.desk.books[model], self.desk.spec(model)
        now = self.pacer.clock()
        entry = book.begin(now, book.estimate_input(chars))
        self.stats.requests += 1
        r = self.client.generate(model, system, user, schema, self.temperature, self.max_output_tokens, spec.thinking_budget)
        now = self.pacer.clock()
        try:
            if r.status == 200:
                self._transient = 0
                self._client_error_models.clear()
                book.settle(entry, r.usage.get("promptTokenCount"), chars)
                book.client_errors = 0
                return r
            book.settle(entry, 0)
            self.event({"kind": "error", "model": model, "http": r.status, "scope": r.quota_scope, "error": r.error[:300]})
            if r.status == 429:
                self.stats.errors_429 += 1
                err = QuotaError.parse(r.quota_violations, r.error, r.quota_scope, r.retry_after)
                self.log(f"{model}: 429 {book.on_quota_error(now, err)}")
            elif r.status == 404:
                book.exhaust(now, "not found", until=now + 24 * 3600)
                self.log(f"{model}: 404, set aside for a day")
            elif r.status in (400, 401, 403):
                self.stats.errors_other += 1
                self._client_error(model, book, now, r)
            else:                                        # 5xx, network (0): not the quota's fault
                self.stats.errors_other += 1
                self._transient += 1
                pause = min(300.0, 5.0 * 2 ** (self._transient - 1))
                self.log(f"{model}: HTTP {r.status} {r.error[:100]}; pause {pause:.0f} s")
                book.block(now, pause)
                self.pacer.sleep(pause)
            return None
        finally:
            self.desk.save()

    def _client_error(self, model: str, book, now: float, r: ApiResult) -> None:
        book.client_errors += 1
        self._client_error_models.add(model)
        self.log(f"{model}: HTTP {r.status} {r.error[:160]}")
        if len(self._client_error_models) >= 3:
            raise FatalError(f"HTTP {r.status} on {len(self._client_error_models)} models in a row ({r.error[:160]}): "
                             "the key or the request is wrong; stopped to protect the quota")
        if book.client_errors >= 2:
            book.exhaust(now, f"HTTP {r.status}", until=PacificDay.next_reset(now))
            self.log(f"{model}: set aside until tomorrow")
