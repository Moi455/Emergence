// Occlusion ambiante tracée (L14, docs/19 § 5) : pour chaque pixel touché, N rayons cosinus dans l'hémisphère de la
// face, de portée courte, tracés par la MÊME `trace()` que le tracé primaire (mode OCCLUSION). Assemblé après :
// voxel_frame, voxel_world (groupe 1). Écrit l'occlusion BRUTE (fraction occultée pondérée par la distance), empaquetée
// dans un mot de 32 bits (`r32uint`) pour que le filtre lise 4 octets par texel :
//   bits 0-7 : fraction occultée (0 libre, 255 enfermé) ; bits 8-10 : face (0 à 5, 7 = rien touché) ;
//   bits 11-31 : plan de la face (voxels relatifs au voxel de la caméra, exact) + 1 048 576.
// Échantillonnage DÉTERMINISTE : spirale de Fibonacci tournée d'un angle tiré du hachage de la position monde du point
// (voxel + quart de voxel + face) ; aucun bruit temporel, aucune dépendance à l'image ni à la caméra.
// Résolution : un texel brut par bloc de `diviseur × diviseur` pixels (1 ou 2), le filtre remonte en pleine résolution.
@group(0) @binding(0) var<uniform> VF: VoxelFrame;
@group(0) @binding(1) var in_hit: texture_2d<u32>;
@group(0) @binding(2) var in_dist: texture_2d<f32>;
@group(0) @binding(3) var<uniform> CFG: array<vec4<f32>, 2>;   // [0] : x = rayons, y = portée (voxels), z = force, w = rayon du filtre (px) ; [1].x = diviseur de résolution
@group(0) @binding(4) var out_raw: texture_storage_2d<r32uint, write>;

const PLAN_DECALAGE: i32 = 1048576;

const ANGLE_D_OR: f32 = 2.399963;
const TAU: f32 = 6.283185307;

fn axis_vec(a: u32) -> vec3<f32> {
  return vec3<f32>(select(0.0, 1.0, a == 0u), select(0.0, 1.0, a == 1u), select(0.0, 1.0, a == 2u));
}

// Miroir de `position_hash` (Rust).
fn ao_hash(voxel: vec3<i32>, q: vec3<f32>, face: u32) -> u32 {
  let c = vec3<u32>(bitcast<vec3<u32>>(voxel)) * 4u + bitcast<vec3<u32>>(vec3<i32>(floor(q * 4.0)));
  var h = (c.x * 0x8da6b343u) ^ (c.y * 0xd8163841u) ^ (c.z * 0xcb1ab31fu) ^ (face * 0x9e3779b9u);
  h ^= h >> 15u;
  h *= 0x2c1b3c6du;
  h ^= h >> 12u;
  h *= 0x297a2d39u;
  h ^= h >> 15u;
  return h;
}

@compute @workgroup_size(8, 8, 1)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
  let dims = vec2<u32>(textureDimensions(out_raw));
  if (gid.x >= dims.x || gid.y >= dims.y) { return; }
  // Le texel brut représente le pixel en haut à gauche du bloc `diviseur × diviseur`.
  let diviseur = u32(CFG[1].x + 0.5);
  let pix = gid.xy * diviseur;
  let px = vec2<i32>(pix);
  let rec = textureLoad(in_hit, px, 0);
  var res = 7u << 8u;
  if ((rec.x & (1u << 20u)) != 0u) {
    let face = (rec.x >> 16u) & 7u;
    let voxel = vec3<i32>(bitcast<i32>(rec.y), bitcast<i32>(rec.z), bitcast<i32>(rec.w));
    let ax = face >> 1u;
    let positif = (face & 1u) == 1u;
    let sgn = select(-1.0, 1.0, positif);
    let m = axis_vec(ax);
    let nrm = m * sgn;
    let t1 = axis_vec((ax + 1u) % 3u);
    let t2 = axis_vec((ax + 2u) % 3u);

    // Point touché dans le repère du voxel : les coordonnées tangentes sont ramenées dans la face, la normale est posée
    // à 0,02 voxel hors du voxel (la cellule de départ est donc la cellule vide d'où le rayon primaire est venu).
    let ndc = pixel_ndc(pix, VF);
    let dir = pixel_dir(ndc, VF);
    let dist_m = textureLoad(in_dist, px, 0).x;
    let p_rel = pixel_origin(ndc, VF) + dir * (dist_m / VOXEL_M);
    let q = p_rel - vec3<f32>(voxel - VF.cam_voxel.xyz);
    var o = clamp(q, vec3<f32>(0.002), vec3<f32>(0.998));
    o = o * (vec3<f32>(1.0) - m) + m * select(-0.02, 1.02, positif);

    let n_rayons = u32(CFG[0].x + 0.5);
    let hash = ao_hash(voxel, o, face);
    let angle0 = f32(hash & 0xFFFFu) / 65536.0 * TAU;
    var r: Ray;
    r.base = voxel;
    r.origin = o;
    var somme = 0.0;
    for (var i = 0u; i < n_rayons; i++) {
      let u = (f32(i) + 0.5) / f32(n_rayons);
      let rr = sqrt(u);
      let phi = angle0 + f32(i) * ANGLE_D_OR;
      r.dir = t1 * (rr * cos(phi)) + t2 * (rr * sin(phi)) + nrm * sqrt(max(1.0 - u, 0.0));
      let h = trace(r, 0.0, CFG[0].y, MODE_OCCLUSION, 0u);
      if (h.hit) {
        let x = clamp(1.0 - h.t / CFG[0].y, 0.0, 1.0);
        somme += x * x;
      }
    }
    let plan = voxel[ax] - VF.cam_voxel[ax] + select(0, 1, positif);
    let occ = u32(clamp(somme / f32(n_rayons), 0.0, 1.0) * 255.0 + 0.5);
    res = occ | (face << 8u) | (u32(plan + PLAN_DECALAGE) << 11u);
  }
  textureStore(out_raw, vec2<i32>(gid.xy), vec4<u32>(res, 0u, 0u, 0u));
}
