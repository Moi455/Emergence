"""train.py - train the student on a labels file (`dataset.jsonl`), in float16 on the GPU.

    cd ai
    python3 -m student2.train --data /path/dataset.jsonl --size small --epochs 3 --batch 64 --out runs/student2-a
    python3 -m student2.train --data a.jsonl b.jsonl --size base --epochs 6 --resume runs/student2-a/last.pt ...
    python3 -m student2.train --data smoke.jsonl --smoke-test --size tiny ...      # a test of the chain, NOT a training

`--epochs` is the TOTAL number of epochs of the run: resuming with the same value continues where the run stopped
(the order of an epoch depends only on (seed, epoch), so even a stop in the middle of an epoch resumes at the same
batch; the learning-rate schedule keeps the total planned at the start).

Quadro RTX 3000 (Turing): no bfloat16, so autocast float16 + GradScaler (the loss is scaled, gradients unscaled before
clipping, a step with non-finite gradients is skipped). AdamW (decay on the weight matrices of Linear layers only, none
on norms, biases, embeddings and the other parameters), linear warm-up then cosine to 10 % of the peak, gradient clip at 1.
A checkpoint carries the tok-2 fingerprints (interface, layout, registry, vocabulary), the fingerprint of the output
shapes, and a snapshot of the output registry: a checkpoint made for another catalogue state is REFUSED at load
(`CheckpointMismatch`); one made for an earlier state of the SAME registry (the catalogue grew inside the capacities)
loads, the new indices starting from their initial weights.

VERSIONED checkpoints (T11). Version 3 records the schema of the output registry and the shape of every tensor. A
checkpoint of an earlier version (2: before the plan and stop heads, possibly before the T09 growth of the vocabulary)
does NOT load as is, because the shapes changed: `Checkpoint.load(path, rt, partial=True)` (CLI: `--init-from`) copies
what fits, remaps the symbol tables and lists every tensor left at its initial weights (partial.py).

THIS TRAINS ON WHATEVER FILE YOU GIVE. Random test data (smoke) is refused unless `--smoke-test` is given.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
import time
from dataclasses import asdict
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn

from .data import Batch, LabelDataset
from .labels import Targets, comparable
from .losses import LossWeights, StudentLoss
from .model import SIZES, StudentConfig, StudentModel
from .partial import PartialLoader
from .runtime import Fingerprints, Runtime
from .spec import NO_LABEL

CHECKPOINT_VERSION = 3
LEGACY_VERSIONS = (2,)             # before T11: only the partial loader reads them
SEED = 0


class CheckpointMismatch(ValueError):
    """A checkpoint made for another interface / layout / registry / output heads."""


def seed_everything(seed: int = SEED) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


# ----------------------------------------------------------------------------------------------- checkpoints
class Checkpoint:
    """Weights + config + the fingerprints they were trained under (+ the training state to resume)."""

    @staticmethod
    def save(path: Path, model: StudentModel, runtime: Runtime, extra: dict | None = None) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": CHECKPOINT_VERSION, "config": model.cfg.to_dict(), "fingerprints": asdict(runtime.fingerprints()),
                   "output_registry": runtime.space.registry.to_dict(), "registry_schema": runtime.space.registry.d["schema"],
                   "shapes": {k: list(v.shape) for k, v in model.state_dict().items()}, "model": model.state_dict(),
                   **(extra or {})}
        tmp = path.with_suffix(".tmp")
        torch.save(payload, tmp)
        tmp.replace(path)

    @staticmethod
    def check(payload: dict, runtime: Runtime, partial: bool = False) -> None:
        v = payload.get("version")
        if v != CHECKPOINT_VERSION and not (partial and v in LEGACY_VERSIONS):
            hint = " (its tensors have other shapes: load it with partial=True / --init-from)" if v in LEGACY_VERSIONS else ""
            raise CheckpointMismatch(f"checkpoint version {v!r}, expected {CHECKPOINT_VERSION}{hint}")
        theirs = Fingerprints(**payload["fingerprints"])
        diff = runtime.fingerprints().diff(theirs)
        if diff and not partial:
            raise CheckpointMismatch("this checkpoint was trained for another catalogue state (current, checkpoint): "
                                     + json.dumps(diff))
        why = runtime.space.registry.compatible(payload.get("output_registry", {}))
        if why:
            raise CheckpointMismatch("the output registry is not an extension of the checkpoint's: " + "; ".join(why))

    @classmethod
    def load(cls, path: Path, runtime: Runtime, device="cpu", memory=None, partial: bool = False) -> tuple[StudentModel, dict]:
        """partial=False: the checkpoint must fit exactly. partial=True: copy what fits (partial.py); the report is
        `payload["load_report"]`, and the fingerprints that differ `payload["fingerprint_diff"]` (the registry of the
        output indices must still be a prefix of the current one)."""
        payload = torch.load(path, map_location=device, weights_only=False)
        cls.check(payload, runtime, partial)
        model = StudentModel(StudentConfig(**payload["config"]), runtime.space, memory).to(device)
        if partial:
            payload["fingerprint_diff"] = runtime.fingerprints().diff(Fingerprints(**payload["fingerprints"]))
            payload["load_report"] = PartialLoader(model).load(payload["model"]).to_dict()
        else:
            model.load_state_dict(payload["model"])
        return model, payload


# ----------------------------------------------------------------------------------------------- optimiser
class Schedule:
    """Linear warm-up, cosine decay to `floor` x peak."""

    def __init__(self, peak: float, warmup: int, total: int, floor: float = 0.1):
        self.peak, self.warmup, self.total, self.floor = peak, warmup, max(total, warmup + 1), floor

    def __call__(self, step: int) -> float:
        if step < self.warmup:
            return self.peak * (step + 1) / self.warmup
        p = (step - self.warmup) / (self.total - self.warmup)
        return self.peak * (self.floor + (1 - self.floor) * 0.5 * (1 + math.cos(math.pi * min(1.0, p))))


def make_optimizer(model: nn.Module, lr: float, weight_decay: float = 0.05) -> torch.optim.AdamW:
    """Decay on the weight matrices of Linear layers; none on norms, embeddings, biases and free parameters (by TYPE)."""
    decay, plain = [], []
    for mod in model.modules():
        for name, p in mod.named_parameters(recurse=False):
            (decay if isinstance(mod, nn.Linear) and name == "weight" else plain).append(p)
    return torch.optim.AdamW([{"params": decay, "weight_decay": weight_decay}, {"params": plain, "weight_decay": 0.0}],
                             lr=lr, betas=(0.9, 0.95), fused=torch.cuda.is_available())


# ----------------------------------------------------------------------------------------------- the loop
class Trainer:
    def __init__(self, model: StudentModel, device: str, lr: float = 3e-4, total_steps: int = 1000, warmup: int = 100,
                 clip: float = 1.0, weights: LossWeights | None = None, amp: bool | None = None, seed: int = SEED):
        seed_everything(seed)
        self.model, self.device, self.clip = model.to(device), torch.device(device), clip
        self.amp = (self.device.type == "cuda") if amp is None else amp
        self.opt = make_optimizer(model, lr)
        self.total_steps = total_steps
        self.schedule = Schedule(lr, warmup, total_steps)
        self.scaler = torch.amp.GradScaler("cuda", enabled=self.amp)
        self.loss = StudentLoss(weights)
        self.step = 0

    def train_step(self, batch: Batch) -> dict:
        self.model.train()
        batch = batch.to(self.device)
        for g in self.opt.param_groups:
            g["lr"] = self.schedule(self.step)
        with torch.autocast(self.device.type, dtype=torch.float16, enabled=self.amp):
            out = self.model(batch)
        total, parts, acc = self.loss(out, batch)                    # logits are float32
        self.opt.zero_grad(set_to_none=True)
        self.scaler.scale(total).backward()
        self.scaler.unscale_(self.opt)
        norm = torch.nn.utils.clip_grad_norm_(self.model.parameters(), self.clip)
        self.scaler.step(self.opt)
        self.scaler.update()
        self.step += 1
        return {"loss": total.detach(), "grad_norm": norm.detach(), "lr": self.opt.param_groups[0]["lr"],
                "parts": {k: v.detach() for k, v in parts.items()}, "acc": acc}

    def loss_scale(self) -> float:
        """The GradScaler scale (a device read: call it when logging, not on every step)."""
        return float(self.scaler.get_scale()) if self.amp else 1.0

    def state(self) -> dict:
        return {"optimizer": self.opt.state_dict(), "scaler": self.scaler.state_dict(), "step": self.step,
                "total_steps": self.total_steps}

    def load_state(self, payload: dict) -> None:
        self.opt.load_state_dict(payload["optimizer"])
        if payload.get("scaler") and self.amp:
            self.scaler.load_state_dict(payload["scaler"])
        self.step = payload["step"]

    @torch.no_grad()
    def evaluate(self, loader, runtime: Runtime, max_batches: int | None = None) -> dict:
        """Teacher-forced loss and per-head accuracy, and the exact-decision rate of the model's own greedy decision."""
        self.model.eval()
        tot, n_batches, correct, count = 0.0, 0, {}, {}
        tally = {"exact": 0, "gesture": 0, "n": 0, "errors": 0, "forced_eos": 0, "overflow": 0}
        reasons: dict[str, int] = {}
        for i, batch in enumerate(loader):
            if max_batches is not None and i >= max_batches:
                break
            batch = batch.to(self.device)
            with torch.autocast(self.device.type, dtype=torch.float16, enabled=self.amp):
                out = self.model(batch)
                total, _, acc = self.loss(out, batch)
                pred = self.model.predict(batch, speech_capacity=max(8, int(batch.seq_ok.sum()) if batch.seq_ok is not None else 8))
            tot += float(total)
            n_batches += 1
            for k, v in acc.items():
                if k.endswith("#"):
                    count[k[:-1]] = count.get(k[:-1], 0.0) + float(v)
                    correct[k[:-1]] = correct.get(k[:-1], 0.0) + float(acc[k[:-1]]) * float(v)
            self.exact_match(batch, pred, runtime, tally, reasons)
        n = max(1, tally["n"])
        return {"loss": tot / max(1, n_batches), "decisions": tally["n"], "exact_decision": tally["exact"] / n,
                "gesture_acc": tally["gesture"] / n, "decode_errors": tally["errors"], "decode_error_reasons": reasons,
                "forced_eos": tally["forced_eos"], "speech_overflow": tally["overflow"],
                "acc": {k: correct[k] / max(1.0, count[k]) for k in correct}}

    def exact_match(self, batch: Batch, pred: dict, runtime: Runtime, tally: dict, reasons: dict) -> None:
        """How many of the model's own decisions equal the label, as a decision (needs the records). An invalid
        prediction (it does not decode) is COUNTED with its reason, and so is a sentence whose end was forced."""
        names = Targets.names()
        p = {k: v.cpu().numpy() for k, v in pred.items()}
        t = {k: v.cpu().numpy() for k, v in batch.targets.items()}
        tally["forced_eos"] += int(p["seq_forced"].sum())
        tally["overflow"] += int(p["speech_overflow"])
        for i, meta in enumerate(batch.meta):
            records, enc = meta["records"], meta["enc"]
            want = Targets(**{n: t[n][i] for n in names})
            got = Targets(**{n: p[n][i].copy() for n in names})
            if want.plan_gesture[0] == NO_LABEL:                  # the label says nothing about plans / stops: do not judge them
                for n in ("plan_gesture", "plan_ref", "plan_repeat", "plan_period", "plan_parent"):
                    setattr(got, n, np.full_like(getattr(got, n), NO_LABEL))
            if want.stop == NO_LABEL:
                for n in ("stop", "stop_ref", "stop_num", "stop_word"):
                    setattr(got, n, np.full_like(getattr(got, n), NO_LABEL))
            tally["n"] += 1
            tally["gesture"] += int(got.gesture == want.gesture)
            try:
                tally["exact"] += int(comparable(runtime.codec.decode(want, enc, records)) == comparable(runtime.codec.decode(got, enc, records)))
            except Exception as e:                              # noqa: BLE001  (counted and reported, never swallowed)
                tally["errors"] += 1
                key = f"{type(e).__name__}: {str(e)[:80]}"
                reasons[key] = reasons.get(key, 0) + 1


