// engine.js — prototype « Village voxel » : rendu WebGL2, LOD, destruction, collisions.
'use strict';
(async function () {
const VS = VX.VS, SEED = 1337;
const $ = (id) => document.getElementById(id);
const status = (t) => { $('loadmsg').textContent = t; };
const T0 = performance.now();

// ======================= GL setup =======================
const canvas = $('c');
const gl = canvas.getContext('webgl2', { antialias: false, powerPreference: 'low-power', depth: true, stencil: false });
if (!gl) { status('WebGL2 indisponible sur ce navigateur.'); return; }
const dbg = gl.getExtension('WEBGL_debug_renderer_info');
const GPU_NAME = dbg ? gl.getParameter(dbg.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER);
const tq = gl.getExtension('EXT_disjoint_timer_query_webgl2');

const Q = { scale: 1.0, shadows: true, ao: true, dist: 1.0 };   // quality settings
const QS = new URLSearchParams(location.search); if (QS.get('scale')) Q.scale = +QS.get('scale');
const MEM = { atlas: 0, indir: 0, vbo: 0, shadow: 0, idx: 0 };

function sh(type, src) {
  const s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s);
  if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s) + '\n' + src.split('\n').map((l, i) => (i + 1) + ': ' + l).join('\n'));
  return s;
}
function prog(vs, fs) {
  const p = gl.createProgram(); gl.attachShader(p, sh(gl.VERTEX_SHADER, vs)); gl.attachShader(p, sh(gl.FRAGMENT_SHADER, fs));
  gl.bindAttribLocation(p, 0, 'a_pos'); gl.bindAttribLocation(p, 1, 'a_fc'); gl.bindAttribLocation(p, 2, 'a_inst');
  gl.linkProgram(p);
  if (!gl.getProgramParameter(p, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(p));
  const u = {}; const n = gl.getProgramParameter(p, gl.ACTIVE_UNIFORMS);
  for (let i = 0; i < n; i++) { const a = gl.getActiveUniform(p, i); u[a.name.replace('[0]', '')] = gl.getUniformLocation(p, a.name); }
  return { p, u };
}

const VERT = `#version 300 es
precision highp float; precision highp int;
layout(location=0) in vec3 a_pos; layout(location=1) in vec2 a_fc; layout(location=2) in vec4 a_inst;
uniform mat4 u_vp; uniform mat4 u_lvp; uniform vec3 u_cam; uniform float u_vs;
out vec3 v_local; out vec3 v_rel; out vec4 v_ls; flat out int v_face; flat out int v_cls; flat out vec4 v_inst;
const vec3 NRM[6] = vec3[6](vec3(1,0,0),vec3(-1,0,0),vec3(0,1,0),vec3(0,-1,0),vec3(0,0,1),vec3(0,0,-1));
vec3 rot(vec3 p, int r){ if(r==1) return vec3(p.z,p.y,-p.x); if(r==2) return vec3(-p.x,p.y,-p.z); if(r==3) return vec3(-p.z,p.y,p.x); return p; }
void main(){
  int r = int(a_inst.w + 0.5);
  v_local = a_pos; v_face = int(a_fc.x + 0.5); v_cls = int(a_fc.y + 0.5); v_inst = a_inst;
  vec3 w = (rot(a_pos, r) + a_inst.xyz) * u_vs - u_cam;
  v_rel = w;
  vec3 nw = rot(NRM[v_face], r);
  v_ls = u_lvp * vec4(w + nw * 0.035, 1.0);
  gl_Position = u_vp * vec4(w, 1.0);
}`;

const FRAG_SRC = `
precision highp float; precision highp int; precision highp usampler3D; precision highp usampler2D; precision highp sampler2DShadow;
in vec3 v_local; in vec3 v_rel; in vec4 v_ls; flat in int v_face; flat in int v_cls; flat in vec4 v_inst;
uniform usampler3D u_atlas; uniform usampler2D u_indir; uniform usampler2D u_bpal; uniform sampler2D u_pal; uniform sampler2DShadow u_shadow;
uniform ivec3 u_nb; uniform ivec3 u_mmin; uniform ivec3 u_mdim; uniform int u_base; uniform int u_mode; uniform int u_lodstep;
uniform int u_ao; uniform int u_shadows; uniform vec3 u_sun; uniform vec3 u_sunCol; uniform float u_fog;
uniform mat4 u_vp; uniform mat4 u_lvp; uniform vec3 u_cam; uniform vec3 u_camvox; uniform float u_vs;
out vec4 o;
const vec3 NRM[6] = vec3[6](vec3(1,0,0),vec3(-1,0,0),vec3(0,1,0),vec3(0,-1,0),vec3(0,0,1),vec3(0,0,-1));
vec3 rot(vec3 p, int r){ if(r==1) return vec3(p.z,p.y,-p.x); if(r==2) return vec3(-p.x,p.y,-p.z); if(r==3) return vec3(-p.z,p.y,p.x); return p; }
uint hash3(ivec3 p){ uint h = uint(p.x)*0x8da6b343u ^ uint(p.y)*0xd8163841u ^ uint(p.z)*0xcb1ab31fu; h ^= h>>16; h *= 0x7feb352du; h ^= h>>15; h*=0x846ca68bu; h^=h>>16; return h; }
float h01(ivec3 p){ return float(hash3(p) & 0xffffu) / 65535.0; }
uint fetchId(ivec3 v){
  v -= u_mmin;
  if (any(lessThan(v, ivec3(0))) || any(greaterThanEqual(v, u_mdim))) return 0u;
  ivec3 b = v >> 3; int idx = u_base + b.x + u_nb.x * (b.y + u_nb.y * b.z);
  uint e = texelFetch(u_indir, ivec2(idx & 2047, idx >> 11), 0).r;
  if (e == 0u) return 0u;
  if ((e & 0x80000000u) != 0u) return e & 0xffffu;
  int s = int(e) - 1; ivec3 l = v & 7;
  uint byt = texelFetch(u_atlas, ivec3((s & 127) * 4 + (l.x >> 1), ((s >> 7) & 63) * 8 + l.y, (s >> 13) * 8 + l.z), 0).r;
  uint pi = (l.x & 1) == 1 ? (byt >> 4) : (byt & 15u);
  if (pi == 0u) return 0u;
  return texelFetch(u_bpal, ivec2((s & 127) * 16 + int(pi), s >> 7), 0).r;
}
float solid(ivec3 v){ return fetchId(v) != 0u ? 1.0 : 0.0; }
float vao(float s1, float s2, float c){ return (s1 > 0.5 && s2 > 0.5) ? 0.0 : (3.0 - s1 - s2 - c) / 3.0; }
vec3 srgb(vec3 c){ return pow(c, vec3(2.2)); }
vec3 aces(vec3 x){ return clamp((x*(2.51*x+0.03))/(x*(2.43*x+0.59)+0.14), 0.0, 1.0); }
float cobble(ivec3 v, out float stoneId){
  vec2 p = vec2(v.xz) / 13.0; vec2 ip = floor(p); vec2 fp = fract(p);
  float d1 = 9.0, d2 = 9.0; stoneId = 0.0;
  for (int j=-1;j<=1;j++) for (int i=-1;i<=1;i++){
    vec2 g = vec2(i,j); ivec3 c = ivec3(ip + g, 0).xzy;
    vec2 r = g + vec2(h01(c), h01(c + ivec3(7,0,3))) * 0.8 + 0.1 - fp;
    float d = dot(r,r);
    if (d < d1){ d2 = d1; d1 = d; stoneId = h01(c + ivec3(1,0,1)); } else if (d < d2) d2 = d;
  }
  return sqrt(d2) - sqrt(d1);
}
float vnz(vec2 p){ ivec2 i = ivec2(floor(p)); vec2 f = fract(p); f = f * f * (3.0 - 2.0 * f);
  float a = h01(ivec3(i, 5).xzy), b = h01(ivec3(i + ivec2(1, 0), 5).xzy), c = h01(ivec3(i + ivec2(0, 1), 5).xzy), d = h01(ivec3(i + ivec2(1, 1), 5).xzy);
  return mix(mix(a, b, f.x), mix(c, d, f.x), f.y); }
float voxAO(ivec3 v, vec3 n, vec3 hitLocal){
  ivec3 N = ivec3(n);
  ivec3 T1 = n.x != 0.0 ? ivec3(0,1,0) : ivec3(1,0,0);
  ivec3 T2 = n.z != 0.0 ? ivec3(0,1,0) : ivec3(0,0,1);
  ivec3 q = v + N;
  float a = solid(q + T1), b = solid(q - T1), c = solid(q + T2), d = solid(q - T2);
  float ac = solid(q + T1 + T2), bc = solid(q - T1 + T2), ad = solid(q + T1 - T2), bd = solid(q - T1 - T2);
  vec3 f3 = clamp(hitLocal - vec3(v), 0.0, 1.0); vec2 f = vec2(dot(f3, vec3(T1)), dot(f3, vec3(T2)));
  float o00 = vao(b, d, bd), o10 = vao(a, d, ad), o01 = vao(b, c, bc), o11 = vao(a, c, ac);
  return 0.42 + 0.58 * mix(mix(o00, o10, f.x), mix(o01, o11, f.x), f.y);
}
vec3 light(vec3 alb, vec3 nw, vec3 rel, vec4 ls, float ao){
  float dist = length(rel);
  float shadow = 1.0;
  if (u_shadows == 1) {
    vec3 sc = ls.xyz / ls.w * 0.5 + 0.5;
    if (all(greaterThan(sc, vec3(0.0))) && all(lessThan(sc, vec3(1.0)))) {
      float s = 0.0; vec2 ts = vec2(1.0 / 2048.0);
      for (int j=-1;j<=1;j++) for (int i=-1;i<=1;i++) s += texture(u_shadow, vec3(sc.xy + vec2(i,j) * ts, sc.z - 0.0008));
      shadow = s / 9.0;
    }
  }
  float ndl = max(dot(nw, u_sun), 0.0);
  vec3 sky = mix(vec3(0.26, 0.22, 0.17), vec3(0.30, 0.42, 0.66), nw.y * 0.5 + 0.5);
  vec3 col = alb * (u_sunCol * ndl * shadow + sky * 0.75 * ao);
  vec3 vd = rel / max(dist, 1e-3);
  vec3 fogc = mix(vec3(0.52, 0.62, 0.76), vec3(0.95, 0.80, 0.60), pow(max(dot(vd, u_sun), 0.0), 6.0) * 0.6);
  col = mix(col, fogc, 1.0 - exp(-max(dist - 25.0, 0.0) * u_fog));
  col = aces(col * 0.9);
  float l = dot(col, vec3(0.2126, 0.7152, 0.0722));
  col = max(mix(vec3(l), col, 1.04), 0.0);                    // grade: a touch more saturation
  col = pow(col, vec3(1.0/2.2));
  return col * col * (3.0 - 2.0 * col) * 0.35 + col * 0.65;  // soft S-curve
}
float edgeDark(vec3 hitLocal, vec3 n, float dist){
  vec3 fl = fract(hitLocal); vec3 e3 = min(fl, 1.0 - fl);
  float em = n.x != 0.0 ? min(e3.y, e3.z) : n.y != 0.0 ? min(e3.x, e3.z) : min(e3.x, e3.y);
  float edge = mix(0.88, 1.0, smoothstep(0.0, 0.14, em));
  return mix(edge, 1.0, smoothstep(3.0, 9.0, dist));
}
void main(){
  int r = int(v_inst.w + 0.5);
  vec3 n = NRM[v_face];
#ifdef TRACE
  // ---- micro-trace: the rasterized face belongs to an 8 cm micro-brick; find the 2 cm voxel the ray hits
  vec3 camL = rot(u_camvox - v_inst.xyz, (4 - r) & 3);
  vec3 d = normalize(v_local - camL);
  d = mix(d, vec3(1e-5), lessThan(abs(d), vec3(1e-5)));
  vec3 p = v_local + d * 0.002;
  ivec3 v = ivec3(floor(p));
  vec3 sv = sign(d); ivec3 st = ivec3(sv);
  vec3 tD = abs(1.0 / d);
  vec3 tM = (sv * (vec3(v) - p) + max(sv, vec3(0.0))) * tD;
  vec3 nl = n; float t = 0.0; uint id = 0u;
  for (int i = 0; i < 40; i++) {
    id = fetchId(v); if (id != 0u) break;
    if (tM.x < tM.y && tM.x < tM.z) { t = tM.x; tM.x += tD.x; v.x += st.x; nl = vec3(-sv.x, 0.0, 0.0); }
    else if (tM.y < tM.z) { t = tM.y; tM.y += tD.y; v.y += st.y; nl = vec3(0.0, -sv.y, 0.0); }
    else { t = tM.z; tM.z += tD.z; v.z += st.z; nl = vec3(0.0, 0.0, -sv.z); }
  }
  if (id == 0u) discard;
  vec3 hit = p + d * t;
  vec3 nw = rot(nl, r);
  vec3 rel = (rot(hit, r) + v_inst.xyz) * u_vs - u_cam;
  vec4 clip = u_vp * vec4(rel, 1.0);
  gl_FragDepth = clip.z / clip.w * 0.5 + 0.5;
  int cls = int(id >> 7), tint = int(id & 127u);
  float ao = u_ao == 1 ? voxAO(v, nl, hit) : 1.0;
  ivec3 wv = ivec3(floor(rot(vec3(v) + 0.5, r) + v_inst.xyz));
  vec3 alb = srgb(texelFetch(u_pal, ivec2(tint, cls), 0).rgb) * (0.93 + 0.14 * h01(wv));
  float dist = length(rel);
  vec4 ls = u_lvp * vec4(rel + nw * 0.06, 1.0);
  o = vec4(light(alb * edgeDark(hit, nl, dist), nw, rel, ls, ao), 1.0);
#else
  vec3 p = v_local - n * 0.5;
  ivec3 v = ivec3(floor(p));
  int cls = v_cls, tint = 64; float jitter;
  ivec3 wv = ivec3(floor(rot(p, r) + v_inst.xyz));
  if (u_mode == 0) {
    // coarse raster LOD: look inward for the real 2 cm voxel colour
    uint id = 0u;
    for (int i = 0; i < 8; i++) { if (i >= u_lodstep) break; id = fetchId(ivec3(floor(v_local - n * (0.5 + float(i) * max(1.0, float(u_lodstep) / 8.0))))); if (id != 0u) break; }
    if (id != 0u) { cls = int(id >> 7); tint = int(id & 127u); }
    jitter = 0.95 + 0.1 * h01(wv);
  } else {
    float dist = length(v_rel);
    float h = h01(wv);
    float pch = vnz(vec2(wv.xz) / 55.0) * 0.55 + vnz(vec2(wv.xz) / 260.0 + 17.0) * 0.45;
    tint = int(clamp(pch * 90.0 + h * 38.0, 0.0, 127.0));
    jitter = 0.95 + 0.1 * h;
    if (cls == 19) {
      float sid; float e = cobble(wv, sid);
      tint = int(30.0 + sid * 90.0);
      if (e < 0.10) { tint = 6; jitter *= 0.7; }
    }
    if (cls == 16 && v_face == 2 && h > 0.9965 && dist < 25.0) tint = 127;
  }
  vec3 alb = srgb(texelFetch(u_pal, ivec2(tint, cls), 0).rgb) * jitter;
  float dist = length(v_rel);
  vec3 nw0 = rot(n, r);
  if (u_mode == 1 && n.y == 0.0) nw0 = normalize(nw0 + vec3(0.0, mix(2.2, 6.0, smoothstep(10.0, 60.0, dist)), 0.0));
  float tao = (u_mode == 1 && n.y == 0.0) ? 0.85 : 1.0;
  o = vec4(light(alb * edgeDark(v_local, n, dist), nw0, v_rel, v_ls, tao), 1.0);
#endif
}`;
const FRAG = '#version 300 es\n' + FRAG_SRC, FRAG_TRACE = '#version 300 es\n#define TRACE 1\n' + FRAG_SRC;

const SHADOW_FRAG = `#version 300 es
precision mediump float; out vec4 o; void main(){ o = vec4(1.0); }`;

const SKY_VERT = `#version 300 es
precision highp float; out vec2 v_uv; void main(){ vec2 p = vec2((gl_VertexID<<1)&2, gl_VertexID&2); v_uv = p*2.0-1.0; gl_Position = vec4(p*2.0-1.0, 1.0, 1.0); }`;
const SKY_FRAG = `#version 300 es
precision highp float; in vec2 v_uv; uniform mat4 u_ivp; uniform vec3 u_sun; out vec4 o;
vec3 aces(vec3 x){ return clamp((x*(2.51*x+0.03))/(x*(2.43*x+0.59)+0.14), 0.0, 1.0); }
float hh(vec2 p){ return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
float vn(vec2 p){ vec2 i = floor(p), f = fract(p); f = f*f*(3.0-2.0*f);
  return mix(mix(hh(i), hh(i+vec2(1,0)), f.x), mix(hh(i+vec2(0,1)), hh(i+vec2(1,1)), f.x), f.y); }
float fbm(vec2 p){ float s = 0.0, a = 0.5; for (int i = 0; i < 5; i++){ s += a * vn(p); p = p * 2.03 + 7.1; a *= 0.5; } return s; }
void main(){
  vec4 w = u_ivp * vec4(v_uv, 1.0, 1.0); vec3 d = normalize(w.xyz / w.w);
  float t = max(d.y, 0.0);
  vec3 c = mix(vec3(0.52, 0.62, 0.76), vec3(0.16, 0.34, 0.70), pow(t, 0.5));
  float s = max(dot(d, u_sun), 0.0);
  if (d.y > 0.0) {
    vec2 cp = d.xz / (d.y + 0.12) * 1.6;
    float cl = smoothstep(0.48, 0.78, fbm(cp + vec2(3.0, 1.0)));
    vec3 ccol = mix(vec3(0.78, 0.80, 0.86), vec3(1.15, 1.08, 0.98), smoothstep(0.4, 1.0, fbm(cp * 1.7 - 2.0) + s * 0.4));
    c = mix(c, ccol, cl * smoothstep(0.0, 0.15, d.y) * 0.9);
  }
  c += vec3(1.0, 0.82, 0.55) * (pow(s, 8.0) * 0.22 + pow(s, 900.0) * 6.0);
  c = mix(c, vec3(0.40, 0.46, 0.40), smoothstep(0.0, -0.08, d.y));
  c = aces(c * 0.95);
  c = pow(c, vec3(1.0/2.2));
  o = vec4(c * c * (3.0 - 2.0 * c) * 0.35 + c * 0.65, 1.0);
}`;

const PART_VERT = `#version 300 es
precision highp float;
layout(location=0) in vec3 a_c; layout(location=1) in vec4 a_p; layout(location=2) in vec4 a_col;
uniform mat4 u_vp; uniform vec3 u_cam; uniform vec3 u_sun; out vec3 v_c;
void main(){ vec3 w = a_p.xyz + (a_c - 0.5) * a_p.w - u_cam; vec3 n = normalize(a_c - 0.5);
  v_c = a_col.rgb * (0.55 + 0.6 * max(dot(n, u_sun), 0.0)); gl_Position = u_vp * vec4(w, 1.0); }`;
const PART_FRAG = `#version 300 es
precision mediump float; in vec3 v_c; out vec4 o; void main(){ o = vec4(pow(v_c, vec3(1.0/2.2)), 1.0); }`;

const P_RASTER = prog(VERT, FRAG), PT = prog(VERT, FRAG_TRACE), PS = prog(VERT, SHADOW_FRAG), PK = prog(SKY_VERT, SKY_FRAG), PP = prog(PART_VERT, PART_FRAG);

// ======================= load data =======================
status('Téléchargement du village voxélisé…');
// data ships as base64 text (artifact hosting serves text, not arbitrary binaries); same bytes as world.bin
const resp = await fetch('world.b64.txt');
const b64 = (await resp.text()).trim();
const DOWNLOAD = Number(resp.headers.get('content-length')) || b64.length;
let buf = (() => { const s = atob(b64), a = new Uint8Array(s.length); for (let i = 0; i < s.length; i++) a[i] = s.charCodeAt(i); return a.buffer; })();
const u8h = new Uint8Array(buf, 0, 2);
let GZ_BYTES = buf.byteLength;
if (u8h[0] === 0x1f && u8h[1] === 0x8b) {
  status('Décompression…');
  const ds = new Response(new Blob([buf]).stream().pipeThrough(new DecompressionStream('gzip')));
  buf = await ds.arrayBuffer();
}
const RAW_BYTES = buf.byteLength;
status('Lecture des briques…');
const W = VX.parseVXB(buf);
status('Génération procédurale des arbres…');
VX.addTrees(W, SEED, 4);
const MOD = {}; W.mods.forEach((m) => { MOD[m.name] = m; m.instances = []; });
const pool = W.pool; const owner = new Map();   // slot -> instance id (copy-on-write ownership)

// ======================= village (plan generator, deterministic) =======================
const rng = (() => { let s = SEED >>> 0; return () => { s = (s + 0x6D2B79F5) >>> 0; let t = s; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; })();
const pick = (a) => a[Math.floor(rng() * a.length)];
const CX = 8192, CZ = 8192, M = 50; // M voxels per meter
const instances = [];
const pads = [], streets = [];
const tmpTerrain = new VX.Terrain({ seed: SEED, cx: CX, cz: CZ, pads: [], streets: [] });
function rotP(x, z, r) { return r === 1 ? [z, -x] : r === 2 ? [-x, -z] : r === 3 ? [-z, x] : [x, z]; }
function place(name, x, y, z, r) {
  const mod = MOD[name]; if (!mod) { console.warn('missing', name); return null; }
  const inst = { id: instances.length, mod, x: Math.round(x), y: Math.round(y), z: Math.round(z), r: r & 3, bricks: null };
  instances.push(inst); mod.instances.push(inst); return inst;
}
// house builder in house-local meters; front (door) on z=0 facing -z
function house(H, hr, Wm, Lm, n, opts) {
  const add = (name, x, y, z, r) => {
    const [wx, wz] = rotP(x * M, z * M, hr);
    return place(name, H.x + wx, H.y + y * M, H.z + wz, (r + hr) & 3);
  };
  const ground = opts.ground;  // 'UnevenBrick' | 'Plaster'
  for (let s = 0; s < n; s++) {
    const y = 3 * s, st = s === 0 ? ground : 'Plaster';
    const segs = [];
    for (let i = 0; i < Wm / 2; i++) { segs.push([1 + 2 * i, 0, 2, 'front', i]); segs.push([1 + 2 * i, Lm, 0, 'back', i]); }
    for (let j = 0; j < Lm / 2; j++) { segs.push([0, 1 + 2 * j, 3, 'left', j]); segs.push([Wm, 1 + 2 * j, 1, 'right', j]); }
    for (const [x, z, r, side, i] of segs) {
      if (s === 0 && side === 'front' && i === opts.door) {
        add(`Wall_${st}_Door_Round`, x, y, z, r);
        const [ox, oz] = rotP(-0.52, -0.16, r);
        add(opts.doorPiece, x + ox, y, z + oz, r);
        continue;
      }
      const roll = rng();
      if (roll < 0.45) {
        add(`Wall_${st}_Window_Wide_Round`, x, y, z, r); add('Window_Wide_Round1', x, y, z, r);
        if (rng() < 0.5) add('WindowShutters_Wide_Round_Open', x, y, z, r);
      } else if (roll < 0.7) {
        add(`Wall_${st}_Window_Thin_Round`, x, y, z, r); add('Window_Thin_Round1', x, y, z, r);
        if (rng() < 0.4) add('WindowShutters_Thin_Round_Open', x, y, z, r);
      } else if (st === 'Plaster' && s > 0 && roll < 0.85) add('Wall_Plaster_WoodGrid', x, y, z, r);
      else add(`Wall_${st}_Straight`, x, y, z, r);
      if (s === n - 1 && rng() < 0.12) { const [vx, vz] = rotP(0, 0.1, r); add(pick(['Prop_Vine1', 'Prop_Vine6']), x + vx, y + 2.95, z + vz, r); }
    }
    const corner = (st === 'UnevenBrick') ? 'Corner_Exterior_Brick' : 'Corner_Exterior_Wood';
    for (const [x, z, r] of [[0, 0, 2], [Wm, 0, 1], [Wm, Lm, 0], [0, Lm, 3]]) add(corner, x, y, z, r);
    for (let i = 0; i < Wm / 2; i++) for (let j = 0; j < Lm / 2; j++)
      add(s === 0 ? 'Floor_UnevenBrick' : 'Floor_WoodDark', 1 + 2 * i, y, 1 + 2 * j, 0);
  }
  for (let i = 0; i < Wm / 2; i++) for (let j = 0; j < Lm / 2; j++) add('Floor_WoodDark', 1 + 2 * i, 3 * n, 1 + 2 * j, 0);
  add(`Roof_RoundTiles_${Wm}x${Lm}`, Wm / 2, 3 * n, Lm / 2, 0);
  add(`Roof_Front_Brick${Wm}`, Wm / 2, 3 * n, 0, 2);
  add(`Roof_Front_Brick${Wm}`, Wm / 2, 3 * n, Lm, 0);
  if (opts.chimney) add('Prop_Chimney', Wm - 0.75, 3 * n - 0.2, Lm * 0.65, 0);
}
function tower(H, n) {
  const add = (name, x, y, z, r) => place(name, H.x + x * M, H.y + y * M, H.z + z * M, r);
  for (let s = 0; s < n; s++) {
    const y = 3 * s;
    const segs = [[1, 0, 2], [3, 0, 2], [1, 4, 0], [3, 4, 0], [0, 1, 3], [0, 3, 3], [4, 1, 1], [4, 3, 1]];
    segs.forEach(([x, z, r], k) => {
      if (s === 0 && k === 0) { add('Wall_UnevenBrick_Door_Round', x, y, z, r); const [ox, oz] = rotP(-0.52, -0.16, r); add('Door_4_Round', x + ox, y, z + oz, r); }
      else if (s > 0 && (k + s) % 3 === 0) { add('Wall_UnevenBrick_Window_Thin_Round', x, y, z, r); add('Window_Thin_Round1', x, y, z, r); }
      else add('Wall_UnevenBrick_Straight', x, y, z, r);
    });
    for (const [x, z, r] of [[0, 0, 2], [4, 0, 1], [4, 4, 0], [0, 4, 3]]) add('Corner_Exterior_Brick', x, y, z, r);
    for (let i = 0; i < 2; i++) for (let j = 0; j < 2; j++) add(s === 0 ? 'Floor_UnevenBrick' : 'Floor_WoodDark', 1 + 2 * i, y, 1 + 2 * j, 0);
  }
  add('Roof_Tower_RoundTiles', 2, 3 * n, 2, 0);
}
function padFor(x0, z0, x1, z1, h) { pads.push({ x0: Math.min(x0, x1), z0: Math.min(z0, z1), x1: Math.max(x0, x1), z1: Math.max(z0, z1), h, blend: 5 * M }); }
const groundAt = (x, z) => Math.round(tmpTerrain.natural(x, z) / VS);

streets.push({ ax: CX - 60 * M, az: CZ, bx: CX + 60 * M, bz: CZ, w: 1.7 * M });
streets.push({ ax: CX, az: CZ - 55 * M, bx: CX, bz: CZ + 50 * M, w: 1.5 * M });
streets.push({ ax: CX, az: CZ, bx: CX, bz: CZ, w: 9 * M });       // plaza

const SIZES = [[4, 4], [4, 6], [4, 8], [6, 6], [6, 8], [4, 6]];
function lotHouse(fx, fz, facing) {    // front-centre point (voxels), facing = direction the door looks at
  const [Wm, Lm] = pick(SIZES); const n = rng() < 0.25 ? 3 : 2;
  const opts = { ground: rng() < 0.6 ? 'UnevenBrick' : 'Plaster', door: Math.floor(rng() * (Wm / 2)), doorPiece: pick(['Door_1_Round', 'Door_4_Round']), chimney: rng() < 0.7 };
  if (!MOD[`Roof_RoundTiles_${Wm}x${Lm}`]) return;
  let H, hr, rect;
  const w = Wm * M, l = Lm * M;
  if (facing === '+z') { hr = 2; H = { x: fx + w / 2, z: fz }; rect = [fx - w / 2, fz - l, fx + w / 2, fz]; }
  else if (facing === '-z') { hr = 0; H = { x: fx - w / 2, z: fz }; rect = [fx - w / 2, fz, fx + w / 2, fz + l]; }
  else if (facing === '-x') { hr = 1; H = { x: fx, z: fz + w / 2 }; rect = [fx, fz - w / 2, fx + l, fz + w / 2]; }
  else { hr = 3; H = { x: fx, z: fz - w / 2 }; rect = [fx - l, fz - w / 2, fx, fz + w / 2]; }
  const cx = (rect[0] + rect[2]) / 2, cz = (rect[1] + rect[3]) / 2;
  H.y = groundAt(cx, cz);
  padFor(rect[0] - 1.2 * M, rect[1] - 1.2 * M, rect[2] + 1.2 * M, rect[3] + 1.2 * M, H.y);
  house(H, hr, Wm, Lm, n, opts);
  // yard props
  if (rng() < 0.6) {
    const bx = (rect[0] + rect[2]) / 2 + (rng() - 0.5) * w, bz = facing === '+z' ? rect[1] - 1.5 * M : facing === '-z' ? rect[3] + 1.5 * M : cz;
    if (facing === '+z' || facing === '-z') for (let k = -1; k <= 1; k++) place(k === 0 ? 'Prop_WoodenFence_Extension1' : 'Prop_WoodenFence_Single', bx + k * 2 * M, groundAt(bx + k * 2 * M, bz), bz, 0);
  }
  if (rng() < 0.5) {
    const side = rng() < 0.5 ? rect[0] - 0.8 * M : rect[2] + 0.8 * M;
    place('Prop_Crate', side, groundAt(side, cz) , cz + (rng() - 0.5) * 2 * M, Math.floor(rng() * 4));
  }
}
for (const x of [-46, -36, -26, 17, 27, 38]) { lotHouse(CX + x * M, CZ - 4.6 * M, '+z'); lotHouse(CX + x * M + 2 * M, CZ + 4.6 * M, '-z'); }
for (const z of [-44, -32, -20]) { lotHouse(CX + 4.4 * M, CZ + z * M, '-x'); lotHouse(CX - 4.4 * M, CZ + z * M + 1 * M, '+x'); }
for (const z of [18, 30]) { lotHouse(CX + 4.4 * M, CZ + z * M, '-x'); lotHouse(CX - 4.4 * M, CZ + z * M, '+x'); }
// tower on the plaza edge
{ const tx = CX + 9 * M, tz = CZ - 13 * M, ty = groundAt(tx + 2 * M, tz + 2 * M); padFor(tx - M, tz - M, tx + 5 * M, tz + 5 * M, ty); tower({ x: tx, y: ty, z: tz }, 4); }
// plaza props
place('Prop_Wagon', CX - 5 * M, groundAt(CX - 5 * M, CZ + 2 * M), CZ + 2 * M, 1);
for (let k = 0; k < 6; k++) { const a = rng() * 6.28, r = (4 + rng() * 3) * M; const x = CX + Math.cos(a) * r, z = CZ + Math.sin(a) * r; place(pick(['Prop_Crate', 'Prop_Brick1', 'Prop_Brick2']), x, groundAt(x, z), z, Math.floor(rng() * 4)); }
for (let k = -3; k <= 3; k++) { if (k === 0) continue; const x = CX + k * 2 * M; place('Prop_ExteriorBorder_Straight1', x, groundAt(x, CZ - 9.5 * M), CZ - 9.5 * M, 2); }

const TER = { seed: SEED, cx: CX, cz: CZ, pads, streets };
const terrain = new VX.Terrain(TER);
// trees: procedural modules scattered around the village (deterministic)
{
  let placed = 0;
  for (let k = 0; k < 400 && placed < 70; k++) {
    const a = rng() * 6.283, r = (12 + Math.pow(rng(), 0.7) * 75) * M;
    const x = Math.round(CX + Math.cos(a) * r), z = Math.round(CZ + Math.sin(a) * r);
    if (terrain.topClass(x, z) !== 16) continue;
    if (pads.some((q) => x > q.x0 - 3 * M && x < q.x1 + 3 * M && z > q.z0 - 3 * M && z < q.z1 + 3 * M)) continue;
    if (instances.some((i) => i.mod.name.startsWith('Tree') && Math.hypot(i.x - x, i.z - z) < 6 * M)) continue;
    place('Tree_' + (placed % 4), x, terrain.height(x, z) - 3, z, Math.floor(rng() * 4)); placed++;
  }
}

// instance bounds (world voxels) + spatial grid (64-voxel cells in xz)
function instToWorld(inst, x, y, z) {   // local corner point -> world
  const [a, b] = rotP(x, z, inst.r); return [a + inst.x, y + inst.y, b + inst.z];
}
const GRID = new Map(), GC = 64;
for (const inst of instances) {
  const m = inst.mod;
  const p0 = instToWorld(inst, m.ox, m.oy, m.oz), p1 = instToWorld(inst, m.ox + m.dx, m.oy + m.dy, m.oz + m.dz);
  inst.x0 = Math.min(p0[0], p1[0]); inst.x1 = Math.max(p0[0], p1[0]); inst.y0 = p0[1]; inst.y1 = p1[1];
  inst.z0 = Math.min(p0[2], p1[2]); inst.z1 = Math.max(p0[2], p1[2]);
  inst.cx = (inst.x0 + inst.x1) / 2 * VS; inst.cy = (inst.y0 + inst.y1) / 2 * VS; inst.cz = (inst.z0 + inst.z1) / 2 * VS;
  inst.rad = 0.5 * VS * Math.hypot(inst.x1 - inst.x0, inst.y1 - inst.y0, inst.z1 - inst.z0);
  for (let gx = Math.floor(inst.x0 / GC); gx <= Math.floor((inst.x1 - 1) / GC); gx++)
    for (let gz = Math.floor(inst.z0 / GC); gz <= Math.floor((inst.z1 - 1) / GC); gz++) {
      const k = gx * 65536 + gz; let a = GRID.get(k); if (!a) GRID.set(k, a = []); a.push(inst);
    }
}
// world -> local cell
function toLocal(inst, x, y, z) {
  const dx = x - inst.x, dz = z - inst.z, r = inst.r;
  if (r === 0) return [dx, y - inst.y, dz];
  if (r === 1) return [-dz - 1, y - inst.y, dx];
  if (r === 2) return [-dx - 1, y - inst.y, -dz - 1];
  return [dz, y - inst.y, -dx - 1];
}

// ======================= terrain queries (CPU) =======================
const HCACHE = new Map(), REMOVED = new Map(), TS = 128;
function heightAt(x, z) {
  const tx = x >> 7, tz = z >> 7, k = tx * 4096 + tz;
  let a = HCACHE.get(k);
  if (!a) { a = new Int32Array(TS * TS); for (let j = 0; j < TS; j++) for (let i = 0; i < TS; i++) a[i + TS * j] = terrain.height(tx * TS + i, tz * TS + j); HCACHE.set(k, a); }
  return a[(x & 127) + TS * (z & 127)];
}
function terrainRemoved(x, y, z) {
  const s = REMOVED.get((x >> 7) * 4096 + (z >> 7)); return s ? s.has((x & 127) + TS * ((z & 127) + TS * y)) : false;
}
function voxelAt(x, y, z) {             // VoxelId (0 = air)
  const g = GRID.get((x >> 6) * 65536 + (z >> 6));
  if (g) for (let i = 0; i < g.length; i++) {
    const inst = g[i];
    if (x < inst.x0 || x >= inst.x1 || y < inst.y0 || y >= inst.y1 || z < inst.z0 || z >= inst.z1) continue;
    const l = toLocal(inst, x, y, z);
    const id = VX.getLocal(inst.mod, inst.bricks || inst.mod.bricks, pool, l[0], l[1], l[2]);
    if (id) return id;
  }
  const h = heightAt(x, z);
  if (y < h && !terrainRemoved(x, y, z)) return terrain.classAt(terrain.topClass(x, z), h - 1 - y) << 7 | 64;
  return 0;
}
function solid(x, y, z) {
  const g = GRID.get((x >> 6) * 65536 + (z >> 6));
  if (g) for (let i = 0; i < g.length; i++) {
    const inst = g[i];
    if (x < inst.x0 || x >= inst.x1 || y < inst.y0 || y >= inst.y1 || z < inst.z0 || z >= inst.z1) continue;
    const l = toLocal(inst, x, y, z);
    if (VX.getLocal(inst.mod, inst.bricks || inst.mod.bricks, pool, l[0], l[1], l[2])) return true;
  }
  return y < heightAt(x, z) && !terrainRemoved(x, y, z);
}

// ======================= GPU resources =======================
// palette (classes x 128 tints), terrain rows generated here
const NCLS = W.ncls, NT = W.nt;
const palData = new Uint8Array(NT * NCLS * 4);
for (let c = 0; c < NCLS; c++) for (let t = 0; t < NT; t++) { const s = (c * NT + t) * 3, d = (c * NT + t) * 4; palData[d] = W.palette[s]; palData[d + 1] = W.palette[s + 1]; palData[d + 2] = W.palette[s + 2]; palData[d + 3] = 255; }
function ramp(c, a, b, extra) {
  for (let t = 0; t < NT; t++) { const f = t / (NT - 1), d = (c * NT + t) * 4; for (let k = 0; k < 3; k++) palData[d + k] = Math.round(a[k] + (b[k] - a[k]) * f); palData[d + 3] = 255; }
  if (extra) extra();
}
ramp(16, [44, 70, 30], [104, 128, 56], () => { const d = (16 * NT + 127) * 4; palData.set([235, 220, 120, 255], d); });
ramp(17, [92, 66, 44], [140, 104, 70]);
ramp(18, [92, 92, 96], [150, 148, 145]);
ramp(19, [70, 72, 80], [128, 124, 122], () => { for (let t = 0; t < 10; t++) palData.set([58, 54, 50, 255], (19 * NT + t) * 4); });
ramp(20, [118, 104, 82], [168, 152, 124]);
ramp(12, [28, 52, 22], [98, 140, 48]);
ramp(13, [78, 62, 48], [138, 118, 92]);
const palTex = gl.createTexture(); gl.bindTexture(gl.TEXTURE_2D, palTex);
gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA8, NT, NCLS, 0, gl.RGBA, gl.UNSIGNED_BYTE, palData);
gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
const palRGB = (id) => { const c = Math.min(id >> 7, NCLS - 1), t = id & 127, d = (c * NT + t) * 4; return [palData[d] / 255, palData[d + 1] / 255, palData[d + 2] / 255]; };

// brick atlas: R8UI, each brick = 4x8x8 texels (two 4-bit voxels per texel), 128 x 64 bricks per 8-deep layer
const ATLAS_CAP = Math.ceil((pool.n + 24576) / 8192) * 8192;
const ATLAS_D = (ATLAS_CAP / 8192) * 8;
const atlas = gl.createTexture(); gl.bindTexture(gl.TEXTURE_3D, atlas);
gl.texStorage3D(gl.TEXTURE_3D, 1, gl.R8UI, 512, 512, ATLAS_D);
gl.texParameteri(gl.TEXTURE_3D, gl.TEXTURE_MIN_FILTER, gl.NEAREST); gl.texParameteri(gl.TEXTURE_3D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
// per-brick local palettes: R16UI, 128 bricks x 16 entries per row
const BPAL_H = ATLAS_CAP / 128;
const bpal = gl.createTexture(); gl.bindTexture(gl.TEXTURE_2D, bpal);
gl.texStorage2D(gl.TEXTURE_2D, 1, gl.R16UI, 2048, BPAL_H);
gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
MEM.atlas = 512 * 512 * ATLAS_D + 2048 * BPAL_H * 2;
gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
{
  const layer = new Uint8Array(512 * 512 * 8);
  const layers = Math.ceil(pool.n / 8192);
  for (let L = 0; L < layers; L++) {
    layer.fill(0);
    for (let s = L * 8192; s < Math.min(pool.n, (L + 1) * 8192); s++) {
      const sx = (s & 127) * 4, sy = ((s >> 7) & 63) * 8, src0 = s * 256;
      for (let z = 0; z < 8; z++) for (let y = 0; y < 8; y++) {
        const dst = sx + 512 * ((sy + y) + 512 * z), src = src0 + 4 * (y + 8 * z);
        layer[dst] = pool.idx[src]; layer[dst + 1] = pool.idx[src + 1]; layer[dst + 2] = pool.idx[src + 2]; layer[dst + 3] = pool.idx[src + 3];
      }
    }
    gl.texSubImage3D(gl.TEXTURE_3D, 0, 0, 0, L * 8, 512, 512, 8, gl.RED_INTEGER, gl.UNSIGNED_BYTE, layer);
  }
  const rows = Math.ceil(pool.n / 128), pd = new Uint16Array(rows * 2048); pd.set(pool.pal.subarray(0, pool.n * 16));
  gl.bindTexture(gl.TEXTURE_2D, bpal);
  gl.texSubImage2D(gl.TEXTURE_2D, 0, 0, 0, 2048, rows, gl.RED_INTEGER, gl.UNSIGNED_SHORT, pd);
}
function uploadBrick(s) {
  if (s >= ATLAS_CAP) return false;
  gl.bindTexture(gl.TEXTURE_3D, atlas);
  gl.texSubImage3D(gl.TEXTURE_3D, 0, (s & 127) * 4, ((s >> 7) & 63) * 8, (s >> 13) * 8, 4, 8, 8, gl.RED_INTEGER, gl.UNSIGNED_BYTE, pool.idx.subarray(s * 256, s * 256 + 256));
  gl.bindTexture(gl.TEXTURE_2D, bpal);
  gl.texSubImage2D(gl.TEXTURE_2D, 0, (s & 127) * 16, s >> 7, 16, 1, gl.RED_INTEGER, gl.UNSIGNED_SHORT, pool.pal.subarray(s * 16, s * 16 + 16));
  return true;
}
// indirection: R32UI 2048 wide
let totalBricks = 0; for (const m of W.mods) totalBricks += m.bricks.length;
const IND_W = 2048, IND_H = Math.ceil((totalBricks + 1500000) / IND_W);
const indir = gl.createTexture(); gl.bindTexture(gl.TEXTURE_2D, indir);
gl.texStorage2D(gl.TEXTURE_2D, 1, gl.R32UI, IND_W, IND_H);
gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
MEM.indir = IND_W * IND_H * 4;
let indirTop = 0;
const encB = (b) => b === 0 ? 0 : b > 0 ? ((0x80000000 | b) >>> 0) : (-b);   // mixed: slot+1
function uploadIndir(base, data) {
  gl.bindTexture(gl.TEXTURE_2D, indir);
  let i = 0;
  while (i < data.length) {
    const idx = base + i, row = Math.floor(idx / IND_W), col = idx % IND_W, n = Math.min(IND_W - col, data.length - i);
    gl.texSubImage2D(gl.TEXTURE_2D, 0, col, row, n, 1, gl.RED_INTEGER, gl.UNSIGNED_INT, data.subarray(i, i + n));
    i += n;
  }
}
function allocIndir(bricks) {
  const base = indirTop; indirTop += bricks.length;
  if (indirTop > IND_W * IND_H) throw new Error('indirection full');
  const d = new Uint32Array(bricks.length); for (let i = 0; i < bricks.length; i++) d[i] = encB(bricks[i]);
  uploadIndir(base, d); return base;
}
for (const m of W.mods) m.base = allocIndir(m.bricks);

// quad index buffer (grown on demand)
const ibo = gl.createBuffer(); let iboQuads = 0;
function ensureIndex(q) {
  if (q <= iboQuads) return;
  let n = Math.max(q, iboQuads * 2, 65536); const a = new Uint32Array(n * 6);
  for (let i = 0; i < n; i++) { const v = i * 4, o = i * 6; a[o] = v; a[o + 1] = v + 1; a[o + 2] = v + 2; a[o + 3] = v; a[o + 4] = v + 2; a[o + 5] = v + 3; }
  gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, ibo); gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, a, gl.STATIC_DRAW);
  MEM.idx = a.byteLength; iboQuads = n;
}
ensureIndex(65536);
function makeMesh(ab) {
  if (!ab || !ab.byteLength) return null;
  const b = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, b); gl.bufferData(gl.ARRAY_BUFFER, ab, gl.STATIC_DRAW);
  MEM.vbo += ab.byteLength; const quads = ab.byteLength / 32; ensureIndex(quads);
  return { b, quads, bytes: ab.byteLength };
}
function freeMesh(m) { if (m) { gl.deleteBuffer(m.b); MEM.vbo -= m.bytes; } }
function concat(list) {
  let n = 0; for (const a of list) n += a.byteLength;
  const out = new Uint8Array(n); let o = 0; for (const a of list) { out.set(new Uint8Array(a), o); o += a.byteLength; }
  return out.buffer;
}

