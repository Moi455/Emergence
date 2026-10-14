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

const Q = { scale: 1.0, shadows: true, ao: true, dist: 1.0, bloom: true };   // quality settings
const QS = new URLSearchParams(location.search); if (QS.get('scale')) Q.scale = +QS.get('scale');
const MEM = { skyvol: 0, vbo: 0, shadow: 0, idx: 0, hdr: 0 };

function sh(type, src) {
  const s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s);
  if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s) + '\n' + src.split('\n').map((l, i) => (i + 1) + ': ' + l).join('\n'));
  return s;
}
function prog(vs, fs) {
  const p = gl.createProgram(); gl.attachShader(p, sh(gl.VERTEX_SHADER, vs)); gl.attachShader(p, sh(gl.FRAGMENT_SHADER, fs));
  gl.bindAttribLocation(p, 0, 'a_pos'); gl.bindAttribLocation(p, 1, 'a_fa'); gl.bindAttribLocation(p, 2, 'a_bn');
  gl.bindAttribLocation(p, 3, 'a_vid'); gl.bindAttribLocation(p, 4, 'a_inst');
  gl.linkProgram(p);
  if (!gl.getProgramParameter(p, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(p));
  const u = {}; const n = gl.getProgramParameter(p, gl.ACTIVE_UNIFORMS);
  for (let i = 0; i < n; i++) { const a = gl.getActiveUniform(p, i); u[a.name.replace('[0]', '')] = gl.getUniformLocation(p, a.name); }
  return { p, u };
}

// ============================================================================
// Shading model
//   ambient : sky light reconstructed from an order-1 spherical harmonic. Each vertex
//             carries its own baked visibility (openness + bent normal), and a coarse
//             world volume carries how much sky reaches that point through the village.
//             Changing the hour only changes four RGB numbers on the CPU, so a full
//             day/night cycle costs nothing per pixel.
//   sun     : one shadow map, cheap now that the geometry is 10 cm voxels.
//   surface : per-class roughness and metalness, a procedural grain and a bevel on each
//             voxel edge. No bitmap textures: the detail is generated, so it costs no
//             memory and keeps the voxel look.
// ============================================================================
const SKY_COMMON = `
uniform vec3 u_zen, u_hor, u_grnd, u_sunCol, u_sun; uniform float u_haze;
vec3 skyCol(vec3 d){
  float up = clamp(d.y, -1.0, 1.0);
  float mu = dot(d, u_sun);
  vec3 c = mix(u_hor, u_zen, pow(clamp(up, 0.0, 1.0), 0.42));
  c += u_sunCol * (0.22 * pow(max(mu, 0.0), 10.0) + 0.05 * pow(max(mu, 0.0), 2.5)) * u_haze;
  c = mix(u_grnd, c, smoothstep(-0.12, 0.02, up));
  return c;
}`;

const NOISE = `
float h31(vec3 p){ p = fract(p * 0.3183099 + vec3(0.71, 0.113, 0.419)); p *= 17.0; return fract(p.x * p.y * p.z * (p.x + p.y + p.z)); }
float vn3(vec3 x){
  vec3 i = floor(x), f = fract(x); f = f * f * (3.0 - 2.0 * f);
  return mix(mix(mix(h31(i + vec3(0,0,0)), h31(i + vec3(1,0,0)), f.x), mix(h31(i + vec3(0,1,0)), h31(i + vec3(1,1,0)), f.x), f.y),
             mix(mix(h31(i + vec3(0,0,1)), h31(i + vec3(1,0,1)), f.x), mix(h31(i + vec3(0,1,1)), h31(i + vec3(1,1,1)), f.x), f.y), f.z);
}`;

const VERT = `#version 300 es
precision highp float;
layout(location=0) in vec3 a_pos;     // voxel units
layout(location=1) in vec2 a_fa;      // face index, baked openness
layout(location=2) in vec4 a_bn;      // bent normal (the average direction the sky comes from)
layout(location=3) in float a_vid;    // VoxelId: class << 7 | tint
layout(location=4) in vec4 a_inst;    // instance origin (voxels) and quarter turns
uniform mat4 u_vp; uniform mat4 u_lvp; uniform vec3 u_cam; uniform float u_vs;
out vec3 v_rel; out vec3 v_vox; out vec3 v_bn; out float v_ao; out vec4 v_ls;
flat out vec3 v_n; flat out float v_vid;
const vec3 NRM[6] = vec3[6](vec3(1,0,0),vec3(-1,0,0),vec3(0,1,0),vec3(0,-1,0),vec3(0,0,1),vec3(0,0,-1));
vec3 rot(vec3 p, int r){ if(r==1) return vec3(p.z,p.y,-p.x); if(r==2) return vec3(-p.x,p.y,-p.z); if(r==3) return vec3(-p.z,p.y,p.x); return p; }
void main(){
  int r = int(a_inst.w + 0.5);
  vec3 vox = rot(a_pos, r) + a_inst.xyz;
  vec3 w = vox * u_vs - u_cam;
  v_vox = vox; v_rel = w; v_ao = a_fa.y * (1.0 / 255.0);
  v_n = rot(NRM[int(a_fa.x + 0.5)], r);
  v_bn = rot(a_bn.xyz, r);
  v_vid = a_vid;
  v_ls = u_lvp * vec4(w + v_n * 0.08, 1.0);
  gl_Position = u_vp * vec4(w, 1.0);
}`;

const FRAG = `#version 300 es
precision highp float; precision highp sampler2DShadow; precision highp sampler3D;
in vec3 v_rel; in vec3 v_vox; in vec3 v_bn; in float v_ao; in vec4 v_ls;
flat in vec3 v_n; flat in float v_vid;
uniform sampler2D u_pal; uniform sampler2DShadow u_shadow; uniform sampler3D u_skyvol;
uniform vec3 u_volMin, u_volScale;       // world metres -> [0,1] in the sky volume
uniform vec3 u_shL0, u_shL1r, u_shL1g, u_shL1b;   // sky irradiance, order 1
uniform vec3 u_cam; uniform float u_vs; uniform float u_fog; uniform int u_shadows; uniform int u_ao;
uniform vec4 u_mat[21];                  // roughness, metalness, grain scale, grain amount
uniform vec4 u_fires[6];                 // xyz camera-relative, w radiant power (0 = off)
uniform float u_exposure; uniform float u_glow;
out vec4 o;
` + SKY_COMMON + NOISE + `
float shadowAt(vec4 ls){
  vec3 p = ls.xyz / ls.w * 0.5 + 0.5;
  if (p.x < 0.002 || p.x > 0.998 || p.y < 0.002 || p.y > 0.998 || p.z > 1.0) return 1.0;
  float s = 0.0; vec2 t = vec2(1.0 / 2048.0);
  for (int j = -1; j <= 1; j++) for (int i = -1; i <= 1; i++) s += texture(u_shadow, vec3(p.xy + vec2(float(i), float(j)) * t, p.z - 0.00035));
  return s / 9.0;
}
// irradiance of the sky arriving on a surface whose open direction is b
vec3 skyIrr(vec3 b){
  const float A0 = 0.886227 * 0.3183099, A1 = 1.023328 * 0.3183099;   // the 1/pi of a Lambert surface
  return max(vec3(0.0), A0 * u_shL0 + A1 * vec3(dot(u_shL1r, b), dot(u_shL1g, b), dot(u_shL1b, b)));
}
void main(){
  int vid = int(v_vid + 0.5); int cls = vid >> 7; int tint = vid & 127;
  vec3 alb = texture(u_pal, vec3(0.0).xy + vec2((float(tint) + 0.5) / 128.0, (float(cls) + 0.5) / 21.0)).rgb;
  alb = pow(alb, vec3(2.2));
  vec4 mt = u_mat[cls];
  vec3 n = v_n, b = normalize(v_bn);
  vec3 wpos = v_rel + u_cam;

  // --- surface detail, generated rather than sampled: a grain plus a bevel on every voxel edge.
  // Beyond ~20 m a voxel is smaller than a pixel, so the detail is faded out rather than aliased.
  float dist = length(v_rel);
  float det = 1.0 - smoothstep(14.0, 55.0, dist);
  vec3 cell = fract(v_vox);
  vec3 ax = abs(n);
  vec2 uv = ax.x > 0.5 ? cell.zy : (ax.y > 0.5 ? cell.xz : cell.xy);
  float edge = min(min(uv.x, 1.0 - uv.x), min(uv.y, 1.0 - uv.y));
  float bevel = mix(1.0, smoothstep(0.0, 0.14, edge) * 0.22 + 0.78, det);
  float g = vn3(v_vox * mt.z) * 0.6 + vn3(v_vox * mt.z * 3.1) * 0.4;
  float grain = 1.0 + (g - 0.5) * mt.w * 0.5 * det;
  // a slow stain over metres, which survives distance and breaks up the large flat areas
  float macro = vn3(wpos * 0.33) * 0.62 + vn3(wpos * 0.097) * 0.38;
  alb *= grain * bevel * (0.88 + 0.24 * macro);

  // --- what reads as texture in a voxel world is colour per voxel: every voxel and every stone
  // has its own shade, moss gathers where the sky falls and the damp stays, grime where it does not.
  // All of it is decided per voxel, so it stays blocky, and none of it is stored.
  float det2 = 1.0 - smoothstep(45.0, 130.0, dist);
  vec3 vc = floor(v_vox - n * 0.5);                  // the voxel this face belongs to
  float hvx = h31(vc + 0.5);
  float row = floor(vc.y / 2.0), off = mod(row, 2.0);
  float hs = h31(vec3(floor((vc.x + off) / 3.0), row, floor((vc.z + off) / 3.0)) + 7.31);   // stones in courses
  bool stony = cls == 4 || cls == 5 || cls == 6 || cls == 7 || cls == 18 || cls == 19 || cls == 20;
  bool woody = cls == 2 || cls == 3 || cls == 13;
  bool tiles = cls == 8;
  bool plant = cls == 11 || cls == 12 || cls == 16;
  float vVox = stony ? 0.10 : woody ? 0.13 : tiles ? 0.16 : plant ? 0.17 : 0.06;
  float vStone = stony ? 0.30 : woody ? 0.12 : tiles ? 0.12 : 0.0;
  float shade = 1.0 + (hvx - 0.5) * 2.0 * vVox + (hs - 0.5) * 2.0 * vStone;
  vec3 hue = vec3(1.0 + (hs - 0.5) * 0.12, 1.0, 1.0 - (hs - 0.5) * 0.12);
  if (plant) hue = mix(vec3(0.82, 1.0, 0.80), vec3(1.25, 1.10, 0.66), hvx * hvx);   // dark blades and dry ones
  alb *= mix(vec3(1.0), shade * hue, det2);
  if (cls == 16) alb *= mix(vec3(0.74, 0.92, 0.66), vec3(1.18, 1.06, 0.66), smoothstep(0.30, 0.75, macro));
  float mossy = (stony || tiles || cls == 3 || cls == 13) ? 1.0 : 0.0;
  float mn = vn3((vc + 0.5) * 0.13) * 0.7 + hvx * 0.3;
  float moss = mossy * smoothstep(0.60, 0.80, mn + max(n.y, 0.0) * 0.16 + (1.0 - v_ao) * 0.30 - 0.08);
  alb = mix(alb, vec3(0.050, 0.082, 0.020) * (0.7 + 0.6 * hvx), moss * 0.85 * det2);
  float grime = clamp((1.0 - v_ao) * 1.2 - 0.12, 0.0, 1.0);
  alb *= mix(vec3(1.0), vec3(0.60, 0.53, 0.45), grime * 0.6);
  float rough = clamp(mt.x * (0.85 + 0.3 * g), 0.04, 1.0);

  // --- ambient: baked openness at the vertex, times how much sky reaches this spot in the village
  vec3 vp = (wpos + n * 1.4 - u_volMin) * u_volScale;
  float vol = all(greaterThan(vp, vec3(0.0))) && all(lessThan(vp, vec3(1.0))) ? texture(u_skyvol, vp).r : 1.0;
  float ao = u_ao == 1 ? v_ao : 1.0;
  if (cls == 12) ao = mix(ao, 1.0, 0.35);
  vec3 amb = skyIrr(b) * alb * (ao * mix(0.25, 1.0, vol));

  // --- sun
  float ndl = max(dot(n, u_sun), 0.0);
  float sh = (u_shadows == 1 && ndl > 0.0) ? shadowAt(v_ls) : 1.0;
  vec3 dir = u_sunCol * 0.3183099 * ndl * sh;
  vec3 col = amb + dir * alb;
  if (cls == 12 || cls == 16 && dist < 40.0) {          // light through leaves and blades, towards the viewer
    float back = pow(max(dot(normalize(v_rel), u_sun), 0.0), 3.0);
    col += alb * u_sunCol * 0.3183099 * back * (cls == 12 ? 0.9 : 0.35) * (0.4 + 0.6 * v_ao);
  }

  // --- specular: the sun as a rough highlight, plus the sky seen in the surface
  vec3 vdir = normalize(-v_rel);
  vec3 hv = normalize(vdir + u_sun);
  float a2 = rough * rough * rough * rough;
  float d = (dot(n, hv) * dot(n, hv)) * (a2 - 1.0) + 1.0;
  float spec = a2 / (3.14159 * d * d + 1e-4);
  float f0 = mix(0.035, 1.0, mt.y);
  float fmax = max(1.0 - rough, f0);                        // rough stone keeps its colour at grazing angles
  float fres = f0 + (fmax - f0) * pow(1.0 - max(dot(vdir, n), 0.0), 5.0);
  vec3 tintSpec = mix(vec3(1.0), alb, mt.y);
  col += u_sunCol * sh * ndl * spec * fres * tintSpec * 0.9;
  vec3 refl = reflect(-vdir, n);
  col += skyCol(normalize(mix(refl, b, rough * 0.85))) * fres * mix(0.25, 1.0, mt.y) * mix(0.35, 1.0, vol) * (1.0 - rough * 0.65) * tintSpec;

  // --- lit windows: from late afternoon the glass glows with the hearth behind it
  if (cls == 10) col += vec3(1.0, 0.50, 0.17) * u_glow * (0.55 + 0.45 * hvx) * 2.2;

  // --- braziers: a few warm point lights, the only lighting that is not precomputed
  for (int i = 0; i < 6; i++) {
    if (u_fires[i].w <= 0.0) continue;
    vec3 dv = u_fires[i].xyz - v_rel; float d2 = dot(dv, dv);
    if (d2 > 121.0) continue;                               // a brazier lights eleven metres, no more
    float att = u_fires[i].w / (d2 + 0.6) * (1.0 - d2 / 121.0);
    col += vec3(1.0, 0.52, 0.19) * alb * att * max(dot(n, dv * inversesqrt(d2)), 0.0);
  }

  // --- aerial perspective
  float f = 1.0 - exp(-max(dist - 25.0, 0.0) * u_fog);
  col = mix(col, skyCol(normalize(v_rel)) * 0.92, f * 0.86);
  o = vec4(col * u_exposure, 1.0);
}`;

const SHADOW_FRAG = `#version 300 es
precision mediump float; void main(){}`;

const SKY_VERT = `#version 300 es
precision highp float; uniform mat4 u_ivp; out vec3 v_d;
void main(){ vec2 p = vec2(float((gl_VertexID << 1) & 2), float(gl_VertexID & 2)) * 2.0 - 1.0;
  vec4 q = u_ivp * vec4(p, 1.0, 1.0); v_d = q.xyz / q.w; gl_Position = vec4(p, 1.0, 1.0); }`;

const SKY_FRAG = `#version 300 es
precision highp float; in vec3 v_d; uniform float u_time; uniform float u_exposure; out vec4 o;
` + SKY_COMMON + NOISE + `
void main(){
  vec3 d = normalize(v_d);
  vec3 c = skyCol(d);
  // sun disc, softened
  float mu = dot(d, u_sun);
  c += u_sunCol * 12.0 * smoothstep(0.9975, 0.99935, mu);
  // a thin layer of cloud, lit from the sun side
  if (d.y > 0.015) {
    vec3 p = d / d.y * 0.9;
    float n = 0.0, amp = 0.55, fr = 0.12;
    for (int i = 0; i < 5; i++) { n += amp * vn3(vec3(p.x * fr + u_time * 0.004, 2.3, p.z * fr)); amp *= 0.5; fr *= 2.1; }
    float cov = smoothstep(0.50, 0.80, n) * smoothstep(0.015, 0.22, d.y);
    vec3 lit = mix(u_hor * 1.05, u_sunCol * 0.55 + u_zen * 0.6, 0.55 + 0.45 * max(mu, 0.0));
    c = mix(c, lit, cov * 0.88);
  }
  o = vec4(c * u_exposure, 0.0);    // alpha 0 = open sky, read by the sun-shaft pass
}`;

const WATER_VERT = `#version 300 es
precision highp float; layout(location=0) in vec2 a_xz; uniform mat4 u_vp; uniform vec3 u_cam; uniform vec4 u_pond; out vec3 v_w; out vec2 v_q;
void main(){ vec3 w = vec3(u_pond.x + a_xz.x * u_pond.z, u_pond.y, u_pond.w + a_xz.y * u_pond.z); v_w = w; v_q = a_xz; gl_Position = u_vp * vec4(w - u_cam, 1.0); }`;

const WATER_FRAG = `#version 300 es
precision highp float; in vec3 v_w; in vec2 v_q; uniform vec3 u_cam; uniform float u_time; uniform float u_fog; uniform float u_exposure; out vec4 o;
` + SKY_COMMON + `
void main(){
  if (dot(v_q, v_q) > 1.0) discard;
  vec2 p = v_w.xz; float t = u_time;
  vec2 g = vec2(0.0);
  g += vec2(0.8, 0.3) * cos(dot(p, vec2(0.8, 0.3)) * 3.1 + t * 1.3) * 0.045;
  g += vec2(-0.4, 0.9) * cos(dot(p, vec2(-0.4, 0.9)) * 5.3 + t * 1.9) * 0.028;
  g += vec2(0.6, -0.7) * cos(dot(p, vec2(0.6, -0.7)) * 11.0 + t * 2.7) * 0.014;
  vec3 n = normalize(vec3(-g.x, 1.0, -g.y));
  vec3 rel = v_w - u_cam; float dist = length(rel); vec3 v = rel / dist;
  vec3 r = reflect(v, n);
  float fres = 0.02 + 0.98 * pow(1.0 - max(dot(-v, n), 0.0), 5.0);
  vec3 deep = u_zen * 0.08 + vec3(0.010, 0.030, 0.028);
  vec3 col = mix(deep, skyCol(r), fres) + u_sunCol * pow(max(dot(r, u_sun), 0.0), 600.0) * 3.0;
  float f = 1.0 - exp(-max(dist - 12.0, 0.0) * u_fog);
  col = mix(col, skyCol(v) * 0.92, f);
  o = vec4(col * u_exposure, mix(0.74, 0.97, fres));
}`;

const PART_VERT = `#version 300 es
precision highp float;
layout(location=0) in vec3 a_c; layout(location=1) in vec4 a_p; layout(location=2) in vec4 a_col;
uniform mat4 u_vp; uniform vec3 u_cam; uniform vec3 u_sun; uniform vec3 u_shL0; uniform vec3 u_sunCol; out vec3 v_c;
void main(){ vec3 w = a_p.xyz + (a_c - 0.5) * a_p.w - u_cam; vec3 n = normalize(a_c - 0.5);
  v_c = a_col.a > 0.5 ? a_col.rgb * (u_shL0 * 1.4 + u_sunCol * max(dot(n, u_sun), 0.0)) : a_col.rgb;
  gl_Position = u_vp * vec4(w, 1.0); }`;
const PART_FRAG = `#version 300 es
precision mediump float; in vec3 v_c; uniform float u_exposure; out vec4 o; void main(){ o = vec4(v_c * u_exposure, 1.0); }`;

// tone mapping and bloom, applied to the HDR buffer
const POST_VERT = `#version 300 es
precision highp float; out vec2 v_uv;
void main(){ vec2 p = vec2(float((gl_VertexID << 1) & 2), float(gl_VertexID & 2)) * 2.0 - 1.0;
  v_uv = p * 0.5 + 0.5; gl_Position = vec4(p, 0.0, 1.0); }`;
const BRIGHT_FRAG = `#version 300 es
precision highp float; in vec2 v_uv; uniform sampler2D u_src; out vec4 o;
void main(){ vec3 c = texture(u_src, v_uv).rgb; float l = dot(c, vec3(0.2126, 0.7152, 0.0722));
  o = vec4(c * smoothstep(1.0, 2.2, l), 1.0); }`;
const BLUR_FRAG = `#version 300 es
precision highp float; in vec2 v_uv; uniform sampler2D u_src; uniform vec2 u_dir; out vec4 o;
void main(){ vec3 c = texture(u_src, v_uv).rgb * 0.227;
  c += (texture(u_src, v_uv + u_dir * 1.3846).rgb + texture(u_src, v_uv - u_dir * 1.3846).rgb) * 0.316;
  c += (texture(u_src, v_uv + u_dir * 3.2308).rgb + texture(u_src, v_uv - u_dir * 3.2308).rgb) * 0.070;
  o = vec4(c, 1.0); }`;
// sun shafts: march from each pixel towards the sun and gather the open sky met on the way.
// Where a roof, a trunk or leaves hide the sky, the ray is cut, which is what draws the beams.
// 32 taps at quarter resolution: about the cost of the bloom, and nothing is precomputed or stored.
const RAY_FRAG = `#version 300 es
precision highp float; in vec2 v_uv; uniform sampler2D u_src; uniform vec2 u_sunUV; out vec4 o;
void main(){
  vec2 d = (u_sunUV - v_uv) * (1.0 / 32.0);
  vec2 uv = v_uv; float w = 1.0; vec3 acc = vec3(0.0);
  for (int i = 0; i < 32; i++) {
    vec4 s = texture(u_src, uv);
    acc += min(s.rgb, vec3(6.0)) * (1.0 - s.a) * w;
    w *= 0.955; uv += d;
  }
  float fall = exp(-length((v_uv - u_sunUV) * vec2(1.6, 1.0)) * 2.2);
  o = vec4(acc * (fall / 32.0), 1.0);
}`;

const POST_FRAG = `#version 300 es
precision highp float; in vec2 v_uv; uniform sampler2D u_src; uniform sampler2D u_bloom; uniform float u_bloomAmt;
uniform sampler2D u_rays; uniform vec3 u_rayCol; out vec4 o;
vec3 aces(vec3 x){ return clamp((x * (2.51 * x + 0.03)) / (x * (2.43 * x + 0.59) + 0.14), 0.0, 1.0); }
void main(){
  vec3 c = texture(u_src, v_uv).rgb + texture(u_bloom, v_uv).rgb * u_bloomAmt + texture(u_rays, v_uv).rgb * u_rayCol;
  c = aces(c);
  float l = dot(c, vec3(0.2126, 0.7152, 0.0722));
  c = mix(vec3(l), c, 1.14);                                          // a touch more colour
  c *= mix(vec3(0.94, 0.99, 1.07), vec3(1.05, 1.0, 0.91), smoothstep(0.08, 0.65, l));   // cool shade, warm light
  c = pow(c, vec3(1.0 / 2.2));
  vec2 q = v_uv - 0.5;
  c *= 1.0 - dot(q, q) * 0.28;                                        // gentle vignette
  o = vec4(c, 1.0);
}`;

const P_MAIN = prog(VERT, FRAG), PS = prog(VERT, SHADOW_FRAG), PK = prog(SKY_VERT, SKY_FRAG);
const PW = prog(WATER_VERT, WATER_FRAG), PP = prog(PART_VERT, PART_FRAG);
const PRAY = prog(POST_VERT, RAY_FRAG), PBRIGHT = prog(POST_VERT, BRIGHT_FRAG), PBLUR = prog(POST_VERT, BLUR_FRAG), PPOST = prog(POST_VERT, POST_FRAG);

// ======================= load data =======================
status('Téléchargement du village voxélisé…');
// data ships as base64 text (artifact hosting serves text, not arbitrary binaries); same bytes as world.bin
// falls back to world.bin when the text copy is absent (the GitHub repository keeps only the binary)
let resp = await fetch('world.b64.txt'), buf, DOWNLOAD;
if (resp.ok) {
  const b64 = (await resp.text()).trim();
  DOWNLOAD = Number(resp.headers.get('content-length')) || b64.length;
  buf = (() => { const s = atob(b64), a = new Uint8Array(s.length); for (let i = 0; i < s.length; i++) a[i] = s.charCodeAt(i); return a.buffer; })();
} else {
  resp = await fetch('world.bin'); if (!resp.ok) throw new Error('world.b64.txt et world.bin introuvables');
  buf = await resp.arrayBuffer(); DOWNLOAD = buf.byteLength;
}
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
const M = Math.round(1 / VS);            // voxels per metre (10 at 10 cm)
const CX = 410 * M, CZ = 410 * M;        // village centre, in voxels
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

const ponds = [{ x: CX - 22 * M, z: CZ + 29 * M, r: 8 * M, depth: Math.round(1.3 / VS) }];
for (const q of ponds) { let lo = 1e9; for (let k = 0; k < 64; k++) { const a = k / 64 * Math.PI * 2; lo = Math.min(lo, tmpTerrain.natural(q.x + Math.cos(a) * q.r, q.z + Math.sin(a) * q.r) / VS); } q.level = Math.round(lo) - Math.round(0.12 / VS); }
const TER = { seed: SEED, cx: CX, cz: CZ, pads, streets, ponds };
const terrain = new VX.Terrain(TER);
// trees: procedural modules scattered around the village (deterministic)
{
  let placed = 0;
  for (let k = 0; k < 400 && placed < 70; k++) {
    const a = rng() * 6.283, r = (12 + Math.pow(rng(), 0.7) * 75) * M;
    const x = Math.round(CX + Math.cos(a) * r), z = Math.round(CZ + Math.sin(a) * r);
    if (terrain.topClass(x, z) !== 16) continue;
    if (ponds.some((q) => Math.hypot(x - q.x, z - q.z) < q.r + 3 * M)) continue;
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
// palette (classes x 128 tints); the terrain ramps are generated here
const NCLS = W.ncls, NT = W.nt;
const palData = new Uint8Array(NT * NCLS * 4);
for (let c = 0; c < NCLS; c++) for (let t = 0; t < NT; t++) { const s = (c * NT + t) * 3, d = (c * NT + t) * 4; palData[d] = W.palette[s]; palData[d + 1] = W.palette[s + 1]; palData[d + 2] = W.palette[s + 2]; palData[d + 3] = 255; }
function ramp(c, a, b, extra) {
  for (let t = 0; t < NT; t++) { const f = t / (NT - 1), d = (c * NT + t) * 4; for (let k = 0; k < 3; k++) palData[d + k] = Math.round(a[k] + (b[k] - a[k]) * f); palData[d + 3] = 255; }
  if (extra) extra();
}
ramp(16, [52, 78, 33], [128, 143, 60], () => { const d = (16 * NT + 127) * 4; palData.set([226, 214, 128, 255], d); });
ramp(17, [92, 65, 41], [152, 116, 76]);
ramp(18, [92, 88, 82], [156, 149, 136]);
ramp(19, [78, 70, 60], [146, 134, 116], () => { for (let t = 0; t < 10; t++) palData.set([64, 56, 47, 255], (19 * NT + t) * 4); });
ramp(20, [120, 104, 80], [178, 158, 124]);
ramp(12, [32, 58, 24], [106, 148, 52]);
ramp(13, [80, 64, 50], [140, 120, 94]);
const palTex = gl.createTexture(); gl.bindTexture(gl.TEXTURE_2D, palTex);
gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA8, NT, NCLS, 0, gl.RGBA, gl.UNSIGNED_BYTE, palData);
gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
const palRGB = (id) => { const c = Math.min(id >> 7, NCLS - 1), t = id & 127, d = (c * NT + t) * 4; return [palData[d] / 255, palData[d + 1] / 255, palData[d + 2] / 255]; };

// per-class surface response: roughness, metalness, grain frequency (per voxel), grain amount
const MAT = new Float32Array(21 * 4);
const setMat = (c, r, m, gs, ga) => { MAT[c * 4] = r; MAT[c * 4 + 1] = m; MAT[c * 4 + 2] = gs; MAT[c * 4 + 3] = ga; };
for (let c = 0; c < 21; c++) setMat(c, 0.9, 0, 3.0, 0.10);
setMat(1, 0.93, 0.0, 5.0, 0.11);   // plaster: fine mottle
setMat(2, 0.78, 0.0, 2.2, 0.17);   // wood
setMat(3, 0.86, 0.0, 2.6, 0.20);   // worn wood
setMat(4, 0.84, 0.0, 3.4, 0.16);   // dressed stone
setMat(5, 0.87, 0.0, 3.0, 0.15);   // brick
setMat(6, 0.87, 0.0, 3.0, 0.15);   // red brick
setMat(7, 0.90, 0.0, 2.4, 0.20);   // rubble masonry
setMat(8, 0.52, 0.0, 2.0, 0.13);   // roof tiles: glazed enough to catch the sun
setMat(9, 0.34, 0.92, 7.0, 0.07);  // iron
setMat(10, 0.07, 0.0, 9.0, 0.03);  // glass
setMat(11, 0.72, 0.0, 4.0, 0.22);  // vine
setMat(12, 0.66, 0.0, 5.5, 0.26);  // leaves
setMat(13, 0.92, 0.0, 2.6, 0.24);  // bark
setMat(16, 0.88, 0.0, 4.5, 0.24);  // grass
setMat(17, 0.95, 0.0, 3.2, 0.19);  // earth
setMat(18, 0.80, 0.0, 2.6, 0.18);  // rock
setMat(19, 0.68, 0.0, 2.2, 0.17);  // cobbles
setMat(20, 0.94, 0.0, 6.0, 0.22);  // gravel

// coarse volume of how much sky reaches each point of the village (2 m cells, one byte)
const VOL_C = Math.max(1, Math.round(2.0 / VS));           // cell size in voxels
let VOLN = [1, 1, 1], VOL_ORG = [0, 0, 0];
const skyvol = gl.createTexture();
gl.bindTexture(gl.TEXTURE_3D, skyvol);
gl.texImage3D(gl.TEXTURE_3D, 0, gl.R8, 1, 1, 1, 0, gl.RED, gl.UNSIGNED_BYTE, new Uint8Array([255]));
gl.texParameteri(gl.TEXTURE_3D, gl.TEXTURE_MIN_FILTER, gl.LINEAR); gl.texParameteri(gl.TEXTURE_3D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
for (const w of [gl.TEXTURE_WRAP_S, gl.TEXTURE_WRAP_T, gl.TEXTURE_WRAP_R]) gl.texParameteri(gl.TEXTURE_3D, w, gl.CLAMP_TO_EDGE);
function uploadSkyVol(data, nx, ny, nz, org) {
  VOLN = [nx, ny, nz]; VOL_ORG = org;
  gl.bindTexture(gl.TEXTURE_3D, skyvol);
  gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
  gl.texImage3D(gl.TEXTURE_3D, 0, gl.R8, nx, ny, nz, 0, gl.RED, gl.UNSIGNED_BYTE, data);
  MEM.skyvol = nx * ny * nz;
}

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
const VSTRIDE = 16;
function makeMesh(ab) {
  if (!ab || !ab.byteLength) return null;
  const b = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, b); gl.bufferData(gl.ARRAY_BUFFER, ab, gl.STATIC_DRAW);
  MEM.vbo += ab.byteLength; const quads = ab.byteLength / (VSTRIDE * 4); ensureIndex(quads);
  return { b, quads, bytes: ab.byteLength };
}
function freeMesh(m) { if (m) { gl.deleteBuffer(m.b); MEM.vbo -= m.bytes; } }

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
const PRE = { mesh: 0, terr: 0, sky: 0, edit: 0, editN: 0 };   // what the precomputation costs, in ms
function moduleMeshed(m) {
  const mod = W.mods[m.id];
  mod.lod = m.lods.map((b) => makeMesh(b));
  MESH_MS += m.ms; PRE.mesh += m.ms; modsDone++;
  status(`Maillage et occlusion des modules ${modsDone}/${usedMods.length}…`);
}
usedMods.sort((a, b) => b.nvox - a.nvox).forEach((m) => nextW().postMessage({ type: 'module', id: m.id }));
await new Promise((res) => { const t = setInterval(() => { if (modsDone >= usedMods.length) { clearInterval(t); res(); } }, 50); });
workers.forEach((w) => w.postMessage({ type: 'drop' }));

// ======================= terrain quadtree =======================
// 1024 m of terrain. The roots are a power of two times 128 voxels, so the finest leaves are exactly
// 128 voxels wide and meshed one cell per voxel (with roots of 256 m, the leaves came out 80 voxels
// wide and the ground near the camera was meshed at 0.625 voxel per cell: 2.5 times too many quads).
const WORLD = 1024 * M, ROOT = 128 * Math.pow(2, Math.round(Math.log2(256 * M / 128)));
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
    terrainPending--; PRE.terr += m.ms || 0;
    if (ver !== nd.ver) return;
    const old = nd.mesh; nd.mesh = makeMesh(m.v); nd.state = 2; freeMesh(old);
  });
  nextW().postMessage({ type: 'terrain', job, x0: nd.x0, z0: nd.z0, S: nd.S, s: step, removed });
}
const tdraw = [];
let camX = 0, camY = 0, camZ = 0;
// extension points for other modules (villagers.js): draw hooks get camera-relative matrices like ours
const HOOKS = [], UPDATES = [];
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
    // the finest leaves (one cell per voxel, with grass tufts) only near the camera: that level
    // alone holds most of the terrain triangles, and beyond twenty metres a tuft is a few pixels
    const lim = S === 256 ? 20 * Q.dist : K * S * VS;
    let split = S > 128 && (d < lim || (d < 60 && nodeHasEdits(x0, z0, S)));
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

