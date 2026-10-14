// Roadmap M3 on the game's generator (worldgen): loads every LOD ring around
// a village from nothing, then walks and digs, and reports times, quads and
// memory per level.
#include <cstdio>
#include <cstdlib>
#include <string>
#include <vector>

#include "emergence/base/parallel.h"
#include "emergence/base/timer.h"
#include "emergence/mesh/terrain_streamer.h"
#include "emergence/terrain/worldgen_source.h"

using namespace em;

int main(int argc, char** argv) {
  std::string at = argc > 1 ? argv[1] : "market_town";
  bool ao = !(argc > 2 && std::string(argv[2]) == "noao");
  Timer tp;
  WorldPlan plan = generate_world_plan(WorldParams{1});
  wg::WorldGen gen(plan);
  WorldGenSource src(gen);
  std::printf("plan + worldgen: %.0f ms, %d threads\n", tp.ms(), worker_count());
  const Settlement* site = &plan.settlements[0];
  for (const auto& s : plan.settlements)
    if (at == settlement_id(s.kind)) site = &s;
  int64_t vx = site->i * plan.cell_mm / kVoxelMm, vz = site->j * plan.cell_mm / kVoxelMm;

  ChunkCache cache(src);
  StreamerParams p;
  p.ao_max_lod = ao ? 2 : -1;
  TerrainStreamer ts(cache, p);
  ts.set_view(vx, vz);
  std::vector<RegionUpdate> up;
  Timer t;
  while (!ts.update(1e9, up)) {}
  double load_ms = t.ms();
  std::vector<size_t> q(static_cast<size_t>(p.lods)), regions(static_cast<size_t>(p.lods));
  for (auto& r : up) {
    q[static_cast<size_t>(r.key.lod)] += r.quads.size();
    regions[static_cast<size_t>(r.key.lod)]++;
  }
  size_t total = 0, nreg = 0;
  std::printf("%s, ambient occlusion %s (levels 0-2): full load %.0f ms, %zu chunks generated, %zu meshed (plan %.0f, generate %.0f, mesh %.0f ms)\n",
              settlement_id(site->kind), ao ? "on" : "off", load_ms, ts.totals().chunks_generated, ts.totals().chunks_meshed,
              ts.totals().plan_ms, ts.totals().generate_ms, ts.totals().mesh_ms);
  for (int L = 0; L < p.lods; ++L) {
    auto b = ts.box(L);
    std::printf("  level %d: voxel %3d cm, square %5.0f m, %3zu regions, %8zu quads, %5.1f MB\n", L, 2 << L,
                static_cast<double>(b.x1 - b.x0 + 1) * 1.28 * (1 << L), regions[static_cast<size_t>(L)],
                q[static_cast<size_t>(L)], static_cast<double>(q[static_cast<size_t>(L)]) * 8 / 1048576.0);
    total += q[static_cast<size_t>(L)];
    nreg += regions[static_cast<size_t>(L)];
  }
  std::printf("  total: %zu draw regions, %.2f M quads, %.1f MB of quads; chunk cache %.0f MB (%zu chunks)\n", nreg,
              static_cast<double>(total) / 1e6, static_cast<double>(total) * 8 / 1048576.0,
              static_cast<double>(cache.memory_bytes()) / 1048576.0, cache.size());

  // Walk 20 m east at 1.5 m/s, one update per 2.56 m step (a lod-1 chunk).
  double worst = 0, sum = 0;
  int steps = 0;
  StreamerStats t0 = ts.totals();
  for (int64_t d = 128; d <= 1000; d += 128) {
    ts.set_view(vx + d, vz);
    up.clear();
    Timer ts_t;
    while (!ts.update(1e9, up)) {}
    double ms = ts_t.ms();
    worst = std::max(worst, ms);
    sum += ms;
    ++steps;
  }
  std::printf("walking: %.0f ms per 2.56 m step on average, %.0f ms worst (all levels, all cores)\n", sum / steps, worst);
  StreamerStats t1 = ts.totals();
  std::printf("  per step: %.0f chunks generated, %.0f meshed; plan %.0f ms, generate %.0f ms, mesh %.0f ms\n",
              double(t1.chunks_generated - t0.chunks_generated) / steps, double(t1.chunks_meshed - t0.chunks_meshed) / steps,
              (t1.plan_ms - t0.plan_ms) / steps, (t1.generate_ms - t0.generate_ms) / steps, (t1.mesh_ms - t0.mesh_ms) / steps);

  // Dig 20 holes of 30 cm.
  int64_t gx = vx + 1000;
  Timer td;
  size_t dig_regions = 0;
  for (int i = 0; i < 20; ++i) {
    int64_t x = gx + i * 7, y = src.ground_voxel_y(x, vz);
    auto ch = cache.edit_sphere(x, y, vz, 15, kAir);
    ts.mark_edited(ch);
    up.clear();
    while (!ts.update(1e9, up)) {}
    dig_regions += up.size();
  }
  std::printf("digging: %.1f ms per 30 cm hole (edit + remesh + %zu regions re-sent each)\n", td.ms() / 20,
              dig_regions / 20);
  return 0;
}
