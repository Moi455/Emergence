"""Round 2 of the generator review: lock, token caps, learned limits, monotone day, quota.json recovery, counted before sent,
per-slot encoding errors, safe migration, restart between batch and repair, full disk, series-prefixed ids, launcher PID check.
No network (fake client).
"""
from __future__ import annotations

import contextlib
import errno
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from teacher.caller import ModelCaller, Pacer
from teacher.dataset import LabelRecord, LineMeta
from teacher.generator import REEXEC, main as generator_main
from teacher.migrate import cli as migrate_cli, generator_running
from teacher.quota import Limits, PacificDay, QuotaBook, QuotaConfig, QuotaDesk, QuotaError, QuotaFileError
from teacher.series import AppendFile, SeriesDirectory, SeriesLock
from teacher.tests.test_generator import FakeTeacher, GeneratorCase
from teacher.tests.test_quota import FakeClock, ScriptedClient, config, ok_result, pt, spec
from teacher.toolkit import ROOT
from teacher.gemini import ApiResult

AI = ROOT / "ai"


# ------------------------------------------------------------------------------------------------ 1. the lock
class LockTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.series = SeriesDirectory("x", self.tmp.name)

    def test_second_holder_is_refused_and_the_lock_is_released_on_close(self):
        a, b = SeriesLock(self.series), SeriesLock(self.series)
        self.assertTrue(a.acquire())
        self.assertFalse(b.acquire())
        self.assertTrue(SeriesLock.held(self.series.path))
        self.assertEqual(int(a.path.read_text()), os.getpid())
        a.release()
        self.assertFalse(SeriesLock.held(self.series.path))
        self.assertTrue(b.acquire())
        b.release()

    def test_descriptor_is_close_on_exec(self):
        a = SeriesLock(self.series)
        a.acquire()
        self.assertFalse(os.get_inheritable(a.fd))
        a.release()

    def test_waiting_for_the_lock_after_a_restart(self):
        a, b = SeriesLock(self.series), SeriesLock(self.series)
        a.acquire()
        threading.Timer(0.5, a.release).start()
        self.assertTrue(b.acquire(wait=5.0))
        b.release()

    def test_the_lock_survives_an_execv(self):
        """The process holds the lock, re-executes itself (as the restart does) and takes it again; meanwhile a rival
        cannot."""
        script = Path(self.tmp.name) / "child.py"
        script.write_text(
            "import os, sys\n"
            f"sys.path.insert(0, {str(AI)!r})\n"
            "from teacher.series import SeriesDirectory, SeriesLock\n"
            f"l = SeriesLock(SeriesDirectory('x', {self.tmp.name!r}))\n"
            "if os.environ.get('STEP') == '2':\n"
            "    print('reacquired', l.acquire(wait=5.0)); sys.exit(0)\n"
            "assert l.acquire()\n"
            "os.environ['STEP'] = '2'\n"
            "os.execv(sys.executable, [sys.executable, __file__])\n")
        out = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, timeout=60)
        self.assertIn("reacquired True", out.stdout, out.stderr)

    def test_main_exits_2_when_the_series_is_already_running(self):
        lock = SeriesLock(self.series)
        lock.acquire()
        err = io.StringIO()
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "k" * 20}, clear=False), contextlib.redirect_stderr(err):
            code = generator_main(["--name", "x", "--out", self.tmp.name, "--call", "--max-requests", "1"])
        lock.release()
        self.assertEqual(code, 2)
        self.assertIn("already running", err.getvalue())

    def test_reexec_marker_is_consumed(self):
        with mock.patch.dict(os.environ, {REEXEC: "1", "GEMINI_API_KEY": "k" * 20}):
            a = SeriesLock(self.series)
            a.acquire()
            threading.Timer(0.4, a.release).start()
            err = io.StringIO()
            with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
                code = generator_main(["--name", "x", "--out", self.tmp.name, "--call", "--max-requests", "0", "--no-restart"])
            self.assertNotEqual(code, 2)                          # it waited for the lock and ran (no request: cap 0)
            self.assertNotIn(REEXEC, os.environ)


