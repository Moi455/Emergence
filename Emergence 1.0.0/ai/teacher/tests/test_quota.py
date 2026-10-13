"""Tests of the quota books, the 429 classifier and the model caller (no network, fake clock).

    python3 -m unittest discover -s ai/teacher/tests -t ai
"""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from teacher.caller import FatalError, ModelCaller, Pacer
from teacher.gemini import ApiResult, GeminiClient, Redactor
from teacher.quota import (PACIFIC, Limits, ModelSpec, PacificDay, QuotaBook, QuotaConfig, QuotaDesk, QuotaError,
                           DEFAULT_CONFIG)


def pt(y, mo, d, h=0, mi=0, s=0) -> float:
    return datetime(y, mo, d, h, mi, s, tzinfo=PACIFIC).timestamp()


class FakeClock:
    """Epoch seconds; waiting advances it."""
    def __init__(self, t=None):
        self.t = pt(2026, 10, 13, 10) if t is None else t
        self.waits = []

    def now(self):
        return self.t

    def wait(self, s):
        self.waits.append(s)
        self.t += s


def violation(quota_id, value=None, metric="generativelanguage.googleapis.com/generate_content_free_tier_requests"):
    v = {"quotaMetric": metric, "quotaId": quota_id, "quotaDimensions": {"model": "x"}}
    if value is not None:
        v["quotaValue"] = str(value)
    return v


def limited(quota_id, value=None, retry=0.0, metric="generativelanguage.googleapis.com/generate_content_free_tier_requests"):
    scope, _ = GeminiClient.classify_quota({"details": [{"retryDelay": f"{retry}s"}] if retry else [],
                                            "message": quota_id})
    return ApiResult(False, 429, error="RESOURCE_EXHAUSTED You exceeded your current quota", quota_scope=scope,
                     retry_after=retry, quota_violations=[violation(quota_id, value, metric)])


def ok_result(prompt=1000, text='{"decisions": []}'):
    return ApiResult(True, 200, text, "STOP", {"promptTokenCount": prompt, "candidatesTokenCount": 50}, 0.5)


def config(*specs, margin=1.0):
    return QuotaConfig(tuple(specs), margin)


def spec(name, rpm=None, rpd=None, tpm=None, tpd=None):
    return ModelSpec(name, Limits(rpm, rpd, tpm, tpd))


# ------------------------------------------------------------------------------------------------ the Pacific day
class PacificDayTests(unittest.TestCase):
    def test_midnight_pacific_not_utc(self):
        t = pt(2026, 10, 13, 23, 59, 30)
        self.assertEqual(PacificDay.key(t), "2026-10-13")
        reset = PacificDay.next_reset(t)
        self.assertAlmostEqual(reset, pt(2026, 10, 14) + 3, delta=0.01)
        self.assertEqual(PacificDay.key(reset), "2026-10-14")
        self.assertEqual(PacificDay.key(reset - 10), "2026-10-13")

    def test_summer_time_changes_the_utc_hour_of_the_reset(self):
        summer, winter = PacificDay.next_reset(pt(2026, 7, 1, 12)), PacificDay.next_reset(pt(2026, 12, 1, 12))
        hour = lambda ts: datetime.fromtimestamp(ts, timezone.utc).hour         # noqa: E731
        self.assertEqual((hour(summer - 3), hour(winter - 3)), (7, 8))          # 00:00 PDT = 07:00 UTC, 00:00 PST = 08:00 UTC

    def test_day_of_25_hours(self):
        t = pt(2026, 11, 1, 12)                                                  # DST ends on 1 Nov 2026
        self.assertEqual(PacificDay.key(PacificDay.next_reset(t)), "2026-11-02")