// ---- how much sky reaches each part of the village: built once, in a worker
{
  const pad = 28 * M;
  let x0 = CX - 200 * M, z0 = CZ - 200 * M, x1 = CX + 200 * M, z1 = CZ + 200 * M, y0 = 1e9, y1 = -1e9;
  for (const i of instances) { y0 = Math.min(y0, i.y0); y1 = Math.max(y1, i.y1); }
  y0 = Math.min(y0, heightAt(CX, CZ)) - 4 * M; y1 += 10 * M;
  const org = [x0, y0, z0];
  const nx = Math.ceil((x1 - x0) / VOL_C), ny = Math.ceil((y1 - y0) / VOL_C), nz = Math.ceil((z1 - z0) / VOL_C);
  const inst = new Int32Array(instances.length * 5);
  instances.forEach((i, k) => { inst[k * 5] = i.mod.id; inst[k * 5 + 1] = i.x; inst[k * 5 + 2] = i.y; inst[k * 5 + 3] = i.z; inst[k * 5 + 4] = i.r; });
  const job = ++jobSeq, t0 = performance.now();
  jobs.set(job, (r) => { PRE.sky = performance.now() - t0; if (r.v) uploadSkyVol(r.v, nx, ny, nz, org); });
  nextW().postMessage({ type: 'skyvol', job, n: [nx, ny, nz], c: VOL_C, org, inst }, [inst.buffer]);
}

