#!/usr/bin/env python3
"""build_dataset.py - builds a training set for the student Transformer, without any API.

  situations (generate_states 0.4)  ->  labels (reference_decider, later the teacher)  ->  tokens (encode tok-1)  ->  binary shards

Output directory (default /mnt/project-files/donnees-transformer/<name>/):
  manifest.json          format, vocabulary hash, layout, counts per split and family, seeds, label sources
  tok_cat.i16            int16 [n_tokens, 9]   type, 5 categories, 3 pointers (pointer = index inside its own sequence)
  tok_num.i8             int8  [n_tokens, 33]  scalar slots (-10..10)
  samples.i32            int32 [n, 8]          tok_start, n_tok, cand_first, n_cands, lab_start, family_id, split(0 train,1 val,2 test), source(0 ref,1 teacher,2 sim)
  lab_score.i8           int8  [n_labels]      score 0..4 per candidate (teacher scale)
  lab_soft.u16           uint16[n_labels]      soft target x 10000
  lab_util.i16           int16 [n_labels]      reference utility x 1000 (lets you change the softmax temperature later)
  drivers.u16            uint16[n]             bit mask over the 10 drivers of the best option
  meta.jsonl.gz          one line per sample: id, family, split, source, drivers
  situations.jsonl.gz    the canonical records (only with --keep-json): what the teacher will label, and the oracle input for the C++ port
All little-endian. Read with dataset_reader.py (numpy) or train_student.py.

  python3 build_dataset.py --n 60000 --name ref_v04_60k --workers 4
  python3 build_dataset.py --n 2000 --name smoke --out /tmp/x --keep-json
  python3 build_dataset.py --n 300000 --name mix --teacher-labels data/dataset.jsonl     # adds the teacher's labels (source=1), later
"""
import argparse
import array
import gzip
import hashlib
import json
import multiprocessing as mp
import os
import random
import sys
import time
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import encode as enc                    # noqa: E402
import generate_states as gs            # noqa: E402
import reference_decider as rd          # noqa: E402

DEFAULT_ROOT = "/mnt/project-files/donnees-transformer"
DRV = {d: i for i, d in enumerate(rd.DRIVERS)}


def split_of(sid):
    """Same rule as teacher_run.split_of: 5 % test, 5 % val, by hash of the id (stable across tools)."""
    h = int(hashlib.md5(sid.encode()).hexdigest(), 16) % 100
    return 2 if h < 5 else 1 if h < 10 else 0


