// Villager generator: seed -> appearance variables -> voxel layers -> skinned meshes per outfit.
import { Rng, hashCombine, h3, vnoise } from './rng.js';
import { hex, mix, ramp } from './color.js';
import { MAT, Grid, proportions, makeSkeleton, makeJoints, bodyPrimitives, bodyField, refineLabels } from './body.js';
import { fillBody, face, hair, beard, hands } from './head.js';
import { makeWeigher, meshGrid, downsample } from './mesh.js';
import { styleMesh } from './stylemesh.js';
import { dressOutfit, makeWardrobe } from './garments.js';

export const GENERATOR_VERSION = 2;
export const DEFAULT_VOXEL = 0.01; // metres per fine voxel (paint); the mesh is built in blocks of 2 (2 cm)

const SKIN = ['#f3d5bd', '#ecc3a3', '#e0ab88', '#d29a72', '#bf835c', '#a46a46', '#865337', '#6a3f28', '#4f2e1e'];
const SKIN_W = [6, 10, 12, 11, 9, 7, 5, 4, 3];
const HAIR = { black: '#1f1915', darkbrown: '#3b2719', brown: '#5c3b22', chestnut: '#7a4524', auburn: '#8e3b1f', red: '#b4501f', ginger: '#c8702e', blond: '#c9a35a', ashblond: '#b5a78a', flax: '#ddc98f', silver: '#cfd3d6', raven: '#20243a' };
const HAIR_W = { black: 14, darkbrown: 20, brown: 20, chestnut: 12, auburn: 7, red: 4, ginger: 4, blond: 8, ashblond: 5, flax: 3, silver: 1, raven: 1 };
const EYES = { brown: '#5a3820', hazel: '#7a5a2a', green: '#4b7a3a', blue: '#3f6fa8', grey: '#7f8b94', amber: '#b07a20', violet: '#6a4aa0' };
const EYES_W = { brown: 30, hazel: 14, green: 10, blue: 14, grey: 8, amber: 3, violet: 1 };