// ======================= braziers =======================
// Fire is not voxelised: a point light plus a few emissive cubes. The light is the only
// part of the lighting that is not precomputed, which is why there are six of them and not sixty.
const FIRES = [];
{
  const place = (vx, vz) => {
    const y = heightAt(vx | 0, vz | 0);
    FIRES.push({ x: vx * VS, y: (y + 1) * VS, z: vz * VS, seed: FIRES.length * 7.13 });
  };
  for (const d of [-40, -14, 14, 40]) place(CX + d * M, CZ + 5.5 * M);
  place(CX + 5.5 * M, CZ - 34 * M); place(CX - 5.5 * M, CZ + 30 * M);
}
const fireUni = new Float32Array(6 * 4);
const FIRE_CUBES = 7;                       // emissive cubes per brazier, placed analytically
const fireData = new Float32Array(FIRES.length * (FIRE_CUBES + 1) * 8);
function updateFires(now) {
  const t = now / 1000;
  // the light fades out with daylight; at noon a brazier adds nothing anyone can see
  const night = Math.max(0, Math.min(1, 0.15 - SKY.el * 4));
  let k = 0;
  for (let i = 0; i < 6; i++) {
    const f = FIRES[i];
    if (!f || night <= 0.01) { fireUni[i * 4 + 3] = 0; continue; }
    const flick = 0.82 + 0.18 * Math.sin(t * 7.3 + f.seed) * Math.sin(t * 3.1 + f.seed * 2.1);
    fireUni[i * 4] = f.x - camX; fireUni[i * 4 + 1] = f.y + 0.25 - camY; fireUni[i * 4 + 2] = f.z - camZ;
    fireUni[i * 4 + 3] = 3.2 * night * flick;
  }
  for (const f of FIRES) {
    fireData.set([f.x, f.y - 0.16, f.z, 0.5, 0.09, 0.075, 0.07, 1], k * 8); k++;   // the iron basket
    if (night <= 0.01) continue;
    for (let c = 0; c < FIRE_CUBES; c++) {
      const ph = (t * 1.5 + c / FIRE_CUBES + f.seed) % 1;
      const up = ph * 0.95, sz = (0.19 - 0.15 * ph) * (0.7 + 0.5 * Math.sin(c * 2.3 + f.seed));
      const w = 0.11 * ph * Math.sin(t * 4 + c * 2.1 + f.seed), w2 = 0.11 * ph * Math.cos(t * 3.3 + c * 1.7);
      const heat = 1 - ph;
      fireData.set([f.x + w, f.y + up, f.z + w2, Math.max(0.03, sz),
        3.4 * heat + 0.6, 1.5 * heat * heat + 0.12, 0.25 * heat * heat * heat, 0], k * 8); k++;
    }
  }
  return k;
}

