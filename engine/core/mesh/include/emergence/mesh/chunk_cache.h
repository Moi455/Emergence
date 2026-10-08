// Chunks by level of detail, generated on demand from a ChunkSource and kept
// in memory, plus the player's edits (lod 0). Reads may run on several
// threads at once; inserts (get of a missing chunk, prefetch, edits) may not.
#pragma once
#include <cstdint>
#include <map>
#include <memory>
#include <set>
#include <tuple>
#include <vector>

#include "emergence/mesh/chunk_source.h"
#include "emergence/mesh/greedy.h"
#include "emergence/world/chunk_gen.h"

namespace em {

struct LodChunk {
  int lod = 0;
  int32_t x = 0, y = 0, z = 0;
  auto tie() const { return std::tie(lod, x, y, z); }
  bool operator<(const LodChunk& o) const { return tie() < o.tie(); }
  bool operator==(const LodChunk& o) const { return tie() == o.tie(); }
};

class ChunkCache {
 public:
  explicit ChunkCache(const ChunkSource& src) : src_(src) {}
  // Convenience for tools and tests: wraps the engine's minimal generator.
  explicit ChunkCache(const ChunkGenerator& gen)
      : own_(std::make_unique<BasicChunkSource>(gen)), src_(*own_) {}

  const ChunkSource& source() const { return src_; }
  const Chunk& get(int lod, int x, int y, int z);
  const Chunk* find(int lod, int x, int y, int z) const;
  // Generates the missing chunks in parallel (sources with native LOD).
  void prefetch(const std::vector<LodChunk>& keys);

  // Meshes chunk (lod, x, y, z) against its six neighbours. Bit d of
  // open_sides (FaceDir order) treats that neighbour as air, which closes the
  // chunk with a wall there: the skirt that hides cracks between LOD rings.
  MeshStats mesh(int lod, int x, int y, int z, std::vector<Quad>& out, uint8_t open_sides = 0, bool ao = true);

  // Player edits at lod 0: every voxel whose centre lies inside the sphere
  // (centre and radius in 2 cm voxels) becomes `v`. Returns the chunks changed.
  std::vector<LodChunk> edit_sphere(int64_t cx, int64_t cy, int64_t cz, int64_t radius, VoxelId v);
  VoxelId voxel(int64_t vx, int64_t vy, int64_t vz);  // lod 0
  bool edited(const LodChunk& k) const { return edited_.count(k) != 0; }

  // Drops chunks of `lod` outside the chunk range [x0, x1] x [z0, z1]; edits stay.
  void evict_outside(int lod, int64_t x0, int64_t z0, int64_t x1, int64_t z1);
  size_t size() const { return cache_.size(); }
  size_t memory_bytes() const;

 private:
  Chunk make(int lod, int x, int y, int z);
  void border(int lod, int x, int y, int z, FaceDir d, std::array<uint64_t, 64>& out);

  std::unique_ptr<BasicChunkSource> own_;
  const ChunkSource& src_;
  std::map<LodChunk, Chunk> cache_;
  std::set<LodChunk> edited_;
};

}  // namespace em
