#include <algorithm>
#include <cstring>

#include "emergence/base/fingerprint.h"
#include "emergence/world/chunk.h"

namespace em {

namespace {

inline VoxelId read_u16(const uint8_t* p) { return static_cast<VoxelId>(p[0] | (p[1] << 8)); }
inline void write_u16(uint8_t* p, VoxelId v) {
  p[0] = static_cast<uint8_t>(v);
  p[1] = static_cast<uint8_t>(v >> 8);
}

size_t data_bytes(const BrickHeader& h) {
  if (h.bits == 0) return 0;
  if (h.bits == 16) return kVoxelsPerBrick * 2;
  size_t pal = h.palette_size == 0 ? 256 : h.palette_size;
  return pal * 2 + kVoxelsPerBrick * h.bits / 8;
}

}  // namespace

void Chunk::clear(VoxelId fill) {
  for (auto& b : bricks_) b = BrickHeader{0, 0, 0, fill};
  pool_.clear();
}

void Chunk::set_brick_uniform(int b, VoxelId v) { bricks_[static_cast<size_t>(b)] = BrickHeader{0, 0, 0, v}; }

void Chunk::set_brick(int b, const VoxelId* v) {
  VoxelId palette[256];
  uint8_t index[kVoxelsPerBrick];
  int pal_n = 0;
  bool raw = false;
  for (int k = 0; k < kVoxelsPerBrick && !raw; ++k) {
    int found = -1;
    for (int q = 0; q < pal_n; ++q)
      if (palette[q] == v[k]) {
        found = q;
        break;
      }
    if (found < 0) {
      if (pal_n == 256) {
        raw = true;
        break;
      }
      palette[pal_n] = v[k];
      found = pal_n++;
    }
    index[k] = static_cast<uint8_t>(found);
  }
  if (!raw && pal_n == 1) {
    set_brick_uniform(b, palette[0]);
    return;
  }
  BrickHeader h;
  h.offset = static_cast<uint32_t>(pool_.size());
  if (raw) {
    h.bits = 16;
    pool_.resize(pool_.size() + kVoxelsPerBrick * 2);
    for (int k = 0; k < kVoxelsPerBrick; ++k) write_u16(&pool_[h.offset + static_cast<size_t>(k) * 2], v[k]);
    bricks_[static_cast<size_t>(b)] = h;
    return;
  }
  h.bits = pal_n <= 2 ? 1 : pal_n <= 4 ? 2 : pal_n <= 16 ? 4 : 8;
  h.palette_size = static_cast<uint8_t>(pal_n == 256 ? 0 : pal_n);
  pool_.resize(pool_.size() + static_cast<size_t>(pal_n) * 2 + kVoxelsPerBrick * h.bits / 8, 0);
  uint8_t* p = &pool_[h.offset];
  for (int q = 0; q < pal_n; ++q) write_u16(p + q * 2, palette[q]);
  uint8_t* d = p + pal_n * 2;
  const int per_byte = 8 / h.bits;
  for (int k = 0; k < kVoxelsPerBrick; ++k)
    d[k / per_byte] = static_cast<uint8_t>(d[k / per_byte] | (index[k] << ((k % per_byte) * h.bits)));
  bricks_[static_cast<size_t>(b)] = h;
}

VoxelId Chunk::get(int x, int y, int z) const {
  const BrickHeader& h = bricks_[static_cast<size_t>(brick_index(x >> 3, y >> 3, z >> 3))];
  if (h.bits == 0) return h.value;
  int k = in_brick_index(x & 7, y & 7, z & 7);
  const uint8_t* p = &pool_[h.offset];
  if (h.bits == 16) return read_u16(p + k * 2);
  size_t pal = h.palette_size == 0 ? 256 : h.palette_size;
  const uint8_t* d = p + pal * 2;
  const int per_byte = 8 / h.bits;
  int idx = (d[k / per_byte] >> ((k % per_byte) * h.bits)) & ((1 << h.bits) - 1);
  return read_u16(p + idx * 2);
}

void Chunk::decode_brick(int b, VoxelId* out) const {
  const BrickHeader& h = bricks_[static_cast<size_t>(b)];
  if (h.bits == 0) {
    std::fill(out, out + kVoxelsPerBrick, h.value);
    return;
  }
  const uint8_t* p = &pool_[h.offset];
  if (h.bits == 16) {
    for (int k = 0; k < kVoxelsPerBrick; ++k) out[k] = read_u16(p + k * 2);
    return;
  }
  size_t pal = h.palette_size == 0 ? 256 : h.palette_size;
  const uint8_t* d = p + pal * 2;
  const int per_byte = 8 / h.bits;
  const int mask = (1 << h.bits) - 1;
  for (int k = 0; k < kVoxelsPerBrick; ++k)
    out[k] = read_u16(p + ((d[k / per_byte] >> ((k % per_byte) * h.bits)) & mask) * 2);
}

void Chunk::decode(std::span<VoxelId> out) const {
  VoxelId tmp[kVoxelsPerBrick];
  for (int by = 0; by < kBricksPerChunk; ++by)
    for (int bz = 0; bz < kBricksPerChunk; ++bz)
      for (int bx = 0; bx < kBricksPerChunk; ++bx) {
        decode_brick(brick_index(bx, by, bz), tmp);
        for (int y = 0; y < kBrickSize; ++y)
          for (int z = 0; z < kBrickSize; ++z)
            std::memcpy(&out[static_cast<size_t>(chunk_index(bx * 8, by * 8 + y, bz * 8 + z))],
                        &tmp[in_brick_index(0, y, z)], kBrickSize * sizeof(VoxelId));
      }
}

void Chunk::compact() {
  std::vector<uint8_t> np;
  np.reserve(pool_.size());
  for (auto& h : bricks_) {
    size_t n = data_bytes(h);
    if (n == 0) continue;
    uint32_t off = static_cast<uint32_t>(np.size());
    np.insert(np.end(), pool_.begin() + h.offset, pool_.begin() + h.offset + static_cast<long>(n));
    h.offset = off;
  }
  pool_ = std::move(np);
}

bool Chunk::is_uniform(VoxelId* value) const {
  for (const auto& h : bricks_)
    if (h.bits != 0 || h.value != bricks_[0].value) return false;
  if (value) *value = bricks_[0].value;
  return true;
}

int Chunk::uniform_brick_count() const {
  int n = 0;
  for (const auto& h : bricks_) n += h.bits == 0;
  return n;
}

size_t Chunk::memory_bytes() const {
  size_t b = 0;
  for (const auto& h : bricks_) b += h.bits == 0 ? 2 : 8 + data_bytes(h);
  return b;
}

uint64_t Chunk::fingerprint() const {
  std::vector<VoxelId> v(kVoxelsPerChunk);
  decode(v);
  Fingerprint f;
  f.add_i32(coord.x);
  f.add_i32(coord.y);
  f.add_i32(coord.z);
  f.add(std::span<const uint16_t>(v));
  return f.value();
}

}  // namespace em