// ======================= player =======================
const player = { x: CX + 0.5 * M, y: 0, z: CZ + 1 * M, vx: 0, vy: 0, vz: 0, yaw: Math.PI * 0.75, pitch: -0.08, ground: false, fly: false, eyeSmooth: 0 };
player.y = heightAt(player.x | 0, player.z | 0) + 2;
const HW = Math.max(1, Math.round(0.24 / VS)), HH = Math.round(1.72 / VS), EYE = Math.round(1.6 / VS), STEP = Math.max(1, Math.round(0.42 / VS));
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
const TOOLS = [0.09, 0.18, 0.30, 0.55].map((m) => Math.max(1, Math.round(m / VS)));   // tool radius in voxels
let tool = 1;
let editedCount = 0, voxelsRemoved = 0;
function ensureEdited(inst) {
  if (inst.bricks) return;
  inst.bricks = Int32Array.from(inst.mod.bricks);
  inst.mesh = null; inst.meshDirty = true; inst.pending = 0;
  const arr = inst.mod.instances; arr.splice(arr.indexOf(inst), 1);
  editedList.push(inst); editedCount++;
}
const editedList = [];
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
function removeInstVoxel(inst, l) {
  ensureEdited(inst); inst.blocksDirty = true; inst.meshDirty = true;
  setLocal(inst, l[0], l[1], l[2]);
}
// Flood fill from the ground and from the border of the box: solid voxels not reached are floating and fall.
let collapsedTotal = 0;
function collapse(x0, y0, z0, x1, y1, z1) {
  const nx = x1 - x0 + 1, ny = y1 - y0 + 1, nz = z1 - z0 + 1, N = nx * ny * nz;
  const occ = new Uint8Array(N);   // 0 air, 1 building, 2 terrain/anchored, 3 reached
  const insts = new Set();
  for (let gx = x0 >> 6; gx <= x1 >> 6; gx++) for (let gz = z0 >> 6; gz <= z1 >> 6; gz++) { const g = GRID.get(gx * 65536 + gz); if (g) g.forEach((i) => insts.add(i)); }
  const list = [...insts].filter((i) => !(x1 < i.x0 || x0 >= i.x1 || y1 < i.y0 || y0 >= i.y1 || z1 < i.z0 || z0 >= i.z1));
  for (const inst of list) {
    const bk = inst.bricks || inst.mod.bricks;
    for (let z = Math.max(z0, inst.z0); z <= Math.min(z1, inst.z1 - 1); z++)
      for (let y = Math.max(y0, inst.y0); y <= Math.min(y1, inst.y1 - 1); y++)
        for (let x = Math.max(x0, inst.x0); x <= Math.min(x1, inst.x1 - 1); x++) {
          const i = (x - x0) + nx * ((y - y0) + ny * (z - z0));
          if (occ[i]) continue;
          const l = toLocal(inst, x, y, z);
          if (VX.getLocal(inst.mod, bk, pool, l[0], l[1], l[2])) occ[i] = 1;
        }
  }
  const q = new Int32Array(N); let qh = 0, qt = 0;
  for (let z = 0; z < nz; z++) for (let x = 0; x < nx; x++) {
    const h = heightAt(x0 + x, z0 + z);
    for (let y = 0; y < ny; y++) {
      const i = x + nx * (y + ny * z);
      const wy = y0 + y;
      if (wy < h && !terrainRemoved(x0 + x, wy, z0 + z)) { occ[i] = 3; q[qt++] = i; continue; }
      if (occ[i] === 1 && (x === 0 || z === 0 || y === 0 || x === nx - 1 || y === ny - 1 || z === nz - 1)) { occ[i] = 3; q[qt++] = i; }
    }
  }
  const sx = 1, sy = nx, sz = nx * ny;
  while (qh < qt) {
    const i = q[qh++], x = i % nx, y = ((i / nx) | 0) % ny, z = (i / sz) | 0;
    if (x > 0 && occ[i - sx] === 1) { occ[i - sx] = 3; q[qt++] = i - sx; }
    if (x < nx - 1 && occ[i + sx] === 1) { occ[i + sx] = 3; q[qt++] = i + sx; }
    if (y > 0 && occ[i - sy] === 1) { occ[i - sy] = 3; q[qt++] = i - sy; }
    if (y < ny - 1 && occ[i + sy] === 1) { occ[i + sy] = 3; q[qt++] = i + sy; }
    if (z > 0 && occ[i - sz] === 1) { occ[i - sz] = 3; q[qt++] = i - sz; }
    if (z < nz - 1 && occ[i + sz] === 1) { occ[i + sz] = 3; q[qt++] = i + sz; }
  }
  const floating = [];
  for (let i = 0; i < N; i++) if (occ[i] === 1) floating.push(i);
  const res = { n: 0, debris: [] };
  if (!floating.length) return res;
  const every = Math.max(1, Math.ceil(floating.length / 1200));
  for (let k = 0; k < floating.length; k++) {
    const i = floating[k], x = x0 + i % nx, y = y0 + ((i / nx) | 0) % ny, z = z0 + ((i / sz) | 0);
    for (const inst of list) {
      if (x < inst.x0 || x >= inst.x1 || y < inst.y0 || y >= inst.y1 || z < inst.z0 || z >= inst.z1) continue;
      const l = toLocal(inst, x, y, z);
      const id = VX.getLocal(inst.mod, inst.bricks || inst.mod.bricks, pool, l[0], l[1], l[2]);
      if (!id) continue;
      removeInstVoxel(inst, l); res.n++;
      if (k % every === 0) res.debris.push(x, y, z, id | (every > 1 ? 1 << 20 : 0) | (Math.min(7, Math.round(Math.cbrt(every))) << 21));
      break;
    }
  }
  collapsedTotal += res.n;
  return res;
}
// ---- whole-building check: islands of 8 cm cells no longer linked to the ground fall (debounced after digging)
// Each instance's occupied 4^3 blocks are cached (per module, or per edited instance). A block marks every world
// cell its span overlaps, so pieces that touch always link: the test can only miss a collapse, never invent one.
const structTouched = new Set(); let structTimer = 0, structFallen = 0;
function fromLocal(inst, lx, lz) {
  const r = inst.r;
  if (r === 0) return [inst.x + lx, inst.z + lz];
  if (r === 1) return [inst.x + lz, inst.z - lx - 1];
  if (r === 2) return [inst.x - lx - 1, inst.z - lz - 1];
  return [inst.x - lz - 1, inst.z + lx];
}
function blocksOf(inst) {
  const owner_ = inst.bricks ? inst : inst.mod;
  if (owner_.blocks && !(inst.bricks && inst.blocksDirty)) return owner_.blocks;
  const m = inst.mod, bk = inst.bricks || m.bricks, out = [];
  for (let bz = 0; bz < m.nbz; bz++) for (let by = 0; by < m.nby; by++) for (let bx = 0; bx < m.nbx; bx++) {
    const e = bk[bx + m.nbx * (by + m.nby * bz)];
    if (e === 0) continue;
    for (let sz = 0; sz < 2; sz++) for (let sy = 0; sy < 2; sy++) for (let sx = 0; sx < 2; sx++) {
      let any = e > 0;
      if (!any) {
        const o = (-e - 1) * 256;
        for (let z = sz * 4; z < sz * 4 + 4 && !any; z++) for (let y = sy * 4; y < sy * 4 + 4 && !any; y++) {
          const k = o + 4 * (y + 8 * z) + sx * 2; if (pool.idx[k] || pool.idx[k + 1]) any = true;
        }
      }
      if (any) out.push(m.ox + bx * 8 + sx * 4, m.oy + by * 8 + sy * 4, m.oz + bz * 8 + sz * 4);
    }
  }
  owner_.blocks = new Int32Array(out); inst.blocksDirty = false;
  return owner_.blocks;
}
let structRuns = 0;
function structuralCheck(dry) {
  structRuns++;
  // the building: instances linked by overlapping boxes, starting from those just dug
  const region = new Set(), stack = [...structTouched]; structTouched.clear();
  const near = (a, b) => !(a.x1 + 2 < b.x0 || b.x1 + 2 < a.x0 || a.y1 + 2 < b.y0 || b.y1 + 2 < a.y0 || a.z1 + 2 < b.z0 || b.z1 + 2 < a.z0);
  while (stack.length && region.size < 400) {
    const a = stack.pop(); if (region.has(a)) continue; region.add(a);
    for (let gx = (a.x0 - 4) >> 6; gx <= (a.x1 + 4) >> 6; gx++) for (let gz = (a.z0 - 4) >> 6; gz <= (a.z1 + 4) >> 6; gz++) {
      const g = GRID.get(gx * 65536 + gz); if (g) for (const b of g) if (!region.has(b) && near(a, b)) stack.push(b);
    }
  }
  let X0 = 1e9, Y0 = 1e9, Z0 = 1e9, X1 = -1e9, Y1 = -1e9, Z1 = -1e9;
  for (const i of region) { X0 = Math.min(X0, i.x0); Y0 = Math.min(Y0, i.y0); Z0 = Math.min(Z0, i.z0); X1 = Math.max(X1, i.x1); Y1 = Math.max(Y1, i.y1); Z1 = Math.max(Z1, i.z1); }
  const cx0 = Math.floor(X0 / 4) - 1, cy0 = Math.floor(Y0 / 4) - 1, cz0 = Math.floor(Z0 / 4) - 1;
  const nx = Math.floor(X1 / 4) + 2 - cx0, ny = Math.floor(Y1 / 4) + 2 - cy0, nz = Math.floor(Z1 / 4) + 2 - cz0, N = nx * ny * nz;
  if (N > 6e6) return region;
  const g = new Uint8Array(N);   // 1 occupied, 2 reached
  const t0 = performance.now();
  for (const inst of region) {
    if (inst.mod.tree) continue;
    const bl = blocksOf(inst);
    for (let k = 0; k < bl.length; k += 3) {
      const lx = bl[k], ly = bl[k + 1], lz = bl[k + 2];
      const a = fromLocal(inst, lx, lz), b = fromLocal(inst, lx + 3, lz + 3);
      const qx0 = (Math.min(a[0], b[0]) >> 2) - cx0, qx1 = (Math.max(a[0], b[0]) >> 2) - cx0;
      const qz0 = (Math.min(a[1], b[1]) >> 2) - cz0, qz1 = (Math.max(a[1], b[1]) >> 2) - cz0;
      const qy0 = ((inst.y + ly) >> 2) - cy0, qy1 = ((inst.y + ly + 3) >> 2) - cy0;
      for (let qz = qz0; qz <= qz1; qz++) for (let qy = qy0; qy <= qy1; qy++) for (let qx = qx0; qx <= qx1; qx++) g[qx + nx * (qy + ny * qz)] = 1;
    }
  }
  // anchors: occupied cells at or below the ground of their column
  const q = new Int32Array(N); let qh = 0, qt = 0;
  for (let qz = 0; qz < nz; qz++) for (let qx = 0; qx < nx; qx++) {
    const h = heightAt((cx0 + qx) * 4 + 2, (cz0 + qz) * 4 + 2), top = Math.min(ny - 1, (h >> 2) - cy0);
    for (let qy = 0; qy <= top; qy++) { const i = qx + nx * (qy + ny * qz); if (g[i] === 1) { g[i] = 2; q[qt++] = i; } }
  }
  const sy = nx, sz = nx * ny;
  while (qh < qt) {
    const i = q[qh++], x = i % nx, y = ((i / nx) | 0) % ny, z = (i / sz) | 0;
    if (x > 0 && g[i - 1] === 1) { g[i - 1] = 2; q[qt++] = i - 1; }
    if (x < nx - 1 && g[i + 1] === 1) { g[i + 1] = 2; q[qt++] = i + 1; }
    if (y > 0 && g[i - sy] === 1) { g[i - sy] = 2; q[qt++] = i - sy; }
    if (y < ny - 1 && g[i + sy] === 1) { g[i + sy] = 2; q[qt++] = i + sy; }
    if (z > 0 && g[i - sz] === 1) { g[i - sz] = 2; q[qt++] = i - sz; }
    if (z < nz - 1 && g[i + sz] === 1) { g[i + sz] = 2; q[qt++] = i + sz; }
  }
  // floating blocks: remove their voxels; one large debris per block (subsampled when many)
  const fall = [];
  for (const inst of region) {
    if (inst.mod.tree) continue;
    const bl = blocksOf(inst);
    for (let k = 0; k < bl.length; k += 3) {
      const lx = bl[k], ly = bl[k + 1], lz = bl[k + 2];
      const a = fromLocal(inst, lx, lz), b = fromLocal(inst, lx + 3, lz + 3);
      const i = ((Math.min(a[0], b[0]) >> 2) - cx0) + nx * ((((inst.y + ly) >> 2) - cy0) + ny * ((Math.min(a[1], b[1]) >> 2) - cz0));
      if (g[i] === 1) fall.push(inst, lx, ly, lz);
    }
  }
  if (!fall.length) return region;
  if (dry) { const c = {}; for (let k = 0; k < fall.length; k += 4) c[fall[k].mod.name] = (c[fall[k].mod.name] || 0) + 1; dry.push(c); return region; }
  const every = Math.max(1, Math.ceil(fall.length / 4 / (PMAX - parts.length + 1)));
  const debris = []; let n = 0;
  for (let k = 0; k < fall.length; k += 4) {
    const inst = fall[k], lx = fall[k + 1], ly = fall[k + 2], lz = fall[k + 3], bk = () => inst.bricks || inst.mod.bricks;
    let first = 0;
    for (let z = lz; z < lz + 4; z++) for (let y = ly; y < ly + 4; y++) for (let x = lx; x < lx + 4; x++) {
      const id = VX.getLocal(inst.mod, bk(), pool, x, y, z); if (!id) continue;
      if (!first) first = id;
      removeInstVoxel(inst, [x, y, z]); n++;
    }
    if (first && (k / 4) % every === 0) {
      const w = fromLocal(inst, lx + 2, lz + 2);
      debris.push(w[0], inst.y + ly + 2, w[1], first | 1 << 20 | Math.min(7, 4 + Math.round(Math.cbrt(every))) << 21);
    }
  }
  structFallen += n; collapsedTotal += n; voxelsRemoved += n;
  spawnDebris(debris); flushEdits();
  console.info(`effondrement : ${region.size} pièces examinées, ${fall.length / 4} blocs de 8 cm tombés (${n} voxels) en ${(performance.now() - t0).toFixed(0)} ms`);
  return region;
}
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
          removeInstVoxel(inst, l); removed++; structTouched.add(inst);
          if ((removed & 15) === 0 || removed < 40) debris.push(x, y, z, id);
        }
  }
  // structural check: anything no longer connected to the ground or to the outside of the work zone falls
  const G = Math.max(3, Math.round(0.5 / VS));
  const fell = collapse(x0 - G, y0 - G, z0 - G, x1 + G, y1 + G, z1 + G);
  removed += fell.n;
  for (let i = 0; i < fell.debris.length; i += 4) debris.push(fell.debris[i], fell.debris[i + 1], fell.debris[i + 2], fell.debris[i + 3]);
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
  spawnDebris(debris);
  flushEdits();
  if (structTouched.size) { clearTimeout(structTimer); structTimer = setTimeout(structuralCheck, 350); }
}
function spawnDebris(debris) {
  for (let i = 0; i < debris.length && parts.length < PMAX; i += 4) {
    const raw = debris[i + 3], big = (raw >> 20) & 1, sc = (raw >> 21) & 7;
    const c = palRGB(raw & 0xffff); const j = VX.hash2(debris[i], debris[i + 2], debris[i + 1]);
    const lin = c.map((v) => Math.pow(v, 2.2) * (0.85 + 0.3 * j));
    parts.push({ x: (debris[i] + 0.5) * VS, y: (debris[i + 1] + 0.5) * VS, z: (debris[i + 2] + 0.5) * VS,
      vx: (Math.random() - 0.5) * (big ? 0.6 : 2.5), vy: big ? 0 : Math.random() * 3, vz: (Math.random() - 0.5) * (big ? 0.6 : 2.5),
      s: VS * (big ? Math.max(1, sc) * (1 + Math.random() * 0.3) : 1 + Math.random() * 1.5), c: lin, life: (big ? 5 : 2.5) + Math.random() * 2 });
  }
}
function flushEdits() { /* meshes are rebuilt from meshDirty in the main loop */ 
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
document.addEventListener('keydown', (e) => {
  if (e.code === 'Comma' || e.code === 'Semicolon' || e.code === 'BracketLeft' || e.code === 'BracketRight') {
    const d = (e.code === 'Comma' || e.code === 'BracketLeft') ? -0.012 : 0.012;
    TOD = (TOD + d + 1) % 1; updateSky(); hud();
  } else if (e.code === 'KeyN') { skyAuto = !skyAuto; hud(); }
});
document.addEventListener('wheel', (e) => { tool = Math.max(0, Math.min(TOOLS.length - 1, tool + Math.sign(e.deltaY))); updTool(); });
document.addEventListener('keydown', (e) => {
  keys[e.code] = true;
  if (e.code === 'KeyF') { player.fly = !player.fly; player.vy = 0; }
  if (e.code >= 'Digit1' && e.code <= 'Digit4') { tool = +e.code.slice(5) - 1; updTool(); }
  if (e.code === 'KeyH') $('hud').classList.toggle('hidden');
  if (e.code === 'KeyB') startBench();
});
document.addEventListener('keyup', (e) => { keys[e.code] = false; });
function updTool() { $('tool').textContent = `Outil : rayon ${Math.round(TOOLS[tool] * VS * 100)} cm (molette ou 1-4)`; }
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

// high dynamic range target, so the sun can be brighter than white and bloom has something to catch
const floatRT = gl.getExtension('EXT_color_buffer_float') || gl.getExtension('EXT_color_buffer_half_float');
const HDRFMT = floatRT ? gl.RGBA16F : gl.RGBA8;
let hdrTex = null, hdrDepth = null, hdrFB = null, bloomTex = [null, null, null], bloomFB = [null, null, null], bloomW = 0, bloomH = 0;
function makeTargets(w, h) {
  for (const t of [hdrTex, hdrDepth, bloomTex[0], bloomTex[1], bloomTex[2]]) if (t) gl.deleteTexture(t);
  for (const f of [hdrFB, bloomFB[0], bloomFB[1], bloomFB[2]]) if (f) gl.deleteFramebuffer(f);
  hdrTex = gl.createTexture(); gl.bindTexture(gl.TEXTURE_2D, hdrTex);
  gl.texStorage2D(gl.TEXTURE_2D, 1, HDRFMT, w, h);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
  hdrDepth = gl.createRenderbuffer(); gl.bindRenderbuffer(gl.RENDERBUFFER, hdrDepth);
  gl.renderbufferStorage(gl.RENDERBUFFER, gl.DEPTH_COMPONENT24, w, h);
  hdrFB = gl.createFramebuffer(); gl.bindFramebuffer(gl.FRAMEBUFFER, hdrFB);
  gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, hdrTex, 0);
  gl.framebufferRenderbuffer(gl.FRAMEBUFFER, gl.DEPTH_ATTACHMENT, gl.RENDERBUFFER, hdrDepth);
  bloomW = Math.max(1, w >> 2); bloomH = Math.max(1, h >> 2);
  for (let i = 0; i < 3; i++) {
    bloomTex[i] = gl.createTexture(); gl.bindTexture(gl.TEXTURE_2D, bloomTex[i]);
    gl.texStorage2D(gl.TEXTURE_2D, 1, HDRFMT, bloomW, bloomH);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    bloomFB[i] = gl.createFramebuffer(); gl.bindFramebuffer(gl.FRAMEBUFFER, bloomFB[i]);
    gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, bloomTex[i], 0);
  }
  gl.bindFramebuffer(gl.FRAMEBUFFER, null);
  MEM.hdr = (w * h + bloomW * bloomH * 3) * (floatRT ? 8 : 4) + w * h * 4;
}
const instBuf = gl.createBuffer(); let instCap = 0;
const cubeBuf = gl.createBuffer(); {
  const v = [];
  const c = [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0], [0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1]];
  const faces = [[0, 3, 2, 1], [4, 5, 6, 7], [0, 1, 5, 4], [3, 7, 6, 2], [0, 4, 7, 3], [1, 2, 6, 5]];
  for (const f of faces) for (const k of [0, 1, 2, 0, 2, 3]) v.push(...c[f[k]]);
  gl.bindBuffer(gl.ARRAY_BUFFER, cubeBuf); gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(v), gl.STATIC_DRAW);
}
const partBuf = gl.createBuffer();
const waterBuf = gl.createBuffer(); {
  const v = []; const n = 32;
  for (let j = 0; j < n; j++) for (let i = 0; i < n; i++) {
    const a = [-1 + 2 * i / n, -1 + 2 * j / n], b = [-1 + 2 * (i + 1) / n, -1 + 2 * (j + 1) / n];
    v.push(a[0], a[1], a[0], b[1], b[0], b[1], a[0], a[1], b[0], b[1], b[0], a[1]);
  }
  gl.bindBuffer(gl.ARRAY_BUFFER, waterBuf); gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(v), gl.STATIC_DRAW);
}
const vao = gl.createVertexArray();

