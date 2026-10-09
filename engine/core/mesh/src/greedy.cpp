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
  uint32_t key[N][N];     // merge key of the faces of one slice: class << 8 | ao, bit 31 = mergeable
  bool ao = true;
};

inline MaterialClass cls_at(const Work& w, int x, int y, int z) {
  return voxel_class(w.dense[static_cast<size_t>(chunk_index(x, y, z))]);
}

// Solidity at a cell in [-1, 64]^3: inside from the chunk, on the six face
// layers from the borders, air elsewhere (edges and corners of the chunk).
inline bool solid_at(const Work& w, const ChunkBorders& B, int x, int y, int z) {
  bool ox = x < 0 || x >= N, oy = y < 0 || y >= N, oz = z < 0 || z >= N;
  if (!ox && !oy && !oz) return (w.col_x[y * N + z] >> x) & 1;
  if (int(ox) + int(oy) + int(oz) > 1) return false;
  auto row = [&](FaceDir d, int r, int b) { return (B.solid[static_cast<size_t>(d)][static_cast<size_t>(r)] >> b) & 1; };
  if (ox) return row(x < 0 ? FaceDir::NegX : FaceDir::PosX, y, z);
  if (oy) return row(y < 0 ? FaceDir::NegY : FaceDir::PosY, z, x);
  return row(z < 0 ? FaceDir::NegZ : FaceDir::PosZ, y, x);
}

// Ambient occlusion of the four corners of a unit face (0 = darkest, 3 = open),
// packed 2 bits each in the order (u-, v-), (u+, v-), (u-, v+), (u+, v+) where
// u is the quad's w axis and v its h axis.
uint8_t face_ao(const Work& w, const ChunkBorders& B, FaceDir d, int x, int y, int z) {
  static const int nrm[6][3] = {{1, 0, 0}, {-1, 0, 0}, {0, 1, 0}, {0, -1, 0}, {0, 0, 1}, {0, 0, -1}};
  // u (w axis) and v (h axis) per direction: X faces (z, y), Y faces (x, z), Z faces (x, y).
  static const int ua[6][3] = {{0, 0, 1}, {0, 0, 1}, {1, 0, 0}, {1, 0, 0}, {1, 0, 0}, {1, 0, 0}};
  static const int va[6][3] = {{0, 1, 0}, {0, 1, 0}, {0, 0, 1}, {0, 0, 1}, {0, 1, 0}, {0, 1, 0}};
  const int di = static_cast<int>(d);
  const int fx = x + nrm[di][0], fy = y + nrm[di][1], fz = z + nrm[di][2];
  uint8_t out = 0;
  for (int c = 0; c < 4; ++c) {
    int su = (c & 1) ? 1 : -1, sv = (c & 2) ? 1 : -1;
    bool s1 = solid_at(w, B, fx + su * ua[di][0], fy + su * ua[di][1], fz + su * ua[di][2]);
    bool s2 = solid_at(w, B, fx + sv * va[di][0], fy + sv * va[di][1], fz + sv * va[di][2]);
    bool cn = solid_at(w, B, fx + su * ua[di][0] + sv * va[di][0], fy + su * ua[di][1] + sv * va[di][1],
                       fz + su * ua[di][2] + sv * va[di][2]);
    int ao = (s1 && s2) ? 0 : 3 - (int(s1) + int(s2) + int(cn));
    out = static_cast<uint8_t>(out | ao << (2 * c));
  }
  return out;
}

// Merges the faces of one direction, slice by slice.
template <typename Coord>
void greedy_planes(Work& w, const ChunkBorders& B, FaceDir dir, Coord coord, std::vector<Quad>& out, MeshStats& st) {
  // Faces merge when class and corner occlusion match; a face whose four
  // corners differ stays alone so its gradient is not stretched.
  constexpr uint32_t kMergeable = 1u << 31;
  auto key = [&](int r, int b) { return w.key[r][b] & ~kMergeable; };
  for (int s = 0; s < N; ++s) {
    uint64_t* plane = w.plane[s];
    for (int r = 0; r < N; ++r) {
      st.faces += static_cast<size_t>(std::popcount(plane[r]));
      uint64_t m = plane[r];
      while (m) {
        int b = std::countr_zero(m);
        m &= m - 1;
        int x, y, z;
        coord(s, r, b, x, y, z);
        uint8_t ao = w.ao ? face_ao(w, B, dir, x, y, z) : 0xFF;
        bool uniform = ao == 0x00 || ao == 0x55 || ao == 0xAA || ao == 0xFF;
        w.key[r][b] = static_cast<uint32_t>(cls_at(w, x, y, z)) << 8 | ao | (uniform ? kMergeable : 0);
      }
    }
    for (int r = 0; r < N; ++r) {
      while (plane[r]) {
        int b0 = std::countr_zero(plane[r]);
        int x, y, z;
        coord(s, r, b0, x, y, z);
        const uint32_t m = key(r, b0);
        const bool mergeable = w.key[r][b0] & kMergeable;
        int len = 1;
        while (mergeable && b0 + len < N && ((plane[r] >> (b0 + len)) & 1)) {
          if (key(r, b0 + len) != m) break;
          ++len;
        }
        uint64_t run = (len == 64 ? ~uint64_t{0} : ((uint64_t{1} << len) - 1)) << b0;
        int h = 1;
        while (mergeable && r + h < N && (plane[r + h] & run) == run) {
          bool same = true;
          for (int b = b0; b < b0 + len && same; ++b) same = key(r + h, b) == m;
          if (!same) break;
          ++h;
        }
        for (int k = 0; k < h; ++k) plane[r + k] &= ~run;
        coord(s, r, b0, x, y, z);
        out.push_back(Quad::make(x, y, z, len, h, dir, static_cast<MaterialClass>(m >> 8), static_cast<uint8_t>(m & 255)));
        ++st.quads;
      }
    }
  }
}

}  // namespace

Quad Quad::make(int x, int y, int z, int w, int h, FaceDir d, MaterialClass cls, uint8_t ao) {
  Quad q;
  q.bits = static_cast<uint64_t>(x) | static_cast<uint64_t>(y) << 6 | static_cast<uint64_t>(z) << 12 |
           static_cast<uint64_t>(w - 1) << 18 | static_cast<uint64_t>(h - 1) << 24 |
           static_cast<uint64_t>(d) << 30 | static_cast<uint64_t>(cls) << 33 | static_cast<uint64_t>(ao) << 42;
  return q;
}

MeshStats mesh_chunk(const Chunk& chunk, const ChunkBorders& borders, std::vector<Quad>& out, bool ambient_occlusion) {
  static thread_local Work w;
  w.ao = ambient_occlusion;
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
    greedy_planes(w, borders, d == 0 ? FaceDir::PosX : FaceDir::NegX,
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
    greedy_planes(w, borders, d == 0 ? FaceDir::PosY : FaceDir::NegY,
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
    greedy_planes(w, borders, d == 0 ? FaceDir::PosZ : FaceDir::NegZ,
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
