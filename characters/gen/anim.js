// Procedural clips on the humanoid skeleton (interfaces.md § 7). Rotations are local, relative
// to the rest pose (all rest orientations are identity, so local axes = character axes:
// X = character's left, Y = up, Z = forward). Sampled at 30 frames per second.
//
// Sign conventions (rest pose, arms down):
//   X(-a) on an arm or a thigh swings it forward; X(+a) on LowerLeg bends the knee,
//   X(-a) on LowerArm bends the elbow; X(+a) on Spine/Chest/Head leans forward or nods.
//   Z(s*a) on a left (s=1) or right (s=-1) limb moves it away from the body.
//
// A clip: { name, duration, loop, speed_mps?, events: [{name, t}], tracks: {bone: {times, rotations}},
//           root?: {times, values: [[x,y,z]...]} }  root = Hips offset from rest, metres.
const D = Math.PI / 180;
export const FPS = 30;

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
// Euler in degrees, applied Z then X then Y (twist last)
const E = (rx = 0, ry = 0, rz = 0) => qMul(Y(ry), qMul(X(rx), Z(rz)));
const smooth = u => u <= 0 ? 0 : u >= 1 ? 1 : u * u * (3 - 2 * u);
const SIDES = [['Left', 1], ['Right', -1]];
const FINGERS = ['Index', 'Middle', 'Ring', 'Little'];

// A pose: { bone: [rx, ry, rz] } plus optional root [x, y, z] in metres.
function lerpPose(a, b, u) {
  const out = {};
  for (const k of new Set([...Object.keys(a), ...Object.keys(b)])) {
    const pa = a[k] || [0, 0, 0], pb = b[k] || [0, 0, 0];
    out[k] = [0, 1, 2].map(i => pa[i] + (pb[i] - pa[i]) * u);
  }
  return out;
}
// keyed poses: keys = [[u, pose], ...] with u in [0, 1]; smoothstep between keys
function keyed(keys, u) {
  if (u <= keys[0][0]) return keys[0][1];
  for (let i = 0; i < keys.length - 1; i++) {
    const [u0, p0] = keys[i], [u1, p1] = keys[i + 1];
    if (u <= u1) return lerpPose(p0, p1, smooth((u - u0) / (u1 - u0)));
  }
  return keys[keys.length - 1][1];
}
const add = (...ps) => { const o = {}; for (const p of ps) for (const [k, v] of Object.entries(p)) o[k] = o[k] ? o[k].map((x, i) => x + v[i]) : v.slice(); return o; };

// hand shapes
function hand(S, s, curl, thumb = curl * 0.5) {
  const o = {};
  for (const F of FINGERS) { o[S + F + 'Proximal'] = [0, 0, -s * curl]; o[S + F + 'Intermediate'] = [0, 0, -s * curl * 1.1]; o[S + F + 'Distal'] = [0, 0, -s * curl * 0.8]; }
  o[S + 'ThumbProximal'] = [0, 0, -s * thumb]; o[S + 'ThumbDistal'] = [0, 0, -s * thumb * 0.7];
  return o;
}
const relaxed = () => add(hand('Left', 1, 18, 10), hand('Right', -1, 18, 10));
const grip = (sides = 'both') => add(sides !== 'right' ? hand('Left', 1, 78, 40) : hand('Left', 1, 18, 10), sides !== 'left' ? hand('Right', -1, 78, 40) : hand('Right', -1, 18, 10));
const armsRest = (open = 5) => ({ LeftUpperArm: [-2, 0, open], RightUpperArm: [-2, 0, -open], LeftLowerArm: [-8, 0, 0], RightLowerArm: [-8, 0, 0], LeftHand: [0, 0, 4], RightHand: [0, 0, -4] });

