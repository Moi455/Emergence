"""Tests of the GLOBAL quota ledger, the quota pools, the token accounting and the compact instructions (no network).

    python3 -m unittest discover -s ai/teacher/tests -t ai
"""
from __future__ import annotations

import json
import multiprocessing
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from teacher.batch import BatchInstructions, VariantText
from teacher.caller import LaneBusy, ModelCaller, Pacer
from teacher.gemini import ApiResult, GeminiClient, PromptOnlyStrategy, SchemaText
from teacher.generator import COMPACT_PHRASES, LANE_DEFER
from teacher.phrasebook import PhraseBook
from teacher.quota import (FAR, Limits, LedgerGate, ModelSpec, PacificDay, QuotaBook, QuotaConfig, QuotaDesk, QuotaError,
                           merge_book_dicts)
from teacher.tests.test_generator import TK, FakeTeacher, GeneratorCase
from teacher.tests.test_quota import (CALL, FakeClock, ScriptedClient, config, limited, ok_result, pt, spec, violation)

T0 = pt(2026, 10, 15, 10)


def cfg(*specs, **kw):
    return QuotaConfig(tuple(specs), kw.pop("margin", 1.0), (), kw.pop("tpm_target", 1.0), tuple(specs) + tuple(kw.pop("extra", ())))


def bump(args):
    """One worker process: `n` requests counted in the shared ledger."""
    path, n = args
    desk = QuotaDesk(cfg(spec("a", rpm=100000, rpd=10 ** 9)), path, now=T0)
    for i in range(n):
        with desk.transaction(T0 + i):
            desk.books["a"].begin(T0 + i, 10)
    return n


# ------------------------------------------------------------------------------------------------ 1. one ledger for all
class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "quota_global.json"

    def test_two_desks_are_two_processes_on_one_key(self):
        a = QuotaDesk(cfg(spec("m", rpm=15, rpd=500)), self.path, now=T0)
        b = QuotaDesk(cfg(spec("m", rpm=15, rpd=500)), self.path, now=T0)               # a second generator, or a bench
        with a.transaction(T0):
            a.books["m"].begin(T0, 100)
        c = b.choose(T0 + 0.1, 100)                                                       # b sees a's request without being told
        self.assertAlmostEqual(c.at, T0 + 4.0)                                            # ... and keeps the 60/15 s spacing of the POOL
        with b.transaction(T0 + 5):
            b.books["m"].begin(T0 + 5, 100)
        self.assertEqual(a.table(T0 + 6)[0]["requests"], 2)

    def test_concurrent_processes_lose_nothing(self):
        QuotaDesk(cfg(spec("a", rpm=100000, rpd=10 ** 9)), self.path, now=T0)
        ctx = multiprocessing.get_context("fork")
        with ctx.Pool(4) as pool:
            self.assertEqual(sum(pool.map(bump, [(self.path, 40)] * 4)), 160)
        doc = json.loads(self.path.read_text())
        self.assertEqual(doc["pools"]["a"]["day_requests"], 160)

    def test_a_pool_of_the_file_that_this_chain_does_not_use_is_kept(self):
        QuotaDesk(cfg(spec("x", rpd=5), spec("y", rpd=5)), self.path, now=T0)
        only_x = QuotaDesk(cfg(spec("x", rpd=5)), self.path, now=T0)
        with only_x.transaction(T0):
            only_x.books["x"].begin(T0, 1)
        doc = json.loads(self.path.read_text())
        self.assertEqual(sorted(doc["pools"]), ["x", "y"])
        self.assertEqual(doc["pools"]["x"]["day_requests"], 1)

    def test_nothing_is_written_when_nothing_changed(self):
        d = QuotaDesk(cfg(spec("m", rpm=15)), self.path, now=T0)
        before = self.path.stat().st_mtime_ns
        for _ in range(3):
            d.choose(T0, 10)
        self.assertEqual(self.path.stat().st_mtime_ns, before)

    def test_the_lock_is_released_after_an_exception(self):
        d = QuotaDesk(cfg(spec("m")), self.path, now=T0)
        with self.assertRaises(RuntimeError):
            with d.transaction(T0):
                d.books["m"].begin(T0, 5)
                raise RuntimeError("boom")
        self.assertEqual(json.loads(self.path.read_text())["pools"]["m"]["day_requests"], 1)     # the spent request is not forgotten
        with d.transaction(T0 + 1):                                                                # and the lock is free
            pass


