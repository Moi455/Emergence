// web-ocean : MIT License, Copyright (c) 2026 Maksymilian Dendura (voir LICENSE à côté de ce fichier).
// Module généré par engine-rs/scripts/extract_web_ocean.py : NE PAS ÉDITER à la main.
// Source : sky.js (export ENV_CUBE), SHA-256 du fichier source 23a43cdc394b41e0b1e3610c76139b1bc2e6b7b4ffd3249c68cb08a4b7e9d45f.

//@FRAME_WGSL

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

@group(0) @binding(0) var<uniform> F: Frame;
@group(0) @binding(1) var transLUT: texture_2d<f32>;
@group(0) @binding(2) var skyLUT: texture_2d<f32>;
@group(0) @binding(3) var sampC: sampler;
@group(0) @binding(4) var dst: texture_storage_2d_array<rgba16float, write>;

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

fn skyAtmo(dir: vec3f) -> vec3f {
  return textureSampleLevel(skyLUT, sampC, skyViewUV(dir), 0.0).rgb * F.sunDir.w;
}


// ---- clouds -------------------------------------------------------------
// Two thin, light-aware layers: broken low cumulus with cauliflower edges (2 km) and
// high cirrus wisps (7 km). Each is shaded with self-shadowing towards the sun, bright
// sun-facing rims, silver linings on thin back-lit parts and warm multiple scattering.
const CLOUD_ROT: mat2x2f = mat2x2f(0.8, 0.6, -0.6, 0.8);
// fbm whose octaves fade once smaller than the pixel footprint fp (noise units);
// 'billow' turns the small octaves into bulgy |noise| for cauliflower-like edges
fn cloudFbm(p: vec2f, fp: f32, oct: i32, billow: f32) -> f32 {
  var s = 0.0;
  var a = 0.5;
  var q = p;
  var f = 1.0;
  for (var i = 0; i < oct; i++) {
    // fade octaves well before they reach pixel size (half-res buffer) -> no shimmer in motion
    let w = 1.0 - smoothstep(0.08, 0.28, fp * f);
    var n = gnoise(q);
    if (i >= 2) { n = mix(n, abs(n) * 2.0 - 0.38, billow); }
    s += a * n * w;
    q = CLOUD_ROT * q * 2.03 + vec2f(13.1, 7.7);
    f *= 2.03;
    a *= 0.5;
  }
  return s;
}
// Signed "edge" functions (cloud where > 0) and their density ramps. The edge value is
// what the sky pass differentiates (fwidth) to anti-alias the cloud silhouettes analytically.
fn lowEdge(q: vec2f, fp: f32, oct: i32) -> f32 {
  let t = F.cloudP.w;
  var p = q * 0.38 + vec2f(t * 0.004, t * 0.0012);
  let w = vec2f(gnoise(p * 0.3 + vec2f(1.7, 9.2)), gnoise(p * 0.3 + vec2f(8.3, 2.8)));
  p += w * 1.4;
  // slightly elongated cells (cloud streets), mildly billowy small scales for ragged edges
  let base = cloudFbm(p * vec2f(1.0, 1.7), fp * 0.65, oct, 0.35) * 1.3 + 0.5;
  let large = gnoise(q * 0.05 + vec2f(3.1, 1.3)) * 0.7;
  return base + large - (1.0 - F.cloudP.y);
}
fn lowSoft(fp: f32) -> f32 { return 0.38 + min(fp * 0.65, 1.0) * 0.3; }
fn lowDensity(q: vec2f, fp: f32, oct: i32) -> f32 {
  return clamp(lowEdge(q, fp, oct) / lowSoft(fp), 0.0, 1.0);
}
fn highEdge(q: vec2f, fp: f32, oct: i32) -> f32 {
  let t = F.cloudP.w;
  // altostratus deck: smooth, slightly fibrous
  let p = CLOUD_ROT * (q * vec2f(0.09, 0.20)) + vec2f(t * 0.0015, 0.0);
  let n = cloudFbm(p, fp * 0.2, oct, 0.0) * 1.25 + 0.5;
  let big = gnoise(q * 0.012 + vec2f(7.0, 3.0)) * 0.6;
  return n + big - (1.0 - F.atmo.z);
}
fn highSoft(fp: f32) -> f32 { return 0.85 + min(fp * 0.2, 1.0) * 0.3; }
fn highDensity(q: vec2f, fp: f32, oct: i32) -> f32 {
  return clamp(highEdge(q, fp, oct) / highSoft(fp), 0.0, 1.0);
}

