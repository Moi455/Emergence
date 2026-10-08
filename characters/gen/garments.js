// Garments: each garment is a data record (type, material, colors, pattern, params, wear, seed)
// carried by the NPC. Its voxels are rebuilt for the body that wears it, so any garment
// fits any villager. Builders write into a copy of the base grid in layer order.
import { Rng, hashCombine, h3, vnoise } from './rng.js';
import { hex, mix, ramp, mul, rgb, desat } from './color.js';
import { MAT, MODE_NORMAL, MODE_SKIRT, MODE_CLOAK, MODE_RIGID, clamp01, boneT } from './body.js';
import { LAYER } from './head.js';

// ------------------------------------------------------------------ helpers
function classes(sk) {
  return sk.bones.map(b => {
    const n = b.name;
    if (/^(Hips|Spine|Chest|UpperChest)$|Shoulder/.test(n)) return 'torso';
    if (n === 'Neck') return 'neck';
    if (n === 'Head') return 'head';
    if (/UpperArm/.test(n)) return 'uarm';
    if (/LowerArm/.test(n)) return 'larm';
    if (/Hand|Thumb|Index|Middle|Ring|Little/.test(n)) return 'hand';
    if (/UpperLeg/.test(n)) return 'uleg';
    if (/LowerLeg/.test(n)) return 'lleg';
    if (/Foot|Toes/.test(n)) return 'foot';
    return 'root';
  });
}

export function prepare(base) {
  if (base.prep) return base.prep;
  const { grid, field, sk, P, U } = base;
  const cls = classes(sk);
  const near = [];
  for (let i = 0; i < field.d.length; i++) if (field.d[i] <= 7) near.push(i);
  // cross-section of hips/legs at hip height for skirts
  const prep = { cls, near: Int32Array.from(near) };
  const NX = grid.nx, NY = grid.ny;
  prep.xyz = i => [i % NX, Math.floor(i / NX) % NY, Math.floor(i / (NX * NY))];
  const yh = Math.round(P.yHip * U);
  let mx = 0, zmin = 1e9, zmax = -1e9;
  for (let zk = 0; zk < grid.nz; zk++) for (let xi = 0; xi < grid.nx; xi++) {
    const i = grid.idx(xi, yh, zk);
    if (field.d[i] <= 0 && (cls[field.lab[i]] === 'torso' || cls[field.lab[i]] === 'uleg')) {
      mx = Math.max(mx, Math.abs(grid.cx(xi))); const z = grid.cz(zk); zmin = Math.min(zmin, z); zmax = Math.max(zmax, z);
    }
  }
  prep.hipRx = mx; prep.hipRz = (zmax - zmin) / 2; prep.hipCz = (zmax + zmin) / 2;
  // body cross-section per row (torso and legs), used to fit skirts from the waist down
  prep.row = [];
  for (let yj = 0; yj < grid.ny; yj++) {
    let rx = 0, z0 = 1e9, z1 = -1e9;
    for (let zk = 0; zk < grid.nz; zk++) for (let xi = 0; xi < grid.nx; xi++) {
      const i = grid.idx(xi, yj, zk);
      if (field.d[i] > 0) continue;
      const c = cls[field.lab[i]];
      if (c !== 'torso' && c !== 'uleg' && c !== 'lleg') continue;
      rx = Math.max(rx, Math.abs(grid.cx(xi)) + 0.5); const z = grid.cz(zk); z0 = Math.min(z0, z - 0.5); z1 = Math.max(z1, z + 0.5);
    }
    prep.row.push(rx > 0 ? { rx, rz: (z1 - z0) / 2, cz: (z1 + z0) / 2 } : null);
  }
  // per-row free radius before touching the hanging arms and hands
  prep.free = new Float32Array(grid.ny).fill(1e9);
  for (let i = 0; i < field.d.length; i++) {
    if (field.d[i] > 0) continue;
    const c = cls[field.lab[i]];
    if (c !== 'uarm' && c !== 'larm' && c !== 'hand') continue;
    const xi = i % NX, yj = Math.floor(i / NX) % NY;
    const ax = Math.abs(grid.cx(xi)) - 0.5;
    if (ax < prep.free[yj]) prep.free[yj] = ax;
  }
  for (let y = 0; y < grid.ny; y++) if (prep.free[y] < 1e8) prep.free[y] -= 1.2;
  base.prep = prep;
  return prep;
}

// ------------------------------------------------------------------ fabric shading
function matTex(material, x, y, z, seed) {
  const h = h3(x, y, z, seed) - 0.5;
  switch (material) {
    case 'linen': return 1 + (((x + y + z) & 1) ? 0.012 : -0.012) + h * 0.03 + (vnoise(x, y, z, 5, seed) - 0.5) * 0.1;
    case 'wool': return 1 + h * 0.07 + (vnoise(x, y, z, 4, seed) - 0.5) * 0.14;
    case 'leather': { const s = h3(x, y, z, seed + 9); return 1 + (vnoise(x, y, z, 4, seed) - 0.5) * 0.24 + h * 0.06 + (s < 0.03 ? 0.18 : 0); }
    case 'fur': return 1 + (h3(x, y >> 1, z, seed) - 0.5) * 0.36;
    case 'felt': return 1 + h * 0.06;
    case 'oilskin': return 1 + (vnoise(x, y * 3, z, 6, seed) - 0.5) * 0.25 + h * 0.04;
    case 'knit': return 1 + (((x + z) & 1) ? 0.07 : -0.07) + h * 0.05;
    case 'straw': return 1 + ((((x + y) >> 1) + z) & 1 ? 0.1 : -0.08) + h * 0.06;
    case 'velvet': return 1 + h * 0.04 + (vnoise(x, y, z, 5, seed) - 0.5) * 0.08;
    case 'metal': return 1 + h * 0.1;
    default: return 1 + h * 0.06;
  }
}

function patternMix(g, x, y, z, cx, cz) {
  const p = g.pattern;
  if (!p || p.kind === 'plain') return null;
  const per = p.period || 3;
  const fx = Math.floor((x - cx) / per), fy = Math.floor(y / per), fz = Math.floor((z - cz) / per);
  switch (p.kind) {
    case 'stripes_h': return (fy & 1) ? [p.c2, 1] : null;
    case 'stripes_v': { const s = Math.abs(z - cz) > Math.abs(x - cx) ? fx : fz; return (s & 1) ? [p.c2, 1] : null; }
    case 'check': return ((fx + fy + fz) & 1) ? [p.c2, 0.85] : null;
    case 'plaid': {
      const a = ((fy % 3) + 3) % 3 === 0, b = (((fx + fz) % 3) + 3) % 3 === 0;
      if (a && b) return [mul(p.c2, 0.75), 1];
      if (a || b) return [p.c2, 0.6];
      return ((y + x + z) % 7 === 0) ? [p.c3 ?? p.c2, 0.5] : null;
    }
    case 'miparti': return (x < cx) ? [p.c2, 1] : null;
    case 'quilt': { const q = per + 1; const u = Math.abs(z - cz) > Math.abs(x - cx) ? x : z; return ((((u + y) % q) + q) % q === 0 || (((u - y) % q) + q) % q === 0) ? [mul(g.colors.main, 0.78), 1] : null; }
    case 'patchwork': { const k = h3(Math.floor(x / 5), Math.floor(y / 5), Math.floor(z / 5), g.seed); return k < 0.33 ? [p.c2, 1] : k < 0.5 ? [p.c3 ?? p.c2, 1] : null; }
  }
  return null;
}

