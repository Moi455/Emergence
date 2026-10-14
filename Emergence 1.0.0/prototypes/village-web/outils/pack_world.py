"""Pack voxelized kit pieces into one VXB1 file: 8^3 bricks, VoxelId 16 bits = class(9) | tint(7)."""
import sys, glob, os, struct, gzip, json, numpy as np
from scipy.cluster.vq import kmeans2
from scipy.spatial import cKDTree

VOX = sys.argv[1]; OUT = sys.argv[2]
CLASSES = ['air', 'plaster', 'wood', 'woodwear', 'rocktrim', 'brick', 'redbrick', 'masonry', 'tiles', 'iron',
           'glass', 'vine', 'leaves', 'bark', 'r14', 'r15', 'grass', 'dirt', 'stone', 'cobble', 'gravel']
MAT2CLASS = {'MI_Plaster': 1, 'MI_WoodTrim': 2, 'MI_WoodTrim_Wear': 3, 'MI_RockTrim': 4, 'MI_Brick': 5,
             'MI_RedBrick': 6, 'MI_UnevenBrick': 7, 'MI_RoundTiles': 8, 'MI_MetalOrnaments': 9,
             'MI_WindowGlass': 10, 'MI_Vine': 11}
NT = 128
rng = np.random.default_rng(7)

mods = []
for f in sorted(glob.glob(os.path.join(VOX, '*.npz'))):
    name = os.path.basename(f)[:-4]
    d = np.load(f)
    xyz = d['xyz'].astype(np.int32); rgb = d['rgb'].astype(np.float32)
    cls = np.array([MAT2CLASS.get(m, 2) for m in d['mat']], np.int32)
    if name.startswith('Wall_') and not name.startswith('Wall_BottomCover'):
        # kit walls are two open sheets: fill the core between them, column by column along z
        mn = xyz.min(0); key = (xyz[:, 0] - mn[0]) * 100000 + (xyz[:, 1] - mn[1])
        order = np.lexsort((xyz[:, 2], key)); k = key[order]
        starts = np.r_[0, np.nonzero(k[1:] != k[:-1])[0] + 1]; ends = np.r_[starts[1:], len(k)]
        occ = set(map(tuple, xyz.tolist()))
        add_xyz, add_rgb, add_cls = [], [], []
        for s, e in zip(starts, ends):
            i0, i1 = order[s], order[e - 1]
            z0, z1 = xyz[i0, 2], xyz[i1, 2]
            if z1 - z0 < 2 or z1 - z0 > 24: continue
            x, y = xyz[i0, 0], xyz[i0, 1]
            for z in range(z0 + 1, z1):
                if (x, y, z) in occ: continue
                src = i0 if (z - z0) < (z1 - z) else i1
                add_xyz.append((x, y, z)); add_rgb.append(rgb[src] * 0.82); add_cls.append(cls[src])
        if add_xyz:
            xyz = np.vstack([xyz, np.array(add_xyz, np.int32)]); rgb = np.vstack([rgb, np.array(add_rgb, np.float32)])
            cls = np.r_[cls, np.array(add_cls, np.int32)]
    mods.append(dict(name=name, xyz=xyz, rgb=rgb, cls=cls))
    print(name, len(xyz), file=sys.stderr)

# per-class tint palettes (k-means in sRGB on a subsample)
pal = np.zeros((len(CLASSES), NT, 3), np.uint8)
tints = [None] * len(mods)
for c in range(1, len(CLASSES)):
    cols = [m['rgb'][m['cls'] == c] for m in mods]
    allc = np.vstack([x for x in cols if len(x)] or [np.zeros((0, 3), np.float32)])
    if len(allc) == 0: continue
    if c == 11:   # vine: kit texture carries no colour, use leaf greens
        g = np.linspace(0, 1, NT)[:, None]
        pal[c] = np.clip(np.hstack([40 + 50 * g, 80 + 70 * g, 25 + 25 * g]), 0, 255).astype(np.uint8)
        continue
    sub = allc[rng.choice(len(allc), min(len(allc), 150000), replace=False)]
    k = min(NT, max(2, len(np.unique(sub.astype(np.int32), axis=0))))
    cent, _ = kmeans2(sub, k, minit='++', seed=7, iter=15)
    cent = cent[np.argsort(cent.sum(1))]
    pal[c, :k] = np.clip(np.rint(cent), 0, 255).astype(np.uint8)
    pal[c, k:] = pal[c, k - 1]
    tree = cKDTree(cent)
    for i, m in enumerate(mods):
        sel = m['cls'] == c
        if sel.any():
            if tints[i] is None: tints[i] = np.zeros(len(m['cls']), np.int32)
            tints[i][sel] = tree.query(m['rgb'][sel])[1]
