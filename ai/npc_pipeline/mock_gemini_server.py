#!/usr/bin/env python3
"""mock_gemini_server.py - a local stand-in for POST /v1beta/interactions, to test the pipeline without a key.

It follows the documented request/response shapes and injects the failures a real run meets:
per-minute and per-day 429s, 503s, safety blocks, truncated JSON, wrong array lengths, flat scores.
It proves the orchestration (limits, resume, retries, splitting, parsing); it does NOT prove the live API accepts
our payload - run `teacher_run.py probe` with your real key for that.

  python3 mock_gemini_server.py --port 8765 --rpm 120 --rpd 40 --p503 .05 --pblock .0 --poison-mod 53
  (set NPC_SIM_DAY_SECONDS=30 in BOTH processes to shorten the quota 'day')
"""
import argparse
import hashlib
import json
import os
import random
import re
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SIM_DAY = float(os.environ.get("NPC_SIM_DAY_SECONDS", "0") or 0)
LOCK = threading.Lock()
WIN = deque()
DAYS = {}
STATS = {"requests": 0, "429m": 0, "429d": 0, "503": 0, "blocked": 0, "bad_json": 0, "bad_len": 0, "flat": 0, "ok": 0}
ARGS = None
RNG = random.Random(7)


def day_key():
    return str(int(time.time() // SIM_DAY)) if SIM_DAY else time.strftime("%Y-%m-%d", time.gmtime())


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, obj, headers=None):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/stats":
            self._send(200, STATS)
        else:
            self._send(404, {"error": {"message": "not found"}})

    def do_POST(self):
        if not self.path.startswith("/v1beta/interactions"):
            return self._send(404, {"error": {"code": 404, "message": "unknown path"}})
        if not self.headers.get("x-goog-api-key"):
            return self._send(403, {"error": {"code": 403, "message": "API key missing"}})
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        with LOCK:
            STATS["requests"] += 1
            now = time.time()
            while WIN and now - WIN[0] >= 60:
                WIN.popleft()
            dk = day_key()
            DAYS[dk] = DAYS.get(dk, 0) + 1
            if DAYS[dk] > ARGS.rpd:
                STATS["429d"] += 1
                return self._send(429, {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED",
                                                  "message": "Quota exceeded for metric GenerateRequestsPerDayPerProjectPerModel-FreeTier"}})
            if len(WIN) >= ARGS.rpm:
                STATS["429m"] += 1
                return self._send(429, {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED",
                                                  "message": "Quota exceeded for metric GenerateRequestsPerMinutePerProjectPerModel-FreeTier"}})
            WIN.append(now)
            r = RNG.random()
        if body.get("generation_config", {}).get("thinking_level") == "minimal" and ARGS.reject_minimal:
            return self._send(400, {"error": {"code": 400, "message": "thinking_level 'minimal' is not supported for this model"}})
        if r < ARGS.p503:
            STATS["503"] += 1
            return self._send(503, {"error": {"code": 503, "message": "The model is overloaded."}})
        system = body.get("system_instruction", "")
        user = body.get("input", "")
        if not system:
            system = user
        time.sleep(ARGS.latency)
        blocks = re.findall(r"### (s\d+|x\d+|p\d+)\n(.*?)(?=\n\n### |\n\nBased on|\Z)", user, re.S)
        if not blocks:                                          # a probe-style request
            text = json.dumps({"ok": True, "n": 3})
            return self._send(200, self._reply(text, user))
        ids = [b[0] for b in blocks]
        if ARGS.poison_mod and any(int(re.sub(r"\D", "", i)) % ARGS.poison_mod == 0 and int(re.sub(r"\D", "", i)) > 0 for i in ids):
            STATS["blocked"] += 1
            return self._send(200, {"id": "v1_blocked", "model": body.get("model"), "object": "interaction", "status": "failed", "steps": []})
        variant = "codes" if ('"k"' in system and "closed list" in system) else "text" if '"why"' in system else "none"
        out = []
        for sid, txt in blocks:
            m = re.search(r"OPTS (.*)", txt)
            opts = m.group(1).split(" | ") if m else ["x", "y", "z"]
            scores = []
            for o in opts:
                o2 = re.sub(r"^\d+\s*", "", o.strip())
                h = int(hashlib.md5(o2.encode()).hexdigest(), 16)
                s = h % 5
                if RNG.random() < .1:
                    s = max(0, min(4, s + RNG.choice([-1, 1])))
                scores.append(s)
            item = {"id": sid}
            if variant == "text":
                item["why"] = "plausible reaction"
            if variant == "codes":
                item["k"] = ["need"]
            item["s"] = scores
            item["alt"] = RNG.choice([None, None, None, "chase E2"])
            out.append(item)
        r2 = RNG.random()
        if r2 < ARGS.pflat:
            STATS["flat"] += 1
            for it in out:
                it["s"] = [2] * len(it["s"])
        elif r2 < ARGS.pflat + ARGS.plen:
            STATS["bad_len"] += 1
            out[0]["s"] = out[0]["s"][:-1]
        text = json.dumps({"r": out})
        if RNG.random() < ARGS.pbad:
            STATS["bad_json"] += 1
            text = text[: len(text) // 2]
        STATS["ok"] += 1
        self._send(200, self._reply(text, user + system))

    @staticmethod
    def _reply(text, prompt):
        tin, tout = len(prompt) // 3, len(text) // 3
        return {"id": "v1_mock", "model": "gemini-3.5-flash-lite", "object": "interaction", "status": "completed",
                "steps": [{"type": "thought", "content": []}, {"type": "model_output", "content": [{"type": "text", "text": text}]}],
                "usage": {"total_tokens": tin + tout, "total_input_tokens": tin, "total_output_tokens": tout}}


def main():
    global ARGS
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--rpm", type=int, default=120)
    ap.add_argument("--rpd", type=int, default=40)
    ap.add_argument("--p503", type=float, default=.04)
    ap.add_argument("--pbad", type=float, default=.03)
    ap.add_argument("--plen", type=float, default=.03)
    ap.add_argument("--pflat", type=float, default=.02)
    ap.add_argument("--poison-mod", type=int, default=0)
    ap.add_argument("--latency", type=float, default=.05)
    ap.add_argument("--reject-minimal", action="store_true")
    ARGS = ap.parse_args()
    ThreadingHTTPServer(("127.0.0.1", ARGS.port), H).serve_forever()


if __name__ == "__main__":
    main()
