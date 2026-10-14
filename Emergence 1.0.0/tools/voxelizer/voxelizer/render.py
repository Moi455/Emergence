"""Rendu soigné d'un VoxelModel (numpy pur) : G-buffer + AO + ombres portées + sol + contour.

Chaîne : 1) faces exposées -> rasterisation orthographique en G-buffer (id de face, u, v, profondeur) ;
2) ombrage par pixel : lumière clé chaude + ambiance hémisphérique froide/chaude, AO par coin
interpolée dans la face (+ AO douce sur ~3 voxels), ombres portées par shadow map filtrée (PCF 3x3) ;
3) sol récepteur d'ombre, fond dégradé, contour de silhouette et de plis ; 4) tone mapping ACES, sRGB.
"""
import math
from typing import Optional, Tuple

import numpy as np
from PIL import Image
from scipy import ndimage as ndi

from .ao import AO_BRIGHT, TANGENTS, corner_levels
from .lattice import exposed_masks, pack
from .model import VoxelModel
from .scene import linear_to_srgb, srgb_to_linear

_N = np.array([[1, 0, 0], [-1, 0, 0], [0, 1, 0], [0, -1, 0], [0, 0, 1], [0, 0, -1]], np.float32)
_EB, _EC, _OFF = (np.zeros((6, 3), np.float32) for _ in range(3))
for _f in range(6):
    _a, _s = _f // 2, (1 if _f % 2 == 0 else -1)
    _b, _c = TANGENTS[_a]
    _EB[_f, _b], _EC[_f, _c], _OFF[_f, _a] = 1, 1, (1 if _s > 0 else 0)


class _Ortho:
    """Caméra orthographique. `toward` = direction vers la caméra (ou vers la lumière). Unités : cellules."""

    def __init__(self, toward, pts: np.ndarray, s: float, margin: float = 2.0):
        c = np.asarray(toward, float); c /= np.linalg.norm(c)
        r = np.cross(-c, [0, 1, 0])
        r = r / np.linalg.norm(r) if np.linalg.norm(r) > 1e-6 else np.array([1.0, 0, 0])
        u = np.cross(r, -c)
        self.c, self.r, self.u, self.s = c, r, u, s
        sx, sy = pts @ r, pts @ u
        self.x0, self.y1 = sx.min() - margin, sy.max() + margin
        self.W = int(math.ceil((sx.max() - sx.min() + 2 * margin) * s))
        self.H = int(math.ceil((sy.max() - sy.min() + 2 * margin) * s))

    def project(self, P: np.ndarray):
        return (P @ self.r - self.x0) * self.s, (self.y1 - P @ self.u) * self.s, P @ self.c


