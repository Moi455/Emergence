"""VXP : stockage hybride ultra-léger de voxels, avec accès aléatoire.

Principe (voir README, « Compression ») :
  * l'espace est découpé en bricks BxBxB indexées par un code de Morton ; seuls les bricks non vides existent ;
  * GÉOMÉTRIE et ATTRIBUTS sont découplés (cf. Dado et al. 2016) :
        occupation d'un brick : PLEIN | tableau d'indices | bitmap | runs     (esprit Roaring, on garde le plus petit)
        flux de couleurs, puis flux d'ID matériau, des voxels occupés dans l'ordre :
                              valeur unique | palette locale bit-packée | RLE (on garde le plus petit)
  * charges utiles identiques mises en commun (dédup) : un motif répété est stocké une seule fois ;
  * option « coque seule » : on ne stocke que les voxels visibles, l'intérieur est reconstruit au chargement.
Lecture aléatoire : recherche du brick par dichotomie sur la clé de Morton, décodage du seul brick visé.
"""
import json
import lzma
import struct
import zlib
from typing import Dict, List, Optional, Tuple

import numpy as np

MAGIC = b"VXP1"
_SPREAD = [(32, 0x1f00000000ffff), (16, 0x1f0000ff0000ff), (8, 0x100f00f00f00f00f), (4, 0x10c30c30c30c30c3),
           (2, 0x1249249249249249)]
_COMPACT = [(2, 0x10c30c30c30c30c3), (4, 0x100f00f00f00f00f), (8, 0x1f0000ff0000ff), (16, 0x1f00000000ffff),
            (32, 0x1fffff)]


# ----------------------------------------------------------------------------- Morton
def _spread(v):
    v = np.asarray(v).astype(np.uint64) & np.uint64(0x1fffff)
    for sh, m in _SPREAD:
        v = (v | (v << np.uint64(sh))) & np.uint64(m)
    return v


def morton3(x, y, z) -> np.ndarray:
    return _spread(x) | (_spread(y) << np.uint64(1)) | (_spread(z) << np.uint64(2))


def _compact(v):
    v = v & np.uint64(0x1249249249249249)
    for sh, m in _COMPACT:
        v = (v | (v >> np.uint64(sh))) & np.uint64(m)
    return v


def unmorton3(m):
    m = np.asarray(m).astype(np.uint64)
    return (_compact(m).astype(np.int64), _compact(m >> np.uint64(1)).astype(np.int64),
            _compact(m >> np.uint64(2)).astype(np.int64))


def _m3(x: int, y: int, z: int) -> int:                      # version scalaire (requêtes isolées)
    def sp(v):
        v &= 0x1fffff
        for sh, m in _SPREAD:
            v = (v | (v << sh)) & m
        return v
    return sp(x) | (sp(y) << 1) | (sp(z) << 2)


# ----------------------------------------------------------------------------- entiers à longueur variable
def varint_lens(vals) -> np.ndarray:
    v = np.asarray(vals, dtype=np.uint64)
    n = np.ones(len(v), np.int64)
    for k in range(1, 10):
        n += (v >> np.uint64(7 * k)) > 0
    return n


def put_varints(vals) -> bytes:
    v = np.asarray(vals, dtype=np.uint64)
    if not len(v):
        return b""
    nb = varint_lens(v)
    ends = np.cumsum(nb)
    starts = ends - nb
    out = np.zeros(int(ends[-1]), np.uint8)
    for k in range(10):
        sel = nb > k
        if not sel.any():
            break
        byte = ((v[sel] >> np.uint64(7 * k)) & np.uint64(0x7f)).astype(np.uint8)
        out[starts[sel] + k] = byte | ((nb[sel] > k + 1).astype(np.uint8) << 7)
    return out.tobytes()


