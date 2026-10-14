// Rasterisation of ellipsoids and capsules into a chunk, clipped to the
// chunk box. Shared by ore bodies, lenses, boulders, caves and trees.
#include "internal.h"

namespace em::wg {

bool replace_ok(const Mats& m, VoxelId cur, uint8_t mask) {
  if (cur == kAir) return (mask & kRepAir) != 0;
  MaterialClass c = voxel_class(cur);
  if (c == voxel_class(m.leaves) && !m.leaves_is_fallback) return (mask & kRepLeaves) != 0;
  if (c == voxel_class(m.wood) || c == voxel_class(m.bark)) return (mask & kRepWood) != 0;
  if (m.is_soil(cur)) return (mask & kRepSoil) != 0;
  return (mask & kRepRock) != 0;  // bedrock, ore, salt
}

namespace {

struct Range {
  int lo = 0, hi = -1;  // inclusive voxel indices
};

// Voxel indices whose centres fall in [a, b] along an axis starting at o.
Range clip(int64_t o, int64_t v, int64_t a, int64_t b) {
  Range r;
  int64_t lo = floor_div(a - o - v / 2 + v - 1, v);
  int64_t hi = floor_div(b - o - v / 2, v);
  r.lo = static_cast<int>(clamp64(lo, 0, kChunkSize));
  r.hi = static_cast<int>(clamp64(hi, -1, kChunkSize - 1));
  return r;
}

inline bool hole(const RasterStyle& s, int64_t x, int64_t y, int64_t z, int64_t v) {
  if (s.hole_seed == 0 || s.hole_pct <= 0) return false;
  int64_t q = 4 * v;
  uint64_t h = hash3(s.hole_seed, floor_div(x, q), floor_div(y + kYBias, q), floor_div(z, q));
  return static_cast<int32_t>(h % 100) < s.hole_pct;
}

}  // namespace

// The ellipsoid tested at the centres of blocks of s.block_mm (a multiple of
// the voxel, anchored on the voxel boundary next to the centre): a few large
// flat faces, which a greedy mesher merges, instead of a round staircase.
int64_t raster_blocky_ellipsoid(const WorldGen::Impl& g, const ChunkBox& b, const Ellipsoid& e, const RasterStyle& s,
                                VoxelId* out) {
  const int64_t q = s.block_mm;
  const int64_t ax = floor_div(e.cx, b.v) * b.v, ay = floor_div(e.cy, b.v) * b.v, az = floor_div(e.cz, b.v) * b.v;
  auto snap = [&](int64_t c, int64_t anchor) { return anchor + floor_div(c - anchor, q) * q + q / 2; };
  Range rx = clip(b.ox, b.v, e.cx - e.rx - q, e.cx + e.rx + q), ry = clip(b.oy, b.v, e.cy - e.ry - q, e.cy + e.ry + q),
        rz = clip(b.oz, b.v, e.cz - e.rz - q, e.cz + e.rz + q);
  if (rx.lo > rx.hi || ry.lo > ry.hi || rz.lo > rz.hi) return 0;
  constexpr int64_t kUnit = int64_t{1} << 40;
  const int64_t kx = kUnit / (e.rx * e.rx), ky = kUnit / (e.ry * e.ry), kz = kUnit / (e.rz * e.rz);
  int64_t written = 0;
  for (int y = ry.lo; y <= ry.hi; ++y) {
    int64_t dy = snap(b.c(b.oy, y), ay) - e.cy, ty = dy * dy * ky;
    if (ty >= kUnit) continue;
    for (int z = rz.lo; z <= rz.hi; ++z) {
      int64_t dz = snap(b.c(b.oz, z), az) - e.cz, tyz = ty + dz * dz * kz;
      if (tyz >= kUnit) continue;
      VoxelId* row = out + voxel_index(0, y, z);
      for (int x = rx.lo; x <= rx.hi; ++x) {
        int64_t dx = snap(b.c(b.ox, x), ax) - e.cx;
        if (tyz + dx * dx * kx >= kUnit || !replace_ok(g.m, row[x], s.replace)) continue;
        row[x] = s.voxel;
        ++written;
      }
    }
  }
  return written;
}

int64_t raster_ellipsoid(const WorldGen::Impl& g, const ChunkBox& b, const Ellipsoid& e, const RasterStyle& s,
                         VoxelId* out) {
  if (e.rx <= 0 || e.ry <= 0 || e.rz <= 0) return 0;
  if (s.block_mm > b.v) return raster_blocky_ellipsoid(g, b, e, s, out);
  const bool use_noise = s.noise && s.noise_q16 > 0;
  const int64_t grow = use_noise ? s.noise_q16 : 0;
  int64_t ex = e.rx + ((e.rx * grow) >> 16), ey = e.ry + ((e.ry * grow) >> 16), ez = e.rz + ((e.rz * grow) >> 16);
  Range rx = clip(b.ox, b.v, e.cx - ex, e.cx + ex), ry = clip(b.oy, b.v, e.cy - ey, e.cy + ey),
        rz = clip(b.oz, b.v, e.cz - ez, e.cz + ez);
  if (rx.lo > rx.hi || ry.lo > ry.hi || rz.lo > rz.hi) return 0;
  constexpr int64_t kUnit = int64_t{1} << 40;
  const int64_t kx = kUnit / (e.rx * e.rx), ky = kUnit / (e.ry * e.ry), kz = kUnit / (e.rz * e.rz);
  int64_t written = 0;
  // Per row, solve for the x span: inside the inner span the voxel is in
  // whatever the noise; only the shell between inner and outer spans needs it.
  const int64_t thr_in = use_noise ? (kOne - grow) << 24 : kUnit;
  const int64_t thr_out = use_noise ? (kOne + grow) << 24 : kUnit;
  for (int y = ry.lo; y <= ry.hi; ++y) {
    int64_t yc = b.c(b.oy, y), dy = yc - e.cy;
    int64_t ty = dy * dy * ky;
    if (ty >= thr_out) continue;
    for (int z = rz.lo; z <= rz.hi; ++z) {
      int64_t zc = b.c(b.oz, z), dz = zc - e.cz;
      int64_t tyz = ty + dz * dz * kz;
      if (tyz >= thr_out) continue;
      int64_t span_out = static_cast<int64_t>(isqrt64(static_cast<uint64_t>((thr_out - tyz) / kx))) + 1;
      int64_t span_in = tyz < thr_in ? static_cast<int64_t>(isqrt64(static_cast<uint64_t>((thr_in - tyz) / kx))) - 1 : -1;
      Range r = clip(b.ox, b.v, e.cx - span_out, e.cx + span_out);
      r.lo = std::max(r.lo, rx.lo);
      r.hi = std::min(r.hi, rx.hi);
      VoxelId* row = out + voxel_index(0, y, z);
      for (int x = r.lo; x <= r.hi; ++x) {
        int64_t xc = b.c(b.ox, x), dx = xc - e.cx;
        if (abs64(dx) > span_in) {
          int64_t d = tyz + dx * dx * kx;
          int64_t thr = use_noise ? (kOne + ((s.noise->at(xc, yc, zc) * s.noise_q16) >> 16)) << 24 : kUnit;
          if (d >= thr) continue;
        }
        if (!replace_ok(g.m, row[x], s.replace)) continue;
        if (hole(s, xc, yc, zc, b.v)) continue;
        row[x] = s.voxel;
        ++written;
      }
    }
  }
  return written;
}

int64_t raster_capsule(const WorldGen::Impl& g, const ChunkBox& b, const Capsule& c, const RasterStyle& s,
                       VoxelId* out) {
  const bool use_noise = s.noise && s.noise_q16 > 0;
  int64_t rmax = std::max(c.ra, c.rb);
  if (rmax <= 0) return 0;
  int64_t ext = rmax + (use_noise ? ((rmax * s.noise_q16) >> 16) : 0);
  Range rx = clip(b.ox, b.v, std::min(c.ax, c.bx) - ext, std::max(c.ax, c.bx) + ext);
  Range ry = clip(b.oy, b.v, std::min(c.ay, c.by) - ext, std::max(c.ay, c.by) + ext);
  Range rz = clip(b.oz, b.v, std::min(c.az, c.bz) - ext, std::max(c.az, c.bz) + ext);
  if (rx.lo > rx.hi || ry.lo > ry.hi || rz.lo > rz.hi) return 0;
  const int64_t abx = c.bx - c.ax, aby = c.by - c.ay, abz = c.bz - c.az;
  const int64_t len2 = abx * abx + aby * aby + abz * abz;
  int64_t written = 0;
  for (int y = ry.lo; y <= ry.hi; ++y) {
    int64_t yc = b.c(b.oy, y), apy = yc - c.ay;
    for (int z = rz.lo; z <= rz.hi; ++z) {
      int64_t zc = b.c(b.oz, z), apz = zc - c.az;
      VoxelId* row = out + voxel_index(0, y, z);
      for (int x = rx.lo; x <= rx.hi; ++x) {
        int64_t xc = b.c(b.ox, x), apx = xc - c.ax;
        int64_t t = 0;
        if (len2 > 0) t = clamp64(((apx * abx + apy * aby + apz * abz) << 8) / (len2 >> 8 | 1), 0, kOne);
        int64_t px = apx - ((abx * t) >> 16), py = apy - ((aby * t) >> 16), pz = apz - ((abz * t) >> 16);
        int64_t d2 = px * px + py * py + pz * pz;
        int64_t r = c.ra + (((c.rb - c.ra) * t) >> 16);
        if (use_noise) r += (r * ((s.noise->at(xc, yc, zc) * s.noise_q16) >> 16)) >> 16;
        if (d2 >= r * r) continue;
        if (!replace_ok(g.m, row[x], s.replace)) continue;
        if (hole(s, xc, yc, zc, b.v)) continue;
        row[x] = s.voxel;
        ++written;
      }
    }
  }
  return written;
}

}  // namespace em::wg
