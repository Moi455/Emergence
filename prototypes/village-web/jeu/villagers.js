// villagers.js — villageois animés dans le prototype « Village voxel ».
// Source des personnages : le générateur du fil « Skins des villageois » (personnages/gen),
// lancé dans des workers à partir des graines de personnages/data/villagers.json (le jeu ne
// stocke que la graine et la garde-robe). Chaque villageois a son squelette humanoïde Godot
// (43 os), son atlas, deux niveaux de détail (2,5 cm et 5 cm) et des tenues interchangeables
// (quotidien, travail) générées à la demande. Comportement simple en attendant le moteur de
// décision : flâner, travailler (tenue de travail), discuter, s'asseoir, saluer le joueur.
// Se branche sur window.__game (crochets addDrawHook / addUpdate) ; sans eux, ne fait rien.
'use strict';
(function () {
const QS = new URLSearchParams(location.search);
const N_NPC = Math.max(0, Math.min(120, +(QS.get('npc') || 48)));
const VILLAGE = QS.get('village') || 'bourg';
const SEED = 1337;
const LOD_NEAR_M = 14, DRAW_MAX_M = 95;

function rng(seed) { let s = seed >>> 0; return () => { s = (s + 0x6D2B79F5) >>> 0; let t = s; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; }

// ---------------------------------------------------------------- math (column-major mat4)
function mulTo(o, a, b) {
  for (let i = 0; i < 4; i++) { const b0 = b[i * 4], b1 = b[i * 4 + 1], b2 = b[i * 4 + 2], b3 = b[i * 4 + 3];
    o[i * 4] = a[0] * b0 + a[4] * b1 + a[8] * b2 + a[12] * b3; o[i * 4 + 1] = a[1] * b0 + a[5] * b1 + a[9] * b2 + a[13] * b3;
    o[i * 4 + 2] = a[2] * b0 + a[6] * b1 + a[10] * b2 + a[14] * b3; o[i * 4 + 3] = a[3] * b0 + a[7] * b1 + a[11] * b2 + a[15] * b3; }
  return o;
}
function trs(o, t, q) {
  const [x, y, z, w] = q, x2 = x + x, y2 = y + y, z2 = z + z, xx = x * x2, xy = x * y2, xz = x * z2, yy = y * y2, yz = y * z2, zz = z * z2, wx = w * x2, wy = w * y2, wz = w * z2;
  o[0] = 1 - (yy + zz); o[1] = xy + wz; o[2] = xz - wy; o[3] = 0; o[4] = xy - wz; o[5] = 1 - (xx + zz); o[6] = yz + wx; o[7] = 0;
  o[8] = xz + wy; o[9] = yz - wx; o[10] = 1 - (xx + yy); o[11] = 0; o[12] = t[0]; o[13] = t[1]; o[14] = t[2]; o[15] = 1; return o;
}
function slerp(o, a, b, t) {
  let bx = b[0], by = b[1], bz = b[2], bw = b[3], c = a[0] * bx + a[1] * by + a[2] * bz + a[3] * bw;
  if (c < 0) { c = -c; bx = -bx; by = -by; bz = -bz; bw = -bw; }
  let k0 = 1 - t, k1 = t;
  if (c < 0.9995) { const th = Math.acos(c), s = Math.sin(th); k0 = Math.sin(k0 * th) / s; k1 = Math.sin(k1 * th) / s; }
  const r0 = a[0] * k0 + bx * k1, r1 = a[1] * k0 + by * k1, r2 = a[2] * k0 + bz * k1, r3 = a[3] * k0 + bw * k1, l = Math.hypot(r0, r1, r2, r3) || 1;
  o[0] = r0 / l; o[1] = r1 / l; o[2] = r2 / l; o[3] = r3 / l; return o;
}
const D2R = Math.PI / 180;
const qA = (ax, ay, az, deg) => { const h = deg * D2R / 2, s = Math.sin(h); return [ax * s, ay * s, az * s, Math.cos(h)]; };
const qM = (a, b) => [a[3] * b[0] + a[0] * b[3] + a[1] * b[2] - a[2] * b[1], a[3] * b[1] - a[0] * b[2] + a[1] * b[3] + a[2] * b[0], a[3] * b[2] + a[0] * b[1] - a[1] * b[0] + a[2] * b[3], a[3] * b[3] - a[0] * b[0] - a[1] * b[1] - a[2] * b[2]];
const X = (d) => qA(1, 0, 0, d), Y = (d) => qA(0, 1, 0, d), Z = (d) => qA(0, 0, 1, d);

// ---------------------------------------------------------------- extra clips (interfaces.md § 7)
// Same convention as personnages/gen/anim.js: rest rotations are identity, X = character's left,
// Y = up, Z = forward, arms hang at rest. Used only when the model lacks the clip.
function extraClips(heightM) {
  const clips = [];
  const make = (name, T, N, loop, speed, events, fn) => {
    const times = [], tracks = {}, drop = { times, values: [] };
    for (let i = 0; i < N; i++) {
      const t = (i / (N - 1)) * T; times.push(t);
      const { r, dy } = fn(i / (N - 1));
      for (const [b, q] of Object.entries(r)) (tracks[b] ??= { times, rotations: [] }).rotations.push(q);
      drop.values.push(dy || 0);
    }
    for (const tr of Object.values(tracks)) if (tr.rotations.length !== N) tr.rotations = null;
    clips.push({ name, duration: T, loop, speed, events, tracks, hipsDrop: drop });
  };
  const fingers = (r, S, s, k) => { for (const F of ['Index', 'Middle', 'Ring', 'Little']) { r[S + F + 'Proximal'] = Z(-s * k); r[S + F + 'Intermediate'] = Z(-s * (k + 6)); } r[S + 'ThumbProximal'] = Z(-s * 12); };
  // run: walk with more swing, forward lean
  make('run', 0.66, 21, true, 3.4, [{ name: 'footstep_l', time: 0.16 }, { name: 'footstep_r', time: 0.5 }], (u) => {
    const ph = u * 2 * Math.PI, r = {};
    r.Hips = Y(Math.sin(ph) * 8); r.Spine = qM(Y(-Math.sin(ph) * 6), X(10)); r.Chest = Y(-Math.sin(ph) * 4); r.Neck = X(-6);
    for (const [S, s, off] of [['Left', 1, 0], ['Right', -1, Math.PI]]) {
      const p = ph + off, leg = Math.sin(p);
      r[S + 'UpperLeg'] = X(-leg * 45 - 10); r[S + 'LowerLeg'] = X(Math.max(0, Math.sin(p - 1.6)) * 95 + 10);
      r[S + 'Foot'] = X(leg * 12); r[S + 'UpperArm'] = qM(Z(s * 10), X(leg * 45)); r[S + 'LowerArm'] = X(-70);
      fingers(r, S, s, 40);
    }
    return { r, dy: (Math.cos(4 * Math.PI * u) * -0.025 - 0.03) * heightM / 1.7 };
  });
  // swing_axe: raise overhead, strike forward-down (event impact), recover
  make('swing_axe', 1.4, 29, true, 0, [{ name: 'impact', time: 0.95 }], (u) => {
    let a; if (u < 0.55) a = -20 - 150 * (0.5 - 0.5 * Math.cos(u / 0.55 * Math.PI)); else if (u < 0.68) a = -170 + 135 * ((u - 0.55) / 0.13); else a = -35 + 15 * ((u - 0.68) / 0.32);
    const bend = u >= 0.55 && u < 0.85 ? 18 : 2, r = { Spine: X(bend), Chest: X(bend * 0.5), Neck: X(-bend * 0.6) };
    for (const [S, s] of [['Left', 1], ['Right', -1]]) { r[S + 'UpperArm'] = qM(Z(-s * 12), X(a)); r[S + 'LowerArm'] = X(-25); r[S + 'Hand'] = X(-10); fingers(r, S, s, 70); }
    r.LeftUpperLeg = X(-18); r.LeftLowerLeg = X(14); r.RightUpperLeg = X(10); r.RightLowerLeg = X(6);
    return { r, dy: -0.02 };
  });
  // talk_calm: right hand gestures, small nods
  make('talk_calm', 2.4, 25, true, 0, [], (u) => {
    const ph = u * 2 * Math.PI, s1 = Math.sin(ph), r = {};
    r.Head = qM(X(Math.sin(ph * 2) * 4), Y(Math.sin(ph) * 6)); r.Chest = Y(s1 * 3);
    r.RightUpperArm = qM(Z(-12), X(-30 - 10 * s1)); r.RightLowerArm = qM(X(-65 - 15 * s1), Y(20 * Math.sin(ph * 2)));
    r.LeftUpperArm = qM(Z(6), X(-4)); r.LeftLowerArm = X(-12); fingers(r, 'Left', 1, 20); fingers(r, 'Right', -1, 8);
    return { r };
  });
  // wave: right arm up, forearm swings
  make('wave', 1.6, 25, false, 0, [], (u) => {
    const up = Math.min(1, u / 0.2, (1 - u) / 0.2), r = {};
    r.RightUpperArm = Z(-150 * up); r.RightLowerArm = qM(Z(-30 * up * Math.sin(u * 6 * Math.PI)), X(-20 * up)); r.Head = Z(-5 * up);
    r.LeftUpperArm = Z(6); fingers(r, 'Right', -1, 0); fingers(r, 'Left', 1, 20);
    return { r };
  });
  // sit_idle: sitting on the ground, legs forward, leaning back on the hands
  make('sit_idle', 4, 17, true, 0, [], (u) => {
    const b = Math.sin(u * 4 * Math.PI), r = {};
    r.LeftUpperLeg = qM(Z(6), X(-88)); r.RightUpperLeg = qM(Z(-6), X(-88)); r.LeftLowerLeg = X(18); r.RightLowerLeg = X(26);
    r.Spine = X(-10 + b); r.Chest = X(-b); r.Head = qM(X(8), Y(Math.sin(u * 2 * Math.PI) * 10));
    for (const [S, s] of [['Left', 1], ['Right', -1]]) { r[S + 'UpperArm'] = qM(Z(s * 18), X(28)); r[S + 'LowerArm'] = X(-6); fingers(r, S, s, 10); }
    return { r, dy: -0.47 * heightM };
  });
  return clips;
}

// convert a clip in anim.js format into sampled channels on a skeleton
function bindClip(skel, c) {
  const ch = [];
  for (const [bn, t] of Object.entries(c.tracks)) {
    const j = skel.index[bn]; if (j === undefined || !t.rotations) continue;
    ch.push({ j, n: 4, times: Float32Array.from(t.times), vals: Float32Array.from(t.rotations.flat()) });
  }
  const hips = skel.index.Hips, drop = c.rootY || c.hipsDrop;
  if (drop && hips !== undefined) {
    const base = skel.rest[hips], v = new Float32Array(drop.values.length * 3);
    drop.values.forEach((d, i) => { v[i * 3] = base[0]; v[i * 3 + 1] = base[1] + d; v[i * 3 + 2] = base[2]; });
    ch.push({ j: hips, n: 3, times: Float32Array.from(drop.times), vals: v });
  }
  return { name: c.name, ch, dur: c.duration, loop: c.loop !== undefined ? c.loop : true, speed: c.speed !== undefined ? c.speed : c.name === 'walk' ? 1.3 : 0, events: c.events || [] };
}
const tq = [0, 0, 0, 1], tq2 = [0, 0, 0, 1];
function sampleClip(clip, t, pose, w) {
  for (const c of clip.ch) {
    const T = c.times, n = T.length; let i = 0;
    if (t >= T[n - 1]) i = n - 2; else if (t > T[0]) { let lo = 0, hi = n - 1; while (hi - lo > 1) { const m = (lo + hi) >> 1; if (T[m] <= t) lo = m; else hi = m; } i = lo; }
    const i1 = Math.min(i + 1, n - 1), f = i1 === i ? 0 : Math.min(1, Math.max(0, (t - T[i]) / (T[i1] - T[i])));
    if (c.n === 4) {
      slerp(tq, c.vals.subarray(i * 4, i * 4 + 4), c.vals.subarray(i1 * 4, i1 * 4 + 4), f);
      const d = pose.r[c.j]; if (w >= 1) { d[0] = tq[0]; d[1] = tq[1]; d[2] = tq[2]; d[3] = tq[3]; } else { tq2[0] = d[0]; tq2[1] = d[1]; tq2[2] = d[2]; tq2[3] = d[3]; slerp(d, tq2, tq, w); }
    } else { const d = pose.t[c.j]; for (let k = 0; k < 3; k++) { const v = c.vals[i * 3 + k] * (1 - f) + c.vals[i1 * 3 + k] * f; d[k] = w >= 1 ? v : d[k] * (1 - w) + v * w; } }
  }
}

// ---------------------------------------------------------------- shaders
const VS_SRC = `#version 300 es
precision highp float; precision highp int; precision highp sampler2D;
layout(location=0) in vec3 a_pos; layout(location=1) in vec3 a_nrm; layout(location=2) in vec2 a_uv; layout(location=3) in vec4 a_jnt; layout(location=4) in vec4 a_wgt;
uniform sampler2D u_bones; uniform mat4 u_vp; uniform mat4 u_lvp; uniform int u_row;
out vec3 v_rel; out vec3 v_n; out vec2 v_uv; out vec4 v_ls;
mat4 bone(int j){ return mat4(texelFetch(u_bones, ivec2(j*4,u_row),0), texelFetch(u_bones, ivec2(j*4+1,u_row),0), texelFetch(u_bones, ivec2(j*4+2,u_row),0), texelFetch(u_bones, ivec2(j*4+3,u_row),0)); }
void main(){
  mat4 sk = bone(int(a_jnt.x)) * a_wgt.x + bone(int(a_jnt.y)) * a_wgt.y + bone(int(a_jnt.z)) * a_wgt.z + bone(int(a_jnt.w)) * a_wgt.w;
  vec4 w = sk * vec4(a_pos, 1.0);
  v_rel = w.xyz; v_n = normalize(mat3(sk) * a_nrm); v_uv = a_uv;
  v_ls = u_lvp * vec4(w.xyz + v_n * 0.03, 1.0);
  gl_Position = u_vp * w;
}`;
const FS_SRC = `#version 300 es
precision highp float; precision highp sampler2DShadow;
in vec3 v_rel; in vec3 v_n; in vec2 v_uv; in vec4 v_ls;
uniform sampler2D u_atlas; uniform sampler2DShadow u_shadow; uniform int u_shadows; uniform vec3 u_sun; uniform float u_fog; uniform int u_depthOnly;
out vec4 o;
vec3 aces(vec3 x){ return clamp((x*(2.51*x+0.03))/(x*(2.43*x+0.59)+0.14), 0.0, 1.0); }
void main(){
  if (u_depthOnly == 1) { o = vec4(1.0); return; }
  vec3 nw = normalize(v_n); float dist = length(v_rel);
  float shadow = 1.0;
  if (u_shadows == 1) {
    vec3 sc = v_ls.xyz / v_ls.w * 0.5 + 0.5;
    if (all(greaterThan(sc, vec3(0.0))) && all(lessThan(sc, vec3(1.0)))) {
      float s = 0.0; vec2 ts = vec2(1.0 / 2048.0);
      for (int j=-1;j<=1;j++) for (int i=-1;i<=1;i++) s += texture(u_shadow, vec3(sc.xy + vec2(i,j) * ts, sc.z - 0.0008));
      shadow = s / 9.0;
    }
  }
  vec3 alb = pow(texture(u_atlas, v_uv).rgb, vec3(2.2));
  float ndl = max(dot(nw, u_sun), 0.0);
  vec3 sky = mix(vec3(0.26, 0.22, 0.17), vec3(0.30, 0.42, 0.66), nw.y * 0.5 + 0.5);
  vec3 col = alb * (vec3(2.5, 2.2, 1.8) * ndl * shadow + sky * 0.8);
  vec3 vd = v_rel / max(dist, 1e-3);
  vec3 fogc = mix(vec3(0.52, 0.62, 0.76), vec3(0.95, 0.80, 0.60), pow(max(dot(vd, u_sun), 0.0), 6.0) * 0.6);
  col = mix(col, fogc, 1.0 - exp(-max(dist - 25.0, 0.0) * u_fog));
  col = aces(col * 0.9);
  float l = dot(col, vec3(0.2126, 0.7152, 0.0722));
  col = max(mix(vec3(l), col, 1.04), 0.0);
  col = pow(col, vec3(1.0/2.2));
  o = vec4(col * col * (3.0 - 2.0 * col) * 0.35 + col * 0.65, 1.0);
}`;

// ---------------------------------------------------------------- names (the player speaks English)
const FIRST_F = ['Agnes', 'Alice', 'Amice', 'Beatrix', 'Cecily', 'Edith', 'Emma', 'Isabel', 'Joan', 'Margery', 'Matilda', 'Rose', 'Sybil', 'Avice', 'Elena', 'Godith', 'Maud', 'Juliana'];
const FIRST_M = ['Adam', 'Alan', 'Geoffrey', 'Gilbert', 'Hugh', 'John', 'Nicholas', 'Ralph', 'Richard', 'Robert', 'Roger', 'Simon', 'Thomas', 'Walter', 'William', 'Osbert', 'Henry', 'Peter'];
const SURN = ['Atwood', 'Baker', 'Brewer', 'Carter', 'Cooper', 'Fletcher', 'Hayward', 'Mason', 'Miller', 'Smith', 'Thatcher', 'Webb', 'Wright', 'Hill', 'Brook', 'Green', 'Fuller', 'Turner'];
const GREET = ['Good day to you!', 'Well met, stranger.', 'Fair weather today.', 'Mind the cart, friend.', 'God keep you.', 'You are not from here, are you?'];

function start(G, roster, BASE) {
  const gl = G.gl, VS = G.VS, M = 1 / VS;
  const mk = (t, s) => { const sh = gl.createShader(t); gl.shaderSource(sh, s); gl.compileShader(sh); if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(sh)); return sh; };
  const prog = gl.createProgram(); gl.attachShader(prog, mk(gl.VERTEX_SHADER, VS_SRC)); gl.attachShader(prog, mk(gl.FRAGMENT_SHADER, FS_SRC)); gl.linkProgram(prog);
  if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(prog));
  const U = {}; for (const n of ['u_bones', 'u_vp', 'u_lvp', 'u_row', 'u_atlas', 'u_shadow', 'u_shadows', 'u_sun', 'u_fog', 'u_depthOnly']) U[n] = gl.getUniformLocation(prog, n);

  const JMAX = 64, W = JMAX * 4, ROWS = Math.max(1, roster.length);
  const boneTex = gl.createTexture(); gl.activeTexture(gl.TEXTURE7); gl.bindTexture(gl.TEXTURE_2D, boneTex);
  gl.texStorage2D(gl.TEXTURE_2D, 1, gl.RGBA32F, W, ROWS);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
  const boneData = new Float32Array(W * 4 * ROWS);
  const stats = { gpuBytes: 0, tris: 0, ready: 0, genMs: 0 };

  function upload(mesh) {
    const prevVao = gl.getParameter(gl.VERTEX_ARRAY_BINDING), prevBuf = gl.getParameter(gl.ARRAY_BUFFER_BINDING), prevTex = gl.getParameter(gl.ACTIVE_TEXTURE);
    const vao = gl.createVertexArray(); gl.bindVertexArray(vao);
    const vb = (data, loc, n) => { const b = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, b); gl.bufferData(gl.ARRAY_BUFFER, data, gl.STATIC_DRAW); gl.enableVertexAttribArray(loc); gl.vertexAttribPointer(loc, n, gl.FLOAT, false, 0, 0); stats.gpuBytes += data.byteLength; };
    vb(mesh.positions, 0, 3); vb(mesh.normals, 1, 3); vb(mesh.uvs, 2, 2); vb(mesh.joints, 3, 4); vb(mesh.weights, 4, 4);
    const e = gl.createBuffer(); gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, e); gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, mesh.indices, gl.STATIC_DRAW); stats.gpuBytes += mesh.indices.byteLength;
    gl.bindVertexArray(prevVao);
    const tex = gl.createTexture(); gl.activeTexture(gl.TEXTURE6); gl.bindTexture(gl.TEXTURE_2D, tex);
    gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA8, mesh.atlas.w, mesh.atlas.h, 0, gl.RGBA, gl.UNSIGNED_BYTE, mesh.atlas.data);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    stats.gpuBytes += mesh.atlas.w * mesh.atlas.h * 4;
    gl.bindBuffer(gl.ARRAY_BUFFER, prevBuf); gl.activeTexture(prevTex);
    return { vao, tex, count: mesh.indices.length };
  }

  // ---- spawn points on walkable ground
  const R = rng(SEED ^ 0x51ED);
  const pick = (a) => a[(R() * a.length) | 0];
  const groundAt = (vx, vz, fromY) => { const x = Math.floor(vx), z = Math.floor(vz); for (let y = Math.floor(fromY); y > fromY - 2.5 * M; y--) if (G.solid(x, y, z)) return y + 1; return null; };
  const clear = (vx, vy, vz) => !G.solid(Math.floor(vx), Math.floor(vy + 0.5 * M), Math.floor(vz)) && !G.solid(Math.floor(vx), Math.floor(vy + 1.3 * M), Math.floor(vz));
  const outdoors = (vx, vy, vz) => { for (const h of [2.2, 3.2, 4.5]) if (G.solid(Math.floor(vx), Math.floor(vy + h * M), Math.floor(vz))) return false; return true; };
  const anchors = G.instances.filter((i) => /door/i.test(i.mod && i.mod.name || '')).map((i) => [i.cx * M, i.cz * M]);
  const randomSpot = () => {
    for (let tries = 0; tries < 40; tries++) {
      let x, z;
      if (anchors.length && R() < 0.6) { const a = pick(anchors), ang = R() * 6.283, d = (1.5 + R() * 5) * M; x = a[0] + Math.cos(ang) * d; z = a[1] + Math.sin(ang) * d; }
      else { const ang = R() * 6.283, d = Math.sqrt(R()) * 45 * M; x = G.CX + Math.cos(ang) * d; z = G.CZ + Math.sin(ang) * d; }
      const y = groundAt(x, z, G.heightAt(x | 0, z | 0) + 0.6 * M);
      if (y !== null && clear(x, y, z) && outdoors(x, y, z)) return [x, y, z];
    }
    return null;
  };

  const npcs = [];
  for (const rec of roster) {
    const s = randomSpot(); if (!s) continue;
    const ap = rec.appearance || {}, nr = rng(rec.seed), female = ap.sex === 'f';
    npcs.push({
      id: rec.id, seed: rec.seed, row: npcs.length, rec, name: `${(female ? FIRST_F : FIRST_M)[(nr() * 18) | 0]} ${SURN[(nr() * 18) | 0]}`,
      job: rec.job, age: ap.ageClass || 'adult', height: ap.height || 1.7,
      x: s[0], y: s[1], z: s[2], yaw: R() * 6.283,
      state: 'idle', timer: 1 + R() * 4, target: null, partner: null, clip: 'idle', t: R() * 3, prev: null, prevT: 0, blend: 1,
      outfit: rec.worn || 'everyday', wantOutfit: rec.worn || 'everyday', meshes: {}, skel: null, clips: null, pose: null,
    });
  }

  // ---- generation workers (CPU only; the GPU stays free)
  const NW = Math.max(1, Math.min(4, (navigator.hardwareConcurrency || 4) - 1));
  const queue = [], pending = new Map(), workers = [];
  let workerFailed = null;
  for (let k = 0; k < NW; k++) {
    const w = new Worker('villager_worker.js', { type: 'module' }); w.busy = false; workers.push(w);
    w.postMessage({ base: BASE, origin: location.href });
    w.onerror = (e) => { workerFailed = e.message || 'worker error'; console.error('villager worker', e.message); };
    w.onmessage = (e) => { w.busy = false; onMesh(e.data); pump(); };
  }
  const request = (n, outfit, lod, prio) => {
    const key = n.seed + '/' + outfit + '/' + lod;
    if (pending.has(key) || (n.meshes[outfit] && n.meshes[outfit][lod])) return;
    pending.set(key, 0); const q = { seed: n.seed, village: n.rec.village, outfit, lod };
    if (prio) queue.unshift(q); else queue.push(q);
  };
  function pump() { for (const w of workers) { if (w.busy || !queue.length) continue; const q = queue.shift(); w.busy = true; pending.set(q.seed + '/' + q.outfit + '/' + q.lod, performance.now()); w.postMessage(q); } }
  const bySeed = new Map(npcs.map((n) => [n.seed, n]));
  function onMesh(d) {
    const key = d.seed + '/' + d.outfit + '/' + d.lod, t0 = pending.get(key); pending.delete(key);
    if (d.error) { console.error('villager', d.seed, d.error); workerFailed = workerFailed || 'génération'; return; }
    const n = bySeed.get(d.seed); if (!n) return;
    if (d.skel && !n.skel) {
      const index = {}; d.skel.names.forEach((nm, i) => { index[nm] = i; });
      const par = d.skel.parents, H = d.skel.heads, J = H.length;
      const rest = H.map((h, i) => { const p = par[i] >= 0 ? H[par[i]] : [0, 0, 0]; return [h[0] - p[0], h[1] - p[1], h[2] - p[2]]; });
      const ibm = new Float32Array(J * 16); H.forEach((h, i) => { const o = i * 16; ibm[o] = ibm[o + 5] = ibm[o + 10] = ibm[o + 15] = 1; ibm[o + 12] = -h[0]; ibm[o + 13] = -h[1]; ibm[o + 14] = -h[2]; });
      const order = [], seen = new Uint8Array(J); const visit = (j) => { if (seen[j]) return; if (par[j] >= 0) visit(par[j]); seen[j] = 1; order.push(j); }; for (let j = 0; j < J; j++) visit(j);
      n.skel = { index, parents: par, rest, ibm, order, J, local: rest.map(() => new Float32Array(16)), global: rest.map(() => new Float32Array(16)) };
      n.clips = {}; for (const c of d.clips) n.clips[c.name] = bindClip(n.skel, c);
      for (const c of extraClips(d.bp.height)) if (!n.clips[c.name]) n.clips[c.name] = bindClip(n.skel, c);
      n.pose = { t: rest.map((r) => r.slice()), r: rest.map(() => [0, 0, 0, 1]) };
      if (d.job) n.job = d.job;
      if (t0) { stats.genMs += performance.now() - t0; }
      stats.ready++;
    }
    (n.meshes[d.outfit] ??= {})[d.lod] = upload(d.mesh);
    stats.tris += d.mesh.indices.length / 3;
  }
  // far LOD for everyone first (nearest first); the near LOD is requested on approach
  const P0 = G.player;
  npcs.slice().sort((a, b) => Math.hypot(a.x - P0.x, a.z - P0.z) - Math.hypot(b.x - P0.x, b.z - P0.z)).forEach((n) => request(n, n.outfit, 2));
  pump();

  const play = (n, c) => { if (!n.clips[c]) c = 'idle'; if (n.clip === c) return; n.prev = n.clip; n.prevT = n.t; n.clip = c; n.t = 0; n.blend = 0; };
  const say = new Map();
  const turnTo = (a, b, k) => { let d = b - a; while (d > Math.PI) d -= 6.283185; while (d < -Math.PI) d += 6.283185; return a + Math.max(-k, Math.min(k, d)); };
  const setOutfit = (n, o) => { n.wantOutfit = o; if (!(n.meshes[o] && n.meshes[o][2])) request(n, o, 2, true); };

  // ---- behaviour (stand-in for the decision engine: go_to, chat, work, rest, greet, dress)
  function think(n, dt, now, player) {
    n.timer -= dt;
    const pdx = player.x - n.x, pdz = player.z - n.z, pd = Math.hypot(pdx, pdz) * VS;
    if (n.state !== 'greet' && pd < 2.2 && n.state !== 'sit' && n.state !== 'talk' && !n.greeted) {
      n.state = 'greet'; n.timer = 1.6; n.greeted = true; play(n, 'wave'); say.set(n.id, { text: GREET[(n.seed >>> 3) % GREET.length], until: now + 3000 });
    }
    if (pd > 6) n.greeted = false;
    switch (n.state) {
      case 'greet': n.yaw = turnTo(n.yaw, Math.atan2(pdx, pdz), dt * 6); if (n.timer <= 0) { n.state = 'idle'; n.timer = 1 + R() * 2; play(n, 'idle'); } return 0;
      case 'walk': {
        const dx = n.target[0] - n.x, dz = n.target[2] - n.z, d = Math.hypot(dx, dz);
        if (d < 0.4 * M || n.timer <= 0) { n.state = 'idle'; n.timer = 2 + R() * 5; play(n, 'idle'); return 0; }
        n.yaw = turnTo(n.yaw, Math.atan2(dx, dz), dt * 4);
        return n.run ? 3.2 : n.age === 'elder' ? 0.9 : n.age === 'child' ? 1.1 : 1.3;
      }
      case 'talk': if (n.partner) n.yaw = turnTo(n.yaw, Math.atan2(n.partner.x - n.x, n.partner.z - n.z), dt * 4);
        if (n.timer <= 0) { n.state = 'idle'; n.timer = 1 + R() * 3; n.partner = null; play(n, 'idle'); } return 0;
      case 'work': if (n.timer <= 0) { n.state = 'idle'; n.timer = 1 + R() * 2; play(n, 'idle'); setOutfit(n, n.rec.worn || 'everyday'); } return 0;
      case 'sit': if (n.timer <= 0) { n.state = 'idle'; n.timer = 1 + R() * 2; play(n, 'idle'); } return 0;
      default: {
        if (n.timer > 0) return 0;
        const r = R();
        if (r < 0.48) { const s = randomSpot(); if (s) { n.target = s; n.state = 'walk'; n.run = n.age === 'child' ? R() < 0.4 : R() < 0.08; n.timer = 40; play(n, n.run ? 'run' : 'walk'); } }
        else if (r < 0.68) {
          let best = null, bd = 3.5 * M;
          for (const m of npcs) if (m !== n && m.skel && m.state === 'idle') { const d = Math.hypot(m.x - n.x, m.z - n.z); if (d < bd) { bd = d; best = m; } }
          if (best) for (const [a, b] of [[n, best], [best, n]]) { a.state = 'talk'; a.partner = b; a.timer = 4 + R() * 4; play(a, a.clips.talk ? 'talk' : 'talk_calm'); }
          else n.timer = 1;
        } else if (r < 0.84 && n.age !== 'child' && n.age !== 'teen' && n.job !== 'elder') { n.state = 'work'; n.timer = 6 + R() * 8; play(n, n.clips.work ? 'work' : 'swing_axe'); setOutfit(n, 'work'); }
        else if (r < 0.93) { n.state = 'sit'; n.timer = 6 + R() * 8; play(n, 'sit_idle'); }
        else n.timer = 1 + R() * 3;
        return 0;
      }
    }
  }
  function move(n, speed, dt) {
    if (speed <= 0) return;
    const step = speed * dt * M, nx = n.x + Math.sin(n.yaw) * step, nz = n.z + Math.cos(n.yaw) * step;
    const gy = groundAt(nx, nz, n.y + 0.45 * M);
    if (gy === null || gy < n.y - 1.2 * M || !clear(nx, gy, nz)) { n.state = 'idle'; n.timer = 0.3; play(n, 'idle'); return; }
    n.x = nx; n.z = nz; n.y += (gy - n.y) * Math.min(1, dt * 12);
  }

  // ---- animation -> bone texture rows (camera-relative)
  const world = new Float32Array(16), tmp = new Float32Array(16), tmp2 = new Float32Array(16);
  function animate(n, cam) {
    const S = n.skel, p = n.pose;
    for (let j = 0; j < S.J; j++) { const r = S.rest[j], t = p.t[j], q = p.r[j]; t[0] = r[0]; t[1] = r[1]; t[2] = r[2]; q[0] = q[1] = q[2] = 0; q[3] = 1; }
    const c = n.clips[n.clip] || n.clips.idle, pc = n.prev && n.blend < 1 ? n.clips[n.prev] : null;
    if (pc) sampleClip(pc, pc.loop ? n.prevT % pc.dur : Math.min(n.prevT, pc.dur), p, 1);
    if (c) sampleClip(c, c.loop ? n.t % c.dur : Math.min(n.t, c.dur), p, pc ? Math.max(0, n.blend) : 1);
    for (const j of S.order) { trs(S.local[j], p.t[j], p.r[j]); const pj = S.parents[j]; if (pj >= 0) mulTo(S.global[j], S.global[pj], S.local[j]); else S.global[j].set(S.local[j]); }
    const cy = Math.cos(n.yaw), sy = Math.sin(n.yaw);
    world[0] = cy; world[1] = 0; world[2] = -sy; world[3] = 0; world[4] = 0; world[5] = 1; world[6] = 0; world[7] = 0;
    world[8] = sy; world[9] = 0; world[10] = cy; world[11] = 0; world[12] = n.x * VS - cam[0]; world[13] = n.y * VS - cam[1]; world[14] = n.z * VS - cam[2]; world[15] = 1;
    const base = n.row * W * 4;
    for (let j = 0; j < S.J; j++) { mulTo(tmp, S.global[j], S.ibm.subarray(j * 16, j * 16 + 16)); mulTo(tmp2, world, tmp); boneData.set(tmp2, base + j * 16); }
  }

  // ---- HUD: name under the crosshair, villager stats
  const label = document.createElement('div');
  label.style.cssText = 'position:fixed;left:50%;top:calc(50% + 22px);transform:translateX(-50%);background:rgba(14,17,22,.72);color:#e8e4da;padding:4px 10px;border-radius:6px;font:13px system-ui,sans-serif;pointer-events:none;display:none;text-align:center;max-width:calc(100vw - 32px)';
  document.body.appendChild(label);
  const info = document.getElementById('info'); let infoEl = null;
  if (info) { info.insertAdjacentHTML('beforeend', '<br><span id="vinfo"></span>'); infoEl = document.getElementById('vinfo'); }
  const ACT = { idle: 'resting', walk: 'walking', talk: 'chatting', work: 'working', sit: 'sitting', greet: 'greeting you' };
  const JOB = (j) => j && j !== 'child' && j !== 'elder' ? j.replace(/_/g, ' ') : null;

  let last = 0, needAnim = false, infoT = 0, drawn = { n: 0, tris: 0 };
  G.addUpdate((dt, now) => {
    needAnim = true; last = now;
    const P = G.player, cam = G.cam;
    for (const n of npcs) {
      if (!n.skel) continue;
      const sp = think(n, dt, now, P);
      move(n, sp, dt);
      const c = n.clips[n.clip], rate = c && c.speed > 0 && sp > 0 ? sp / c.speed : 1;
      n.t += dt * rate; n.prevT += dt; n.blend += dt * 5;
      if (n.wantOutfit !== n.outfit && n.meshes[n.wantOutfit] && n.meshes[n.wantOutfit][2]) n.outfit = n.wantOutfit;
      const d = Math.hypot(n.x * VS - cam[0], n.z * VS - cam[2]);
      if (d < LOD_NEAR_M * 1.5 && !(n.meshes[n.outfit] && n.meshes[n.outfit][1])) request(n, n.outfit, 1);
    }
    pump();
    for (let i = 0; i < npcs.length; i++) for (let k = i + 1; k < npcs.length; k++) {
      const a = npcs[i], b = npcs[k], dx = b.x - a.x, dz = b.z - a.z, d = Math.hypot(dx, dz), m = 0.45 * M;
      if (d > 0 && d < m) { const push = (m - d) / 2 / d; a.x -= dx * push; a.z -= dz * push; b.x += dx * push; b.z += dz * push; }
    }
    let best = null, bd = 1e9;
    for (const n of npcs) {
      if (!n.skel) continue;
      const dx = n.x * VS - cam[0], dz = n.z * VS - cam[2], d = Math.hypot(dx, dz);
      if (d > 6) continue;
      let da = Math.atan2(-dx, -dz) - P.yaw; while (da > Math.PI) da -= 6.283; while (da < -Math.PI) da += 6.283;
      if (Math.abs(da) < Math.max(0.12, 0.35 / d) && d < bd) { bd = d; best = n; }
    }
    const s = best && say.get(best.id);
    if (best) { const job = JOB(best.job); label.style.display = 'block'; label.innerHTML = `<b>${best.name}</b>${job ? ', ' + job : best.age === 'child' ? ', child' : ''} · ${ACT[best.state] || best.state}` + (s && s.until > now ? `<br><i>“${s.text}”</i>` : ''); }
    else label.style.display = 'none';
    if (infoEl && now - infoT > 1000) {
      infoT = now;
      infoEl.innerHTML = `<b>Villageois :</b> ${stats.ready}/${npcs.length} générés (${NW} workers, ${stats.ready ? (stats.genMs / stats.ready).toFixed(0) + ' ms chacun' : '…'}) · ${drawn.n} dessinés, ${(drawn.tris / 1000).toFixed(0)} k triangles · ${(stats.gpuBytes / 1048576).toFixed(1)} Mo GPU` + (workerFailed ? ` · <b>erreur</b> ${workerFailed}` : '');
    }
  });

  G.addDrawHook((gl_, shadowPass, vp, lvp, cam, SUN) => {
    if (needAnim) {
      needAnim = false;
      let rows = 0;
      for (const n of npcs) {
        if (!n.skel) continue;
        const d = Math.hypot(n.x * VS - cam[0], n.z * VS - cam[2]);
        n.dist = d; if (d > DRAW_MAX_M) continue;
        if (d > 25 && last - (n.lastAnim || 0) < 100 && n.lastCam) {   // far: 10 Hz animation, re-centred every frame
          const base = n.row * W * 4, ox = n.lastCam[0] - cam[0], oy = n.lastCam[1] - cam[1], oz = n.lastCam[2] - cam[2];
          for (let j = 0; j < n.skel.J; j++) { boneData[base + j * 16 + 12] += ox; boneData[base + j * 16 + 13] += oy; boneData[base + j * 16 + 14] += oz; }
        } else { animate(n, cam); n.lastAnim = last; }
        n.lastCam = cam; rows = Math.max(rows, n.row + 1);
      }
      if (rows) { gl.activeTexture(gl.TEXTURE7); gl.bindTexture(gl.TEXTURE_2D, boneTex); gl.texSubImage2D(gl.TEXTURE_2D, 0, 0, 0, W, rows, gl.RGBA, gl.FLOAT, boneData, 0); }
    }
    const prevProg = gl.getParameter(gl.CURRENT_PROGRAM), prevVao = gl.getParameter(gl.VERTEX_ARRAY_BINDING), prevBuf = gl.getParameter(gl.ARRAY_BUFFER_BINDING), prevTex = gl.getParameter(gl.ACTIVE_TEXTURE);
    gl.useProgram(prog);
    gl.activeTexture(gl.TEXTURE7); gl.bindTexture(gl.TEXTURE_2D, boneTex);
    gl.uniform1i(U.u_bones, 7); gl.uniform1i(U.u_shadow, 3); gl.uniform1i(U.u_atlas, 6);
    gl.uniformMatrix4fv(U.u_vp, false, vp); gl.uniformMatrix4fv(U.u_lvp, false, lvp);
    gl.uniform1i(U.u_shadows, !shadowPass && G.Q.shadows ? 1 : 0); gl.uniform3fv(U.u_sun, SUN); gl.uniform1f(U.u_fog, 0.0022);
    gl.uniform1i(U.u_depthOnly, shadowPass ? 1 : 0);
    gl.activeTexture(gl.TEXTURE6);
    let cnt = 0, tris = 0;
    for (const n of npcs) {
      if (!n.skel || !(n.dist <= DRAW_MAX_M) || (shadowPass && n.dist > 45)) continue;
      const set = n.meshes[n.outfit]; if (!set) continue;
      const m = (n.dist < LOD_NEAR_M && set[1]) || set[2] || set[1]; if (!m) continue;
      gl.bindTexture(gl.TEXTURE_2D, m.tex); gl.uniform1i(U.u_row, n.row);
      gl.bindVertexArray(m.vao); gl.drawElements(gl.TRIANGLES, m.count, gl.UNSIGNED_INT, 0);
      cnt++; tris += m.count / 3;
    }
    if (!shadowPass) drawn = { n: cnt, tris };
    gl.bindVertexArray(prevVao); gl.useProgram(prevProg); gl.bindBuffer(gl.ARRAY_BUFFER, prevBuf); gl.activeTexture(prevTex);
  });
  window.__villagers = { npcs, stats, get drawn() { return drawn; } };
  console.log(`villagers: ${npcs.length} villageois du village « ${VILLAGE} », ${NW} workers`);
}

