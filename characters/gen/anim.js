// Procedural clips on the humanoid skeleton. Rotations are local, relative to the rest
// pose (all rest orientations are identity, so local axes = character axes:
// X = character's left, Y = up, Z = forward).
const D = Math.PI / 180;

function qAxis(ax, ay, az, deg) {
  const h = deg * D / 2, s = Math.sin(h);
  return [ax * s, ay * s, az * s, Math.cos(h)];
}
function qMul(a, b) {
  return [
    a[3] * b[0] + a[0] * b[3] + a[1] * b[2] - a[2] * b[1],
    a[3] * b[1] - a[0] * b[2] + a[1] * b[3] + a[2] * b[0],
    a[3] * b[2] + a[0] * b[1] - a[1] * b[0] + a[2] * b[3],
    a[3] * b[3] - a[0] * b[0] - a[1] * b[1] - a[2] * b[2],
  ];
}
const X = (d) => qAxis(1, 0, 0, d), Y = (d) => qAxis(0, 1, 0, d), Z = (d) => qAxis(0, 0, 1, d);

// returns { name, duration, tracks: { boneName: { times, rotations: [[x,y,z,w]...] } }, rootY: {times, values} }
export function makeClips(sk, bp) {
  const old = bp.age >= 60, child = bp.age < 13;
  const clips = [];
  // idle: breathing, arms slightly away from the body, slow head turn
  {
    const T = 4, N = 17, times = [], tr = {};
    const add = (b, q) => { (tr[b] ??= { times, rotations: [] }).rotations.push(q); };
    for (let i = 0; i < N; i++) {
      const t = (i / (N - 1)) * T; times.push(t);
      const ph = (t / T) * 2 * Math.PI;
      const br = Math.sin(ph * 2);
      add('Spine', X(br * 0.8 + (old ? 6 : 0)));
      add('Chest', X(-br * 1.2 + (old ? 4 : 0)));
      add('UpperChest', X(-br * 0.6));
      add('Neck', X(old ? -6 : 0));
      add('Head', qMul(Y(Math.sin(ph) * 7), X(Math.sin(ph * 2 + 1) * 1.5 + (old ? -4 : 0))));
      for (const [S, s] of [['Left', 1], ['Right', -1]]) {
        add(S + 'Shoulder', Z(s * (br * 0.8)));
        add(S + 'UpperArm', qMul(Z(s * (5 + br * 0.8)), X(-2)));
        add(S + 'LowerArm', X(-8 - br * 1.5));
        add(S + 'Hand', Z(s * 4));
        for (const F of ['Index', 'Middle', 'Ring', 'Little']) { add(S + F + 'Proximal', Z(-s * 18)); add(S + F + 'Intermediate', Z(-s * 22)); }
        add(S + 'ThumbProximal', Z(-s * 10));
      }
    }
    clips.push({ name: 'idle', duration: T, tracks: tr });
  }
  // walk cycle
  {
    const T = child ? 0.8 : old ? 1.3 : 1.05, N = 25, times = [], tr = {}, rootY = { times, values: [] };
    const add = (b, q) => { (tr[b] ??= { times, rotations: [] }).rotations.push(q); };
    const amp = old ? 0.7 : 1;
    for (let i = 0; i < N; i++) {
      const t = (i / (N - 1)) * T; times.push(t);
      const ph = (t / T) * 2 * Math.PI;
      const s1 = Math.sin(ph), c2 = Math.cos(2 * ph);
      rootY.values.push((c2 * -0.012 - 0.008) * amp * bp.height / 1.7);
      add('Hips', qMul(Y(s1 * 6 * amp), Z(Math.cos(ph) * 2.5 * amp)));
      add('Spine', qMul(Y(-s1 * 4 * amp), X(old ? 7 : 3)));
      add('Chest', Y(-s1 * 3 * amp));
      add('UpperChest', X(-1));
      add('Neck', X(old ? -6 : -2));
      add('Head', qMul(Y(s1 * 3), X(c2 * 1.5)));
      for (const [S, s, off] of [['Left', 1, 0], ['Right', -1, Math.PI]]) {
        const p = ph + off;
        const leg = Math.sin(p);                 // +1 = this leg forward
        const knee = Math.max(0, Math.sin(p - 1.7)) * 55 + 6; // flex during swing
        add(S + 'UpperLeg', X(-leg * 26 * amp));
        add(S + 'LowerLeg', X(knee * amp));
        add(S + 'Foot', X(leg * 10 * amp - Math.max(0, Math.sin(p - 2.4)) * 18 * amp));
        add(S + 'Toes', X(Math.max(0, -Math.sin(p + 0.4)) * 25 * amp));
        add(S + 'Shoulder', Z(s * 0));
        add(S + 'UpperArm', qMul(Z(s * 6), X(leg * 22 * amp)));
        add(S + 'LowerArm', X(-14 - Math.max(0, -leg) * 18 * amp));
        add(S + 'Hand', Z(s * 4));
        for (const F of ['Index', 'Middle', 'Ring', 'Little']) { add(S + F + 'Proximal', Z(-s * 22)); add(S + F + 'Intermediate', Z(-s * 26)); }
        add(S + 'ThumbProximal', Z(-s * 12));
      }
    }
    clips.push({ name: 'walk', duration: T, tracks: tr, rootY });
  }
  // work: two-handed tool swing (axe, hammer, pick): raise overhead, strike down in front
  {
    const T = child ? 1.0 : old ? 1.6 : 1.25, N = 25, times = [], tr = {};
    const add = (b, q) => { (tr[b] ??= { times, rotations: [] }).rotations.push(q); };
    for (let i = 0; i < N; i++) {
      const t = (i / (N - 1)) * T; times.push(t);
      const u = t / T;
      let k = u < 0.5 ? 1 - u / 0.5 : u < 0.68 ? (u - 0.5) / 0.18 : 1; // 1 = down, 0 = up
      k = k * k * (3 - 2 * k);
      add('Hips', X(k * 6));
      add('Spine', X(-8 + k * 22));
      add('Chest', X(-4 + k * 10));
      add('UpperChest', X(k * 4));
      add('Neck', X(-k * 10));
      add('Head', X(-k * 8 + 4));
      for (const [S, s] of [['Left', 1], ['Right', -1]]) {
        add(S + 'UpperLeg', X(-k * 10));
        add(S + 'LowerLeg', X(k * 16));
        add(S + 'Foot', X(-k * 6));
        add(S + 'Shoulder', Z(s * (1 - k) * 8));
        // arms converge to the centre line, raised overhead then down in front
        add(S + 'UpperArm', qMul(Z(-s * (8 + (1 - k) * 4)), X(-160 + k * 115)));
        add(S + 'LowerArm', X(-35 + k * 20));
        add(S + 'Hand', X(-(1 - k) * 25));
        for (const F of ['Index', 'Middle', 'Ring', 'Little']) { add(S + F + 'Proximal', Z(-s * 75)); add(S + F + 'Intermediate', Z(-s * 80)); }
        add(S + 'ThumbProximal', Z(-s * 40));
      }
    }
    clips.push({ name: 'work', duration: T, tracks: tr });
  }
  // talk: one hand gestures while the head nods
  {
    const T = 3.2, N = 33, times = [], tr = {};
    const add = (b, q) => { (tr[b] ??= { times, rotations: [] }).rotations.push(q); };
    for (let i = 0; i < N; i++) {
      const t = (i / (N - 1)) * T; times.push(t);
      const ph = (t / T) * 2 * Math.PI;
      add('Spine', X(old ? 6 : 1));
      add('Chest', Y(Math.sin(ph) * 4));
      add('Head', qMul(X(Math.sin(ph * 3) * 5), Y(Math.sin(ph) * 6 - 4)));
      const g = 0.5 + 0.5 * Math.sin(ph * 2);
      add('RightUpperArm', qMul(Z(-10 - g * 6), X(-25 - g * 20)));
      add('RightLowerArm', X(-70 - g * 25));
      add('RightHand', qMul(Y(-30 - g * 30), X(-10)));
      add('LeftUpperArm', qMul(Z(6), X(-4)));
      add('LeftLowerArm', X(-12 - Math.sin(ph * 2 + 1) * 4));
      for (const F of ['Index', 'Middle', 'Ring', 'Little']) { add('Right' + F + 'Proximal', Z(8 - g * 10)); add('Left' + F + 'Proximal', Z(-18)); add('Left' + F + 'Intermediate', Z(-22)); }
    }
    clips.push({ name: 'talk', duration: T, tracks: tr });
  }
  return clips;
}