function shade(g, zone, x, y, z, ctx) {
  const C = g.colors;
  let c;
  let material = g.material;
  switch (zone) {
    case 'trim': c = C.trim ?? mul(C.main, 0.8); material = g.trimMaterial ?? material; break;
    case 'accent': c = C.accent ?? C.trim ?? C.main; break;
    case 'cord': c = C.cord ?? hex('#3a2a1e'); material = 'leather'; break;
    case 'metal': c = C.metal ?? hex('#b8a070'); material = 'metal'; break;
    case 'sole': c = C.sole ?? hex('#3b2a1e'); material = 'leather'; break;
    case 'lining': c = C.lining ?? mul(C.main, 0.7); break;
    case 'fur': c = C.fur ?? hex('#d8cbb0'); material = 'fur'; break;
    default: c = C.main;
  }
  if (zone === 'main') {
    const pm = patternMix(g, x, y, z, ctx.cx ?? 0, ctx.cz ?? 0);
    if (pm) c = mix(c, pm[0], pm[1]);
  }
  if (zone === 'trim' && g.embroider) {
    // repeated motif in the band: small diamonds / zigzag
    const m = ((x + z) % 4 + 4) % 4, row = ctx.bandRow ?? 0;
    if ((g.embroider === 'zigzag' && m === row % 4) || (g.embroider === 'diamond' && (m === 1 + (row & 1) || m === 3 - (row & 1))) || (g.embroider === 'dots' && m === 2 && (row & 1))) c = C.accent ?? hex('#d8b04a');
  }
  let k = matTex(material, x, y, z, g.seed);
  if (ctx.fold) k *= ctx.fold;
  c = ramp(c, k);
  // wear: dust/mud toward the ground and the hem
  if (g.wear > 0 && ctx.U) {
    const yy = y / ctx.U;
    const dirt = clamp01((0.18 - yy) / 0.18) * g.wear * 0.7 + (h3(x, y, z, g.seed + 3) < g.wear * 0.05 ? 0.14 : 0);
    if (dirt > 0) c = mix(c, hex('#5b4a38'), dirt);
    if (g.wear > 0.3) c = desat(c, (g.wear - 0.3) * 0.3);
  }
  if (material === 'metal') {
    const hl = clamp01((h3(x, y, z, 7) - 0.6) * 2);
    c = mix(c, hex('#fff2c8'), hl * 0.4);
  }
  return c;
}

function matId(material) {
  return { leather: MAT.leather, metal: MAT.metal, fur: MAT.fur, straw: MAT.straw, wood: MAT.wood }[material] ?? MAT.cloth;
}

// ------------------------------------------------------------------ writers
function writer(base, grid, g) {
  const layer = LAYER[g.layer] ?? 5;
  return (xi, yj, zk, zone, bone, mode, ctx = {}) => {
    if (!grid.inb(xi, yj, zk)) return;
    const i = grid.idx(xi, yj, zk);
    if (g.under && grid.col[i] && grid.layer[i] > layer) return; // never cover outer layers
    const c = shade(g, zone, xi, yj, zk, { ...ctx, U: base.U, cx: grid.ox, cz: grid.oz });
    const mat = zone === 'metal' ? MAT.metal : zone === 'sole' || zone === 'cord' ? MAT.leather : zone === 'fur' ? MAT.fur : matId(g.material);
    grid.col[i] = (c & 0xffffff) | 0x1000000; grid.bone[i] = bone; grid.mat[i] = mat; grid.layer[i] = layer; grid.mode[i] = mode;
  };
}

// ------------------------------------------------------------------ builders
const B = {};

// Tops: shirts, tunics, dresses, doublets, vests, coats, robes, smocks, gambesons.
B.top = (base, grid, g) => {
  const { field, sk, P, U } = base, prep = prepare(base), { cls, near } = prep;
  const pr = g.params;
  const put = writer(base, grid, g);
  const off = pr.off ?? 1;
  const yS = P.yS * U, yHip = P.yHip * U;
  const hemY = pr.hem * U;
  const nw = (pr.neckW ?? 0.05) * U, nd = (pr.neckD ?? 0.04) * U;
  const skirtTop = yHip + 0.07 * U;
  const n = sk.byName;
  const bandH = pr.hemBand ? 2 : 0;
  const openW = (pr.open ?? 0) * U;
  for (let q = 0; q < near.length; q++) {
    const i = near[q];
    const d = field.d[i];
    const lab = field.lab[i], c = cls[lab];
    const [xi, yj, zk] = prep.xyz(i);
    const x = grid.cx(xi), y = yj + 0.5, z = grid.cz(zk);
    let o = off, zone = 'main';
    if (c === 'torso') {
      if (y < hemY && hemY > skirtTop) continue;
      if (y < skirtTop && hemY <= skirtTop) continue; // below the hips: skirt part handles it
      // neckline
      if (z > 0) {
        const ax = Math.abs(x);
        if (ax < nw) {
          let depth = nd;
          if (pr.neck === 'v') depth = nd * (1 - ax / nw);
          else if (pr.neck === 'round') depth = nd * Math.sqrt(1 - (ax / nw) * (ax / nw));
          else if (pr.neck === 'high') depth = -1;
          if (y > yS - depth) continue;
          if (y > yS - depth - 1.6 && pr.collarTrim) zone = 'trim';
        }
      } else if (Math.abs(x) < nw * 0.8 && y > yS - nd * 0.15 && pr.neck !== 'high') continue;
      if (openW > 0 && z > 0 && Math.abs(x) < openW && y < yS - (pr.openFrom ?? 0) * U) continue;
      if (openW > 0 && z > 0 && Math.abs(x) < openW + 1.5 && pr.frontTrim) zone = 'trim';
      if (pr.hemBand && y < hemY + bandH && hemY > skirtTop) zone = 'trim';
      if (pr.lacing && z > 0 && y < yS - nd * 0.6 && y > (P.yHip + 0.14) * U && Math.abs(x) <= 1.6 && d > off - 1.2) {
        const r = Math.floor(y) % 3; if ((r === 0 && Math.abs(x) <= 1.2) || (r !== 0 && Math.abs(Math.abs(x) - 1) < 0.6)) zone = 'cord';
      }
    } else if (c === 'neck') {
      if (pr.neck !== 'high' && pr.collar !== 'stand') continue;
      if (y > (P.yNb + 0.03) * U) continue;
      zone = 'trim'; o = off + 0.6;
    } else if (c === 'uarm') {
      if (pr.sleeve == null || pr.sleeve < 0) continue;
      const t = boneT(sk, lab, x, y, z);
      if (pr.sleeve === 0 && t > 0.45) continue;
      if (pr.sleeve === 0 && t > 0.3 && pr.cuff) { zone = 'trim'; o = off + 0.6; }
      if (pr.puff) o += 0.8 * clamp01(1 - Math.abs(t - 0.45) * 2.2);
    } else if (c === 'larm') {
      if (!(pr.sleeve > 0)) continue;
      const t = boneT(sk, lab, x, y, z);
      if (t > pr.sleeve) continue;
      if (pr.wideSleeve) o += clamp01((t - 0.2) / 0.8) * pr.wideSleeve * U;
      if (pr.cuff && t > pr.sleeve - 0.12) { zone = 'trim'; o += 0.6; }
    } else if (c === 'uleg' && hemY < skirtTop && pr.legFit) {
      // fitted tunic over legs (rare); the skirt part normally covers legs
      continue;
    } else continue;
    // sleeve wrinkles: horizontal bands
    let fold = 1;
    if (c === 'uarm' || c === 'larm') fold = 0.9 + vnoise(0, yj, 0, 3, g.seed) * 0.16;
    if (d <= o) {
      put(xi, yj, zk, zone, lab, MODE_NORMAL, { fold });
    }
  }
  // collar fold / fur collar on shoulders
  if (pr.collar === 'fold' || pr.collar === 'fur') {
    for (let q = 0; q < near.length; q++) {
      const i = near[q], lab = field.lab[i];
      if (cls[lab] !== 'torso' && cls[lab] !== 'neck') continue;
      const [xi, yj, zk] = prep.xyz(i);
      const x = grid.cx(xi), y = yj + 0.5, z = grid.cz(zk);
      if (y < yS - 0.035 * U || y > (P.yNb + 0.02) * U) continue;
      if (z > 0 && Math.abs(x) < nw * 0.9 && openW > 0) continue;
      if (field.d[i] <= off + (pr.collar === 'fur' ? 2.2 : 1.3) && field.d[i] > off - 1) {
        const fz = pr.collar === 'fur' ? 'fur' : 'trim';
        put(xi, yj, zk, fz, lab, MODE_NORMAL, {});
      }
    }
  }
  // skirt part (below the hips)
  if (hemY < skirtTop) skirt(base, grid, g, put, hemY, skirtTop, off, pr);
  // buttons
  if (pr.buttons) {
    for (let y = Math.floor(yS - nd - 2); y > Math.max(hemY, skirtTop - 0.08 * U) + 2; y -= 4) {
      const xi = Math.round(grid.ox + (openW > 0 ? openW + 1 : 0) - 0.5);
      for (let zk = grid.nz - 1; zk > 0; zk--) {
        const j = grid.idx(xi, y, zk);
        if (grid.col[j] && grid.layer[j] === (LAYER[g.layer] ?? 5)) { put(xi, y, zk + 1, 'metal', grid.bone[j], MODE_NORMAL); break; }
        if (grid.col[j]) break;
      }
    }
  }
};