# ------------------------------------------------------------------------------------------------ 2 + 4. caps and learning
class CapsTests(unittest.TestCase):
    def test_learned_limits_only_lower_the_file(self):
        b = QuotaBook(spec("m", rpm=15, rpd=500, tpm=250000, tpd=20_000_000), margin=1.0)
        t0 = pt(2026, 10, 13, 10)
        b.on_quota_error(t0, QuotaError("minute", "tokens", 100000.0, 5.0))
        self.assertEqual(b.limits().tpm, 100000)
        b.on_quota_error(t0 + 100, QuotaError("minute", "tokens", 900000.0, 5.0))          # higher than the file: ignored
        self.assertEqual(b.limits().tpm, 100000)
        b.learn("rpd", 900.0)
        self.assertEqual(b.limits().rpd, 500)                                              # never above the file
        b.learn("rpd", 40.0)
        b.learn("rpd", 60.0)
        self.assertEqual(b.limits().rpd, 40)                                               # nor back up

    def test_nothing_is_learned_without_an_explicit_quota_value(self):
        b = QuotaBook(spec("m", rpm=15, rpd=500), margin=1.0)
        t0 = pt(2026, 10, 13, 10)
        for i in range(5):
            b.settle(b.begin(t0 + i, 1000), 1000)
        b.on_quota_error(t0 + 6, QuotaError("minute", "requests", None, 12.0))
        b.on_quota_error(t0 + 7, QuotaError("day", "tokens", None, 0.0))
        self.assertEqual(b.learned.to_dict(), {})
        self.assertEqual(b.limits(), Limits(15, 500))
        self.assertGreater(b.exhausted_until, t0)                                            # but the day-long block is applied

    def test_token_caps_from_the_file_throttle_before_any_429(self):
        b = QuotaBook(spec("m", tpm=250000, tpd=60000), margin=1.0)
        t0 = pt(2026, 10, 13, 10)
        b.settle(b.begin(t0, 24000), 24000)
        b.settle(b.begin(t0 + 5, 24000), 24000)
        self.assertEqual(b.available_at(t0 + 6, 24000), PacificDay.next_reset(t0))           # 72 000 > 60 000 a day
        self.assertEqual(b.exhausted_why, "tpd")

    def test_a_zero_limit_from_quota_value_closes_the_model_for_the_day(self):
        b = QuotaBook(spec("m", rpd=500), margin=1.0)
        t0 = pt(2026, 10, 13, 10)
        b.on_quota_error(t0, QuotaError("day", "requests", 0.0, 0.0))
        self.assertEqual(b.limits().rpd, 0)
        self.assertGreater(b.available_at(t0 + 1, 10), t0 + 3600)


# ------------------------------------------------------------------------------------------------ 5. monotone day
class MonotoneDayTests(unittest.TestCase):
    def test_a_clock_that_jumps_back_never_resets_the_counters(self):
        b = QuotaBook(spec("m", rpm=15, rpd=500), margin=1.0)
        t0 = pt(2026, 10, 13, 10)
        for i in range(5):
            b.settle(b.begin(t0 + i, 100), 100)
        b.roll(pt(2026, 10, 12, 9))                                                          # yesterday
        self.assertEqual((b.day, b.day_requests, b.day_tokens), ("2026-10-13", 5, 500))
        b.roll(pt(2026, 10, 13, 10, 5))
        self.assertEqual(b.day_requests, 5)
        b.roll(pt(2026, 10, 14, 0, 0, 10))                                                   # the real next day resets
        self.assertEqual((b.day, b.day_requests), ("2026-10-14", 0))

    def test_entries_stamped_in_the_future_do_not_freeze_the_model(self):
        b = QuotaBook(spec("m", rpm=15), margin=1.0)
        t0 = pt(2026, 10, 13, 10)
        b.begin(t0 + 7200, 100)                                                              # the clock was two hours ahead
        self.assertLess(b.available_at(t0, 100), t0 + 10)


