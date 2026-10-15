"""gemini.py - a small REST client for the Gemini API (urllib only; no SDK, no dependency).

    key        ApiKeyLoader        GEMINI_API_KEY, else ~/.config/emergence/API_Keys (never printed, logged or written)
    client     GeminiClient        models.list, countTokens, generateContent (structured JSON output)
    models     ModelCatalog        which models to use, in which order (Flash Lite first, then Flash; other families on request)
    families   ModelFamilies       what each family of models can do (systemInstruction, structured JSON, thinking setting)
    strategy   RequestStrategy     how a request is built for a model: StructuredStrategy (normal) or PromptOnlyStrategy
                                   (everything folded in the user text, pure JSON asked, JSON extracted from the reply)
    limits     RateLimiter         spacing between calls of one model; QuotaBook remembers the models spent for the day

The key travels in the x-goog-api-key header, never in a URL. Every text that may reach a log goes through Redactor.
No network call is made when this module is imported or when the classes are built.
"""
from __future__ import annotations

import json
import os
import re
import stat
import time
import http.client
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_KEY_FILE = Path.home() / ".config" / "emergence" / "API_Keys"
ENV_VAR = "GEMINI_API_KEY"


class ApiKeyError(RuntimeError):
    """No usable key (the message never contains the key)."""


class ApiKeyLoader:
    """The key comes from the environment, else from a file outside the repository. Accepted file contents: a single
    key, or a line GEMINI_API_KEY=... (optionally 'export ' and quotes). Other lines are ignored."""

    def __init__(self, env: dict | None = None, path: Path | None = None):
        self.env = os.environ if env is None else env
        self.path = Path(path) if path is not None else DEFAULT_KEY_FILE

    def load(self) -> str:
        k = self.env.get(ENV_VAR, "").strip()
        if k:
            return k
        if not self.path.exists():
            raise ApiKeyError(f"no key: set {ENV_VAR} or put it in {self.path} (permissions 600)")
        self.check_permissions()
        key = self.parse(self.path.read_text())
        if not key:
            raise ApiKeyError(f"no key found in {self.path}")
        return key

    def check_permissions(self) -> None:
        mode = stat.S_IMODE(self.path.stat().st_mode)
        if mode & 0o077:
            raise ApiKeyError(f"{self.path} is readable by others (mode {mode:o}); run: chmod 600 {self.path}")

    @staticmethod
    def parse(text: str) -> str:
        loose = []
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            m = re.match(rf"^(?:export\s+)?{ENV_VAR}\s*=\s*(.+)$", line)
            if m:
                return m.group(1).strip().strip("'\"")
            if "=" not in line and " " not in line:
                loose.append(line.strip("'\""))
        return loose[0] if len(loose) == 1 else ""


class Redactor:
    """Removes the secret (and its URL-encoded form) from any text before it is shown or written."""

    def __init__(self, secret: str = ""):
        self.secret = secret

    def clean(self, text: str) -> str:
        if self.secret and len(self.secret) >= 8:
            text = text.replace(self.secret, "<key>")
        return re.sub(r"AIza[0-9A-Za-z_\-]{20,}", "<key>", text)


# ---------------------------------------------------------------------------------------------------- limits
class RateLimiter:
    """At most rpm calls per minute for one model: waits so that calls are spaced 60/rpm seconds apart."""

    def __init__(self, rpm: float, clock=time.monotonic, sleep=time.sleep):
        self.interval, self.clock, self.sleep, self._next = 60.0 / rpm, clock, sleep, 0.0

    def wait(self) -> float:
        now = self.clock()
        pause = max(0.0, self._next - now)
        if pause:
            self.sleep(pause)
        self._next = max(now, self._next) + self.interval
        return pause


@dataclass(frozen=True)
class Quota:
    rpm: float
    rpd: int


class QuotaTable:
    """Free-tier figures given by Monsieur (11 oct.): Flash Lite 15 req/min and 500/day, Flash 5 req/min and 20/day.
    They are assumptions: the client also reads the 429 answers and adapts."""

    LITE, FLASH = Quota(15, 500), Quota(5, 20)

    @classmethod
    def for_model(cls, name: str) -> Quota:
        return cls.LITE if "flash-lite" in name else cls.FLASH


class QuotaBook:
    """Models whose daily quota is spent are skipped until the next run."""

    def __init__(self):
        self.spent: set[str] = set()
        self.calls: dict[str, int] = {}

    def spend(self, model: str) -> None:
        self.spent.add(model)

    def count(self, model: str) -> None:
        self.calls[model] = self.calls.get(model, 0) + 1

    def available(self, models: list[str]) -> list[str]:
        return [m for m in models if m not in self.spent and self.calls.get(m, 0) < QuotaTable.for_model(m).rpd]


