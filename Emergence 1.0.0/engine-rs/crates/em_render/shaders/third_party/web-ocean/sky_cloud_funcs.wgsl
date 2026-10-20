// web-ocean : MIT License, Copyright (c) 2026 Maksymilian Dendura (voir LICENSE à côté de ce fichier).
// Module généré par engine-rs/scripts/extract_web_ocean.py : NE PAS ÉDITER à la main.
// Source : sky.js (export SKY_CLOUD_FUNCS), SHA-256 du fichier source 23a43cdc394b41e0b1e3610c76139b1bc2e6b7b4ffd3249c68cb08a4b7e9d45f.


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
    if (w <= 0.0) { break; } // [ADAPTATION EM] octave déjà éteinte, les suivantes aussi : on ne les calcule plus
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
  let sunC = sampleTrans(RG + hc, dot(h.up, F.sunDir.xyz)) * F.sunDir.w * planetShadow(RG + hc, dot(h.up, F.sunDir.xyz)); // [ADAPTATION EM]
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
