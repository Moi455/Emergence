// Body: skeleton (Godot SkeletonProfileHumanoid names), signed-distance body built from
// primitives attached to bones, voxelized into a character grid in bind pose
// (arms down, palms facing the thighs, character facing +Z, its left side is +X, Y up).
import { h3 } from './rng.js';
import { mix, ramp, rgb, R, G, B, mul } from './color.js';

export const MODE_NORMAL = 0, MODE_SKIRT = 1, MODE_CLOAK = 2, MODE_RIGID = 3;
export const MAT = { skin: 1, hair: 2, cloth: 3, leather: 4, metal: 5, wood: 6, fur: 7, straw: 8, eye: 9, gem: 10 };

export class Grid {
  constructor(nx, ny, nz, ox, oz) {
    this.nx = nx; this.ny = ny; this.nz = nz; this.ox = ox; this.oz = oz;
    const n = nx * ny * nz;
    this.col = new Uint32Array(n);   // 0 = empty, else 0x1RRGGBB
    this.bone = new Uint8Array(n);
    this.mode = new Uint8Array(n);
    this.mat = new Uint8Array(n);
    this.layer = new Uint8Array(n);
  }
  idx(x, y, z) { return x + this.nx * (y + this.ny * z); }
  inb(x, y, z) { return x >= 0 && y >= 0 && z >= 0 && x < this.nx && y < this.ny && z < this.nz; }
  get(x, y, z) { return this.inb(x, y, z) ? this.col[this.idx(x, y, z)] : 0; }
  set(x, y, z, c, bone, mat, layer = 0, mode = 0) {
    if (!this.inb(x, y, z)) return;
    const i = this.idx(x, y, z);
    this.col[i] = (c & 0xffffff) | 0x1000000; this.bone[i] = bone; this.mat[i] = mat; this.layer[i] = layer; this.mode[i] = mode;
  }
  clear(x, y, z) { if (this.inb(x, y, z)) this.col[this.idx(x, y, z)] = 0; }
  clone() {
    const g = new Grid(this.nx, this.ny, this.nz, this.ox, this.oz);
    g.col.set(this.col); g.bone.set(this.bone); g.mode.set(this.mode); g.mat.set(this.mat); g.layer.set(this.layer);
    return g;
  }
  // voxel-space center of cell (character units, origin between the feet on the ground)
  cx(i) { return i + 0.5 - this.ox; }
  cz(k) { return k + 0.5 - this.oz; }
}

// ---------------------------------------------------------------- SDF primitives
const sq = v => v * v;
function sdEllipsoid(px, py, pz, rx, ry, rz) {
  const k0 = Math.sqrt(sq(px / rx) + sq(py / ry) + sq(pz / rz));
  const k1 = Math.sqrt(sq(px / (rx * rx)) + sq(py / (ry * ry)) + sq(pz / (rz * rz)));
  return k1 === 0 ? -Math.min(rx, ry, rz) : k0 * (k0 - 1) / k1;
}
function sdCapsule(px, py, pz, a, b, r0, r1) {
  const bax = b[0] - a[0], bay = b[1] - a[1], baz = b[2] - a[2];
  const pax = px - a[0], pay = py - a[1], paz = pz - a[2];
  let t = (pax * bax + pay * bay + paz * baz) / (bax * bax + bay * bay + baz * baz);
  t = t < 0 ? 0 : t > 1 ? 1 : t;
  const dx = pax - bax * t, dy = pay - bay * t, dz = paz - baz * t;
  return Math.sqrt(dx * dx + dy * dy + dz * dz) - (r0 + (r1 - r0) * t);
}
function sdRoundBox(px, py, pz, hx, hy, hz, r) {
  const qx = Math.abs(px) - hx + r, qy = Math.abs(py) - hy + r, qz = Math.abs(pz) - hz + r;
  const mx = Math.max(qx, 0), my = Math.max(qy, 0), mz = Math.max(qz, 0);
  return Math.sqrt(mx * mx + my * my + mz * mz) + Math.min(Math.max(qx, qy, qz), 0) - r;
}
export function evalPrim(p, x, y, z) {
  switch (p.kind) {
    case 'ell': return sdEllipsoid(x - p.c[0], y - p.c[1], z - p.c[2], p.r[0], p.r[1], p.r[2]);
    case 'cap': return sdCapsule(x, y, z, p.a, p.b, p.r0, p.r1);
    case 'box': return sdRoundBox(x - p.c[0], y - p.c[1], z - p.c[2], p.h[0], p.h[1], p.h[2], p.round);
  }
}
export function primBox(p) {
  if (p.kind === 'ell') return [p.c[0] - p.r[0], p.c[1] - p.r[1], p.c[2] - p.r[2], p.c[0] + p.r[0], p.c[1] + p.r[1], p.c[2] + p.r[2]];
  if (p.kind === 'box') return [p.c[0] - p.h[0], p.c[1] - p.h[1], p.c[2] - p.h[2], p.c[0] + p.h[0], p.c[1] + p.h[1], p.c[2] + p.h[2]];
  const r = Math.max(p.r0, p.r1);
  return [Math.min(p.a[0], p.b[0]) - r, Math.min(p.a[1], p.b[1]) - r, Math.min(p.a[2], p.b[2]) - r,
          Math.max(p.a[0], p.b[0]) + r, Math.max(p.a[1], p.b[1]) + r, Math.max(p.a[2], p.b[2]) + r];
}
export function smin(a, b, k) { const h = Math.max(k - Math.abs(a - b), 0) / k; return Math.min(a, b) - h * h * k * 0.25; }
export const clamp01 = v => v < 0 ? 0 : v > 1 ? 1 : v;
export const smooth = (e0, e1, x) => { const t = clamp01((x - e0) / (e1 - e0)); return t * t * (3 - 2 * t); };

