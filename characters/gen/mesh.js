// Voxel grid -> skinned mesh: visible faces only, baked ambient occlusion per face,
// greedy merging of faces that share a normal, a plane and identical skin weights,
// colors in a small nearest-filtered atlas (one texel per voxel face).
import { MODE_NORMAL, MODE_SKIRT, MODE_CLOAK, MODE_RIGID, clamp01, smooth } from './body.js';
import { R, G, B } from './color.js';

const DIRS = [[1, 0, 0], [-1, 0, 0], [0, 1, 0], [0, -1, 0], [0, 0, 1], [0, 0, -1]];

function occSAT(grid) {
  // 3D summed-area table of occupancy, (nx+1)(ny+1)(nz+1)
  const { nx, ny, nz } = grid, X = nx + 1, Y = ny + 1;
  const S = new Int32Array(X * Y * (nz + 1));
  for (let z = 1; z <= nz; z++) for (let y = 1; y <= ny; y++) for (let x = 1; x <= nx; x++) {
    const o = grid.col[(x - 1) + nx * ((y - 1) + ny * (z - 1))] ? 1 : 0;
    const i = x + X * (y + Y * z);
    S[i] = o + S[i - 1] + S[i - X] + S[i - X * Y] - S[i - 1 - X] - S[i - 1 - X * Y] - S[i - X - X * Y] + S[i - 1 - X - X * Y];
  }
  return (x0, y0, z0, x1, y1, z1) => { // inclusive cell box, clipped
    x0 = Math.max(x0, 0); y0 = Math.max(y0, 0); z0 = Math.max(z0, 0);
    x1 = Math.min(x1, nx - 1); y1 = Math.min(y1, ny - 1); z1 = Math.min(z1, nz - 1);
    if (x0 > x1 || y0 > y1 || z0 > z1) return 0;
    const a = (x, y, z) => S[x + X * (y + Y * z)];
    x1++; y1++; z1++;
    return a(x1, y1, z1) - a(x0, y1, z1) - a(x1, y0, z1) - a(x1, y1, z0) + a(x0, y0, z1) + a(x0, y1, z0) + a(x1, y0, z0) - a(x0, y0, z0);
  };
}

export function makeWeigher(sk, joints, P, U) {
  const n = sk.byName, B = sk.bones;
  const yHip = P.yHip * U, yLow = 0.12 * U;
  const ySp = B[n.Spine].head[1], yUC = B[n.UpperChest].head[1];
  const q = v => Math.round(v * 16) / 16;
  return (x, y, z, label, mode) => {
    if (mode === MODE_RIGID) return [[label, 1]];
    if (mode === MODE_SKIRT) {
      const fy = Math.floor(clamp01((yHip - y) / (yHip - yLow)) * 6) / 6;
      const fx = Math.floor(clamp01(Math.abs(x) / (P.lx * U * 1.3)) * 3) / 3;
      const w = q(fy * fx * 0.6);
      if (w <= 0) return [[n.Hips, 1]];
      return [[x > 0 ? n.LeftUpperLeg : n.RightUpperLeg, w], [n.Hips, 1 - w]];
    }
    if (mode === MODE_CLOAK) {
      const t = q(Math.floor(clamp01((y - ySp) / (yUC - ySp)) * 4) / 4);
      if (t >= 1) return [[n.UpperChest, 1]];
      if (t <= 0) return [[n.Spine, 1]];
      return [[n.UpperChest, t], [n.Spine, 1 - t]];
    }
    const js = joints.byBone[label];
    let best = null, bd = 1e9;
    for (const j of js) {
      const dx = x - j.pos[0], dy = y - j.pos[1], dz = z - j.pos[2];
      const dd = dx * dx + dy * dy + dz * dz;
      if (dd < bd) { bd = dd; best = j; }
    }
    if (!best) return [[label, 1]];
    const s = (x - best.pos[0]) * best.axis[0] + (y - best.pos[1]) * best.axis[1] + (z - best.pos[2]) * best.axis[2];
    if (s <= -best.r || s >= best.r) return [[label, 1]];
    const wc = q(smooth(-best.r, best.r, s));
    if (wc <= 0) return [[best.p, 1]];
    if (wc >= 1) return [[best.c, 1]];
    return [[best.c, wc], [best.p, 1 - wc]];
  };
}