for i, m in enumerate(mods):
    t = tints[i] if tints[i] is not None else np.zeros(len(m['cls']), np.int32)
    vine = m['cls'] == 11
    if vine.any():
        h = (m['xyz'][vine] * np.array([73856093, 19349663, 83492791])).sum(1)
        t[vine] = (h ^ (h >> 7)) % NT
    m['vid'] = (m['cls'] << 7 | t).astype(np.uint16)

def bits_for(k):
    for b in (1, 2, 4, 8):
        if k <= (1 << b): return b
    return 16

nlossy = [0]
out = bytearray(b'VXB2'); out += struct.pack('<HH', len(CLASSES), NT); out += pal.tobytes()
out += struct.pack('<H', len(mods))
stats = []
for m in mods:
    xyz = m['xyz']; mn = xyz.min(0); dims = xyz.max(0) - mn + 1
    nb = (dims + 7) // 8
    grid = np.zeros(tuple(nb * 8), np.uint16)   # x, y, z
    l = xyz - mn; grid[l[:, 0], l[:, 1], l[:, 2]] = m['vid']
    # buried voxels (6 solid neighbours) never show their own colour until dug: give them one tint per class
    occ = grid > 0
    inner = occ.copy()
    inner[1:] &= occ[:-1]; inner[:-1] &= occ[1:]; inner[:, 1:] &= occ[:, :-1]; inner[:, :-1] &= occ[:, 1:]
    inner[:, :, 1:] &= occ[:, :, :-1]; inner[:, :, :-1] &= occ[:, :, 1:]
    inner[0] = inner[-1] = False; inner[:, 0] = inner[:, -1] = False; inner[:, :, 0] = inner[:, :, -1] = False
    grid[inner] = (grid[inner] & 0xFF80) | 40
    g = grid.reshape(nb[0], 8, nb[1], 8, nb[2], 8).transpose(4, 2, 0, 5, 3, 1)  # bz,by,bx, z,y,x
    nm = m['name'].encode()
    out += struct.pack('<B', len(nm)) + nm + struct.pack('<hhhHHH', *mn.tolist(), *dims.tolist())
    ne = nu = nmx = 0
    for bz in range(nb[2]):
        for by in range(nb[1]):
            for bx in range(nb[0]):
                b = g[bz, by, bx].reshape(-1)   # index = x + 8*(y + 8*z)
                u = np.unique(b)
                if len(u) == 1:
                    if u[0] == 0: out += b'\x00'; ne += 1
                    else: out += b'\x01' + struct.pack('<H', int(u[0])); nu += 1
                    continue
                nmx += 1
                nz = u[u != 0]
                if len(nz) > 15:
                    # local palette limited to 15 colours: keep the most frequent ids, map the rest to the closest
                    vals, cnt = np.unique(b[b != 0], return_counts=True)
                    keep = vals[np.argsort(-cnt)[:15]]
                    kc, kt = (keep >> 7).astype(np.int32), (keep & 127).astype(np.int32)
                    lut = {}
                    for v in vals:
                        if v in keep: continue
                        c, t = int(v) >> 7, int(v) & 127
                        cost = np.where(kc == c, 0, 1000) + np.abs(kt - t)
                        lut[int(v)] = keep[int(np.argmin(cost))]
                    b = b.copy()
                    for v, w in lut.items(): b[b == v] = w
                    nz = np.sort(keep); nlossy[0] += 1
                pal = np.r_[0, nz].astype(np.uint16)
                idx = np.searchsorted(pal, b).astype(np.uint8)       # 0 = air
                packed = (idx[0::2] | (idx[1::2] << 4)).astype(np.uint8)   # x even in low nibble
                out += b'\x02' + struct.pack('<B', len(nz)) + nz.astype('<u2').tobytes() + packed.tobytes()
    stats.append(dict(name=m['name'], voxels=int(len(xyz)), dims=dims.tolist(), empty=ne, uniform=nu, mixed=nmx))
raw = bytes(out)
gz = gzip.compress(raw, 9)
open(OUT, 'wb').write(gz)
json.dump(dict(raw=len(raw), gz=len(gz), modules=stats, classes=CLASSES), open(OUT + '.json', 'w'), indent=1)
print('lossy bricks', nlossy[0]); print('raw', len(raw), 'gz', len(gz), 'voxels', sum(s['voxels'] for s in stats), 'mixed', sum(s['mixed'] for s in stats))
