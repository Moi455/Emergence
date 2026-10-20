// ViewProbe: the occupancy of the world IN THE ACTOR'S FIELD OF VIEW (docs/14 section 4.8: the 32 cm occupancy grid is
// consulted only in view, which amounts to seeing the obstacle). The voxel world is entrusted to another team and
// answers behind this interface; FlatTerrain (a flat grid) is the implementation of tests and benches, NOT voxel code.
// The Navigator never asks about a point farther than its view distance from the actor.
#pragma once
#include <cstdint>
#include <unordered_set>

#include "emergence/act/navigation/navigation_types.h"

namespace em::act::navigation {

class ViewProbe {
 public:
  virtual ~ViewProbe() = default;
  // True when the walk on the straight line `from` -> `to` meets an impassable cell. const, pure, thread-safe.
  virtual bool blocked(const Position& from, const Position& to) const = 0;
};

class FlatTerrain final : public ViewProbe {
 public:
  explicit FlatTerrain(std::int32_t cell_mm = 1000) : cell_(cell_mm) {}
  // Impassable block of cells [x0..x1] x [y0..y1] (cell coordinates).
  void block(std::int32_t x0, std::int32_t y0, std::int32_t x1, std::int32_t y1);
  bool cell_blocked(std::int32_t cx, std::int32_t cy) const { return cells_.count(key(cx, cy)) != 0; }
  std::int32_t cell_mm() const { return cell_; }
  bool blocked(const Position& from, const Position& to) const override;

 private:
  static std::uint64_t key(std::int32_t cx, std::int32_t cy) { return (std::uint64_t(std::uint32_t(cx)) << 32) | std::uint32_t(cy); }
  std::int32_t cell_;
  std::unordered_set<std::uint64_t> cells_;   // looked up by key only, never iterated (determinism)
};

}  // namespace em::act::navigation
