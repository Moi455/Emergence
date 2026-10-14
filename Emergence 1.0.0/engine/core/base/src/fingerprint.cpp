#include "emergence/base/fingerprint.h"

#include "emergence/base/hash.h"

namespace em {

namespace {
constexpr uint64_t kPrime = 0x100000001b3ULL;
}

void Fingerprint::add_u8(uint8_t v) { h_ = (h_ ^ v) * kPrime; }
void Fingerprint::add_u16(uint16_t v) {
  add_u8(static_cast<uint8_t>(v));
  add_u8(static_cast<uint8_t>(v >> 8));
}
void Fingerprint::add_u32(uint32_t v) {
  add_u16(static_cast<uint16_t>(v));
  add_u16(static_cast<uint16_t>(v >> 16));
}
void Fingerprint::add_u64(uint64_t v) {
  add_u32(static_cast<uint32_t>(v));
  add_u32(static_cast<uint32_t>(v >> 32));
}
void Fingerprint::add(std::span<const uint8_t> v) {
  for (uint8_t x : v) add_u8(x);
}
void Fingerprint::add(std::span<const uint16_t> v) {
  for (uint16_t x : v) add_u16(x);
}
void Fingerprint::add(std::span<const uint32_t> v) {
  for (uint32_t x : v) add_u32(x);
}
void Fingerprint::add(std::span<const int32_t> v) {
  for (int32_t x : v) add_u32(static_cast<uint32_t>(x));
}
void Fingerprint::add(std::span<const int16_t> v) {
  for (int16_t x : v) add_u16(static_cast<uint16_t>(x));
}
uint64_t Fingerprint::value() const { return mix64(h_); }
std::string Fingerprint::hex() const { return to_hex(value()); }

std::string to_hex(uint64_t v) {
  static const char* d = "0123456789abcdef";
  std::string s(16, '0');
  for (int i = 15; i >= 0; --i, v >>= 4) s[static_cast<size_t>(i)] = d[v & 15];
  return s;
}

}  // namespace em