# ------------------------------------------------------------------------------------------------ 6. quota.json
class QuotaFileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.now = pt(2026, 10, 13, 12)
        self.cfg = config(spec("a", rpm=15, rpd=500), spec("b", rpm=15, rpd=500))

    def journal(self):
        lines = []
        for i, (model, kind, tokens) in enumerate([("a", "batch", 1000), ("a", "repair", 400), ("b", "batch", 2000),
                                                   ("a", "error", 0)]):
            ts = self.now - 3000 + i * 10 if kind != "error" else self.now - 30
            lines.append(json.dumps({"ts": ts, "pday": PacificDay.key(self.now), "kind": kind, "model": model,
                                     "usage": {"prompt": tokens}}, separators=(",", ":")))
        lines.append(json.dumps({"ts": self.now - 90000, "pday": "2026-10-12", "kind": "batch", "model": "a",
                                 "usage": {"prompt": 9999}}, separators=(",", ":")))                # another day: not counted
        lines.append(json.dumps({"ts": self.now - 5, "pday": PacificDay.key(self.now), "kind": "sample_error"}, separators=(",", ":")))
        (self.dir / "journal.jsonl").write_text("\n".join(lines) + "\n")

    def test_save_is_atomic_and_fsynced(self):
        desk = QuotaDesk(self.cfg, self.dir / "quota.json", now=self.now)
        desk.books["a"].begin(self.now, 10)
        calls = []
        real = os.fsync
        with mock.patch("teacher.quota.os.fsync", side_effect=lambda fd: (calls.append(fd), real(fd))[1]):
            desk.save()
        self.assertGreaterEqual(len(calls), 2)                                               # the file, then its folder
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), ["quota.json"])         # no temp file left
        self.assertEqual(json.loads((self.dir / "quota.json").read_text())["models"]["a"]["day_requests"], 1)

    def test_corrupt_file_is_rebuilt_from_the_journal(self):
        self.journal()
        (self.dir / "quota.json").write_text('{"models": {"a": {"day_requ')
        desk = QuotaDesk(self.cfg, self.dir / "quota.json", self.dir / "journal.jsonl", self.now)
        a, b = desk.books["a"], desk.books["b"]
        self.assertEqual((a.day, a.day_requests, a.day_tokens), ("2026-10-13", 3, 1400))        # batch, repair, error of today
        self.assertEqual((b.day_requests, b.day_tokens), (1, 2000))
        self.assertEqual(desk.rebuilt, ["a", "b"])
        self.assertTrue(a.window)                                                            # the last minute is known again

    def test_badly_typed_field_rebuilds_that_book_only(self):
        self.journal()
        desk = QuotaDesk(self.cfg, self.dir / "quota.json", self.dir / "journal.jsonl", self.now)
        desk.books["a"].day_requests = 77
        desk.books["b"].day_requests = 5
        desk.save()
        doc = json.loads((self.dir / "quota.json").read_text())
        for bad in ("many", True, None, [1], {"x": 1}, float("inf")):
            doc["models"]["a"]["day_requests"] = bad
            (self.dir / "quota.json").write_text(json.dumps(doc) if bad != float("inf") else json.dumps(doc).replace("Infinity", "1e999"))
            again = QuotaDesk(self.cfg, self.dir / "quota.json", self.dir / "journal.jsonl", self.now)
            self.assertEqual(again.books["a"].day_requests, 3, bad)                          # rebuilt from the journal
            self.assertEqual(again.books["b"].day_requests, 5, bad)                          # untouched
            self.assertEqual(again.rebuilt, ["a"])

    def test_wrong_types_everywhere_raise_a_quota_file_error(self):
        b = QuotaBook(spec("m"), 1.0)
        good = b.to_dict()
        for key, bad in (("learned", {"tpm": "x"}), ("learned", []), ("window", [["a", 1]]), ("window", 5), ("day", 3),
                         ("exhausted_why", 3), ("tokens_per_char", -1), ("history", []), ("last_sent", "x"), ("blocked_until", None)):
            with self.assertRaises(QuotaFileError, msg=key):
                QuotaBook(spec("m"), 1.0).load({**good, key: bad})
        with self.assertRaises(QuotaFileError):
            QuotaBook(spec("m"), 1.0).load([1])
        untouched = QuotaBook(spec("m"), 1.0)
        untouched.day_requests = 4
        with self.assertRaises(QuotaFileError):
            untouched.load({**good, "day_requests": 9, "blocked_until": "bad"})
        self.assertEqual(untouched.day_requests, 4)                                          # nothing half-loaded

    def test_lost_file_with_a_journal_is_rebuilt_and_without_a_journal_starts_clean(self):
        self.journal()
        desk = QuotaDesk(self.cfg, self.dir / "quota.json", self.dir / "journal.jsonl", self.now)
        self.assertEqual(desk.books["a"].day_requests, 3)
        fresh = QuotaDesk(self.cfg, self.dir / "nothing.json", self.dir / "no_journal.jsonl", self.now)
        self.assertEqual((fresh.books["a"].day_requests, fresh.rebuilt), (0, []))