// ======================= workers =======================
const shared = await (await fetch('shared.js')).text();
const NW = Math.max(1, Math.min(4, (navigator.hardwareConcurrency || 4) - 1));
const workers = [];
let jobSeq = 0; const jobs = new Map();
function onMsg(m) {
  const j = jobs.get(m.job); if (m.job !== undefined) jobs.delete(m.job);
  if (m.type === 'module') moduleMeshed(m);
  else if (j) j(m);
}
let usedLocal = false;
const raw = new Uint8Array(buf);
function useLocal() {
  usedLocal = true; workers.forEach((w) => w.terminate && w.terminate()); workers.length = 0;
  const h = VX.makeHandler();
  // main-thread fallback: same code, run in small slices so the page stays responsive
  const q = []; let running = false;
  const pump = () => { const m = q.shift(); if (!m) { running = false; return; } h(m, (r) => onMsg(r)); setTimeout(pump, 0); };
  workers.push({ postMessage(m) { q.push(m); if (!running) { running = true; setTimeout(pump, 0); } } });
  workers[0].postMessage({ type: 'init', buf: raw.slice().buffer, terrain: TER });
}
try {
  const url = URL.createObjectURL(new Blob([shared], { type: 'text/javascript' }));
  for (let i = 0; i < NW; i++) { const w = new Worker(url); workers.push(w); }
  let ready = 0;
  const ok = await Promise.race([
    new Promise((res) => workers.forEach((w) => {
      w.onmessage = (e) => { if (e.data.type === 'ready') { w.onmessage = (ev) => onMsg(ev.data); if (++ready === workers.length) res(true); } };
      w.onerror = () => res(false);
      w.postMessage({ type: 'init', buf: raw.slice().buffer, terrain: TER });
    })),
    new Promise((res) => setTimeout(() => res(false), 20000)),
  ]);
  if (!ok) useLocal();
} catch (e) { useLocal(); }
let rr = 0; const nextW = () => workers[(rr++) % workers.length];

