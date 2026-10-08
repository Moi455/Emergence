// Ground surface below the plan's 16 m: bicubic plan relief, coarse detail
// octaves on a grid of 8 voxels, fine octaves per column, roads cut into the
// slope and settlement pads levelled.
#include <algorithm>

#include "internal.h"

namespace em::wg {

namespace {

// Detail amplitude (mm) and craggy share per biome, indexed by em::Biome.
constexpr int32_t kBiomeAmp[] = {600, 250, 150, 700, 800, 900, 500, 350, 1600, 1800, 3000, 1500, 300};
constexpr int32_t kBiomeRocky[] = {0, 0, 0, 0, 0, 0, 0, 0, kOne * 3 / 10, kOne / 2, kOne, kOne * 7 / 10, 0};
constexpr int64_t kDetailWavelength = 24 * M;  // first octave
constexpr int kCoarseOctaves = 4;              // 24, 12, 6, 3 m on the grid
constexpr int kFineOctaves = 3;                // 1.5, 0.75, 0.375 m per column
constexpr int64_t kRoadInfluence = 8 * M;

// Catmull-Rom through p1..p2 at t (Q16).
inline int64_t catmull(int64_t p0, int64_t p1, int64_t p2, int64_t p3, int64_t t) {
  int64_t a = -p0 + 3 * p1 - 3 * p2 + p3;
  int64_t b = 2 * p0 - 5 * p1 + 4 * p2 - p3;
  int64_t c = -p0 + p2;
  int64_t t2 = (t * t) >> 16, t3 = (t2 * t) >> 16;
  return (((a * t3) >> 16) + ((b * t2) >> 16) + ((c * t) >> 16) + 2 * p1) >> 1;
}

// Closest point parameter (Q16) and squared distance from (x, z) to a segment.
inline int64_t seg_dist2(const RoadSeg& s, int64_t x, int64_t z, int64_t* t_out) {
  int64_t dx = s.bx - s.ax, dz = s.bz - s.az;
  int64_t len2 = dx * dx + dz * dz;
  int64_t t = 0;
  if (len2 > 0) t = clamp64(((x - s.ax) * dx + (z - s.az) * dz) / std::max<int64_t>(len2 >> 16, 1), 0, kOne);
  int64_t px = s.ax + ((dx * t) >> 16), pz = s.az + ((dz * t) >> 16);
  *t_out = t;
  return (x - px) * (x - px) + (z - pz) * (z - pz);
}

}  // namespace

// ---------------------------------------------------------------- GridIndex

void GridIndex::build(int64_t map_mm, int64_t cell, const std::vector<std::array<int64_t, 4>>& boxes) {
  cell_mm = cell;
  n = static_cast<int32_t>((map_mm + cell - 1) / cell);
  size_t cells = static_cast<size_t>(n) * static_cast<size_t>(n);
  std::vector<uint32_t> count(cells + 1, 0);
  auto span = [&](const std::array<int64_t, 4>& b, auto&& fn) {
    int32_t i0 = static_cast<int32_t>(clamp64(floor_div(b[0], cell), 0, n - 1));
    int32_t j0 = static_cast<int32_t>(clamp64(floor_div(b[1], cell), 0, n - 1));
    int32_t i1 = static_cast<int32_t>(clamp64(floor_div(b[2], cell), 0, n - 1));
    int32_t j1 = static_cast<int32_t>(clamp64(floor_div(b[3], cell), 0, n - 1));
    for (int32_t j = j0; j <= j1; ++j)
      for (int32_t i = i0; i <= i1; ++i) fn(static_cast<size_t>(j) * static_cast<size_t>(n) + static_cast<size_t>(i));
  };
  for (const auto& b : boxes) span(b, [&](size_t c) { ++count[c + 1]; });
  for (size_t c = 0; c < cells; ++c) count[c + 1] += count[c];
  start = count;
  items.assign(start[cells], 0);
  std::vector<uint32_t> fill(start.begin(), start.end() - 1);
  for (uint32_t id = 0; id < boxes.size(); ++id) span(boxes[id], [&](size_t c) { items[fill[c]++] = id; });
}

void GridIndex::query(int64_t x0, int64_t z0, int64_t x1, int64_t z1, std::vector<uint32_t>* out) const {
  out->clear();
  if (n == 0) return;
  int32_t i0 = static_cast<int32_t>(clamp64(floor_div(x0, cell_mm), 0, n - 1));
  int32_t j0 = static_cast<int32_t>(clamp64(floor_div(z0, cell_mm), 0, n - 1));
  int32_t i1 = static_cast<int32_t>(clamp64(floor_div(x1, cell_mm), 0, n - 1));
  int32_t j1 = static_cast<int32_t>(clamp64(floor_div(z1, cell_mm), 0, n - 1));
  for (int32_t j = j0; j <= j1; ++j)
    for (int32_t i = i0; i <= i1; ++i) {
      size_t c = static_cast<size_t>(j) * static_cast<size_t>(n) + static_cast<size_t>(i);
      out->insert(out->end(), items.begin() + start[c], items.begin() + start[c + 1]);
    }
  std::sort(out->begin(), out->end());
  out->erase(std::unique(out->begin(), out->end()), out->end());
}

// ---------------------------------------------------------------- Lattice3

void Lattice3::build(uint64_t seed, int spacing_shift, int64_t x0, int64_t y0, int64_t z0, int64_t x1, int64_t y1,
                     int64_t z1) {
  shift_ = spacing_shift;
  y0 += kYBias;
  y1 += kYBias;
  bx_ = x0 >> shift_;
  by_ = y0 >> shift_;
  bz_ = z0 >> shift_;
  nx_ = static_cast<int32_t>((x1 >> shift_) - bx_ + 2);
  ny_ = static_cast<int32_t>((y1 >> shift_) - by_ + 2);
  nz_ = static_cast<int32_t>((z1 >> shift_) - bz_ + 2);
  v_.resize(static_cast<size_t>(nx_) * static_cast<size_t>(ny_) * static_cast<size_t>(nz_));
  size_t k = 0;
  for (int32_t y = 0; y < ny_; ++y)
    for (int32_t z = 0; z < nz_; ++z)
      for (int32_t x = 0; x < nx_; ++x)
        v_[k++] = static_cast<int32_t>((hash3(seed, bx_ + x, by_ + y, bz_ + z) & 0x1FFFF)) - kOne;
}

int64_t Lattice3::at(int64_t x, int64_t y, int64_t z) const {
  y += kYBias;
  int64_t mask = (int64_t{1} << shift_) - 1;
  int32_t ix = static_cast<int32_t>((x >> shift_) - bx_), iy = static_cast<int32_t>((y >> shift_) - by_),
          iz = static_cast<int32_t>((z >> shift_) - bz_);
  ix = std::clamp(ix, 0, nx_ - 2);
  iy = std::clamp(iy, 0, ny_ - 2);
  iz = std::clamp(iz, 0, nz_ - 2);
  int64_t fx = ((x & mask) << 16) >> shift_, fy = ((y & mask) << 16) >> shift_, fz = ((z & mask) << 16) >> shift_;
  size_t sx = 1, sz = static_cast<size_t>(nx_), sy = static_cast<size_t>(nx_) * static_cast<size_t>(nz_);
  size_t b = static_cast<size_t>(iy) * sy + static_cast<size_t>(iz) * sz + static_cast<size_t>(ix);
  int64_t c00 = qlerp(v_[b], v_[b + sx], fx), c10 = qlerp(v_[b + sz], v_[b + sz + sx], fx);
  int64_t c01 = qlerp(v_[b + sy], v_[b + sy + sx], fx), c11 = qlerp(v_[b + sy + sz], v_[b + sy + sz + sx], fx);
  return qlerp(qlerp(c00, c10, fz), qlerp(c01, c11, fz), fy);
}

// ---------------------------------------------------------------- surface

uint32_t WorldGen::Impl::cell_at(int64_t x, int64_t z) const {
  int32_t i = static_cast<int32_t>(clamp64(floor_div(x + p.cell_mm / 2, p.cell_mm), 0, p.n - 1));
  int32_t j = static_cast<int32_t>(clamp64(floor_div(z + p.cell_mm / 2, p.cell_mm), 0, p.n - 1));
  return static_cast<uint32_t>(p.idx(i, j));
}

int64_t WorldGen::Impl::plan_cubic(int64_t x, int64_t z) const {
  int32_t i = static_cast<int32_t>(floor_div(x, p.cell_mm)), j = static_cast<int32_t>(floor_div(z, p.cell_mm));
  int64_t fx = ((x - i * p.cell_mm) * kOne) / p.cell_mm, fz = ((z - j * p.cell_mm) * kOne) / p.cell_mm;
  int64_t rows[4];
  for (int r = 0; r < 4; ++r) {
    int32_t jj = j - 1 + r;
    rows[r] = catmull(plan_h(i - 1, jj), plan_h(i, jj), plan_h(i + 1, jj), plan_h(i + 2, jj), fx);
  }
  return catmull(rows[0], rows[1], rows[2], rows[3], fz);
}

int32_t WorldGen::Impl::biome_amp_at(int64_t x, int64_t z, int64_t* rocky_q16) const {
  int32_t i = static_cast<int32_t>(floor_div(x, p.cell_mm)), j = static_cast<int32_t>(floor_div(z, p.cell_mm));
  int64_t fx = ((x - i * p.cell_mm) * kOne) / p.cell_mm, fz = ((z - j * p.cell_mm) * kOne) / p.cell_mm;
  auto at = [&](int32_t a, int32_t b, const int32_t* table) {
    a = std::clamp(a, 0, p.n - 1);
    b = std::clamp(b, 0, p.n - 1);
    return int64_t{table[p.biome[p.idx(a, b)]]};
  };
  auto bil = [&](const int32_t* t) {
    return qlerp(qlerp(at(i, j, t), at(i + 1, j, t), fx), qlerp(at(i, j + 1, t), at(i + 1, j + 1, t), fx), fz);
  };
  *rocky_q16 = bil(kBiomeRocky);
  return static_cast<int32_t>(bil(kBiomeAmp));
}

void WorldGen::Impl::roads_near(int64_t x0, int64_t z0, int64_t x1, int64_t z1, std::vector<uint32_t>* out) const {
  road_index.query(x0 - kRoadInfluence, z0 - kRoadInfluence, x1 + kRoadInfluence, z1 + kRoadInfluence, out);
}

GridSample WorldGen::Impl::grid_sample(int64_t gx, int64_t gz, int lod, std::span<const uint32_t> road_ids) const {
  const int64_t v = voxel_mm(lod);
  GridSample s;
  int64_t h = plan_cubic(gx, gz);
  int64_t rocky = 0;
  int64_t amp = biome_amp_at(gx, gz, &rocky);
  const uint64_t dseed = fine_seed(seed, FineLayer::Detail);
  int64_t coarse = 0;
  for (int o = 0; o < kCoarseOctaves; ++o) {
    int64_t wl = kDetailWavelength >> o;
    if (wl < 4 * v) break;
    int64_t n = gradient_noise2(hash_combine(dseed, static_cast<uint64_t>(o)), to_noise(gx, wl), to_noise(gz, wl));
    int64_t crag = kOne - 2 * abs64(n);
    n += ((crag - n) * rocky) >> 16;
    coarse += ((amp >> o) * n) >> 16;
  }

  // Roads: detail removed on the carriageway, cross-slope levelled around it.
  int64_t rd = 0, flat = 0, road_h = 0;
  for (uint32_t id : road_ids) {
    const RoadSeg& r = roads[id];
    int64_t t;
    int64_t d2 = seg_dist2(r, gx, gz, &t);
    int64_t reach = r.half_width_mm + 4500;
    if (d2 >= reach * reach) continue;
    int64_t d = static_cast<int64_t>(isqrt64(static_cast<uint64_t>(d2)));
    int64_t f = kOne - qsmoothstep(r.half_width_mm + 500, reach, d);
    if (f > flat) {
      flat = f;
      rd = kOne - qsmoothstep(r.half_width_mm, r.half_width_mm + 1500, d);
      road_h = plan_cubic(r.ax + (((r.bx - r.ax) * t) >> 16), r.az + (((r.bz - r.az) * t) >> 16));
    }
  }

  // Settlement pads: levelled to the site height, never over open water.
  int64_t w = 0, pad_h = 0;
  uint32_t near_cell = cell_at(gx, gz);
  if ((p.flags[near_cell] & (kFlagSea | kFlagLake | kFlagRiver)) == 0) {
    for (const auto& pad : pads) {
      int64_t dx = gx - pad.x_mm, dz = gz - pad.z_mm;
      int64_t r = pad.radius_mm;
      if (abs64(dx) >= r || abs64(dz) >= r) continue;
      int64_t d = static_cast<int64_t>(isqrt64(static_cast<uint64_t>(dx * dx + dz * dz)));
      int64_t f = kOne - qsmoothstep(r * 6 / 10, r, d);
      if (f > w) {
        w = f;
        pad_h = pad.height_mm;
      }
    }
  }

  int64_t keep = ((kOne - rd) * (kOne - ((w * 85) / 100))) >> 16;
  h += (coarse * keep) >> 16;
  if (flat > 0) h = qlerp(h, road_h, flat);
  if (w > 0) h = qlerp(h, pad_h, w);
  s.h = h;
  s.fine_amp = static_cast<int32_t>((amp * (((kOne - rd) * (kOne - ((w * 9) / 10))) >> 16)) >> 16);
  s.road_q16 = static_cast<int32_t>(rd);

  // Material regions do not follow the 16 m cell edges: the lookup point wanders.
  const uint64_t jseed = fine_seed(seed, FineLayer::Jitter);
  int64_t jx = (fbm2(jseed, to_noise(gx, 48 * M), to_noise(gz, 48 * M), 2) * 10 * M) >> 16;
  int64_t jz = (fbm2(hash_combine(jseed, 1), to_noise(gx, 48 * M), to_noise(gz, 48 * M), 2) * 10 * M) >> 16;
  s.cell = cell_at(gx + jx, gz + jz);
  return s;
}

int64_t WorldGen::Impl::fine_detail(int64_t x, int64_t z, int32_t amp, int lod) const {
  const int64_t v = voxel_mm(lod);
  const uint64_t dseed = fine_seed(seed, FineLayer::Detail);
  int64_t sum = 0;
  for (int o = kCoarseOctaves; o < kCoarseOctaves + kFineOctaves; ++o) {
    int64_t wl = kDetailWavelength >> o;
    int64_t a = amp >> o;
    if (wl < 4 * v || a * 4 < v) break;
    sum += (a * gradient_noise2(hash_combine(dseed, static_cast<uint64_t>(o)), to_noise(x, wl), to_noise(z, wl))) >> 16;
  }
  return sum;
}

int64_t WorldGen::Impl::ground(int64_t x, int64_t z, int lod) const {
  const int64_t G = kGridStride * voxel_mm(lod);
  int64_t gx = floor_div(x, G) * G, gz = floor_div(z, G) * G;
  std::vector<uint32_t> ids;
  roads_near(gx, gz, gx + G, gz + G, &ids);
  GridSample s00 = grid_sample(gx, gz, lod, ids), s10 = grid_sample(gx + G, gz, lod, ids);
  GridSample s01 = grid_sample(gx, gz + G, lod, ids), s11 = grid_sample(gx + G, gz + G, lod, ids);
  int64_t fx = ((x - gx) * kOne) / G, fz = ((z - gz) * kOne) / G;
  int64_t h = qlerp(qlerp(s00.h, s10.h, fx), qlerp(s01.h, s11.h, fx), fz);
  int64_t a = qlerp(qlerp(s00.fine_amp, s10.fine_amp, fx), qlerp(s01.fine_amp, s11.fine_amp, fx), fz);
  return h + fine_detail(x, z, static_cast<int32_t>(a), lod);
}

void WorldGen::Impl::ground_bounds(int64_t x0, int64_t z0, int64_t x1, int64_t z1, int64_t* lo, int64_t* hi) const {
  int32_t i0 = static_cast<int32_t>(floor_div(x0, p.cell_mm)) - 1, i1 = static_cast<int32_t>(floor_div(x1, p.cell_mm)) + 2;
  int32_t j0 = static_cast<int32_t>(floor_div(z0, p.cell_mm)) - 1, j1 = static_cast<int32_t>(floor_div(z1, p.cell_mm)) + 2;
  int64_t mn = INT64_MAX, mx = INT64_MIN, amp = 0;
  for (int32_t j = j0; j <= j1; ++j)
    for (int32_t i = i0; i <= i1; ++i) {
      int64_t h = plan_h(i, j);
      mn = std::min(mn, h);
      mx = std::max(mx, h);
      int32_t ci = std::clamp(i, 0, p.n - 1), cj = std::clamp(j, 0, p.n - 1);
      amp = std::max<int64_t>(amp, kBiomeAmp[p.biome[p.idx(ci, cj)]]);
    }
  int64_t over = (mx - mn) / 6 + 2 * amp + M;
  *lo = mn - over;
  *hi = mx + over;
  for (const auto& pad : pads) {
    if (x1 < pad.x_mm - pad.radius_mm || x0 > pad.x_mm + pad.radius_mm || z1 < pad.z_mm - pad.radius_mm ||
        z0 > pad.z_mm + pad.radius_mm)
      continue;
    *lo = std::min<int64_t>(*lo, pad.height_mm - M);
    *hi = std::max<int64_t>(*hi, pad.height_mm + M);
  }
}

}  // namespace em::wg
