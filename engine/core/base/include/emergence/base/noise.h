// Integer gradient noise (Perlin-style) in Q16 fixed point.
// Inputs are in "noise units" Q16: one unit is one lattice cell, i.e. one
// wavelength of the base octave. Output is roughly in [-1, 1] (Q16).
// Pure function of (seed, x, y): safe to call from any thread, in any order.
#pragma once
#include <cstdint>

#include "emergence/base/fixed.h"
#include "emergence/base/hash.h"

namespace em {

namespace detail {
constexpr int64_t fade(int64_t t) {  // 6t^5 - 15t^4 + 10t^3, Q16
  int64_t t3 = (((t * t) >> 16) * t) >> 16;
  int64_t inner = ((t * (6 * t - 15 * kOne)) >> 16) + 10 * kOne;
  return (t3 * inner) >> 16;
}
constexpr int64_t grad(uint64_t h, int64_t dx, int64_t dy) {
  switch (h & 7) {
    case 0: return dx + dy;
    case 1: return -dx + dy;
    case 2: return dx - dy;
    case 3: return -dx - dy;
    case 4: return dx;
    case 5: return -dx;
    case 6: return dy;
    default: return -dy;
  }
}
}  // namespace detail

constexpr int64_t gradient_noise2(uint64_t seed, int64_t x, int64_t y) {
  int64_t xi = x >> 16, yi = y >> 16;
  int64_t xf = x & 0xFFFF, yf = y & 0xFFFF;
  int64_t n00 = detail::grad(hash2(seed, xi, yi), xf, yf);
  int64_t n10 = detail::grad(hash2(seed, xi + 1, yi), xf - kOne, yf);
  int64_t n01 = detail::grad(hash2(seed, xi, yi + 1), xf, yf - kOne);
  int64_t n11 = detail::grad(hash2(seed, xi + 1, yi + 1), xf - kOne, yf - kOne);
  int64_t u = detail::fade(xf), v = detail::fade(yf);
  int64_t a = qlerp(n00, n10, u);
  int64_t b = qlerp(n01, n11, u);
  return qlerp(a, b, v);
}

// Fractal sum: octaves double the frequency and halve the amplitude.
// Normalised so the result stays roughly in [-1, 1].
constexpr int64_t fbm2(uint64_t seed, int64_t x, int64_t y, int octaves) {
  int64_t sum = 0, amp = kOne, total = 0;
  for (int o = 0; o < octaves; ++o) {
    sum += (gradient_noise2(hash_combine(seed, static_cast<uint64_t>(o)), x, y) * amp) >> 16;
    total += amp;
    amp >>= 1;
    x <<= 1;
    y <<= 1;
  }
  return (sum * kOne) / total;
}

// Ridged fractal: sharp crests, used for mountain chains. Result in [0, 1].
constexpr int64_t ridged2(uint64_t seed, int64_t x, int64_t y, int octaves) {
  int64_t sum = 0, amp = kOne, total = 0, weight = kOne;
  for (int o = 0; o < octaves; ++o) {
    int64_t n = kOne - abs64(gradient_noise2(hash_combine(seed, static_cast<uint64_t>(o)), x, y));
    n = clamp64(n, 0, kOne);
    n = (n * n) >> 16;
    n = (n * weight) >> 16;
    weight = clamp64(n * 2, 0, kOne);
    sum += (n * amp) >> 16;
    total += amp;
    amp >>= 1;
    x <<= 1;
    y <<= 1;
  }
  return (sum * kOne) / total;
}

// Converts a coordinate in millimetres to noise units for a given wavelength.
constexpr int64_t to_noise(int64_t pos_mm, int64_t wavelength_mm) {
  return (pos_mm * kOne) / wavelength_mm;
}

}  // namespace em