const sigKey = w => w.map(([b, v]) => b + ':' + v).join('|');

export function meshGrid(grid, weigher, opts = {}) {
  const { nx, ny, nz, ox, oz } = grid;
  // A face between two voxels is hidden only when both move with the same limb group;
  // otherwise it stays, so a raised arm or a stepping leg never reveals a hollow shell.
  const grp = opts.group;
  const occ = (x, y, z, g) => {
    if (x < 0 || y < 0 || z < 0 || x >= nx || y >= ny || z >= nz) return false;
    const j = x + nx * (y + ny * z);
    return grid.col[j] !== 0 && (!grp || grp[grid.bone[j]] === g);
  };
  const box = occSAT(grid);
  const sigs = [], sigIndex = new Map();
  const sigId = w => { const k = sigKey(w); let id = sigIndex.get(k); if (id === undefined) { id = sigs.length; sigs.push(w); sigIndex.set(k, id); } return id; };
  const quads = []; // {pos[4][3], n, sig[4], w, h, texels Uint32Array}
  const aoK = opts.ao ?? 1;

  for (let d = 0; d < 6; d++) {
    const [dx, dy, dz] = DIRS[d];
    const ax = dx ? 0 : dy ? 1 : 2, sg = dx + dy + dz;
    const ua = ax === 0 ? 1 : 0, va = ax === 2 ? 1 : 2; // in-plane axes
    const dims = [nx, ny, nz];
    const NU = dims[ua], NV = dims[va];
    for (let sl = 0; sl < dims[ax]; sl++) {
      const sigMap = new Int32Array(NU * NV).fill(-1);
      const colMap = new Uint32Array(NU * NV);
      const cornerSig = []; // for non-uniform faces
      let any = false;
      for (let v = 0; v < NV; v++) for (let u = 0; u < NU; u++) {
        const c = [0, 0, 0]; c[ax] = sl; c[ua] = u; c[va] = v;
        const [x, y, z] = c;
        const i = x + nx * (y + ny * z);
        if (!grid.col[i] || occ(x + dx, y + dy, z + dz, grp ? grp[grid.bone[i]] : 0)) continue;
        any = true;
        // AO: near ring (3x3 at +1) and wider box (5x5 at +1..+3)
        const fx = x + dx, fy = y + dy, fz = z + dz;
        let near, far;
        const F = 3, a1 = 2, a2 = 5; // far window: 7x7, from +2 to +5 voxels out
        if (ax === 0) { near = box(fx, y - 1, z - 1, fx, y + 1, z + 1); far = box(Math.min(x + a1 * dx, x + a2 * dx), y - F, z - F, Math.max(x + a1 * dx, x + a2 * dx), y + F, z + F); }
        else if (ax === 1) { near = box(x - 1, fy, z - 1, x + 1, fy, z + 1); far = box(x - F, Math.min(y + a1 * dy, y + a2 * dy), z - F, x + F, Math.max(y + a1 * dy, y + a2 * dy), z + F); }
        else { near = box(x - 1, y - 1, fz, x + 1, y + 1, fz); far = box(x - F, y - F, Math.min(z + a1 * dz, z + a2 * dz), x + F, y + F, Math.max(z + a1 * dz, z + a2 * dz)); }
        const nf = far / 196;
        let ao = 1 - aoK * (0.13 * near / 8 + 0.65 * nf);
        if (d === 3) ao *= 0.9; // faces looking down
        ao = ao < 0.35 ? 0.35 : ao;
        const col = grid.col[i];
        const rr = R(col) * ao, gg = G(col) * ao, bb = B(col) * ao;
        colMap[u + NU * v] = (Math.round(rr) << 16) | (Math.round(gg) << 8) | Math.round(bb);
        // corner weights
        const lab = grid.bone[i], mode = grid.mode[i];
        const pc = sg > 0 ? sl + 1 : sl;
        const cs = [];
        for (const [cu, cv] of [[0, 0], [1, 0], [1, 1], [0, 1]]) {
          const p = [0, 0, 0]; p[ax] = pc; p[ua] = u + cu; p[va] = v + cv;
          const f = opts.scale ?? 1;
          cs.push(sigId(weigher((p[0] - ox) * f, p[1] * f, (p[2] - oz) * f, lab, mode)));
        }
        if (cs[0] === cs[1] && cs[0] === cs[2] && cs[0] === cs[3]) sigMap[u + NU * v] = cs[0];
        else { sigMap[u + NU * v] = -2; cornerSig.push([u, v, cs]); }
      }
      if (!any) continue;
      const pc = sg > 0 ? sl + 1 : sl;
      const mk = (u0, v0, w, h, sig4, tex) => {
        const pos = [];
        for (const [cu, cv] of [[0, 0], [w, 0], [w, h], [0, h]]) {
          const p = [0, 0, 0]; p[ax] = pc; p[ua] = u0 + cu; p[va] = v0 + cv;
          const f = opts.scale ?? 1;
          pos.push([(p[0] - ox) * f, p[1] * f, (p[2] - oz) * f]);
        }
        quads.push({ pos, d, sig: sig4, w, h, tex });
      };
      // non-uniform faces: one quad each
      for (const [u, v, cs] of cornerSig) mk(u, v, 1, 1, cs, new Uint32Array([colMap[u + NU * v]]));
      // greedy merge uniform faces
      const done = new Uint8Array(NU * NV);
      for (let v = 0; v < NV; v++) for (let u = 0; u < NU; u++) {
        const s = sigMap[u + NU * v];
        if (s < 0 || done[u + NU * v]) continue;
        let w = 1;
        while (u + w < NU && sigMap[u + w + NU * v] === s && !done[u + w + NU * v]) w++;
        let h = 1;
        outer: while (v + h < NV) {
          for (let k = 0; k < w; k++) { const j = u + k + NU * (v + h); if (sigMap[j] !== s || done[j]) break outer; }
          h++;
        }
        const tex = new Uint32Array(w * h);
        for (let b = 0; b < h; b++) for (let a = 0; a < w; a++) { const j = u + a + NU * (v + b); done[j] = 1; tex[a + w * b] = colMap[j]; }
        mk(u, v, w, h, [s, s, s, s], tex);
      }
    }
  }
  return buildBuffers(quads, sigs, opts);
}