# ------------------------------------------------------------------------------------------------ one book
class QuotaBookTests(unittest.TestCase):
    def test_rpm_spacing_is_exact_and_never_a_burst(self):
        b = QuotaBook(spec("m", rpm=15), margin=1.0)
        t0 = pt(2026, 10, 13, 10)
        b.begin(t0, 100)
        self.assertAlmostEqual(b.available_at(t0, 100), t0 + 4.0)                # 60 / 15
        self.assertAlmostEqual(QuotaBook(spec("m", rpm=5), 1.05).available_at(t0, 10), t0)   # nothing sent yet: right now

    def test_window_survives_a_restart(self):
        b = QuotaBook(spec("m", rpm=3), margin=0.0001)                           # spacing nil: only the sliding minute counts
        t0 = pt(2026, 10, 13, 10)
        for i in range(3):
            b.begin(t0 + i, 100)
        again = QuotaBook(spec("m", rpm=3), margin=0.0001)
        again.load(json.loads(json.dumps(b.to_dict())))
        self.assertGreaterEqual(again.available_at(t0 + 3, 100), t0 + 60.5)      # the 4th waits for the 1st to leave the minute

    def test_tpm_waits_for_old_requests_to_leave_the_minute(self):
        b = QuotaBook(spec("m", tpm=20000), margin=1.0)
        t0 = pt(2026, 10, 13, 10)
        e = b.begin(t0, 12000)
        b.settle(e, 12000)
        b.begin(t0 + 5, 7000)
        self.assertEqual(b.available_at(t0 + 6, 500), t0 + 6)                    # 19 000 + 500 <= 20 000
        self.assertGreaterEqual(b.available_at(t0 + 6, 2000), t0 + 60.5)         # 21 000 > 20 000: wait for the first one
        self.assertLess(b.available_at(t0 + 6, 2000), t0 + 62)

    def test_tpd_exhausts_until_the_pacific_midnight(self):
        b = QuotaBook(spec("m", tpd=30000), margin=1.0)
        t0 = pt(2026, 10, 13, 20)
        b.settle(b.begin(t0, 12000), 12000)
        b.settle(b.begin(t0 + 10, 12000), 12000)
        at = b.available_at(t0 + 20, 12000)
        self.assertAlmostEqual(at, PacificDay.next_reset(t0))
        self.assertTrue(b.exhausted_until)
        self.assertEqual(b.exhausted_why, "tpd")

    def test_rpd_then_reset_at_midnight(self):
        b = QuotaBook(spec("m", rpd=3), margin=1.0)
        t0 = pt(2026, 10, 13, 23, 50)
        for i in range(3):
            b.settle(b.begin(t0 + i, 10), 10)
        reset = PacificDay.next_reset(t0)
        self.assertAlmostEqual(b.available_at(t0 + 100, 10), reset)
        self.assertEqual(b.day_requests, 3)
        self.assertEqual(b.available_at(reset + 1, 10), reset + 1)               # a new Pacific day: counters at zero
        self.assertEqual((b.day, b.day_requests, b.exhausted_until), ("2026-10-14", 0, 0.0))
        self.assertEqual(b.history["2026-10-13"]["requests"], 3)

    def test_measured_tokens_replace_the_estimate(self):
        b = QuotaBook(spec("m", tpd=10 ** 9), margin=1.0)
        t0 = pt(2026, 10, 13, 10)
        e = b.begin(t0, 5000)
        b.settle(e, 9000, chars=30000)
        self.assertEqual(b.day_tokens, 9000)
        self.assertEqual(list(b.window[-1]), [t0, 9000])
        self.assertGreater(b.estimate_input(30000), 5000)                        # the ratio learned from the answer

    def test_a_failed_request_gives_back_its_tokens_but_keeps_its_rpm_slot(self):
        b = QuotaBook(spec("m", rpm=15, tpd=100000), margin=1.0)
        t0 = pt(2026, 10, 13, 10)
        b.settle(b.begin(t0, 9000), 0)
        self.assertEqual(b.day_tokens, 0)
        self.assertAlmostEqual(b.available_at(t0, 100), t0 + 4.0)


