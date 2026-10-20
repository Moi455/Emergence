// Épaisseur de feuillage le long du soleil (translucidité des feuilles, docs/19 § 5.4). Assemblé après : frame du ciel
// (struct `Frame`), voxel_frame, voxel_world (groupe 1), material.wgsl (matières, groupe 2).
//
// Pour chaque pixel dont le voxel touché est du feuillage : DDA (Amanatides et Woo) en cellules ENTIÈRES depuis le centre
// du voxel touché, le long du soleil, borné à `zone` voxels. Écrit la longueur parcourue dans des voxels de feuillage (mètres),
// ou BLOQUE (1000) si un solide qui n'est pas du feuillage barre le trajet, 0 hors feuillage.
// Groupe 0 : ciel (soleil), image voxel, impact, zone, sortie.
@group(0) @binding(0) var<uniform> F: Frame;
@group(0) @binding(1) var<uniform> VF: VoxelFrame;
@group(0) @binding(2) var in_hit: texture_2d<u32>;
@group(0) @binding(3) var<uniform> ZONE: vec4<f32>;     // x = zone (voxels), y = code « soleil barré » (m), z = coupure (voxels)
@group(0) @binding(4) var out_thick: texture_storage_2d<r32float, write>;

// Matières (groupe 2) : mêmes tampons que la passe de matière ; seul `materials` sert ici.
@group(2) @binding(0) var<storage, read> materials: array<MaterialGpu>;
@group(2) @binding(1) var<storage, read> class_ramps: array<vec4<f32>>;
@group(2) @binding(2) var<storage, read> veg_ramps: array<vec4<f32>>;
@group(2) @binding(3) var<storage, read> veg_seeds: array<u32>;
@group(2) @binding(4) var<storage, read> class_extra: array<vec4<u32>>;
@group(2) @binding(5) var<storage, read> veg_counts: array<u32>;
@group(2) @binding(6) var<storage, read> pixel_params: array<vec4<f32>>;

// Contenu de la brique de la cellule : 0 vide, 1 uniforme (valeur dans `valeur`), 2 à palette (emplacement dans `slot`).
struct Brique {
  genre: u32,
  valeur: u32,
  slot: u32,
};

// Brique (8 voxels) contenant la cellule absolue `cell` (niveau 0) : EMPTY si vide ou hors de la fenêtre.
fn brique_de(cell: vec3<i32>) -> Brique {
  var b: Brique;
  b.genre = 0u;
  b.valeur = 0u;
  b.slot = 0u;
  let lv = levels[0];
  let cc = cell >> vec3<u32>(6u);
  let r = cc - lv.origin_chunk;
  if (any(r < vec3<i32>(0)) || any(r >= vec3<i32>(16))) { return b; }
  let ce = chunk_table[lv.table_offset + u32(cc.x & 15) + 16u * u32(cc.z & 15) + 256u * u32(cc.y & 15)];
  if (ce == EMPTY) { return b; }
  if ((ce & BIT_UNIFORM) != 0u) { b.genre = 1u; b.valeur = ce & 0xFFFFu; return b; }
  let pool = ce & 0xFFFFFFu;
  let bc = cell >> vec3<u32>(3u);
  let bi = u32(bc.x & 7) + 8u * u32(bc.z & 7) + 64u * u32(bc.y & 7);
  let be = chunk_pool[pool].bricks[bi];
  if (be == EMPTY) { return b; }
  if ((be & BIT_UNIFORM) != 0u) { b.genre = 1u; b.valeur = be & 0xFFFFu; return b; }
  b.genre = 2u;
  b.slot = be & 0xFFFFFFu;
  return b;
}

// Valeur du voxel de la cellule `cell` dans sa brique `b` ; EMPTY si vide.
fn valeur_dans(b: Brique, cell: vec3<i32>) -> u32 {
  if (b.genre == 0u) { return EMPTY; }
  if (b.genre == 1u) { return b.valeur; }
  let vi = u32(cell.x & 7) + 8u * u32(cell.z & 7) + 64u * u32(cell.y & 7);
  let w = brick_occ[b.slot * 4u + (vi >> 7u)][(vi >> 5u) & 3u];
  if (((w >> (vi & 31u)) & 1u) == 0u) { return EMPTY; }
  return brick_value(b.slot, vi);
}

// Cellules suivies exactement par le DDA, puis pas d'échantillonnage (voxels) au-delà.
const N_EXACT: u32 = 8u;
const STEP_ECH: f32 = 1.5;

fn is_foliage(value: u32) -> bool {
  return (materials[voxel_class(value)].flags & FLAG_FOLIAGE) != 0u;
}

