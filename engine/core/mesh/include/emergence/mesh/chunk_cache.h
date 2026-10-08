// Chunks by level of detail, generated or downsampled on demand and kept in
// memory. A stop-gap until the streaming module: no eviction, one thread.
#pragma once
#include <map>
#include <tuple>
#include <vector>

#include "emergence/mesh/greedy.h"
#include "emergence/world/chunk_gen.h"

namespace em {

class ChunkCache {
 public:
  explicit ChunkCache(const ChunkGenerator& gen) : gen_(gen) {}
  const Chunk& get(int lod, int x, int y, int z);
  // Meshes chunk (lod, x, y, z) with the borders of its six neighbours.
  MeshStats mesh(int lod, int x, int y, int z, std::vector<Quad>& out);
  size_t size() const { return cache_.size(); }

 private:
  const ChunkGenerator& gen_;
  std::map<std::tuple<int, int, int, int>, Chunk> cache_;
};

}  // namespace em