# ------------------------------------------------------------------------------------------------ 7. counted before sent
class CountedBeforeSentTests(unittest.TestCase):
    def test_the_request_is_on_disk_before_it_leaves(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "quota.json"
            clock = FakeClock()
            seen = []

            def handler(model, n):
                doc = json.loads(path.read_text())["models"][model]
                seen.append((doc["day_requests"], doc["day_tokens"] > 0))
                return ok_result()
            desk = QuotaDesk(config(spec("a", rpm=60, rpd=500)), path)
            caller = ModelCaller(ScriptedClient(handler), desk, Pacer(clock.now, clock.wait), log=lambda s: None)
            caller("sys", "user", {})
            caller("sys", "user", {})
            self.assertEqual(seen, [(1, True), (2, True)])

    def test_failed_network_attempts_stay_counted(self):
        clock = FakeClock()
        desk = QuotaDesk(config(spec("a", rpm=60, rpd=500)))
        caller = ModelCaller(ScriptedClient(lambda m, n: ApiResult(False, 0, error="NETWORK timed out") if n == 1 else ok_result()),
                             desk, Pacer(clock.now, clock.wait), log=lambda s: None)
        caller("sys", "user", {})
        self.assertEqual(desk.books["a"].day_requests, 2)                                    # the timed-out one counts (it may have arrived)
        self.assertEqual(desk.books["a"].day_tokens, 1000)


# ------------------------------------------------------------------------------------------------ 8 + 10. generator
class GeneratorRound2Tests(GeneratorCase):
    def test_a_slot_that_cannot_be_encoded_is_refused_and_the_round_goes_on(self):
        import teacher.generator as G
        real = LabelRecord.build
        calls = []

        def build(tok, sit, outcome, teacher, **kw):
            calls.append(sit.index)
            if sit.index == 1:
                raise ValueError("cannot encode")
            return real(tok, sit, outcome, teacher, **kw)
        gen = self.generator(FakeTeacher(), k=4, max_requests=2)
        with mock.patch.object(G.LabelRecord, "build", staticmethod(build)):
            self.assertEqual(gen.run(), 0)
        ids = [l["id"] for l in self.lines()]
        self.assertNotIn("s:0:1", ids)
        self.assertEqual(len(ids), 7)                                                        # 2 rounds of 4, one lost
        self.assertEqual(gen.state.refused, 1)
        self.assertEqual(gen.state.next_index, 8)                                            # no rewind: nothing asked twice
        self.assertTrue(any(r.get("kind") == "encode_error" and r["index"] == 1 for r in self.journal()))

    def test_ids_carry_the_series_name(self):
        self.generator(FakeTeacher(), name="alpha", k=2, max_requests=1).run()
        self.generator(FakeTeacher(), name="beta", k=2, max_requests=1).run()
        a, b = self.lines("alpha"), self.lines("beta")
        self.assertEqual([l["id"] for l in a], ["alpha:0:0", "alpha:0:1"])
        self.assertEqual({l["id"] for l in a} & {l["id"] for l in b}, set())                 # same seed and index, no clash
        self.assertEqual(LineMeta.of(json.dumps(a[0], separators=(",", ":"))).id, "alpha:0:0")
        rec = LabelRecord({"header": {}}, {"gesture": "wait"}, "ok", {"seed": 3, "index": 4})
        self.assertEqual(rec.id, "3:4")                                                      # an old line keeps its id
        self.assertEqual(LabelRecord({}, {"gesture": "wait"}, "ok", {"seed": 3, "index": 4, "series": "z"}).id, "z:3:4")

    def test_resume_reads_both_id_forms_and_ignores_another_series(self):
        self.generator(FakeTeacher(), name="alpha", k=2, max_requests=2).run()
        base = Path(self.tmp.name) / "alpha"
        (base / "state.json").unlink()
        (base / "journal.jsonl").write_text("")
        lines = (base / "dataset.jsonl").read_text().splitlines()
        self.assertEqual(self.generator(FakeTeacher(), name="alpha", k=2).cursor.index, 4)       # from "alpha:0:3"
        d = json.loads(lines[-1])
        d["id"] = "other:0:900"
        (base / "dataset.jsonl").write_text(json.dumps(d) + "\n")
        self.assertEqual(self.generator(FakeTeacher(), name="alpha", k=2).cursor.index, 0)        # not ours: ignored
        d["id"] = "0:41"                                                                          # an old line, no series
        (base / "dataset.jsonl").write_text(json.dumps(d) + "\n")
        self.assertEqual(self.generator(FakeTeacher(), name="alpha", k=2).cursor.index, 42)

    def test_cursor_is_found_in_the_journal_past_trailing_events(self):
        self.generator(FakeTeacher(), k=2, max_requests=2).run()
        base = Path(self.tmp.name) / "s"
        (base / "state.json").unlink()
        (base / "dataset.jsonl").write_text("")
        with open(base / "journal.jsonl", "a") as f:
            for _ in range(3):
                f.write(json.dumps({"kind": "error", "model": "a"}) + "\n")
        self.assertEqual(self.generator(FakeTeacher(), k=2).cursor.index, 4)

    def test_a_restart_waits_for_the_round_to_be_written(self):
        """A reply held between the batch and its repair is never lost to an execv: the restart comes after the write."""
        seen = []

        class Watch:
            def changed(self_):
                return True

            def accept_current(self_):
                pass
        t = FakeTeacher(broken={"S1"})
        qc = config(spec("a", rpm=20, rpd=100000))                                           # 3 s between requests: the repair waits
        gen = self.generator(t, k=2, qc=qc, watcher=Watch(), selfcheck=lambda: True, max_requests=2,
                             restarter=lambda argv: seen.append((len(t.requests), len(self.lines()))))
        held, orig = [], gen.check_restart
        gen.pacer.idle = lambda: (held.append(gen.holding), orig())[0]
        gen.run()
        self.assertIn(True, held)                          # the repair really waited, with the reply held, and was asked to restart
        self.assertTrue(set(seen) <= {(0, 0), (2, 2)}, seen)   # never (1, 0): between the batch and its repair
        self.assertEqual(len(self.lines()), 2)

    def test_idle_wait_before_the_first_request_may_still_restart(self):
        seen = []

        class Watch:
            def changed(self_):
                return True

            def accept_current(self_):
                pass
        qc = config(spec("a", rpm=60, rpd=1))
        self.clock.t = pt(2026, 10, 13, 22, 30)
        t = FakeTeacher()
        gen = self.generator(t, k=2, qc=qc, watcher=Watch(), selfcheck=lambda: True, restarter=lambda argv: seen.append(len(t.requests)))
        gen.caller.max_requests = 2
        gen.run()
        self.assertIn(1, seen)                             # during the long sleep (one round done, nothing held)


class AppendFileDiskFullTests(unittest.TestCase):
    def test_a_partial_write_is_cut_back_to_the_original_size(self):
        with tempfile.TemporaryDirectory() as d:
            f = AppendFile(Path(d) / "x.jsonl")
            f.append(['{"a":1}'])
            size = f.path.stat().st_size

            def full(fd):
                raise OSError(errno.ENOSPC, "No space left on device")
            with mock.patch("teacher.series.os.fsync", side_effect=full):
                with self.assertRaises(OSError):
                    f.append(['{"a":2}', '{"a":3}'])
            self.assertEqual(f.path.stat().st_size, size)
            self.assertEqual(f.last_line(), '{"a":1}')
            f.append(['{"a":4}'])
            self.assertEqual(f.count_lines(), 2)

    def test_the_first_write_on_a_missing_file_leaves_nothing_half_written(self):
        with tempfile.TemporaryDirectory() as d:
            f = AppendFile(Path(d) / "new.jsonl")
            with mock.patch("teacher.series.os.fsync", side_effect=OSError(errno.ENOSPC, "full")):
                with self.assertRaises(OSError):
                    f.append(['{"a":1}'])
            self.assertEqual(f.path.stat().st_size, 0)


# ------------------------------------------------------------------------------------------------ 9. migration safety
class MigrationSafetyTests(GeneratorCase):
    def setUp(self):
        super().setUp()
        self.generator(FakeTeacher(), k=2, max_requests=1).run()
        self.base = Path(self.tmp.name) / "s"
        self.file = self.base / "dataset.jsonl"

    def cli(self, *args):
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            code = migrate_cli(["migrate", str(self.file), *args])
        return code, err.getvalue()

    def test_in_place_is_refused_while_the_generator_holds_the_lock(self):
        lock = SeriesLock(SeriesDirectory("s", self.tmp.name))
        lock.acquire()
        before = self.file.read_text()
        code, err = self.cli("--in-place")
        lock.release()
        self.assertEqual(code, 2)
        self.assertIn("holds the lock", err)
        self.assertEqual(self.file.read_text(), before)
        self.assertFalse((self.base / "dataset.jsonl.pre-migration").exists())
        self.assertEqual(self.cli("--in-place")[0], 0)                                       # lock free: allowed

    def test_in_place_is_refused_while_generator_pid_is_alive(self):
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)", "teacher.generator", "--name", "s"])
        self.addCleanup(lambda: (proc.kill(), proc.wait()))
        (self.base / "generator.pid").write_text(str(proc.pid))
        self.assertIn("generator.pid says process", generator_running(self.base))
        self.assertEqual(self.cli("--in-place")[0], 2)
        proc.kill()
        proc.wait()
        self.assertEqual(generator_running(self.base), "")
        (self.base / "generator.pid").write_text(str(os.getpid()))                           # alive, but not a generator
        self.assertEqual(generator_running(self.base), "")

    def test_limit_is_forbidden_with_in_place(self):
        before = self.file.read_text()
        code, err = self.cli("--in-place", "--limit", "1")
        self.assertEqual(code, 2)
        self.assertIn("--limit", err)
        self.assertEqual(self.file.read_text(), before)
        self.assertEqual(self.cli("--limit", "1", "--out", str(self.base / "o.jsonl"))[0], 0)    # fine with --out


