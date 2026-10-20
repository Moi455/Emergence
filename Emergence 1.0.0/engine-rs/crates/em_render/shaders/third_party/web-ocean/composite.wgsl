// web-ocean : MIT License, Copyright (c) 2026 Maksymilian Dendura (voir LICENSE à côté de ce fichier).
// Module généré par engine-rs/scripts/extract_web_ocean.py : NE PAS ÉDITER à la main.
// Source : post.js (export COMPOSITE), SHA-256 du fichier source d19d7ad8301a4eb236d8bfec8ad1fd15bf736738c2501ca5695a7c65664df0ef.

struct VO { @builtin(position) pos: vec4f, @location(0) uv: vec2f };
@vertex fn vs(@builtin(vertex_index) i: u32) -> VO {
  let p = vec2f(f32((i << 1u) & 2u), f32(i & 2u));
  var o: VO;
  o.pos = vec4f(p * 2.0 - 1.0, 0.0, 1.0);
  o.uv = vec2f(p.x, 1.0 - p.y);
  return o;
}

struct P { p: vec4f, q: vec4f };  // p: exposure, bloom, frame, vignette; q: saturation, contrast, warmth, grain
@group(0) @binding(0) var hdr: texture_2d<f32>;
@group(0) @binding(1) var bloom: texture_2d<f32>;
@group(0) @binding(2) var samp: sampler;
@group(0) @binding(3) var<uniform> U: P;

fn agxContrast(x: vec3f) -> vec3f {
  let x2 = x * x;
  let x4 = x2 * x2;
  return 15.5 * x4 * x2 - 40.14 * x4 * x + 31.96 * x4 - 6.868 * x2 * x + 0.4298 * x2 + 0.1191 * x - 0.00232;
}
fn agx(v: vec3f) -> vec3f {
  let m = mat3x3f(0.842479062253094, 0.0423282422610123, 0.0423756549057051,
                  0.0784335999999992, 0.878468636469772, 0.0784336,
                  0.0792237451477643, 0.0791661274605434, 0.879142973793104);
  let minEv = -12.47393;
  let maxEv = 4.026069;
  var x = m * max(v, vec3f(1e-10));
  x = clamp(log2(x), vec3f(minEv), vec3f(maxEv));
  x = (x - minEv) / (maxEv - minEv);
  return agxContrast(x);
}
fn agxEotf(v: vec3f) -> vec3f {
  let mi = mat3x3f(1.19687900512017, -0.0528968517574562, -0.0529716355144438,
                   -0.0980208811401368, 1.15190312990417, -0.0980434501171241,
                   -0.0990297440797205, -0.0989611768448433, 1.15107367264116);
  return mi * v;
}
fn agxLook(v: vec3f, sat: f32, power: f32) -> vec3f {
  let l = dot(v, vec3f(0.2126, 0.7152, 0.0722));
  let p = pow(max(v, vec3f(0.0)), vec3f(power));
  return l + sat * (p - l);
}
fn ign(p: vec2f) -> f32 { return fract(52.9829189 * fract(dot(p, vec2f(0.06711056, 0.00583715)))); }

@fragment fn fs(in: VO) -> @location(0) vec4f {
  let dims = vec2f(textureDimensions(hdr));
  let pc = vec2i(in.pos.xy);
  var c = textureLoad(hdr, pc, 0).rgb;
  // the up-chain accumulates 8 blur levels
  let b = textureSampleLevel(bloom, samp, in.uv, 0.0).rgb * (1.0 / 8.0);
  c = mix(c, b, U.p.y);
  c *= U.p.x;
  // subtle vignette
  let d = (in.uv - 0.5) * vec2f(dims.x / dims.y, 1.0);
  c *= 1.0 - U.p.w * dot(d, d);
  c *= vec3f(1.0 + U.q.z, 1.0, 1.0 - U.q.z);
  // film/sensor-like highlight desaturation: very bright glints and the sun go towards white
  let lum = dot(c, vec3f(0.2126, 0.7152, 0.0722));
  c = mix(c, vec3f(lum), smoothstep(0.7, 6.0, lum) * 0.55);
  var o = agx(c);
  o = agxLook(o, U.q.x, U.q.y);
  o = agxEotf(o);
  // triangular dither against banding in the sky gradients
  let n = ign(in.pos.xy + U.p.z * 5.588238) + ign(in.pos.xy * 1.37 + 17.0 + U.p.z * 3.1) - 1.0;
  o += n / 255.0;
  // [ADAPTATION EM] cible sRGB : le materiel ré-encode, on rend donc le signal linéaire (EOTF d'AgX).
  return vec4f(pow(clamp(o, vec3f(0.0), vec3f(1.0)), vec3f(2.2)), 1.0);
}
