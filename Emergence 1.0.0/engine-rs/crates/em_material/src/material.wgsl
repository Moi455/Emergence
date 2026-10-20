// Matières du laboratoire (em_material). Fragment WGSL sans liaison : les passes qui l'incluent déclarent
// elles-mêmes les tampons `materials`, `class_ramps`, `veg_ramps`, `veg_seeds` (docs/19a § 5.3) et, ajoutés par L09,
// `class_extra` (array<vec4<u32>> : graine de classe basse, haute, rôle de rampe ou 255, 0) et `veg_counts`
// (array<u32> : nombre de rampes par essence × 4 + rôle). L10 (feuillage) et L22 (détail bitmap) complètent ce fichier.

// Miroir exact de `em_material::gpu::MaterialGpu` (64 octets, 16 mots de 4 octets, indice = classe de matière).
struct MaterialGpu {
    albedo_linear: vec3<f32>,
    albedo_var: f32,
    hue_var: f32,
    voxel_jitter: f32,
    roughness: f32,
    roughness_var: f32,
    relief: f32,
    detail_strength: f32,
    detail_scale_m: f32,
    translucency: f32,
    emission: f32,
    detail_layer: u32,   // 0xFFFFFFFF = aucune couche de détail
    tint_mode: u32,      // 0 ramp128, 1 wood_axis, 2 stone_piece, 3 vegetation, 4 terrain
    flags: u32,          // 1 foliage, 2 moss, 4 skin, 8 flicker
}

const TINT_RAMP128: u32 = 0u;
const TINT_WOOD_AXIS: u32 = 1u;
const TINT_STONE_PIECE: u32 = 2u;
const TINT_VEGETATION: u32 = 3u;
const TINT_TERRAIN: u32 = 4u;

const FLAG_FOLIAGE: u32 = 1u;
const FLAG_MOSS: u32 = 2u;
const FLAG_SKIN: u32 = 4u;
const FLAG_FLICKER: u32 = 8u;

// Teinte 7 bits d'un voxel : valeur = classe (9 bits) << 7 | teinte.
fn voxel_class(value: u32) -> u32 { return (value >> 7u) & 511u; }
fn voxel_tint(value: u32) -> u32 { return value & 127u; }

// Décodage des teintes (19a § 5.3).
fn wood_axis(tint: u32) -> u32 { return (tint >> 5u) & 3u; }      // 0 x, 1 y, 2 z, 3 bois de bout
fn wood_variant(tint: u32) -> u32 { return tint & 31u; }
fn stone_piece(tint: u32) -> u32 { return tint; }                  // 0 = mortier
fn veg_species(tint: u32) -> u32 { return (tint >> 2u) & 31u; }
fn veg_ramp(tint: u32) -> u32 { return tint & 3u; }

// Indice dans `veg_ramps` : ((essence × 4 + rôle) × 4 + rampe) × 3 + couleur (rôles : 0 écorce, 1 feuilles, 2 fleurs, 3 fruits).
fn veg_ramp_index(species: u32, role: u32, ramp: u32, color: u32) -> u32 {
    return ((species * 4u + role) * 4u + ramp) * 3u + color;
}

// Couleur à la position t de [0, 1] dans une rampe de trois couleurs (sombre, moyen, clair).
fn ramp3(dark: vec3<f32>, mid: vec3<f32>, light: vec3<f32>, t: f32) -> vec3<f32> {
    let c = clamp(t, 0.0, 1.0);
    if (c <= 0.5) { return mix(dark, mid, c * 2.0); }
    return mix(mid, light, (c - 0.5) * 2.0);
}


// ---------------------------------------------------------------------------------------------------------------
// Évaluation de la couleur d'un voxel (L09) : PORT EXACT de `em_material::eval` (référence CPU en entiers Q16).
// Le champ est continu en coordonnées MONDE, évalué au CENTRE du voxel : aucune coordonnée locale, donc aucun
// biseau ni couture. Le hachage est celui du CPU (SplitMix64) : le shader n'a pas d'entier 64 bits, un u64 est un
// vec2<u32> (x = mot bas, y = mot haut). Les indices de réseau du bruit sont calculés EN ENTIERS (pas de
// coordonnée flottante géante à 10 km de l'origine) ; seules les interpolations finales sont en f32.
// ---------------------------------------------------------------------------------------------------------------

