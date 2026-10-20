"""providers.py - other teachers than Gemini: any API compatible with OpenAI's chat completions (Groq, OpenRouter).

    ProviderSpec        a provider: base URL, key file (outside the repository, permissions 600), key variable
    OpenAICompatClient  one provider's REST client (urllib only): chat request, JSON asked, usage and limits read, errors classified
    RateHeaders         the X-RateLimit-* / Retry-After headers, as a small dict
    LimitReader         a 429 / 413 body -> the Gemini-shaped QuotaFailure violations that quota.py already understands
    JsonObjectStrategy  prompt-only request + response_format json_object (a model without json_schema)
    RefusalDetector     a model's own refusal of the content (finish_reason content_filter, a `refusal` field, a stock sentence):
                        COUNTED, never worked around
    ProviderRouter      the client the generator sees: routes a model name `groq/...` / `openrouter/...` to its provider, any
                        other name to Gemini; the same interface as GeminiClient (generate, strategies, redactor...)

The key travels ONLY in the `Authorization: Bearer` header: never in a URL, a log, a journal, an error or a file. Every text that
may be shown goes through the Redactor (gemini.py). Nothing here reads a key or opens the network when imported or built.
A model is named `<provider>/<id the API knows>`: that whole name is the `teacher` of a dataset line.
"""
from __future__ import annotations

import http.client
import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from .gemini import ApiKeyLoader, ApiResult, GeminiClient, PromptOnlyStrategy, Redactor, SchemaText, StructuredStrategy

USER_AGENT = "emergence-teacher/1.0"        # Groq sits behind a firewall that refuses the default urllib agent
CONFIG_DIR = Path.home() / ".config" / "emergence"
THINK_BLOCK = re.compile(r"<think>.*?</think>", re.S | re.I)


@dataclass(frozen=True)
class ProviderSpec:
    name: str                     # the prefix of the model names: "groq", "openrouter"
    base_url: str
    key_file: Path
    env_var: str
    free_suffix: str = ""         # ":free" for OpenRouter

    def loader(self, path: Path | None = None) -> ApiKeyLoader:
        return ApiKeyLoader(path=path or self.key_file, env_var=self.env_var)


class Providers:
    GROQ = ProviderSpec("groq", "https://api.groq.com/openai/v1", CONFIG_DIR / "Groq_Key", "GROQ_API_KEY")
    OPENROUTER = ProviderSpec("openrouter", "https://openrouter.ai/api/v1", CONFIG_DIR / "OpenRouter_Key", "OPENROUTER_API_KEY",
                              ":free")
    ALL = {"groq": GROQ, "openrouter": OPENROUTER}

    @staticmethod
    def of(model: str) -> str:
        """'groq' for 'groq/openai/gpt-oss-20b', 'gemini' for every other name."""
        head = model.split("/", 1)[0]
        return head if "/" in model and head in Providers.ALL else "gemini"

    @staticmethod
    def api_id(model: str) -> str:
        """The id the API knows: the name without its provider prefix."""
        return model.split("/", 1)[1] if Providers.of(model) != "gemini" else model


class MultiRedactor:
    """Several Redactors as one (one key per provider)."""

    def __init__(self, *redactors: Redactor):
        self.redactors = [r for r in redactors if r is not None]

    @property
    def secret(self) -> str:
        return ""

    def clean(self, text: str) -> str:
        for r in self.redactors:
            text = r.clean(text)
        return Redactor("").clean(text)


# ---------------------------------------------------------------------------------------------------- strategy
class JsonObjectStrategy(PromptOnlyStrategy):
    """The schema is written in the prompt (PromptOnlyStrategy) AND the provider is asked for `json_object` mode, which makes it
    return a JSON object. For a model without `json_schema` that does accept `response_format: json_object`."""

    name = "json_object"
    json_object = True


# ---------------------------------------------------------------------------------------------------- limits
class RateHeaders:
    """The rate-limit headers a provider sends (lower-cased names), kept as strings: x-ratelimit-*, retry-after."""

    @staticmethod
    def pick(headers) -> dict:
        out = {}
        for k, v in (headers.items() if headers else []):
            k = str(k).lower()
            if k.startswith("x-ratelimit") or k == "retry-after":
                out[k] = str(v)[:60]
        return out

    @staticmethod
    def retry_seconds(headers: dict) -> float:
        try:
            return max(0.0, float(headers.get("retry-after", "")))
        except ValueError:
            return 0.0