function skirt(base, grid, g, put, hemY, topY, off, pr) {
  const { P, U, sk } = base, prep = prepare(base);
  const flare = pr.flare ?? 0.25;
  const rz0 = prep.hipRz + off, cz = prep.hipCz;
  const n = sk.byName;
  const y0 = Math.max(0, Math.floor(hemY)), y1 = Math.ceil(topY + 2);
  const bandH = pr.hemBand ? 2 : 0;
  const seed = g.seed;
  let rxPrev = 0, rzPrev = 0;
  const myLayer = LAYER[g.layer] ?? 5;
  for (let yj = y1; yj >= y0; yj--) {
    const y = yj + 0.5;
    const depth = Math.max(0, topY - y);
    const row = prep.row[yj];
    // grow by `flare` per row from the previous (possibly arm-limited) radius, never inside the body
    let rx = Math.max(rxPrev + flare, row ? row.rx + off : 0);
    let rz = Math.max(rzPrev + flare * 0.85, row ? row.rz + off : 0);
    rx = Math.min(rx, prep.free[yj] ?? 1e9);
    // cover whatever lower garment layers already occupy this row (except arms)
    const fr = prep.free[yj] ?? 1e9;
    for (let zk = 0; zk < grid.nz; zk++) for (let xi = 0; xi < grid.nx; xi++) {
      const i = grid.idx(xi, yj, zk);
      if (!grid.col[i] || grid.layer[i] === 0 || grid.layer[i] >= myLayer) continue;
      const c = prep.cls[grid.bone[i]]; if (c === 'hand' || c === 'larm' || c === 'uarm' || c === 'foot') continue;
      const x = Math.abs(grid.cx(xi)) + 0.6, z = Math.abs(grid.cz(zk) - cz) + 0.6;
      if (x > fr - 1) continue;
      const e = (x / rx) * (x / rx) + (z / rz) * (z / rz);
      if (e <= 1) continue;
      const k = Math.sqrt(e);
      if (rx * k <= fr) { rx *= k; rz *= k; }
      else { rx = fr; const fx = (x / rx) * (x / rx); rz = Math.max(rz, Math.min(z / Math.sqrt(1 - fx), rz * 1.3)); }
    }
    rz = Math.min(rz, rz0 + depth * flare * 1.6 + 8);
    rxPrev = rx; rzPrev = rz;
    const xr = Math.ceil(rx + 3), zr = Math.ceil(rz + 3);
    for (let zk = Math.floor(grid.oz + cz - zr); zk <= Math.ceil(grid.oz + cz + zr); zk++) for (let xi = Math.floor(grid.ox - xr); xi <= Math.ceil(grid.ox + xr); xi++) {
      if (!grid.inb(xi, yj, zk)) continue;
      const x = grid.cx(xi), z = grid.cz(zk) - cz;
      const nx = x / rx, nz = z / rz;
      // folds: radius grows outward with pseudo-angle noise, more toward the hem
      const pa = z >= 0 ? clamp01((nx + 1) / 2) * 2 : 2 + clamp01((1 - nx) / 2) * 2;
      const fnz = vnoise(Math.floor(pa * 36), 0, 0, 4, seed);
      const amp = clamp01(depth / (0.12 * U)) * 0.12;
      const rr = 1 + fnz * amp;
      const e = nx * nx + nz * nz;
      if (e > rr * rr) continue;
      if (Math.abs(x) > (prep.free[yj] ?? 1e9) + 0.5 && e > 0.3) continue;
      const i = grid.idx(xi, yj, zk);
      // keep hanging hands and arms intact
      if (grid.col[i]) { const c = prep.cls[grid.bone[i]]; if (c === 'hand' || c === 'larm' || c === 'uarm') continue; }
      if (pr.open && z > 0 && Math.abs(x) < pr.open * U && e > 0.4) continue; // open coat front
      let zone = 'main';
      if (y < hemY + bandH) zone = 'trim';
      if (pr.open && pr.frontTrim && z > 0 && Math.abs(x) < pr.open * U + 1.5) zone = 'trim';
      const fold = 0.9 + fnz * 0.2;
      put(xi, yj, zk, zone, n.Hips, MODE_SKIRT, { fold, bandRow: Math.floor(y - hemY) });
    }
  }
  // frayed hem for worn garments
  if (g.wear > 0.55) {
    const yj = Math.floor(hemY);
    for (let zk = 0; zk < grid.nz; zk++) for (let xi = 0; xi < grid.nx; xi++) {
      const i = grid.idx(xi, yj, zk);
      if (grid.col[i] && grid.layer[i] === (LAYER[g.layer] ?? 5) && h3(xi, yj, zk, seed) < 0.35) grid.col[i] = 0;
    }
  }
}

