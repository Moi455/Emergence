// Determinism and consistency tests of the fine generator, on a 4 km map
// (same layout as the 20 km one, every horizontal distance scaled).
#include <algorithm>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <map>
#include <memory>
#include <string>
#include <vector>

#include "emergence/base/fingerprint.h"
#include "emergence/base/fixed.h"
#include "emergence/base/hash.h"
#include "emergence/base/parallel.h"
#include "emergence/testing/check.h"
#include "emergence/worldgen/worldgen.h"

using namespace em;
using namespace em::wg;

namespace {

constexpr uint64_t kSeed = 7;
constexpr int32_t kSize = 4000;

const WorldPlan& plan() {
  static WorldPlan p = generate_world_plan(WorldParams::scaled(kSeed, kSize));
  return p;
}
const WorldGen& gen() {
  static WorldGen g(plan());
  return g;
}

ChunkKey surface_key(const WorldGen& g, int64_t x, int64_t z, int lod, int dy = 0) {
  int64_t S = chunk_mm(lod);
  int64_t h = g.ground_mm(x, z, lod);
  return {static_cast<int32_t>(x / S), static_cast<int32_t>(floor_div(h, S)) + dy,
          static_cast<int32_t>(z / S), static_cast<uint8_t>(lod)};
}

// Reference chunks: around each settlement, on a diagonal across the map
// (sea, core, desert), in the forest march, underground and in the air.
std::vector<ChunkKey> reference_keys(const WorldGen& g) {
  std::vector<ChunkKey> keys;
  const int64_t map = int64_t{g.plan().n} * g.plan().cell_mm;
  for (const auto& pad : g.settlement_pads()) keys.push_back(surface_key(g, pad.x_mm + 150000, pad.z_mm, 0));
  for (int k = 1; k < 8; ++k) {
    int64_t x = map * k / 8, z = map * (8 - k) / 8;
    keys.push_back(surface_key(g, x, z, 0));
    keys.push_back(surface_key(g, x, z, 0, 1));
    keys.push_back(surface_key(g, x, z, 0, -3));
    keys.push_back(surface_key(g, x, z, 2));
  }
  keys.push_back(surface_key(g, map / 2, map / 30, 0));      // forest march (south)
  keys.push_back(surface_key(g, map / 2, map / 30, 0, 4));
  keys.push_back(surface_key(g, map / 2, map - map / 20, 0)); // mountains (north)
  for (const auto& c : g.cave_segments()) {  // inside a cave
    keys.push_back({static_cast<int32_t>(c.ax / chunk_mm(0)), static_cast<int32_t>(floor_div(c.ay, chunk_mm(0))),
                    static_cast<int32_t>(c.az / chunk_mm(0)), 0});
    if (keys.size() > 40) break;
  }
  return keys;
}

std::vector<uint64_t> fingerprints(const WorldGen& g, const std::vector<ChunkKey>& keys) {
  std::vector<uint64_t> out(keys.size());
  parallel_for(0, static_cast<int64_t>(keys.size()), [&](int64_t a, int64_t b) {
    std::vector<VoxelId> vox(kChunkVoxels);
    for (int64_t i = a; i < b; ++i) {
      g.generate(keys[static_cast<size_t>(i)], vox.data());
      out[static_cast<size_t>(i)] = WorldGen::chunk_fingerprint(vox.data());
    }
  });
  return out;
}

}  // namespace

TEST(same_seed_same_chunks) {
  WorldPlan p2 = generate_world_plan(WorldParams::scaled(kSeed, kSize));
  CHECK_EQ(p2.fingerprint(), plan().fingerprint());
  WorldGen g2(p2);
  auto keys = reference_keys(gen());
  set_worker_count(1);
  auto a = fingerprints(gen(), keys);
  set_worker_count(4);
  auto b = fingerprints(g2, keys);
  std::reverse(keys.begin(), keys.end());
  auto c = fingerprints(gen(), keys);
  std::reverse(c.begin(), c.end());
  CHECK(a == b);
  CHECK(a == c);
}