function buildBuffers(quads, sigs, opts) {
  // atlas: shelf packing, tallest first
  const order = quads.map((q, i) => i).sort((a, b) => quads[b].h - quads[a].h || quads[b].w - quads[a].w);
  let area = 0; for (const q of quads) area += q.w * q.h;
  let W = 64; while (W * W < area * 1.25) W *= 2;
  let x = 0, y = 0, rowH = 0;
  const place = new Array(quads.length);
  for (const i of order) {
    const q = quads[i];
    if (x + q.w > W) { x = 0; y += rowH; rowH = 0; }
    place[i] = [x, y]; x += q.w; rowH = Math.max(rowH, q.h);
  }
  let H = 64; while (H < y + rowH) H *= 2;
  const atlas = new Uint8Array(W * H * 4);
  const nq = quads.length;
  const pos = new Float32Array(nq * 12), nor = new Float32Array(nq * 12), uv = new Float32Array(nq * 8);
  const jnt = new Uint16Array(nq * 16), wgt = new Float32Array(nq * 16);
  const idx = new Uint32Array(nq * 6);
  const vs = opts.voxelSize ?? 1;
  for (let i = 0; i < nq; i++) {
    const q = quads[i], [px, py] = place[i];
    for (let b = 0; b < q.h; b++) for (let a = 0; a < q.w; a++) {
      const c = q.tex[a + q.w * b], o = ((px + a) + W * (py + b)) * 4;
      atlas[o] = (c >> 16) & 255; atlas[o + 1] = (c >> 8) & 255; atlas[o + 2] = c & 255; atlas[o + 3] = 255;
    }
    const nrm = DIRS[q.d];
    const e = 0.02; // inset: never sample the neighbour texel
    const uvs = [[px + e, py + e], [px + q.w - e, py + e], [px + q.w - e, py + q.h - e], [px + e, py + q.h - e]];
    for (let k = 0; k < 4; k++) {
      const v = i * 4 + k;
      pos[v * 3] = q.pos[k][0] * vs; pos[v * 3 + 1] = q.pos[k][1] * vs; pos[v * 3 + 2] = q.pos[k][2] * vs;
      nor[v * 3] = nrm[0]; nor[v * 3 + 1] = nrm[1]; nor[v * 3 + 2] = nrm[2];
      uv[v * 2] = uvs[k][0] / W; uv[v * 2 + 1] = uvs[k][1] / H;
      const w = sigs[q.sig[k]];
      for (let m = 0; m < 4; m++) { jnt[v * 4 + m] = m < w.length ? w[m][0] : 0; wgt[v * 4 + m] = m < w.length ? w[m][1] : 0; }
    }
    // winding: corners go +u then +v; normal = u x v for (ua,va) order; flip when it disagrees
    const e1 = [q.pos[1][0] - q.pos[0][0], q.pos[1][1] - q.pos[0][1], q.pos[1][2] - q.pos[0][2]];
    const e2 = [q.pos[3][0] - q.pos[0][0], q.pos[3][1] - q.pos[0][1], q.pos[3][2] - q.pos[0][2]];
    const cr = [e1[1] * e2[2] - e1[2] * e2[1], e1[2] * e2[0] - e1[0] * e2[2], e1[0] * e2[1] - e1[1] * e2[0]];
    const ok = cr[0] * nrm[0] + cr[1] * nrm[1] + cr[2] * nrm[2] > 0;
    const b = i * 4;
    if (ok) idx.set([b, b + 1, b + 2, b, b + 2, b + 3], i * 6);
    else idx.set([b, b + 2, b + 1, b, b + 3, b + 2], i * 6);
  }
  return { positions: pos, normals: nor, uvs: uv, joints: jnt, weights: wgt, indices: idx, atlas: { w: W, h: H, data: atlas }, quads: nq };
}

