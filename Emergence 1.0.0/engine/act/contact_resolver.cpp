#include "contact_resolver.h"

#include <algorithm>

namespace em::act {
namespace {

bool is_body_kind(gen::EntityKind k) {
  return k == gen::EntityKind::item || k == gen::EntityKind::structure || k == gen::EntityKind::plant;
}

constexpr int kCellShift = 10;   // 1024 mm cells
std::uint64_t cell_key(std::int32_t cx, std::int32_t cz) {
  return (static_cast<std::uint64_t>(static_cast<std::uint32_t>(cx + (1 << 24))) << 32) | static_cast<std::uint32_t>(cz + (1 << 24));
}

std::int64_t overlap(const Body& a, const Body& b, int axis) {   // int64: positions may be anywhere in int32
  std::int64_t ha_ = (axis == 0 ? a.ext.x : a.ext.z) / 2, hb = (axis == 0 ? b.ext.x : b.ext.z) / 2;
  std::int64_t ca = a.pos[axis == 0 ? 0 : 2], cb = b.pos[axis == 0 ? 0 : 2];
  return std::min(ca + ha_, cb + hb) - std::max(ca - ha_, cb - hb);
}

// A body larger than 64 cells on an axis is indexed in its first 64 cells only (a 65 m footprint at 1 m cells):
// beyond that the grid would not find it as a supporter. Sheets that big are terrain, not entities.
template <class F>
void for_cells(const Body& b, F&& f) {
  std::int32_t x0 = static_cast<std::int32_t>((std::int64_t{b.pos[0]} - b.ext.x / 2) >> kCellShift), x1 = static_cast<std::int32_t>((std::int64_t{b.pos[0]} + b.ext.x / 2) >> kCellShift);
  std::int32_t z0 = static_cast<std::int32_t>((std::int64_t{b.pos[2]} - b.ext.z / 2) >> kCellShift), z1 = static_cast<std::int32_t>((std::int64_t{b.pos[2]} + b.ext.z / 2) >> kCellShift);
  if (x1 - x0 > 63) x1 = x0 + 63;
  if (z1 - z0 > 63) z1 = z0 + 63;
  for (std::int32_t cx = x0; cx <= x1; ++cx)
    for (std::int32_t cz = z0; cz <= z1; ++cz) f(cell_key(cx, cz));
}

}  // namespace

std::int64_t ContactResolver::break_energy_mj(const Profile& p) {
  if (p.main_material() == kNoMatter) return 0;
  std::int64_t area_cm2 = static_cast<std::int64_t>(p.size.x) * p.size.z / 100;
  return std::max<std::int64_t>(1, matter::kMaterials[p.main_material()].toughness * area_cm2 * kBreakMjPerToughnessCm2);
}

std::int64_t ContactResolver::capacity_g(const Profile& p) {
  if (p.main_material() == kNoMatter) return 0;
  std::int64_t area_cm2 = static_cast<std::int64_t>(p.size.x) * p.size.z / 100;
  return matter::kMaterials[p.main_material()].toughness * area_cm2 * kCapacityGPerToughnessCm2;
}

Affordances ContactResolver::affordances(const Profile& p, std::int32_t target_hardness) const {
  Affordances a;
  a.cuts = (p.flags & matter::kFormEdge) && p.edge_hardness > 0;
  a.impacts = p.mass_g >= kMinImpactMassG && p.max_hardness >= 10;
  // digs: a pointed or edged head on a handle, harder than what it digs (properties.toml rule).
  a.digs = ((p.flags & matter::kFormPoint) || (p.flags & matter::kFormEdge)) && (p.flags & matter::kFormHandle) &&
           p.mass_g >= kMinDiggerMassG &&
           std::max(p.edge_hardness, p.point_hardness) > target_hardness;
  a.binds = (p.flags & matter::kFormBinds) && p.binds_toughness > 0;
  a.sharpens = (p.flags & matter::kFormAbrasiveness) && p.abrasive_hardness > 0;
  a.graspable = p.mass_g <= kMaxGraspMassG && std::max({p.size.x, p.size.y, p.size.z}) <= kMaxGraspSizeMm;
  return a;
}

Body ContactResolver::body(EntityId id) const {
  Body b;
  gen::EntityKind k = store_.kind(id);
  if (!is_body_kind(k)) return b;
  const Profile* p = catalog_.profile(k, store_.sort(id));
  if (!p) return b;
  b.id = id; b.kind = k; b.sort = store_.sort(id); b.pos = store_.position_mm(id); b.ext = p->size; b.profile = p;
  return b;
}

Facet ContactResolver::facet(EntityId id) const {
  Facet f;
  if (id == kNoEntity || !store_.alive(id)) return f;
  f.id = id;
  f.kind = store_.kind(id);
  f.sort = store_.sort(id);
  f.pos = store_.position_mm(id);
  f.profile = catalog_.profile(f.kind, f.sort);
  if (!f.profile) return f;
  const Profile& p = *f.profile;
  f.mass_g = p.mass_g;
  f.material = p.main_material();
  if (f.material != kNoMatter) {
    const auto& m = matter::kMaterials[f.material];
    f.hardness = m.hardness; f.toughness = m.toughness; f.cohesion = m.cohesion;
  }
  f.break_mj = break_energy_mj(p);
  return f;
}

Resolved ContactResolver::resolve(const Contact& c) const {
  Resolved r;
  r.tool = facet(c.tool);
  r.target = facet(c.target);
  r.other = facet(c.other);
  std::int32_t th = r.target.valid() ? r.target.hardness
                                     : (c.voxel_material < matter::kMaterials.size() ? matter::kMaterials[c.voxel_material].hardness : 0);
  if (r.tool.valid()) {
    r.tool.aff = affordances(*r.tool.profile, th);
    r.energy_mj = kinetic_energy_mj(r.tool.mass_g, c.speed_mm_s);
  }
  if (r.target.valid()) r.target.aff = affordances(*r.target.profile, 0);
  if (r.other.valid()) r.other.aff = affordances(*r.other.profile, 0);
  return r;
}

std::int32_t SupportMap::index_of(EntityId id) const {
  auto it = std::lower_bound(bodies.begin(), bodies.end(), id, [](const Body& b, EntityId v) { return b.id < v; });
  return it != bodies.end() && it->id == id ? static_cast<std::int32_t>(it - bodies.begin()) : -1;
}

SupportMap ContactResolver::support_map() const {
  SupportMap m;
  store_.for_each([&](EntityId id, gen::EntityKind k) {
    if (!is_body_kind(k) || store_.holder(id) != kNoEntity) return;
    Body b = body(id);
    if (b.profile) m.bodies.push_back(b);
  });
  // Ids are not ascending in slot order (generations): sort by id so that every later order is canonical.
  std::sort(m.bodies.begin(), m.bodies.end(), [](const Body& a, const Body& b) { return a.id < b.id; });
  const std::size_t n = m.bodies.size();
  m.below.assign(n, {});
  m.on_ground.assign(n, 0);
  m.load_above_g.assign(n, 0);
  m.margin_permille.assign(n, 1000);

  // Uniform grid over the footprints (sorted vector of (cell, body), no hash order).
  auto& grid = m.grid;
  for (std::uint32_t i = 0; i < n; ++i) for_cells(m.bodies[i], [&](std::uint64_t key) { grid.emplace_back(key, i); });
  std::sort(grid.begin(), grid.end());

  std::vector<std::uint32_t> cand;
  for (std::uint32_t i = 0; i < n; ++i) {
    const Body& a = m.bodies[i];
    if (a.kind == gen::EntityKind::plant || std::int64_t{a.pos[1]} <= std::int64_t{ground_at(a)} + kSupportToleranceMm) m.on_ground[i] = 1;
    cand.clear();
    for_cells(a, [&](std::uint64_t key) {
      auto it = std::lower_bound(grid.begin(), grid.end(), std::make_pair(key, std::uint32_t{0}));
      for (; it != grid.end() && it->first == key; ++it) cand.push_back(it->second);
    });
    std::sort(cand.begin(), cand.end());
    cand.erase(std::unique(cand.begin(), cand.end()), cand.end());
    for (std::uint32_t j : cand) {
      if (j == i) continue;
      const Body& b = m.bodies[j];
      if (b.kind == gen::EntityKind::plant) continue;   // a plant carries nothing
      if (b.pos[1] >= a.pos[1]) continue;               // only what starts lower can carry
      std::int64_t gap = std::int64_t{a.pos[1]} - b.top();
      if (gap > kSupportToleranceMm || gap < -kSupportToleranceMm) continue;
      std::int64_t ox = overlap(a, b, 0), oz = overlap(a, b, 2);
      if (ox > 0 && oz > 0) m.below[i].push_back(j);
    }
  }

  // Loads: from the highest base down; a body passes its mass and what it carries to its supporters (equal shares,
  // the remainder to the first supporters by id).
  std::vector<std::uint32_t> order(n);
  for (std::uint32_t i = 0; i < n; ++i) order[i] = i;
  std::sort(order.begin(), order.end(), [&](std::uint32_t a, std::uint32_t b) {
    if (m.bodies[a].pos[1] != m.bodies[b].pos[1]) return m.bodies[a].pos[1] > m.bodies[b].pos[1];
    return m.bodies[a].id < m.bodies[b].id;
  });
  for (std::uint32_t i : order) {
    const auto& sup = m.below[i];
    if (sup.empty()) continue;
    std::int64_t total = m.bodies[i].profile->mass_g + m.load_above_g[i];
    std::int64_t share = total / static_cast<std::int64_t>(sup.size());
    std::int64_t rest = total % static_cast<std::int64_t>(sup.size());
    for (std::size_t s = 0; s < sup.size(); ++s) m.load_above_g[sup[s]] += share + (static_cast<std::int64_t>(s) < rest ? 1 : 0);
  }
  for (std::uint32_t i = 0; i < n; ++i) {
    std::int64_t cap = capacity_g(*m.bodies[i].profile);
    if (cap <= 0) { m.margin_permille[i] = m.load_above_g[i] > 0 ? 0 : 1000; continue; }
    std::int64_t mg = (cap - m.load_above_g[i]) * 1000 / cap;
    m.margin_permille[i] = static_cast<std::int32_t>(std::clamp<std::int64_t>(mg, -1000, 1000));
  }
  return m;
}

std::vector<TouchPair> ContactResolver::touching() const {
  SupportMap m = support_map();
  std::vector<TouchPair> out;
  for (std::size_t i = 0; i < m.bodies.size(); ++i)
    for (std::uint32_t j : m.below[i]) out.push_back({m.bodies[i].id, m.bodies[j].id});
  std::sort(out.begin(), out.end(), [](const TouchPair& a, const TouchPair& b) {
    return a.upper != b.upper ? a.upper < b.upper : a.lower < b.lower;
  });
  return out;
}

}  // namespace em::act

namespace em::act {
std::int32_t ContactResolver::landing_mm(const SupportMap& m, std::size_t i) const {
  const Body& a = m.bodies[i];
  std::int32_t land = ground_at(a);
  std::vector<std::uint32_t> cand;
  for_cells(a, [&](std::uint64_t key) {
    auto it = std::lower_bound(m.grid.begin(), m.grid.end(), std::make_pair(key, std::uint32_t{0}));
    for (; it != m.grid.end() && it->first == key; ++it) cand.push_back(it->second);
  });
  std::sort(cand.begin(), cand.end());
  cand.erase(std::unique(cand.begin(), cand.end()), cand.end());
  for (std::uint32_t j : cand) {
    if (j == i) continue;
    const Body& b = m.bodies[j];
    if (b.kind == gen::EntityKind::plant || b.top() > std::int64_t{a.pos[1]} + kSupportToleranceMm) continue;
    std::int64_t ox = overlap(a, b, 0), oz = overlap(a, b, 2);
    if (ox > 0 && oz > 0) land = std::max(land, b.top());
  }
  return land;
}
}  // namespace em::act
