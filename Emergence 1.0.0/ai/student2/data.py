"""data.py - the labels file -> fixed batches for the student.

    ds = LabelDataset(["dataset.jsonl"], split="train")      # opens the file, checks every line, builds/reads the cache
    for batch in ds.loader(64, shuffle=True, epoch=0): ...

What happens at open (and why):
  * every line is checked from its short header (`hdr`, `id`, `teacher`, see teacher/dataset.py) WITHOUT decoding it:
    a line written for another interface or layout is excluded and counted; above 5 % of the file the open FAILS
    (`DatasetMismatch`): the file belongs to another catalogue state;
  * a situation asked twice (same `id` = seed:index) is kept once;
  * random test data (`synthetic` or a teacher called smoke*) is REFUSED unless `allow_smoke=True`
    (`SyntheticData`): it must never be trained on by mistake;
  * the train/validation split is a hash of (split seed, `id`), so it does not depend on the order of the lines nor
    on what else is in the file;
  * every kept line is tokenised ONCE into a cache (memory-mapped .npy files in chunks of 1024 lines, keyed by the
    fingerprints of the catalogue state and the digest of the chunk's bytes: a new catalogue state or an edited
    chunk is rebuilt, the rest is reused). A line the codec cannot turn into targets is excluded and counted
    (`stats["unusable"]`, with the reasons; above 25 % the open fails). Nothing is substituted for a bad line.

The Collator then pads a batch and builds what the model consumes with FIXED shapes and no data-dependent branch:
  cat_col / cat_id [B, n, K]   the filled word columns of each record, compacted (K a bucket of the registry bound)
  prop_* [B, R, 20]            the records that carry a proposition (R = the budget of such records), padded
  edge_dst / edge_rel [B, n, E] the pointers of each record (pointer columns and proposition slots) as graph edges
  ptr_dst [B, n, 5]            the same pointers for the message pass (position in [records | ghosts])
  seq_b / seq_s [C]            which (decision, sequence) pairs have a sentence to write (teacher forcing)
"""
from __future__ import annotations

import concurrent.futures as cf
import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import DataLoader, Dataset, Sampler

from teacher.dataset import DatasetError, LabelRecord, LineMeta
from tok2 import DecisionContext
from tok2.codecs import GHOST_BASE, GHOST_SLOTS
from tok2.errors import TokenError
from tok2.interface import InputVocabulary

from .labels import LabelError, Targets
from .runtime import Runtime
from .spec import MAX_SLOTS, SpaceError, TargetKind

CACHE_VERSION = 3   # +1: plans read from `thoughts` (labels.plan_of)
CHUNK = 1024
MAX_FOREIGN = 0.05
MAX_UNUSABLE = 0.25
EDGE_CAP = 16                    # edges kept per record: 5 pointer columns + up to 11 proposition pointers
K_BUCKETS = (12, 20, 38)         # capacities of the compact word columns (38 = every column of the registry)
ARRAYS = ("type_id", "num", "known", "cat", "cat_known", "ptr", "ptr_known", "prop_sym", "prop_arity", "prop_depth",
          "prop_slot", "prop_num")


class DatasetMismatch(ValueError):
    """The file was written for another interface or layout than the tokenizer in use (too many foreign lines)."""


class SyntheticData(ValueError):
    """The file holds random test data (smoke): training on it is refused unless the caller says it is a test."""


def ceil8(n: int) -> int:
    return (n + 7) // 8 * 8


# ----------------------------------------------------------------------------------------------- examples
@dataclass
class Example:
    """One decision: the tok-2 arrays trimmed to its n records, and its targets (int arrays)."""
    arrays: dict
    targets: dict
    slot_kind: np.ndarray             # [n] TargetKind of each record (what a write can be addressed to)
    slot_ptrkind: np.ndarray          # [n] index in POINTER_KINDS of the key (-1: the language cannot point to it)
    meta: dict = field(default_factory=dict)

    @property
    def n(self) -> int:
        return self.arrays["type_id"].shape[0]


