// Chunk storage (architecture § 3.1): 64^3 voxels = 1.28 m, split into 8^3
// storage bricks of 16 cm. A brick is either uniform (one VoxelId, no data)
// or a local palette plus 1, 2, 4, 8 or 16 bits per voxel.
// Write access is meant for the generator and, later, the `ops` module only
// (invariant I4); everything else reads.
#pragma once
#include <array>
#include <cstdint>
#include <span>
#include <vector>

#include "emergence/world/voxel_id.h"

namespace em {

struct ChunkCoord {
  int32_t x = 0, y = 0, z = 0;  // in chunks; voxel = coord * 64 + local
  bool operator==(const ChunkCoord&) const = default;
};

constexpr int kVoxelsPerChunk = kChunkSize * kChunkSize * kChunkSize;  // 262144
constexpr int kVoxelsPerBrick = kBrickSize * kBrickSize * kBrickSize;  // 512
constexpr int kBricks = kBricksPerChunk * kBricksPerChunk * kBricksPerChunk;  // 512

// Dense index inside a chunk: x fastest, then z, then y.
constexpr int chunk_index(int x, int y, int z) { return (y * kChunkSize + z) * kChunkSize + x; }
constexpr int brick_index(int bx, int by, int bz) { return (by * kBricksPerChunk + bz) * kBricksPerChunk + bx; }
constexpr int in_brick_index(int x, int y, int z) { return (y * kBrickSize + z) * kBrickSize + x; }

struct BrickHeader {
  uint32_t offset = 0;      // into the pool: palette (u16 each) then packed indices
  uint8_t bits = 0;         // 0 = uniform
  uint8_t palette_size = 0; // 0 means 256 when bits == 8; unused when bits == 16
  VoxelId value = kAir;     // uniform value
};

class Chunk {
 public:
  ChunkCoord coord;

  void clear(VoxelId fill = kAir);
  VoxelId get(int x, int y, int z) const;
  void decode(std::span<VoxelId> out) const;  // out.size() == kVoxelsPerChunk
  void decode_brick(int b, VoxelId* out512) const;

  // Encoders (generator / ops). A rewritten brick leaves its old data in the
  // pool until compact() is called.
  void set_brick_uniform(int b, VoxelId v);
  void set_brick(int b, const VoxelId* voxels512);
  void compact();

  const BrickHeader& brick(int b) const { return bricks_[static_cast<size_t>(b)]; }
  bool is_uniform(VoxelId* value = nullptr) const;
  int uniform_brick_count() const;
  size_t pool_bytes() const { return pool_.size(); }
  // Compact size estimate: 2 bytes per uniform brick, header + data otherwise.
  size_t memory_bytes() const;
  uint64_t fingerprint() const;

 private:
  std::array<BrickHeader, kBricks> bricks_{};
  std::vector<uint8_t> pool_;
};

}  // namespace em
