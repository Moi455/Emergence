"""compare.py - the yardstick: a deliberately oversized `xl` Transformer, quantised, against the small unquantised ones.

    cd ai && python3 -m student2.compare --data ~/.local/share/emergence/runs/xl_vs_small/serie1_copy.jsonl \
        --out ~/.local/share/emergence/runs/xl_vs_small/run1

Decision of 15 Oct.: "take a transformer far too big to hold the performance, quantise it, and compare it with our small
unquantised transformers". This script trains `small` and `xl` on EXACTLY the same data, the same split (hash of the
line id), the same seed, the same number of epochs (at most), the same batch, dropout and weight decay, with early
stopping on the validation loss (the best epoch is restored). Then ONE evaluator (evaluate.py) scores, on the same
validation batches: small fp16, xl fp16, xl int8 weights only, xl W8A8 (quantize.py, `--scope` layers), and measures size,
GPU memory, throughput, agreement of the decisions with the fp16 of the same model, and the GPU share a policy running at
`--rate` decisions per second would take (policy = `forward(teacher=False)`, the speech decoder not included).

Caveats built into the method (also printed in the report):
  * the early-stopping epoch is chosen on the validation split the final scores are computed on: the scores are slightly
    optimistic, equally for both models;
  * with few labels, and none that plan, this is a test of the CHAIN, not a ranking of the sizes;
  * learning rate per size (`--lr small xl`), because a 175 M model does not take the rate of a 12 M one.

`--reuse` skips the training of a size whose `best.pt` already exists in `--out` (a new quantisation or evaluation of
the same weights). Re-run with a bigger file and `--out` elsewhere.
"""
from __future__ import annotations

import argparse
import copy
import dataclasses
import json
import sys
import time
from pathlib import Path

import numpy as np
import torch

from .data import LabelDataset
from .evaluate import Evaluator, flatten, load_model
from .model import SIZES, StudentModel
from .quantize import Bench, Comparison, DynamicInt8, WeightOnlyInt8
from .runtime import Runtime
from .train import Checkpoint, Trainer, seed_everything

HEADS = (("gesture.top1", "geste top-1"), ("gesture.top3", "geste top-3"), ("pointers.per_pointer|g", "pointeurs (geste juste)"),
         ("manner.per_value|g", "manières (geste juste)"), ("stop_condition.condition|g", "condition d'arrêt (geste juste)"),
         ("writes.n_writes", "nombre d'écritures"), ("writes.write_exact", "écriture exacte"),
         ("sequences.speech_exact|g", "parole exacte (geste juste)"))


# ----------------------------------------------------------------------------------------------- training
class FitReport(dict):
    """What a training run did: per-epoch losses, the epoch kept, speed and peak memory."""


class Fitter:
    """Trains one size with early stopping on the validation loss and returns the best weights (restored in the model)."""

    def __init__(self, rt: Runtime, train: LabelDataset, val: LabelDataset, batch: int, seed: int, workers: int = 2):
        self.rt, self.train, self.val, self.batch, self.seed, self.workers = rt, train, val, batch, seed, workers

    @torch.no_grad()
    def val_loss(self, trainer: Trainer) -> float:
        trainer.model.eval()
        tot, n = 0.0, 0
        for b in self.val.loader(self.batch):
            b = b.to(trainer.device)
            with torch.autocast("cuda", dtype=torch.float16, enabled=trainer.amp):
                total, _, _ = trainer.loss(trainer.model(b), b)
            tot, n = tot + float(total), n + 1
        return tot / max(1, n)

    def fit(self, name: str, cfg, lr: float, epochs: int, patience: int, warmup: int, weight_decay: float, out: Path) -> tuple[StudentModel, FitReport]:
        seed_everything(self.seed)
        model = StudentModel(cfg, self.rt.space)
        per_epoch = len(self.train) // self.batch
        trainer = Trainer(model, "cuda", lr, epochs * per_epoch, warmup, seed=self.seed)
        for g in trainer.opt.param_groups:
            if g["weight_decay"]:
                g["weight_decay"] = weight_decay
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()
        rows, best, best_state, bad, train_s, seen = [], float("inf"), None, 0, 0.0, 0
        for epoch in range(epochs):
            loader = self.train.loader(self.batch, shuffle=True, num_workers=self.workers, seed=self.seed, epoch=epoch, drop_last=True)
            t0, acc, k = time.perf_counter(), torch.zeros((), device="cuda"), 0
            for b in loader:
                acc += trainer.train_step(b)["loss"]
                k += 1
            torch.cuda.synchronize()
            train_s += time.perf_counter() - t0
            seen += k * self.batch
            row = {"epoch": epoch + 1, "train_loss": round(float(acc) / max(1, k), 4), "val_loss": round(self.val_loss(trainer), 4)}
            rows.append(row)
            print(name, json.dumps(row), flush=True)
            if row["val_loss"] < best:
                best, bad = row["val_loss"], 0
                best_state = {k_: v.detach().cpu().clone() for k_, v in model.state_dict().items()}
                row["best"] = True
            else:
                bad += 1
                if bad >= patience:
                    break
        model.load_state_dict(best_state)
        Checkpoint.save(out / name / "best.pt", model, self.rt)
        peak = torch.cuda.max_memory_allocated() / 2**20
        kept = next(r for r in rows if r.get("best") and r["val_loss"] == best)
        rep = FitReport(size=name, params_M=round(model.n_params() / 1e6, 2), lr=lr, weight_decay=weight_decay, dropout=cfg.dropout,
                        batch=self.batch, checkpointing=cfg.checkpoint, epochs_run=len(rows), epoch_kept=kept["epoch"],
                        best_val_loss=best, train_loss_at_best=kept["train_loss"], last_train_loss=rows[-1]["train_loss"],
                        epochs=rows, train_decisions_per_s=round(seen / train_s, 1), peak_train_MiB=round(peak))
        del trainer
        torch.cuda.empty_cache()
        return model.cpu().eval(), rep


