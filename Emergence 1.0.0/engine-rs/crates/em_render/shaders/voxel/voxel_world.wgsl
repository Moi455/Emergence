// Monde voxel côté GPU (docs/19a § 5.1) et traversée hiérarchique (docs/19 § 4.5) : chunks de 64 voxels,
// briques de 8, voxels, avec le DDA d'Amanatides et Woo en cellules ENTIÈRES et distances f32 relatives à la
// caméra. `trace()` est la fonction partagée : tracé primaire ici ; ombres, occlusion et reflets la réutiliseront
// avec d'autres bornes et un autre `mode`.

struct ClipLevel {
  origin_chunk: vec3<i32>,
  lod: u32,
  table_offset: u32,
  _pad0: u32, _pad1: u32, _pad2: u32,
};
struct ChunkGpu {
  mask_all: array<u32, 16>,
  mask_visible: array<u32, 16>,
  bricks: array<u32, 512>,
};
@group(1) @binding(0) var<uniform> levels: array<ClipLevel, 6>;
@group(1) @binding(1) var<storage, read> chunk_table: array<u32>;
@group(1) @binding(2) var<storage, read> chunk_pool: array<ChunkGpu>;
@group(1) @binding(3) var<storage, read> brick_occ: array<vec4<u32>>;
@group(1) @binding(4) var<storage, read> brick_meta: array<vec2<u32>>;
@group(1) @binding(5) var<storage, read> payload: array<u32>;

const EMPTY: u32 = 0xFFFFFFFFu;
const BIT_UNIFORM: u32 = 0x80000000u;
const BIT_SKIN: u32 = 0x40000000u;

const MODE_PRIMARY: u32 = 0u;
const MODE_SHADOW_MAP: u32 = 1u;
const MODE_OCCLUSION: u32 = 2u;

const MAX_STEPS: u32 = 1500u;
const FACE_NONE: u32 = 6u;

// Rayon : position absolue = base + origin (origin en voxels, de n'importe quelle taille raisonnable).
struct Ray {
  origin: vec3<f32>,
  dir: vec3<f32>,
  base: vec3<i32>,
};

// Impact. `face` : 2 × axe + (1 si la normale est positive) ; `t` en voxels.
struct Hit {
  hit: bool,
  t: f32,
  value: u32,
  voxel: vec3<i32>,
  face: u32,
};

fn safe_inv(x: f32) -> f32 {
  let s = select(-1e-20, 1e-20, x >= 0.0);
  return 1.0 / select(x, s, abs(x) < 1e-20);
}

fn argmin3(v: vec3<f32>) -> u32 {
  if (v.x <= v.y && v.x <= v.z) { return 0u; }
  if (v.y <= v.z) { return 1u; }
  return 2u;
}

// Voxel i (0..512) d'une brique à palette : lecture miroir de `voxel::pack::decode_voxel`.
fn brick_value(bslot: u32, vi: u32) -> u32 {
  let m = brick_meta[bslot];
  let off = m.x;
  let lb = m.y & 15u;
  if (lb == 4u) {
    let w16 = payload[off + (vi >> 1u)];
    return (w16 >> ((vi & 1u) * 16u)) & 0xFFFFu;
  }
  let bits = 1u << lb;
  var pal_words = 128u;
  if (lb <= 1u) { pal_words = 2u; } else if (lb == 2u) { pal_words = 8u; }
  let pos = vi * bits;
  let w = payload[off + pal_words + (pos >> 5u)];
  let idx = (w >> (pos & 31u)) & ((1u << bits) - 1u);
  let pw = payload[off + (idx >> 1u)];
  return (pw >> ((idx & 1u) * 16u)) & 0xFFFFu;
}

// Masque de l'axe du plus petit composant (en cas d'égalité : x, puis y, puis z, comme `argmin3`).
fn axis_mask(v: vec3<f32>) -> vec3<bool> {
  let ax = argmin3(v);
  return vec3<bool>(ax == 0u, ax == 1u, ax == 2u);
}

// Composante de `v` sur l'axe masqué (sans indexation dynamique, qui coûte cher sur GPU).
fn pick_i(m: vec3<bool>, v: vec3<i32>) -> i32 {
  return select(select(v.z, v.y, m.y), v.x, m.x);
}

fn face_mask(m: vec3<bool>, sgn: i32) -> u32 {
  let axis = select(select(2u, 1u, m.y), 0u, m.x);
  return axis * 2u + select(1u, 0u, sgn > 0);
}