def read_varints(buf, pos: int, n: int) -> Tuple[List[int], int]:
    out = []
    for _ in range(n):
        v = shift = 0
        while True:
            b = buf[pos]; pos += 1
            v |= (b & 0x7f) << shift
            if not b & 0x80:
                break
            shift += 7
        out.append(v)
    return out, pos


# ----------------------------------------------------------------------------- bit-packing
def pack_bits(vals: np.ndarray, b: int) -> bytes:
    if b == 0 or not len(vals):
        return b""
    bits = (np.asarray(vals, np.uint32)[:, None] >> np.arange(b, dtype=np.uint32)[None, :]) & 1
    return np.packbits(bits.astype(np.uint8).ravel(), bitorder="little").tobytes()


def unpack_bits(buf, n: int, b: int) -> np.ndarray:
    if b == 0:
        return np.zeros(n, np.int64)
    bits = np.unpackbits(np.frombuffer(buf, np.uint8), bitorder="little")[: n * b].reshape(n, b)
    return (bits.astype(np.int64) << np.arange(b)).sum(axis=1)


def _bits_for(k: int) -> int:
    return max(1, int(k - 1).bit_length())


# ----------------------------------------------------------------------------- flux de valeurs (couleur / matériau)
def enc_values(v: np.ndarray, cb: int) -> bytes:
    """tag 0 = valeur unique, 1 = palette locale bit-packée, 2 = RLE. On garde le plus court."""
    n = len(v)
    if n == 0:
        return b""
    dt = "<u1" if cb == 1 else "<u2"
    if (v == v[0]).all():
        return b"\x00" + int(v[0]).to_bytes(cb, "little")
    best = None
    uniq, inv = np.unique(v, return_inverse=True)
    pal = b"\x01" + put_varints([len(uniq)]) + uniq.astype(dt).tobytes() + pack_bits(inv.reshape(-1), _bits_for(len(uniq)))
    best = pal
    starts = np.r_[0, np.flatnonzero(v[1:] != v[:-1]) + 1]
    lens = np.diff(np.r_[starts, n])
    rle = b"\x02" + put_varints([len(starts)]) + v[starts].astype(dt).tobytes() + put_varints(lens)
    return rle if len(rle) < len(best) else best


def dec_values(buf, pos: int, n: int, cb: int) -> Tuple[np.ndarray, int]:
    tag = buf[pos]; pos += 1
    dt = "<u1" if cb == 1 else "<u2"
    if tag == 0:
        return np.full(n, int.from_bytes(bytes(buf[pos:pos + cb]), "little"), np.int64), pos + cb
    if tag == 1:
        (k,), pos = read_varints(buf, pos, 1)
        uniq = np.frombuffer(bytes(buf[pos:pos + k * cb]), dt).astype(np.int64); pos += k * cb
        b = _bits_for(k); nbytes = (n * b + 7) // 8
        return uniq[unpack_bits(bytes(buf[pos:pos + nbytes]), n, b)], pos + nbytes
    (r,), pos = read_varints(buf, pos, 1)
    vals = np.frombuffer(bytes(buf[pos:pos + r * cb]), dt).astype(np.int64); pos += r * cb
    lens, pos = read_varints(buf, pos, r)
    return np.repeat(vals, lens), pos


# ----------------------------------------------------------------------------- occupation d'un brick
def enc_occ(li: np.ndarray, b3: int) -> bytes:
    """tag 0 = PLEIN, 1 = bitmap, 2 = runs (vide/plein alternés), 3 = tableau d'indices (delta)."""
    n = len(li)
    if n == b3:
        return b"\x00"
    occ = np.zeros(b3, np.uint8); occ[li] = 1
    cands = [b"\x01" + np.packbits(occ, bitorder="little").tobytes()]
    bounds = np.r_[0, np.flatnonzero(occ[1:] != occ[:-1]) + 1, b3]
    lens = np.diff(bounds)
    if occ[0]:
        lens = np.r_[0, lens]
    cands.append(b"\x02" + put_varints([len(lens)]) + put_varints(lens))
    cands.append(b"\x03" + put_varints([n]) + put_varints(np.diff(np.r_[-1, li]) - 1))
    return min(cands, key=len)