// ---------------------------------------------------------------- skeleton
const SIDES = [['Left', 1], ['Right', -1]];
const FINGERS = ['Index', 'Middle', 'Ring', 'Little'];

export function proportions(bp) {
  // all values are fractions of the height H
  const { sex, age, build: b, muscle: m } = bp;
  const child = age < 13, teen = age >= 13 && age < 18, elder = age >= 60;
  const f = sex === 'f';
  // close to real proportions (adult head about 1/7 of the height, as in the reference image)
  let headH = child ? 0.19 + (12 - age) * 0.006 : teen ? 0.158 : 0.145;
  if (f) headH += 0.002;
  const P = { headH, child, teen, elder, f };
  P.ry = headH * 0.5; P.rx = headH * (0.42 + b * 0.012) ; P.rz = headH * 0.45;
  P.cy = 0.985 - P.ry;
  P.yNb = P.cy - P.ry - (child ? 0.022 : 0.034);
  P.yS = P.yNb - 0.012;
  P.sx = (child ? 0.112 : f ? 0.116 : 0.130) + b * 0.010 + m * 0.012;
  P.ax = P.sx + (child ? 0.016 : 0.014);
  P.ru = (f ? 0.029 : 0.033) + b * 0.009 + m * 0.007 + (child ? 0.006 : 0);
  P.rf = P.ru * 0.88;
  const armScale = child ? 0.92 : 1;
  P.yEl = P.yS - 0.03 - 0.172 * armScale;
  P.yW = P.yEl - 0.150 * armScale;
  P.hl = child ? 0.092 : 0.098; // hand length
  P.yHip = child ? 0.425 : teen ? 0.455 : 0.468;
  P.lx = (f ? 0.060 : 0.057) + b * 0.010 + (child ? 0.004 : 0);
  P.yK = P.yHip * 0.52;
  P.yA = 0.046;
  P.rth = (f ? 0.064 : 0.060) + b * 0.020 + m * 0.006 + (child ? 0.006 : 0);
  P.rsh = 0.040 + b * 0.008 + m * 0.006 + (child ? 0.004 : 0);
  P.footL = child ? 0.165 : 0.150; P.footW = child ? 0.034 : 0.031;
  P.neckR = (f ? 0.030 : 0.034) + b * 0.006 + m * 0.004;
  return P;
}

