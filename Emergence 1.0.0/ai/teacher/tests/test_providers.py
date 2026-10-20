"""Tests of the other teachers (Groq, OpenRouter): client, limits, router, quota.toml, lean text, probe, bench. NO network, no key:
every key here is a made-up string, every reply is scripted.

    python3 -m unittest discover -s ai/teacher/tests -t ai
"""
from __future__ import annotations

import io
import json
import os
import re
import tempfile
import unittest
import urllib.error
from pathlib import Path

from teacher.bench import QualityBench
from teacher.batch import BatchInstructions
from teacher.caller import ModelCaller
from teacher.gemini import STRUCTURED, ApiKeyError, ApiKeyLoader, ApiResult, PromptOnlyStrategy, Redactor
from teacher.phrasebook import PhraseBook
from teacher.probe import SECRET_WORD, CompatProbe
from teacher.providers import (JsonObjectStrategy, LimitReader, MultiRedactor, OpenAICompatClient, ProviderRouter, Providers,
                               RateHeaders, RefusalDetector)
from teacher.quota import DEFAULT_CONFIG, Limits, ModelSpec, QuotaBook, QuotaConfig, QuotaError
from teacher.tests.test_generator import FakeTeacher, TK, sampler_factory
from teacher.tests.test_quota import FakeClock, config, spec

GROQ_KEY = "gsk_" + "Z" * 48
OR_KEY = "sk-or-v1-" + "q" * 48
SCHEMA = {"type": "OBJECT", "propertyOrdering": ["answer"], "properties": {"answer": {"type": "STRING"}}, "required": ["answer"]}


class Resp:
    def __init__(self, status, body, headers=None):
        self.status, self._raw, self.headers = status, json.dumps(body).encode(), headers or {}

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class ScriptedOpener:
    """Answers from a list [(status, body, headers)]; an exception instance in the list is raised. Records every request."""

    def __init__(self, *script):
        self.script, self.seen = list(script), []

    def __call__(self, req, timeout):
        self.seen.append(req)
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        status, body, headers = (list(item) + [None])[:3]
        if status >= 400:
            raise urllib.error.HTTPError(req.full_url, status, "err", headers or {}, io.BytesIO(json.dumps(body).encode()))
        return Resp(status, body, headers)


def chat(text, finish="stop", usage=None, **msg):
    return 200, {"choices": [{"message": {"content": text, **msg}, "finish_reason": finish}],
                 "usage": usage or {"prompt_tokens": 100, "completion_tokens": 30, "total_tokens": 130}}, {"x-ratelimit-limit-requests": "1000"}


def client(opener, provider=Providers.GROQ, key=GROQ_KEY):
    return OpenAICompatClient(provider, key, opener=opener, clock=lambda: 1000.0)


