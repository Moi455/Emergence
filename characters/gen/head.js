// Skin fill, face features, hair and beard.
import { h3, vnoise } from './rng.js';
import { mix, ramp, rgb, mul, hex, R, G, B } from './color.js';
import { MAT, clamp01 } from './body.js';

export const LAYER = { body: 0, hair: 1, legs: 2, feet: 3, shirt: 4, over: 5, vest: 6, belt: 7, apron: 8, hands: 9, cloak: 10, head: 11, beard: 12, acc: 13 };

export function fillBody(grid, field, bp, seed) {
  const { d, lab } = field;
  const skin = bp.skin;
  for (let i = 0; i < d.length; i++) {
    if (d[i] > 0) continue;
    const zk = Math.floor(i / (grid.nx * grid.ny)), yj = Math.floor(i / grid.nx) % grid.ny, xi = i % grid.nx;
    const n = h3(xi, yj, zk, seed) - 0.5;
    const c = ramp(skin, 1 + n * 0.022 + (vnoise(xi, yj, zk, 4, seed) - 0.5) * 0.05);
    grid.col[i] = c | 0x1000000; grid.bone[i] = lab[i]; grid.mat[i] = MAT.skin; grid.layer[i] = 0; grid.mode[i] = 0;
  }
}

// Finger creases: darken skin where two different finger bones touch, lighter nails at the tips.
export function hands(grid, sk) {
  const isF = sk.bones.map(b => /Index|Middle|Ring|Little/.test(b.name));
  const isTip = sk.bones.map(b => /Intermediate|Distal/.test(b.name));
  const { nx, ny, nz } = grid;
  const mark = [];
  for (let zk = 1; zk < nz - 1; zk++) for (let yj = 1; yj < ny - 1; yj++) for (let xi = 1; xi < nx - 1; xi++) {
    const i = grid.idx(xi, yj, zk);
    if (!grid.col[i] || !isF[grid.bone[i]]) continue;
    const b = grid.bone[i];
    const j = grid.idx(xi, yj, zk + 1), k = grid.idx(xi, yj - 1, zk);
    if (grid.col[j] && isF[grid.bone[j]] && grid.bone[j] !== b && !(isTip[b] !== isTip[grid.bone[j]])) mark.push([i, 0.72]);
    else if (isTip[b] && !grid.col[k]) mark.push([i, 1.12]);
  }
  for (const [i, k] of mark) grid.col[i] = ramp(grid.col[i] & 0xffffff, k) | 0x1000000;
}

function frontZ(grid, xi, yj, boneOK) {
  for (let zk = grid.nz - 1; zk >= 0; zk--) {
    const i = grid.idx(xi, yj, zk);
    if (grid.col[i] && boneOK(grid.bone[i])) return zk;
  }
  return -1;
}

