"""dataset_reader.py - reads a dataset written by ai/npc_pipeline/build_dataset.py (numpy, memory-mapped).

    from dataset_reader import TokDataset
    ds = TokDataset("/mnt/project-files/donnees-transformer/ref_v04_300k")
    batch = ds.batch(ds.indices("train")[:64])      # dict of numpy arrays, padded to the longest sequence
"""
import gzip
import json
import os

import numpy as np

SPLITS = {"train": 0, "val": 1, "test": 2}


class TokDataset:
    def __init__(self, root):
        self.root = root
        self.man = json.load(open(os.path.join(root, "manifest.json")))
        assert self.man["format"] == "tok-1", self.man["format"]
        A = self.man["arrays"]

        def mm(name):
            dt, shape = A[name]
            return np.memmap(os.path.join(root, name), dtype=np.dtype(dt).newbyteorder("<"), mode="r", shape=tuple(shape))
        self.cat = mm("tok_cat.i16")
        self.num = mm("tok_num.i8")
        self.smp = mm("samples.i32")
        self.score = mm("lab_score.i8")
        self.soft = mm("lab_soft.u16")
        self.util = mm("lab_util.i16")
        self.drv = mm("drivers.u16")
        self.n = self.man["n"]
        self.vocab_size = self.man["vocab_size"]
        self.F = self.man["layout"]["F"]

    def indices(self, split):
        return np.nonzero(self.smp[:, 6] == SPLITS[split])[0]

    def families(self):
        return self.man["families"]

    def meta(self):
        with gzip.open(os.path.join(self.root, "meta.jsonl.gz"), "rt") as f:
            return [json.loads(l) for l in f]

    def batch(self, idx, temperature=None):
        """Padded batch. Targets: soft (as stored, or re-derived from utilities at `temperature`), scores, drivers."""
        s = self.smp[np.asarray(idx)]
        T = int(s[:, 1].max())
        B = len(idx)
        cat = np.zeros((B, T, 9), np.int64)
        cat[..., 6:9] = -1
        num = np.zeros((B, T, self.F), np.float32)
        mask = np.zeros((B, T), bool)
        cand = np.zeros((B, T), bool)
        soft = np.zeros((B, T), np.float32)
        score = np.full((B, T), -1, np.int64)
        drv = np.zeros((B, 10), np.float32)
        for b, (t0, nt, cf, nc, l0, fam, sp, src) in enumerate(s):
            cat[b, :nt] = self.cat[t0:t0 + nt]
            num[b, :nt] = self.num[t0:t0 + nt] / 10.0
            mask[b, :nt] = True
            cand[b, cf:cf + nc] = True
            if temperature is None or src == 1:
                soft[b, cf:cf + nc] = self.soft[l0:l0 + nc] / 10000.0
            else:
                u = self.util[l0:l0 + nc] / 1000.0
                e = np.exp((u - u.max()) / temperature)
                soft[b, cf:cf + nc] = e / e.sum()
            score[b, cf:cf + nc] = self.score[l0:l0 + nc]
            m = int(self.drv[idx[b]])
            for k in range(10):
                drv[b, k] = (m >> k) & 1
        return {"cat": cat, "num": num, "mask": mask, "cand": cand, "soft": soft, "score": score, "drivers": drv,
                "family": s[:, 5].astype(np.int64), "source": s[:, 7].astype(np.int64)}
