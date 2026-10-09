// Voxel STYLE mesh (not strict voxels): the shape is built from coarse blocks of about 2 cm,
// then block corners are pulled toward the surface like a surface net. How far depends on the
// material: skin and fur turn their one-block steps into slopes and facets (the wedge nose,
// cheekbones, knuckles), hair and metal keep crisp cube steps, cloth sits in between. Colour
// is painted on top, one fine voxel per texel, so eyes and mouth stay sharp pixel art.
//
//   fine grid (1 cm, layers composed) --blocks of f--> coarse shape (2 cm at LOD0)
//   one quad per exposed block face, split along its shorter diagonal, flat shaded.
//
// The block lattice is laid out on the character, not on the grid: the middle column of the
// face is the middle of one block (so nose and body stay symmetric), the ground and the brow
// line are block boundaries, and the face plane is a block boundary (so the nose and the brow
// stand out by whole blocks).
import { R, G, B } from './color.js';

const DIRS = [[1, 0, 0], [-1, 0, 0], [0, 1, 0], [0, -1, 0], [0, 0, 1], [0, 0, -1]];
// material ids from body.js: skin 1, hair 2, cloth 3, leather 4, metal 5, wood 6, fur 7, straw 8, eye 9, gem 10
export const BEVEL = [0.5, 0.9, 0.2, 0.45, 0.4, 0.15, 0.3, 0.6, 0.45, 0.9, 0.15];

function occSAT(grid) {
  const { nx, ny, nz } = grid, X = nx + 1, Y = ny + 1;
  const S = new Int32Array(X * Y * (nz + 1));
  for (let z = 1; z <= nz; z++) for (let y = 1; y <= ny; y++) for (let x = 1; x <= nx; x++) {
    const o = grid.col[(x - 1) + nx * ((y - 1) + ny * (z - 1))] ? 1 : 0;
    const i = x + X * (y + Y * z);
    S[i] = o + S[i - 1] + S[i - X] + S[i - X * Y] - S[i - 1 - X] - S[i - 1 - X * Y] - S[i - X - X * Y] + S[i - 1 - X - X * Y];
  }
  return (x0, y0, z0, x1, y1, z1) => {
    x0 = Math.max(x0, 0); y0 = Math.max(y0, 0); z0 = Math.max(z0, 0);
    x1 = Math.min(x1, nx - 1); y1 = Math.min(y1, ny - 1); z1 = Math.min(z1, nz - 1);
    if (x0 > x1 || y0 > y1 || z0 > z1) return 0;
    const a = (x, y, z) => S[x + X * (y + Y * z)];
    x1++; y1++; z1++;
    return a(x1, y1, z1) - a(x0, y1, z1) - a(x1, y0, z1) - a(x1, y1, z0) + a(x0, y0, z1) + a(x0, y1, z0) + a(x1, y0, z0) - a(x0, y0, z0);
  };
}

// Ambient occlusion of a fine voxel face looking along d (same recipe as the strict mesher).
function aoAt(box, x, y, z, d) {
  const [dx, dy, dz] = DIRS[d], ax = dx ? 0 : dy ? 1 : 2;
  const F = 3, a1 = 2, a2 = 5;
  const fx = x + dx, fy = y + dy, fz = z + dz;
  let near, far;
  if (ax === 0) { near = box(fx, y - 1, z - 1, fx, y + 1, z + 1); far = box(Math.min(x + a1 * dx, x + a2 * dx), y - F, z - F, Math.max(x + a1 * dx, x + a2 * dx), y + F, z + F); }
  else if (ax === 1) { near = box(x - 1, fy, z - 1, x + 1, fy, z + 1); far = box(x - F, Math.min(y + a1 * dy, y + a2 * dy), z - F, x + F, Math.max(y + a1 * dy, y + a2 * dy), z + F); }
  else { near = box(x - 1, y - 1, fz, x + 1, y + 1, fz); far = box(x - F, y - F, Math.min(z + a1 * dz, z + a2 * dz), x + F, y + F, Math.max(z + a1 * dz, z + a2 * dz)); }
  let ao = 1 - (0.1 * near / 8 + 0.55 * far / 196);
  if (d === 3) ao *= 0.92;
  return ao < 0.45 ? 0.45 : ao;
}

