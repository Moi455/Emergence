"""train.py - train the student on a labels file (`dataset.jsonl`), in float16 on the GPU.

    cd ai
    python3 -m student2.train --data /path/dataset.jsonl --size small --epochs 3 --batch 64 --out runs/student2-a
    python3 -m student2.train --data a.jsonl b.jsonl --size base --resume runs/student2-a/last.pt ...

Quadro RTX 3000 (Turing): no bfloat16, so autocast float16 + GradScaler (the loss is scaled, gradients unscaled before
clipping, a step with non-finite gradients is skipped). AdamW (no decay on norms, biases, embeddings and the graph
bias), linear warm-up then cosine to 10 % of the peak, gradient clipping at 1. A checkpoint carries the tok-2
fingerprints (interface, layout, registry, vocabulary) and the output-interface fingerprint: a checkpoint trained for
another catalogue state is REFUSED at load (`CheckpointMismatch`), because its weights mean something else.

THIS TRAINS ON WHATEVER FILE YOU GIVE. Never give it the smoke file (`source.teacher = "smoke-random"`) for anything
but a test: it holds random answers.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from dataclasses import asdict
from pathlib import Path

import torch

from .data import Batch, LabelDataset
from .labels import comparable
from .losses import LossWeights, StudentLoss
from .model import SIZES, StudentConfig, StudentModel
from .runtime import Fingerprints, Runtime

CHECKPOINT_VERSION = 1


class CheckpointMismatch(ValueError):
    """A checkpoint made for another interface / layout / registry / output heads."""


# ----------------------------------------------------------------------------------------------- checkpoints
class Checkpoint:
    """Weights + config + the fingerprints they were trained under."""

    @staticmethod
    def save(path: Path, model: StudentModel, fingerprints: Fingerprints, extra: dict | None = None) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": CHECKPOINT_VERSION, "config": model.cfg.to_dict(), "fingerprints": asdict(fingerprints),
                   "model": model.state_dict(), **(extra or {})}
        tmp = path.with_suffix(".tmp")
        torch.save(payload, tmp)
        tmp.replace(path)

    @staticmethod
    def check(payload: dict, fingerprints: Fingerprints) -> None:
        if payload.get("version") != CHECKPOINT_VERSION:
            raise CheckpointMismatch(f"checkpoint version {payload.get('version')!r}, expected {CHECKPOINT_VERSION}")
        theirs = Fingerprints(**payload["fingerprints"])
        diff = fingerprints.diff(theirs)
        if diff:
            raise CheckpointMismatch("this checkpoint was trained for another catalogue state (current, checkpoint): "
                                     + json.dumps(diff))

    @classmethod
    def load(cls, path: Path, runtime: Runtime, device="cpu", memory=None) -> tuple[StudentModel, dict]:
        payload = torch.load(path, map_location=device, weights_only=False)
        cls.check(payload, runtime.fingerprints())
        model = StudentModel(StudentConfig(**payload["config"]), runtime.space, memory).to(device)
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


def make_optimizer(model: StudentModel, lr: float, weight_decay: float = 0.05) -> torch.optim.AdamW:
    decay, plain = [], []
    for name, p in model.named_parameters():
        no_decay = p.ndim < 2 or "emb" in name or "bias" in name or "gain" in name or "ghost" in name or "film" in name
        (plain if no_decay else decay).append(p)
    return torch.optim.AdamW([{"params": decay, "weight_decay": weight_decay}, {"params": plain, "weight_decay": 0.0}],
                             lr=lr, betas=(0.9, 0.95), fused=torch.cuda.is_available())


# ----------------------------------------------------------------------------------------------- the loop
class Trainer:
    def __init__(self, model: StudentModel, device: str, lr: float = 3e-4, total_steps: int = 1000, warmup: int = 100,
                 clip: float = 1.0, weights: LossWeights | None = None, amp: bool | None = None):
        self.model, self.device, self.clip = model.to(device), torch.device(device), clip
        self.amp = (self.device.type == "cuda") if amp is None else amp
        self.opt = make_optimizer(model, lr)
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
                "scale": self.scaler.get_scale() if self.amp else 1.0, "parts": {k: v.detach() for k, v in parts.items()},
                "acc": acc}

    @torch.no_grad()
    def evaluate(self, loader, runtime: Runtime, max_batches: int | None = None) -> dict:
        """Teacher-forced loss and per-head accuracy, and the exact-decision rate of the model's own greedy decision."""
        self.model.eval()
        tot, n_batches, correct, count, exact, n_dec, gest = 0.0, 0, {}, {}, 0, 0, 0
        for i, batch in enumerate(loader):
            if max_batches is not None and i >= max_batches:
                break
            batch = batch.to(self.device)
            with torch.autocast(self.device.type, dtype=torch.float16, enabled=self.amp):
                out = self.model(batch)
                total, _, acc = self.loss(out, batch)
                pred = self.model.predict(batch)
            tot += float(total)
            n_batches += 1
            for k, v in acc.items():
                if k.endswith("#"):
                    count[k[:-1]] = count.get(k[:-1], 0.0) + float(v)
                    correct[k[:-1]] = correct.get(k[:-1], 0.0) + float(acc[k[:-1]]) * float(v)
            exact_i, gest_i, n_i = self.exact_match(batch, pred, runtime)
            exact, gest, n_dec = exact + exact_i, gest + gest_i, n_dec + n_i
        return {"loss": tot / max(1, n_batches), "decisions": n_dec, "exact_decision": exact / max(1, n_dec),
                "gesture_acc": gest / max(1, n_dec), "acc": {k: correct[k] / max(1.0, count[k]) for k in correct}}

    def exact_match(self, batch: Batch, pred: dict, runtime: Runtime) -> tuple[int, int, int]:
        """How many of the model's own decisions equal the label, as a decision (needs the records: re-tokenised)."""
        from .labels import Targets
        names = Targets.names()
        exact = gest = 0
        p = {k: v.cpu().numpy() for k, v in pred.items()}
        t = {k: v.cpu().numpy() for k, v in batch.targets.items()}
        for i, meta in enumerate(batch.meta):
            records, enc = meta["records"], meta["enc"]
            want = Targets(**{n: t[n][i] for n in names})
            got = Targets(**{n: p[n][i] for n in names if n in p})
            gest += int(got.gesture == want.gesture)
            try:
                a = comparable(runtime.codec.decode(want, enc, records))
                b = comparable(runtime.codec.decode(got, enc, records))
                exact += int(a == b)
            except Exception:                                   # noqa: BLE001  (an invalid prediction is simply not exact)
                pass
        return exact, gest, len(batch.meta)


