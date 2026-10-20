// Passe de matière (docs/19 § 4.6) : lit l'impact du tracé, évalue la couleur du voxel EN COORDONNÉES MONDE avec
// le paquet de matières et écrit le G-buffer (docs/19a § 5.2). Assemblé après `voxel_frame.wgsl` et `material.wgsl`.
//   gb0 (rgba8unorm) : albédo sRGB encodé à la main (rgb), occlusion de matière (a)
//   gb1 (r32uint)    : normale de FACE octaédrique, 2 × 16 bits
//   gb2 (rgba8unorm) : rugosité, translucidité, émission (logarithmique), drapeaux (bit 0 feuillage, bit 3 voxel)

@group(0) @binding(0) var<uniform> VF: VoxelFrame;
@group(0) @binding(1) var in_hit: texture_2d<u32>;
@group(0) @binding(2) var out_gb0: texture_storage_2d<rgba8unorm, write>;
@group(0) @binding(3) var out_gb1: texture_storage_2d<r32uint, write>;
@group(0) @binding(4) var out_gb2: texture_storage_2d<rgba8unorm, write>;

@group(1) @binding(0) var<storage, read> materials: array<MaterialGpu>;
@group(1) @binding(1) var<storage, read> class_ramps: array<vec4<f32>>;
@group(1) @binding(2) var<storage, read> veg_ramps: array<vec4<f32>>;
@group(1) @binding(3) var<storage, read> veg_seeds: array<u32>;
@group(1) @binding(4) var<storage, read> class_extra: array<vec4<u32>>;
@group(1) @binding(5) var<storage, read> veg_counts: array<u32>;
@group(1) @binding(6) var<storage, read> pixel_params: array<vec4<f32>>;       // mode VoxelPixel (L23p), 2 vec4 par classe

fn linear_to_srgb(c: vec3<f32>) -> vec3<f32> {
  let x = clamp(c, vec3<f32>(0.0), vec3<f32>(1.0));
  let lo = x * 12.92;
  let hi = 1.055 * pow(x, vec3<f32>(1.0 / 2.4)) - vec3<f32>(0.055);
  return select(hi, lo, x <= vec3<f32>(0.0031308));
}

// Normale de face : axe (face >> 1), signe (face & 1).
fn face_normal(face: u32) -> vec3<f32> {
  var n = vec3<f32>(0.0);
  let s = select(-1.0, 1.0, (face & 1u) == 1u);
  let ax = face >> 1u;
  if (ax == 0u) { n.x = s; } else if (ax == 1u) { n.y = s; } else { n.z = s; }
  return n;
}

fn oct_encode(n: vec3<f32>) -> u32 {
  let p = n.xy / (abs(n.x) + abs(n.y) + abs(n.z));
  var e = p;
  if (n.z < 0.0) {
    e = (vec2<f32>(1.0) - abs(p.yx)) * select(vec2<f32>(-1.0), vec2<f32>(1.0), p >= vec2<f32>(0.0));
  }
  return pack2x16unorm(e * 0.5 + vec2<f32>(0.5));
}

@compute @workgroup_size(8, 8, 1)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
  if (f32(gid.x) >= VF.screen.x || f32(gid.y) >= VF.screen.y) { return; }
  let px = vec2<i32>(gid.xy);
  let rec = textureLoad(in_hit, px, 0);
  if ((rec.x & (1u << 20u)) == 0u) {
    textureStore(out_gb0, px, vec4<f32>(0.0));
    textureStore(out_gb1, px, vec4<u32>(0u));
    textureStore(out_gb2, px, vec4<f32>(0.0));
    return;
  }
  let value = rec.x & 0xFFFFu;
  let face = (rec.x >> 16u) & 7u;
  let voxel = vec3<i32>(bitcast<i32>(rec.y), bitcast<i32>(rec.z), bitcast<i32>(rec.w));
  let albedo = eval_voxel_albedo(value, voxel, 0u);
  let m = materials[voxel_class(value)];
  var flags = 8.0;                                   // drapeau « voxel »
  if ((m.flags & FLAG_FOLIAGE) != 0u) { flags += 1.0; }
  textureStore(out_gb0, px, vec4<f32>(linear_to_srgb(albedo), 1.0));
  textureStore(out_gb1, px, vec4<u32>(oct_encode(face_normal(face)), 0u, 0u, 0u));
  textureStore(out_gb2, px, vec4<f32>(m.roughness, m.translucency, log2(1.0 + m.emission) * 0.25, flags / 255.0));
}
