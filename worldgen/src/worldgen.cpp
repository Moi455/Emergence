#include "emergence/worldgen/worldgen.h"

#include <algorithm>
#include <cstring>

#include "emergence/base/fingerprint.h"
#include "internal.h"

namespace em::wg {

namespace {

// Chaikin corner cutting, twice: smooth road centre lines from plan cells.
std::vector<std::array<int64_t, 2>> smooth(std::vector<std::array<int64_t, 2>> pts) {
  for (int it = 0; it < 2 && pts.size() > 2; ++it) {
    std::vector<std::array<int64_t, 2>> o;
    o.reserve(pts.size() * 2);
    o.push_back(pts.front());
    for (size_t i = 0; i + 1 < pts.size(); ++i) {
      const auto &a = pts[i], &b = pts[i + 1];
      o.push_back({(3 * a[0] + b[0]) / 4, (3 * a[1] + b[1]) / 4});
      o.push_back({(a[0] + 3 * b[0]) / 4, (a[1] + 3 * b[1]) / 4});
    }
    o.push_back(pts.back());
    pts.swap(o);
  }
  return pts;
}

}  // namespace

WorldGen::Impl::Impl(const WorldPlan& plan, const MaterialTable& t) : p(plan) {
  map_mm = int64_t{p.n} * p.cell_mm;
  seed = p.params.seed;
  auto req = [&](const char* n) { return make_voxel(t.require(n)); };
  m.turf = req("turf");
  m.dirt = req("dirt");
  m.clay = req("clay");
  m.sand = req("sand");
  m.gravel = req("gravel");
  m.forest_floor = req("forest_floor");
  m.snow = req("snow");
  m.limestone = req("limestone");
  m.sandstone = req("sandstone");
  m.granite = req("granite");
  m.slate = req("slate");
  m.basalt = req("basalt");
  m.salt = req("salt");
  m.iron_ore = req("iron_ore");
  m.wood = req("oak_raw");
  m.bark = req("bark");
  if (const Material* l = t.find("leaves")) {
    m.leaves = make_voxel(l->id);
  } else {
    m.leaves = m.turf;
    m.leaves_is_fallback = true;
  }
  for (int r = 0; r < static_cast<int>(RockType::kCount); ++r)
    m.rock[static_cast<size_t>(r)] = req(rock_material_name(static_cast<RockType>(r)));

  for (int s = 0; s < 4; ++s)
    if (p.params.frontier[static_cast<size_t>(s)] == FrontierKind::Forest) forest_side = s;

  for (const Settlement& s : p.settlements) {
    SettlementPad pad;
    pad.kind = s.kind;
    pad.x_mm = s.i * p.cell_mm;
    pad.z_mm = s.j * p.cell_mm;
    pad.height_mm = s.height_mm;
    pad.radius_mm = s.kind == SettlementKind::Town ? 180 * M : 120 * M;
    pads.push_back(pad);
  }

  std::vector<std::array<int64_t, 4>> boxes;
  for (const Road& r : p.roads) {
    std::vector<std::array<int64_t, 2>> pts;
    for (uint32_t c : r.cells)
      pts.push_back({int64_t{static_cast<int32_t>(c % static_cast<uint32_t>(p.n))} * p.cell_mm,
                     int64_t{static_cast<int32_t>(c / static_cast<uint32_t>(p.n))} * p.cell_mm});
    pts = smooth(std::move(pts));
    int32_t hw = (r.from == 0 || r.to == 0) ? 2500 : 1750;  // roads to the market town are wider
    for (size_t i = 0; i + 1 < pts.size(); ++i) {
      RoadSeg s{pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1], hw};
      roads.push_back(s);
      boxes.push_back({std::min(s.ax, s.bx) - hw, std::min(s.az, s.bz) - hw, std::max(s.ax, s.bx) + hw,
                       std::max(s.az, s.bz) + hw});
    }
  }
  road_index.build(map_mm, 64 * M, boxes);
  build_caves();
}

WorldGen::WorldGen(const WorldPlan& plan, const MaterialTable& materials)
    : plan_(plan), impl_(std::make_unique<Impl>(plan, materials)) {}
WorldGen::~WorldGen() = default;

ChunkInfo WorldGen::classify(const ChunkKey& key) const {
  const Impl& g = *impl_;
  const int64_t S = chunk_mm(key.lod);
  const int64_t ox = int64_t{key.x} * S, oy = int64_t{key.y} * S, oz = int64_t{key.z} * S;
  if (oy + S <= kWorldBottomMm || key.x < 0 || key.z < 0 || ox >= g.map_mm || oz >= g.map_mm)
    return {ChunkKind::OutOfWorld, kAir};
  if (oy >= kWorldTopMm) return {ChunkKind::Air, kAir};
  int64_t lo, hi;
  g.ground_bounds(ox, oz, ox + S, oz + S, &lo, &hi);
  constexpr int64_t kBoulderTop = 3500;
  if (oy >= hi + kBoulderTop) {
    if (oy >= hi + g.max_tree_height(ox, oz, ox + S, oz + S)) return {ChunkKind::Air, kAir};
    std::vector<TreeInstance> trees;
    g.trees_in(ox, oz, ox + S, oz + S, -1, &trees);
    for (const auto& t : trees) {
      int64_t e = (int64_t{t.crown_radius_mm} * 13) / 10;
      if (t.x_mm + e <= ox || t.x_mm - e >= ox + S || t.z_mm + e <= oz || t.z_mm - e >= oz + S) continue;
      if (t.y_mm + (int64_t{t.height_mm} * 11) / 10 <= oy) continue;
      return {ChunkKind::Mixed, kAir};
    }
    return {ChunkKind::Air, kAir};
  }
  if (oy + S <= lo && !g.caves_touch(ox, oy, oz, ox + S, oy + S, oz + S)) {
    uint32_t c = g.cell_at(ox + S / 2, oz + S / 2);
    return {ChunkKind::Solid, g.m.rock[g.p.rock[c]]};
  }
  return {ChunkKind::Mixed, kAir};
}

