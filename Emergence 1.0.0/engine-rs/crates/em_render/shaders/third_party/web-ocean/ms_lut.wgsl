// web-ocean : MIT License, Copyright (c) 2026 Maksymilian Dendura (voir LICENSE à côté de ce fichier).
// Module généré par engine-rs/scripts/extract_web_ocean.py : NE PAS ÉDITER à la main.
// Source : sky.js (export MS_LUT), SHA-256 du fichier source 23a43cdc394b41e0b1e3610c76139b1bc2e6b7b4ffd3249c68cb08a4b7e9d45f.

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

struct AtmoP { haze: vec4f };   // x = mie multiplier
@group(0) @binding(0) var<uniform> A: AtmoP;

@group(0) @binding(1) var transLUT: texture_2d<f32>;
@group(0) @binding(2) var sampC: sampler;
@group(0) @binding(3) var dst: texture_storage_2d<rgba16float, write>;

fn sampleTrans(r: f32, mu: f32) -> vec3f {
  return textureSampleLevel(transLUT, sampC, transRMuToUV(r, mu), 0.0).rgb;
}

@compute @workgroup_size(8, 8, 1)
fn main(@builtin(global_invocation_id) id: vec3u) {
  if (f32(id.x) >= MS_SIZE || f32(id.y) >= MS_SIZE) { return; }
  var uv = (vec2f(id.xy) + 0.5) / MS_SIZE;
  uv = vec2f(fromSubUvsToUnit(uv.x, MS_SIZE), fromSubUvsToUnit(uv.y, MS_SIZE));
  let cosSun = uv.x * 2.0 - 1.0;
  let h = max(uv.y * (RT - RG), 0.01);
  let r = RG + h;
  let ro = vec3f(0.0, r, 0.0);
  let sun = vec3f(sqrt(max(0.0, 1.0 - cosSun * cosSun)), cosSun, 0.0);
  var Lsum = vec3f(0.0);
  var Fsum = vec3f(0.0);
  let SQ = 8u;
  let STEPS = 20u;
  for (var a = 0u; a < SQ; a++) {
    for (var b = 0u; b < SQ; b++) {
      let th = acos(1.0 - 2.0 * (f32(b) + 0.5) / f32(SQ));
      let ph = 2.0 * PI * (f32(a) + 0.5) / f32(SQ);
      let rd = vec3f(sin(th) * cos(ph), cos(th), sin(th) * sin(ph));
      let tTop = raySphere(ro, rd, RT);
      let tGr = raySphere(ro, rd, RG);
      var tMax = tTop.y;
      let hitG = tGr.x > 0.0;
      if (hitG) { tMax = tGr.x; }
      let dt = tMax / f32(STEPS);
      var T = vec3f(1.0);
      var L = vec3f(0.0);
      var Fms = vec3f(0.0);
      for (var s = 0u; s < STEPS; s++) {
        let p = ro + rd * ((f32(s) + 0.5) * dt);
        let pr = length(p);
        let m = medium(pr - RG, A.haze.x);
        let scat = m.rayS + vec3f(m.mieS);
        let Ts = exp(-m.ext * dt);
        let smu = dot(p, sun) / pr;
        var sunT = sampleTrans(pr, smu);
        if (sunBelowHorizon(pr, smu)) { sunT = vec3f(0.0); }
        let ext = max(m.ext, vec3f(1e-9));
        let S = scat * sunT / (4.0 * PI);
        L += T * (S - S * Ts) / ext;
        Fms += T * (scat - scat * Ts) / ext;
        T *= Ts;
      }
      if (hitG) {
        let pg = ro + rd * tMax;
        let ng = normalize(pg);
        let smu = dot(ng, sun);
        L += T * sampleTrans(RG, smu) * max(smu, 0.0) * 0.06 / PI;
      }
      Lsum += L;
      Fsum += Fms;
    }
  }
  let invN = 1.0 / f32(SQ * SQ);
  let L2 = Lsum * invN;
  let fms = Fsum * invN;
  textureStore(dst, id.xy, vec4f(L2 / (1.0 - fms), 1.0));
}
