// Remplissage RASTER d'une cascade d'ombre du soleil (L33) : on dessine les quads dans la fenêtre de la cascade, vue
// du soleil, en projection orthographique ; la profondeur (Z inversé) est 1 - distance / portée, où la distance est
// celle du plan de départ des cascades (même définition que le remplissage compute de L11 : l'échantillonnage de
// `voxel_shadow_sample.wgsl` n'a pas changé). Assemblé après : mesh_quad.
struct ShadowView {
  vp: mat4x4<f32>,
};
@group(0) @binding(0) var<uniform> SV: ShadowView;

@vertex fn vs_shadow(@builtin(vertex_index) vi: u32, @builtin(instance_index) qi: u32) -> @builtin(position) vec4<f32> {
  let q = quad_vertex(qi, vi);
  let p_rel = CU.origin.xyz + q.local * CU.origin.w;
  return SV.vp * vec4<f32>(p_rel, 1.0);
}