// module meshing
const usedMods = W.mods.filter((m) => m.instances.length);
let modsDone = 0; let MESH_MS = 0;
function moduleMeshed(m) {
  const mod = W.mods[m.id];
  mod.chunkMeshes = new Map(); for (const c of m.chunks) mod.chunkMeshes.set(c.c, c.v);
  mod.lod = [makeMesh(concat(m.chunks.map((c) => c.v)))];
  for (const c of m.coarse) mod.lod.push(makeMesh(c));
  MESH_MS += m.ms; modsDone++;
  status(`Maillage glouton des modules ${modsDone}/${usedMods.length}…`);
}
usedMods.sort((a, b) => b.nvox - a.nvox).forEach((m) => nextW().postMessage({ type: 'module', id: m.id }));
await new Promise((res) => { const t = setInterval(() => { if (modsDone >= usedMods.length) { clearInterval(t); res(); } }, 50); });
workers.forEach((w) => w.postMessage({ type: 'drop' }));

// ======================= terrain quadtree =======================
const WORLD = 16384, ROOT = 4096;
const TNODES = new Map();     // key -> {mesh, state, used}
const tkey = (x, z, S) => x + ',' + z + ',' + S;
const editedTiles = new Set();   // 128-tiles with removed voxels
let terrainPending = 0;
function requestNode(x0, z0, S) {
  const k = tkey(x0, z0, S); let nd = TNODES.get(k);
  if (nd) return nd;
  nd = { x0, z0, S, mesh: null, state: 0, used: 0, ver: 0 }; TNODES.set(k, nd);
  meshNode(nd); return nd;
}
function meshNode(nd) {
  const job = ++jobSeq; nd.state = 1; terrainPending++;
  const ver = ++nd.ver;
  const step = nd.S <= 256 ? nd.S / 128 : nd.S / 64;
  let removed = null;
  if (step === 1) { const set = REMOVED.get((nd.x0 >> 7) * 4096 + (nd.z0 >> 7)); if (set && set.size) removed = Uint32Array.from(set); }
  jobs.set(job, (m) => {
    terrainPending--;
    if (ver !== nd.ver) return;
    const old = nd.mesh; nd.mesh = makeMesh(m.v); nd.state = 2; freeMesh(old);
  });
  nextW().postMessage({ type: 'terrain', job, x0: nd.x0, z0: nd.z0, S: nd.S, s: step, removed });
}
const tdraw = [];
let camX = 0, camY = 0, camZ = 0;
function nodeHasEdits(x0, z0, S) {
  for (const k of editedTiles) { const tx = Math.floor(k / 4096) * 128, tz = (k % 4096) * 128; if (tx >= x0 && tx < x0 + S && tz >= z0 && tz < z0 + S) return true; }
  return false;
}
let evictTick = 0;
function selectTerrain(now) {
  tdraw.length = 0;
  const K = 1.4 * Q.dist;
  const visit = (x0, z0, S) => {
    const nd = requestNode(x0, z0, S); nd.used = now;
    const cxm = (x0 + S / 2) * VS, czm = (z0 + S / 2) * VS;
    const dx = Math.max(Math.abs(camX - cxm) - S * VS / 2, 0), dz = Math.max(Math.abs(camZ - czm) - S * VS / 2, 0);
    const hy = Math.abs(camY - heightAt(Math.min(Math.max(Math.round(camX / VS), x0), x0 + S - 1), Math.min(Math.max(Math.round(camZ / VS), z0), z0 + S - 1)) * VS);
    const d = Math.hypot(dx, dz, hy * 0.5);
    let split = S > 128 && (d < K * S * VS || (d < 60 && nodeHasEdits(x0, z0, S)));
    if (split) {
      const h = S / 2, kids = [[x0, z0], [x0 + h, z0], [x0, z0 + h], [x0 + h, z0 + h]];
      const nodes = kids.map(([a, b]) => requestNode(a, b, h));
      if (nodes.every((n) => n.state === 2 || (n.mesh))) { kids.forEach(([a, b]) => visit(a, b, h)); return; }
    }
    if (nd.mesh) tdraw.push(nd);
  };
  for (let x = 0; x < WORLD; x += ROOT) for (let z = 0; z < WORLD; z += ROOT) visit(x, z, ROOT);
  if (++evictTick % 120 === 0) for (const [k, nd] of TNODES) if (now - nd.used > 1500 && nd.state === 2) { freeMesh(nd.mesh); TNODES.delete(k); }
}