@compute @workgroup_size(8, 8, 1)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
  if (f32(gid.x) >= VF.screen.x || f32(gid.y) >= VF.screen.y) { return; }
  let px = vec2<i32>(gid.xy);
  let rec = textureLoad(in_hit, px, 0);
  var epais = 0.0;
  // Face touchée : axe (face >> 1), signe (face & 1) ; la normale regarde l'observateur. Seules les faces à peu près
  // tournées à l'opposé du soleil (n · soleil < 0,35, comme `derriere` de l'éclairage) transmettent.
  let face = (rec.x >> 16u) & 7u;
  let signe = select(-1.0, 1.0, (face & 1u) == 1u);
  let sun_n = normalize(F.sunDir.xyz);
  let ax = face >> 1u;
  let cos_ns = signe * select(select(sun_n.z, sun_n.y, ax == 1u), sun_n.x, ax == 0u);
  if ((rec.x & (1u << 20u)) != 0u && cos_ns < 0.35 && is_foliage(rec.x & 0xFFFFu)) {
    let voxel = vec3<i32>(bitcast<i32>(rec.y), bitcast<i32>(rec.z), bitcast<i32>(rec.w));
    // Départ au CENTRE du voxel touché : toute la face d'un voxel reçoit la même épaisseur, donc la même lumière
    // (aplat net, comme la nuance du voxel), et le résultat ne dépend pas du pixel.
    let p = vec3<f32>(0.5);
    let s = sun_n;
    let pas = vec3<i32>(select(-1, 1, s.x >= 0.0), select(-1, 1, s.y >= 0.0), select(-1, 1, s.z >= 0.0));
    let inv = vec3<f32>(abs(safe_inv(s.x)), abs(safe_inv(s.y)), abs(safe_inv(s.z)));
    var tmax = select(p, vec3<f32>(1.0) - p, s >= vec3<f32>(0.0)) * inv;
    var cell = voxel;
    var t = 0.0;
    var dans_feuille = true;                       // la cellule de départ est du feuillage
    var brique = brique_de(cell);
    var bc = cell >> vec3<u32>(3u);
    var derniere = 0xFFFFFFFFu;                    // mémo : dernière valeur testée et son verdict
    var derniere_feuille = false;
    var fini = false;
    let zone = ZONE.x;
    let coupure = ZONE.z;                          // épaisseur (voxels) au-delà de laquelle la lumière est négligeable
    // Phase 1 : DDA exact sur les premières cellules (le liseré se joue sur les 1 à 4 premiers voxels de feuillage).
    for (var i = 0u; i < N_EXACT; i++) {
      let te = min(min(tmax.x, tmax.y), tmax.z);
      if (dans_feuille) { epais += max(min(te, zone) - t, 0.0); }
      if (te >= zone || epais >= coupure) { fini = true; break; }
      t = te;
      let am = axis_mask(tmax);
      cell = cell + select(vec3<i32>(0), pas, am);
      tmax = select(tmax, tmax + inv, am);
      let nb = cell >> vec3<u32>(3u);
      if (any(nb != bc)) {
        bc = nb;
        brique = brique_de(cell);
      }
      let v = valeur_dans(brique, cell);
      if (v == EMPTY) {
        dans_feuille = false;
      } else {
        if (v != derniere) {
          derniere = v;
          derniere_feuille = is_foliage(v);
        }
        if (derniere_feuille) {
          dans_feuille = true;
        } else {
          epais = ZONE.y;                          // tronc, pierre... : le soleil est barré
          fini = true;
          break;
        }
      }
    }
    // Phase 2 : au-delà, un échantillon tous les 1,5 voxel le long du soleil (moitié moins de lectures que le DDA) ;
    // la cellule courante, entrée à `t`, est comptée jusqu'au premier échantillon.
    if (!fini) {
      if (dans_feuille) { epais += min(STEP_ECH * 0.5, max(zone - t, 0.0)); }
      var tt = t + STEP_ECH * 0.5;
      for (var k = 0u; k < 40u; k++) {
        if (tt >= zone || epais >= coupure) { break; }
        let c2 = voxel + vec3<i32>(floor(vec3<f32>(0.5) + s * tt));
        let nb = c2 >> vec3<u32>(3u);
        if (any(nb != bc)) {
          bc = nb;
          brique = brique_de(c2);
        }
        let v = valeur_dans(brique, c2);
        if (v != EMPTY) {
          if (v != derniere) {
            derniere = v;
            derniere_feuille = is_foliage(v);
          }
          if (derniere_feuille) {
            epais += min(STEP_ECH, zone - tt + STEP_ECH * 0.5);
          } else {
            epais = ZONE.y;
            break;
          }
        }
        tt += STEP_ECH;
      }
    }
    if (epais < ZONE.y) { epais = epais * VOXEL_M; }
  }
  textureStore(out_thick, px, vec4<f32>(epais, 0.0, 0.0, 0.0));
}
