// Tracé primaire (docs/19 § 4.5, mode PRIMARY) : un rayon par pixel, écrit l'impact brut. La matière (passe
// suivante) en tire la couleur ; ici seulement la géométrie.
//   hit  (rgba32uint) : x = valeur (16 bits) | face << 16 | 1 << 20 si touché ; yzw = voxel touché (i32 en bits)
//   dist (r32float)   : distance le long du rayon en mètres, 1e30 si rien

@group(0) @binding(0) var<uniform> VF: VoxelFrame;
@group(0) @binding(1) var out_hit: texture_storage_2d<rgba32uint, write>;
@group(0) @binding(2) var out_dist: texture_storage_2d<r32float, write>;

@compute @workgroup_size(8, 8, 1)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
  if (f32(gid.x) >= VF.screen.x || f32(gid.y) >= VF.screen.y) { return; }
  let ndc = pixel_ndc(gid.xy, VF);
  var r: Ray;
  r.base = VF.cam_voxel.xyz;
  r.origin = pixel_origin(ndc, VF);
  r.dir = pixel_dir(ndc, VF);
  let h = trace(r, 0.0, VF.params.y, MODE_PRIMARY, 0u);
  var rec = vec4<u32>(0u);
  var dist = 1e30;
  if (h.hit) {
    rec = vec4<u32>(h.value | (h.face << 16u) | (1u << 20u), bitcast<u32>(h.voxel.x), bitcast<u32>(h.voxel.y), bitcast<u32>(h.voxel.z));
    dist = h.t * VOXEL_M;
  }
  textureStore(out_hit, vec2<i32>(gid.xy), rec);
  textureStore(out_dist, vec2<i32>(gid.xy), vec4<f32>(dist, 0.0, 0.0, 0.0));
}
