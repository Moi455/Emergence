// VoxelId (architecture § 3.2): 16 bits = material class (9 bits) << 7 | tint (7 bits).
// The voxel carries nothing else: dynamic state lives in sparse fields.
#pragma once
#include <cstdint>

namespace em {

using VoxelId = uint16_t;
using MaterialClass = uint16_t;  // 0..511

constexpr int kClassBits = 9;
constexpr int kTintBits = 7;
constexpr MaterialClass kMaxClasses = 1 << kClassBits;
constexpr VoxelId kAir = 0;

constexpr VoxelId make_voxel(MaterialClass cls, uint8_t tint = 0) {
  return static_cast<VoxelId>((cls << kTintBits) | (tint & 0x7F));
}
constexpr MaterialClass voxel_class(VoxelId v) { return static_cast<MaterialClass>(v >> kTintBits); }
constexpr uint8_t voxel_tint(VoxelId v) { return static_cast<uint8_t>(v & 0x7F); }

// World scale constants.
constexpr int64_t kVoxelMm = 20;                    // 2 cm
constexpr int kChunkSize = 64;                      // voxels per chunk side (1.28 m)
constexpr int kBrickSize = 8;                       // voxels per brick side (16 cm)
constexpr int kBricksPerChunk = kChunkSize / kBrickSize;  // 8
constexpr int64_t kWorldBottomMm = -500'000;        // -500 m
constexpr int64_t kWorldTopMm = 3'500'000;          // headroom above the 3 km peaks

}  // namespace em
