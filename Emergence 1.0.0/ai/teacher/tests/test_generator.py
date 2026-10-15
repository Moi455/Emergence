"""Tests of the continuous generator: batches, repair, resume, stop, restart, status, migration (no network).

    python3 -m unittest discover -s ai/teacher/tests -t ai
"""
from __future__ import annotations

import contextlib
import io
import json
import re
import tempfile
import unittest
from pathlib import Path

from situations.sampler import SituationSampler

from teacher.batch import (BatchAnswer, BatchInstructions, BatchPrompt, BatchSchema, GroupedRound, Outcome, RoundResult,
                           Slot)
from teacher.caller import FatalError, Pacer
from teacher.dataset import DatasetFile, LabelRecord, LineMeta
from teacher.gemini import ApiResult, Redactor
from teacher.generator import CodeFingerprint, Generator, RestartWatcher, main as generator_main, selfcheck
from teacher.migrate import Migration, cli as migrate_cli, stats
from teacher.phrasebook import PhraseBook
from teacher.quota import PacificDay
from teacher.render import SituationRenderer
from teacher.schema import DecisionSchema
from teacher.series import AppendFile, SeriesDirectory, SeriesState, SituationCursor
from teacher.status import StatusReport
from teacher.tests.test_quota import FakeClock, config, pt, spec
from teacher.toolkit import ROOT, Toolkit

TK = Toolkit()
SAMPLERS: dict = {}


def sampler_factory(seed):
    if seed not in SAMPLERS:
        SAMPLERS[seed] = SituationSampler(seed)
    return SAMPLERS[seed]


def wait_decision(label):
    return {"id": label, "why": "nothing calls me", "gesture": "wait", "params": [{"name": "until", "value": "c_done"}],
            "speech": "", "writes": []}


class FakeTeacher:
    """Stands in for GeminiClient. `broken` = labels refused on the FIRST reply of each batch (unknown gesture)."""

    def __init__(self, broken=(), hook=None, drop=(), extra=False, always_broken=(), garbage=False, clock=None, step=0.0,
                 garbage_models=()):
        self.requests, self.redactor, self.key = [], Redactor(""), ""
        self.broken, self.hook, self.drop, self.extra = set(broken), hook, set(drop), extra
        self.always_broken, self.garbage, self.clock, self.step = set(always_broken), garbage, clock, step
        self.garbage_models = set(garbage_models)

    def generate(self, model, system, user, schema, temperature=0.9, max_output_tokens=1024, thinking_budget=None):
        self.requests.append({"model": model, "system": system, "user": user, "schema": schema})
        if self.hook:
            self.hook(self)
        if self.clock is not None:
            self.clock.t += self.step
        if self.garbage or model in self.garbage_models:
            return ApiResult(True, 200, "this is not json", "STOP", {"promptTokenCount": 500}, 0.2)
        repair = user.startswith("REPAIR")
        out = []
        for label in re.findall(r"=== SITUATION (S\d+) ===", user):
            if label in self.drop and not repair:
                continue
            d = wait_decision(label)
            if label in self.always_broken or (label in self.broken and not repair):
                d["gesture"] = "teleport"
            out.append(d)
        if self.extra and not repair:
            out += [wait_decision("S1"), wait_decision("S99")]
        usage = {"promptTokenCount": (len(system) + len(user)) // 4, "candidatesTokenCount": 40 * len(out),
                 "thoughtsTokenCount": 0}
        return ApiResult(True, 200, json.dumps({"decisions": out}), "STOP", usage, 0.3)


class GeneratorCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.clock = FakeClock()

    def generator(self, client, name="s", k=4, max_requests=None, days=None, **kw):
        series = SeriesDirectory(name, self.tmp.name)
        pacer = kw.pop("pacer", None) or Pacer(self.clock.now, self.clock.wait)
        qc = kw.pop("qc", None) or config(spec("a", rpm=600, rpd=100000), spec("b", rpm=600, rpd=100000))
        gen = Generator(series, client, qc, k=k, days=days, max_requests=max_requests, tk=TK, pacer=pacer,
                        log=kw.pop("log", lambda s: None), sampler_factory=sampler_factory, phrases=12, **kw)
        return gen

    def lines(self, series="s"):
        p = Path(self.tmp.name) / series / "dataset.jsonl"
        return [json.loads(l) for l in p.read_text().splitlines()] if p.exists() else []

    def journal(self, series="s"):
        p = Path(self.tmp.name) / series / "journal.jsonl"
        return [json.loads(l) for l in p.read_text().splitlines()] if p.exists() else []