// Pose evaluation without any engine: local rotation per bone at time t (looping),
// then skinning matrices (column-major 4x4 per bone, metres) ready for a vertex shader.
export function sampleClip(clip, t) {
  const out = {};
  const tt = ((t % clip.duration) + clip.duration) % clip.duration;
  for (const [bn, tr] of Object.entries(clip.tracks)) {
    const ts = tr.times; let i = 0;
    while (i < ts.length - 2 && ts[i + 1] < tt) i++;
    const a = tr.rotations[i], b = tr.rotations[i + 1], u = Math.min(1, Math.max(0, (tt - ts[i]) / (ts[i + 1] - ts[i])));
    const dot = a[0] * b[0] + a[1] * b[1] + a[2] * b[2] + a[3] * b[3], sg = dot < 0 ? -1 : 1;
    const q = [0, 1, 2, 3].map(k => a[k] + (b[k] * sg - a[k]) * u);
    const l = Math.hypot(...q); out[bn] = q.map(v => v / l);
  }
  let rootY = 0;
  if (clip.rootY) {
    const ts = clip.rootY.times; let i = 0;
    while (i < ts.length - 2 && ts[i + 1] < tt) i++;
    const u = (tt - ts[i]) / (ts[i + 1] - ts[i]);
    rootY = clip.rootY.values[i] + (clip.rootY.values[i + 1] - clip.rootY.values[i]) * u;
  }
  return { rot: out, rootY };
}

