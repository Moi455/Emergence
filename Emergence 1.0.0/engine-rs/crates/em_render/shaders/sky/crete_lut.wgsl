// Calcul unique de la LUT des crêtes : 4096 azimuts, une pente par couche (rgb). Azimut 0 = -Z, positif vers +X.
@group(0) @binding(0) var dst: texture_storage_2d<rgba16float, write>;

@compute @workgroup_size(64, 1, 1)
fn main(@builtin(global_invocation_id) id: vec3u) {
  if (id.x >= 4096u) { return; }
  let a = f32(id.x) * (6.28318530718 / 4096.0);
  let az = vec2f(sin(a), -cos(a));
  textureStore(dst, vec2u(id.x, 0u), vec4f(ridgeSlope(az, 0.0), ridgeSlope(az, 1.0), ridgeSlope(az, 2.0), 1.0));
}
