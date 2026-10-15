"""Tests of the model probe, the prompt-only strategy, the model families and the small-batch lane (no network).

    python3 -m unittest discover -s ai/teacher/tests -t ai
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from teacher.bench import ModelScore, QualityBench, write_report
from teacher.caller import LaneBusy
from teacher.gemini import (STRUCTURED, ApiResult, GeminiClient, JsonExtractor, ModelCatalog, ModelFamilies, PromptOnlyStrategy,
                            SchemaText, StructuredStrategy)
from teacher.probe import SECRET_WORD, CandidateList, KeyRefused, ModelProbe, ProbeReport
from teacher.quota import FAR, Limits, ModelSpec, QuotaBook, QuotaConfig, QuotaDesk
from teacher.tests.test_generator import FakeTeacher, GeneratorCase, TK, sampler_factory
from teacher.tests.test_quota import CALL, FakeClock, config, make_caller, ok_result, pt, spec

KEY = "AIzaSyFAKEFAKEFAKEFAKEFAKEFAKE1234567"


class Resp:
    def __init__(self, status, body):
        self.status, self._raw = status, json.dumps(body).encode()

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def good(answer=SECRET_WORD, thoughts=0):
    usage = {"promptTokenCount": 44, "candidatesTokenCount": 13}
    if thoughts:
        usage["thoughtsTokenCount"] = thoughts
    return 200, {"candidates": [{"content": {"parts": [{"text": json.dumps({"answer": answer, "n": 2})}]}, "finishReason": "STOP"}],
                 "usageMetadata": usage}


def failure(code, message, **extra):
    return code, {"error": {"code": code, "status": extra.pop("status", "INVALID_ARGUMENT"), "message": message, **extra}}


class ScriptedNetwork:
    """An opener answering from a script {model: [(status, body), ...]}; records (model, body) of every request."""

    def __init__(self, script):
        self.script, self.seen = {k: list(v) for k, v in script.items()}, []

    def __call__(self, req, timeout):
        model = req.full_url.split("/models/")[1].split(":")[0]
        self.seen.append((model, json.loads(req.data or b"{}")))
        return Resp(*self.script[model].pop(0))


def probe_for(script, pause=5.0):
    net = ScriptedNetwork(script)
    t = [100.0]
    sleeps = []

    def sleep(s):
        sleeps.append(s)
        t[0] += s
    probe = ModelProbe(GeminiClient(KEY, opener=net), pause, sleep=sleep, clock=lambda: t[0], log=lambda s: None)
    return probe, net, sleeps


# ------------------------------------------------------------------------------------------------ the probe
class ProbeTests(unittest.TestCase):
    def test_a_full_model_costs_one_request_and_reports_its_abilities(self):
        probe, net, _ = probe_for({"m": [good(thoughts=90)]})
        row = probe.probe("m")
        self.assertEqual((row["requests"], row["viable"], row["mode"]), (1, True, "structured"))
        self.assertTrue(row["system_instruction"] and row["json_schema"] and row["thinks"])
        body = net.seen[0][1]
        self.assertIn("systemInstruction", body)
        self.assertEqual(body["generationConfig"]["responseMimeType"], "application/json")
        self.assertLessEqual(body["generationConfig"]["maxOutputTokens"], 600)

    def test_an_answer_that_ignores_the_system_instruction_is_flagged(self):
        probe, _, _ = probe_for({"m": [good(answer="no idea")]})
        row = probe.probe("m")
        self.assertFalse(row["system_instruction"])
        self.assertEqual(row["mode"], "prompt_only")

    def test_400_on_the_developer_instruction_falls_back_to_one_plain_request(self):
        plain = (200, {"candidates": [{"content": {"parts": [{"text": '```json\n{"answer": "pelican", "n": 2}\n```'}]}}]})
        probe, net, _ = probe_for({"g": [failure(400, "Developer instruction is not enabled for models/g"), plain]})
        row = probe.probe("g")
        self.assertEqual(row["requests"], 2)
        self.assertEqual((row["system_instruction"], row["json_schema"]), (False, True))
        self.assertEqual((row["viable"], row["mode"]), (True, "prompt_only"))
        second = net.seen[1][1]
        self.assertNotIn("systemInstruction", second)
        self.assertNotIn("responseSchema", second["generationConfig"])

    def test_400_on_the_json_mode_marks_the_schema_unsupported(self):
        probe, _, _ = probe_for({"g": [failure(400, "JSON mode is not enabled for this model"), good()]})
        row = probe.probe("g")
        self.assertEqual((row["system_instruction"], row["json_schema"]), (True, False))

    def test_never_more_than_two_requests_per_model(self):
        probe, net, _ = probe_for({"x": [failure(400, "no"), failure(400, "no")]})
        row = probe.probe("x")
        self.assertEqual((row["requests"], row["viable"], len(net.seen)), (2, False, 2))
        self.assertIn("error_plain", row)

    def test_429_reports_scope_limit_and_free_tier_without_quota(self):
        err = failure(429, "You exceeded your current quota, please check your plan and billing details.\n"
                           "* Quota exceeded for metric: generativelanguage.googleapis.com/generate_content_free_tier_requests, limit: 0",
                      status="RESOURCE_EXHAUSTED",
                      details=[{"@type": "type.googleapis.com/google.rpc.QuotaFailure",
                                "violations": [{"quotaMetric": "x", "quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}]},
                               {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "30s"}])
        probe, net, _ = probe_for({"p": [err]})
        row = probe.probe("p")
        self.assertEqual(len(net.seen), 1)                                   # a 429 is not retried
        e = row["error"]
        self.assertEqual((e["http"], e["scope"], e["retry_after_s"]), (429, "day", 30.0))
        self.assertTrue(e["billing_required"])
        self.assertEqual(e["limits_in_message"][0]["limit"], 0)

    def test_an_ordinary_429_is_not_billing_required(self):
        err = failure(429, "You exceeded your current quota, please check your plan and billing details.\n"
                           "* Quota exceeded for metric: generativelanguage.googleapis.com/x_requests, limit: 15", status="RESOURCE_EXHAUSTED")
        probe, _, _ = probe_for({"p": [err]})
        self.assertNotIn("billing_required", probe.probe("p")["error"])

    def test_404_is_recorded_and_not_retried(self):
        probe, net, _ = probe_for({"old": [failure(404, "This model is no longer available", status="NOT_FOUND")]})
        row = probe.probe("old")
        self.assertEqual((row["error"]["http"], len(net.seen), row["viable"]), (404, 1, False))

    def test_pause_between_two_requests_is_at_least_five_seconds(self):
        probe, _, sleeps = probe_for({"a": [good()], "b": [good()], "c": [failure(400, "x"), good()]}, pause=2.0)
        probe.pause = 5.0
        probe.run(["a", "b", "c"])
        self.assertEqual(len(sleeps), 3)                                     # 4 requests -> 3 pauses
        self.assertTrue(all(s >= 4.99 for s in sleeps), sleeps)

    def test_a_refused_key_stops_everything(self):
        refused = failure(403, "Your API key was reported as leaked. Please use another API key.", status="PERMISSION_DENIED")
        probe, net, _ = probe_for({"a": [good()], "b": [refused], "c": [good()]})
        rows = probe.run(["a", "b", "c"])
        self.assertEqual([r["model"] for r in rows], ["a", "b"])             # c is never asked
        self.assertTrue(rows[-1]["aborted"])
        self.assertEqual(len(net.seen), 2)

    def test_a_403_about_one_model_does_not_stop_the_others(self):
        denied = failure(403, "Permission denied on model m: not allowed for this project", status="PERMISSION_DENIED")
        probe, net, _ = probe_for({"m": [denied], "n": [good()]})
        rows = probe.run(["m", "n"])
        self.assertEqual([r["viable"] for r in rows], [False, True])

    def test_the_key_never_reaches_the_report(self):
        probe, _, _ = probe_for({"m": [failure(400, f"bad key {KEY} in request"), failure(400, f"again {KEY}")]})
        row = probe.probe("m")
        self.assertNotIn(KEY, json.dumps(row))

    def test_unlisted_and_excluded_candidates_are_not_asked(self):
        listed = [{"name": f"models/{n}", "supportedGenerationMethods": ["generateContent"]}
                  for n in ("gemma-4-31b-it", "gemini-3.1-pro-preview", "gemini-2.5-flash-image", "gemini-3.8-flash-tts", "old-one")]
        with tempfile.TemporaryDirectory() as d:
            q = Path(d) / "quota.json"
            q.write_text(json.dumps({"models": {"old-one": {"exhausted_why": "not found"}, "gemini-3.1-pro-preview": {"exhausted_why": "rpd"}}}))
            keep, skipped = CandidateList(listed, q).select(
                ["gemma-4-31b-it", "gemini-3.1-pro-preview", "old-one", "gemini-2.5-flash-image", "gemini-3.8-flash-tts", "ghost"])
        self.assertEqual(keep, ["gemma-4-31b-it", "gemini-3.1-pro-preview"])
        self.assertIn("404", skipped["old-one"])
        self.assertIn("excluded", skipped["gemini-3.8-flash-tts"])
        self.assertIn("models.list", skipped["ghost"])

    def test_report_is_written_outside_the_repository_and_merges_earlier_rows(self):
        from teacher.toolkit import ROOT
        with self.assertRaises(SystemExit):
            ProbeReport([], {}).write(ROOT / "probe.json")
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "probe_models.json"
            ProbeReport([{"model": "a", "viable": True, "mode": "structured", "system_instruction": True, "json_schema": True,
                          "thinks": False, "full": {"latency_s": 1}}], {}).write(path)
            ProbeReport([{"model": "b", "viable": False, "error": {"http": 404, "message": "gone"}}], {"c": "why"}).write(path)
            doc = json.loads(path.read_text())
            self.assertEqual([r["model"] for r in doc["models"]], ["a", "b"])
            self.assertEqual(doc["skipped"], {"c": "why"})
            self.assertTrue(any("OK" in l for l in doc["readable"]))


# ------------------------------------------------------------------------------------------------ prompt-only
SCHEMA = {"type": "OBJECT", "properties": {"decisions": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {"id": {"type": "STRING"}}}}}}


class PromptOnlyTests(unittest.TestCase):
    def test_everything_is_folded_into_the_user_text(self):
        body = PromptOnlyStrategy().body("RULES: be human", "S1 says hello", SCHEMA, 0.7, 4096, None)
        self.assertNotIn("systemInstruction", body)
        cfg = body["generationConfig"]
        self.assertNotIn("responseSchema", cfg)
        self.assertNotIn("responseMimeType", cfg)
        self.assertNotIn("thinkingConfig", cfg)
        self.assertEqual((cfg["temperature"], cfg["maxOutputTokens"]), (0.7, 4096))
        text = body["contents"][0]["parts"][0]["text"]
        for want in ("RULES: be human", "S1 says hello", '"type":"object"', '"type":"array"', "no Markdown fence", "JSON object"):
            self.assertIn(want, text)
        self.assertLess(text.index("RULES"), text.index("S1 says hello"))

    def test_only_the_missing_feature_is_folded(self):
        no_schema = PromptOnlyStrategy(fold_system=False, fold_schema=True).body("SYS", "usr", SCHEMA, 0.5, 100, None)
        self.assertEqual(no_schema["systemInstruction"]["parts"][0]["text"], "SYS")
        self.assertNotIn("responseSchema", no_schema["generationConfig"])
        self.assertIn("JSON Schema", no_schema["contents"][0]["parts"][0]["text"])
        no_system = PromptOnlyStrategy(fold_system=True, fold_schema=False).body("SYS", "usr", SCHEMA, 0.5, 100, None)
        self.assertNotIn("systemInstruction", no_system)
        self.assertEqual(no_system["generationConfig"]["responseSchema"], SCHEMA)
        self.assertIn("SYS", no_system["contents"][0]["parts"][0]["text"])

    def test_schema_text_is_a_plain_json_schema(self):
        plain = SchemaText.plain(SCHEMA)
        self.assertEqual(plain["properties"]["decisions"]["items"]["type"], "object")
        self.assertEqual(SCHEMA["type"], "OBJECT")                              # the original is untouched
        json.loads(SchemaText.text(SCHEMA))

    def test_extractor(self):
        obj = '{"decisions":[{"id":"S1","why":"a } brace, and \\" quote"}]}'
        for reply in (obj, f"```json\n{obj}\n```", f"Sure! Here it is:\n{obj}\nHope it helps", f"{{not json}} then {obj}"):
            self.assertEqual(json.loads(JsonExtractor.extract(reply)), json.loads(obj), reply)
        self.assertEqual(JsonExtractor.extract("no json at all"), "no json at all")
        self.assertEqual(JsonExtractor.extract('{"a": '), '{"a": ')              # cut reply: left for the validator to refuse

    def test_client_uses_the_strategy_of_the_model_and_cleans_the_reply(self):
        seen = []

        def opener(req, timeout):
            seen.append((req.full_url, json.loads(req.data)))
            return Resp(200, {"candidates": [{"content": {"parts": [{"text": "thinking...", "thought": True},
                                                                    {"text": 'Here:\n```json\n{"decisions": []}\n```'}]},
                                              "finishReason": "STOP"}], "usageMetadata": {}})
        c = GeminiClient(KEY, opener=opener)
        c.strategies["gemma-x"] = PromptOnlyStrategy()
        r = c.generate("gemma-x", "SYS", "usr", SCHEMA)
        self.assertEqual(json.loads(r.text), {"decisions": []})
        self.assertNotIn("systemInstruction", seen[0][1])
        c.generate("gemini-y", "SYS", "usr", SCHEMA)                           # other models keep the structured request
        self.assertIn("systemInstruction", seen[1][1])
        self.assertEqual(seen[1][1]["generationConfig"]["responseMimeType"], "application/json")

    def test_a_prompt_only_reply_goes_through_the_batch_parser_and_the_validator(self):
        from teacher.batch import BatchAnswer
        from teacher.tests.test_generator import wait_decision
        raw = "Of course.\n```json\n" + json.dumps({"decisions": [wait_decision("S1")]}) + "\n```"
        r = PromptOnlyStrategy().shape(ApiResult(True, 200, raw, "STOP"))
        self.assertEqual(list(BatchAnswer.parse(r, ["S1"]).items), ["S1"])


# ------------------------------------------------------------------------------------------------ families and config
class FamilyTests(unittest.TestCase):
    NAMES = ["gemini-3.5-flash-lite", "gemini-3.8-flash", "gemma-4-31b-it", "gemma-4-26b-a4b-it", "gemini-3.1-pro-preview",
             "gemini-2.5-pro", "gemini-pro-latest", "gemini-flash-latest", "gemini-flash-lite-latest", "gemini-3.8-flash-tts",
             "gemini-2.5-flash-image", "gemini-omni-1.1-flash", "antigravity-preview-latest", "lyria-3.5", "gemini-4-argon"]

    def models(self):
        return [{"name": f"models/{n}", "supportedGenerationMethods": ["generateContent"]} for n in self.NAMES]

    def test_family_of(self):
        of = lambda n: ModelFamilies.of(n).name           # noqa: E731
        self.assertEqual([of("gemini-3.5-flash-lite"), of("gemini-flash-lite-latest"), of("gemini-3.8-flash"), of("gemini-flash-latest"),
                          of("gemini-3.1-pro-preview"), of("gemini-pro-latest"), of("gemma-4-31b-it"), of("gemini-4-argon")],
                         ["gemini-flash-lite", "gemini-flash-lite", "gemini-flash", "gemini-flash", "gemini-pro", "gemini-pro",
                          "gemma", "other"])

    def test_default_chain_is_unchanged(self):
        self.assertEqual(ModelCatalog(self.models()).chain(), ["gemini-3.5-flash-lite", "gemini-3.8-flash"])

    def test_wider_chain_opens_pro_and_gemma_but_never_the_non_text_models(self):
        chain = ModelCatalog(self.models()).chain(ModelFamilies.ALL)
        self.assertIn("gemma-4-31b-it", chain)
        self.assertIn("gemini-3.1-pro-preview", chain)
        for banned in ("tts", "image", "omni", "antigravity", "lyria", "latest"):
            self.assertFalse(any(banned in m for m in chain), banned)
        self.assertLess(chain.index("gemini-3.8-flash"), chain.index("gemini-2.5-pro"))        # flash before pro before gemma
        self.assertLess(chain.index("gemini-3.1-pro-preview"), chain.index("gemma-4-31b-it"))

    def test_strategy_follows_the_family_unless_the_file_says_otherwise(self):
        limits = Limits()
        self.assertIs(ModelSpec("gemini-3.8-flash", limits).strategy(), STRUCTURED)
        self.assertIs(ModelSpec("gemma-4-31b-it", limits).strategy(), STRUCTURED)          # the probe saw it accept both
        s = ModelSpec("gemma-4-31b-it", limits, json_schema=False).strategy()
        self.assertIsInstance(s, PromptOnlyStrategy)
        self.assertEqual((s.fold_system, s.fold_schema), (False, True))
        s = ModelSpec("x", limits, system_instruction=False, json_schema=False).strategy()
        self.assertEqual((s.fold_system, s.fold_schema), (True, True))

    def test_quota_file_enabled_disabled_and_only(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "q.toml"
            f.write_text('[[model]]\nname = "a"\nrpm = 5\n[[model]]\nname = "g"\nenabled = false\nnote = "too weak"\n'
                         '[[model]]\nname = "gemma-4-31b-it"\ntpm = 16000\njson_schema = false\nmax_k = 2\n')
            qc = QuotaConfig.load(f)
        self.assertEqual([s.name for s in qc.models], ["a", "gemma-4-31b-it"])
        self.assertEqual([(s.name, s.note) for s in qc.disabled], [("g", "too weak")])
        self.assertEqual((qc.models[1].max_k, qc.models[1].limits.tpm, qc.models[1].limits.rpm), (2, 16000, None))
        self.assertEqual([s.name for s in qc.only(["g", "a"]).models], ["g", "a"])           # a disabled model can be named
        client = GeminiClient(KEY)
        qc.install(client)
        self.assertIsInstance(client.strategies["gemma-4-31b-it"], PromptOnlyStrategy)
        self.assertIs(client.strategies["a"], STRUCTURED)

    def test_the_shipped_quota_file_loads_and_explains_every_disabled_model(self):
        qc = QuotaConfig.load()
        self.assertTrue(qc.models)
        for s in qc.disabled:
            self.assertTrue(s.note, f"{s.name} is disabled without a reason")
        for s in qc.models:
            self.assertIsInstance(s.strategy(), (StructuredStrategy, PromptOnlyStrategy))


# ------------------------------------------------------------------------------------------------ small-batch lane
class LaneTests(GeneratorCase):
    def test_a_request_above_the_tokens_per_minute_ceiling_is_never_sent_to_that_model(self):
        b = QuotaBook(spec("g", rpm=10, tpm=16000))
        self.assertEqual(b.available_at(1000.0, 30000), FAR)
        self.assertLess(b.available_at(1000.0, 10000), FAR)

    def test_choose_skips_the_small_model_for_a_big_batch_and_honours_only(self):
        desk = QuotaDesk(config(spec("big", rpm=600), spec("g", rpm=600, tpm=16000)))
        t = pt(2026, 10, 13, 10)
        self.assertEqual(desk.choose(t, 120_000).model, "big")
        self.assertEqual(desk.choose(t, 20_000, only="g").model, "g")
        self.assertEqual(desk.choose(t, 120_000, only="g").model, None)

    def test_caller_raises_lane_busy_when_the_reserved_model_cannot_answer(self):
        caller, client, desk, clock, _ = make_caller(lambda m, n: ok_result(), spec("a", rpm=600), spec("g", rpm=600, tpm=16000))
        caller.only = "g"
        desk.books["g"].block(clock.t, 60)
        with self.assertRaises(LaneBusy):
            caller(*CALL)
        self.assertEqual(client.calls, [])
        caller.only = "g"
        clock.wait(61)
        self.assertEqual(caller(*CALL)[0], "g")
        self.assertIsNone(caller.only)                                       # consumed by the answer ...
        self.assertEqual(caller.sticky, "g")                                 # ... but the repair of that round stays with the lane model
        caller.end_round()
        self.assertIsNone(caller.sticky)

    def test_a_normal_model_that_can_answer_keeps_the_round(self):
        qc = config(spec("a", rpm=600, rpd=100000), ModelSpec("g", Limits(600, 100000), max_k=2))
        fake = FakeTeacher()
        gen = self.generator(fake, k=6, qc=qc)
        gen.one_round()
        self.assertEqual([r["model"] for r in fake.requests], ["a"])                          # a small-batch model is the FALLBACK
        self.assertEqual(len(fake.requests[0]["user"].split("=== SITUATION")) - 1, 6)

    def test_generator_gives_a_small_round_to_the_small_model_and_labels_carry_its_name(self):
        qc = config(spec("a", rpm=600, rpd=100000), ModelSpec("g", Limits(600, 100000), max_k=2))
        fake = FakeTeacher()
        gen = self.generator(fake, k=6, qc=qc)
        with gen.desk.transaction():
            gen.desk.books["a"].exhaust(gen.pacer.clock(), "test", until=gen.pacer.clock() + 3600)   # no normal model can answer now
        gen.one_round()
        self.assertEqual([r["model"] for r in fake.requests], ["g"])
        self.assertEqual(len(fake.requests[0]["user"].split("=== SITUATION")) - 1, 2)         # max_k situations, not 6
        self.assertEqual({l["teacher"] for l in self.lines()}, {"g"})

    def test_generator_falls_back_to_the_normal_round_when_the_lane_is_busy(self):
        qc = config(spec("a", rpm=600, rpd=100000), ModelSpec("g", Limits(600, 100000, tpm=1_000_000), max_k=2))
        fake = FakeTeacher()
        gen = self.generator(fake, k=4, qc=qc)
        with gen.desk.transaction():
            gen.desk.books["g"].block(gen.pacer.clock(), 300)                # the lane is blocked: no lane round at all
        gen.one_round()
        self.assertEqual({r["model"] for r in fake.requests}, {"a"})
        self.assertEqual(len(fake.requests[0]["user"].split("=== SITUATION")) - 1, 4)

    def test_lane_busy_in_mid_round_rewinds_the_cursor(self):
        qc = config(spec("a", rpm=600, rpd=100000), ModelSpec("g", Limits(600, 100000), max_k=2))
        fake = FakeTeacher()
        gen = self.generator(fake, k=4, qc=qc)
        before = (gen.cursor.seed, gen.cursor.index)
        gen.small_lane = lambda: "g"
        with gen.desk.transaction():
            gen.desk.books["g"].block(gen.pacer.clock(), 300)
        self.assertTrue(gen.one_round())
        self.assertEqual((gen.cursor.seed, gen.cursor.index), before)
        self.assertEqual(fake.requests, [])
        self.assertGreater(gen._lane_until["g"], gen.pacer.clock())


# ------------------------------------------------------------------------------------------------ the quality bench
class BenchTests(unittest.TestCase):
    def test_same_situations_for_every_model_first_shot_rate_and_chunks_for_a_small_model(self):
        qc = config(spec("a", rpm=600), ModelSpec("g", Limits(600), max_k=2, json_schema=False))
        fake = FakeTeacher(broken={"S2"})
        t = [0.0]
        slept = []
        bench = QualityBench(fake, qc, TK, k=4, pause=1.0, sleep=lambda s: (slept.append(s), t.__setitem__(0, t[0] + s)),
                             clock=lambda: t[0], log=lambda s: None, sampler_factory=sampler_factory)
        a, g = bench.run(["a", "g"])
        self.assertEqual((a.asked, a.valid_first, a.requests), (4, 3, 1))
        self.assertEqual(a.codes, {"unknown_gesture": 1})
        self.assertEqual(a.valid_rate, 0.75)
        self.assertEqual((g.asked, g.requests, g.strategy), (4, 2, "prompt_only"))             # 2 chunks of 2
        users = [r["user"] for r in fake.requests]
        self.assertEqual(users[0].count("=== SITUATION"), 4)
        self.assertEqual(users[1].count("=== SITUATION"), 2)
        self.assertEqual(a.passive_share, 1.0)                                                   # the fake always waits
        self.assertTrue(all(s >= 64.0 for s in slept[-1:]))                                      # a whole minute between the chunks

    def test_report_merges_and_stays_outside_the_repository(self):
        from teacher.toolkit import ROOT
        with self.assertRaises(SystemExit):
            write_report([], ROOT / "x.json", 0, 6)
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "q.json"
            write_report([ModelScore("a", asked=6, valid_first=6)], p, 0, 6)
            write_report([ModelScore("b", asked=6, valid_first=3)], p, 0, 6)
            self.assertEqual([m["model"] for m in json.loads(p.read_text())["models"]], ["a", "b"])


if __name__ == "__main__":
    unittest.main()