// Trousers, braies, hose.
B.legs = (base, grid, g) => {
  const { field, sk, P, U } = base, prep = prepare(base), { cls, near } = prep;
  const pr = g.params, put = writer(base, grid, g), off = pr.off ?? 0.8;
  const waist = (P.yHip + (pr.waist ?? 0.09)) * U;
  for (let q = 0; q < near.length; q++) {
    const i = near[q], d = field.d[i], lab = field.lab[i], c = cls[lab];
    const [xi, yj, zk] = prep.xyz(i);
    const x = grid.cx(xi), y = yj + 0.5, z = grid.cz(zk);
    let o = off, zone = 'main';
    if (c === 'torso') { if (y > waist) continue; if (y > waist - 1.5 && pr.waistBand) zone = 'trim'; }
    else if (c === 'uleg') { o += (pr.loose ?? 0) * clamp01(1 - boneT(sk, lab, x, y, z) * 0.5); }
    else if (c === 'lleg') {
      const t = boneT(sk, lab, x, y, z);
      if (t > pr.len) continue;
      if (pr.loose) o += pr.loose * 0.6;
      if (pr.cuff && t > pr.len - 0.1) { zone = 'trim'; o += 0.5; }
      if (pr.wraps && t > 0.25) { o += 0.5; zone = ((Math.floor(y) + (x > 0 ? 0 : 1)) % 3 === 0) ? 'cord' : 'trim'; }
    } else continue;
    if ((c === 'uleg' || c === 'torso') && Math.abs(x) > (prep.free[yj] ?? 1e9) - 0.5) continue;
    const fold = (c === 'uleg' || c === 'lleg') ? 0.92 + vnoise(0, yj, xi > grid.ox ? 1 : 9, 3, g.seed) * 0.13 : 1;
    if (d <= o) put(xi, yj, zk, zone, lab, MODE_NORMAL, { fold });
  }
};

// Shoes, boots, sandals, waders.
B.feet = (base, grid, g) => {
  const { field, sk, P, U } = base, prep = prepare(base), { cls, near } = prep;
  const pr = g.params, put = writer(base, grid, g), off = pr.off ?? 1.1;
  const solH = 1.5;
  for (let q = 0; q < near.length; q++) {
    const i = near[q], d = field.d[i], lab = field.lab[i], c = cls[lab];
    const [xi, yj, zk] = prep.xyz(i);
    const x = grid.cx(xi), y = yj + 0.5, z = grid.cz(zk);
    let o = off, zone = 'main';
    if (c === 'foot') {
      if (pr.sandal) { if (y > solH + 0.5 && !((Math.floor(z) % 4 === 0) || y < solH + 1.6)) continue; }
      if (y < solH) zone = 'sole';
      if (pr.pointed && z > P.footL * 0.8 * U) o += 1;
    } else if (c === 'lleg') {
      const t = boneT(sk, lab, x, y, z);
      if (t < 1 - pr.height) continue;
      if (pr.sandal) { if (t < 0.9 || Math.floor(y) % 3) continue; zone = 'cord'; }
      if (pr.cuff && t < 1 - pr.height + 0.12) { zone = 'trim'; o += 0.8; }
      if (pr.laces && z > 0 && Math.abs(x - Math.sign(x) * P.lx * U) < 1.1 && Math.floor(y) % 2 === 0) zone = 'cord';
    } else if (c === 'uleg' && pr.height > 1) {
      const t = boneT(sk, lab, x, y, z);
      if (t < 2 - pr.height) continue;
    } else continue;
    if (d <= o) put(xi, yj, zk, zone, lab, MODE_NORMAL, {});
  }
};

B.hands = (base, grid, g) => {
  const { field, sk, U } = base, prep = prepare(base), { cls, near } = prep;
  const pr = g.params, put = writer(base, grid, g), off = pr.off ?? 0.7;
  for (let q = 0; q < near.length; q++) {
    const i = near[q], d = field.d[i], lab = field.lab[i], c = cls[lab];
    const [xi, yj, zk] = prep.xyz(i);
    const x = grid.cx(xi), y = yj + 0.5, z = grid.cz(zk);
    let zone = 'main', o = off;
    if (c === 'hand') { if (pr.mitten && /Index|Middle|Ring|Little/.test(sk.bones[lab].name)) o += 0.4; }
    else if (c === 'larm') { const t = boneT(sk, lab, x, y, z); if (t < 0.78) continue; zone = 'trim'; o += 0.8; }
    else continue;
    if (d <= o) put(xi, yj, zk, zone, lab, MODE_NORMAL, {});
  }
};

B.belt = (base, grid, g) => {
  const { field, sk, P, U } = base, prep = prepare(base), { cls, near } = prep;
  const pr = g.params, put = writer(base, grid, g);
  const wy = (P.yHip + (pr.y ?? 0.1)) * U, hw = pr.width ?? 1.6;
  // belt sits on top of whatever is there: find the outer surface per column ring
  const n = sk.byName;
  for (let yj = Math.floor(wy - hw); yj <= Math.ceil(wy + hw - 1); yj++) {
    for (let zk = 0; zk < grid.nz; zk++) for (let xi = 0; xi < grid.nx; xi++) {
      const i = grid.idx(xi, yj, zk);
      if (grid.col[i]) continue;
      if (!(field.d[i] < 8)) continue;
      const c = cls[field.lab[i]];
      if (c !== 'torso' && c !== 'uleg') continue;
      // empty cell touching the clothed torso
      let touch = false;
      for (const [dx, dz] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
        const j = grid.idx(xi + dx, yj, zk + dz);
        if (grid.inb(xi + dx, yj, zk + dz) && grid.col[j]) { const cc = prep.cls[grid.bone[j]]; if (cc === 'torso' || cc === 'uleg') touch = true; }
      }
      if (!touch) continue;
      const x = grid.cx(xi), z = grid.cz(zk);
      let zone = pr.sash ? 'main' : 'main';
      if (!pr.sash && z > 0 && Math.abs(x) < 1.6) zone = 'metal';
      put(xi, yj, zk, zone, n.Hips, MODE_NORMAL, {});
    }
  }
  // buckle relief / sash knot
  const zf = (xi, yj) => { for (let zk = grid.nz - 1; zk >= 0; zk--) if (grid.col[grid.idx(xi, yj, zk)]) return zk; return -1; };
  const cxI = Math.round(grid.ox - 0.5);
  if (!pr.sash) {
    for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++) {
      const yj = Math.round(wy) + dy - 1, xi = cxI + dx; const z = zf(xi, yj);
      if (z >= 0 && !(dx === 0 && dy === 0)) put(xi, yj, z + 1, 'metal', n.Hips, MODE_NORMAL);
    }
  } else {
    // knot and hanging ends on the left hip
    const kx = Math.round(grid.ox + prep.hipRx * 0.55);
    for (let dy = -6; dy <= 1; dy++) for (let dx = 0; dx <= 1; dx++) {
      const yj = Math.round(wy) + dy - 1, xi = kx + dx + (dy < -2 && dy % 2 ? 1 : 0); const z = zf(xi, yj);
      if (z >= 0) put(xi, yj, z + 1, dy > -1 ? 'accent' : 'main', n.Hips, MODE_SKIRT);
    }
  }
  // pouch on the right hip
  if (pr.pouch) {
    const px = Math.round(grid.ox - prep.hipRx * 0.75 - 0.5);
    for (let dy = 0; dy < 5; dy++) for (let dx = -1; dx <= 2; dx++) {
      const yj = Math.round(wy) - 2 - dy, xi = px - dx;
      const z = zf(xi, yj); if (z < 0) continue;
      for (let dz = 1; dz <= 2; dz++) put(xi, yj, z + dz, dy === 0 ? 'cord' : 'trim', n.Hips, MODE_SKIRT);
    }
  }
};