// Block boundaries along one axis, in fine voxels, from 0 to n. `centre`: a voxel that must be
// the middle of a block (that block is f + 1 wide); otherwise every f from `anchor`. End blocks
// thinner than half a block are merged into their neighbour.
export function bounds(n, f, anchor = 0, centre = null) {
  const b = [];
  if (centre != null) {
    const lo = centre - f / 2, hi = centre + 1 + f / 2;
    for (let x = lo; x > 0; x -= f) b.unshift(x);
    for (let x = hi; x < n; x += f) b.push(x);
  } else {
    for (let x = ((anchor % f) + f) % f; x < n; x += f) if (x > 0) b.push(x);
  }
  if (b.length > 1 && b[0] <= f / 2) b.shift();
  if (b.length > 1 && n - b[b.length - 1] <= f / 2) b.pop();
  return Int32Array.from([0, ...b, n]);
}

// opts: { f: block size in fine voxels, texel: fine voxels per texel, voxelSize: metres per
//         fine voxel, group: Uint8Array limb group per bone, align: { y, z } fine indices that
//         must be block boundaries, bevel: scale on the material bevels (1 = as listed) }
export function styleMesh(fine, weigher, opts) {
  const f = opts.f ?? 2, ts = Math.max(1, opts.texel ?? 1), grp = opts.group, bscale = opts.bevel ?? 1;
  const al = opts.align || {};
  const cx0 = Number.isInteger(fine.ox) ? null : Math.floor(fine.ox);
  const BX = bounds(fine.nx, f, 0, cx0), BY = bounds(fine.ny, f, al.y ?? 0), BZ = bounds(fine.nz, f, al.z ?? 0);
  const NX = BX.length - 1, NY = BY.length - 1, NZ = BZ.length - 1;
  const bi = (i, j, l) => i + NX * (j + NY * l);
  const fidx = (x, y, z) => x + fine.nx * (y + fine.ny * z);
  const fsolid = (x, y, z) => x >= 0 && y >= 0 && z >= 0 && x < fine.nx && y < fine.ny && z < fine.nz && fine.col[fidx(x, y, z)] !== 0;
  const fgroup = i => grp ? grp[fine.bone[i]] : 0;

  // coarse blocks: solid when 3/8 of the block is filled; the top layer's voxel names it
  const nb = NX * NY * NZ;
  const bcol = new Uint32Array(nb), bbone = new Uint8Array(nb), bmode = new Uint8Array(nb), bmat = new Uint8Array(nb);
  for (let l = 0; l < NZ; l++) for (let j = 0; j < NY; j++) for (let i = 0; i < NX; i++) {
    let n = 0, best = -1, bl = -1;
    for (let z = BZ[l]; z < BZ[l + 1]; z++) for (let y = BY[j]; y < BY[j + 1]; y++) for (let x = BX[i]; x < BX[i + 1]; x++) {
      const k = fidx(x, y, z);
      if (!fine.col[k]) continue;
      n++; if (fine.layer[k] > bl) { bl = fine.layer[k]; best = k; }
    }
    const vol = (BX[i + 1] - BX[i]) * (BY[j + 1] - BY[j]) * (BZ[l + 1] - BZ[l]);
    if (n < Math.max(1, Math.round(vol * 3 / 8))) continue;
    const b = bi(i, j, l);
    bcol[b] = fine.col[best]; bbone[b] = fine.bone[best]; bmode[b] = fine.mode[best]; bmat[b] = fine.mat[best];
  }
  const solid = (i, j, l) => i >= 0 && j >= 0 && l >= 0 && i < NX && j < NY && l < NZ && bcol[bi(i, j, l)] !== 0;
  const gof = b => grp ? grp[bbone[b]] : 0;
  const ctr = (Bs, i) => i < 0 ? Bs[0] - f / 2 : i >= Bs.length - 1 ? Bs[Bs.length - 1] + f / 2 : (Bs[i] + Bs[i + 1]) / 2;

  // lattice point -> moved position (fine units, character origin); shared by every group so
  // the surface has no cracks, while the weights are per group (limbs part cleanly in motion)
  const pcache = new Map(), wcache = new Map();
  function position(i, j, l) {
    const key = (i * 1024 + j) * 1024 + l;
    let p = pcache.get(key);
    if (p) return p;
    const o = new Uint8Array(8);
    let bsum = 0, bn = 0;
    for (let c = 0; c < 2; c++) for (let b = 0; b < 2; b++) for (let a = 0; a < 2; a++) {
      if (!solid(i - 1 + a, j - 1 + b, l - 1 + c)) continue;
      o[a + 2 * b + 4 * c] = 1;
      bsum += BEVEL[bmat[bi(i - 1 + a, j - 1 + b, l - 1 + c)]] ?? 0.5; bn++;
    }
    const PX = BX[i], PY = BY[j], PZ = BZ[l];
    const cx = [ctr(BX, i - 1), ctr(BX, i)], cy = [ctr(BY, j - 1), ctr(BY, j)], cz = [ctr(BZ, l - 1), ctr(BZ, l)];
    // surface-net mass point: mean of the midpoints of the edges that cross the surface
    let sx = 0, sy = 0, sz = 0, n = 0;
    for (let b = 0; b < 2; b++) for (let c = 0; c < 2; c++) if (o[2 * b + 4 * c] !== o[1 + 2 * b + 4 * c]) { sx += PX; sy += cy[b]; sz += cz[c]; n++; }
    for (let a = 0; a < 2; a++) for (let c = 0; c < 2; c++) if (o[a + 4 * c] !== o[a + 2 + 4 * c]) { sx += cx[a]; sy += PY; sz += cz[c]; n++; }
    for (let a = 0; a < 2; a++) for (let b = 0; b < 2; b++) if (o[a + 2 * b] !== o[a + 2 * b + 4]) { sx += cx[a]; sy += cy[b]; sz += PZ; n++; }
    const k = n && bn ? Math.min(1, bscale * bsum / bn) : 0;
    p = n ? [PX + (sx / n - PX) * k - fine.ox, PY + (sy / n - PY) * k, PZ + (sz / n - PZ) * k - fine.oz] : [PX - fine.ox, PY, PZ - fine.oz];
    pcache.set(key, p);
    return p;
  }
  // skin weights: mean over the group's blocks around the point, taken at the unmoved point
  function weights(i, j, l, group) {
    const key = ((i * 1024 + j) * 1024 + l) * 8 + group;
    let w = wcache.get(key);
    if (w) return w;
    const cells = [];
    for (let c = 0; c < 2; c++) for (let b = 0; b < 2; b++) for (let a = 0; a < 2; a++) {
      const x = i - 1 + a, y = j - 1 + b, z = l - 1 + c;
      if (solid(x, y, z) && gof(bi(x, y, z)) === group) cells.push(bi(x, y, z));
    }
    const acc = new Map(), wx = BX[i] - fine.ox, wy = BY[j], wz = BZ[l] - fine.oz;
    for (const b of cells) for (const [bone, v] of weigher(wx, wy, wz, bbone[b], bmode[b])) acc.set(bone, (acc.get(bone) || 0) + v / cells.length);
    w = [...acc.entries()].sort((p, q) => q[1] - p[1] || p[0] - q[0]).slice(0, 4);
    const sum = w.reduce((s, e) => s + e[1], 0) || 1;
    w = w.map(([bone, v]) => [bone, v / sum]);
    wcache.set(key, w);
    return w;
  }

  // paint one block face: texels of ts x ts fine voxels; each column is the first voxel of the
  // block's own limb met looking into the block from one block outside, with its occlusion
  const fbox = occSAT(fine);
  function paint(i, j, l, d, group, nu, nv) {
    const [dx, dy, dz] = DIRS[d], ax = dx ? 0 : dy ? 1 : 2, sg = dx + dy + dz;
    const ua = ax === 0 ? 1 : 0, va = ax === 2 ? 1 : 2;
    const Bs = [BX, BY, BZ], id = [i, j, l];
    const lo = Bs[ax][id[ax]], hi = Bs[ax][id[ax] + 1];
    const u0 = Bs[ua][id[ua]], u1 = Bs[ua][id[ua] + 1], v0 = Bs[va][id[va]], v1 = Bs[va][id[va] + 1];
    const start = sg > 0 ? hi + f - 1 : lo - f, end = sg > 0 ? lo - f : hi + f - 1, st = sg > 0 ? -1 : 1;
    const fb = bcol[bi(i, j, l)];
    const out = new Uint32Array(nu * nv), p = [0, 0, 0];
    for (let tv = 0; tv < nv; tv++) for (let tu = 0; tu < nu; tu++) {
      let r = 0, g = 0, b = 0, n = 0;
      for (let v = v0 + tv * ts; v < Math.min(v1, v0 + (tv + 1) * ts); v++) for (let u = u0 + tu * ts; u < Math.min(u1, u0 + (tu + 1) * ts); u++) {
        p[ua] = u; p[va] = v;
        let col = 0, ao = 0.85;
        for (let t = start; sg > 0 ? t >= end : t <= end; t += st) {
          p[ax] = t;
          if (!fsolid(p[0], p[1], p[2])) continue;
          const k = fidx(p[0], p[1], p[2]);
          if (fgroup(k) !== group) continue;
          col = fine.col[k]; ao = aoAt(fbox, p[0], p[1], p[2], d);
          break;
        }
        if (!col) col = fb;
        r += R(col) * ao; g += G(col) * ao; b += B(col) * ao; n++;
      }
      out[tu + nu * tv] = (Math.round(r / n) << 16) | (Math.round(g / n) << 8) | Math.round(b / n);
    }
    return out;
  }

  const quads = [];
  for (let l = 0; l < NZ; l++) for (let j = 0; j < NY; j++) for (let i = 0; i < NX; i++) {
    const b = bi(i, j, l);
    if (!bcol[b]) continue;
    const gr = gof(b);
    for (let d = 0; d < 6; d++) {
      const [dx, dy, dz] = DIRS[d];
      // faces against another limb stay: hidden at rest, they close the joint in motion
      if (solid(i + dx, j + dy, l + dz) && gof(bi(i + dx, j + dy, l + dz)) === gr) continue;
      const ax = dx ? 0 : dy ? 1 : 2, sg = dx + dy + dz;
      const ua = ax === 0 ? 1 : 0, va = ax === 2 ? 1 : 2;
      const c = [i, j, l]; c[ax] += sg > 0 ? 1 : 0;
      const Bs = [BX, BY, BZ];
      const nu = Math.ceil((Bs[ua][c[ua] + 1] - Bs[ua][c[ua]]) / ts), nv = Math.ceil((Bs[va][c[va] + 1] - Bs[va][c[va]]) / ts);
      const vs = [];
      for (const [cu, cv] of [[0, 0], [1, 0], [1, 1], [0, 1]]) {
        const q = c.slice(); q[ua] += cu; q[va] += cv;
        vs.push({ p: position(q[0], q[1], q[2]), w: weights(q[0], q[1], q[2], gr) });
      }
      quads.push({ d, vs, nu, nv, tex: paint(i, j, l, d, gr, nu, nv) });
    }
  }
  const out = buildStyled(quads, opts.voxelSize ?? 1);
  out.blocks = { nx: NX, ny: NY, nz: NZ, f };
  return out;
}

