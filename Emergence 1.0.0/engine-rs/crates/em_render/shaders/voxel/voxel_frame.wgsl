// Uniforme d'image du rendu voxel (docs/19a § 5.4, réduit à ce que L09 lit). Miroir de `voxel::gpu::VoxelFrame`
// (Rust) : 7 vec4, tout en vec4 (aucun piège d'alignement). Repère GAUCHE : x est, y haut, z nord.
struct VoxelFrame {
  ray_right: vec4<f32>,   // perspective : droite × tan(champ x / 2) ; orthographique : droite × demi-largeur en voxels
  ray_up:    vec4<f32>,   // idem pour le haut
  ray_fwd:   vec4<f32>,   // avant ; w = 1 si orthographique
  cam_voxel: vec4<i32>,   // voxel entier de la caméra ; w = n° d'image
  cam_frac:  vec4<f32>,   // position dans ce voxel, en voxels ; w = temps (s)
  screen:    vec4<f32>,   // largeur, hauteur, 1/largeur, 1/hauteur
  params:    vec4<f32>,   // x = plan proche (m), y = portée max (voxels)
};

const VOXEL_M: f32 = 0.05;

// Coordonnées de pixel (centre) -> NDC, y vers le haut.
fn pixel_ndc(px: vec2<u32>, vf: VoxelFrame) -> vec2<f32> {
  return vec2<f32>((f32(px.x) + 0.5) * vf.screen.z * 2.0 - 1.0, 1.0 - (f32(px.y) + 0.5) * vf.screen.w * 2.0);
}

// Direction du rayon du pixel (unitaire).
fn pixel_dir(ndc: vec2<f32>, vf: VoxelFrame) -> vec3<f32> {
  if (vf.ray_fwd.w > 0.5) { return vf.ray_fwd.xyz; }
  return normalize(vf.ray_fwd.xyz + vf.ray_right.xyz * ndc.x + vf.ray_up.xyz * ndc.y);
}

// Origine du rayon relative au voxel entier de la caméra, en voxels.
fn pixel_origin(ndc: vec2<f32>, vf: VoxelFrame) -> vec3<f32> {
  if (vf.ray_fwd.w > 0.5) { return vf.cam_frac.xyz + vf.ray_right.xyz * ndc.x + vf.ray_up.xyz * ndc.y; }
  return vf.cam_frac.xyz;
}