// Front panel hanging from the waist (and optional bib), following the body's front.
B.apron = (base, grid, g) => {
  const { P, U, sk } = base, prep = prepare(base);
  const pr = g.params, put = writer(base, grid, g);
  const n = sk.byName;
  const top = (P.yHip + 0.1) * U, bot = pr.hem * U, bibTop = pr.bib ? (P.yS - 0.06) * U : top;
  const hw = (pr.width ?? 0.11) * U;
  for (let xi = Math.floor(grid.ox - hw); xi <= Math.ceil(grid.ox + hw); xi++) {
    let zrun = -1;
    for (let yj = Math.ceil(bibTop); yj >= Math.floor(bot); yj--) {
      const x = grid.cx(xi), y = yj + 0.5;
      const bw = y > top ? hw * 0.6 : hw;
      if (Math.abs(x) > bw) continue;
      let zf = -1;
      for (let zk = grid.nz - 1; zk >= 0; zk--) { const i = grid.idx(xi, yj, zk); if (grid.col[i]) { const c = prep.cls[grid.bone[i]]; if (c !== 'hand' && c !== 'larm' && c !== 'uarm') { zf = zk; break; } } }
      if (y <= top) zrun = Math.max(zrun, zf); else zrun = zf;
      if (zrun < 0) continue;
      const below = y < P.yHip * U;
      const zone = (y < bot + 1.5 && pr.hemBand) || Math.abs(Math.abs(x) - bw) < 0.8 && pr.edge ? 'trim' : 'main';
      put(xi, yj, zrun + 1, zone, below ? n.Hips : y > (P.yHip + 0.3 * (P.yS - P.yHip)) * U ? n.Chest : n.Spine, below ? MODE_SKIRT : MODE_NORMAL, { fold: 0.95 + vnoise(xi, 0, 0, 3, g.seed) * 0.1 });
    }
  }
  if (pr.bib) { // neck strap
    for (let q = 0; q < prep.near.length; q++) {
      const i = prep.near[q]; const [xi, yj, zk] = prep.xyz(i);
      const x = grid.cx(xi), y = yj + 0.5;
      if (y < (P.yS - 0.06) * U || Math.abs(Math.abs(x) - 0.045 * U) > 1) continue;
      if (base.field.d[i] > 2.6 || base.field.d[i] < 1.2) continue;
      if (prep.cls[base.field.lab[i]] !== 'torso' && prep.cls[base.field.lab[i]] !== 'neck') continue;
      put(xi, yj, zk, 'trim', base.field.lab[i], MODE_NORMAL);
    }
  }
};

// Cape hanging from the shoulders, shoulder mantle, clasp, optional hood.
B.cloak = (base, grid, g) => {
  const { field, sk, P, U } = base, prep = prepare(base), { cls, near } = prep;
  const pr = g.params, put = writer(base, grid, g);
  const n = sk.byName;
  const yS = P.yS * U, hem = pr.hem * U;
  // mantle over shoulders and upper back
  for (let q = 0; q < near.length; q++) {
    const i = near[q], lab = field.lab[i], c = cls[lab];
    if (c !== 'torso' && c !== 'uarm' && c !== 'neck') continue;
    const [xi, yj, zk] = prep.xyz(i);
    const x = grid.cx(xi), y = yj + 0.5, z = grid.cz(zk);
    const ylim = yS - (pr.mantle ?? 0.06) * U - (z < 0 ? 0.02 * U : 0);
    if (y < ylim || y > (P.yNb + 0.012) * U) continue;
    if (c === 'neck' && z > 0) continue;
    if (grid.col[i] && grid.layer[i] > LAYER.cloak) continue;
    if (field.d[i] <= (pr.off ?? 2.4)) put(xi, yj, zk, y < ylim + 1.5 && pr.edgeTrim ? 'trim' : 'main', c === 'uarm' ? n[x > 0 ? 'LeftShoulder' : 'RightShoulder'] : lab, MODE_NORMAL);
  }
  // back panel: per column follows the back, never moving forward as it goes down
  const hw0 = (P.ax + P.ru) * U + 1.5;
  for (let xi = Math.floor(grid.ox - hw0 - 3); xi <= Math.ceil(grid.ox + hw0 + 3); xi++) {
    let zrun = 1e9;
    const x = grid.cx(xi);
    for (let yj = Math.ceil(yS); yj >= Math.floor(hem); yj--) {
      const y = yj + 0.5;
      const hw = hw0 + (yS - y) * (pr.flare ?? 0.12);
      if (Math.abs(x) > hw) continue;
      let zb = 1e9;
      for (let zk = 0; zk < grid.nz; zk++) if (grid.col[grid.idx(xi, yj, zk)]) { zb = zk; break; }
      zrun = Math.min(zrun, zb === 1e9 ? zrun : zb);
      if (zrun === 1e9) continue;
      const fz = vnoise(xi, 0, 0, 3, g.seed);
      const zz = zrun - 1 - Math.round(fz * 1.2 * clamp01((yS - y) / (0.15 * U)));
      const thick = 2;
      for (let k = 0; k < thick; k++) {
        const zone = (y < hem + 2 && pr.edgeTrim) || (Math.abs(x) > hw - 1.5 && pr.edgeTrim) ? 'trim' : k === 0 ? 'main' : 'main';
        put(xi, yj, zz - k, zone, n.UpperChest, MODE_CLOAK, { fold: 0.86 + fz * 0.24 });
      }
    }
  }
  // clasp
  const cy = Math.round(yS - 0.01 * U);
  for (const s of [-1, 1]) {
    const xi = Math.round(grid.ox + s * 0.05 * U - 0.5);
    let zf = -1; for (let zk = grid.nz - 1; zk >= 0; zk--) if (grid.col[grid.idx(xi, cy, zk)]) { zf = zk; break; }
    if (zf >= 0) for (let dy = 0; dy < 2; dy++) put(xi, cy - dy, zf + 1, 'metal', n.UpperChest, MODE_NORMAL);
  }
  if (pr.hood) B.hood(base, grid, { ...g, params: { ...pr.hood, mantle: 0 } });
};

