// Fixed-point and integer maths for deterministic generation.
// Q16 means 16 fractional bits: 1.0 == 65536. Everything is int64 inside,
// so results are bit-exact on every compiler and CPU (C++20 defines >> on
// negative values as an arithmetic shift).
#pragma once
#include <cstdint>

namespace em {

constexpr int64_t kOne = 65536;  // 1.0 in Q16

constexpr int64_t qmul(int64_t a, int64_t b) { return (a * b) >> 16; }
constexpr int64_t qdiv(int64_t a, int64_t b) { return (a * kOne) / b; }

constexpr int64_t clamp64(int64_t v, int64_t lo, int64_t hi) {
  return v < lo ? lo : (v > hi ? hi : v);
}
constexpr int64_t abs64(int64_t v) { return v < 0 ? -v : v; }
constexpr int64_t min64(int64_t a, int64_t b) { return a < b ? a : b; }
constexpr int64_t max64(int64_t a, int64_t b) { return a > b ? a : b; }

// Floor division that rounds toward minus infinity (C++ '/' truncates).
constexpr int64_t floor_div(int64_t a, int64_t b) {
  int64_t q = a / b;
  return (a % b != 0 && ((a < 0) != (b < 0))) ? q - 1 : q;
}

// Lerp in Q16: a + (b - a) * t, t in [0, 1].
constexpr int64_t qlerp(int64_t a, int64_t b, int64_t t) { return a + (((b - a) * t) >> 16); }

// Smoothstep of x between edges e0 < e1, result in Q16 [0, 1].
constexpr int64_t qsmoothstep(int64_t e0, int64_t e1, int64_t x) {
  int64_t t = clamp64(((x - e0) * kOne) / (e1 - e0), 0, kOne);
  return (t * t >> 16) * (3 * kOne - 2 * t) >> 16;
}

// Linear ramp of x between e0 and e1, result in Q16 [0, 1].
constexpr int64_t qramp(int64_t e0, int64_t e1, int64_t x) {
  return clamp64(((x - e0) * kOne) / (e1 - e0), 0, kOne);
}

// Integer square root: largest r with r*r <= v.
constexpr uint64_t isqrt64(uint64_t v) {
  uint64_t r = 0;
  uint64_t bit = uint64_t{1} << 62;
  while (bit > v) bit >>= 2;
  while (bit != 0) {
    if (v >= r + bit) {
      v -= r + bit;
      r = (r >> 1) + bit;
    } else {
      r >>= 1;
    }
    bit >>= 2;
  }
  return r;
}

// 2^x with x in Q16, result in Q16. Cubic minimax for the fraction
// (max relative error about 1e-4), exact shifts for the integer part.
constexpr int64_t qexp2(int64_t x) {
  int64_t ip = x >> 16;
  int64_t f = x & 0xFFFF;
  int64_t p = kOne + ((f * (45560 + ((f * (14823 + ((f * 5154) >> 16))) >> 16))) >> 16);
  if (ip >= 0) return ip > 40 ? INT64_MAX : p << ip;
  return ip < -40 ? 0 : p >> (-ip);
}

}  // namespace em