@dataclass
class Batch:
    """Tensors of B decisions, padded to `n` records (+ `ghosts` ghost tokens). Shapes are static given (B, n, K, ghosts)."""
    arrays: dict                      # name -> tensor
    self_idx: torch.Tensor            # [B]            row of the SELF token
    ghost_used: torch.Tensor          # [B, ghosts]    which ghost tokens each decision uses
    slot_kind: torch.Tensor           # [B, n]         TargetKind of the record in each row
    slot_ptrkind: torch.Tensor        # [B, n]         pointer kind of the record's key (-1 none)
    feasible: torch.Tensor            # [B, gestures]  gestures the engine allows (all ones by default)
    targets: dict | None              # Targets field -> tensor [B, ...]
    seq_b: torch.Tensor | None = None   # [C] decision of each sentence to write (teacher forcing), padded
    seq_s: torch.Tensor | None = None   # [C] which sequence (0 speech, 1 + i = proposition of write i)
    seq_ok: torch.Tensor | None = None  # [C] real entry (False = padding)
    meta: list = field(default_factory=list)
    memory: object = None             # per-NPC memory state (the NpcMemory hook; None = stateless)
    dropped_edges: int = 0            # pointers beyond EDGE_CAP that were not turned into an edge (0 expected)

    _TENSORS = ("self_idx", "ghost_used", "slot_kind", "slot_ptrkind", "feasible", "seq_b", "seq_s", "seq_ok")

    @property
    def size(self) -> int:
        return self.self_idx.shape[0]

    @property
    def n(self) -> int:
        return self.arrays["type_id"].shape[1]

    @property
    def ghosts(self) -> int:
        return self.ghost_used.shape[1]

    def _map(self, f) -> "Batch":
        out = Batch(**{k: getattr(self, k) for k in ("meta", "memory", "dropped_edges")}, arrays={k: f(v) for k, v in self.arrays.items()},
                    targets=None if self.targets is None else {k: f(v) for k, v in self.targets.items()},
                    **{k: (None if getattr(self, k) is None else f(getattr(self, k))) for k in self._TENSORS})
        return out

    def to(self, device) -> "Batch":
        return self._map(lambda t: t.to(device, non_blocking=True))

    def pin_memory(self) -> "Batch":
        return self._map(lambda t: t.pin_memory())


# ----------------------------------------------------------------------------------------------- collate
@dataclass(frozen=True)
class BatchSpec:
    """Sizes the Collator needs (plain numbers: picklable into the loader workers)."""
    n_types: int
    cat_w: int
    ptr_w: int
    prop_len: int
    prop_rows: int
    gestures: int
    self_type: int
    n_pointer_kinds: int = len(InputVocabulary.POINTER_KINDS)

    @classmethod
    def of(cls, rt: Runtime) -> "BatchSpec":
        lay = rt.tokenizer.layout
        rows = sum(t.count for t in lay.types.values() if any(c.codec.block == "prop" for c in t.columns.values()))
        return cls(rt.space.n_types, lay.width["cat"], lay.width["ptr"], lay.prop_len, ceil8(rows), rt.space.gestures.n,
                   rt.space.self_type)


