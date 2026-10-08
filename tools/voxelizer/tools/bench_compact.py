"""Benchmark d'encodages compacts de voxels, sur de vraies pièces voxélisées.

    python tools/bench_compact.py --obj-dir ../village/OBJ --cache work/cache --make-cache [--big]
    python tools/bench_compact.py --cache work/cache --bench [--out work/bench.md]

Chaque ligne indique si la taille est MESURÉE (encodeur + décodeur réels, aller-retour vérifié) ou CALCULÉE
(taille exacte déduite de la structure, sans écrire le flux). On sépare GÉOMÉTRIE et ATTRIBUTS.
"""
import argparse
import gzip
import itertools
import json
import lzma
import sys
import time
import zlib
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from voxelizer import ScaleSpec, VoxelizationPipeline, VoxelizeConfig, VoxelPack
from voxelizer.compact import encode, morton3, varint_lens
from voxelizer.lattice import pack as lpack

PIECES = [("Mur_fenetre", "Wall_Plaster_Window_Wide_Flat", {}), ("Porte", "Door_1_Round", {}),
          ("Caisse", "Prop_Crate", {}), ("Toit", "Roof_RoundTile_2x1_Long", {}),
          ("Mur_ferme_seal11", "Wall_Plaster_Straight", {"seal_radius": 11}),
          ("Brique_x5", "Prop_Brick1", {"scale": 5}), ("Brique_x10", "Prop_Brick1", {"scale": 10})]


# ----------------------------------------------------------------------------- cache
def make_cache(obj_dir, cache, big):
    cache.mkdir(parents=True, exist_ok=True)
    for tag, name, kw in PIECES:
        if tag.endswith("x10") and not big:
            continue
        f = cache / f"{tag}.npz"
        if f.exists():
            continue
        t = time.perf_counter()
        cfg = VoxelizeConfig(scale=ScaleSpec(factor=kw.get("scale", 1)), seal_radius=kw.get("seal_radius", 0))
        m = VoxelizationPipeline(cfg).run(Path(obj_dir) / f"{name}.obj").model
        a = m.to_arrays()
        np.savez_compressed(f, cell=a["cell"].astype(np.int32), color=a["color"].astype(np.uint16), kind=a["kind"],
                            faces=a["faces"], material=a["material"].astype(np.int16), palette=np.array(m.palette, np.uint8))
        print(f"cache {tag:18s} {len(m):>9,} voxels  {time.perf_counter() - t:5.0f}s", flush=True)


# ----------------------------------------------------------------------------- outils
def lz(b: bytes) -> int:
    return len(lzma.compress(b, preset=3 if len(b) > 4_000_000 else 6))


def h0(v):
    _, c = np.unique(v, return_counts=True)
    p = c / c.sum()
    return float(-(p * np.log2(p)).sum())


def h1(v):
    _, v = np.unique(v, return_inverse=True)
    v = v.reshape(-1)
    k = int(v.max()) + 1
    j = np.bincount(v[:-1] * k + v[1:], minlength=k * k).reshape(k, k).astype(np.float64)
    r = j.sum(1, keepdims=True)
    nz = j > 0
    return float(-((j[nz] / j.sum()) * np.log2((j / np.maximum(r, 1))[nz])).sum())


