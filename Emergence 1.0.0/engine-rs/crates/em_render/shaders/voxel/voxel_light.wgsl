// Éclairage différé (docs/19b L09, L10, L11) : soleil lambertien (couleur = transmittance de l'atmosphère de Hillaire)
// avec ombres en cascades, ambiance = intégrale cosinus du ciel sur l'hémisphère de la face, translucidité et liseré
// du feuillage ; SANS occlusion (L14) ni indirect (L15). Assemblé après : frame (ciel), atmo_core, sky_render_funcs,
// aerial, voxel_frame, voxel_shadow_sample. Groupe 0 = ciel (comme le fond), groupe 1 = G-buffer, groupe 2 = ombres.
@group(0) @binding(0) var<uniform> F: Frame;
@group(0) @binding(1) var transLUT: texture_2d<f32>;
@group(0) @binding(2) var skyLUT: texture_2d<f32>;
@group(0) @binding(3) var sampC: sampler;

@group(1) @binding(0) var<uniform> VF: VoxelFrame;
// Miroir de `voxel::gpu::LightUniform`.
struct LightU {
  vue: vec4<f32>,   // x = vue (0 image, 1 albédo, 2 normales, 3 distance, 4 masque...), y = ambiance, z = épaisseur dispo, w = zone (m)
  fa: vec4<f32>,    // x = force de la translucidité, y = longueur d'absorption (m), z = lobe avant, w = force du liseré
  fb: vec4<f32>,    // rgb = teinte de transmission, w = épaisseur du liseré (m)
  fc: vec4<f32>,    // x = saturation du feuillage, y = soulèvement des ombres, z = occlusion ambiante disponible
  fd: vec4<f32>,    // rgb = teinte du soulèvement des ombres
};
@group(1) @binding(1) var<uniform> LU: LightU;
@group(1) @binding(2) var gb0: texture_2d<f32>;
@group(1) @binding(3) var gb1: texture_2d<u32>;
@group(1) @binding(4) var gb2: texture_2d<f32>;
@group(1) @binding(5) var dist_tex: texture_2d<f32>;
@group(1) @binding(6) var thick_tex: texture_2d<f32>;   // épaisseur de feuillage le long du soleil (m), 1000 = barré
@group(1) @binding(7) var ao_tex: texture_2d<f32>;      // visibilité de l'ambiance (L14) : 1 libre, 0 enfermé

const LUMA: vec3<f32> = vec3<f32>(0.2126, 0.7152, 0.0722);
const BLOQUE_M: f32 = 1000.0;

// Ambiance du ciel : moyenne de la radiance du ciel (LUT de Hillaire) sur l'hémisphère cosinus de la face, 8 directions
// du disque de Vogel autour de la normale. Les directions sous l'horizon reçoivent `sol` (rebond provisoire du sol, L15
// fera mieux). Aucune constante : bleu-gris le jour, rose-violet au crépuscule, orange du côté du soleil couchant.
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

// Sortie du sommet : l'ambiance du ciel pour chacune des six faces d'un voxel (+x, -x, +y, -y, +z, -z), calculée UNE
// fois par sommet (3 sommets) au lieu d'une fois par pixel : les normales des voxels sont alignées sur les axes.
struct VO {
  @builtin(position) pos: vec4<f32>,
  @location(0) @interpolate(flat) a0: vec3<f32>,
  @location(1) @interpolate(flat) a1: vec3<f32>,
  @location(2) @interpolate(flat) a2: vec3<f32>,
  @location(3) @interpolate(flat) a3: vec3<f32>,
  @location(4) @interpolate(flat) a4: vec3<f32>,
  @location(5) @interpolate(flat) a5: vec3<f32>,
};

@vertex fn vs(@builtin(vertex_index) i: u32) -> VO {
  let p = vec2<f32>(f32((i << 1u) & 2u), f32(i & 2u)) * 2.0 - 1.0;
  var o: VO;
  o.pos = vec4<f32>(p, 0.0, 1.0);
  let e_sun = sunIlluminance() * planetShadow(camR(), F.sunDir.y);
  let ciel_haut = skyAtmo(vec3<f32>(0.0, 1.0, 0.0));
  // Rebond provisoire du sol (sous l'horizon) : L15 le remplacera par des sondes.
  let rebond = 0.18 * (e_sun * (max(F.sunDir.y, 0.0) * 0.35 / PI) + ciel_haut * 0.6);
  let k = LU.vue.y;
  o.a0 = sky_hemisphere(vec3<f32>(1.0, 0.0, 0.0), rebond) * k;
  o.a1 = sky_hemisphere(vec3<f32>(-1.0, 0.0, 0.0), rebond) * k;
  o.a2 = sky_hemisphere(vec3<f32>(0.0, 1.0, 0.0), rebond) * k;
  o.a3 = sky_hemisphere(vec3<f32>(0.0, -1.0, 0.0), rebond) * k;
  o.a4 = sky_hemisphere(vec3<f32>(0.0, 0.0, 1.0), rebond) * k;
  o.a5 = sky_hemisphere(vec3<f32>(0.0, 0.0, -1.0), rebond) * k;
  return o;
}