TEST(other_seed_other_chunks) {
  WorldPlan p2 = generate_world_plan(WorldParams::scaled(kSeed + 1, kSize));
  WorldGen g2(p2);
  std::vector<VoxelId> a(kChunkVoxels), b(kChunkVoxels);
  ChunkKey k = surface_key(gen(), 2000000, 2000000, 0);
  gen().generate(k, a.data());
  g2.generate(k, b.data());
  CHECK(WorldGen::chunk_fingerprint(a.data()) != WorldGen::chunk_fingerprint(b.data()));
}

// classify() promises Air and Solid exactly: check against the real content
// on whole columns of chunks at many places.
TEST(classify_matches_content) {
  const WorldGen& g = gen();
  const int64_t map = int64_t{g.plan().n} * g.plan().cell_mm;
  std::vector<VoxelId> vox(kChunkVoxels);
  int air = 0, solid = 0, mixed = 0, wrong = 0;
  for (int k = 0; k < 24; ++k) {
    uint64_t h = hash2(99, k, 0);
    int64_t x = static_cast<int64_t>(h % static_cast<uint64_t>(map)), z = static_cast<int64_t>((h >> 32) % static_cast<uint64_t>(map));
    ChunkKey base = surface_key(g, x, z, k % 3);
    for (int dy = -6; dy <= 10; ++dy) {
      ChunkKey key = base;
      key.y += dy;
      ChunkInfo c = g.classify(key);
      ChunkInfo r = g.generate_unclassified(key, vox.data());
      if (c.kind == ChunkKind::Air) { ++air; if (r.kind != ChunkKind::Air) ++wrong; }
      else if (c.kind == ChunkKind::Solid) { ++solid; if (r.kind != ChunkKind::Solid) ++wrong; }
      else ++mixed;
    }
  }
  std::printf("  classify: %d air, %d solid, %d mixed\n", air, solid, mixed);
  CHECK_EQ(wrong, 0);
  CHECK(air > 0);
  CHECK(solid > 0);
}

// The top of each column sits at ground_mm() (trees and boulders aside).
TEST(ground_matches_voxels) {
  const WorldGen& g = gen();
  std::vector<VoxelId> lo(kChunkVoxels), hi(kChunkVoxels);
  int checked = 0, bad = 0;
  for (int k = 0; k < 12; ++k) {
    int64_t x = 400000 + k * 270000, z = 3600000 - k * 260000;
    for (int lod = 0; lod < 3; ++lod) {
      ChunkKey key = surface_key(g, x, z, lod, -1);
      ChunkKey up = key;
      up.y += 1;
      g.generate(key, lo.data());
      g.generate(up, hi.data());
      const int64_t S = chunk_mm(lod), v = voxel_mm(lod);
      for (int cz = 0; cz < kChunkSize; cz += 7)
        for (int cx = 0; cx < kChunkSize; cx += 7) {
          int64_t wx = int64_t{key.x} * S + cx * v + v / 2, wz = int64_t{key.z} * S + cz * v + v / 2;
          int64_t gy = g.ground_mm(wx, wz, lod);
          int64_t oy = int64_t{key.y} * S;
          int iy = static_cast<int>(floor_div(gy - oy - v / 2 - 1, v));  // last voxel centre below ground
          if (iy < 0 || iy + 1 >= 2 * kChunkSize) continue;
          auto at = [&](int y) { return y < kChunkSize ? lo[voxel_index(cx, y, cz)] : hi[voxel_index(cx, y - kChunkSize, cz)]; };
          ++checked;
          if (at(iy) == kAir) {  // a cave mouth can do this, rarely
            ++bad;
            if (std::getenv("WG_DEBUG"))
              std::printf("    lod %d x %lld z %lld g %lld iy %d below %d above %d\n", lod, (long long)wx, (long long)wz, (long long)gy, iy,
                          iy > 0 ? at(iy - 1) : -1, at(iy + 1));
          }
        }
    }
  }
  std::printf("  ground: %d columns checked, %d without ground voxel\n", checked, bad);
  CHECK(checked > 500);
  CHECK(bad * 100 <= checked);
}

