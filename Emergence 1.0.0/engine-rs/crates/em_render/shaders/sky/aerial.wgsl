// Perspective aérienne exposée aux passes suivantes (docs/19 § 5.6, brume en L-ultérieure).
// À inclure APRÈS `frame.wgsl`, `atmo_core`, `sky_render_funcs` (skyAtmo) : prend une couleur de surface
// à `dist` mètres dans la direction `dir` et la fond dans la brume du ciel.
//   T      = exp(-extinction * dist)        (extinction : atmosphère + plancher de brume du jeu)
//   résultat = surface * T + skyAtmo(horizon dans l'azimut de dir) * (1 - T)
fn aerialTransmittance(dist: f32) -> vec3f {
  return exp(-max(F.fogExt.rgb, vec3f(F.fogExt.w)) * dist);
}

fn applyAerial(surface: vec3f, dir: vec3f, dist: f32) -> vec3f {
  let T = aerialTransmittance(dist);
  let horizon = skyAtmo(normalize(vec3f(dir.x, 0.0005, dir.z)));
  return surface * T + horizon * (vec3f(1.0) - T);
}
