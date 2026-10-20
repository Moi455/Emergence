#include "executor_navigation.h"

#include <algorithm>
#include <cstdlib>

#include "emergence/act/perception/trig.h"

namespace em::act {
namespace {
using perception::isqrt;

std::int64_t dist2(const Position& a, const Position& b) {
  const std::int64_t dx = std::int64_t{a[0]} - b[0], dy = std::int64_t{a[1]} - b[1];
  return dx * dx + dy * dy;
}

// Squared distance from point p to the segment a-b (horizontal plane).
std::int64_t segment_distance2(const Position& a, const Position& b, const Position& p) {
  const std::int64_t abx = std::int64_t{b[0]} - a[0], aby = std::int64_t{b[1]} - a[1];
  const std::int64_t apx = std::int64_t{p[0]} - a[0], apy = std::int64_t{p[1]} - a[1];
  const std::int64_t len2 = abx * abx + aby * aby;
  if (len2 == 0) return apx * apx + apy * apy;
  const std::int64_t t = std::clamp<std::int64_t>((apx * abx + apy * aby) * 1000 / len2, 0, 1000);   // per-mille along a-b
  const std::int64_t cx = abx * t / 1000, cy = aby * t / 1000;
  const std::int64_t ex = apx - cx, ey = apy - cy;
  return ex * ex + ey * ey;
}
}  // namespace

MoveStep FlatNavigation::step(std::uint32_t, const Position& from, const Position& goal, std::int32_t max_mm,
                             std::int32_t stop_within_mm, bool away) {
  MoveStep out;
  out.to = from;
  const std::int64_t dx = std::int64_t{goal[0]} - from[0], dy = std::int64_t{goal[1]} - from[1];
  const std::int64_t d = static_cast<std::int64_t>(isqrt(static_cast<std::uint64_t>(dx * dx + dy * dy)));
  if (!away && d <= stop_within_mm) {
    out.status = MoveStatus::Arrived;
    return out;
  }
  if (d == 0 && !away) { out.status = MoveStatus::Arrived; return out; }
  // Unit direction (toward or away), advance, never overshoot the stop distance.
  std::int64_t move = away ? max_mm : std::min<std::int64_t>(max_mm, d - stop_within_mm);
  if (move < 0) move = 0;
  std::int64_t ux = d ? dx : 1, uy = d ? dy : 0, norm = d ? d : 1;
  if (away) { ux = -ux; uy = -uy; }
  Position next = from;
  next[0] = static_cast<std::int32_t>(from[0] + ux * move / norm);
  next[1] = static_cast<std::int32_t>(from[1] + uy * move / norm);
  // A closed stretch ahead: the walker learns it only by SEEING it (within sight of the cut), never before.
  if (!away) {
    for (const Cut& c : cuts_) {
      const std::int64_t r = c.radius, lim = std::int64_t{sight_mm_} + r;
      if (dist2(from, c.at) > lim * lim) continue;
      if (segment_distance2(from, goal, c.at) <= r * r) {
        out.status = MoveStatus::Blocked;
        return out;
      }
    }
  }
  out.to = next;
  out.moved_mm = static_cast<std::int32_t>(move);
  out.status = (!away && d - move <= stop_within_mm) ? MoveStatus::Arrived : MoveStatus::Moving;
  return out;
}

}  // namespace em::act
