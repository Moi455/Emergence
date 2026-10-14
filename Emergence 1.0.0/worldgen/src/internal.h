// Internal pieces of the fine generator, shared between its .cpp files.
#pragma once
#include <algorithm>
#include <array>
#include <cstdint>
#include <span>
#include <vector>

#include "emergence/base/fixed.h"
#include "emergence/base/hash.h"
#include "emergence/base/noise.h"
#include "emergence/worldgen/worldgen.h"

namespace em::wg {

constexpr int64_t M = 1000;  // millimetres per metre
constexpr int kGridStride = 8;  // voxels between two surface grid points
constexpr int kGridN = kChunkSize / kGridStride + 3;  // grid points per side, one border each way

// Layer seeds of this module, derived from the world seed. Kept apart from
// em::Layer so that the plan's own layers never shift.
enum class FineLayer : uint64_t {
  Detail = 101, Jitter, Strata, Basement, Ore, Salt, Clay, Boulder, Cave, Tree, Leaf, Snow, Grove,
};
inline uint64_t fine_seed(uint64_t world_seed, FineLayer l) {
  return hash_combine(mix64(world_seed ^ 0x5eed5eed5eedULL), static_cast<uint64_t>(l) * 0x9fb21c651e98df25ULL);
}

// Uniform draw in [0, n) from a hash (n small).
inline int64_t pick(uint64_t h, int64_t n) { return static_cast<int64_t>(h % static_cast<uint64_t>(n)); }
inline int64_t range(uint64_t h, int64_t lo, int64_t hi) { return lo + pick(h, hi - lo + 1); }
inline uint64_t rehash(uint64_t h, uint64_t k) { return hash_combine(h, k); }
// Uniform draw in [-1, 1] (Q16).
inline int64_t unit_q16(uint64_t h) { return static_cast<int64_t>(h & 0x1FFFF) - kOne; }

// Material classes used by the generator, resolved once from the table.
struct Mats {
  VoxelId air = kAir, turf, dirt, clay, sand, gravel, forest_floor, snow;
  VoxelId limestone, sandstone, granite, slate, basalt, salt, iron_ore;
  VoxelId wood, bark, leaves;
  std::array<VoxelId, static_cast<size_t>(RockType::kCount)> rock{};
  bool leaves_is_fallback = false;
  bool is_rock(VoxelId v) const {
    MaterialClass c = voxel_class(v);
    return c == voxel_class(limestone) || c == voxel_class(sandstone) || c == voxel_class(granite) ||
           c == voxel_class(slate) || c == voxel_class(basalt);
  }
  bool is_soil(VoxelId v) const {
    MaterialClass c = voxel_class(v);
    return c == voxel_class(turf) || c == voxel_class(dirt) || c == voxel_class(clay) ||
           c == voxel_class(sand) || c == voxel_class(gravel) || c == voxel_class(forest_floor) ||
           c == voxel_class(snow);
  }
};

// Flat spatial index over the map (CSR): cell -> list of item ids.
struct GridIndex {
  int64_t cell_mm = 64 * M;
  int32_t n = 0;
  std::vector<uint32_t> start, items;
  // Builds from per-item xz boxes [x0, x1] x [z0, z1] (mm).
  void build(int64_t map_mm, int64_t cell, const std::vector<std::array<int64_t, 4>>& boxes);
  // Appends the ids whose cells touch the box, sorted and unique.
  void query(int64_t x0, int64_t z0, int64_t x1, int64_t z1, std::vector<uint32_t>* out) const;
};

struct RoadSeg {
  int64_t ax, az, bx, bz;  // mm
  int32_t half_width_mm;
};

// Box of the chunk being generated, in world millimetres.
struct ChunkBox {
  int64_t ox, oy, oz;  // origin (min corner)
  int64_t v;           // voxel size
  int64_t size;        // 64 * v
  int lod;
  // Centre of voxel index i along an axis whose origin is o.
  int64_t c(int64_t o, int i) const { return o + i * v + v / 2; }
};

// Trilinear value noise on a lattice cached for one box: building costs a
// few hundred hashes, each lookup is eight loads. Continuous across chunks
// because lattice values depend only on world lattice coordinates.
class Lattice3 {
 public:
  // spacing_shift: lattice spacing is 1 << spacing_shift millimetres.
  void build(uint64_t seed, int spacing_shift, int64_t x0, int64_t y0, int64_t z0, int64_t x1, int64_t y1, int64_t z1);
  // Result in Q16, roughly [-1, 1].
  int64_t at(int64_t x, int64_t y, int64_t z) const;
  bool empty() const { return v_.empty(); }