fn mulhi_u32(a: u32, b: u32) -> u32 {
  let a0 = a & 0xFFFFu; let a1 = a >> 16u;
  let b0 = b & 0xFFFFu; let b1 = b >> 16u;
  let p00 = a0 * b0; let p01 = a0 * b1; let p10 = a1 * b0; let p11 = a1 * b1;
  let mid = (p00 >> 16u) + (p01 & 0xFFFFu) + (p10 & 0xFFFFu);
  return p11 + (p01 >> 16u) + (p10 >> 16u) + (mid >> 16u);
}
fn mul64(a: vec2<u32>, b: vec2<u32>) -> vec2<u32> {
  return vec2<u32>(a.x * b.x, mulhi_u32(a.x, b.x) + a.x * b.y + a.y * b.x);
}
fn add64(a: vec2<u32>, b: vec2<u32>) -> vec2<u32> {
  let lo = a.x + b.x;
  return vec2<u32>(lo, a.y + b.y + select(0u, 1u, lo < a.x));
}
fn mix64(x: vec2<u32>) -> vec2<u32> {
  var v = x;
  v = v ^ vec2<u32>((v.x >> 30u) | (v.y << 2u), v.y >> 30u);
  v = mul64(v, vec2<u32>(0x1ce4e5b9u, 0xbf58476du));
  v = v ^ vec2<u32>((v.x >> 27u) | (v.y << 5u), v.y >> 27u);
  v = mul64(v, vec2<u32>(0x133111ebu, 0x94d049bbu));
  v = v ^ vec2<u32>((v.x >> 31u) | (v.y << 1u), v.y >> 31u);
  return v;
}
fn hash_combine(h: vec2<u32>, v: vec2<u32>) -> vec2<u32> {
  let m = add64(mul64(v, vec2<u32>(0x7f4a7c15u, 0x9e3779b9u)), vec2<u32>(0xd9b4e019u, 0x632be59bu));
  return mix64(h ^ m);
}
fn u64_of_i32(x: i32) -> vec2<u32> { return vec2<u32>(bitcast<u32>(x), select(0u, 0xFFFFFFFFu, x < 0)); }
fn u64_of_u32(x: u32) -> vec2<u32> { return vec2<u32>(x, 0u); }

// Centre du voxel en mètres Q16 : partie entière (mètres) et fraction sur 16 bits, par axe.
struct WorldPt { phi: vec3<i32>, plo: vec3<u32> };

fn world_point(v: vec3<i32>, lod: u32) -> WorldPt {
  let mm = ((v * 2 + vec3<i32>(1)) * 25) << vec3<u32>(lod);          // centre en millimètres
  var a = mm / 125;
  a = a - select(vec3<i32>(0), vec3<i32>(1), (mm % 125) < vec3<i32>(0));   // division vers moins l'infini
  let b = mm - a * 125;
  let p = a * 8192 + (b * 8192) / 125;                                // floor(mm × 65536 / 1000)
  var w: WorldPt;
  w.phi = p >> vec3<u32>(16u);
  w.plo = vec3<u32>(p & vec3<i32>(0xFFFF));
  return w;
}

// (indice de cellule, fraction sur 16 bits) de `p × f` en Q16, exact sans entier 64 bits.
fn axis_cell_frac(phi: i32, plo: u32, f: u32) -> vec2<i32> {
  let fi = f >> 16u;
  let fl = f & 0xFFFFu;
  let s = phi * i32(fl) + i32(plo * fi) + i32((plo * fl) >> 16u);
  return vec2<i32>(phi * i32(fi) + (s >> 16u), s & 0xFFFF);
}

fn smooth_q16(frac: i32) -> i32 {
  let t = u32(frac);
  let t2 = (t * t) >> 16u;
  let m = 196608u - 2u * t;
  return i32(t2 * (m >> 16u) + ((t2 * (m & 0xFFFFu)) >> 16u));
}

// a + ((b - a) × t) >> 16, avec le décalage arithmétique du CPU, sans dépasser 32 bits.
fn qlerp_i(a: i32, b: i32, t: i32) -> i32 {
  let d = b - a;
  if (d >= 0) { return a + i32((u32(d) * u32(t)) >> 16u); }
  return a - i32(((u32(-d) * u32(t)) + 65535u) >> 16u);
}

fn lattice(h: vec2<u32>, z: i32) -> i32 { return i32(hash_combine(h, u64_of_i32(z)).y >> 16u); }

