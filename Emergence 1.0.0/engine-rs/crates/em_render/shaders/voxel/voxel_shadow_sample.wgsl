// Échantillonnage des ombres du soleil (docs/19 § 5.3). Assemblé AVANT voxel_light.wgsl. Groupe 2 : uniforme des
// cascades et tableau de profondeurs (R32Float, une distance par texel, lue par `textureLoad` : pas de flou qui
// lisse les voxels, le filtrage est fait ici à la main).
//
// Principe : le point éclairé est décalé selon sa normale (de quelques fractions de texel, proportionnellement au
// sinus de l'angle normale/soleil), converti en coordonnées de texel de la cascade, et sa profondeur le long du
// soleil est comparée à celle du premier voxel plein vu par le texel. La pénombre vient d'une recherche
// d'occulteur (9 prises) puis d'un filtre de 16 prises sur le disque de Vogel, SANS rotation par pixel : pas de
// bruit, et un rayon plafonné (quelques centimètres) pour que les voxels des feuilles restent nets.

struct ShadowCascadeU {
  origin: vec4<f32>,   // xyz : centre du texel (0, 0) sur le plan, repère caméra (m) ; w : texel (m)
  right:  vec4<f32>,   // xyz : axe u ; w : couche avant
  up:     vec4<f32>,   // xyz : axe v ; w : côté (texels)
  sun:    vec4<f32>,   // xyz : vers le soleil ; w : 1 si prête
  limits: vec4<f32>,   // x : portée pleine (m)
};
struct ShadowU {
  cfg0: vec4<f32>,     // x : nombre de cascades, y : actif, z : fraction de fondu, w : tan(demi-angle solaire)
  cfg1: vec4<f32>,     // x : décalage normal (texels), y : biais (m), z : biais de pente, w : échelle de pénombre
  cfg2: vec4<f32>,     // x : rayon maximal de pénombre (m)
  cas: array<ShadowCascadeU, 4>,
};
@group(2) @binding(0) var<uniform> SU: ShadowU;
@group(2) @binding(1) var sh_tex: texture_2d_array<f32>;

var<private> VOGEL: array<vec2<f32>, 16> = array<vec2<f32>, 16>(
  vec2<f32>(0.17678, 0.00000),
  vec2<f32>(-0.22577, 0.20683),
  vec2<f32>(0.03456, -0.39377),
  vec2<f32>(0.28457, 0.37117),
  vec2<f32>(-0.52222, -0.09237),
  vec2<f32>(0.49470, -0.31468),
  vec2<f32>(-0.16547, 0.61553),
  vec2<f32>(-0.31556, -0.60759),
  vec2<f32>(0.68464, 0.25003),
  vec2<f32>(-0.71226, 0.29401),
  vec2<f32>(0.34335, -0.73373),
  vec2<f32>(0.25373, 0.80893),
  vec2<f32>(-0.76475, -0.44319),
  vec2<f32>(0.89713, -0.19723),
  vec2<f32>(-0.54751, 0.77877),
  vec2<f32>(-0.12649, -0.97609)
);

fn sh_load(layer: i32, size: i32, ij: vec2<i32>) -> f32 {
  return textureLoad(sh_tex, clamp(ij, vec2<i32>(0), vec2<i32>(size - 1)), layer, 0).x;
}

// Visibilité (0 ou 1, lissée à 1 texel) d'une profondeur `d` au texel flottant `f` : comparaison bilinéaire.
fn sh_bilinear(layer: i32, size: i32, f: vec2<f32>, d: f32) -> f32 {
  let g = f - vec2<f32>(0.5);
  let i0 = vec2<i32>(floor(g));
  let w = g - floor(g);
  let a = select(0.0, 1.0, d <= sh_load(layer, size, i0));
  let b = select(0.0, 1.0, d <= sh_load(layer, size, i0 + vec2<i32>(1, 0)));
  let c = select(0.0, 1.0, d <= sh_load(layer, size, i0 + vec2<i32>(0, 1)));
  let e = select(0.0, 1.0, d <= sh_load(layer, size, i0 + vec2<i32>(1, 1)));
  return mix(mix(a, b, w.x), mix(c, e, w.x), w.y);
}

// Le point (repère caméra) est-il bien à l'intérieur de la fenêtre de la cascade `c`, avec une marge de `m` texels ?
fn sh_inside(c: u32, p: vec3<f32>, marge: f32) -> bool {
  let cs = SU.cas[c];
  if (cs.sun.w < 0.5) { return false; }
  let rel = p - cs.origin.xyz;
  let ts = cs.origin.w;
  let f = vec2<f32>(dot(rel, cs.right.xyz), dot(rel, cs.up.xyz)) / ts;
  let n = cs.up.w;
  return all(f >= vec2<f32>(marge)) && all(f <= vec2<f32>(n - marge));
}

