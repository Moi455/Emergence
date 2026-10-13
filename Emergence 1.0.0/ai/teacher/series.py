"""series.py - the files of one series (a long run), outside the repository.

    ~/.local/share/emergence/dataset/<series>/
        dataset.jsonl    the labels (teacher/dataset.py): one valid decision per line, append only
        journal.jsonl    one line per request: model, tokens, latency, raw reply (key-free), verdict per decision
        state.json       where to resume: seed, next index, counters (atomic write)
        quota.json       the quota counters of each model (quota.py)
        generator.log    what the process says (the launcher script redirects its output there)

    SeriesDirectory   paths, refuses the repository
    AppendFile        append-only text file that survives a crash (a half-written last line is cut at open)
    SeriesState       the resume point
    SituationCursor   (seed, index) pairs that only advance: a situation is never asked twice
"""
from __future__ import annotations

import fcntl
import json
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .toolkit import ROOT

DEFAULT_BASE = Path.home() / ".local" / "share" / "emergence" / "dataset"
SEED_BLOCK = 1_000_000          # situations per seed: then the next seed starts at 0
STATE_SCHEMA = 1


class SeriesDirectory:
    def __init__(self, name: str, base: Path | str | None = None):
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", name):
            raise SystemExit(f"series name {name!r}: letters, digits, . _ - only")
        self.name = name
        self.path = (Path(base) if base else DEFAULT_BASE).expanduser().resolve() / name
        if self.path == ROOT or ROOT in self.path.parents:
            raise SystemExit(f"refusing to write inside the repository ({self.path}): pass --out outside {ROOT}")
        self.path.mkdir(parents=True, exist_ok=True)

    def file(self, name: str) -> Path:
        return self.path / name

    dataset = property(lambda self: self.file("dataset.jsonl"))
    journal = property(lambda self: self.file("journal.jsonl"))
    state = property(lambda self: self.file("state.json"))
    quota = property(lambda self: self.file("quota.json"))
    log = property(lambda self: self.file("generator.log"))


class SeriesLock:
    """One generator per series: an exclusive flock on <series>/.lock. The descriptor is close-on-exec, so an os.execv
    (restart on a code change) releases it and the new image takes it again; the kernel frees it if the process dies."""

    def __init__(self, series: SeriesDirectory):
        self.path = series.file(".lock")
        self.fd: int | None = None

    def acquire(self, wait: float = 0.0, sleep=None) -> bool:
        """True if taken. `wait` > 0 retries for that many seconds (right after a restart by execv)."""
        import time
        sleep = sleep or time.sleep
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o644)
        waited = 0.0
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if waited >= wait:
                    os.close(fd)
                    return False
                sleep(0.2)
                waited += 0.2
        os.ftruncate(fd, 0)
        os.write(fd, f"{os.getpid()}\n".encode())
        self.fd = fd
        return True

    def release(self) -> None:
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    @classmethod
    def held(cls, directory: Path) -> bool:
        """Is another process holding the lock of that series folder? (without keeping it)"""
        p = Path(directory) / ".lock"
        if not p.exists():
            return False
        fd = os.open(p, os.O_RDWR | os.O_CLOEXEC)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(fd, fcntl.LOCK_UN)
            return False
        except OSError:
            return True
        finally:
            os.close(fd)


class AppendFile:
    """Append-only text file. `open()` cuts a last line that has no newline (a crash in the middle of a write): it is
    never valid, and the next line would be glued to it."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def recover(self) -> int:
        """Returns the number of bytes cut."""
        if not self.path.exists() or self.path.stat().st_size == 0:
            return 0
        with open(self.path, "rb+") as f:
            size = f.seek(0, os.SEEK_END)
            f.seek(size - 1)
            if f.read(1) == b"\n":
                return 0
            pos, step = size, 65536
            cut = 0
            while pos > 0:
                start = max(0, pos - step)
                f.seek(start)
                chunk = f.read(pos - start)
                i = chunk.rfind(b"\n")
                if i >= 0:
                    cut = start + i + 1
                    break
                pos = start
            f.truncate(cut)
            return size - cut

    def append(self, lines: list[str]) -> None:
        if not lines:
            return
        data = "".join(l.rstrip("\n") + "\n" for l in lines).encode("utf-8")
        before = self.path.stat().st_size if self.path.exists() else 0
        try:
            with open(self.path, "ab") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
        except OSError:                                  # disk full...: no half-written block stays in the file
            try:
                with open(self.path, "rb+") as f:
                    f.truncate(before)
            except OSError:
                pass
            raise

    def last_line(self) -> str:
        if not self.path.exists() or self.path.stat().st_size == 0:
            return ""
        with open(self.path, "rb") as f:
            size = f.seek(0, os.SEEK_END)
            back = min(size, 1 << 20)
            f.seek(size - back)
            lines = f.read(back).decode("utf-8", "replace").splitlines()
        return lines[-1] if lines else ""

    def last_matching(self, keep) -> str:
        """The last line of the tail (1 MB) for which keep(line) is true, else ''."""
        if not self.path.exists() or self.path.stat().st_size == 0:
            return ""
        with open(self.path, "rb") as f:
            size = f.seek(0, os.SEEK_END)
            back = min(size, 1 << 20)
            f.seek(size - back)
            lines = f.read(back).decode("utf-8", "replace").splitlines()
        return next((l for l in reversed(lines) if keep(l)), "")

    def count_lines(self) -> int:
        if not self.path.exists():
            return 0
        with open(self.path, "rb") as f:
            return sum(chunk.count(b"\n") for chunk in iter(lambda: f.read(1 << 20), b""))


@dataclass
class SeriesState:
    name: str
    seed: int = 0
    next_index: int = 0
    k: int = 6
    started_at: float = 0.0
    requests: int = 0
    batches: int = 0
    valid: int = 0
    refused: int = 0
    restarts: int = 0
    sample_errors: int = 0
    updated: str = ""
    schema: int = STATE_SCHEMA
    extra: dict = field(default_factory=dict)

    @classmethod
    def load_or_new(cls, path: Path, name: str, seed: int, k: int, now: float) -> "SeriesState":
        if Path(path).exists():
            try:
                d = json.loads(Path(path).read_text(encoding="utf-8"))
                known = {f for f in cls.__dataclass_fields__}
                st = cls(**{k_: v for k_, v in d.items() if k_ in known})
                return st
            except (ValueError, TypeError):
                pass
        return cls(name=name, seed=seed, k=k, started_at=now)

    def save(self, path: Path) -> None:
        self.updated = datetime.now(timezone.utc).isoformat(timespec="seconds")
        tmp = Path(path).with_name(Path(path).name + ".tmp")
        tmp.write_text(json.dumps(asdict(self), indent=1), encoding="utf-8")
        os.replace(tmp, path)


class SituationCursor:
    """Hands out (seed, index) pairs in order. Indexes are never reused, even after a crash or a restart with a new
    catalogue; after SEED_BLOCK situations the seed moves on and the index restarts at 0."""

    def __init__(self, state: SeriesState):
        self.state = state
        self.seed, self.index = state.seed, state.next_index

    def take(self, k: int) -> list[tuple[int, int]]:
        out = []
        for _ in range(k):
            out.append((self.seed, self.index))
            self.index += 1
            if self.index >= SEED_BLOCK:
                self.seed, self.index = self.seed + 1, 0
        return out

    def commit(self) -> None:
        self.state.seed, self.state.next_index = self.seed, self.index

    def rewind(self) -> None:
        self.seed, self.index = self.state.seed, self.state.next_index
