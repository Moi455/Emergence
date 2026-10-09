// 64-bit fingerprint of generated data, independent of host endianness.
// Used by the determinism tests: same seed => same fingerprint everywhere.
#pragma once
#include <cstddef>
#include <cstdint>
#include <span>
#include <string>

namespace em {

class Fingerprint {
 public:
  void add_u8(uint8_t v);
  void add_u16(uint16_t v);
  void add_u32(uint32_t v);
  void add_u64(uint64_t v);
  void add_i32(int32_t v) { add_u32(static_cast<uint32_t>(v)); }
  void add(std::span<const uint8_t> v);
  void add(std::span<const uint16_t> v);
  void add(std::span<const uint32_t> v);
  void add(std::span<const int32_t> v);
  void add(std::span<const int16_t> v);
  uint64_t value() const;
  std::string hex() const;

 private:
  uint64_t h_ = 0xcbf29ce484222325ULL;  // FNV-1a offset basis
};

std::string to_hex(uint64_t v);

}  // namespace em
