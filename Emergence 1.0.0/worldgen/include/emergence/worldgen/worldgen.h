// Fine world generation (roadmap M2): voxel chunks of 2 cm generated locally
// from the world plan (16 m), on demand, in any order, on any thread.
//
// The plan (engine/core/world) holds everything non-local: relief after
// erosion, rivers, lakes, biomes, geology, frontier marches, settlements and
// roads. This module adds everything below 16 m: surface detail, soil
// layers, rock strata, ore bodies, salt and clay lenses, a cave network,
// boulders and trees. Each chunk only looks at the plan and at the features
// whose bounding box touches it, so generation needs no neighbour chunk.
//
// Determinism (invariant I2): integer and Q16 fixed-point maths only, every
// random draw is a hash of (seed, layer, position). A chunk is bit-identical
// for a given (plan, chunk key, kChunkGenVersion) on every platform.
//
// Multi-scale: a chunk at level of detail `lod` has 64^3 voxels of
// 2 cm << lod. Detail finer than the voxel is never computed.
#pragma once
#include <cstdint>
#include <memory>
#include <vector>

#include "emergence/world/chunk.h"
#include "emergence/world/materials.h"
#include "emergence/world/voxel_id.h"
#include "emergence/world/world_plan.h"

namespace em::wg {

constexpr uint32_t kChunkGenVersion = 2;  // 2: species tints, full crowns beyond lod 2
constexpr int kChunkVoxels = kChunkSize * kChunkSize * kChunkSize;  // 262 144

// Chunk address (docs/interfaces.md § 1): x east, y up, z north, origin at
// the south-west corner of the map, y = 0 at sea level. Chunk (x, y, z) at
// level `lod` covers [x * S, (x + 1) * S) in millimetres on each axis, with
// S = 64 * (20 << lod). At lod 0 it is em::ChunkCoord: voxel = coord * 64 + local.
// Voxels below the world bottom (-500 m) are bedrock.
struct ChunkKey {
  int32_t x = 0, y = 0, z = 0;
  uint8_t lod = 0;
};

constexpr int64_t voxel_mm(int lod) { return kVoxelMm << lod; }
constexpr int64_t chunk_mm(int lod) { return (kVoxelMm * kChunkSize) << lod; }
// Voxel index inside a chunk: x fastest, then z, then y.
constexpr int voxel_index(int x, int y, int z) { return (y * kChunkSize + z) * kChunkSize + x; }

enum class ChunkKind : uint8_t {
  Air,         // only air (water is a separate field, never voxels)
  Solid,       // no air voxel: nothing to mesh, regenerated when first dug
  Mixed,       // has a surface
  OutOfWorld,  // outside the map or below the world bottom
};

struct ChunkInfo {
  ChunkKind kind = ChunkKind::Mixed;
  // Dominant voxel when known (air for Air, bedrock class for Solid).
  VoxelId voxel = kAir;
};

enum class TreeSpecies : uint8_t { Oak, Birch, Pine, Willow, kCount };
const char* tree_species_name(TreeSpecies s);

// A tree placed by the seed. `id` is stable: a cut or planted tree is saved
// as a delta keyed by it.
struct TreeInstance {
  uint64_t id = 0;
  TreeSpecies species = TreeSpecies::Oak;
  int64_t x_mm = 0, y_mm = 0, z_mm = 0;  // base of the trunk, on the ground
  int32_t height_mm = 0;
  int32_t trunk_radius_mm = 0;  // bark outside, oak wood inside
  int32_t crown_radius_mm = 0;
  uint8_t tier = 0;  // size class: 0 ordinary, 3 the giants deep in the forest march
};

// Capsule of the cave network (radius interpolated from a to b).
struct CaveSegment {
  int64_t ax, ay, az, bx, by, bz;  // mm
  int32_t ra, rb;                  // mm
  uint32_t system = 0;
};

struct CaveStats {
  size_t systems = 0, segments = 0, chambers = 0, entrances = 0;
};

// Flat-ish ground prepared for a settlement (the village builder starts here).
struct SettlementPad {
  SettlementKind kind;
  int64_t x_mm = 0, z_mm = 0;
  int32_t height_mm = 0;
  int32_t radius_mm = 0;  // fully flat inside 60 % of the radius, blended outside
};

struct GenStats {
  uint64_t chunks = 0, air = 0, solid = 0, mixed = 0;
};

class WorldGen {
 public:
  explicit WorldGen(const WorldPlan& plan, const MaterialTable& materials = MaterialTable::builtin());
  ~WorldGen();
  WorldGen(const WorldGen&) = delete;
  WorldGen& operator=(const WorldGen&) = delete;

  const WorldPlan& plan() const { return plan_; }

  // Conservative and cheap (no voxel touched): Air and Solid are exact
  // promises, Mixed means "generate to know".
  ChunkInfo classify(const ChunkKey& key) const;

  // Fills out[voxel_index(x, y, z)] for the 64^3 voxels and returns the
  // chunk's actual kind (Air / Solid / Mixed).
  ChunkInfo generate(const ChunkKey& key, VoxelId* out) const;
  // Same, without the classify() shortcut: every chunk is generated voxel by
  // voxel. For tests that check classify() against the real content.
  ChunkInfo generate_unclassified(const ChunkKey& key, VoxelId* out) const;
  // Same as generate(), encoded into the engine's brick storage (lod 0).
  ChunkInfo generate(const ChunkCoord& coord, Chunk& out) const;

  // Ground height with all surface detail (no trees, no boulders), as used
  // by generate() at that level of detail. Settlement and road builders,
  // navigation and the far-field renderer read it.
  int32_t ground_mm(int64_t x_mm, int64_t z_mm, int lod = 0) const;
  // Water surface from the plan (sea, lake, river), or WorldPlan::kNoWater.
  int32_t water_mm(int64_t x_mm, int64_t z_mm) const;
  // Trees whose trunk base lies in [x0, x1) x [z0, z1).
  void trees_in(int64_t x0_mm, int64_t z0_mm, int64_t x1_mm, int64_t z1_mm,
                std::vector<TreeInstance>* out) const;

  const std::vector<CaveSegment>& cave_segments() const;
  CaveStats cave_stats() const;
  const std::vector<SettlementPad>& settlement_pads() const;

  // Fingerprint of a generated chunk (determinism tests).
  static uint64_t chunk_fingerprint(const VoxelId* voxels);

  struct Impl;

 private:
  const WorldPlan& plan_;
  std::unique_ptr<Impl> impl_;
};

}  // namespace em::wg