B.hood = (base, grid, g) => {
  const { field, sk, P, U } = base, prep = prepare(base), { cls, near } = prep;
  const pr = g.params, put = writer(base, grid, g);
  const n = sk.byName;
  const HU = P.headH * U, cyv = P.cy * U, rx = P.rx * U, ry = P.ry * U, rz = P.rz * U;
  const off = pr.off ?? 2.2;
  const yE = cyv - HU * 0.045;
  for (let q = 0; q < near.length; q++) {
    const i = near[q], lab = field.lab[i], c = cls[lab];
    const [xi, yj, zk] = prep.xyz(i);
    const x = grid.cx(xi), y = yj + 0.5, z = grid.cz(zk);
    const d = field.d[i];
    if (c === 'head' || c === 'neck') {
      // face opening
      const open = z > rz * 0.15 && Math.abs(x) < rx * 0.86 && y < yE + HU * 0.24 && y > cyv - ry * 1.25;
      if (open) continue;
      if (d > off + (y > cyv + ry * 0.5 ? 0.8 : 0)) continue;
      const rim = z > rz * 0.05 && Math.abs(x) < rx * 0.86 + 1.8 && y < yE + HU * 0.24 + 1.8 && y > cyv - ry * 1.3;
      put(xi, yj, zk, rim && pr.rimTrim ? 'trim' : 'main', c === 'neck' ? n.Neck : n.Head, MODE_NORMAL);
    } else if (c === 'torso' && (pr.mantle ?? 0.07) > 0) {
      if (y < P.yS * U - (pr.mantle ?? 0.07) * U || d > off + 0.4) continue;
      put(xi, yj, zk, y < P.yS * U - (pr.mantle ?? 0.07) * U + 1.5 && pr.rimTrim ? 'trim' : 'main', lab, MODE_NORMAL);
    }
  }
  // pointed tail (liripipe)
  if (pr.tail) {
    const a = [0, cyv + ry * 0.6, -rz * 0.9], len = pr.tail * U;
    for (let k = 0; k < len; k++) {
      const t = k / len;
      const y = a[1] - t * len * 0.75, z = a[2] - 2 - t * len * 0.45;
      const r = 2.2 * (1 - t) + 0.6;
      for (let dz = -3; dz <= 3; dz++) for (let dy = -3; dy <= 3; dy++) for (let dx = -3; dx <= 3; dx++) {
        if (dx * dx + dy * dy + dz * dz > r * r) continue;
        put(Math.round(grid.ox + dx - 0.5), Math.round(y + dy), Math.round(grid.oz + z + dz - 0.5), 'main', n.Head, MODE_RIGID);
      }
    }
  }
};

