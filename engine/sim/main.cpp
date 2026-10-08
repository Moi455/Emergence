// emergence_sim: headless executable linking the same core as the game.
// For now it drives world generation (M1/M2): plan, images, fingerprints.
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>

#include "emergence/base/fingerprint.h"
#include "emergence/base/parallel.h"
#include "emergence/world/world_plan.h"

using namespace em;

namespace {

void usage() {
  std::printf(
      "usage: emergence_sim plan [--seed N] [--size M] [--threads T] [--out DIR] [--no-backdrop]\n"
      "  Generates the world plan, prints timings and fingerprint, writes debug maps to DIR.\n");
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

}  // namespace

int main(int argc, char** argv) {
  if (argc < 2) {
    usage();
    return 2;
  }
  if (std::strcmp(argv[1], "plan") == 0) return cmd_plan(argc, argv);
  usage();
  return 2;
}