class ClientTests(unittest.TestCase):
    def test_key_only_in_the_authorization_header_and_never_in_the_url_or_body(self):
        op = ScriptedOpener(chat('{"answer":"x"}'))
        c = client(op)
        c.strategies["groq/m"] = STRUCTURED
        r = c.generate("groq/m", "SYS", "USER", SCHEMA)
        req = op.seen[0]
        self.assertTrue(r.ok)
        self.assertEqual(req.get_header("Authorization"), f"Bearer {GROQ_KEY}")
        self.assertNotIn(GROQ_KEY, req.full_url)
        self.assertNotIn(GROQ_KEY, req.data.decode())
        self.assertTrue(req.full_url.endswith("/openai/v1/chat/completions"))
        self.assertEqual(req.get_header("User-agent"), "emergence-teacher/1.0")

    def test_structured_request_sends_a_plain_json_schema_and_the_provider_prefix_is_removed(self):
        op = ScriptedOpener(chat("{}"))
        c = client(op)
        c.strategies["groq/openai/gpt-oss-20b"] = STRUCTURED
        c.generate("groq/openai/gpt-oss-20b", "SYS", "USER", SCHEMA, 0.5, 777)
        body = json.loads(op.seen[0].data)
        self.assertEqual(body["model"], "openai/gpt-oss-20b")
        self.assertEqual((body["temperature"], body["max_tokens"]), (0.5, 777))
        self.assertEqual([m["role"] for m in body["messages"]], ["system", "user"])
        sch = body["response_format"]["json_schema"]["schema"]
        self.assertEqual(sch["type"], "object")
        self.assertEqual(sch["properties"]["answer"]["type"], "string")
        self.assertNotIn("propertyOrdering", sch)

    def test_prompt_only_and_json_object_ways_of_asking(self):
        op = ScriptedOpener(chat("{}"), chat("{}"))
        c = client(op, Providers.OPENROUTER, OR_KEY)
        c.strategies["openrouter/a:free"] = PromptOnlyStrategy(fold_system=False, fold_schema=True)
        c.strategies["openrouter/b:free"] = JsonObjectStrategy(fold_system=False, fold_schema=True)
        c.generate("openrouter/a:free", "SYS", "USER", SCHEMA)
        c.generate("openrouter/b:free", "SYS", "USER", SCHEMA)
        a, b = (json.loads(r.data) for r in op.seen)
        self.assertNotIn("response_format", a)
        self.assertEqual(a["messages"][0], {"role": "system", "content": "SYS"})
        self.assertIn("REPLY FORMAT", a["messages"][1]["content"])
        self.assertEqual(b["response_format"], {"type": "json_object"})
        self.assertEqual(a["model"], "a:free")

    def test_reasoning_effort_goes_where_each_provider_wants_it(self):
        op = ScriptedOpener(chat("{}"), chat("{}"))
        c = client(op)
        c.options["groq/m"] = {"reasoning_effort": "low"}
        c.generate("groq/m", "S", "U", SCHEMA)
        o = client(op, Providers.OPENROUTER, OR_KEY)
        o.options["openrouter/m"] = {"reasoning_effort": "low"}
        o.generate("openrouter/m", "S", "U", SCHEMA)
        g, r = (json.loads(x.data) for x in op.seen)
        self.assertEqual(g["reasoning_effort"], "low")
        self.assertEqual(r["reasoning"], {"effort": "low"})

    def test_reply_is_read_usage_mapped_think_blocks_removed_headers_kept(self):
        usage = {"prompt_tokens": 120, "completion_tokens": 50, "total_tokens": 170,
                 "completion_tokens_details": {"reasoning_tokens": 20}}
        op = ScriptedOpener(chat('<think>{"a":1}</think> {"answer":"x"}', "length", usage))
        c = client(op)
        c.strategies["groq/m"] = PromptOnlyStrategy(fold_system=False)
        r = c.generate("groq/m", "S", "U", SCHEMA)
        self.assertEqual(r.text, '{"answer":"x"}')
        self.assertEqual(r.finish, "MAX_TOKENS")
        self.assertEqual((r.usage["promptTokenCount"], r.usage["candidatesTokenCount"], r.usage["thoughtsTokenCount"]), (120, 30, 20))
        self.assertEqual(r.rate_limit, {"x-ratelimit-limit-requests": "1000"})

    def test_content_filter_and_refusal_field_are_recognised_not_worked_around(self):
        op = ScriptedOpener(chat("", "content_filter"), chat("", "stop", refusal="I can't help with that."))
        c = client(op)
        a = c.generate("groq/m", "S", "U", SCHEMA)
        b = c.generate("groq/m", "S", "U", SCHEMA)
        self.assertEqual(len(op.seen), 2)                                    # nothing was asked again
        self.assertTrue(RefusalDetector.of(a).startswith("finish:"))
        self.assertEqual(RefusalDetector.of(b), "field")
        t = ApiResult(True, 200, "I'm sorry, but I can't help with that request.", "STOP")
        self.assertEqual(RefusalDetector.of(t), "text")
        self.assertEqual(RefusalDetector.of(ApiResult(True, 200, '{"decisions":[]}', "STOP")), "")
        self.assertEqual(RefusalDetector.of(ApiResult(True, 200, 'Here: {"I can\'t help":1}', "STOP")), "")

    def test_errors_never_carry_the_key(self):
        op = ScriptedOpener(urllib.error.URLError(f"cannot reach host with {GROQ_KEY}"),
                            (401, {"error": {"message": f"bad key {GROQ_KEY}", "type": "invalid"}}))
        c = client(op)
        r1 = c.generate("groq/m", "S", "U", SCHEMA)
        r2 = c.generate("groq/m", "S", "U", SCHEMA)
        self.assertEqual((r1.status, r2.status), (0, 401))
        for r in (r1, r2):
            self.assertNotIn(GROQ_KEY, r.error)
        self.assertNotIn(GROQ_KEY, MultiRedactor(Redactor(GROQ_KEY), Redactor(OR_KEY)).clean(f"x {GROQ_KEY} {OR_KEY}"))
        self.assertNotIn("sk-or-", Redactor("").clean(f"leak {OR_KEY}"))
        self.assertNotIn("gsk_", Redactor("").clean(f"leak {GROQ_KEY}"))

    def test_groq_429_per_minute_and_per_day(self):
        tpm = "Rate limit reached for model `x` in organization `o` service tier `on_demand` on tokens per minute (TPM): Limit 8000, Used 7000, Requested 3000. Please try again in 5.5s."
        rpd = "Rate limit reached for model `x` on requests per day (RPD): Limit 1000, Used 1000, Requested 1. Please try again in 7m12.5s."
        op = ScriptedOpener((429, {"error": {"message": tpm, "type": "tokens"}}, {"retry-after": "6"}),
                            (429, {"error": {"message": rpd, "type": "requests"}}, {}))
        c = client(op)
        m = c.generate("groq/x", "S", "U", SCHEMA)
        d = c.generate("groq/x", "S", "U", SCHEMA)
        self.assertEqual((m.quota_scope, m.retry_after), ("minute", 6.0))
        e = QuotaError.parse(m.quota_violations, m.error, m.quota_scope, m.retry_after)
        self.assertEqual((e.scope, e.kind, e.limit), ("minute", "tokens", 8000.0))
        self.assertEqual(d.quota_scope, "day")
        e = QuotaError.parse(d.quota_violations, d.error, d.quota_scope, d.retry_after)
        self.assertEqual((e.scope, e.kind, e.limit), ("day", "requests", 1000.0))
        self.assertAlmostEqual(e.reset_after, 432.5)

    def test_openrouter_daily_limit_gives_its_reset_and_an_upstream_limit_is_a_short_wait(self):
        daily = {"error": {"message": "Rate limit exceeded: free-models-per-day. Add 10 credits to unlock 1000 free model requests per day",
                           "code": 429, "metadata": {"headers": {"X-RateLimit-Limit": "50", "X-RateLimit-Remaining": "0",
                                                                "X-RateLimit-Reset": str(1000 * 1000 + 3600 * 1000)}}}}
        up = {"error": {"message": "Provider returned error", "code": 429, "metadata": {"raw": "temporarily rate-limited upstream"}}}
        op = ScriptedOpener((429, daily, {}), (429, up, {"retry-after": "12"}))
        c = client(op, Providers.OPENROUTER, OR_KEY)
        d = c.generate("openrouter/a:free", "S", "U", SCHEMA)
        u = c.generate("openrouter/a:free", "S", "U", SCHEMA)
        e = QuotaError.parse(d.quota_violations, d.error, d.quota_scope, d.retry_after)
        self.assertEqual((e.scope, e.limit), ("day", 50.0))
        self.assertAlmostEqual(e.reset_after, 3600.0)
        self.assertEqual((u.quota_scope, u.retry_after), ("minute", 12.0))

    def test_a_day_429_with_a_stated_reset_closes_the_pool_until_then_not_until_midnight(self):
        book = QuotaBook(spec("m", rpm=30), 1.05)
        now = 1_800_000_000.0
        book.on_quota_error(now, QuotaError("day", "requests", 1000.0, 0.0, "", 900.0))
        self.assertAlmostEqual(book.exhausted_until, now + 905.0)
        self.assertGreater(book.spent_at, 0)                                  # the next request after it is the probe
        book2 = QuotaBook(spec("m", rpm=30), 1.05)
        book2.on_quota_error(now, QuotaError("day", "requests", 500.0, 0.0))          # Gemini: no stated reset, the old way
        self.assertAlmostEqual(book2.exhausted_until, now + 600.0)

    def test_payment_required_and_oversize_are_client_errors_not_endless_retries(self):
        op = ScriptedOpener((402, {"error": {"message": "insufficient credits", "code": 402}}, {}),
                            (413, {"error": {"message": "Request too large ... TPM Limit 8000, Requested 9000"}}, {}),
                            (200, {"error": {"message": "upstream down", "code": 503}}, {}))
        c = client(op)
        self.assertEqual(c.generate("groq/m", "S", "U", SCHEMA).status, 402)
        self.assertEqual(c.generate("groq/m", "S", "U", SCHEMA).status, 413)
        self.assertEqual(c.generate("groq/m", "S", "U", SCHEMA).status, 503)               # an error inside a 200

    def test_limit_reader_durations_and_headers(self):
        self.assertAlmostEqual(LimitReader.seconds("please try again in 1h2m3.5s."), 3723.5)
        self.assertAlmostEqual(LimitReader.seconds("retry in 350ms"), 0.35)
        self.assertEqual(LimitReader.seconds("nothing"), 0.0)
        self.assertEqual(RateHeaders.pick({"X-RateLimit-Remaining": "3", "Content-Type": "x", "Retry-After": "4"}),
                         {"x-ratelimit-remaining": "3", "retry-after": "4"})