# ------------------------------------------------------------------------------------------------ the 429
class QuotaErrorTests(unittest.TestCase):
    def test_per_day_requests(self):
        e = QuotaError.parse([violation("GenerateRequestsPerDayPerProjectPerModel-FreeTier", 500)])
        self.assertEqual((e.scope, e.kind, e.limit), ("day", "requests", 500.0))

    def test_per_minute_tokens(self):
        e = QuotaError.parse([violation("GenerateContentInputTokensPerModelPerMinute-FreeTier", 250000,
                                        "generativelanguage.googleapis.com/generate_content_free_tier_input_token_count")],
                             retry_after=17)
        self.assertEqual((e.scope, e.kind, e.limit, e.retry_after), ("minute", "tokens", 250000.0, 17.0))

    def test_the_day_wins_over_the_minute(self):
        e = QuotaError.parse([violation("GenerateRequestsPerMinutePerProjectPerModel-FreeTier", 15),
                              violation("GenerateRequestsPerDayPerProjectPerModel-FreeTier", 500)])
        self.assertEqual(e.scope, "day")

    def test_message_when_there_are_no_details(self):
        e = QuotaError.parse([], "Quota exceeded for metric: generate_content_free_tier_requests, limit: 20 per day. "
                                 "Please retry in 41.5s.")
        self.assertEqual((e.scope, e.kind, e.limit, e.retry_after), ("day", "requests", None, 41.5))   # a limit only from quotaValue
        self.assertEqual(QuotaError.parse([], "").scope, "minute")               # nothing said: the mild reading

    def test_minute_429_blocks_and_learns(self):
        b = QuotaBook(spec("m", rpm=15, rpd=500), margin=1.0)
        t0 = pt(2026, 10, 13, 10)
        b.settle(b.begin(t0, 100), 0)
        msg = b.on_quota_error(t0, QuotaError("minute", "requests", 10.0, 20.0))
        self.assertIn("per minute", msg)
        self.assertEqual(b.limits().rpm, 10.0)                                   # learned from quotaValue
        self.assertAlmostEqual(b.available_at(t0, 100), t0 + 21.0)

    def test_three_minute_429_in_a_row_leave_the_model_for_ten_minutes(self):
        b = QuotaBook(spec("m"), margin=1.0)
        t0 = pt(2026, 10, 13, 10)
        for i in range(3):
            b.on_quota_error(t0 + i, QuotaError("minute", "requests", None, 5.0))
        self.assertGreaterEqual(b.available_at(t0 + 3, 1), t0 + 2 + 600)

    def test_day_429_exhausts_until_reset_and_learns_the_limit(self):
        b = QuotaBook(spec("m", rpd=500), margin=1.0)
        t0 = pt(2026, 10, 13, 10)
        b.on_quota_error(t0, QuotaError("day", "tokens", 1000000.0, 0.0))
        self.assertEqual(b.limits().tpd, 1000000)
        self.assertAlmostEqual(b.available_at(t0 + 5, 1), PacificDay.next_reset(t0))

    def test_gemini_client_exposes_the_violations(self):
        err = {"code": 429, "status": "RESOURCE_EXHAUSTED", "message": "quota",
               "details": [{"@type": "type.googleapis.com/google.rpc.QuotaFailure",
                            "violations": [violation("GenerateRequestsPerDayPerProjectPerModel-FreeTier", 20)]},
                           {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "30s"}]}
        r = GeminiClient("k")._failure(429, {"error": err}, 0.1)
        self.assertEqual(r.quota_scope, "day")
        self.assertEqual(r.quota_violations[0]["quotaValue"], "20")
        self.assertEqual(r.retry_after, 30.0)


# ------------------------------------------------------------------------------------------------ the desk and the file
class QuotaDeskTests(unittest.TestCase):
    def test_config_file_lists_the_models_in_preference_order(self):
        qc = QuotaConfig.load(DEFAULT_CONFIG)
        self.assertEqual(qc.models[0].name, "gemini-3.5-flash-lite")
        self.assertEqual(qc.models[0].limits, Limits(15, 500, 250000, 20_000_000))
        self.assertEqual([s.name for s in qc.models if s.limits.rpd == 20][:2], ["gemini-3.8-flash", "gemini-3.7-flash"])
        self.assertEqual(qc.only(["a-flash-lite", "gemini-2.5-flash"]).models[0].limits, Limits(15, 500))
        for m in qc.models:                                                  # every model has a local token cap (estimates, in the file)
            self.assertEqual(m.limits.tpm, 250000, m.name)
            self.assertEqual(m.limits.tpd, 20_000_000 if "lite" in m.name else 2_000_000, m.name)

    def test_choice_is_the_model_that_can_answer_first(self):
        desk = QuotaDesk(config(spec("a", rpm=15), spec("b", rpm=15)))
        t0 = pt(2026, 10, 13, 10)
        self.assertEqual(desk.choose(t0, 100).model, "a")
        desk.books["a"].begin(t0, 100)
        c = desk.choose(t0 + 0.1, 100)
        self.assertEqual((c.model, c.at), ("b", t0 + 0.1))
        desk.books["b"].begin(t0 + 0.1, 100)
        c = desk.choose(t0 + 0.2, 100)
        self.assertEqual(c.model, "a")
        self.assertAlmostEqual(c.at, t0 + 4.0)

    def test_all_exhausted_is_reported_and_the_wait_is_the_earliest_reset(self):
        desk = QuotaDesk(config(spec("a", rpd=1), spec("b", rpd=1)))
        t0 = pt(2026, 10, 13, 22)
        for n in ("a", "b"):
            desk.books[n].settle(desk.books[n].begin(t0, 10), 10)
        c = desk.choose(t0 + 1, 10)
        self.assertTrue(c.all_exhausted)
        self.assertAlmostEqual(c.at, PacificDay.next_reset(t0))

    def test_file_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "quota.json"
            desk = QuotaDesk(config(spec("a", rpm=15, rpd=500)), path)
            t0 = pt(2026, 10, 13, 10)
            desk.books["a"].settle(desk.books["a"].begin(t0, 100), 90)
            desk.books["a"].on_quota_error(t0, QuotaError("minute", "tokens", 250000.0, 3.0))
            desk.save()
            again = QuotaDesk(config(spec("a", rpm=15, rpd=500)), path)
            b = again.books["a"]
            self.assertEqual((b.day_requests, b.day_tokens, b.learned.tpm), (1, 90, 250000))
            self.assertGreater(b.blocked_until, t0)
            path.write_text("{not json")
            self.assertEqual(QuotaDesk(config(spec("a")), path).books["a"].day_requests, 0)    # damaged: start again