// ======================= player =======================
const player = { x: CX + 0.5 * M, y: 0, z: CZ + 1 * M, vx: 0, vy: 0, vz: 0, yaw: Math.PI * 0.75, pitch: -0.08, ground: false, fly: false, eyeSmooth: 0 };
player.y = heightAt(player.x | 0, player.z | 0) + 2;
const HW = 12, HH = 86, EYE = 80, STEP = 20;
const keys = {};
function boxFree(x0, x1, y0, y1, z0, z1) {
  for (let x = x0; x <= x1; x++) for (let z = z0; z <= z1; z++) for (let y = y0; y <= y1; y++) if (solid(x, y, z)) return false;
  return true;
}
function moveAxis(ax, d) {
  let moved = 0;
  while (Math.abs(d) > 1e-6) {
    const st = Math.max(-1, Math.min(1, d)); d -= st;
    const p = [player.x, player.y, player.z];
    const mn = [p[0] - HW, p[1], p[2] - HW], mx = [p[0] + HW, p[1] + HH, p[2] + HW];
    let layer, enter;
    if (st > 0) { layer = Math.floor(mx[ax] + st - 1e-4); enter = layer > Math.floor(mx[ax] - 1e-4); }
    else { layer = Math.floor(mn[ax] + st); enter = layer < Math.floor(mn[ax]); }
    let ok = true;
    if (enter && !player.fly) {
      const r = [[Math.floor(mn[0]), Math.floor(mx[0] - 1e-4)], [Math.floor(mn[1]), Math.floor(mx[1] - 1e-4)], [Math.floor(mn[2]), Math.floor(mx[2] - 1e-4)]];
      r[ax] = [layer, layer];
      ok = boxFree(r[0][0], r[0][1], r[1][0], r[1][1], r[2][0], r[2][1]);
      if (!ok && ax !== 1 && player.ground) {
        for (let k = 1; k <= STEP; k++) {
          const r2 = r.map((a) => a.slice()); r2[1] = [r[1][0] + k, r[1][1] + k];
          if (!boxFree(r2[0][0], r2[0][1], r2[1][0], r2[1][1], r2[2][0], r2[2][1])) continue;
          const top = r[1][1];
          if (!boxFree(Math.floor(mn[0]), Math.floor(mx[0] - 1e-4), top + 1, top + k, Math.floor(mn[2]), Math.floor(mx[2] - 1e-4))) break;
          player.y = Math.floor(player.y) + k; player.eyeSmooth -= k; ok = true; break;
        }
      }
    }
    if (!ok) {
      if (ax === 1) { if (st < 0) player.ground = true; player.vy = 0; }
      else if (ax === 0) player.vx = 0; else player.vz = 0;
      return moved;
    }
    if (ax === 0) player.x += st; else if (ax === 1) player.y += st; else player.z += st;
    moved += st;
  }
  return moved;
}

