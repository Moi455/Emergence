// Local chunk generation (roadmap M2): every chunk is a pure function of
// (plan, position). Columns follow the plan relief plus a deterministic detail
// noise; materials come in layers (top, soil, bedrock, deep granite).
// Water is not stored in voxels (architecture § 3.3).
// Terrain voxels carry tint 0; colour variation is left to the shader (§ 3.2).
#pragma once
#include <cstdint>

#include "emergence/world/chunk.h"
#include "emergence/world/materials.h"
#include "emergence/world/world_plan.h"

namespace em {

class ChunkGenerator {
 public:
  ChunkGenerator(const WorldPlan& plan, const MaterialTable& materials);

  enum class Kind : uint8_t { Air, Solid, Mixed };
  // Cheap test from plan bounds only: Air and Solid chunks are implicit and
  // never allocated. Mixed means "generate to know".
  Kind classify(ChunkCoord c, VoxelId* solid_value = nullptr) const;

  void generate(ChunkCoord c, Chunk& out) const;

  // Top of the terrain at a voxel column: voxels with y < result are solid.
  int32_t surface_voxel_y(int64_t vx, int64_t vz) const;

  // Map extent in voxels (x and z).
  int64_t map_voxels() const { return map_voxels_; }

 private:
  struct Node;  // coarse sample of the column profile
  void sample_node(int64_t vx, int64_t vz, Node& n) const;
  int64_t detail_amplitude_mm(int64_t x_mm, int64_t z_mm) const;

  const WorldPlan& plan_;
  int64_t map_voxels_;
  uint64_t detail_seed_;
  uint64_t jitter_seed_;
  VoxelId deep_rock_;
  VoxelId rock_[static_cast<int>(RockType::kCount)];
  VoxelId top_[static_cast<int>(Biome::kCount)];
  VoxelId sub_[static_cast<int>(Biome::kCount)];
  int32_t top_mm_[static_cast<int>(Biome::kCount)];
  int32_t detail_mm_[static_cast<int>(Biome::kCount)];
};

}  // namespace em
