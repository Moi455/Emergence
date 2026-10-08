#!/usr/bin/env python3
"""train_student.py - trains the student Transformer on a tok-1 dataset (PyTorch). Runs on CPU or one CUDA GPU.

On Monsieur's laptop (RTX 3000 series, 6 GB):
    python train_student.py --data /chemin/donnees-transformer/ref_v04_300k --config small --epochs 8 --batch 256
CPU smoke test (a few minutes):
    python train_student.py --data ... --config tiny --epochs 1 --max-train 20000 --device cpu

Loss: cross-entropy between the soft target over the options of each situation and the softmax of the student's
logits (masked to CAND tokens), + 0.1 x binary cross-entropy on the 10 drivers. Teacher-labelled samples (source=1)
get --teacher-weight (default 3) once they exist.
Checkpoints: <out>/best.pt (best validation top-1), <out>/last.pt; metrics in <out>/log.jsonl.
"""
import argparse
import json
import math
import os
import sys
import time

import numpy as np
import torch
import torch.nn.functional as F_

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dataset_reader import TokDataset          # noqa: E402
from student_model import Student, n_params    # noqa: E402


def to_dev(b, dev):
    return {k: torch.as_tensor(v).to(dev, non_blocking=True) for k, v in b.items()}


def losses(model, b, teacher_weight=3.0, drv_weight=0.1):
    logits, drv = model(b["cat"], b["num"] if b["num"].dtype != torch.float64 else b["num"].float(), b["mask"])
    logits = logits.float().masked_fill(~b["cand"], -1e9)
    logp = F_.log_softmax(logits, -1)
    ce = -(b["soft"] * logp).masked_fill(~b["cand"], 0).sum(-1)
    w = torch.where(b["source"] == 1, teacher_weight, 1.0)
    l_main = (ce * w).sum() / w.sum()
    l_drv = F_.binary_cross_entropy_with_logits(drv.float(), b["drivers"])
    return l_main + drv_weight * l_drv, l_main, logits


@torch.no_grad()
def evaluate(model, ds, idx, dev, bs, amp):
    """top1 = student's best option equals the label's best; good = student's best has label score >= 3;
    kl = KL(label || student) in nats; per family top1."""
    was_training = model.training
    model.eval()
    n = top1 = good = 0
    kl_sum = 0.0
    fam_hit, fam_n = np.zeros(len(ds.families())), np.zeros(len(ds.families()))
    for i in range(0, len(idx), bs):
        b = to_dev(ds.batch(idx[i:i + bs]), dev)
        with torch.autocast(dev.type, dtype=torch.bfloat16 if dev.type == "cuda" else torch.bfloat16, enabled=amp):
            _, _, logits = losses(model, b)
        logp = F_.log_softmax(logits, -1)
        p = b["soft"]
        kl = (p * (torch.log(p.clamp(min=1e-9)) - logp)).masked_fill(~b["cand"], 0).sum(-1)
        pred = logits.argmax(-1)
        tgt = p.masked_fill(~b["cand"], -1).argmax(-1)
        hit = (pred == tgt)
        sc = torch.gather(b["score"], 1, pred.unsqueeze(1)).squeeze(1)
        n += len(pred)
        top1 += hit.sum().item()
        good += (sc >= 3).sum().item()
        kl_sum += kl.sum().item()
        fam = b["family"].cpu().numpy()
        np.add.at(fam_hit, fam, hit.cpu().numpy())
        np.add.at(fam_n, fam, 1)
    model.train(was_training)
    fams = {f: round(fam_hit[i] / fam_n[i], 3) for i, f in enumerate(ds.families()) if fam_n[i]}
    return {"n": n, "top1": top1 / max(1, n), "good": good / max(1, n), "kl": kl_sum / max(1, n), "family_top1": fams}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", default="runs/student")
    ap.add_argument("--config", default="small", choices=["tiny", "small", "base", "large"])
    ap.add_argument("--epochs", type=int, default=8)
    ap.add_argument("--batch", type=int, default=256)
    ap.add_argument("--lr", type=float, default=6e-4)
    ap.add_argument("--wd", type=float, default=0.05)
    ap.add_argument("--warmup", type=int, default=1000)
    ap.add_argument("--max-train", type=int, default=0)
    ap.add_argument("--max-eval", type=int, default=5000)
    ap.add_argument("--temperature", type=float, default=0, help="re-derive soft targets from utilities at this temperature (0 = stored)")
    ap.add_argument("--teacher-weight", type=float, default=3.0)
    ap.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    ap.add_argument("--no-amp", action="store_true")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--eval-every", type=int, default=2000)
    a = ap.parse_args()
    torch.manual_seed(a.seed)
    rng = np.random.default_rng(a.seed)
    dev = torch.device(a.device)
    amp = dev.type == "cuda" and not a.no_amp
    ds = TokDataset(a.data)
    tr = ds.indices("train")
    if a.max_train:
        tr = tr[:a.max_train]
    va = ds.indices("val")[:a.max_eval]
    model = Student(ds.vocab_size, ds.F, a.config).to(dev)
    os.makedirs(a.out, exist_ok=True)
    print(f"data {ds.n} situations (train {len(tr)}, val {len(va)}), model {a.config} {n_params(model) / 1e6:.2f} M params, device {dev}")
    opt = torch.optim.AdamW(model.parameters(), lr=a.lr, weight_decay=a.wd, betas=(0.9, 0.98))
    steps = a.epochs * math.ceil(len(tr) / a.batch)
    sched = torch.optim.lr_scheduler.LambdaLR(opt, lambda s: min(1, (s + 1) / a.warmup) * 0.5 * (1 + math.cos(math.pi * min(1, s / steps))))
    temp = a.temperature or None
    log = open(os.path.join(a.out, "log.jsonl"), "a")
    best, step, t0 = -1, 0, time.time()
    for ep in range(a.epochs):
        perm = rng.permutation(tr)
        for i in range(0, len(perm), a.batch):
            b = to_dev(ds.batch(np.sort(perm[i:i + a.batch]), temperature=temp), dev)
            with torch.autocast(dev.type, dtype=torch.bfloat16, enabled=amp):
                loss, l_main, _ = losses(model, b, a.teacher_weight)
            opt.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            sched.step()
            step += 1
            if step % 100 == 0:
                el = time.time() - t0
                print(f"ep {ep} step {step}/{steps} loss {l_main.item():.4f}  {step * a.batch / el:.0f} situations/s  "
                      f"eta {(steps - step) * el / step / 60:.1f} min", flush=True)
            if step % a.eval_every == 0 or step == steps:
                m = evaluate(model, ds, va, dev, 512, amp)
                m.update({"step": step, "epoch": ep, "loss": l_main.item(), "time_s": round(time.time() - t0)})
                log.write(json.dumps(m) + "\n")
                log.flush()
                print(f"  val top1 {m['top1']:.3f}  good {m['good']:.3f}  kl {m['kl']:.3f}", flush=True)
                ck = {"model": model.state_dict(), "config": a.config, "vocab_size": ds.vocab_size, "F": ds.F,
                      "vocab_hash": ds.man["vocab_hash"], "format": ds.man["format"], "val": m, "args": vars(a)}
                torch.save(ck, os.path.join(a.out, "last.pt"))
                if m["top1"] > best:
                    best = m["top1"]
                    torch.save(ck, os.path.join(a.out, "best.pt"))
    print(f"done in {(time.time() - t0) / 60:.1f} min, best val top1 {best:.3f} -> {a.out}/best.pt")


if __name__ == "__main__":
    main()