export function skinMatrices(sk, voxel, pose, out) {
  const n = sk.bones.length;
  out = out || new Float32Array(n * 16);
  const world = new Float32Array(n * 16);
  for (let i = 0; i < n; i++) {
    const b = sk.bones[i];
    const p = b.parent >= 0 ? sk.bones[b.parent].head : [0, 0, 0];
    const q = (pose && pose.rot[b.name]) || [0, 0, 0, 1];
    const [x, y, z, w] = q;
    const L = [1 - 2 * (y * y + z * z), 2 * (x * y + z * w), 2 * (x * z - y * w), 0,
      2 * (x * y - z * w), 1 - 2 * (x * x + z * z), 2 * (y * z + x * w), 0,
      2 * (x * z + y * w), 2 * (y * z - x * w), 1 - 2 * (x * x + y * y), 0,
      (b.head[0] - p[0]) * voxel, (b.head[1] - p[1]) * voxel + (b.name === 'Hips' && pose ? pose.rootY : 0), (b.head[2] - p[2]) * voxel, 1];
    const W = world.subarray(i * 16, i * 16 + 16);
    if (b.parent < 0) W.set(L);
    else {
      const P = world.subarray(b.parent * 16, b.parent * 16 + 16);
      for (let c = 0; c < 4; c++) for (let r = 0; r < 4; r++) W[c * 4 + r] = P[r] * L[c * 4] + P[4 + r] * L[c * 4 + 1] + P[8 + r] * L[c * 4 + 2] + P[12 + r] * L[c * 4 + 3];
    }
    // skin = world * translate(-bindHead)
    const O = out.subarray(i * 16, i * 16 + 16);
    O.set(W);
    const hx = -b.head[0] * voxel, hy = -b.head[1] * voxel, hz = -b.head[2] * voxel;
    for (let r = 0; r < 4; r++) O[12 + r] = W[r] * hx + W[4 + r] * hy + W[8 + r] * hz + W[12 + r];
  }
  return out;
}