// ---------------- sky, time of day, and its spherical harmonic ----------------
// The hour only changes a handful of RGB numbers. Everything baked into the geometry
// (openness, bent normals, the village sky volume) stays valid, which is the whole point.
const SKY_KEY = [   // by sun elevation (sin of the altitude)
  { e: -0.35, sun: [0.030, 0.042, 0.085], zen: [0.011, 0.018, 0.042], hor: [0.030, 0.042, 0.072], haze: 0.3 },
  { e: -0.06, sun: [0.42, 0.26, 0.22], zen: [0.045, 0.062, 0.145], hor: [0.26, 0.17, 0.19], haze: 1.5 },
  { e: 0.035, sun: [3.30, 1.30, 0.42], zen: [0.070, 0.125, 0.420], hor: [0.92, 0.50, 0.30], haze: 1.55 },
  { e: 0.18, sun: [4.40, 2.80, 1.55], zen: [0.110, 0.225, 0.660], hor: [0.78, 0.66, 0.56], haze: 1.05 },
  { e: 0.50, sun: [4.60, 4.25, 3.80], zen: [0.165, 0.330, 0.760], hor: [0.620, 0.715, 0.870], haze: 1.0 },
  { e: 0.90, sun: [4.70, 4.45, 4.10], zen: [0.175, 0.350, 0.800], hor: [0.640, 0.740, 0.900], haze: 0.9 },
];
let TOD = 0.728;                      // 0.25 sunrise, 0.5 noon, 0.75 sunset; we open on the golden hour
let skyAuto = false;
const SKY = { sun: [0, 1, 0], el: 1, sunCol: [1, 1, 1], zen: [0, 0, 0], hor: [0, 0, 0], grnd: [0, 0, 0], haze: 1, exposure: 1, fog: 0.0018, L0: [0, 0, 0], L1r: [0, 0, 0], L1g: [0, 0, 0], L1b: [0, 0, 0] };
const GROUND_ALBEDO = [0.26, 0.30, 0.19];
function skyColJS(d, S) {
  const up = Math.max(-1, Math.min(1, d[1]));
  const mu = d[0] * S.sun[0] + d[1] * S.sun[1] + d[2] * S.sun[2];
  const t = Math.pow(Math.max(0, up), 0.42);
  const m1 = Math.pow(Math.max(mu, 0), 10), m2 = Math.pow(Math.max(mu, 0), 2.5);
  const g = VX.smooth(-0.12, 0.02, up), c = [0, 0, 0];
  for (let k = 0; k < 3; k++) {
    const v = S.hor[k] + (S.zen[k] - S.hor[k]) * t + S.sunCol[k] * (0.22 * m1 + 0.05 * m2) * S.haze;
    c[k] = S.grnd[k] + (v - S.grnd[k]) * g;
  }
  return c;
}
const SH_DIRS = (() => {               // Fibonacci sphere, used to project the sky onto its harmonic
  const n = 160, a = [];
  for (let i = 0; i < n; i++) {
    const y = 1 - (i + 0.5) * 2 / n, r = Math.sqrt(Math.max(0, 1 - y * y)), th = Math.PI * (1 + Math.sqrt(5)) * i;
    a.push([Math.cos(th) * r, y, Math.sin(th) * r]);
  }
  return a;
})();
function updateSky() {
  const u = (TOD - 0.25) * 2;
  const el = Math.sin(u * Math.PI) * 1.05, az = -0.75 + u * 2.6;
  SKY.sun = [Math.cos(el) * Math.sin(az), Math.sin(el), Math.cos(el) * Math.cos(az)];
  const e = SKY.sun[1]; SKY.el = e;   // real sun elevation, kept before the moon flips the vector
  let i = 0; while (i < SKY_KEY.length - 2 && e > SKY_KEY[i + 1].e) i++;
  const A = SKY_KEY[i], B = SKY_KEY[i + 1];
  const f = Math.max(0, Math.min(1, (e - A.e) / (B.e - A.e))), ff = f * f * (3 - 2 * f);
  const lerp3 = (p, q) => [p[0] + (q[0] - p[0]) * ff, p[1] + (q[1] - p[1]) * ff, p[2] + (q[2] - p[2]) * ff];
  SKY.sunCol = lerp3(A.sun, B.sun); SKY.zen = lerp3(A.zen, B.zen); SKY.hor = lerp3(A.hor, B.hor);
  SKY.haze = A.haze + (B.haze - A.haze) * ff;
  if (e < 0.02) {                       // below the horizon the light comes from the moon, from the other side
    const k = Math.max(0, Math.min(1, (0.02 - e) / 0.12));
    SKY.sun = [-SKY.sun[0] * k + SKY.sun[0] * (1 - k), Math.abs(SKY.sun[1]) * k + SKY.sun[1] * (1 - k), -SKY.sun[2] * k + SKY.sun[2] * (1 - k)];
    const l = Math.hypot(...SKY.sun) || 1; SKY.sun = SKY.sun.map((v) => v / l);
  }
  // the ground sends part of the sky back up: this is the one bounce we keep, and it is free
  const skyAvg = [(SKY.zen[0] + SKY.hor[0] * 2) / 3, (SKY.zen[1] + SKY.hor[1] * 2) / 3, (SKY.zen[2] + SKY.hor[2] * 2) / 3];
  const sunUp = Math.max(0, SKY.sun[1]);
  SKY.grnd = [0, 1, 2].map((k) => (skyAvg[k] * 0.9 + SKY.sunCol[k] * sunUp * 0.30) * GROUND_ALBEDO[k]);
  // project onto the order-1 harmonic
  const w = 4 * Math.PI / SH_DIRS.length;
  const L0 = [0, 0, 0], L1 = [[0, 0, 0], [0, 0, 0], [0, 0, 0]];
  for (const d of SH_DIRS) {
    const c = skyColJS(d, SKY);
    for (let k = 0; k < 3; k++) { L0[k] += c[k] * 0.282095 * w; L1[k][0] += c[k] * 0.488603 * d[0] * w; L1[k][1] += c[k] * 0.488603 * d[1] * w; L1[k][2] += c[k] * 0.488603 * d[2] * w; }
  }
  SKY.L0 = L0; SKY.L1r = L1[0]; SKY.L1g = L1[1]; SKY.L1b = L1[2];
  const lum = 0.2126 * SKY.hor[0] + 0.7152 * SKY.hor[1] + 0.0722 * SKY.hor[2];
  SKY.exposure = Math.max(0.75, Math.min(3.2, 0.78 / Math.max(0.03, lum)));
  SKY.fog = 0.00085 + 0.0011 * Math.max(0, (SKY.haze - 1) / 1.2);
}
updateSky();

