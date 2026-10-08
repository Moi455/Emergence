#!/usr/bin/env python3
"""gemini_client.py - minimal REST client for Gemini 3.5 Flash-Lite (Interactions API) + rate limiter.

No SDK needed (standard library only), so a future SDK change cannot break it.
Request/response shapes follow the Interactions API documentation (Sept 2026):
  POST {BASE}/v1beta/interactions
  headers: x-goog-api-key, Content-Type, Api-Revision
  body: model, input, system_instruction, response_format{type,mime_type,schema}, generation_config{thinking_level}
  reply: {status, steps:[{type:'model_output', content:[{type:'text', text}]}], usage:{total_tokens,...}}
If the API rejects an optional field, the client drops it and remembers (self.caps) instead of crashing.
"""
import json
import os
import socket
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from datetime import datetime, timedelta, timezone

BASE = os.environ.get("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com")
API_REVISION = "2026-05-20"
SIM_DAY = float(os.environ.get("NPC_SIM_DAY_SECONDS", "0") or 0)     # tests only: shortened 'day'


class ApiError(Exception):
    """kind: rate_minute | rate_day | server | timeout | auth | bad_request | blocked | empty | other"""

    def __init__(self, kind, status=None, message="", retry_after=None):
        super().__init__(f"{kind} ({status}): {message[:300]}")
        self.kind, self.status, self.message, self.retry_after = kind, status, message, retry_after


# --------------------------------------------------------------------------- days
def _pacific_now():
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("America/Los_Angeles"))
    except Exception:                                   # no tz database: conservative fixed UTC-8
        return datetime.now(timezone(timedelta(hours=-8)))