 private:
  int shift_ = 8;
  int64_t bx_ = 0, by_ = 0, bz_ = 0;
  int32_t nx_ = 0, ny_ = 0, nz_ = 0;
  std::vector<int32_t> v_;
};

// y in world millimetres is shifted by this so lattice coordinates stay positive.
constexpr int64_t kYBias = -kWorldBottomMm;

// Sample of the coarse surface at one grid point.
struct GridSample {
  int64_t h = 0;          // ground without the fine octaves
  int32_t fine_amp = 0;   // amplitude of the fine octaves (mm)
  uint32_t cell = 0;      // plan cell for materials (jittered)
  int32_t road_q16 = 0;   // 1 at the centre of a road
};

struct Feature;  // ellipsoids and capsules rasterised into chunks

struct WorldGen::Impl {
  const WorldPlan& p;
  Mats m;
  int64_t map_mm = 0;
  uint64_t seed = 0;
  std::vector<SettlementPad> pads;
  std::vector<RoadSeg> roads;
  GridIndex road_index;
  std::vector<CaveSegment> caves;
  GridIndex cave_index;
  CaveStats cave_stats;
  int forest_side = -1;  // Side index of the forest march, -1 if none

  explicit Impl(const WorldPlan& plan, const MaterialTable& mats);

  // --- plan access (surface.cpp) ---
  int64_t plan_h(int32_t i, int32_t j) const {
    i = std::clamp(i, 0, p.n - 1);
    j = std::clamp(j, 0, p.n - 1);
    return p.height_mm[p.idx(i, j)];
  }
  uint32_t cell_at(int64_t x, int64_t z) const;  // nearest plan cell
  int64_t plan_cubic(int64_t x, int64_t z) const;
  int32_t biome_amp_at(int64_t x, int64_t z, int64_t* rocky_q16) const;
  GridSample grid_sample(int64_t gx, int64_t gz, int lod, std::span<const uint32_t> road_ids) const;
  int64_t fine_detail(int64_t x, int64_t z, int32_t amp, int lod) const;
  void roads_near(int64_t x0, int64_t z0, int64_t x1, int64_t z1, std::vector<uint32_t>* out) const;
  // Conservative ground bounds over an xz box (no fine sampling).
  void ground_bounds(int64_t x0, int64_t z0, int64_t x1, int64_t z1, int64_t* lo, int64_t* hi) const;
  int64_t ground(int64_t x, int64_t z, int lod) const;
  int64_t tree_scale_q16(int64_t x, int64_t z) const;

  // --- columns and geology (geology.cpp) ---
  void fill_columns(const ChunkBox& b, VoxelId* out) const;
  void overlay_geology(const ChunkBox& b, VoxelId* out) const;

  // --- caves (caves.cpp) ---
  void build_caves();
  bool caves_touch(int64_t x0, int64_t y0, int64_t z0, int64_t x1, int64_t y1, int64_t z1) const;
  void carve_caves(const ChunkBox& b, VoxelId* out) const;

  // --- trees and boulders (trees.cpp) ---
  void trees_in(int64_t x0, int64_t z0, int64_t x1, int64_t z1, int64_t reach, std::vector<TreeInstance>* out) const;
  int64_t max_tree_height(int64_t x0, int64_t z0, int64_t x1, int64_t z1) const;
  void plant_trees(const ChunkBox& b, VoxelId* out) const;
  void place_boulders(const ChunkBox& b, VoxelId* out) const;
};

// --- rasterisation helpers (raster.cpp) ---
enum ReplaceMask : uint8_t { kRepAir = 1, kRepSoil = 2, kRepRock = 4, kRepLeaves = 8, kRepWood = 16, kRepAll = 31 };

struct Ellipsoid {
  int64_t cx, cy, cz;
  int64_t rx, ry, rz;
};
struct Capsule {
  int64_t ax, ay, az, bx, by, bz;
  int64_t ra, rb;
};

struct RasterStyle {
  VoxelId voxel = kAir;
  uint8_t replace = kRepAir;
  int32_t noise_q16 = 0;         // surface roughness, fraction of the radius
  const Lattice3* noise = nullptr;
  uint64_t hole_seed = 0;        // when non-zero, holes on a 4-voxel grid
  int32_t hole_pct = 0;
  int64_t block_mm = 0;          // when non-zero (ellipsoids only), tested on blocks of this size
};

// Returns the number of voxels written.
int64_t raster_ellipsoid(const WorldGen::Impl& g, const ChunkBox& b, const Ellipsoid& e, const RasterStyle& s, VoxelId* out);
int64_t raster_blocky_ellipsoid(const WorldGen::Impl& g, const ChunkBox& b, const Ellipsoid& e, const RasterStyle& s,
                                VoxelId* out);
int64_t raster_capsule(const WorldGen::Impl& g, const ChunkBox& b, const Capsule& c, const RasterStyle& s, VoxelId* out);
bool replace_ok(const Mats& m, VoxelId cur, uint8_t mask);

}  // namespace em::wg
