#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
parity_stats.py : statistiques de référence du générateur Python pour la parité du port Rust (L30-L32).

Pour chaque essence (arbres et arbustes), 20 graines (0..19) à la hauteur médiane de l'essence, été, densité 1,
sans ombrage cuit : nombre de nœuds, de bouquets de feuilles, boîte de couronne (m), rayon à la base, voxels
(sans dédoublonnage de sorte), part de feuilles. Écrit un JSON lu par `cargo test -p em_gen --test parite`.

    python3 parity_stats.py ../../engine-rs/crates/em_gen/tests/data/parite_python.json
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import numpy as np            # noqa: E402
import voxel_bush as vb       # noqa: E402
import voxel_tree as vt       # noqa: E402

SEEDS = range(20)


def stats(gen, table, key, seed, height, season="summer"):
    # on réutilise generate_tree pour les voxels, et le grower pour les nœuds
    tree = gen(seed, key, height, season)
    kinds = tree.kind
    n = len(kinds)
    c = tree.coords
    box = (c.max(axis=0) - c.min(axis=0) + 1) * tree.voxel_size
    return dict(voxels=int(n), leaf=int((kinds == vt.KIND_LEAF).sum()), bark=int((kinds == vt.KIND_BARK).sum()),
                twig=int((kinds == vt.KIND_TWIG).sum()), flower=int((kinds == vt.KIND_FLOWER).sum()),
                fruit=int((kinds == vt.KIND_FRUIT).sum()),
                box=[round(float(v), 3) for v in box], base_radius=round(float(tree.meta["base_radius_m"]), 4),
                height=round(float(tree.height_m), 3))


def nodes(seed, sp, grower_cls, H, table):
    s = vt.seed_to_int(seed)
    ss = np.random.SeedSequence(s)
    r = [np.random.default_rng(x) for x in ss.spawn(6)]
    sk = grower_cls(sp, H, r[1]).run()
    return len(sk.pos), len(sk.leafy)


def main(out):
    res = {}
    for table, grower, gen, lo_hi in ((vt.SPECIES, vt.Grower, lambda s, k, h, se: vt.generate_tree(s, k, h, se, 1.0, False), None),
                                      (vb.BUSHES, vb.BushGrower, lambda s, k, h, se: vb.generate_bush(s, k, h, se, 1.0, False), None)):
        for key, sp in table.items():
            H = round((sp.h_range[0] + sp.h_range[1]) / 2, 2)
            lst = []
            for seed in SEEDS:
                nn, nl = nodes(seed, sp, grower, min(vt.MAX_HEIGHT, max(vt.MIN_HEIGHT, H)) if table is vt.SPECIES else min(2.0, max(0.3, H)), table)
                d = stats(gen, table, key, seed, H)
                d.update(nodes=nn, leafy=nl, seed=seed)
                lst.append(d)
            res[key] = dict(height=H, seeds=lst)
            print(key, H, np.mean([x["nodes"] for x in lst]), np.mean([x["voxels"] for x in lst]), flush=True)
    with open(out, "w") as f:
        json.dump(res, f, indent=1)


if __name__ == "__main__":
    main(sys.argv[1])
