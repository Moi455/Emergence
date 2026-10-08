#include "emergence/mesh/chunk_cache.h"

namespace em {

const Chunk& ChunkCache::get(int lod, int x, int y, int z) {
  auto key = std::make_tuple(lod, x, y, z);
  auto it = cache_.find(key);
  if (it != cache_.end()) return it->second;
  Chunk c;
  if (lod == 0) {
    VoxelId v = kAir;
    if (gen_.classify({x, y, z}, &v) == ChunkGenerator::Kind::Mixed) gen_.generate({x, y, z}, c);
    else c.clear(v);
  } else {
    std::array<const Chunk*, 8> kids{};
    for (int k = 0; k < 8; ++k)
      kids[static_cast<size_t>(k)] = &get(lod - 1, 2 * x + (k & 1), 2 * y + (k >> 2), 2 * z + ((k >> 1) & 1));
    downsample(kids, c);
  }
  c.coord = {x, y, z};
  return cache_.emplace(key, std::move(c)).first->second;
}

MeshStats ChunkCache::mesh(int lod, int x, int y, int z, std::vector<Quad>& out) {
  static const int nb[6][3] = {{1, 0, 0}, {-1, 0, 0}, {0, 1, 0}, {0, -1, 0}, {0, 0, 1}, {0, 0, -1}};
  ChunkBorders b;
  for (int d = 0; d < 6; ++d)
    border_from_neighbor(get(lod, x + nb[d][0], y + nb[d][1], z + nb[d][2]), static_cast<FaceDir>(d),
                         b.solid[static_cast<size_t>(d)]);
  return mesh_chunk(get(lod, x, y, z), b, out);
}

}  // namespace em
