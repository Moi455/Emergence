// Cave network (monde_horizon § 2): built once from the seed as a list of
// capsules (galleries) and spheres (chambers) with an index, so that any
// chunk knows at once whether a cave crosses it. Systems are likelier in
// limestone (karst), rarer in granite; some open on the surface.
#include <algorithm>

#include "internal.h"

namespace em::wg {

namespace {

constexpr int64_t kSystemCell = 400 * M;
constexpr int64_t kBottomLimit = -470 * M;
constexpr int64_t kRoofCover = 8 * M;       // rock kept above galleries
constexpr int64_t kWaterCover = 25 * M;     // under the sea, lakes and rivers
constexpr int64_t kPadCover = 30 * M;       // under villages


struct Vec {
  int64_t x, y, z;
};

Vec normalize(Vec d) {
  int64_t len = static_cast<int64_t>(isqrt64(static_cast<uint64_t>(d.x * d.x + d.y * d.y + d.z * d.z)));
  if (len == 0) return {kOne, 0, 0};
  return {(d.x * kOne) / len, (d.y * kOne) / len, (d.z * kOne) / len};
}

}  // namespace

void WorldGen::Impl::build_caves() {
  const uint64_t s = fine_seed(seed, FineLayer::Cave);
  const int64_t nsys = (map_mm + kSystemCell - 1) / kSystemCell;
  const int64_t margin = std::min<int64_t>(60 * M, map_mm / 10);
  auto water_cell = [&](int64_t x, int64_t z) {
    return (p.flags[cell_at(x, z)] & (kFlagSea | kFlagLake | kFlagRiver)) != 0;
  };
  auto near_pad = [&](int64_t x, int64_t z, int64_t extra) {
    for (const auto& pad : pads) {
      int64_t dx = x - pad.x_mm, dz = z - pad.z_mm, r = pad.radius_mm + extra;
      if (dx * dx + dz * dz < r * r) return true;
    }
    return false;
  };

  uint32_t system = 0;
  for (int64_t cj = 0; cj < nsys; ++cj)
    for (int64_t ci = 0; ci < nsys; ++ci) {
      uint64_t h = hash2(s, ci, cj);
      int64_t x = ci * kSystemCell + range(rehash(h, 1), 40 * M, kSystemCell - 40 * M);
      int64_t z = cj * kSystemCell + range(rehash(h, 2), 40 * M, kSystemCell - 40 * M);
      if (x < margin || z < margin || x >= map_mm - margin || z >= map_mm - margin) continue;
      if (water_cell(x, z)) continue;
      static constexpr int kProb[] = {65, 35, 25, 30, 30};  // by RockType
      if (pick(h, 100) >= kProb[p.rock[cell_at(x, z)]]) continue;
      int64_t ground = plan_cubic(x, z);
      Vec start{x, std::max(ground - range(rehash(h, 3), 15 * M, 150 * M), kBottomLimit), z};
      int worms = 1 + static_cast<int>(pick(rehash(h, 4), 3));
      int entrance_worm = (pick(rehash(h, 5), 100) < 45 && !near_pad(x, z, 80 * M)) ? 0 : -1;
      ++cave_stats.systems;
      for (int w = 0; w < worms; ++w) {
        uint64_t hw = rehash(h, 100 + static_cast<uint64_t>(w));
        Vec pos = start;
        Vec dir = normalize({unit_q16(rehash(hw, 1)), unit_q16(rehash(hw, 2)) / 4, unit_q16(rehash(hw, 3))});
        int steps = static_cast<int>(range(rehash(hw, 4), 15, 60));
        int64_t r = range(rehash(hw, 5), 1200, 3500);
        bool entrance = false;
        for (int st = 0; st < steps; ++st) {
          uint64_t hs = rehash(hw, 1000 + static_cast<uint64_t>(st));
          if (w == entrance_worm && st >= steps / 3) entrance = true;
          int64_t len = range(rehash(hs, 1), 5 * M, 12 * M);
          Vec d{dir.x * 3 + unit_q16(rehash(hs, 2)), dir.y * 3 + unit_q16(rehash(hs, 3)) / 2, dir.z * 3 + unit_q16(rehash(hs, 4))};
          if (entrance) d.y = std::max<int64_t>(d.y, 0) + kOne * 2;
          dir = normalize(d);
          Vec next{pos.x + ((dir.x * len) >> 16), pos.y + ((dir.y * len) >> 16), pos.z + ((dir.z * len) >> 16)};
          if (next.x < margin || next.x >= map_mm - margin) { dir.x = -dir.x; next.x = std::clamp(next.x, margin, map_mm - margin - 1); }
          if (next.z < margin || next.z >= map_mm - margin) { dir.z = -dir.z; next.z = std::clamp(next.z, margin, map_mm - margin - 1); }
          int64_t g = plan_cubic(next.x, next.z);
          if (entrance && (water_cell(next.x, next.z) || near_pad(next.x, next.z, 20 * M))) entrance = false, entrance_worm = -1;
          if (!entrance) {
            int64_t cover = kRoofCover;
            if (water_cell(next.x, next.z)) cover = kWaterCover;
            if (near_pad(next.x, next.z, 30 * M)) cover = std::max(cover, kPadCover);
            if (next.y > g - cover - r) {
              next.y = g - cover - r;
              dir.y = -abs64(dir.y);
            }
          }
          if (next.y < kBottomLimit) {
            next.y = kBottomLimit;
            dir.y = abs64(dir.y);
          }
          int64_t r_next = std::clamp<int64_t>(r + range(rehash(hs, 5), -600, 600), 900, 4000);
          caves.push_back({pos.x, pos.y, pos.z, next.x, next.y, next.z, static_cast<int32_t>(r), static_cast<int32_t>(r_next), system});
          if (entrance && next.y > g + 2 * M) {
            ++cave_stats.entrances;
            break;
          }
          if (!entrance && pick(rehash(hs, 6), 100) < 7) {
            int64_t rc = range(rehash(hs, 7), 5 * M, 14 * M);
            int64_t cover = water_cell(next.x, next.z) ? kWaterCover : kRoofCover;
            int64_t cy = std::max(std::min(next.y, g - cover - rc), kBottomLimit + rc);
            int64_t half = (rc * range(rehash(hs, 8), 30, 90)) / 100;
            caves.push_back({next.x - ((dir.x * half) >> 16), cy, next.z - ((dir.z * half) >> 16),
                             next.x + ((dir.x * half) >> 16), cy, next.z + ((dir.z * half) >> 16),
                             static_cast<int32_t>(rc), static_cast<int32_t>((rc * 8) / 10), system});
            ++cave_stats.chambers;
          }
          pos = next;
          r = r_next;
        }
      }
      ++system;
    }
  cave_stats.segments = caves.size();

  std::vector<std::array<int64_t, 4>> boxes;
  boxes.reserve(caves.size());
  for (const auto& c : caves) {
    int64_t e = (std::max(c.ra, c.rb) * 13) / 10;
    boxes.push_back({std::min(c.ax, c.bx) - e, std::min(c.az, c.bz) - e, std::max(c.ax, c.bx) + e, std::max(c.az, c.bz) + e});
  }
  cave_index.build(map_mm, 64 * M, boxes);
}

namespace {
bool seg_touches(const CaveSegment& c, int64_t x0, int64_t y0, int64_t z0, int64_t x1, int64_t y1, int64_t z1) {
  int64_t e = (std::max(c.ra, c.rb) * 13) / 10;
  return std::min(c.ax, c.bx) - e < x1 && std::max(c.ax, c.bx) + e > x0 && std::min(c.ay, c.by) - e < y1 &&
         std::max(c.ay, c.by) + e > y0 && std::min(c.az, c.bz) - e < z1 && std::max(c.az, c.bz) + e > z0;
}
}  // namespace

bool WorldGen::Impl::caves_touch(int64_t x0, int64_t y0, int64_t z0, int64_t x1, int64_t y1, int64_t z1) const {
  std::vector<uint32_t> ids;
  cave_index.query(x0, z0, x1, z1, &ids);
  for (uint32_t id : ids)
    if (seg_touches(caves[id], x0, y0, z0, x1, y1, z1)) return true;
  return false;
}

void WorldGen::Impl::carve_caves(const ChunkBox& b, VoxelId* out) const {
  const int64_t x1 = b.ox + b.size, y1 = b.oy + b.size, z1 = b.oz + b.size;
  std::vector<uint32_t> ids;
  cave_index.query(b.ox, b.oz, x1, z1, &ids);
  Lattice3 noise;
  for (uint32_t id : ids) {
    const CaveSegment& c = caves[id];
    if (!seg_touches(c, b.ox, b.oy, b.oz, x1, y1, z1)) continue;
    if (noise.empty() && b.v <= 160) noise.build(fine_seed(seed, FineLayer::Cave), 10, b.ox, b.oy, b.oz, x1, y1, z1);
    RasterStyle st;
    st.voxel = kAir;
    st.replace = kRepSoil | kRepRock | kRepWood;
    st.noise = noise.empty() ? nullptr : &noise;
    st.noise_q16 = kOne / 4;
    raster_capsule(*this, b, {c.ax, c.ay, c.az, c.bx, c.by, c.bz, c.ra, c.rb}, st, out);
  }
}

}  // namespace em::wg