TEST(lod_surfaces_agree) {
  const WorldGen& g = gen();
  int64_t worst = 0;
  for (int k = 0; k < 400; ++k) {
    uint64_t h = hash2(5, k, 1);
    int64_t x = 100000 + static_cast<int64_t>(h % 3800000), z = 100000 + static_cast<int64_t>((h >> 32) % 3800000);
    int64_t a = g.ground_mm(x, z, 0), b = g.ground_mm(x, z, 3);
    worst = std::max(worst, abs64(a - b));
  }
  std::printf("  worst ground gap between lod 0 and lod 3: %lld mm\n", static_cast<long long>(worst));
  CHECK(worst < 1500);
}

TEST(trees_partition_and_stable_ids) {
  const WorldGen& g = gen();
  std::vector<TreeInstance> all, left, right;
  g.trees_in(1000000, 1000000, 1400000, 1400000, &all);
  g.trees_in(1000000, 1000000, 1200000, 1400000, &left);
  g.trees_in(1200000, 1000000, 1400000, 1400000, &right);
  CHECK_EQ(all.size(), left.size() + right.size());
  std::map<uint64_t, int> ids;
  for (const auto& t : all) ids[t.id]++;
  CHECK_EQ(ids.size(), all.size());
  std::printf("  %zu trees in 400 m x 400 m\n", all.size());
}

TEST(caves_exist_and_stay_in_the_world) {
  const WorldGen& g = gen();
  CaveStats s = g.cave_stats();
  std::printf("  caves: %zu systems, %zu segments, %zu chambers, %zu entrances\n", s.systems, s.segments, s.chambers, s.entrances);
  CHECK(s.systems > 0);
  for (const auto& c : g.cave_segments()) {
    CHECK(c.ay - c.ra > kWorldBottomMm);
    CHECK(c.by - c.rb > kWorldBottomMm);
  }
}

TEST(brick_storage_roundtrip) {
  ChunkKey k = surface_key(gen(), 1500000, 1700000, 0);
  std::vector<VoxelId> dense(kChunkVoxels), back(kChunkVoxels);
  gen().generate(k, dense.data());
  Chunk c;
  gen().generate(ChunkCoord{k.x, k.y, k.z}, c);
  c.decode(back);
  CHECK(dense == back);
  std::printf("  surface chunk in bricks: %zu bytes (%d uniform bricks of 512)\n", c.memory_bytes(), c.uniform_brick_count());
}

TEST(out_of_world) {
  std::vector<VoxelId> vox(kChunkVoxels, 1);
  CHECK(gen().classify({-1, 3, 5, 0}).kind == ChunkKind::OutOfWorld);
  CHECK(gen().generate({5, -400, 5, 0}, vox.data()).kind == ChunkKind::OutOfWorld);
  CHECK(gen().classify({5, -390, 5, 0}).kind == ChunkKind::Solid);  // straddles the world bottom
  CHECK_EQ(vox[123], kAir);
}

// Golden fingerprints, written by `worldgen_tool golden` and compared across
// compilers and machines (scripts/check_determinism.sh).
TEST(golden_fingerprints) {
  const char* path = std::getenv("WORLDGEN_GOLDEN");
  std::string file = path ? path : EMERGENCE_WORLDGEN_GOLDEN;
  auto keys = reference_keys(gen());
  auto fps = fingerprints(gen(), keys);
  Fingerprint all;
  for (uint64_t f : fps) all.add_u64(f);
  if (std::getenv("WORLDGEN_WRITE_GOLDEN")) {
    std::ofstream o(file);
    o << "plan " << to_hex(plan().fingerprint()) << "\nchunks " << to_hex(all.value()) << "\n";
    std::printf("  golden written to %s\n", file.c_str());
    return;
  }
  std::ifstream in(file);
  if (!in) {
    std::printf("  no golden file at %s, skipped\n", file.c_str());
    return;
  }
  std::string key, value;
  std::map<std::string, std::string> golden;
  while (in >> key >> value) golden[key] = value;
  CHECK(golden["plan"] == to_hex(plan().fingerprint()));
  CHECK(golden["chunks"] == to_hex(all.value()));
  std::printf("  plan %s chunks %s\n", to_hex(plan().fingerprint()).c_str(), to_hex(all.value()).c_str());
}

EMERGENCE_TEST_MAIN()
