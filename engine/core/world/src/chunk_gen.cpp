#include "emergence/world/chunk_gen.h"

#include <algorithm>

#include "emergence/base/fixed.h"
#include "emergence/base/hash.h"
#include "emergence/base/noise.h"

namespace em {

namespace {

// The column profile is sampled every kNode voxels (8 cm) and interpolated:
// the finest detail noise has a 1.6 m wavelength, so 8 cm is ample, and the
// shader adds sub-brick micro-detail (architecture § 3.2).
constexpr int kNode = 4;
constexpr int kNodes = kChunkSize / kNode + 1;  // 17
constexpr int64_t kDeepRockMm = 40'000;          // granite basement 40 m below the surface

struct BiomeLayers {
  const char* top;
  const char* sub;
  int32_t top_mm;
  int32_t detail_mm;
};

// Indexed by Biome.
constexpr BiomeLayers kLayers[] = {
    {"sand", "gravel", 300, 300},        // Ocean
    {"sand", "sand", 0, 120},            // Beach
    {"dirt", "clay", 200, 150},          // Marsh
    {"turf", "dirt", 200, 250},          // Meadow
    {"forest_floor", "dirt", 150, 300},  // Woodland
    {"forest_floor", "clay", 250, 350},  // DeepForest
    {"dirt", "dirt", 100, 250},          // Steppe
    {"sand", "sand", 0, 500},            // Desert
    {"turf", "gravel", 120, 700},        // Foothills
    {"turf", "gravel", 100, 600},        // Alpine
    {"gravel", "gravel", 0, 1500},       // Rock
    {"snow", "gravel", 800, 400},        // Snow
    {"clay", "dirt", 300, 200},          // LakeBed
};
static_assert(sizeof(kLayers) / sizeof(kLayers[0]) == static_cast<size_t>(Biome::kCount));

}  // namespace

struct ChunkGenerator::Node {
  int64_t h_mm;
  int32_t top_mm, soil_mm;
  VoxelId top, sub, rock;
};

ChunkGenerator::ChunkGenerator(const WorldPlan& plan, const MaterialTable& m)
    : plan_(plan),
      map_voxels_(int64_t{plan.params.size_m} * 1000 / kVoxelMm),
      detail_seed_(layer_seed(plan.params.seed, Layer::Detail)),
      jitter_seed_(hash_combine(layer_seed(plan.params.seed, Layer::Detail), 1)) {
  deep_rock_ = make_voxel(m.require("granite"));
  for (int r = 0; r < static_cast<int>(RockType::kCount); ++r)
    rock_[r] = make_voxel(m.require(rock_material_name(static_cast<RockType>(r))));
  for (int b = 0; b < static_cast<int>(Biome::kCount); ++b) {
    top_[b] = make_voxel(m.require(kLayers[b].top));
    sub_[b] = make_voxel(m.require(kLayers[b].sub));
    top_mm_[b] = kLayers[b].top_mm;
    detail_mm_[b] = kLayers[b].detail_mm;
  }
}

int64_t ChunkGenerator::detail_amplitude_mm(int64_t x, int64_t z) const {
  // Bilinear over the four plan cells so the amplitude is continuous across
  // biome borders (no seams).
  const int64_t cm = plan_.cell_mm, max_mm = (plan_.n - 1) * cm;
  x = clamp64(x, 0, max_mm);
  z = clamp64(z, 0, max_mm);
  int32_t i = static_cast<int32_t>(x / cm), j = static_cast<int32_t>(z / cm);
  int32_t i1 = std::min(i + 1, plan_.n - 1), j1 = std::min(j + 1, plan_.n - 1);
  int64_t fx = ((x - i * cm) * kOne) / cm, fz = ((z - j * cm) * kOne) / cm;
  auto A = [&](int32_t a, int32_t b) { return int64_t{detail_mm_[plan_.biome[plan_.idx(a, b)]]}; };
  return qlerp(qlerp(A(i, j), A(i1, j), fx), qlerp(A(i, j1), A(i1, j1), fx), fz);
}

void ChunkGenerator::sample_node(int64_t vx, int64_t vz, Node& n) const {
  const int64_t x = vx * kVoxelMm, z = vz * kVoxelMm;
  int64_t amp = detail_amplitude_mm(x, z);
  int64_t d1 = fbm2(detail_seed_, to_noise(x, 8000), to_noise(z, 8000), 2);
  int64_t d2 = fbm2(hash_combine(detail_seed_, 2), to_noise(x, 1600), to_noise(z, 1600), 2);
  n.h_mm = plan_.height_at_mm(x, z) + ((d1 * amp) >> 16) + ((d2 * amp / 5) >> 16);

  // Materials: nearest plan cell after a jitter of up to ~8 m, so biome and
  // rock borders are ragged instead of 16 m squares.
  int64_t jx = (fbm2(jitter_seed_, to_noise(x, 12000), to_noise(z, 12000), 2) * 9000) >> 16;
  int64_t jz = (fbm2(hash_combine(jitter_seed_, 1), to_noise(x, 12000), to_noise(z, 12000), 2) * 9000) >> 16;
  const int64_t cm = plan_.cell_mm;
  int32_t i = static_cast<int32_t>(clamp64(floor_div(x + jx + cm / 2, cm), 0, plan_.n - 1));
  int32_t j = static_cast<int32_t>(clamp64(floor_div(z + jz + cm / 2, cm), 0, plan_.n - 1));
  size_t c = plan_.idx(i, j);
  int b = plan_.biome[c];
  n.top = top_[b];
  n.sub = sub_[b];
  n.top_mm = top_mm_[b];
  n.soil_mm = plan_.soil_mm[c];
  n.rock = rock_[plan_.rock[c]];
}

int32_t ChunkGenerator::surface_voxel_y(int64_t vx, int64_t vz) const {
  int64_t nx = floor_div(vx, kNode) * kNode, nz = floor_div(vz, kNode) * kNode;
  int64_t fx = vx - nx, fz = vz - nz;
  Node a, b, c, d;
  sample_node(nx, nz, a);
  sample_node(nx + kNode, nz, b);
  sample_node(nx, nz + kNode, c);
  sample_node(nx + kNode, nz + kNode, d);
  int64_t h = a.h_mm * (kNode - fx) * (kNode - fz) + b.h_mm * fx * (kNode - fz) + c.h_mm * (kNode - fx) * fz +
              d.h_mm * fx * fz;
  return static_cast<int32_t>(floor_div(h, int64_t{kNode} * kNode * kVoxelMm));
}

ChunkGenerator::Kind ChunkGenerator::classify(ChunkCoord cc, VoxelId* solid_value) const {
  const int64_t cm = plan_.cell_mm;
  const int64_t x0 = int64_t{cc.x} * kChunkSize * kVoxelMm, z0 = int64_t{cc.z} * kChunkSize * kVoxelMm;
  const int64_t ext = kChunkSize * kVoxelMm;
  // Heights: the cells used by bilinear interpolation. Materials: one more
  // cell around, for the jitter of up to 9 m.
  const int32_t last = plan_.n - 1;
  int32_t hi0 = static_cast<int32_t>(clamp64(floor_div(x0, cm), 0, last));
  int32_t hi1 = static_cast<int32_t>(clamp64(floor_div(x0 + ext, cm) + 1, 0, last));
  int32_t hj0 = static_cast<int32_t>(clamp64(floor_div(z0, cm), 0, last));
  int32_t hj1 = static_cast<int32_t>(clamp64(floor_div(z0 + ext, cm) + 1, 0, last));
  int64_t hmin = INT64_MAX, hmax = INT64_MIN, amp = 0, soil = 0;
  for (int32_t j = hj0; j <= hj1; ++j)
    for (int32_t i = hi0; i <= hi1; ++i) {
      size_t c = plan_.idx(i, j);
      hmin = std::min<int64_t>(hmin, plan_.height_mm[c]);
      hmax = std::max<int64_t>(hmax, plan_.height_mm[c]);
      amp = std::max<int64_t>(amp, detail_mm_[plan_.biome[c]]);
    }
  uint8_t rock = plan_.rock[plan_.idx(hi0, hj0)];
  bool same_rock = true;
  for (int32_t j = std::max(hj0 - 1, 0); j <= std::min(hj1 + 1, last); ++j)
    for (int32_t i = std::max(hi0 - 1, 0); i <= std::min(hi1 + 1, last); ++i) {
      size_t c = plan_.idx(i, j);
      soil = std::max<int64_t>(soil, std::max<int64_t>(plan_.soil_mm[c], top_mm_[plan_.biome[c]]));
      same_rock = same_rock && plan_.rock[c] == rock;
    }
  const int64_t margin = 2 * amp + 2 * kVoxelMm;
  const int64_t y0 = int64_t{cc.y} * kChunkSize * kVoxelMm, y1 = y0 + ext;
  if (y0 >= hmax + margin) return Kind::Air;
  if (y1 <= hmin - margin - kDeepRockMm) {
    if (solid_value) *solid_value = deep_rock_;
    return Kind::Solid;
  }
  if (same_rock && y1 <= hmin - margin - soil && y0 >= hmax + margin - kDeepRockMm) {
    if (solid_value) *solid_value = rock_[rock];
    return Kind::Solid;
  }
  return Kind::Mixed;
}

void ChunkGenerator::generate(ChunkCoord cc, Chunk& out) const {
  out.clear();
  out.coord = cc;
  const int64_t vx0 = int64_t{cc.x} * kChunkSize, vz0 = int64_t{cc.z} * kChunkSize;
  const int64_t vy0 = int64_t{cc.y} * kChunkSize;

  Node nodes[kNodes * kNodes];
  for (int k = 0; k < kNodes; ++k)
    for (int q = 0; q < kNodes; ++q) sample_node(vx0 + q * kNode, vz0 + k * kNode, nodes[k * kNodes + q]);

  // Per column layer boundaries (chunk-local voxel y): a voxel at y is deep
  // rock below b[0], bedrock below b[1], sub-soil below b[2], top layer below
  // b[3], air above.
  struct Column {
    int32_t b[4];
    VoxelId mat[5];
  };
  static thread_local Column cols[kChunkSize * kChunkSize];
  const int64_t div = int64_t{kNode} * kNode;
  for (int z = 0; z < kChunkSize; ++z) {
    const int k = z / kNode, fz = z % kNode;
    for (int x = 0; x < kChunkSize; ++x) {
      const int q = x / kNode, fx = x % kNode;
      const Node& a = nodes[k * kNodes + q];
      const Node& b = nodes[k * kNodes + q + 1];
      const Node& c = nodes[(k + 1) * kNodes + q];
      const Node& d = nodes[(k + 1) * kNodes + q + 1];
      int64_t h = a.h_mm * (kNode - fx) * (kNode - fz) + b.h_mm * fx * (kNode - fz) +
                  c.h_mm * (kNode - fx) * fz + d.h_mm * fx * fz;
      int64_t h_mm = floor_div(h, div);
      int64_t s = floor_div(h, div * kVoxelMm) - vy0;
      const Node& m = nodes[(k + (fz >= kNode / 2)) * kNodes + q + (fx >= kNode / 2)];
      int64_t soil = std::max<int64_t>(m.soil_mm, m.top_mm);
      auto clampy = [](int64_t v) { return static_cast<int32_t>(clamp64(v, -1, kChunkSize + 1)); };
      Column& col = cols[z * kChunkSize + x];
      col.b[3] = clampy(s);
      col.b[2] = std::min(col.b[3], clampy(floor_div(h_mm - m.top_mm, kVoxelMm) - vy0));
      col.b[1] = std::min(col.b[2], clampy(floor_div(h_mm - soil, kVoxelMm) - vy0));
      col.b[0] = std::min(col.b[1], clampy(floor_div(h_mm - kDeepRockMm, kVoxelMm) - vy0));
      col.mat[0] = deep_rock_;
      col.mat[1] = m.rock;
      col.mat[2] = m.sub;
      col.mat[3] = m.top;
      col.mat[4] = kAir;
    }
  }
  auto layer = [](const Column& col, int y) {
    int l = 0;
    while (l < 4 && y >= col.b[l]) ++l;
    return l;
  };

  VoxelId buf[kVoxelsPerBrick];
  for (int by = 0; by < kBricksPerChunk; ++by)
    for (int bz = 0; bz < kBricksPerChunk; ++bz)
      for (int bx = 0; bx < kBricksPerChunk; ++bx) {
        const int y0 = by * kBrickSize;
        // Uniform if every column stays in one layer of the same material.
        VoxelId first = kAir;
        bool uniform = true;
        for (int z = 0; z < kBrickSize && uniform; ++z)
          for (int x = 0; x < kBrickSize; ++x) {
            const Column& col = cols[(bz * kBrickSize + z) * kChunkSize + bx * kBrickSize + x];
            int la = layer(col, y0);
            if (la != layer(col, y0 + kBrickSize - 1)) {
              uniform = false;
              break;
            }
            VoxelId v = col.mat[la];
            if ((z | x) == 0) first = v;
            else if (v != first) {
              uniform = false;
              break;
            }
          }
        const int b = brick_index(bx, by, bz);
        if (uniform) {
          out.set_brick_uniform(b, first);
          continue;
        }
        for (int y = 0; y < kBrickSize; ++y)
          for (int z = 0; z < kBrickSize; ++z)
            for (int x = 0; x < kBrickSize; ++x) {
              const Column& col = cols[(bz * kBrickSize + z) * kChunkSize + bx * kBrickSize + x];
              buf[in_brick_index(x, y, z)] = col.mat[layer(col, y0 + y)];
            }
        out.set_brick(b, buf);
      }
}

}  // namespace em