export function makeSkeleton(P, U) {
  // U = voxels per height unit. Returns bones with head positions (voxel units).
  const bones = [], byName = {};
  const add = (name, parent, head, tail) => {
    const b = { name, parent: parent == null ? -1 : byName[parent], head: head.map(v => v * U), tail: tail ? tail.map(v => v * U) : null, index: bones.length };
    bones.push(b); byName[name] = b.index; return b;
  };
  const tl = P.yS - P.yHip;
  const ySp = P.yHip + 0.30 * tl, yCh = P.yHip + 0.52 * tl, yUC = P.yHip + 0.74 * tl;
  add('Root', null, [0, 0, 0]);
  add('Hips', 'Root', [0, P.yHip + 0.10 * tl, 0]);
  add('Spine', 'Hips', [0, ySp, 0]);
  add('Chest', 'Spine', [0, yCh, 0]);
  add('UpperChest', 'Chest', [0, yUC, 0]);
  add('Neck', 'UpperChest', [0, P.yNb, -0.004]);
  add('Head', 'Neck', [0, P.cy - P.ry * 0.62, 0], [0, 1.0, 0]);
  for (const [S, s] of SIDES) {
    add(S + 'Shoulder', 'UpperChest', [s * 0.022, P.yS - 0.014, -0.004]);
    add(S + 'UpperArm', S + 'Shoulder', [s * P.ax, P.yS - 0.028, -0.004]);
    add(S + 'LowerArm', S + 'UpperArm', [s * P.ax, P.yEl, -0.004]);
    add(S + 'Hand', S + 'LowerArm', [s * P.ax, P.yW, 0]);
    add(S + 'ThumbMetacarpal', S + 'Hand', [s * (P.ax - 0.004), P.yW - 0.012, 0.022]);
    add(S + 'ThumbProximal', S + 'ThumbMetacarpal', [s * (P.ax - 0.006), P.yW - 0.040, 0.034], [s * (P.ax - 0.008), P.yW - 0.066, 0.040]);
    FINGERS.forEach((F, i) => {
      const z = 0.020 - i * 0.0135;
      add(S + F + 'Proximal', S + 'Hand', [s * P.ax, P.yW - P.hl * 0.50, z]);
      add(S + F + 'Intermediate', S + F + 'Proximal', [s * P.ax, P.yW - P.hl * 0.74, z], [s * P.ax, P.yW - P.hl, z]);
    });
  }
  for (const [S, s] of SIDES) {
    add(S + 'UpperLeg', 'Hips', [s * P.lx, P.yHip, 0]);
    add(S + 'LowerLeg', S + 'UpperLeg', [s * P.lx, P.yK, 0]);
    add(S + 'Foot', S + 'LowerLeg', [s * P.lx, P.yA, -0.006]);
    add(S + 'Toes', S + 'Foot', [s * P.lx, 0.018, P.footL * 0.55], [s * P.lx, 0.018, P.footL * 0.86]);
  }
  // Appended after the original 43 so earlier bone indices never move (interfaces.md § 3).
  // Third phalanges carry skin weights; eyes, jaw and attachment points carry none.
  for (const [S, s] of SIDES) {
    add(S + 'ThumbDistal', S + 'ThumbProximal', [s * (P.ax - 0.007), P.yW - 0.056, 0.038], [s * (P.ax - 0.008), P.yW - 0.068, 0.041]);
    FINGERS.forEach((F, i) => {
      const z = 0.020 - i * 0.0135;
      add(S + F + 'Distal', S + F + 'Intermediate', [s * P.ax, P.yW - P.hl * 0.88, z], [s * P.ax, P.yW - P.hl, z]);
    });
  }
  const eyeY = P.cy - P.headH * 0.045, eyeX = P.headH * 0.175;
  for (const [S, s] of SIDES) add(S + 'Eye', 'Head', [s * eyeX, eyeY, P.rz * 0.8], [s * eyeX, eyeY, P.rz * 1.1]);
  add('Jaw', 'Head', [0, P.cy - P.ry * 0.35, P.rz * 0.15], [0, P.cy - P.ry * 0.95, P.rz * 0.75]);
  // attachment points: tool grip in the palm (handle along local +Y), back, right hip, top of head
  for (const [S, s] of SIDES) add(S + 'HandProp', S + 'Hand', [s * P.ax, P.yW - P.hl * 0.42, 0.006], [s * P.ax, P.yW - P.hl * 0.42 + 0.1, 0.006]);
  add('BackProp', 'UpperChest', [0, yUC, -0.1], [0, yUC + 0.1, -0.1]);
  add('HipProp', 'Hips', [-(P.lx + 0.075), P.yHip + 0.02, 0.01], [-(P.lx + 0.075), P.yHip + 0.12, 0.01]);
  add('HeadProp', 'Head', [0, P.cy + P.ry, 0], [0, P.cy + P.ry + 0.1, 0]);
  // tails: first child head, else explicit
  for (const b of bones) {
    if (b.tail) continue;
    const kid = bones.find(c => c.parent === b.index && !/Shoulder|Thumb|Index|Middle|Ring|Little|UpperLeg/.test(c.name) ) || bones.find(c => c.parent === b.index);
    b.tail = kid ? kid.head.slice() : [b.head[0], b.head[1] + 0.05 * U, b.head[2]];
  }
  // Hips' natural tail is the spine; legs blend from Hips
  return { bones, byName };
}