# ----------------------------------------------------------------------------------------------- measures
def gpu_share(entry: dict, rate: float, batches) -> dict:
    """GPU fraction used by a policy deciding `rate` decisions per second, per batch size (graph time when it exists).
    1.0 = the whole GPU; the AI budget is 0.25."""
    out = {}
    for b in batches:
        r = (entry.get("bench") or {}).get(f"batch{b}", {})
        ms = r.get("policy_graph_ms") or r.get("policy_eager_ms")
        out[f"batch{b}"] = None if not ms else round(rate * (ms / 1e3) / b, 3)
    return out


def flat_acc(entry: dict) -> dict:
    flat = flatten(entry["report"])
    return {k: flat[k]["acc"] for k, _ in HEADS if k in flat and flat[k]["n"]}


def table(res: dict, batches, rate: float, budget: float = 0.25) -> str:
    rows = [("small fp16", res["small"]["fp16"], None)]
    for k, e in res["xl"].items():
        if not k.startswith("_"):
            rows.append((f"xl {k}", e, res["xl"]["fp16"]))
    acc_cols = [t for _, t in HEADS]
    lines = ["| variante | " + " | ".join(acc_cols) + " | décision valide (validateur) |", "|" + "---|" * (len(acc_cols) + 2)]
    for name, e, _ in rows:
        a = flat_acc(e)
        cells = [("n/a" if a.get(k) is None else f"{100 * a[k]:.1f} %") for k, _ in HEADS]
        lines.append(f"| {name} | " + " | ".join(cells) + f" | {100 * e['decision_valid']:.1f} % |")
    b0, b1 = batches[0], batches[-1]
    lines += ["", f"| variante | taille (Mo) | poids GPU (Mo) | pic inférence lot {b0} / {b1} (Mo) | politique lot {b0} / {b1} (ms, graphe) | "
              f"décisions/s lot {b0} / {b1} | coût GPU à {rate:g} déc/s, lot {b0} / {b1} | vs budget {budget:.0%} | accord geste+pointeurs avec le fp16 | accord décision entière |",
              "|" + "---|" * 10]
    for name, e, _ in rows:
        bn = e.get("bench") or {}
        g = lambda b, key: (bn.get(f"batch{b}") or {}).get(key)              # noqa: E731
        share = gpu_share(e, rate, batches)
        ag = e.get("agreement_with_fp16")
        worst = max([v for v in share.values() if v is not None], default=None)
        verdict = "n/a" if worst is None else f"x{worst / budget:.1f}" + (" (dépasse)" if worst > budget else " (tient)")
        lines.append(f"| {name} | {e['size_MiB']} | {g(b0, 'weights_MiB')} | {g(b0, 'peak_inference_MiB')} / {g(b1, 'peak_inference_MiB')} | "
                     f"{g(b0, 'policy_graph_ms')} / {g(b1, 'policy_graph_ms')} | {g(b0, 'policy_graph_decisions_per_s')} / {g(b1, 'policy_graph_decisions_per_s')} | "
                     f"{share[f'batch{b0}']} / {share[f'batch{b1}']} | {verdict} | "
                     + (f"{100 * ag['gesture_and_pointers']:.1f} % | {100 * ag['whole_decision']:.1f} %" if ag else "(réf.) | (réf.)") + " |")
    return "\n".join(lines)