export function makeClips(sk, bp, voxel = 0.0125) {
  const old = bp.age >= 60, child = bp.age < 13;
  const n = sk.byName, B = sk.bones, m = v => v * voxel;
  const hipY = m(B[n.LeftUpperLeg].head[1]), kneeY = m(B[n.LeftLowerLeg].head[1]), ankleY = m(B[n.LeftFoot].head[1]);
  const thigh = hipY - kneeY, shin = kneeY - ankleY;
  const stoop = old ? { Spine: [6, 0, 0], Chest: [4, 0, 0], Neck: [-6, 0, 0], Head: [-4, 0, 0] } : {};
  const clips = [];

  // Sampling helper: f(u, t) -> pose; writes tracks for every bone the poses mention.
  function clip(name, T, loop, f, extra = {}) {
    const N = Math.max(2, Math.round(T * FPS) + 1), times = [], tr = {}, root = { times, values: [] };
    let hasRoot = false;
    const frames = [];
    for (let i = 0; i < N; i++) { const t = (i / (N - 1)) * T; times.push(t); frames.push(f(t / T, t)); }
    const bones = new Set(); for (const p of frames) for (const k of Object.keys(p)) if (k !== 'root') bones.add(k);
    for (const b of bones) if (n[b] !== undefined) tr[b] = { times, rotations: frames.map(p => p[b] ? E(...p[b]) : [0, 0, 0, 1]) };
    for (const p of frames) { root.values.push(p.root || [0, 0, 0]); if (p.root) hasRoot = true; }
    const c = { name, duration: T, loop, events: [], tracks: tr, ...extra };
    if (hasRoot) c.root = root;
    c.events = (c.events || []).map(e => ({ name: e.name, t: Math.round(e.t * 1000) / 1000 }));
    clips.push(c);
    return c;
  }
  const base = () => add(relaxed(), armsRest(), stoop);

  // ---------------------------------------------------------------- locomotion
  clip('idle', 4, true, (u) => {
    const ph = u * 2 * Math.PI, br = Math.sin(ph * 2);
    return add(base(), {
      Spine: [br * 0.8, 0, 0], Chest: [-br * 1.2, 0, 0], UpperChest: [-br * 0.6, 0, 0],
      Head: [Math.sin(ph * 2 + 1) * 1.5, Math.sin(ph) * 7, 0],
      LeftShoulder: [0, 0, br * 0.8], RightShoulder: [0, 0, -br * 0.8],
      LeftUpperArm: [0, 0, br * 0.8], RightUpperArm: [0, 0, -br * 0.8], LeftLowerArm: [-br * 1.5, 0, 0], RightLowerArm: [-br * 1.5, 0, 0],
    });
  });

  // walk, run and carry_walk share one gait
  function gait(name, T, amp, kneeA, armA, bob, lean, arms, elbow = -14) {
    const step = 2 * thigh * 1.9 * Math.sin(amp * D); // two steps per cycle, leg ~ thigh + shin
    return clip(name, T, true, (u) => {
      const ph = u * 2 * Math.PI, s1 = Math.sin(ph), c2 = Math.cos(2 * ph);
      const p = add(relaxed(), stoop, {
        root: [0, (c2 * -bob - bob * 0.6), 0],
        Hips: [0, s1 * 6 * amp / 26, Math.cos(ph) * 2.5],
        Spine: [lean, -s1 * 4 * amp / 26, 0], Chest: [0, -s1 * 3 * amp / 26, 0], UpperChest: [-1, 0, 0],
        Neck: [-lean * 0.5, 0, 0], Head: [c2 * 1.5, s1 * 3, 0],
      });
      for (const [S, s, off] of [['Left', 1, 0], ['Right', -1, Math.PI]]) {
        const q = ph + off, leg = Math.sin(q);
        p[S + 'UpperLeg'] = [-leg * amp - kneeA * 0.08, 0, 0];
        p[S + 'LowerLeg'] = [Math.max(0, Math.sin(q - 1.7)) * kneeA + 6, 0, 0];
        p[S + 'Foot'] = [leg * amp * 0.4 - Math.max(0, Math.sin(q - 2.4)) * 18, 0, 0];
        p[S + 'Toes'] = [Math.max(0, -Math.sin(q + 0.4)) * 25, 0, 0];
        if (!arms) {
          p[S + 'UpperArm'] = [leg * armA, 0, s * 6];
          p[S + 'LowerArm'] = [elbow - Math.max(0, -leg) * armA * 0.8, 0, 0];
          p[S + 'Hand'] = [0, 0, s * 4];
        }
      }
      return arms ? add(p, arms) : p;
    }, { speed_mps: Math.round(2 * step / T * 100) / 100, events: [{ name: 'footstep_l', t: T * 0.25 }, { name: 'footstep_r', t: T * 0.75 }] });
  }
  const wk = old ? 0.7 : 1;
  gait('walk', child ? 0.8 : old ? 1.3 : 1.05, 26 * wk, 55 * wk, 22 * wk, 0.012 * bp.height / 1.7, old ? 7 : 3);
  gait('run', child ? 0.56 : old ? 0.9 : 0.7, 40 * (old ? 0.8 : 1), 95, 40, 0.025 * bp.height / 1.7, 12, null, -75);
  // carrying something in front with both hands (a sack, a crate, firewood)
  const carryArms = add(grip(), { LeftUpperArm: [-30, 0, 4], RightUpperArm: [-30, 0, -4], LeftLowerArm: [-70, 0, 0], RightLowerArm: [-70, 0, 0], LeftHand: [0, 0, -12], RightHand: [0, 0, 12], Spine: [-4, 0, 0] });
  gait('carry_walk', child ? 0.9 : old ? 1.4 : 1.15, 20 * wk, 45 * wk, 0, 0.014 * bp.height / 1.7, 0, carryArms);
  clip('carry_idle', 3, true, (u) => {
    const br = Math.sin(u * 4 * Math.PI);
    return add(stoop, carryArms, { Spine: [br * 0.8, 0, 0], Chest: [-br, 0, 0], Head: [0, Math.sin(u * 2 * Math.PI) * 5, 0] });
  });

  // ---------------------------------------------------------------- body
  // seated on a chair or bench of knee height: hips back by about a thigh length
  const seated = add(relaxed(), stoop, {
    root: [0, kneeY + 0.03 - hipY, -thigh * 0.85],
    LeftUpperLeg: [-88, 0, 3], RightUpperLeg: [-88, 0, -3], LeftLowerLeg: [86, 0, 0], RightLowerLeg: [86, 0, 0],
    LeftFoot: [2, 0, 0], RightFoot: [2, 0, 0],
    Spine: [4, 0, 0], LeftUpperArm: [-28, 0, 6], RightUpperArm: [-28, 0, -6], LeftLowerArm: [-48, 0, 0], RightLowerArm: [-48, 0, 0],
    LeftHand: [10, 0, -6], RightHand: [10, 0, 6],
  });
  const leanSit = add(seated, { root: [0, (kneeY + 0.03 - hipY) * 0.7, -thigh * 0.5], Spine: [30, 0, 0], Chest: [8, 0, 0], Head: [-10, 0, 0], LeftUpperLeg: [-60, 0, 3], RightUpperLeg: [-60, 0, -3], LeftLowerLeg: [70, 0, 0], RightLowerLeg: [70, 0, 0], LeftUpperArm: [-10, 0, 0], RightUpperArm: [-10, 0, 0] });
  const standing = base();
  clip('sit_down', 1.3, false, (u) => keyed([[0, standing], [0.45, leanSit], [1, seated]], u));
  clip('sit_idle', 4, true, (u) => { const br = Math.sin(u * 4 * Math.PI); return add(seated, { Chest: [-br * 1.2, 0, 0], Head: [0, Math.sin(u * 2 * Math.PI) * 8, 0] }); });
  clip('stand_up', 1.3, false, (u) => keyed([[0, seated], [0.5, leanSit], [1, standing]], u));

  // lying on the back, face up, head towards -Z; knees slightly bent, arms along the body
  const lying = add(relaxed(), {
    root: [0, 0.11 - hipY + (hipY - m(B[n.Hips].head[1])) * 0, 0], Hips: [-90, 0, 0],
    LeftUpperLeg: [-12, 0, 4], RightUpperLeg: [-12, 0, -4], LeftLowerLeg: [16, 0, 0], RightLowerLeg: [16, 0, 0], LeftFoot: [-20, 0, 0], RightFoot: [-20, 0, 0],
    LeftUpperArm: [-4, 0, 10], RightUpperArm: [-4, 0, -10], LeftLowerArm: [-12, 0, 0], RightLowerArm: [-12, 0, 0],
    Head: [8, 12, 0],
  });
  // the root moves the Hips bone head, which sits above the hip joints: lift it so the pelvis rests on the ground
  lying.root = [0, 0.1 - m(B[n.Hips].head[1]), -(m(B[n.Hips].head[1]) - hipY)];
  clip('sleep', 6, true, (u) => { const br = Math.sin(u * 2 * Math.PI); return add(lying, { Chest: [-br * 2.5, 0, 0], UpperChest: [-br * 1.2, 0, 0], LeftUpperArm: [-br * 2, 0, 0], RightUpperArm: [-br * 2, 0, 0] }); });

  // eat and drink: right hand to the mouth, standing
  const toMouth = { RightUpperArm: [-42, 32, 6], RightLowerArm: [-128, 0, 0], RightHand: [-10, -20, 8], Head: [4, 0, 0] };
  const holdLow = { RightUpperArm: [-22, 0, -4], RightLowerArm: [-70, 0, 0], RightHand: [0, 0, 6] };
  clip('eat', 3.2, true, (u) => {
    const k = keyed([[0, holdLow], [0.25, toMouth], [0.42, toMouth], [0.62, holdLow], [1, holdLow]], u);
    const chew = u > 0.42 && u < 0.95 ? Math.sin((u - 0.42) * 40) * 1.5 : 0;
    return add(base(), { RightUpperArm: [2, 0, 5], RightLowerArm: [8, 0, 0] }, k, hand('Right', -1, 60, 30), { Jaw: [Math.max(0, chew) * 4, 0, 0], Head: [chew, 0, 0] });
  });
  const sip = { RightUpperArm: [-48, 30, 6], RightLowerArm: [-120, 0, 0], RightHand: [-30, -25, 8], Head: [-18, 0, 0], Neck: [-6, 0, 0], Chest: [-3, 0, 0] };
  clip('drink', 3.6, true, (u) => {
    const k = keyed([[0, holdLow], [0.3, sip], [0.62, sip], [0.85, holdLow], [1, holdLow]], u);
    return add(base(), { RightUpperArm: [2, 0, 5], RightLowerArm: [8, 0, 0] }, k, hand('Right', -1, 65, 35));
  });

  // ---------------------------------------------------------------- work
  // overhead two-handed strike (pickaxe, sledge): raise, strike down in front
  const strike = (name, T0, impactU) => clip(name, child ? T0 * 0.8 : old ? T0 * 1.25 : T0, true, (u) => {
    let k = u < 0.5 ? 1 - u / 0.5 : u < impactU ? (u - 0.5) / (impactU - 0.5) : 1; // 1 = down, 0 = up
    k = smooth(k);
    const p = add(grip(), stoop, {
      Hips: [k * 6, 0, 0], Spine: [-8 + k * 22, 0, 0], Chest: [-4 + k * 10, 0, 0], UpperChest: [k * 4, 0, 0],
      Neck: [-k * 10, 0, 0], Head: [-k * 8 + 4, 0, 0],
      root: [0, -k * 0.03, 0],
    });
    for (const [S, s] of SIDES) {
      p[S + 'UpperLeg'] = [-k * 10, 0, s * 4]; p[S + 'LowerLeg'] = [k * 16, 0, 0]; p[S + 'Foot'] = [-k * 6, 0, 0];
      p[S + 'Shoulder'] = [0, 0, s * (1 - k) * 8];
      p[S + 'UpperArm'] = [-160 + k * 115, 0, -s * (8 + (1 - k) * 4)];
      p[S + 'LowerArm'] = [-35 + k * 20, 0, 0];
      p[S + 'Hand'] = [-(1 - k) * 25, 0, 0];
    }
    return p;
  }, { events: [{ name: 'grab', t: 0 }, { name: 'impact', t: impactU * (child ? T0 * 0.8 : old ? T0 * 1.25 : T0) }] });
  strike('swing_pickaxe', 1.25, 0.68);

  // axe: diagonal chop from over the right shoulder down to the left, torso twisting
  {
    const T = child ? 1.1 : old ? 1.7 : 1.35, iu = 0.66;
    clip('swing_axe', T, true, (u) => {
      let k = u < 0.5 ? 1 - u / 0.5 : u < iu ? (u - 0.5) / (iu - 0.5) : 1; k = smooth(k); // 0 = wound up, 1 = struck
      return add(grip(), stoop, {
        root: [0, -0.02 * k, 0],
        Hips: [0, -10 + k * 22, 0], Spine: [k * 14, -12 + k * 20, 0], Chest: [k * 8, -10 + k * 18, 0], Head: [k * 6, 14 - k * 22, 0],
        LeftUpperLeg: [-10, 0, 8], LeftLowerLeg: [10, 0, 0], RightUpperLeg: [8, 0, -8], RightLowerLeg: [12, 0, 0],
        // both hands on the handle: wound up over the right shoulder, then down across the body
        RightUpperArm: [-150 + k * 100, 0, -30 + k * 40], RightLowerArm: [-70 + k * 50, 0, 0], RightHand: [-20 + k * 10, 0, 0],
        LeftUpperArm: [-120 + k * 80, 0, -25 + k * 25], LeftLowerArm: [-80 + k * 50, 0, 0], LeftHand: [-10, 0, 0],
      });
    }, { events: [{ name: 'grab', t: 0 }, { name: 'impact', t: iu * T }] });
  }

  // shovel: push the blade in with the foot, lever, lift and toss to the side
  {
    const T = child ? 2.0 : old ? 2.8 : 2.3;
    const ready = { Spine: [18, 0, 0], Chest: [6, 0, 0], RightUpperArm: [-30, 0, -6], RightLowerArm: [-40, 0, 0], LeftUpperArm: [-45, 0, 12], LeftLowerArm: [-50, 0, 0], RightUpperLeg: [-10, 0, 0], RightLowerLeg: [10, 0, 0] };
    const push = { Spine: [10, 0, 0], RightUpperArm: [-20, 0, -6], RightLowerArm: [-30, 0, 0], LeftUpperArm: [-38, 0, 12], LeftLowerArm: [-40, 0, 0], RightUpperLeg: [-40, 0, 0], RightLowerLeg: [50, 0, 0], RightFoot: [-10, 0, 0], root: [0, 0.03, 0] };
    const scoop = { Spine: [38, 0, 0], Chest: [12, 0, 0], Head: [-12, 0, 0], RightUpperArm: [-25, 0, -4], RightLowerArm: [-20, 0, 0], LeftUpperArm: [-55, 0, 10], LeftLowerArm: [-30, 0, 0], LeftUpperLeg: [-25, 0, 0], RightUpperLeg: [-25, 0, 0], LeftLowerLeg: [35, 0, 0], RightLowerLeg: [35, 0, 0], root: [0, -0.06, 0] };
    const toss = { Spine: [12, -30, 0], Chest: [0, -20, 0], Head: [0, -20, 0], RightUpperArm: [-50, 0, -20], RightLowerArm: [-50, 0, 0], LeftUpperArm: [-75, 0, 0], LeftLowerArm: [-40, 0, 0] };
    clip('dig_shovel', T, true, (u) => add(grip(), stoop, keyed([[0, ready], [0.22, push], [0.45, scoop], [0.7, toss], [1, ready]], u)),
      { events: [{ name: 'grab', t: 0 }, { name: 'impact', t: 0.22 * T }, { name: 'release', t: 0.7 * T }] });
  }

  // kneeling on the right knee, both hands working on the ground (planting, weeding, laying stones)
  {
    const T = 2.4;
    const kneel = add(relaxed(), {
      root: [0, kneeY - hipY + 0.02, -0.05],
      LeftUpperLeg: [-82, 0, 6], LeftLowerLeg: [84, 0, 0], LeftFoot: [0, 0, 0],
      RightUpperLeg: [-4, 0, -4], RightLowerLeg: [96, 0, 0], RightFoot: [-30, 0, 0], RightToes: [40, 0, 0],
      Spine: [26, 0, 0], Chest: [12, 0, 0], Neck: [-6, 0, 0], Head: [-6, 0, 0],
    });
    clip('kneel_work', T, true, (u) => {
      const ph = u * 2 * Math.PI, a = Math.sin(ph), b = Math.sin(ph + Math.PI);
      return add(kneel, grip(), {
        LeftUpperArm: [-38 + a * 12, 0, 8], LeftLowerArm: [-30 - a * 10, 0, 0], LeftHand: [10, 0, 0],
        RightUpperArm: [-38 + b * 12, 0, -8], RightLowerArm: [-30 - b * 10, 0, 0], RightHand: [10, 0, 0],
        Spine: [Math.sin(ph * 2) * 2, a * 4, 0],
      });
    }, { events: [{ name: 'impact', t: 0.25 * T }, { name: 'impact', t: 0.75 * T }] });
  }

  // ---------------------------------------------------------------- objects
  const crouchReach = add(relaxed(), {
    root: [0, -(hipY - kneeY) * 0.75, -0.06],
    LeftUpperLeg: [-70, 0, 8], RightUpperLeg: [-70, 0, -8], LeftLowerLeg: [105, 0, 0], RightLowerLeg: [105, 0, 0], LeftFoot: [-25, 0, 0], RightFoot: [-25, 0, 0],
    Spine: [35, 0, 0], Chest: [14, 0, 0], Head: [-14, 0, 0],
    RightUpperArm: [-38, 0, -4], RightLowerArm: [-10, 0, 0], RightHand: [20, 0, 0],
    LeftUpperArm: [-10, 0, 14], LeftLowerArm: [-30, 0, 0],
  });
  const holding = add(base(), hand('Right', -1, 70, 40), { RightUpperArm: [-20, 0, -4], RightLowerArm: [-60, 0, 0], RightHand: [0, 0, 10] });
  clip('pick_up', 1.8, false, (u) => keyed([[0, base()], [0.4, crouchReach], [0.5, add(crouchReach, hand('Right', -1, 70, 40))], [1, holding]], u), { events: [{ name: 'grab', t: 0.45 * 1.8 }] });
  clip('put_down', 1.8, false, (u) => keyed([[0, holding], [0.45, add(crouchReach, hand('Right', -1, 70, 40))], [0.55, crouchReach], [1, base()]], u), { events: [{ name: 'release', t: 0.5 * 1.8 }] });
  const offer = add(base(), hand('Right', -1, 45, 30), { RightUpperArm: [-62, 0, 4], RightLowerArm: [-22, 0, 0], RightHand: [0, -70, 0], Spine: [6, 0, 0], Head: [6, 0, 0] });
  clip('give', 1.8, false, (u) => keyed([[0, holding], [0.4, offer], [0.6, add(offer, hand('Right', -1, 15, 10))], [1, base()]], u), { events: [{ name: 'release', t: 0.5 * 1.8 }] });

  // ---------------------------------------------------------------- speech
  clip('talk_calm', 3.2, true, (u) => {
    const ph = u * 2 * Math.PI, g = 0.5 + 0.5 * Math.sin(ph * 2);
    return add(base(), {
      Spine: [1, 0, 0], Chest: [0, Math.sin(ph) * 4, 0],
      Head: [Math.sin(ph * 3) * 5, Math.sin(ph) * 6 - 4, 0], Jaw: [Math.max(0, Math.sin(ph * 9)) * 5, 0, 0],
      RightUpperArm: [-25 - g * 20 + 2, 0, -10 - g * 6 + 5], RightLowerArm: [-70 - g * 25 + 8, 0, 0], RightHand: [-10, -30 - g * 30, 4],
      RightIndexProximal: [0, 0, -10 + g * 18], RightMiddleProximal: [0, 0, -10 + g * 14],
      LeftLowerArm: [-4 - Math.sin(ph * 2 + 1) * 4, 0, 0],
    });
  });
  clip('wave', 2, true, (u) => {
    const w = Math.sin(u * 4 * Math.PI);
    return add(base(), hand('Right', -1, 5, 0), {
      RightShoulder: [0, 0, -14], RightUpperArm: [-15, 0, -98], RightLowerArm: [-10, 0, -50 + w * 25], RightHand: [0, 0, w * 8],
      Chest: [0, 0, 3], Head: [0, -8, 4],
    });
  });
  clip('nod', 1.2, false, (u) => add(base(), { Head: [Math.sin(u * 4 * Math.PI) * 12 * (1 - u * 0.5) * (u < 0.9 ? 1 : (1 - u) * 10), 0, 0], Neck: [Math.sin(u * 4 * Math.PI) * 4 * (1 - u), 0, 0] }));
  clip('shake_head', 1.4, false, (u) => add(base(), { Head: [-2, Math.sin(u * 6 * Math.PI) * 22 * (1 - u), 0], Neck: [0, Math.sin(u * 6 * Math.PI) * 6 * (1 - u), 0] }));

  // ---------------------------------------------------------------- conflict
  const flinch = add(relaxed(), { root: [0, -0.02, -0.05], Spine: [-8, 10, 0], Chest: [-10, 6, 0], Head: [-18, 15, 0], LeftUpperArm: [-40, 0, 20], LeftLowerArm: [-90, 0, 0], RightUpperArm: [-30, 0, -15], RightLowerArm: [-80, 0, 0], LeftUpperLeg: [8, 0, 3], LeftLowerLeg: [10, 0, 0], RightUpperLeg: [-6, 0, -3], RightLowerLeg: [8, 0, 0] });
  clip('hit_react', 0.9, false, (u) => keyed([[0, base()], [0.18, flinch], [0.4, add(flinch, { Head: [6, 0, 0] })], [1, base()]], u));
  // backwards onto the ground, ends lying like sleep
  const sag = add(relaxed(), { root: [0, -(hipY - kneeY) * 0.7, -0.15], Spine: [-15, 0, 0], Head: [20, 0, 0], LeftUpperLeg: [-40, 0, 6], RightUpperLeg: [-35, 0, -6], LeftLowerLeg: [80, 0, 0], RightLowerLeg: [70, 0, 0], LeftUpperArm: [-30, 0, 40], RightUpperArm: [-30, 0, -40], LeftLowerArm: [-30, 0, 0], RightLowerArm: [-30, 0, 0] });
  const down = add(lying, { root: [0, lying.root[1] - 0.02, lying.root[2] - 0.35], LeftUpperArm: [-60, 0, 55], RightUpperArm: [-60, 0, -55], LeftLowerArm: [-10, 0, 0], RightLowerArm: [-10, 0, 0], Head: [-6, 20, 0] });
  down.root = [0, lying.root[1] - 0.01, lying.root[2] - 0.35];
  clip('fall_down', 1.4, false, (u) => keyed([[0, base()], [0.15, flinch], [0.55, sag], [0.85, down], [1, down]], u), { events: [{ name: 'impact', t: 0.85 * 1.4 }] });

  return clips;
}

