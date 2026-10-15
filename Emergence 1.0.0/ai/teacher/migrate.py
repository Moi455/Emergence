"""migrate.py - bring old label lines up to date with the current catalogue and tokenizer.

    cd ai
    python3 -m teacher.dataset migrate FILE [--out OUT | --in-place] [--limit N]
    python3 -m teacher.dataset stats FILE

A week of data must stay usable when the catalogue grows. A line written for another interface or layout (its `hdr`) is:
  1. its context re-read (records are the same JSON) and RE-ENCODED with the current tokenizer: if the tokenizer no longer
     accepts it (a field or a type removed...), the line is dropped;
  2. its decision REVALIDATED on that context: the stored answer is turned back into a raw answer and goes through the same
     AnswerValidator and governor as a live answer (words, pointers, bounds, hard rule D10). A decision that is refused now is
     dropped. The rewritten decision is the one the current validator returns (a write may be clipped differently);
  3. rewritten with the new header (the context is dumped again by the current tokenizer).
A line already at the current header is kept as it is. Dropped lines are counted by reason, never silently.

Truth: the generator stores the real ages of the people of the scene in `source.ages` (for this check only; the model
never reads them). A line without it (older files) is revalidated with unknown real ages, which the governor treats as
possible minors: stricter than the first time, never looser.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

from tok2 import DecisionContext, Record, Tokenizer

from .dataset import LabelRecord, LineMeta
from .toolkit import Toolkit
from .validate import AnswerValidator, TruthSource


class AgeTruth(TruthSource):
    def __init__(self, ages: dict):
        self.ages = ages

    def real_age(self, key):
        v = self.ages.get(key)
        return float(v) if isinstance(v, (int, float)) else None


@dataclass
class MigrationReport:
    read: int = 0
    kept_current: int = 0
    migrated: int = 0
    migrated_without_truth: int = 0
    dropped: Counter = field(default_factory=Counter)

    @property
    def written(self) -> int:
        return self.kept_current + self.migrated

    def text(self) -> str:
        lines = [f"read {self.read} lines: {self.kept_current} already current, {self.migrated} migrated "
                 f"({self.migrated_without_truth} without stored real ages), {sum(self.dropped.values())} dropped"]
        for why, n in self.dropped.most_common():
            lines.append(f"  dropped {n:>6}  {why}")
        return "\n".join(lines)


class Migration:
    def __init__(self, tk: Toolkit | None = None):
        self.tk = tk or Toolkit()
        self.tokenizer = Tokenizer(self.tk.interface, grammar=self.tk.vocab)
        self.validator = AnswerValidator(self.tk, truth_factory=lambda s: AgeTruth(s.ages))

    @property
    def header(self) -> str:
        return LabelRecord.short_header(self.tokenizer.header())

    # ---- one line
    def line(self, text: str, report: MigrationReport) -> str | None:
        report.read += 1
        try:
            meta = LineMeta.of(text)
            d = json.loads(text)
            rec = LabelRecord.from_line(text)
        except Exception as e:      # noqa: BLE001
            report.dropped[f"unreadable line ({type(e).__name__})"] += 1
            return None
        if meta.hdr == self.header and d.get("context", {}).get("header") == self.tokenizer.header():
            report.kept_current += 1
            return text.rstrip("\n")
        try:
            ctx = DecisionContext([Record.from_dict(r) for r in rec.context["records"]], rec.context.get("known_keys"))
            self.tokenizer.encode(ctx)
            new_context = ctx.to_dict(self.tokenizer)
        except Exception as e:      # noqa: BLE001
            report.dropped[f"re-encoding refused: {type(e).__name__}: {str(e)[:90]}"] += 1
            return None
        ages = rec.source.get("ages") if isinstance(rec.source.get("ages"), dict) else {}
        outcome = self.validator.validate(self.raw_answer(rec.decision), SimpleNamespace(context=ctx, ages=ages, scene=None))
        if not outcome.ok:
            report.dropped[f"decision refused now: {outcome.code}"] += 1
            return None
        source = dict(rec.source)
        source["migrated_from"] = rec.hdr
        migrated = LabelRecord(new_context, outcome.decision.to_dict(), outcome.code, source, rec.synthetic)
        report.migrated += 1
        report.migrated_without_truth += not ages
        return migrated.to_line()

    @staticmethod
    def raw_answer(decision: dict) -> str:
        """The stored (normalised) decision back as the raw JSON answer a teacher gives."""
        def text(v) -> str:
            if isinstance(v, bool):
                return "true" if v else "false"
            if isinstance(v, (int, float)):
                return format(float(v), ".10g")
            return str(v)
        raw = {"gesture": decision.get("gesture", ""),
               "params": [{"name": k, "value": text(v)} for k, v in (decision.get("params") or {}).items()],
               "speech": decision.get("speech") or "",
               "writes": [{"target": w["target"], "variable": w["variable"], "value": text(w["value"])}
                          for w in decision.get("writes", [])]}
        for name in ("plan", "stop", "thoughts"):               # T11 / T36: kept, so a planner line is revalidated whole (and not stripped)
            if name in decision:
                raw[name] = decision[name]
        return json.dumps(raw, ensure_ascii=False)

    # ---- a file
    def file(self, src: Path, dst: Path, limit: int | None = None) -> MigrationReport:
        report = MigrationReport()
        tmp = dst.with_name(dst.name + ".tmp")
        with open(src, encoding="utf-8") as f, open(tmp, "w", encoding="utf-8") as out:
            for n, line in enumerate(f):
                if limit is not None and n >= limit:
                    break
                if not line.strip():
                    continue
                new = self.line(line, report)
                if new is not None:
                    out.write(new + "\n")
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp, dst)
        return report


def generator_running(folder: Path) -> str:
    """Why the folder's file must not be rewritten now ('' if it may): a generator holds its lock, or generator.pid is alive."""
    from .series import SeriesLock
    if SeriesLock.held(folder):
        return f"a generator holds the lock of {folder}"
    pidfile = folder / "generator.pid"
    try:
        pid = int(pidfile.read_text().strip())
        os.kill(pid, 0)
        cmd = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode("utf-8", "replace")
    except (OSError, ValueError):
        return ""
    return f"generator.pid says process {pid} is alive ({cmd.strip()[:80]})" if "teacher.generator" in cmd else ""


