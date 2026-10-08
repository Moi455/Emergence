// shared.js — code used by both the main thread and the meshing workers.
// World units: 1 voxel = 2 cm. VoxelId (16 bits) = class (9 bits) << 7 | tint (7 bits).
'use strict';
var VX = {};
(function (VX) {
  VX.VS = 0.02;
  VX.BR = 8;          // brick edge (voxels)
  VX.CH = 32;         // mesh chunk edge (voxels)
  VX.TERRAIN_CLASS = { grass: 16, dirt: 17, stone: 18, cobble: 19, gravel: 20 };

  // ---------- brick pool: mixed bricks = 15-colour local palette + 4-bit indices (0 = air) ----------
  VX.Pool = function (cap) { this.cap = cap; this.n = 0; this.idx = new Uint8Array(cap * 256); this.pal = new Uint16Array(cap * 16); };
  VX.Pool.prototype.alloc = function () {
    if (this.n >= this.cap) {
      const c = this.cap * 2, i = new Uint8Array(c * 256), p = new Uint16Array(c * 16);
      i.set(this.idx); p.set(this.pal); this.idx = i; this.pal = p; this.cap = c;
    }
    return this.n++;
  };
  VX.Pool.prototype.copy = function (s) {
    const d = this.alloc();
    this.idx.copyWithin(d * 256, s * 256, s * 256 + 256); this.pal.copyWithin(d * 16, s * 16, s * 16 + 16); return d;
  };
  VX.Pool.prototype.fromUniform = function (id) {
    const d = this.alloc(); this.idx.fill(0x11, d * 256, d * 256 + 256); this.pal.fill(0, d * 16, d * 16 + 16); this.pal[d * 16 + 1] = id; return d;
  };

  // ---------- VXB2 parsing ----------
  VX.parseVXB = function (buf, extra) {
    const dv = new DataView(buf); const u8 = new Uint8Array(buf);
    let p = 0;
    const magic = String.fromCharCode(u8[0], u8[1], u8[2], u8[3]); p = 4;
    if (magic !== 'VXB2') throw new Error('bad magic ' + magic);
    const ncls = dv.getUint16(p, true), nt = dv.getUint16(p + 2, true); p += 4;
    const palette = u8.slice(p, p + ncls * nt * 3); p += ncls * nt * 3;
    const nmod = dv.getUint16(p, true); p += 2;
    const mods = []; const pool = new VX.Pool(4096);
    for (let m = 0; m < nmod; m++) {
      const nl = u8[p++]; let name = '';
      for (let i = 0; i < nl; i++) name += String.fromCharCode(u8[p++]);
      const ox = dv.getInt16(p, true), oy = dv.getInt16(p + 2, true), oz = dv.getInt16(p + 4, true);
      const dx = dv.getUint16(p + 6, true), dy = dv.getUint16(p + 8, true), dz = dv.getUint16(p + 10, true); p += 12;
      const nbx = (dx + 7) >> 3, nby = (dy + 7) >> 3, nbz = (dz + 7) >> 3, nb = nbx * nby * nbz;
      const bricks = new Int32Array(nb);
      let nvox = 0;
      for (let b = 0; b < nb; b++) {
        const tag = u8[p++];
        if (tag === 0) { bricks[b] = 0; }
        else if (tag === 1) { bricks[b] = dv.getUint16(p, true); p += 2; nvox += 512; }
        else {
          const k = u8[p++], s = pool.alloc();
          pool.pal[s * 16] = 0;
          for (let i = 0; i < k; i++) { pool.pal[s * 16 + 1 + i] = dv.getUint16(p, true); p += 2; }
          pool.idx.set(u8.subarray(p, p + 256), s * 256);
          for (let i = 0; i < 256; i++) { const v = u8[p + i]; if (v & 15) nvox++; if (v >> 4) nvox++; }
          p += 256;
          bricks[b] = -(s + 1);
        }
      }
      mods.push({ id: m, name, ox, oy, oz, dx, dy, dz, nbx, nby, nbz, bricks, nvox });
    }
    return { ncls, nt, palette, mods, pool };
  };

  // ---------- procedural modules (plan generators): trees ----------
  // Deterministic: main thread and workers build identical pools from the same seed.
  VX.addTrees = function (W, seed, count) {
    const LEAF = 12, BARK = 13;
    for (let t = 0; t < count; t++) {
      let rs = (seed * 7919 + t * 104729) >>> 0;
      const rnd = () => { rs = (rs + 0x6D2B79F5) >>> 0; let q = rs; q = Math.imul(q ^ (q >>> 15), q | 1); q ^= q + Math.imul(q ^ (q >>> 7), q | 61); return ((q ^ (q >>> 14)) >>> 0) / 4294967296; };
      const B = new Map();   // brick key -> Uint16Array(512)
      const R = 220, H = 520; // half-extent xz, height (voxels)
      const nb = (2 * R) >> 3, nbx = nb, nby = (H + 8) >> 3, nbz = nb;
      const put = (x, y, z, id) => {
        const lx = x + R, ly = y, lz = z + R;
        if (lx < 0 || ly < 0 || lz < 0 || lx >= 2 * R || ly >= H || lz >= 2 * R) return;
        const k = (lx >> 3) + nbx * ((ly >> 3) + nby * (lz >> 3));
        let a = B.get(k); if (!a) B.set(k, a = new Uint16Array(512));
        a[(lx & 7) + 8 * ((ly & 7) + 8 * (lz & 7))] = id;
      };
      const h = 300 + rnd() * 120, r0 = 11 + rnd() * 4;
      // trunk with slight lean, bark tint from noise
      const lean = [(rnd() - 0.5) * 0.15, (rnd() - 0.5) * 0.15];
      const seg = [];
      for (let y = 0; y < h; y++) {
        const f = y / h, r = r0 * (1 - 0.45 * f) + (y < 20 ? (20 - y) * 0.35 : 0);
        const cx = lean[0] * y, cz = lean[1] * y;
        for (let z = -Math.ceil(r); z <= Math.ceil(r); z++) for (let x = -Math.ceil(r); x <= Math.ceil(r); x++) {
          const d2 = x * x + z * z; if (d2 > r * r) continue;
          const tint = Math.min(127, Math.floor(VX.hash2(Math.floor((Math.atan2(z, x) + 4) * 6), y >> 2, 3) * 70 + (d2 > (r - 2) * (r - 2) ? 0 : 50)));
          put(Math.round(cx + x), y, Math.round(cz + z), BARK << 7 | tint);
        }
        if (y > h * 0.45 && y % 30 === 0) seg.push([cx, y, cz]);
      }
      // branches + leaf clusters
      const blobs = [];
      const top = [lean[0] * h, h, lean[1] * h];
      blobs.push([top[0], top[1] + 20, top[2], 58 + rnd() * 16]);
      const nbr = 4 + Math.floor(rnd() * 3);
      for (let i = 0; i < nbr; i++) {
        const s0 = seg[Math.floor(rnd() * seg.length)] || top;
        const ang = rnd() * 6.283, len = 70 + rnd() * 90, up = 0.4 + rnd() * 0.6;
        const ex = s0[0] + Math.cos(ang) * len, ey = s0[1] + len * up, ez = s0[2] + Math.sin(ang) * len;
        const n = Math.ceil(len);
        for (let k = 0; k <= n; k++) {
          const f = k / n, x = s0[0] + (ex - s0[0]) * f, y = s0[1] + (ey - s0[1]) * f, z = s0[2] + (ez - s0[2]) * f, r = 5 * (1 - f) + 2;
          for (let dz = -r; dz <= r; dz++) for (let dy = -r; dy <= r; dy++) for (let dx = -r; dx <= r; dx++)
            if (dx * dx + dy * dy + dz * dz <= r * r) put(Math.round(x + dx), Math.round(y + dy), Math.round(z + dz), BARK << 7 | 30);
        }
        blobs.push([ex, ey, ez, 44 + rnd() * 22]);
        for (let j = 0; j < 2; j++) blobs.push([ex + (rnd() - 0.5) * 90, ey + (rnd() - 0.3) * 50, ez + (rnd() - 0.5) * 90, 32 + rnd() * 18]);
      }
      for (const [bx, by, bz, br] of blobs) {
        const r = Math.ceil(br);
        for (let z = -r; z <= r; z++) for (let y = -r; y <= r; y++) for (let x = -r; x <= r; x++) {
          const d = Math.sqrt(x * x + y * y + z * z);
          const X = Math.round(bx + x), Y = Math.round(by + y), Z = Math.round(bz + z);
          const n = VX.hash2(X >> 2, (Y >> 2) * 31 + (Z >> 2), 7 + t);
          if (d > br * (0.82 + 0.18 * n) || d < br * (0.82 + 0.18 * n) - 8) continue;   // noisy shell 16 cm thick
          const g = VX.hash2(X, Y * 977 + Z, 11 + t);
          if (g < 0.5) continue;                                            // sparse, leafy
          const light = Math.max(0, Math.min(1, (y / br) * 0.5 + 0.5));      // darker underneath
          const tint = Math.min(127, Math.floor(light * 80 + g * 40)) & 0x78; // 16 tint levels: fits a local palette
          put(X, Y, Z, LEAF << 7 | tint);
        }
      }
      // to brick table + pool
      const bricks = new Int32Array(nbx * nby * nbz);
      let nvox = 0;
      for (const [k, a] of B) {
        const vals = []; let n = 0;
        for (let i = 0; i < 512; i++) if (a[i]) { n++; if (vals.indexOf(a[i]) < 0 && vals.length < 15) vals.push(a[i]); }
        nvox += n;
        if (n === 512 && vals.length === 1) { bricks[k] = vals[0]; continue; }
        vals.sort((p, q) => p - q);
        const s = W.pool.alloc();
        W.pool.pal[s * 16] = 0; for (let i = 0; i < vals.length; i++) W.pool.pal[s * 16 + 1 + i] = vals[i];
        for (let i = 0; i < 16 - 1 - vals.length; i++) W.pool.pal[s * 16 + 1 + vals.length + i] = 0;
        for (let i = 0; i < 256; i++) {
          const v0 = a[2 * i], v1 = a[2 * i + 1];
          let i0 = v0 ? vals.indexOf(v0) + 1 : 0, i1 = v1 ? vals.indexOf(v1) + 1 : 0;
          if (v0 && i0 === 0) i0 = 1; if (v1 && i1 === 0) i1 = 1;
          W.pool.idx[s * 256 + i] = i0 | (i1 << 4);
        }
        bricks[k] = -(s + 1);
      }
      W.mods.push({ id: W.mods.length, name: 'Tree_' + t, ox: -R, oy: 0, oz: -R, dx: 2 * R, dy: H, dz: 2 * R, nbx, nby, nbz, bricks, nvox });
    }
  };

  // VoxelId at module-local voxel (x,y,z) using a bricks table (module's or an instance copy)
  VX.getLocal = function (mod, bricks, pool, x, y, z) {
    x -= mod.ox; y -= mod.oy; z -= mod.oz;
    if (x < 0 || y < 0 || z < 0 || x >= mod.dx || y >= mod.dy || z >= mod.dz) return 0;
    const b = bricks[(x >> 3) + mod.nbx * ((y >> 3) + mod.nby * (z >> 3))];
    if (b >= 0) return b;
    const s = -b - 1;
    const byte = pool.idx[s * 256 + ((x & 7) >> 1) + 4 * ((y & 7) + 8 * (z & 7))];
    const pi = (x & 1) ? byte >> 4 : byte & 15;
    return pi ? pool.pal[s * 16 + pi] : 0;
  };

  // ---------- greedy mesher on a dense class grid with a 1-cell border ----------
  // C: Uint8Array classes, index x + NX*(y + NY*z). Interior cells 1..N-2.
  // Output vertices: Int16 x,y,z (in voxel units = (origin + cell) * s), Uint8 face, Uint8 class (8 bytes)
  function Out() { this.buf = new ArrayBuffer(1 << 16); this.i16 = new Int16Array(this.buf); this.u8 = new Uint8Array(this.buf); this.n = 0; }
  Out.prototype.grow = function () {
    const nb = new ArrayBuffer(this.buf.byteLength * 2); new Uint8Array(nb).set(this.u8);
    this.buf = nb; this.i16 = new Int16Array(nb); this.u8 = new Uint8Array(nb);
  };
  Out.prototype.v = function (x, y, z, face, cls) {
    if ((this.n + 1) * 8 > this.buf.byteLength) this.grow();
    const o = this.n * 4; this.i16[o] = x; this.i16[o + 1] = y; this.i16[o + 2] = z;
    this.u8[o * 2 + 6] = face; this.u8[o * 2 + 7] = cls; this.n++;
  };
  Out.prototype.result = function () { return this.buf.slice(0, this.n * 8); };
  VX.Out = Out;

  VX.meshDense = function (C, NX, NY, NZ, ox, oy, oz, s, out) {
    const dims = [NX - 2, NY - 2, NZ - 2], strides = [1, NX, NX * NY];
    const c = [0, 0, 0], P = [0, 0, 0];
    let mask = new Uint8Array(0);
    for (let d = 0; d < 3; d++) {
      const u = (d + 1) % 3, v = (d + 2) % 3, du = dims[u], dvv = dims[v];
      if (mask.length < du * dvv) mask = new Uint8Array(du * dvv);
      for (let dir = 1; dir >= -1; dir -= 2) {
        const face = d * 2 + (dir > 0 ? 0 : 1), nOff = dir * strides[d];
        for (let i = 0; i < dims[d]; i++) {
          c[d] = i + 1; let any = false;
          for (let b = 0; b < dvv; b++) {
            c[v] = b + 1;
            c[u] = 1; let idx = c[0] + NX * (c[1] + NY * c[2]);
            const su = strides[u];
            for (let a = 0; a < du; a++, idx += su) {
              const k = C[idx];
              const m = (k && !C[idx + nOff]) ? k : 0;
              mask[a + b * du] = m; if (m) any = true;
            }
          }
          if (!any) continue;
          const plane = (dir > 0 ? i + 1 : i);
          for (let b = 0; b < dvv; b++) {
            for (let a = 0; a < du;) {
              const m = mask[a + b * du];
              if (!m) { a++; continue; }
              let w = 1; while (a + w < du && mask[a + w + b * du] === m) w++;
              let h = 1;
              outer: for (; b + h < dvv; h++) {
                const row = (b + h) * du;
                for (let k = 0; k < w; k++) if (mask[a + k + row] !== m) break outer;
              }
              for (let hh = 0; hh < h; hh++) mask.fill(0, a + (b + hh) * du, a + w + (b + hh) * du);
              P[d] = plane; P[u] = a; P[v] = b;
              const x0 = (ox + P[0]) * s, y0 = (oy + P[1]) * s, z0 = (oz + P[2]) * s;
              const U = [0, 0, 0], V = [0, 0, 0]; U[u] = w * s; V[v] = h * s;
              if (dir > 0) {
                out.v(x0, y0, z0, face, m); out.v(x0 + U[0], y0 + U[1], z0 + U[2], face, m);
                out.v(x0 + U[0] + V[0], y0 + U[1] + V[1], z0 + U[2] + V[2], face, m); out.v(x0 + V[0], y0 + V[1], z0 + V[2], face, m);
              } else {
                out.v(x0, y0, z0, face, m); out.v(x0 + V[0], y0 + V[1], z0 + V[2], face, m);
                out.v(x0 + U[0] + V[0], y0 + U[1] + V[1], z0 + U[2] + V[2], face, m); out.v(x0 + U[0], y0 + U[1], z0 + U[2], face, m);
              }
              a += w;
            }
          }
        }
      }
    }
  };

  // Trace mesh of one 32^3 chunk: faces of the occupied 4^3 micro-bricks (8 cm). The 2 cm detail inside
  // is ray-traced per pixel by the shader. get(x,y,z) returns the VoxelId at module-local voxel coords.
  VX.meshTraceRegion = function (get, bx, by, bz, ox, oy, oz) {
    // bx,by,bz: first voxel of the chunk (local coords); cells of 4 voxels, 8 per axis + 1 border cell
    const N = 10, C = new Uint8Array(N * N * N), cnt = new Uint16Array(32);
    let any = false;
    for (let cz = 0; cz < N; cz++) for (let cy = 0; cy < N; cy++) for (let cx = 0; cx < N; cx++) {
      const x0 = bx + (cx - 1) * 4, y0 = by + (cy - 1) * 4, z0 = bz + (cz - 1) * 4;
      let best = 0, bc = 0; cnt.fill(0);
      for (let k = 0; k < 64; k++) {
        const id = get(x0 + (k & 3), y0 + ((k >> 2) & 3), z0 + (k >> 4));
        if (id) { const c = (id >> 7) & 31; if (++cnt[c] > bc) { bc = cnt[c]; best = c; } }
      }
      if (best) { C[cx + N * (cy + N * cz)] = best; if (cx > 0 && cy > 0 && cz > 0 && cx < 9 && cy < 9 && cz < 9) any = true; }
    }
    if (!any) return null;
    const out = new Out();
    VX.meshDense(C, N, N, N, 0, 0, 0, 4, out);
    const n = out.n, i16 = out.i16;
    for (let i = 0; i < n; i++) { i16[i * 4] += bx; i16[i * 4 + 1] += by; i16[i * 4 + 2] += bz; }
    return n ? out.result() : null;
  };
  VX.meshModuleChunk = function (mod, bricks, pool, cx, cy, cz) {
    // skip chunks whose bricks are all empty
    let any = false;
    for (let z = cz * 4; z < Math.min(mod.nbz, cz * 4 + 4) && !any; z++) for (let y = cy * 4; y < Math.min(mod.nby, cy * 4 + 4) && !any; y++)
      for (let x = cx * 4; x < Math.min(mod.nbx, cx * 4 + 4); x++) if (bricks[x + mod.nbx * (y + mod.nby * z)]) { any = true; break; }
    if (!any) return null;
    return VX.meshTraceRegion((x, y, z) => VX.getLocal(mod, bricks, pool, x, y, z), mod.ox + cx * VX.CH, mod.oy + cy * VX.CH, mod.oz + cz * VX.CH);
  };

  // Coarse class grid (LOD k: cell = 2^k voxels). Built level by level from the finer one.
  VX.buildLods = function (mod, pool, levels) {
    // level 1 from the bricks directly
    const res = [];
    let nx = (mod.dx + 1) >> 1, ny = (mod.dy + 1) >> 1, nz = (mod.dz + 1) >> 1;
    let g = new Uint8Array(nx * ny * nz);
    const cnt = new Uint8Array(32);
    for (let z = 0; z < nz; z++) for (let y = 0; y < ny; y++) for (let x = 0; x < nx; x++) {
      let n = 0, best = 0, bc = 0; cnt.fill(0);
      for (let k = 0; k < 8; k++) {
        const id = VX.getLocal(mod, mod.bricks, pool, mod.ox + 2 * x + (k & 1), mod.oy + 2 * y + ((k >> 1) & 1), mod.oz + 2 * z + (k >> 2));
        if (id) { n++; const c = (id >> 7) & 31; if (++cnt[c] > bc) { bc = cnt[c]; best = c; } }
      }
      if (n >= 2) g[x + nx * (y + ny * z)] = best;
    }
    res.push({ g, nx, ny, nz });
    for (let l = 2; l <= levels; l++) {
      const p = res[res.length - 1];
      const mx = (p.nx + 1) >> 1, my = (p.ny + 1) >> 1, mz = (p.nz + 1) >> 1;
      const h = new Uint8Array(mx * my * mz);
      for (let z = 0; z < mz; z++) for (let y = 0; y < my; y++) for (let x = 0; x < mx; x++) {
        let n = 0, best = 0, bc = 0; cnt.fill(0);
        for (let k = 0; k < 8; k++) {
          const X = 2 * x + (k & 1), Y = 2 * y + ((k >> 1) & 1), Z = 2 * z + (k >> 2);
          if (X >= p.nx || Y >= p.ny || Z >= p.nz) continue;
          const c = p.g[X + p.nx * (Y + p.ny * Z)];
          if (c) { n++; if (++cnt[c] > bc) { bc = cnt[c]; best = c; } }
        }
        if (n >= 2) h[x + mx * (y + my * z)] = best;
      }
      res.push({ g: h, nx: mx, ny: my, nz: mz });
    }
    return res;
  };

  VX.meshCoarse = function (mod, lod, level) {
    const s = 1 << level;
    const { g, nx, ny, nz } = lod;
    // pad with a border
    const NX = nx + 2, NY = ny + 2, NZ = nz + 2, C = new Uint8Array(NX * NY * NZ);
    for (let z = 0; z < nz; z++) for (let y = 0; y < ny; y++) {
      const src = nx * (y + ny * z), dst = 1 + NX * (y + 1 + NY * (z + 1));
      C.set(g.subarray(src, src + nx), dst);
    }
    // origin: coarse cell 0 starts at module min voxel; write positions in voxel units directly
    const out2 = new Out();
    VX.meshDense(C, NX, NY, NZ, 0, 0, 0, s, out2);
    // shift by module min (exact, in voxels)
    const n = out2.n, i16 = out2.i16;
    for (let i = 0; i < n; i++) { i16[i * 4] += mod.ox; i16[i * 4 + 1] += mod.oy; i16[i * 4 + 2] += mod.oz; }
    return n ? out2.result() : null;
  };

  // ---------- deterministic terrain ----------
  function hash2(x, z, seed) {
    let h = Math.imul(x | 0, 0x27d4eb2d) ^ Math.imul(z | 0, 0x165667b1) ^ Math.imul(seed | 0, 0x9e3779b1);
    h = Math.imul(h ^ (h >>> 15), 0x85ebca6b); h = Math.imul(h ^ (h >>> 13), 0xc2b2ae35); h ^= h >>> 16;
    return (h >>> 0) / 4294967296;
  }
  VX.hash2 = hash2;
  function vnoise(x, z, seed) {
    const ix = Math.floor(x), iz = Math.floor(z), fx = x - ix, fz = z - iz;
    const ux = fx * fx * fx * (fx * (fx * 6 - 15) + 10), uz = fz * fz * fz * (fz * (fz * 6 - 15) + 10);
    const a = hash2(ix, iz, seed), b = hash2(ix + 1, iz, seed), c = hash2(ix, iz + 1, seed), d = hash2(ix + 1, iz + 1, seed);
    return a + (b - a) * ux + (c - a) * uz + (a - b - c + d) * ux * uz;
  }
  function smooth(e0, e1, x) { const t = Math.min(1, Math.max(0, (x - e0) / (e1 - e0))); return t * t * (3 - 2 * t); }
  VX.smooth = smooth;

  // params: {seed, cx, cz (village centre, voxels), pads:[{x0,z0,x1,z1,h}], streets:[{ax,az,bx,bz,w}]}
  VX.Terrain = function (params) { this.p = params; };
  VX.Terrain.prototype.natural = function (x, z) {           // meters
    const s = this.p.seed, m = 0.02, X = x * m, Z = z * m;
    let h = 9 * vnoise(X / 140, Z / 140, s) + 3.5 * vnoise(X / 45, Z / 45, s + 1) + 0.9 * vnoise(X / 14, Z / 14, s + 2)
      ;
    // village bowl: flatten near the centre, rise to hills around
    const dx = (x - this.p.cx) * m, dz = (z - this.p.cz) * m, r = Math.sqrt(dx * dx + dz * dz);
    const w = smooth(45, 110, r);
    const village = 4 + 1.2 * vnoise(X / 30, Z / 30, s + 5);
    return village * (1 - w) + (h + 3 + 16 * smooth(80, 200, r)) * w;
  };
  VX.Terrain.prototype.height = function (x, z) {            // voxels (integer): solid for y < height
    let h = this.natural(x, z) / 0.02;
    const pads = this.p.pads;
    let best = 0, bw = 0;
    for (let i = 0; i < pads.length; i++) {
      const q = pads[i];
      const ddx = Math.max(q.x0 - x, 0, x - q.x1), ddz = Math.max(q.z0 - z, 0, z - q.z1);
      const d = Math.sqrt(ddx * ddx + ddz * ddz);
      if (d < q.blend) { const w = 1 - smooth(0, q.blend, d); if (w > bw) { bw = w; best = q.h; } }
    }
    if (bw > 0) h = h * (1 - bw) + best * bw;
    const ponds = this.p.ponds || [];
    for (let i = 0; i < ponds.length; i++) {
      const q = ponds[i], d = Math.hypot(x - q.x, z - q.z);
      if (d < q.r * 1.4) {
        // bowl under the water line, plus a lip so the water never spills on a slope
        if (d < q.r) h = Math.min(h, q.level + 6 - (q.depth + 6) * (1 - smooth(q.r * 0.2, q.r, d)));
        const w = d < q.r ? smooth(q.r * 0.9, q.r, d) : 1 - smooth(q.r, q.r * 1.4, d);
        h = Math.max(h, h * (1 - w) + (q.level + 5) * w);
      }
    }
    return Math.floor(h);
  };
  // class of the top layer at (x,z)
  VX.Terrain.prototype.topClass = function (x, z) {
    const ponds = this.p.ponds || [];
    for (let i = 0; i < ponds.length; i++) { const q = ponds[i], d = Math.hypot(x - q.x, z - q.z); if (d < q.r * 0.8) return 17; if (d < q.r + 30 + (hash2(x >> 3, z >> 3, 98) - 0.5) * 20) return 20; }
    const st = this.p.streets;
    let best = 1e9;
    const jitter = (hash2(x >> 3, z >> 3, 99) - 0.5) * 14;
    for (let i = 0; i < st.length; i++) {
      const q = st[i];
      const ax = q.bx - q.ax, az = q.bz - q.az, L2 = Math.max(1, ax * ax + az * az);
      let t = ((x - q.ax) * ax + (z - q.az) * az) / L2; t = t < 0 ? 0 : t > 1 ? 1 : t;
      const ex = q.ax + ax * t - x, ez = q.az + az * t - z, d = Math.sqrt(ex * ex + ez * ez) - q.w;
      if (d < best) best = d;
    }
    if (best < jitter * 0.3) return 19;
    if (best < 22 + jitter) return 20;
    return 16;
  };
  VX.Terrain.prototype.classAt = function (top, depth) {
    if (top === 19) return depth < 5 ? 19 : depth < 40 ? 17 : 18;
    if (top === 20) return depth < 3 ? 20 : depth < 40 ? 17 : 18;
    return depth < 3 ? 16 : depth < 45 ? 17 : 18;
  };

  // Heightfield mesh of a terrain leaf: origin (x0,z0), size S voxels, step s.
  VX.meshTerrainLeaf = function (T, x0, z0, S, s) {
    const n = S / s, N = n + 2;
    const H = new Int32Array(N * N), K = new Uint8Array(N * N);
    for (let j = 0; j < N; j++) for (let i = 0; i < N; i++) {
      const x = x0 + (i - 1) * s, z = z0 + (j - 1) * s;
      const h = T.height(x + (s >> 1), z + (s >> 1));
      H[i + N * j] = s > 1 ? Math.round(h / 1) : h;
      K[i + N * j] = T.topClass(x + (s >> 1), z + (s >> 1));
    }
    const out = new Out();
    // top faces: greedy over equal (h, class)
    const done = new Uint8Array(n * n);
    for (let j = 0; j < n; j++) for (let i = 0; i < n; i++) {
      if (done[i + n * j]) continue;
      const h = H[i + 1 + N * (j + 1)], k = K[i + 1 + N * (j + 1)];
      let w = 1; while (i + w < n && !done[i + w + n * j] && H[i + w + 1 + N * (j + 1)] === h && K[i + w + 1 + N * (j + 1)] === k) w++;
      let hh = 1;
      outer: for (; j + hh < n; hh++) for (let a = 0; a < w; a++) {
        const q = i + a + 1 + N * (j + hh + 1);
        if (done[i + a + n * (j + hh)] || H[q] !== h || K[q] !== k) break outer;
      }
      for (let b = 0; b < hh; b++) done.fill(1, i + n * (j + b), i + w + n * (j + b));
      const X = x0 + i * s, Z = z0 + j * s, W = w * s, D = hh * s;
      out.v(X, h, Z, 2, k); out.v(X, h, Z + D, 2, k); out.v(X + W, h, Z + D, 2, k); out.v(X + W, h, Z, 2, k);
    }
    // side faces: towards lower neighbours (+ skirts on leaf borders)
    const dirs = [[1, 0, 0], [-1, 0, 1], [0, 1, 4], [0, -1, 5]];
    for (let j = 0; j < n; j++) for (let i = 0; i < n; i++) {
      const h = H[i + 1 + N * (j + 1)], k = K[i + 1 + N * (j + 1)];
      for (let q = 0; q < 4; q++) {
        const di = dirs[q][0], dj = dirs[q][1], face = dirs[q][2];
        const ni = i + di, nj = j + dj;
        let hn = H[ni + 1 + N * (nj + 1)];
        const border = ni < 0 || nj < 0 || ni >= n || nj >= n;
        if (border) hn = Math.min(hn, h) - 2 * s - 6;
        if (hn >= h) continue;
        // band split: top class for the first 3 voxels (grass skin), then dirt
        const top = Math.max(hn, h - (s > 1 ? 12 * s : (k === 19 ? 5 : 3)));
        const kd = k === 19 ? 17 : 17;
        emitSide(out, x0 + i * s, z0 + j * s, s, face, top, h, k);
        if (top > hn) emitSide(out, x0 + i * s, z0 + j * s, s, face, hn, top, kd);
      }
    }
    return out.n ? out.result() : null;
  };
  function emitSide(out, X, Z, s, face, y0, y1, k) {
    // column cell [X,X+s]x[Z,Z+s]; face: 0 +x, 1 -x, 4 +z, 5 -z
    if (face === 0) { const x = X + s; out.v(x, y0, Z, 0, k); out.v(x, y1, Z, 0, k); out.v(x, y1, Z + s, 0, k); out.v(x, y0, Z + s, 0, k); }
    else if (face === 1) { const x = X; out.v(x, y0, Z, 1, k); out.v(x, y0, Z + s, 1, k); out.v(x, y1, Z + s, 1, k); out.v(x, y1, Z, 1, k); }
    else if (face === 4) { const z = Z + s; out.v(X, y0, z, 4, k); out.v(X + s, y0, z, 4, k); out.v(X + s, y1, z, 4, k); out.v(X, y1, z, 4, k); }
    else { const z = Z; out.v(X, y0, z, 5, k); out.v(X, y1, z, 5, k); out.v(X + s, y1, z, 5, k); out.v(X + s, y0, z, 5, k); }
  }

  // Full 3D mesh of an edited LOD0 terrain leaf (size S, step 1) with removed voxels.
  // removed: Uint32Array of local indices lx + S*(lz + S*(y))
  VX.meshTerrainEdited = function (T, x0, z0, S, removed) {
    const N = S + 2;
    const H = new Int32Array(N * N), K = new Uint8Array(N * N);
    let ymin = 1e9, ymax = -1e9;
    for (let j = 0; j < N; j++) for (let i = 0; i < N; i++) {
      const h = T.height(x0 + i - 1, z0 + j - 1); H[i + N * j] = h; K[i + N * j] = T.topClass(x0 + i - 1, z0 + j - 1);
      if (h < ymin) ymin = h; if (h > ymax) ymax = h;
    }
    let ylow = ymin;
    for (let r = 0; r < removed.length; r++) { const y = Math.floor(removed[r] / (S * S)); if (y < ylow) ylow = y; }
    ylow -= 2;
    const NY = ymax - ylow + 2;
    const C = new Uint8Array(N * NY * N);
    // fill: index i + N*(yy + NY*j) with yy = y - ylow ; y from ylow-? : bottom border row (yy=0) solid
    for (let j = 0; j < N; j++) for (let i = 0; i < N; i++) {
      const h = H[i + N * j], k = K[i + N * j];
      for (let yy = 0; yy < NY; yy++) {
        const y = ylow - 1 + yy;
        if (y < h) C[i + N * (yy + NY * j)] = T.classAt(k, h - 1 - y);
      }
    }
    for (let r = 0; r < removed.length; r++) {
      const v = removed[r], lx = v % S, lz = Math.floor(v / S) % S, y = Math.floor(v / (S * S));
      const yy = y - ylow + 1;
      if (yy > 0 && yy < NY) C[(lx + 1) + N * (yy + NY * (lz + 1))] = 0;
    }
    // C layout is x + N*(y + NY*z): matches meshDense(NX=N, NY, NZ=N)
    const out = new Out();
    VX.meshDense(C, N, NY, N, x0, ylow, z0, 1, out);
    return out.n ? out.result() : null;
  };
})(VX);