// ======================= digging =======================
const HARD = { 1: 1.2, 2: 0.9, 3: 0.9, 4: 0.55, 5: 0.6, 6: 0.6, 7: 0.6, 8: 0.8, 9: 0.25, 10: 1.5, 11: 1.6, 16: 1.3, 17: 1.3, 18: 0.5, 19: 0.6, 20: 1.2 };
const TOOLS = [4, 8, 14, 24];   // radius in voxels (8, 16, 28, 48 cm)
let tool = 1;
const dirtyInst = new Map(); // inst -> Set(chunk index)
let editedCount = 0, voxelsRemoved = 0;
function ensureEdited(inst) {
  if (inst.bricks) return;
  inst.bricks = Int32Array.from(inst.mod.bricks);
  inst.base = allocIndir(inst.bricks);
  inst.chunks = new Map(inst.mod.chunkMeshes);
  inst.mesh = null; inst.meshDirty = true; inst.pending = 0;
  const arr = inst.mod.instances; arr.splice(arr.indexOf(inst), 1);
  editedList.push(inst); editedCount++;
}
const editedList = [];
const changedBricks = new Set();
function setLocal(inst, x, y, z) {      // remove one voxel (copy-on-write at brick level)
  const m = inst.mod; x -= m.ox; y -= m.oy; z -= m.oz;
  const bi = (x >> 3) + m.nbx * ((y >> 3) + m.nby * (z >> 3));
  let e = inst.bricks[bi], slot;
  if (e === 0) return;
  if (e > 0) { slot = pool.fromUniform(e); owner.set(slot, inst.id); inst.bricks[bi] = -(slot + 1); }
  else {
    slot = -e - 1;
    if (owner.get(slot) !== inst.id) { slot = pool.copy(slot); owner.set(slot, inst.id); inst.bricks[bi] = -(slot + 1); }
  }
  const k = slot * 256 + ((x & 7) >> 1) + 4 * ((y & 7) + 8 * (z & 7));
  pool.idx[k] &= (x & 1) ? 0x0f : 0xf0;
  changedBricks.add(inst.id * 4194304 + bi);
}
function raycast(ox, oy, oz, dx, dy, dz, maxD) {   // voxel units
  let x = Math.floor(ox), y = Math.floor(oy), z = Math.floor(oz);
  const sx = Math.sign(dx), sy = Math.sign(dy), sz = Math.sign(dz);
  const tdx = Math.abs(1 / dx), tdy = Math.abs(1 / dy), tdz = Math.abs(1 / dz);
  let tx = (sx > 0 ? x + 1 - ox : ox - x) * tdx, ty = (sy > 0 ? y + 1 - oy : oy - y) * tdy, tz = (sz > 0 ? z + 1 - oz : oz - z) * tdz;
  let t = 0;
  while (t < maxD) {
    if (solid(x, y, z)) return { x, y, z, t };
    if (tx < ty && tx < tz) { x += sx; t = tx; tx += tdx; } else if (ty < tz) { y += sy; t = ty; ty += tdy; } else { z += sz; t = tz; tz += tdz; }
  }
  return null;
}
const parts = []; const PMAX = 3000;
function carve(hx, hy, hz) {
  const id0 = voxelAt(hx, hy, hz); const cls = id0 >> 7;
  const R = Math.max(2, Math.round(TOOLS[tool] * (HARD[cls] || 1))), R2 = R * R;
  const x0 = hx - R, x1 = hx + R, y0 = hy - R, y1 = hy + R, z0 = hz - R, z1 = hz + R;
  const insts = new Set();
  for (let gx = x0 >> 6; gx <= x1 >> 6; gx++) for (let gz = z0 >> 6; gz <= z1 >> 6; gz++) { const g = GRID.get(gx * 65536 + gz); if (g) g.forEach((i) => insts.add(i)); }
  let removed = 0; const debris = [];
  for (const inst of insts) {
    if (x1 < inst.x0 || x0 >= inst.x1 || y1 < inst.y0 || y0 >= inst.y1 || z1 < inst.z0 || z0 >= inst.z1) continue;
    let touched = false;
    for (let x = Math.max(x0, inst.x0); x <= Math.min(x1, inst.x1 - 1); x++)
      for (let y = Math.max(y0, inst.y0); y <= Math.min(y1, inst.y1 - 1); y++)
        for (let z = Math.max(z0, inst.z0); z <= Math.min(z1, inst.z1 - 1); z++) {
          const ddx = x - hx, ddy = y - hy, ddz = z - hz; if (ddx * ddx + ddy * ddy + ddz * ddz > R2) continue;
          const l = toLocal(inst, x, y, z);
          const id = VX.getLocal(inst.mod, inst.bricks || inst.mod.bricks, pool, l[0], l[1], l[2]);
          if (!id) continue;
          if (!touched) { ensureEdited(inst); touched = true; }
          setLocal(inst, l[0], l[1], l[2]); removed++;
          if ((removed & 15) === 0 || removed < 40) debris.push(x, y, z, id);
          let s = dirtyInst.get(inst); if (!s) dirtyInst.set(inst, s = new Set());
          const m = inst.mod, ncx = Math.ceil(m.dx / 32), ncy = Math.ceil(m.dy / 32);
          const lx = l[0] - m.ox, ly = l[1] - m.oy, lz = l[2] - m.oz;
          // the chunk and its neighbours if on a border (faces change across chunk borders)
          const ncz = Math.ceil(m.dz / 32);
          for (const [ax, ay, az] of [[0, 0, 0], [-4, 0, 0], [4, 0, 0], [0, -4, 0], [0, 4, 0], [0, 0, -4], [0, 0, 4]]) {
            const cx = (lx + ax) >> 5, cy = (ly + ay) >> 5, cz = (lz + az) >> 5;
            if (cx < 0 || cy < 0 || cz < 0 || cx >= ncx || cy >= ncy || cz >= ncz) continue;
            s.add(cx + ncx * (cy + ncy * cz));
          }
        }
  }
  // terrain
  const tilesTouched = new Set();
  for (let x = x0; x <= x1; x++) for (let z = z0; z <= z1; z++) {
    const h = heightAt(x, z);
    for (let y = y0; y <= Math.min(y1, h - 1); y++) {
      const ddx = x - hx, ddy = y - hy, ddz = z - hz; if (ddx * ddx + ddy * ddy + ddz * ddz > R2) continue;
      const tk = (x >> 7) * 4096 + (z >> 7); let set = REMOVED.get(tk); if (!set) REMOVED.set(tk, set = new Set());
      const li = (x & 127) + TS * ((z & 127) + TS * y);
      if (set.has(li)) continue;
      set.add(li); removed++; tilesTouched.add(tk); editedTiles.add(tk);
      if ((removed & 15) === 0 || removed < 40) debris.push(x, y, z, terrain.classAt(terrain.topClass(x, z), h - 1 - y) << 7 | 64);
      // neighbours tiles if on border
      if ((x & 127) === 0) tilesTouched.add(tk - 4096); if ((x & 127) === 127) tilesTouched.add(tk + 4096);
      if ((z & 127) === 0) tilesTouched.add(tk - 1); if ((z & 127) === 127) tilesTouched.add(tk + 1);
    }
  }
  voxelsRemoved += removed;
  for (const tk of tilesTouched) { const nd = TNODES.get(tkey(Math.floor(tk / 4096) * 128, (tk % 4096) * 128, 128)); if (nd) meshNode(nd); }
  // debris particles
  for (let i = 0; i < debris.length && parts.length < PMAX; i += 4) {
    const c = palRGB(debris[i + 3]); const j = VX.hash2(debris[i], debris[i + 2], debris[i + 1]);
    const lin = c.map((v) => Math.pow(v, 2.2) * (0.85 + 0.3 * j));
    parts.push({ x: (debris[i] + 0.5) * VS, y: (debris[i + 1] + 0.5) * VS, z: (debris[i + 2] + 0.5) * VS,
      vx: (Math.random() - 0.5) * 2.5, vy: Math.random() * 3, vz: (Math.random() - 0.5) * 2.5, s: VS * (1 + Math.random() * 1.5), c: lin, life: 2.5 + Math.random() * 2 });
  }
  flushEdits();
}
function flushEdits() {
  // atlas + indirection
  for (const key of changedBricks) {
    const inst = instances[Math.floor(key / 4194304)], bi = key % 4194304;
    let e = inst.bricks[bi];
    if (e < 0) {
      const slot = -e - 1, a = pool.idx; let any = false; for (let i = slot * 256; i < slot * 256 + 256; i++) if (a[i]) { any = true; break; }
      if (!any) { inst.bricks[bi] = 0; e = 0; } else uploadBrick(slot);
    }
    uploadIndir(inst.base + bi, new Uint32Array([encB(e)]));
  }
  changedBricks.clear();
  // remesh chunks
  for (const [inst, set] of dirtyInst) {
    const m = inst.mod, ncx = Math.ceil(m.dx / 32), ncy = Math.ceil(m.dy / 32);
    for (const c of set) {
      const cx = c % ncx, cy = Math.floor(c / ncx) % ncy, cz = Math.floor(c / (ncx * ncy));
      const N = 40, block = new Uint16Array(N * N * N);
      const bx = m.ox + cx * 32 - 4, by = m.oy + cy * 32 - 4, bz = m.oz + cz * 32 - 4;
      for (let z = 0; z < N; z++) for (let y = 0; y < N; y++) for (let x = 0; x < N; x++) block[x + N * (y + N * z)] = VX.getLocal(m, inst.bricks, pool, bx + x, by + y, bz + z);
      const job = ++jobSeq; inst.pending++;
      jobs.set(job, (r) => { inst.pending--; if (r.v) inst.chunks.set(c, r.v); else inst.chunks.delete(c); inst.meshDirty = true; });
      nextW().postMessage({ type: 'chunk', job, block, x0: bx, y0: by, z0: bz }, [block.buffer]);
    }
  }
  dirtyInst.clear();
}