class KeyAndRouterTests(unittest.TestCase):
    def test_key_file_with_its_own_variable_and_permissions(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "Groq_Key"
            p.write_text(f"GROQ_API_KEY={GROQ_KEY}\n")
            os.chmod(p, 0o600)
            self.assertEqual(Providers.GROQ.loader(p).load(), GROQ_KEY)
            with self.assertRaises(ApiKeyError):
                ApiKeyLoader(env={}, path=Path(d) / "absent", env_var="GROQ_API_KEY").load()
            self.assertEqual(ApiKeyLoader.parse("OPENROUTER_API_KEY=abc", "GROQ_API_KEY"), "")
            os.chmod(p, 0o644)
            with self.assertRaises(ApiKeyError) as ctx:
                Providers.GROQ.loader(p).load()
            self.assertNotIn(GROQ_KEY, str(ctx.exception))
            self.assertEqual(ApiKeyLoader(env={"GROQ_API_KEY": "from-env"}, path=p, env_var="GROQ_API_KEY").load(), "from-env")

    def test_provider_of_a_model_name(self):
        self.assertEqual([Providers.of(n) for n in ("groq/openai/gpt-oss-20b", "openrouter/x/y:free", "gemini-3.5-flash-lite", "gemma-4-31b-it")],
                         ["groq", "openrouter", "gemini", "gemini"])
        self.assertEqual(Providers.api_id("openrouter/nvidia/x:free"), "nvidia/x:free")
        self.assertEqual(Providers.api_id("gemini-3.5-flash-lite"), "gemini-3.5-flash-lite")

    def test_router_sends_each_model_to_its_provider_and_shares_one_strategy_table(self):
        seen = []

        class Stub:
            def __init__(self, name):
                self.name, self.redactor, self.strategies = name, Redactor(name * 10), {}

            def generate(self, model, *a):
                seen.append((self.name, model))
                return ApiResult(True, 200, "{}")

        r = ProviderRouter({"gemini": Stub("g"), "groq": Stub("q")})
        r.generate("groq/m", "s", "u", {})
        r.generate("gemini-3.5-flash-lite", "s", "u", {})
        self.assertEqual(seen, [("q", "groq/m"), ("g", "gemini-3.5-flash-lite")])
        self.assertIs(r.clients["groq"].strategies, r.strategies)
        with self.assertRaises(KeyError):
            r.generate("openrouter/x", "s", "u", {})
        self.assertNotIn("g" * 10, r.redactor.clean("a " + "g" * 10 + " " + "q" * 10))
        self.assertEqual(r.key, "")

    def test_build_reads_only_the_keys_of_the_providers_it_uses(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "Gemini"
            p.write_text("AIza" + "k" * 35)
            os.chmod(p, 0o600)
            r = ProviderRouter.build(["gemini"], p)
            self.assertEqual(list(r.clients), ["gemini"])


class QuotaFileTests(unittest.TestCase):
    def test_default_chain_is_gemini_only_and_every_other_provider_model_is_listed(self):
        qc = QuotaConfig.load(DEFAULT_CONFIG)
        self.assertTrue(all(Providers.of(s.name) == "gemini" for s in qc.models))
        others = [s for s in qc.catalogue if s.provider]
        self.assertGreaterEqual(len([s for s in others if s.provider == "groq"]), 4)
        self.assertGreaterEqual(len([s for s in others if s.provider == "openrouter"]), 8)
        for s in others:
            self.assertEqual(Providers.of(s.name), s.provider)
            self.assertTrue(s.note, s.name)
        for s in others:
            if s.provider == "openrouter" and not s.name.endswith("free-pool"):
                self.assertTrue(s.name.endswith(":free"), s.name)                    # a model that is not free is never listed
                self.assertEqual(s.pool, "openrouter/free-pool")

    def test_a_provider_chain_is_its_enabled_models_and_a_pool_is_shared(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "q.toml"
            f.write_text('''
[[model]]
name = "gemini-3.5-flash-lite"
rpm = 15
[[model]]
name = "openrouter/pool"
provider = "openrouter"
enabled = false
rpm = 20
rpd = 50
[[model]]
name = "openrouter/a:free"
provider = "openrouter"
pool = "openrouter/pool"
minimal = false
max_output = 9000
reasoning_effort = "low"
[[model]]
name = "openrouter/b:free"
provider = "openrouter"
pool = "openrouter/pool"
json_object = true
json_schema = false
''')
            self.assertEqual([s.name for s in QuotaConfig.load(f).models], ["gemini-3.5-flash-lite"])
            qc = QuotaConfig.load(f, "openrouter")
            self.assertEqual([s.name for s in qc.models], ["openrouter/a:free", "openrouter/b:free"])
            self.assertEqual(qc.models[0].max_output, 9000)
            self.assertIsInstance(qc.models[1].strategy(), JsonObjectStrategy)
            self.assertIs(qc.models[0].strategy(), STRUCTURED)
            self.assertEqual(qc.pool_of("openrouter/b:free"), "openrouter/pool")
            with self.assertRaises(ValueError):
                QuotaConfig.load(f, "groq")                                              # nothing enabled for that provider
            router = ProviderRouter({})
            qc.install(router)
            self.assertEqual(router.options["openrouter/a:free"], {"reasoning_effort": "low"})
            self.assertIn("openrouter/b:free", router.strategies)

    def test_a_model_named_after_a_provider_must_say_so(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "q.toml"
            f.write_text('[[model]]\nname = "groq/x"\n')
            with self.assertRaises(ValueError):
                QuotaConfig.load(f)


class LeanTextTests(unittest.TestCase):
    def test_lean_text_is_much_shorter_keeps_format_and_rules_and_leaves_the_default_alone(self):
        pb = PhraseBook(TK, 30)
        plain = BatchInstructions(TK, pb, thoughts=True)
        both = BatchInstructions(TK, pb, thoughts=True, compact_phrasebook=PhraseBook(TK, 12), lean_phrasebook=PhraseBook(TK, 8))
        self.assertEqual(plain.text(), both.text())                                        # the default text is untouched
        lean = both.text(minimal=True)
        self.assertLess(len(lean), len(both.text(True)) - 8000)
        for must in ("== ANSWER FORMAT ==", "== GESTURES", "== SPEECH", "== HARD RULES ==", "thoughts", '"writes" as an empty list'):
            self.assertIn(must, lean)
        self.assertNotIn("== WORDS", lean)
        v = both.variants()
        self.assertIs(ModelCaller.system_for(v, ModelSpec("m", Limits(), minimal=True)), v.minimal)
        self.assertEqual(ModelCaller.system_for(v, ModelSpec("m", Limits(), compact=True)), v.compact)
        self.assertEqual(ModelCaller.system_for(v, ModelSpec("m", Limits())), str(v))


class ProbeAndBenchTests(unittest.TestCase):
    def test_compat_probe_two_requests_at_most_and_402_is_dropped(self):
        seen = []

        class Net:
            strategies = {}
            redactor = Redactor("")

            def __init__(self, script):
                self.script = list(script)

            def generate(self, model, system, user, schema, *a):
                seen.append(model)
                return self.script.pop(0)

        ok = ApiResult(True, 200, json.dumps({"answer": SECRET_WORD, "n": 2}), "STOP", {"promptTokenCount": 9, "candidatesTokenCount": 3},
                       0.2, rate_limit={"x-ratelimit-limit-requests": "50"})
        bad = ApiResult(False, 400, error="response_format unsupported")
        pay = ApiResult(False, 402, error="credits required")
        p = CompatProbe(Net([bad, ok, pay]), pause=0, sleep=lambda s: None, log=lambda s: None)
        rows = p.run(["openrouter/a", "openrouter/b"])
        self.assertEqual((rows[0]["requests"], rows[0]["viable"], rows[0]["mode"]), (2, True, "prompt_only"))
        self.assertEqual(rows[0]["plain"]["secret_word_found"], True)
        self.assertEqual((rows[1]["requests"], rows[1]["viable"]), (1, False))
        self.assertIn("never paid", " ".join(rows[1]["notes"]))
        self.assertEqual(len(seen), 3)

    def test_bench_counts_content_refusals_validity_after_repair_traces_and_never_retries_a_refusal(self):
        class Refuser(FakeTeacher):
            def generate(self, model, system, user, schema, *a, **kw):
                self.requests.append({"model": model, "system": system, "user": user})
                if model == "r":
                    return ApiResult(False, 200, "", "SAFETY", {"promptTokenCount": 50}, 0.1)
                return super().generate(model, system, user, schema, *a, **kw)

        qc = config(spec("a", rpm=600), spec("r", rpm=600))
        fake = Refuser(broken={"S2"})
        t = [0.0]
        with tempfile.TemporaryDirectory() as d:
            raw = Path(d) / "x" / "bench_raw.jsonl"
            bench = QualityBench(fake, qc, TK, k=3, pause=0.0, sleep=lambda s: None, clock=lambda: t[0], log=lambda s: None,
                                 sampler_factory=sampler_factory, repair=True, raw_path=raw)
            a, r = bench.run(["a", "r"])
            lines = [json.loads(l) for l in raw.read_text().splitlines()]
        self.assertEqual((a.asked, a.valid_first, a.valid_final, a.repaired_ok, a.all_requests), (3, 2, 3, 1, 2))
        self.assertEqual(a.final_rate, 1.0)
        self.assertEqual((r.valid_final, r.refusals, r.all_requests), (0, {"finish:SAFETY": 1}, 1))     # one request: no second try
        self.assertEqual(sum(1 for q in fake.requests if q["model"] == "r"), 1)
        self.assertEqual([l["model"] for l in lines], ["a", "a", "r"])


if __name__ == "__main__":
    unittest.main()
