// ExecutorNavigation (T22, docs/14 section 4.8, P51): how a NPC moves with what it KNOWS. The executor of gestures never reads
// the true terrain: it asks this interface for the next stretch of the route computed on the walker's mental map. T23b's
// Navigator (engine/act/navigation, its own NavigationQuery::next_step) is wired in by NavigatorAdapter (navigator_adapter.h). FlatNavigation is the
// simple implementation for tests and benches (a flat plane, straight lines), NOT the voxel world.
//
// Conventions: positions are millimetres (em::act::Position); x and y are horizontal (the convention of the perception's
// SpaceQuery), z is up. The walker keeps its z unless the implementation says otherwise.
#pragma once
#include <cstdint>
#include <vector>

#include "emergence/act/entity_ops.h"

namespace em::act {

enum class MoveStatus : std::uint8_t {
  Moving,    // progressed (possibly 0 mm: waiting) and not there yet
  Arrived,   // the goal is reached (within `stop_within_mm`)
  Blocked,   // the walker SEES an obstacle on its route (only ever reported when the obstacle is in its field of view)
  Lost,      // the goal is beyond everything the walker knows and it found no direction to explore
};

struct MoveStep {
  Position to{};                  // where the walker stands after the step
  std::int32_t moved_mm = 0;
  MoveStatus status = MoveStatus::Moving;
};

class ExecutorNavigation {
 public:
  virtual ~ExecutorNavigation() = default;
  // Advances the walker from `from` toward `goal` (the place it BELIEVES the goal to be) by at most `max_mm` along the route
  // it knows; it stops `stop_within_mm` short of the goal. `away` = move away from the goal instead (flight). Deterministic; distinct walkers may be
  // called from several threads at once.
  virtual MoveStep step(std::uint32_t walker, const Position& from, const Position& goal, std::int32_t max_mm,
                       std::int32_t stop_within_mm, bool away) = 0;
  // The walker drops its journey (the gesture ended, was interrupted or replaced).
  virtual void cancel(std::uint32_t /*walker*/) {}
};

// A flat plane without relief. Cuts model a route that is closed at some place: the walker only learns it by SEEING it
// (`sight_mm` away from the cut), so a cut seen from farther than that is invisible to the walker and it walks on.
class FlatNavigation final : public ExecutorNavigation {
 public:
  explicit FlatNavigation(std::int32_t sight_mm = 20000) : sight_mm_(sight_mm) {}
  // The segment through (x, y) of half-width `half_mm` across the route is closed (a disc, in this simple model).
  void cut(const Position& at, std::int32_t radius_mm) { cuts_.push_back({at, radius_mm}); }
  MoveStep step(std::uint32_t walker, const Position& from, const Position& goal, std::int32_t max_mm,
                std::int32_t stop_within_mm, bool away) override;

 private:
  struct Cut { Position at; std::int32_t radius; };
  std::int32_t sight_mm_;
  std::vector<Cut> cuts_;
};

}  // namespace em::act
