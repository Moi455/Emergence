#include "emergence/mesh/greedy.h"

#include <algorithm>
#include <bit>
#include <vector>

namespace em {

namespace {

constexpr int N = kChunkSize;

struct Work {
  std::vector<VoxelId> dense = std::vector<VoxelId>(kVoxelsPerChunk);
  uint64_t col_x[N * N];  // [y][z], bit x
  uint64_t col_y[N * N];  // [z][x], bit y
  uint64_t col_z[N * N];  // [y][x], bit z
  uint64_t plane[N][N];   // [slice][row], bit = in-plane w axis
};

inline MaterialClass cls_at(const Work& w, int x, int y, int z) {
  return voxel_class(w.dense[static_cast<size_t>(chunk_index(x, y, z))]);
}

// Merges the faces of one direction, slice by slice.
template <typename Coord>
void greedy_planes(Work& w, FaceDir dir, Coord coord, std::vector<Quad>& out, MeshStats& st) {
  for (int s = 0; s < N; ++s) {
    uint64_t* plane = w.plane[s];
    for (int r = 0; r < N; ++r) {
      st.faces += static_cast<size_t>(std::popcount(plane[r]));
    }
    for (int r = 0; r < N; ++r) {
      while (plane[r]) {
        int b0 = std::countr_zero(plane[r]);
        int x, y, z;
        coord(s, r, b0, x, y, z);
        MaterialClass m = cls_at(w, x, y, z);
        int len = 1;
        while (b0 + len < N && ((plane[r] >> (b0 + len)) & 1)) {
          coord(s, r, b0 + len, x, y, z);
          if (cls_at(w, x, y, z) != m) break;
          ++len;
        }
        uint64_t run = (len == 64 ? ~uint64_t{0} : ((uint64_t{1} << len) - 1)) << b0;
        int h = 1;
        while (r + h < N && (plane[r + h] & run) == run) {
          bool same = true;
          for (int b = b0; b < b0 + len && same; ++b) {
            coord(s, r + h, b, x, y, z);
            same = cls_at(w, x, y, z) == m;
          }
          if (!same) break;
          ++h;
        }
        for (int k = 0; k < h; ++k) plane[r + k] &= ~run;
        coord(s, r, b0, x, y, z);
        out.push_back(Quad::make(x, y, z, len, h, dir, m));
        ++st.quads;
      }
    }
  }
}

}  // namespace

Quad Quad::make(int x, int y, int z, int w, int h, FaceDir d, MaterialClass cls) {
  Quad q;
  q.bits = static_cast<uint64_t>(x) | static_cast<uint64_t>(y) << 6 | static_cast<uint64_t>(z) << 12 |
           static_cast<uint64_t>(w - 1) << 18 | static_cast<uint64_t>(h - 1) << 24 |
           static_cast<uint64_t>(d) << 30 | static_cast<uint64_t>(cls) << 33;
  return q;
}

MeshStats mesh_chunk(const Chunk& chunk, const ChunkBorders& borders, std::vector<Quad>& out) {
  static thread_local Work w;
  MeshStats st;
  chunk.decode(w.dense);
  for (int i = 0; i < N * N; ++i) w.col_x[i] = w.col_y[i] = w.col_z[i] = 0;
  for (int y = 0; y < N; ++y)
    for (int z = 0; z < N; ++z) {
      const VoxelId* row = &w.dense[static_cast<size_t>(chunk_index(0, y, z))];
      uint64_t bits = 0;
      for (int x = 0; x < N; ++x) bits |= static_cast<uint64_t>(row[x] != kAir) << x;
      w.col_x[y * N + z] = bits;
      uint64_t m = bits;
      while (m) {
        int x = std::countr_zero(m);
        m &= m - 1;
        w.col_y[z * N + x] |= uint64_t{1} << y;
        w.col_z[y * N + x] |= uint64_t{1} << z;
      }
    }
  const auto& B = borders.solid;
  auto bit = [](uint64_t row, int b) { return (row >> b) & 1; };

  // +X and -X: planes [x][y], bit z.
  for (int d = 0; d < 2; ++d) {
    for (auto& p : w.plane) for (auto& r : p) r = 0;
    const auto& border = B[static_cast<size_t>(d == 0 ? FaceDir::PosX : FaceDir::NegX)];
    for (int y = 0; y < N; ++y)
      for (int z = 0; z < N; ++z) {
        uint64_t c = w.col_x[y * N + z];
        uint64_t f = d == 0 ? c & ~((c >> 1) | (bit(border[static_cast<size_t>(y)], z) << 63))
                            : c & ~((c << 1) | bit(border[static_cast<size_t>(y)], z));
        while (f) {
          int x = std::countr_zero(f);
          f &= f - 1;
          w.plane[x][y] |= uint64_t{1} << z;
        }
      }
    greedy_planes(w, d == 0 ? FaceDir::PosX : FaceDir::NegX,
                  [](int s, int r, int b, int& x, int& y, int& z) { x = s; y = r; z = b; }, out, st);
  }
  // +Y and -Y: planes [y][z], bit x.
  for (int d = 0; d < 2; ++d) {
    for (auto& p : w.plane) for (auto& r : p) r = 0;
    const auto& border = B[static_cast<size_t>(d == 0 ? FaceDir::PosY : FaceDir::NegY)];
    for (int z = 0; z < N; ++z)
      for (int x = 0; x < N; ++x) {
        uint64_t c = w.col_y[z * N + x];
        uint64_t f = d == 0 ? c & ~((c >> 1) | (bit(border[static_cast<size_t>(z)], x) << 63))
                            : c & ~((c << 1) | bit(border[static_cast<size_t>(z)], x));
        while (f) {
          int y = std::countr_zero(f);
          f &= f - 1;
          w.plane[y][z] |= uint64_t{1} << x;
        }
      }
    greedy_planes(w, d == 0 ? FaceDir::PosY : FaceDir::NegY,
                  [](int s, int r, int b, int& x, int& y, int& z) { x = b; y = s; z = r; }, out, st);
  }
  // +Z and -Z: planes [z][y], bit x.
  for (int d = 0; d < 2; ++d) {
    for (auto& p : w.plane) for (auto& r : p) r = 0;
    const auto& border = B[static_cast<size_t>(d == 0 ? FaceDir::PosZ : FaceDir::NegZ)];
    for (int y = 0; y < N; ++y)
      for (int x = 0; x < N; ++x) {
        uint64_t c = w.col_z[y * N + x];
        uint64_t f = d == 0 ? c & ~((c >> 1) | (bit(border[static_cast<size_t>(y)], x) << 63))
                            : c & ~((c << 1) | bit(border[static_cast<size_t>(y)], x));
        while (f) {
          int z = std::countr_zero(f);
          f &= f - 1;
          w.plane[z][y] |= uint64_t{1} << x;
        }
      }
    greedy_planes(w, d == 0 ? FaceDir::PosZ : FaceDir::NegZ,
                  [](int s, int r, int b, int& x, int& y, int& z) { x = b; y = r; z = s; }, out, st);
  }
  return st;
}

void border_from_neighbor(const Chunk& nb, FaceDir d, std::array<uint64_t, 64>& out) {
  for (int r = 0; r < N; ++r) {
    uint64_t row = 0;
    for (int b = 0; b < N; ++b) {
      VoxelId v = kAir;
      switch (d) {
        case FaceDir::PosX: v = nb.get(0, r, b); break;
        case FaceDir::NegX: v = nb.get(N - 1, r, b); break;
        case FaceDir::PosY: v = nb.get(b, 0, r); break;
        case FaceDir::NegY: v = nb.get(b, N - 1, r); break;
        case FaceDir::PosZ: v = nb.get(b, r, 0); break;
        case FaceDir::NegZ: v = nb.get(b, r, N - 1); break;
      }
      row |= static_cast<uint64_t>(v != kAir) << b;
    }
    out[static_cast<size_t>(r)] = row;
  }
}

void downsample(const std::array<const Chunk*, 8>& children, Chunk& out) {
  static thread_local std::vector<VoxelId> child(kVoxelsPerChunk), dense(kVoxelsPerChunk);
  std::fill(dense.begin(), dense.end(), kAir);
  const int H = N / 2;
  for (int c = 0; c < 8; ++c) {
    if (!children[static_cast<size_t>(c)]) continue;
    children[static_cast<size_t>(c)]->decode(child);
    int ox = (c & 1) * H, oz = ((c >> 1) & 1) * H, oy = ((c >> 2) & 1) * H;
    for (int y = 0; y < H; ++y)
      for (int z = 0; z < H; ++z)
        for (int x = 0; x < H; ++x) {
          VoxelId v[8];
          int n = 0;
          for (int k = 0; k < 8; ++k) {
            VoxelId s = child[static_cast<size_t>(chunk_index(2 * x + (k & 1), 2 * y + (k >> 2), 2 * z + ((k >> 1) & 1)))];
            if (s != kAir) v[n++] = s;
          }
          if (n < 4) continue;
          VoxelId best = v[0];
          int best_count = 0;
          for (int a = 0; a < n; ++a) {
            int cnt = 0;
            for (int b = 0; b < n; ++b) cnt += v[b] == v[a];
            if (cnt > best_count || (cnt == best_count && v[a] < best)) {
              best = v[a];
              best_count = cnt;
            }
          }
          dense[static_cast<size_t>(chunk_index(ox + x, oy + y, oz + z))] = best;
        }
  }
  out.clear();
  VoxelId brick[kVoxelsPerBrick];
  for (int by = 0; by < kBricksPerChunk; ++by)
    for (int bz = 0; bz < kBricksPerChunk; ++bz)
      for (int bx = 0; bx < kBricksPerChunk; ++bx) {
        for (int y = 0; y < kBrickSize; ++y)
          for (int z = 0; z < kBrickSize; ++z)
            for (int x = 0; x < kBrickSize; ++x)
              brick[in_brick_index(x, y, z)] =
                  dense[static_cast<size_t>(chunk_index(bx * 8 + x, by * 8 + y, bz * 8 + z))];
        out.set_brick(brick_index(bx, by, bz), brick);
      }
}

}  // namespace em
