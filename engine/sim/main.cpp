// emergence_sim: headless executable linking the same core as the game.
// For now it drives world generation (M1/M2): plan, images, fingerprints.
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>

#include "emergence/base/fingerprint.h"
#include "emergence/base/parallel.h"
#include <algorithm>
#include <cmath>
#include <map>
#include <tuple>

#include "emergence/base/fixed.h"
#include "emergence/base/hash.h"
#include "emergence/base/image.h"
#include "emergence/base/timer.h"
#include "emergence/world/chunk_gen.h"
#include "emergence/world/materials.h"
#include "emergence/world/world_plan.h"

using namespace em;

namespace {

void usage() {
  std::printf(
      "usage: emergence_sim plan [--seed N] [--size M] [--threads T] [--out DIR] [--no-backdrop]\n"
      "  Generates the world plan, prints timings and fingerprint, writes debug maps to DIR.\n"
      "usage: emergence_sim chunks [--seed N] [--at town|port|miners|oasis|foresters] [--out DIR]\n"
      "  Generates 2 cm voxel chunks over 20 x 20 m and writes a top view and a vertical section.\n"
      "usage: emergence_sim geo [--seed N] [--out FILE]\n"
      "  Writes the geography JSON (villages, frontiers, resources, road lengths) for the sim and data threads.\n"
      "usage: emergence_sim zone [--seed N] [--at VILLAGE] [--size M] [--out DIR]\n"
      "  Exports an M x M metre heightfield at 8 cm around a village (heights, top material, water).\n");
}

int cmd_plan(int argc, char** argv) {
  WorldParams p;
  std::string out;
  for (int a = 2; a < argc; ++a) {
    std::string k = argv[a];
    auto next = [&]() -> const char* { return a + 1 < argc ? argv[++a] : ""; };
    if (k == "--seed") p.seed = std::strtoull(next(), nullptr, 10);
    else if (k == "--size") {
      uint64_t seed = p.seed;
      p = WorldParams::scaled(seed, std::atoi(next()));
    } else if (k == "--threads") set_worker_count(std::atoi(next()));
    else if (k == "--out") out = next();
    else if (k == "--no-backdrop") p.backdrop = false;
    else {
      usage();
      return 2;
    }
  }
  WorldPlan plan = generate_world_plan(p);
  const auto& t = plan.timings;
  std::printf("seed %llu, map %d m, %d x %d cells of %d m, %d threads\n",
              static_cast<unsigned long long>(p.seed), p.size_m, plan.n, plan.n, p.cell_m, worker_count());
  std::printf("time ms: frontier+relief %.0f, erosion %.0f, hydrology %.0f, biomes %.0f, settlements+roads %.0f, backdrop %.0f, total %.0f\n",
              t.frontier_relief_ms, t.erosion_ms, t.hydrology_ms, t.biomes_ms, t.settlements_ms, t.backdrop_ms, t.total_ms);
  std::printf("memory: %.1f MB\n", static_cast<double>(plan.memory_bytes()) / 1048576.0);
  std::printf("fingerprint: %s\n", to_hex(plan.fingerprint()).c_str());
  size_t sea = 0, lake = 0, river = 0, road = 0;
  int32_t hmin = INT32_MAX, hmax = INT32_MIN;
  for (size_t c = 0; c < plan.flags.size(); ++c) {
    sea += (plan.flags[c] & kFlagSea) != 0;
    lake += (plan.flags[c] & kFlagLake) != 0;
    river += (plan.flags[c] & kFlagRiver) != 0;
    road += (plan.flags[c] & kFlagRoad) != 0;
    hmin = std::min(hmin, plan.height_mm[c]);
    hmax = std::max(hmax, plan.height_mm[c]);
  }
  double cell_km2 = static_cast<double>(p.cell_m) * p.cell_m / 1e6;
  std::printf("height: %.0f m .. %.0f m; sea %.1f km2, lakes %.2f km2, river cells %zu, road cells %zu\n",
              hmin / 1000.0, hmax / 1000.0, sea * cell_km2, lake * cell_km2, river, road);
  for (const auto& s : plan.settlements)
    std::printf("settlement %-9s at (%.2f km, %.2f km), %.0f m\n", settlement_name(s.kind),
                s.i * p.cell_m / 1000.0, s.j * p.cell_m / 1000.0, s.height_mm / 1000.0);
  for (const auto& r : plan.roads)
    std::printf("road %s -> %s: %.1f km\n", settlement_name(plan.settlements[static_cast<size_t>(r.from)].kind),
                settlement_name(plan.settlements[static_cast<size_t>(r.to)].kind), r.length_m / 1000.0);
  if (!out.empty() && !write_plan_images(plan, out)) {
    std::fprintf(stderr, "cannot write images to %s\n", out.c_str());
    return 1;
  }
  return 0;
}

int cmd_chunks(int argc, char** argv) {
  WorldParams p;
  std::string out = ".", at = "town";
  for (int a = 2; a < argc; ++a) {
    std::string k = argv[a];
    auto next = [&]() -> const char* { return a + 1 < argc ? argv[++a] : ""; };
    if (k == "--seed") p.seed = std::strtoull(next(), nullptr, 10);
    else if (k == "--at") at = next();
    else if (k == "--out") out = next();
    else {
      usage();
      return 2;
    }
  }
  WorldPlan plan = generate_world_plan(p);
  const MaterialTable& mats = MaterialTable::builtin();
  ChunkGenerator gen(plan, mats);
  const Settlement* site = nullptr;
  for (const auto& s : plan.settlements)
    if (at == settlement_name(s.kind)) site = &s;
  if (!site) {
    std::fprintf(stderr, "no settlement named %s\n", at.c_str());
    return 2;
  }
  const int span = 16;  // chunks per side: 20.48 m
  const int W = span * kChunkSize;
  int64_t cx0 = site->i * plan.cell_mm / kVoxelMm / kChunkSize - span / 2;
  int64_t cz0 = site->j * plan.cell_mm / kVoxelMm / kChunkSize - span / 2;
  std::map<std::tuple<int, int, int>, Chunk> cache;
  Timer t;
  int generated = 0;
  auto chunk_at = [&](int32_t cx, int32_t cy, int32_t cz) -> const Chunk& {
    auto key = std::make_tuple(cx, cy, cz);
    auto it = cache.find(key);
    if (it != cache.end()) return it->second;
    Chunk& c = cache[key];
    gen.generate({cx, cy, cz}, c);
    ++generated;
    return c;
  };
  std::vector<int32_t> top(static_cast<size_t>(W) * W);
  std::vector<VoxelId> mat(static_cast<size_t>(W) * W);
  for (int z = 0; z < W; ++z)
    for (int x = 0; x < W; ++x) {
      int64_t vx = cx0 * kChunkSize + x, vz = cz0 * kChunkSize + z;
      int32_t s = gen.surface_voxel_y(vx, vz);
      int32_t y = s - 1;
      const Chunk& c = chunk_at(static_cast<int32_t>(cx0 + x / kChunkSize), static_cast<int32_t>(floor_div(y, kChunkSize)),
                                static_cast<int32_t>(cz0 + z / kChunkSize));
      top[static_cast<size_t>(z) * W + x] = s;
      mat[static_cast<size_t>(z) * W + x] = c.get(x % kChunkSize, static_cast<int>(y - floor_div(y, kChunkSize) * kChunkSize), z % kChunkSize);
    }
  double ms = t.ms();
  size_t bytes = 0;
  for (auto& [k, c] : cache) bytes += c.memory_bytes();
  std::printf("%s: %d chunks generated in %.0f ms (%.3f ms each incl. lookups), %.1f KB stored\n", at.c_str(), generated,
              ms, ms / generated, static_cast<double>(bytes) / 1024.0);

  auto color = [&](VoxelId v, float shade) {
    uint32_t c = mats.get(voxel_class(v)).color;
    float r = ((c >> 16) & 255) / 255.0f, g = ((c >> 8) & 255) / 255.0f, b = (c & 255) / 255.0f;
    return std::array<uint8_t, 3>{static_cast<uint8_t>(std::clamp(r * shade, 0.0f, 1.0f) * 255),
                                  static_cast<uint8_t>(std::clamp(g * shade, 0.0f, 1.0f) * 255),
                                  static_cast<uint8_t>(std::clamp(b * shade, 0.0f, 1.0f) * 255)};
  };
  std::vector<uint8_t> img(static_cast<size_t>(W) * W * 3);
  for (int z = 0; z < W; ++z)
    for (int x = 0; x < W; ++x) {
      auto T = [&](int a, int b) {
        a = std::clamp(a, 0, W - 1);
        b = std::clamp(b, 0, W - 1);
        return static_cast<float>(top[static_cast<size_t>(b) * W + a]);
      };
      float dx = T(x + 1, z) - T(x - 1, z), dz = T(x, z + 1) - T(x, z - 1);
      float shade = std::clamp(1.0f + 0.25f * (-dx + dz), 0.4f, 1.4f);
      auto c = color(mat[static_cast<size_t>(z) * W + x], shade);
      size_t o = (static_cast<size_t>(W - 1 - z) * W + x) * 3;
      img[o] = c[0];
      img[o + 1] = c[1];
      img[o + 2] = c[2];
    }
  write_png_rgb(out + "/voxels_" + at + "_top.png", W, W, img);

  // Vertical section through the middle, 2 cm per pixel.
  int zmid = W / 2;
  int32_t ymin = INT32_MAX, ymax = INT32_MIN;
  for (int x = 0; x < W; ++x) {
    ymin = std::min(ymin, top[static_cast<size_t>(zmid) * W + x]);
    ymax = std::max(ymax, top[static_cast<size_t>(zmid) * W + x]);
  }
  int32_t y0 = ymin - 150, y1 = ymax + 60;
  int H = y1 - y0;
  std::vector<uint8_t> sec(static_cast<size_t>(W) * H * 3);
  for (int x = 0; x < W; ++x)
    for (int y = y0; y < y1; ++y) {
      const Chunk& c = chunk_at(static_cast<int32_t>(cx0 + x / kChunkSize), static_cast<int32_t>(floor_div(y, kChunkSize)),
                                static_cast<int32_t>(cz0 + zmid / kChunkSize));
      VoxelId v = c.get(x % kChunkSize, static_cast<int>(y - floor_div(y, kChunkSize) * kChunkSize), zmid % kChunkSize);
      std::array<uint8_t, 3> col = v == kAir ? std::array<uint8_t, 3>{186, 214, 240} : color(v, 1.0f);
      size_t o = (static_cast<size_t>(y1 - 1 - y) * W + x) * 3;
      sec[o] = col[0];
      sec[o + 1] = col[1];
      sec[o + 2] = col[2];
    }
  write_png_rgb(out + "/voxels_" + at + "_section.png", W, H, sec);
  return 0;
}

const Settlement* find_site(const WorldPlan& plan, const std::string& at) {
  for (const auto& s : plan.settlements)
    if (at == settlement_name(s.kind) || at == settlement_id(s.kind)) return &s;
  return nullptr;
}

// Indicative resources around a village, 0..10, from plan cells within 3 km
// (villages sit 0.2 to 2.6 km before their march, the resources are in it).
// The sim and data threads use them for trade dependence; worldgen owns the
// real deposits (ore bodies, salt lenses) and may refine these later.
std::string village_resources(const WorldPlan& plan, const Settlement& s) {
  const int32_t r = static_cast<int32_t>(3'000'000 / plan.cell_mm);
  int64_t total = 0, sea = 0, fresh = 0, wood = 0, deep = 0, farm = 0, stone = 0, hard = 0, sand = 0, salt = 0;
  for (int32_t dj = -r; dj <= r; ++dj)
    for (int32_t di = -r; di <= r; ++di) {
      if (int64_t{di} * di + int64_t{dj} * dj > int64_t{r} * r) continue;
      int32_t i = s.i + di, j = s.j + dj;
      if (!plan.in_map(i, j)) continue;
      size_t c = plan.idx(i, j);
      ++total;
      uint8_t f = plan.flags[c];
      auto b = static_cast<Biome>(plan.biome[c]);
      auto rock = static_cast<RockType>(plan.rock[c]);
      if (f & kFlagSea) ++sea;
      if (f & (kFlagLake | kFlagRiver)) ++fresh;
      if (b == Biome::Woodland || b == Biome::DeepForest) ++wood;
      if (b == Biome::DeepForest) ++deep;
      if (b == Biome::Meadow || b == Biome::Steppe) ++farm;
      if (b == Biome::Rock || b == Biome::Alpine || b == Biome::Foothills || plan.soil_mm[c] < 300) ++stone;
      if ((rock == RockType::Granite || rock == RockType::Basalt || rock == RockType::Slate) &&
          (b == Biome::Rock || b == Biome::Alpine || b == Biome::Foothills))
        ++hard;
      if (b == Biome::Desert || b == Biome::Beach) ++sand;
      if ((b == Biome::Desert && (f & kFlagLake)) || b == Biome::Beach || b == Biome::Marsh) ++salt;
    }
  auto score = [&](int64_t n, int64_t full_per_mille) {
    // 10 when the share reaches full_per_mille.
    if (total == 0) return int64_t{0};
    return std::min<int64_t>(10, (n * 1000 * 10 + total * full_per_mille / 2) / (total * full_per_mille));
  };
  char buf[512];
  std::snprintf(buf, sizeof buf,
                "{\"fish\": %lld, \"fresh_water\": %lld, \"timber\": %lld, \"old_growth\": %lld, \"farmland\": %lld, "
                "\"stone\": %lld, \"iron_ore\": %lld, \"sand\": %lld, \"salt\": %lld}",
                static_cast<long long>(score(sea, 300)), static_cast<long long>(score(fresh, 30)),
                static_cast<long long>(score(wood, 500)), static_cast<long long>(score(deep, 300)),
                static_cast<long long>(score(farm, 500)), static_cast<long long>(score(stone, 300)),
                static_cast<long long>(score(hard, 200)), static_cast<long long>(score(sand, 400)),
                static_cast<long long>(score(salt, 50)));
  return buf;
}

int cmd_geo(int argc, char** argv) {
  WorldParams p;
  std::string out = "geography.json";
  for (int a = 2; a < argc; ++a) {
    std::string k = argv[a];
    auto next = [&]() -> const char* { return a + 1 < argc ? argv[++a] : ""; };
    if (k == "--seed") p.seed = std::strtoull(next(), nullptr, 10);
    else if (k == "--out") out = next();
    else {
      usage();
      return 2;
    }
  }
  WorldPlan plan = generate_world_plan(p);  // with backdrop, so the fingerprint matches `plan`
  FILE* f = std::fopen(out.c_str(), "w");
  if (!f) {
    std::fprintf(stderr, "cannot write %s\n", out.c_str());
    return 1;
  }
  std::fprintf(f, "{\n  \"schema_version\": \"geo-1\",\n  \"seed\": %llu,\n  \"world_generator_version\": %u,\n",
               static_cast<unsigned long long>(p.seed), plan.generator_version);
  std::fprintf(f, "  \"plan_fingerprint\": \"%016llx\",\n  \"map_size_m\": %d,\n",
               static_cast<unsigned long long>(plan.fingerprint()), p.size_m);
  std::fprintf(f, "  \"axes\": \"pos_m = [x east, z north] in metres from the south-west corner; height_m above sea level\",\n");
  std::fprintf(f, "  \"villages\": [\n");
  for (size_t k = 0; k < plan.settlements.size(); ++k) {
    const Settlement& s = plan.settlements[k];
    double x = static_cast<double>(s.i * plan.cell_mm) / 1000.0, z = static_cast<double>(s.j * plan.cell_mm) / 1000.0;
    std::fprintf(f,
                 "    {\"id\": \"%s\", \"frontier\": \"%s\", \"pos_m\": [%.0f, %.0f], \"height_m\": %.1f, "
                 "\"resources\": %s}%s\n",
                 settlement_id(s.kind), settlement_frontier(s.kind), x, z, s.height_mm / 1000.0,
                 village_resources(plan, s).c_str(), k + 1 < plan.settlements.size() ? "," : "");
  }
  std::fprintf(f, "  ],\n  \"road_km\": [\n");
  for (size_t k = 0; k < plan.roads.size(); ++k) {
    const Road& r = plan.roads[k];
    std::fprintf(f, "    [\"%s\", \"%s\", %.1f]%s\n", settlement_id(plan.settlements[r.from].kind),
                 settlement_id(plan.settlements[r.to].kind), static_cast<double>(r.length_m) / 1000.0,
                 k + 1 < plan.roads.size() ? "," : "");
  }
  std::fprintf(f, "  ]\n}\n");
  std::fclose(f);
  std::printf("wrote %s (%zu villages, %zu roads, plan %016llx)\n", out.c_str(), plan.settlements.size(),
              plan.roads.size(), static_cast<unsigned long long>(plan.fingerprint()));
  return 0;
}

// Heightfield of a square zone around a village, sampled every 4 voxels (8 cm,
// the column-profile step of P18). Raw little-endian files plus a JSON header:
//   height.u16  surface in voxels (2 cm) above base_voxel_y; voxels below are solid
//   top.u8      material class of the top voxel (data/materials.csv)
//   water.u16   water surface in voxels above base_voxel_y, 65535 = dry
// Row-major, x east fastest, then z north; row 0 is the south edge.
int cmd_zone(int argc, char** argv) {
  WorldParams p;
  std::string out = ".", at = "market_town";
  int32_t size_m = 128;
  for (int a = 2; a < argc; ++a) {
    std::string k = argv[a];
    auto next = [&]() -> const char* { return a + 1 < argc ? argv[++a] : ""; };
    if (k == "--seed") p.seed = std::strtoull(next(), nullptr, 10);
    else if (k == "--at") at = next();
    else if (k == "--size") size_m = std::atoi(next());
    else if (k == "--out") out = next();
    else {
      usage();
      return 2;
    }
  }
  WorldPlan plan = generate_world_plan(p);
  const Settlement* site = find_site(plan, at);
  if (!site || size_m <= 0) {
    std::fprintf(stderr, "no settlement named %s\n", at.c_str());
    return 2;
  }
  const MaterialTable& mats = MaterialTable::builtin();
  ChunkGenerator gen(plan, mats);
  const int step = 4;  // voxels per sample
  const int32_t chunks = (size_m * 1000 / kVoxelMm + kChunkSize - 1) / kChunkSize;
  const int32_t n = chunks * kChunkSize / step;
  const int64_t cx0 = site->i * plan.cell_mm / kVoxelMm / kChunkSize - chunks / 2;
  const int64_t cz0 = site->j * plan.cell_mm / kVoxelMm / kChunkSize - chunks / 2;
  const int64_t vx0 = cx0 * kChunkSize, vz0 = cz0 * kChunkSize;
  Timer t;
  std::vector<int32_t> top(static_cast<size_t>(n) * n);
  std::vector<uint8_t> cls(top.size());
  std::vector<int32_t> water(top.size(), INT32_MIN);
  int generated = 0;
  for (int32_t crz = 0; crz < chunks; ++crz) {
    std::map<std::tuple<int, int, int>, Chunk> cache;  // one row of chunk columns at a time
    for (int32_t zz = 0; zz < kChunkSize / step; ++zz)
      for (int32_t x = 0; x < n; ++x) {
        int32_t z = crz * (kChunkSize / step) + zz;
        int64_t vx = vx0 + int64_t{x} * step, vz = vz0 + int64_t{z} * step;
        int32_t s = gen.surface_voxel_y(vx, vz);
        int32_t y = s - 1;
        auto key = std::make_tuple(static_cast<int>(cx0 + x * step / kChunkSize), static_cast<int>(floor_div(y, kChunkSize)),
                                   static_cast<int>(cz0 + crz));
        auto it = cache.find(key);
        if (it == cache.end()) {
          it = cache.emplace(key, Chunk{}).first;
          gen.generate({std::get<0>(key), std::get<1>(key), std::get<2>(key)}, it->second);
          ++generated;
        }
        VoxelId v = it->second.get((x * step) % kChunkSize, static_cast<int>(y - floor_div(y, kChunkSize) * kChunkSize),
                                   (zz * step) % kChunkSize);
        size_t o = static_cast<size_t>(z) * n + x;
        top[o] = s;
        cls[o] = static_cast<uint8_t>(voxel_class(v));
        int32_t ci = static_cast<int32_t>(std::clamp<int64_t>((vx * kVoxelMm + plan.cell_mm / 2) / plan.cell_mm, 0, plan.n - 1));
        int32_t cj = static_cast<int32_t>(std::clamp<int64_t>((vz * kVoxelMm + plan.cell_mm / 2) / plan.cell_mm, 0, plan.n - 1));
        int32_t w = plan.water_mm[plan.idx(ci, cj)];
        if (w != WorldPlan::kNoWater && static_cast<int64_t>(w) > int64_t{s} * kVoxelMm)
          water[o] = static_cast<int32_t>(floor_div(w, kVoxelMm));
      }
  }
  int32_t base = *std::min_element(top.begin(), top.end()) - 64;
  int32_t hi = *std::max_element(top.begin(), top.end());
  if (hi - base >= 65535) {
    std::fprintf(stderr, "zone relief too tall for u16 voxels\n");
    return 1;
  }
  std::vector<uint8_t> hbytes(top.size() * 2), wbytes(top.size() * 2);
  for (size_t o = 0; o < top.size(); ++o) {
    uint16_t h = static_cast<uint16_t>(top[o] - base);
    uint16_t w = water[o] == INT32_MIN ? 65535 : static_cast<uint16_t>(std::clamp(water[o] - base, 0, 65534));
    hbytes[2 * o] = static_cast<uint8_t>(h & 255);
    hbytes[2 * o + 1] = static_cast<uint8_t>(h >> 8);
    wbytes[2 * o] = static_cast<uint8_t>(w & 255);
    wbytes[2 * o + 1] = static_cast<uint8_t>(w >> 8);
  }
  auto write_bin = [&](const std::string& path, const std::vector<uint8_t>& b) {
    FILE* f = std::fopen(path.c_str(), "wb");
    if (!f) return false;
    bool ok = std::fwrite(b.data(), 1, b.size(), f) == b.size();
    return std::fclose(f) == 0 && ok;
  };
  std::string stem = out + "/zone_" + settlement_id(site->kind);
  if (!write_bin(stem + "_height.u16", hbytes) || !write_bin(stem + "_top.u8", cls) || !write_bin(stem + "_water.u16", wbytes)) {
    std::fprintf(stderr, "cannot write into %s\n", out.c_str());
    return 1;
  }
  std::vector<uint64_t> words;
  words.reserve(top.size());
  for (size_t o = 0; o < top.size(); ++o)
    words.push_back((uint64_t(uint32_t(top[o])) << 16) ^ (uint64_t(cls[o]) << 8) ^ uint64_t(uint32_t(water[o])) << 40);
  uint64_t fp = 0x9e3779b97f4a7c15ULL;
  for (uint64_t w : words) fp = hash_combine(fp, w);
  FILE* f = std::fopen((stem + ".json").c_str(), "w");
  if (!f) return 1;
  std::fprintf(f,
               "{\n  \"schema_version\": \"zone-1\",\n  \"seed\": %llu,\n  \"world_generator_version\": %u,\n"
               "  \"plan_fingerprint\": \"%016llx\",\n  \"zone_fingerprint\": \"%016llx\",\n"
               "  \"village\": \"%s\",\n  \"n\": %d,\n  \"step_voxels\": %d,\n  \"cell_m\": %.2f,\n"
               "  \"origin_voxel\": [%lld, %lld],\n  \"origin_m\": [%.2f, %.2f],\n  \"base_voxel_y\": %d,\n"
               "  \"base_m\": %.2f,\n  \"village_center_m\": [%.2f, %.2f],\n"
               "  \"files\": {\"height\": \"%s_height.u16\", \"top\": \"%s_top.u8\", \"water\": \"%s_water.u16\"},\n"
               "  \"layout\": \"little-endian, row-major, x east fastest then z north, row 0 = south edge; "
               "height and water in voxels (2 cm) above base_voxel_y, voxels below height are solid; water 65535 = dry; "
               "top = material class of the top voxel (engine/data/materials.csv)\",\n"
               "  \"note\": \"origin is the south-west corner in world voxels (x east, z north, y up, y=0 at sea level); "
               "Godot z = -z\"\n}\n",
               static_cast<unsigned long long>(p.seed), plan.generator_version,
               static_cast<unsigned long long>(plan.fingerprint()), static_cast<unsigned long long>(fp),
               settlement_id(site->kind), n, step, step * kVoxelMm / 1000.0, static_cast<long long>(vx0),
               static_cast<long long>(vz0), vx0 * kVoxelMm / 1000.0, vz0 * kVoxelMm / 1000.0, base,
               base * kVoxelMm / 1000.0, site->i * plan.cell_mm / 1000.0, site->j * plan.cell_mm / 1000.0,
               std::string("zone_").append(settlement_id(site->kind)).c_str(),
               std::string("zone_").append(settlement_id(site->kind)).c_str(),
               std::string("zone_").append(settlement_id(site->kind)).c_str());
  std::fclose(f);

  // Shaded preview for humans, one pixel per 32 cm.
  const int pv = n / 4;
  std::vector<uint8_t> img(static_cast<size_t>(pv) * pv * 3);
  for (int pz = 0; pz < pv; ++pz)
    for (int px = 0; px < pv; ++px) {
      int x = px * 4, z = pz * 4;
      auto T = [&](int a, int b) {
        a = std::clamp(a, 0, n - 1);
        b = std::clamp(b, 0, n - 1);
        return static_cast<float>(top[static_cast<size_t>(b) * n + a]);
      };
      float shade = std::clamp(1.0f + 0.03f * (-(T(x + 4, z) - T(x - 4, z)) + (T(x, z + 4) - T(x, z - 4))), 0.4f, 1.4f);
      size_t o = static_cast<size_t>(z) * n + x;
      uint32_t c = water[o] != INT32_MIN ? 0x3a6ea5u : mats.get(cls[o]).color;
      size_t q = (static_cast<size_t>(pv - 1 - pz) * pv + px) * 3;
      img[q] = static_cast<uint8_t>(std::clamp(((c >> 16) & 255) * shade, 0.0f, 255.0f));
      img[q + 1] = static_cast<uint8_t>(std::clamp(((c >> 8) & 255) * shade, 0.0f, 255.0f));
      img[q + 2] = static_cast<uint8_t>(std::clamp((c & 255) * shade, 0.0f, 255.0f));
    }
  write_png_rgb(stem + "_preview.png", pv, pv, img);
  std::printf("%s: %d x %d samples at 8 cm, %d chunks generated in %.0f ms, relief %.1f m, zone %016llx\n",
              settlement_id(site->kind), n, n, generated, t.ms(), (hi - base - 64) * kVoxelMm / 1000.0,
              static_cast<unsigned long long>(fp));
  return 0;
}

}  // namespace

int main(int argc, char** argv) {
  if (argc < 2) {
    usage();
    return 2;
  }
  if (std::strcmp(argv[1], "plan") == 0) return cmd_plan(argc, argv);
  if (std::strcmp(argv[1], "chunks") == 0) return cmd_chunks(argc, argv);
  if (std::strcmp(argv[1], "geo") == 0) return cmd_geo(argc, argv);
  if (std::strcmp(argv[1], "zone") == 0) return cmd_zone(argc, argv);
  usage();
  return 2;
}