// Face: painted voxels plus a few relief voxels (brow, nose, lips, ears).
// block: block size of the style mesh in voxels (0 for strict voxels). With blocks, relief is
// made in whole blocks (nose, ears) and half-block relief (brow ridge, chin) is left to paint.
export function face(grid, sk, P, bp, U, rng, block = 0) {
  const head = sk.byName.Head;
  const isHead = b => b === head;
  const HU = P.headH * U;
  const ox = grid.ox;
  const X = x => Math.round(x + ox - 0.5);
  const cyv = P.cy * U;
  const skin = bp.skin;
  const dark = mix(ramp(skin, 0.55), hex('#3a2218'), 0.45);
  const lip = mix(ramp(skin, 0.78), hex('#b0504a'), 0.30);
  const blush = mix(skin, hex('#e06a5a'), 0.16);
  const set = (xi, yj, zk, c, mat = MAT.skin) => grid.set(xi, yj, zk, c, head, mat, 0, 0);
  const paint = (xi, yj, c, mat = MAT.skin, dz = 0) => {
    const z = frontZ(grid, xi, yj, isHead); if (z < 0) return -1;
    set(xi, yj, z + dz, c, mat); return z;
  };
  const yE = Math.round(cyv - HU * (P.child ? 0.07 : 0.045));
  // face plane between the eyes, before any relief: the style mesh lines its blocks up on it
  const zFace = frontZ(grid, X(0), yE, isHead);
  // eye socket: remove the surface voxel, paint the one behind it
  const sock = (xi, yj, c) => {
    const z = frontZ(grid, xi, yj, isHead); if (z < 0) return;
    grid.clear(xi, yj, z); set(xi, yj, z - 1, c, MAT.eye);
  };
  const eyeX = Math.max(3, Math.round(HU * (P.child ? 0.19 : 0.175)));
  const ew = HU > 22 ? 3 : 2;
  const eyeCol = bp.eyes;
  const brow = mul(bp.hairColor, 0.85);
  const lash = mix(bp.hairColor, hex('#1d1410'), 0.6);
  // skin modulation: cheeks, nose redness, under-brow
  for (let yj = yE - Math.round(HU * 0.3); yj <= yE + Math.round(HU * 0.3); yj++) {
    for (let x = -Math.round(HU * 0.45); x <= Math.round(HU * 0.45); x++) {
      const xi = X(x);
      const z = frontZ(grid, xi, yj, isHead); if (z < 0) continue;
      const i = grid.idx(xi, yj, z);
      const cur = grid.col[i] & 0xffffff;
      const ax = Math.abs(x);
      if (yj < yE - 1 && yj > yE - HU * 0.24 && ax >= eyeX - 1 && ax <= eyeX + 2) grid.col[i] = mix(cur, blush, 0.5 + bp.ruddy * 0.5) | 0x1000000;
      if (bp.freckles && yj < yE - 1 && yj > yE - HU * 0.2 && ax < eyeX + 2 && h3(xi, yj, z, 77) < 0.18) grid.col[i] = ramp(cur, 0.82) | 0x1000000;
      if (bp.stubble && yj < yE - HU * 0.25 && (ax > HU * 0.12 || yj < yE - HU * 0.38)) grid.col[i] = mix(cur, bp.stubbleColor, 0.32 + h3(xi, yj, z, 5) * 0.12) | 0x1000000;
    }
  }
  // brow ridge: the forehead overhangs the eyes by one voxel, so the sockets sit in shadow
  const ridgeW = eyeX + ew + 1;
  for (let yj = yE + 2; !block && yj <= yE + 3 + (P.child ? 0 : 1); yj++) for (let x = -ridgeW; x <= ridgeW; x++) {
    if (Math.abs(x) === ridgeW && yj === yE + 2) continue;
    const xi = X(x), z = frontZ(grid, xi, yj, isHead); if (z < 0) continue;
    const cur = grid.col[grid.idx(xi, yj, z)] & 0xffffff;
    set(xi, yj, z + 1, ramp(cur, 1.03));
  }
  // chin: the jaw comes forward a little under the mouth
  const yMouth = yE - bp.noseL - (P.child ? 2 : 3);
  for (let yj = yMouth - 4; !block && yj <= yMouth - 2; yj++) for (let x = -(bp.mouthW + 1); x <= bp.mouthW + 1; x++) {
    if (Math.abs(x) === bp.mouthW + 1 && yj !== yMouth - 3) continue;
    const xi = X(x), z = frontZ(grid, xi, yj, isHead); if (z < 0) continue;
    set(xi, yj, z + 1, ramp(grid.col[grid.idx(xi, yj, z)] & 0xffffff, 1.0));
  }
  // eyes (set into the face: paint on surface; brow row protrudes)
  for (const s of [-1, 1]) {
    const cx = s * eyeX;
    const xs = [];
    for (let k = 0; k < ew; k++) xs.push(cx + s * (k - (ew === 3 ? 1 : 0)));
    // inner->outer order
    xs.sort((a, b) => Math.abs(a) - Math.abs(b));
    for (let k = 0; k < xs.length; k++) {
      const xi = X(xs[k]);
      // lower row: sclera / iris
      let c;
      if (ew === 3) c = k === 1 ? mix(eyeCol, hex('#120c0a'), 0.55) : k === 0 ? hex('#f0e9e0') : hex('#e2d8cc');
      else c = k === 0 ? mix(eyeCol, hex('#120c0a'), 0.5) : hex('#ece4da');
      sock(xi, yE, c);
      // upper row: iris top / lid line
      const cu = ew === 3 && k === 1 ? mix(eyeCol, hex('#120c0a'), 0.2) : lash;
      sock(xi, yE + 1, ew === 3 && k === 1 ? cu : (k === 0 ? mix(lash, skin, 0.35) : lash));
    }
    // outer lash flick
    if (bp.lashes) paint(X(cx + s * (ew === 3 ? 2 : 1)), yE + 1, lash, MAT.eye);
    // brow: protrudes one voxel, 2 rows above the eye
    const bw = ew + 2;
    for (let k = -1; k < bw - 1; k++) {
      const x = cx + s * (k - (ew === 3 ? 1 : 0));
      const tilt = bp.browTilt * (s * (x - cx)) / bw; // angry/sad brows
      const yb = yE + 3 + Math.round(tilt + (k === bw - 2 ? -0.6 : 0));
      const z = paint(X(x), yb, brow, MAT.hair, 0);
      if (z >= 0 && bp.browThick > 0.5) set(X(x), yb, z + 1, mul(brow, 1.05), MAT.hair);
      if (z >= 0 && bp.browThick > 0.8) paint(X(x), yb + 1, mul(brow, 0.92), MAT.hair);
    }
    // under-eye shade
    for (let k = 0; k < ew; k++) {
      const xi = X(cx + s * (k - (ew === 3 ? 1 : 0)));
      const z = frontZ(grid, xi, yE - 1, isHead);
      if (z >= 0) { const i = grid.idx(xi, yE - 1, z); grid.col[i] = ramp(grid.col[i] & 0xffffff, bp.age > 45 ? 0.86 : 0.94) | 0x1000000; }
    }
  }
  // nose: a sculpted wedge. Narrow bridge between the eyes, widening to a rounded tip
  // that stands out 2 to 4 voxels, with wings and dark nostrils underneath.
  const nl = bp.noseL + 1, nyTop = yE + 1, nyBot = yE - nl + 1, nw = bp.noseW;
  // nose depth is set for 1.25 cm voxels (head about 26 voxels tall); coarser voxels shrink it
  const tipD = Math.max(2, Math.round((bp.noseD + (P.child ? 0 : 1)) * Math.min(1, HU / 26)));
  if (block) {
    // nose in whole blocks: the middle block column of the face (3 voxels wide), out by 0 at
    // the eyes, then one block, then the tip; the mesh bevel turns the steps into a wedge
    const tipB = P.child ? 1 : tipD >= 3 ? 2 : 1, B2 = block;
    for (let yj = nyBot; yj <= nyTop; yj++) {
      const m = Math.floor((yE + 1 - yj) / B2);
      const db = m <= 0 ? 0 : Math.min(tipB, m);
      if (!db) continue;
      const f = (nyTop - yj) / (nyTop - nyBot);
      for (let x = -1; x <= 1; x++) {
        const xi = X(x), z = frontZ(grid, xi, yj, isHead); if (z < 0) continue;
        let c = mix(skin, blush, 0.1 + f * 0.25);
        if (bp.noseRed) c = mix(c, hex('#d06050'), 0.1 + f * 0.3);
        for (let k = z + 1; k <= zFace + B2 * db; k++) set(xi, yj, k, ramp(c, (x ? 0.95 : 1.0) + (k - zFace) * 0.01));
      }
    }
  } else {
    for (let yj = nyBot; yj <= nyTop; yj++) {
      const f = (nyTop - yj) / (nyTop - nyBot); // 0 at the bridge, 1 at the tip row
      // straight profile from the bridge to the tip; the lowest row tucks back under the tip
      const depth = yj === nyBot ? Math.max(1, tipD - 1) : Math.max(1, Math.round(1 + (tipD - 1) * f));
      const half = f < 0.3 ? 0 : nw >= 2 && f > 0.75 ? 2 : 1;
      for (let x = -half; x <= half; x++) {
        const xi = X(x);
        const z = frontZ(grid, xi, yj, isHead); if (z < 0) continue;
        const side = Math.abs(x);
        const dd = side === 0 ? depth : side === 1 && half === 2 ? Math.max(1, depth - 1) : Math.max(1, depth - (half === 2 ? 2 : 1));
        let c = mix(skin, blush, 0.1 + f * 0.25);
        if (bp.noseRed) c = mix(c, hex('#d06050'), 0.1 + f * 0.3);
        for (let k = 1; k <= dd; k++) set(xi, yj, z + k, ramp(c, (side > 0 ? 0.93 : 1.0) + k * 0.02));
      }
    }
  }
  // nostrils and the shadow under the tip
  for (const x of [-1, 0, 1]) {
    const xi = X(x), z = frontZ(grid, xi, nyBot - 1, isHead);
    if (z >= 0) set(xi, nyBot - 1, z, x === 0 ? ramp(skin, 0.82) : mix(ramp(skin, 0.55), hex('#3a2218'), 0.35));
  }
  // mouth
  const yM = nyBot - (P.child ? 2 : 3);
  const mw = bp.mouthW;
  for (let x = -mw; x <= mw; x++) {
    const xi = X(x);
    const corner = Math.abs(x) === mw;
    const yy = yM + (corner ? bp.smile : 0);
    paint(xi, yy, corner ? mix(dark, skin, 0.4) : dark);
    if (!corner && Math.abs(x) < mw) {
      const z = paint(xi, yM - 1, lip);
      // lower lip catches the light: one voxel out, two for full lips
      if (z >= 0 && Math.abs(x) < mw - (bp.lipFull ? 0 : 1)) set(xi, yM - 1, z + 1, ramp(lip, 1.04));
    }
  }
  // chin dimple / chin shade
  const zc = frontZ(grid, X(0), yM - 3, isHead);
  if (zc >= 0) { const i = grid.idx(X(0), yM - 3, zc); grid.col[i] = ramp(grid.col[i] & 0xffffff, 0.95) | 0x1000000; }
  // wrinkles for elders
  if (bp.age > 50) {
    for (const s of [-1, 1]) {
      paint(X(s * (eyeX + (ew === 3 ? 3 : 2))), yE, ramp(skin, 0.84));
      paint(X(s * (eyeX + (ew === 3 ? 3 : 2))), yE - 1, ramp(skin, 0.88));
      paint(X(s * (nw + 2)), nyBot, ramp(skin, 0.86)); paint(X(s * (nw + 2)), nyBot - 1, ramp(skin, 0.88));
    }
    for (let x = -eyeX; x <= eyeX; x++) if (h3(x, 3, 3, 9) < 0.7) paint(X(x), yE + 6, ramp(skin, 0.9));
  }
  // scar
  if (bp.scar) {
    const s = bp.scar;
    for (let k = 0; k < 4; k++) paint(X(s * (eyeX + 1) - s * k * 0), yE + 2 - k * 2 + 1, mix(skin, hex('#e0b0a0'), 0.5));
  }
  // ears
  const earTop = yE + 1, earBot = yE - Math.round(HU * 0.2);
  for (const s of [-1, 1]) {
    for (let yj = earBot; yj <= earTop; yj++) {
      // side surface: scan x outward
      const zMid = Math.round(grid.oz - 0.5 - HU * 0.04);
      for (let dz = -1; dz <= 1; dz++) {
        const zk = zMid + dz;
        let xs = -1;
        if (s > 0) { for (let xi = grid.nx - 1; xi >= 0; xi--) { const i = grid.idx(xi, yj, zk); if (grid.col[i] && grid.bone[i] === head) { xs = xi; break; } } }
        else { for (let xi = 0; xi < grid.nx; xi++) { const i = grid.idx(xi, yj, zk); if (grid.col[i] && grid.bone[i] === head) { xs = xi; break; } } }
        if (xs < 0) continue;
        const rim = yj === earTop || yj === earBot || dz !== 0;
        if (yj === earTop && dz === 1) continue;
        const c = rim ? mix(skin, blush, 0.6) : ramp(mix(skin, blush, 0.5), 0.8);
        set(xs + s, yj, zk, c);
        if ((bp.earBig || block) && !rim) set(xs + 2 * s, yj, zk, mix(skin, blush, 0.7));
        else if (block) set(xs + 2 * s, yj, zk, c);
      }
    }
  }
  return { yE, zFace };
}

