// NavigatorAdapter (T22): wires the Navigator of T23b (MentalMap + RoutePlanner, engine/act/navigation, its own interface
// navigation::NavigationQuery::next_step) to the executor's ExecutorNavigation::step. The Navigator gives the next waypoint on the
// walker's mental map; the adapter walks toward it by the distance of this tick and reports the arrival, the closed way seen on
// the spot, or the plain move. Nothing of the true terrain passes here.
#pragma once
#include "emergence/act/navigation/navigator.h"
#include "executor_navigation.h"

namespace em::act {

class NavigatorAdapter final : public ExecutorNavigation {
 public:
  explicit NavigatorAdapter(navigation::Navigator& navigator) : nav_(navigator) {}
  // The game day (obstacle expiry and fading of places in the mental map); set before each step of the executor.
  void set_day(std::uint16_t day) { day_ = day; }
  MoveStep step(std::uint32_t walker, const Position& from, const Position& goal, std::int32_t max_mm, std::int32_t stop_within_mm,
                bool away) override;
  void cancel(std::uint32_t walker) override { nav_.cancel(walker); }

 private:
  navigation::Navigator& nav_;
  std::uint16_t day_ = 0;
};

}  // namespace em::act