// ---------- job handler (used inside workers, or on the main thread as a fallback) ----------
VX.makeHandler = function () {
  let W = null, T = null;
  return function (m, post) {
    if (m.type === 'init') {
      W = VX.parseVXB(m.buf); VX.addTrees(W, m.terrain.seed, 4); T = new VX.Terrain(m.terrain);
      post({ type: 'ready' });
    } else if (m.type === 'drop') {
      W = null;
    } else if (m.type === 'module') {
      const mod = W.mods[m.id], t0 = performance.now();
      const chunks = [], transfer = [];
      const ncx = Math.ceil(mod.dx / VX.CH), ncy = Math.ceil(mod.dy / VX.CH), ncz = Math.ceil(mod.dz / VX.CH);
      for (let cz = 0; cz < ncz; cz++) for (let cy = 0; cy < ncy; cy++) for (let cx = 0; cx < ncx; cx++) {
        const r = VX.meshModuleChunk(mod, mod.bricks, W.pool, cx, cy, cz);
        if (r) { chunks.push({ c: cx + ncx * (cy + ncy * cz), v: r }); transfer.push(r); }
      }
      const lods = VX.buildLods(mod, W.pool, 4), coarse = [];
      for (let l = 1; l < lods.length; l++) { const r = VX.meshCoarse(mod, lods[l], l + 1); coarse.push(r); if (r) transfer.push(r); }
      post({ type: 'module', id: m.id, chunks, coarse, ms: performance.now() - t0 }, transfer);
    } else if (m.type === 'chunk') {
      const N = 40, b = m.block, x0 = m.x0, y0 = m.y0, z0 = m.z0;
      const get = (x, y, z) => b[(x - x0) + N * ((y - y0) + N * (z - z0))];
      const r = VX.meshTraceRegion(get, x0 + 4, y0 + 4, z0 + 4);
      post({ type: 'chunk', job: m.job, v: r }, r ? [r] : []);
    } else if (m.type === 'terrain') {
      const r = m.removed ? VX.meshTerrainEdited(T, m.x0, m.z0, m.S, m.removed) : VX.meshTerrainLeaf(T, m.x0, m.z0, m.S, m.s);
      post({ type: 'terrain', job: m.job, v: r }, r ? [r] : []);
    }
  };
};
if (typeof WorkerGlobalScope !== 'undefined' && self instanceof WorkerGlobalScope) {
  const h = VX.makeHandler();
  self.onmessage = function (e) { h(e.data, function (msg, tr) { self.postMessage(msg, tr || []); }); };
}