// ---------------------------------------------------------------- boot
async function init() {
  const G = window.__game;
  if (!G || !G.addDrawHook || !G.addUpdate || !G.gl || !G.solid) { console.warn('villagers.js : engine.js n’expose pas les crochets (addDrawHook, addUpdate, gl, solid, VS).'); return; }
  try {
    // the generator sits next to the page (published build) or in the repository's characters/ folder
    let BASE = null, all = null;
    for (const b of [QS.get('characters'), 'personnages/', '../../../characters/'].filter(Boolean)) {
      try { const r = await fetch(b + 'data/villagers.json'); if (r.ok) { all = (await r.json()).villagers; BASE = b; break; } } catch (e) { /* next */ }
    }
    if (!all) { console.warn('villagers.js : générateur de villageois introuvable (personnages/ ou ../../../characters/).'); return; }
    const pool = all.filter((v) => v.village === VILLAGE);
    const r = rng(SEED ^ 0xBEEF), roster = pool.slice();      // deterministic subset of the village
    for (let i = roster.length - 1; i > 0; i--) { const j = (r() * (i + 1)) | 0; [roster[i], roster[j]] = [roster[j], roster[i]]; }
    start(G, roster.slice(0, N_NPC), BASE);
  } catch (e) { console.error('villagers.js :', e); }
}
if (window.__game) init(); else window.addEventListener('village-ready', init, { once: true });
})();
