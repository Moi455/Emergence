// Montée en résolution et filtre bilatéral de l'occlusion ambiante (L14), en pleine résolution : chaque pixel moyenne les
// texels bruts voisins (un texel par bloc de `diviseur × diviseur` pixels) en donnant un poids gaussien selon la distance
// en pixels, et un poids 50 fois moindre aux texels qui ne sont PAS de sa face (même axe et même sens) à un plan voisin
// (au plus un voxel d'écart). Les arêtes de voxels, les marches et les silhouettes ne sont donc pas traversées dès qu'un
// texel de la même surface existe. N'agit que sur l'occlusion : l'albédo reste net.
// Écrit la visibilité de l'ambiance (1 = libre) = 1 - force × fraction occultée filtrée.
@group(0) @binding(0) var<uniform> VF: VoxelFrame;
@group(0) @binding(1) var<uniform> CFG: array<vec4<f32>, 2>;   // comme `voxel_ao.wgsl`
@group(0) @binding(2) var raw_tex: texture_2d<u32>;   // voir `voxel_ao.wgsl` pour l'empaquetage

const PLAN_DECALAGE: i32 = 1048576;
@group(0) @binding(3) var in_hit: texture_2d<u32>;
@group(0) @binding(4) var out_ao: texture_storage_2d<r32float, write>;

const INCOMPATIBLE: f32 = 0.02;

@compute @workgroup_size(8, 8, 1)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
  if (f32(gid.x) >= VF.screen.x || f32(gid.y) >= VF.screen.y) { return; }
  let px = vec2<i32>(gid.xy);
  let rec = textureLoad(in_hit, px, 0);
  var vis = 1.0;
  if ((rec.x & (1u << 20u)) != 0u) {
    let diviseur = i32(CFG[1].x + 0.5);
    let dims = vec2<i32>(textureDimensions(raw_tex));
    let face = (rec.x >> 16u) & 7u;
    let ax = face >> 1u;
    let voxel = vec3<i32>(bitcast<i32>(rec.y), bitcast<i32>(rec.z), bitcast<i32>(rec.w));
    let plan = voxel[ax] - VF.cam_voxel[ax] + select(0, 1, (face & 1u) == 1u);
    let filtre = i32(CFG[0].w + 0.5);
    // Rayon de recherche en texels bruts : couvre le rayon du filtre, au moins les 4 texels autour du pixel.
    let rayon = max((filtre + diviseur - 1) / diviseur, select(0, 1, diviseur > 1));
    let sigma = 0.5 * f32(max(filtre, 1)) + 0.35 * f32(diviseur);
    let sigma2 = 2.0 * sigma * sigma;
    let base = px / diviseur;
    var somme = 0.0;
    var poids = 0.0;
    for (var dy = -rayon; dy <= rayon; dy++) {
      for (var dx = -rayon; dx <= rayon; dx++) {
        let q = base + vec2<i32>(dx, dy);
        if (q.x < 0 || q.y < 0 || q.x >= dims.x || q.y >= dims.y) { continue; }
        let n = textureLoad(raw_tex, q, 0).x;
        let nface = (n >> 8u) & 7u;
        if (nface == 7u) { continue; }
        let d = vec2<f32>(q * diviseur - px);
        var w = exp(-dot(d, d) / sigma2);
        if (nface != face || abs(i32(n >> 11u) - PLAN_DECALAGE - plan) > 0) { w *= INCOMPATIBLE; }
        somme += f32(n & 255u) * w;
        poids += w;
      }
    }
    if (poids > 0.0) { vis = clamp(1.0 - CFG[0].z * (somme / (255.0 * poids)), 0.0, 1.0); }
  }
  textureStore(out_ao, px, vec4<f32>(vis, 0.0, 0.0, 0.0));
}