// Hats are rigid on the Head bone.
B.hat = (base, grid, g) => {
  const { field, sk, P, U } = base, prep = prepare(base), { cls, near } = prep;
  const pr = g.params, put = writer(base, grid, g);
  const n = sk.byName, head = n.Head;
  const HU = P.headH * U, cyv = P.cy * U, rx = P.rx * U, ry = P.ry * U, rz = P.rz * U;
  const kind = pr.kind;
  const yE = cyv - HU * 0.045;
  const disk = (yj, r0, r1, zone, ctx = {}) => {
    for (let zk = 0; zk < grid.nz; zk++) for (let xi = 0; xi < grid.nx; xi++) {
      const x = grid.cx(xi), z = grid.cz(zk) + rz * 0.05;
      const rr = x * x / (1.0) + z * z * (rx * rx) / (rz * rz) ;
      if (rr <= r1 * r1 && rr >= r0 * r0) put(xi, yj, zk, typeof zone === 'function' ? zone(Math.sqrt(rr)) : zone, head, MODE_RIGID, ctx);
    }
  };
  const shellHead = (off, ymin, zoneF) => {
    for (let q = 0; q < near.length; q++) {
      const i = near[q]; if (cls[field.lab[i]] !== 'head') continue;
      const [xi, yj, zk] = prep.xyz(i);
      const y = yj + 0.5;
      if (y < ymin || field.d[i] > off) continue;
      put(xi, yj, zk, zoneF(xi, yj, zk), head, MODE_RIGID);
    }
  };
  // hair taller than the hat crown gets flattened under it
  const flatten = (ymin, r) => {
    for (let zk = 0; zk < grid.nz; zk++) for (let yj = Math.floor(ymin); yj < grid.ny; yj++) for (let xi = 0; xi < grid.nx; xi++) {
      const i = grid.idx(xi, yj, zk);
      if (grid.col[i] && grid.mat[i] === MAT.hair && grid.layer[i] === LAYER.hair) grid.col[i] = 0;
    }
  };
  if (kind === 'straw' || kind === 'felt' || kind === 'pointed' || kind === 'helmet') {
    const brimY = Math.round(cyv + ry * (kind === 'helmet' ? 0.15 : 0.3));
    const crownR = rx + (kind === 'helmet' ? 1.2 : 1.6);
    const crownH = kind === 'pointed' ? 0 : (pr.crown ?? 0.11) * U;
    flatten(brimY, crownR);
    // crown
    for (let yj = brimY; yj <= brimY + crownH + (kind === 'pointed' ? 0 : ry * 0.7); yj++) {
      const rise = yj - brimY;
      const top = brimY + ry * 0.7 + crownH;
      let r = crownR;
      if (kind === 'felt' || kind === 'straw') r = crownR - Math.max(0, rise - (top - brimY) + 3) * 0.9;
      if (kind === 'helmet') r = crownR * Math.sqrt(clamp01(1 - (rise / (ry * 0.95 + 2)) * (rise / (ry * 0.95 + 2))));
      if (r < 0.6) break;
      const inner = yj >= top - 1 || kind === 'helmet' && rise > ry * 0.8 ? 0 : r - 1.6;
      disk(yj, inner, r, () => (pr.band && rise <= 2 && rise >= 1) ? 'trim' : 'main');
    }
    // pointed cone
    if (kind === 'pointed') {
      const h = (pr.tall ?? 0.26) * U;
      for (let k = 0; k <= h; k++) {
        const t = k / h;
        const r = crownR * (1 - t) + 0.5;
        const bend = t * t * (pr.bend ?? 0.08) * U;
        const yj = brimY + k;
        for (let zk = 0; zk < grid.nz; zk++) for (let xi = 0; xi < grid.nx; xi++) {
          const x = grid.cx(xi), z = grid.cz(zk) + rz * 0.05 + bend;
          const rr = Math.sqrt(x * x + z * z * (rx * rx) / (rz * rz));
          if (rr <= r && (rr >= r - 1.6 || k > h - 4 || k === 0 || t > 0.35)) put(xi, yj, zk, (pr.band && k >= 1 && k <= 2) ? 'trim' : 'main', head, MODE_RIGID);
        }
      }
    }
    // brim
    const brimR = (pr.brim ?? 0.0) * U + crownR;
    if (brimR > crownR + 0.5) {
      for (let zk = 0; zk < grid.nz; zk++) for (let xi = 0; xi < grid.nx; xi++) {
        const x = grid.cx(xi), z = grid.cz(zk) + rz * 0.05;
        const rr = Math.sqrt(x * x + z * z * (rx * rx) / (rz * rz) * 0.9);
        if (rr > brimR || rr < crownR - 1.6) continue;
        const droop = kind === 'straw' ? Math.floor(clamp01((rr - crownR) / (brimR - crownR)) * 1.6 + 0.2) : 0;
        const up = kind === 'felt' && pr.upturn && z < 0 ? Math.floor(clamp01((rr - crownR) / (brimR - crownR)) * 2) : 0;
        put(xi, brimY - droop + up, zk, rr > brimR - 1.2 && pr.edge ? 'trim' : 'main', head, MODE_RIGID);
        if (kind === 'straw' && h3(xi, 0, zk, g.seed) < g.wear * 0.25 && rr > brimR - 1.5) grid.clear(xi, brimY - droop, zk);
      }
    }
    // feather
    if (pr.feather) {
      const fx = Math.round(grid.ox + crownR - 0.5), fz = Math.round(grid.oz - 1.5);
      for (let k = 0; k < 9; k++) put(fx + (k > 5 ? 1 : 0), brimY + 1 + k, fz - Math.floor(k / 2), k > 6 ? 'accent' : 'fur', head, MODE_RIGID);
    }
  } else if (kind === 'coif' || kind === 'knit' || kind === 'kerchief' || kind === 'beret') {
    const off = kind === 'coif' ? 1.4 : kind === 'knit' ? 1.8 : 1.3;
    const ymin = kind === 'coif' ? cyv - ry * 1.15 : kind === 'knit' ? yE + HU * 0.15 : yE + HU * 0.24;
    for (let q = 0; q < near.length; q++) {
      const i = near[q]; const lab = field.lab[i];
      if (cls[lab] !== 'head' && !(kind === 'coif' && cls[lab] === 'neck')) continue;
      const [xi, yj, zk] = prep.xyz(i);
      const x = grid.cx(xi), y = yj + 0.5, z = grid.cz(zk);
      if (y < ymin) continue;
      const d = field.d[i];
      if (d > off + (grid.col[i] && grid.mat[i] === MAT.hair ? 1.0 : 0) || d < -2) continue;
      if (kind === 'coif' && z > rz * 0.2 && Math.abs(x) < rx * 0.88 && y < yE + HU * 0.22) continue; // face
      if (kind === 'kerchief' && z > rz * 0.5 && y < yE + HU * 0.3) continue;
      let zone = 'main';
      if (kind === 'knit' && y < yE + HU * 0.15 + 3) zone = 'trim';
      if (kind === 'coif' && z > rz * 0.05 && Math.abs(x) < rx * 0.88 + 1.5 && y < yE + HU * 0.22 + 1.5) zone = 'trim';
      put(xi, yj, zk, zone, n.Head, MODE_RIGID);
    }
    // remove hair voxels poking through the cap
    for (let q = 0; q < near.length; q++) {
      const i = near[q]; if (cls[field.lab[i]] !== 'head') continue;
      const [, yj] = prep.xyz(i);
      if (yj + 0.5 >= ymin && grid.col[i] && grid.mat[i] === MAT.hair && grid.layer[i] === LAYER.hair && field.d[i] > off) grid.col[i] = 0;
    }
    if (kind === 'knit' || kind === 'beret') { // pompom / tip
      const yj = Math.round(cyv + ry + off + 1);
      for (let dz = -1; dz <= 1; dz++) for (let dx = -1; dx <= 1; dx++) for (let dy = 0; dy <= 1; dy++)
        if (Math.abs(dx) + Math.abs(dz) + dy < 3) put(Math.round(grid.ox + dx - 0.5 + (kind === 'beret' ? 2 : 0)), yj + dy, Math.round(grid.oz + dz - 0.5), kind === 'knit' ? 'trim' : 'main', head, MODE_RIGID);
    }
    if (kind === 'kerchief') { // knot and tails at the nape
      for (let k = 0; k < 6; k++) for (let dx = -1; dx <= 1; dx++) put(Math.round(grid.ox + dx - 0.5), Math.round(cyv - ry * 0.3 - k), Math.round(grid.oz - rz - off - 1 - k * 0.3), 'main', n.Head, MODE_RIGID);
    }
  } else if (kind === 'crown' || kind === 'headband') {
    const yb = Math.round(yE + HU * 0.27);
    for (let q = 0; q < near.length; q++) {
      const i = near[q]; if (cls[field.lab[i]] !== 'head') continue;
      const [xi, yj, zk] = prep.xyz(i);
      if (yj < yb || yj > yb + (kind === 'crown' ? 2 : 1)) continue;
      const d = field.d[i];
      const surf = grid.col[i] && grid.mat[i] === MAT.hair ? 2.8 : 1.6;
      if (d > surf || d < surf - 1.5) continue;
      let zone = 'main';
      if (kind === 'crown') { const k = h3(xi >> 1, yj, zk >> 1, g.seed); zone = k < 0.3 ? 'accent' : k < 0.55 ? 'trim' : 'main'; }
      put(xi, yj, zk, zone, n.Head, MODE_RIGID);
    }
  }
};

