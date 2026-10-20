// Éclairage différé (docs/19b L09, L11) : soleil lambertien avec ombres en cascades + ciel (LUT de Hillaire), SANS
// occlusion (L14) ni indirect (L15). Assemblé après : frame (ciel), atmo_core, sky_render_funcs, aerial,
// voxel_frame, voxel_shadow_sample. Groupe 0 = ciel (comme le fond), groupe 1 = G-buffer, groupe 2 = ombres.
@group(0) @binding(0) var<uniform> F: Frame;
@group(0) @binding(1) var transLUT: texture_2d<f32>;
@group(0) @binding(2) var skyLUT: texture_2d<f32>;
@group(0) @binding(3) var sampC: sampler;

@group(1) @binding(0) var<uniform> VF: VoxelFrame;
@group(1) @binding(1) var<uniform> LU: vec4<f32>;       // x = vue (0 image, 1 albédo, 2 normales, 3 distance, 4 masque), y = ambiance
@group(1) @binding(2) var gb0: texture_2d<f32>;
@group(1) @binding(3) var gb1: texture_2d<u32>;
@group(1) @binding(4) var gb2: texture_2d<f32>;
@group(1) @binding(5) var dist_tex: texture_2d<f32>;

struct VO { @builtin(position) pos: vec4<f32> };

@vertex fn vs(@builtin(vertex_index) i: u32) -> VO {
  let p = vec2<f32>(f32((i << 1u) & 2u), f32(i & 2u)) * 2.0 - 1.0;
  var o: VO;
  o.pos = vec4<f32>(p, 0.0, 1.0);
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

@fragment fn fs(in: VO) -> @location(0) vec4<f32> {
  let px = vec2<i32>(in.pos.xy);
  let dist = textureLoad(dist_tex, px, 0).x;
  if (dist > 1e29) { discard; }
  let view = u32(LU.x + 0.5);
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
  // Soleil : transmittance de l'atmosphère jusqu'à la caméra (approximation : même rayon pour toute la scène),
  // éteint sous l'horizon de la planète.
  let direct_plein = sunIlluminance() * planetShadow(camR(), F.sunDir.y) * ndl / PI;
  let direct = direct_plein * visibilite;

  // Ciel : radiance de la LUT dans la direction de la normale (relevée au-dessus de l'horizon), plus le rebond
  // du sol, mélangés selon l'orientation de la face. Aucune occlusion : une face sous le houppier reçoit
  // autant de ciel que le dessus d'un rocher (manque assumé, L14).
  let n_haut = normalize(vec3<f32>(n.x, max(n.y, 0.12), n.z) + vec3<f32>(0.0, 0.0005, 0.0));
  let ciel_n = skyAtmo(n_haut);
  let ciel_haut = skyAtmo(vec3<f32>(0.0, 1.0, 0.0));
  let rebond = 0.18 * (direct_plein * 0.35 + ciel_haut * 0.6);
  let w_haut = clamp(0.5 + 0.5 * n.y, 0.0, 1.0);
  let ambiant = mix(rebond, ciel_n * 0.85, w_haut) * LU.y;

  let surface = albedo * (direct + ambiant);
  let lointain = applyAerial(surface, dir, dist);

  // Raccord provisoire du sol : la clipmap n'a qu'un niveau (25 m autour de la caméra, L26 ajoute les autres). Au
  // bord, le plan du sol (face tournée vers le haut à y = 0) se fond dans le sol du ciel déjà écrit dans la cible
  // HDR (mélange par la transparence de sortie), sinon on verrait une bande de couleur à la limite de la grille.
  let y_surface = F.camPos.y + dir.y * dist;
  let sol = abs(y_surface) < 0.02 && n.y > 0.9;
  let fondu = select(0.0, smoothstep(14.0, 25.0, dist), sol);
  return vec4<f32>(lointain, 1.0 - fondu);
}
