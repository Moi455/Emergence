// Acuity: how well one observer perceives something, as a CLARITY in per-mille (0 = nothing, 1000 = perfect), from
//   the distance, the light and the fog, the angle to where the observer faces, what stands in between (SpaceQuery),
//   the attention (SELF_STATE.attention: what is at the centre is perceived finer), the observer's own eye, ear and
//   mind (Body.vision, Body.hearing, MindStatic.perceptiveness, Body.consciousness).
// A percept variable is written only if the clarity reaches its threshold (PerceptRules::min_clarity): the finer the
// detail (an expression, a scar), the closer and the clearer it must be. All integer arithmetic.
// [Hypothese] every constant below is a first value to be tuned by play-tests; none is a catalogue decision.
#pragma once
#include <algorithm>
#include <cstdint>

#include "emergence/act/entity_ops.h"
#include "emergence/social/state_types.h"

namespace em::act::perception {

// The senses of one observer at one tick (copied from its own body and mind; never from the truth of others).
struct SenseProfile {
  Position eye{};
  std::int32_t facing_mrad = 0;   // Spatial.orientation: where the observer looks
  std::int16_t vision = 0, hearing = 0, perceptiveness = 0, consciousness = 0;   // 0..100
  std::int16_t light = 100;        // light around the observer, 0..100
  std::uint16_t fog_pm = 0;
  em::social::MRef attention{};    // one of its own records (SELF_STATE.attention)
  bool awake = false;              // alive and conscious enough to perceive anything
};

namespace acuity {

inline constexpr std::int32_t kFovFullMrad = 524;     // +-30 degrees: sharp central view
inline constexpr std::int32_t kFovEdgeMrad = 1745;    // +-100 degrees: nothing is seen beyond
inline constexpr std::int32_t kNearMm = 1200;         // closer than this, the side and the back are sensed too

// Range of the sight (mm) for something whose own visibility range is `kind_range_mm` (60 m by day for a person).
inline std::int64_t sight_range_mm(const SenseProfile& s, std::int64_t kind_range_mm) {
  const std::int64_t light = 200 + 8 * std::clamp<std::int64_t>(s.light, 0, 100);   // 20 % in the dark .. 100 %
  const std::int64_t fog = 1000 - 700 * std::min<std::int64_t>(s.fog_pm, 1000) / 1000;
  return kind_range_mm * light / 1000 * fog / 1000 * (std::clamp<std::int64_t>(s.vision, 0, 100) * 10) / 1000;
}

inline std::int64_t angle_factor(std::int32_t off_mrad, std::int64_t dist_mm) {
  const std::int32_t a = off_mrad < 0 ? -off_mrad : off_mrad;
  std::int64_t f = a <= kFovFullMrad ? 1000 : a >= kFovEdgeMrad ? 0 : 1000 - std::int64_t(a - kFovFullMrad) * 700 / (kFovEdgeMrad - kFovFullMrad);
  if (dist_mm < kNearMm) f = std::max<std::int64_t>(f, 600);
  return f;
}

// Clarity of seeing a target at dist_mm, off_mrad away from the facing, with `transmission_pm` of the view clear.
inline std::uint16_t sight_clarity(const SenseProfile& s, std::int64_t dist_mm, std::int32_t off_mrad, std::uint16_t transmission_pm,
                                   bool attended, std::int64_t kind_range_mm) {
  if (!s.awake || transmission_pm == 0) return 0;
  const std::int64_t range = sight_range_mm(s, kind_range_mm);
  if (range <= 0 || dist_mm >= range) return 0;
  const std::int64_t r = dist_mm * 1000 / range;                       // 0..999
  const std::int64_t q = (1000 - r) * (1000 - r) / 1000;               // steep: fine details only near
  std::int64_t c = q * angle_factor(off_mrad, dist_mm) / 1000;
  c = c * transmission_pm / 1000;
  c = c * (400 + 6 * std::clamp<std::int64_t>(s.light, 0, 100)) / 1000;            // contrast
  c = c * (attended ? 1300 : 1000) / 1000;                                         // attention
  c = c * (800 + 4 * std::clamp<std::int64_t>(s.perceptiveness, 0, 100)) / 1000;   // a fine eye
  c = c * (std::clamp<std::int64_t>(s.consciousness, 0, 100) * 10) / 1000;
  return static_cast<std::uint16_t>(std::clamp<std::int64_t>(c, 0, 1000));
}

// How far a sound of level 0..10 carries in open, quiet air (mm). Level 1 is a whisper: 2 m at the very most.
inline std::int64_t hearing_range_mm(std::uint8_t level) {
  static constexpr std::int64_t kRange[11] = {0, 2000, 5000, 9000, 15000, 25000, 40000, 60000, 90000, 130000, 200000};
  return kRange[std::min<std::uint8_t>(level, 10)];
}

// Clarity of hearing a sound of `level` made dist_mm away; `ambient` (0..100) masks it, `transmission_pm` is the share
// that passes the walls. A whisper does not cross a crowd (ambient masks up to 80 % of the range).
inline std::uint16_t hearing_clarity(const SenseProfile& s, std::int64_t dist_mm, std::uint8_t level, std::uint16_t transmission_pm,
                                     std::int16_t ambient) {
  if (!s.awake || level == 0 || transmission_pm == 0) return 0;
  const std::int64_t mask = 1000 - 8 * std::clamp<std::int64_t>(ambient, 0, 100);
  const std::int64_t range = hearing_range_mm(level) * mask / 1000 * (std::clamp<std::int64_t>(s.hearing, 0, 100) * 10) / 1000;
  if (range <= 0 || dist_mm >= range) return 0;
  const std::int64_t r = dist_mm * 1000 / range;
  std::int64_t c = 1000 - r;   // a voice fades linearly (the eye's falloff is steeper)
  c = c * transmission_pm / 1000;
  c = c * (800 + 4 * std::clamp<std::int64_t>(s.perceptiveness, 0, 100)) / 1000;
  c = c * (std::clamp<std::int64_t>(s.consciousness, 0, 100) * 10) / 1000;
  return static_cast<std::uint16_t>(std::clamp<std::int64_t>(c, 0, 1000));
}

// A deterministic pseudo-random value in -1000..1000 from integers only (observer, target, field, time bucket): the
// same observer sees the same blur for a while, two observers see different ones. Never rand(), never a clock.
inline std::int32_t noise_pm(std::uint32_t a, std::uint32_t b, std::uint32_t salt, std::uint32_t bucket) {
  std::uint64_t x = (std::uint64_t(a) << 32 | b) * 0x9E3779B97F4A7C15ull ^ (std::uint64_t(salt) << 32 | bucket) * 0xC2B2AE3D27D4EB4Full;
  x ^= x >> 29; x *= 0xBF58476D1CE4E5B9ull; x ^= x >> 32; x *= 0x94D049BB133111EBull; x ^= x >> 29;
  return static_cast<std::int32_t>(x % 2001) - 1000;
}

}  // namespace acuity
}  // namespace em::act::perception