export function appearance(seed, opts = {}) {
  const r = new Rng(hashCombine(seed, 'appearance'));
  const bp = {};
  bp.sex = opts.sex ?? (r.chance(0.5) ? 'f' : 'm');
  const ac = opts.ageClass ?? r.wpick({ child: 17, teen: 10, adult: 57, elder: 16 });
  bp.age = opts.age ?? (ac === 'child' ? r.int(6, 12) : ac === 'teen' ? r.int(13, 17) : ac === 'adult' ? r.int(18, 59) : r.int(60, 82));
  bp.ageClass = bp.age < 13 ? 'child' : bp.age < 18 ? 'teen' : bp.age < 60 ? 'adult' : 'elder';
  const f = bp.sex === 'f';
  let H;
  if (bp.ageClass === 'child') H = 1.12 + (bp.age - 6) * 0.062 + r.gauss() * 0.03;
  else if (bp.ageClass === 'teen') H = (f ? 1.52 : 1.56) + (bp.age - 13) * (f ? 0.02 : 0.035) + r.gauss() * 0.04;
  else H = (f ? 1.62 : 1.73) + r.gauss() * (f ? 0.055 : 0.065) - (bp.ageClass === 'elder' ? 0.03 : 0);
  bp.height = Math.round(H * 100) / 100;
  let build = r.gauss() * 0.42 + (bp.ageClass === 'elder' ? 0.12 : 0) + (bp.ageClass === 'child' ? -0.1 : 0);
  bp.build = Math.max(-1, Math.min(1, Math.round(build * 100) / 100));
  bp.muscle = Math.round(Math.max(0, Math.min(1, 0.35 + r.gauss() * 0.25 + (f ? -0.1 : 0.05))) * 100) / 100;
  bp.bust = f ? 0.85 + r.f() * 0.3 : 0;
  bp.jaw = f ? 0.9 + r.f() * 0.08 : 1.0 + r.f() * 0.1;
  bp.skinIndex = r.wpick(SKIN.map((s, i) => [i, SKIN_W[i]]));
  bp.skin = hex(SKIN[bp.skinIndex]);
  // hair
  let hc = r.wpick(HAIR_W);
  bp.hairName = hc;
  let hcol = hex(HAIR[hc]);
  if (bp.skinIndex >= 6 && (hc === 'blond' || hc === 'flax' || hc === 'ashblond') && r.chance(0.7)) { hc = 'black'; hcol = hex(HAIR.black); bp.hairName = hc; }
  if (bp.age > 45) hcol = mix(hcol, hex('#b9b6b0'), Math.min(0.95, (bp.age - 45) / 32 + r.f() * 0.2));
  bp.hairColor = hcol;
  bp.beardTint = r.chance(0.3) ? hex('#8a4a22') : hcol;
  bp.eyesName = r.wpick(EYES_W); bp.eyes = hex(EYES[bp.eyesName]);
  bp.tieColor = r.pick([hex('#7a2e2a'), hex('#2f4f7a'), hex('#5a6a2a'), hex('#c49a3a'), hex('#4a3a2a')]);
  const child = bp.ageClass === 'child';
  if (f) bp.hairStyle = r.wpick(child ? { braid: 4, ponytail: 3, long: 3, short: 1, bun: 1 } : bp.ageClass === 'elder' ? { bun: 6, braid: 2, long: 1, short: 2 } : { long: 6, braid: 5, bun: 5, ponytail: 3, short: 1, curly: 1 });
  else bp.hairStyle = r.wpick(child ? { short: 4, bowl: 3, crop: 2, curly: 1, wild: 1 } : bp.ageClass === 'elder' ? { short: 4, bald: 3, crop: 2, wild: 1, tonsure: 0.5 } : { short: 6, crop: 4, bowl: 2, long: 2, curly: 2, wild: 1, topknot: 1, ponytail: 1 });
  bp.hairLen = 0.06 + r.f() * 0.14;
  bp.part = (r.f() - 0.5) * 0.6;
  bp.receding = !f && bp.age > 35 && r.chance(0.35);
  bp.sideburns = !f && !child && r.chance(0.5);
  bp.beard = (!f && (bp.ageClass === 'adult' || bp.ageClass === 'elder')) ? r.wpick({ none: 7, short: 4, full: 4, long: bp.ageClass === 'elder' ? 3 : 1, goatee: 2, mustache: 2 }) : 'none';
  bp.stubble = !f && bp.beard === 'none' && bp.ageClass !== 'child' && bp.ageClass !== 'teen' && r.chance(0.6);
  bp.stubbleColor = mix(hcol, hex('#5a6470'), 0.4);
  // face
  bp.noseW = child ? 0 : r.wpick({ 0: 2, 1: 6, 2: f ? 0 : 2 }) | 0;
  bp.noseL = child ? 3 : r.int(4, f ? 5 : 6);
  bp.noseD = child ? 1 : r.wpick({ 2: 6, 3: f ? 1 : 4 }) | 0;
  bp.noseRed = !child && r.chance(0.15);
  bp.mouthW = child ? 1 : r.int(2, 3);
  bp.smile = r.wpick({ 0: 5, 1: 3, '-1': 1 }) | 0;
  bp.lipFull = f && r.chance(0.4);
  bp.browTilt = Math.round((r.f() - 0.5) * 3 * 10) / 10;
  bp.browThick = !f ? r.f() * 1.0 + 0.1 : r.f() * 0.6;
  bp.lashes = f;
  bp.freckles = r.chance(bp.hairName === 'red' || bp.hairName === 'ginger' ? 0.6 : 0.12);
  bp.ruddy = r.f() * 0.6;
  bp.earBig = r.chance(0.12);
  bp.scar = !child && r.chance(0.06) ? (r.chance(0.5) ? 1 : -1) : 0;
  return bp;
}

