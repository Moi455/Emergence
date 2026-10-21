// Éclairage du rendu par maillage (L33) : un seul passage raster, la lumière est calculée dans le fragment.
// Assemblé après : ciel (Frame, atmo_core, sky_render_funcs), aerial, mesh_quad, mesh_sky, voxel_shadow_sample (version
// raster). Groupe 0 = ciel, 1 = image du maillage, 2 = ombres, 3 = chunks.
//
// - soleil : transmittance de l'atmosphère (texel 6 de la texture d'ambiance), lambertien, ombre en cascades ;
// - ambiance : intégrale cosinus du ciel sur l'hémisphère de la face (texels 0 à 5), multipliée par l'occlusion
//   BAKÉE du sommet (jamais le soleil) avec rebonds ;
// - paramètres de matière (octet du sommet) : réflexion = brillance spéculaire douce du soleil ;
// - feuillage : saturation, translucidité par l'épaisseur BAKÉE de la face, liseré doré en contre-jour ;
// - perspective aérienne, comme l'éclairage différé.
@group(0) @binding(0) var<uniform> F: Frame;
@group(0) @binding(1) var transLUT: texture_2d<f32>;
@group(0) @binding(2) var skyLUT: texture_2d<f32>;
@group(0) @binding(3) var sampC: sampler;

struct MeshFrame {
  view_proj: mat4x4<f32>,
  screen: vec4<f32>,
};
@group(1) @binding(0) var<uniform> MF: MeshFrame;
// Miroir de `voxel::gpu::LightUniform` (même disposition que l'éclairage différé).
struct LightU {
  vue: vec4<f32>,   // x = vue, y = ambiance, z = épaisseur de feuillage cuite, w = zone (m)
  fa: vec4<f32>,    // x = force de la translucidité, y = longueur d'absorption (m), z = lobe avant, w = force du liseré
  fb: vec4<f32>,    // rgb = teinte de transmission, w = épaisseur du liseré (m)
  fc: vec4<f32>,    // x = saturation du feuillage, y = soulèvement des ombres, w = 1 : occlusion baked éteinte
  fd: vec4<f32>,    // rgb = teinte du soulèvement des ombres
};
@group(1) @binding(1) var<uniform> LU: LightU;
@group(1) @binding(2) var amb_tex: texture_2d<f32>;
// Style de L34 : relief froissé, tables de l'occlusion, chaleur. Miroir de `MeshStyle::uniform`.
struct StyleU {
  relief: vec4<f32>,  // x = force (0 éteint), y = distance de pleine force (m), z = distance nulle (m)
  ao: vec4<f32>,      // facteur d'ambiance par niveau d'occlusion 0..3 (3 = dégagé)
  creux: vec4<f32>,   // facteur d'ambiance par profondeur de creux 0..3 (0 = dégagé)
  divers: vec4<f32>,  // x = facteur des faces intérieures, y = chaleur de l'ambiance
};
@group(1) @binding(3) var<uniform> ST: StyleU;

const BLOQUE_Q: u32 = 255u;      // code « soleil barré » de l'épaisseur cuite
const QUART_M: f32 = 0.0125;     // un cran d'épaisseur cuite : un quart de voxel, en mètres

var<private> FACE_N: array<vec3<f32>, 6> = array<vec3<f32>, 6>(
  vec3<f32>(1.0, 0.0, 0.0), vec3<f32>(-1.0, 0.0, 0.0),
  vec3<f32>(0.0, 1.0, 0.0), vec3<f32>(0.0, -1.0, 0.0),
  vec3<f32>(0.0, 0.0, 1.0), vec3<f32>(0.0, 0.0, -1.0));

struct VO {
  @builtin(position) pos: vec4<f32>,
  @location(0) @interpolate(flat) w0: u32,
  @location(1) @interpolate(flat) w1: u32,
  @location(2) @interpolate(flat) foliage: u32,
  @location(3) p_rel: vec3<f32>,
  @location(4) ao: f32,
  @location(5) local: vec3<f32>,
  @location(6) @interpolate(flat) vox: vec3<i32>,
};

