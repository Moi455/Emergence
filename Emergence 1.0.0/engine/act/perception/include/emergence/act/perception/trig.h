// Integer trigonometry for the perception (no libm: the same bits on every machine). Angles are milli-radians.
// Accuracy (measured by the test): sin/cos within 0.3 % of full scale, atan2 within 8 milli-radians (0.46 degree).
#pragma once
#include <cstdint>

namespace em::act::perception {

inline constexpr std::int32_t kPiMilli = 3142;
inline constexpr std::int32_t kTwoPiMilli = 6283;

// Wraps an angle into (-pi, pi].
constexpr std::int32_t wrap_angle(std::int64_t a) {
  a %= kTwoPiMilli;
  if (a > kPiMilli) a -= kTwoPiMilli;
  if (a <= -kPiMilli) a += kTwoPiMilli;
  return static_cast<std::int32_t>(a);
}

// sin in per-mille (-1000..1000): parabola 4x(pi-x)/pi^2 refined by the 0.225 correction.
constexpr std::int32_t sin_milli(std::int64_t angle_mrad) {
  std::int64_t x = angle_mrad % kTwoPiMilli;
  if (x < 0) x += kTwoPiMilli;
  const bool neg = x > kPiMilli;
  if (neg) x -= kPiMilli;
  std::int64_t y = 4000 * x * (kPiMilli - x) / (std::int64_t(kPiMilli) * kPiMilli);   // 0..1000
  y = y + 225 * (y * y / 1000 - y) / 1000;
  return static_cast<std::int32_t>(neg ? -y : y);
}
constexpr std::int32_t cos_milli(std::int64_t angle_mrad) { return sin_milli(angle_mrad + 1571); }

// atan2(y, x) in milli-radians, (-pi, pi]; 0 for (0, 0).
constexpr std::int32_t atan2_mrad(std::int64_t y, std::int64_t x) {
  if (x == 0 && y == 0) return 0;
  const std::int64_t ax = x < 0 ? -x : x, ay = y < 0 ? -y : y;
  const bool steep = ay > ax;
  const std::int64_t z = steep ? ax * 1000 / ay : ay * 1000 / ax;   // 0..1000
  std::int64_t a = 785 * z / 1000 + 273 * z * (1000 - z) / 1000000;
  if (steep) a = 1571 - a;
  if (x < 0) a = kPiMilli - a;
  return static_cast<std::int32_t>(y < 0 ? -a : a);
}

// Integer square root (floor) of a non-negative 64-bit value: the IEEE square root (correctly rounded, so the same on
// every machine) as a first guess, then an exact integer correction.
inline std::uint64_t isqrt(std::uint64_t v) {
  std::uint64_t r = static_cast<std::uint64_t>(__builtin_sqrt(static_cast<double>(v)));
  while (r * r > v) --r;
  while ((r + 1) * (r + 1) <= v) ++r;
  return r;
}

}  // namespace em::act::perception
