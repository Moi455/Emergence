// Columns (top layer, soil, bedrock strata, basement) and the geological
// bodies laid over them: iron ore, salt lenses, clay lenses.
#include <vector>

#include "internal.h"

namespace em::wg {

namespace {

constexpr int64_t kBandMm = 2500;  // sedimentary band thickness

struct ColumnStack {
  int64_t g;            // ground
  int64_t top_end;      // bottom of the top layer
  int64_t soil1_end;    // bottom of the first soil layer
  int64_t soil2_end;    // bottom of the second soil layer (bedrock below)
  int64_t basement;     // crystalline basement below this height
  int64_t tilt;         // strata offset
  VoxelId top, soil1, soil2, rock, alt, base_rock;
};

}  // namespace

void WorldGen::Impl::fill_columns(const ChunkBox& b, VoxelId* out) const {
  const int64_t v = b.v, G = kGridStride * v;
  std::vector<uint32_t> ids;
  roads_near(b.ox - G, b.oz - G, b.ox + b.size + G, b.oz + b.size + G, &ids);

  // Coarse surface grid with one point of border for slopes.
  GridSample grid[kGridN][kGridN];
  for (int gj = 0; gj < kGridN; ++gj)
    for (int gi = 0; gi < kGridN; ++gi)
      grid[gj][gi] = grid_sample(b.ox + (gi - 1) * G, b.oz + (gj - 1) * G, b.lod, ids);
  int32_t slope[kGridN][kGridN] = {};
  for (int gj = 1; gj < kGridN - 1; ++gj)
    for (int gi = 1; gi < kGridN - 1; ++gi) {
      int64_t dx = (grid[gj][gi + 1].h - grid[gj][gi - 1].h) * 1000 / (2 * G);
      int64_t dz = (grid[gj + 1][gi].h - grid[gj - 1][gi].h) * 1000 / (2 * G);
      slope[gj][gi] = static_cast<int32_t>(isqrt64(static_cast<uint64_t>(dx * dx + dz * dz)));
    }

  const uint64_t jseed = fine_seed(seed, FineLayer::Jitter);
  const uint64_t sseed = fine_seed(seed, FineLayer::Strata);
  const uint64_t bseed = fine_seed(seed, FineLayer::Basement);
  const uint64_t snseed = fine_seed(seed, FineLayer::Snow);
  const int64_t top_y = b.oy + b.size;
  // Columns are filled in a column-major scratch buffer (contiguous runs),
  // then transposed into the chunk layout (x fastest, then z, then y).
  thread_local std::vector<VoxelId> scratch(kChunkVoxels);
  VoxelId* tmp = scratch.data();
  int64_t slow[2][4];
  for (int k = 0; k < 4; ++k) {
    int64_t xk = b.ox + (k & 1) * b.size, zk = b.oz + (k >> 1) * b.size;
    slow[0][k] = -250 * M + ((fbm2(bseed, to_noise(xk, 2000 * M), to_noise(zk, 2000 * M), 2) * 60 * M) >> 16);
    slow[1][k] = (fbm2(sseed, to_noise(xk, 600 * M), to_noise(zk, 600 * M), 2) * 40 * M) >> 16;
  }

  for (int z = 0; z < kChunkSize; ++z) {
    const int64_t zc = b.c(b.oz, z);
    const int gj = z / kGridStride + 1;
    const int64_t fz = ((zc - (b.oz + (gj - 1) * G)) * kOne) / G;
    for (int x = 0; x < kChunkSize; ++x) {
      const int64_t xc = b.c(b.ox, x);
      const int gi = x / kGridStride + 1;
      const int64_t fx = ((xc - (b.ox + (gi - 1) * G)) * kOne) / G;
      const GridSample &s00 = grid[gj][gi], &s10 = grid[gj][gi + 1], &s01 = grid[gj + 1][gi], &s11 = grid[gj + 1][gi + 1];
      int64_t h = qlerp(qlerp(s00.h, s10.h, fx), qlerp(s01.h, s11.h, fx), fz);
      int64_t amp = qlerp(qlerp(s00.fine_amp, s10.fine_amp, fx), qlerp(s01.fine_amp, s11.fine_amp, fx), fz);
      ColumnStack c;
      VoxelId* col = tmp + (z * kChunkSize + x) * kChunkSize;  // column-major scratch
      constexpr int kStrideY = 1;
      // Fine octaves add at most amp / 8: skip them for columns surely in the air.
      c.g = h + amp / 4 <= b.oy ? b.oy : h + fine_detail(xc, zc, static_cast<int32_t>(amp), b.lod);
      if (c.g <= b.oy) {  // whole column is air
        for (int y = 0; y < kChunkSize; ++y) col[y * kStrideY] = kAir;
        continue;
      }
      int64_t sl = qlerp(qlerp(slope[gj][gi], slope[gj][gi + 1], fx), qlerp(slope[gj + 1][gi], slope[gj + 1][gi + 1], fx), fz);
      int64_t road = qlerp(qlerp(s00.road_q16, s10.road_q16, fx), qlerp(s01.road_q16, s11.road_q16, fx), fz);

      // Material cell: one of the four grid corners, dithered by the weights.
      uint64_t dh = hash2(jseed, floor_div(xc, 4 * v), floor_div(zc, 4 * v));
      bool pick_x = static_cast<int64_t>(dh & 0xFFFF) < fx;
      bool pick_z = static_cast<int64_t>((dh >> 16) & 0xFFFF) < fz;
      const GridSample& sc = pick_z ? (pick_x ? s11 : s01) : (pick_x ? s10 : s00);
      const size_t cell = sc.cell;
      const Biome biome = static_cast<Biome>(p.biome[cell]);
      const RockType rt = static_cast<RockType>(p.rock[cell]);
      const uint8_t flags = p.flags[cell];
      const int32_t water = p.water_mm[cell];
      const bool wet = water != WorldPlan::kNoWater && water > c.g;

      int64_t soil = (int64_t{p.soil_mm[cell]} * (kOne - qramp(450, 1100, sl))) >> 16;
      int64_t top_t = 0, s1 = soil, s2 = 0;
      c.top = m.turf;
      c.soil1 = m.dirt;
      c.soil2 = m.gravel;
      if (road > kOne / 2) {
        c.top = m.gravel; top_t = 150; s1 = std::max<int64_t>(soil, 300);
      } else if (road > kOne * 15 / 100) {
        c.top = m.dirt; top_t = 100;
      } else if (wet) {
        if (flags & kFlagRiver) { c.top = m.gravel; top_t = 300; c.soil1 = m.sand; }
        else if (biome == Biome::LakeBed || (flags & kFlagLake)) { c.top = m.clay; top_t = 300; c.soil1 = m.sand; }
        else if (biome == Biome::Marsh) { c.top = m.clay; top_t = 200; c.soil1 = m.clay; }
        else { c.top = m.sand; top_t = 400; c.soil1 = m.sand; }
      } else {
        switch (biome) {
          case Biome::Snow: {
            int64_t n = gradient_noise2(snseed, to_noise(xc, 6 * M), to_noise(zc, 6 * M));
            top_t = 600 + ((n * 500) >> 16);
            top_t -= (top_t * qramp(700, 1300, sl)) >> 16;
            c.top = m.snow; c.soil1 = m.gravel; s1 = soil / 2;
            break;
          }
          case Biome::Rock: s1 = 0; break;
          case Biome::Beach: c.top = m.sand; c.soil1 = m.sand; s1 = std::max<int64_t>(soil, 1500); break;
          case Biome::Desert: c.top = m.sand; c.soil1 = m.sand; s1 = std::max<int64_t>(soil, 2500); break;
          case Biome::Ocean: c.top = m.sand; c.soil1 = m.sand; break;
          case Biome::LakeBed: c.top = m.clay; top_t = 200; break;
          case Biome::Steppe: c.top = (dh >> 40) & 1 ? m.turf : m.dirt; top_t = 30; break;
          case Biome::DeepForest: c.top = m.forest_floor; top_t = 80; break;
          case Biome::Woodland: c.top = (dh >> 41) % 3 ? m.forest_floor : m.turf; top_t = 50; break;
          case Biome::Marsh: c.top = m.turf; top_t = 40; c.soil1 = m.clay; break;
          case Biome::Foothills:
          case Biome::Alpine: top_t = 30; s2 = (soil * 4) / 10; s1 = soil - s2; break;
          default: top_t = 40; break;  // meadow
        }
        if (sl > 1000 && biome != Biome::Snow) { top_t = 0; s1 = 0; s2 = 0; }
      }
      if (top_t > 0) top_t = std::max(top_t, v);  // keep the surface colour at every level of detail
      c.top_end = c.g - top_t;
      c.soil1_end = c.top_end - s1;
      c.soil2_end = c.soil1_end - s2;

      c.rock = m.rock[static_cast<size_t>(rt)];
      switch (rt) {
        case RockType::Limestone: c.alt = m.sandstone; break;
        case RockType::Sandstone: c.alt = m.limestone; break;
        case RockType::Slate: c.alt = m.limestone; break;
        default: c.alt = c.rock; break;
      }
      c.base_rock = rt == RockType::Basalt ? m.basalt : m.granite;
      // Basement and strata tilt vary over kilometres: bilinear from the chunk corners.
      const int64_t ux = ((xc - b.ox) * kOne) / b.size, uz = ((zc - b.oz) * kOne) / b.size;
      c.basement = qlerp(qlerp(slow[0][0], slow[0][1], ux), qlerp(slow[0][2], slow[0][3], ux), uz);
      c.tilt = qlerp(qlerp(slow[1][0], slow[1][1], ux), qlerp(slow[1][2], slow[1][3], ux), uz);

      // Runs, top down: air, top layer, soil, subsoil, strata, basement.
      auto first_at_or_above = [&](int64_t hmm) {  // first voxel whose centre is >= hmm
        return static_cast<int>(clamp64(floor_div(hmm - b.oy - v / 2 + v - 1, v), 0, kChunkSize));
      };
      auto fill = [&](int y0, int y1, VoxelId vv) {
        for (int y = y0; y < y1; ++y) col[y * kStrideY] = vv;
      };
      const int i_g = first_at_or_above(c.g), i_top = first_at_or_above(c.top_end);
      const int i_s1 = first_at_or_above(c.soil1_end), i_s2 = first_at_or_above(c.soil2_end);
      const int i_base = std::min(first_at_or_above(c.basement), i_s2);
      fill(i_g, kChunkSize, kAir);
      fill(i_top, i_g, c.top);
      fill(i_s1, i_top, c.soil1);
      fill(i_s2, i_s1, c.soil2);
      fill(0, i_base, c.base_rock);
      if (c.alt == c.rock) {
        fill(i_base, i_s2, c.rock);
      } else {
        for (int y = i_base; y < i_s2;) {
          int64_t band = floor_div(b.oy + y * v + v / 2 + c.tilt, kBandMm);
          int next = std::min(first_at_or_above((band + 1) * kBandMm - c.tilt), i_s2);
          fill(y, next, (hash_combine(sseed, static_cast<uint64_t>(band)) % 100) < 30 ? c.alt : c.rock);
          y = std::max(next, y + 1);
        }
      }
      (void)top_y;
    }
  }
  for (int z = 0; z < kChunkSize; ++z)
    for (int y = 0; y < kChunkSize; ++y) {
      VoxelId* row = out + voxel_index(0, y, z);
      const VoxelId* src = tmp + z * kChunkSize * kChunkSize + y;
      for (int x = 0; x < kChunkSize; ++x) row[x] = src[x * kChunkSize];
    }
}

void WorldGen::Impl::overlay_geology(const ChunkBox& b, VoxelId* out) const {
  const int64_t x1 = b.ox + b.size, y1 = b.oy + b.size, z1 = b.oz + b.size;
  Lattice3 noise;
  auto lattice = [&]() -> const Lattice3* {
    if (b.v > 128) return nullptr;
    if (noise.empty()) noise.build(fine_seed(seed, FineLayer::Ore), 9, b.ox, b.oy, b.oz, x1, y1, z1);
    return &noise;
  };

  // Iron ore: blobs on a 24 m 3D lattice, inside rock only.
  {
    constexpr int64_t C = 24 * M, R = 8 * M;
    const uint64_t s = fine_seed(seed, FineLayer::Ore);
    for (int64_t cy = floor_div(b.oy - R + kYBias, C); cy <= floor_div(y1 + R + kYBias, C); ++cy)
      for (int64_t cz = floor_div(b.oz - R, C); cz <= floor_div(z1 + R, C); ++cz)
        for (int64_t cx = floor_div(b.ox - R, C); cx <= floor_div(x1 + R, C); ++cx) {
          uint64_t h = hash3(s, cx, cy, cz);
          int64_t ex = cx * C + range(rehash(h, 1), 3 * M, C - 3 * M);
          int64_t ey = cy * C - kYBias + range(rehash(h, 2), 3 * M, C - 3 * M);
          int64_t ez = cz * C + range(rehash(h, 3), 3 * M, C - 3 * M);
          if (ex < 0 || ez < 0 || ex >= map_mm || ez >= map_mm) continue;
          uint32_t cell = cell_at(ex, ez);
          RockType rt = static_cast<RockType>(p.rock[cell]);
          int64_t per_mille = (rt == RockType::Granite || rt == RockType::Slate || rt == RockType::Basalt) ? 30 : 8;
          if (p.march_side[cell] == static_cast<uint8_t>(Side::North)) per_mille *= 3;
          if (pick(h, 1000) >= per_mille) continue;
          if (ey > plan_cubic(ex, ez) - 4 * M) continue;
          int64_t r = range(rehash(h, 4), 1500, 5000);
          Ellipsoid e{ex, ey, ez, r, (r * range(rehash(h, 5), 40, 100)) / 100, (r * range(rehash(h, 6), 60, 140)) / 100};
          RasterStyle st;
          st.voxel = m.iron_ore;
          st.replace = kRepRock;
          st.noise = lattice();
          st.noise_q16 = kOne * 35 / 100;
          raster_ellipsoid(*this, b, e, st, out);
        }
  }

  // Salt (desert march and coastal flats) and clay (lowland soils): flat lenses
  // under the ground on 2D lattices.
  struct LensKind {
    FineLayer layer;
    int64_t cell, max_r;
  };
  const LensKind kinds[2] = {{FineLayer::Salt, 32 * M, 15 * M}, {FineLayer::Clay, 20 * M, 8 * M}};
  for (int k = 0; k < 2; ++k) {
    const LensKind& lk = kinds[k];
    const uint64_t s = fine_seed(seed, lk.layer);
    for (int64_t cz = floor_div(b.oz - lk.max_r, lk.cell); cz <= floor_div(z1 + lk.max_r, lk.cell); ++cz)
      for (int64_t cx = floor_div(b.ox - lk.max_r, lk.cell); cx <= floor_div(x1 + lk.max_r, lk.cell); ++cx) {
        uint64_t h = hash2(s, cx, cz);
        int64_t ex = cx * lk.cell + pick(rehash(h, 1), lk.cell), ez = cz * lk.cell + pick(rehash(h, 2), lk.cell);
        if (ex < 0 || ez < 0 || ex >= map_mm || ez >= map_mm) continue;
        uint32_t cell = cell_at(ex, ez);
        Biome bi = static_cast<Biome>(p.biome[cell]);
        int64_t pct;
        if (k == 0)
          pct = (bi == Biome::Desert || bi == Biome::Steppe) ? 35 : (bi == Biome::Beach || bi == Biome::Marsh) ? 20 : 0;
        else
          pct = (bi == Biome::Meadow || bi == Biome::Marsh || bi == Biome::Woodland || bi == Biome::LakeBed) ? 15 : 0;
        if (pick(h, 100) >= pct) continue;
        int64_t gy = plan_cubic(ex, ez);
        int64_t ey = gy - (k == 0 ? range(rehash(h, 3), 1500, 8000) : range(rehash(h, 3), 600, 3000));
        int64_t r = k == 0 ? range(rehash(h, 4), 4 * M, lk.max_r) : range(rehash(h, 4), 2 * M, lk.max_r);
        int64_t ry = k == 0 ? range(rehash(h, 5), 600, 1800) : range(rehash(h, 5), 300, 1000);
        if (ey + ry < b.oy || ey - ry > y1) continue;
        Ellipsoid e{ex, ey, ez, r, ry, (r * range(rehash(h, 6), 50, 100)) / 100};
        RasterStyle st;
        st.voxel = k == 0 ? m.salt : m.clay;
        st.replace = k == 0 ? (kRepSoil | kRepRock) : kRepSoil;
        st.noise = lattice();
        st.noise_q16 = kOne / 4;
        raster_ellipsoid(*this, b, e, st, out);
      }
  }
}

}  // namespace em::wg