@dataclass(frozen=True)
class ModelFamily:
    """A family of models and what its members accept by default (a quota.toml model can override each flag, with what the
    probe OBSERVED)."""
    name: str
    pattern: str
    system_instruction: bool = True
    json_schema: bool = True
    thinking_config: bool = True

    def matches(self, model: str) -> bool:
        return re.match(self.pattern, model) is not None


class ModelFamilies:
    """The registry. Order matters: the first family that matches wins (flash-lite before flash)."""

    FLASH_LITE = ModelFamily("gemini-flash-lite", r"^gemini-(?:[\d.]+-)?flash-lite(?:-|$)")
    FLASH = ModelFamily("gemini-flash", r"^gemini-(?:[\d.]+-)?flash(?:-|$)")
    PRO = ModelFamily("gemini-pro", r"^gemini-(?:[\d.]+-)?pro(?:-|$)")
    GEMMA = ModelFamily("gemma", r"^gemma-", thinking_config=False)       # thinkingConfig never asked of Gemma
    OTHER = ModelFamily("other", r"")
    ALL = (FLASH_LITE, FLASH, PRO, GEMMA)
    DEFAULT = (FLASH_LITE, FLASH)                                       # what ModelCatalog.chain() lists without arguments

    @classmethod
    def of(cls, model: str) -> ModelFamily:
        return next((f for f in cls.ALL if f.matches(model)), cls.OTHER)


class ModelCatalog:
    """From the models.list answer, the models usable for the pilot. By default Flash Lite (newest stable first), then Flash;
    `families` opens other families (ModelFamilies.ALL: + pro, gemma), still without the aliases ("latest") and the
    non-text models."""

    EXCLUDE = ("tts", "image", "live", "audio", "embedding", "robotics", "computer", "exp", "learnlm", "vision", "aqa",
               "gemma", "imagen", "veo", "thinking", "customtools", "latest", "transcribe", "lyria", "deep-research", "nano-banana",
               "antigravity", "omni")

    def __init__(self, models: list[dict]):
        self.models = models

    @staticmethod
    def short(name: str) -> str:
        return name.split("/", 1)[-1]

    @classmethod
    def key(cls, name: str):
        n = cls.short(name)
        ver = tuple(int(x) for x in re.findall(r"(?<=gemini-)(\d+(?:\.\d+)*)", n)[0].split(".")) if re.search(r"gemini-\d", n) else (0,)
        stable = not re.search(r"preview|-\d{2}-\d{2,4}|-\d{3}$", n)
        return (not stable, tuple(-x for x in ver), n)

    def chain(self, families: tuple = ModelFamilies.DEFAULT) -> list[str]:
        by_family: dict = {f.name: [] for f in families}
        for m in self.models:
            n = self.short(m.get("name", ""))
            if "generateContent" not in m.get("supportedGenerationMethods", []):
                continue
            fam = ModelFamilies.of(n)
            exclude = [x for x in self.EXCLUDE if not (fam.name == "gemma" and x == "gemma")]
            if fam.name not in by_family or any(x in n for x in exclude):
                continue
            by_family[fam.name].append(n)
        return [n for f in families for n in sorted(by_family[f.name], key=self.key)]


# ---------------------------------------------------------------------------------------------------- strategies
class SchemaText:
    """A Gemini response schema (upper-case types) as the plain JSON Schema a model can read in a prompt."""

    LISTED_ELSEWHERE = ("enum", "propertyOrdering")      # the compact text drops them: the instructions list the same values

    @classmethod
    def plain(cls, schema, compact: bool = False):
        if isinstance(schema, dict):
            return {k: (v.lower() if k == "type" and isinstance(v, str) else cls.plain(v, compact)) for k, v in schema.items()
                    if not (compact and k in cls.LISTED_ELSEWHERE and isinstance(v, list))}
        if isinstance(schema, list):
            return [cls.plain(x, compact) for x in schema]
        return schema

    @classmethod
    def text(cls, schema: dict, compact: bool = False) -> str:
        """`compact`: without the `enum` lists and the `propertyOrdering` (the gesture ids, parameter names, variables and
        kinds are all written in the instructions; the validator stays the judge of every value)."""
        return json.dumps(cls.plain(schema, compact), separators=(",", ":"), ensure_ascii=False)


class JsonExtractor:
    """The first balanced top-level JSON object of a reply that may carry a Markdown fence or a sentence around it."""

    @staticmethod
    def extract(text: str) -> str:
        """The object as text, or the reply unchanged when none is found (the validator then refuses it by its usual code)."""
        s = text.strip()
        start = s.find("{")
        while start != -1:
            depth, in_str, esc = 0, False, False
            for i in range(start, len(s)):
                c = s[i]
                if in_str:
                    if esc:
                        esc = False
                    elif c == "\\":
                        esc = True
                    elif c == '"':
                        in_str = False
                    continue
                if c == '"':
                    in_str = True
                elif c == "{":
                    depth += 1
                elif c == "}":
                    depth -= 1
                    if depth == 0:
                        candidate = s[start:i + 1]
                        try:
                            json.loads(candidate)
                            return candidate
                        except ValueError:
                            break
            start = s.find("{", start + 1)
        return text


