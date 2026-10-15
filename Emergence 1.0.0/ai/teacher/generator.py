"""generator.py - the continuous generator of training labels (a series that can run for a week).

    cd ai
    python3 -m teacher.generator --name serie1                    DRY: renders one batch, writes it, no network
    python3 -m teacher.generator --name serie1 --call             REAL calls, without end (the free quota, Monsieur's agreement 13 oct.)
    python3 -m teacher.generator --name serie1 --call --days 7    ... for seven days
    python3 -m teacher.generator --name serie1 --status           what it did, per Pacific day and per model
    python3 -m teacher.generator --selfcheck                      loads everything and samples; exit 0 if the code is sound

Per round: K situations (default 6) -> one request (structured JSON, batch.py) -> every decision validated by the
SAME validator and governor as the pilot -> the refused ones sent back once with the reason -> the valid ones appended to
dataset.jsonl. The model is chosen by the QuotaDesk (quota.py): the one that can answer first, at the exact pace of its
RPM/TPM, switching when a daily limit is reached, sleeping to the Pacific midnight when all are spent.

Crash or SIGTERM: the files are written in the order dataset -> journal -> state, each fsynced, and a half-written last line
is cut at start, so the run resumes exactly: an index is never asked twice. When the code of the teacher, the situations,
the tokenizer or the catalogue changes, the process checks that the new code works (--selfcheck in a child process) and
re-executes itself, so the new data uses the new vocabulary; the old lines are brought up to date by
`python3 -m teacher.dataset migrate`. Everything is written under ~/.local/share/emergence/dataset/<series>/.
The key is read by the existing loader and never printed, logged or written.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from .batch import BatchInstructions, BatchPrompt, BatchSchema, GroupedRound, RoundResult
from .caller import FatalError, LaneBusy, ModelCaller, Pacer
from .dataset import LabelRecord
from .gemini import ApiKeyError, ApiKeyLoader, GeminiClient, Redactor
from .phrasebook import DEFAULT_COUNT, PhraseBook
from .quota import DEFAULT_CONFIG, PacificDay, QuotaConfig, QuotaDesk
from .render import SituationRenderer
from .schema import DecisionSchema
from .series import DEFAULT_BASE, AppendFile, SeriesDirectory, SeriesLock, SeriesState, SituationCursor
from .toolkit import ROOT, Toolkit
from .validate import AnswerValidator, Outcome

AI_DIR = ROOT / "ai"
EXIT_FATAL = 3
EXIT_LOCKED = 2
REEXEC = "EMERGENCE_REEXEC"
UNUSABLE_ASIDE = 3600.0         # a model whose batch gave no valid decision at all (even repaired) is left alone for an hour
PERMANENT = ("not found", "HTTP 400", "HTTP 401", "HTTP 403")      # exhausted_why of a model that is out for good
MAX_SAMPLE_ERRORS = 50
LANE_PAUSE = 120.0              # a small-batch model that could not answer when its turn came waits this long before the next try
SITUATION_CHARS = 6500          # first guess of the rendered size of one situation (the real mean is learned from the rounds)
MAX_CRASHES = 5                 # rounds in a row that raised an unexpected exception: stop


# ---------------------------------------------------------------------------------------------------- code watch
class CodeFingerprint:
    """The files whose change must restart the generator: its own code and what it reads (situations, tokenizer, the
    catalogue and its generated interface). `signature()` is cheap (stat); `digest()` reads the contents."""

    def __init__(self, root: Path = ROOT):
        self.root = root

    def files(self) -> list[Path]:
        r, out = self.root, []
        for pattern in ("ai/teacher/*.py", "ai/teacher/*.toml", "ai/situations/*.py", "ai/tok2/*.py", "catalogue/tools/*.py",
                        "catalogue/data/*.toml", "catalogue/generated/*.json"):
            out += sorted(r.glob(pattern))
        return out

    def signature(self) -> tuple:
        sig = []
        for p in self.files():
            try:
                st = p.stat()
                sig.append((str(p), st.st_size, st.st_mtime_ns))
            except OSError:
                sig.append((str(p), -1, 0))
        return tuple(sig)

    def digest(self) -> str:
        h = hashlib.sha256()
        for p in self.files():
            try:
                h.update(p.name.encode() + b"\0" + p.read_bytes())
            except OSError:
                h.update(b"?")
        return h.hexdigest()[:16]


class RestartWatcher:
    """True when the code has changed AND has stayed unchanged for `quiet` seconds (an editor is not finished). The cheap
    signature (stat) is looked at every time; the contents are read only when the signature moved."""

    def __init__(self, fingerprint: CodeFingerprint, clock=time.time, quiet: float = 30.0):
        self.fp, self.clock, self.quiet = fingerprint, clock, quiet
        self.baseline = fingerprint.digest()
        self._base_sig = self._sig = fingerprint.signature()
        self._since = clock()

    def changed(self) -> bool:
        now = self.clock()
        sig = self.fp.signature()
        if sig != self._sig:
            self._sig, self._since = sig, now
        if sig == self._base_sig or now - self._since < self.quiet:
            return False
        if self.fp.digest() != self.baseline:
            return True
        self._base_sig = sig                          # touched, same contents: nothing to do
        return False

    def accept_current(self) -> None:
        """The change was looked at and is not usable now: do not ask again until the files change once more."""
        self.baseline, self._base_sig = self.fp.digest(), self.fp.signature()


# ---------------------------------------------------------------------------------------------------- log
class Log:
    def __init__(self, redactor: Redactor | None = None, stream=None):
        self.redactor, self.stream = redactor or Redactor(), stream or sys.stdout

    def __call__(self, message: str) -> None:
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
        print(f"{stamp} {self.redactor.clean(message)}", file=self.stream, flush=True)


# ---------------------------------------------------------------------------------------------------- the generator
class Generator:
    def __init__(self, series: SeriesDirectory, client, quota_config: QuotaConfig, k: int = 6, seed: int = 0,
                 days: float | None = None, max_requests: int | None = None, temperature: float = 0.9, repair: bool = True,
                 phrases: int = DEFAULT_COUNT, tk: Toolkit | None = None, pacer: Pacer | None = None, log=None,
                 watcher: RestartWatcher | None = None, restarter=None, argv: list[str] | None = None,
                 sampler_factory=None, selfcheck=None, planner: bool = False, max_items: bool = True):
        self.series, self.k, self.days, self.argv = series, k, days, list(argv or [])
        self.log = log or Log(getattr(client, "redactor", None))
        self.tk = tk or Toolkit()
        self.pacer = pacer or Pacer()
        self.watcher, self.restarter = watcher, restarter or self._execv
        self.selfcheck = selfcheck or self._selfcheck_subprocess
        self.dataset, self.journal = AppendFile(series.dataset), AppendFile(series.journal)
        self.recovered = {"dataset": self.dataset.recover(), "journal": self.journal.recover()}
        now = self.pacer.clock()
        self.state = SeriesState.load_or_new(series.state, series.name, seed, k, now)
        self.cursor = SituationCursor(self.state)
        self._floor_cursor()
        self.desk = QuotaDesk(quota_config, series.quota, series.journal, now)
        if self.desk.rebuilt:
            self.log(f"quota.json was damaged: today's counters of {', '.join(self.desk.rebuilt)} rebuilt from journal.jsonl")
        self.caller = ModelCaller(client, self.desk, self.pacer, self.log, self._event, temperature, 8192, max_requests)
        self.planner = planner                          # T36: the "human planner" instructions and the trace of thoughts (off by default)
        self.schema_single = DecisionSchema(self.tk, "full", thoughts=planner, max_items=max_items)
        self._check_mode()
        self.phrasebook = PhraseBook(self.tk, phrases)
        self.instructions = BatchInstructions(self.tk, self.phrasebook, thoughts=planner)
        self.renderer = SituationRenderer(self.tk)
        self.round = GroupedRound(self.instructions, BatchSchema(self.schema_single), BatchPrompt(self.renderer),
                                  AnswerValidator(self.tk), self.caller, self.caller.can_call, repair,
                                  on_reply=self._hold)
        self._sampler_factory = sampler_factory or self._default_sampler
        self._samplers: dict = {}
        self._unusable_models: set = set()
        self._lane_until: dict = {}                    # small-batch model -> epoch second before which it is not tried again
        self._situation_chars = SITUATION_CHARS        # running estimate of the rendered size of one situation
        self.holding = False            # a reply is held, not yet written: no restart now (it would be asked again)
        if watcher is not None and self.pacer.idle is None:
            self.pacer.idle = self.check_restart

    # ---- mode of the series (default | planner): never mixed without an alert
    def _check_mode(self) -> None:
        want = "planner" if self.planner else "default"
        have = self.state.extra.get("mode", "default")
        untouched = self.state.requests == 0 and self.state.next_index == 0 and not self.dataset.count_lines()
        if have != want and ('mode' in self.state.extra or not untouched):
            raise FatalError(f"series {self.series.name} is a '{have}' series; this run is '{want}' (use another --name)")
        if want == "planner" and self.state.extra.get("mode") != "planner":
            self.state.extra["mode"] = "planner"         # a default series never gets the key: its state.json stays as it was
            self.state.save(self.series.state)

    # ---- resume
    def _floor_cursor(self) -> None:
        """The cursor never goes back: it is at least past the last journal record and the last dataset line (a crash
        between two of the three files must not make the same situation be asked twice)."""
        floors = []
        try:
            last = json.loads(self.journal.last_matching(lambda l: '"cursor"' in l) or "{}")
            if isinstance(last.get("cursor"), list) and len(last["cursor"]) == 2:
                floors.append((int(last["cursor"][0]), int(last["cursor"][1])))
        except (ValueError, TypeError):
            pass
        try:
            parts = str(json.loads(self.dataset.last_line() or "{}").get("id", "")).split(":")     # [serie:]seed:index
            ours = len(parts) == 2 or (len(parts) == 3 and parts[0] == self.series.name)
            if ours and parts[-2].lstrip("-").isdigit() and parts[-1].isdigit():
                floors.append((int(parts[-2]), int(parts[-1]) + 1))
        except ValueError:
            pass
        here = (self.cursor.seed, self.cursor.index)
        best = max([here, *floors])
        if best != here:
            self.log(f"resume: the files are ahead of state.json ({here} -> {best})")
            self.cursor.seed, self.cursor.index = best
            self.cursor.commit()

    # ---- situations
    def _default_sampler(self, seed: int):
        from situations.sampler import SituationSampler
        return SituationSampler(seed)

    def sampler(self, seed: int):
        if seed not in self._samplers:
            self._samplers = {seed: self._sampler_factory(seed)}          # only the current seed is kept
        return self._samplers[seed]

    def build_situations(self, pairs: list[tuple[int, int]]) -> list:
        out = []
        for seed, index in pairs:
            try:
                out.append(self.sampler(seed).sample(index))
            except Exception as e:      # noqa: BLE001  (a situation the sampler cannot make is skipped, never asked)
                self.state.sample_errors += 1
                self._event({"kind": "sample_error", "seed": seed, "index": index, "error": f"{type(e).__name__}: {e}"[:300]})
                if self.state.sample_errors > MAX_SAMPLE_ERRORS:
                    raise FatalError(f"{self.state.sample_errors} situations could not be sampled: {e}") from e
        return out

    # ---- journal events
    def _event(self, e: dict) -> None:
        now = self.pacer.clock()
        self.journal.append([json.dumps({"t": _iso(now), "ts": round(now, 1), "pday": PacificDay.key(now), **e},
                                        ensure_ascii=False, separators=(",", ":"))])

    # ---- the loop
    def finished(self) -> str:
        if self.days is not None and self.pacer.clock() - self.state.started_at >= self.days * 86400:
            return f"{self.days:g} day(s) done"
        if not self.caller.can_call():
            return "request cap reached"
        return ""

    def run(self) -> int:
        self.log(f"series {self.series.name} in {self.series.path}; K={self.k}; cursor seed {self.cursor.seed} index {self.cursor.index}; "
                 f"{self.dataset.count_lines()} labels already; instructions {self.instructions.text().count(chr(10))} lines "
                 f"({len(self.instructions.text())} characters); models {', '.join(self.desk.order)}")
        if any(self.recovered.values()):
            self.log(f"recovered a half-written last line: {self.recovered}")
        code, crashes = 0, 0
        try:
            while not self.pacer.stopped:
                why = self.finished()
                if why:
                    self.log(f"stop: {why}")
                    break
                self.check_restart()
                try:
                    if not self.one_round():
                        break
                    crashes = 0
                except FatalError:
                    raise
                except Exception as e:      # noqa: BLE001  (a bug must not loop on the quota: a few tries, then stop for a human)
                    crashes += 1
                    self.holding = False
                    self.cursor.rewind()
                    self.log(f"ERROR in a round ({crashes}/{MAX_CRASHES}): {type(e).__name__}: {e}")
                    self._event({"kind": "crash", "error": f"{type(e).__name__}: {e}"[:300]})
                    if crashes >= MAX_CRASHES:
                        raise FatalError(f"{crashes} rounds in a row failed with an exception ({type(e).__name__}: {e})") from e
                    self.pacer.sleep(30.0)
        except FatalError as e:
            self.log(f"FATAL: {e}")
            code = EXIT_FATAL
        finally:
            self.state.save(self.series.state)
            self.desk.save()
        if self.pacer.stopped and not code:
            self.log("stopped on request; state saved")
        return code

    def small_lane(self) -> str | None:
        """A model that only takes small batches (quota.toml `max_k`) and may answer right now: this round is for it. The
        size of its prompt is estimated from the last rounds (characters per situation)."""
        now = self.pacer.clock()
        fixed = len(self.instructions.text()) + 1500
        best, best_sent = None, float("inf")
        for name in self.desk.order:
            spec = self.desk.spec(name)
            book = self.desk.books[name]
            if not spec.max_k or self._lane_until.get(name, 0.0) > now:
                continue
            chars = fixed + spec.max_k * self._situation_chars
            if book.available_at(now, book.estimate_input(chars)) <= now + 0.25 and book.last_sent < best_sent:
                best, best_sent = name, book.last_sent
        return best

    def one_round(self) -> bool:
        lane = self.small_lane()
        k = min(self.k, self.desk.spec(lane).max_k) if lane else self.k
        pairs = self.cursor.take(k)
        sits = self.build_situations(pairs)
        if not sits:
            self.cursor.commit()
            return True
        t0 = time.monotonic()
        self.caller.only = lane
        try:
            res = self.round.run(sits)
            if res is None:                               # stopped or capped before an answer: nothing is consumed
                self.cursor.rewind()
                return False
            self.commit(res, time.monotonic() - t0)
        except LaneBusy:                                  # the small-batch model could not answer: nothing was held, try the normal way
            self.cursor.rewind()
            self._lane_until[lane] = self.pacer.clock() + LANE_PAUSE
            return True
        finally:
            self.holding = False
            self.caller.only = None
        return True

    def _hold(self) -> None:
        self.holding = True

    # ---- write a finished round
    def commit(self, res: RoundResult, seconds: float) -> None:
        lines, valid = [], 0
        for s in res.slots:
            if not s.ok:
                continue
            sit = s.situation
            try:                                          # a decision the codec cannot write is one refused, not a stop
                rec = LabelRecord.build(self.sampler(sit.seed).tokenizer, sit, s.final, s.model, series=self.series.name)
                rec.source["ages"] = {k: round(float(p.age), 2) for k, p in (getattr(sit, "people", None) or {}).items()}
                if s.repaired:
                    rec.source["repaired"] = True
                line = rec.to_line()
            except Exception as e:      # noqa: BLE001
                s.final = Outcome(None, "encode_error", f"{type(e).__name__}: {e}"[:160])
                self._event({"kind": "encode_error", "id": s.label, "seed": sit.seed, "index": sit.index,
                             "error": f"{type(e).__name__}: {e}"[:300]})
                continue
            lines.append(line)
            valid += 1
        first = res.requests[0]
        if first.labels:
            seen = (first.prompt_chars - len(self.instructions.text())) / len(first.labels)
            if seen > 0:
                self._situation_chars = 0.8 * self._situation_chars + 0.2 * seen
        self.dataset.append(lines)
        self.cursor.commit()                              # the labels are on disk: these situations are never asked again
        for rq in res.requests:
            self.journal.append([json.dumps(self._journal_record(rq, res), ensure_ascii=False, separators=(",", ":"))])
        st = self.state
        st.requests += len(res.requests)
        st.batches += 1
        st.valid += valid
        st.refused += len(res.slots) - valid
        st.save(self.series.state)
        self.desk.save()
        usage = [rq.result.usage for rq in res.requests]
        tin, tout = sum(u.get("promptTokenCount", 0) for u in usage), sum(u.get("candidatesTokenCount", 0) for u in usage)
        rep = sum(1 for s in res.slots if s.repaired and s.ok)
        self.log(f"[{st.batches}] {'+'.join(rq.model for rq in res.requests)} {len(res.slots)} asked, {valid} valid"
                 f"{f' ({rep} after repair)' if rep else ''}, tokens in {tin} out {tout}, {seconds:.1f} s; "
                 f"refused: {_codes(res) or 'none'}; total {st.valid} labels, next index {self.cursor.seed}:{self.cursor.index}")
        if res.unusable:
            self.after_unusable(res)
        else:
            self._unusable_models.clear()

    def after_unusable(self, res: RoundResult) -> None:
        """No valid decision at all, even after the repair: the models that answered are set aside for an hour (the
        others go on). Fatal only when EVERY model has failed that way (or is out for good): the prompt is then broken."""
        now = self.pacer.clock()
        for rq in res.requests:
            self.desk.books[rq.model].exhaust(now, "unusable", until=now + UNUSABLE_ASIDE)
            self._unusable_models.add(rq.model)
            self.log(f"{rq.model}: no usable decision, set aside for {UNUSABLE_ASIDE / 3600:g} h")
        self.desk.save()
        left = [n for n in self.desk.order
                if n not in self._unusable_models and self.desk.books[n].exhausted_why not in PERMANENT]
        if not left:
            raise FatalError(f"every model failed to give a usable decision ({', '.join(sorted(self._unusable_models))}): "
                             "stopped to protect the quota")

    def _journal_record(self, rq, res: RoundResult) -> dict:
        now = self.pacer.clock()
        first = rq.kind == "batch"
        results = []
        for s in res.slots:
            if rq.kind == "repair" and not s.repaired:
                continue
            o = s.first if first else s.second
            if o is None:
                continue
            gesture = o.decision.gesture if o.ok else _gesture(s.raw_item)
            results.append({"id": s.label, "index": s.situation.index, "code": o.code, "gesture": gesture,
                            "family": o.decision.family if o.ok else self._family(gesture),
                            "detail": o.detail[:160] if not o.ok else ""})
            if o.ok and o.decision.thoughts:                 # T36: only planner lines carry the key; default journals are unchanged
                results[-1]["traced"] = len(o.decision.thoughts)
        r = rq.result
        return {"t": _iso(now), "ts": round(now, 1), "pday": PacificDay.key(now), "kind": rq.kind, "model": rq.model,
                "http": r.status, "finish": r.finish, "latency_s": round(r.latency, 2), "usage": _usage(r.usage),
                "prompt_chars": rq.prompt_chars, "asked": len(rq.labels), "answered": len(rq.answer.items),
                "problem": rq.answer.problem, "duplicates": rq.answer.duplicates, "unknown_ids": rq.answer.unknown,
                "fp": self._fp(), "cursor": [self.cursor.seed, self.cursor.index], "results": results,
                "raw": Redactor(getattr(self.caller.client, "key", "")).clean(r.text)}

    def _family(self, gesture: str) -> str:
        g = self.tk.spec.gestures.get(gesture)
        return g.family if g else ""

    def _fp(self) -> str:
        if not hasattr(self, "_fp_cache"):
            self._fp_cache = hashlib.sha256((self.instructions.text() + json.dumps(self.round.schema.response_schema(1), sort_keys=True))
                                            .encode()).hexdigest()[:12]
        return self._fp_cache

    # ---- restart on change
    def check_restart(self) -> None:
        if self.watcher is None or self.holding or not self.watcher.changed():
            return
        self.log("the code or the catalogue changed: checking that the new version works")
        if not self.selfcheck():
            self.log("the new version does NOT pass the self-check; keeping the running one (next change will be tried again)")
            self.watcher.accept_current()
            return
        self.state.restarts += 1
        self.state.save(self.series.state)
        self.desk.save()
        self.log("restarting on the new version")
        self.restarter(self.argv)

    def _selfcheck_subprocess(self) -> bool:
        try:
            p = subprocess.run([sys.executable, "-m", "teacher.generator", "--selfcheck"], cwd=AI_DIR, capture_output=True,
                               text=True, timeout=600)
        except (OSError, subprocess.TimeoutExpired) as e:
            self.log(f"self-check could not run: {e}")
            return False
        if p.returncode != 0:
            self.log("self-check output: " + (p.stdout + p.stderr)[-600:].replace("\n", " | "))
        return p.returncode == 0

    def _execv(self, argv: list[str]) -> None:
        os.chdir(AI_DIR)
        os.environ[REEXEC] = "1"             # the new image waits a few seconds for the lock instead of giving up
        os.execv(sys.executable, [sys.executable, "-m", "teacher.generator", *argv])


# ---------------------------------------------------------------------------------------------------- helpers
def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds")


def _usage(u: dict) -> dict:
    return {"prompt": u.get("promptTokenCount", 0), "output": u.get("candidatesTokenCount", 0),
            "thoughts": u.get("thoughtsTokenCount", 0), "cached": u.get("cachedContentTokenCount", 0),
            "total": u.get("totalTokenCount", 0)}


def _gesture(item) -> str:
    g = item.get("gesture") if isinstance(item, dict) else ""
    return g if isinstance(g, str) else ""


def _codes(res: RoundResult) -> str:
    from collections import Counter
    c = Counter(s.final.code for s in res.slots if s.final is not None and not s.final.ok)
    return ", ".join(f"{k}x{v}" for k, v in c.most_common())


# ---------------------------------------------------------------------------------------------------- command line
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="teacher.generator", description=__doc__.split("\n\n")[0])
    ap.add_argument("--name", default="serie1", help="name of the series (its folder)")
    ap.add_argument("--out", type=Path, default=None, help=f"base folder (default {DEFAULT_BASE}); outside the repository")
    ap.add_argument("--call", action="store_true", help="REAL network calls (default: dry run, no network)")
    ap.add_argument("--k", type=int, default=6, help="situations per request")
    ap.add_argument("--seed", type=int, default=0, help="first seed of a NEW series (a resumed series keeps its own)")
    ap.add_argument("--days", type=float, default=None, help="stop after this many days since the series began (default: no end)")
    ap.add_argument("--max-requests", type=int, default=None, help="hard cap of requests in this process (repairs included)")
    ap.add_argument("--models", default="", help="comma-separated models, in order of preference (default: quota.toml)")
    ap.add_argument("--quota-file", type=Path, default=DEFAULT_CONFIG, help="known free-tier limits")
    ap.add_argument("--temperature", type=float, default=0.9)
    ap.add_argument("--phrases", type=int, default=DEFAULT_COUNT, help="valid sentences listed in the instructions")
    ap.add_argument("--planner", action="store_true",
                    help="T36 'human planner' mode: a short written trace of thoughts before each act (use a SEPARATE series, "
                         "e.g. --name serie_planner; default off: the prompt of the running series is unchanged)")
    ap.add_argument("--no-max-items", action="store_true",
                    help="planner mode: leave maxItems off the thoughts and steps arrays (if the API answers 400 'invalid argument')")
    ap.add_argument("--no-repair", action="store_true", help="no repair request for the refused decisions")
    ap.add_argument("--no-restart", action="store_true", help="do not restart when the code or the catalogue changes")
    ap.add_argument("--key-file", type=Path, default=None, help="key file (default ~/.config/emergence/API_Keys)")
    ap.add_argument("--status", action="store_true", help="print what the series did, and exit")
    ap.add_argument("--selfcheck", action="store_true", help="load everything, sample situations, exit 0 if sound")
    return ap


def selfcheck() -> int:
    from situations.sampler import SituationSampler
    tk = Toolkit()
    pb = PhraseBook(tk)
    phrases = pb.select()
    text = BatchInstructions(tk, pb).text()
    sampler, renderer = SituationSampler(0), SituationRenderer(tk)
    n = 0
    for i in range(4):
        n += len(renderer.render(sampler.sample(i)))
    QuotaConfig.load()
    problems = []
    if len(BatchInstructions(tk, pb, thoughts=True).text()) < 5000:        # T36 planner mode loads too (not run)
        problems.append("the planner instructions are suspiciously short")
    if len(phrases) < 10:
        problems.append(f"only {len(phrases)} valid sentences in the phrasebook")
    if len(text) < 5000:
        problems.append("the instructions are suspiciously short")
    print(("selfcheck FAILED: " + "; ".join(problems)) if problems else
          f"selfcheck ok: {len(phrases)} sentences, instructions {len(text)} characters, 4 situations rendered ({n} characters)")
    return 1 if problems else 0


def dry_run(a, series: SeriesDirectory, qc: QuotaConfig) -> int:
    from situations.sampler import SituationSampler
    tk = Toolkit()
    pb = PhraseBook(tk, a.phrases)
    inst = BatchInstructions(tk, pb, thoughts=a.planner)
    schema = BatchSchema(DecisionSchema(tk, "full", thoughts=a.planner, max_items=not a.no_max_items))
    prompt = BatchPrompt(SituationRenderer(tk))
    sampler = SituationSampler(a.seed)
    from .batch import Slot
    slots = [Slot(l, sampler.sample(i)) for i, l in enumerate(prompt.labels(a.k))]
    user = prompt.render(slots)
    d = series.path / "dry"
    d.mkdir(exist_ok=True)
    (d / "system.txt").write_text(inst.text(), encoding="utf-8")
    (d / "batch_user.txt").write_text(user, encoding="utf-8")
    (d / "schema.gemini.json").write_text(json.dumps(schema.response_schema(a.k), indent=1), encoding="utf-8")
    est = tk.estimate_tokens
    print(f"DRY RUN (no network), written to {d}")
    print(f"instructions: {len(inst.text())} characters (about {est(inst.text())} tokens, estimate), {len(pb.select())} sentences")
    print(f"batch of {a.k}: user text {len(user)} characters (about {est(user)} tokens, estimate); "
          f"schema {len(json.dumps(schema.response_schema(a.k)))} characters")
    print(f"models: {', '.join(s.name for s in qc.models)}")
    return 0


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    a = build_parser().parse_args(argv)
    if a.selfcheck:
        return selfcheck()
    series = SeriesDirectory(a.name, a.out)
    qc = QuotaConfig.load(a.quota_file)
    if a.models:
        qc = qc.only([m.strip() for m in a.models.split(",") if m.strip()])
    if a.status:
        from .status import StatusReport
        print(StatusReport(series, qc).text())
        return 0
    if not a.call:
        return dry_run(a, series, qc)
    try:
        key = ApiKeyLoader(path=a.key_file).load()
    except ApiKeyError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    lock = SeriesLock(series)
    if not lock.acquire(wait=10.0 if os.environ.pop(REEXEC, "") else 0.0):
        print(f"error: series {series.name} is already running (lock {lock.path} is held)", file=sys.stderr)
        return EXIT_LOCKED
    client = GeminiClient(key)
    qc.install(client)                       # how to ask each model: structured JSON, or the prompt-only way
    log = Log(Redactor(key))
    watcher = None if a.no_restart else RestartWatcher(CodeFingerprint())
    gen = Generator(series, client, qc, a.k, a.seed, a.days, a.max_requests, a.temperature, not a.no_repair, a.phrases, log=log,
                    watcher=watcher, argv=argv, planner=a.planner, max_items=not a.no_max_items)
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: gen.pacer.request_stop())
    return gen.run()


if __name__ == "__main__":
    sys.exit(main())