# ------------------------------------------------------------------------------------------------ the caller
class ScriptedClient:
    def __init__(self, handler):
        self.handler, self.calls, self.redactor, self.key = handler, [], Redactor(""), ""

    def generate(self, model, system, user, schema, temperature=0.9, max_output_tokens=1024, thinking_budget=None):
        self.calls.append(model)
        return self.handler(model, len(self.calls))


def make_caller(handler, *specs, margin=1.0, max_requests=None, clock=None):
    clock = clock or FakeClock()
    pacer = Pacer(clock.now, clock.wait)
    desk = QuotaDesk(config(*specs, margin=margin))
    client = ScriptedClient(handler)
    events = []
    caller = ModelCaller(client, desk, pacer, log=lambda s: None, event=events.append, max_requests=max_requests)
    return caller, client, desk, clock, events


CALL = ("sys", "user", {"type": "OBJECT"})


class CallerTests(unittest.TestCase):
    def test_daily_429_switches_to_the_next_model_and_keeps_it_out(self):
        def handler(model, n):
            return limited("GenerateRequestsPerDayPerProjectPerModel-FreeTier", 500) if model == "a" else ok_result()
        caller, client, desk, clock, events = make_caller(handler, spec("a", rpm=15, rpd=500), spec("b", rpm=15, rpd=500))
        self.assertEqual(caller(*CALL)[0], "b")
        self.assertEqual(client.calls, ["a", "b"])
        clock.wait(5)
        self.assertEqual(caller(*CALL)[0], "b")                              # "a" is out for the day: not asked again
        self.assertEqual(client.calls, ["a", "b", "b"])
        self.assertGreater(desk.books["a"].exhausted_until, clock.t)
        self.assertEqual(events[0]["http"], 429)

    def test_minute_429_waits_then_resumes_on_the_same_model(self):
        def handler(model, n):
            return limited("GenerateRequestsPerMinutePerProjectPerModel-FreeTier", 15, retry=20) if n == 1 else ok_result()
        caller, client, desk, clock, _ = make_caller(handler, spec("a", rpm=15, rpd=500))
        t0 = clock.t
        self.assertEqual(caller(*CALL)[0], "a")
        self.assertEqual(client.calls, ["a", "a"])
        self.assertGreaterEqual(clock.t - t0, 21.0)                          # the delay Google gave
        self.assertLess(clock.t - t0, 40.0)

    def test_minute_429_moves_to_another_model_without_waiting(self):
        def handler(model, n):
            return limited("GenerateRequestsPerMinutePerProjectPerModel-FreeTier", 15, retry=40) if model == "a" else ok_result()
        caller, client, desk, clock, _ = make_caller(handler, spec("a", rpm=15), spec("b", rpm=15))
        t0 = clock.t
        self.assertEqual(caller(*CALL)[0], "b")
        self.assertLess(clock.t - t0, 1.0)

    def test_pace_is_exact_no_burst(self):
        caller, client, desk, clock, _ = make_caller(lambda m, n: ok_result(), spec("a", rpm=15, rpd=500))
        times = []
        for _ in range(5):
            caller(*CALL)
            times.append(clock.t)
        gaps = [b - a for a, b in zip(times, times[1:])]
        self.assertTrue(all(abs(g - 4.0) < 0.01 for g in gaps), gaps)        # 60 / 15 s between two requests

    def test_all_models_out_sleeps_to_the_pacific_midnight_and_resumes(self):
        clock = FakeClock(pt(2026, 10, 13, 22, 30))
        caller, client, desk, _, _ = make_caller(lambda m, n: ok_result(), spec("a", rpm=60, rpd=2), spec("b", rpm=60, rpd=1),
                                                 clock=clock)
        for _ in range(3):
            caller(*CALL)
        self.assertEqual(client.calls, ["a", "b", "a"])
        got = caller(*CALL)                                                   # everything is spent: must sleep past midnight
        self.assertEqual(client.calls[-1], "a")
        self.assertGreaterEqual(clock.t, PacificDay.next_reset(pt(2026, 10, 13, 22, 30)))
        self.assertEqual(PacificDay.key(clock.t), "2026-10-14")
        self.assertEqual(got[0], "a")
        self.assertEqual(desk.books["a"].day_requests, 1)                    # counters restarted with the new day

    def test_tpm_counted_from_the_measured_tokens(self):
        caller, client, desk, clock, _ = make_caller(lambda m, n: ok_result(prompt=9000), spec("a", tpm=20000))
        t0 = clock.t
        for _ in range(3):
            caller(*CALL)
        # two requests of 9 000 fit in a minute, the third has to wait for the first to leave it
        self.assertGreaterEqual(clock.t - t0, 60.0)
        self.assertEqual(desk.books["a"].day_tokens, 27000)

    def test_server_errors_pause_and_are_not_counted_as_quota(self):
        def handler(model, n):
            return ApiResult(False, 503, error="UNAVAILABLE overloaded") if n <= 2 else ok_result()
        caller, client, desk, clock, _ = make_caller(handler, spec("a", rpm=60, rpd=500))
        t0 = clock.t
        self.assertEqual(caller(*CALL)[0], "a")
        self.assertGreaterEqual(clock.t - t0, 5 + 10)                         # 5 s, then 10 s
        self.assertEqual(desk.books["a"].day_tokens, 1000)                    # only the answered request counts as tokens

    def test_missing_model_is_set_aside(self):
        caller, client, desk, clock, _ = make_caller(lambda m, n: ApiResult(False, 404, error="NOT_FOUND") if m == "a" else ok_result(),
                                                     spec("a"), spec("b"))
        self.assertEqual(caller(*CALL)[0], "b")
        self.assertGreater(desk.books["a"].exhausted_until, clock.t)

    def test_client_errors_on_three_models_are_fatal(self):
        bad = lambda m, n: ApiResult(False, 400, error="INVALID_ARGUMENT API key not valid")     # noqa: E731
        caller, *_ = make_caller(bad, spec("a"), spec("b"), spec("c"))
        with self.assertRaises(FatalError):
            caller(*CALL)

    def test_a_model_with_two_client_errors_is_set_aside_but_the_others_go_on(self):
        caller, client, desk, clock, _ = make_caller(
            lambda m, n: ApiResult(False, 400, error="INVALID_ARGUMENT thinking") if m == "a" else ok_result(), spec("a"), spec("b"))
        self.assertEqual(caller(*CALL)[0], "b")
        self.assertEqual(caller(*CALL)[0], "b")                              # "a" failed a second time: set aside for the day
        caller(*CALL)
        self.assertEqual(client.calls.count("a"), 2)

    def test_request_cap_and_stop(self):
        caller, client, desk, clock, _ = make_caller(lambda m, n: ok_result(), spec("a", rpm=60), max_requests=2)
        self.assertIsNotNone(caller(*CALL))
        self.assertIsNotNone(caller(*CALL))
        self.assertIsNone(caller(*CALL))
        self.assertEqual(len(client.calls), 2)
        caller2, c2, *_ = make_caller(lambda m, n: ok_result(), spec("a", rpm=60))
        caller2.pacer.request_stop()
        self.assertIsNone(caller2(*CALL))
        self.assertEqual(c2.calls, [])

    def test_stop_interrupts_a_long_sleep(self):
        clock = FakeClock(pt(2026, 10, 13, 22, 30))
        caller, client, desk, _, _ = make_caller(lambda m, n: ok_result(), spec("a", rpd=1), clock=clock)
        caller(*CALL)
        seen = []
        orig = clock.wait
        clock.wait = lambda s: (seen.append(s), orig(s), caller.pacer.request_stop() if len(seen) == 3 else None)[0]
        caller.pacer._wait = clock.wait
        self.assertIsNone(caller(*CALL))
        self.assertEqual(len(seen), 3)
        self.assertLess(clock.t, PacificDay.next_reset(pt(2026, 10, 13, 22, 30)))


if __name__ == "__main__":
    unittest.main()