// ======================= input =======================
let digging = false, lastDig = 0, dragLook = false;
const locked = () => document.pointerLockElement === canvas;
canvas.addEventListener('contextmenu', (e) => e.preventDefault());
canvas.addEventListener('mousedown', (e) => {
  if (!locked() && e.button === 0 && !canvas.__triedLock) { canvas.__triedLock = true; try { const r = canvas.requestPointerLock(); if (r && r.catch) r.catch(() => {}); } catch (err) {} }
  if (e.button === 0) { digging = true; lastDig = 0; }
  if (e.button === 2) dragLook = true;
});
document.addEventListener('pointerlockchange', () => { canvas.__triedLock = locked(); $('help').style.display = locked() ? 'none' : 'block'; });
document.addEventListener('mousemove', (e) => {
  if (!locked() && !dragLook) return;
  player.yaw -= e.movementX * 0.0022; player.pitch = Math.max(-1.55, Math.min(1.55, player.pitch - e.movementY * 0.0022));
});
document.addEventListener('mouseup', (e) => { if (e.button === 0) digging = false; if (e.button === 2) dragLook = false; });
document.addEventListener('wheel', (e) => { tool = Math.max(0, Math.min(TOOLS.length - 1, tool + Math.sign(e.deltaY))); updTool(); });
document.addEventListener('keydown', (e) => {
  keys[e.code] = true;
  if (e.code === 'KeyF') { player.fly = !player.fly; player.vy = 0; }
  if (e.code >= 'Digit1' && e.code <= 'Digit4') { tool = +e.code.slice(5) - 1; updTool(); }
  if (e.code === 'KeyH') $('hud').classList.toggle('hidden');
  if (e.code === 'KeyB') startBench();
});
document.addEventListener('keyup', (e) => { keys[e.code] = false; });
function updTool() { $('tool').textContent = `Outil : rayon ${TOOLS[tool] * 2} cm (molette ou 1-4)`; }
updTool();
for (const el of document.querySelectorAll('[data-q]')) el.addEventListener('change', () => {
  const k = el.dataset.q; Q[k] = el.type === 'checkbox' ? el.checked : +el.value; resize();
});

// ======================= math =======================
function persp(fy, a, n, f) { const t = 1 / Math.tan(fy / 2); return new Float32Array([t / a, 0, 0, 0, 0, t, 0, 0, 0, 0, (f + n) / (n - f), -1, 0, 0, 2 * f * n / (n - f), 0]); }
function mul(a, b) { const o = new Float32Array(16); for (let i = 0; i < 4; i++) for (let j = 0; j < 4; j++) { let s = 0; for (let k = 0; k < 4; k++) s += a[k * 4 + j] * b[i * 4 + k]; o[i * 4 + j] = s; } return o; }
function lookDir(f, up) {  // view matrix (rotation only) looking along f
  const z = [-f[0], -f[1], -f[2]]; let x = [up[1] * z[2] - up[2] * z[1], up[2] * z[0] - up[0] * z[2], up[0] * z[1] - up[1] * z[0]];
  const l = Math.hypot(...x); x = x.map((v) => v / l); const y = [z[1] * x[2] - z[2] * x[1], z[2] * x[0] - z[0] * x[2], z[0] * x[1] - z[1] * x[0]];
  return new Float32Array([x[0], y[0], z[0], 0, x[1], y[1], z[1], 0, x[2], y[2], z[2], 0, 0, 0, 0, 1]);
}
function ortho(l, r, b, t, n, f) { return new Float32Array([2 / (r - l), 0, 0, 0, 0, 2 / (t - b), 0, 0, 0, 0, -2 / (f - n), 0, -(r + l) / (r - l), -(t + b) / (t - b), -(f + n) / (f - n), 1]); }
function inv(m) {
  const a = m, o = new Float32Array(16);
  const b00 = a[0] * a[5] - a[1] * a[4], b01 = a[0] * a[6] - a[2] * a[4], b02 = a[0] * a[7] - a[3] * a[4], b03 = a[1] * a[6] - a[2] * a[5], b04 = a[1] * a[7] - a[3] * a[5], b05 = a[2] * a[7] - a[3] * a[6];
  const b06 = a[8] * a[13] - a[9] * a[12], b07 = a[8] * a[14] - a[10] * a[12], b08 = a[8] * a[15] - a[11] * a[12], b09 = a[9] * a[14] - a[10] * a[13], b10 = a[9] * a[15] - a[11] * a[13], b11 = a[10] * a[15] - a[11] * a[14];
  const d = 1 / (b00 * b11 - b01 * b10 + b02 * b09 + b03 * b08 - b04 * b07 + b05 * b06);
  o[0] = (a[5] * b11 - a[6] * b10 + a[7] * b09) * d; o[1] = (a[2] * b10 - a[1] * b11 - a[3] * b09) * d; o[2] = (a[13] * b05 - a[14] * b04 + a[15] * b03) * d; o[3] = (a[10] * b04 - a[9] * b05 - a[11] * b03) * d;
  o[4] = (a[6] * b08 - a[4] * b11 - a[7] * b07) * d; o[5] = (a[0] * b11 - a[2] * b08 + a[3] * b07) * d; o[6] = (a[14] * b02 - a[12] * b05 - a[15] * b01) * d; o[7] = (a[8] * b05 - a[10] * b02 + a[11] * b01) * d;
  o[8] = (a[4] * b10 - a[5] * b08 + a[7] * b06) * d; o[9] = (a[1] * b08 - a[0] * b10 - a[3] * b06) * d; o[10] = (a[12] * b04 - a[13] * b02 + a[15] * b00) * d; o[11] = (a[9] * b02 - a[8] * b04 - a[11] * b00) * d;
  o[12] = (a[5] * b07 - a[4] * b09 - a[6] * b06) * d; o[13] = (a[0] * b09 - a[1] * b07 + a[2] * b06) * d; o[14] = (a[13] * b01 - a[12] * b03 - a[14] * b00) * d; o[15] = (a[8] * b03 - a[9] * b01 + a[10] * b00) * d;
  return o;
}
function planes(m) {
  const p = []; const r = (i) => [m[i], m[4 + i], m[8 + i], m[12 + i]];
  const r0 = r(0), r1 = r(1), r2 = r(2), r3 = r(3);
  for (const [a, s] of [[r0, 1], [r0, -1], [r1, 1], [r1, -1], [r2, 1], [r2, -1]]) { const q = [r3[0] + s * a[0], r3[1] + s * a[1], r3[2] + s * a[2], r3[3] + s * a[3]]; const l = Math.hypot(q[0], q[1], q[2]); p.push(q.map((v) => v / l)); }
  return p;
}
const visible = (P, x, y, z, rad) => { for (const p of P) if (p[0] * x + p[1] * y + p[2] * z + p[3] < -rad) return false; return true; };