fn srgb_to_linear(c: vec3<f32>) -> vec3<f32> {
  let lo = c / 12.92;
  let hi = pow((c + vec3<f32>(0.055)) / 1.055, vec3<f32>(2.4));
  return select(hi, lo, c <= vec3<f32>(0.04045));
}

fn oct_decode(packed: u32) -> vec3<f32> {
  let e = unpack2x16unorm(packed) * 2.0 - vec2<f32>(1.0);
  var n = vec3<f32>(e.x, e.y, 1.0 - abs(e.x) - abs(e.y));
  if (n.z < 0.0) {
    let t = (vec2<f32>(1.0) - abs(e.yx)) * select(vec2<f32>(-1.0), vec2<f32>(1.0), e >= vec2<f32>(0.0));
    n = vec3<f32>(t.x, t.y, n.z);
  }
  return normalize(n);
}

// Occlusion de l'ambiance AVEC REBONDS (approximation de Jimenez et al., « Practical Real-Time Strategies for Accurate
// Indirect Occlusion », 2016) : la lumière qui rebondit dans un creux prend la couleur de l'albédo, donc un creux de
// feuillage reste vert profond (pas gris, pas noir) et un joint de pierre reste chaud. Égale `ao` pour un albédo moyen
// de 0,5 environ, plus clair (plus de rebond) pour les albédos clairs.
fn ao_couleur(ao: f32, albedo: vec3<f32>) -> vec3<f32> {
  let a = 2.0404 * albedo - vec3<f32>(0.3324);
  let b = -4.7951 * albedo + vec3<f32>(0.6417);
  let c = 2.7552 * albedo + vec3<f32>(0.6903);
  return max(vec3<f32>(ao), ((vec3<f32>(ao) * a + b) * ao + c) * ao);
}

// Visibilité du soleil EN UNE PRISE (sans pénombre) pour un point au-delà de la zone de feuillage : l'occulteur est loin,
// sa pénombre ne se verrait pas. Marge de profondeur d'un texel (la zone comptée a une marge de 2,4 voxels).
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