function resize() {
  const dpr = Math.min(window.devicePixelRatio || 1, 1) * Q.scale;
  canvas.width = Math.max(2, Math.round(canvas.clientWidth * dpr)); canvas.height = Math.max(2, Math.round(canvas.clientHeight * dpr));
  makeTargets(canvas.width, canvas.height);
}
window.addEventListener('resize', resize); resize();

let stats = { tris: 0, draws: 0, terr: 0 };
function bindMesh(mesh) {
  gl.bindBuffer(gl.ARRAY_BUFFER, mesh.b);
  gl.enableVertexAttribArray(0); gl.vertexAttribPointer(0, 3, gl.SHORT, false, 16, 0);
  gl.enableVertexAttribArray(1); gl.vertexAttribPointer(1, 2, gl.UNSIGNED_BYTE, false, 16, 6);
  gl.enableVertexAttribArray(2); gl.vertexAttribPointer(2, 4, gl.BYTE, true, 16, 8);
  gl.enableVertexAttribArray(3); gl.vertexAttribPointer(3, 1, gl.UNSIGNED_SHORT, false, 16, 12);
}
// 10 cm up close, 20 cm, then 40 cm
function lodFor(d) { const s = Q.dist; return d < 32 * s ? 0 : d < 85 * s ? 1 : 2; }
function setCommon(pr, vp, lvp) {
  gl.useProgram(pr.p);
  const u = pr.u;
  gl.uniformMatrix4fv(u.u_vp, false, vp);
  if (u.u_lvp) gl.uniformMatrix4fv(u.u_lvp, false, lvp);
  gl.uniform3f(u.u_cam, camX, camY, camZ); if (u.u_vs) gl.uniform1f(u.u_vs, VS);
  if (u.u_pal) {
    gl.uniform1i(u.u_pal, 2); gl.uniform1i(u.u_shadow, 3); gl.uniform1i(u.u_skyvol, 5);
    gl.uniform1i(u.u_ao, Q.ao ? 1 : 0); gl.uniform1i(u.u_shadows, Q.shadows ? 1 : 0);
    gl.uniform4fv(u.u_mat, MAT);
    gl.uniform4fv(u.u_fires, fireUni);
    gl.uniform1f(u.u_glow, Math.max(0, Math.min(1, 0.32 - SKY.el * 1.6)));
    gl.uniform3f(u.u_volMin, VOL_ORG[0] * VS, VOL_ORG[1] * VS, VOL_ORG[2] * VS);
    gl.uniform3f(u.u_volScale, 1 / (VOLN[0] * VOL_C * VS), 1 / (VOLN[1] * VOL_C * VS), 1 / (VOLN[2] * VOL_C * VS));
    setSkyUniforms(pr);
    gl.uniform1f(u.u_fog, SKY.fog); gl.uniform1f(u.u_exposure, SKY.exposure);
    gl.uniform3fv(u.u_shL0, SKY.L0); gl.uniform3fv(u.u_shL1r, SKY.L1r); gl.uniform3fv(u.u_shL1g, SKY.L1g); gl.uniform3fv(u.u_shL1b, SKY.L1b);
  }
}
function setSkyUniforms(pr) {
  const u = pr.u;
  if (u.u_zen) gl.uniform3fv(u.u_zen, SKY.zen);
  if (u.u_hor) gl.uniform3fv(u.u_hor, SKY.hor);
  if (u.u_grnd) gl.uniform3fv(u.u_grnd, SKY.grnd);
  if (u.u_sunCol) gl.uniform3fv(u.u_sunCol, SKY.sunCol);
  if (u.u_sun) gl.uniform3fv(u.u_sun, SKY.sun);
  if (u.u_haze) gl.uniform1f(u.u_haze, SKY.haze);
}
function drawScene(shadowPass, vp, lvp, P) {
  const PR = shadowPass ? PS : P_MAIN;
  setCommon(PR, vp, lvp);
  gl.disableVertexAttribArray(4); gl.vertexAttrib4f(4, 0, 0, 0, 0);
  // terrain
  for (const nd of tdraw) {
    const S = nd.S * VS, cx = nd.x0 * VS + S / 2 - camX, cz = nd.z0 * VS + S / 2 - camZ;
    const hy = heightAt(nd.x0 + (nd.S >> 1), nd.z0 + (nd.S >> 1)) * VS - camY;
    if (!visible(P, cx, hy, cz, S * 0.75 + 15)) continue;
    bindMesh(nd.mesh); gl.drawElements(gl.TRIANGLES, nd.mesh.quads * 6, gl.UNSIGNED_INT, 0);
    stats.draws++; stats.tris += nd.mesh.quads * 2; stats.terr += nd.mesh.quads * 2;
  }
  // untouched instances: bucket by module and level of detail, one instanced draw per bucket
  const data = []; const draws = [];
  for (const mod of usedMods) {
    if (!mod.instances.length || !mod.lod) continue;
    const buckets = [[], [], []];
    for (const inst of mod.instances) {
      const x = inst.cx - camX, y = inst.cy - camY, z = inst.cz - camZ;
      if (!visible(P, x, y, z, inst.rad)) continue;
      const d = Math.max(0, Math.hypot(x, y, z) - inst.rad * 0.5);
      let l = lodFor(d); if (shadowPass) l = Math.min(2, l + 1);
      while (l > 0 && !mod.lod[l]) l--;
      if (!mod.lod[l]) continue;
      buckets[l].push(inst);
    }
    for (let l = 0; l < 3; l++) if (buckets[l].length && mod.lod[l]) {
      draws.push([mod, l, data.length / 4, buckets[l].length]);
      for (const i of buckets[l]) data.push(i.x, i.y, i.z, i.r);
    }
  }
  const arr = new Float32Array(data);
  gl.bindBuffer(gl.ARRAY_BUFFER, instBuf);
  if (arr.byteLength > instCap) { instCap = Math.max(1024, arr.byteLength * 2); gl.bufferData(gl.ARRAY_BUFFER, instCap, gl.DYNAMIC_DRAW); }
  if (arr.byteLength) gl.bufferSubData(gl.ARRAY_BUFFER, 0, arr);
  for (const [mod, l, off, n] of draws) {
    const mesh = mod.lod[l];
    bindMesh(mesh);
    gl.bindBuffer(gl.ARRAY_BUFFER, instBuf);
    gl.enableVertexAttribArray(4); gl.vertexAttribPointer(4, 4, gl.FLOAT, false, 16, off * 16); gl.vertexAttribDivisor(4, 1);
    gl.drawElementsInstanced(gl.TRIANGLES, mesh.quads * 6, gl.UNSIGNED_INT, 0, n);
    stats.draws++; stats.tris += mesh.quads * 2 * n;
    stats['l' + l] = (stats['l' + l] || 0) + mesh.quads * 2 * n;
  }
  gl.vertexAttribDivisor(4, 0); gl.disableVertexAttribArray(4);
  // instances that have been dug into carry their own mesh
  for (const inst of editedList) {
    if (!inst.mesh) continue;
    const x = inst.cx - camX, y = inst.cy - camY, z = inst.cz - camZ;
    if (!visible(P, x, y, z, inst.rad)) continue;
    gl.vertexAttrib4f(4, inst.x, inst.y, inst.z, inst.r);
    bindMesh(inst.mesh); gl.drawElements(gl.TRIANGLES, inst.mesh.quads * 6, gl.UNSIGNED_INT, 0);
    stats.draws++; stats.tris += inst.mesh.quads * 2;
  }
  for (const h of HOOKS) { try { h(gl, shadowPass, vp, lvp, [camX, camY, camZ], SKY.sun); } catch (err) { console.error('draw hook', err); } }
}