class RunLog:
    """One JSON line per log step, in the output folder."""

    def __init__(self, out: Path):
        self.path = out / "log.jsonl"
        out.mkdir(parents=True, exist_ok=True)

    def write(self, record: dict) -> None:
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")


def scalar(x):
    return float(x) if hasattr(x, "item") else x


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--data", nargs="+", type=Path, required=True)
    ap.add_argument("--smoke-test", action="store_true", help="the data is the random smoke set: a test of the chain only")
    ap.add_argument("--cache", type=Path, default=None, help="folder of the tokenised cache (default ~/.cache/emergence)")
    ap.add_argument("--size", choices=sorted(SIZES), default="small")
    ap.add_argument("--epochs", type=int, default=1, help="TOTAL epochs of the run (a resume continues up to this number)")
    ap.add_argument("--batch", type=int, default=64)
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--warmup", type=int, default=100)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--resume", type=Path, default=None)
    ap.add_argument("--init-from", type=Path, default=None,
                    help="weights of an older checkpoint, loaded PARTIALLY (new heads start fresh; a new optimiser)")
    ap.add_argument("--log-every", type=int, default=20)
    ap.add_argument("--eval-every", type=int, default=500, help="steps (0: once per epoch)")
    ap.add_argument("--save-every", type=int, default=500)
    ap.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    a = ap.parse_args(argv)
    seed_everything(a.seed)
    rt = Runtime.build()
    kw = dict(runtime=rt, allow_smoke=a.smoke_test, cache_dir=a.cache)
    train = LabelDataset(a.data, split="train", **kw)
    val = LabelDataset(a.data, split="val", keep_context=True, **kw)
    print("data:", json.dumps(train.audit()))
    per_epoch = math.ceil(len(train) / a.batch)
    start_step, start_epoch, total = 0, 0, a.epochs * per_epoch
    payload = None
    if a.resume:
        model, payload = Checkpoint.load(a.resume, rt, a.device)
        start_step, total = payload["step"], payload.get("total_steps", total)
        start_epoch = start_step // per_epoch
    elif a.init_from:
        model, loaded = Checkpoint.load(a.init_from, rt, a.device, partial=True)
        rep_ = loaded["load_report"]
        print("partial load:", {k: (len(v) if not isinstance(v, dict) else len(v)) for k, v in rep_.items()},
              "reinitialised:", PartialLoader.reinitialized_of(rep_))
    else:
        model = StudentModel(SIZES[a.size], rt.space)
    trainer = Trainer(model, a.device, a.lr, total, a.warmup, seed=a.seed)
    if payload:
        trainer.load_state(payload)
    print(f"{model.cfg.name}: {model.n_params() / 1e6:.2f} M parameters, {len(train)} train / {len(val)} val, "
          f"{a.epochs} epochs = {a.epochs * per_epoch} steps (schedule planned for {total}), from step {start_step}, {a.device}")
    log, t0 = RunLog(a.out), time.time()

    def save():
        Checkpoint.save(a.out / "last.pt", model, rt, trainer.state() | {"epoch": trainer.step // per_epoch, "epochs": a.epochs})

    def evaluate(limit=None):
        if len(val):
            ev = trainer.evaluate(val.loader(a.batch), rt, max_batches=limit)
            log.write({"step": trainer.step, "eval": ev})
            print("eval", json.dumps(ev))

    for epoch in range(start_epoch, a.epochs):
        skip = trainer.step - epoch * per_epoch                       # batches of this epoch already done (resume)
        loader = train.loader(a.batch, shuffle=True, num_workers=a.workers, seed=a.seed, epoch=epoch, skip_batches=skip)
        for batch in loader:
            r = trainer.train_step(batch)
            if trainer.step % a.log_every == 0:
                rec = {"step": trainer.step, "epoch": epoch, "loss": scalar(r["loss"]), "grad_norm": scalar(r["grad_norm"]),
                       "lr": r["lr"], "scale": trainer.loss_scale(), "elapsed_s": round(time.time() - t0, 1),
                       "decisions_per_s": round((trainer.step - start_step) * a.batch / (time.time() - t0), 1)}
                log.write(rec)
                print(json.dumps(rec))
            if a.save_every and trainer.step % a.save_every == 0:
                save()
            if a.eval_every and trainer.step % a.eval_every == 0:
                evaluate(20)
        if not a.eval_every:
            evaluate()
    save()
    return 0


if __name__ == "__main__":
    sys.exit(main())