def dec_occ(buf, pos: int, b3: int) -> Tuple[np.ndarray, int]:
    tag = buf[pos]; pos += 1
    if tag == 0:
        return np.arange(b3), pos
    if tag == 1:
        nb = (b3 + 7) // 8
        occ = np.unpackbits(np.frombuffer(bytes(buf[pos:pos + nb]), np.uint8), bitorder="little")[:b3]
        return np.flatnonzero(occ), pos + nb
    if tag == 2:
        (r,), pos = read_varints(buf, pos, 1)
        lens, pos = read_varints(buf, pos, r)
        edges = np.cumsum(lens)
        idx = [np.arange(edges[i - 1] if i else 0, edges[i]) for i in range(1, r, 2)]
        return (np.concatenate(idx) if idx else np.empty(0, np.int64)), pos
    (n,), pos = read_varints(buf, pos, 1)
    d, pos = read_varints(buf, pos, n)
    return np.cumsum(np.array(d, np.int64) + 1) - 1, pos


# ----------------------------------------------------------------------------- compression par blocs de bricks
_LZMA_RAW = [{"id": lzma.FILTER_LZMA2, "preset": 6}]


def _deflate(b: bytes) -> bytes:
    c = zlib.compressobj(9, zlib.DEFLATED, -15)               # deflate brut : pas d'en-tête par bloc
    return c.compress(b) + c.flush()


def _compress(b: bytes, how: str) -> Tuple[int, bytes]:
    c = _deflate(b) if how == "zlib" else lzma.compress(b, format=lzma.FORMAT_RAW, filters=_LZMA_RAW)
    return (1 if how == "zlib" else 2, c) if len(c) < len(b) else (0, b)


def _decompress(tag: int, b: bytes) -> bytes:
    if tag == 0:
        return b
    if tag == 1:
        return zlib.decompress(b, -15)
    return lzma.decompress(b, format=lzma.FORMAT_RAW, filters=_LZMA_RAW)


