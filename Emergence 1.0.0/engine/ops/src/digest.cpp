#include "emergence/ops/digest.h"

#include <array>

namespace em::ops {
namespace {

constexpr std::array<std::uint32_t, 256> make_table() {
  std::array<std::uint32_t, 256> t{};
  for (std::uint32_t i = 0; i < 256; ++i) {
    std::uint32_t c = i;
    for (int k = 0; k < 8; ++k) c = (c & 1u) ? (0xEDB88320u ^ (c >> 1)) : (c >> 1);
    t[i] = c;
  }
  return t;
}
constexpr auto kTable = make_table();

}  // namespace

std::uint32_t crc32(std::span<const std::uint8_t> bytes) {
  std::uint32_t c = 0xFFFFFFFFu;
  for (std::uint8_t b : bytes) c = kTable[(c ^ b) & 0xFFu] ^ (c >> 8);
  return c ^ 0xFFFFFFFFu;
}

void Fnv64::add(std::span<const std::uint8_t> bytes) {
  for (std::uint8_t b : bytes) {
    h_ ^= b;
    h_ *= 0x100000001b3ULL;
  }
}

void Fnv64::add_u64(std::uint64_t v) {
  for (int i = 0; i < 8; ++i) {
    h_ ^= static_cast<std::uint8_t>(v >> (8 * i));
    h_ *= 0x100000001b3ULL;
  }
}

}  // namespace em::ops