class RequestStrategy:
    """How one request is written for a model. body() -> the generateContent JSON; shape() -> the ApiResult the rest sees."""

    name = "base"

    def body(self, system: str, user: str, schema: dict, temperature: float, max_output_tokens: int,
             thinking_budget: int | None) -> dict:
        raise NotImplementedError

    def shape(self, result: "ApiResult") -> "ApiResult":
        return result


class StructuredStrategy(RequestStrategy):
    """systemInstruction + responseMimeType/responseSchema (what every Gemini model of the chain accepts)."""

    name = "structured"

    def body(self, system, user, schema, temperature, max_output_tokens, thinking_budget):
        cfg = {"responseMimeType": "application/json", "responseSchema": schema, "temperature": temperature,
               "maxOutputTokens": max_output_tokens}
        if thinking_budget is not None:
            cfg["thinkingConfig"] = {"thinkingBudget": thinking_budget}
        return {**GeminiClient._contents(system, user), "generationConfig": cfg}


class PromptOnlyStrategy(RequestStrategy):
    """For a model without structured JSON and/or without systemInstruction (probable for Gemma): the instructions go in
    the user text, the schema is written in the prompt, pure JSON is asked, and the JSON object is extracted from the reply.
    `fold_system` / `fold_schema` can be turned off one by one when a model lacks only one of the two features. The validator
    and the governor stay the judges of what comes out; this class only changes the way of asking."""

    name = "prompt_only"

    def __init__(self, fold_system: bool = True, fold_schema: bool = True, thinking_config: bool = False,
                 compact_schema: bool = False):
        self.fold_system, self.fold_schema, self.thinking_config = fold_system, fold_schema, thinking_config
        self.compact_schema = compact_schema

    def prompt(self, system: str, user: str, schema: dict) -> str:
        parts = []
        if self.fold_system:
            parts.append("=== INSTRUCTIONS (follow them exactly) ===\n" + system.strip())
        if self.fold_schema:
            parts.append("=== REPLY FORMAT ===\nReply with ONE JSON object and nothing else: no sentence before or after it, "
                         "no Markdown fence, no comment. It must follow this JSON Schema"
                         + (" (the allowed values are those listed in the instructions)" if self.compact_schema else " exactly")
                         + ":\n" + SchemaText.text(schema, self.compact_schema))
        parts.append(("=== TASK ===\n" if parts else "") + user.strip())
        return "\n\n".join(parts) + ("\n\nReply now with the JSON object only." if self.fold_schema else "")

    def body(self, system, user, schema, temperature, max_output_tokens, thinking_budget):
        cfg = {"temperature": temperature, "maxOutputTokens": max_output_tokens}
        if not self.fold_schema:
            cfg.update({"responseMimeType": "application/json", "responseSchema": schema})
        if thinking_budget is not None and self.thinking_config:
            cfg["thinkingConfig"] = {"thinkingBudget": thinking_budget}
        contents = [{"role": "user", "parts": [{"text": self.prompt(system, user, schema)}]}]
        out = {"contents": contents, "generationConfig": cfg}
        if not self.fold_system:
            out["systemInstruction"] = {"parts": [{"text": system}]}
        return out

    def shape(self, result):
        if result.text:
            result.text = JsonExtractor.extract(result.text)
        return result


STRUCTURED = StructuredStrategy()


# ---------------------------------------------------------------------------------------------------- client
@dataclass
class ApiResult:
    ok: bool
    status: int = 0
    text: str = ""
    finish: str = ""
    usage: dict = field(default_factory=dict)
    latency: float = 0.0
    error: str = ""
    quota_scope: str = ""          # "day" | "minute" | "" (for a 429)
    retry_after: float = 0.0
    quota_violations: list = field(default_factory=list)   # QuotaFailure violations of a 429 (quotaMetric, quotaId, quotaValue...)