class LimitReader:
    """A 429 (or a 413 'request too large') of Groq / OpenRouter -> (scope, retry seconds, QuotaFailure-shaped violations).
    Groq says in its message: 'Rate limit reached for model `x` ... on tokens per minute (TPM): Limit 8000, Used 7000, Requested
    3000. Please try again in 5.1s' (or 'requests per day (RPD)'). OpenRouter says 'Rate limit exceeded: free-models-per-day' and
    gives X-RateLimit-Limit / -Remaining / -Reset (epoch milliseconds) in error.metadata.headers."""

    @staticmethod
    def seconds(text: str) -> float:
        """'try again in 7m12.5s' / '2.5s' / '350ms' -> seconds (0 when absent)."""
        m = re.search(r"(?:try again|retry) in ((?:\d+(?:\.\d+)?\s*(?:h|ms|m|s)\s*)+)", text, re.I)
        if not m:
            return 0.0
        total = 0.0
        for n, unit in re.findall(r"(\d+(?:\.\d+)?)\s*(ms|h|m|s)", m.group(1), re.I):
            total += float(n) * {"h": 3600.0, "m": 60.0, "s": 1.0, "ms": 0.001}[unit.lower()]
        return total

    @classmethod
    def read(cls, message: str, payload: dict, headers: dict, now: float) -> tuple[str, float, list]:
        msg = message or ""
        meta = {}
        err = payload.get("error", {}) if isinstance(payload, dict) else {}
        if isinstance(err, dict) and isinstance(err.get("metadata"), dict):
            raw = err["metadata"].get("headers")
            meta = {str(k).lower(): str(v) for k, v in raw.items()} if isinstance(raw, dict) else {}
        blob = (msg + " " + json.dumps(err.get("metadata", {}) if isinstance(err, dict) else {})).lower()
        per_day = bool(re.search(r"per day|per-day|\(rpd\)|\(tpd\)|daily", blob))
        kind = "tokens" if re.search(r"token|\(tpm\)|\(tpd\)", blob) else "requests"
        limit = None
        m = re.search(r"limit[: ]+(\d+)", msg, re.I)
        if m:
            limit = int(m.group(1))
        elif meta.get("x-ratelimit-limit", "").isdigit():
            limit = int(meta["x-ratelimit-limit"])
        retry = RateHeaders.retry_seconds(headers) or cls.seconds(msg)
        reset_ms = meta.get("x-ratelimit-reset", "")
        if not retry and reset_ms.isdigit():
            retry = max(0.0, int(reset_ms) / 1000.0 - now)
        scope = "day" if per_day else "minute"
        violation = {"quotaId": f"{kind}Per{'Day' if per_day else 'Minute'}", "quotaMetric": kind}
        if limit is not None:
            violation["quotaValue"] = limit
        if per_day and retry:
            violation["resetAfter"] = round(retry, 1)             # when the provider says the day-quota reopens (quota.py uses it)
        return scope, retry, [violation]


class RefusalDetector:
    """A model that refuses the CONTENT of a situation (violence, say) says so in its own words. The refusal is recognised so as to
    be COUNTED; nothing is ever rephrased or retried to get round it."""

    STOCK = re.compile(r"\b(i(?:'m| am)? (?:sorry|unable)|i can(?:'|no)?t (?:help|assist|comply|provide|continue|do that)|"
                       r"i cannot (?:help|assist|comply|provide|continue)|i won'?t (?:help|assist)|cannot (?:fulfil|fulfill) "
                       r"(?:this|that) request|against my (?:guidelines|policy|policies)|violates? (?:my|our) (?:guidelines|polic))",
                       re.I)

    @classmethod
    def of(cls, result: ApiResult) -> str:
        """'' when the reply is no refusal, else a short label: 'finish:<x>', 'field', or 'text'."""
        if result.refusal:
            return "field"
        if str(result.finish).startswith(("SAFETY", "PROHIBITED", "BLOCKLIST", "content_filter")):
            return f"finish:{result.finish}"
        text = (result.text or "").strip()
        if text and "{" not in text[:200] and cls.STOCK.search(text[:400]):
            return "text"
        return ""


