"""probe.py - what can each Gemini-API model do? At most 2 tiny real requests per model (free quota only).

    ModelProbe     one candidate: request 1 asks for everything at once (systemInstruction + structured JSON, no thinking
                   setting, 600 tokens); only if it is refused with a 400, request 2 is the same question in plain text.
                   It measures: answers? systemInstruction honoured? responseSchema honoured? thoughts? and the error otherwise
                   (HTTP code, message, 429 scope minute/day, quotaValue).
    CandidateList  which models are worth asking: the textual ones that models.list offers, minus the families that are never
                   labellers (tts, image, lyria...) and the models quota.json already set aside as 404.
    ProbeReport    the table, as JSON and as readable text, outside the repository.

One request at a time, at least `pause` seconds (5) between two requests; a refused key (403 / invalid key) stops everything.
The key never appears in the report (the client's Redactor cleans every message).

    cd ai && python3 -m teacher.probe --call                          # the default candidates (real requests)
    cd ai && python3 -m teacher.probe --call --models gemma-4-31b-it  # some of them
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from .gemini import ApiKeyError, ApiKeyLoader, GeminiClient, ModelCatalog, PromptOnlyStrategy
from .providers import ProviderRouter, Providers, RefusalDetector
from .quota import DEFAULT_CONFIG, LedgerGate, QuotaConfig
from .toolkit import ROOT

DEFAULT_OUT = Path.home() / ".local" / "share" / "emergence" / "dataset"
REPORT_NAME = "probe_models.json"
DEFAULT_QUOTA_FILE = DEFAULT_OUT / "quota_global.json"          # the ledger shared by every series and tool (quota.py)
DEFAULT_CANDIDATES = (
    "gemma-4-26b-a4b-it", "gemma-4-31b-it", "gemini-2.5-pro", "gemini-3.1-pro-preview", "gemini-pro-latest",
    "gemini-flash-latest", "gemini-flash-lite-latest", "gemini-4-argon", "gemini-omni-1.1-flash", "gemini-omni-flash-preview",
    "antigravity-preview-05-2026", "antigravity-preview-09-2026", "antigravity-preview-latest")
NEVER = ("tts", "image", "transcribe", "lyria", "robotics", "computer-use", "deep-research", "nano-banana", "live", "embedding",
         "veo", "imagen", "aqa", "audio")
SECRET_WORD = "pelican"


class KeyRefused(RuntimeError):
    """The API refused the key itself: nothing else is worth asking."""


# ---------------------------------------------------------------------------------------------------- candidates
class CandidateList:
    def __init__(self, listed: list[dict], quota_file: Path | None = None):
        self.listed = listed
        self.quota_file = quota_file

    def set_aside(self) -> set[str]:
        """Models that quota.json put aside because the API answered 404."""
        if not self.quota_file or not Path(self.quota_file).exists():
            return set()
        try:
            doc = json.loads(Path(self.quota_file).read_text(encoding="utf-8"))
            books = doc.get("pools") or doc.get("models") or {}          # the global ledger ("pools"), or an old <series>/quota.json ("models")
            return {n for n, b in books.items() if b.get("exhausted_why") == "not found"}
        except (OSError, ValueError, AttributeError):
            return set()

    def select(self, wanted: list[str]) -> tuple[list[str], dict]:
        """-> (models to ask, {model: reason it is not asked})."""
        offered = {ModelCatalog.short(m.get("name", "")): m for m in self.listed
                   if "generateContent" in m.get("supportedGenerationMethods", [])}
        skipped, keep, gone = {}, [], self.set_aside()
        for name in wanted:
            if name in gone:
                skipped[name] = "404 in quota.json (already set aside)"
            elif any(x in name for x in NEVER):
                skipped[name] = "family excluded (not a text labeller)"
            elif name not in offered:
                skipped[name] = "not in models.list with generateContent"
            else:
                keep.append(name)
        return keep, skipped


# ---------------------------------------------------------------------------------------------------- one model
class ModelProbe:
    SYSTEM = f'You are a test fixture. The secret word is "{SECRET_WORD}". Never explain anything.'
    USER = ('What is the secret word? Reply with the JSON object {"answer": <the secret word>, "n": 2}.')
    SCHEMA = {"type": "OBJECT", "properties": {"answer": {"type": "STRING"}, "n": {"type": "INTEGER"}}, "required": ["answer", "n"]}
    PLAIN = (f'The secret word is "{SECRET_WORD}". What is the secret word? Reply with only the JSON object '
             '{"answer": <the secret word>, "n": 2}, no other text.')
    MAX_TOKENS = 600

    def __init__(self, client: GeminiClient, pause: float = 5.0, sleep=time.sleep, clock=time.monotonic, log=print):
        self.client, self.pause, self.sleep, self.clock, self.log = client, pause, sleep, clock, log
        self._last = None

    # ---- one HTTP request, paced
    def _send(self, model: str, body: dict) -> tuple[int, dict, float]:
        if self._last is not None:
            wait = self.pause - (self.clock() - self._last)
            if wait > 0:
                self.sleep(wait)
        status, payload, latency = self.client.post_generate(model, body)
        self._last = self.clock()
        if self._key_refused(status, payload):
            raise KeyRefused(f"HTTP {status}: {self._error(status, payload)['message']}")
        return status, payload, latency

    @staticmethod
    def _key_refused(status: int, payload: dict) -> bool:
        err = payload.get("error", {}) if isinstance(payload, dict) else {}
        blob = json.dumps(err).lower() if isinstance(err, dict) else str(err).lower()
        if status == 403:
            return bool(re.search(r"api key|api_key|leaked|consumer.*suspended|permission_denied", blob)) and "model" not in blob
        return status in (400, 401) and bool(re.search(r"api key not valid|api_key_invalid|api key expired", blob))

    def _error(self, status: int, payload: dict) -> dict:
        err = payload.get("error", {}) if isinstance(payload, dict) else {}
        err = err if isinstance(err, dict) else {"message": str(err)}
        full = self.client.redactor.clean(str(err.get("message", "")))
        out = {"http": status, "status": str(err.get("status", "")), "message": full[:300]}
        limits = re.findall(r"quota exceeded for metric: \S*?([A-Za-z_]+), limit: (\d+)", full, re.I)
        if limits:
            out["limits_in_message"] = [{"metric": m, "limit": int(n)} for m, n in limits]
        blob = json.dumps(err).lower()
        if status == 429:
            scope, retry = GeminiClient.classify_quota(err)
            out["scope"], out["retry_after_s"] = scope, retry
            violations = GeminiClient.quota_violations(err)
            out["quota"] = [{"quotaId": v.get("quotaId", ""), "quotaMetric": v.get("quotaMetric", ""),
                             "quotaValue": v.get("quotaValue", "")} for v in violations]
        # "check your plan and billing details" is on EVERY 429; what means "no free tier" is a free-tier limit of 0
        if (limits and all(int(n) == 0 for _, n in limits)) or re.search(r"paid tier|enable billing|billing (is )?required", blob):
            out["billing_required"] = True
        return out

    # ---- reading an answer
    @staticmethod
    def _text(payload: dict) -> tuple[str, bool, str]:
        cands = payload.get("candidates") or []
        parts = (cands[0].get("content", {}).get("parts") or []) if cands else []
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        thought_part = any(p.get("thought") for p in parts)
        return text, thought_part, (cands[0].get("finishReason", "") if cands else "NO_CANDIDATE")

    @staticmethod
    def _json(text: str):
        s = text.strip()
        if s.startswith("```"):
            s = re.sub(r"^```(?:json)?|```$", "", s, flags=re.I).strip()
        try:
            data = json.loads(s)
        except ValueError:
            m = re.search(r"\{.*\}", s, re.S)
            try:
                data = json.loads(m.group(0)) if m else None
            except ValueError:
                data = None
        return data if isinstance(data, dict) else None

    def _observe(self, status: int, payload: dict, latency: float) -> dict:
        text, thought_part, finish = self._text(payload)
        usage = payload.get("usageMetadata", {}) if isinstance(payload, dict) else {}
        data = self._json(text)
        return {"answered": bool(text), "finish": finish, "latency_s": round(latency, 2),
                "pure_json": self._pure(text), "json_valid": data is not None,
                "secret_word_found": bool(data and SECRET_WORD in str(data.get("answer", "")).lower()),
                "thoughts_tokens": int(usage.get("thoughtsTokenCount", 0) or 0), "thought_parts": thought_part,
                "usage": {"prompt": usage.get("promptTokenCount", 0), "output": usage.get("candidatesTokenCount", 0)},
                "text_sample": self.client.redactor.clean(text)[:160]}

    @staticmethod
    def _pure(text: str) -> bool:
        try:
            return isinstance(json.loads(text), dict)
        except ValueError:
            return False

    # ---- the probe
    def probe(self, model: str) -> dict:
        row = {"model": model, "requests": 0, "viable": False, "mode": "", "system_instruction": None, "json_schema": None,
               "thinks": None, "error": None, "notes": []}
        body = {"systemInstruction": {"parts": [{"text": self.SYSTEM}]},
                "contents": [{"role": "user", "parts": [{"text": self.USER}]}],
                "generationConfig": {"responseMimeType": "application/json", "responseSchema": self.SCHEMA, "temperature": 0.0,
                                     "maxOutputTokens": self.MAX_TOKENS}}
        status, payload, latency = self._send(model, body)
        row["requests"] = 1
        if status == 200:
            obs = self._observe(status, payload, latency)
            row["full"] = obs
            row["system_instruction"] = obs["secret_word_found"]
            row["json_schema"] = obs["pure_json"]
            row["thinks"] = obs["thoughts_tokens"] > 0 or obs["thought_parts"]
            row["viable"] = obs["answered"]
            row["mode"] = "structured" if obs["pure_json"] and obs["secret_word_found"] else "prompt_only" if obs["answered"] else ""
            if not obs["answered"]:
                row["notes"].append(f"HTTP 200 without text (finish {obs['finish']}, thoughts {obs['thoughts_tokens']})")
            return row
        err = self._error(status, payload)
        row["error"] = err
        if status == 400:
            self._fallback(model, row, err)
        return row

    def _fallback(self, model: str, row: dict, err: dict) -> None:
        """Request 2 (only after a 400): the same question without systemInstruction and without responseSchema. The message
        of the 400 says which of the two was refused (when it does not, both are marked unsupported)."""
        msg = err["message"].lower()
        no_system = bool(re.search(r"system|developer instruction", msg))
        no_schema = bool(re.search(r"json|schema|mime|response_", msg))
        if not (no_system or no_schema):
            no_system = no_schema = True
        row["system_instruction"], row["json_schema"] = not no_system, not no_schema
        body = {"contents": [{"role": "user", "parts": [{"text": self.PLAIN}]}],
                "generationConfig": {"temperature": 0.0, "maxOutputTokens": self.MAX_TOKENS}}
        status, payload, latency = self._send(model, body)
        row["requests"] = 2
        if status == 200:
            obs = self._observe(status, payload, latency)
            row["plain"] = obs
            row["thinks"] = obs["thoughts_tokens"] > 0 or obs["thought_parts"]
            row["viable"] = obs["answered"] and obs["json_valid"]
            row["mode"] = "prompt_only" if row["viable"] else ""
            row["notes"].append("plain text works" if row["viable"] else "plain text answered but without valid JSON")
        else:
            row["error_plain"] = self._error(status, payload)

    # ---- everything
    def run(self, models: list[str]) -> list[dict]:
        rows = []
        for m in models:
            self.log(f"probe {m} ...")
            try:
                row = self.probe(m)
            except KeyRefused as e:
                rows.append({"model": m, "viable": False, "requests": 1, "error": {"http": 403, "message": f"KEY REFUSED: {e}"},
                             "aborted": True})
                self.log(f"key refused, everything stops: {e}")
                break
            rows.append(row)
            self.log("  " + ProbeReport.line(row))
        return rows


# ---------------------------------------------------------------------------------------------------- other providers
class CompatProbe:
    """The probe of a Groq / OpenRouter model: at most 2 tiny requests. Request 1 asks the way quota.toml says (json_object,
    json_schema or prompt-only); only if the API answers 400 / 422 (the way of asking is refused), request 2 is the same question
    in plain text. Observed: does it answer, pure JSON, system message honoured, reasoning tokens, the X-RateLimit-* headers
    (they CONFIRM the limits of quota.toml), the error (402 = credits required: the model is dropped, never paid)."""

    MAX_TOKENS = 1500           # reasoning tokens are counted in the limit

    def __init__(self, client, pause: float = 5.0, sleep=time.sleep, clock=time.monotonic, log=print):
        self.client, self.pause, self.sleep, self.clock, self.log = client, pause, sleep, clock, log
        self._last = None

    def _send(self, model: str):
        if self._last is not None and self.clock() - self._last < self.pause:
            self.sleep(self.pause - (self.clock() - self._last))
        r = self.client.generate(model, ModelProbe.SYSTEM, ModelProbe.USER, ModelProbe.SCHEMA, 0.0, self.MAX_TOKENS)
        self._last = self.clock()
        return r

    def _observe(self, r) -> dict:
        data = ModelProbe._json(r.text)
        u = r.usage
        return {"answered": bool(r.text), "finish": r.finish, "latency_s": round(r.latency, 2), "pure_json": ModelProbe._pure(r.text),
                "json_valid": data is not None, "secret_word_found": bool(data and SECRET_WORD in str(data.get("answer", "")).lower()),
                "thoughts_tokens": int(u.get("thoughtsTokenCount", 0) or 0),
                "usage": {"prompt": u.get("promptTokenCount", 0), "output": u.get("candidatesTokenCount", 0)},
                "refusal": RefusalDetector.of(r), "text_sample": self.client.redactor.clean(r.text)[:160]}

    def probe(self, model: str) -> dict:
        row = {"model": model, "requests": 1, "viable": False, "mode": "", "system_instruction": None, "json_schema": None,
               "thinks": None, "error": None, "notes": []}
        r = self._send(model)
        if r.status == 200:
            obs = self._observe(r)
            row.update(full=obs, rate_limit=r.rate_limit, system_instruction=obs["secret_word_found"], json_schema=obs["pure_json"],
                       thinks=obs["thoughts_tokens"] > 0, viable=obs["answered"] and obs["json_valid"],
                       mode=getattr(self.client.strategies.get(model), "name", "structured"))
            if not row["viable"]:
                row["notes"].append(f"HTTP 200 but no valid JSON (finish {obs['finish']})")
            return row
        row["error"] = {"http": r.status, "scope": r.quota_scope, "message": r.error[:300], "retry_after_s": r.retry_after}
        row["rate_limit"] = r.rate_limit
        if r.status in (400, 422):
            row["notes"].append("the way of asking was refused; plain text tried")
            prev = self.client.strategies.get(model)
            self.client.strategies[model] = PromptOnlyStrategy(fold_system=False, fold_schema=True)
            try:
                r2 = self._send(model)
            finally:
                if prev is not None:
                    self.client.strategies[model] = prev
            row["requests"] = 2
            if r2.status == 200:
                obs = self._observe(r2)
                row.update(plain=obs, viable=obs["answered"] and obs["json_valid"], mode="prompt_only", thinks=obs["thoughts_tokens"] > 0)
            else:
                row["error_plain"] = {"http": r2.status, "message": r2.error[:300]}
        if r.status == 402:
            row["notes"].append("payment / credits required: dropped, never paid")
        return row

    def run(self, models: list[str]) -> list[dict]:
        rows = []
        for m in models:
            self.log(f"probe {m} ...")
            row = self.probe(m)
            rows.append(row)
            self.log("  " + ProbeReport.line(row))
            if (row.get("error") or {}).get("http") in (401, 403):
                self.log("key refused, everything stops")
                row["aborted"] = True
                break
        return rows


# ---------------------------------------------------------------------------------------------------- report
class ProbeReport:
    def __init__(self, rows: list[dict], skipped: dict, when: str | None = None):
        self.rows, self.skipped = rows, skipped
        self.when = when or datetime.now(timezone.utc).isoformat(timespec="seconds")

    @staticmethod
    def line(r: dict) -> str:
        if r.get("viable"):
            return (f"OK {r['mode']:<11} system={r['system_instruction']} schema={r['json_schema']} thinks={r['thinks']} "
                    f"{(r.get('full') or r.get('plain') or {}).get('latency_s', '?')}s")
        e = r.get("error") or {}
        extra = ""
        if e.get("http") == 429:
            q = ",".join(f"{x['quotaId'].split('_')[-1] or x['quotaMetric']}={x['quotaValue']}" for x in e.get("quota", []))
            extra = f" scope={e.get('scope')} {q}"
        if e.get("billing_required"):
            extra += " BILLING"
        return f"NO  HTTP {e.get('http', '?')}{extra} {e.get('message', '')[:120]}" + (f" | {'; '.join(r['notes'])}" if r.get("notes") else "")

    def text(self) -> str:
        out = [f"{r['model']:<34} {self.line(r)}" for r in self.rows]
        out += [f"{m:<34} skipped: {why}" for m, why in self.skipped.items()]
        return "\n".join(out)

    def write(self, path: Path) -> Path:
        path = Path(path).resolve()
        if path == ROOT or ROOT in path.parents:
            raise SystemExit(f"refusing to write inside the repository ({path})")
        path.parent.mkdir(parents=True, exist_ok=True)
        rows = {r["model"]: r for r in self._previous(path)}          # a later probe of a few models keeps the other rows
        rows.update({r["model"]: r for r in self.rows})
        merged = ProbeReport(list(rows.values()), {**self._previous_skipped(path), **self.skipped}, self.when)
        path.write_text(json.dumps({"when": self.when, "models": merged.rows, "skipped": merged.skipped,
                                    "readable": merged.text().splitlines()}, indent=1, ensure_ascii=False), encoding="utf-8")
        return path

    @staticmethod
    def _read(path: Path) -> dict:
        try:
            doc = json.loads(Path(path).read_text(encoding="utf-8"))
            return doc if isinstance(doc, dict) else {}
        except (OSError, ValueError):
            return {}

    def _previous(self, path: Path) -> list:
        return [r for r in self._read(path).get("models", []) if isinstance(r, dict) and "model" in r]

    def _previous_skipped(self, path: Path) -> dict:
        s = self._read(path).get("skipped", {})
        return s if isinstance(s, dict) else {}


# ---------------------------------------------------------------------------------------------------- command line
def other_provider(a) -> int:
    qc = QuotaConfig.load(a.quota_file)
    names = [m.strip() for m in a.models.split(",") if m.strip()] if a.models else [
        s.name for s in qc.catalogue if s.provider == a.provider and not s.name.endswith("free-pool")]
    if not a.call:
        print("dry run: nothing is sent. Candidates: " + ", ".join(names))
        return 0
    try:
        router = ProviderRouter.build([a.provider], a.key_file)
    except ApiKeyError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    qc = qc.only(names)
    qc.install(router)
    rows = CompatProbe(LedgerGate.for_tool(router, names, a.quota_file, a.quota_json), max(5.0, a.pause)).run(names)
    report = ProbeReport(rows, {})
    print(report.text())
    print(f"written to {report.write(a.out)}")
    return 3 if any(r.get("aborted") for r in rows) else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="teacher.probe", description=__doc__.split("\n\n")[0])
    ap.add_argument("--call", action="store_true", help="REAL requests (free quota; at most 2 per model)")
    ap.add_argument("--models", default=None, help="comma-separated candidates (default: the Gemini list, or all the models of --provider)")
    ap.add_argument("--provider", choices=("gemini", "groq", "openrouter"), default="gemini",
                    help="groq / openrouter: probe their quota.toml models (2 requests at most each, free quota)")
    ap.add_argument("--quota-file", type=Path, default=DEFAULT_CONFIG)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT / REPORT_NAME)
    ap.add_argument("--quota-json", type=Path, default=DEFAULT_QUOTA_FILE, help="models set aside (404) there are not asked")
    ap.add_argument("--pause", type=float, default=5.0, help="seconds between two requests (>= 5)")
    ap.add_argument("--key-file", type=Path, default=None)
    a = ap.parse_args(argv)
    if a.provider != "gemini":
        return other_provider(a)
    a.models = a.models or ",".join(DEFAULT_CANDIDATES)
    if not a.call:
        print("dry run: nothing is sent. Candidates: " + a.models)
        return 0
    try:
        key = ApiKeyLoader(path=a.key_file).load()
    except ApiKeyError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    client = GeminiClient(key)
    keep, skipped = CandidateList(client.list_models(), a.quota_json).select([m.strip() for m in a.models.split(",") if m.strip()])
    rows = ModelProbe(LedgerGate.for_tool(client, keep, ledger=a.quota_json), max(5.0, a.pause)).run(keep)      # counted in the shared ledger
    report = ProbeReport(rows, skipped)
    print(report.text())
    print(f"written to {report.write(a.out)}")
    return 3 if any(r.get("aborted") for r in rows) else 0


if __name__ == "__main__":
    sys.exit(main())