class RunLog:
    """One JSON line per log step, in the output folder, and a short line on stdout."""

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
    ap.add_argument("--size", choices=sorted(SIZES), default="small")
    ap.add_argument("--epochs", type=int, default=1)
    ap.add_argument("--batch", type=int, default=64)
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--warmup", type=int, default=100)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--resume", type=Path, default=None)
    ap.add_argument("--log-every", type=int, default=20)
    ap.add_argument("--eval-every", type=int, default=500, help="steps (0: once per epoch)")
    ap.add_argument("--save-every", type=int, default=500)
    ap.add_argument("--audit", action="store_true", help="tokenise every line once first and report the unusable ones")
    ap.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    a = ap.parse_args(argv)
    rt = Runtime.build()
    train = LabelDataset(a.data, split="train", runtime=rt)
    val = LabelDataset(a.data, split="val", runtime=rt, keep_context=True)
    if a.audit:
        print("audit:", json.dumps(train.audit()))
    steps = a.epochs * math.ceil(len(train) / a.batch)
    model = StudentModel(SIZES[a.size], rt.space)
    trainer = Trainer(model, a.device, a.lr, steps, a.warmup)
    if a.resume:
        model, payload = Checkpoint.load(a.resume, rt, a.device)
        trainer = Trainer(model, a.device, a.lr, steps, a.warmup)
        trainer.opt.load_state_dict(payload["optimizer"])
        trainer.step = payload["step"]
    print(f"{a.size}: {model.n_params() / 1e6:.2f} M parameters, {len(train)} train / {len(val)} val, {steps} steps, {a.device}")
    log = RunLog(a.out)
    t0 = time.time()
    loader = train.loader(a.batch, shuffle=True, num_workers=a.workers, seed=trainer.step)
    for epoch in range(a.epochs):
        for batch in loader:
            r = trainer.train_step(batch)
            if trainer.step % a.log_every == 0:
                rec = {"step": trainer.step, "epoch": epoch, "loss": scalar(r["loss"]), "grad_norm": scalar(r["grad_norm"]),
                       "lr": r["lr"], "scale": r["scale"], "elapsed_s": round(time.time() - t0, 1),
                       "decisions_per_s": round(trainer.step * a.batch / (time.time() - t0), 1)}
                log.write(rec)
                print(json.dumps(rec))
            if a.save_every and trainer.step % a.save_every == 0:
                Checkpoint.save(a.out / "last.pt", model, rt.fingerprints(), {"optimizer": trainer.opt.state_dict(), "step": trainer.step})
            if a.eval_every and trainer.step % a.eval_every == 0 and len(val):
                ev = trainer.evaluate(val.loader(a.batch), rt, max_batches=20)
                log.write({"step": trainer.step, "eval": ev})
                print("eval", json.dumps(ev))
        if len(val) and not a.eval_every:
            ev = trainer.evaluate(val.loader(a.batch), rt)
            log.write({"step": trainer.step, "eval": ev})
            print("eval", json.dumps(ev))
    Checkpoint.save(a.out / "last.pt", model, rt.fingerprints(), {"optimizer": trainer.opt.state_dict(), "step": trainer.step})
    return 0


if __name__ == "__main__":
    sys.exit(main())