# ---------------------------------------------------------------------------------------------------- client
class OpenAICompatClient:
    """chat/completions of an OpenAI-compatible provider. Model names carry the provider prefix (`groq/openai/gpt-oss-20b`);
    `strategies[name]` says how to ask (Structured -> response_format json_schema; JsonObjectStrategy -> json_object;
    PromptOnlyStrategy -> schema in the prompt, JSON extracted from the reply); `options[name]` may hold `reasoning_effort`."""

    def __init__(self, provider: ProviderSpec, key: str, timeout: float = 180.0, opener=None, clock=time.time):
        self.provider, self.key, self.timeout, self.clock = provider, key, timeout, clock
        self.redactor = Redactor(key)
        self._open = opener or urllib.request.urlopen
        self.strategies: dict = {}
        self.options: dict = {}

    # ---- plumbing
    def _request(self, method: str, path: str, body: dict | None = None) -> tuple[int, dict, dict, float]:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(f"{self.provider.base_url}/{path}", data=data, method=method,
                                     headers={"Authorization": f"Bearer {self.key}", "Content-Type": "application/json",
                                              "User-Agent": USER_AGENT, "Accept": "application/json"})
        t0 = time.monotonic()
        headers: dict = {}
        try:
            with self._open(req, timeout=self.timeout) as resp:
                status, raw, headers = resp.status, resp.read(), RateHeaders.pick(getattr(resp, "headers", None))
        except urllib.error.HTTPError as e:
            status, raw, headers = e.code, e.read(), RateHeaders.pick(e.headers)
        except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException) as e:
            return 0, {"error": {"message": self.redactor.clean(str(e)), "type": "network"}}, {}, time.monotonic() - t0
        try:
            payload = json.loads(raw or b"{}")
        except ValueError:
            payload = {"error": {"message": self.redactor.clean(raw[:300].decode("utf-8", "replace"))}}
        return status, payload if isinstance(payload, dict) else {}, headers, time.monotonic() - t0

    def list_models(self) -> list[dict]:
        status, payload, _, _ = self._request("GET", "models")
        if status != 200:
            raise RuntimeError(f"{self.provider.name} models failed: HTTP {status} {self._message(payload)}")
        return [m for m in payload.get("data", []) if isinstance(m, dict)]

    # ---- the request
    @staticmethod
    def plain_schema(schema: dict) -> dict:
        """The Gemini response schema as the plain JSON Schema OpenAI-style APIs read (lower-case types, no propertyOrdering)."""
        if isinstance(schema, dict):
            return {k: (v.lower() if k == "type" and isinstance(v, str) else OpenAICompatClient.plain_schema(v))
                    for k, v in schema.items() if k not in ("propertyOrdering", "nullable")}
        if isinstance(schema, list):
            return [OpenAICompatClient.plain_schema(x) for x in schema]
        return schema

    def body(self, model: str, system: str, user: str, schema: dict, temperature: float, max_tokens: int) -> dict:
        strategy = self.strategies.get(model)
        messages = []
        body: dict = {"model": Providers.api_id(model), "temperature": temperature, "max_tokens": max_tokens}
        if strategy is None or isinstance(strategy, StructuredStrategy):
            messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
            body["response_format"] = {"type": "json_schema", "json_schema": {"name": "decisions", "strict": False,
                                                                              "schema": self.plain_schema(schema)}}
        else:
            text = strategy.prompt(system, user, schema)
            if not strategy.fold_system:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": text})
            if getattr(strategy, "json_object", False):
                body["response_format"] = {"type": "json_object"}
        body["messages"] = messages
        effort = self.options.get(model, {}).get("reasoning_effort")
        if effort:
            if self.provider.name == "openrouter":
                body["reasoning"] = {"effort": effort}
            else:
                body["reasoning_effort"] = effort
        return body

    def generate(self, model: str, system: str, user: str, schema: dict, temperature: float = 0.9,
                 max_output_tokens: int = 2048, thinking_budget: int | None = None) -> ApiResult:
        strategy = self.strategies.get(model)
        body = self.body(model, system, user, schema, temperature, max_output_tokens)
        status, payload, headers, latency = self._request("POST", "chat/completions", body)
        err = payload.get("error")
        if status == 200 and err and not payload.get("choices"):          # OpenRouter reports an upstream failure inside a 200
            code = err.get("code") if isinstance(err, dict) else None
            status = code if isinstance(code, int) and code >= 400 else 502
        if status != 200:
            return self._failure(status, payload, headers, latency)
        choices = payload.get("choices") or []
        choice = choices[0] if choices and isinstance(choices[0], dict) else {}
        msg = choice.get("message") if isinstance(choice.get("message"), dict) else {}
        text = THINK_BLOCK.sub("", str(msg.get("content") or "")).strip()
        refusal = self.redactor.clean(str(msg.get("refusal") or ""))[:300]
        finish = self._finish(str(choice.get("finish_reason") or ""), bool(refusal), bool(choices))
        r = ApiResult(bool(text), 200, text, finish, self.usage(payload.get("usage")), latency, rate_limit=headers, refusal=refusal)
        return strategy.shape(r) if strategy is not None else r

    @staticmethod
    def _finish(reason: str, refused: bool, has_choice: bool) -> str:
        if refused:
            return "SAFETY"
        if not has_choice:
            return "NO_CANDIDATE"
        return {"stop": "STOP", "length": "MAX_TOKENS", "content_filter": "SAFETY"}.get(reason, reason.upper() or "STOP")

    @staticmethod
    def usage(u) -> dict:
        """OpenAI usage -> the keys the rest of the program reads (Gemini names): input, output (without reasoning), reasoning."""
        if not isinstance(u, dict):
            return {}
        prompt, done = int(u.get("prompt_tokens", 0) or 0), int(u.get("completion_tokens", 0) or 0)
        details = u.get("completion_tokens_details") if isinstance(u.get("completion_tokens_details"), dict) else {}
        thought = int(details.get("reasoning_tokens", 0) or 0)
        out = {"promptTokenCount": prompt, "candidatesTokenCount": max(0, done - thought),
               "totalTokenCount": int(u.get("total_tokens", prompt + done) or 0)}
        if thought:
            out["thoughtsTokenCount"] = thought
        cached = (u.get("prompt_tokens_details") or {}).get("cached_tokens") if isinstance(u.get("prompt_tokens_details"), dict) else 0
        if cached:
            out["cachedContentTokenCount"] = int(cached)
        return out

    # ---- errors
    @staticmethod
    def _message(payload: dict) -> str:
        err = payload.get("error", {})
        return re.sub(r"org_[0-9A-Za-z]+", "org_<id>", str(err.get("message", "") if isinstance(err, dict) else err))[:300]

    def _failure(self, status: int, payload: dict, headers: dict, latency: float) -> ApiResult:
        err = payload.get("error", {})
        err = err if isinstance(err, dict) else {"message": str(err)}
        message = self._message(payload)
        scope, retry, violations = "", 0.0, []
        if status == 429:
            scope, retry, violations = LimitReader.read(message, payload, headers, self.clock())
        label = str(err.get("type") or err.get("code") or "")
        return ApiResult(False, status, error=self.redactor.clean(f"{label} {message}".strip()), latency=latency, quota_scope=scope,
                         retry_after=retry, quota_violations=violations, rate_limit=headers)


