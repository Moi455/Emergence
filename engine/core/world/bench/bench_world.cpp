// Roadmap M1 and M2 measurements: plan of the 20 km map, then generation of
// surface chunks at deterministic spots all over the map.
#include <algorithm>
#include <cstdio>
#include <cstdlib>
#include <vector>

#include "emergence/base/fixed.h"
#include "emergence/base/hash.h"
#include "emergence/base/timer.h"
#include "emergence/world/chunk_gen.h"
#include "emergence/world/materials.h"
#include "emergence/world/world_plan.h"

using namespace em;

int main(int argc, char** argv) {
  uint64_t seed = argc > 1 ? std::strtoull(argv[1], nullptr, 10) : 1;
  int samples = argc > 2 ? std::atoi(argv[2]) : 500;
  WorldPlan plan = generate_world_plan(WorldParams{seed});
  std::printf("M1 plan 20 km: %.0f ms total (erosion %.0f ms), %.1f MB\n", plan.timings.total_ms,
              plan.timings.erosion_ms, static_cast<double>(plan.memory_bytes()) / 1048576.0);

  ChunkGenerator gen(plan, MaterialTable::builtin());
  std::vector<double> times;
  double classify_ms = 0;
  size_t bytes = 0, mixed_bricks = 0, chunks = 0, implicit = 0, column_chunks = 0;
  Chunk ch;
  for (int k = 0; k < samples; ++k) {
    int64_t vx = static_cast<int64_t>(mix64(static_cast<uint64_t>(k) * 2 + 1) % static_cast<uint64_t>(gen.map_voxels()));
    int64_t vz = static_cast<int64_t>(mix64(static_cast<uint64_t>(k) * 2 + 2) % static_cast<uint64_t>(gen.map_voxels()));
    int32_t s = gen.surface_voxel_y(vx, vz);
    ChunkCoord cc{static_cast<int32_t>(vx / kChunkSize), static_cast<int32_t>(floor_div(s, kChunkSize)),
                  static_cast<int32_t>(vz / kChunkSize)};
    Timer t;
    gen.generate(cc, ch);
    times.push_back(t.ms());
    bytes += ch.memory_bytes();
    mixed_bricks += static_cast<size_t>(kBricks - ch.uniform_brick_count());
    ++chunks;
    // How many chunks of this column need real storage (the rest is implicit).
    Timer tc;
    for (int dy = -60; dy <= 60; ++dy) {
      auto kind = gen.classify({cc.x, cc.y + dy, cc.z});
      if (kind == ChunkGenerator::Kind::Mixed) ++column_chunks;
      else ++implicit;
    }
    classify_ms += tc.ms();
  }
  std::sort(times.begin(), times.end());
  double sum = 0;
  for (double t : times) sum += t;
  std::printf("M2 surface chunk generation (%zu chunks): mean %.3f ms, median %.3f ms, p95 %.3f ms, max %.3f ms\n",
              chunks, sum / static_cast<double>(chunks), times[times.size() / 2], times[times.size() * 95 / 100],
              times.back());
  std::printf("   memory per surface chunk: %.1f KB, mixed bricks %.0f of 512\n",
              static_cast<double>(bytes) / static_cast<double>(chunks) / 1024.0,
              static_cast<double>(mixed_bricks) / static_cast<double>(chunks));
  std::printf("   classify: %.2f us per chunk; per column of 121 chunks, %.1f need generation, the rest implicit\n",
              classify_ms * 1000.0 / static_cast<double>(chunks * 121),
              static_cast<double>(column_chunks) / static_cast<double>(chunks));
  return 0;
}