# ------------------------------------------------------------------------------------------------ migration
def old_book(day, requests, tokens, **kw):
    return {"learned": kw.get("learned", {}), "window": kw.get("window", []), "last_sent": kw.get("last_sent", 0.0), "day": day,
            "day_requests": requests, "day_tokens": tokens, "exhausted_until": kw.get("until", 0.0),
            "exhausted_why": kw.get("why", ""), "blocked_until": 0.0, "minute_429": 0, "client_errors": 0,
            "tokens_per_char": 0.3, "history": kw.get("history", {})}


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.config = cfg(spec("lite", rpm=15, rpd=500, tpm=250000), spec("flash", rpm=5, rpd=20),
                          extra=[ModelSpec("lite-latest", Limits(), enabled=False, pool="lite"),
                                 ModelSpec("lite-preview", Limits(), enabled=False, pool="lite")])

    def legacy(self, series, models):
        d = self.base / series
        d.mkdir()
        (d / "quota.json").write_text(json.dumps({"schema": 1, "models": models}))
        return d / "quota.json"

    def test_old_series_books_merge_by_pool_and_day_without_loss(self):
        s1 = self.legacy("serie1", {
            "lite": old_book("2026-10-14", 500, 11_000_000, learned={"rpd": 500, "tpm": 250000}, until=T0 - 100,
                             history={"2026-10-13": {"requests": 491, "tokens": 8_900_000}}),
            "lite-preview": old_book("2026-10-14", 150, 3_800_000)})
        s2 = self.legacy("serie_planner", {
            "lite": old_book("2026-10-15", 407, 7_600_000, last_sent=T0 - 10, until=T0 + 9000, why="requests/day",
                             history={"2026-10-14": {"requests": 3, "tokens": 25740}}),
            "lite-latest": old_book("2026-10-15", 92, 1_900_000, learned={"rpd": 400}),
            "flash": old_book("2026-10-15", 20, 70_000)})
        before = (s1.read_text(), s2.read_text())
        desk = QuotaDesk(self.config, self.base / "quota_global.json", now=T0)
        b = desk.books["lite"]
        self.assertIs(desk.books["lite"], desk.pools["lite"])
        self.assertEqual((b.day, b.day_requests, b.day_tokens), ("2026-10-15", 407 + 92, 7_600_000 + 1_900_000))   # today: the alias is added
        self.assertEqual(b.history["2026-10-14"], {"requests": 500 + 150 + 3, "tokens": 11_000_000 + 3_800_000 + 25740})  # yesterday, all series
        self.assertEqual(b.history["2026-10-13"]["requests"], 491)
        self.assertEqual(b.learned.to_dict(), {"rpd": 400, "tpm": 250000})                  # the lowest limit learned
        self.assertGreater(b.exhausted_until, T0)                                           # today's exhaustion is not forgotten
        self.assertEqual(b.exhausted_why, "requests/day")
        self.assertEqual(desk.books["flash"].day_requests, 20)
        self.assertEqual(len(desk.migrated), 2)
        self.assertEqual((s1.read_text(), s2.read_text()), before)                          # the old files are not touched

    def test_migration_happens_once(self):
        self.legacy("serie1", {"lite": old_book("2026-10-15", 10, 100)})
        first = QuotaDesk(self.config, self.base / "quota_global.json", now=T0)
        with first.transaction(T0):
            first.books["lite"].begin(T0, 5)
        self.legacy_again = self.base / "serie1" / "quota.json"
        again = QuotaDesk(self.config, self.base / "quota_global.json", now=T0)
        self.assertEqual(again.books["lite"].day_requests, 11)                              # not re-added from the old file

    def test_merge_of_one_book_is_the_book(self):
        d = old_book("2026-10-15", 7, 70, learned={"rpm": 3}, history={"2026-10-14": {"requests": 2, "tokens": 20}})
        m = merge_book_dicts([d])
        for k in ("day", "day_requests", "day_tokens", "learned", "history"):
            self.assertEqual(m[k], d[k], k)

    def test_a_new_ledger_without_old_files_reads_today_from_the_journals(self):
        j = self.base / "serie_x"
        j.mkdir()
        rows = [{"ts": T0 - 50, "pday": PacificDay.key(T0), "kind": "batch", "model": "lite-latest", "usage": {"prompt": 900, "output": 100}},
                {"ts": T0 - 40, "pday": PacificDay.key(T0), "kind": "error", "model": "lite"}]
        (j / "journal.jsonl").write_text("\n".join(json.dumps(r, separators=(",", ":")) for r in rows) + "\n")
        desk = QuotaDesk(self.config, self.base / "quota_global.json", now=T0,
                         journals=sorted(self.base.glob("*/journal.jsonl")))
        self.assertEqual(desk.books["lite"].day_requests, 2)                                # the alias journal line counts for the pool
        self.assertEqual(desk.rebuilt, [])                                                  # a normal first start is not an alarm


