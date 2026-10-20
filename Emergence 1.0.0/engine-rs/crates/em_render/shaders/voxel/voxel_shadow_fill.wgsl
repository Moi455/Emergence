// Remplissage des cascades d'ombre (docs/19 § 5.3) : un rayon par texel, lancé DU PLAN DE DÉPART VERS LA SCÈNE le long
// de -soleil, par la MÊME fonction `trace()` que le tracé primaire (mode SHADOW_MAP : briques `skin` ignorées).
// Écrit la distance du premier voxel plein depuis le plan (m), 1e9 si rien. Un groupe de travail de 8 × 8 texels ;
// `workgroup_id.xy` parcourt une tuile de 128 × 128 texels, `workgroup_id.z` est le numéro de la tuile du lot.
// Assemblé après : voxel_frame, voxel_world. Groupe 0 = ce passe, groupe 1 = monde.

struct FillCascade {
  base:  vec4<i32>,   // voxel entier du texel (0, 0) sur le plan
  frac:  vec4<f32>,   // position dans ce voxel (voxels)
  du:    vec4<f32>,   // pas d'un texel selon u (voxels)
  dv:    vec4<f32>,   // pas d'un texel selon v (voxels)
  dir:   vec4<f32>,   // direction des rayons
  infos: vec4<u32>,   // x = couche écrite, y = côté (texels)
};

@group(0) @binding(0) var<uniform> FC: array<FillCascade, 4>;
@group(0) @binding(1) var<storage, read> jobs: array<vec4<u32>>;
@group(0) @binding(2) var out_depth: texture_storage_2d_array<r32float, write>;

const TUILE: u32 = 128u;
const LOIN: f32 = 1.0e9;
// Portée d'un rayon d'ombre en voxels : plan à 72 m au plus devant la scène + 50 m de fenêtre.
const PORTEE_OMBRE: f32 = 2600.0;

@compute @workgroup_size(8, 8, 1)
fn main(@builtin(workgroup_id) wg: vec3<u32>, @builtin(local_invocation_id) li: vec3<u32>) {
  let job = jobs[wg.z];
  let c = FC[job.x];
  let px = vec2<u32>(job.y * TUILE + wg.x * 8u + li.x, job.z * TUILE + wg.y * 8u + li.y);
  var r: Ray;
  r.base = c.base.xyz;
  r.origin = c.frac.xyz + c.du.xyz * f32(px.x) + c.dv.xyz * f32(px.y);
  r.dir = c.dir.xyz;
  let h = trace(r, 0.0, PORTEE_OMBRE, MODE_SHADOW_MAP, 0u);
  let d = select(LOIN, h.t * VOXEL_M, h.hit);
  textureStore(out_depth, vec2<i32>(px), i32(c.infos.x), vec4<f32>(d, 0.0, 0.0, 0.0));
}
