#include "emergence/mesh/chunk_cache.h"

#include <algorithm>

#include "emergence/base/fixed.h"
#include "emergence/base/parallel.h"

namespace em {

Chunk ChunkCache::make(int lod, int x, int y, int z) {
  Chunk c;
  VoxelId v = kAir;
  SourceKind k = src_.classify(lod, {x, y, z}, &v);
  if (k != SourceKind::Mixed) {
    c.clear(v);
  } else if (lod == 0 || src_.native_lod()) {
    src_.fill(lod, {x, y, z}, c);
  } else {
    std::array<const Chunk*, 8> kids{};
    for (int i = 0; i < 8; ++i)
      kids[static_cast<size_t>(i)] = &get(lod - 1, 2 * x + (i & 1), 2 * y + (i >> 2), 2 * z + ((i >> 1) & 1));
    downsample(kids, c);
  }
  c.coord = {x, y, z};
  return c;
}

const Chunk& ChunkCache::get(int lod, int x, int y, int z) {
  LodChunk key{lod, x, y, z};
  auto it = cache_.find(key);
  if (it != cache_.end()) return it->second;
  Chunk c = make(lod, x, y, z);
  return cache_.emplace(key, std::move(c)).first->second;
}

const Chunk* ChunkCache::find(int lod, int x, int y, int z) const {
  auto it = cache_.find(LodChunk{lod, x, y, z});
  return it == cache_.end() ? nullptr : &it->second;
}

void ChunkCache::prefetch(const std::vector<LodChunk>& keys) {
  std::vector<LodChunk> missing;
  for (const LodChunk& k : keys)
    if (!cache_.count(k)) missing.push_back(k);
  std::sort(missing.begin(), missing.end());
  missing.erase(std::unique(missing.begin(), missing.end()), missing.end());
  if (missing.empty()) return;
  if (!src_.native_lod()) {
    for (const LodChunk& k : missing) get(k.lod, k.x, k.y, k.z);
    return;
  }
  std::vector<Chunk> made(missing.size());
  parallel_each(0, static_cast<int64_t>(missing.size()), [&](int64_t i) {
    const LodChunk& k = missing[static_cast<size_t>(i)];
    made[static_cast<size_t>(i)] = make(k.lod, k.x, k.y, k.z);
  });
  for (size_t i = 0; i < missing.size(); ++i) cache_.emplace(missing[i], std::move(made[i]));
}

void ChunkCache::border(int lod, int x, int y, int z, FaceDir d, std::array<uint64_t, 64>& out) {
  static const int nb[6][3] = {{1, 0, 0}, {-1, 0, 0}, {0, 1, 0}, {0, -1, 0}, {0, 0, 1}, {0, 0, -1}};
  const int di = static_cast<int>(d);
  const int nx = x + nb[di][0], ny = y + nb[di][1], nz = z + nb[di][2];
  if (const Chunk* c = find(lod, nx, ny, nz)) {
    border_from_neighbor(*c, d, out);
    return;
  }
  VoxelId v = kAir;
  SourceKind k = src_.classify(lod, {nx, ny, nz}, &v);
  if (k != SourceKind::Mixed) {
    out.fill(k == SourceKind::Solid ? ~uint64_t{0} : 0);
    return;
  }
  border_from_neighbor(get(lod, nx, ny, nz), d, out);
}

MeshStats ChunkCache::mesh(int lod, int x, int y, int z, std::vector<Quad>& out, uint8_t open_sides, bool ao) {
  ChunkBorders b;
  for (int d = 0; d < 6; ++d) {
    auto& row = b.solid[static_cast<size_t>(d)];
    if (open_sides & (1 << d)) row.fill(0);
    else border(lod, x, y, z, static_cast<FaceDir>(d), row);
  }
  const Chunk& c = get(lod, x, y, z);
  VoxelId u = kAir;
  if (c.is_uniform(&u)) {
    if (u == kAir) return {};
    bool closed = true;
    for (const auto& side : b.solid)
      for (uint64_t r : side) closed = closed && r == ~uint64_t{0};
    if (closed) return {};
  }
  return mesh_chunk(c, b, out, ao);
}

std::vector<LodChunk> ChunkCache::edit_sphere(int64_t cx, int64_t cy, int64_t cz, int64_t r, VoxelId v) {
  std::vector<LodChunk> changed;
  const int64_t N = kChunkSize;
  const int64_t r2 = r * r;
  std::vector<VoxelId> dense(kVoxelsPerChunk);
  for (int64_t qy = floor_div(cy - r, N); qy <= floor_div(cy + r, N); ++qy)
    for (int64_t qz = floor_div(cz - r, N); qz <= floor_div(cz + r, N); ++qz)
      for (int64_t qx = floor_div(cx - r, N); qx <= floor_div(cx + r, N); ++qx) {
        LodChunk key{0, static_cast<int32_t>(qx), static_cast<int32_t>(qy), static_cast<int32_t>(qz)};
        Chunk& c = const_cast<Chunk&>(get(0, key.x, key.y, key.z));
        c.decode(dense);
        bool any = false;
        for (int y = 0; y < N; ++y)
          for (int z = 0; z < N; ++z)
            for (int x = 0; x < N; ++x) {
              // Voxel centres at (q * 64 + local + 0.5); compare doubled values.
              int64_t dx = 2 * (qx * N + x) + 1 - 2 * cx, dy = 2 * (qy * N + y) + 1 - 2 * cy,
                      dz = 2 * (qz * N + z) + 1 - 2 * cz;
              if (dx * dx + dy * dy + dz * dz > 4 * r2) continue;
              VoxelId& d = dense[static_cast<size_t>(chunk_index(x, y, z))];
              if (d != v) {
                d = v;
                any = true;
              }
            }
        if (!any) continue;
        VoxelId brick[kVoxelsPerBrick];
        for (int b = 0; b < kBricks; ++b) {
          int bx = b % 8, bz = (b / 8) % 8, by = b / 64;
          for (int y = 0; y < 8; ++y)
            for (int z = 0; z < 8; ++z)
              for (int x = 0; x < 8; ++x)
                brick[in_brick_index(x, y, z)] = dense[static_cast<size_t>(chunk_index(bx * 8 + x, by * 8 + y, bz * 8 + z))];
          c.set_brick(brick_index(bx, by, bz), brick);
        }
        c.compact();
        edited_.insert(key);
        changed.push_back(key);
      }
  return changed;
}

VoxelId ChunkCache::voxel(int64_t vx, int64_t vy, int64_t vz) {
  const int64_t N = kChunkSize;
  int64_t qx = floor_div(vx, N), qy = floor_div(vy, N), qz = floor_div(vz, N);
  if (!find(0, static_cast<int>(qx), static_cast<int>(qy), static_cast<int>(qz))) {
    VoxelId u = kAir;
    if (src_.classify(0, {static_cast<int32_t>(qx), static_cast<int32_t>(qy), static_cast<int32_t>(qz)}, &u) !=
        SourceKind::Mixed)
      return u;
  }
  const Chunk& c = get(0, static_cast<int>(qx), static_cast<int>(qy), static_cast<int>(qz));
  return c.get(static_cast<int>(vx - qx * N), static_cast<int>(vy - qy * N), static_cast<int>(vz - qz * N));
}

void ChunkCache::evict_outside(int lod, int64_t x0, int64_t z0, int64_t x1, int64_t z1) {
  for (auto it = cache_.begin(); it != cache_.end();) {
    const LodChunk& k = it->first;
    bool keep = k.lod != lod || (k.x >= x0 && k.x <= x1 && k.z >= z0 && k.z <= z1) || edited_.count(k);
    it = keep ? std::next(it) : cache_.erase(it);
  }
}

size_t ChunkCache::memory_bytes() const {
  size_t b = 0;
  for (const auto& [k, c] : cache_) b += sizeof(Chunk) + c.pool_bytes();
  return b;
}

}  // namespace em