def levels_of(m):
    return max(1, -(-int(m.max()).bit_length() // 3))


# ----------------------------------------------------------------------------- encodages CALCULÉS
def morton_gap(m, color, cb, K=64):
    gaps = np.diff(np.r_[0, m.astype(np.int64)]).astype(np.uint64)
    g_raw = int(varint_lens(gaps).sum())
    anchors = (len(m) // K + 1) * 12
    n = len(m)
    U = int(m.max()) + 1
    l = max(0, int(np.floor(np.log2(max(U / n, 1)))))
    ef = (n * l + n + (U >> l) + 64) / 8
    return {"geom": g_raw + anchors, "ef": int(ef), "geom_H0": int(h0(gaps) * n / 8) + anchors, "color": n * cb}


def column_rle(cell, color, cb):
    best = None
    for ax in range(3):
        o = [a for a in range(3) if a != ax]
        ck = (cell[:, o[0]].astype(np.int64) << 21) | cell[:, o[1]]
        od = np.lexsort((cell[:, ax], ck))
        ck, t, c = ck[od], cell[od, ax].astype(np.int64), color[od].astype(np.int64)
        new_col = np.r_[True, ck[1:] != ck[:-1]]
        new_run = new_col | (t != np.r_[-10, t[:-1]] + 1) | (c != np.r_[-1, c[:-1]])
        rs = np.flatnonzero(new_run)
        lens = np.diff(np.r_[rs, len(t)])
        ends = t[rs + lens - 1]
        gap = np.where(new_col[rs], t[rs], t[rs] - np.r_[0, ends[:-1]] - 1)
        ncol = int(new_col.sum())
        size = int(varint_lens(gap.astype(np.uint64)).sum() + varint_lens(lens.astype(np.uint64)).sum()) + cb * len(rs)
        size += ncol * 3                                       # nb de runs + index de colonne (delta)
        best = min(best or (size, ax), (size, ax))
    return best


def kv6_like(cell, kind, cb):
    """Voxlap KV6-like : voxels de SURFACE seuls, par colonne : (z, couleur) + un octet de compte par colonne."""
    s = cell[kind == 0]
    best = None
    for ax in range(3):
        o = [a for a in range(3) if a != ax]
        zb = 1 if s[:, ax].max() - s[:, ax].min() < 256 else 2
        ncols = (s[:, o[0]].max() - s[:, o[0]].min() + 1) * (s[:, o[1]].max() - s[:, o[1]].min() + 1)
        size = len(s) * (zb + cb) + int(ncols)
        best = min(best or (size, ax), (size, ax))
    return best


def svo_dag(m, color, cb):
    n, L = len(m), levels_of(m)
    keys = [m]
    uni = [np.ones(n, bool)]
    cur, cnt, mn, mx = m, np.ones(n, np.int64), color.astype(np.int64), color.astype(np.int64)
    for h in range(1, L + 1):
        g = cur >> np.uint64(3)
        st = np.r_[0, np.flatnonzero(g[1:] != g[:-1]) + 1]
        pk = g[st]
        cnt = np.add.reduceat(cnt, st); mn = np.minimum.reduceat(mn, st); mx = np.maximum.reduceat(mx, st)
        keys.append(pk); uni.append((cnt == 8 ** h) & (mn == mx)); cur = pk
    n_int = sum(int((~u).sum()) for u in uni[1:])
    n_leaf = 1 if uni[L][0] else 0
    for h in range(L):
        par = np.searchsorted(keys[h + 1], keys[h] >> np.uint64(3))
        n_leaf += int((uni[h] & ~uni[h + 1][par]).sum())
    svo = 6 * n_int + cb * n_leaf                              # masque(2) + pointeur(4) par nœud interne + 1 couleur/feuille
    # DAG de géométrie seule : nœuds identiques fusionnés ; couleurs à part dans l'ordre de Morton
    cur, ids = m, np.ones(n, np.int64)
    dag, nodes = 0, []
    for h in range(1, L + 1):
        g = cur >> np.uint64(3)
        newg = np.r_[False, g[1:] != g[:-1]]
        gi = np.cumsum(newg)
        mat = np.zeros((int(gi[-1]) + 1, 8), np.int64)
        mat[gi, (cur & np.uint64(7)).astype(np.int64)] = ids
        u, inv = np.unique(mat, axis=0, return_inverse=True)
        dag += len(u) + (4 * int((u > 0).sum()) if h >= 2 else 0)
        nodes.append(len(u))
        cur, ids = g[np.r_[True, newg[1:]]], inv.reshape(-1) + 1
    return {"svo_nodes_int": n_int, "svo_leaves": n_leaf, "svo": svo, "dag_geom": dag, "dag_nodes": sum(nodes),
            "dag_attr": n * cb + 4 * sum(nodes)}


def tiles2d(cell, color, cb, T=8):
    best = None
    dims = cell.max(0) + 1
    if int(np.prod(dims)) > 60_000_000:
        return None
    for ax in range(3):
        o = [a for a in range(3) if a != ax]
        vol = np.zeros((dims[ax], dims[o[0]], dims[o[1]]), np.uint16)
        vol[cell[:, ax], cell[:, o[0]], cell[:, o[1]]] = color.astype(np.uint16) + 1
        pad = [(0, 0), (0, -dims[o[0]] % T), (0, -dims[o[1]] % T)]
        v = np.pad(vol, pad)
        s, a, b = v.shape
        t = v.reshape(s, a // T, T, b // T, T).transpose(0, 1, 3, 2, 4).reshape(-1, T * T)
        nz = t.any(axis=1)
        t = np.ascontiguousarray(t[nz])
        uniq = len(np.unique(t.view(np.dtype((np.void, t.dtype.itemsize * T * T)))))
        bits = max(1, int(np.ceil(np.log2(uniq + 1))))
        size = uniq * T * T * cb + (len(t) * bits + 7) // 8 + (s * (a // T) * (b // T) + 7) // 8     # + carte d'occupation 1 bit/tuile
        best = min(best or (size, ax, uniq, len(t)), (size, ax, uniq, len(t)))
    return best


def chain_dfs(cell, dims):
    N = len(cell)
    keys = lpack(cell[:, 0], cell[:, 1], cell[:, 2])
    order = np.argsort(keys)
    keys = keys[order]
    offs = sorted((d for d in itertools.product((-1, 0, 1), repeat=3) if d != (0, 0, 0)), key=lambda d: sum(map(abs, d)))
    nbr = np.empty((N, 26), np.int32)
    for j, d in enumerate(offs):
        nk = keys + ((d[0] << 42) + (d[1] << 21) + d[2])
        pos = np.minimum(np.searchsorted(keys, nk), N - 1)
        nbr[:, j] = np.where(keys[pos] == nk, pos, -1)
    vis = np.zeros(N, bool)
    syms, stack, nxt, jumps = [], [], 0, 0
    while True:
        if not stack:
            while nxt < N and vis[nxt]:
                nxt += 1
            if nxt >= N:
                break
            vis[nxt] = True; stack.append(nxt); syms.append(27); jumps += 1
        u = stack[-1]
        row = nbr[u]
        ok = (row >= 0) & ~vis[np.maximum(row, 0)]
        if ok.any():
            j = int(ok.argmax()); v = int(row[j]); vis[v] = True; stack.append(v); syms.append(j)
        else:
            stack.pop(); syms.append(26)
    syms = np.array(syms)
    jump_bits = jumps * 3 * int(np.ceil(np.log2(max(dims))))
    bits = len(syms) * h1(syms) + jump_bits
    return {"bits": bits, "symbols": len(syms), "jumps": jumps, "H0": h0(syms), "H1": h1(syms)}


# ----------------------------------------------------------------------------- banc d'essai
def bench_piece(tag, d):
    cell, color, kind, mat = d["cell"].astype(np.int64), d["color"].astype(np.int64), d["kind"], d["material"].astype(np.int64)
    N = len(cell)
    cell = cell - cell.min(0)
    dims = cell.max(0) + 1
    cb = 1 if color.max() < 256 else 2
    rows = []

    def add(name, nbytes, how, note=""):
        rows.append((name, int(nbytes), how, note))

    # --- références
    sub = slice(0, min(N, 150_000))
    r = np.column_stack([np.arange(N)[sub], cell[sub], color[sub], kind[sub], d["faces"][sub], mat[sub]]).tolist()
    js = len(gzip.compress(json.dumps(r, separators=(",", ":")).encode(), 6))
    add("JSON .gz (export actuel)", js * (N / min(N, 150_000)), "mesuré" if N <= 150_000 else "extrapolé")
    zb = 2 if dims.max() > 255 else 1
    cols = b"".join(a.astype(f"<u{zb}").tobytes() for a in (cell[:, 0], cell[:, 1], cell[:, 2])) + color.astype(f"<u{cb}").tobytes()
    add("liste x,y,z,couleur brute", N * (3 * zb + cb), "calculé")
    add("  + lzma", lz(cols), "mesuré")
    dense = int(np.prod(dims)) * cb
    add("grille dense (octet/cellule)", dense, "calculé", f"boîte {tuple(int(x) for x in dims)}")
    if int(np.prod(dims)) <= 20_000_000:
        vol = np.zeros(tuple(dims), "<u1" if cb == 1 else "<u2"); vol[tuple(cell.T)] = color + 1
        add("  + lzma", lz(vol.tobytes()), "mesuré")

    # --- Morton + écarts (positions relatives dans un ordre canonique)
    m = morton3(cell[:, 0], cell[:, 1], cell[:, 2])
    o = np.argsort(m)
    ms, cs = m[o], color[o]
    g = morton_gap(ms, cs, cb)
    add("Morton: écarts varint + ancres/64 (géométrie)", g["geom"], "calculé")
    add("  Elias-Fano (géométrie, borne sans ancres)", g["ef"], "calculé")
    add("  entropie ordre 0 des écarts (borne)", g["geom_H0"], "calculé")
    # --- colonnes RLE / KV6
    size, ax = column_rle(cell, color, cb)
    add(f"colonnes RLE (axe {'xyz'[ax]}) géom+couleur", size, "calculé")
    ks, ax = kv6_like(cell, kind, cb)
    add(f"KV6-like surface seule (axe {'xyz'[ax]})", ks, "calculé", "intérieur à reconstruire")
    # --- SVO / DAG
    sd = svo_dag(ms, cs, cb)
    add("SVO pointeurs+couleur feuilles (collapse uniforme)", sd["svo"], "calculé", f"{sd['svo_nodes_int']:,} nœuds, {sd['svo_leaves']:,} feuilles")
    add("SVDAG géométrie seule", sd["dag_geom"], "calculé", f"{sd['dag_nodes']:,} nœuds uniques")
    add("  + couleurs (flux Morton) + index", sd["dag_attr"], "calculé", "total attributs; ajouter la ligne au-dessus")
    # --- tuiles 2D (plaques)
    for T in (4, 8):
        t = tiles2d(cell, color, cb, T)
        if t:
            add(f"plaques 2D {T}x{T} dédup (axe {'xyz'[t[1]]}) exact", t[0], "calculé", f"{t[2]:,} tuiles uniques / {t[3]:,}")
    # --- bricks VXP (mesuré + aller-retour)
    surf = kind == 0
    for B in (4, 8, 16):
        if B == 4 and N > 600_000:
            continue
        t0 = time.perf_counter()
        data = encode(*cell.T, color, mat, brick=B)
        te = time.perf_counter() - t0
        p = VoxelPack(data)
        add(f"VXP bricks {B}³ couleur+matériau", len(data), "mesuré", f"{len(p._keys):,} bricks, {len(p._off) - 1:,} charges uniques, encodage {te:.1f}s")
        if B == 8:
            add("  + lzma sur le fichier", lz(data), "mesuré")
            geo = len(encode(*cell.T, np.zeros(N, np.int64), None, brick=8))
            col = len(encode(*cell.T, color, None, brick=8))
            add("  dont géométrie seule (VXP 8³)", geo, "mesuré")
            add("  dont couleur seule", col - geo, "mesuré")
            add("  dont matériau", len(data) - col, "mesuré")
            ds = encode(*cell[surf].T, color[surf], mat[surf], brick=8, shell_only=True)
            add("VXP 8³ coque seule (intérieur reconstruit)", len(ds), "mesuré")
            add("  + lzma", lz(ds), "mesuré")
    # --- chaîne relative (idée utilisateur)
    cls = np.bincount((cell[:, 0] & 1) + 2 * (cell[:, 1] & 1) + 4 * (cell[:, 2] & 1), minlength=8)
    cov = max(cls[c] + cls[c ^ 7] for c in range(8)) / N
    notes = [f"chaîne littérale ±1 : couverture max {cov * 100:.0f} % des voxels (parité)"]
    ns = int(surf.sum())
    if ns <= 120_000:
        cd = chain_dfs(cell[surf], dims)
        add("chaîne 26-voisins DFS (surface, géométrie)", cd["bits"] / 8, "mesuré", f"{cd['symbols']:,} symboles, {cd['jumps']} sauts, H1={cd['H1']:.2f} b/sym; sans index d'accès")
    else:
        notes.append("chaîne DFS non évaluée (> 120 000 voxels de surface)")
    # --- flux de couleur en ordre de Morton
    runs = int(1 + (cs[1:] != cs[:-1]).sum())
    fc = {"brut": N * cb, "H0": h0(cs) * N / 8, "H1": h1(cs) * N / 8, "RLE": runs * (cb + 1), "lzma": lz(cs.astype(f"<u{cb}").tobytes())}
    # --- accès aléatoire
    rng = np.random.default_rng(0)
    occ = cell[rng.integers(0, N, 1500)]
    rnd = (rng.random((1500, 3)) * dims).astype(np.int64)
    qs = [tuple(map(int, q)) for q in np.vstack([occ, rnd])]
    p8 = VoxelPack(encode(*cell.T, color, mat, brick=8))
    t0 = time.perf_counter(); [p8.get(*q) for q in qs]; cold = (time.perf_counter() - t0) / len(qs) * 1e6
    t0 = time.perf_counter(); [p8.get(*q) for q in qs]; warm = (time.perf_counter() - t0) / len(qs) * 1e6
    return {"N": N, "dims": dims.tolist(), "interior": int((~surf).sum()), "rows": rows, "notes": notes,
            "color_stream": fc, "get_us_cold": cold, "get_us_warm": warm}


def render(tag, r):
    N = r["N"]
    base = next(b for n, b, *_ in r["rows"] if n.startswith("JSON"))
    out = [f"\n### {tag} : {N:,} voxels (dont {r['interior']:,} intérieur), boîte {tuple(r['dims'])}\n",
           "| encodage | octets | bits/voxel | vs JSON .gz | statut |", "|---|---:|---:|---:|---|"]
    for name, b, how, note in r["rows"]:
        out.append(f"| {name} | {b:,} | {b * 8 / N:.2f} | ×{base / max(b, 1):.1f} | {how}{'; ' + note if note else ''} |")
    fc = r["color_stream"]
    out.append(f"\nFlux couleur (ordre Morton), octets : brut {fc['brut']:,} · RLE {fc['RLE']:,} · entropie H0 {fc['H0']:,.0f} · "
               f"H1 {fc['H1']:,.0f} · lzma {fc['lzma']:,}.  Accès aléatoire VXP 8³ (Python, µs/requête) : à froid {r['get_us_cold']:.0f}, à chaud {r['get_us_warm']:.0f}.")
    out += [f"- {n}" for n in r["notes"]]
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--obj-dir", default="../village/OBJ"); ap.add_argument("--cache", default="work/cache")
    ap.add_argument("--make-cache", action="store_true"); ap.add_argument("--bench", action="store_true")
    ap.add_argument("--big", action="store_true"); ap.add_argument("--only", default=""); ap.add_argument("--out", default="")
    a = ap.parse_args()
    cache = Path(a.cache)
    if a.make_cache:
        make_cache(a.obj_dir, cache, a.big)
    if a.bench:
        md, allr = [], {}
        for tag, *_ in PIECES:
            f = cache / f"{tag}.npz"
            if not f.exists() or a.only not in tag:
                continue
            t = time.perf_counter()
            r = bench_piece(tag, dict(np.load(f)))
            allr[tag] = r
            s = render(tag, r); print(s, f"\n(banc {time.perf_counter() - t:.0f}s)", flush=True); md.append(s)
        if a.out:
            Path(a.out).write_text("\n".join(md)); json.dump(allr, open(Path(a.out).with_suffix(".json"), "w"), default=str)


if __name__ == "__main__":
    main()