@vertex fn vs(@builtin(vertex_index) vi: u32, @builtin(instance_index) qi: u32) -> VO {
  let q = quad_vertex(qi, vi);
  let p_rel = CU.origin.xyz + q.local * CU.origin.w;
  var o: VO;
  o.pos = MF.view_proj * vec4<f32>(p_rel, 1.0);
  o.w0 = q.w0;
  o.w1 = q.w1;
  o.foliage = q.foliage;
  o.p_rel = p_rel;
  o.ao = ST.ao[q.ao_l] * ST.creux[q.cx_l];
  o.local = q.local;
  o.vox = CU.vox.xyz;
  return o;
}

// Visibilité du soleil EN UNE PRISE (sans pénombre) pour un point au-delà de la zone de feuillage (voir L10).
fn sun_visible_hard(p: vec3<f32>) -> f32 {
  if (SU.cfg0.y < 0.5) { return 1.0; }
  let c = sh_pick(p, length(p));
  if (c == 99u) { return 1.0; }
  let cs = SU.cas[c];
  let ts = cs.origin.w;
  let rel = p - cs.origin.xyz;
  let f = vec2<f32>(dot(rel, cs.right.xyz), dot(rel, cs.up.xyz)) / ts + vec2<f32>(0.5);
  let d = dot(cs.origin.xyz - p, cs.sun.xyz) - (SU.cfg1.y + ts);
  let s = sh_load(i32(cs.right.w + 0.5), i32(cs.up.w + 0.5), vec2<i32>(floor(f)));
  return select(0.0, 1.0, d <= s);
}

// ---- Relief froissé (L34) : port de `patchStd` de maison-voxel.html -----------------------------------------------
// Bruit de valeur 3D ancré au MONDE : la position est l'origine entière du chunk + la position locale, jamais l'écran ni la
// caméra. Les fréquences sont des rationnels a/10 par voxel : l'origine du chunk s'écrit 10 k + r, d'où r (petit, exact en
// flottant) et un décalage entier k a dans le réseau : aucune perte de précision, aucun scintillement.
fn bruit_hash(c: vec3<i32>) -> f32 {
  var h = bitcast<u32>(c.x) * 374761393u + bitcast<u32>(c.y) * 668265263u + bitcast<u32>(c.z) * 1274126177u;
  h = (h ^ (h >> 13u)) * 1274126177u;
  h = h ^ (h >> 16u);
  return f32(h & 0xFFFFu) / 65536.0;
}

fn bruit_monde(l: vec3<f32>, o: vec3<i32>, a: i32, decalage: i32) -> f32 {
  let r = ((o % vec3<i32>(10)) + vec3<i32>(10)) % vec3<i32>(10);
  let k = (o - r) / vec3<i32>(10);
  let base = (l + vec3<f32>(r)) * (f32(a) * 0.1);
  let cell = floor(base);
  var f = base - cell;
  f = f * f * (vec3<f32>(3.0) - 2.0 * f);
  let c = vec3<i32>(cell) + k * a + vec3<i32>(decalage);
  let x00 = mix(bruit_hash(c), bruit_hash(c + vec3<i32>(1, 0, 0)), f.x);
  let x10 = mix(bruit_hash(c + vec3<i32>(0, 1, 0)), bruit_hash(c + vec3<i32>(1, 1, 0)), f.x);
  let x01 = mix(bruit_hash(c + vec3<i32>(0, 0, 1)), bruit_hash(c + vec3<i32>(1, 0, 1)), f.x);
  let x11 = mix(bruit_hash(c + vec3<i32>(0, 1, 1)), bruit_hash(c + vec3<i32>(1, 1, 1)), f.x);
  return mix(mix(x00, x10, f.y), mix(x01, x11, f.y), f.z);
}

// Hauteur de relief en mètres : luminance de l'albédo, deux octaves de bruit, biseau léger d'arête de voxel.
fn hauteur_relief(local: vec3<f32>, vox: vec3<i32>, n: vec3<f32>, albedo: vec3<f32>) -> f32 {
  let pp = local - n * 0.03;
  let n2 = bruit_monde(pp, vox, 31, 7);
  let n3 = bruit_monde(pp, vox, 63, 3);
  let ed = vec3<f32>(0.5) - abs(fract(pp) - vec3<f32>(0.5)) + abs(n) * 9.0;
  let e = min(ed.x, min(ed.y, ed.z));
  let bev = smoothstep(0.0, 0.14 + 0.1 * n2, e);
  let lum = dot(albedo, vec3<f32>(0.3, 0.55, 0.15));
  return (lum * 0.4 + (n2 - 0.5) * 0.14 + (n3 - 0.5) * 0.05 + (bev - 1.0) * 0.04) * 0.05;
}