// Joint blend zones (radius in H fractions). Axis = direction of the child bone.
export function makeJoints(sk, P, U) {
  const J = [];
  const n = sk.byName;
  const add = (parent, child, r) => {
    const c = sk.bones[n[child]];
    const ax = [c.tail[0] - c.head[0], c.tail[1] - c.head[1], c.tail[2] - c.head[2]];
    const l = Math.sqrt(ax[0] * ax[0] + ax[1] * ax[1] + ax[2] * ax[2]) || 1;
    J.push({ p: n[parent], c: n[child], pos: c.head, axis: ax.map(v => v / l), r: r * U });
  };
  add('Hips', 'Spine', 0.045); add('Spine', 'Chest', 0.04); add('Chest', 'UpperChest', 0.035);
  add('UpperChest', 'Neck', 0.02); add('Neck', 'Head', 0.014);
  for (const [S] of SIDES) {
    add('UpperChest', S + 'Shoulder', 0.02); add(S + 'Shoulder', S + 'UpperArm', 0.032);
    add(S + 'UpperArm', S + 'LowerArm', 0.026); add(S + 'LowerArm', S + 'Hand', 0.016);
    add(S + 'Hand', S + 'ThumbMetacarpal', 0.006); add(S + 'ThumbMetacarpal', S + 'ThumbProximal', 0.004);
    for (const F of FINGERS) { add(S + 'Hand', S + F + 'Proximal', 0.008); add(S + F + 'Proximal', S + F + 'Intermediate', 0.005); add(S + F + 'Intermediate', S + F + 'Distal', 0.004); }
    add(S + 'ThumbProximal', S + 'ThumbDistal', 0.003);
    add('Hips', S + 'UpperLeg', 0.04); add(S + 'UpperLeg', S + 'LowerLeg', 0.028);
    add(S + 'LowerLeg', S + 'Foot', 0.018); add(S + 'Foot', S + 'Toes', 0.01);
  }
  const byBone = Array.from({ length: sk.bones.length }, () => []);
  for (const j of J) { byBone[j.p].push(j); byBone[j.c].push(j); }
  return { list: J, byBone };
}

