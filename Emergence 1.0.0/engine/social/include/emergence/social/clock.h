// The two clocks of decision D30 (integer arithmetic, deterministic):
//  - the CALENDAR: 1 game day = 1 h 30 real (1 h of day, 30 min of night), 1 year = 7 h real, 1 season = 1 h 45;
//  - the LIFE CLOCK, separate (charter § 25: a life of about 150 h): childhood 0-14 years of age in 15 h real,
//    teenage 14-18 in 6 h, adulthood 18-60 in 105 h, old age 60-75 in 24 h (ageing accelerates).
#pragma once
#include <cstdint>

#include "emergence/social/state_types.h"

namespace em::social {

class WorldClock {
 public:
  static constexpr std::int64_t kGameSecondsPerDay = 86'400;
  static constexpr std::int64_t kRealSecondsPerDay = 5'400;                 // 1 h 30
  static constexpr std::int64_t kGamePerReal = kGameSecondsPerDay / kRealSecondsPerDay;   // 16
  static constexpr std::int64_t kRealSecondsPerYear = 7 * 3'600;            // 7 h
  static constexpr std::int64_t kRealSecondsPerSeason = kRealSecondsPerYear / 4;          // 1 h 45
  static constexpr std::int64_t kNightRealSeconds = 1'800;                  // the last 30 min of each day

  explicit WorldClock(GameTime start = 0) : t_(start) {}
  void advance_real(std::int64_t real_seconds) { t_ += real_seconds * kGamePerReal; }
  GameTime now() const { return t_; }

  std::int64_t real_seconds() const { return t_ / kGamePerReal; }
  std::int64_t day() const { return t_ / kGameSecondsPerDay; }
  // seconds since midnight of the game day, 0..86399
  std::int64_t time_of_day() const { return t_ % kGameSecondsPerDay; }
  bool night() const { return real_seconds() % kRealSecondsPerDay >= kRealSecondsPerDay - kNightRealSeconds; }
  std::int64_t year() const { return real_seconds() / kRealSecondsPerYear; }
  int season() const { return int(real_seconds() % kRealSecondsPerYear / kRealSecondsPerSeason); }   // 0 spring

 private:
  GameTime t_;
};

// Age in TENTHS of years of life from the real seconds lived (piecewise linear, integer).
class LifeClock {
 public:
  struct Stage { std::int64_t real_seconds; std::int32_t from_tenths, to_tenths; };
  static constexpr Stage kStages[] = {
      {15 * 3'600, 0, 140},      // childhood
      {6 * 3'600, 140, 180},     // teenage
      {105 * 3'600, 180, 600},   // adulthood
      {24 * 3'600, 600, 750},    // old age
  };
  static constexpr std::int32_t age_tenths(std::int64_t lived_real_seconds) {
    std::int64_t r = lived_real_seconds < 0 ? 0 : lived_real_seconds;
    for (const Stage& s : kStages) {
      if (r < s.real_seconds) return s.from_tenths + std::int32_t((s.to_tenths - s.from_tenths) * r / s.real_seconds);
      r -= s.real_seconds;
    }
    return kStages[3].to_tenths;   // past the expected life: the engine's mortality decides, not the clock
  }
  static constexpr std::int64_t lifespan_real_seconds() {
    std::int64_t t = 0;
    for (const Stage& s : kStages) t += s.real_seconds;
    return t;
  }
};

}  // namespace em::social