// Visibilité du point `p` (repère caméra, mètres), de normale `n`, par la cascade `c`.
fn sh_cascade(c: u32, p: vec3<f32>, n: vec3<f32>) -> f32 {
  let cs = SU.cas[c];
  let ts = cs.origin.w;
  let sun = cs.sun.xyz;
  let ndl = clamp(dot(n, sun), 0.0, 1.0);
  let sin_phi = sqrt(max(1.0 - ndl * ndl, 0.0));
  let tan_phi = min(sin_phi / max(ndl, 0.05), 8.0);
  let layer = i32(cs.right.w + 0.5);
  let size = i32(cs.up.w + 0.5);

  let r_max = clamp(SU.cfg2.x / ts, 0.75, 6.0);                 // rayon maximal de filtrage, en texels
  let po = p + n * (SU.cfg1.x * ts * sin_phi);                  // décalage selon la normale
  let rel = po - cs.origin.xyz;
  let f = vec2<f32>(dot(rel, cs.right.xyz), dot(rel, cs.up.xyz)) / ts + vec2<f32>(0.5);   // texel (i, j) : [i, i+1[
  let d0 = dot(cs.origin.xyz - po, sun);                        // profondeur du récepteur depuis le plan
  let biais_pente = SU.cfg1.z * ts * tan_phi;
  let biais = SU.cfg1.y + biais_pente * max(1.0, r_max);
  let d = d0 - biais;

  // Recherche d'occulteur : le centre et 8 prises sur le cercle de rayon r_max.
  var nb = 0.0;
  var somme = 0.0;
  for (var k = 0u; k < 9u; k++) {
    var off = vec2<f32>(0.0);
    if (k > 0u) {
      let a = f32(k - 1u) * 0.785398;
      off = vec2<f32>(cos(a), sin(a)) * r_max;
    }
    let s = sh_load(layer, size, vec2<i32>(floor(f + off)));
    if (s < d) { nb += 1.0; somme += d0 - s; }
  }
  if (nb < 0.5) { return 1.0; }
  if (nb > 8.5) { return 0.0; }
  let moyenne = somme / nb;
  let r_pen = clamp(moyenne * SU.cfg0.w * SU.cfg1.w / ts, 0.0, r_max);
  if (r_pen < 0.75) {
    return sh_bilinear(layer, size, f, d);
  }
  var vis = 0.0;
  for (var k = 0u; k < 16u; k++) {
    let s = sh_load(layer, size, vec2<i32>(floor(f + VOGEL[k] * r_pen)));
    vis += select(0.0, 1.0, d <= s);
  }
  return vis / 16.0;
}

// Cascade choisie pour un point à `r` mètres de la caméra ; 99 si aucune. Dépend de la DISTANCE seule (pas de
// l'orientation de la caméra : rien ne bouge quand elle tourne) tant que le point est dans la fenêtre.
fn sh_pick(p: vec3<f32>, r: f32) -> u32 {
  let count = u32(SU.cfg0.x + 0.5);
  for (var c = 0u; c < count; c++) {
    let marge = clamp(SU.cfg2.x / SU.cas[c].origin.w, 0.75, 6.0) + 2.0;
    if (r < SU.cas[c].limits.x && sh_inside(c, p, marge)) { return c; }
  }
  return 99u;
}

// Visibilité du soleil (1 = éclairé) pour un point `p` en mètres relatifs à la caméra.
fn shadow_visibility(p: vec3<f32>, n: vec3<f32>) -> f32 {
  if (SU.cfg0.y < 0.5) { return 1.0; }
  let r = length(p);
  let c = sh_pick(p, r);
  if (c == 99u) { return 1.0; }
  var vis = sh_cascade(c, p, n);
  let count = u32(SU.cfg0.x + 0.5);
  let far = SU.cas[c].limits.x;
  let debut = far * (1.0 - SU.cfg0.z);
  if (r > debut) {
    // Fondu vers la cascade suivante (ou vers « pas d'ombre » après la dernière).
    let w = smoothstep(debut, far, r);
    var suivante = 1.0;
    if (c + 1u < count) {
      let marge = clamp(SU.cfg2.x / SU.cas[c + 1u].origin.w, 0.75, 6.0) + 2.0;
      if (sh_inside(c + 1u, p, marge)) { suivante = sh_cascade(c + 1u, p, n); } else { suivante = vis; }
    }
    vis = mix(vis, suivante, w);
  }
  return vis;
}