// Shelf-pack the tiles into one atlas, write positions (metres), UVs, joints, weights and
// two triangles per quad.
function buildStyled(quads, vsz) {
  const nq = quads.length;
  let area = 0, th = 1;
  for (const q of quads) { area += q.nu * q.nv; th = Math.max(th, q.nv); }
  let W = 64; while (W * W < area * 1.25 && W < 4096) W *= 2;
  // place tiles row by row, rows as tall as the tallest tile
  const place = new Int32Array(nq * 2);
  let x = 0, y = 0;
  for (let i = 0; i < nq; i++) {
    const q = quads[i];
    if (x + q.nu > W) { x = 0; y += th; }
    place[i * 2] = x; place[i * 2 + 1] = y; x += q.nu;
  }
  let H = 16; while (H < y + th) H *= 2;
  const atlas = new Uint8Array(W * H * 4);
  const pos = new Float32Array(nq * 12), uv = new Float32Array(nq * 8);
  const jnt = new Uint16Array(nq * 16), wgt = new Float32Array(nq * 16), idxs = new Uint32Array(nq * 6);
  const e = 0.02;
  for (let i = 0; i < nq; i++) {
    const q = quads[i], px = place[i * 2], py = place[i * 2 + 1];
    for (let b = 0; b < q.nv; b++) for (let a = 0; a < q.nu; a++) {
      const c = q.tex[a + q.nu * b], o = ((px + a) + W * (py + b)) * 4;
      atlas[o] = (c >> 16) & 255; atlas[o + 1] = (c >> 8) & 255; atlas[o + 2] = c & 255; atlas[o + 3] = 255;
    }
    const uvs = [[px + e, py + e], [px + q.nu - e, py + e], [px + q.nu - e, py + q.nv - e], [px + e, py + q.nv - e]];
    for (let k = 0; k < 4; k++) {
      const v = i * 4 + k, V = q.vs[k];
      pos[v * 3] = V.p[0] * vsz; pos[v * 3 + 1] = V.p[1] * vsz; pos[v * 3 + 2] = V.p[2] * vsz;
      uv[v * 2] = uvs[k][0] / W; uv[v * 2 + 1] = uvs[k][1] / H;
      for (let m = 0; m < 4; m++) { jnt[v * 4 + m] = m < V.w.length ? V.w[m][0] : 0; wgt[v * 4 + m] = m < V.w.length ? V.w[m][1] : 0; }
    }
    // winding from the face direction; split along the shorter diagonal (that is where the
    // visible triangles of the style come from)
    const p = q.vs.map(V => V.p), n = DIRS[q.d];
    const e1 = [p[1][0] - p[0][0], p[1][1] - p[0][1], p[1][2] - p[0][2]], e2 = [p[3][0] - p[0][0], p[3][1] - p[0][1], p[3][2] - p[0][2]];
    const cr = [e1[1] * e2[2] - e1[2] * e2[1], e1[2] * e2[0] - e1[0] * e2[2], e1[0] * e2[1] - e1[1] * e2[0]];
    const ok = cr[0] * n[0] + cr[1] * n[1] + cr[2] * n[2] >= 0;
    const d2 = (a, b) => { const x = p[a][0] - p[b][0], y = p[a][1] - p[b][1], z = p[a][2] - p[b][2]; return x * x + y * y + z * z; };
    const diag02 = d2(0, 2) <= d2(1, 3);
    const b0 = i * 4;
    let tri = diag02 ? [0, 1, 2, 0, 2, 3] : [0, 1, 3, 1, 2, 3];
    if (!ok) tri = diag02 ? [0, 2, 1, 0, 3, 2] : [0, 3, 1, 1, 3, 2];
    idxs.set(tri.map(t => b0 + t), i * 6);
  }
  return { positions: pos, uvs: uv, joints: jnt, weights: wgt, indices: idxs, atlas: { w: W, h: H, data: atlas }, quads: nq };
}
