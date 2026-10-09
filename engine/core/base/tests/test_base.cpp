#include <algorithm>
#include <cmath>
#include <cstdlib>
#include <cstdio>
#include <string>
#include <vector>

#include "emergence/base/fingerprint.h"
#include "emergence/base/fixed.h"
#include "emergence/base/hash.h"
#include "emergence/base/image.h"
#include "emergence/base/noise.h"
#include "emergence/base/parallel.h"
#include "emergence/testing/check.h"

using namespace em;

TEST(hash_is_pinned) {
  // Golden values: if these change, every world changes. Never edit them
  // without bumping kWorldGeneratorVersion.
  CHECK_EQ(mix64(0), 0ULL);
  CHECK_EQ(mix64(1), 0x5692161d100b05e5ULL);
  CHECK_EQ(hash2(42, -3, 7), hash2(42, -3, 7));
  CHECK(hash2(42, -3, 7) != hash2(42, 7, -3));
  CHECK(layer_seed(1, Layer::Detail) != layer_seed(1, Layer::Biome));
}

TEST(floor_div_rounds_down) {
  CHECK_EQ(floor_div(7, 2), 3);
  CHECK_EQ(floor_div(-7, 2), -4);
  CHECK_EQ(floor_div(-8, 2), -4);
  CHECK_EQ(floor_div(0, 5), 0);
}

TEST(isqrt_exact) {
  for (uint64_t v : {0ULL, 1ULL, 2ULL, 3ULL, 4ULL, 15ULL, 16ULL, 17ULL, 1000000ULL, 999999999999ULL, 0xFFFFFFFFFFFFFFFFULL}) {
    uint64_t r = isqrt64(v);
    CHECK(r * r <= v);
    CHECK((r + 1) > 0xFFFFFFFFULL || (r + 1) * (r + 1) > v);
  }
}

TEST(qexp2_accuracy) {
  for (int64_t x = -10 * kOne; x <= 12 * kOne; x += kOne / 7) {
    double expect = std::pow(2.0, static_cast<double>(x) / 65536.0);
    double got = static_cast<double>(qexp2(x)) / 65536.0;
    if (expect > 0.01) CHECK(std::fabs(got - expect) / expect < 2e-3);
  }
  CHECK_EQ(qexp2(0), kOne);
  CHECK_EQ(qexp2(10 * kOne), 1024 * kOne);
}

TEST(noise_range_and_continuity) {
  int64_t lo = 0, hi = 0;
  for (int64_t y = 0; y < 200; ++y)
    for (int64_t x = 0; x < 200; ++x) {
      int64_t a = gradient_noise2(9, x * 3000 - 300000, y * 3000);
      lo = std::min(lo, a);
      hi = std::max(hi, a);
      // A step of 1/1000 of a cell moves the value very little.
      int64_t b = gradient_noise2(9, x * 3000 - 300000 + 65, y * 3000);
      CHECK(abs64(a - b) < 400);
    }
  CHECK(lo < -kOne / 3 && hi > kOne / 3);
  CHECK(lo >= -kOne * 3 / 2 && hi <= kOne * 3 / 2);
  int64_t r = ridged2(3, 123456, 654321, 5);
  CHECK(r >= 0 && r <= kOne);
}

TEST(fingerprint_endian_independent) {
  Fingerprint a, b;
  a.add_u32(0x01020304);
  b.add_u8(4);
  b.add_u8(3);
  b.add_u8(2);
  b.add_u8(1);
  CHECK_EQ(a.value(), b.value());
}

TEST(parallel_for_covers_range) {
  std::vector<int> hit(1000, 0);
  set_worker_count(4);
  parallel_for(0, 1000, [&](int64_t b, int64_t e) {
    for (int64_t i = b; i < e; ++i) hit[static_cast<size_t>(i)]++;
  });
  set_worker_count(0);
  int ok = 1;
  for (int h : hit) ok &= h == 1;
  CHECK(ok);
}

TEST(png_writes) {
  std::vector<uint8_t> px(4 * 3 * 3, 128);
  std::string path = std::string(std::getenv("TMPDIR") ? std::getenv("TMPDIR") : "/tmp") + "/em_test.png";
  CHECK(write_png_rgb(path, 4, 3, px));
  std::remove(path.c_str());
}

EMERGENCE_TEST_MAIN()