# ---------------------------------------------------------------------------------------------------- router
@dataclass
class ProviderRouter:
    """The one client of a run. `clients` maps 'gemini' / 'groq' / 'openrouter' to the client of that provider (only the ones
    this run uses). Same interface as GeminiClient for what the generator, caller, probe and bench call."""
    clients: dict = field(default_factory=dict)
    strategies: dict = field(default_factory=dict)
    options: dict = field(default_factory=dict)

    def __post_init__(self):
        for c in self.clients.values():              # one shared table: install() writes it, every client reads it
            c.strategies = self.strategies
            if isinstance(c, OpenAICompatClient):
                c.options = self.options

    @classmethod
    def build(cls, providers: list[str], gemini_key_file: Path | None = None, opener=None) -> "ProviderRouter":
        """The clients for these providers, each with its own key (ApiKeyError when one is missing; the message holds no key)."""
        clients: dict = {}
        for name in dict.fromkeys(providers):
            if name == "gemini":
                clients[name] = GeminiClient(ApiKeyLoader(path=gemini_key_file).load(), opener=opener)
            else:
                spec = Providers.ALL[name]
                clients[name] = OpenAICompatClient(spec, spec.loader().load(), opener=opener)
        return cls(clients)

    @property
    def redactor(self) -> MultiRedactor:
        return MultiRedactor(*[c.redactor for c in self.clients.values()])

    key = ""               # no single key: the redactor holds them all

    def configure(self, spec) -> None:
        """quota.QuotaConfig.install: the per-model options (reasoning effort)."""
        if getattr(spec, "reasoning_effort", ""):
            self.options[spec.name] = {"reasoning_effort": spec.reasoning_effort}

    def client_for(self, model: str):
        provider = Providers.of(model)
        if provider not in self.clients:
            raise KeyError(f"no client for provider {provider!r} (model {model})")
        return self.clients[provider]

    def generate(self, model, system, user, schema, temperature=0.9, max_output_tokens=2048, thinking_budget=None) -> ApiResult:
        return self.client_for(model).generate(model, system, user, schema, temperature, max_output_tokens, thinking_budget)

    # ---- the Gemini-only calls (probe, bench, ledger gate) and the static helpers
    quota_violations = staticmethod(GeminiClient.quota_violations)
    classify_quota = staticmethod(GeminiClient.classify_quota)

    def post_generate(self, model: str, body: dict):
        return self.client_for(model).post_generate(model, body)

    def list_models(self):
        return self.clients["gemini"].list_models()

    def count_tokens(self, *a, **kw):
        return self.clients["gemini"].count_tokens(*a, **kw)