struct CloudHit { t: f32, q: vec2f, mu: f32, up: vec3f };
fn hitLayer(dir: vec3f, hc: f32) -> CloudHit {
  var h: CloudHit;
  let ro = vec3f(0.0, camR(), 0.0);
  h.t = raySphere(ro, dir, RG + hc).y;
  let p = ro + dir * h.t;
  h.up = p / length(p);
  h.q = p.xz + F.camPos.xz * 0.001;
  h.mu = max(dot(h.up, dir), 0.03);
  return h;
}

// d: density at the hit; s1..s3: densities 80 m / 250 m / 600 m towards the sun
fn shadeLayer(dir: vec3f, h: CloudHit, hc: f32, d: f32, s1: f32, s2: f32, s3: f32, sigma: f32, g: f32) -> vec4f {
  let tau = d * sigma / h.mu;
  let alpha = 1.0 - exp(-tau);
  let tauS = (d * 0.5 + s1 * 0.6 + s2 + s3 * 0.7) * sigma * 0.55;
  let Ts = exp(-tauS);
  let sunC = sampleTrans(RG + hc, dot(h.up, F.sunDir.xyz)) * F.sunDir.w;
  let cosT = dot(dir, F.sunDir.xyz);
  let ph = mix(phaseHG(cosT, g), phaseHG(cosT, -0.2), 0.25);
  let fwd = smoothstep(-0.2, 0.7, cosT);
  // single scattering: reflected when front-lit, transmitted through thin parts when back-lit
  let single = sunC * Ts * ph * mix(alpha * 0.55, tau * exp(-tau) * 2.2, fwd) * 3.0;
  // edges where density falls off towards the sun catch direct light
  let rim = clamp((d - s1) * 2.5, 0.0, 1.0);
  // multiple scattering: a low sun lights cloud tops and sun-facing flanks, not the bases we
  // see from below, so diffused sunlight shows mostly when looking towards the sun
  let toward = smoothstep(-0.3, 0.9, cosT);
  let ms = sunC * (0.025 + 0.22 * rim) * mix(1.0, Ts, 0.5) * alpha * (0.25 + 0.75 * toward);
  // bases are lit by the sky from the sides/below (horizon band + sea), cooler than the tops
  let amb = (skyAtmo(normalize(vec3f(dir.x, 0.03, dir.z))) * 0.26 + skyAtmo(vec3f(0.0, 1.0, 0.0)) * 0.42)
            * alpha * (1.0 - 0.35 * d);
  return vec4f(single + ms + amb, alpha);
}

// returns (premultiplied radiance, fraction of the background sky hidden)
// aa: per-layer edge change per pixel (fwidth of the edge function); negative = estimate it
// from the pixel footprint (compute passes, which have no derivatives)
fn cloudLayers(dir: vec3f, pixAng: f32, aa: vec2f, sunT: ptr<function, f32>) -> vec4f {
  *sunT = 1.0;
  if (dir.y <= 0.0) { return vec4f(0.0); }
  let sxz = F.sunDir.xz / max(length(F.sunDir.xz), 1e-4);
  var lo = vec4f(0.0);
  var loVis = 1.0;
  if (F.cloudP.y > 0.001) {
    let hc = F.cloudP.x;
    let h = hitLayer(dir, hc);
    // clear band near the horizon, where the low sun shines under the clouds
    let far = 1.0 - smoothstep(18.0, 36.0, h.t);
    if (far > 0.0) {
      let fp = h.t * pixAng / h.mu;
      let e = lowEdge(h.q, fp, 7);
      let d = clamp(e / lowSoft(fp), 0.0, 1.0) * far;
      if (d > 0.002) {
        let s1 = lowDensity(h.q + sxz * 0.08, fp, 5) * far;
        let s2 = lowDensity(h.q + sxz * 0.25, fp, 4) * far;
        let s3 = lowDensity(h.q + sxz * 0.6, fp, 3) * far;
        lo = shadeLayer(dir, h, hc, d, s1, s2, s3, F.cloudP.z, 0.75);
        // opacity saturates within a sliver of the density ramp, making a hard silhouette:
        // spread it over ~1.5 pixels
        let aw = select(fp * 0.38 * 2.5, aa.x, aa.x >= 0.0);
        lo *= smoothstep(0.0, aw * 1.5 + 1e-6, e);
        loVis = exp(-h.t * 0.02 * (0.6 + 0.4 * F.atmo.x));
      }
    }
  }
  var hi = vec4f(0.0);
  var hiVis = 1.0;
  if (F.atmo.z > 0.001) {
    let hc = 4.5;
    let h = hitLayer(dir, hc);
    let far = 1.0 - smoothstep(30.0, 70.0, h.t);
    if (far > 0.0) {
      let fp = h.t * pixAng / h.mu;
      let e = highEdge(h.q, fp, 6);
      let d = clamp(e / highSoft(fp), 0.0, 1.0) * far;
      if (d > 0.002) {
        let s1 = highDensity(h.q + sxz * 0.15, fp, 4) * far;
        let s2 = highDensity(h.q + sxz * 0.5, fp, 3) * far;
        hi = shadeLayer(dir, h, hc, d, s1, s2, s2, F.atmo.w, 0.80);
        let aw = select(fp * 0.2 * 2.5, aa.y, aa.y >= 0.0);
        hi *= smoothstep(0.0, aw * 1.5 + 1e-6, e);
        hiVis = exp(-h.t * 0.010 * (0.6 + 0.4 * F.atmo.x));
      }
    }
  }
  *sunT = (1.0 - lo.a) * (1.0 - hi.a);
  // low layer in front; aerial perspective fades each layer into the haze without making
  // it transparent to the layer behind
  let col = lo.rgb * loVis + hi.rgb * hiVis * (1.0 - lo.a);
  let hidden = lo.a * loVis + hi.a * hiVis * (1.0 - lo.a);
  return vec4f(col, hidden);
}