class Collator:
    """Examples -> Batch. `fixed=True` pads to the buckets (64 or 128 records, 8 or 40 ghost tokens) so that a decision
    gets the same shapes alone or in any batch (CUDA graphs, the determinism test); otherwise to the next multiple of 8."""

    def __init__(self, spec: BatchSpec, fixed: bool = False, pad_to: int | None = None, pad_ghosts: int | None = None):
        self.s, self.fixed, self.pad_to, self.pad_ghosts = spec, fixed, pad_to, pad_ghosts

    def __call__(self, examples: list[Example]) -> Batch:
        s, B = self.s, len(examples)
        n_max = max(e.n for e in examples)
        n = self.pad_to or ((64 if n_max <= 64 else 128) if self.fixed else ceil8(n_max))
        a = {k: np.zeros((B, n) + examples[0].arrays[k].shape[1:], examples[0].arrays[k].dtype) for k in ARRAYS}
        kind = np.zeros((B, n), np.int64)
        ptrkind = np.full((B, n), -1, np.int64)
        for i, e in enumerate(examples):
            for k in ARRAYS:
                a[k][i, :e.n] = e.arrays[k]
            kind[i, :e.n], ptrkind[i, :e.n] = e.slot_kind, e.slot_ptrkind
        tid = a["type_id"]
        self_idx = np.argmax(tid == s.self_type, axis=1)
        out = {k: a[k] for k in ("type_id", "num", "known", "cat_known", "ptr_known")}
        out.update(self._words(a))
        out.update(self._propositions(a, n))
        ghost_used, ptr_dst, edge_dst, edge_rel, dropped = self._graph(a, n)
        out.update(ptr_dst=ptr_dst, edge_dst=edge_dst, edge_rel=edge_rel)
        feasible = np.ones((B, s.gestures), bool)
        targets = None
        seq = (None, None, None)
        if examples[0].targets is not None:
            targets = {k: torch.from_numpy(np.stack([e.targets[k] for e in examples]).astype(np.int64)) for k in examples[0].targets}
            seq = self._sequences(targets["seq_len"].numpy())
        t = torch.from_numpy
        return Batch({k: t(np.ascontiguousarray(v)) for k, v in out.items()}, t(self_idx), t(ghost_used), t(kind), t(ptrkind), t(feasible),
                     targets, *(None if x is None else t(x) for x in seq), [e.meta for e in examples], None, dropped)

    # ---- the word columns, compacted: no [B, n, 38, d] tensor, no data-dependent shape inside the model
    def _words(self, a: dict) -> dict:
        mask = (a["cat"] > 0) & (a["cat_known"] > 0)
        need = int(mask.sum(-1).max()) if mask.size else 0
        K = next((k for k in K_BUCKETS if k >= need), self.s.cat_w)
        order = np.argsort(~mask, axis=-1, kind="stable")[..., :K]
        taken = np.take_along_axis(mask, order, -1)
        return {"cat_col": order.astype(np.int16), "cat_id": (np.take_along_axis(a["cat"], order, -1) * taken).astype(np.int16)}

    # ---- the records that carry a proposition, gathered (fixed capacity R)
    def _propositions(self, a: dict, n: int) -> dict:
        R = self.s.prop_rows
        has = a["prop_sym"][..., 0] > 0
        if int(has.sum(-1).max()) > R:
            raise ValueError(f"more than {R} records carry a proposition: the budget of the registry is exceeded")
        order = np.argsort(~has, axis=1, kind="stable")[:, :R]
        ok = np.take_along_axis(has, order, 1)
        out = {"prop_row_ok": ok, "prop_row": np.where(ok, order, n + np.arange(R)[None]).astype(np.int16)}
        for k in ("prop_sym", "prop_arity", "prop_depth", "prop_slot", "prop_num"):
            g = np.take_along_axis(a[k], order[..., None], 1)
            out[k] = g * ok[..., None]
        return out

    # ---- pointers as edges
    def _graph(self, a: dict, n: int):
        s = self.s
        B = a["type_id"].shape[0]

        def ext(slots):                                  # tok-2 slot -> position in [records | ghosts], -1 none
            x = slots.astype(np.int64)
            ghost = n + np.minimum(x - GHOST_BASE, GHOST_SLOTS)
            return np.where(x == 0, -1, np.where(x <= MAX_SLOTS, x - 1, ghost)).astype(np.int16)

        g = np.concatenate([a["ptr"], a["prop_slot"]], -1).astype(np.int64)
        used = np.zeros((B, ceil8(GHOST_SLOTS + 1)), bool)
        hit = g >= GHOST_BASE
        bi = np.broadcast_to(np.arange(B)[:, None, None], g.shape)
        used[bi[hit], np.minimum(g[hit] - GHOST_BASE, GHOST_SLOTS)] = True
        top = int(np.nonzero(used.any(0))[0].max()) + 1 if used.any() else 0
        width = self.pad_ghosts if self.pad_ghosts is not None else (8 if top <= 8 else 40) if self.fixed else ceil8(top)
        ghost_used = used[:, :width]
        ptr_dst = ext(a["ptr"])
        prop_dst = ext(a["prop_slot"])
        dst = np.concatenate([ptr_dst, prop_dst], -1)
        tid = a["type_id"].astype(np.int64)[..., None]
        rel = np.concatenate([tid * s.ptr_w + np.arange(s.ptr_w), np.broadcast_to(s.n_types * s.ptr_w + tid, prop_dst.shape)], -1)
        valid = dst >= 0
        order = np.argsort(~valid, axis=-1, kind="stable")[..., :EDGE_CAP]
        ok = np.take_along_axis(valid, order, -1)
        edge_dst = np.where(ok, np.take_along_axis(dst, order, -1), -1).astype(np.int16)
        edge_rel = np.where(ok, np.take_along_axis(rel, order, -1), 0).astype(np.int16)
        dropped = int(np.maximum(valid.sum(-1) - EDGE_CAP, 0).sum())
        return ghost_used, ptr_dst, edge_dst, edge_rel, dropped

    # ---- which sentences are to be written (teacher forcing): host side, padded to a multiple of 8
    @staticmethod
    def _sequences(seq_len: np.ndarray):
        b, si = np.nonzero(seq_len >= 0)
        C = max(8, ceil8(len(b)))
        pad = lambda x, dt: np.concatenate([x, np.zeros(C - len(x), dt)])          # noqa: E731
        return pad(b, np.int64), pad(si, np.int64), np.arange(C) < len(b)


