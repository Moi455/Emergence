// The game's chunk source: the worldgen module (emergence/worldgen, owned by
// the world generation thread) behind the engine's ChunkSource interface.
#pragma once
#include "emergence/mesh/chunk_source.h"
#include "emergence/worldgen/worldgen.h"

namespace em {

class WorldGenSource final : public ChunkSource {
 public:
  explicit WorldGenSource(const wg::WorldGen& gen) : gen_(gen) {}
  bool native_lod() const override { return true; }
  SourceKind classify(int lod, ChunkCoord c, VoxelId* uniform) const override;
  void fill(int lod, ChunkCoord c, Chunk& out) const override;
  int32_t ground_voxel_y(int64_t vx, int64_t vz) const override;
  int64_t map_voxels() const override;
  const wg::WorldGen& worldgen() const { return gen_; }

 private:
  const wg::WorldGen& gen_;
};

}  // namespace em
