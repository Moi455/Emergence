// Fusion des profondeurs (docs/19 § 4.5 et 5.1, ligne 7) : convertit la distance du tracé en profondeur Z INVERSÉ
// infini (1 au plan proche, 0 à l'infini). En L09 il n'y a pas de peau à fusionner : seul le tracé écrit.
@group(0) @binding(0) var<uniform> VF: VoxelFrame;
@group(0) @binding(1) var dist_tex: texture_2d<f32>;

struct VO { @builtin(position) pos: vec4<f32> };

@vertex fn vs(@builtin(vertex_index) i: u32) -> VO {
  let p = vec2<f32>(f32((i << 1u) & 2u), f32(i & 2u)) * 2.0 - 1.0;
  var o: VO;
  o.pos = vec4<f32>(p, 0.0, 1.0);
  return o;
}

@fragment fn fs(in: VO) -> @builtin(frag_depth) f32 {
  let px = vec2<i32>(in.pos.xy);
  let d = textureLoad(dist_tex, px, 0).x;
  if (d > 1e29) { discard; }
  let ndc = pixel_ndc(vec2<u32>(px), VF);
  var z_view = d;
  if (VF.ray_fwd.w < 0.5) {
    // distance le long du rayon -> distance le long de l'axe de vue
    let dir = pixel_dir(ndc, VF);
    z_view = d * dot(dir, VF.ray_fwd.xyz);
    return clamp(VF.params.x / max(z_view, VF.params.x), 0.0, 1.0);
  }
  return clamp(1.0 - z_view / 1000.0, 0.0, 1.0);
}