def day_key():
    """Quota day. Real use: calendar date in Pacific time (RPD resets at midnight Pacific)."""
    if SIM_DAY:
        return str(int(time.time() // SIM_DAY))
    return _pacific_now().strftime("%Y-%m-%d")


def seconds_to_next_day():
    if SIM_DAY:
        return SIM_DAY - (time.time() % SIM_DAY) + .3
    now = _pacific_now()
    nxt = (now + timedelta(days=1)).replace(hour=0, minute=0, second=15, microsecond=0)
    return max(5.0, (nxt - now).total_seconds())


# --------------------------------------------------------------------------- limiter
class Limiter:
    """Sliding-window RPM and TPM (input tokens) + persistent per-day request counter, shared by all threads."""

    def __init__(self, rpm, tpm, rpd, state_path, stop_event=None, rpm_margin=1, tpm_margin=.8, rpd_reserve=5):
        self.rpm, self.tpm = max(1, rpm - rpm_margin), int(tpm * tpm_margin)
        self.rpd = max(1, rpd - rpd_reserve)
        self.path, self.lock = state_path, threading.Lock()
        self.stop = stop_event or threading.Event()
        self.win = deque()                              # (timestamp, est_input_tokens)
        self.blocked_until = 0.0
        self.day, self.count = day_key(), 0
        self._load()

    def _load(self):
        try:
            d = json.load(open(self.path))
            if d.get("day") == self.day:
                self.count = int(d.get("count", 0))
        except Exception:
            pass

    def _save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump({"day": self.day, "count": self.count}, f)
        os.replace(tmp, self.path)

    def _roll_day(self):
        k = day_key()
        if k != self.day:
            self.day, self.count = k, 0
            self._save()

    def used_today(self):
        with self.lock:
            self._roll_day()
            return self.count

    def block_for(self, seconds):
        with self.lock:
            self.blocked_until = max(self.blocked_until, time.time() + seconds)

    def block_until_next_day(self):
        with self.lock:
            self.count = max(self.count, self.rpd)
            self._save()
            self.blocked_until = max(self.blocked_until, time.time() + seconds_to_next_day())

    def acquire(self, est_tokens):
        """Block until one more request may start. Returns False if a stop was requested."""
        while not self.stop.is_set():
            wait = 0.0
            with self.lock:
                self._roll_day()
                now = time.time()
                while self.win and now - self.win[0][0] >= 60:
                    self.win.popleft()
                tok = sum(t for _, t in self.win)
                if self.count >= self.rpd:
                    wait = seconds_to_next_day()
                elif now < self.blocked_until:
                    wait = self.blocked_until - now
                elif len(self.win) >= self.rpm:
                    wait = 60 - (now - self.win[0][0]) + .05
                elif tok + est_tokens > self.tpm and self.win:
                    wait = 60 - (now - self.win[0][0]) + .05
                else:
                    self.win.append((now, est_tokens))
                    self.count += 1
                    self._save()
                    return True
            self.stop.wait(min(wait, 30.0) if wait < 3600 else 30.0)
        return False


# --------------------------------------------------------------------------- client
def extract_text(resp):
    """Pull the model's text out of an Interactions response (also tolerates other known shapes)."""
    if isinstance(resp.get("output_text"), str) and resp["output_text"]:
        return resp["output_text"]
    texts = []
    for st in resp.get("steps") or []:
        if st.get("type") == "model_output":
            for c in st.get("content") or []:
                if c.get("type") == "text" and c.get("text"):
                    texts.append(c["text"])
    if texts:
        return "".join(texts)
    for cand in resp.get("candidates") or []:                      # generateContent shape
        parts = (cand.get("content") or {}).get("parts") or []
        t = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        if t:
            return t
    return None


def sum_usage(u):
    out = {}
    for k, v in (u or {}).items():
        if isinstance(v, (int, float)):
            out[k] = v
    return out


class GeminiClient:
    def __init__(self, api_key, model="gemini-3.5-flash-lite", base=BASE, timeout=240, log=print):
        self.key, self.model, self.base, self.timeout, self.log = api_key, model, base.rstrip("/"), timeout, log
        self.caps = {"system_instruction": True, "response_format": True, "thinking": True, "revision": True}
        self._lock = threading.Lock()

    def _post(self, body):
        headers = {"x-goog-api-key": self.key, "Content-Type": "application/json"}
        if self.caps["revision"]:
            headers["Api-Revision"] = API_REVISION
        req = urllib.request.Request(self.base + "/v1beta/interactions", data=json.dumps(body).encode(), headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            txt = e.read().decode(errors="replace")
            ra = e.headers.get("Retry-After") if e.headers else None
            low = txt.lower()
            if e.code == 429:
                kind = "rate_day" if any(s in low for s in ("perday", "per day", "daily", "rpd")) else "rate_minute"
                raise ApiError(kind, 429, txt, float(ra) if ra and ra.replace(".", "").isdigit() else None)
            if e.code in (401, 403):
                raise ApiError("auth", e.code, txt)
            if e.code in (500, 502, 503, 504):
                raise ApiError("server", e.code, txt)
            if e.code in (400, 404, 422):
                raise ApiError("bad_request", e.code, txt)
            raise ApiError("other", e.code, txt)
        except (socket.timeout, TimeoutError):
            raise ApiError("timeout", None, "timeout")
        except urllib.error.URLError as e:
            raise ApiError("server", None, f"network: {e.reason}")

    def generate(self, system, user, schema, thinking=None):
        """One call. Returns {'text', 'usage', 'status'}. Raises ApiError."""
        for _ in range(5):                                   # at most 4 capability fallbacks
            body = {"model": self.model, "input": user}
            if self.caps["system_instruction"]:
                body["system_instruction"] = system
            else:
                body["input"] = system + "\n\n" + user
            if self.caps["response_format"] and schema is not None:
                body["response_format"] = {"type": "text", "mime_type": "application/json", "schema": schema}
            if self.caps["thinking"] and thinking:
                body["generation_config"] = {"thinking_level": thinking}
            try:
                resp = self._post(body)
                break
            except ApiError as e:
                if e.kind != "bad_request":
                    raise
                low = e.message.lower()
                changed = False
                with self._lock:
                    for cap, hints in (("revision", ("api-revision", "revision")), ("system_instruction", ("system_instruction", "systeminstruction")),
                                       ("response_format", ("response_format", "responseformat", "mime_type")),
                                       ("thinking", ("thinking_level", "thinking level", "thinkinglevel", "thinking"))):
                        if self.caps[cap] and any(h in low for h in hints):
                            if cap == "thinking" and thinking and thinking.lower() in low:
                                e.level_rejected = True          # this level is refused; thinking itself is fine
                                raise e
                            self.caps[cap] = False
                            self.log(f"[client] API rejected '{cap}': continuing without it ({e.message[:120]!r})")
                            changed = True
                            break
                if not changed:
                    raise
        else:
            raise ApiError("bad_request", 400, "too many capability fallbacks")
        status = resp.get("status")
        text = extract_text(resp)
        if status not in (None, "completed", "COMPLETED") and not text:
            raise ApiError("blocked", None, f"status={status} {json.dumps(resp)[:200]}")
        if not text:
            raise ApiError("empty", None, "no text in response: " + json.dumps(resp)[:200])
        return {"text": text, "usage": sum_usage(resp.get("usage")), "status": status}