# ----------------------------------------------------------------------------------------------- the cache
class ChunkBuilder:
    """Tokenises and encodes the lines of one chunk into memory-mapped arrays. Runs in a worker process."""

    _rt: Runtime | None = None

    @classmethod
    def runtime(cls) -> Runtime:
        if cls._rt is None:
            cls._rt = Runtime.build()
        return cls._rt

    @classmethod
    def build(cls, task: dict) -> dict:
        rt = cls.runtime()
        tok, codec = rt.tokenizer, rt.codec
        out_dir = Path(task["out"])
        if out_dir.exists():
            return {"dir": str(out_dir), "built": False}
        lines = task["lines"]
        C = len(lines)
        status = np.zeros(C, np.uint8)
        reasons: list[str] = [""] * C
        digest = np.zeros(C, np.uint32)
        rounding = np.zeros(C, np.float32)
        rows_per = np.zeros(C, np.int64)
        per: dict[str, list] = {k: [] for k in ARRAYS}
        kinds, ptrkinds = [], []
        targets: dict[str, list] = {}
        template = Targets.empty(rt.space)
        blank = template_arrays(tok)
        for name in Targets.names():
            targets[name] = []
        for i, line in enumerate(lines):
            try:
                rec = LabelRecord.from_line(line)
                ctx = DecisionContext.loads(json.dumps(rec.context), tok)
                enc = tok.encode(ctx)
                t = codec.encode(rec.decision, enc, ctx.records)
            except (LabelError, SpaceError, TokenError, DatasetError) as e:
                status[i], reasons[i] = 1, f"{type(e).__name__}: {str(e)[:100]}"
                t = template
                enc = None
            for name in Targets.names():
                targets[name].append(np.asarray(getattr(t, name)).astype(np.int16))
            if enc is None:
                for k in ARRAYS:
                    per[k].append(np.zeros((0,) + getattr(blank, k).shape[1:], getattr(blank, k).dtype))
                kinds.append(np.zeros(0, np.uint8))
                ptrkinds.append(np.zeros(0, np.int8))
                continue
            n = enc.n
            rows_per[i], digest[i], rounding[i] = n, enc.digest(), codec.rounding
            for k in ARRAYS:
                per[k].append(np.asarray(getattr(enc, k))[:n])
            kinds.append(np.array([TargetKind.of_key(k) for k in enc.keys], np.uint8))
            ptrkinds.append(np.array([cls._pointer_kind(tok, k) for k in enc.keys], np.int8))
        tmp = Path(tempfile.mkdtemp(dir=out_dir.parent, prefix=".tmp-"))
        for k in ARRAYS:
            np.save(tmp / f"{k}.npy", np.concatenate(per[k]))
        np.save(tmp / "slot_kind.npy", np.concatenate(kinds))
        np.save(tmp / "slot_ptrkind.npy", np.concatenate(ptrkinds))
        np.save(tmp / "row_start.npy", np.concatenate([[0], np.cumsum(rows_per)]))
        for name, lst in targets.items():
            np.save(tmp / f"t_{name}.npy", np.stack(lst))
        np.save(tmp / "status.npy", status)
        np.save(tmp / "digest.npy", digest)
        np.save(tmp / "rounding.npy", rounding)
        (tmp / "reasons.json").write_text(json.dumps(reasons))
        try:
            tmp.rename(out_dir)
        except OSError:                                    # another process built it first
            shutil.rmtree(tmp, ignore_errors=True)
        return {"dir": str(out_dir), "built": True}

    @staticmethod
    def _pointer_kind(tok, key: str) -> int:
        try:
            return InputVocabulary.POINTER_KINDS.index(tok.vocab.pointer_kind(key))
        except Exception:                                  # noqa: BLE001  (me, h:, q:, p:... cannot be pointed to)
            return -1