def make_shard(args):
    """args = (shard, n, seed, max_ent, max_ev, labelled) ; with `labelled` (a list of teacher-labelled records from
    teacher_run.py export) the shard encodes those records instead of generating new ones."""
    shard, n, seed, max_ent, max_ev, labelled = args
    vocab = enc.Vocab.load()
    rng = random.Random(seed * 1000003 + shard)
    world_seed = (seed * 7919 + shard) % 2 ** 31
    fams = dict(gs.FAMILIES)
    names, ws = zip(*fams.items())
    cat, num, smp, ls, lsoft, lutil, drv, meta, js = (array.array("h"), array.array("b"), array.array("i"), array.array("b"),
                                                      array.array("H"), array.array("h"), array.array("H"), [], [])
    viol, fam_n, skipped = Counter(), Counter(), 0
    tok = lab = 0
    for i in range(n):
        if labelled:
            lr = labelled[i]
            rec = {"id": ("t" if "scores" in lr else "") + lr["id"], "family": lr.get("family", "sim"), "state": lr["state"],
                   "cands": lr["cands"]}
            rec["view"] = gs.view_of_state(rec["state"], rec["cands"])
            rec["text"] = gs.view_text(rec["view"])
            t_lab = lr if "scores" in lr else None        # sim trajectories carry no teacher scores: the reference labels them
        else:
            fam = rng.choices(names, weights=ws)[0]
            rec = gs.gen_situation(rng, i, fam, world_seed, max_ent, max_ev, False)
            rec["id"] = f"s{shard:03d}{i:06d}"
            t_lab = None
        bad = gs.validate(rec)
        if bad:
            for b in bad:
                viol[b] += 1
            skipped += 1
            continue
        out = rd.decide(rec)
        try:
            e = enc.encode(rec, vocab)
        except ValueError:
            skipped += 1
            continue
        if t_lab is not None and len(t_lab["scores"]) == len(rec["cands"]):
            scores, soft, src = t_lab["scores"], t_lab["soft"], 1
            dr = t_lab.get("drivers") or out["drivers"]
        else:
            scores, soft, src, dr = out["scores"], out["soft"], 2 if labelled else 0, out["drivers"]
        sp = split_of(rec["id"])
        for row in e["cat"]:
            cat.extend(row)
        for row in e["num"]:
            num.extend(row)
        fam_id = list(gs.FAMILIES).index(rec["family"]) if rec["family"] in gs.FAMILIES else len(gs.FAMILIES)   # last id = other/sim
        smp.extend([tok, len(e["cat"]), e["cand_first"], e["n_cands"], lab, fam_id, sp, src])
        ls.extend(scores)
        lsoft.extend(min(10000, int(round(x * 10000))) for x in soft)
        lutil.extend(max(-32000, min(32000, int(round(u * 1000)))) for u in out["util"])
        mask = 0
        for d in dr:
            if d in DRV:
                mask |= 1 << DRV[d]
        drv.append(mask)
        tok += len(e["cat"])
        lab += e["n_cands"]
        fam_n[rec["family"]] += 1
        meta.append({"id": rec["id"], "family": rec["family"], "split": ["train", "val", "test"][sp], "source": ["ref", "teacher", "sim"][src],
                     "drivers": dr})
        js.append(rec)
    return {"shard": shard, "cat": cat.tobytes(), "num": num.tobytes(), "smp": smp.tolist(), "ls": ls.tobytes(),
            "lsoft": lsoft.tobytes(), "lutil": lutil.tobytes(), "drv": drv.tobytes(), "meta": meta, "json": js,
            "viol": dict(viol), "fam": dict(fam_n), "skipped": skipped, "n_tok": tok, "n_lab": lab}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=60000)
    ap.add_argument("--name", default="ref_v04")
    ap.add_argument("--out", default="", help="output dir (default /mnt/project-files/donnees-transformer/<name>)")
    ap.add_argument("--seed", type=int, default=20261008)
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    ap.add_argument("--shard-size", type=int, default=5000)
    ap.add_argument("--max-entities", type=int, default=4)
    ap.add_argument("--max-events", type=int, default=2)
    ap.add_argument("--keep-json", action="store_true", help="also write the canonical situations (big: ~6 KB each)")
    ap.add_argument("--teacher-labels", default="", help="dataset.jsonl from teacher_run.py export; added with source=1")
    ap.add_argument("--sim-trajectories", nargs="*", default=[],
                    help="JSONL decisions from the headless simulation (fields id, family, state, cands); added with source=2, labelled by the reference")
    a = ap.parse_args()
    out = a.out or os.path.join(DEFAULT_ROOT, a.name)
    os.makedirs(out, exist_ok=True)
    jobs, left, sh = [], a.n, 0
    while left > 0:
        k = min(a.shard_size, left)
        jobs.append((sh, k, a.seed, a.max_entities, a.max_events, None))
        left -= k
        sh += 1
    extra = []
    if a.teacher_labels:                       # teacher-labelled situations are ADDED (source=1), with the reference set
        extra += [json.loads(l) for l in open(a.teacher_labels, encoding="utf-8")]
    for path in a.sim_trajectories:            # states really visited by the simulation (source=2)
        extra += [json.loads(l) for l in open(path, encoding="utf-8")]
    if extra:
        lab = extra
        lab = [r for r in lab if r.get("state", {}).get("village") is not None]     # 0.4 records only
        print(f"added situations (teacher or simulation): {len(lab)}")
        for i in range(0, len(lab), a.shard_size):
            part = lab[i:i + a.shard_size]
            jobs.append((sh, len(part), a.seed, a.max_entities, a.max_events, part))
            sh += 1
    t0 = time.time()
    files = {k: open(os.path.join(out, f), "wb") for k, f in (("cat", "tok_cat.i16"), ("num", "tok_num.i8"), ("smp", "samples.i32"),
                                                                ("ls", "lab_score.i8"), ("lsoft", "lab_soft.u16"),
                                                                ("lutil", "lab_util.i16"), ("drv", "drivers.u16"))}
    meta_f = gzip.open(os.path.join(out, "meta.jsonl.gz"), "wt", encoding="utf-8")
    json_f = gzip.open(os.path.join(out, "situations.jsonl.gz"), "wt", encoding="utf-8") if a.keep_json else None
    tok_base = lab_base = 0
    tot_viol, tot_fam, skipped, splits, sources = Counter(), Counter(), 0, Counter(), Counter()
    n_ok = 0
    with mp.Pool(a.workers) as pool:
        for r in pool.imap(make_shard, jobs):           # imap keeps shard order: the file is deterministic
            files["cat"].write(r["cat"])
            files["num"].write(r["num"])
            smp = array.array("i", r["smp"])
            for j in range(0, len(smp), 8):
                smp[j] += tok_base
                smp[j + 4] += lab_base
            files["smp"].write(smp.tobytes())
            for k in ("ls", "lsoft", "lutil", "drv"):
                files[k].write(r[k])
            for m in r["meta"]:
                meta_f.write(json.dumps(m, separators=(",", ":")) + "\n")
                splits[m["split"]] += 1
                sources[m["source"]] += 1
            if json_f:
                for rec in r["json"]:
                    json_f.write(json.dumps(rec, separators=(",", ":"), ensure_ascii=False) + "\n")
            tok_base += r["n_tok"]
            lab_base += r["n_lab"]
            n_ok += len(r["meta"])
            tot_viol.update(r["viol"])
            tot_fam.update(r["fam"])
            skipped += r["skipped"]
            print(f"  shard {r['shard']:3d}: {len(r['meta'])} situations  ({time.time() - t0:.0f} s)", flush=True)
    for f in files.values():
        f.close()
    meta_f.close()
    if json_f:
        json_f.close()
    vocab = json.load(open(enc.VOCAB_FILE))
    manifest = {
        "dataset": a.name, "format": enc.FORMAT, "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "generator": gs.VERSION, "reference": rd.VERSION, "vocab_hash": vocab["hash"], "vocab_size": vocab["size"],
        "seed": a.seed, "shard_size": a.shard_size, "max_entities": a.max_entities, "max_events": a.max_events,
        "n": n_ok, "n_tokens": tok_base, "n_labels": lab_base, "skipped": skipped, "violations": dict(tot_viol),
        "splits": dict(splits), "label_sources": dict(sources), "families": list(gs.FAMILIES) + ["other"], "family_counts": dict(tot_fam),
        "drivers": list(rd.DRIVERS), "byteorder": sys.byteorder,
        "arrays": {"tok_cat.i16": ["int16", [tok_base, enc.NCAT]], "tok_num.i8": ["int8", [tok_base, enc.F]],
                   "samples.i32": ["int32", [n_ok, 8]], "lab_score.i8": ["int8", [lab_base]], "lab_soft.u16": ["uint16", [lab_base]],
                   "lab_util.i16": ["int16", [lab_base]], "drivers.u16": ["uint16", [n_ok]]},
        "samples_fields": ["tok_start", "n_tok", "cand_first", "n_cands", "lab_start", "family_id", "split", "source"],
        "layout": enc.layout_table(),
        "softmax_temperature": rd.TEMP, "score_step": rd.STEP,
    }
    json.dump(manifest, open(os.path.join(out, "manifest.json"), "w"), indent=1)
    import shutil
    shutil.copy(enc.VOCAB_FILE, os.path.join(out, "model_vocab.json"))
    size = sum(os.path.getsize(os.path.join(out, f)) for f in os.listdir(out))
    print(f"wrote {n_ok} situations ({tok_base} tokens, {lab_base} labelled options) to {out}  [{size / 1e6:.0f} MB, {time.time() - t0:.0f} s]")
    print(f"splits {dict(splits)}  label sources {dict(sources)}  skipped {skipped}  violations {dict(tot_viol) or 'none'}")


if __name__ == "__main__":
    main()
