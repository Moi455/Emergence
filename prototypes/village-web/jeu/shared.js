// shared.js — code used by both the main thread and the meshing workers.
// World units: 1 voxel = 2 cm. VoxelId (16 bits) = class (9 bits) << 7 | tint (7 bits).
'use strict';
var VX = {};
(function (VX) {
  VX.VS = +(new URLSearchParams(typeof location !== 'undefined' ? location.search : '').get('vs') || 0.10);   // voxel edge in metres
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
  // ---------- VXB3 (docs/interfaces.md § 2): canonical classes, world axes, voxels x then z then y ----------
  // Converted on load to the prototype's internal layout: glTF axes (z_gltf = -z_world), prototype classes,
  // bricks with at most 15 colours (the GPU atlas uses 4-bit indices; extra colours go to the nearest kept tint).
  VX.CANON = { 1: 17, 2: 21, 3: 22, 4: 23, 5: 24, 6: 25, 7: 26, 8: 18, 9: 27, 10: 28, 11: 29, 12: 30, 13: 31, 16: 1, 17: 2, 18: 20, 19: 32, 20: 5 };
  VX.parseVXB3 = function (buf) {
    const dv = new DataView(buf), u8 = new Uint8Array(buf);
    const NCLS = 21, NT = 128, inv = new Uint16Array(512);
    for (const c in VX.CANON) inv[VX.CANON[c]] = +c;
    const toInt = (v) => (inv[v >> 7] << 7) | (v & 127);
    let p = 4;
    const ver = dv.getUint16(p, true), flags = dv.getUint16(p + 4, true), nmod = dv.getUint16(p + 6, true); p += 8;
    if (ver !== 1) throw new Error('VXB3 version ' + ver);
    let vsmm = 20; if (flags & 2) { vsmm = dv.getUint16(p, true); p += 2; }
    const palette = new Uint8Array(NCLS * NT * 3);
    if (flags & 1) {
      const nr = dv.getUint16(p, true); p += 2;
      for (let r = 0; r < nr; r++) { const c = inv[dv.getUint16(p, true)]; p += 2; palette.set(u8.subarray(p, p + NT * 3), c * NT * 3); p += NT * 3; }
    }
    const mods = [], pool = new VX.Pool(4096), vox = new Uint16Array(512);
    const cnt16 = new Uint16Array(65536), rem16 = new Uint16Array(65536), slot16 = new Uint8Array(65536);
    for (let m = 0; m < nmod; m++) {
      const nl = u8[p++]; let name = '';
      for (let i = 0; i < nl; i++) name += String.fromCharCode(u8[p++]);
      const wx = dv.getInt32(p, true), wy = dv.getInt32(p + 4, true), wz = dv.getInt32(p + 8, true);
      const dx = dv.getUint16(p + 12, true), dy = dv.getUint16(p + 14, true), dz = dv.getUint16(p + 16, true), nbr = dv.getUint32(p + 18, true); p += 22;
      const nbx = (dx + 7) >> 3, nby = (dy + 7) >> 3, nbz = (dz + 7) >> 3, nb = nbx * nby * nbz;
      if (nb !== nbr) throw new Error('VXB3: brick count mismatch in ' + name);
      const bricks = new Int32Array(nb); let nvox = 0;
      for (let by = 0; by < nby; by++) for (let bz = 0; bz < nbz; bz++) for (let bx = 0; bx < nbx; bx++) {
        const b = bx + nbx * (by + nby * (nbz - 1 - bz));   // internal order, z mirrored brick by brick
        const tag = u8[p++];
        if (tag === 0) continue;
        if (tag === 1) { bricks[b] = toInt(dv.getUint16(p, true)); p += 2; nvox += 512; continue; }
        if (tag === 2) {
          const k = u8[p++], ids = []; for (let i = 0; i < k; i++) { ids.push(dv.getUint16(p, true)); p += 2; }
          const bits = k + 1 <= 2 ? 1 : k + 1 <= 4 ? 2 : k + 1 <= 16 ? 4 : 8, per = 8 / bits, mask = (1 << bits) - 1;
          for (let i = 0; i < 512; i++) { const q = (u8[p + ((i / per) | 0)] >> ((i % per) * bits)) & mask; vox[i] = q ? ids[q - 1] : 0; }
          p += 512 * bits / 8;
        } else if (tag === 3) { for (let i = 0; i < 512; i++) vox[i] = dv.getUint16(p + 2 * i, true); p += 1024; }
        else throw new Error('VXB3: bad brick tag ' + tag);
        // local palette, reduced to 15 entries when needed (count and slot tables indexed by VoxelId)
        const keep = [];
        for (let i = 0; i < 512; i++) { const v = vox[i]; if (v && cnt16[v]++ === 0) keep.push(v); }
        if (keep.length > 15) {
          keep.sort((a, c) => cnt16[c] - cnt16[a]);
          for (let j = 15; j < keep.length; j++) {
            const v = keep[j]; let best = keep[0], bc = 1e9;
            for (let w = 0; w < 15; w++) { const kw = keep[w], c = ((kw >> 7) === (v >> 7) ? 0 : 1000) + Math.abs((kw & 127) - (v & 127)); if (c < bc) { bc = c; best = kw; } }
            rem16[v] = best;
          }
        }
        const nk = Math.min(15, keep.length), kept = keep.slice(0, nk).sort((a, c) => a - c);
        const s = pool.alloc();
        pool.pal.fill(0, s * 16, s * 16 + 16);
        for (let i = 0; i < nk; i++) { pool.pal[s * 16 + 1 + i] = toInt(kept[i]); slot16[kept[i]] = i + 1; }
        const o = s * 256; pool.idx.fill(0, o, o + 256);
        for (let i = 0; i < 512; i++) {
          let v = vox[i]; if (!v) continue;
          if (rem16[v]) v = rem16[v];
          const x = i & 7, z = (i >> 3) & 7, y = i >> 6, q = slot16[v], li = x + 8 * (y + 8 * (7 - z));
          pool.idx[o + (li >> 1)] |= (li & 1) ? q << 4 : q; nvox++;
        }
        for (const v of keep) { cnt16[v] = 0; rem16[v] = 0; slot16[v] = 0; }
        bricks[b] = -(s + 1);
      }
      // back to glTF axes: cell z_gltf = -z_world - 1, so the grid min corner is -(wz + dz)
      mods.push({ id: m, name, ox: wx, oy: wy, oz: -(wz + dz), dx, dy, dz, nbx, nby, nbz, bricks, nvox });
    }
    return { ncls: NCLS, nt: NT, palette, mods, pool, vsmm };
  };

  VX.parseVXB = function (buf, extra) {
    const dv = new DataView(buf); const u8 = new Uint8Array(buf);
    let p = 0;
    const magic = String.fromCharCode(u8[0], u8[1], u8[2], u8[3]); p = 4;
    if (magic === 'VXB3') return VX.parseVXB3(buf);
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
    const K = 0.02 / VX.VS;                    // scale from the original 2 cm pipeline
    const ri = (v) => Math.max(1, Math.round(v * K));
    const LEAFFILL = Math.min(0.5, 0.5 * K * 2.5);   // coarser voxels need denser foliage to read as leaves
    for (let t = 0; t < count; t++) {
      let rs = (seed * 7919 + t * 104729) >>> 0;
      const rnd = () => { rs = (rs + 0x6D2B79F5) >>> 0; let q = rs; q = Math.imul(q ^ (q >>> 15), q | 1); q ^= q + Math.imul(q ^ (q >>> 7), q | 61); return ((q ^ (q >>> 14)) >>> 0) / 4294967296; };
      const B = new Map();   // brick key -> Uint16Array(512)
      const R = ri(220), H = ri(520); // half-extent xz, height (voxels)
      const nb = (2 * R) >> 3, nbx = nb, nby = (H + 8) >> 3, nbz = nb;
      const put = (x, y, z, id) => {
        const lx = x + R, ly = y, lz = z + R;
        if (lx < 0 || ly < 0 || lz < 0 || lx >= 2 * R || ly >= H || lz >= 2 * R) return;
        const k = (lx >> 3) + nbx * ((ly >> 3) + nby * (lz >> 3));
        let a = B.get(k); if (!a) B.set(k, a = new Uint16Array(512));
        a[(lx & 7) + 8 * ((ly & 7) + 8 * (lz & 7))] = id;
      };
      const h = (300 + rnd() * 120) * K, r0 = (11 + rnd() * 4) * K;
      // trunk with slight lean, bark tint from noise
      const lean = [(rnd() - 0.5) * 0.15, (rnd() - 0.5) * 0.15];
      const seg = [];
      for (let y = 0; y < h; y++) {
        const f = y / h, r = r0 * (1 - 0.45 * f) + (y < 20 * K ? (20 * K - y) * 0.35 : 0);
        const cx = lean[0] * y, cz = lean[1] * y;
        for (let z = -Math.ceil(r); z <= Math.ceil(r); z++) for (let x = -Math.ceil(r); x <= Math.ceil(r); x++) {
          const d2 = x * x + z * z; if (d2 > r * r) continue;
          const tint = Math.min(127, Math.floor(VX.hash2(Math.floor((Math.atan2(z, x) + 4) * 6), y >> 2, 3) * 70 + (d2 > (r - 2 * K) * (r - 2 * K) ? 0 : 50)));
          put(Math.round(cx + x), y, Math.round(cz + z), BARK << 7 | tint);
        }
        if (y > h * 0.45 && y % ri(30) === 0) seg.push([cx, y, cz]);
      }
      // branches + leaf clusters
      const blobs = [];
      const top = [lean[0] * h, h, lean[1] * h];
      blobs.push([top[0], top[1] + 20 * K, top[2], (58 + rnd() * 16) * K]);
      const nbr = 4 + Math.floor(rnd() * 3);
      for (let i = 0; i < nbr; i++) {
        const s0 = seg[Math.floor(rnd() * seg.length)] || top;
        const ang = rnd() * 6.283, len = (70 + rnd() * 90) * K, up = 0.4 + rnd() * 0.6;
        const ex = s0[0] + Math.cos(ang) * len, ey = s0[1] + len * up, ez = s0[2] + Math.sin(ang) * len;
        const n = Math.ceil(len);
        for (let k = 0; k <= n; k++) {
          const f = k / n, x = s0[0] + (ex - s0[0]) * f, y = s0[1] + (ey - s0[1]) * f, z = s0[2] + (ez - s0[2]) * f, r = (5 * (1 - f) + 2) * K;
          for (let dz = -r; dz <= r; dz++) for (let dy = -r; dy <= r; dy++) for (let dx = -r; dx <= r; dx++)
            if (dx * dx + dy * dy + dz * dz <= r * r) put(Math.round(x + dx), Math.round(y + dy), Math.round(z + dz), BARK << 7 | 30);
        }
        blobs.push([ex, ey, ez, (44 + rnd() * 22) * K]);
        for (let j = 0; j < 2; j++) blobs.push([ex + (rnd() - 0.5) * 90 * K, ey + (rnd() - 0.3) * 50 * K, ez + (rnd() - 0.5) * 90 * K, (32 + rnd() * 18) * K]);
      }
      for (const [bx, by, bz, br] of blobs) {
        const r = Math.ceil(br);
        for (let z = -r; z <= r; z++) for (let y = -r; y <= r; y++) for (let x = -r; x <= r; x++) {
          const d = Math.sqrt(x * x + y * y + z * z);
          const X = Math.round(bx + x), Y = Math.round(by + y), Z = Math.round(bz + z);
          const sc = Math.max(1, Math.round(4 * K)); const n = VX.hash2(Math.floor(X / sc), Math.floor(Y / sc) * 31 + Math.floor(Z / sc), 7 + t);
          if (d > br * (0.82 + 0.18 * n) || d < br * (0.82 + 0.18 * n) - Math.max(2, 8 * K)) continue;   // noisy shell
          const g = VX.hash2(X, Y * 977 + Z, 11 + t);
          if (g < LEAFFILL) continue;                                       // sparse, leafy
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
      W.mods.push({ id: W.mods.length, name: 'Tree_' + t, ox: -R, oy: 0, oz: -R, dx: 2 * R, dy: H, dz: 2 * R, nbx, nby, nbz, bricks, nvox, tree: true });
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
  VX.Terrain.prototype.rawH = function (X, Z) {              // metres in, metres out, no village, no pads
    const s = this.p.seed;
    let h = 11.0 * vnoise(X / 190, Z / 190, s)
          +  5.0 * vnoise(X / 78, Z / 78, s + 1)
          +  2.0 * vnoise(X / 29, Z / 29, s + 2)
          +  0.7 * vnoise(X / 11, Z / 11, s + 3);
    const rg = 1 - Math.abs(vnoise(X / 115, Z / 115, s + 7) * 2 - 1);
    h += 7.0 * rg * rg;                                      // ridged term: the hills get a crest
    // a brook runs roughly north-south and bends; the ground falls towards it
    const bend = 26 * (vnoise(Z / 240, 11.5, s + 11) - 0.5);
    const d = Math.abs(X - this.p.sx - bend);
    h -= 6.0 * (1 - smooth(0, 55, d));
    return h;
  };
  VX.Terrain.prototype.natural = function (x, z) {           // metres
    const m = VX.VS, X = x * m, Z = z * m, s = this.p.seed;
    if (this._hc === undefined) { this.p.sx = (this.p.cx * m) - 78; this._hc = this.rawH(this.p.cx * m, this.p.cz * m); }
    const h = this.rawH(X, Z);
    // the village sits in a shallow dip rather than on a table: it keeps a gentle swell of its own
    const dx = (x - this.p.cx) * m, dz = (z - this.p.cz) * m, r = Math.sqrt(dx * dx + dz * dz);
    const w = smooth(28, 102, r);
    const village = this._hc + 1.75 * vnoise(X / 24, Z / 24, s + 5) + 0.5 * vnoise(X / 9, Z / 9, s + 6) - 0.9;
    return village * (1 - w) + h * w;
  };
  VX.Terrain.prototype.height = function (x, z) {            // voxels (integer): solid for y < height
    let h = this.natural(x, z) / VX.VS;
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
        const lip = 1.0 / VX.VS;                             // one metre of rim, so the water never spills
        if (d < q.r) h = Math.min(h, q.level + lip - (q.depth + lip) * (1 - smooth(q.r * 0.2, q.r, d)));
        const w = d < q.r ? smooth(q.r * 0.9, q.r, d) : 1 - smooth(q.r, q.r * 1.4, d);
        h = Math.max(h, h * (1 - w) + (q.level + lip * 0.8) * w);
      }
    }
    return Math.floor(h);
  };
  // rise per voxel of horizontal travel: 1.0 is 45 degrees
  VX.Terrain.prototype.slope = function (x, z, s) {
    s = s || 1;
    const hx = this.height(x + s, z) - this.height(x - s, z), hz = this.height(x, z + s) - this.height(x, z - s);
    return Math.hypot(hx, hz) / (2 * s);
  };
  // class of the top layer at (x,z). slope is optional: pass it when the caller already has it.
  VX.Terrain.prototype.topClass = function (x, z, slope) {
    const V = (metres) => metres / VX.VS;
    const ponds = this.p.ponds || [];
    for (let i = 0; i < ponds.length; i++) {
      const q = ponds[i], d = Math.hypot(x - q.x, z - q.z);
      if (d < q.r * 0.82) return 17;
      if (d < q.r + V(0.6) + (hash2(Math.floor(x / V(0.16)), Math.floor(z / V(0.16)), 98) - 0.5) * V(0.4)) return 20;
    }
    const st = this.p.streets;
    let best = 1e9;
    const jitter = (hash2(Math.floor(x / V(0.16)), Math.floor(z / V(0.16)), 99) - 0.5) * V(0.28);
    for (let i = 0; i < st.length; i++) {
      const q = st[i];
      const ax = q.bx - q.ax, az = q.bz - q.az, L2 = Math.max(1, ax * ax + az * az);
      let t = ((x - q.ax) * ax + (z - q.az) * az) / L2; t = t < 0 ? 0 : t > 1 ? 1 : t;
      const ex = q.ax + ax * t - x, ez = q.az + az * t - z, d = Math.sqrt(ex * ex + ez * ez) - q.w;
      if (d < best) best = d;
    }
    if (best < jitter * 0.3) return 19;                       // cobbles
    if (best < V(0.44) + jitter) return 20;                   // gravel verge
    const sl = slope === undefined ? this.slope(x, z, Math.max(1, Math.round(V(0.04)))) : slope;
    if (sl > 1.15) return 18;                                 // bare rock where it is steep
    if (sl > 0.72) return 17;                                 // trodden earth on slopes
    // strip fields in a ring around the village, the medieval way: long narrow plots
    const m = VX.VS, X = x * m, Z = z * m, s2 = this.p.seed;
    const r = Math.hypot((x - this.p.cx) * m, (z - this.p.cz) * m);
    if (r > 54 && r < 125 && sl < 0.33) {
      const band = vnoise(X / 85, Z / 85, s2 + 21);
      if (band > 0.47) {
        const u = X * 0.80 + Z * 0.60, strip = Math.floor(u / 6.5);
        if (hash2(strip, Math.floor(band * 7), 33) > 0.42) return 17;
      }
    }
    return 16;
  };
  VX.Terrain.prototype.classAt = function (top, depth) {
    const V = (metres) => Math.max(1, Math.round(metres / VX.VS));
    if (top === 19) return depth < V(0.1) ? 19 : depth < V(0.8) ? 17 : 18;
    if (top === 20) return depth < V(0.06) ? 20 : depth < V(0.8) ? 17 : 18;
    if (top === 18) return 18;
    return depth < V(0.06) ? top : depth < V(0.9) ? 17 : 18;
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
      // keep W: the sky volume needs the module occupancy
    } else if (m.type === 'module') {
      const mod = W.mods[m.id], t0 = performance.now(), lods = [], transfer = [];
      for (let l = 0; l < 3; l++) { const r = VX.meshModuleV3(mod, mod.bricks, W.pool, l); lods.push(r ? r.buf : null); if (r) transfer.push(r.buf); }
      post({ type: 'module', id: m.id, lods, ms: performance.now() - t0 }, transfer);
    } else if (m.type === 'grid') {
      const t0 = performance.now();
      const out = new VX.VOut();
      VX.meshVox(m.V, m.nx, m.ny, m.nz, m.ox, m.oy, m.oz, out, m.step || 1);
      const v = out.n ? out.result() : null;
      post({ type: 'grid', job: m.job, v, ms: performance.now() - t0 }, v ? [v] : []);
    } else if (m.type === 'terrain') {
      const t0 = performance.now();
      const r = m.removed ? VX.meshTerrainEditedV3(T, m.x0, m.z0, m.S, m.removed) : VX.meshTerrainV3(T, m.x0, m.z0, m.S, m.s);
      const v = r ? r.buf : null;
      post({ type: 'terrain', job: m.job, v, ms: performance.now() - t0 }, v ? [v] : []);
    } else if (m.type === 'skyvol') {
      post({ type: 'skyvol', job: m.job, v: skyVolume(W, T, m) }, []);
    }
  };
};

// How much of the open sky reaches each 2 m cell of the village. Solid cells block it and the
// light spreads sideways with a loss per cell, so a room lit through one door goes dark at the back.
// It is the slow, world-scale half of the ambient term; the per-vertex bake is the fine half.
function skyVolume(W, T, m) {
  const nx = m.n[0], ny = m.n[1], nz = m.n[2], C = m.c, org = m.org;
  const N = nx * ny * nz, solid = new Uint8Array(N);
  const idx = (x, y, z) => x + nx * (y + ny * z);
  // ground
  const top = new Int32Array(nx * nz);
  for (let z = 0; z < nz; z++) for (let x = 0; x < nx; x++) {
    const h = T.height(org[0] + x * C + (C >> 1), org[2] + z * C + (C >> 1));
    top[x + nx * z] = h;
    const ty = Math.min(ny, Math.ceil((h - org[1]) / C));
    for (let y = 0; y < ty; y++) solid[idx(x, y, z)] = 1;
  }
  // buildings, through the 8^3 brick occupancy of each instance
  const inst = m.inst;
  for (let i = 0; i < inst.length; i += 5) {
    const mod = W.mods[inst[i]], ix = inst[i + 1], iy = inst[i + 2], iz = inst[i + 3], r = inst[i + 4];
    for (let bz = 0; bz < mod.nbz; bz++) for (let by = 0; by < mod.nby; by++) for (let bx = 0; bx < mod.nbx; bx++) {
      if (!mod.bricks[bx + mod.nbx * (by + mod.nby * bz)]) continue;
      const lx = mod.ox + bx * 8 + 4, ly = mod.oy + by * 8 + 4, lz = mod.oz + bz * 8 + 4;
      let wx, wz;
      if (r === 1) { wx = ix + lz; wz = iz - lx; } else if (r === 2) { wx = ix - lx; wz = iz - lz; }
      else if (r === 3) { wx = ix - lz; wz = iz + lx; } else { wx = ix + lx; wz = iz + lz; }
      const cx = Math.floor((wx - org[0]) / C), cy = Math.floor((iy + ly - org[1]) / C), cz = Math.floor((wz - org[2]) / C);
      if (cx >= 0 && cy >= 0 && cz >= 0 && cx < nx && cy < ny && cz < nz) solid[idx(cx, cy, cz)] = 1;
    }
  }
  // seed: cells with nothing above them in their own column see the whole sky
  const L = new Float32Array(N);
  for (let z = 0; z < nz; z++) for (let x = 0; x < nx; x++) {
    let open = true;
    for (let y = ny - 1; y >= 0; y--) {
      const i = idx(x, y, z);
      if (solid[i]) { open = false; continue; }
      if (open) L[i] = 1;
    }
  }
  // spread sideways and downwards, losing a fixed share per cell
  const DECAY = 0.70, PASSES = 14;
  for (let p = 0; p < PASSES; p++) {
    for (let z = 0; z < nz; z++) for (let y = 0; y < ny; y++) for (let x = 0; x < nx; x++) {
      const i = idx(x, y, z); if (solid[i] || L[i] >= 1) continue;
      let best = L[i];
      if (x > 0) best = Math.max(best, L[i - 1]); if (x < nx - 1) best = Math.max(best, L[i + 1]);
      if (y > 0) best = Math.max(best, L[i - nx]); if (y < ny - 1) best = Math.max(best, L[i + nx]);
      if (z > 0) best = Math.max(best, L[i - nx * ny]); if (z < nz - 1) best = Math.max(best, L[i + nx * ny]);
      const v = best * DECAY;
      if (v > L[i]) L[i] = v;
    }
  }
  // one smoothing pass, so the 2 m grid does not show as blocks once interpolated
  const out = new Uint8Array(N);
  for (let z = 0; z < nz; z++) for (let y = 0; y < ny; y++) for (let x = 0; x < nx; x++) {
    const i = idx(x, y, z);
    let a = L[i] * 2, w = 2;
    if (x > 0) { a += L[i - 1]; w++; } if (x < nx - 1) { a += L[i + 1]; w++; }
    if (y > 0) { a += L[i - nx]; w++; } if (y < ny - 1) { a += L[i + nx]; w++; }
    if (z > 0) { a += L[i - nx * ny]; w++; } if (z < nz - 1) { a += L[i + nx * ny]; w++; }
    out[i] = Math.round(255 * Math.min(1, a / w));
  }
  return out;
}

if (typeof WorkerGlobalScope !== 'undefined' && self instanceof WorkerGlobalScope) {
  const h = VX.makeHandler();
  self.onmessage = function (e) { h(e.data, function (msg, tr) { self.postMessage(msg, tr || []); }); };
}

// ============================================================================
// v3 pipeline (10 cm voxels): plain quad meshes carrying baked sky visibility.
// No per-pixel ray marching, no 3D atlas. Each vertex stores, besides its VoxelId,
// an order-1 spherical-harmonic visibility of the sky at that corner. At runtime the
// ambient term is one dot product with the sky's own SH, so the time of day and the
// weather cost nothing. This is precomputed radiance transfer, kept to order 1.
// ============================================================================
(function (VX) {
  // 16-byte vertex: i16 x,y,z | u8 face | u8 ao | i8 bx,by,bz | u8 _ | u16 vid | u16 _
  function VOut(cap) { this.buf = new ArrayBuffer(cap || (1 << 16)); this.view(); this.n = 0; }
  VOut.prototype.view = function () { this.i16 = new Int16Array(this.buf); this.u8 = new Uint8Array(this.buf); this.i8 = new Int8Array(this.buf); this.u16 = new Uint16Array(this.buf); };
  VOut.prototype.grow = function () { const nb = new ArrayBuffer(this.buf.byteLength * 2); new Uint8Array(nb).set(this.u8); this.buf = nb; this.view(); };
  VOut.prototype.v = function (x, y, z, face, ao, bx, by, bz, vid) {
    if ((this.n + 1) * 16 > this.buf.byteLength) this.grow();
    const o8 = this.n * 16, o16 = this.n * 8;
    this.i16[o16] = x; this.i16[o16 + 1] = y; this.i16[o16 + 2] = z;
    this.u8[o8 + 6] = face; this.u8[o8 + 7] = ao;
    this.i8[o8 + 8] = bx; this.i8[o8 + 9] = by; this.i8[o8 + 10] = bz;
    this.u16[o16 + 6] = vid;
    this.n++;
  };
  VOut.prototype.result = function () { return this.buf.slice(0, this.n * 16); };
  VX.VOut = VOut;

  // axes in the face plane, per face (+x,-x,+y,-y,+z,-z)
  const FN = [[1, 0, 0], [-1, 0, 0], [0, 1, 0], [0, -1, 0], [0, 0, 1], [0, 0, -1]];
  const FU = [[0, 1, 0], [0, 0, 1], [0, 0, 1], [0, 1, 0], [0, 1, 0], [1, 0, 0]];
  const FV = [[0, 0, 1], [0, 1, 0], [1, 0, 0], [0, 0, 1], [1, 0, 0], [0, 1, 0]];
  const AOC = [0.34, 0.58, 0.78, 1.0];

  // density field: occupancy blurred three times with a 3-wide box, so openness varies smoothly
  // over about six voxels. Its gradient gives the direction the sky comes from (the bent normal).
  function density(V, NX, NY, NZ) {
    const N = NX * NY * NZ, a = new Float32Array(N), b = new Float32Array(N);
    for (let i = 0; i < N; i++) a[i] = V[i] ? 1 : 0;
    const sx = 1, sy = NX, sz = NX * NY;
    let src = a, dst = b;
    for (let p = 0; p < 3; p++) {
      for (const s of [sx, sy, sz]) {
        const len = s === sx ? NX : s === sy ? NY : NZ;
        for (let z = 0; z < NZ; z++) for (let y = 0; y < NY; y++) for (let x = 0; x < NX; x++) {
          const i = x + NX * (y + NY * z);
          const k = s === sx ? x : s === sy ? y : z;
          const lo = k > 0 ? src[i - s] : src[i], hi = k < len - 1 ? src[i + s] : src[i];
          dst[i] = (lo + src[i] + hi) * (1 / 3);
        }
        const t = src; src = dst; dst = t;
      }
    }
    return src;
  }

  // V: Uint16Array of VoxelId with a border of at least 4 empty cells on every side.
  // ox,oy,oz: voxel coordinates of cell (0,0,0). Vertices are written in voxel units.
  VX.meshVox = function (V, NX, NY, NZ, ox, oy, oz, out, step) {
    const D = density(V, NX, NY, NZ), sx = 1, sy = NX, sz = NX * NY;
    const s = step || 1;
    const solid = (i) => V[i] !== 0;
    const dens = (x, y, z) => {
      const xi = Math.max(0, Math.min(NX - 1, x)), yi = Math.max(0, Math.min(NY - 1, y)), zi = Math.max(0, Math.min(NZ - 1, z));
      return D[xi + NX * (yi + NY * zi)];
    };
    for (let z = 1; z < NZ - 1; z++) for (let y = 1; y < NY - 1; y++) for (let x = 1; x < NX - 1; x++) {
      const i = x + NX * (y + NY * z), vid = V[i];
      if (!vid) continue;
      for (let f = 0; f < 6; f++) {
        const n = FN[f], ni = i + n[0] * sx + n[1] * sy + n[2] * sz;
        if (solid(ni)) continue;
        const u = FU[f], v = FV[f];
        // bent normal: away from matter, measured one cell out from the face
        const cx = x + n[0], cy = y + n[1], cz = z + n[2];
        let gx = dens(cx + 1, cy, cz) - dens(cx - 1, cy, cz);
        let gy = dens(cx, cy + 1, cz) - dens(cx, cy - 1, cz);
        let gz = dens(cx, cy, cz + 1) - dens(cx, cy, cz - 1);
        let bx = n[0] * 0.75 - gx, by = n[1] * 0.75 - gy, bz = n[2] * 0.75 - gz;
        const bl = Math.hypot(bx, by, bz) || 1; bx /= bl; by /= bl; bz /= bl;
        const ib = [Math.round(bx * 127), Math.round(by * 127), Math.round(bz * 127)];
        // corners of the face, in the order the two triangles expect
        const base = [x + (n[0] > 0 ? 1 : 0), y + (n[1] > 0 ? 1 : 0), z + (n[2] > 0 ? 1 : 0)];
        const C = [[0, 0], [1, 0], [1, 1], [0, 1]], vtx = [];
        for (let k = 0; k < 4; k++) {
          const a = C[k][0], c = C[k][1];
          const du = a * 2 - 1, dv = c * 2 - 1;      // corner direction inside the plane
          const s1 = solid(ni + du * (u[0] * sx + u[1] * sy + u[2] * sz));
          const s2 = solid(ni + dv * (v[0] * sx + v[1] * sy + v[2] * sz));
          const sc = solid(ni + du * (u[0] * sx + u[1] * sy + u[2] * sz) + dv * (v[0] * sx + v[1] * sy + v[2] * sz));
          const lvl = (s1 && s2) ? 0 : 3 - ((s1 ? 1 : 0) + (s2 ? 1 : 0) + (sc ? 1 : 0));
          // large-scale openness one and a half cells out, towards this corner
          const ox2 = cx + n[0] * 0.5 + du * u[0] + dv * v[0], oy2 = cy + n[1] * 0.5 + du * u[1] + dv * v[1], oz2 = cz + n[2] * 0.5 + du * u[2] + dv * v[2];
          const open = 1 - dens(Math.round(ox2), Math.round(oy2), Math.round(oz2));
          const ao = Math.max(0, Math.min(255, Math.round(255 * AOC[lvl] * (0.35 + 0.65 * open))));
          vtx.push([(ox + base[0] + a * u[0] + c * v[0]) * s, (oy + base[1] + a * u[1] + c * v[1]) * s, (oz + base[2] + a * u[2] + c * v[2]) * s, ao]);
        }
        // keep the winding outward
        const order = (n[0] + n[1] + n[2] > 0) ? [0, 1, 2, 3] : [0, 3, 2, 1];
        for (const k of order) { const q = vtx[k]; out.v(q[0], q[1], q[2], f, q[3], ib[0], ib[1], ib[2], vid); }
      }
    }
  };

  // dense VoxelId grid of a module (with a 4-cell border), optionally downsampled by 2^lod
  VX.moduleGrid = function (mod, bricks, pool, lod) {
    const k = 1 << (lod || 0), B = 4;
    const nx = Math.ceil(mod.dx / k) + 2 * B, ny = Math.ceil(mod.dy / k) + 2 * B, nz = Math.ceil(mod.dz / k) + 2 * B;
    const V = new Uint16Array(nx * ny * nz);
    for (let z = 0; z < nz - 2 * B; z++) for (let y = 0; y < ny - 2 * B; y++) for (let x = 0; x < nx - 2 * B; x++) {
      let id = 0;
      if (k === 1) id = VX.getLocal(mod, bricks, pool, mod.ox + x, mod.oy + y, mod.oz + z);
      else {   // most frequent non-empty id of the 2^lod block
        const cnt = new Map();
        for (let c = 0; c < k; c++) for (let b = 0; b < k; b++) for (let a = 0; a < k; a++) {
          const w = VX.getLocal(mod, bricks, pool, mod.ox + x * k + a, mod.oy + y * k + b, mod.oz + z * k + c);
          if (w) cnt.set(w, (cnt.get(w) || 0) + 1);
        }
        let best = 0, bc = 0, tot = 0;
        for (const [w, c] of cnt) { tot += c; if (c > bc) { bc = c; best = w; } }
        // a third full is enough: at a half, trunks, fences and window bars vanish at distance
        if (tot * 3 >= k * k * k) id = best;
      }
      V[(x + B) + nx * ((y + B) + ny * (z + B))] = id;
    }
    return { V, nx, ny, nz, B, k };
  };

  VX.meshModuleV3 = function (mod, bricks, pool, lod) {
    const g = VX.moduleGrid(mod, bricks, pool, lod), out = new VX.VOut();
    VX.meshVox(g.V, g.nx, g.ny, g.nz, Math.floor(mod.ox / g.k) - g.B, Math.floor(mod.oy / g.k) - g.B, Math.floor(mod.oz / g.k) - g.B, out, g.k);
    return out.n ? { buf: out.result(), quads: out.n / 4 } : null;
  };
})(VX);

// ---------- v3 terrain: same voxel staircase, but shaded with the smooth ground normal ----------
// The silhouette stays blocky (that is the voxel look); only the shading normal is continuous,
// which is what turns a flat green plane into rolling ground. Each vertex also carries a
// hollow/ridge occlusion term computed from the height field, so dips darken on their own.
(function (VX) {
  VX.meshTerrainV3 = function (T, x0, z0, S, s) {
    const n = S / s, N = n + 4, O = 2;                 // O cells of margin on each side
    const H = new Int32Array(N * N), FH = new Float32Array(N * N), K = new Uint8Array(N * N);
    const at = (i, j) => Math.max(0, Math.min(N - 1, i + O)) + N * Math.max(0, Math.min(N - 1, j + O));
    for (let j = -O; j < n + O; j++) for (let i = -O; i < n + O; i++) {
      const x = x0 + i * s + (s >> 1), z = z0 + j * s + (s >> 1);
      const h = T.height(x, z);
      const q = (i + O) + N * (j + O);
      H[q] = h; FH[q] = T.natural(x, z) / VX.VS;
      K[q] = T.topClass(x, z, Math.abs(T.natural(x + s, z) - T.natural(x - s, z)) / VX.VS / (2 * s)
                            + Math.abs(T.natural(x, z + s) - T.natural(x, z - s)) / VX.VS / (2 * s));
    }
    // blurred height, for the hollow/ridge term
    const BL = new Float32Array(N * N);
    for (let j = 0; j < N; j++) for (let i = 0; i < N; i++) {
      let a = 0, c = 0;
      for (let b = -2; b <= 2; b++) for (let d = -2; d <= 2; d++) { a += FH[at(i - O + d, j - O + b)]; c++; }
      BL[i + N * j] = a / c;
    }
    const out = new VX.VOut();
    // smooth normal and occlusion at the corner between cells (i-1,j-1)..(i,j)
    const corner = (i, j) => {
      const h00 = FH[at(i - 1, j - 1)], h10 = FH[at(i, j - 1)], h01 = FH[at(i - 1, j)], h11 = FH[at(i, j)];
      const w00 = FH[at(i - 2, j - 2)], w10 = FH[at(i + 1, j - 2)], w01 = FH[at(i - 2, j + 1)], w11 = FH[at(i + 1, j + 1)];
      const dx = ((h10 + h11 + w10 + w11) - (h00 + h01 + w00 + w01)) / (6 * s);
      const dz = ((h01 + h11 + w01 + w11) - (h00 + h10 + w00 + w10)) / (6 * s);
      let nx = -dx, ny = 1, nz = -dz; const l = Math.hypot(nx, ny, nz); nx /= l; ny /= l; nz /= l;
      const hc = (h00 + h10 + h01 + h11) * 0.25;
      const bc = (BL[at(i - 1, j - 1)] + BL[at(i, j - 1)] + BL[at(i - 1, j)] + BL[at(i, j)]) * 0.25;
      const rel = (bc - hc) / Math.max(1, 2.2 / VX.VS);                 // positive in a hollow
      const ao = Math.max(0, Math.min(255, Math.round(255 * (1 - 0.55 * Math.max(0, Math.min(1, rel))))));
      return [ao, Math.round(nx * 127), Math.round(ny * 127), Math.round(nz * 127)];
    };
    const tint = (k, x, z) => {
      const g = VX.hash2(Math.floor(x / Math.max(1, 0.5 / VX.VS)), Math.floor(z / Math.max(1, 0.5 / VX.VS)), 44 + k);
      const f = VX.hash2(Math.floor(x / Math.max(1, 6 / VX.VS)), Math.floor(z / Math.max(1, 6 / VX.VS)), 70 + k);
      return Math.min(127, Math.max(0, Math.round(28 + g * 58 + f * 40)));
    };
    // top faces, merged while the height and the class agree
    const done = new Uint8Array(n * n);
    for (let j = 0; j < n; j++) for (let i = 0; i < n; i++) {
      if (done[i + n * j]) continue;
      const h = H[at(i, j)], k = K[at(i, j)];
      const MAXQ = 6;
      let w = 1; while (w < MAXQ && i + w < n && !done[i + w + n * j] && H[at(i + w, j)] === h && K[at(i + w, j)] === k) w++;
      let hh = 1;
      outer: for (; hh < MAXQ && j + hh < n; hh++) for (let a = 0; a < w; a++) {
        if (done[i + a + n * (j + hh)] || H[at(i + a, j + hh)] !== h || K[at(i + a, j + hh)] !== k) break outer;
      }
      for (let b = 0; b < hh; b++) done.fill(1, i + n * (j + b), i + w + n * (j + b));
      const X = x0 + i * s, Z = z0 + j * s, Wd = w * s, D = hh * s;
      const vid = k << 7 | tint(k, X, Z);
      const c00 = corner(i, j), c01 = corner(i, j + hh), c11 = corner(i + w, j + hh), c10 = corner(i + w, j);
      out.v(X, h, Z, 2, c00[0], c00[1], c00[2], c00[3], vid);
      out.v(X, h, Z + D, 2, c01[0], c01[1], c01[2], c01[3], vid);
      out.v(X + Wd, h, Z + D, 2, c11[0], c11[1], c11[2], c11[3], vid);
      out.v(X + Wd, h, Z, 2, c10[0], c10[1], c10[2], c10[3], vid);
    }
    // side faces towards lower neighbours, plus a skirt at the leaf border
    const dirs = [[1, 0, 0], [-1, 0, 1], [0, 1, 4], [0, -1, 5]];
    const skin = Math.max(1, Math.round((s > 1 ? 1.2 : 0.3) / VX.VS));
    for (let j = 0; j < n; j++) for (let i = 0; i < n; i++) {
      const h = H[at(i, j)], k = K[at(i, j)];
      for (let q = 0; q < 4; q++) {
        const di = dirs[q][0], dj = dirs[q][1], face = dirs[q][2];
        const ni = i + di, nj = j + dj;
        let hn = H[at(ni, nj)];
        if (ni < 0 || nj < 0 || ni >= n || nj >= n) hn = Math.min(hn, h) - 2 * s - Math.round(0.6 / VX.VS);
        if (hn >= h) continue;
        const top = Math.max(hn, h - skin);
        side(out, x0 + i * s, z0 + j * s, s, face, top, h, k << 7 | tint(k, x0 + i * s, z0 + j * s), h);
        if (top > hn) side(out, x0 + i * s, z0 + j * s, s, face, hn, top, 17 << 7 | tint(17, x0 + i * s, z0 + j * s), h);
      }
    }
    return out.n ? { buf: out.result(), quads: out.n / 4 } : null;
  };
  // vertical face of a terrain column; darkens towards the bottom, where little sky reaches
  function side(out, X, Z, s, face, y0, y1, vid, hTop) {
    const N6 = [[1, 0, 0], [-1, 0, 0], null, null, [0, 0, 1], [0, 0, -1]][face];
    const a0 = Math.max(0, Math.min(255, Math.round(255 * (0.30 + 0.70 * Math.max(0, 1 - (hTop - y0) / Math.max(1, 1.5 / VX.VS))))));
    const a1 = Math.max(0, Math.min(255, Math.round(255 * (0.30 + 0.70 * Math.max(0, 1 - (hTop - y1) / Math.max(1, 1.5 / VX.VS))))));
    const b = [Math.round(N6[0] * 90), Math.round(0.55 * 127), Math.round(N6[2] * 90)];
    const P = (x, y, z, ao) => out.v(x, y, z, face, ao, b[0], b[1], b[2], vid);
    if (face === 0) { const x = X + s; P(x, y0, Z, a0); P(x, y1, Z, a1); P(x, y1, Z + s, a1); P(x, y0, Z + s, a0); }
    else if (face === 1) { const x = X; P(x, y0, Z, a0); P(x, y0, Z + s, a0); P(x, y1, Z + s, a1); P(x, y1, Z, a1); }
    else if (face === 4) { const z = Z + s; P(X, y0, z, a0); P(X + s, y0, z, a0); P(X + s, y1, z, a1); P(X, y1, z, a1); }
    else { const z = Z; P(X, y0, z, a0); P(X, y1, z, a1); P(X + s, y1, z, a1); P(X + s, y0, z, a0); }
  }

  // dug terrain leaf: a real 3D mesh, so the same mesher as the modules handles it
  VX.meshTerrainEditedV3 = function (T, x0, z0, S, removed) {
    const B = 4, N = S + 2 * B;
    const H = new Int32Array(N * N), K = new Uint8Array(N * N);
    let ymin = 1e9, ymax = -1e9;
    for (let j = 0; j < N; j++) for (let i = 0; i < N; i++) {
      const h = T.height(x0 + i - B, z0 + j - B);
      H[i + N * j] = h; K[i + N * j] = T.topClass(x0 + i - B, z0 + j - B);
      if (h < ymin) ymin = h; if (h > ymax) ymax = h;
    }
    let ylow = ymin;
    for (let r = 0; r < removed.length; r++) { const y = Math.floor(removed[r] / (S * S)); if (y < ylow) ylow = y; }
    ylow -= B;
    const NY = ymax - ylow + 2 * B;
    if (NY * N * N > 8e6) return null;
    const C = new Uint16Array(N * NY * N);
    for (let j = 0; j < N; j++) for (let i = 0; i < N; i++) {
      const h = H[i + N * j], k = K[i + N * j];
      for (let yy = 0; yy < NY; yy++) {
        const y = ylow + yy;
        if (y < h) { const c = T.classAt(k, h - 1 - y); C[i + N * (yy + NY * j)] = c << 7 | (40 + ((VX.hash2(x0 + i, z0 + j + y * 31, 44 + c) * 50) | 0)); }
      }
    }
    for (let r = 0; r < removed.length; r++) {
      const v = removed[r], lx = v % S, lz = Math.floor(v / S) % S, y = Math.floor(v / (S * S));
      const yy = y - ylow;
      if (yy > 0 && yy < NY) C[(lx + B) + N * (yy + NY * (lz + B))] = 0;
    }
    const out = new VX.VOut();
    VX.meshVox(C, N, NY, N, x0 - B, ylow, z0 - B, out, 1);
    return out.n ? { buf: out.result(), quads: out.n / 4 } : null;
  };
})(VX);