@fragment fn fs(in: VO) -> @location(0) vec4<f32> {
  let face = (in.w0 >> 21u) & 7u;
  let n = FACE_N[face];
  let view = u32(LU.vue.x + 0.5);
  if (view == 4u) { return vec4<f32>(64.0, 64.0, 64.0, 1.0); }   // blanc après AgX (sans bloom : --bloom 0)
  let c8 = vec3<f32>(f32(in.w1 & 255u), f32((in.w1 >> 8u) & 255u), f32((in.w1 >> 16u) & 255u)) / 255.0;
  let albedo = srgb_to_linear(c8);
  if (view == 1u) { return vec4<f32>(albedo, 1.0); }
  if (view == 2u) { return vec4<f32>(n * 0.5 + vec3<f32>(0.5), 1.0); }
  let dist = length(in.p_rel);
  if (view == 3u) { let g = clamp(dist / 40.0, 0.0, 1.0); return vec4<f32>(g, g, g, 1.0); }
  let dir = in.p_rel / dist;
  let sun = normalize(F.sunDir.xyz);
  // Relief : normale perturbée par les dérivées d'écran de la hauteur, pente limitée, fondu avec la distance. Les dérivées
  // se calculent hors de toute branche. Amplitude = relief de la classe (bits 27 à 29 du mot 1) x force.
  let amp = f32((in.w1 >> 27u) & 7u) / 7.0;
  let fondu_relief = 1.0 - smoothstep(ST.relief.y, ST.relief.z, dist);
  let hr = hauteur_relief(in.local, in.vox, n, albedo) * (amp * ST.relief.x * fondu_relief);
  let sx = dpdx(in.p_rel);
  let sy = dpdy(in.p_rel);
  let lx = length(sx);
  let ly = length(sy);
  let hx = clamp(dpdx(hr), -1.4 * lx, 1.4 * lx);
  let hy = clamp(dpdy(hr), -1.4 * ly, 1.4 * ly);
  let r1 = cross(sy, n);
  let r2 = cross(n, sx);
  let det = dot(sx, r1);
  var nn = n;
  if (abs(det) > 1e-12) {
    nn = normalize(abs(det) * n - sign(det) * (hx * r1 + hy * r2));
  }
  let ndl_g = max(dot(n, sun), 0.0);
  let ndl = select(0.0, max(dot(nn, sun), 0.0), ndl_g > 0.0);
  let interieur = ((in.w1 >> 30u) & 1u) != 0u;
  let emissif = ((in.w1 >> 31u) & 1u) != 0u;
  var visibilite = 1.0;
  if (ndl_g > 0.0) { visibilite = shadow_visibility(in.p_rel, n); }
  if (view == 5u) {
    if (ndl_g <= 0.0) { return vec4<f32>(0.25, 0.0, 0.25, 1.0); }
    return vec4<f32>(visibilite, visibilite, visibilite, 1.0);
  }
  if (view == 6u) {
    var teinte = vec3<f32>(0.45);
    let c = sh_pick(in.p_rel, dist);
    if (c == 0u) { teinte = vec3<f32>(1.0, 0.25, 0.25); }
    if (c == 1u) { teinte = vec3<f32>(0.25, 1.0, 0.25); }
    if (c == 2u) { teinte = vec3<f32>(0.3, 0.4, 1.0); }
    if (c == 3u) { teinte = vec3<f32>(1.0, 1.0, 0.25); }
    return vec4<f32>(teinte * (0.35 + 0.65 * visibilite), 1.0);
  }
  if (view == 7u) { return vec4<f32>(in.ao, in.ao, in.ao, 1.0); }

  let e_sun = textureLoad(amb_tex, vec2<i32>(6, 0), 0).rgb;
  let direct = e_sun * (ndl * visibilite / PI_M);
  // Ambiance : cube de six directions pondéré par le carré de la normale PERTURBÉE (une face plane retrouve son texel) :
  // le relief modèle aussi la lumière du ciel, pas seulement le soleil.
  let wn = nn * nn;
  let ix = select(1, 0, nn.x >= 0.0);
  let iy = select(3, 2, nn.y >= 0.0);
  let iz = select(5, 4, nn.z >= 0.0);
  var ciel = (wn.x * textureLoad(amb_tex, vec2<i32>(ix, 0), 0).rgb
    + wn.y * textureLoad(amb_tex, vec2<i32>(iy, 0), 0).rgb
    + wn.z * textureLoad(amb_tex, vec2<i32>(iz, 0), 0).rgb) * LU.vue.y;
  // Chaleur de l'ambiance : tire l'ambiance froide du ciel vers le beige (même luminance), pour que la pierre à l'ombre
  // reste de la couleur voulue par le générateur.
  let tiede = vec3<f32>(1.7, 1.0, 0.5);
  ciel = mix(ciel, ciel * tiede / dot(tiede, LUMA), ST.divers.y);
  if (interieur) { ciel = ciel * ST.divers.x; }
  // Ombres colorées : un peu de bleu-violet proportionnel au soleil, jamais de noir pur le jour.
  let soulevement = LU.fd.rgb * (dot(e_sun, LUMA) * LU.fc.y);

  var alb = albedo;
  var extra = vec3<f32>(0.0);
  if (in.foliage != 0u) {
    let l = dot(albedo, LUMA);
    alb = max(vec3<f32>(l) + LU.fc.x * (albedo - vec3<f32>(l)), vec3<f32>(0.0));
    let cuit = (in.w0 >> 24u) & 255u;
    if (LU.vue.z > 0.5) {
      let cos_ns = dot(n, sun);
      let cos_vs = clamp(dot(dir, sun), 0.0, 1.0);
      let barre = cuit == BLOQUE_Q;
      // Soleil derrière la feuille (face tournée vers l'observateur, à l'opposé du soleil).
      let derriere = smoothstep(0.35, -0.35, cos_ns);
      if (derriere > 0.0 && !barre) {
        let epais = f32(cuit) * QUART_M;
        var vis_t = 1.0;
        if (LU.vue.w > 0.0) { vis_t = sun_visible_hard(in.p_rel + sun * (LU.vue.w + 0.12)); }
        let att = exp(-epais / LU.fa.y);
        let lobe = (1.0 - LU.fa.z) + LU.fa.z * cos_vs * cos_vs;
        let tcol = sqrt(max(alb, vec3<f32>(0.0))) * LU.fb.rgb;
        let k = LU.fa.x * 0.45 * derriere * att * vis_t * lobe / PI_M;
        let mince = 1.0 - smoothstep(0.04, LU.fb.w, epais);
        let c2 = cos_vs * cos_vs;
        let rim = LU.fa.w * (c2 * c2) * derriere * mince * vis_t / PI_M;
        let dore = vec3<f32>(1.0, 0.8, 0.35);
        extra = e_sun * (k * tcol + rim * (tcol * 0.5 + dore * 0.5));
      }
    }
  }

  // Spéculaire doux du soleil : la réflexion (3 bits de l'octet de paramètres) donne la brillance ; nulle pour le bois sec.
  let refl = f32((in.w1 >> 24u) & 7u) / 7.0;
  var spec = vec3<f32>(0.0);
  if (refl > 0.0 && ndl > 0.0) {
    let h = normalize(sun - dir);
    let brillance = 12.0 + 140.0 * refl;
    let lobe = pow(max(dot(nn, h), 0.0), brillance) * (brillance + 8.0) / (8.0 * PI_M);
    let f0 = 0.02 + 0.30 * refl * refl;
    spec = e_sun * (visibilite * ndl * lobe * f0) * mix(vec3<f32>(1.0), alb, 0.25 * refl);
  }

  let ao = select(in.ao, 1.0, LU.fc.w > 0.5);
  var surface = alb * (direct + ciel * ao_couleur(ao, alb) + soulevement * ao) + extra + spec;
  // Émissif (lampes, braises, fenêtres allumées) : HDR x3,2 comme la référence, le bloom fait le halo.
  if (emissif) { surface = albedo * 3.2; }
  let lointain = applyAerial(surface, dir, dist);

  // Raccord du sol : au bord de la région maillée (25 m), le plan du sol se fond dans le sol du ciel déjà écrit.
  let y_surface = F.camPos.y + in.p_rel.y;
  let sol = abs(y_surface) < 0.02 && n.y > 0.9;
  let fondu = select(0.0, smoothstep(14.0, 25.0, dist), sol);
  return vec4<f32>(lointain, 1.0 - fondu);
}
