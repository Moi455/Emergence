#include "emergence/world/world_plan.h"

#include <algorithm>
#include <cstdio>
#include <cstdlib>

#include "emergence/base/fingerprint.h"
#include "emergence/base/fixed.h"
#include "emergence/base/noise.h"
#include "emergence/base/parallel.h"
#include "emergence/base/timer.h"
#include "plan_internal.h"

namespace em {

namespace {
constexpr int64_t M = 1000;
}

const char* biome_name(Biome b) {
  static const char* names[] = {"ocean", "beach", "marsh", "meadow", "woodland", "deep_forest", "steppe",
                                "desert", "foothills", "alpine", "rock", "snow", "lake_bed"};
  return b < Biome::kCount ? names[static_cast<int>(b)] : "?";
}

const char* rock_material_name(RockType r) {
  static const char* names[] = {"limestone", "sandstone", "granite", "slate", "basalt"};
  return r < RockType::kCount ? names[static_cast<int>(r)] : "limestone";
}

const char* settlement_name(SettlementKind k) {
  static const char* names[] = {"port", "foresters", "miners", "oasis", "town"};
  return names[static_cast<int>(k)];
}

const char* settlement_id(SettlementKind k) {
  static const char* ids[] = {"sea_village", "forest_village", "mountain_village", "desert_village", "market_town"};
  return ids[static_cast<int>(k)];
}

const char* settlement_frontier(SettlementKind k) {
  static const char* sides[] = {"west", "south", "north", "east", "center"};
  return sides[static_cast<int>(k)];
}

WorldParams WorldParams::scaled(uint64_t seed, int32_t size_m) {
  WorldParams p;
  p.seed = seed;
  p.size_m = size_m;
  for (auto& w : p.march_width_m) w = static_cast<int32_t>(int64_t{w} * size_m / 20000);
  for (auto& d : p.hostility_doubling_m) d = std::max(1, static_cast<int32_t>(int64_t{d} * size_m / 20000));
  return p;
}

int64_t WorldParams::scale_q16() const { return (int64_t{size_m} * kOne) / 20000; }

int64_t WorldPlan::hostility_q16(size_t cell) const {
  uint8_t s = march_side[cell];
  int64_t d = march_depth_m[cell];
  if (s == static_cast<uint8_t>(Side::None) || d <= 0) return kOne;
  return qexp2((d * kOne) / params.hostility_doubling_m[s]);
}

int32_t WorldPlan::height_at_mm(int64_t x_mm, int64_t z_mm) const {
  int64_t max_mm = (n - 1) * cell_mm;
  x_mm = clamp64(x_mm, 0, max_mm);
  z_mm = clamp64(z_mm, 0, max_mm);
  int32_t i = static_cast<int32_t>(x_mm / cell_mm), j = static_cast<int32_t>(z_mm / cell_mm);
  int32_t i1 = std::min(i + 1, n - 1), j1 = std::min(j + 1, n - 1);
  int64_t fx = ((x_mm - i * cell_mm) * kOne) / cell_mm, fz = ((z_mm - j * cell_mm) * kOne) / cell_mm;
  int64_t a = qlerp(height_mm[idx(i, j)], height_mm[idx(i1, j)], fx);
  int64_t b = qlerp(height_mm[idx(i, j1)], height_mm[idx(i1, j1)], fx);
  return static_cast<int32_t>(qlerp(a, b, fz));
}

uint64_t WorldPlan::fingerprint() const {
  Fingerprint f;
  f.add_u32(generator_version);
  f.add_u64(params.seed);
  f.add_i32(params.size_m);
  f.add_i32(params.cell_m);
  f.add(std::span<const int32_t>(height_mm));
  f.add(std::span<const int32_t>(water_mm));
  f.add(std::span<const uint32_t>(flow_m2));
  f.add(std::span<const uint8_t>(receiver));
  f.add(std::span<const uint8_t>(biome));
  f.add(std::span<const uint8_t>(rock));
  f.add(std::span<const uint16_t>(soil_mm));
  f.add(std::span<const uint8_t>(flags));
  f.add(std::span<const uint8_t>(march_side));
  f.add(std::span<const int16_t>(march_depth_m));
  for (const auto& s : settlements) {
    f.add_u8(static_cast<uint8_t>(s.kind));
    f.add_i32(s.i);
    f.add_i32(s.j);
  }
  for (const auto& r : roads) f.add(std::span<const uint32_t>(r.cells));
  f.add(std::span<const int32_t>(near_backdrop.height_mm));
  f.add(std::span<const int32_t>(far_backdrop.height_mm));
  return f.value();
}

size_t WorldPlan::memory_bytes() const {
  size_t cells = height_mm.size();
  size_t b = cells * (4 + 4 + 4 + 1 + 1 + 1 + 2 + 1 + 1 + 2);
  for (const auto& r : roads) b += r.cells.size() * 4;
  b += (near_backdrop.height_mm.size() + far_backdrop.height_mm.size()) * 4;
  return b;
}

WorldPlan generate_world_plan(const WorldParams& params) {
  Timer total, stage;
  WorldPlan p;
  p.params = params;
  p.cell_mm = int64_t{params.cell_m} * M;
  p.n = params.size_m / params.cell_m;
  const int32_t n = p.n;
  const size_t N = static_cast<size_t>(n) * static_cast<size_t>(n);
  plan::Relief relief(params);

  // 1. Frontiers and pre-erosion relief.
  p.height_mm.resize(N);
  p.march_side.resize(N);
  p.march_depth_m.resize(N);
  std::vector<uint16_t> rain_q8(N);
  std::vector<std::array<int64_t, 4>> weights(N);
  std::vector<int16_t> moisture(N);
  parallel_for(0, n, [&](int64_t j0, int64_t j1) {
    for (int32_t j = static_cast<int32_t>(j0); j < j1; ++j) {
      for (int32_t i = 0; i < n; ++i) {
        size_t c = p.idx(i, j);
        int64_t x = i * p.cell_mm, z = j * p.cell_mm;
        plan::FrontierSample fs;
        p.height_mm[c] = static_cast<int32_t>(relief.height_mm(x, z, 2 * p.cell_mm, &fs));
        int best = 0;
        for (int s = 1; s < 4; ++s)
          if (fs.depth_mm[static_cast<size_t>(s)] > fs.depth_mm[static_cast<size_t>(best)]) best = s;
        int64_t d = fs.depth_mm[static_cast<size_t>(best)];
        p.march_side[c] = d > 0 ? static_cast<uint8_t>(best) : static_cast<uint8_t>(Side::None);
        p.march_depth_m[c] = static_cast<int16_t>(clamp64(d / M, -32767, 32767));
        int64_t m = relief.moisture_q16(x, z, fs);
        moisture[c] = static_cast<int16_t>(m >> 4);
        rain_q8[c] = static_cast<uint16_t>(m >> 8);
        weights[c] = fs.weight_q16;
      }
    }
  });
  p.timings.frontier_relief_ms = stage.ms();

  // 2. Erosion, then 3. sea, lakes, rivers.
  stage.reset();
  plan::erode(p, rain_q8, params.erosion_iterations);
  p.timings.erosion_ms = stage.ms();
  stage.reset();
  plan::compute_hydrology(p, rain_q8);
  p.timings.hydrology_ms = stage.ms();

  // 4. Biomes, geology, soil.
  stage.reset();
  p.biome.resize(N);
  p.rock.resize(N);
  p.soil_mm.resize(N);
  auto weight_of = [&](size_t c, FrontierKind k) {
    int64_t w = 0;
    for (int s = 0; s < 4; ++s)
      if (params.frontier[static_cast<size_t>(s)] == k) w = std::max(w, weights[c][static_cast<size_t>(s)]);
    return w;
  };
  const uint64_t snow_seed = layer_seed(params.seed, Layer::Snowline);
  const uint64_t biome_seed = layer_seed(params.seed, Layer::Biome);
  const uint64_t geo_seed = layer_seed(params.seed, Layer::Geology);
  const int64_t sc = params.scale_q16();
  auto L = [&](int64_t mm) { return std::max<int64_t>((mm * sc) >> 16, 1); };
  parallel_for(0, n, [&](int64_t j0, int64_t j1) {
    for (int32_t j = static_cast<int32_t>(j0); j < j1; ++j) {
      for (int32_t i = 0; i < n; ++i) {
        size_t c = p.idx(i, j);
        int64_t x = i * p.cell_mm, z = j * p.cell_mm;
        int64_t h = p.height_mm[c];
        int64_t slope = plan::slope_permille(p, i, j);
        int64_t w_sea = weight_of(c, FrontierKind::Sea), w_des = weight_of(c, FrontierKind::Desert),
                w_for = weight_of(c, FrontierKind::Forest);
        int64_t snowline = 2300 * M + ((fbm2(snow_seed, to_noise(x, L(3000 * M)), to_noise(z, L(3000 * M)), 3) * 200 * M) >> 16);
        // Biome borders wander instead of following the march weights exactly.
        int64_t jitter = (fbm2(hash_combine(biome_seed, 9), to_noise(x, L(900 * M)), to_noise(z, L(900 * M)), 4) * 22) / 100;
        w_des = clamp64(w_des + (w_des > 0 ? jitter : 0), 0, kOne);
        w_for = clamp64(w_for + (w_for > 0 ? jitter : 0), 0, kOne);
        int64_t woods = moisture[c] * 16 + ((fbm2(biome_seed, to_noise(x, L(1500 * M)), to_noise(z, L(1500 * M)), 4) * 6) / 10);
        Biome b;
        if (p.flags[c] & kFlagSea) b = Biome::Ocean;
        else if (p.flags[c] & kFlagLake) b = Biome::LakeBed;
        else if (h < 4 * M && w_sea > kOne / 5) b = w_for > kOne * 4 / 10 ? Biome::Marsh : Biome::Beach;
        else if (h > snowline) b = Biome::Snow;
        else if (slope > 900 || h > snowline - 500 * M) b = Biome::Rock;
        else if (h > 1300 * M) b = Biome::Alpine;
        else if (h > 450 * M && slope > 150) b = Biome::Foothills;
        else if (w_des > kOne * 6 / 10) b = Biome::Desert;
        else if (w_des > kOne / 5) b = Biome::Steppe;
        else if (w_for > kOne * 55 / 100) b = Biome::DeepForest;
        else if (woods > kOne * 72 / 100) b = Biome::Woodland;
        else b = Biome::Meadow;
        p.biome[c] = static_cast<uint8_t>(b);

        int64_t g = fbm2(geo_seed, to_noise(x, L(3000 * M)), to_noise(z, L(3000 * M)), 3);
        RockType r;
        if (h > 400 * M && p.march_side[c] == static_cast<uint8_t>(Side::North)) r = RockType::Granite;
        else if (h > 900 * M) r = RockType::Granite;
        else if (w_des > kOne * 4 / 10) r = RockType::Sandstone;
        else if (w_sea > kOne * 3 / 10) r = g > 0 ? RockType::Slate : RockType::Basalt;
        else if (w_for > kOne / 2) r = RockType::Slate;
        else if (g < -kOne * 3 / 10) r = RockType::Sandstone;
        else if (g > kOne * 35 / 100) r = RockType::Slate;
        else r = RockType::Limestone;
        p.rock[c] = static_cast<uint8_t>(r);

        static constexpr int32_t soil_by_biome[] = {1500, 3000, 2000, 900, 1200, 1500, 600, 4000,
                                                    500, 300, 0, 0, 1000};
        int64_t soil = soil_by_biome[static_cast<int>(b)];
        soil -= (soil * qramp(200, 900, slope)) >> 16;
        p.soil_mm[c] = static_cast<uint16_t>(soil);
      }
    }
  });
  p.timings.biomes_ms = stage.ms();

  // 5. Settlements and roads.
  stage.reset();
  plan::place_settlements(p);
  plan::build_roads(p);
  p.timings.settlements_ms = stage.ms();

  // 6. Backdrop.
  stage.reset();
  if (params.backdrop) plan::build_backdrop(p, relief);
  p.timings.backdrop_ms = stage.ms();
  p.timings.total_ms = total.ms();
  return p;
}

}  // namespace em