fn face_of(axis: u32, sgn: i32) -> u32 {
  // la normale s'oppose au sens de marche : sgn > 0 -> normale négative
  return axis * 2u + select(1u, 0u, sgn > 0);
}

fn trace(ray: Ray, t_min: f32, t_max: f32, mode: u32, level: u32) -> Hit {
  var h: Hit;
  h.hit = false;
  h.t = 0.0;
  h.value = 0u;
  h.voxel = vec3<i32>(0);
  h.face = FACE_NONE;

  let lv = levels[level];
  let d = ray.dir;
  let sgn = vec3<i32>(select(-1, 1, d.x >= 0.0), select(-1, 1, d.y >= 0.0), select(-1, 1, d.z >= 0.0));
  let pos_bits = select(vec3<i32>(0), vec3<i32>(1), sgn > vec3<i32>(0));
  let inv = vec3<f32>(safe_inv(d.x), safe_inv(d.y), safe_inv(d.z));

  // Cellule de départ et position fractionnaire : tout le calcul est relatif à `cell0`.
  let fo = floor(ray.origin);
  let cell0 = ray.base + vec3<i32>(fo);
  let org = ray.origin - fo;

  // Fenêtre du niveau (16 chunks de 64 voxels), relative à cell0.
  let wmin = lv.origin_chunk * 64 - cell0;
  let wmax = wmin + vec3<i32>(1024);
  let tA = (vec3<f32>(wmin) - org) * inv;
  let tB = (vec3<f32>(wmax) - org) * inv;
  let tlo = min(tA, tB);
  let thi = max(tA, tB);
  let t_enter = max(max(tlo.x, tlo.y), tlo.z);
  let t_exit = min(min(thi.x, thi.y), thi.z);
  var t = max(t_min, t_enter);
  let t_end = min(t_max, t_exit);
  if (t > t_end) { return h; }

  // Face d'entrée du premier voxel : celle de la fenêtre si le rayon y entre, sinon (départ dans la fenêtre,
  // éventuellement dans un voxel plein) la face opposée à l'axe dominant du rayon.
  var face: u32;
  if (t_enter > t_min && t_enter >= 0.0) {
    let ax_e = argmin3(-tlo);
    face = face_of(ax_e, sgn[ax_e]);
  } else {
    let a = abs(d);
    var ax = 0u;
    if (a.y >= a.x && a.y >= a.z) { ax = 1u; } else if (a.z >= a.x && a.z >= a.y) { ax = 2u; }
    face = face_of(ax, sgn[ax]);
  }

  var c = clamp(vec3<i32>(floor(org + d * t)), wmin, wmax - vec3<i32>(1));
  let tdc = abs(inv) * 64.0;
  var steps = 0u;

  // Boucle externe : chunks de 64 voxels. Les chunks vides se traversent par un DDA incrémental (peu
  // d'instructions par chunk) ; un chunk plein uniforme est touché à l'entrée ; un chunk mixte passe à la boucle
  // interne (briques de 8 voxels, puis voxels).
  for (var ci = 0u; ci < 256u && steps < MAX_STEPS; ci++) {
    let A = cell0 + c;
    let cc = A >> vec3<u32>(6u);
    let r = cc - lv.origin_chunk;
    if (any(r < vec3<i32>(0)) || any(r >= vec3<i32>(16))) { break; }
    var ce = chunk_table[lv.table_offset + u32(cc.x & 15) + 16u * u32(cc.z & 15) + 256u * u32(cc.y & 15)];

    if (ce == EMPTY) {
      // Traversée incrémentale des chunks vides jusqu'au prochain chunk non vide.
      var tmc = (vec3<f32>((cc + pos_bits) * 64 - cell0) - org) * inv;
      var cn = cc;
      var am = vec3<bool>(false);
      var sortie = false;
      for (var k = 0u; k < 64u; k++) {
        am = axis_mask(tmc);
        let te = min(min(tmc.x, tmc.y), tmc.z);
        if (te > t_end) { sortie = true; break; }
        t = te;
        cn = cn + select(vec3<i32>(0), sgn, am);
        tmc = select(tmc, tmc + tdc, am);
        let rn = cn - lv.origin_chunk;
        if (any(rn < vec3<i32>(0)) || any(rn >= vec3<i32>(16))) { sortie = true; break; }
        ce = chunk_table[lv.table_offset + u32(cn.x & 15) + 16u * u32(cn.z & 15) + 256u * u32(cn.y & 15)];
        steps += 1u;
        if (ce != EMPTY) { break; }
      }
      if (sortie || ce == EMPTY) { break; }
      // Entrée dans le chunk `cn` par l'axe `am` : cellule exacte sur cet axe, partie entière ailleurs.
      let cmin = cn * 64 - cell0;
      let exact = select(cmin + vec3<i32>(63), cmin, sgn > vec3<i32>(0));
      c = select(clamp(vec3<i32>(floor(org + d * t)), cmin, cmin + vec3<i32>(63)), exact, am);
      face = face_mask(am, pick_i(am, sgn));
      continue;
    }

    if ((ce & BIT_UNIFORM) != 0u) {
      h.hit = true; h.t = t; h.value = ce & 0xFFFFu; h.voxel = A; h.face = face;
      return h;
    }

    // Chunk mixte : DDA incrémental par briques de 8 voxels ; voxel par voxel dans les briques à palette.
    let pool = ce & 0xFFFFFFu;
    let tdb = abs(inv) * 8.0;
    var bc = (cell0 + c) >> vec3<u32>(3u);
    var tmb = (vec3<f32>((bc + pos_bits) * 8 - cell0) - org) * inv;
    for (var i = 0u; i < 256u && steps < MAX_STEPS; i++) {
      steps += 1u;
      let bi = u32(bc.x & 7) + 8u * u32(bc.z & 7) + 64u * u32(bc.y & 7);
      let be = chunk_pool[pool].bricks[bi];
      let vide = be == EMPTY || (mode == MODE_SHADOW_MAP && (be & BIT_SKIN) != 0u);
      if (!vide && (be & BIT_UNIFORM) != 0u) {
        h.hit = true; h.t = t; h.value = be & 0xFFFFu; h.voxel = cell0 + c; h.face = face;
        return h;
      }
      if (!vide) {
        // Brique à palette : voxels, jusqu'à en sortir.
        let bslot = be & 0xFFFFFFu;
        var tm = (vec3<f32>(c + pos_bits) - org) * inv;
        for (var j = 0u; j < 32u; j++) {
          let Ai = cell0 + c;
          let vi = u32(Ai.x & 7) + 8u * u32(Ai.z & 7) + 64u * u32(Ai.y & 7);
          let w = brick_occ[bslot * 4u + (vi >> 7u)][(vi >> 5u) & 3u];
          if (((w >> (vi & 31u)) & 1u) != 0u) {
            h.hit = true; h.t = t; h.value = brick_value(bslot, vi); h.voxel = Ai; h.face = face;
            return h;
          }
          let am = axis_mask(tm);
          let tn = min(min(tm.x, tm.y), tm.z);
          if (tn > t_end) { return h; }
          t = tn;
          let cs = c + select(vec3<i32>(0), sgn, am);
          c = cs;
          tm = select(tm, (vec3<f32>(cs + pos_bits) - org) * inv, am);
          face = face_mask(am, pick_i(am, sgn));
          if (any(((cell0 + cs) >> vec3<u32>(3u)) != bc)) { break; }
        }
        // On a quitté la brique : recalcul de l'état des briques depuis la cellule entière exacte.
        bc = (cell0 + c) >> vec3<u32>(3u);
        if (any((bc >> vec3<u32>(3u)) != cc)) { break; }
        tmb = (vec3<f32>((bc + pos_bits) * 8 - cell0) - org) * inv;
        continue;
      }
      // Brique vide : pas incrémental jusqu'à la brique voisine.
      let am = axis_mask(tmb);
      let te = min(min(tmb.x, tmb.y), tmb.z);
      if (te > t_end) { return h; }
      t = te;
      bc = bc + select(vec3<i32>(0), sgn, am);
      tmb = select(tmb, tmb + tdb, am);
      let bmin = bc * 8 - cell0;
      let exact = select(bmin + vec3<i32>(7), bmin, sgn > vec3<i32>(0));
      c = select(clamp(vec3<i32>(floor(org + d * t)), bmin, bmin + vec3<i32>(7)), exact, am);
      face = face_mask(am, pick_i(am, sgn));
      if (any((bc >> vec3<u32>(3u)) != cc)) { break; }
    }
  }
  return h;
}