fn sunDisk(dir: vec3f) -> vec3f {
  let c = dot(dir, F.sunDir.xyz);
  let ang = sqrt(max(2.0 * (1.0 - c), 0.0));
  let pix = F.screen.w * 2.0 * length(F.camUp.xyz) * 0.75;
  let edge = 1.0 - smoothstep(SUN_ANG_R - pix, SUN_ANG_R + pix, ang);
  if (edge <= 0.0) { return vec3f(0.0); }
  let x = min(ang / SUN_ANG_R, 1.0);
  let mu = sqrt(max(1.0 - x * x, 0.0));
  let limb = vec3f(1.0) - vec3f(0.397, 0.503, 0.652) * (1.0 - mu);
  let rad = F.sunDir.w / (PI * SUN_ANG_R * SUN_ANG_R);
  return rad * limb * edge * sampleTrans(camR(), max(dir.y, -0.01));
}

fn skyRadiance(dirIn: vec3f, withSun: bool, pixAng: f32) -> vec3f {
  var dir = dirIn;
  dir.y = max(dir.y, 0.0005);
  dir = normalize(dir);
  var L = skyAtmo(dir);
  var sunT = 1.0;
  let cl = cloudLayers(dir, pixAng, vec2f(-1.0), &sunT);
  L = L * (1.0 - cl.a) + cl.rgb;
  if (withSun) { L += sunDisk(dir) * sunT; }
  return L;
}

const ENV: f32 = 256.0;
fn faceDir(face: u32, uv: vec2f) -> vec3f {
  let u = uv.x * 2.0 - 1.0;
  let v = uv.y * 2.0 - 1.0;
  switch (face) {
    case 0u: { return vec3f(1.0, -v, -u); }
    case 1u: { return vec3f(-1.0, -v, u); }
    case 2u: { return vec3f(u, 1.0, v); }
    case 3u: { return vec3f(u, -1.0, -v); }
    case 4u: { return vec3f(u, -v, 1.0); }
    default: { return vec3f(-u, -v, -1.0); }
  }
}
@compute @workgroup_size(8, 8, 1)
fn main(@builtin(global_invocation_id) id: vec3u) {
  if (f32(id.x) >= ENV || f32(id.y) >= ENV) { return; }
  // faces are refreshed round-robin: face = (frame + z) % 6
  let face = (u32(F.post.z) + id.z) % 6u;
  let dir = normalize(faceDir(face, (vec2f(id.xy) + 0.5) / ENV));
  var L: vec3f;
  if (dir.y >= 0.0) {
    L = skyRadiance(dir, false, 1.5708 / ENV * 1.5);
  } else {
    // below the horizon: what a reflected ray would see -> far, hazy ocean
    let hz = skyRadiance(normalize(vec3f(dir.x, 0.004, dir.z)), false, 1.5708 / ENV * 1.5);
    let body = F.waterCol.rgb * (sunIlluminance() * max(F.sunDir.y, 0.0) + skyAtmo(vec3f(0.0, 1.0, 0.0)) * 2.0);
    L = mix(hz * 0.75, body, clamp(-dir.y * 6.0, 0.0, 1.0));
  }
  textureStore(dst, id.xy, face, vec4f(L, 1.0));
}