// ---------------------------------------------------------------- primitives
export function bodyPrimitives(P, bp, U, sk) {
  const n = sk.byName, prims = [];
  const u = v => v * U;
  const E = (bone, c, r, part) => prims.push({ kind: 'ell', bone: n[bone], c: c.map(u), r: r.map(u), part });
  const C = (bone, a, b, r0, r1, part) => prims.push({ kind: 'cap', bone: n[bone], a: a.map(u), b: b.map(u), r0: u(r0), r1: u(r1), part });
  const X = (bone, c, h, round, part) => prims.push({ kind: 'box', bone: n[bone], c: c.map(u), h: h.map(u), round: u(round), part });
  const b = bp.build, m = bp.muscle, f = P.f;
  // head
  X('Head', [0, P.cy + P.ry * 0.08, -P.rz * 0.02], [P.rx, P.ry * 0.92, P.rz], Math.min(P.rx, P.rz) * 0.5, 'head');
  X('Head', [0, P.cy - P.ry * 0.46, P.rz * 0.1], [P.rx * (f ? 0.78 : 0.86) * bp.jaw, P.ry * 0.5, P.rz * 0.86], P.rx * (f ? 0.5 : 0.4), 'head');
  // neck
  C('Neck', [0, P.yNb - 0.01, -0.006], [0, P.cy - P.ry * 0.5, -0.004], P.neckR, P.neckR * 0.95, 'neck');
  // torso
  const tl = P.yS - P.yHip;
  const chestRx = P.sx - (f ? 0.040 : 0.044) + b * 0.008;
  E('Chest', [0, P.yS - 0.088, 0.002], [chestRx, 0.094, 0.074 + b * 0.012 + m * 0.008 - (P.child ? 0.006 : 0)], 'torso');
  // trapezius / clavicle line
  for (const [S, s] of SIDES) C(S + 'Shoulder', [s * 0.03, P.yS - 0.024, -0.008], [s * (P.ax - 0.012), P.yS - 0.032, -0.006], 0.026 + m * 0.004, 0.026 + m * 0.004, 'torso');
  const wy = P.yHip + tl * 0.42;
  E('Spine', [0, wy, 0], [(f ? 0.086 : 0.095) + b * 0.034, 0.092, 0.064 + b * 0.026], 'torso');
  if (b > 0.15) E('Spine', [0, wy - 0.012, 0.028 + b * 0.02], [0.07 + b * 0.03, 0.07 + b * 0.012, 0.048 + b * 0.034], 'torso');
  E('Hips', [0, P.yHip + 0.035, -0.006], [(f ? 0.118 : 0.106) + b * 0.026, 0.072, 0.07 + b * 0.02], 'torso');
  if (f && !P.child && !P.teen) for (const [, s] of SIDES)
    E('Chest', [s * 0.042, P.yS - 0.108, 0.038 + b * 0.01], [0.04, 0.036, 0.034 * bp.bust], 'torso');
  for (const [S, s] of SIDES) {
    const ax = s * P.ax;
    // deltoid
    E(S + 'UpperArm', [ax, P.yS - 0.048, -0.004], [P.ru * 1.08, P.ru * 1.25, P.ru * 1.04], 'arm');
    C(S + 'UpperArm', [ax, P.yS - 0.04, -0.004], [ax, P.yEl, -0.004], P.ru, P.ru * 0.86, 'arm');
    C(S + 'LowerArm', [ax, P.yEl, -0.004], [ax, P.yW + 0.006, 0], P.rf, P.rf * 0.74, 'arm');
    // hand (palm faces -s*x, thumb forward)
    const hw = P.child ? 0.026 : 0.028;
    X(S + 'Hand', [ax, P.yW - P.hl * 0.5 + 0.004, 0.0015], [0.0155 + b * 0.002, P.hl * 0.5, hw], 0.007, 'hand');
    C(S + 'ThumbProximal', [ax - s * 0.003, P.yW - 0.014, 0.022], [ax - s * 0.006, P.yW - 0.062, 0.038], 0.012, 0.0105, 'hand');
    // legs
    const lx = s * P.lx;
    C(S + 'UpperLeg', [lx, P.yHip + 0.02, 0], [lx, P.yK, 0.002], P.rth, P.rsh * 1.04, 'leg');
    C(S + 'LowerLeg', [lx, P.yK, 0.002], [lx, P.yA + 0.01, -0.004], P.rsh, P.rsh * 0.66, 'leg');
    E(S + 'LowerLeg', [lx, P.yK - 0.075, -0.014], [P.rsh * 0.96, 0.075, P.rsh * 0.95], 'leg');
    X(S + 'Foot', [lx, 0.031, P.footL * 0.33 - 0.03], [P.footW + b * 0.003, 0.031, P.footL * 0.5], 0.013, 'foot');
  }
  return prims;
}