class GeminiClient:
    def __init__(self, key: str, base_url: str = BASE_URL, timeout: float = 120.0, opener=None):
        self.key, self.base, self.timeout = key, base_url, timeout
        self.redactor = Redactor(key)
        self._open = opener or urllib.request.urlopen
        self.strategies: dict[str, RequestStrategy] = {}        # model -> how to ask it (default: structured)

    # ---- plumbing
    def _request(self, method: str, path: str, body: dict | None = None) -> tuple[int, dict, float]:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(f"{self.base}/{path}", data=data, method=method,
                                     headers={"x-goog-api-key": self.key, "Content-Type": "application/json"})
        t0 = time.monotonic()
        try:
            with self._open(req, timeout=self.timeout) as resp:
                status, raw = resp.status, resp.read()
        except urllib.error.HTTPError as e:
            status, raw = e.code, e.read()
        except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException) as e:
            return 0, {"error": {"message": self.redactor.clean(str(e)), "status": "NETWORK"}}, time.monotonic() - t0
        try:
            payload = json.loads(raw or b"{}")
        except ValueError:
            payload = {"error": {"message": self.redactor.clean(raw[:300].decode("utf-8", "replace"))}}
        if isinstance(payload, list):                       # some errors come wrapped in a list
            payload = payload[0] if payload and isinstance(payload[0], dict) else {}
        if not isinstance(payload, dict):
            payload = {}
        return status, payload, time.monotonic() - t0

    # ---- models.list
    def list_models(self) -> list[dict]:
        out, token = [], ""
        while True:
            status, payload, _ = self._request("GET", "models?pageSize=100" + (f"&pageToken={urllib.parse.quote(token)}" if token else ""))
            if status != 200:
                raise RuntimeError(f"models.list failed: HTTP {status} {self._message(payload)}")
            out += payload.get("models", [])
            token = payload.get("nextPageToken", "")
            if not token:
                return out

    # ---- countTokens
    def count_tokens(self, model: str, system: str, user: str, schema: dict | None = None) -> int:
        req = {"model": f"models/{model}", **self._contents(system, user)}
        if schema is not None:
            req["generationConfig"] = {"responseMimeType": "application/json", "responseSchema": schema}
        body = {"generateContentRequest": req}
        status, payload, _ = self._request("POST", f"models/{model}:countTokens", body)
        if status != 200:
            raise RuntimeError(f"countTokens failed: HTTP {status} {self._message(payload)}")
        return int(payload["totalTokens"])

    # ---- generateContent
    def post_generate(self, model: str, body: dict) -> tuple[int, dict, float]:
        """A raw generateContent call: (HTTP status, JSON payload, latency). For the probe, which reads the payload itself."""
        return self._request("POST", f"models/{model}:generateContent", body)

    @staticmethod
    def _contents(system: str, user: str) -> dict:
        return {"systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": user}]}]}

    def generate(self, model: str, system: str, user: str, schema: dict, temperature: float = 0.9,
                 max_output_tokens: int = 2048, thinking_budget: int | None = None) -> ApiResult:
        strategy = self.strategies.get(model, STRUCTURED)
        body = strategy.body(system, user, schema, temperature, max_output_tokens, thinking_budget)
        status, payload, latency = self.post_generate(model, body)
        if status != 200:
            return self._failure(status, payload, latency)
        cands = payload.get("candidates") or []
        parts = (cands[0].get("content", {}).get("parts") or []) if cands else []
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        finish = cands[0].get("finishReason", "") if cands else "NO_CANDIDATE:" + str(payload.get("promptFeedback", {}))
        return strategy.shape(ApiResult(bool(text), 200, text, finish, payload.get("usageMetadata", {}), latency))

    # ---- errors
    @staticmethod
    def _message(payload: dict) -> str:
        err = payload.get("error", {})
        return str(err.get("message", "") if isinstance(err, dict) else err)[:300]

    def _failure(self, status: int, payload: dict, latency: float) -> ApiResult:
        err = payload.get("error", {})
        err = err if isinstance(err, dict) else {"message": str(err)}
        scope, retry, violations = "", 0.0, []
        if status == 429:
            scope, retry = self.classify_quota(err)
            violations = self.quota_violations(err)
        return ApiResult(False, status, error=self.redactor.clean(f"{err.get('status', '')} {self._message(payload)}".strip()),
                         latency=latency, quota_scope=scope, retry_after=retry, quota_violations=violations)

    @staticmethod
    def quota_violations(err: dict) -> list:
        """The `violations` of the QuotaFailure detail of a 429: [{quotaMetric, quotaId, quotaValue, ...}]."""
        out = []
        for d in err.get("details", []):
            if isinstance(d, dict) and "QuotaFailure" in str(d.get("@type", "")):
                out += [v for v in d.get("violations", []) if isinstance(v, dict)]
        return out

    @staticmethod
    def classify_quota(err: dict) -> tuple[str, float]:
        """A 429 -> ('day' | 'minute', seconds to wait). Per-day quotas do not come back before tomorrow."""
        scope, retry = "minute", 0.0
        blob = json.dumps(err)
        if re.search(r"PerDay|per day|daily", blob, re.I):
            scope = "day"
        for d in err.get("details", []):
            if not isinstance(d, dict):
                continue
            m = re.match(r"^(\d+(?:\.\d+)?)s$", str(d.get("retryDelay", "")))
            if m:
                retry = float(m.group(1))
        return scope, retry
