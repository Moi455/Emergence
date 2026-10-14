#include <cstdio>
#include <vector>

#include "emergence/base/fingerprint.h"
#include "emergence/base/fixed.h"
#include "emergence/base/hash.h"
#include "emergence/testing/check.h"
#include "emergence/world/chunk.h"
#include "emergence/world/chunk_gen.h"
#include "emergence/world/materials.h"
#include "emergence/world/world_plan.h"

using namespace em;

namespace {

const WorldPlan& plan() {
  static const WorldPlan p = generate_world_plan(WorldParams::scaled(7, 4096));
  return p;
}
const ChunkGenerator& gen() {
  static const ChunkGenerator g(plan(), MaterialTable::builtin());
  return g;
}

// Chunk containing the surface at a voxel column.
ChunkCoord surface_chunk(int64_t vx, int64_t vz) {
  int32_t s = gen().surface_voxel_y(vx, vz);
  return {static_cast<int32_t>(vx / kChunkSize), static_cast<int32_t>(floor_div(s, kChunkSize)),
          static_cast<int32_t>(vz / kChunkSize)};
}

}  // namespace

TEST(material_table_loads) {
  const MaterialTable& m = MaterialTable::builtin();
  CHECK_EQ(m.schema_version(), 1);
  CHECK_EQ(m.require("air"), 0);
  CHECK(m.size() >= 20);
  CHECK_EQ(voxel_class(make_voxel(m.require("granite"), 77)), m.require("granite"));
  CHECK_EQ(voxel_tint(make_voxel(m.require("granite"), 77)), 77);
  MaterialTable bad;
  std::string err;
  CHECK(!bad.parse_csv("schema_version,1\nid,name,category,density_kg_m3,hardness,flammability,color\n0,air,gas,1,0,0,0\n0,x,gas,1,0,0,0\n", &err));
}

TEST(brick_roundtrip) {
  for (int distinct : {1, 2, 3, 5, 16, 17, 255, 256, 300}) {
    Chunk c;
    c.clear();
    VoxelId in[kVoxelsPerBrick], out[kVoxelsPerBrick];
    for (int k = 0; k < kVoxelsPerBrick; ++k)
      in[k] = static_cast<VoxelId>(1 + (k * 7 + k / 64) % distinct);
    c.set_brick(5, in);
    c.decode_brick(5, out);
    bool same = true;
    for (int k = 0; k < kVoxelsPerBrick; ++k) same &= in[k] == out[k];
    CHECK(same);
    for (int y = 0; y < 8; ++y)
      for (int z = 0; z < 8; ++z)
        for (int x = 0; x < 8; ++x) same &= c.get(40 + x, y, z) == in[in_brick_index(x, y, z)];
    CHECK(same);
    if (distinct == 1) CHECK_EQ(c.brick(5).bits, 0);
    if (distinct == 2) CHECK_EQ(c.brick(5).bits, 1);
    if (distinct == 5) CHECK_EQ(c.brick(5).bits, 4);
    if (distinct == 300) CHECK_EQ(c.brick(5).bits, 16);
    // Rewriting then compacting keeps the content.
    c.set_brick(5, in);
    c.compact();
    c.decode_brick(5, out);
    for (int k = 0; k < kVoxelsPerBrick; ++k) same &= in[k] == out[k];
    CHECK(same);
  }
}

TEST(generation_is_deterministic) {
  int64_t vx = plan().settlements[0].i * plan().cell_mm / kVoxelMm;
  int64_t vz = plan().settlements[0].j * plan().cell_mm / kVoxelMm;
  ChunkCoord cc = surface_chunk(vx, vz);
  Chunk a, b;
  gen().generate(cc, a);
  gen().generate(cc, b);
  CHECK_EQ(a.fingerprint(), b.fingerprint());
  CHECK(!a.is_uniform());
}

TEST(surface_matches_generated_columns_across_borders) {
  // Two neighbouring chunks: every column's first air voxel must sit exactly
  // at surface_voxel_y, including on the shared border (no seams).
  int64_t vx = plan().settlements[1].i * plan().cell_mm / kVoxelMm;
  int64_t vz = plan().settlements[1].j * plan().cell_mm / kVoxelMm;
  ChunkCoord c0 = surface_chunk(vx, vz);
  int bad = 0, checked = 0;
  for (int dx = 0; dx < 2; ++dx) {
    for (int dy = -1; dy <= 1; ++dy) {
      ChunkCoord cc{c0.x + dx, c0.y + dy, c0.z};
      Chunk ch;
      gen().generate(cc, ch);
      for (int z = 0; z < kChunkSize; z += 7)
        for (int x = 0; x < kChunkSize; ++x) {
          int64_t gx = int64_t{cc.x} * kChunkSize + x, gz = int64_t{cc.z} * kChunkSize + z;
          int32_t s = gen().surface_voxel_y(gx, gz) - cc.y * kChunkSize;
          if (s <= 0 || s >= kChunkSize) continue;
          ++checked;
          bad += ch.get(x, s, z) != kAir || ch.get(x, s - 1, z) == kAir;
        }
    }
  }
  CHECK(checked > 100);
  CHECK_EQ(bad, 0);
}

TEST(classify_agrees_with_generation) {
  int mismatches = 0, implicit = 0;
  for (int k = 0; k < 40; ++k) {
    int64_t vx = static_cast<int64_t>(mix64(static_cast<uint64_t>(k)) % static_cast<uint64_t>(gen().map_voxels()));
    int64_t vz = static_cast<int64_t>(mix64(static_cast<uint64_t>(k) + 1000) % static_cast<uint64_t>(gen().map_voxels()));
    ChunkCoord s = surface_chunk(vx, vz);
    for (int dy : {-40, -8, -3, -1, 1, 3, 30}) {
      ChunkCoord cc{s.x, s.y + dy, s.z};
      VoxelId v = 0;
      auto kind = gen().classify(cc, &v);
      if (kind == ChunkGenerator::Kind::Mixed) continue;
      ++implicit;
      Chunk ch;
      gen().generate(cc, ch);
      VoxelId got = 0;
      bool uni = ch.is_uniform(&got);
      if (kind == ChunkGenerator::Kind::Air) mismatches += !(uni && got == kAir);
      else mismatches += !(uni && got == v);
    }
  }
  std::printf("  %d implicit chunks checked\n", implicit);
  CHECK(implicit > 60);
  CHECK_EQ(mismatches, 0);
}

TEST(chunk_golden_fingerprints) {
  // Pinned with the plan fingerprint; see test_world_plan.
  Fingerprint f;
  for (const auto& s : plan().settlements) {
    ChunkCoord cc = surface_chunk(s.i * plan().cell_mm / kVoxelMm, s.j * plan().cell_mm / kVoxelMm);
    Chunk ch;
    gen().generate(cc, ch);
    f.add_u64(ch.fingerprint());
  }
  std::printf("  settlement chunks fingerprint %s\n", f.hex().c_str());
  CHECK_EQ(f.value(), 0x96e9fd423333928aULL);
}

EMERGENCE_TEST_MAIN()