// ---------------------------------------------------------------- field
// Distance field of the body (voxel units), the nearest primitive's bone per cell.
export function bodyField(grid, prims, margin, k) {
  const n = grid.nx * grid.ny * grid.nz;
  const d = new Float32Array(n).fill(1e9), rawd = new Float32Array(n).fill(1e9);
  const lab = new Uint8Array(n), part = new Uint8Array(n);
  const PARTS = { head: 1, neck: 2, torso: 3, arm: 4, hand: 5, leg: 6, foot: 7 };
  for (const p of prims) {
    const bb = primBox(p);
    const x0 = Math.max(0, Math.floor(bb[0] - margin + grid.ox)), x1 = Math.min(grid.nx - 1, Math.ceil(bb[3] + margin + grid.ox));
    const y0 = Math.max(0, Math.floor(bb[1] - margin)), y1 = Math.min(grid.ny - 1, Math.ceil(bb[4] + margin));
    const z0 = Math.max(0, Math.floor(bb[2] - margin + grid.oz)), z1 = Math.min(grid.nz - 1, Math.ceil(bb[5] + margin + grid.oz));
    for (let zk = z0; zk <= z1; zk++) for (let yj = y0; yj <= y1; yj++) for (let xi = x0; xi <= x1; xi++) {
      const v = evalPrim(p, grid.cx(xi), yj + 0.5, grid.cz(zk));
      const i = grid.idx(xi, yj, zk);
      if (v < rawd[i]) { rawd[i] = v; lab[i] = p.bone; part[i] = PARTS[p.part]; }
      d[i] = d[i] > 1e8 ? v : smin(d[i], v, k);
    }
  }
  return { d, lab, part, PARTS };
}

// Assign torso / hand / foot cells to finer bones by position.
export function refineLabels(grid, field, sk, P, U) {
  const n = sk.byName, B = sk.bones;
  const yUC = B[n.UpperChest].head[1], yCh = B[n.Chest].head[1], ySp = B[n.Spine].head[1];
  const { lab, part, PARTS } = field;
  for (let zk = 0; zk < grid.nz; zk++) for (let yj = 0; yj < grid.ny; yj++) for (let xi = 0; xi < grid.nx; xi++) {
    const i = grid.idx(xi, yj, zk);
    const y = yj + 0.5, x = grid.cx(xi), z = grid.cz(zk);
    const pt = part[i];
    if (pt === PARTS.torso) {
      const nm = B[lab[i]].name;
      if (/Shoulder/.test(nm)) continue;
      lab[i] = y > yUC ? n.UpperChest : y > yCh ? n.Chest : y > ySp ? n.Spine : n.Hips;
    } else if (pt === PARTS.hand) {
      const S = x > 0 ? 'Left' : 'Right';
      if (/Thumb/.test(B[lab[i]].name)) {
        lab[i] = y > P.yW * U - 0.03 * U ? n[S + 'ThumbMetacarpal'] : y > (P.yW - 0.056) * U ? n[S + 'ThumbProximal'] : n[S + 'ThumbDistal'];
        continue;
      }
      const yf = P.yW * U - P.hl * U * 0.5;
      if (y < yf) {
        const zr = 0.0275 * U; // hand half width
        let fi = Math.floor((zr - z) / (2 * zr) * 4); fi = fi < 0 ? 0 : fi > 3 ? 3 : fi;
        const F = FINGERS[fi];
        lab[i] = y > P.yW * U - P.hl * U * 0.74 ? n[S + F + 'Proximal'] : y > (P.yW - P.hl * 0.88) * U ? n[S + F + 'Intermediate'] : n[S + F + 'Distal'];
      } else lab[i] = n[S + 'Hand'];
    } else if (pt === PARTS.foot) {
      const S = x > 0 ? 'Left' : 'Right';
      lab[i] = z > P.footL * 0.55 * U ? n[S + 'Toes'] : n[S + 'Foot'];
    }
  }
}

// Bone-axis parameter t in [0,1] (0 at the bone head) for limb garments.
export function boneT(sk, bi, x, y, z) {
  const b = sk.bones[bi];
  const ax = b.tail[0] - b.head[0], ay = b.tail[1] - b.head[1], az = b.tail[2] - b.head[2];
  return ((x - b.head[0]) * ax + (y - b.head[1]) * ay + (z - b.head[2]) * az) / (ax * ax + ay * ay + az * az);
}