// ======================= HUD =======================
const hhmm = (t) => { const m = Math.round(((t + 0.5) % 1) * 1440); return String(Math.floor(m / 60)).padStart(2, '0') + ' h ' + String(m % 60).padStart(2, '0'); };
const fmtB = (b) => b > 1048576 ? (b / 1048576).toFixed(1) + ' Mo' : (b / 1024).toFixed(0) + ' Ko';
let virtualVox = 0; for (const i of instances) virtualVox += i.mod.nvox;
let uniqueVox = 0; for (const m of usedMods) uniqueVox += m.nvox;
const LOAD_MS = performance.now() - T0;
$('info').innerHTML = `<b>GPU :</b> ${GPU_NAME}<br>` +
  `<b>Téléchargé :</b> ${fmtB(DOWNLOAD)} (données ${fmtB(RAW_BYTES)} décompressées) · chargement ${(LOAD_MS / 1000).toFixed(1)} s<br>` +
  `<b>Modules uniques :</b> ${usedMods.length} · <b>instances :</b> ${instances.length}<br>` +
  `<b>Voxels du village :</b> ${(virtualVox / 1e6).toFixed(0)} M (dont ${(uniqueVox / 1e6).toFixed(1)} M stockés une fois) + terrain procédural`;
let fpsN = 0, fpsT = performance.now(), fps = 0, cpuMs = 0, gpuMs = -1, tqObj = null, tqPending = false;
function hud() {
  const mem = MEM.skyvol + MEM.vbo + MEM.shadow + MEM.idx + MEM.hdr;
  let cpuNow = pool.idx.byteLength + pool.pal.byteLength; for (const m of W.mods) cpuNow += m.bricks.byteLength; for (const i of editedList) cpuNow += i.bricks.byteLength;
  $('stats').innerHTML = `<b>${fps.toFixed(0)} img/s</b> · CPU ${cpuMs.toFixed(1)} ms · GPU ${gpuMs >= 0 ? gpuMs.toFixed(1) + ' ms' : 'n/d'}<br>` +
    `${(stats.tris / 1e6).toFixed(2)} M triangles · ${stats.draws} appels · ${canvas.width}×${canvas.height}<br>` +
    `<b>Mémoire GPU :</b> ${fmtB(mem)} (maillages ${fmtB(MEM.vbo)}, ombre ${fmtB(MEM.shadow)}, ciel du village ${fmtB(MEM.skyvol)}, image ${fmtB(MEM.hdr)})<br>` +
    `<b>Heure :</b> ${hhmm(TOD)} (touches , et ; · N : cycle ${skyAuto ? 'en cours' : 'arrêté'}) · soleil ${(Math.asin(Math.max(-1, Math.min(1, SKY.sun[1]))) * 57.3).toFixed(0)}°<br>` +
    `<b>Précalculs :</b> modules ${PRE.mesh.toFixed(0)} ms · terrain ${PRE.terr.toFixed(0)} ms · ciel du village ${PRE.sky.toFixed(0)} ms` +
    (PRE.editN ? ` · remaillage après destruction ${PRE.edit.toFixed(0)} ms` : '') + `<br>` +
    `<b>Mémoire voxels CPU :</b> ${fmtB(cpuNow)} · briques mixtes ${pool.n}<br>` +
    `<b>Destruction :</b> ${(voxelsRemoved / 1000).toFixed(1)} k voxels retirés (dont ${(collapsedTotal / 1000).toFixed(1)} k effondrés) · ${editedCount} modules copiés à l'écriture` +
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
  for (const u of UPDATES) { try { u(dt, now); } catch (err) { console.error('update hook', err); } }
  camX = player.x * VS; camY = (player.y + EYE + player.eyeSmooth) * VS; camZ = player.z * VS;
  const fwd = [-Math.sin(player.yaw) * Math.cos(player.pitch), Math.sin(player.pitch), -Math.cos(player.yaw) * Math.cos(player.pitch)];
  // --- dig
  if (digging && now - lastDig > 110) {
    lastDig = now;
    const h = raycast(camX / VS, camY / VS, camZ / VS, fwd[0], fwd[1], fwd[2], 7 / VS);
    if (h) carve(h.x, h.y, h.z);
  }
  // --- rebuild edited instance meshes
  // --- rebuild the mesh of instances that have been dug into (the grid is built here, meshed in a worker)
  for (const inst of editedList) {
    if (!inst.meshDirty || inst.pending) continue;
    inst.meshDirty = false; inst.pending = 1;
    const g = VX.moduleGrid(inst.mod, inst.bricks, pool, 0);
    const job = ++jobSeq;
    jobs.set(job, (r) => { inst.pending = 0; const old = inst.mesh; inst.mesh = makeMesh(r.v); freeMesh(old); PRE.edit = r.ms || 0; PRE.editN++; });
    nextW().postMessage({ type: 'grid', job, V: g.V, nx: g.nx, ny: g.ny, nz: g.nz, ox: inst.mod.ox - g.B, oy: inst.mod.oy - g.B, oz: inst.mod.oz - g.B, step: 1 }, [g.V.buffer]);
  }
  // --- particles
  for (let i = parts.length - 1; i >= 0; i--) {
    const p = parts[i]; p.life -= dt; if (p.life <= 0) { parts.splice(i, 1); continue; }
    p.vy -= 18 * dt; const nx = p.x + p.vx * dt, ny = p.y + p.vy * dt, nz = p.z + p.vz * dt;
    if (solid(Math.floor(nx / VS), Math.floor(ny / VS), Math.floor(nz / VS))) { p.vy *= -0.25; p.vx *= 0.5; p.vz *= 0.5; } else { p.x = nx; p.y = ny; p.z = nz; }
  }
  selectTerrain(now);
  const nFire = updateFires(now);   // before the world is drawn: the braziers light it
  // --- matrices (camera-relative)
  if (skyAuto) { TOD = (TOD + dt / 240) % 1; updateSky(); }
  const proj = persp(70 * Math.PI / 180, canvas.width / canvas.height, 0.05, 900);
  const view = lookDir(fwd, [0, 1, 0]);
  const vp = mul(proj, view);
  const Pc = planes(vp);
  const SUNV = SKY.sun;
  // light: ortho box around the camera, snapped to texels so the shadow does not crawl
  const lview = lookDir([-SUNV[0], -SUNV[1], -SUNV[2]], [0, 1, 0]);
  const ext = 58, texel = 2 * ext / SH;
  const lc = [lview[0] * camX + lview[4] * camY + lview[8] * camZ, lview[1] * camX + lview[5] * camY + lview[9] * camZ];
  const sx = (Math.round(lc[0] / texel) * texel - lc[0]), sy = (Math.round(lc[1] / texel) * texel - lc[1]);
  const lproj = ortho(-ext + sx, ext + sx, -ext + sy, ext + sy, -220, 220);
  const lvp = mul(lproj, lview);
  stats = { tris: 0, draws: 0, terr: 0 };
  gl.bindVertexArray(vao);
  gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, ibo);
  gl.enable(gl.DEPTH_TEST); gl.enable(gl.CULL_FACE); gl.cullFace(gl.BACK);
  gl.activeTexture(gl.TEXTURE2); gl.bindTexture(gl.TEXTURE_2D, palTex);
  gl.activeTexture(gl.TEXTURE5); gl.bindTexture(gl.TEXTURE_3D, skyvol);
  if (tq && !tqPending) { tqObj = gl.createQuery(); gl.beginQuery(tq.TIME_ELAPSED_EXT, tqObj); }
  if (Q.shadows) {
    gl.activeTexture(gl.TEXTURE3); gl.bindTexture(gl.TEXTURE_2D, null);
    gl.bindFramebuffer(gl.FRAMEBUFFER, shadowFB); gl.viewport(0, 0, SH, SH);
    gl.clear(gl.DEPTH_BUFFER_BIT); gl.enable(gl.POLYGON_OFFSET_FILL); gl.polygonOffset(1.6, 3);
    gl.cullFace(gl.FRONT);
    drawScene(true, lvp, lvp, planes(lvp));
    gl.disable(gl.POLYGON_OFFSET_FILL); gl.cullFace(gl.BACK);
  }
  gl.activeTexture(gl.TEXTURE3); gl.bindTexture(gl.TEXTURE_2D, shadowTex);
  gl.bindFramebuffer(gl.FRAMEBUFFER, hdrFB);
  gl.viewport(0, 0, canvas.width, canvas.height);
  gl.clear(gl.DEPTH_BUFFER_BIT);
  // sky
  gl.disable(gl.DEPTH_TEST); gl.depthMask(false); gl.useProgram(PK.p);
  gl.uniformMatrix4fv(PK.u.u_ivp, false, inv(vp)); setSkyUniforms(PK);
  gl.uniform1f(PK.u.u_time, now / 1000); gl.uniform1f(PK.u.u_exposure, SKY.exposure);
  gl.drawArrays(gl.TRIANGLES, 0, 3); gl.enable(gl.DEPTH_TEST); gl.depthMask(true);
  // world
  drawScene(false, vp, lvp, Pc);
  // water, blended over the opaque pass
  gl.useProgram(PW.p); gl.uniformMatrix4fv(PW.u.u_vp, false, vp); gl.uniform3f(PW.u.u_cam, camX, camY, camZ);
  setSkyUniforms(PW); gl.uniform1f(PW.u.u_time, now / 1000); gl.uniform1f(PW.u.u_fog, SKY.fog); gl.uniform1f(PW.u.u_exposure, SKY.exposure);
  gl.bindBuffer(gl.ARRAY_BUFFER, waterBuf); gl.enableVertexAttribArray(0); gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 8, 0); gl.vertexAttribDivisor(0, 0);
  for (const i of [1, 2, 3, 4]) gl.disableVertexAttribArray(i);
  gl.enable(gl.BLEND); gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA); gl.depthMask(false); gl.disable(gl.CULL_FACE);
  for (const q of ponds) { gl.uniform4f(PW.u.u_pond, q.x * VS, q.level * VS, q.r * VS, q.z * VS); gl.drawArrays(gl.TRIANGLES, 0, 32 * 32 * 6); }
  gl.disable(gl.BLEND); gl.depthMask(true); gl.enable(gl.CULL_FACE);
  // debris
  if (parts.length || nFire) {
    const pd = new Float32Array((parts.length + nFire) * 8);
    parts.forEach((p, i) => { pd.set([p.x, p.y, p.z, p.s, p.c[0], p.c[1], p.c[2], 1], i * 8); });
    if (nFire) pd.set(fireData.subarray(0, nFire * 8), parts.length * 8);
    const nDraw = parts.length + nFire;
    gl.useProgram(PP.p); gl.uniformMatrix4fv(PP.u.u_vp, false, vp); gl.uniform3f(PP.u.u_cam, camX, camY, camZ);
    gl.uniform3fv(PP.u.u_sun, SUNV); gl.uniform3fv(PP.u.u_shL0, SKY.L0); gl.uniform3fv(PP.u.u_sunCol, SKY.sunCol); gl.uniform1f(PP.u.u_exposure, SKY.exposure);
    gl.bindBuffer(gl.ARRAY_BUFFER, cubeBuf); gl.enableVertexAttribArray(0); gl.vertexAttribPointer(0, 3, gl.FLOAT, false, 12, 0); gl.vertexAttribDivisor(0, 0);
    gl.bindBuffer(gl.ARRAY_BUFFER, partBuf); gl.bufferData(gl.ARRAY_BUFFER, pd, gl.STREAM_DRAW);
    gl.enableVertexAttribArray(1); gl.vertexAttribPointer(1, 4, gl.FLOAT, false, 32, 0); gl.vertexAttribDivisor(1, 1);
    gl.enableVertexAttribArray(2); gl.vertexAttribPointer(2, 4, gl.FLOAT, false, 32, 16); gl.vertexAttribDivisor(2, 1);
    gl.disable(gl.CULL_FACE);
    gl.drawArraysInstanced(gl.TRIANGLES, 0, 36, nDraw);
    gl.enable(gl.CULL_FACE);
    gl.vertexAttribDivisor(1, 0); gl.vertexAttribDivisor(2, 0); gl.disableVertexAttribArray(2);
  }
  // --- bloom and tone mapping
  gl.disable(gl.DEPTH_TEST); gl.disable(gl.CULL_FACE);
  for (const i of [0, 1, 2, 3, 4]) gl.disableVertexAttribArray(i);
  if (Q.bloom) {
    gl.bindFramebuffer(gl.FRAMEBUFFER, bloomFB[0]); gl.viewport(0, 0, bloomW, bloomH);
    gl.useProgram(PBRIGHT.p); gl.uniform1i(PBRIGHT.u.u_src, 0);
    gl.activeTexture(gl.TEXTURE0); gl.bindTexture(gl.TEXTURE_2D, hdrTex);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
    gl.useProgram(PBLUR.p); gl.uniform1i(PBLUR.u.u_src, 0);
    for (let p = 0; p < 2; p++) {
      gl.bindFramebuffer(gl.FRAMEBUFFER, bloomFB[1]); gl.uniform2f(PBLUR.u.u_dir, 1 / bloomW, 0);
      gl.bindTexture(gl.TEXTURE_2D, bloomTex[0]); gl.drawArrays(gl.TRIANGLES, 0, 3);
      gl.bindFramebuffer(gl.FRAMEBUFFER, bloomFB[0]); gl.uniform2f(PBLUR.u.u_dir, 0, 1 / bloomH);
      gl.bindTexture(gl.TEXTURE_2D, bloomTex[1]); gl.drawArrays(gl.TRIANGLES, 0, 3);
    }
  }
  // --- sun shafts, only when the sun is low enough to matter and somewhere ahead of the camera
  let rayAmt = 0, sunUV = [0.5, 0.5];
  {
    const S = SKY.sun, p = [0, 0, 0, 0];
    for (let r = 0; r < 4; r++) p[r] = vp[r] * S[0] + vp[4 + r] * S[1] + vp[8 + r] * S[2];   // direction: w = 0
    if (p[3] > 0.05 && SKY.el > -0.02) {
      sunUV = [p[0] / p[3] * 0.5 + 0.5, p[1] / p[3] * 0.5 + 0.5];
      const out = Math.max(0, Math.max(Math.abs(sunUV[0] - 0.5), Math.abs(sunUV[1] - 0.5)) - 0.5);
      rayAmt = Math.max(0, 1 - out * 1.6) * Math.max(0, Math.min(1, (0.55 - SKY.el) * 2.2)) * Math.min(1, (SKY.el + 0.02) * 12);
    }
  }
  if (rayAmt > 0.01) {
    gl.bindFramebuffer(gl.FRAMEBUFFER, bloomFB[2]); gl.viewport(0, 0, bloomW, bloomH);
    gl.useProgram(PRAY.p); gl.uniform1i(PRAY.u.u_src, 0); gl.uniform2f(PRAY.u.u_sunUV, sunUV[0], sunUV[1]);
    gl.activeTexture(gl.TEXTURE0); gl.bindTexture(gl.TEXTURE_2D, hdrTex);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
  }
  gl.bindFramebuffer(gl.FRAMEBUFFER, null); gl.viewport(0, 0, canvas.width, canvas.height);
  gl.useProgram(PPOST.p);
  gl.uniform1i(PPOST.u.u_rays, 2);
  { const k = rayAmt * 0.55 / Math.max(0.3, SKY.sunCol[0]); gl.uniform3f(PPOST.u.u_rayCol, SKY.sunCol[0] * k, SKY.sunCol[1] * k * 0.92, SKY.sunCol[2] * k * 0.8); }
  gl.activeTexture(gl.TEXTURE2); gl.bindTexture(gl.TEXTURE_2D, bloomTex[2]);
  gl.uniform1i(PPOST.u.u_src, 0); gl.uniform1i(PPOST.u.u_bloom, 1);
  gl.uniform1f(PPOST.u.u_bloomAmt, Q.bloom ? 0.42 : 0.0);
  gl.activeTexture(gl.TEXTURE0); gl.bindTexture(gl.TEXTURE_2D, hdrTex);
  gl.activeTexture(gl.TEXTURE1); gl.bindTexture(gl.TEXTURE_2D, Q.bloom ? bloomTex[0] : hdrTex);
  gl.drawArrays(gl.TRIANGLES, 0, 3);
  gl.enable(gl.DEPTH_TEST); gl.enable(gl.CULL_FACE);
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
  window.__stats = { st: stats, tnodes: TNODES.size, tdraw: tdraw.length, tvbo: tv, fps, cpuMs, gpuMs, tris: stats.tris, draws: stats.draws, mem: MEM, terrainPending, parts: parts.length, removed: voxelsRemoved, pre: PRE, sunY: SKY.sun[1], tod: TOD, fires: fireUni[3], collapsed: collapsedTotal, fallen: structFallen, structRuns };
  requestAnimationFrame(frame);
}
// test hooks (used by automated screenshots)
window.__game = {
  skyUniforms: () => SKY,   // read by villagers.js: L0, L1r, L1g, L1b, sun, sunCol, exposure
  dig() { const p = player; const f = [-Math.sin(p.yaw) * Math.cos(p.pitch), Math.sin(p.pitch), -Math.cos(p.yaw) * Math.cos(p.pitch)]; const h = raycast(camX / VS, camY / VS, camZ / VS, f[0], f[1], f[2], 7 / VS); if (h) carve(h.x, h.y, h.z); return !!h; }, startBench, player, carve, raycast, keys, Q, setTool: (t) => { tool = t; updTool(); }, get cam() { return [camX, camY, camZ]; }, M, CX, CZ, heightAt, instances, gl, VS, solid, voxelAt, addDrawHook: (f) => HOOKS.push(f), addUpdate: (f) => UPDATES.push(f), setTOD: (t) => { TOD = t; updateSky(); },
  structTest: (dry) => { const seen = new Set(); let regions = 0; const t = performance.now(); for (const i of instances) { if (seen.has(i)) continue; structTouched.add(i); const r = structuralCheck(dry); regions++; if (r) for (const j of r) seen.add(j); } return { regions, fallen: structFallen, ms: performance.now() - t }; } };
window.dispatchEvent(new Event('village-ready'));
requestAnimationFrame(frame);
})().catch((e) => { console.error(e); document.getElementById('loadmsg').textContent = 'Erreur : ' + e.message; });
