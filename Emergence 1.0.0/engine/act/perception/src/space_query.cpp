#include "emergence/act/perception/space_query.h"

#include <algorithm>
#include <cstdlib>

#include "emergence/social/clock.h"

namespace em::act::perception {

void FlatSpace::block(std::int32_t x0, std::int32_t y0, std::int32_t x1, std::int32_t y1, std::uint16_t opacity, std::uint16_t sound_block) {
  for (std::int32_t x = x0; x <= x1; ++x)
    for (std::int32_t y = y0; y <= y1; ++y) {
      Cell& c = cell_at(x, y);
      c.opacity = opacity;
      c.sound_block = sound_block;
    }
}

void FlatSpace::roof(std::int32_t x0, std::int32_t y0, std::int32_t x1, std::int32_t y1, std::int16_t light) {
  for (std::int32_t x = x0; x <= x1; ++x)
    for (std::int32_t y = y0; y <= y1; ++y) {
      Cell& c = cell_at(x, y);
      c.roof = true;
      c.light = light;
    }
}

const FlatSpace::Cell* FlatSpace::find(std::int32_t cx, std::int32_t cy) const {
  auto it = cells_.find(key(cx, cy));
  return it == cells_.end() ? nullptr : &it->second;
}

// Walks the cells of the segment a -> b (integer stepping along the longer axis, so the same cells whatever the
// platform) and multiplies the shares that pass. The start and end cells are not counted.
std::uint16_t FlatSpace::ray(const Position& a, const Position& b, bool sight) const {
  const std::int32_t ax = cell_of(a[0]), ay = cell_of(a[1]), bx = cell_of(b[0]), by = cell_of(b[1]);
  const std::int32_t dx = bx - ax, dy = by - ay;
  const std::int32_t steps = std::max(std::abs(dx), std::abs(dy));
  std::int64_t pass = 1000;
  for (std::int32_t i = 1; i < steps && pass > 0; ++i) {
    const std::int32_t cx = ax + std::int32_t((std::int64_t(dx) * i + (dx >= 0 ? steps / 2 : -steps / 2)) / steps);
    const std::int32_t cy = ay + std::int32_t((std::int64_t(dy) * i + (dy >= 0 ? steps / 2 : -steps / 2)) / steps);
    if (const Cell* c = find(cx, cy)) pass = pass * (1000 - (sight ? c->opacity : c->sound_block)) / 1000;
  }
  return static_cast<std::uint16_t>(pass);
}

std::int16_t FlatSpace::daylight(GameTime now) {
  using em::social::WorldClock;
  const std::int64_t r = WorldClock(now).real_seconds() % WorldClock::kRealSecondsPerDay;   // 0 at dawn
  constexpr std::int64_t kDay = WorldClock::kRealSecondsPerDay - WorldClock::kNightRealSeconds, kTwi = 300, kNight = 12;
  if (r >= kDay) return kNight;
  if (r < kTwi) return static_cast<std::int16_t>(kNight + (100 - kNight) * r / kTwi);
  if (r >= kDay - kTwi) return static_cast<std::int16_t>(kNight + (100 - kNight) * (kDay - r) / kTwi);
  return 100;
}

std::int16_t FlatSpace::light_at(const Position& p, GameTime now) const {
  if (const Cell* c = find(cell_of(p[0]), cell_of(p[1])); c && c->light >= 0) return c->light;
  return daylight(now);
}

std::int16_t FlatSpace::ambient_noise_at(const Position& p) const {
  const Cell* c = find(cell_of(p[0]), cell_of(p[1]));
  return static_cast<std::int16_t>(std::min<int>(100, noise_ + (c ? c->noise : 0)));
}

bool FlatSpace::indoors(const Position& p) const {
  const Cell* c = find(cell_of(p[0]), cell_of(p[1]));
  return c && c->roof;
}

}  // namespace em::act::perception