@fragment fn fs(in: VO) -> @location(0) vec4<f32> {
  let px = vec2<i32>(in.pos.xy);
  let dist = textureLoad(dist_tex, px, 0).x;
  if (dist > 1e29) { discard; }
  let view = u32(LU.vue.x + 0.5);
  if (view == 4u) { return vec4<f32>(64.0, 64.0, 64.0, 1.0); }   // blanc après AgX (sans bloom : --bloom 0)
  let g0 = textureLoad(gb0, px, 0);
  let n = oct_decode(textureLoad(gb1, px, 0).x);
  let albedo = srgb_to_linear(g0.rgb);
  if (view == 1u) { return vec4<f32>(albedo, 1.0); }
  if (view == 2u) { return vec4<f32>(n * 0.5 + vec3<f32>(0.5), 1.0); }
  if (view == 3u) { let g = clamp(dist / 40.0, 0.0, 1.0); return vec4<f32>(g, g, g, 1.0); }

  let ndc = pixel_ndc(vec2<u32>(px), VF);
  let dir = pixel_dir(ndc, VF);
  let sun = normalize(F.sunDir.xyz);
  let ndl = max(dot(n, sun), 0.0);
  // Point éclairé en mètres relatifs à la caméra (en orthographique, l'origine du rayon dépend du pixel).
  let p_rel = (pixel_origin(ndc, VF) - VF.cam_frac.xyz) * VOXEL_M + dir * dist;
  var visibilite = 1.0;
  if (ndl > 0.0) { visibilite = shadow_visibility(p_rel, n); }
  // Vue « ombre » : visibilité en gris ; pourpre (0,25 ; 0 ; 0,25) sur les faces tournées à l'opposé du soleil.
  if (view == 5u) {
    if (ndl <= 0.0) { return vec4<f32>(0.25, 0.0, 0.25, 1.0); }
    return vec4<f32>(visibilite, visibilite, visibilite, 1.0);
  }
  if (view == 6u) {
    var teinte = vec3<f32>(0.45);
    let c = sh_pick(p_rel, length(p_rel));
    if (c == 0u) { teinte = vec3<f32>(1.0, 0.25, 0.25); }
    if (c == 1u) { teinte = vec3<f32>(0.25, 1.0, 0.25); }
    if (c == 2u) { teinte = vec3<f32>(0.3, 0.4, 1.0); }
    if (c == 3u) { teinte = vec3<f32>(1.0, 1.0, 0.25); }
    return vec4<f32>(teinte * (0.35 + 0.65 * visibilite), 1.0);
  }
  // Soleil : transmittance de l'atmosphère (LUT de Hillaire) jusqu'à la caméra (approximation : même rayon pour toute
  // la scène), éteint sous l'horizon de la planète : blanc-jaune à midi, orange doré à 18 h 30, rouge au coucher.
  let e_sun = sunIlluminance() * planetShadow(camR(), F.sunDir.y);
  let direct = e_sun * (ndl * visibilite / PI);

  // Ciel : intégrale cosinus de la radiance de la LUT sur l'hémisphère de la face (précalculée par sommet), plus le
  // rebond du sol (sous l'horizon). Aucune occlusion : une face sous le houppier reçoit autant de ciel que le dessus d'un rocher (manque
  // assumé, L14).
  let an = abs(n);
  var ambiant = in.a0;
  if (an.x >= an.y && an.x >= an.z) {
    ambiant = select(in.a1, in.a0, n.x > 0.0);
  } else if (an.y >= an.z) {
    ambiant = select(in.a3, in.a2, n.y > 0.0);
  } else {
    ambiant = select(in.a5, in.a4, n.z > 0.0);
  }
  // Ombres colorées : un peu de bleu-violet proportionnel au soleil, jamais de noir pur le jour.
  let soulevement = LU.fd.rgb * (dot(e_sun, LUMA) * LU.fc.y);

  // Feuillage : saturation de l'albédo, translucidité du soleil et liseré de contre-jour.
  let g2 = textureLoad(gb2, px, 0);
  let foliage = (u32(g2.a * 255.0 + 0.5) & 1u) != 0u;
  var alb = albedo;
  var extra = vec3<f32>(0.0);
  if (foliage) {
    let l = dot(albedo, LUMA);
    alb = max(vec3<f32>(l) + LU.fc.x * (albedo - vec3<f32>(l)), vec3<f32>(0.0));
    if (LU.vue.z > 0.5) {
      let cos_ns = dot(n, sun);
      let cos_vs = clamp(dot(dir, sun), 0.0, 1.0);
      let epais = textureLoad(thick_tex, px, 0).x;
      let barre = epais > BLOQUE_M * 0.5;
      // Soleil derrière la feuille (face tournée vers l'observateur, à l'opposé du soleil).
      let derriere = smoothstep(0.35, -0.35, cos_ns);
      if (derriere > 0.0 && !barre) {
        // Ombre de L11 au-delà de la zone comptée : le point de départ est décalé du bord de la zone (et de 2,4
        // voxels de marge), la normale est celle du soleil : seul un occulteur au-delà de la zone éteint la lumière.
        var vis_t = 1.0;
        if (LU.vue.w > 0.0) { vis_t = sun_visible_hard(p_rel + sun * (LU.vue.w + 0.12)); }
        let att = exp(-epais / LU.fa.y);
        let lobe = (1.0 - LU.fa.z) + LU.fa.z * cos_vs * cos_vs;
        let tcol = sqrt(max(alb, vec3<f32>(0.0))) * LU.fb.rgb;
        let k = g2.g * LU.fa.x * derriere * att * vis_t * lobe / PI;
        let mince = 1.0 - smoothstep(0.04, LU.fb.w, epais);
        let c2 = cos_vs * cos_vs;
        let rim = LU.fa.w * (c2 * c2) * derriere * mince * vis_t / PI;
        let dore = vec3<f32>(1.0, 0.8, 0.35);
        extra = e_sun * (k * tcol + rim * (tcol * 0.5 + dore * 0.5));
      }
    }
  }

  // Occlusion ambiante (L14) : assombrit l'ambiance du ciel et le soulèvement bleu-violet (l'indirect), jamais le soleil
  // direct (qui a ses ombres de L11). Aucune obscurité grise : le creux garde la couleur de l'albédo.
  var ao = 1.0;
  if (LU.fc.z > 0.5) { ao = textureLoad(ao_tex, px, 0).x; }
  if (view == 7u) { return vec4<f32>(ao, ao, ao, 1.0); }
  let surface = alb * (direct + ambiant * ao_couleur(ao, alb) + soulevement * ao) + extra;
  let lointain = applyAerial(surface, dir, dist);

  // Raccord provisoire du sol : la clipmap n'a qu'un niveau (25 m autour de la caméra, L26 ajoute les autres). Au
  // bord, le plan du sol (face tournée vers le haut à y = 0) se fond dans le sol du ciel déjà écrit dans la cible
  // HDR (mélange par la transparence de sortie), sinon on verrait une bande de couleur à la limite de la grille.
  let y_surface = F.camPos.y + dir.y * dist;
  let sol = abs(y_surface) < 0.02 && n.y > 0.9;
  let fondu = select(0.0, smoothstep(14.0, 25.0, dist), sol);
  return vec4<f32>(lointain, 1.0 - fondu);
}
