#include "navigator_adapter.h"

#include <algorithm>

#include "emergence/act/perception/trig.h"

namespace em::act {

MoveStep NavigatorAdapter::step(std::uint32_t walker, const Position& from, const Position& goal, std::int32_t max_mm,
                                std::int32_t stop_within_mm, bool away) {
  MoveStep out;
  out.to = from;
  Position target = goal;
  if (away) {   // flight: aim at a far point on the opposite side of the believed danger
    const std::int64_t dx = std::int64_t{from[0]} - goal[0], dy = std::int64_t{from[1]} - goal[1];
    const std::int64_t d = std::max<std::int64_t>(1, static_cast<std::int64_t>(perception::isqrt(static_cast<std::uint64_t>(dx * dx + dy * dy))));
    target[0] = static_cast<std::int32_t>(from[0] + dx * 200000 / d);
    target[1] = static_cast<std::int32_t>(from[1] + dy * 200000 / d);
  }
  navigation::NavRequest rq{from, target, stop_within_mm, day_};
  const navigation::NavStep s = nav_.next_step(walker, rq);
  switch (s.status) {
    case navigation::NavStatus::Blocked: out.status = MoveStatus::Blocked; return out;
    case navigation::NavStatus::Arrived: out.status = away ? MoveStatus::Moving : MoveStatus::Arrived; return out;
    case navigation::NavStatus::Moving:
    case navigation::NavStatus::Exploring: break;
  }
  const std::int64_t dx = std::int64_t{s.waypoint[0]} - from[0], dy = std::int64_t{s.waypoint[1]} - from[1];
  const std::int64_t d = static_cast<std::int64_t>(perception::isqrt(static_cast<std::uint64_t>(dx * dx + dy * dy)));
  const std::int64_t mv = std::min<std::int64_t>(max_mm, d);
  if (d > 0) {
    out.to[0] = static_cast<std::int32_t>(from[0] + dx * mv / d);
    out.to[1] = static_cast<std::int32_t>(from[1] + dy * mv / d);
  }
  out.moved_mm = static_cast<std::int32_t>(mv);
  return out;
}

}  // namespace em::act
