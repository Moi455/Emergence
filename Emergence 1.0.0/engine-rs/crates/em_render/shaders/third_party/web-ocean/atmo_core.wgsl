// web-ocean : MIT License, Copyright (c) 2026 Maksymilian Dendura (voir LICENSE à côté de ce fichier).
// Module généré par engine-rs/scripts/extract_web_ocean.py : NE PAS ÉDITER à la main.
// Source : common.js (export ATMO_CORE_WGSL), SHA-256 du fichier source d759a8d1c5d52ad93c46b92d274af5dc8afbe7da349cf63c1330a54cd2c13bff.

const PI: f32 = 3.14159265358979;
const RG: f32 = 6360.0;
const RT: f32 = 6460.0;
const RAY_S: vec3f = vec3f(5.802e-3, 13.558e-3, 33.1e-3);
const MIE_S: f32 = 3.996e-3;
const MIE_E: f32 = 4.40e-3;
const OZO_A: vec3f = vec3f(0.650e-3, 1.881e-3, 0.085e-3);
const SUN_ANG_R: f32 = 0.004675;
const TRANS_W: f32 = 256.0;
const TRANS_H: f32 = 64.0;
const MS_SIZE: f32 = 32.0;

struct Medium { ext: vec3f, rayS: vec3f, mieS: f32 };

fn medium(h: f32, haze: f32) -> Medium {
  let hh = max(h, 0.0);
  let dR = exp(-hh / 8.0);
  // aerosols: regular 1.2 km layer plus a dense marine boundary layer
  let dM = exp(-hh / 1.2);
  let dO = max(0.0, 1.0 - abs(hh - 25.0) / 15.0);
  var m: Medium;
  m.rayS = RAY_S * dR;
  m.mieS = MIE_S * dM * haze;
  m.ext = m.rayS + vec3f(MIE_E * dM * haze) + OZO_A * dO;
  return m;
}

fn raySphere(ro: vec3f, rd: vec3f, R: f32) -> vec2f {
  let l = length(ro);
  let b = dot(ro, rd);
  let c = (l - R) * (l + R);
  let d = b * b - c;
  if (d < 0.0) { return vec2f(-1.0, -1.0); }
  let s = sqrt(d);
  return vec2f(-b - s, -b + s);
}

fn rhoOf(r: f32) -> f32 { return sqrt(max(0.0, (r - RG) * (r + RG))); }

fn transRMuToUV(r: f32, mu: f32) -> vec2f {
  let H = sqrt(RT * RT - RG * RG);
  let rho = rhoOf(r);
  let disc = r * r * (mu * mu - 1.0) + RT * RT;
  let d = max(0.0, -r * mu + sqrt(max(disc, 0.0)));
  let dMin = RT - r;
  let dMax = rho + H;
  let x = (d - dMin) / (dMax - dMin);
  let y = rho / H;
  return vec2f(x, y);
}

fn transUVToRMu(uv: vec2f) -> vec2f {
  let H = sqrt(RT * RT - RG * RG);
  let rho = H * uv.y;
  let r = sqrt(rho * rho + RG * RG);
  let dMin = RT - r;
  let dMax = rho + H;
  let d = dMin + uv.x * (dMax - dMin);
  var mu = 1.0;
  if (d > 0.0) { mu = (H * H - rho * rho - d * d) / (2.0 * r * d); }
  return vec2f(r, clamp(mu, -1.0, 1.0));
}

fn fromUnitToSubUvs(u: f32, res: f32) -> f32 { return (u + 0.5 / res) * (res / (res + 1.0)); }
fn fromSubUvsToUnit(u: f32, res: f32) -> f32 { return (u - 0.5 / res) * (res / (res - 1.0)); }

fn phaseRayleigh(c: f32) -> f32 { return 3.0 / (16.0 * PI) * (1.0 + c * c); }
fn phaseMie(c: f32, g: f32) -> f32 {
  let g2 = g * g;
  return 3.0 / (8.0 * PI) * ((1.0 - g2) * (1.0 + c * c)) / ((2.0 + g2) * pow(max(1.0 + g2 - 2.0 * g * c, 1e-4), 1.5));
}
fn phaseHG(c: f32, g: f32) -> f32 {
  let g2 = g * g;
  return (1.0 - g2) / (4.0 * PI * pow(max(1.0 + g2 - 2.0 * g * c, 1e-4), 1.5));
}

// true when the sun is below the geometric horizon of a point at radius r
fn sunBelowHorizon(r: f32, mu: f32) -> bool {
  return mu < -rhoOf(r) / r;
}