// ======================= render setup =======================
const SH = 2048;
const shadowTex = gl.createTexture(); gl.bindTexture(gl.TEXTURE_2D, shadowTex);
gl.texStorage2D(gl.TEXTURE_2D, 1, gl.DEPTH_COMPONENT24, SH, SH);
gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_COMPARE_MODE, gl.COMPARE_REF_TO_TEXTURE); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_COMPARE_FUNC, gl.LEQUAL);
gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
const shadowFB = gl.createFramebuffer(); gl.bindFramebuffer(gl.FRAMEBUFFER, shadowFB);
gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.DEPTH_ATTACHMENT, gl.TEXTURE_2D, shadowTex, 0);
gl.drawBuffers([gl.NONE]); gl.readBuffer(gl.NONE);
gl.bindFramebuffer(gl.FRAMEBUFFER, null);
MEM.shadow = SH * SH * 4;
const instBuf = gl.createBuffer(); let instCap = 0;
const cubeBuf = gl.createBuffer(); {
  const v = []; const F = [[0, 1, 2, 0, 2, 3]];
  const c = [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0], [0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1]];
  const faces = [[0, 3, 2, 1], [4, 5, 6, 7], [0, 1, 5, 4], [3, 7, 6, 2], [0, 4, 7, 3], [1, 2, 6, 5]];
  for (const f of faces) for (const k of [0, 1, 2, 0, 2, 3]) v.push(...c[f[k]]);
  gl.bindBuffer(gl.ARRAY_BUFFER, cubeBuf); gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(v), gl.STATIC_DRAW);
}
const partBuf = gl.createBuffer();
const vao = gl.createVertexArray();

const SUN = (() => { const v = [0.45, 0.62, 0.38]; const l = Math.hypot(...v); return v.map((x) => x / l); })();
function resize() {
  const dpr = Math.min(window.devicePixelRatio || 1, 1) * Q.scale;
  canvas.width = Math.round(canvas.clientWidth * dpr); canvas.height = Math.round(canvas.clientHeight * dpr);
}
window.addEventListener('resize', resize); resize();

let stats = { tris: 0, draws: 0, traced: 0, terr: 0 };
function bindMesh(mesh) {
  gl.bindBuffer(gl.ARRAY_BUFFER, mesh.b);
  gl.enableVertexAttribArray(0); gl.vertexAttribPointer(0, 3, gl.SHORT, false, 8, 0);
  gl.enableVertexAttribArray(1); gl.vertexAttribPointer(1, 2, gl.UNSIGNED_BYTE, false, 8, 6);
}
function setModuleUniforms(pr, mod, base) {
  gl.uniform3i(pr.u.u_nb, mod.nbx, mod.nby, mod.nbz); gl.uniform3i(pr.u.u_mmin, mod.ox, mod.oy, mod.oz);
  gl.uniform3i(pr.u.u_mdim, mod.dx, mod.dy, mod.dz); gl.uniform1i(pr.u.u_base, base);
}
// LOD: 0 = micro-traced (8 cm faces, 2 cm per pixel) < 30 m < 1 = 8 cm raster < 60 m < 2 = 16 cm raster
function lodFor(d) { const s = Q.dist; return d < 25 * s ? 0 : d < 40 * s ? 1 : d < 75 * s ? 2 : 3; }
const LODSTEP = [0, 4, 8, 16];
function setCommon(pr, vp, lvp) {
  gl.useProgram(pr.p);
  const u = pr.u;
  gl.uniformMatrix4fv(u.u_vp, false, vp);
  if (u.u_lvp) gl.uniformMatrix4fv(u.u_lvp, false, lvp);
  gl.uniform3f(u.u_cam, camX, camY, camZ); gl.uniform1f(u.u_vs, VS);
  if (u.u_camvox) gl.uniform3f(u.u_camvox, camX / VS, camY / VS, camZ / VS);
  if (u.u_atlas) {
    gl.uniform1i(u.u_atlas, 0); gl.uniform1i(u.u_indir, 1); gl.uniform1i(u.u_pal, 2); gl.uniform1i(u.u_shadow, 3); gl.uniform1i(u.u_bpal, 4);
    gl.uniform1i(u.u_ao, Q.ao ? 1 : 0); gl.uniform1i(u.u_shadows, Q.shadows ? 1 : 0);
    gl.uniform3fv(u.u_sun, SUN); gl.uniform3f(u.u_sunCol, 2.5, 2.2, 1.8); gl.uniform1f(u.u_fog, 0.0022);
  }
}
function drawScene(shadowPass, vp, lvp, P) {
  const PR = shadowPass ? PS : P_RASTER, PRT = shadowPass ? PS : PT;
  setCommon(PR, vp, lvp);
  // terrain
  gl.disableVertexAttribArray(2); gl.vertexAttrib4f(2, 0, 0, 0, 0);
  if (PR.u.u_mode) gl.uniform1i(PR.u.u_mode, 1);
  for (const nd of (shadowPass ? [] : tdraw)) {
    const S = nd.S * VS, cx = nd.x0 * VS + S / 2 - camX, cz = nd.z0 * VS + S / 2 - camZ;
    const hy = heightAt(nd.x0 + (nd.S >> 1), nd.z0 + (nd.S >> 1)) * VS - camY;
    if (!visible(P, cx, hy, cz, S * 0.75 + 15)) continue;
    bindMesh(nd.mesh); gl.drawElements(gl.TRIANGLES, nd.mesh.quads * 6, gl.UNSIGNED_INT, 0);
    stats.draws++; stats.tris += nd.mesh.quads * 2; stats.terr += nd.mesh.quads * 2;
  }
  if (PR.u.u_mode) gl.uniform1i(PR.u.u_mode, 0);
  // unedited instances: bucket by module and LOD, one instanced draw per bucket
  const data = []; const draws = [];
  for (const mod of usedMods) {
    if (!mod.instances.length) continue;
    const buckets = [[], [], [], []];
    for (const inst of mod.instances) {
      const x = inst.cx - camX, y = inst.cy - camY, z = inst.cz - camZ;
      if (!visible(P, x, y, z, inst.rad)) continue;
      const d = Math.max(0, Math.hypot(x, y, z) - inst.rad * 0.5);
      let l = lodFor(d); if (shadowPass) l = Math.min(3, Math.max(l + 1, 1));
      while (l > 0 && !mod.lod[l]) l--;
      if (l === 0 && !mod.lod[0]) continue;
      buckets[l].push(inst);
    }
    for (let l = 0; l < 4; l++) if (buckets[l].length && mod.lod[l]) {
      draws.push([mod, l, data.length / 4, buckets[l].length]);
      for (const i of buckets[l]) data.push(i.x, i.y, i.z, i.r);
    }
  }
  const arr = new Float32Array(data);
  gl.bindBuffer(gl.ARRAY_BUFFER, instBuf);
  if (arr.byteLength > instCap) { instCap = arr.byteLength * 2; gl.bufferData(gl.ARRAY_BUFFER, instCap, gl.DYNAMIC_DRAW); }
  gl.bufferSubData(gl.ARRAY_BUFFER, 0, arr);
  for (const pass of [0, 1]) {          // raster LODs first, then the traced ring
    const pr = pass === 0 ? PR : PRT;
    if (pass === 1) setCommon(pr, vp, lvp);
    for (const [mod, l, off, n] of draws) {
      if ((l === 0) !== (pass === 1)) continue;
      const mesh = mod.lod[l];
      if (pr.u.u_nb) { setModuleUniforms(pr, mod, mod.base); if (pr.u.u_lodstep) gl.uniform1i(pr.u.u_lodstep, LODSTEP[l]); }
      bindMesh(mesh);
      gl.bindBuffer(gl.ARRAY_BUFFER, instBuf);
      gl.enableVertexAttribArray(2); gl.vertexAttribPointer(2, 4, gl.FLOAT, false, 16, off * 16); gl.vertexAttribDivisor(2, 1);
      gl.drawElementsInstanced(gl.TRIANGLES, mesh.quads * 6, gl.UNSIGNED_INT, 0, n);
      stats.draws++; stats.tris += mesh.quads * 2 * n;
      if (l === 0) stats.traced += n; stats['l' + l] = (stats['l' + l] || 0) + mesh.quads * 2 * n;
    }
    gl.vertexAttribDivisor(2, 0); gl.disableVertexAttribArray(2);
  }
  // edited instances (own bricks, own trace mesh)
  for (const inst of editedList) {
    if (!inst.mesh) continue;
    const x = inst.cx - camX, y = inst.cy - camY, z = inst.cz - camZ;
    if (!visible(P, x, y, z, inst.rad)) continue;
    gl.vertexAttrib4f(2, inst.x, inst.y, inst.z, inst.r);
    if (PRT.u.u_nb) setModuleUniforms(PRT, inst.mod, inst.base);
    bindMesh(inst.mesh); gl.drawElements(gl.TRIANGLES, inst.mesh.quads * 6, gl.UNSIGNED_INT, 0);
    stats.draws++; stats.tris += inst.mesh.quads * 2;
  }
}

// ======================= HUD =======================
const fmtB = (b) => b > 1048576 ? (b / 1048576).toFixed(1) + ' Mo' : (b / 1024).toFixed(0) + ' Ko';
let meshCPU = 0; for (const m of usedMods) for (const v of m.chunkMeshes.values()) meshCPU += v.byteLength;
let virtualVox = 0; for (const i of instances) virtualVox += i.mod.nvox;
let uniqueVox = 0; for (const m of usedMods) uniqueVox += m.nvox;
const LOAD_MS = performance.now() - T0;
$('info').innerHTML = `<b>GPU :</b> ${GPU_NAME}<br>` +
  `<b>Téléchargé :</b> ${fmtB(DOWNLOAD)} (données ${fmtB(RAW_BYTES)} décompressées) · chargement ${(LOAD_MS / 1000).toFixed(1)} s<br>` +
  `<b>Modules uniques :</b> ${usedMods.length} · <b>instances :</b> ${instances.length}<br>` +
  `<b>Voxels du village :</b> ${(virtualVox / 1e6).toFixed(0)} M (dont ${(uniqueVox / 1e6).toFixed(1)} M stockés une fois) + terrain procédural`;
let fpsN = 0, fpsT = performance.now(), fps = 0, cpuMs = 0, gpuMs = -1, tqObj = null, tqPending = false;
function hud() {
  const mem = MEM.atlas + MEM.indir + MEM.vbo + MEM.shadow + MEM.idx;
  let cpuNow = pool.idx.byteLength + pool.pal.byteLength; for (const m of W.mods) cpuNow += m.bricks.byteLength; for (const i of editedList) cpuNow += i.bricks.byteLength;
  $('stats').innerHTML = `<b>${fps.toFixed(0)} img/s</b> · CPU ${cpuMs.toFixed(1)} ms · GPU ${gpuMs >= 0 ? gpuMs.toFixed(1) + ' ms' : 'n/d'}<br>` +
    `${(stats.tris / 1e6).toFixed(2)} M triangles · ${stats.draws} appels · ${stats.traced} modules micro-tracés · ${canvas.width}×${canvas.height}<br>` +
    `<b>Mémoire GPU :</b> ${fmtB(mem)} (atlas ${fmtB(MEM.atlas)}, maillages ${fmtB(MEM.vbo)}, ombre ${fmtB(MEM.shadow)})<br>` +
    `<b>Mémoire voxels CPU :</b> ${fmtB(cpuNow)} · briques mixtes ${pool.n}<br>` +
    `<b>Destruction :</b> ${(voxelsRemoved / 1000).toFixed(1)} k voxels retirés · ${editedCount} modules copiés à l'écriture` +
    (player.fly ? '<br><i>Mode vol (F)</i>' : '');
}