// --------------------------------------------------------------- hair
export function hair(grid, field, sk, P, bp, U, seed) {
  if (bp.hairStyle === 'bald') return;
  const head = sk.byName.Head, neck = sk.byName.Neck, uc = sk.byName.UpperChest;
  const HU = P.headH * U;
  const cyv = P.cy * U, rx = P.rx * U, ry = P.ry * U, rz = P.rz * U;
  const st = bp.hairStyle;
  const base = bp.hairColor;
  const hl = ramp(base, 1.18), sh = ramp(base, 0.74);
  const th = { crop: 0.9, short: 1.5, bowl: 2.2, long: 1.6, braid: 1.3, bun: 1.3, ponytail: 1.3, curly: 2.6, wild: 2.4, tonsure: 1.5, topknot: 1.3 }[st] ?? 1.5;
  const { d, lab } = field;
  const yE = cyv - HU * 0.045;
  const strand = (xi, yj, zk) => {
    // vertical strand stripes + clumps + top highlight
    const col = h3(xi >> 1, 0, zk >> 1, seed);
    const clump = vnoise(xi, yj * 0.7, zk, 4, seed + 3);
    let k = 0.84 + col * 0.12 + (clump - 0.5) * 0.4;
    const ny = (yj + 0.5 - cyv) / ry;
    k += ny > 0.55 ? 0.1 : ny < -0.4 ? -0.08 : 0;
    return k > 1.08 ? mix(base, hl, (k - 1.0) * 2.5) : k < 0.9 ? mix(base, sh, (0.95 - k) * 3) : ramp(base, k);
  };
  const put = (xi, yj, zk, c) => {
    const i = grid.idx(xi, yj, zk);
    // hair never overwrites face features painted on the head surface, only fills air or skin
    if (grid.col[i] && grid.mat[i] !== 1) return;
    grid.col[i] = (c & 0xffffff) | 0x1000000; grid.bone[i] = head; grid.mat[i] = MAT.hair; grid.layer[i] = 1; grid.mode[i] = 0;
  };
  const x0 = Math.max(0, Math.floor(grid.ox - rx - 8)), x1 = Math.min(grid.nx - 1, Math.ceil(grid.ox + rx + 8));
  const y0 = Math.max(0, Math.floor(cyv - ry * 3.2)), y1 = Math.min(grid.ny - 1, Math.ceil(cyv + ry + 6));
  const z0 = Math.max(0, Math.floor(grid.oz - rz - 8)), z1 = Math.min(grid.nz - 1, Math.ceil(grid.oz + rz + 8));
  for (let zk = z0; zk <= z1; zk++) for (let yj = y0; yj <= y1; yj++) for (let xi = x0; xi <= x1; xi++) {
    const i = grid.idx(xi, yj, zk);
    const x = grid.cx(xi), y = yj + 0.5, z = grid.cz(zk);
    const nx = x / rx, ny = (y - cyv) / ry, nz = z / rz;
    const onHead = lab[i] === head;
    const n = vnoise(xi, yj, zk, 3.5, seed + 11) - 0.5;
    let inside = false;
    if (onHead) {
      const dd = d[i];
      let t = th + n * (st === 'curly' || st === 'wild' ? 2.4 : 1.6);
      if (dd > t || dd < -2.0) { /* not in shell */ }
      else {
        // hairline masks
        const front = nz > 0.25;
        let lineFront = 0.36, lineSide = 0.06, lineBack = -0.42;
        if (st === 'bowl') { lineFront = 0.26; lineSide = -0.02; lineBack = -0.3; }
        if (st === 'long' || st === 'wild') { lineSide = -0.5; lineBack = -0.9; }
        if (st === 'crop') { lineFront = 0.42; }
        if (bp.receding) lineFront += 0.18;
        let ok;
        if (front) {
          // side part / fringe shaping
          const fr = lineFront + (st === 'long' || st === 'braid' || st === 'bun' || st === 'ponytail' ? Math.abs(nx - bp.part) * 0.25 - 0.05 : 0);
          ok = ny > fr && Math.abs(nx) < 1.2;
          if (st === 'bowl' && ny > lineFront) ok = true;
          if ((st === 'long' || st === 'wild') && Math.abs(nx) > 0.55 && ny > -0.6) ok = true; // curtains framing face
        } else if (nz > -0.25) ok = ny > lineSide || (bp.sideburns && ny > -0.3 && Math.abs(nx) > 0.8 && nz > 0 && nz < 0.45);
        else ok = ny > lineBack;
        if (st === 'tonsure' && ny > 0.62 && Math.abs(nx) < 0.5 && Math.abs(nz) < 0.55) ok = false;
        // keep the face clear (eyes, ears)
        if (front && nz > 0.55 && ny < lineFront && st !== 'bowl') ok = false;
        if (Math.abs(nx) > 0.85 && ny > -0.45 && ny < 0.1 && nz > -0.3 && nz < 0.2 && st !== 'long' && st !== 'wild') ok = false; // ears
        inside = ok;
      }
    }
    // long hair volume behind the head and shoulders
    if (!inside && (st === 'long' || st === 'wild')) {
      const yEnd = (P.yS - bp.hairLen) * U;
      if (y > yEnd && y < cyv && z < rz * 0.15 && z > -rz * 1.08 - (y < cyv - ry ? 2 : 0)) {
        const w = rx * (1.06 - (cyv - y) / (cyv - yEnd) * 0.18) + n * 1.2;
        const behind = d[i] > -0.5 && (lab[i] === head || lab[i] === neck || lab[i] === uc || /Shoulder|Chest|UpperArm/.test(sk.bones[lab[i]].name));
        if (Math.abs(x) < w && behind && (z < -rz * 0.25 || Math.abs(x) > rx * 0.7)) {
          // stay off the shoulders' front
          if (!(y < P.yS * U + 2 && z > -rz * 0.2)) inside = d[i] > 0 && d[i] < 3.5 + (yEnd < y ? 2 : 0) || (z < -rz * 0.4 && d[i] > 0 && y > P.yS * U - 2);
          if (y > cyv - ry * 0.9 && lab[i] === head) inside = d[i] > 0 && d[i] < th + 1.5;
        }
      }
    }
    if (inside) put(xi, yj, zk, strand(xi, yj, zk));
  }
  // extras
  const capsule = (a, b, r, colf) => {
    const minx = Math.floor(Math.min(a[0], b[0]) - r + grid.ox), maxx = Math.ceil(Math.max(a[0], b[0]) + r + grid.ox);
    const miny = Math.floor(Math.min(a[1], b[1]) - r), maxy = Math.ceil(Math.max(a[1], b[1]) + r);
    const minz = Math.floor(Math.min(a[2], b[2]) - r + grid.oz), maxz = Math.ceil(Math.max(a[2], b[2]) + r + grid.oz);
    for (let zk = minz; zk <= maxz; zk++) for (let yj = miny; yj <= maxy; yj++) for (let xi = minx; xi <= maxx; xi++) {
      if (!grid.inb(xi, yj, zk)) continue;
      const x = grid.cx(xi), y = yj + 0.5, z = grid.cz(zk);
      const bx = b[0] - a[0], by = b[1] - a[1], bz = b[2] - a[2];
      let t = ((x - a[0]) * bx + (y - a[1]) * by + (z - a[2]) * bz) / (bx * bx + by * by + bz * bz);
      t = clamp01(t);
      const dx = x - a[0] - bx * t, dy = y - a[1] - by * t, dz = z - a[2] - bz * t;
      if (dx * dx + dy * dy + dz * dz <= r * r) put(xi, yj, zk, colf(xi, yj, zk, t));
    }
  };
  if (st === 'bun' || st === 'topknot') {
    const c = st === 'bun' ? [0, cyv + ry * 0.35, -rz * 0.95] : [0, cyv + ry * 1.02, -rz * 0.1];
    const r = HU * 0.16;
    capsule(c, [c[0], c[1] + 0.01, c[2] + 0.01], r, (xi, yj, zk) => ramp(strand(xi, yj, zk), ((xi + yj) & 1) ? 1.04 : 0.95));
  }
  if (st === 'ponytail') {
    const a = [0, cyv + ry * 0.1, -rz * 1.0], b = [0, (P.yS - 0.08) * U, -rz * 1.15];
    capsule(a, b, HU * 0.085, (xi, yj, zk, t) => t < 0.08 ? bp.tieColor : strand(xi, yj, zk));
  }
  if (st === 'braid') {
    for (const s of [-1, 1]) {
      const a = [s * rx * 0.85, cyv - ry * 0.3, -rz * 0.25], b = [s * rx * 0.95, (P.yS - bp.hairLen * 0.8) * U, rz * 0.35];
      capsule(a, b, HU * 0.075, (xi, yj, zk, t) => t > 0.93 ? bp.tieColor : ((yj + (s > 0 ? 0 : 1)) % 3 === 0 ? sh : strand(xi, yj, zk)));
    }
  }
}