// Bruit de valeur 3D (`em_material::ValueNoise::sample`), entier brut dans [0, 65535] ; `f` en cycles/m Q16 par axe.
fn value_noise(seed: vec2<u32>, p: WorldPt, f: vec3<u32>) -> i32 {
  let cx = axis_cell_frac(p.phi.x, p.plo.x, f.x);
  let cy = axis_cell_frac(p.phi.y, p.plo.y, f.y);
  let cz = axis_cell_frac(p.phi.z, p.plo.z, f.z);
  let sx = smooth_q16(cx.y);
  let sy = smooth_q16(cy.y);
  let sz = smooth_q16(cz.y);
  let hx0 = hash_combine(seed, u64_of_i32(cx.x));
  let hx1 = hash_combine(seed, u64_of_i32(cx.x + 1));
  let h00 = hash_combine(hx0, u64_of_i32(cy.x));
  let h01 = hash_combine(hx0, u64_of_i32(cy.x + 1));
  let h10 = hash_combine(hx1, u64_of_i32(cy.x));
  let h11 = hash_combine(hx1, u64_of_i32(cy.x + 1));
  let z0 = cz.x;
  let z1 = cz.x + 1;
  let b00 = qlerp_i(lattice(h00, z0), lattice(h10, z0), sx);   // y0, z0
  let b10 = qlerp_i(lattice(h01, z0), lattice(h11, z0), sx);   // y1, z0
  let b01 = qlerp_i(lattice(h00, z1), lattice(h10, z1), sx);   // y0, z1
  let b11 = qlerp_i(lattice(h01, z1), lattice(h11, z1), sx);   // y1, z1
  let p0 = qlerp_i(b00, b10, sy);
  let p1 = qlerp_i(b01, b11, sy);
  return qlerp_i(p0, p1, sz);
}

// Fréquences en cycles par mètre, Q16 brut (= `Q16::from_ratio` / `from_int` du CPU ; un test Rust le vérifie).
const FQ_0_2: u32 = 13107u;
const FQ_0_3: u32 = 19660u;
const FQ_0_5: u32 = 32768u;
const FQ_0_55: u32 = 36044u;
const FQ_0_7: u32 = 45875u;
const FQ_1_0: u32 = 65536u;
const FQ_1_3: u32 = 85196u;
const FQ_2_0: u32 = 131072u;
const FQ_4_0: u32 = 262144u;
const FQ_5_0: u32 = 327680u;
const FQ_6_0: u32 = 393216u;
const FQ_8_0: u32 = 524288u;
const FQ_9_0: u32 = 589824u;
const FQ_12_0: u32 = 786432u;

fn unit_of(raw: i32) -> f32 { return f32(raw) / 65536.0; }

