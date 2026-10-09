"""Pack voxelized kit pieces into one VXB3 file (docs/interfaces.md § 2): 8^3 bricks, VoxelId 16 bits = class(9) | tint(7),
classes from engine/data/materials.csv, world axes (x east, y up, z north: z_world = -z_gltf), voxels ordered x, then z, then y."""
import sys, glob, os, struct, gzip, json, numpy as np
from scipy.cluster.vq import kmeans2
from scipy.spatial import cKDTree

VOX = sys.argv[1]; OUT = sys.argv[2]
VS_MM = int(sys.argv[3]) if len(sys.argv) > 3 else 20      # voxel edge in millimetres
R = 20.0 / VS_MM                                           # scale factor from the original 2 cm pipeline
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
            if z1 - z0 < max(2, round(2 * R)) or z1 - z0 > max(3, round(24 * R)): continue
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


# prototype class -> canonical class of materials.csv (interfaces.md § 2)
CANON = {1: 17, 2: 21, 3: 22, 4: 23, 5: 24, 6: 25, 7: 26, 8: 18, 9: 27, 10: 28, 11: 29, 12: 30, 13: 31,
         16: 1, 17: 2, 18: 20, 19: 32, 20: 5}
lut = np.zeros(1 << 16, np.uint16)
for c, k in CANON.items():
    for t in range(NT): lut[c << 7 | t] = k << 7 | t

def bits_for(k):
    for b in (1, 2, 4, 8):
        if k + 1 <= (1 << b): return b
    return None

def pack_bits(idx, b):
    per = 8 // b; idx = idx.astype(np.uint16).reshape(-1, per)
    out = np.zeros(len(idx), np.uint16)
    for j in range(per): out |= idx[:, j] << (j * b)
    return out.astype(np.uint8).tobytes()

used = sorted(c for c in CANON if pal[c].any())
out = bytearray(b'VXB3') + struct.pack('<HHHHH', 1, 1, 3, len(mods), VS_MM)   # flags bit 1: voxel size present
out += struct.pack('<H', len(used))
for c in used: out += struct.pack('<H', CANON[c]) + pal[c].tobytes()
stats = []; tagn = [0, 0, 0, 0]; wide = 0
for m in mods:
    xyz = m['xyz']; mn = xyz.min(0); dims = xyz.max(0) - mn + 1
    nb = (dims + 7) // 8
    grid = np.zeros(tuple(nb * 8), np.uint16)
    l = xyz - mn; grid[l[:, 0], l[:, 1], l[:, 2]] = m['vid']
    occ = grid > 0
    inner = occ.copy()
    inner[1:] &= occ[:-1]; inner[:-1] &= occ[1:]; inner[:, 1:] &= occ[:, :-1]; inner[:, :-1] &= occ[:, 1:]
    inner[:, :, 1:] &= occ[:, :, :-1]; inner[:, :, :-1] &= occ[:, :, 1:]
    inner[0] = inner[-1] = False; inner[:, 0] = inner[:, -1] = False; inner[:, :, 0] = inner[:, :, -1] = False
    grid[inner] = (grid[inner] & 0xFF80) | 40
    # to world axes: a pure mirror through the pivot plane, z_world = -z_gltf, so voxel cell z becomes cell -z - 1.
    # The flip is taken over the brick-padded depth D so that bricks stay whole (a reader going back to glTF axes
    # mirrors each brick in place); the grid's min corner is (mn.x, mn.y, -(mn.z + D))
    D = int(nb[2]) * 8
    nzv = np.nonzero(grid)
    vids = lut[grid[nzv]]
    wz = (D - 1) - nzv[2]
    origin = np.array([mn[0], mn[1], -(mn[2] + D)])
    dims = np.array([dims[0], dims[1], D])
    gw = np.zeros((nb[1] * 8, nb[2] * 8, nb[0] * 8), np.uint16)     # y, z, x
    gw[nzv[1], wz, nzv[0]] = vids
    g = gw.reshape(nb[1], 8, nb[2], 8, nb[0], 8).transpose(0, 2, 4, 1, 3, 5)  # by, bz, bx, y, z, x
    nm = m['name'].encode()
    out += struct.pack('<B', len(nm)) + nm + struct.pack('<iiiHHHI', *origin.tolist(), *dims.tolist(), int(nb.prod()))
    for by in range(nb[1]):
        for bz in range(nb[2]):
            for bx in range(nb[0]):
                b = g[by, bz, bx].reshape(-1)          # index = x + 8*(z + 8*y)
                u = np.unique(b)
                if len(u) == 1:
                    if u[0] == 0: out += b'\x00'; tagn[0] += 1
                    else: out += b'\x01' + struct.pack('<H', int(u[0])); tagn[1] += 1
                    continue
                ids = u[u != 0]; k = len(ids); bits = bits_for(k)
                if bits is None:
                    out += b'\x03' + b.astype('<u2').tobytes(); tagn[3] += 1; continue
                if k > 15: wide += 1
                idx = np.searchsorted(np.r_[0, ids], b)
                out += b'\x02' + struct.pack('<B', k) + ids.astype('<u2').tobytes() + pack_bits(idx, bits); tagn[2] += 1
    stats.append(dict(name=m['name'], voxels=int(len(xyz)), dims=dims.tolist(), origin=origin.tolist()))
import zlib
out += struct.pack('<I', zlib.crc32(bytes(out)) & 0xffffffff)
raw = bytes(out); gz = gzip.compress(raw, 9)
open(OUT, 'wb').write(gz)
json.dump(dict(format='VXB3', raw=len(raw), gz=len(gz), tags=tagn, bricks_over_15_colours=wide, modules=stats), open(OUT + '.json', 'w'), indent=1)
print('tags', tagn, 'wide', wide, 'raw', len(raw), 'gz', len(gz))
