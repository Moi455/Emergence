// Ambiance du ciel des six faces d'un voxel et éclairement du soleil, calculés UNE fois par image dans une texture de
// 7 x 1 (au lieu de 8 lectures du ciel par pixel) : texel 0 à 5 = +x, -x, +y, -y, +z, -z ; texel 6 = soleil.
// Assemblé après : ciel (Frame, atmo_core, sky_render_funcs), mesh_sky. Groupe 0 = ciel, comme le fond.
@group(0) @binding(0) var<uniform> F: Frame;
@group(0) @binding(1) var transLUT: texture_2d<f32>;
@group(0) @binding(2) var skyLUT: texture_2d<f32>;
@group(0) @binding(3) var sampC: sampler;

@vertex fn vs(@builtin(vertex_index) i: u32) -> @builtin(position) vec4<f32> {
  let p = vec2<f32>(f32((i << 1u) & 2u), f32(i & 2u)) * 2.0 - 1.0;
  return vec4<f32>(p, 0.0, 1.0);
}

@fragment fn fs(@builtin(position) pos: vec4<f32>) -> @location(0) vec4<f32> {
  let e_sun = sunIlluminance() * planetShadow(camR(), F.sunDir.y);
  let ciel_haut = skyAtmo(vec3<f32>(0.0, 1.0, 0.0));
  // Rebond provisoire du sol (sous l'horizon), identique à l'éclairage différé de L09.
  let rebond = 0.18 * (e_sun * (max(F.sunDir.y, 0.0) * 0.35 / PI_M) + ciel_haut * 0.6);
  let i = u32(pos.x);
  switch (i) {
    case 0u: { return vec4<f32>(sky_hemisphere(vec3<f32>(1.0, 0.0, 0.0), rebond), 1.0); }
    case 1u: { return vec4<f32>(sky_hemisphere(vec3<f32>(-1.0, 0.0, 0.0), rebond), 1.0); }
    case 2u: { return vec4<f32>(sky_hemisphere(vec3<f32>(0.0, 1.0, 0.0), rebond), 1.0); }
    case 3u: { return vec4<f32>(sky_hemisphere(vec3<f32>(0.0, -1.0, 0.0), rebond), 1.0); }
    case 4u: { return vec4<f32>(sky_hemisphere(vec3<f32>(0.0, 0.0, 1.0), rebond), 1.0); }
    case 5u: { return vec4<f32>(sky_hemisphere(vec3<f32>(0.0, 0.0, -1.0), rebond), 1.0); }
    default: { return vec4<f32>(e_sun, 1.0); }
  }
}
