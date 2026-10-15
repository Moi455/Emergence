// binary16 conversion and crc32 against known values (the exhaustive comparison with numpy is tests/test_native.py).
#include "emergence/social/tokenizer/tokenizer.h"
#include "emergence/testing/check.h"

using namespace em::social::tok2;

TEST(half_known_values) {
  CHECK_EQ(int(to_half_bits(1.0)), 0x3c00);
  CHECK_EQ(int(to_half_bits(-2.0)), 0xc000);
  CHECK_EQ(int(to_half_bits(0.0)), 0);
  CHECK_EQ(int(to_half_bits(-0.0)), 0);           // never -0.0
  CHECK_EQ(int(to_half_bits(-1e-9)), 0);          // zero after rounding is +0
  CHECK_EQ(int(to_half_bits(65504.0)), 0x7bff);
  CHECK_EQ(int(to_half_bits(65520.0)), 0x7c00);   // rounds up to infinity
  CHECK_EQ(int(to_half_bits(5.960464477539063e-8)), 0x0001);   // smallest subnormal
  CHECK_EQ(int(to_half_bits(2.9802322387695312e-8)), 0x0000);  // tie to even: zero
  CHECK_EQ(int(to_half_bits(0.1)), 0x2e66);
  CHECK_EQ(int(to_half_bits(1.0009765625 + 0.00048828125)), 0x3c02);   // tie to even upwards
}

TEST(crc32_known_value) {
  const char* s = "123456789";
  CHECK_EQ(crc32_update(0, s, 9), 0xCBF43926u);
}

EMERGENCE_TEST_MAIN()