// Albédo linéaire du voxel `voxel` (coordonnées du niveau `lod`) de valeur `value` : référence CPU
// `em_material::eval_albedo_cpu` (sans les voisins de pierre : pas de joint avant L23).
fn eval_voxel_albedo(value: u32, voxel: vec3<i32>, lod: u32) -> vec3<f32> {
  let cls = voxel_class(value);
  let tint = voxel_tint(value);
  let m = materials[cls];
  let ex = class_extra[cls];
  let cseed = vec2<u32>(ex.x, ex.y);
  let pt = world_point(voxel, lod);
  let mode = m.tint_mode;
  let role = ex.z;

  // tirage propre au voxel (gigue de grain) : seulement s'il sert
  var vu = 0.5;
  if (m.voxel_jitter > 0.0 || (mode == TINT_VEGETATION && role == 1u)) {
    var hj = hash_combine(cseed, u64_of_u32(lod));
    hj = hash_combine(hj, u64_of_i32(voxel.x));
    hj = hash_combine(hj, u64_of_i32(voxel.y));
    hj = hash_combine(hj, u64_of_i32(voxel.z));
    vu = f32(hj.y >> 16u) / 65536.0;
  }

  var t = 0.5;
  var use_species = false;
  var species = 0u;
  var ramp_idx = 0u;
  var pick = -1;            // >= 0 : tirage continu de rampe (feuilles), entier brut

  if (mode == TINT_RAMP128) {
    t = f32(tint) / 127.0;
  } else if (mode == TINT_TERRAIN) {
    let lent = unit_of(value_noise(hash_combine(cseed, u64_of_u32(0x7E44u)), pt, vec3<u32>(FQ_0_2)));
    let variante = f32(tint) / 127.0;
    t = 0.5 + (variante - 0.5) * 0.6 + (lent - 0.5) * 0.4;
  } else if (mode == TINT_WOOD_AXIS) {
    let axe = wood_axis(tint);
    let variante = wood_variant(tint);
    var f = vec3<u32>(FQ_6_0);
    if (axe == 0u) { f = vec3<u32>(FQ_0_3, FQ_8_0, FQ_8_0); }
    else if (axe == 1u) { f = vec3<u32>(FQ_8_0, FQ_0_3, FQ_8_0); }
    else if (axe == 2u) { f = vec3<u32>(FQ_8_0, FQ_8_0, FQ_0_3); }
    let graine = hash_combine(cseed, u64_of_u32(0x100u + variante));
    let veine = unit_of(value_noise(graine, pt, f));
    let planche = f32(mix64(graine).y >> 16u) / 65536.0;
    t = 0.5 + (planche - 0.5) * (13107.0 / 65536.0) + (veine - 0.5) * (29491.0 / 65536.0);
  } else if (mode == TINT_STONE_PIECE) {
    let gs = hash_combine(cseed, u64_of_u32(0x200u + tint));
    let grain = unit_of(value_noise(gs, pt, vec3<u32>(FQ_12_0)));
    if (tint == 0u) {
      t = 7864.0 / 65536.0 + (grain - 0.5) / 10.0;
    } else {
      let nuance = f32(mix64(gs).y >> 16u) / 65536.0;
      t = 19660.0 / 65536.0 + nuance * 0.55 + (grain - 0.5) / 5.0;
    }
  } else { // TINT_VEGETATION
    species = veg_species(tint);
    let rampe = veg_ramp(tint);
    if (role == 255u) {
      t = 0.5;
    } else {
      use_species = true;
      let graine = hash_combine(cseed, u64_of_u32(veg_seeds[species]));
      if (role == 1u) {          // feuilles
        let lent = value_noise(hash_combine(graine, u64_of_u32(1u)), pt, vec3<u32>(FQ_0_55));
        let moyen = value_noise(hash_combine(graine, u64_of_u32(2u)), pt, vec3<u32>(FQ_1_3));
        let fin = unit_of(value_noise(hash_combine(graine, u64_of_u32(3u)), pt, vec3<u32>(FQ_5_0)));
        t = 38010.0 / 65536.0 + (fin - 0.5) * 0.22 + (vu - 0.5) * 0.28;
        pick = (lent + moyen) / 2;
      } else if (role == 0u) {   // écorce
        let a = value_noise(hash_combine(graine, u64_of_u32(4u)), pt, vec3<u32>(FQ_4_0, FQ_0_5, FQ_4_0));
        let b = value_noise(hash_combine(graine, u64_of_u32(5u)), pt, vec3<u32>(FQ_9_0, FQ_1_0, FQ_9_0));
        t = 29491.0 / 65536.0 + (unit_of((a + b) / 2) - 0.5) / 2.0;
        ramp_idx = rampe;
      } else if (role == 2u) {   // fleurs
        let n6 = unit_of(value_noise(hash_combine(graine, u64_of_u32(6u)), pt, vec3<u32>(FQ_6_0)));
        t = 0.5 + (n6 - 0.5) * 0.3;
        ramp_idx = rampe;
      } else {                   // fruits
        let n7 = unit_of(value_noise(hash_combine(graine, u64_of_u32(7u)), pt, vec3<u32>(FQ_6_0)));
        t = 0.5 + (n7 - 0.5) * 0.3;
        ramp_idx = min(rampe, 1u);
      }
    }
  }
  t = clamp(t, 0.0, 1.0);

  // champ continu commun : luminance et teinte, indépendants du voxel
  let lent_c = unit_of(value_noise(hash_combine(cseed, u64_of_u32(0xA1u)), pt, vec3<u32>(FQ_2_0)));
  let chaud = unit_of(value_noise(hash_combine(cseed, u64_of_u32(0xA2u)), pt, vec3<u32>(FQ_0_7)));
  let decalage = (lent_c - 0.5) * 2.0 * m.albedo_var + (vu - 0.5) * 2.0 * m.voxel_jitter;

  var dark = class_ramps[cls * 3u].xyz;
  var mid = class_ramps[cls * 3u + 1u].xyz;
  var light = class_ramps[cls * 3u + 2u].xyz;
  if (use_species) {
    let n = veg_counts[species * 4u + role];
    if (n > 0u) {
      var idx = ramp_idx;
      if (pick >= 0) { idx = u32(pick) * n / 65537u; }
      idx = min(idx, n - 1u);
      let base = ((species * 4u + role) * 4u + idx) * 3u;
      dark = veg_ramps[base].xyz;
      mid = veg_ramps[base + 1u].xyz;
      light = veg_ramps[base + 2u].xyz;
    }
  }
  let c = ramp3(dark, mid, light, t + decalage);
  let k = (chaud - 0.5) * 2.0 * m.hue_var;
  return clamp(vec3<f32>(c.x + c.x * k, c.y, c.z - c.z * k), vec3<f32>(0.0), vec3<f32>(1.0));
}