def template_arrays(tok):
    from tok2 import Encoded
    return Encoded(tok.layout)


class Chunk:
    """A built chunk, memory-mapped."""

    def __init__(self, path: Path):
        self.path = path
        ld = lambda name: np.load(path / f"{name}.npy", mmap_mode="r")             # noqa: E731
        self.status, self.row_start = np.asarray(ld("status")), np.asarray(ld("row_start"))
        self.digest, self.rounding = np.asarray(ld("digest")), np.asarray(ld("rounding"))
        self.reasons = json.loads((path / "reasons.json").read_text())
        self.arrays = {k: ld(k) for k in ARRAYS}
        self.slot_kind, self.slot_ptrkind = ld("slot_kind"), ld("slot_ptrkind")
        self.targets = {name: ld(f"t_{name}") for name in Targets.names()}

    def example(self, j: int) -> Example:
        a, b = int(self.row_start[j]), int(self.row_start[j + 1])
        return Example({k: np.array(v[a:b]) for k, v in self.arrays.items()},
                       {k: np.array(v[j]) for k, v in self.targets.items()}, np.array(self.slot_kind[a:b]),
                       np.array(self.slot_ptrkind[a:b]), {"digest": int(self.digest[j])})


def cache_root() -> Path:
    return Path(os.environ.get("EMERGENCE_CACHE", Path.home() / ".cache" / "emergence")) / "student2"


def state_key(rt: Runtime) -> str:
    fp = rt.fingerprints()
    return hashlib.sha1(json.dumps([CACHE_VERSION, fp.interface, fp.layout, fp.registry, fp.vocabulary, fp.output]).encode()).hexdigest()[:12]


# ----------------------------------------------------------------------------------------------- the dataset
@dataclass
class Entry:
    file: int
    line: int                         # line number in its file (0-based, blank lines excluded)
    offset: int
    meta: LineMeta


