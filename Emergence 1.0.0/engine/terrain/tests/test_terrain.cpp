#include <set>
#include <vector>

#include "emergence/base/fixed.h"
#include "emergence/base/hash.h"
#include "emergence/mesh/terrain_streamer.h"
#include "emergence/terrain/worldgen_source.h"
#include "emergence/testing/check.h"

using namespace em;

namespace {

struct World {
  WorldPlan plan = generate_world_plan(WorldParams::scaled(7, 4000));
  wg::WorldGen gen{plan};
  WorldGenSource src{gen};
};

World& world() {
  static World w;
  return w;
}

}  // namespace

TEST(source_matches_worldgen) {
  World& w = world();
  const Settlement& s = w.plan.settlements[0];
  int64_t vx = s.i * w.plan.cell_mm / kVoxelMm, vz = s.j * w.plan.cell_mm / kVoxelMm;
  int64_t vy = w.src.ground_voxel_y(vx, vz);
  ChunkCoord c{static_cast<int32_t>(vx / 64), static_cast<int32_t>(floor_div(vy, 64)), static_cast<int32_t>(vz / 64)};
  Chunk a, b;
  w.src.fill(0, c, a);
  w.gen.generate(c, b);
  CHECK_EQ(a.fingerprint(), b.fingerprint());
  VoxelId u = 0;
  CHECK(w.src.classify(0, c, &u) == SourceKind::Mixed);
}

TEST(rings_nest_without_gap_or_overlap) {
  World& w = world();
  ChunkCache cache(w.src);
  TerrainStreamer ts(cache);
  const int64_t map = w.src.map_voxels();
  for (int k = 0; k < 6; ++k) {
    int64_t vx = static_cast<int64_t>(mix64(static_cast<uint64_t>(k) + 1) % static_cast<uint64_t>(map));
    int64_t vz = static_cast<int64_t>(mix64(static_cast<uint64_t>(k) + 100) % static_cast<uint64_t>(map));
    ts.set_view(vx, vz);
    for (int L = 1; L < ts.params().lods; ++L) {
      auto h = ts.hole(L), lo = ts.box(L - 1), b = ts.box(L);
      CHECK(h.x0 * 2 == lo.x0 && h.z0 * 2 == lo.z0 && h.x1 * 2 + 1 == lo.x1 && h.z1 * 2 + 1 == lo.z1);
      CHECK(b.contains(h.x0, h.z0) && b.contains(h.x1, h.z1));
    }
    // Every column inside the coarsest square and the map is drawn exactly once.
    auto outer = ts.box(ts.params().lods - 1);
    int64_t S = int64_t{kChunkSize} << (ts.params().lods - 1);
    for (int i = 0; i < 400; ++i) {
      int64_t px = outer.x0 * S + static_cast<int64_t>(mix64(static_cast<uint64_t>(i) * 3 + 7) % static_cast<uint64_t>((outer.x1 - outer.x0 + 1) * S));
      int64_t pz = outer.z0 * S + static_cast<int64_t>(mix64(static_cast<uint64_t>(i) * 3 + 8) % static_cast<uint64_t>((outer.z1 - outer.z0 + 1) * S));
      if (px < 0 || pz < 0 || px >= map || pz >= map) continue;
      int count = 0;
      for (int L = 0; L < ts.params().lods; ++L) {
        int64_t size = int64_t{kChunkSize} << L;
        count += ts.drawn(L, floor_div(px, size), floor_div(pz, size));
      }
      CHECK_EQ(count, 1);
    }
  }
}

TEST(streams_moves_and_digs) {
  World& w = world();
  ChunkCache cache(w.src);
  StreamerParams p;
  p.lods = 4;
  TerrainStreamer ts(cache, p);
  const Settlement& s = w.plan.settlements[0];
  int64_t vx = s.i * w.plan.cell_mm / kVoxelMm, vz = s.j * w.plan.cell_mm / kVoxelMm;
  ts.set_view(vx, vz);
  std::vector<RegionUpdate> up;
  while (!ts.update(1e9, up)) {}
  size_t quads = 0;
  for (auto& r : up) quads += r.quads.size();
  CHECK(!up.empty() && quads > 1000);
  // Same place: nothing to do.
  ts.set_view(vx, vz);
  CHECK_EQ(ts.pending(), 0u);
  // One lod-1 chunk east: only columns along the moving edges are rebuilt.
  ts.set_view(vx + 128, vz);
  size_t jobs = ts.pending();
  CHECK(jobs > 0 && jobs < 40);
  up.clear();
  while (!ts.update(1e9, up)) {}
  // Dig a 30 cm hole in the ground under the viewer.
  int64_t gy = w.src.ground_voxel_y(vx, vz);
  CHECK(cache.voxel(vx, gy - 3, vz) != kAir);
  auto changed = cache.edit_sphere(vx, gy, vz, 15, kAir);
  CHECK(!changed.empty());
  CHECK(cache.voxel(vx, gy - 3, vz) == kAir);
  ts.mark_edited(changed);
  CHECK(ts.pending() > 0);
  up.clear();
  while (!ts.update(1e9, up)) {}
  CHECK(!up.empty());
  for (auto& r : up) CHECK(r.key.lod == 0);
}

EMERGENCE_TEST_MAIN()
