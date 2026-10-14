// Where chunks come from, at any level of detail. The renderer, the streamer
// and the edit path only see this interface; the generator behind it is the
// worldgen module (em::wg::WorldGen) in the game, or the engine's minimal
// ChunkGenerator in tests and tools.
#pragma once
#include <cstdint>

#include "emergence/world/chunk.h"
#include "emergence/world/chunk_gen.h"

namespace em {

enum class SourceKind : uint8_t { Air, Solid, Mixed };

class ChunkSource {
 public:
  virtual ~ChunkSource() = default;
  // True when fill() works at lod > 0 directly; otherwise the cache
  // downsamples eight finer chunks.
  virtual bool native_lod() const = 0;
  // Cheap and conservative: Air and Solid are promises (with their voxel).
  virtual SourceKind classify(int lod, ChunkCoord c, VoxelId* uniform) const = 0;
  // Fills one chunk of 64^3 voxels of 2 cm << lod. Must be thread-safe.
  virtual void fill(int lod, ChunkCoord c, Chunk& out) const = 0;
  // Ground height in 2 cm voxels at a column given in 2 cm voxels.
  virtual int32_t ground_voxel_y(int64_t vx, int64_t vz) const = 0;
  // Map extent in 2 cm voxels (x and z).
  virtual int64_t map_voxels() const = 0;
};

// Adapter for the engine's minimal generator (lod 0 only).
class BasicChunkSource final : public ChunkSource {
 public:
  explicit BasicChunkSource(const ChunkGenerator& gen) : gen_(gen) {}
  bool native_lod() const override { return false; }
  SourceKind classify(int lod, ChunkCoord c, VoxelId* uniform) const override {
    if (lod != 0) return SourceKind::Mixed;
    VoxelId v = kAir;
    auto k = gen_.classify(c, &v);
    if (uniform) *uniform = v;
    return k == ChunkGenerator::Kind::Air ? SourceKind::Air
           : k == ChunkGenerator::Kind::Solid ? SourceKind::Solid : SourceKind::Mixed;
  }
  void fill(int, ChunkCoord c, Chunk& out) const override { gen_.generate(c, out); }
  int32_t ground_voxel_y(int64_t vx, int64_t vz) const override { return gen_.surface_voxel_y(vx, vz); }
  int64_t map_voxels() const override { return gen_.map_voxels(); }

 private:
  const ChunkGenerator& gen_;
};

}  // namespace em
