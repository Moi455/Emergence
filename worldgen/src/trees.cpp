// Trees and boulders placed by hashing the seed (monde_horizon § 7): only
// cut or planted trees are ever saved. Four size tiers on lattices of 5, 10,
// 20 and 40 m: deep in the forest march trees grow giant (the size doubles
// about every 900 m of depth) and so does their spacing.
#include <algorithm>

#include "internal.h"

namespace em::wg {

const char* tree_species_name(TreeSpecies s) {
  static const char* names[] = {"oak", "birch", "pine", "willow"};
  return s < TreeSpecies::kCount ? names[static_cast<int>(s)] : "?";
}

namespace {

constexpr int kTiers = 4;
constexpr int64_t kTreeCell0 = 5 * M;
constexpr int64_t kMaxScaleQ16 = 10 * kOne;
constexpr int64_t kBaseMaxHeight = 30 * M;
constexpr int64_t kBoulderCell = 12 * M;
constexpr int64_t kBoulderReach = 2600;

int tier_of(int64_t s) { return s < 2 * kOne ? 0 : s < 4 * kOne ? 1 : s < 8 * kOne ? 2 : 3; }
// Largest crown radius a tree of tier k can have (canopy reach of the lattice).
int64_t tier_reach(int k) { return 7 * M * std::min<int64_t>(int64_t{2} << k, 10) + 2 * M; }

// Density in tree cells per 10 000, by Biome (lattice of 5 m).
constexpr int32_t kDensity[] = {0, 200, 1400, 400, 3800, 7000, 100, 0, 1800, 900, 0, 0, 0};

struct Dims {
  int64_t h_lo, h_hi, r_lo, r_hi, c_lo, c_hi;  // height, trunk radius, crown radius (mm)
};
constexpr Dims kDims[] = {
    {10 * M, 18 * M, 300, 500, 4 * M, 7 * M},       // oak
    {12 * M, 20 * M, 150, 250, 2500, 4 * M},        // birch
    {15 * M, 28 * M, 250, 400, 2500, 4 * M},        // pine
    {8 * M, 12 * M, 400, 600, 4 * M, 6 * M},        // willow
};

TreeSpecies species_for(Biome b, int tier, uint64_t h) {
  int64_t r = pick(h, 100);
  switch (b) {
    case Biome::DeepForest:
      if (tier > 0) return r < 60 ? TreeSpecies::Oak : TreeSpecies::Pine;
      return r < 45 ? TreeSpecies::Oak : r < 80 ? TreeSpecies::Pine : TreeSpecies::Birch;
    case Biome::Woodland: return r < 55 ? TreeSpecies::Oak : r < 90 ? TreeSpecies::Birch : TreeSpecies::Pine;
    case Biome::Marsh: return r < 70 ? TreeSpecies::Willow : TreeSpecies::Birch;
    case Biome::Foothills: return r < 75 ? TreeSpecies::Pine : TreeSpecies::Birch;
    case Biome::Alpine:
    case Biome::Beach: return TreeSpecies::Pine;
    default: return r < 70 ? TreeSpecies::Oak : TreeSpecies::Birch;
  }
}

}  // namespace

int64_t WorldGen::Impl::tree_scale_q16(int64_t x, int64_t z) const {
  if (forest_side < 0) return kOne;
  uint32_t c = cell_at(x, z);
  if (p.march_side[c] != static_cast<uint8_t>(forest_side) || p.march_depth_m[c] <= 0) return kOne;
  int64_t doubling = std::max<int64_t>((900 * M * p.params.scale_q16()) >> 16, 1);
  return std::min(qexp2((int64_t{p.march_depth_m[c]} * M * kOne) / doubling), kMaxScaleQ16);
}

int64_t WorldGen::Impl::max_tree_height(int64_t x0, int64_t z0, int64_t x1, int64_t z1) const {
  int64_t s = kOne;
  if (forest_side >= 0) {
    int64_t e = tier_reach(kTiers - 1);
    for (int a = 0; a < 3; ++a)
      for (int c = 0; c < 3; ++c) {
        int64_t x = x0 - e + ((x1 - x0 + 2 * e) * a) / 2, z = z0 - e + ((z1 - z0 + 2 * e) * c) / 2;
        if (x < 0 || z < 0 || x >= map_mm || z >= map_mm) continue;
        s = std::max(s, tree_scale_q16(x, z));
      }
    s = std::min((s * 5) / 4, kMaxScaleQ16);
  }
  return (kBaseMaxHeight * s) >> 16;
}

void WorldGen::Impl::trees_in(int64_t x0, int64_t z0, int64_t x1, int64_t z1, int64_t reach,
                              std::vector<TreeInstance>* out) const {
  const uint64_t ts = fine_seed(seed, FineLayer::Tree);
  const uint64_t gs = fine_seed(seed, FineLayer::Grove);
  std::vector<uint32_t> road_ids;
  for (int k = 0; k < kTiers; ++k) {
    if (k > 0 && forest_side < 0) break;
    const int64_t C = kTreeCell0 << k;
    const int64_t e = reach < 0 ? tier_reach(k) : reach;
    for (int64_t cj = floor_div(z0 - e, C); cj <= floor_div(z1 + e - 1, C); ++cj)
      for (int64_t ci = floor_div(x0 - e, C); ci <= floor_div(x1 + e - 1, C); ++ci) {
        uint64_t h = hash3(ts, k, ci, cj);
        int64_t x = ci * C + range(rehash(h, 1), C / 10, (C * 9) / 10);
        int64_t z = cj * C + range(rehash(h, 2), C / 10, (C * 9) / 10);
        if (x < x0 - e || x >= x1 + e || z < z0 - e || z >= z1 + e) continue;
        if (x < 0 || z < 0 || x >= map_mm || z >= map_mm) continue;
        uint32_t cell = cell_at(x, z);
        if (p.flags[cell] & (kFlagSea | kFlagLake | kFlagRiver | kFlagRoad | kFlagSettlement)) continue;
        Biome b = static_cast<Biome>(p.biome[cell]);
        int64_t density = kDensity[static_cast<int>(b)];
        if (density == 0) continue;
        if (b != Biome::DeepForest) {  // groves and clearings
          int64_t g = fbm2(gs, to_noise(x, 140 * M), to_noise(z, 140 * M), 2);
          density = (density * clamp64(kOne / 2 + (g * 3) / 2, kOne / 10, kOne * 16 / 10)) >> 16;
        }
        if (pick(rehash(h, 3), 10000) >= density) continue;
        int64_t s = tree_scale_q16(x, z);
        if (tier_of(s) != k) continue;
        bool blocked = false;
        for (const auto& pad : pads) {
          int64_t dx = x - pad.x_mm, dz = z - pad.z_mm, r = (pad.radius_mm * 9) / 10;
          if (dx * dx + dz * dz < r * r) blocked = true;
        }
        if (blocked) continue;
        road_index.query(x - 8 * M, z - 8 * M, x + 8 * M, z + 8 * M, &road_ids);
        for (uint32_t id : road_ids) {
          const RoadSeg& r = roads[id];
          int64_t dx = r.bx - r.ax, dz = r.bz - r.az, len2 = dx * dx + dz * dz;
          int64_t t = len2 > 0 ? clamp64(((x - r.ax) * dx + (z - r.az) * dz) / std::max<int64_t>(len2 >> 16, 1), 0, kOne) : 0;
          int64_t px = r.ax + ((dx * t) >> 16) - x, pz = r.az + ((dz * t) >> 16) - z;
          int64_t clear = r.half_width_mm + 2500;
          if (px * px + pz * pz < clear * clear) blocked = true;
        }
        if (blocked) continue;
        TreeInstance t;
        t.id = hash_combine(h, 0x7ee);
        t.tier = static_cast<uint8_t>(k);
        t.species = species_for(b, k, rehash(h, 4));
        const Dims& d = kDims[static_cast<int>(t.species)];
        t.x_mm = x;
        t.z_mm = z;
        t.height_mm = static_cast<int32_t>((range(rehash(h, 5), d.h_lo, d.h_hi) * s) >> 16);
        t.trunk_radius_mm = static_cast<int32_t>((range(rehash(h, 6), d.r_lo, d.r_hi) * s) >> 16);
        t.crown_radius_mm = static_cast<int32_t>((range(rehash(h, 7), d.c_lo, d.c_hi) * s) >> 16);
        t.y_mm = ground(x, z, 0);
        out->push_back(t);
      }
  }
}

void WorldGen::Impl::plant_trees(const ChunkBox& b, VoxelId* out) const {
  const int64_t x1 = b.ox + b.size, y1 = b.oy + b.size, z1 = b.oz + b.size;
  std::vector<TreeInstance> trees;
  trees_in(b.ox, b.oz, x1, z1, -1, &trees);
  if (trees.empty()) return;
  Lattice3 noise;
  const uint64_t leaf_seed = fine_seed(seed, FineLayer::Leaf);
  for (const TreeInstance& t : trees) {
    const int64_t H = t.height_mm, r0 = t.trunk_radius_mm, cr = t.crown_radius_mm;
    if (cr < b.v) continue;  // smaller than a voxel at this level of detail
    int64_t ext = (cr * 13) / 10;
    if (t.x_mm + ext <= b.ox || t.x_mm - ext >= x1 || t.z_mm + ext <= b.oz || t.z_mm - ext >= z1) continue;
    if (t.y_mm + (H * 11) / 10 <= b.oy || t.y_mm - 2 * M >= y1) continue;
    if (noise.empty() && b.v <= 160) noise.build(leaf_seed, 9, b.ox, b.oy, b.oz, x1, y1, z1);
    const Lattice3* nz = noise.empty() ? nullptr : &noise;

    const uint64_t h = t.id;
    // Generated content carries tint 0 (docs/interfaces.md § 2).
    RasterStyle wood;
    wood.voxel = m.bark;
    wood.replace = kRepAir | kRepSoil | kRepLeaves;
    RasterStyle core = wood;
    core.voxel = m.wood;
    core.replace = kRepAir | kRepSoil | kRepLeaves | kRepWood;
    RasterStyle leaves;
    leaves.voxel = m.leaves;
    leaves.replace = kRepAir;
    leaves.noise = nz;
    leaves.noise_q16 = kOne * 3 / 10;
    if (b.lod <= 2) {
      leaves.hole_seed = rehash(leaf_seed, h);
      leaves.hole_pct = 22;
    }

    // A slight lean, the same for the whole tree.
    int64_t lx = (unit_q16(rehash(h, 10)) * 6) / 100, lz = (unit_q16(rehash(h, 11)) * 6) / 100;
    auto at_height = [&](int64_t dy, int64_t* x, int64_t* z) {
      *x = t.x_mm + ((dy * lx) >> 16);
      *z = t.z_mm + ((dy * lz) >> 16);
    };
    const bool pine = t.species == TreeSpecies::Pine;
    const int64_t trunk_h = pine ? (H * 97) / 100 : (H * range(rehash(h, 12), 55, 70)) / 100;
    int64_t tx, tz;
    at_height(trunk_h, &tx, &tz);
    const Capsule trunk{t.x_mm, t.y_mm - 600 - r0, t.z_mm, tx, t.y_mm + trunk_h, tz, r0, pine ? r0 / 6 : (r0 * 45) / 100};
    raster_capsule(*this, b, trunk, wood, out);
    const int64_t bark = std::max<int64_t>(40, r0 / 8);  // wood shows inside once the bark is cut
    if (r0 - bark > b.v) {
      Capsule inner = trunk;
      inner.ra = r0 - bark;
      inner.rb = std::max<int64_t>(trunk.rb - bark, 0);
      raster_capsule(*this, b, inner, core, out);
    }
    raster_ellipsoid(*this, b, {t.x_mm, t.y_mm + r0 / 2, t.z_mm, (r0 * 19) / 10, (r0 * 12) / 10, (r0 * 19) / 10}, wood, out);

    if (pine) {
      // Stacked whorls: a cone whose radius saw-tooths with height.
      const int64_t base = t.y_mm + (H * 25) / 100, top = t.y_mm + H, span = top - base;
      const int64_t whorls = range(rehash(h, 13), 5, 8);
      int ylo = static_cast<int>(clamp64(floor_div(base - b.oy, b.v), 0, kChunkSize));
      int yhi = static_cast<int>(clamp64(floor_div(top - b.oy, b.v), -1, kChunkSize - 1));
      for (int y = ylo; y <= yhi; ++y) {
        int64_t yc = b.c(b.oy, y);
        int64_t u = ((yc - base) * kOne) / span;
        int64_t saw = (u * whorls) & 0xFFFF;
        int64_t R = (((cr * (kOne - u)) >> 16) * (kOne * 55 / 100 + ((saw * 45) / 100))) >> 16;
        if (R < b.v / 2) continue;
        int64_t cx, cz;
        at_height(yc - t.y_mm, &cx, &cz);
        const RasterStyle& st = leaves;
        // One voxel thick slice of the cone; the noise roughens its rim.
        for (int z = 0; z < kChunkSize; ++z) {
          int64_t zc = b.c(b.oz, z), dz = zc - cz;
          if (abs64(dz) > R + (R * 3) / 10) continue;
          VoxelId* row = out + voxel_index(0, y, z);
          for (int x = 0; x < kChunkSize; ++x) {
            int64_t xc = b.c(b.ox, x), dx = xc - cx;
            int64_t Rn = R;
            if (nz) Rn += (R * ((nz->at(xc, yc, zc) * st.noise_q16) >> 16)) >> 16;
            if (dx * dx + dz * dz >= Rn * Rn || row[x] != kAir) continue;
            if (st.hole_seed && static_cast<int32_t>(hash3(st.hole_seed, floor_div(xc, 4 * b.v), floor_div(yc + kYBias, 4 * b.v),
                                                          floor_div(zc, 4 * b.v)) % 100) < st.hole_pct)
              continue;
            row[x] = st.voxel;
          }
        }
      }
      continue;
    }

    // Broadleaf: boughs from the upper trunk, a leaf mass at each end and on top.
    const int boughs = static_cast<int>(range(rehash(h, 14), 4, 7));
    for (int i = 0; i < boughs; ++i) {
      uint64_t hb = rehash(h, 100 + static_cast<uint64_t>(i));
      int64_t sy = (H * range(rehash(hb, 1), 45, 70)) / 100;
      int64_t sx, sz;
      at_height(sy, &sx, &sz);
      int64_t dx = unit_q16(rehash(hb, 2)), dz = unit_q16(rehash(hb, 3));
      int64_t len = static_cast<int64_t>(isqrt64(static_cast<uint64_t>(dx * dx + dz * dz)));
      if (len == 0) dx = kOne, len = kOne;
      int64_t reach = (cr * range(rehash(hb, 4), 50, 80)) / 100;
      int64_t ex = sx + (dx * reach) / len, ez = sz + (dz * reach) / len;
      int64_t ey = t.y_mm + sy + (H * range(rehash(hb, 5), 8, 28)) / 100;
      raster_capsule(*this, b, {sx, t.y_mm + sy, sz, ex, ey, ez, (r0 * 45) / 100, std::max<int64_t>((r0 * 15) / 100, 30)}, wood, out);
      int64_t br = (cr * range(rehash(hb, 6), 45, 65)) / 100;
      int64_t by = t.species == TreeSpecies::Willow ? ey - H / 10 : ey;
      int64_t bry = t.species == TreeSpecies::Willow ? (br * 9) / 10 : (br * 7) / 10;
      raster_ellipsoid(*this, b, {ex, by, ez, br, bry, br}, leaves, out);
    }
    int64_t topx, topz;
    at_height(trunk_h, &topx, &topz);
    int64_t tr = (cr * 6) / 10;
    raster_ellipsoid(*this, b, {topx, t.y_mm + trunk_h + H / 10, topz, tr, (tr * 8) / 10, tr}, leaves, out);
  }
}

void WorldGen::Impl::place_boulders(const ChunkBox& b, VoxelId* out) const {
  const int64_t x1 = b.ox + b.size, y1 = b.oy + b.size, z1 = b.oz + b.size;
  const uint64_t s = fine_seed(seed, FineLayer::Boulder);
  static constexpr int32_t kPct[] = {0, 3, 2, 6, 8, 10, 8, 2, 30, 40, 45, 10, 0};
  Lattice3 noise;
  for (int64_t cj = floor_div(b.oz - kBoulderReach, kBoulderCell); cj <= floor_div(z1 + kBoulderReach, kBoulderCell); ++cj)
    for (int64_t ci = floor_div(b.ox - kBoulderReach, kBoulderCell); ci <= floor_div(x1 + kBoulderReach, kBoulderCell); ++ci) {
      uint64_t h = hash2(s, ci, cj);
      int64_t x = ci * kBoulderCell + pick(rehash(h, 1), kBoulderCell), z = cj * kBoulderCell + pick(rehash(h, 2), kBoulderCell);
      if (x < 0 || z < 0 || x >= map_mm || z >= map_mm) continue;
      uint32_t cell = cell_at(x, z);
      if (p.flags[cell] & (kFlagSea | kFlagLake | kFlagRiver | kFlagRoad | kFlagSettlement)) continue;
      if (pick(h, 100) >= kPct[p.biome[cell]]) continue;
      int64_t r = range(rehash(h, 3), 400, 1600);
      if (p.march_side[cell] == static_cast<uint8_t>(Side::North)) r = (r * 3) / 2;
      if (x + r < b.ox || x - r > x1 || z + r < b.oz || z - r > z1) continue;
      bool on_pad = false;
      for (const auto& pad : pads) {
        int64_t dx = x - pad.x_mm, dz = z - pad.z_mm;
        if (dx * dx + dz * dz < pad.radius_mm * pad.radius_mm) on_pad = true;
      }
      if (on_pad) continue;
      int64_t gy = ground(x, z, b.lod);
      int64_t cy = gy + (r * range(rehash(h, 4), 0, 35)) / 100;
      if (cy + r < b.oy || cy - r > y1) continue;
      if (noise.empty() && b.v <= 160) noise.build(s, 9, b.ox, b.oy, b.oz, x1, y1, z1);
      RasterStyle st;
      RockType rt = pick(rehash(h, 5), 100) < 20 ? RockType::Granite : static_cast<RockType>(p.rock[cell]);
      st.voxel = m.rock[static_cast<size_t>(rt)];
      st.replace = kRepAir | kRepSoil;
      st.noise = noise.empty() ? nullptr : &noise;
      st.noise_q16 = kOne / 4;
      raster_ellipsoid(*this, b, {x, cy, z, r, (r * range(rehash(h, 6), 55, 85)) / 100, (r * range(rehash(h, 7), 70, 100)) / 100}, st, out);
    }
}

}  // namespace em::wg
