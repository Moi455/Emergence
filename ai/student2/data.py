"""data.py - the labels file -> fixed batches for the student.

    ds = LabelDataset(["dataset.jsonl"], split="train")     # reads the lines, tokenises ON THE FLY (tok-2)
    loader = ds.loader(batch_size=64, shuffle=True)         # DataLoader with the collate below
    for batch in loader: batch.to("cuda"); ...

A line is `teacher.dataset.LabelRecord` (context with its fingerprint header, decision by record KEY). One example =
the tok-2 arrays of the context (`Encoded`) + the targets of the decision (`labels.Targets`). The collate pads a batch
to its longest decision, rounded up to a multiple of 8 (attention kernels want it), and builds what the model needs
beyond the arrays: where each SELF token is, which ghosts each decision uses, what kind of record each slot is (for the
write masks), the feasibility mask (all ones until the engine provides it).

A file written for another interface or layout is refused at open (`DatasetMismatch`): the data is a cache of the
catalogue state it was written for, never silently re-read under another one.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import DataLoader, Dataset

from teacher.dataset import DatasetError, LabelRecord
from tok2 import DecisionContext
from tok2.codecs import GHOST_BASE, GHOST_SLOTS
from tok2.errors import TokenError

from .labels import LabelCodec, LabelError, Targets
from .runtime import Runtime
from .spec import TargetKind


class DatasetMismatch(ValueError):
    """The file was written for another interface or layout than the tokenizer in use."""


def ceil8(n: int) -> int:
    return (n + 7) // 8 * 8


# ----------------------------------------------------------------------------------------------- batch
ARRAYS = ("type_id", "num", "known", "cat", "cat_known", "ptr", "ptr_known", "prop_sym", "prop_arity", "prop_depth",
          "prop_slot", "prop_num")


@dataclass
class Example:
    arrays: dict                      # the tok-2 arrays of one decision (numpy, 128 rows)
    targets: Targets | None
    keys: list                        # slot - 1 -> record key
    meta: dict = field(default_factory=dict)


@dataclass
class Batch:
    """Tensors of B decisions, padded to `n` tokens (multiple of 8). `ghosts` = how many learned ghost tokens are
    appended to the sequence (multiple of 8, 0 when nobody uses one)."""
    arrays: dict                      # name -> tensor [B, n, ...]
    self_idx: torch.Tensor            # [B]            row of the SELF token
    ghost_used: torch.Tensor          # [B, ghosts]    which ghost tokens each decision uses
    slot_kind: torch.Tensor           # [B, n]         TargetKind of the record in each row (0 = nothing can be written on it)
    feasible: torch.Tensor            # [B, gestures]  gestures the engine allows (all ones by default)
    targets: dict | None              # Targets field -> tensor [B, ...]
    meta: list = field(default_factory=list)
    memory: object = None             # per-NPC memory state (the NpcMemory hook; None = stateless)

    @property
    def size(self) -> int:
        return self.self_idx.shape[0]

    @property
    def n(self) -> int:
        return self.arrays["type_id"].shape[1]

    @property
    def ghosts(self) -> int:
        return self.ghost_used.shape[1]

    def to(self, device) -> "Batch":
        mv = lambda t: t.to(device, non_blocking=True)                                       # noqa: E731
        return Batch({k: mv(v) for k, v in self.arrays.items()}, mv(self.self_idx), mv(self.ghost_used), mv(self.slot_kind),
                     mv(self.feasible), None if self.targets is None else {k: mv(v) for k, v in self.targets.items()},
                     self.meta, self.memory)

    def pin_memory(self) -> "Batch":
        return Batch({k: v.pin_memory() for k, v in self.arrays.items()}, self.self_idx.pin_memory(),
                     self.ghost_used.pin_memory(), self.slot_kind.pin_memory(), self.feasible.pin_memory(),
                     None if self.targets is None else {k: v.pin_memory() for k, v in self.targets.items()}, self.meta,
                     self.memory)


class Collator:
    """Examples -> Batch. Needs the number of gestures (feasibility) and the SELF type id."""

    def __init__(self, n_gestures: int, self_type: int):
        self.n_gestures, self.self_type = n_gestures, self_type

    def __call__(self, examples: list[Example]) -> Batch:
        B = len(examples)
        n_max = max(len(e.keys) for e in examples)
        n = ceil8(n_max)
        arrays = {k: torch.from_numpy(np.stack([e.arrays[k][:n] for e in examples])) for k in ARRAYS}
        for k in ("type_id", "known", "cat_known", "ptr", "ptr_known", "prop_arity", "prop_depth", "prop_slot"):
            arrays[k] = arrays[k].to(torch.uint8)
        type_id = arrays["type_id"]
        self_idx = torch.argmax((type_id == self.self_type).to(torch.uint8), dim=1)
        # ghosts: pointer values 129..160 -> 0..31, 161 -> 32
        used = torch.zeros(B, ceil8(GHOST_SLOTS + 1), dtype=torch.bool)
        for a in (arrays["ptr"], arrays["prop_slot"]):
            g = a.long()
            g = torch.where(g >= GHOST_BASE, (g - GHOST_BASE).clamp(max=GHOST_SLOTS), torch.full_like(g, -1))
            hit = g >= 0
            if hit.any():
                b_idx = torch.arange(B).view(B, 1, 1).expand_as(g)
                used[b_idx[hit], g[hit]] = True
        top = int(used.any(0).nonzero().max().item()) + 1 if used.any() else 0
        ghost_used = used[:, :ceil8(top)]                                    # 0 columns when nobody has a ghost
        slot_kind = torch.zeros(B, n, dtype=torch.long)
        for i, e in enumerate(examples):
            slot_kind[i, :len(e.keys)] = torch.tensor([TargetKind.of_key(k) for k in e.keys])
        feasible = torch.ones(B, self.n_gestures, dtype=torch.bool)
        targets = None
        if examples[0].targets is not None:
            targets = {name: torch.from_numpy(np.stack([getattr(e.targets, name) for e in examples]))
                       for name in Targets.names()}
        return Batch(arrays, self_idx, ghost_used, slot_kind, feasible, targets, [e.meta for e in examples])


# ----------------------------------------------------------------------------------------------- dataset
class LabelDataset(Dataset):
    """Reads one or several `dataset.jsonl`, keeps only byte offsets in memory, tokenises each example when asked.

    split: None (all), "train" or "val" (every `val_every`-th line is validation: a fixed, seed-free rule).
    The Runtime (catalogue, tokenizer, output space) is rebuilt lazily in each worker process."""

    def __init__(self, paths, split: str | None = None, val_every: int = 20, runtime: Runtime | None = None,
                 skip_bad: bool = True, keep_context: bool = False):
        self.keep_context = keep_context
        self.paths = [Path(p) for p in ([paths] if isinstance(paths, (str, Path)) else paths)]
        self._rt = runtime
        self.skip_bad = skip_bad
        self.index: list[tuple[int, int]] = []              # (file, byte offset)
        for f, path in enumerate(self.paths):
            self._scan(f, path)
        if split in ("train", "val"):
            keep = [i for i in range(len(self.index)) if (i % val_every == 0) == (split == "val")]
            self.index = [self.index[i] for i in keep]
        elif split is not None:
            raise ValueError("split is None, 'train' or 'val'")
        self.bad: set[int] = set()

    # ---- runtime is not pickled: each process builds its own
    @property
    def runtime(self) -> Runtime:
        if self._rt is None:
            self._rt = Runtime.build()
        return self._rt

    def __getstate__(self):
        d = dict(self.__dict__)
        d["_rt"] = None
        return d

    def _scan(self, f: int, path: Path) -> None:
        first = True
        with open(path, "rb") as fh:
            offset = 0
            for line in fh:
                if line.strip():
                    if first:                                   # fail at open, not in the middle of an epoch
                        self._check_header(path, LabelRecord.from_line(line.decode("utf-8")))
                        first = False
                    self.index.append((f, offset))
                offset += len(line)

    def _check_header(self, path: Path, rec: LabelRecord) -> None:
        header = self.runtime.tokenizer.header()
        if rec.context.get("header") != header:
            raise DatasetMismatch(f"{path} was written for {rec.context.get('header')}, the tokenizer is {header}: "
                                  "re-run the teacher (or the smoke generator) on the current catalogue")

    def __len__(self) -> int:
        return len(self.index)

    def record(self, i: int) -> LabelRecord:
        f, off = self.index[i]
        with open(self.paths[f], "rb") as fh:
            fh.seek(off)
            return LabelRecord.from_line(fh.readline().decode("utf-8"))

    def example(self, i: int) -> Example:
        """Tokenise line i. Raises LabelError / TokenError / DatasetError when the line cannot be a training example."""
        rt = self.runtime
        rec = self.record(i)
        ctx = DecisionContext.loads(json.dumps(rec.context), rt.tokenizer)
        enc = rt.tokenizer.encode(ctx)
        targets = rt.codec.encode(rec.decision, enc, ctx.records)
        arrays = {k: getattr(enc, k) for k in ARRAYS}
        meta = {"index": i, "digest": enc.digest(), "source": rec.source}
        if self.keep_context:                                   # evaluation: the records are needed to decode a decision
            meta.update(enc=enc, records=ctx.records)
        return Example(arrays, targets, list(enc.keys), meta)

    def __getitem__(self, i: int) -> Example:
        n = len(self.index)
        for step in range(n):
            j = (i + step) % n
            if j in self.bad:
                continue
            try:
                return self.example(j)
            except (LabelError, TokenError, DatasetError):
                if not self.skip_bad:
                    raise
                self.bad.add(j)                                 # per process; audit() gives the exact list
        raise LabelError("no usable example in the dataset")

    def audit(self) -> dict:
        """Tokenise and encode every line once: how many cannot be used, and why (first message per kind)."""
        reasons: dict[str, int] = {}
        bad = []
        for i in range(len(self.index)):
            try:
                self.example(i)
            except (LabelError, TokenError, DatasetError) as e:
                reasons[str(e)[:90]] = reasons.get(str(e)[:90], 0) + 1
                bad.append(i)
        self.bad = set(bad)
        return {"lines": len(self.index), "unusable": len(bad), "reasons": dict(sorted(reasons.items(), key=lambda kv: -kv[1])[:10])}

    def collator(self) -> Collator:
        rt = self.runtime
        return Collator(rt.space.gestures.n, rt.space.self_type)

    def loader(self, batch_size: int, shuffle: bool = False, num_workers: int = 0, drop_last: bool = False,
               seed: int = 0) -> DataLoader:
        g = torch.Generator().manual_seed(seed)
        return DataLoader(self, batch_size=batch_size, shuffle=shuffle, num_workers=num_workers, drop_last=drop_last,
                          collate_fn=self.collator(), generator=g, persistent_workers=num_workers > 0)