def stats(path: Path) -> str:
    counts, other = Counter(), 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                counts[LineMeta.of(line).hdr] += 1
            except Exception:   # noqa: BLE001
                other += 1
    return "\n".join([f"{path}: {sum(counts.values())} lines" + (f", {other} unreadable" if other else "")]
                     + [f"  interface:layout {h}  {n}" for h, n in counts.most_common()])


def cli(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="teacher.dataset", description="tools for dataset.jsonl files")
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("migrate", help="bring old lines up to date with the current catalogue")
    m.add_argument("file", type=Path)
    m.add_argument("--out", type=Path, default=None, help="output file (default: FILE.migrated.jsonl)")
    m.add_argument("--in-place", action="store_true", help="replace FILE (the original is kept as FILE.pre-migration)")
    m.add_argument("--limit", type=int, default=None, help="only the first N lines (to try)")
    s = sub.add_parser("stats", help="count the lines per interface:layout header")
    s.add_argument("file", type=Path)
    a = ap.parse_args(argv)
    if a.cmd == "stats":
        print(stats(a.file))
        return 0
    if not a.file.exists():
        print(f"error: {a.file} does not exist", file=sys.stderr)
        return 2
    if a.in_place and a.out:
        print("error: --in-place and --out are exclusive", file=sys.stderr)
        return 2
    if a.in_place and a.limit is not None:
        print("error: --limit would cut the file: it cannot be used with --in-place (use --out)", file=sys.stderr)
        return 2
    if a.in_place:
        why = generator_running(a.file.resolve().parent)
        if why:
            print(f"error: --in-place refused, {why}. Stop the generator first (scripts/run_generator.sh stop NAME), "
                  "or write to another file with --out.", file=sys.stderr)
            return 2
    mig = Migration()
    dst = a.out or a.file.with_name(a.file.name + ".migrated.jsonl") if not a.in_place else a.file.with_name(a.file.name + ".migrating")
    rep = mig.file(a.file, dst, a.limit)
    print(rep.text())
    if a.in_place:
        backup = a.file.with_name(a.file.name + ".pre-migration")
        n = 1
        while backup.exists():
            backup = a.file.with_name(f"{a.file.name}.pre-migration{n}")
            n += 1
        os.replace(a.file, backup)
        os.replace(dst, a.file)
        print(f"{a.file} rewritten ({rep.written} lines at header {mig.header}); the original is {backup}")
    else:
        print(f"written {rep.written} lines at header {mig.header} to {dst}")
    return 0