// ======================= benchmark (B) =======================
let bench = null;
function startBench() {
  if (bench) return;
  player.fly = true; bench = { t0: performance.now(), times: [], gpu: [] };
  $('bench').style.display = 'block'; $('bench').textContent = 'Mesure en cours : tour du village pendant 20 s…';
}
function benchStep(now, dtMs) {
  const t = (now - bench.t0) / 20000;
  if (t >= 1) {
    const a = bench.times.slice().sort((x, y) => x - y), n = a.length;
    const avg = a.reduce((s, x) => s + x, 0) / n, p95 = a[Math.floor(n * 0.95)], p99 = a[Math.floor(n * 0.99)];
    const g = bench.gpu.filter((x) => x >= 0); const gavg = g.length ? g.reduce((s, x) => s + x, 0) / g.length : -1;
    $('bench').innerHTML = `<b>Résultat (20 s, ${canvas.width}×${canvas.height})</b><br>Moyenne ${(1000 / avg).toFixed(0)} img/s (${avg.toFixed(1)} ms) · 95 % des images < ${p95.toFixed(1)} ms · 99 % < ${p99.toFixed(1)} ms<br>GPU ${gavg >= 0 ? gavg.toFixed(1) + ' ms' : 'non mesurable sur ce navigateur'} · ${GPU_NAME}<br><small>Cliquez pour fermer.</small>`;
    $('bench').onclick = () => { $('bench').style.display = 'none'; };
    bench = null; player.fly = false; return;
  }
  bench.times.push(dtMs); bench.gpu.push(gpuMs);
  const a = t * Math.PI * 2, r = 22 * M;
  player.x = CX + Math.cos(a) * r; player.z = CZ + Math.sin(a) * r;
  player.y = heightAt(player.x | 0, player.z | 0) + 2.2 * M + Math.sin(a * 3) * 1.5 * M;
  player.yaw = -a + Math.PI * 0.15; player.pitch = -0.12;
}
window.addEventListener('load', () => {});

// ======================= main loop =======================
let last = performance.now();
$('loading').style.display = 'none';
function frame(now) {
  const t0 = performance.now();
  const dtMs = now - last; const dt = Math.min(0.05, dtMs / 1000); last = now;
  if (bench) benchStep(now, dtMs);
  // --- player
  const sp = (keys.ShiftLeft || keys.ShiftRight ? 9 : 4.5) / VS * (player.fly ? 2.5 : 1);
  const fx = -Math.sin(player.yaw), fz = -Math.cos(player.yaw);
  let mx = 0, mz = 0;
  if (keys.KeyW || keys.KeyZ || keys.ArrowUp) { mx += fx; mz += fz; }
  if (keys.KeyS || keys.ArrowDown) { mx -= fx; mz -= fz; }
  if (keys.KeyA || keys.KeyQ || keys.ArrowLeft) { mx += fz; mz -= fx; }
  if (keys.KeyD || keys.ArrowRight) { mx -= fz; mz += fx; }
  const ml = Math.hypot(mx, mz) || 1;
  player.vx = mx / ml * sp; player.vz = mz / ml * sp;
  if (player.fly) {
    player.vy = (keys.Space ? sp : 0) - (keys.ControlLeft || keys.KeyC ? sp : 0);
  } else {
    if (keys.Space && player.ground) player.vy = 6.2 / VS;
    player.vy -= 22 / VS * dt; player.vy = Math.max(player.vy, -40 / VS);
  }
  player.ground = false;
  moveAxis(0, player.vx * dt); moveAxis(2, player.vz * dt); moveAxis(1, player.vy * dt);
  player.eyeSmooth *= Math.pow(0.0005, dt);
  camX = player.x * VS; camY = (player.y + EYE + player.eyeSmooth) * VS; camZ = player.z * VS;
  const fwd = [-Math.sin(player.yaw) * Math.cos(player.pitch), Math.sin(player.pitch), -Math.cos(player.yaw) * Math.cos(player.pitch)];
  // --- dig
  if (digging && now - lastDig > 110) {
    lastDig = now;
    const h = raycast(camX / VS, camY / VS, camZ / VS, fwd[0], fwd[1], fwd[2], 7 / VS);
    if (h) carve(h.x, h.y, h.z);
  }
  // --- rebuild edited instance meshes
  for (const inst of editedList) if (inst.meshDirty) { inst.meshDirty = false; const old = inst.mesh; inst.mesh = makeMesh(concat([...inst.chunks.values()])); freeMesh(old); }
  // --- particles
  for (let i = parts.length - 1; i >= 0; i--) {
    const p = parts[i]; p.life -= dt; if (p.life <= 0) { parts.splice(i, 1); continue; }
    p.vy -= 18 * dt; const nx = p.x + p.vx * dt, ny = p.y + p.vy * dt, nz = p.z + p.vz * dt;
    if (solid(Math.floor(nx / VS), Math.floor(ny / VS), Math.floor(nz / VS))) { p.vy *= -0.25; p.vx *= 0.5; p.vz *= 0.5; } else { p.x = nx; p.y = ny; p.z = nz; }
  }
  selectTerrain(now);
  // --- matrices (camera-relative)
  const proj = persp(70 * Math.PI / 180, canvas.width / canvas.height, 0.05, 900);
  const view = lookDir(fwd, [0, 1, 0]);
  const vp = mul(proj, view);
  const Pc = planes(vp);
  // light: ortho box of 110 m around the camera, snapped to texels
  const lview = lookDir([-SUN[0], -SUN[1], -SUN[2]], [0, 1, 0]);
  const ext = 55, texel = 2 * ext / SH;
  const lc = [lview[0] * camX + lview[4] * camY + lview[8] * camZ, lview[1] * camX + lview[5] * camY + lview[9] * camZ];
  const sx = (Math.round(lc[0] / texel) * texel - lc[0]), sy = (Math.round(lc[1] / texel) * texel - lc[1]);
  const lproj = ortho(-ext + sx, ext + sx, -ext + sy, ext + sy, -150, 150);
  const lvp = mul(lproj, lview);
  stats = { tris: 0, draws: 0, traced: 0, terr: 0 };
  gl.bindVertexArray(vao);
  gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, ibo);
  gl.enable(gl.DEPTH_TEST); gl.enable(gl.CULL_FACE); gl.cullFace(gl.BACK);
  if (tq && !tqPending) { tqObj = gl.createQuery(); gl.beginQuery(tq.TIME_ELAPSED_EXT, tqObj); }
  if (Q.shadows) {
    gl.activeTexture(gl.TEXTURE3); gl.bindTexture(gl.TEXTURE_2D, null);
    gl.bindFramebuffer(gl.FRAMEBUFFER, shadowFB); gl.viewport(0, 0, SH, SH);
    gl.clear(gl.DEPTH_BUFFER_BIT); gl.enable(gl.POLYGON_OFFSET_FILL); gl.polygonOffset(1.5, 3);
    gl.cullFace(gl.FRONT);
    drawScene(true, lvp, lvp, planes(lvp));
    gl.disable(gl.POLYGON_OFFSET_FILL); gl.cullFace(gl.BACK);
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
  }
  gl.viewport(0, 0, canvas.width, canvas.height);
  gl.clear(gl.DEPTH_BUFFER_BIT);
  // sky
  gl.disable(gl.DEPTH_TEST); gl.useProgram(PK.p);
  gl.uniformMatrix4fv(PK.u.u_ivp, false, inv(vp)); gl.uniform3fv(PK.u.u_sun, SUN);
  gl.drawArrays(gl.TRIANGLES, 0, 3); gl.enable(gl.DEPTH_TEST);
  // world
  gl.activeTexture(gl.TEXTURE0); gl.bindTexture(gl.TEXTURE_3D, atlas);
  gl.activeTexture(gl.TEXTURE1); gl.bindTexture(gl.TEXTURE_2D, indir);
  gl.activeTexture(gl.TEXTURE2); gl.bindTexture(gl.TEXTURE_2D, palTex);
  gl.activeTexture(gl.TEXTURE3); gl.bindTexture(gl.TEXTURE_2D, shadowTex);
  gl.activeTexture(gl.TEXTURE4); gl.bindTexture(gl.TEXTURE_2D, bpal);
  drawScene(false, vp, lvp, Pc);
  // particles
  if (parts.length) {
    const pd = new Float32Array(parts.length * 8);
    parts.forEach((p, i) => { pd.set([p.x, p.y, p.z, p.s, p.c[0], p.c[1], p.c[2], 1], i * 8); });
    gl.useProgram(PP.p); gl.uniformMatrix4fv(PP.u.u_vp, false, vp); gl.uniform3f(PP.u.u_cam, camX, camY, camZ); gl.uniform3fv(PP.u.u_sun, SUN);
    gl.bindBuffer(gl.ARRAY_BUFFER, cubeBuf); gl.enableVertexAttribArray(0); gl.vertexAttribPointer(0, 3, gl.FLOAT, false, 12, 0); gl.vertexAttribDivisor(0, 0);
    gl.bindBuffer(gl.ARRAY_BUFFER, partBuf); gl.bufferData(gl.ARRAY_BUFFER, pd, gl.STREAM_DRAW);
    gl.enableVertexAttribArray(1); gl.vertexAttribPointer(1, 4, gl.FLOAT, false, 32, 0); gl.vertexAttribDivisor(1, 1);
    gl.enableVertexAttribArray(2); gl.vertexAttribPointer(2, 4, gl.FLOAT, false, 32, 16); gl.vertexAttribDivisor(2, 1);
    gl.disable(gl.CULL_FACE);
    gl.drawArraysInstanced(gl.TRIANGLES, 0, 36, parts.length);
    gl.enable(gl.CULL_FACE);
    gl.vertexAttribDivisor(1, 0); gl.vertexAttribDivisor(2, 0); gl.disableVertexAttribArray(2);
  }
  if (tq) {
    if (!tqPending && tqObj) { gl.endQuery(tq.TIME_ELAPSED_EXT); tqPending = true; }
    else if (tqPending && gl.getQueryParameter(tqObj, gl.QUERY_RESULT_AVAILABLE)) {
      if (!gl.getParameter(tq.GPU_DISJOINT_EXT)) gpuMs = gpuMs < 0 ? gl.getQueryParameter(tqObj, gl.QUERY_RESULT) / 1e6 : gpuMs * 0.9 + 0.1 * gl.getQueryParameter(tqObj, gl.QUERY_RESULT) / 1e6;
      gl.deleteQuery(tqObj); tqObj = null; tqPending = false;
    }
  }
  cpuMs = cpuMs * 0.9 + 0.1 * (performance.now() - t0);
  fpsN++; if (now - fpsT > 500) { fps = fpsN * 1000 / (now - fpsT); fpsN = 0; fpsT = now; hud(); }
  let tv = 0; for (const nd of TNODES.values()) if (nd.mesh) tv += nd.mesh.bytes;
  window.__stats = { st: stats, tnodes: TNODES.size, tdraw: tdraw.length, tvbo: tv, fps, cpuMs, gpuMs, tris: stats.tris, draws: stats.draws, mem: MEM, terrainPending, parts: parts.length, removed: voxelsRemoved };
  requestAnimationFrame(frame);
}
// test hooks (used by automated screenshots)
window.__game = { startBench, player, carve, raycast, keys, Q, setTool: (t) => { tool = t; updTool(); }, get cam() { return [camX, camY, camZ]; }, M, CX, CZ, heightAt, instances };
requestAnimationFrame(frame);
})().catch((e) => { console.error(e); document.getElementById('loadmsg').textContent = 'Erreur : ' + e.message; });
