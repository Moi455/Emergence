// RoutePlanner (T23b): A* on the KNOWLEDGE of one NPC. It takes a MentalMap (and the RoadPlan, read only for the
// segments the map says are known) and a BELIEVED target position. It has no access to the world: no grid, no view query
// (a ctest greps the planner files to keep it so). Integer costs, deterministic ties, bounded expansions.
//
// Graph: the 78 x 78 tiles of 256 m, 8 neighbours. Cost per millimetre walked: a known road 1, a tile already walked 2,
// an unknown tile 6 (so the NPC prefers what it knows but, beyond it, walks toward where it believes the target is:
// it explores). An obstacle known between two tiles removes that crossing. A known road segment links its two end tiles.
#pragma once
#include <array>
#include <cstdint>

#include "emergence/act/navigation/mental_map.h"

namespace em::act::navigation {

inline constexpr int kMaxRouteSteps = 192;

struct RouteStep {
  std::uint16_t tile = 0;     // the tile to reach (the start tile is not a step)
  std::int16_t segment = -1;  // the road segment taken to get there, or -1
  bool unknown = false;       // the tile was never walked: exploring
};

enum class PlanStatus : std::uint8_t { Found, Unreachable, OverBudget };

struct Plan {
  PlanStatus status = PlanStatus::Unreachable;
  std::uint16_t count = 0;
  std::array<RouteStep, kMaxRouteSteps> steps{};
  std::uint32_t expansions = 0;
  std::int64_t cost = 0;
  bool explores() const { for (int i = 0; i < count; ++i) if (steps[std::size_t(i)].unknown) return true; return false; }
};

struct PlannerLimits { std::uint32_t max_expansions = 8192; };

class RoutePlanner {
 public:
  RoutePlanner(const RoadPlan* roads = nullptr, PlannerLimits limits = {}) : roads_(roads), limits_(limits) {}
  Plan plan(const MentalMap& map, std::uint16_t day, const Position& from, const Position& believed_target) const;

 private:
  const RoadPlan* roads_;
  PlannerLimits limits_;
};

}  // namespace em::act::navigation