def _rasterize(cam: _Ortho, cell: np.ndarray, fidx: np.ndarray, budget: int = 3_000_000):
    """Rasterise les faces visibles de `cam`. Retourne z (H*W, -inf = vide), id (H*W, -1), u, v."""
    H, W = cam.H, cam.W
    z = np.full(H * W, -np.inf, np.float32)
    ident = np.full(H * W, -1, np.int32)
    U, V = np.zeros(H * W, np.float32), np.zeros(H * W, np.float32)
    for f in range(6):
        a, sgn = f // 2, (1 if f % 2 == 0 else -1)
        b, cc = TANGENTS[a]
        if sgn * cam.c[a] <= 1e-9:
            continue                                              # face de dos
        sel = np.nonzero(fidx == f)[0]
        if not len(sel):
            continue
        Ebx, Eby = cam.r[b] * cam.s, -cam.u[b] * cam.s
        Ecx, Ecy = cam.r[cc] * cam.s, -cam.u[cc] * cam.s
        det = Ebx * Ecy - Ecx * Eby
        if abs(det) < 1e-9:
            continue
        xs, ys = np.array([0, Ebx, Ecx, Ebx + Ecx]), np.array([0, Eby, Ecy, Eby + Ecy])
        kx, ky = int(math.ceil(xs.max() - xs.min())) + 2, int(math.ceil(ys.max() - ys.min())) + 2
        ox, oy = (g.ravel() for g in np.meshgrid(np.arange(kx), np.arange(ky)))
        step = max(1, budget // (kx * ky))
        for s0 in range(0, len(sel), step):
            ids = sel[s0:s0 + step]
            O = cell[ids].astype(np.float64)
            if sgn > 0:
                O[:, a] += 1
            px0, py0 = (O @ cam.r - cam.x0) * cam.s, (cam.y1 - O @ cam.u) * cam.s
            d0 = O @ cam.c
            PX = np.floor(px0 + xs.min()).astype(np.int64)[:, None] + ox[None, :]
            PY = np.floor(py0 + ys.min()).astype(np.int64)[:, None] + oy[None, :]
            dx, dy = PX + 0.5 - px0[:, None], PY + 0.5 - py0[:, None]
            u, v = (dx * Ecy - dy * Ecx) / det, (Ebx * dy - Eby * dx) / det
            e = 2e-3                                              # léger recouvrement : pas de fissure entre faces
            ok = (u >= -e) & (u < 1 + e) & (v >= -e) & (v < 1 + e) & (PX >= 0) & (PX < W) & (PY >= 0) & (PY < H)
            ii, jj = np.nonzero(ok)
            if not len(ii):
                continue
            pix = PY[ii, jj] * W + PX[ii, jj]
            uu, vv = np.clip(u[ii, jj], 0, 1), np.clip(v[ii, jj], 0, 1)
            zf = (d0[ii] + uu * cam.c[b] + vv * cam.c[cc]).astype(np.float32)
            order = np.lexsort((zf, pix))
            pix, zf, fid, uu, vv = pix[order], zf[order], ids[ii][order], uu[order], vv[order]
            last = np.r_[pix[1:] != pix[:-1], True]
            pix, zf, fid, uu, vv = pix[last], zf[last], fid[last], uu[last], vv[last]
            better = zf > z[pix]
            pix = pix[better]
            z[pix], ident[pix], U[pix], V[pix] = zf[better], fid[better], uu[better].astype(np.float32), vv[better].astype(np.float32)
    return z, ident, U, V


def _aces(x: np.ndarray) -> np.ndarray:
    return np.clip((x * (2.51 * x + 0.03)) / (x * (2.43 * x + 0.59) + 0.14), 0, 1)


class PrettyRenderer:
    def __init__(self, width: int = 1200, azimuth: float = 40.0, elevation: float = 30.0, supersample: int = 2,
                 ao: bool = True, ao_radius: int = 3, shadows: bool = True, ground: bool = True,
                 outline: bool = True, light_view=(-0.55, 0.80, 0.60), exposure: float = 1.0,
                 background=((60, 68, 90), (22, 25, 34)), ground_rgb=(86, 90, 102), max_ss_faces: int = 450_000):
        self.__dict__.update(locals())
        del self.__dict__["self"]

    # ------------------------------------------------------------------ données
    def _faces(self, model: VoxelModel, cutaway: bool):
        a = model.to_arrays()
        cell, col = a["cell"], a["color"]
        if cutaway:
            keep = cell[:, 2] <= (cell[:, 2].min() + cell[:, 2].max()) // 2
            cell, col = cell[keep], col[keep]
        keys = pack(cell[:, 0], cell[:, 1], cell[:, 2])
        o = np.argsort(keys)
        keys, cell, col = keys[o], cell[o], col[o]
        masks = exposed_masks(keys)
        lo = cell.min(0)
        soft = None
        dims = cell.max(0) - lo + 1 + 2 * (self.ao_radius + 2)
        if self.ao and self.ao_radius > 0 and int(np.prod(dims)) < 90_000_000:
            occ = np.zeros(dims, np.float32)
            p = self.ao_radius + 2
            occ[tuple((cell - lo + p).T)] = 1.0
            soft = (ndi.uniform_filter(occ, size=2 * self.ao_radius + 1, mode="constant"), lo, p)
        fc, ff, fv, fao, fs = [], [], [], [], []
        for f in range(6):
            idx = np.nonzero((masks >> f) & 1)[0]
            if not len(idx):
                continue
            fc.append(cell[idx]); ff.append(np.full(len(idx), f, np.int8)); fv.append(idx)
            fao.append(corner_levels(keys, keys[idx], f) if self.ao else np.full((len(idx), 4), 3, np.uint8))
            if soft is not None:
                blur, lo_, p = soft
                q = (cell[idx] + _N[f].astype(int) - lo_ + p).T
                b = blur[tuple(q)]
                fs.append(1.0 - 0.55 * np.clip((b - 0.45) / 0.55, 0, 1))
            else:
                fs.append(np.ones(len(idx), np.float32))
        return (np.concatenate(fc), np.concatenate(ff).astype(np.int64), np.concatenate(fv),
                np.concatenate(fao), np.concatenate(fs).astype(np.float32), col, cell)

    # ------------------------------------------------------------------ rendu
    def render(self, model: VoxelModel, cutaway: bool = False, azimuth: Optional[float] = None) -> Image.Image:
        fc, ff, fv, fao, fsoft, col, cell = self._faces(model, cutaway)
        az, el = math.radians(self.azimuth if azimuth is None else azimuth), math.radians(self.elevation)
        toward = np.array([math.cos(el) * math.sin(az), math.sin(el), math.cos(el) * math.cos(az)])
        lo, hi = cell.min(0).astype(float), cell.max(0).astype(float) + 1
        ext = hi - lo
        pad = 0.20 * max(ext[0], ext[2]) + 3 if self.ground else 1.0
        blo, bhi = lo - [pad, 0, pad], hi + [pad, 0, pad]
        corners = np.array([[x, y, z] for x in (blo[0], bhi[0]) for y in (blo[1], bhi[1]) for z in (blo[2], bhi[2])])
        probe = _Ortho(toward, corners, 1.0)
        s = max(2, round(self.width / probe.W))
        ss = self.supersample if len(ff) <= self.max_ss_faces else 1
        cam = _Ortho(toward, corners, s * ss)

        z, ident, U, V = _rasterize(cam, fc, ff)
        mask = ident >= 0
        H, W = cam.H, cam.W

        Lv = np.array(self.light_view, float); Lv /= np.linalg.norm(Lv)
        L = Lv[0] * cam.r + Lv[1] * cam.u + Lv[2] * cam.c
        L /= np.linalg.norm(L)
        lcam = zmap = None
        if self.shadows:
            lcam = _Ortho(L, corners, s * ss)
            zmap = _rasterize(lcam, fc, ff)[0].reshape(lcam.H, lcam.W)

        def shadow(P: np.ndarray) -> np.ndarray:
            px, py, d = lcam.project(P)
            ix, iy = np.rint(px - 0.5).astype(np.int64), np.rint(py - 0.5).astype(np.int64)
            acc = np.zeros(len(P), np.float32)
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    jx, jy = np.clip(ix + dx, 0, lcam.W - 1), np.clip(iy + dy, 0, lcam.H - 1)
                    acc += (zmap[jy, jx] > d + 0.9).astype(np.float32)
            return 1.0 - acc / 9.0

        key = np.array([1.0, 0.92, 0.80], np.float32) * 1.30
        sky, gnd = np.array([0.46, 0.56, 0.74], np.float32) * 0.62, np.array([0.40, 0.33, 0.27], np.float32) * 0.46
        img = np.zeros((H * W, 3), np.float32)

        # --- fragments du modèle
        pi = np.nonzero(mask)[0]
        fid = ident[pi]
        f = ff[fid]
        u, v = U[pi], V[pi]
        alb = srgb_to_linear(np.array([c[:3] for c in model.palette], np.float32) / 255.0)[col[fv[fid]]]
        a4 = AO_BRIGHT[fao[fid]]
        ao = (1 - u) * (1 - v) * a4[:, 0] + u * (1 - v) * a4[:, 1] + (1 - u) * v * a4[:, 2] + u * v * a4[:, 3]
        ao = ao * fsoft[fid]
        n = _N[f]
        P = fc[fid] + _OFF[f] + u[:, None] * _EB[f] + v[:, None] * _EC[f]
        ndl = np.clip(n @ L, 0, 1).astype(np.float32)
        sh = shadow(P + n * 0.02) if self.shadows else np.ones(len(pi), np.float32)
        amb = gnd + (sky - gnd) * (0.5 + 0.5 * n[:, 1:2])
        img[pi] = alb * (amb * ao[:, None] + key * (ndl * sh * (0.6 + 0.4 * ao))[:, None])

        # --- sol récepteur d'ombre + fond
        top, bot = (srgb_to_linear(np.array(c, np.float32) / 255.0) for c in self.background)
        yy = (np.arange(H, dtype=np.float32) + 0.5) / H
        bg = top[None, None, :] * (1 - yy[:, None, None]) + bot[None, None, :] * yy[:, None, None]
        bg = np.repeat(bg, W, axis=1).reshape(H * W, 3)
        xx = (np.arange(W, dtype=np.float32) + 0.5) / W - 0.5
        vig = 1.0 - 0.35 * (xx[None, :] ** 2 * 1.6 + (yy[:, None] - 0.5) ** 2 * 1.2)
        bg *= vig.reshape(-1, 1)
        out = bg.copy()
        if self.ground:
            gcol = srgb_to_linear(np.array(self.ground_rgb, np.float32) / 255.0)
            cx, cz, yg = (lo[0] + hi[0]) / 2, (lo[2] + hi[2]) / 2, lo[1]
            R = 0.5 * max(ext[0], ext[2]) * 1.05 + 0.17 * max(ext[0], ext[2]) + 2.5
            for r0 in range(0, H, 128):
                rows = np.arange(r0, min(H, r0 + 128))
                sx = cam.x0 + (np.arange(W) + 0.5) / cam.s
                sy = cam.y1 - (rows + 0.5) / cam.s
                t = (yg - sx[None, :] * cam.r[1] - sy[:, None] * cam.u[1]) / cam.c[1]
                Px = sx[None, :] * cam.r[0] + sy[:, None] * cam.u[0] + t * cam.c[0]
                Pz = sx[None, :] * cam.r[2] + sy[:, None] * cam.u[2] + t * cam.c[2]
                dist = np.hypot(Px - cx, Pz - cz)
                alpha = np.clip(1 - (dist / R) ** 2, 0, 1) ** 1.3
                sel = np.nonzero((alpha > 0.01).ravel() & ~mask[r0 * W:(r0 + len(rows)) * W])[0]
                if not len(sel):
                    continue
                Pg = np.stack([Px.ravel()[sel], np.full(len(sel), yg), Pz.ravel()[sel]], 1)
                shg = shadow(Pg + [0, 0.02, 0]) if self.shadows else np.ones(len(sel), np.float32)
                lit = gcol * (sky * 0.75 + key * 0.5 * (max(L[1], 0) * shg)[:, None])
                a_ = alpha.ravel()[sel][:, None]
                gi = r0 * W + sel
                out[gi] = bg[gi] * (1 - a_) + lit * a_
        out[pi] = img[pi]

        # --- contour : silhouette (sombre) et plis de profondeur (léger)
        if self.outline:
            m2 = mask.reshape(H, W)
            z2 = z.reshape(H, W)
            t_ = ss
            er = m2.copy()
            crease = np.zeros_like(m2)
            for dy, dx in ((t_, 0), (-t_, 0), (0, t_), (0, -t_)):
                mn = np.roll(m2, (dy, dx), (0, 1))
                zn = np.roll(z2, (dy, dx), (0, 1))
                er &= mn
                crease |= m2 & mn & ((zn - z2) > 1.4)
            sil = (m2 & ~er).ravel()
            cr = (crease & ~sil.reshape(H, W)).ravel()
            out[sil] *= 0.50
            out[cr] *= 0.80

        out = _aces(out * self.exposure)
        im = Image.fromarray(np.rint(linear_to_srgb(out) * 255).astype(np.uint8).reshape(H, W, 3), "RGB")
        return im.resize((W // ss, H // ss), Image.BOX) if ss > 1 else im
