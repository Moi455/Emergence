// Pente (tan de l'élévation) d'une crête dans l'azimut `az` (vecteur unitaire du plan horizontal : périodique).
// Requiert `gnoise` (noise.wgsl de web-ocean). Évaluée une seule fois par texel de la LUT (crete_lut.wgsl).
fn ridgeSlope(az: vec2f, layer: f32) -> f32 {
  var p = az * (1.6 + 0.9 * layer) + vec2f(layer * 17.3, layer * 5.1);
  var h = 0.0;
  var a = 0.5;
  for (var i = 0; i < 5; i++) {
    h += a * gnoise(p);
    p = p * 2.07 + vec2f(3.7, 1.9);
    a *= 0.5;
  }
  let amp = 1.0 - 0.28 * layer;
  return (0.018 + 0.17 * clamp(h * 1.6 + 0.40, 0.0, 1.0)) * amp;
}
