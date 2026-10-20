// web-ocean : MIT License, Copyright (c) 2026 Maksymilian Dendura (voir LICENSE à côté de ce fichier).
// Module généré par engine-rs/scripts/extract_web_ocean.py : NE PAS ÉDITER à la main.
// Source : sky.js (export CUBE_MIPS), SHA-256 du fichier source 23a43cdc394b41e0b1e3610c76139b1bc2e6b7b4ffd3249c68cb08a4b7e9d45f.

@group(0) @binding(0) var src: texture_2d_array<f32>;
@group(0) @binding(1) var dst: texture_storage_2d_array<rgba16float, write>;
@compute @workgroup_size(8, 8, 1)
fn main(@builtin(global_invocation_id) id: vec3u) {
  let size = textureDimensions(dst);
  if (id.x >= size.x || id.y >= size.y) { return; }
  let srcSize = vec2i(textureDimensions(src));
  let p = vec2i(id.xy) * 2;
  // 4x4 tent-ish filter for smoother roughness blur
  var acc = vec4f(0.0);
  var wsum = 0.0;
  for (var j = -1; j <= 2; j++) {
    for (var i = -1; i <= 2; i++) {
      let q = clamp(p + vec2i(i, j), vec2i(0), srcSize - 1);
      let w = select(1.0, 3.0, i == 0 || i == 1) * select(1.0, 3.0, j == 0 || j == 1);
      acc += textureLoad(src, q, id.z, 0) * w;
      wsum += w;
    }
  }
  textureStore(dst, id.xy, id.z, acc / wsum);
}