ChunkInfo WorldGen::generate(const ChunkKey& key, VoxelId* out) const {
  ChunkInfo info = classify(key);
  if (info.kind == ChunkKind::OutOfWorld || info.kind == ChunkKind::Air) {
    std::memset(out, 0, sizeof(VoxelId) * kChunkVoxels);
    return info;
  }
  return generate_unclassified(key, out);
}

ChunkInfo WorldGen::generate_unclassified(const ChunkKey& key, VoxelId* out) const {
  const int64_t S0 = chunk_mm(key.lod);
  if (int64_t{key.y} * S0 + S0 <= kWorldBottomMm || key.x < 0 || key.z < 0 || int64_t{key.x} * S0 >= impl_->map_mm ||
      int64_t{key.z} * S0 >= impl_->map_mm) {
    std::memset(out, 0, sizeof(VoxelId) * kChunkVoxels);
    return {ChunkKind::OutOfWorld, kAir};
  }
  const Impl& g = *impl_;
  ChunkBox b;
  b.lod = key.lod;
  b.v = voxel_mm(key.lod);
  b.size = chunk_mm(key.lod);
  b.ox = int64_t{key.x} * b.size;
  b.oy = int64_t{key.y} * b.size;
  b.oz = int64_t{key.z} * b.size;
  g.fill_columns(b, out);
  g.overlay_geology(b, out);
  g.carve_caves(b, out);
  g.place_boulders(b, out);
  g.plant_trees(b, out);
  // Kind from the content, four voxels at a time.
  bool any_air = false, any_solid = false;
  for (int i = 0; i < kChunkVoxels && !(any_air && any_solid); i += 4) {
    uint64_t w;
    std::memcpy(&w, out + i, sizeof w);
    any_solid |= w != 0;
    any_air |= ((w - 0x0001000100010001ULL) & ~w & 0x8000800080008000ULL) != 0;
  }
  if (!any_solid) return {ChunkKind::Air, kAir};
  if (!any_air) return {ChunkKind::Solid, out[kChunkVoxels / 2]};
  return {ChunkKind::Mixed, kAir};
}

ChunkInfo WorldGen::generate(const ChunkCoord& coord, Chunk& out) const {
  thread_local std::vector<VoxelId> dense(kChunkVoxels);
  ChunkInfo info = generate({coord.x, coord.y, coord.z, 0}, dense.data());
  out.coord = coord;
  if (info.kind != ChunkKind::Mixed) {
    out.clear(info.kind == ChunkKind::Solid ? dense[0] : kAir);
    if (info.kind == ChunkKind::Air || info.kind == ChunkKind::OutOfWorld) return info;
  }
  VoxelId brick[kVoxelsPerBrick];
  for (int by = 0; by < kBricksPerChunk; ++by)
    for (int bz = 0; bz < kBricksPerChunk; ++bz)
      for (int bx = 0; bx < kBricksPerChunk; ++bx) {
        for (int y = 0; y < kBrickSize; ++y)
          for (int z = 0; z < kBrickSize; ++z)
            for (int x = 0; x < kBrickSize; ++x)
              brick[in_brick_index(x, y, z)] = dense[voxel_index(bx * kBrickSize + x, by * kBrickSize + y, bz * kBrickSize + z)];
        out.set_brick(brick_index(bx, by, bz), brick);
      }
  out.compact();
  return info;
}

int32_t WorldGen::ground_mm(int64_t x_mm, int64_t z_mm, int lod) const {
  return static_cast<int32_t>(impl_->ground(x_mm, z_mm, lod));
}

int32_t WorldGen::water_mm(int64_t x_mm, int64_t z_mm) const { return plan_.water_mm[impl_->cell_at(x_mm, z_mm)]; }

void WorldGen::trees_in(int64_t x0, int64_t z0, int64_t x1, int64_t z1, std::vector<TreeInstance>* out) const {
  impl_->trees_in(x0, z0, x1, z1, 0, out);
}

const std::vector<CaveSegment>& WorldGen::cave_segments() const { return impl_->caves; }
CaveStats WorldGen::cave_stats() const { return impl_->cave_stats; }
const std::vector<SettlementPad>& WorldGen::settlement_pads() const { return impl_->pads; }

uint64_t WorldGen::chunk_fingerprint(const VoxelId* voxels) {
  Fingerprint f;
  f.add_u32(kChunkGenVersion);
  f.add(std::span<const uint16_t>(voxels, static_cast<size_t>(kChunkVoxels)));
  return f.value();
}

}  // namespace em::wg
