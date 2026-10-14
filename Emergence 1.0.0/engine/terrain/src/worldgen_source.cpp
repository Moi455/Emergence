#include "emergence/terrain/worldgen_source.h"

#include <vector>

#include "emergence/base/fixed.h"

namespace em {

SourceKind WorldGenSource::classify(int lod, ChunkCoord c, VoxelId* uniform) const {
  wg::ChunkInfo info = gen_.classify({c.x, c.y, c.z, static_cast<uint8_t>(lod)});
  if (uniform) *uniform = info.kind == wg::ChunkKind::Solid ? info.voxel : kAir;
  switch (info.kind) {
    case wg::ChunkKind::Air:
    case wg::ChunkKind::OutOfWorld: return SourceKind::Air;
    case wg::ChunkKind::Solid: return SourceKind::Solid;
    default: return SourceKind::Mixed;
  }
}

void WorldGenSource::fill(int lod, ChunkCoord c, Chunk& out) const {
  thread_local std::vector<VoxelId> dense(wg::kChunkVoxels);
  wg::ChunkInfo info = gen_.generate({c.x, c.y, c.z, static_cast<uint8_t>(lod)}, dense.data());
  out.coord = c;
  if (info.kind != wg::ChunkKind::Mixed) {
    out.clear(info.kind == wg::ChunkKind::Solid ? dense[0] : kAir);
    return;
  }
  out.clear();
  VoxelId brick[kVoxelsPerBrick];
  for (int by = 0; by < kBricksPerChunk; ++by)
    for (int bz = 0; bz < kBricksPerChunk; ++bz)
      for (int bx = 0; bx < kBricksPerChunk; ++bx) {
        for (int y = 0; y < kBrickSize; ++y)
          for (int z = 0; z < kBrickSize; ++z)
            for (int x = 0; x < kBrickSize; ++x)
              brick[in_brick_index(x, y, z)] =
                  dense[static_cast<size_t>(wg::voxel_index(bx * kBrickSize + x, by * kBrickSize + y, bz * kBrickSize + z))];
        out.set_brick(brick_index(bx, by, bz), brick);
      }
  out.compact();
}

int32_t WorldGenSource::ground_voxel_y(int64_t vx, int64_t vz) const {
  return static_cast<int32_t>(floor_div(gen_.ground_mm(vx * kVoxelMm, vz * kVoxelMm), kVoxelMm));
}

int64_t WorldGenSource::map_voxels() const { return int64_t{gen_.plan().params.size_m} * 1000 / kVoxelMm; }

}  // namespace em