# ------------------------------------------------------------------------------------------------ 2. pools
class PoolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "quota_global.json"
        self.config = cfg(spec("lite", rpm=15, rpd=3, tpm=250000), ModelSpec("lite-latest", Limits(), pool="lite"),
                          spec("mystery-latest", rpm=15, rpd=500))

    def test_an_alias_is_counted_in_the_pool_of_its_target(self):
        desk = QuotaDesk(self.config, self.path, now=T0)
        self.assertIs(desk.books["lite-latest"], desk.books["lite"])
        self.assertEqual(desk.books["lite-latest"].limits().rpd, 3)                         # the limits are the pool's
        with desk.transaction(T0):
            for i, name in enumerate(["lite", "lite-latest", "lite"]):
                desk.books[name].begin(T0 + i, 10)
        self.assertEqual(desk.books["lite"].day_requests, 3)                                # 3 requests under two names = 3 in the pool
        with desk.transaction(T0 + 10):
            desk.books["lite"].spend_day(T0 + 10, "requests/day")
        self.assertTrue(desk.choose(T0 + 11, 10, only="lite-latest").all_exhausted)         # refused for the alias as well

    def test_the_429_names_the_real_model_and_the_alias_joins_that_pool(self):
        def handler(model, n):
            r = limited("GenerateRequestsPerDayPerProjectPerModel-FreeTier", 500)
            r.quota_violations[0]["quotaDimensions"] = {"model": "lite", "location": "global"}
            return r
        clock = FakeClock(T0)
        desk = QuotaDesk(self.config, self.path, now=T0)
        with desk.transaction(T0):
            desk.books["mystery-latest"].begin(T0 - 70, 10)                                 # 1 request already spent under the alias name
        logs = []
        caller = ModelCaller(ScriptedClient(handler), desk, Pacer(clock.now, clock.wait), log=logs.append)
        caller.only = "mystery-latest"
        with self.assertRaises(LaneBusy):                                                    # the pool is out for the day, for both names
            caller(*CALL)
        self.assertEqual(desk.aliases, {"mystery-latest": "lite"})
        self.assertIs(desk.books["mystery-latest"], desk.books["lite"])
        self.assertEqual(desk.books["lite"].day_requests, 2)                                  # the earlier request + this one: one pool
        self.assertTrue(desk.books["lite"].exhausted_until > T0)
        self.assertTrue(any("counted together" in l for l in logs))
        again = QuotaDesk(self.config, self.path, now=T0)                                     # another process, later: it knows
        self.assertIs(again.books["mystery-latest"], again.books["lite"])
        self.assertEqual(json.loads(self.path.read_text())["aliases"], {"mystery-latest": "lite"})

    def test_pool_target_must_be_listed(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "q.toml"
            f.write_text('[[model]]\nname = "a"\npool = "nowhere"\n')
            with self.assertRaises(ValueError):
                QuotaConfig.load(f)

    def test_the_shipped_file_pools_the_known_aliases_and_keeps_them_out_of_the_chain(self):
        qc = QuotaConfig.load()
        self.assertEqual(qc.pool_of("gemini-flash-lite-latest"), "gemini-3.5-flash-lite")
        self.assertEqual(qc.pool_of("gemini-3.1-flash-lite-preview"), "gemini-3.1-flash-lite")
        names = [s.name for s in qc.models]
        for alias in ("gemini-flash-lite-latest", "gemini-3.1-flash-lite-preview", "gemini-flash-latest"):
            self.assertNotIn(alias, names)
        desk = QuotaDesk(qc.only(["gemini-3.5-flash-lite", "gemini-flash-lite-latest"]))
        self.assertIs(desk.books["gemini-3.5-flash-lite"], desk.books["gemini-flash-lite-latest"])
        # one pool per distinct quota in the chain
        pools = {qc.pool_of(n) for n in names}
        self.assertEqual(len(pools), len(names))

    def test_observed_console_limits_are_in_the_file(self):
        qc = QuotaConfig.load()
        by = {s.name: s for s in qc.everything()}
        self.assertEqual(by["gemini-2.5-flash-lite"].limits, Limits(10, 20, 250000))        # NOT 500 a day
        self.assertEqual(by["gemini-3.8-flash"].limits.rpd, 20)
        for n in ("gemma-4-26b-a4b-it", "gemma-4-31b-it"):
            self.assertEqual((by[n].limits.rpm, by[n].limits.tpm, by[n].limits.rpd), (30, 16000, 14400))
            self.assertEqual((by[n].max_k, by[n].compact, by[n].tpm_counts), (2, True, "input"))
            self.assertIsInstance(by[n].strategy(), PromptOnlyStrategy)
        self.assertEqual(by["antigravity-preview-latest"].limits, Limits(60, 100, 100000))
        self.assertEqual(by["gemini-robotics-er-2-preview"].limits, Limits(5, 20, 250000))


# ------------------------------------------------------------------------------------------------ 3. tokens
class TokenTests(unittest.TestCase):
    def test_input_output_and_thinking_are_counted_by_default(self):
        b = QuotaBook(ModelSpec("m", Limits(tpm=100000)), 1.0)
        e = b.begin(T0, b.estimate_input(40000))
        b.settle(e, 40000, 120000, extra_tokens=1200 + 800)
        self.assertEqual(list(b.window[-1]), [T0, 42000])
        self.assertEqual(b.day_tokens, 42000)
        self.assertEqual(b.out_estimate, 1550.0)                                             # the reservation follows the real output

    def test_gemma_style_pool_counts_the_input_only(self):
        b = QuotaBook(ModelSpec("g", Limits(tpm=16000), tpm_counts="input"), 1.0)
        b.settle(b.begin(T0, b.estimate_input(40000)), 12000, 40000, extra_tokens=3700)
        self.assertEqual(b.window[-1][1], 12000)
        self.assertEqual(b.out_estimate, 0.0)

    def test_the_target_keeps_the_minute_under_80_percent(self):
        b = QuotaBook(ModelSpec("m", Limits(tpm=250000), tpm_counts="input"), 1.0, tpm_target=0.8)
        for i in range(5):                                                                    # 5 x 40 000 = 200 000 = the target
            b.settle(b.begin(T0 + i, 40000), 40000)
        self.assertGreaterEqual(b.available_at(T0 + 6, 40000), T0 + 60.5)                     # a sixth would pass 80 % : wait
        self.assertEqual(QuotaBook(ModelSpec("m", Limits(tpm=250000)), 1.0).tpm_cap(), 250000)  # no target: the limit itself

    def test_a_request_alone_may_use_92_percent_but_not_more(self):
        b = QuotaBook(ModelSpec("g", Limits(tpm=16000), tpm_counts="input"), 1.0, tpm_target=0.8)
        self.assertEqual(b.available_at(T0, 14000), T0)                                       # 87 % alone: allowed (above the 80 % target)
        self.assertEqual(b.available_at(T0, 15000), FAR)                                      # 94 % : never
        b.settle(b.begin(T0, 14000), 14000)
        self.assertGreaterEqual(b.available_at(T0 + 1, 3000), T0 + 60.5)

    def test_the_caller_settles_with_the_output_and_the_thoughts(self):
        usage = {"promptTokenCount": 1000, "candidatesTokenCount": 300, "thoughtsTokenCount": 200}
        clock = FakeClock(T0)
        desk = QuotaDesk(cfg(ModelSpec("a", Limits(rpm=600, rpd=100, tpm=100000))))
        caller = ModelCaller(ScriptedClient(lambda m, n: ApiResult(True, 200, "{}", "STOP", usage, 0.1)), desk,
                             Pacer(clock.now, clock.wait), log=lambda s: None)
        caller(*CALL)
        self.assertEqual(desk.books["a"].day_tokens, 1500)


# ------------------------------------------------------------------------------------------------ tools share the ledger
class GateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "quota_global.json"

    def gate(self, handler, *specs, clock=None, **kw):
        clock = clock or FakeClock(T0)
        client = ScriptedClient(handler)
        client.post_generate = lambda model, body: (handler(model, 1).status, {"error": {"message": "x", "details": []}}, 0.1)
        desk = QuotaDesk(cfg(*specs), self.path, now=T0)
        return LedgerGate(client, desk, clock.now, clock.wait, **kw), client, desk, clock

    def test_a_tool_request_is_counted_in_the_ledger_the_generators_read(self):
        gate, client, desk, clock = self.gate(lambda m, n: ok_result(prompt=700), ModelSpec("a", Limits(60, 500)))
        gate.generate("a", "sys", "user", {})
        other = QuotaDesk(cfg(spec("a", rpm=60, rpd=500)), self.path, now=T0)
        self.assertEqual(other.table(T0 + 1)[0]["requests"], 1)
        self.assertEqual(other.table(T0 + 1)[0]["input_tokens"], 700 + 50)

    def test_the_tool_waits_for_the_pace_of_the_pool(self):
        gate, client, desk, clock = self.gate(lambda m, n: ok_result(), spec("a", rpm=15, rpd=500))
        gate.generate("a", "s", "u", {})
        gate.generate("a", "s", "u", {})
        self.assertAlmostEqual(clock.t - T0, 4.0, delta=0.01)

    def test_a_pool_that_is_out_for_the_day_is_not_asked(self):
        gate, client, desk, clock = self.gate(lambda m, n: limited("GenerateRequestsPerDayPerProjectPerModel-FreeTier", 500),
                                              spec("a", rpm=60, rpd=500))
        self.assertEqual(gate.generate("a", "s", "u", {}).status, 429)
        r = gate.generate("a", "s", "u", {})
        self.assertEqual((r.status, r.quota_scope), (429, "day"))                              # local 429: the retry time has not come
        self.assertEqual(len(client.calls), 1)

    def test_a_429_from_a_tool_is_learned_by_the_ledger(self):
        gate, client, desk, clock = self.gate(lambda m, n: limited("GenerateRequestsPerDayPerProjectPerModel-FreeTier", 500),
                                              spec("a", rpm=60, rpd=500))
        gate.generate("a", "s", "u", {})
        b = QuotaDesk(cfg(spec("a", rpm=60, rpd=500)), self.path, now=T0).books["a"]
        self.assertTrue(T0 < b.exhausted_until <= T0 + 700)                                    # a retry in 10 minutes, not midnight
        self.assertEqual(b.spent_at, T0)

    def test_status_shows_when_the_daily_quota_refused_and_reopened(self):
        from teacher.series import SeriesDirectory
        from teacher.status import StatusReport
        d = QuotaDesk(cfg(spec("a", rpm=60, rpd=500)), self.path, now=T0)
        with d.transaction(T0):
            d.books["a"].spend_day(T0, "requests/day")
            d.books["a"].settle(d.books["a"].begin(T0 + 700, 5), 5)
        text = StatusReport(SeriesDirectory("s", self.path.parent), cfg(spec("a", rpm=60, rpd=500)), T0 + 800).text()
        self.assertIn("daily-quota tries (UTC)", text)
        self.assertIn("429", text)
        self.assertIn("200", text)

    def test_an_unlisted_model_goes_through_untouched(self):
        gate, client, desk, clock = self.gate(lambda m, n: ok_result(), spec("a"))
        self.assertEqual(gate.generate("zzz", "s", "u", {}).status, 200)
        self.assertEqual(gate.redactor, client.redactor)                                       # every other attribute is the client's


# ------------------------------------------------------------------------------------------------ compact instructions
class CompactTests(unittest.TestCase):
    def test_the_compact_text_differs_only_by_its_sample_sentences(self):
        full = BatchInstructions(TK, PhraseBook(TK, 30), thoughts=True, compact_phrasebook=PhraseBook(TK, COMPACT_PHRASES))
        f, c = full.text(), full.text(True)
        self.assertLess(len(c), len(f) - 800)

        def without_sentences(t):
            i, j = t.index("== SENTENCES"), t.index("Compose in the same way")
            return t[:i] + t[j:]
        self.assertEqual(without_sentences(f), without_sentences(c))                           # same instructions, words, format, rules
        sample = lambda t: {l.strip() for l in t.splitlines() if l.startswith("  ") and ": (" in l}   # noqa: E731
        self.assertTrue(sample(c) <= sample(f))                                                # the compact sentences are among the full ones
        self.assertEqual(BatchInstructions(TK, PhraseBook(TK, 30)).text(True), BatchInstructions(TK, PhraseBook(TK, 30)).text())

    def test_the_variants_travel_with_the_text_and_a_plain_str_still_works(self):
        v = BatchInstructions(TK, PhraseBook(TK, 30), compact_phrasebook=PhraseBook(TK, 12)).variants()
        self.assertIsInstance(v, VariantText)
        self.assertEqual(str(v), BatchInstructions(TK, PhraseBook(TK, 30)).text())
        self.assertLess(len(v.compact), len(v))
        self.assertIsNone(BatchInstructions(TK, PhraseBook(TK, 30)).variants().compact)

    def test_the_compact_schema_text_drops_only_lists_the_instructions_give(self):
        schema = {"type": "OBJECT", "properties": {"g": {"type": "STRING", "enum": ["a", "b"]},
                                                   "p": {"type": "ARRAY", "items": {"type": "STRING"}}},
                  "required": ["g"], "propertyOrdering": ["g", "p"]}
        full, small = SchemaText.text(schema), SchemaText.text(schema, compact=True)
        self.assertIn('"enum"', full)
        self.assertNotIn("enum", small)
        self.assertNotIn("propertyOrdering", small)
        self.assertIn('"required":["g"]', small)                                               # required keys are never dropped
        body = PromptOnlyStrategy(compact_schema=True).prompt("S", "U", schema)
        self.assertIn("listed in the instructions", body)
        self.assertNotIn("listed in the instructions", PromptOnlyStrategy().prompt("S", "U", schema))

    def test_the_caller_gives_the_compact_text_only_to_a_compact_model(self):
        v = VariantText("FULL TEXT")
        v.compact = "SHORT"
        sent = []
        client = ScriptedClient(lambda m, n: ok_result())
        orig = client.generate
        client.generate = lambda model, system, *a, **k: (sent.append((model, system)), orig(model, system, *a, **k))[1]
        clock = FakeClock(T0)
        desk = QuotaDesk(cfg(spec("a", rpm=600), ModelSpec("g", Limits(rpm=600), compact=True, tpm_counts="input")))
        caller = ModelCaller(client, desk, Pacer(clock.now, clock.wait), log=lambda s: None)
        caller(v, "user", {})
        caller.only = "g"
        caller(v, "user", {})
        self.assertEqual(sent, [("a", "FULL TEXT"), ("g", "SHORT")])
        self.assertEqual(caller.last_prompt_chars, len("SHORT") + len("user"))


# ------------------------------------------------------------------------------------------------ generator and the lane
class LaneGeneratorTests(GeneratorCase):
    def lane_config(self, normal=True, **gkw):
        g = ModelSpec("g", Limits(600, 100000, tpm=16000), max_k=2, compact=True, tpm_counts="input", **gkw)
        return config(spec("a", rpm=600, rpd=100000), g) if normal else config(g)

    def test_the_compact_text_reaches_the_compact_model_and_the_journal_says_so(self):
        fake = FakeTeacher()
        with mock.patch("teacher.generator.COMPACT_PHRASES", 6):                              # (the fixture's full text has 12)
            gen = self.generator(fake, k=6, qc=self.lane_config(normal=False), max_requests=1)
        gen.run()
        self.assertEqual([r["model"] for r in fake.requests], ["g"])
        self.assertEqual(str(fake.requests[0]["system"]), gen.instructions.text(True))
        self.assertNotEqual(fake.requests[0]["system"], gen.instructions.text(False))
        rec = self.journal()[0]
        self.assertTrue(rec["compact"])
        self.assertEqual(rec["prompt_chars"], len(fake.requests[0]["system"]) + len(fake.requests[0]["user"]))
        self.assertEqual({l["teacher"] for l in self.lines()}, {"g"})                          # the label keeps the model

    def test_lane_k_follows_the_token_limit(self):
        gen = self.generator(FakeTeacher(), k=6, qc=self.lane_config())
        k = gen.lane_k("g")
        self.assertIn(k, (1, 2))
        gen._situation_chars = 100000                                                          # situations too big for the minute
        self.assertEqual(gen.lane_k("g"), 1)

    def test_a_chain_of_small_models_only_waits_for_its_turn_instead_of_asking_for_a_big_batch(self):
        fake = FakeTeacher(clock=self.clock, step=1.0)
        gen = self.generator(fake, k=12, qc=self.lane_config(normal=False), max_requests=2)
        gen.run()
        users = [r["user"].count("=== SITUATION") for r in fake.requests]
        self.assertTrue(all(1 <= n <= 2 for n in users), users)                                # never the 12 that were asked for

    def test_the_repair_of_a_lane_round_stays_with_the_lane_model(self):
        fake = FakeTeacher(broken={"S1"})
        gen = self.generator(fake, k=2, qc=self.lane_config(), max_requests=2)
        with gen.desk.transaction():
            gen.desk.books["a"].block(gen.pacer.clock(), 1000)                                  # `a` is cooling down: the lane has the round
        gen.one_round()
        self.assertEqual([r["model"] for r in fake.requests], ["g", "g"])                      # batch, then its repair: both Gemma
        self.assertTrue(fake.requests[1]["user"].startswith("REPAIR"))
        self.assertIsNone(gen.caller.sticky)                                                   # the round is over

    def test_a_lane_model_takes_the_round_only_when_nobody_else_answers_soon(self):
        gen = self.generator(FakeTeacher(), k=2, qc=self.lane_config())
        self.assertIsNone(gen.small_lane())                                                    # `a` is free
        with gen.desk.transaction():
            gen.desk.books["a"].block(gen.pacer.clock(), LANE_DEFER + 5)
        self.assertEqual(gen.small_lane(), "g")
        with gen.desk.transaction():
            gen.desk.books["a"].blocked_until = gen.pacer.clock() + LANE_DEFER - 5
        self.assertIsNone(gen.small_lane())

    def test_two_generators_on_two_series_share_the_one_ledger(self):
        qc = config(spec("a", rpm=600, rpd=5))
        g1 = self.generator(FakeTeacher(), name="s1", k=2, qc=qc, max_requests=3)
        g2 = self.generator(FakeTeacher(), name="s2", k=2, qc=qc, max_requests=2)
        g1.run()
        self.assertEqual(g2.desk.table(self.clock.t)[0]["requests"], 3)                        # g2 sees what g1 spent
        g2.run()
        doc = json.loads((Path(self.tmp.name) / "quota_global.json").read_text())
        self.assertEqual(doc["pools"]["a"]["day_requests"], 5)                                  # 3 + 2 = the daily limit of 5, spent by two series
        self.assertFalse((Path(self.tmp.name) / "s1" / "quota.json").exists())


if __name__ == "__main__":
    unittest.main()
