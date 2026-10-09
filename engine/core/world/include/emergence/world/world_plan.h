// World plan (roadmap M1, architecture § 2.6): computed once per game from the
// seed. Relief, erosion, rivers, lakes, biomes, geology, frontier marches,
// settlement sites and roads on a 16 m grid, plus the backdrop beyond the map.
// Every chunk is later generated locally by querying this plan.
//
// Determinism: integer and fixed-point maths only, no floats, no shared random
// state; the plan is bit-identical for a given (params, generator version).
#pragma once
#include <array>
#include <cstdint>
#include <string>
#include <vector>

namespace em {

constexpr uint32_t kWorldGeneratorVersion = 1;

enum class Side : uint8_t { West = 0, North = 1, East = 2, South = 3, None = 255 };
enum class FrontierKind : uint8_t { Sea = 0, Mountain = 1, Desert = 2, Forest = 3 };

enum class Biome : uint8_t {
  Ocean, Beach, Marsh, Meadow, Woodland, DeepForest, Steppe, Desert,
  Foothills, Alpine, Rock, Snow, LakeBed, kCount
};
const char* biome_name(Biome b);

// Geology of the bedrock under a cell; names match data/materials.csv.
enum class RockType : uint8_t { Limestone, Sandstone, Granite, Slate, Basalt, kCount };
const char* rock_material_name(RockType r);

enum CellFlag : uint8_t {
  kFlagSea = 1, kFlagLake = 2, kFlagRiver = 4, kFlagRoad = 8, kFlagSettlement = 16,
};

enum class SettlementKind : uint8_t { Port, Foresters, Miners, Oasis, Town };
const char* settlement_name(SettlementKind k);
// Shared village id (docs/interfaces.md § 8): sea_village, forest_village,
// mountain_village, desert_village, market_town.
const char* settlement_id(SettlementKind k);
// Frontier the settlement belongs to: west, north, east, south or center.
const char* settlement_frontier(SettlementKind k);

constexpr uint8_t kNoReceiver = 8;
// Neighbour order used everywhere (receiver codes 0..7): E, NE, N, NW, W, SW, S, SE.
constexpr std::array<int, 8> kDirDi = {1, 1, 0, -1, -1, -1, 0, 1};
constexpr std::array<int, 8> kDirDj = {0, 1, 1, 1, 0, -1, -1, -1};

struct WorldParams {
  uint64_t seed = 1;
  int32_t size_m = 20000;  // playable map, square
  int32_t cell_m = 16;     // plan resolution
  // Frontier kind per side, indexed by Side (D13: sea W, mountain N, desert E, forest S).
  std::array<FrontierKind, 4> frontier = {FrontierKind::Sea, FrontierKind::Mountain,
                                          FrontierKind::Desert, FrontierKind::Forest};
  std::array<int32_t, 4> march_width_m = {3000, 5000, 3000, 3000};
  std::array<int32_t, 4> hostility_doubling_m = {300, 500, 300, 300};
  int32_t erosion_iterations = 8;
  int32_t river_min_catchment_m2 = 1'500'000;
  int32_t lake_min_cells = 24;
  bool backdrop = true;

  // A smaller map for tests: same layout with every horizontal distance scaled.
  static WorldParams scaled(uint64_t seed, int32_t size_m);
  // 1.0 for the 20 km map, in Q16.
  int64_t scale_q16() const;
};

struct Settlement {
  SettlementKind kind;
  int32_t i = 0, j = 0;  // plan cell
  int32_t height_mm = 0;
};

struct Road {
  int32_t from = 0, to = 0;      // indices into settlements
  std::vector<uint32_t> cells;   // plan cells, from -> to
  int64_t length_m = 0;
};

// Coarse relief beyond the map edge, never voxelised (architecture § 2.2).
struct BackdropLayer {
  int64_t origin_x_mm = 0, origin_z_mm = 0;  // world position of cell (0, 0)
  int64_t cell_mm = 0;
  int32_t n = 0;
  std::vector<int32_t> height_mm;
};

struct PlanTimings {
  double frontier_relief_ms = 0, erosion_ms = 0, hydrology_ms = 0, biomes_ms = 0,
         settlements_ms = 0, backdrop_ms = 0, total_ms = 0;
};

struct WorldPlan {
  WorldParams params;
  uint32_t generator_version = kWorldGeneratorVersion;
  int32_t n = 0;          // cells per side
  int64_t cell_mm = 0;

  // Per cell, index = j * n + i, i eastward (x), j northward (z).
  // Cell (i, j) samples the point (i * cell, j * cell).
  std::vector<int32_t> height_mm;     // terrain surface
  std::vector<int32_t> water_mm;      // water surface, kNoWater if dry
  std::vector<uint32_t> flow_m2;      // rain-weighted drainage area
  std::vector<uint8_t> receiver;      // downstream neighbour (0..7) or kNoReceiver
  std::vector<uint8_t> biome;         // Biome
  std::vector<uint8_t> rock;          // RockType
  std::vector<uint16_t> soil_mm;      // loose soil above bedrock
  std::vector<uint8_t> flags;         // CellFlag
  std::vector<uint8_t> march_side;    // Side, or Side::None in the inhabited core
  std::vector<int16_t> march_depth_m; // signed depth into the nearest march (negative in core)

  std::vector<Settlement> settlements;  // Town first, then one village per frontier
  std::vector<Road> roads;
  BackdropLayer near_backdrop, far_backdrop;
  PlanTimings timings;

  static constexpr int32_t kNoWater = INT32_MIN;

  size_t idx(int32_t i, int32_t j) const { return static_cast<size_t>(j) * static_cast<size_t>(n) + static_cast<size_t>(i); }
  bool in_map(int32_t i, int32_t j) const { return i >= 0 && j >= 0 && i < n && j < n; }

  // Hostility H = 2^(depth / doubling) inside a march, 1 in the core (Q16).
  int64_t hostility_q16(size_t cell) const;
  // Bilinear terrain height at a world position (clamped to the map).
  int32_t height_at_mm(int64_t x_mm, int64_t z_mm) const;

  uint64_t fingerprint() const;
  size_t memory_bytes() const;
};

WorldPlan generate_world_plan(const WorldParams& params);

// Debug maps (PNG) for humans: shaded relief with biomes, water, roads and
// settlements; hostility; backdrop. Returns false if a file cannot be written.
bool write_plan_images(const WorldPlan& plan, const std::string& dir);

}  // namespace em
