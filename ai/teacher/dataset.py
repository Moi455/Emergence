"""dataset.py - the labels file (`dataset.jsonl`): one line = one valid teacher answer, ready to train the student.

    {"format": "emergence-labels-1",
     "context":  the DecisionContext in canonical JSON (tok-2 `DecisionContext.to_dict`, with its header: schema,
                 interface and layout fingerprints) - the records the teacher saw, nothing else,
     "decision": the normalised Decision (`Decision.to_dict`): gesture, params {name: value}, speech (canonical
                 S-expression or null), writes [{target, variable, value, verdict}]. Every pointer is a RECORD KEY
                 (`@E3`, `b:7`, `me`), never a slot: the slots depend on the tokenizer, the keys do not,
     "verdict":  "ok" (only valid answers are written; the governor's code per write stays in `decision.writes`),
     "source":   {"teacher": model name, "date": UTC ISO, "seed": sampler seed, "index": situation index}}

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


@dataclass
class LabelRecord:
    context: dict
    decision: dict
    verdict: str = "ok"
    source: dict = field(default_factory=dict)

    @classmethod
    def build(cls, tokenizer, situation, outcome, teacher: str, now: datetime | None = None) -> "LabelRecord":
        """From a validated Outcome on a Situation (ai/situations)."""
        if not outcome.ok:
            raise DatasetError(f"only valid answers are labels (got {outcome.code})")
        now = now or datetime.now(timezone.utc)
        return cls(context=situation.context.to_dict(tokenizer), decision=outcome.decision.to_dict(), verdict=outcome.code,
                   source={"teacher": teacher, "date": now.isoformat(timespec="seconds"), "seed": situation.seed,
                           "index": situation.index})

    def to_line(self) -> str:
        return json.dumps({"format": FORMAT, "context": self.context, "decision": self.decision, "verdict": self.verdict,
                           "source": self.source}, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

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
        return cls(d["context"], d["decision"], d["verdict"], d["source"])


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