// LOD: merge f x f x f blocks. A block is solid when at least 3/8 of it is; it takes the
// color, bone and mode of its outermost (highest layer) voxel.
export function downsample(grid, f, Grid) {
  const nx = Math.ceil(grid.nx / f), ny = Math.ceil(grid.ny / f), nz = Math.ceil(grid.nz / f);
  const g = new Grid(nx, ny, nz, grid.ox / f, grid.oz / f);
  const need = Math.max(1, Math.round(f * f * f * 3 / 8));
  for (let z = 0; z < nz; z++) for (let y = 0; y < ny; y++) for (let x = 0; x < nx; x++) {
    let n = 0, best = -1, bl = -1;
    for (let c = 0; c < f; c++) for (let b = 0; b < f; b++) for (let a = 0; a < f; a++) {
      const X = x * f + a, Y = y * f + b, Z = z * f + c;
      if (X >= grid.nx || Y >= grid.ny || Z >= grid.nz) continue;
      const i = grid.idx(X, Y, Z);
      if (!grid.col[i]) continue;
      n++; if (grid.layer[i] > bl) { bl = grid.layer[i]; best = i; }
    }
    if (n < need) continue;
    const j = g.idx(x, y, z);
    g.col[j] = grid.col[best]; g.bone[j] = grid.bone[best]; g.mode[j] = grid.mode[best]; g.mat[j] = grid.mat[best]; g.layer[j] = bl;
  }
  return g;
}