# ------------------------------------------------------------------------------------------------ batch pieces
class BatchPieceTests(unittest.TestCase):
    def test_phrasebook_is_valid_varied_deterministic_and_clean(self):
        pb = PhraseBook(TK, 30)
        phrases = pb.select()
        self.assertGreaterEqual(len(phrases), 25)
        self.assertEqual(pb.rejected, [])
        for p in phrases:
            self.assertTrue(TK.expression(p.text).ok, p.text)
        functions = {p.function for p in phrases}
        for want in ("greet", "ask a question", "request an act", "accept", "refuse", "apologise", "promise",
                     "threaten or set a condition", "report hearsay"):
            self.assertIn(want, functions)
        self.assertEqual([p.text for p in phrases], [p.text for p in PhraseBook(TK, 30).select()])      # cache-friendly
        blob = " ".join(p.text for p in phrases)
        for banned in ("romantic", "spouse", "w_beautiful", "touch"):
            self.assertNotIn(banned, blob)

    def test_phrasebook_drops_a_sentence_the_language_no_longer_accepts(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "stories.toml"
            f.write_text('[[story]]\nid = "x"\nutterances = ["(hello)", "(ask (are you well))", "(yes)"]\n')
            pb = PhraseBook(TK, 30, path=f)
            self.assertEqual([p.text for p in pb.select()], ["(hello)", "(yes)"])
            self.assertEqual(pb.rejected[0][0], "(ask (are you well))")

    def test_instructions_describe_the_batch_and_carry_the_phrasebook(self):
        text = BatchInstructions(TK, PhraseBook(TK, 30)).text()
        self.assertIn('{"decisions": [...]}', text)
        self.assertIn("== SENTENCES THAT THE LANGUAGE ACCEPTS", text)
        self.assertIn('"id": the situation id', text)
        self.assertLess(text.index("== SENTENCES"), text.index("== EXAMPLE"))
        self.assertNotIn("Reply with one JSON object and nothing else:\n  \"why\"", text)        # the single-situation format is gone
        for g in TK.spec.gestures:
            self.assertIn(f"  {g}", text)                                                          # the full catalogue is still there

    def test_schema_is_a_list_of_the_single_decision_with_an_id(self):
        single = DecisionSchema(TK, "full")
        s = BatchSchema(single).response_schema(6)
        self.assertEqual(s["required"], ["decisions"])
        arr = s["properties"]["decisions"]
        self.assertEqual(arr["type"], "ARRAY")
        self.assertNotIn("maxItems", arr)                                  # Gemini refuses it here (400, measured): the parser caps
        item = arr["items"]
        self.assertEqual(item["required"][0], "id")
        self.assertEqual(item["propertyOrdering"][0], "id")
        self.assertEqual(set(item["properties"]) - {"id"}, set(single.response_schema()["properties"]))
        self.assertEqual(item["properties"]["gesture"]["enum"], TK.spec.gesture_ids)
        json.dumps(s)
        std = BatchSchema(single).response_schema(3, gemini=False)["properties"]["decisions"]
        self.assertEqual((std["type"], std["maxItems"]), ("array", 3))

    def test_answer_parsing(self):
        ok = lambda t, finish="STOP": ApiResult(True, 200, t, finish)                  # noqa: E731
        a = BatchAnswer.parse(ok(json.dumps({"decisions": [wait_decision("S1"), wait_decision("S1"), wait_decision("S7")]})),
                              ["S1", "S2"])
        self.assertEqual((sorted(a.items), a.duplicates, a.unknown, a.problem), (["S1"], 1, 1, ""))
        self.assertEqual(BatchAnswer.parse(ok("nope"), ["S1"]).problem, "invalid_json")
        self.assertEqual(BatchAnswer.parse(ok("{}"), ["S1"]).problem, "bad_shape")
        self.assertEqual(BatchAnswer.parse(ok('{"decisions": [{"id":'), ["S1"]).problem, "invalid_json")
        self.assertEqual(BatchAnswer.parse(ok("[", "MAX_TOKENS"), ["S1"]).problem, "truncated")
        self.assertEqual(BatchAnswer.parse(ApiResult(False, 200, "", "SAFETY"), ["S1"]).problem, "no_text")
        self.assertEqual(sorted(BatchAnswer.parse(ok(json.dumps([wait_decision("S2")])), ["S1", "S2"]).items), ["S2"])

    def test_d10_refusals_and_our_own_bugs_are_never_sent_back(self):
        for code, repairable in (("governor:d10_intimate", False), ("governor:d10_value", False), ("truth_error", False),
                                 ("governor:step", True), ("bad_speech", True), ("missing", True), ("invalid_json", True)):
            self.assertEqual(Slot("S1", None, first=Outcome(None, code)).repairable, repairable, code)
        self.assertFalse(Slot("S1", None, first=Outcome(None, "ok")).ok)


# ------------------------------------------------------------------------------------------------ the generator
class RoundTests(GeneratorCase):
    def test_batches_write_labels_journal_and_state(self):
        t = FakeTeacher()
        gen = self.generator(t, k=4, max_requests=3)
        self.assertEqual(gen.run(), 0)
        lines = self.lines()
        self.assertEqual(len(lines), 12)
        self.assertEqual([l["id"] for l in lines], [f"s:0:{i}" for i in range(12)])
        self.assertEqual(len({l["id"] for l in lines}), 12)
        tok = sampler_factory(0).tokenizer
        for l in lines:
            self.assertEqual(l["hdr"], LabelRecord.short_header(tok.header()))
            self.assertEqual(l["verdict"], "ok")
            self.assertIn("a", {l["teacher"], "a"})
            self.assertEqual(l["decision"]["gesture"], "wait")
            self.assertEqual(l["context"]["header"], tok.header())
            self.assertIn("me", l["source"]["ages"])
            self.assertNotIn("why", json.dumps(l))
        for r in DatasetFile(Path(self.tmp.name) / "s" / "dataset.jsonl"):
            self.assertTrue(r.decision["gesture"])
        j = self.journal()
        self.assertEqual([r["kind"] for r in j], ["batch"] * 3)
        self.assertEqual(j[-1]["cursor"], [0, 12])
        self.assertEqual(j[0]["usage"]["prompt"], (len(t.requests[0]["system"]) + len(t.requests[0]["user"])) // 4)
        self.assertEqual([x["id"] for x in j[0]["results"]], ["S1", "S2", "S3", "S4"])
        st = SeriesState.load_or_new(Path(self.tmp.name) / "s" / "state.json", "s", 0, 4, 0)
        self.assertEqual((st.next_index, st.valid, st.batches, st.requests), (12, 12, 3, 3))
        self.assertTrue((Path(self.tmp.name) / "quota_global.json").exists())          # ONE ledger next to the series folders
        # the key never reaches the journal; the system text is the same in every request (implicit prompt cache)
        self.assertEqual(len({r["system"] for r in t.requests}), 1)

    def test_refused_decisions_are_repaired_once_with_their_error(self):
        t = FakeTeacher(broken={"S2", "S4"})
        gen = self.generator(t, k=4, max_requests=2)
        gen.run()
        self.assertEqual(len(t.requests), 2)
        repair = t.requests[1]["user"]
        self.assertTrue(repair.startswith("REPAIR"))
        self.assertEqual(re.findall(r"=== SITUATION (S\d+) ===", repair), ["S2", "S4"])              # only the refused ones
        self.assertIn("REFUSED BECAUSE: unknown_gesture", repair)
        self.assertIn("teleport", repair)                                                            # their own refused answer
        lines = self.lines()
        self.assertEqual(len(lines), 4)
        self.assertEqual([bool(l["source"].get("repaired")) for l in lines], [False, True, False, True])
        self.assertEqual([r["kind"] for r in self.journal()], ["batch", "repair"])
        self.assertEqual([x["code"] for x in self.journal()[0]["results"]], ["ok", "unknown_gesture", "ok", "unknown_gesture"])
        self.assertEqual([x["code"] for x in self.journal()[1]["results"]], ["ok", "ok"])

    def test_one_repair_attempt_only(self):
        t = FakeTeacher(always_broken={"S2"})
        gen = self.generator(t, k=4)
        sits = gen.build_situations(gen.cursor.take(4))
        res = gen.round.run(sits)
        self.assertEqual([rq.kind for rq in res.requests], ["batch", "repair"])                      # no third request
        self.assertEqual(len(t.requests), 2)
        self.assertEqual([s.ok for s in res.slots], [True, False, True, True])
        s2 = res.slots[1]
        self.assertEqual((s2.first.code, s2.second.code, s2.final.code, s2.repaired), ("unknown_gesture",) * 3 + (True,))

    def test_missing_unknown_and_duplicate_ids(self):
        t = FakeTeacher(drop={"S3"}, extra=True)
        gen = self.generator(t, k=4, max_requests=2)
        gen.run()
        j = self.journal()
        self.assertEqual((j[0]["answered"], j[0]["duplicates"], j[0]["unknown_ids"]), (3, 1, 1))
        self.assertEqual([x["code"] for x in j[0]["results"]], ["ok", "ok", "missing", "ok"])
        self.assertEqual(len(self.lines()), 4)                                                       # S3 came back with the repair
        self.assertEqual(re.findall(r"=== SITUATION (S\d+) ===", t.requests[1]["user"]), ["S3"])
        self.assertIn("none (that situation was missing", t.requests[1]["user"])

    def test_repair_can_be_switched_off(self):
        t = FakeTeacher(broken={"S1"})
        gen = self.generator(t, k=4, max_requests=1, repair=False)
        gen.run()
        self.assertEqual((len(t.requests), len(self.lines())), (1, 3))

    def test_request_cap_skips_the_repair(self):
        gen = self.generator(FakeTeacher(broken={"S1"}), k=4, max_requests=1)
        sits = gen.build_situations(gen.cursor.take(4))
        res = gen.round.run(sits)
        self.assertEqual(res.skipped_repair, "request cap reached")
        self.assertEqual(sum(s.ok for s in res.slots), 3)


class ResumeTests(GeneratorCase):
    def test_resume_never_asks_the_same_situation_twice(self):
        self.generator(FakeTeacher(), k=4, max_requests=2).run()
        t2 = FakeTeacher()
        gen2 = self.generator(t2, k=4, max_requests=2)
        self.assertEqual((gen2.cursor.seed, gen2.cursor.index), (0, 8))
        gen2.run()
        ids = [l["id"] for l in self.lines()]
        self.assertEqual(ids, [f"s:0:{i}" for i in range(16)])
        self.assertEqual(len(self.journal()), 4)

    def test_crash_in_the_middle_of_a_write_and_a_lost_state_file(self):
        self.generator(FakeTeacher(), k=4, max_requests=2).run()
        base = Path(self.tmp.name) / "s"
        with open(base / "dataset.jsonl", "a") as f:
            f.write('{"format":"emergence-labels-1","hdr":"abc')                                 # killed mid-line
        with open(base / "journal.jsonl", "a") as f:
            f.write('{"t": "2026')
        (base / "state.json").unlink()                                                            # and the state is gone
        gen = self.generator(FakeTeacher(), k=4, max_requests=1)
        self.assertEqual(gen.recovered["dataset"] > 0 and gen.recovered["journal"] > 0, True)
        self.assertEqual((gen.cursor.seed, gen.cursor.index), (0, 8))                             # found again from the journal
        gen.run()
        ids = [l["id"] for l in self.lines()]                                                     # every line parses: nothing glued
        self.assertEqual(ids, [f"s:0:{i}" for i in range(12)])
        for line in (base / "journal.jsonl").read_text().splitlines():
            json.loads(line)

    def test_cursor_is_found_again_from_the_dataset_when_the_journal_is_behind(self):
        self.generator(FakeTeacher(), k=4, max_requests=2).run()
        base = Path(self.tmp.name) / "s"
        (base / "state.json").unlink()
        j = (base / "journal.jsonl").read_text().splitlines()
        (base / "journal.jsonl").write_text(j[0] + "\n")                                          # the last journal line was lost
        gen = self.generator(FakeTeacher(), k=4, max_requests=1)
        self.assertEqual((gen.cursor.seed, gen.cursor.index), (0, 8))

    def test_seed_moves_on_after_a_block(self):
        st = SeriesState("x", seed=3, next_index=999_998)
        c = SituationCursor(st)
        self.assertEqual(c.take(4), [(3, 999_998), (3, 999_999), (4, 0), (4, 1)])

    def test_sigterm_finishes_the_round_and_saves(self):
        gen_box = {}
        t = FakeTeacher(hook=lambda self: gen_box["g"].pacer.request_stop() if len(self.requests) == 2 else None)
        gen = self.generator(t, k=4)
        gen_box["g"] = gen
        self.assertEqual(gen.run(), 0)
        self.assertEqual(len(t.requests), 2)                                                      # the round in flight was finished
        self.assertEqual(len(self.lines()), 8)
        st = json.loads((Path(self.tmp.name) / "s" / "state.json").read_text())
        self.assertEqual((st["next_index"], st["valid"]), (8, 8))

    def test_stopping_while_waiting_consumes_no_situation(self):
        clock = self.clock
        clock.t = pt(2026, 10, 13, 22, 30)
        qc = config(spec("a", rpm=60, rpd=1))

        class Wall(FakeTeacher):                                                                  # Google refuses after the first request
            def generate(self, *a, **k):
                if self.requests:
                    return ApiResult(False, 429, error="RESOURCE_EXHAUSTED", quota_scope="day",
                                     quota_violations=[{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier",
                                                        "quotaMetric": "x_requests", "quotaValue": "500"}])
                return super().generate(*a, **k)
        gen = self.generator(Wall(), k=4, qc=qc)
        n = {"w": 0}
        orig = gen.pacer._wait

        def waiter(s):
            orig(s)
            n["w"] += 1
            if n["w"] == 2:
                gen.pacer.request_stop()
        gen.pacer._wait = waiter
        self.assertEqual(gen.run(), 0)
        self.assertEqual(len(self.lines()), 4)                                                    # one round before the quota ended
        st = json.loads((Path(self.tmp.name) / "s" / "state.json").read_text())
        self.assertEqual(st["next_index"], 4)                                                     # the second round asked nothing

    def test_days_limit(self):
        t = FakeTeacher(clock=self.clock, step=3 * 3600)
        gen = self.generator(t, k=2, days=0.5)
        gen.state.started_at = self.clock.t
        self.assertEqual(gen.run(), 0)
        self.assertEqual(len(t.requests), 4)                                                      # 4 x 3 h = 12 h = half a day

    def test_a_broken_prompt_stops_the_run_only_when_every_model_has_failed(self):
        t = FakeTeacher(garbage=True)
        gen = self.generator(t, k=2)
        self.assertEqual(gen.run(), 3)                                                            # both models gave nothing usable
        self.assertEqual(self.lines(), [])
        self.assertLessEqual(len(t.requests), 4)

    def test_a_model_without_usable_decision_is_set_aside_for_an_hour_and_the_others_go_on(self):
        t = FakeTeacher(garbage_models={"a"})
        qc = config(spec("a", rpm=600, rpd=100000), spec("b", rpm=600, rpd=100000), spec("c", rpm=600, rpd=100000))
        gen = self.generator(t, k=2, qc=qc, max_requests=12)
        self.assertEqual(gen.run(), 0)                                                            # not fatal
        a = gen.desk.books["a"]
        self.assertEqual(a.exhausted_why, "unusable")
        self.assertGreater(a.exhausted_until, self.clock.t - 3600)
        models = [r["model"] for r in t.requests]
        self.assertGreater(len(self.lines()), 0)
        self.assertEqual(models[:2], ["a", "a"])                                                   # batch, then its repair
        self.assertNotIn("a", models[2:])                                                         # left alone afterwards (an hour)

    def test_an_unexpected_exception_is_retried_a_few_times_then_stops(self):
        def boom(self_):
            raise KeyError("bug")
        t = FakeTeacher(hook=boom)
        gen = self.generator(t, k=2)
        self.assertEqual(gen.run(), 3)
        self.assertEqual(len(t.requests), 5)
        self.assertEqual((gen.cursor.seed, gen.cursor.index), (0, 0))                              # nothing consumed
        self.assertEqual(sum(r.get("kind") == "crash" for r in self.journal()), 5)

    def test_a_situation_that_cannot_be_sampled_is_skipped_and_counted(self):
        def factory(seed):
            real = sampler_factory(seed)

            class Wrap:
                tokenizer = real.tokenizer

                def sample(self, i):
                    if i == 1:
                        raise ValueError("boom")
                    return real.sample(i)
            return Wrap()
        series = SeriesDirectory("s", self.tmp.name)
        gen = Generator(series, FakeTeacher(), config(spec("a", rpm=600)), k=3, max_requests=1, tk=TK,
                        pacer=Pacer(self.clock.now, self.clock.wait), log=lambda s: None, sampler_factory=factory, phrases=12)
        gen.run()
        self.assertEqual([l["id"] for l in self.lines()], ["s:0:0", "s:0:2"])
        self.assertEqual(gen.state.sample_errors, 1)
        self.assertTrue(any(r.get("kind") == "sample_error" for r in self.journal()))


class RestartTests(GeneratorCase):
    class Watch:
        def __init__(self, changed):
            self.flags, self.accepted = list(changed), 0

        def changed(self):
            return self.flags.pop(0) if self.flags else False

        def accept_current(self):
            self.accepted += 1

    def test_restart_when_the_new_code_passes_its_selfcheck(self):
        calls = []
        w = self.Watch([False, True])
        gen = self.generator(FakeTeacher(), k=2, watcher=w, selfcheck=lambda: True, restarter=calls.append, argv=["--name", "s", "--call"])
        gen.check_restart()
        self.assertEqual(calls, [])
        gen.check_restart()
        self.assertEqual(calls, [["--name", "s", "--call"]])
        st = json.loads((Path(self.tmp.name) / "s" / "state.json").read_text())
        self.assertEqual(st["restarts"], 1)

    def test_no_restart_into_broken_code(self):
        calls = []
        w = self.Watch([True])
        gen = self.generator(FakeTeacher(), k=2, watcher=w, selfcheck=lambda: False, restarter=calls.append)
        gen.check_restart()
        self.assertEqual((calls, w.accepted), ([], 1))

    def test_idle_waits_also_listen_for_changes(self):
        calls = []
        w = self.Watch([True])
        qc = config(spec("a", rpm=60, rpd=1))
        self.clock.t = pt(2026, 10, 13, 22, 30)
        gen = self.generator(FakeTeacher(), k=2, qc=qc, watcher=w, selfcheck=lambda: True, restarter=calls.append, max_requests=2)
        gen.caller.max_requests = 2
        gen.run()
        self.assertTrue(calls)                                                                    # noticed during the long sleep

    def test_watcher_waits_for_the_edit_to_finish(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for sub in ("ai/teacher", "ai/situations", "ai/tok2", "catalogue/tools", "catalogue/data", "catalogue/generated"):
                (root / sub).mkdir(parents=True)
            f = root / "catalogue" / "data" / "a.toml"
            f.write_text("x = 1\n")
            clock = FakeClock(1000.0)
            w = RestartWatcher(CodeFingerprint(root), clock.now, quiet=30.0)
            self.assertFalse(w.changed())
            f.write_text("x = 2\n")
            clock.t += 5
            self.assertFalse(w.changed())                                                         # changed, but an editor may be at work
            clock.t += 10
            f.write_text("x = 3\n")                                                               # edited again: the quiet time restarts
            clock.t += 20
            self.assertFalse(w.changed())
            clock.t += 31
            self.assertTrue(w.changed())
            w.accept_current()
            self.assertFalse(w.changed())
            calls = []
            real = w.fp.digest
            w.fp.digest = lambda: calls.append(1) or real()
            for _ in range(5):
                clock.t += 60
                w.changed()
            self.assertEqual(calls, [])                                                           # nothing moved: no file is read
            w.fp.digest = real
            f.write_text("x = 3\n")                                                               # touched, same contents
            clock.t += 31
            w.changed()
            clock.t += 31
            self.assertFalse(w.changed())
            (root / "catalogue" / "generated" / "model_interface.json").write_text("{}")
            self.assertFalse(w.changed())                                                         # a new file: the quiet time restarts
            clock.t += 31
            self.assertTrue(w.changed())

    def test_the_real_fingerprint_covers_the_catalogue_and_the_code(self):
        names = {p.relative_to(ROOT).as_posix() for p in CodeFingerprint().files()}
        for want in ("catalogue/generated/model_interface.json", "ai/teacher/generator.py", "catalogue/data/language_core.toml",
                     "ai/tok2/tokenizer.py", "ai/situations/sampler.py", "ai/teacher/quota.toml"):
            self.assertIn(want, names)


class StatusTests(GeneratorCase):
    def test_status_report(self):
        t = FakeTeacher(broken={"S2"})
        gen = self.generator(t, k=4, max_requests=2)
        gen.run()
        rep = StatusReport(gen.series, config(spec("a", rpm=600, rpd=100000), spec("b", rpm=600, rpd=100000)), self.clock.now())
        data = rep.compute()
        day = PacificDay.key(self.clock.now())
        self.assertIn(day, data)
        m = data[day]["a"]
        self.assertEqual((m["batches"], m["repairs"], m["asked"], m["valid_first"], m["valid_repair"]), (1, 1, 4, 3, 1))
        text = rep.text()
        self.assertIn(f"quota day {day}", text)
        self.assertIn("1 batches + 1 repairs", text)
        self.assertIn("valid 4 (3 at once + 1 after repair", text)
        self.assertIn("passive gestures 100%", text)                                              # the fake teacher only waits
        self.assertIn("unknown_gesture", text)
        self.assertIn("dataset.jsonl: 4 lines", text)
        self.assertIn("== quota now", text)

    def test_status_of_an_empty_series(self):
        series = SeriesDirectory("empty", self.tmp.name)
        self.assertIn("series empty", StatusReport(series).text())


class SeriesFileTests(unittest.TestCase):
    def test_refuses_the_repository(self):
        with self.assertRaises(SystemExit):
            SeriesDirectory("x", ROOT / "ai")
        with self.assertRaises(SystemExit):
            SeriesDirectory("../x", tempfile.gettempdir())

    def test_append_file_cuts_a_half_written_last_line(self):
        with tempfile.TemporaryDirectory() as d:
            f = AppendFile(Path(d) / "x.jsonl")
            f.append(["{\"a\":1}", "{\"a\":2}"])
            with open(f.path, "a") as h:
                h.write('{"a":')
            self.assertEqual(f.recover(), 5)
            self.assertEqual(f.last_line(), '{"a":2}')
            self.assertEqual(f.recover(), 0)
            f.append(["{\"a\":3}"])
            self.assertEqual(f.count_lines(), 3)

    def test_main_dry_run_and_selfcheck(self):
        with tempfile.TemporaryDirectory() as d, contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(generator_main(["--name", "dry", "--out", d, "--k", "3"]), 0)
            self.assertTrue((Path(d) / "dry" / "dry" / "system.txt").exists())
            self.assertEqual(generator_main(["--name", "dry", "--out", d, "--status"]), 0)
            self.assertEqual(selfcheck(), 0)
        self.assertIn("selfcheck ok", out.getvalue())


# ------------------------------------------------------------------------------------------------ migration
class MigrationTests(GeneratorCase):
    def setUp(self):
        super().setUp()
        self.generator(FakeTeacher(), k=4, max_requests=2).run()
        self.base = Path(self.tmp.name) / "s"
        self.current = self.lines()
        self.mig = Migration(TK)

    def old(self, line: dict, **changes) -> str:
        d = json.loads(json.dumps(line))
        d["hdr"] = "00000000:00000000"
        d["context"]["header"] = {"schema": d["context"]["header"]["schema"], "interface": "0" * 16, "layout": "0" * 16}
        for k, v in changes.items():
            d[k] = v
        return json.dumps(d, separators=(",", ":"), ensure_ascii=False)

    def test_current_lines_are_kept_byte_for_byte(self):
        from teacher.migrate import MigrationReport
        rep = MigrationReport()
        raw = (self.base / "dataset.jsonl").read_text().splitlines()[0]
        self.assertEqual(self.mig.line(raw, rep), raw)
        self.assertEqual((rep.kept_current, rep.migrated), (1, 0))

    def test_old_header_is_rewritten_when_context_encodes_and_decision_revalidates(self):
        from teacher.migrate import MigrationReport
        rep = MigrationReport()
        out = json.loads(self.mig.line(self.old(self.current[0]), rep))
        self.assertEqual(out["hdr"], self.current[0]["hdr"])
        self.assertEqual(out["context"]["header"], self.current[0]["context"]["header"])
        self.assertEqual(out["context"]["records"], self.current[0]["context"]["records"])
        self.assertEqual(out["decision"]["gesture"], "wait")
        self.assertEqual(out["source"]["migrated_from"], "00000000:00000000")
        self.assertEqual(out["id"], self.current[0]["id"])
        self.assertEqual((rep.migrated, rep.migrated_without_truth), (1, 0))
        LabelRecord.from_line(json.dumps(out))
        self.assertEqual(LineMeta.of(json.dumps(out, separators=(",", ":"))).hdr, self.current[0]["hdr"])

    def test_dropped_lines_are_counted_by_reason(self):
        from teacher.migrate import MigrationReport
        rep = MigrationReport()
        bad_decision = json.loads(json.dumps(self.current[1]))
        bad_decision["decision"]["gesture"] = "teleport"
        bad_context = json.loads(json.dumps(self.current[2]))
        bad_context["context"]["records"].append({"type": "ALIEN", "key": "x:1", "fields": {}})
        sources = [self.old(bad_decision), self.old(bad_context), "{not json", '{"format": "other"}']
        self.assertEqual([self.mig.line(s, rep) for s in sources], [None] * 4)
        reasons = " | ".join(rep.dropped)
        self.assertIn("decision refused now: unknown_gesture", reasons)
        self.assertIn("re-encoding refused", reasons)
        self.assertEqual(sum(rep.dropped.values()), 4)
        self.assertEqual(rep.written, 0)

    def test_lines_without_stored_real_ages_are_counted(self):
        from teacher.migrate import MigrationReport
        rep = MigrationReport()
        line = json.loads(json.dumps(self.current[0]))
        del line["source"]["ages"]
        self.assertIsNotNone(self.mig.line(self.old(line), rep))
        self.assertEqual(rep.migrated_without_truth, 1)

    def test_raw_answer_round_trip_of_a_stored_decision(self):
        d = {"gesture": "speak", "params": {"to": "@E1", "volume": "low"}, "speech": "(hello)",
             "writes": [{"target": "self", "variable": "anger", "value": 3.5, "verdict": "ok"},
                        {"target": "me", "variable": "x", "value": True, "verdict": "ok"}]}
        raw = json.loads(Migration.raw_answer(d))
        self.assertEqual(raw["params"], [{"name": "to", "value": "@E1"}, {"name": "volume", "value": "low"}])
        self.assertEqual([w["value"] for w in raw["writes"]], ["3.5", "true"])
        self.assertEqual(raw["speech"], "(hello)")

    def test_file_and_cli(self):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self._file_and_cli()

    def _file_and_cli(self):
        src = self.base / "mixed.jsonl"
        lines = [self.old(self.current[0]), json.dumps(self.current[1], separators=(",", ":"), ensure_ascii=False), "garbage"]
        src.write_text("\n".join(lines) + "\n")
        out = self.base / "mixed.out.jsonl"
        self.assertEqual(migrate_cli(["migrate", str(src), "--out", str(out)]), 0)
        got = [json.loads(l) for l in out.read_text().splitlines()]
        self.assertEqual([g["hdr"] for g in got], [self.current[0]["hdr"]] * 2)
        self.assertEqual(migrate_cli(["migrate", str(src), "--in-place"]), 0)
        self.assertTrue((self.base / "mixed.jsonl.pre-migration").exists())
        self.assertEqual(len(src.read_text().splitlines()), 2)
        self.assertIn("2 lines", stats(src))
        self.assertEqual(migrate_cli(["migrate", str(self.base / "absent.jsonl")]), 2)
        self.assertEqual(migrate_cli(["stats", str(src)]), 0)


if __name__ == "__main__":
    unittest.main()
