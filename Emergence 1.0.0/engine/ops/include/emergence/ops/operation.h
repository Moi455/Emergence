// The Operation (docs/14 section 4.6, format v1): every change of the world and every
// perceptible act is one typed, versioned, serialisable Operation. Little-endian, 48-byte
// header followed by an opaque payload (a sequence of typed elements written with PayloadWriter).
// Nothing here reads a clock, an address or a random source.
#pragma once
#include <cstddef>
#include <cstdint>
#include <span>
#include <vector>

namespace em::ops {

// Registry of operation kinds: append-only, never renumber. 0 is invalid.
enum class OpKind : std::uint16_t {
  Invalid = 0,
  Act = 1,
  VoxelEdit = 2,
  EntityDelta = 3,
  Spawn = 4,
  Destroy = 5,
  Move = 6,
  Field = 7,
};
inline constexpr std::uint16_t kMaxKnownKind = 7;

// Header flag bits.
inline constexpr std::uint8_t kFlagVoxels = 1u << 0;
inline constexpr std::uint8_t kFlagEntities = 1u << 1;
inline constexpr std::uint8_t kFlagFields = 1u << 2;
inline constexpr std::uint8_t kFlagSpeech = 1u << 3;

inline constexpr std::uint8_t kCurrentVersion = 1;
inline constexpr std::size_t kHeaderBytes = 48;
inline constexpr std::uint32_t kMaxPayloadBytes = 1u << 20;
inline constexpr std::uint16_t kNone16 = 0xFFFF;
inline constexpr std::uint32_t kWorldLaw = 0;   // author 0 = law of the world

struct Operation {
  std::uint64_t op_id = 0;      // world sequence, assigned by the bus at flush, never reused
  std::uint64_t tick = 0;       // simulation step
  std::uint32_t seq = 0;        // rank inside the tick, assigned by the bus at flush
  std::uint32_t author = kWorldLaw;
  std::uint64_t cause = 0;      // op_id or decision_id (bit 63 = decision)
  std::uint16_t kind = 0;       // OpKind
  std::uint16_t process = kNone16;
  std::uint16_t gesture = kNone16;
  std::uint8_t flags = 0;
  std::uint8_t version = kCurrentVersion;
  std::uint8_t noise = 0, sight = 0, trace = 0, reserved = 0;
  std::vector<std::uint8_t> payload;

  OpKind op_kind() const { return static_cast<OpKind>(kind); }
  bool operator==(const Operation&) const = default;
};

enum class DecodeStatus : std::uint8_t {
  Ok,
  Truncated,            // fewer bytes than the header or its payload_bytes announce
  UnsupportedVersion,   // version 0 or newer than this build: refused, never guessed
  UnknownKind,          // a kind this build does not know (future registry entry)
  PayloadTooLarge,
};
const char* to_string(DecodeStatus s);

// Appends the canonical encoding of op to out. The version written is always kCurrentVersion.
void encode(const Operation& op, std::vector<std::uint8_t>& out);
std::vector<std::uint8_t> encode(const Operation& op);

// Decodes one operation from the front of bytes; consumed is set on Ok only.
DecodeStatus decode(std::span<const std::uint8_t> bytes, Operation& out, std::size_t& consumed);

// Lexicographic total order used by the bus: (tick, author, decision_seq, k), then kind, then
// payload bytes. Independent of producer thread, submission time and memory addresses.
struct OrderKey {
  std::uint64_t tick = 0;
  std::uint32_t author = 0;
  std::uint32_t decision_seq = 0;
  std::uint32_t k = 0;
};
bool key_less(const OrderKey& a, const OrderKey& b);

// Little-endian payload builder / reader for the typed elements of docs/14 section 4.6.
class PayloadWriter {
 public:
  PayloadWriter& u8(std::uint8_t v);
  PayloadWriter& u16(std::uint16_t v);
  PayloadWriter& u32(std::uint32_t v);
  PayloadWriter& u64(std::uint64_t v);
  PayloadWriter& i32(std::int32_t v) { return u32(static_cast<std::uint32_t>(v)); }
  const std::vector<std::uint8_t>& bytes() const { return bytes_; }
  std::vector<std::uint8_t> take() { return std::move(bytes_); }

 private:
  std::vector<std::uint8_t> bytes_;
};

class PayloadReader {
 public:
  explicit PayloadReader(std::span<const std::uint8_t> b) : b_(b) {}
  bool u8(std::uint8_t& v);
  bool u16(std::uint16_t& v);
  bool u32(std::uint32_t& v);
  bool u64(std::uint64_t& v);
  bool i32(std::int32_t& v);
  std::size_t remaining() const { return b_.size() - pos_; }

 private:
  std::span<const std::uint8_t> b_;
  std::size_t pos_ = 0;
};

}  // namespace em::ops