export function beard(grid, field, sk, P, bp, U, seed) {
  if (bp.beard === 'none') return;
  const head = sk.byName.Head;
  const HU = P.headH * U;
  const cyv = P.cy * U, rx = P.rx * U, ry = P.ry * U, rz = P.rz * U;
  const yE = Math.round(cyv - HU * 0.045);
  const yM = yE - bp.noseL - 3;
  const base = mix(bp.hairColor, bp.beardTint, 0.3);
  const { d, lab } = field;
  const style = bp.beard;
  const th = { short: 1.1, full: 1.9, long: 2.4, goatee: 1.5, mustache: 1.0 }[style];
  for (let zk = 0; zk < grid.nz; zk++) for (let yj = Math.floor(yM - HU * 0.6); yj <= yE; yj++) for (let xi = 0; xi < grid.nx; xi++) {
    if (!grid.inb(xi, yj, zk)) continue;
    const i = grid.idx(xi, yj, zk);
    if (lab[i] !== head && !(style === 'long' && sk.bones[lab[i]].name === 'Neck')) continue;
    const x = grid.cx(xi), y = yj + 0.5, z = grid.cz(zk);
    if (z < -rz * 0.1) continue;
    const ax = Math.abs(x);
    const n = vnoise(xi, yj, zk, 2, seed + 21) - 0.5;
    let t = th + n * 1.2;
    if (style === 'long') t += clamp01((yM - y) / (HU * 0.3)) * 2.5;
    if (d[i] > t || d[i] < -1.5) continue;
    let ok = false;
    const mustache = yj >= yM && yj <= yM + 1 && ax <= bp.mouthW + 1.5 && z > rz * 0.5;
    if (style === 'mustache') ok = mustache;
    else if (style === 'goatee') ok = mustache || (yj < yM - 1 && ax < HU * 0.13 && z > rz * 0.3);
    else {
      const jaw = yj < yM + 1 && yj >= yM - HU * 0.9;
      const cheek = yj <= yE - HU * 0.12 && ax > HU * 0.18 && z > -rz * 0.1 && ax < rx * 1.02;
      ok = (jaw || cheek || mustache) && !(yj === yM - 1 && ax < bp.mouthW && z > rz * 0.6) && !(yj === yM && ax < bp.mouthW && z > rz * 0.6 && !mustache);
      if (yj === yM && ax < bp.mouthW && d[i] < 0.6) ok = false; // keep the mouth line readable
      if (yj === yM - 1 && ax < bp.mouthW - 1 && d[i] < 0.6) ok = false;
    }
    if (!ok) continue;
    const k = 0.86 + h3(xi, 1, zk, seed) * 0.2 + n * 0.2;
    const c = ramp(base, k);
    if (grid.col[i] && grid.mat[i] !== 1) continue;
    grid.col[i] = c | 0x1000000; grid.bone[i] = head; grid.mat[i] = MAT.hair; grid.layer[i] = 12; grid.mode[i] = 0;
  }
}
