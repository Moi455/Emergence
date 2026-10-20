// Shared constants and integer helpers of the navigation (T23b, docs/14 section 4.8). Positions are millimetres
// (em::act::Position), x and y horizontal. Everything here is integer: no float in the choice of a route.
#pragma once
#include <algorithm>
#include <cstdint>

#include "emergence/act/entity_ops.h"

namespace em::act::navigation {

using em::act::Position;

inline constexpr std::int32_t kTileMm = 256'000;                 // a knowledge tile is 256 m (docs/14 section 4.8)
inline constexpr int kTilesPerSide = 78;                         // 78 * 256 m = 19.97 km, the 20 km of the world plan
inline constexpr int kTileCount = kTilesPerSide * kTilesPerSide; // 6 084 bits = 761 bytes of "tiles walked"
inline constexpr std::int32_t kNoTile = -1;

// The tile of a position (row-major), or kNoTile when the position lies outside the plan.
constexpr std::int32_t tile_of(const Position& p) {
  if (p[0] < 0 || p[1] < 0) return kNoTile;
  const std::int32_t tx = p[0] / kTileMm, ty = p[1] / kTileMm;
  if (tx >= kTilesPerSide || ty >= kTilesPerSide) return kNoTile;
  return ty * kTilesPerSide + tx;
}
// The nearest tile, for a position that may lie outside the plan (a belief can be wrong).
constexpr std::int32_t clamped_tile_of(const Position& p) {
  const std::int32_t tx = std::clamp(p[0] < 0 ? -1 : p[0] / kTileMm, 0, kTilesPerSide - 1);
  const std::int32_t ty = std::clamp(p[1] < 0 ? -1 : p[1] / kTileMm, 0, kTilesPerSide - 1);
  return ty * kTilesPerSide + tx;
}
constexpr Position tile_center(std::int32_t tile) {
  return {(tile % kTilesPerSide) * kTileMm + kTileMm / 2, (tile / kTilesPerSide) * kTileMm + kTileMm / 2, 0};
}

constexpr std::int64_t isqrt64(std::int64_t v) {
  if (v <= 0) return 0;
  std::int64_t x = v, y = (x + 1) / 2;
  while (y < x) { x = y; y = (x + v / x) / 2; }
  return x;
}
// Horizontal distance in millimetres (exact integer square root).
constexpr std::int64_t distance_mm(const Position& a, const Position& b) {
  const std::int64_t dx = std::int64_t(a[0]) - b[0], dy = std::int64_t(a[1]) - b[1];
  return isqrt64(dx * dx + dy * dy);
}

}  // namespace em::act::navigation