# ----------------------------------------------------------------------------- encodage
def encode(x, y, z, color, material=None, *, brick: int = 8, palette=None, materials=None,
           voxel_size: float = 0.02, shell_only: bool = False, compress: Optional[str] = None,
           chunk: int = 32, holes=None) -> bytes:
    """x,y,z : coordonnées de cellules (entiers) ; color, material : indices de palette. Sans perte."""
    x, y, z = (np.asarray(a, np.int64) for a in (x, y, z))
    color = np.asarray(color, np.int64)
    has_mat = material is not None
    mat = np.asarray(material, np.int64) if has_mat else None
    origin = np.array([x.min(), y.min(), z.min()])
    x, y, z = x - origin[0], y - origin[1], z - origin[2]
    dims = np.array([x.max() + 1, y.max() + 1, z.max() + 1])
    cb = 1 if color.max() < 256 else 2
    mb = 1 if (not has_mat or mat.max() < 256) else 2
    B = brick; b3 = B ** 3
    bkey = morton3(x // B, y // B, z // B)
    li = (x % B) + B * ((y % B) + B * (z % B))
    order = np.lexsort((li, bkey))
    bkey, li, color = bkey[order], li[order], color[order]
    if has_mat:
        mat = mat[order]
    cuts = np.r_[0, np.flatnonzero(bkey[1:] != bkey[:-1]) + 1, len(bkey)]
    table: Dict[bytes, int] = {}
    payloads: List[bytes] = []
    ids = np.empty(len(cuts) - 1, np.int64)
    for i in range(len(cuts) - 1):
        s, e = cuts[i], cuts[i + 1]
        p = enc_occ(li[s:e], b3) + enc_values(color[s:e], cb) + (enc_values(mat[s:e], mb) if has_mat else b"")
        pid = table.get(p)
        if pid is None:
            pid = table[p] = len(payloads); payloads.append(p)
        ids[i] = pid
    keys = bkey[cuts[:-1]].astype(np.uint64)
    meta = json.dumps({"palette": [list(map(int, c)) for c in (palette if palette is not None else [])],
                       "materials": list(materials or [])}, separators=(",", ":")).encode()
    flags = (1 if shell_only else 0) | (2 if has_mat else 0) | (4 if compress else 0) | (8 if holes is not None and len(holes[0]) else 0)
    hm = b""
    if flags & 8:                     # poches de vide à NE PAS remplir au chargement (codes de Morton, écarts)
        hx, hy, hz = (np.asarray(a, np.int64) for a in holes)
        h = np.sort(morton3(hx - origin[0], hy - origin[1], hz - origin[2]).astype(np.int64))
        hm = put_varints([len(h)]) + put_varints(np.diff(np.r_[0, h]).astype(np.uint64))
    head = struct.pack("<4sBBBBBf3i3I", MAGIC, 1, B, flags, cb, mb, voxel_size, *map(int, origin), *map(int, dims))
    out = [head, put_varints([len(meta)]), meta, hm, put_varints([len(keys), len(payloads)]),
           put_varints(np.diff(np.r_[0, keys.astype(np.int64)]).astype(np.uint64)), put_varints(ids),
           put_varints([len(p) for p in payloads])]
    if compress:                      # blocs de `chunk` charges utiles, compressés indépendamment (accès aléatoire conservé)
        parts, table = [], []
        for i in range(0, len(payloads), chunk):
            tag, comp = _compress(b"".join(payloads[i:i + chunk]), compress)
            table.append(bytes([tag]) + put_varints([len(comp)])); parts.append(comp)
        out += [put_varints([chunk, len(table)]), b"".join(table), b"".join(parts)]
    else:
        out.append(b"".join(payloads))
    return b"".join(out)


# ----------------------------------------------------------------------------- lecture / accès aléatoire
class VoxelPack:
    """Lecteur VXP. `get(x,y,z)` ne décode que le brick concerné (cache LRU simple)."""

    def __init__(self, data: bytes):
        self.data = memoryview(data)
        magic, ver, B, flags, cb, mb, vs, ox, oy, oz, nx, ny, nz = struct.unpack_from("<4sBBBBBf3i3I", data, 0)
        if magic != MAGIC:
            raise ValueError("Pas un fichier VXP.")
        self.brick, self.flags, self.cb, self.mb, self.voxel_size = B, flags, cb, mb, vs
        self.origin, self.dims = np.array([ox, oy, oz]), np.array([nx, ny, nz])
        self.shell_only, self.has_mat = bool(flags & 1), bool(flags & 2)
        pos = struct.calcsize("<4sBBBBBf3i3I")
        (ml,), pos = read_varints(self.data, pos, 1)
        meta = json.loads(bytes(self.data[pos:pos + ml])); pos += ml
        self.palette = [tuple(c) for c in meta["palette"]]
        self.materials = meta["materials"]
        self._holes = np.empty(0, np.uint64)
        if flags & 8:
            (nh,), pos = read_varints(self.data, pos, 1)
            hd, pos = read_varints(self.data, pos, nh)
            self._holes = np.cumsum(np.array(hd, np.int64)).astype(np.uint64)
        (nb, npay), pos = read_varints(self.data, pos, 2)
        d, pos = read_varints(self.data, pos, nb)
        self._keys = np.cumsum(np.array(d, np.int64)).astype(np.uint64)
        ids, pos = read_varints(self.data, pos, nb)
        self._ids = np.array(ids, np.int64)
        lens, pos = read_varints(self.data, pos, npay)
        self._plen = np.array(lens, np.int64)
        self._cum = np.r_[0, np.cumsum(self._plen)]
        self.chunked = bool(flags & 4)
        if self.chunked:
            (self._chunk, nch), pos = read_varints(self.data, pos, 2)
            table = []
            for _ in range(nch):
                tag = self.data[pos]; pos += 1
                (cl,), pos = read_varints(self.data, pos, 1)
                table.append((tag, cl))
            self._chunks, o = [], pos
            for tag, cl in table:
                self._chunks.append((tag, o, cl)); o += cl
            self._chunk_cache: Dict[int, bytes] = {}
        self._off = pos + self._cum
        self._cache: Dict[int, tuple] = {}
        self.nbytes = len(data)

    def _payload(self, pid: int):
        if pid not in self._cache:
            if len(self._cache) > 256:
                self._cache.pop(next(iter(self._cache)))
            if self.chunked:
                ci = pid // self._chunk
                if ci not in self._chunk_cache:
                    if len(self._chunk_cache) > 32:
                        self._chunk_cache.pop(next(iter(self._chunk_cache)))
                    tag, o, cl = self._chunks[ci]
                    self._chunk_cache[ci] = _decompress(tag, bytes(self.data[o:o + cl]))
                s = int(self._cum[pid] - self._cum[ci * self._chunk])
                buf = self._chunk_cache[ci][s:s + int(self._plen[pid])]
            else:
                buf = self.data[int(self._off[pid]):int(self._off[pid + 1])]
            p = 0
            li, p = dec_occ(buf, p, self.brick ** 3)
            col, p = dec_values(buf, p, len(li), self.cb)
            mat = dec_values(buf, p, len(li), self.mb)[0] if self.has_mat else None
            self._cache[pid] = (li, col, mat)
        return self._cache[pid]

    def get(self, x: int, y: int, z: int):
        """(couleur, matériau) de la cellule (x,y,z), ou None si vide (coordonnées absolues du modèle)."""
        lx, ly, lz = int(x - self.origin[0]), int(y - self.origin[1]), int(z - self.origin[2])
        if min(lx, ly, lz) < 0 or lx >= self.dims[0] or ly >= self.dims[1] or lz >= self.dims[2]:
            return None
        B = self.brick
        key = np.uint64(_m3(lx // B, ly // B, lz // B))
        i = int(np.searchsorted(self._keys, key))
        if i >= len(self._keys) or self._keys[i] != key:
            return None
        li, col, mat = self._payload(int(self._ids[i]))
        loc = (lx % B) + B * ((ly % B) + B * (lz % B))
        j = int(np.searchsorted(li, loc))
        if j >= len(li) or li[j] != loc:
            return None
        return int(col[j]), (int(mat[j]) if mat is not None else 0)

    def arrays(self, fill: bool = False):
        """Tous les voxels : (x, y, z, couleur, matériau), coordonnées absolues. fill=True : reconstruit
        l'intérieur d'un modèle « coque seule »."""
        B = self.brick
        bx, by, bz = unmorton3(self._keys)
        X, Y, Z, C, M = [], [], [], [], []
        for i in range(len(self._keys)):
            li, col, mat = self._payload(int(self._ids[i]))
            X.append(bx[i] * B + li % B); Y.append(by[i] * B + (li // B) % B); Z.append(bz[i] * B + li // (B * B))
            C.append(col); M.append(mat if mat is not None else np.zeros(len(li), np.int64))
        x, y, z, c, m = (np.concatenate(a) for a in (X, Y, Z, C, M))
        if fill and self.shell_only:
            x, y, z, c, m = self._fill_interior(x, y, z, c, m)
        return x + self.origin[0], y + self.origin[1], z + self.origin[2], c, m

    def _fill_interior(self, x, y, z, c, m):
        from scipy import ndimage as ndi
        from scipy.spatial import cKDTree
        occ = np.zeros(self.dims + 2, bool)
        occ[x + 1, y + 1, z + 1] = True
        lab, _ = ndi.label(~occ, structure=ndi.generate_binary_structure(3, 1))
        inner = np.argwhere((~occ) & (lab != lab[0, 0, 0])) - 1
        if len(self._holes) and len(inner):
            inner = inner[~np.isin(morton3(inner[:, 0], inner[:, 1], inner[:, 2]), self._holes)]
        if not len(inner):
            return x, y, z, c, m
        nn = cKDTree(np.stack([x, y, z], 1)).query(inner)[1]
        return (np.r_[x, inner[:, 0]], np.r_[y, inner[:, 1]], np.r_[z, inner[:, 2]], np.r_[c, c[nn]], np.r_[m, m[nn]])


def _pockets(all_cells: np.ndarray, shell_cells: np.ndarray) -> np.ndarray:
    """Cellules que le remplissage depuis l'extérieur ajouterait à tort (poches de vide closes de l'original)."""
    from scipy import ndimage as ndi
    lo = all_cells.min(0)
    occ = np.zeros(all_cells.max(0) - lo + 3, bool)
    s = shell_cells - lo + 1
    occ[s[:, 0], s[:, 1], s[:, 2]] = True
    lab, _ = ndi.label(~occ, structure=ndi.generate_binary_structure(3, 1))
    inner = np.argwhere((~occ) & (lab != lab[0, 0, 0])) - 1 + lo
    if not len(inner):
        return inner
    known = np.sort(morton3(*(all_cells - lo).T))
    mi = morton3(*(inner - lo).T)
    return inner[~np.isin(mi, known)]


def pack_model(model, *, brick="auto", shell_only: bool = False, compress: Optional[str] = "zlib",
               chunk: int = 32) -> bytes:
    """VoxelModel -> octets VXP (couleur + matériau par voxel conservés). brick='auto' : essaie 8 et 16 et garde
    le plus petit. compress : None | 'zlib' (décodage rapide) | 'lzma' (plus petit) ; par blocs, accès aléatoire gardé."""
    a = model.to_arrays()
    cell, keep = a["cell"], np.ones(len(a["cell"]), bool)
    if shell_only:
        keep = a["kind"] == 0
    if brick == "auto":
        return min((pack_model(model, brick=b, shell_only=shell_only, compress=compress, chunk=chunk) for b in (8, 16)), key=len)
    holes = None
    if shell_only:
        p = _pockets(cell, cell[keep])
        holes = (p[:, 0], p[:, 1], p[:, 2]) if len(p) else None
    return encode(cell[keep, 0], cell[keep, 1], cell[keep, 2], a["color"][keep], a["material"][keep], brick=brick,
                  palette=model.palette, materials=model.materials, voxel_size=model.voxel_size, shell_only=shell_only,
                  compress=compress, chunk=chunk, holes=holes)


def _to_model(self):
    """VXP -> VoxelModel (entités) : intérieur reconstruit si besoin, faces exposées et nature recalculées."""
    from .lattice import exposed_masks
    from .lattice import pack as lpack
    from .model import Voxel, VoxelKind, VoxelModel
    x, y, z, c, mt = self.arrays(fill=True)
    keys = lpack(x, y, z)
    o = np.argsort(keys)
    keys, x, y, z, c, mt = keys[o], x[o], y[o], z[o], c[o], mt[o]
    masks = exposed_masks(keys)
    m = VoxelModel(self.voxel_size, self.palette)
    m.materials = list(self.materials)
    pal = m.palette
    for n, (k, xx, yy, zz, cc, mm, fk) in enumerate(zip(keys.tolist(), x.tolist(), y.tolist(), z.tolist(), c.tolist(), mt.tolist(), masks.tolist())):
        m._cells[k] = Voxel(n, xx, yy, zz, pal[cc], VoxelKind.SURFACE if fk else VoxelKind.INTERIOR, fk, m, mm)
    m._next_id = len(keys)
    return m


VoxelPack.to_model = _to_model
