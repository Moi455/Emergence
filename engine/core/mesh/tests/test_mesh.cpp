#include <set>
#include <tuple>
#include <vector>

#include "emergence/base/hash.h"
#include "emergence/mesh/greedy.h"
#include "emergence/testing/check.h"

using namespace em;

namespace {

void fill(Chunk& c, VoxelId (*f)(int, int, int)) {
  c.clear();
  VoxelId b[kVoxelsPerBrick];
  for (int by = 0; by < 8; ++by)
    for (int bz = 0; bz < 8; ++bz)
      for (int bx = 0; bx < 8; ++bx) {
        for (int y = 0; y < 8; ++y)
          for (int z = 0; z < 8; ++z)
            for (int x = 0; x < 8; ++x) b[in_brick_index(x, y, z)] = f(bx * 8 + x, by * 8 + y, bz * 8 + z);
        c.set_brick(brick_index(bx, by, bz), b);
      }
}

using Face = std::tuple<int, int, int, int>;  // x, y, z, dir

// Unit faces covered by quads; returns false on overlap.
bool rasterize(const std::vector<Quad>& qs, std::set<Face>& out) {
  for (const Quad& q : qs) {
    for (int a = 0; a < q.w(); ++a)
      for (int b = 0; b < q.h(); ++b) {
        int x = q.x(), y = q.y(), z = q.z();
        switch (q.dir()) {
          case FaceDir::PosX: case FaceDir::NegX: z += a; y += b; break;
          case FaceDir::PosY: case FaceDir::NegY: x += a; z += b; break;
          default: x += a; y += b; break;
        }
        if (!out.insert({x, y, z, static_cast<int>(q.dir())}).second) return false;
      }
  }
  return true;
}

}  // namespace

TEST(single_voxel_six_quads) {
  Chunk c;
  fill(c, [](int x, int y, int z) -> VoxelId { return x == 3 && y == 4 && z == 5 ? make_voxel(8) : kAir; });
  std::vector<Quad> q;
  MeshStats st = mesh_chunk(c, {}, q);
  CHECK_EQ(q.size(), 6u);
  CHECK_EQ(st.faces, 6u);
  for (const Quad& k : q) CHECK(k.x() == 3 && k.y() == 4 && k.z() == 5 && k.w() == 1 && k.h() == 1 && k.cls() == 8);
}

TEST(full_chunk_and_borders) {
  Chunk c;
  c.clear(make_voxel(10));
  std::vector<Quad> q;
  mesh_chunk(c, {}, q);
  CHECK_EQ(q.size(), 6u);
  for (const Quad& k : q) CHECK(k.w() == 64 && k.h() == 64);
  ChunkBorders all;
  for (auto& f : all.solid) f.fill(~uint64_t{0});
  q.clear();
  mesh_chunk(c, all, q);
  CHECK_EQ(q.size(), 0u);
}

TEST(merges_on_class_only) {
  Chunk c;
  // Same class, different tints: one quad per side.
  fill(c, [](int x, int, int) -> VoxelId { return make_voxel(10, static_cast<uint8_t>(x)); });
  std::vector<Quad> q;
  mesh_chunk(c, {}, q);
  CHECK_EQ(q.size(), 6u);
  // Two classes stacked: sides split in two, no face between them.
  fill(c, [](int, int y, int) -> VoxelId { return make_voxel(y < 32 ? 10 : 8); });
  q.clear();
  mesh_chunk(c, {}, q);
  CHECK_EQ(q.size(), 10u);
}

TEST(random_fill_matches_brute_force) {
  Chunk c;
  fill(c, [](int x, int y, int z) -> VoxelId {
    uint64_t h = hash3(5, x / 3, y / 2, z);
    return (h & 3) == 0 ? kAir : make_voxel(static_cast<MaterialClass>(1 + (h >> 8) % 3));
  });
  ChunkBorders borders;
  for (int r = 0; r < 64; ++r) borders.solid[static_cast<size_t>(FaceDir::PosY)][static_cast<size_t>(r)] = hash2(9, r, 0);
  std::vector<Quad> q;
  MeshStats st = mesh_chunk(c, borders, q);
  std::set<Face> got;
  CHECK(rasterize(q, got));
  std::set<Face> want;
  auto solid = [&](int x, int y, int z) -> bool {
    if (x >= 0 && y >= 0 && z >= 0 && x < 64 && y < 64 && z < 64) return c.get(x, y, z) != kAir;
    if (y == 64 && x >= 0 && x < 64 && z >= 0 && z < 64)
      return (borders.solid[static_cast<size_t>(FaceDir::PosY)][static_cast<size_t>(z)] >> x) & 1;
    return false;
  };
  const int d[6][3] = {{1, 0, 0}, {-1, 0, 0}, {0, 1, 0}, {0, -1, 0}, {0, 0, 1}, {0, 0, -1}};
  for (int y = 0; y < 64; ++y)
    for (int z = 0; z < 64; ++z)
      for (int x = 0; x < 64; ++x) {
        if (!solid(x, y, z)) continue;
        for (int k = 0; k < 6; ++k)
          if (!solid(x + d[k][0], y + d[k][1], z + d[k][2])) want.insert({x, y, z, k});
      }
  CHECK(got == want);
  CHECK_EQ(st.faces, want.size());
  // Every quad has a single class.
  bool ok = true;
  for (const Quad& k : q) ok &= voxel_class(c.get(k.x(), k.y(), k.z())) == k.cls();
  CHECK(ok);
  CHECK(st.quads < st.faces);
}

TEST(downsample_keeps_shape) {
  Chunk solid, empty, wall;
  solid.clear(make_voxel(10));
  empty.clear();
  // One-voxel-thick wall at x = 0: 4 of 8 voxels of each coarse cell when aligned.
  fill(wall, [](int x, int, int) -> VoxelId { return x == 0 ? make_voxel(17) : kAir; });
  Chunk out;
  downsample({&solid, &solid, &solid, &solid, &solid, &solid, &solid, &solid}, out);
  VoxelId v = 0;
  CHECK(out.is_uniform(&v) && v == make_voxel(10));
  downsample({&solid, &solid, &solid, &solid, nullptr, nullptr, nullptr, nullptr}, out);
  CHECK(out.get(10, 10, 10) == make_voxel(10) && out.get(10, 40, 10) == kAir);
  downsample({&wall, &empty, &wall, &empty, &wall, &empty, &wall, &empty}, out);
  CHECK(out.get(0, 5, 5) == make_voxel(17) && out.get(1, 5, 5) == kAir);
}

EMERGENCE_TEST_MAIN()
