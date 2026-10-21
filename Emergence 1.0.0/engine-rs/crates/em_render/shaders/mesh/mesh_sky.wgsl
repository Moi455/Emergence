// Aides de lumière du maillage (L33) : ambiance du ciel sur l'hémisphère d'une face, occlusion avec rebonds, sRGB.
// Copie des fonctions de `voxel_light.wgsl` (l'éclairage différé de L09) : le rendu par maillage les partage avec lui
// par le texte, car l'autre fichier est un shader complet. Assemblé après : ciel (Frame, atmo_core, sky_render_funcs).

const PI_M: f32 = 3.14159265;
const LUMA: vec3<f32> = vec3<f32>(0.2126, 0.7152, 0.0722);

// Moyenne de la radiance du ciel (LUT de Hillaire) sur l'hémisphère cosinus de la normale `n`, 8 directions du disque
// de Vogel ; les directions sous l'horizon reçoivent `sol` (rebond provisoire du sol).
fn sky_hemisphere(n: vec3<f32>, sol: vec3<f32>) -> vec3<f32> {
  let t = normalize(cross(n, select(vec3<f32>(0.0, 1.0, 0.0), vec3<f32>(1.0, 0.0, 0.0), abs(n.y) > 0.9)));
  let b = cross(n, t);
  var somme = vec3<f32>(0.0);
  for (var k = 0u; k < 8u; k++) {
    let r = sqrt((f32(k) + 0.5) / 8.0);
    let a = f32(k) * 2.399963;
    let d = t * (r * cos(a)) + b * (r * sin(a)) + n * sqrt(max(1.0 - r * r, 0.0));
    if (d.y < 0.03) {
      somme += sol;
    } else {
      somme += skyAtmo(normalize(d));
    }
  }
  return somme / 8.0;
}

fn srgb_to_linear(c: vec3<f32>) -> vec3<f32> {
  let lo = c / 12.92;
  let hi = pow((c + vec3<f32>(0.055)) / 1.055, vec3<f32>(2.4));
  return select(hi, lo, c <= vec3<f32>(0.04045));
}

// Occlusion de l'ambiance AVEC REBONDS (Jimenez et al., 2016) : un creux garde la couleur de l'albédo.
fn ao_couleur(ao: f32, albedo: vec3<f32>) -> vec3<f32> {
  let a = 2.0404 * albedo - vec3<f32>(0.3324);
  let b = -4.7951 * albedo + vec3<f32>(0.6417);
  let c = 2.7552 * albedo + vec3<f32>(0.6903);
  return max(vec3<f32>(ao), ((vec3<f32>(ao) * a + b) * ao + c) * ao);
}
