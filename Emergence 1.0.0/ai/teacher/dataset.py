"""dataset.py - the labels file (`dataset.jsonl`): one line = one valid teacher answer, ready to train the student.

    {"format": "emergence-labels-1",
     "context":  the DecisionContext in canonical JSON (tok-2 `DecisionContext.to_dict`, with its header: schema,
                 interface and layout fingerprints) - the records the teacher saw, nothing else,
     "decision": the normalised Decision (`Decision.to_dict`): gesture, params {name: value}, speech (canonical
                 S-expression or null), writes [{target, variable, value, verdict}]. Every pointer is a RECORD KEY
                 (`@E3`, `b:7`, `me`), never a slot: the slots depend on the tokenizer, the keys do not,
     "verdict":  "ok" (only valid answers are written; the governor's code per write stays in `decision.writes`),
     "source":   {"teacher": model name, "date": UTC ISO, "seed": sampler seed, "index": situation index}}

The line STARTS with a short header that a reader can parse without decoding the whole line:
    {"format":..., "hdr": "<interface 8 hex>:<layout 8 hex>", "id": "<seed>:<index>", "teacher": ..., ["synthetic": true,] ...
`hdr` lets a reader exclude (and count) the lines written for another interface or layout when it OPENS the file;
`id` ("<seed>:<index>", or "<series>:<seed>:<index>" for a line written by a long run of the generator, so that two series
never mask each other) deduplicates a situation asked twice; `synthetic: true` marks random test data (the smoke generator), which a
trainer refuses unless it is told it is only a test.

The student reads it with `student2.data.LabelDataset`, which tokenises on the fly and refuses a file written for
another interface or layout. No network, no secret, no teacher "why" text (it is not part of the state).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

FORMAT = "emergence-labels-1"
FILE_NAME = "dataset.jsonl"


class DatasetError(ValueError):
    """A line that is not a label record."""


META_END = ',"verdict":'


@dataclass
class LabelRecord:
    context: dict
    decision: dict
    verdict: str = "ok"
    source: dict = field(default_factory=dict)
    synthetic: bool = False

    @classmethod
    def build(cls, tokenizer, situation, outcome, teacher: str, now: datetime | None = None,
              synthetic: bool = False, series: str = "") -> "LabelRecord":
        """From a validated Outcome on a Situation (ai/situations). `series`: the name of the long run that asked it; it
        prefixes the id (`serie:seed:index`) so that two series never mask each other's lines."""
        if not outcome.ok:
            raise DatasetError(f"only valid answers are labels (got {outcome.code})")
        now = now or datetime.now(timezone.utc)
        source = {"teacher": teacher, "date": now.isoformat(timespec="seconds"), "seed": situation.seed,
                  "index": situation.index}
        if series:
            source["series"] = series
        return cls(context=situation.context.to_dict(tokenizer), decision=outcome.decision.to_dict(), verdict=outcome.code,
                   source=source, synthetic=synthetic)

    # ---- the short header
    @staticmethod
    def short_header(header: dict) -> str:
        return f"{str(header.get('interface', ''))[:8]}:{str(header.get('layout', ''))[:8]}"

    @property
    def hdr(self) -> str:
        return self.short_header(self.context.get("header", {}))

    @property
    def id(self) -> str:
        base = f"{self.source.get('seed')}:{self.source.get('index')}"
        return f"{self.source['series']}:{base}" if self.source.get("series") else base

    @property
    def teacher(self) -> str:
        return str(self.source.get("teacher", ""))

    def to_line(self) -> str:
        d = {"format": FORMAT, "hdr": self.hdr, "id": self.id, "teacher": self.teacher}
        if self.synthetic:
            d["synthetic"] = True
        d.update(verdict=self.verdict, source=self.source, decision=self.decision, context=self.context)
        return json.dumps(d, separators=(",", ":"), ensure_ascii=False)

    @classmethod
    def from_line(cls, line: str) -> "LabelRecord":
        try:
            d = json.loads(line)
        except ValueError as e:
            raise DatasetError(f"not JSON: {e}") from None
        if not isinstance(d, dict) or d.get("format") != FORMAT:
            raise DatasetError(f"not a {FORMAT} line")
        missing = {"context", "decision", "verdict", "source"} - set(d)
        if missing:
            raise DatasetError(f"missing {sorted(missing)}")
        if not isinstance(d["decision"], dict) or "gesture" not in d["decision"]:
            raise DatasetError("a decision has at least a gesture")
        return cls(d["context"], d["decision"], d["verdict"], d["source"], bool(d.get("synthetic", False)))


@dataclass(frozen=True)
class LineMeta:
    """What a reader learns from the START of a line, without decoding the context."""
    hdr: str
    id: str
    teacher: str
    synthetic: bool

    @property
    def smoke(self) -> bool:
        return self.synthetic or self.teacher.startswith("smoke")

    @classmethod
    def of(cls, line: str) -> "LineMeta":
        cut = line.find(META_END)
        if cut > 0:
            try:
                d = json.loads(line[:cut] + "}")
                if d.get("format") == FORMAT and "hdr" in d and "id" in d:
                    return cls(d["hdr"], d["id"], d.get("teacher", ""), bool(d.get("synthetic", False)))
            except ValueError:
                pass
        try:
            d = json.loads(line)                              # no compact header at the start: decode the line
        except ValueError as e:
            raise DatasetError(f"not JSON: {e}") from None
        r = LabelRecord.from_line(line)
        return cls(str(d.get("hdr") or r.hdr), str(d.get("id") or r.id), str(d.get("teacher") or r.teacher),
                   bool(d.get("synthetic", r.synthetic)))


class DatasetFile:
    """Append-only JSONL file of label records."""

    def __init__(self, path: Path | str):
        self.path = Path(path)

    def append(self, record: LabelRecord) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(record.to_line() + "\n")

    def __iter__(self) -> Iterator[LabelRecord]:
        with open(self.path, encoding="utf-8") as f:
            for n, line in enumerate(f, 1):
                if line.strip():
                    try:
                        yield LabelRecord.from_line(line)
                    except DatasetError as e:
                        raise DatasetError(f"{self.path}:{n}: {e}") from None


if __name__ == "__main__":                       # python3 -m teacher.dataset migrate FILE | stats FILE
    import sys as _sys
    from teacher.migrate import cli
    _sys.exit(cli(_sys.argv[1:]))
