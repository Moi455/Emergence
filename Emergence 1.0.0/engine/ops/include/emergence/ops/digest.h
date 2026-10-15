// Small integer-only digests used by the operation bus and journal: CRC-32 (IEEE, reflected)
// for block integrity, FNV-1a 64 for fingerprints. No dependency on other engine modules.
#pragma once
#include <cstddef>
#include <cstdint>
#include <span>

namespace em::ops {

// CRC-32 (polynomial 0xEDB88320), same value as zlib's crc32().
std::uint32_t crc32(std::span<const std::uint8_t> bytes);

// FNV-1a 64-bit, incremental.
class Fnv64 {
 public:
  Fnv64() = default;
  explicit Fnv64(std::uint64_t state) : h_(state) {}   // resume from value()
  void add(std::span<const std::uint8_t> bytes);
  void add_u64(std::uint64_t v);
  std::uint64_t value() const { return h_; }

 private:
  std::uint64_t h_ = 0xcbf29ce484222325ULL;
};

}  // namespace em::ops