# ------------------------------------------------------------------------------------------------ launcher
@unittest.skipUnless((ROOT / "scripts" / "run_generator.sh").exists(), "no launcher")
class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name) / "tst"
        self.dir.mkdir()

    def status(self):
        out = subprocess.run(["bash", str(ROOT / "scripts" / "run_generator.sh"), "status", "tst"], capture_output=True, text=True,
                             timeout=120, env={**os.environ, "EMERGENCE_DATASET_DIR": self.tmp.name})
        return out.stdout.splitlines()[0]

    def test_pid_must_be_our_generator(self):
        (self.dir / "generator.pid").write_text(str(os.getpid()))                            # alive, but a test runner
        self.assertEqual(self.status(), "arrete")
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)", "teacher.generator", "--name", "tst"])
        self.addCleanup(lambda: (proc.kill(), proc.wait()))
        (self.dir / "generator.pid").write_text(str(proc.pid))
        self.assertTrue(self.status().startswith("en marche"))
        other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)", "teacher.generator", "--name", "other"])
        self.addCleanup(lambda: (other.kill(), other.wait()))
        (self.dir / "generator.pid").write_text(str(other.pid))                              # a generator, of another series
        self.assertEqual(self.status(), "arrete")


if __name__ == "__main__":
    unittest.main()