def train_table(fits: dict) -> str:
    lines = ["| modèle | params (M) | lr | époques jouées / retenue | perte entraînement (retenue) | perte validation (retenue) | débit entraînement (déc/s) | pic mémoire entraînement (Mo) |",
             "|" + "---|" * 8]
    for f in fits.values():
        lines.append(f"| {f['size']} | {f['params_M']} | {f['lr']:g} | {f['epochs_run']} / {f['epoch_kept']} | {f['train_loss_at_best']} | "
                     f"{f['best_val_loss']} | {f['train_decisions_per_s']} | {f['peak_train_MiB']} |")
    return "\n".join(lines)


# ----------------------------------------------------------------------------------------------- driver
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--data", type=Path, nargs="+", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--cache", type=Path, default=None)
    ap.add_argument("--epochs", type=int, default=12, help="MAXIMUM epochs (early stopping on the validation loss)")
    ap.add_argument("--patience", type=int, default=3)
    ap.add_argument("--batch", type=int, default=32, help="training batch (xl needs <= 64 on 6 GB with checkpointing)")
    ap.add_argument("--lr", type=float, nargs=2, default=[3e-4, 1e-4], metavar=("SMALL", "XL"))
    ap.add_argument("--warmup", type=int, default=100)
    ap.add_argument("--weight-decay", type=float, default=0.1)
    ap.add_argument("--dropout", type=float, default=0.1, help="the same for both sizes")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--scope", default="body", choices=["body", "all"], help="layers quantised (quantize.py)")
    ap.add_argument("--no-w8a8", action="store_true")
    ap.add_argument("--rate", type=float, default=200.0, help="decisions per second of the cost estimate")
    ap.add_argument("--bench-batch", type=int, nargs="+", default=[32, 128])
    ap.add_argument("--eval-batch", type=int, default=32)
    ap.add_argument("--limit", type=int, default=None, help="evaluate only the first N validation decisions")
    ap.add_argument("--reuse", action="store_true", help="do not retrain a size whose best.pt exists in --out")
    a = ap.parse_args(argv)
    if not torch.cuda.is_available():
        print("no GPU: nothing to compare", file=sys.stderr)
        return 2
    a.out.mkdir(parents=True, exist_ok=True)
    rt = Runtime.build()
    kw = dict(runtime=rt, cache_dir=a.cache)
    train, val = LabelDataset(a.data, split="train", **kw), LabelDataset(a.data, split="val", keep_context=True, **kw)
    print("data:", json.dumps(train.audit()), f"| {len(train)} train / {len(val)} val", flush=True)
    fitter = Fitter(rt, train, val, a.batch, a.seed)
    models, fits = {}, {}
    for name, lr in zip(("small", "xl"), a.lr):
        cfg = dataclasses.replace(SIZES[name], dropout=a.dropout)
        best = a.out / name / "best.pt"
        if a.reuse and best.exists():
            models[name] = load_model(best, rt, "cpu")
            fp = a.out / name / "fit.json"
            fits[name] = FitReport(json.loads(fp.read_text())) if fp.exists() else FitReport(size=name)
            continue
        models[name], fits[name] = fitter.fit(name, cfg, lr, a.epochs, a.patience, a.warmup, a.weight_decay, a.out)
        (a.out / name / "fit.json").write_text(json.dumps(fits[name], indent=1), encoding="utf-8")
    ev = Evaluator(rt, val, a.eval_batch, a.limit, "cuda")
    bench = Bench(ev, tuple(a.bench_batch))
    res = {"small": Comparison(models["small"], ev, [], bench).run()}
    qs = [WeightOnlyInt8(a.scope)] + ([] if a.no_w8a8 else [DynamicInt8(a.scope)])
    res["xl"] = Comparison(models["xl"], ev, qs, bench).run()
    meta = {"data": [str(p) for p in a.data], "train": len(train), "val": len(val), "seed": a.seed, "scope": a.scope, "rate": a.rate,
            "gpu": torch.cuda.get_device_name(0), "torch": torch.__version__, "args": {k: str(v) for k, v in vars(a).items()}}
    (a.out / "results.json").write_text(json.dumps({"meta": meta, "fits": fits, "results": res}, indent=1, default=str), encoding="utf-8")
    md = (f"Données : {len(train)} entraînement / {len(val)} validation, graine {a.seed}.\n\n" + train_table(fits) + "\n\n"
          + table(res, a.bench_batch, a.rate) + "\n")
    (a.out / "results.md").write_text(md, encoding="utf-8")
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
