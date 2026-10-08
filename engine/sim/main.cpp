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
      "  Generates 2 cm voxel chunks over 20 x 20 m and writes a top view and a vertical section.\n");
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

}  // namespace

int main(int argc, char** argv) {
  if (argc < 2) {
    usage();
    return 2;
  }
  if (std::strcmp(argv[1], "plan") == 0) return cmd_plan(argc, argv);
  if (std::strcmp(argv[1], "chunks") == 0) return cmd_chunks(argc, argv);
  usage();
  return 2;
}