// Build everything shared by every outfit of one villager.
export function buildBase(bp, seed, voxel = DEFAULT_VOXEL) {
  const U = bp.height / voxel;               // voxels per height unit
  const P = proportions(bp);
  const sk = makeSkeleton(P, U);
  const joints = makeJoints(sk, P, U);
  const prims = bodyPrimitives(P, bp, U, sk);
  const nx = Math.ceil(U * 0.74) | 1, ny = Math.ceil(U * 1.32), nz = Math.ceil(U * 0.62);
  const grid = new Grid(nx, ny, nz, nx / 2, nz / 2);
  const field = bodyField(grid, prims, 9, 1.6);
  refineLabels(grid, field, sk, P, U);
  fillBody(grid, field, bp, seed);
  hands(grid, sk);
  const fi = face(grid, sk, P, bp, U, new Rng(hashCombine(seed, 'face')), 2);
  hair(grid, field, sk, P, bp, U, hashCombine(seed, 'hair'));
  beard(grid, field, sk, P, bp, U, hashCombine(seed, 'beard'));
  // style mesh lattice: the brow line and the face plane are block boundaries
  const align = { y: fi.yE + 2, z: fi.zFace + 1 };
  return { bp, P, U, sk, joints, prims, grid, field, voxel, seed, align };
}

// Limb group per bone: 0 trunk (hips to head, shoulders), 1/2 arms, 3/4 legs.
export function limbGroups(sk) {
  return Uint8Array.from(sk.bones, b => {
    const m = /^(Left|Right)(UpperArm|LowerArm|Hand|Thumb|Index|Middle|Ring|Little|UpperLeg|LowerLeg|Foot|Toes)/.exec(b.name);
    if (!m) return 0;
    const leg = /Leg|Foot|Toes/.test(m[2]);
    return (leg ? 3 : 1) + (m[1] === 'Right' ? 1 : 0);
  });
}

// Mesh of one outfit. Default: voxel STYLE (blocks of 2 fine voxels with bevels set by the
// material, painted one fine voxel per texel). opts.strict = true gives the plain voxel mesh.
export function meshOutfit(base, grid, lod = 0, opts = {}) {
  const w = makeWeigher(base.sk, base.joints, base.P, base.U);
  const group = base.groups ??= limbGroups(base.sk);
  if (opts.strict) {
    if (!lod) return meshGrid(grid, w, { voxelSize: base.voxel, group });
    const f = 1 << lod;
    return meshGrid(downsample(grid, f, Grid), w, { voxelSize: base.voxel, scale: f, group });
  }
  const f = 2 << lod; // LOD0 blocks of 2 fine voxels, then 4, 8, 16
  return styleMesh(grid, w, { f, texel: lod < 2 ? f / 2 : f, bevel: opts.bevel, voxelSize: base.voxel, group, align: base.align });
}

export function generateVillager(seed, catalog, opts = {}) {
  const bp = appearance(seed, opts);
  const base = buildBase(bp, seed, opts.voxel);
  const wardrobe = catalog ? makeWardrobe(base, catalog, opts) : null;
  return { seed, bp, base, wardrobe };
}

export function composeOutfit(v, occasion, catalog) {
  const grid = v.base.grid.clone();
  if (v.wardrobe) dressOutfit(v.base, grid, v.wardrobe, occasion, catalog);
  painterly(grid, v.seed);
  return grid;
}

// Hand-painted look of the reference image: every voxel's colour wanders a little in value and
// warmth, in soft patches of a few voxels plus a fine grain. Eyes, metal and gems stay clean.
export function painterly(grid, seed) {
  const { nx, ny } = grid, warm = 0xd8a070, cool = 0x7088b0;
  for (let i = 0; i < grid.col.length; i++) {
    const c0 = grid.col[i]; if (!c0) continue;
    const m = grid.mat[i]; if (m === MAT.eye || m === MAT.metal || m === MAT.gem) continue;
    const x = i % nx, y = Math.floor(i / nx) % ny, z = Math.floor(i / (nx * ny));
    const skin = m === MAT.skin;
    const v = (vnoise(x, y, z, 3, seed + 11) - 0.5) * (skin ? 0.07 : 0.16) + (h3(x, y, z, seed + 12) - 0.5) * (skin ? 0.03 : 0.07);
    const t = vnoise(x, y, z, 5, seed + 13) - 0.5;
    let c = ramp(c0 & 0xffffff, 1 + v);
    c = mix(c, t > 0 ? warm : cool, Math.abs(t) * (skin ? 0.08 : 0.16));
    grid.col[i] = c | 0x1000000;
  }
  return grid;
}