// Pose evaluation without any engine: local rotation per bone at time t (looping or clamped),
// then skinning matrices (column-major 4x4 per bone, metres) ready for a vertex shader.
export function sampleClip(clip, t) {
  const out = {};
  const tt = clip.loop === false ? Math.min(Math.max(t, 0), clip.duration) : ((t % clip.duration) + clip.duration) % clip.duration;
  const seg = ts => { let i = 0; while (i < ts.length - 2 && ts[i + 1] < tt) i++; return [i, Math.min(1, Math.max(0, (tt - ts[i]) / (ts[i + 1] - ts[i])))]; };
  for (const [bn, tr] of Object.entries(clip.tracks)) {
    const [i, u] = seg(tr.times);
    const a = tr.rotations[i], b = tr.rotations[i + 1];
    const dot = a[0] * b[0] + a[1] * b[1] + a[2] * b[2] + a[3] * b[3], sg = dot < 0 ? -1 : 1;
    const q = [0, 1, 2, 3].map(k => a[k] + (b[k] * sg - a[k]) * u);
    const l = Math.hypot(...q); out[bn] = q.map(v => v / l);
  }
  let root = null;
  if (clip.root) {
    const [i, u] = seg(clip.root.times), a = clip.root.values[i], b = clip.root.values[i + 1];
    root = [0, 1, 2].map(k => a[k] + (b[k] - a[k]) * u);
  }
  return { rot: out, root };
}

export function skinMatrices(sk, voxel, pose, out) {
  const n = sk.bones.length;
  out = out || new Float32Array(n * 16);
  const world = new Float32Array(n * 16);
  const R = pose && pose.root;
  for (let i = 0; i < n; i++) {
    const b = sk.bones[i];
    const p = b.parent >= 0 ? sk.bones[b.parent].head : [0, 0, 0];
    const q = (pose && pose.rot[b.name]) || [0, 0, 0, 1];
    const [x, y, z, w] = q;
    const hip = b.name === 'Hips' && R;
    const L = [1 - 2 * (y * y + z * z), 2 * (x * y + z * w), 2 * (x * z - y * w), 0,
      2 * (x * y - z * w), 1 - 2 * (x * x + z * z), 2 * (y * z + x * w), 0,
      2 * (x * z + y * w), 2 * (y * z - x * w), 1 - 2 * (x * x + y * y), 0,
      (b.head[0] - p[0]) * voxel + (hip ? R[0] : 0), (b.head[1] - p[1]) * voxel + (hip ? R[1] : 0), (b.head[2] - p[2]) * voxel + (hip ? R[2] : 0), 1];
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