class LabelDataset(Dataset):
    """Reads one or several `dataset.jsonl`; see the module docstring for what is checked and cached.

    split: None (all), "train" or "val" (a hash of (split_seed, id) decides; `val_fraction` of the situations are val)."""

    def __init__(self, paths, split: str | None = None, val_fraction: float = 0.05, split_seed: int = 0,
                 runtime: Runtime | None = None, allow_smoke: bool = False, cache_dir: Path | str | None = None,
                 keep_context: bool = False, workers: int | None = None, max_foreign: float = MAX_FOREIGN,
                 max_unusable: float = MAX_UNUSABLE):
        if split not in (None, "train", "val"):
            raise ValueError("split is None, 'train' or 'val'")
        self.paths = [Path(p) for p in ([paths] if isinstance(paths, (str, Path)) else paths)]
        self._rt, self.keep_context = runtime, keep_context
        self.cache_dir = Path(cache_dir) if cache_dir else cache_root()
        self.stats = {"lines": 0, "foreign": 0, "duplicates": 0, "unusable": 0, "unusable_reasons": {}, "kept": 0, "smoke_lines": 0}
        self._chunks: dict[str, Chunk] = {}
        raw = self._scan()
        kept = self._filter(raw, max_foreign, allow_smoke)
        if split:
            kept = [e for e in kept if (self._split_hash(e.meta.id, split_seed) < val_fraction) == (split == "val")]
        self.items = self._build_cache(kept, workers, max_unusable)
        self.stats["kept"] = len(self.items)

    # ---- the runtime is not pickled: each process builds its own when it needs one
    @property
    def runtime(self) -> Runtime:
        if self._rt is None:
            self._rt = Runtime.build()
        return self._rt

    def __getstate__(self):
        d = dict(self.__dict__)
        d["_rt"], d["_chunks"] = None, {}
        return d

    # ---- opening the file
    def _scan(self) -> list[Entry]:
        entries = []
        for f, path in enumerate(self.paths):
            n = 0
            with open(path, "rb") as fh:
                offset = 0
                for line in fh:
                    if line.strip():
                        try:
                            meta = LineMeta.of(line.decode("utf-8"))
                        except (DatasetError, UnicodeDecodeError):
                            meta = LineMeta("?", f"?:{f}:{n}", "", False)
                        entries.append(Entry(f, n, offset, meta))
                        n += 1
                    offset += len(line)
        self.stats["lines"] = len(entries)
        return entries

    def _filter(self, raw: list[Entry], max_foreign: float, allow_smoke: bool) -> list[Entry]:
        expected = LabelRecord.short_header(self.runtime.tokenizer.header())
        seen, kept = set(), []
        for e in raw:
            if e.meta.hdr != expected:
                self.stats["foreign"] += 1
            elif e.meta.id in seen:
                self.stats["duplicates"] += 1
            else:
                seen.add(e.meta.id)
                kept.append(e)
        if raw and self.stats["foreign"] / len(raw) > max_foreign:
            raise DatasetMismatch(f"{self.stats['foreign']} of {len(raw)} lines were written for another interface or layout "
                                  f"(expected {expected}): the file belongs to another catalogue state; re-run the teacher")
        self.stats["smoke_lines"] = sum(1 for e in kept if e.meta.smoke)
        if self.stats["smoke_lines"] and not allow_smoke:
            raise SyntheticData(f"{self.stats['smoke_lines']} lines are random test data (smoke): refused. "
                                "Pass --smoke-test (or allow_smoke=True) if this is only a test of the chain")
        return kept

    @staticmethod
    def _split_hash(id_: str, seed: int) -> float:
        base = id_.split("#", 1)[0]                        # T11b: the steps of one replayed mind (`<id>#r0`, `#r1`, `#a`) stay on the same side
        h = hashlib.blake2b(f"{seed}|{base}".encode(), digest_size=8).digest()
        return int.from_bytes(h, "little") / 2**64

    # ---- the cache
    def _read_chunk_lines(self, f: int, c: int) -> list[str]:
        out, k = [], 0
        with open(self.paths[f], "rb") as fh:
            for line in fh:
                if line.strip():
                    if c * CHUNK <= k < (c + 1) * CHUNK:
                        out.append(line.decode("utf-8"))
                    k += 1
                    if k >= (c + 1) * CHUNK:
                        break
        return out

    def _chunk_dir(self, f: int, c: int, lines: list[str]) -> Path:
        digest = hashlib.sha1("".join(lines).encode()).hexdigest()[:16]
        return self.cache_dir / state_key(self.runtime) / f"c{digest}"

    def _build_cache(self, kept: list[Entry], workers: int | None, max_unusable: float) -> list[tuple[Path, int]]:
        need: dict[tuple[int, int], list[str]] = {}
        for e in kept:
            need.setdefault((e.file, e.line // CHUNK), [])
        tasks, dirs = [], {}
        root = self.cache_dir / state_key(self.runtime)
        root.mkdir(parents=True, exist_ok=True)
        for (f, c) in sorted(need):
            lines = self._read_chunk_lines(f, c)
            d = self._chunk_dir(f, c, lines)
            dirs[(f, c)] = d
            if not d.exists():
                tasks.append({"lines": lines, "out": str(d)})
        if tasks:
            workers = min(len(tasks), workers if workers is not None else max(1, (os.cpu_count() or 2) // 2))
            if workers <= 1:
                for t in tasks:
                    ChunkBuilder.build(t)
            else:
                with cf.ProcessPoolExecutor(workers) as ex:
                    list(ex.map(ChunkBuilder.build, tasks))
        items, reasons = [], {}
        for e in kept:
            d = dirs[(e.file, e.line // CHUNK)]
            ch = self._chunk(d)
            j = e.line % CHUNK
            if ch.status[j] == 0:
                items.append((d, j))
            else:
                self.stats["unusable"] += 1
                reasons[ch.reasons[j]] = reasons.get(ch.reasons[j], 0) + 1
        self.stats["unusable_reasons"] = dict(sorted(reasons.items(), key=lambda kv: -kv[1])[:8])
        if kept and self.stats["unusable"] / len(kept) > max_unusable:
            raise LabelError(f"{self.stats['unusable']} of {len(kept)} lines cannot be turned into targets: {self.stats['unusable_reasons']}")
        self.stats["rounding_over_5pct"] = sum(1 for d, j in items if self._chunk(d).rounding[j] > 0.05)
        self._by_item = [(e.file, e.line, e.offset) for e in kept if self._chunk(dirs[(e.file, e.line // CHUNK)]).status[e.line % CHUNK] == 0]
        return items

    def _chunk(self, d: Path) -> Chunk:
        ch = self._chunks.get(str(d))
        if ch is None:
            ch = self._chunks[str(d)] = Chunk(d)
        return ch

    # ---- access
    def __len__(self) -> int:
        return len(self.items)

    def audit(self) -> dict:
        """What the open found: lines, foreign, duplicates, unusable (and why), the examples whose quantities/counts are
        rounded by more than 5 %, the random test lines."""
        return dict(self.stats)

    def __getitem__(self, i: int) -> Example:
        d, j = self.items[i]
        ex = self._chunk(d).example(j)
        ex.meta["index"] = i
        if self.keep_context:                              # evaluation: the records are needed to decode a decision
            f, _, offset = self._by_item[i]
            with open(self.paths[f], "rb") as fh:
                fh.seek(offset)
                rec = LabelRecord.from_line(fh.readline().decode("utf-8"))
            ctx = DecisionContext.loads(json.dumps(rec.context), self.runtime.tokenizer)
            ex.meta.update(enc=self.runtime.tokenizer.encode(ctx), records=ctx.records, source=rec.source)
        return ex

    def record(self, i: int) -> LabelRecord:
        f, _, offset = self._by_item[i]
        with open(self.paths[f], "rb") as fh:
            fh.seek(offset)
            return LabelRecord.from_line(fh.readline().decode("utf-8"))

    def example(self, i: int) -> Example:
        return self[i]

    def collator(self, fixed: bool = False, pad_to: int | None = None, pad_ghosts: int | None = None) -> Collator:
        return Collator(BatchSpec.of(self.runtime), fixed, pad_to, pad_ghosts)

    def loader(self, batch_size: int, shuffle: bool = False, num_workers: int = 0, drop_last: bool = False, seed: int = 0,
               epoch: int = 0, skip_batches: int = 0, fixed: bool = False, pin_memory: bool | None = None) -> DataLoader:
        sampler = EpochSampler(len(self), seed, epoch, shuffle, skip_batches * batch_size)
        return DataLoader(self, batch_size=batch_size, sampler=sampler, num_workers=num_workers, drop_last=drop_last,
                          collate_fn=self.collator(fixed), persistent_workers=False, prefetch_factor=4 if num_workers else None,
                          pin_memory=torch.cuda.is_available() if pin_memory is None else pin_memory,
                          pin_memory_device="cuda" if (torch.cuda.is_available() if pin_memory is None else pin_memory) else "")


class EpochSampler(Sampler):
    """The order of an epoch is a function of (seed, epoch) only, so a run can resume in the middle of an epoch."""

    def __init__(self, n: int, seed: int, epoch: int, shuffle: bool, skip: int = 0):
        self.n, self.seed, self.epoch, self.shuffle, self.skip = n, seed, epoch, shuffle, skip

    def __iter__(self):
        if self.shuffle:
            g = torch.Generator().manual_seed(self.seed * 1_000_003 + self.epoch)
            order = torch.randperm(self.n, generator=g).tolist()
        else:
            order = list(range(self.n))
        return iter(order[self.skip:])

    def __len__(self) -> int:
        return max(0, self.n - self.skip)
