#include "emergence/ops/operation.h"

#include <algorithm>
#include <tuple>

namespace em::ops {
namespace {

void put16(std::vector<std::uint8_t>& o, std::uint16_t v) {
  o.push_back(static_cast<std::uint8_t>(v));
  o.push_back(static_cast<std::uint8_t>(v >> 8));
}
void put32(std::vector<std::uint8_t>& o, std::uint32_t v) {
  for (int i = 0; i < 4; ++i) o.push_back(static_cast<std::uint8_t>(v >> (8 * i)));
}
void put64(std::vector<std::uint8_t>& o, std::uint64_t v) {
  for (int i = 0; i < 8; ++i) o.push_back(static_cast<std::uint8_t>(v >> (8 * i)));
}
std::uint16_t get16(const std::uint8_t* p) { return static_cast<std::uint16_t>(p[0] | (p[1] << 8)); }
std::uint32_t get32(const std::uint8_t* p) {
  return static_cast<std::uint32_t>(p[0]) | (static_cast<std::uint32_t>(p[1]) << 8) |
         (static_cast<std::uint32_t>(p[2]) << 16) | (static_cast<std::uint32_t>(p[3]) << 24);
}
std::uint64_t get64(const std::uint8_t* p) {
  return static_cast<std::uint64_t>(get32(p)) | (static_cast<std::uint64_t>(get32(p + 4)) << 32);
}

}  // namespace

const char* to_string(DecodeStatus s) {
  switch (s) {
    case DecodeStatus::Ok: return "ok";
    case DecodeStatus::Truncated: return "truncated";
    case DecodeStatus::UnsupportedVersion: return "unsupported version";
    case DecodeStatus::UnknownKind: return "unknown kind";
    case DecodeStatus::PayloadTooLarge: return "payload too large";
  }
  return "?";
}

void encode(const Operation& op, std::vector<std::uint8_t>& out) {
  out.reserve(out.size() + kHeaderBytes + op.payload.size());
  put64(out, op.op_id);
  put64(out, op.tick);
  put32(out, op.seq);
  put32(out, op.author);
  put64(out, op.cause);
  put16(out, op.kind);
  put16(out, op.process);
  put16(out, op.gesture);
  out.push_back(op.flags);
  out.push_back(kCurrentVersion);
  put32(out, static_cast<std::uint32_t>(op.payload.size()));
  out.push_back(op.noise);
  out.push_back(op.sight);
  out.push_back(op.trace);
  out.push_back(op.reserved);
  out.insert(out.end(), op.payload.begin(), op.payload.end());
}

std::vector<std::uint8_t> encode(const Operation& op) {
  std::vector<std::uint8_t> v;
  encode(op, v);
  return v;
}

DecodeStatus decode(std::span<const std::uint8_t> b, Operation& out, std::size_t& consumed) {
  if (b.size() < kHeaderBytes) return DecodeStatus::Truncated;
  const std::uint8_t* p = b.data();
  // Offsets: op_id 0, tick 8, seq 16, author 20, cause 24, kind 32, process 34, gesture 36,
  // flags 38, version 39, payload_bytes 40, noise 44, sight 45, trace 46, reserved 47.
  const std::uint8_t version = p[39];
  // Check the version first: a newer header may be laid out differently, so nothing else is trusted.
  if (version == 0 || version > kCurrentVersion) return DecodeStatus::UnsupportedVersion;
  const std::uint32_t payload_bytes = get32(p + 40);
  const std::uint16_t kind = get16(p + 32);
  if (kind == 0 || kind > kMaxKnownKind) return DecodeStatus::UnknownKind;
  if (payload_bytes > kMaxPayloadBytes) return DecodeStatus::PayloadTooLarge;
  if (b.size() - kHeaderBytes < payload_bytes) return DecodeStatus::Truncated;
  Operation op;
  op.op_id = get64(p);
  op.tick = get64(p + 8);
  op.seq = get32(p + 16);
  op.author = get32(p + 20);
  op.cause = get64(p + 24);
  op.kind = kind;
  op.process = get16(p + 34);
  op.gesture = get16(p + 36);
  op.flags = p[38];
  op.version = version;
  op.noise = p[44];
  op.sight = p[45];
  op.trace = p[46];
  op.reserved = p[47];
  op.payload.assign(p + kHeaderBytes, p + kHeaderBytes + payload_bytes);
  out = std::move(op);
  consumed = kHeaderBytes + payload_bytes;
  return DecodeStatus::Ok;
}

bool key_less(const OrderKey& a, const OrderKey& b) {
  return std::tie(a.tick, a.author, a.decision_seq, a.k) < std::tie(b.tick, b.author, b.decision_seq, b.k);
}

PayloadWriter& PayloadWriter::u8(std::uint8_t v) { bytes_.push_back(v); return *this; }
PayloadWriter& PayloadWriter::u16(std::uint16_t v) { put16(bytes_, v); return *this; }
PayloadWriter& PayloadWriter::u32(std::uint32_t v) { put32(bytes_, v); return *this; }
PayloadWriter& PayloadWriter::u64(std::uint64_t v) { put64(bytes_, v); return *this; }

bool PayloadReader::u8(std::uint8_t& v) {
  if (remaining() < 1) return false;
  v = b_[pos_++];
  return true;
}
bool PayloadReader::u16(std::uint16_t& v) {
  if (remaining() < 2) return false;
  v = get16(b_.data() + pos_);
  pos_ += 2;
  return true;
}
bool PayloadReader::u32(std::uint32_t& v) {
  if (remaining() < 4) return false;
  v = get32(b_.data() + pos_);
  pos_ += 4;
  return true;
}
bool PayloadReader::u64(std::uint64_t& v) {
  if (remaining() < 8) return false;
  v = get64(b_.data() + pos_);
  pos_ += 8;
  return true;
}
bool PayloadReader::i32(std::int32_t& v) {
  std::uint32_t u;
  if (!u32(u)) return false;
  v = static_cast<std::int32_t>(u);
  return true;
}

}  // namespace em::ops
