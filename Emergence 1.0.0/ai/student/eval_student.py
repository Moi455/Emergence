#!/usr/bin/env python3
"""eval_student.py - evaluates a trained student against its labels AND against the reference decider.

    python eval_student.py --ckpt runs/student/best.pt --data <dataset dir> --pairs <pairs.jsonl>

Reports
  * test split: top1 (same best option as the label), good (student's pick has label score >= 3), KL, per family;
  * minimal pairs: pass rate per probe for the student and for the reference decider (roadmap S7: the student must
    beat the reference; while the labels come from the reference this mainly checks that it learned the directions);
  * speed: decisions per second at batch 512 (one RTX: ~30 decisions/s are needed in game, architecture 9.3).
"""
import argparse
import json
import os
import sys
import time

import numpy as np
import torch
import torch.nn.functional as F_

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "npc_pipeline"))
from dataset_reader import TokDataset          # noqa: E402
from student_model import Student               # noqa: E402
from train_student import evaluate, to_dev      # noqa: E402


def load(ckpt, dev):
    ck = torch.load(ckpt, map_location=dev, weights_only=False)
    m = Student(ck["vocab_size"], ck["F"], ck["config"]).to(dev)
    m.load_state_dict(ck["model"])
    m.eval()
    return m, ck


def batch_from_records(recs, vocab, F):
    import encode as enc
    encs = [enc.encode(r, vocab) for r in recs]
    T = max(len(e["cat"]) for e in encs)
    B = len(encs)
    cat = np.zeros((B, T, 9), np.int64)
    cat[..., 6:9] = -1
    num = np.zeros((B, T, F), np.float32)
    mask = np.zeros((B, T), bool)
    cand = np.zeros((B, T), bool)
    for b, e in enumerate(encs):
        n = len(e["cat"])
        cat[b, :n] = e["cat"]
        num[b, :n] = np.asarray(e["num"]) / 10.0
        mask[b, :n] = True
        cand[b, e["cand_first"]:e["cand_first"] + e["n_cands"]] = True
    return cat, num, mask, cand, encs


@torch.no_grad()
def student_probs(model, recs, vocab, F, dev, bs=256):
    out = []
    for i in range(0, len(recs), bs):
        cat, num, mask, cand, encs = batch_from_records(recs[i:i + bs], vocab, F)
        logits, _ = model(torch.as_tensor(cat, device=dev), torch.as_tensor(num, device=dev), torch.as_tensor(mask, device=dev))
        logits = logits.float().masked_fill(~torch.as_tensor(cand, device=dev), -1e9)
        p = F_.softmax(logits, -1).cpu().numpy()
        for b, e in enumerate(encs):
            out.append(list(p[b, e["cand_first"]:e["cand_first"] + e["n_cands"]]))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpt", required=True)
    ap.add_argument("--data", default="")
    ap.add_argument("--pairs", default="")
    ap.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    ap.add_argument("--max-test", type=int, default=20000)
    a = ap.parse_args()
    dev = torch.device(a.device)
    model, ck = load(a.ckpt, dev)
    print(f"checkpoint {a.ckpt}: config {ck['config']}, vocab {ck['vocab_hash']}, trained val top1 {ck['val']['top1']:.3f}")
    report = {}
    if a.data:
        ds = TokDataset(a.data)
        assert ds.man["vocab_hash"] == ck["vocab_hash"], "dataset and checkpoint use different vocabularies"
        te = ds.indices("test")[:a.max_test]
        m = evaluate(model, ds, te, dev, 512, dev.type == "cuda")
        report["test"] = m
        print(f"test ({m['n']}): top1 {m['top1']:.3f}  good {m['good']:.3f}  kl {m['kl']:.3f}")
        worst = sorted(m["family_top1"].items(), key=lambda kv: kv[1])[:6]
        print("  weakest families:", ", ".join(f"{k} {v:.2f}" for k, v in worst))
        b = to_dev(ds.batch(te[:512]), dev)
        for _ in range(2):
            model(b["cat"], b["num"], b["mask"])
        if dev.type == "cuda":
            torch.cuda.synchronize()
        t0 = time.time()
        for _ in range(10):
            model(b["cat"], b["num"], b["mask"])
        if dev.type == "cuda":
            torch.cuda.synchronize()
        dps = 10 * len(te[:512]) / (time.time() - t0)
        report["decisions_per_s"] = round(dps)
        print(f"speed: {dps:.0f} decisions/s at batch {len(te[:512])} on {dev} (float, not yet integer inference)")
    if a.pairs:
        import encode as enc
        import minimal_pairs as mp
        vocab = enc.Vocab.load()
        assert vocab.hash == ck["vocab_hash"], "vocabulary changed since training"
        recs = [json.loads(l) for l in open(a.pairs, encoding="utf-8")]
        probs = student_probs(model, recs, vocab, ck["F"], dev)
        pmap = {r["id"]: p for r, p in zip(recs, probs)}
        st = mp.score_pairs(recs, lambda r: pmap[r["id"]])
        ref = mp.score_pairs(recs, mp.ref_probs)
        tot_s = [sum(v[0] for v in st.values()), sum(v[1] for v in st.values())]
        tot_r = [sum(v[0] for v in ref.values()), sum(v[1] for v in ref.values())]
        print(f"minimal pairs ({tot_s[1]}): student {100 * tot_s[0] / tot_s[1]:.1f} %   reference {100 * tot_r[0] / tot_r[1]:.1f} %")
        for k in mp.PROBES:
            if k in st:
                print(f"  {k:34s} student {100 * st[k][0] / st[k][1]:5.1f} %   reference {100 * ref[k][0] / ref[k][1]:5.1f} %")
        report["pairs"] = {"student": st, "reference": ref}
    out = os.path.join(os.path.dirname(a.ckpt), "eval.json")
    json.dump(report, open(out, "w"), indent=1)
    print("->", out)


if __name__ == "__main__":
    main()
