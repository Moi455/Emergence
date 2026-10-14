// Deterministic integer hashing and PRNG. Only integer ops and IEEE + - * / sqrt are
// used anywhere in generation, so outputs are bit-identical across JS engines (and
// portable to the C++ core).

export function hash32(a) {
  a = (a ^ 61) ^ (a >>> 16);
  a = Math.imul(a, 9);
  a = a ^ (a >>> 4);
  a = Math.imul(a, 0x27d4eb2d);
  a = a ^ (a >>> 15);
  return a >>> 0;
}

export function hashCombine(...xs) {
  let h = 0x9e3779b9;
  for (const x of xs) {
    let v = typeof x === 'string' ? strHash(x) : (x | 0);
    h = hash32((h ^ v) + 0x7f4a7c15 + Math.imul(h, 31));
  }
  return h >>> 0;
}

export function strHash(s) {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); }
  return h >>> 0;
}

// Hash of an integer lattice point to [0,1)
export function h3(x, y, z, seed) {
  let h = Math.imul(x | 0, 0x8da6b343) ^ Math.imul(y | 0, 0xd8163841) ^ Math.imul(z | 0, 0xcb1ab31f) ^ seed;
  return hash32(h) / 4294967296;
}

// Value noise on an integer lattice with cell size `s` (integer voxels), trilinear, deterministic
export function vnoise(x, y, z, s, seed) {
  const fx = x / s, fy = y / s, fz = z / s;
  const ix = Math.floor(fx), iy = Math.floor(fy), iz = Math.floor(fz);
  let tx = fx - ix, ty = fy - iy, tz = fz - iz;
  tx = tx * tx * (3 - 2 * tx); ty = ty * ty * (3 - 2 * ty); tz = tz * tz * (3 - 2 * tz);
  const c = (a, b, d) => h3(ix + a, iy + b, iz + d, seed);
  const x00 = c(0,0,0) + (c(1,0,0) - c(0,0,0)) * tx;
  const x10 = c(0,1,0) + (c(1,1,0) - c(0,1,0)) * tx;
  const x01 = c(0,0,1) + (c(1,0,1) - c(0,0,1)) * tx;
  const x11 = c(0,1,1) + (c(1,1,1) - c(0,1,1)) * tx;
  const y0 = x00 + (x10 - x00) * ty, y1 = x01 + (x11 - x01) * ty;
  return y0 + (y1 - y0) * tz;
}

export class Rng {
  constructor(seed) { this.s = [hash32(seed ^ 0xa5a5a5a5), hash32(seed + 1), hash32(seed + 2), hash32(seed + 3) | 1]; }
  u32() {
    let [a, b, c, d] = this.s;
    const t = (((a + b) | 0) + d) | 0;
    d = (d + 1) | 0; a = b ^ (b >>> 9); b = (c + (c << 3)) | 0; c = (c << 21) | (c >>> 11); c = (c + t) | 0;
    this.s = [a, b, c, d];
    return t >>> 0;
  }
  f() { return this.u32() / 4294967296; }
  range(a, b) { return a + (b - a) * this.f(); }
  int(a, b) { return a + Math.floor(this.f() * (b - a + 1)); }
  chance(p) { return this.f() < p; }
  pick(arr) { return arr[Math.floor(this.f() * arr.length)]; }
  // weighted pick over {key: weight} or [[item, w], ...]
  wpick(entries) {
    if (!Array.isArray(entries)) entries = Object.entries(entries);
    let tot = 0; for (const [, w] of entries) tot += w;
    let r = this.f() * tot;
    for (const [k, w] of entries) { if ((r -= w) < 0) return k; }
    return entries[entries.length - 1][0];
  }
  gauss() { let s = 0; for (let i = 0; i < 4; i++) s += this.f(); return (s - 2) * 1.732; }
  fork(...keys) { return new Rng(hashCombine(this.s[0], ...keys)); }
}
