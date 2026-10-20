#include "emergence/act/navigation/view_probe.h"

#include <algorithm>
#include <cstdlib>

namespace em::act::navigation {

namespace {
std::int32_t floor_div(std::int32_t a, std::int32_t b) { return a >= 0 ? a / b : -((-a + b - 1) / b); }
}

void FlatTerrain::block(std::int32_t x0, std::int32_t y0, std::int32_t x1, std::int32_t y1) {
  for (std::int32_t y = y0; y <= y1; ++y)
    for (std::int32_t x = x0; x <= x1; ++x) cells_.insert(key(x, y));
}

bool FlatTerrain::blocked(const Position& from, const Position& to) const {
  const std::int64_t dx = std::int64_t(to[0]) - from[0], dy = std::int64_t(to[1]) - from[1];
  const std::int64_t len = std::max(std::llabs(dx), std::llabs(dy));
  const std::int64_t n = std::max<std::int64_t>(1, len / (cell_ / 2));   // two samples per cell
  const std::int32_t c0x = floor_div(from[0], cell_), c0y = floor_div(from[1], cell_);
  for (std::int64_t i = 1; i <= n; ++i) {
    const std::int32_t cx = floor_div(std::int32_t(from[0] + dx * i / n), cell_), cy = floor_div(std::int32_t(from[1] + dy * i / n), cell_);
    if (cx == c0x && cy == c0y) continue;   // the cell where the actor stands does not count
    if (cell_blocked(cx, cy)) return true;
  }
  return false;
}

}  // namespace em::act::navigation