// Bags: satchel on a strap, backpack, wicker basket.
B.bag = (base, grid, g) => {
  const { P, U, sk, field } = base, prep = prepare(base);
  const pr = g.params, put = writer(base, grid, g);
  const n = sk.byName;
  const backZ = (xi, yj) => { for (let zk = 0; zk < grid.nz; zk++) if (grid.col[grid.idx(xi, yj, zk)]) return zk; return -1; };
  if (pr.kind === 'backpack' || pr.kind === 'basket') {
    const w = (pr.kind === 'basket' ? 0.085 : 0.075) * U, top = (P.yS - 0.03) * U, bot = top - (pr.kind === 'basket' ? 0.24 : 0.2) * U, depth = (pr.kind === 'basket' ? 0.09 : 0.07) * U;
    let zb = 1e9;
    for (let yj = Math.floor(bot); yj <= top; yj++) for (let xi = Math.floor(grid.ox - w); xi <= grid.ox + w; xi++) { const z = backZ(xi, yj); if (z >= 0) zb = Math.min(zb, z); }
    for (let yj = Math.floor(bot); yj <= top; yj++) for (let xi = Math.floor(grid.ox - w); xi <= Math.ceil(grid.ox + w); xi++) for (let k = 1; k <= depth; k++) {
      const zk = zb - k;
      const ex = Math.abs(grid.cx(xi)) > w - 1.5, ey = yj > top - 1.5 || yj < bot + 1.5;
      const ez = k > depth - 1.5;
      let zone = 'main';
      if (pr.kind === 'basket') zone = ((yj + (k > depth - 1.5 ? xi : zk)) % 3 === 0) ? 'trim' : 'main';
      else if (ey && !ez) zone = 'trim';
      else if (yj > top - 0.07 * U && ez) zone = 'trim'; // flap
      if (pr.kind === 'basket' && yj > top - 1 && !(ex || ez || k <= 1)) continue; // open top
      put(xi, yj, zk, zone, n.UpperChest, MODE_NORMAL);
    }
    // straps over the shoulders
    for (const s of [-1, 1]) {
      const sx = s * 0.05 * U;
      for (let q = 0; q < prep.near.length; q++) {
        const i = prep.near[q]; const [xi, yj, zk] = prep.xyz(i);
        const x = grid.cx(xi), y = yj + 0.5, z = grid.cz(zk);
        if (Math.abs(x - sx) > 1.1 || y < (P.yS - 0.12) * U) continue;
        const c = prep.cls[field.lab[i]]; if (c !== 'torso') continue;
        if (grid.col[i]) continue;
        let t = false;
        for (const [dx, dy, dz] of [[0, 0, 1], [0, 0, -1], [0, 1, 0], [0, -1, 0]]) if (grid.inb(xi + dx, yj + dy, zk + dz) && grid.col[grid.idx(xi + dx, yj + dy, zk + dz)] && grid.layer[grid.idx(xi + dx, yj + dy, zk + dz)] !== LAYER.acc) t = true;
        if (t && (z < 0 || y > (P.yS - 0.06) * U || Math.abs(x - sx) < 0.6)) put(xi, yj, zk, 'cord', field.lab[i], MODE_NORMAL);
      }
    }
  } else {
    // satchel: strap from left shoulder to right hip, bag on the right hip
    const sh = [0.07 * U, P.yS * U], hp = [-prep.hipRx * 0.9, (P.yHip + 0.03) * U];
    for (let q = 0; q < prep.near.length; q++) {
      const i = prep.near[q]; const [xi, yj, zk] = prep.xyz(i);
      if (grid.col[i]) continue;
      const x = grid.cx(xi), y = yj + 0.5;
      const t = (y - hp[1]) / (sh[1] - hp[1]); if (t < 0 || t > 1.05) continue;
      const lx = hp[0] + (sh[0] - hp[0]) * t;
      if (Math.abs(x - lx) > 1.2) continue;
      const c = prep.cls[field.lab[i]]; if (c !== 'torso' && c !== 'neck') continue;
      let touch = false;
      for (const [dx, dz] of [[0, 1], [0, -1], [1, 0], [-1, 0]]) if (grid.inb(xi + dx, yj, zk + dz) && grid.col[grid.idx(xi + dx, yj, zk + dz)]) touch = true;
      if (touch) put(xi, yj, zk, 'cord', field.lab[i], MODE_NORMAL);
    }
    const bx = Math.round(grid.ox - prep.hipRx - 1.5), by = Math.round((P.yHip + 0.02) * U);
    const h = Math.round(0.07 * U), w = Math.round(0.03 * U), dz = Math.round(0.055 * U);
    for (let yj = by - h; yj <= by; yj++) for (let k = 0; k < w; k++) for (let zk = Math.round(grid.oz - dz); zk <= Math.round(grid.oz + dz); zk++) {
      const zone = yj > by - h * 0.4 && k === w - 1 ? 'trim' : 'main';
      put(bx - k, yj, zk, zone, n.Hips, MODE_SKIRT);
    }
  }
};

B.necklace = (base, grid, g) => {
  const { P, U, sk, field } = base, prep = prepare(base);
  const put = writer(base, grid, g);
  const yN = P.yNb * U;
  for (let q = 0; q < prep.near.length; q++) {
    const i = prep.near[q]; const [xi, yj, zk] = prep.xyz(i);
    if (grid.col[i]) continue;
    const x = grid.cx(xi), y = yj + 0.5, z = grid.cz(zk);
    const c = prep.cls[field.lab[i]]; if (c !== 'torso' && c !== 'neck') continue;
    const target = yN - 1 - (0.05 * U) * clamp01(1 - (x * x) / (0.06 * U * 0.06 * U)) * (z > 0 ? 1 : 0.1);
    if (Math.abs(y - target) > 0.6) continue;
    let touch = false;
    for (const [dx, dz] of [[0, -1], [1, 0], [-1, 0], [0, 1]]) if (grid.inb(xi + dx, yj, zk + dz) && grid.col[grid.idx(xi + dx, yj, zk + dz)]) touch = true;
    if (touch) put(xi, yj, zk, 'cord', field.lab[i], MODE_NORMAL);
  }
  // pendant
  const py = Math.round(yN - 1 - 0.05 * U);
  let zf = -1; const xi0 = Math.round(grid.ox - 0.5);
  for (let zk = grid.nz - 1; zk >= 0; zk--) if (grid.col[grid.idx(xi0, py - 1, zk)]) { zf = zk; break; }
  if (zf >= 0) for (let dy = -2; dy <= 0; dy++) for (let dx = -1; dx <= 0; dx++) {
    const zone = dy === -1 ? 'accent' : 'metal';
    put(xi0 + dx, py + dy, zf + 1, zone, sk.byName.UpperChest, MODE_NORMAL);
  }
};

// Skirt alone (worn over a chemise, under a bodice): waistband + flared part.
B.skirt = (base, grid, g) => {
  const { field, P, U } = base, prep = prepare(base), { cls, near } = prep;
  const pr = g.params, put = writer(base, grid, g), off = pr.off ?? 1.3;
  const top = (P.yHip + 0.09) * U, skirtTop = (P.yHip + 0.02) * U;
  for (let q = 0; q < near.length; q++) {
    const i = near[q]; if (cls[field.lab[i]] !== 'torso') continue;
    const [xi, yj, zk] = prep.xyz(i);
    const y = yj + 0.5;
    if (y > top || y < skirtTop) continue;
    if (field.d[i] <= off) put(xi, yj, zk, y > top - 1.5 ? 'trim' : 'main', field.lab[i], MODE_NORMAL);
  }
  skirt(base, grid, g, put, pr.hem * U, skirtTop, off, pr);
};

export const BUILDERS = B;

// ------------------------------------------------------------------ outfits
const ORDER = ['legs', 'feet', 'shirt', 'over', 'vest', 'hands', 'belt', 'apron', 'acc', 'cloak', 'head', 'neck'];

export function dressOutfit(base, grid, wardrobe, occasion) {
  const ids = wardrobe.outfits[occasion] ?? wardrobe.outfits.everyday;
  const gs = ids.map(id => wardrobe.garments.find(g => g.id === id)).filter(Boolean);
  gs.sort((a, b) => ORDER.indexOf(a.slot) - ORDER.indexOf(b.slot));
  for (const g0 of gs) {
    const g = resolve(g0);
    B[g.builder](base, grid, g);
  }
  // a hood or hat hides beard? no: beard is re-applied on top so it shows under hoods
  return grid;
}

// colors stored as '#rrggbb' strings in the NPC data; builders want ints
function resolve(g) {
  const colors = {};
  for (const [k, v] of Object.entries(g.colors)) colors[k] = typeof v === 'string' ? hex(v) : v;
  const pattern = g.pattern ? { ...g.pattern } : null;
  if (pattern) for (const k of ['c2', 'c3']) if (typeof pattern[k] === 'string') pattern[k] = hex(pattern[k]);
  return { ...g, colors, pattern, layer: g.layer ?? g.slot };
}

export { makeWardrobe } from './wardrobe.js';
