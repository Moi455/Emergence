// web-ocean : MIT License, Copyright (c) 2026 Maksymilian Dendura (voir LICENSE à côté de ce fichier).
// Module généré par engine-rs/scripts/extract_web_ocean.py : NE PAS ÉDITER à la main.
// Source : sky.js (export SKY_RENDER_FUNCS), SHA-256 du fichier source 23a43cdc394b41e0b1e3610c76139b1bc2e6b7b4ffd3249c68cb08a4b7e9d45f.

fn pcgHash(v: u32) -> u32 {
  let s = v * 747796405u + 2891336453u;
  let w = ((s >> ((s >> 28u) + 4u)) ^ s) * 277803737u;
  return (w >> 22u) ^ w;
}
fn hashGrad(i: vec2i) -> vec2f {
  let h = pcgHash(u32(i.x) * 1664525u + pcgHash(u32(i.y) + 1013904223u));
  let a = f32(h) * (6.28318530718 / 4294967296.0);
  return vec2f(cos(a), sin(a));
}
fn gnoise(p: vec2f) -> f32 {
  let i = vec2i(floor(p));
  let f = p - floor(p);
  let u = f * f * f * (f * (f * 6.0 - 15.0) + 10.0);
  let a = dot(hashGrad(i), f);
  let b = dot(hashGrad(i + vec2i(1, 0)), f - vec2f(1.0, 0.0));
  let c = dot(hashGrad(i + vec2i(0, 1)), f - vec2f(0.0, 1.0));
  let d = dot(hashGrad(i + vec2i(1, 1)), f - vec2f(1.0, 1.0));
  return mix(mix(a, b, u.x), mix(c, d, u.x), u.y);
}

const SKY_W: f32 = 256.0;
const SKY_H: f32 = 144.0;

fn camR() -> f32 { return RG + F.atmo.y; }

fn sampleTrans(r: f32, mu: f32) -> vec3f {
  return textureSampleLevel(transLUT, sampC, transRMuToUV(r, mu), 0.0).rgb;
}

fn sunIlluminance() -> vec3f {
  return sampleTrans(camR(), F.sunDir.y) * F.sunDir.w;
}

fn skyViewUV(dir: vec3f) -> vec2f {
  let r = camR();
  let vHorizon = rhoOf(r);
  let cosBeta = vHorizon / r;
  let beta = acos(clamp(cosBeta, -1.0, 1.0));
  let zha = PI - beta;
  let vzc = clamp(dir.y, -1.0, 1.0);
  var uv: vec2f;
  if (vzc >= -cosBeta) {
    var coord = acos(vzc) / zha;
    coord = 1.0 - coord;
    coord = sqrt(max(coord, 0.0));
    coord = 1.0 - coord;
    uv.y = coord * 0.5;
  } else {
    var coord = (acos(vzc) - zha) / beta;
    coord = sqrt(max(coord, 0.0));
    uv.y = coord * 0.5 + 0.5;
  }
  let dl = length(dir.xz);
  let sl = length(F.sunDir.xz);
  var lvc = 1.0;
  if (dl > 1e-6 && sl > 1e-6) { lvc = clamp(dot(dir.xz, F.sunDir.xz) / (dl * sl), -1.0, 1.0); }
  uv.x = sqrt(max(-lvc * 0.5 + 0.5, 0.0));
  return vec2f(fromUnitToSubUvs(uv.x, SKY_W), fromUnitToSubUvs(uv.y, SKY_H));
}

// [ADAPTATION EM] ombre de la planète : web-ocean n'éclaire jamais la nuit (nuages roses à minuit).
// Le soleil sous l'horizon géométrique du point `r` (rayon depuis le centre, km) est éteint en douceur.
fn planetShadow(r: f32, mu: f32) -> f32 {
  let h = rhoOf(r) / r;
  return smoothstep(-h - 0.006, -h + 0.002, mu);
}

fn skyAtmo(dir: vec3f) -> vec3f {
  return textureSampleLevel(skyLUT, sampC, skyViewUV(dir), 0.0).rgb * F.sunDir.w;
}
