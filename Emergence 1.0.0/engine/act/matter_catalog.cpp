#include "matter_catalog.h"

#include <algorithm>

namespace em::act {

std::int32_t icbrt(std::uint64_t v) {
  std::uint64_t lo = 0, hi = 2642245;   // 2642245^3 > 2^64
  while (lo < hi) {
    std::uint64_t mid = (lo + hi + 1) / 2;
    if (mid * mid * mid <= v) lo = mid; else hi = mid - 1;
  }
  return static_cast<std::int32_t>(lo);
}

MatterCatalog::MatterCatalog() {
  items_.resize(matter::kItems.size());
  for (std::size_t i = 0; i < matter::kItems.size(); ++i) {
    const auto& row = matter::kItems[i];
    if (!row.live || row.sort == 0) continue;   // an id that is not a kind has no sort: no entity can be of it
    Profile p;
    p.sort = row.sort;
    p.mass_g = row.mass_g;
    for (std::uint16_t k = 0; k < row.parts_n; ++k) {
      const auto& pr = matter::kItemParts[row.parts_at + k];
      p.parts.push_back({pr.form, pr.material});
    }
    for (std::uint16_t k = 0; k < row.made_by_n; ++k) p.made_by.push_back(matter::kItemMadeBy[row.made_by_at + k]);
    finish(p);
    items_[i] = std::move(p);
    if (by_sort_.size() <= row.sort) by_sort_.resize(row.sort + 1u, 0);
    by_sort_[row.sort] = static_cast<std::uint32_t>(i + 1);
  }
}

void MatterCatalog::finish(Profile& p) const {
  // Hostile or stale sheets: an unknown form is dropped, an unknown material becomes 'no material'; sizes and mass are bounded.
  std::erase_if(p.parts, [](const Part& q) { return q.form >= matter::kForms.size(); });
  for (Part& q : p.parts) if (q.material >= matter::kMaterials.size()) q.material = kNoMatter;
  p.mass_g = std::clamp(p.mass_g, 0, kMaxMassG);
  p.size.x = std::clamp(p.size.x, 0, kMaxSizeMm); p.size.y = std::clamp(p.size.y, 0, kMaxSizeMm); p.size.z = std::clamp(p.size.z, 0, kMaxSizeMm);
  p.flags = 0;
  p.edge_hardness = p.point_hardness = p.abrasive_hardness = p.binds_toughness = p.max_hardness = 0;
  for (const Part& part : p.parts) {
    std::uint8_t bits = part.form < matter::kForms.size() ? matter::kForms[part.form].flags : 0;
    p.flags |= bits;
    if (part.material == kNoMatter) continue;
    const auto& m = matter::kMaterials[part.material];
    p.max_hardness = std::max<std::int16_t>(p.max_hardness, m.hardness);
    if (bits & matter::kFormEdge) p.edge_hardness = std::max<std::int16_t>(p.edge_hardness, m.hardness);
    if (bits & matter::kFormPoint) p.point_hardness = std::max<std::int16_t>(p.point_hardness, m.hardness);
    if (bits & matter::kFormAbrasiveness) p.abrasive_hardness = std::max<std::int16_t>(p.abrasive_hardness, m.hardness);
    if (bits & matter::kFormBinds) p.binds_toughness = std::max<std::int16_t>(p.binds_toughness, m.toughness);
  }
  // A cube of the volume (mass / density of the main material) where the sheet gives no size.
  if (p.size.x <= 0 || p.size.y <= 0 || p.size.z <= 0) {
    std::int32_t dens = p.main_material() == kNoMatter ? 1000 : std::max(1, matter::kMaterials[p.main_material()].density_kg_m3);
    std::uint64_t mm3 = static_cast<std::uint64_t>(std::max(p.mass_g, 1)) * 1000000ull / static_cast<std::uint64_t>(dens);
    std::int32_t side = std::max(1, icbrt(mm3));
    if (p.size.x <= 0) p.size.x = side;
    if (p.size.y <= 0) p.size.y = side;
    if (p.size.z <= 0) p.size.z = side;
  }
}

const Profile* MatterCatalog::profile(gen::EntityKind kind, std::uint16_t sort) const {
  auto k = static_cast<std::size_t>(kind);
  if (k >= custom_.size()) return nullptr;
  if (sort < custom_set_[k].size() && custom_set_[k][sort]) return &custom_[k][sort];
  if (kind == gen::EntityKind::item && sort < by_sort_.size() && by_sort_[sort] != 0) return &items_[by_sort_[sort] - 1u];
  return nullptr;
}

void MatterCatalog::set_profile(gen::EntityKind kind, std::uint16_t sort, Profile p) {
  auto k = static_cast<std::size_t>(kind);
  finish(p);
  if (custom_[k].size() <= sort) { custom_[k].resize(sort + 1u); custom_set_[k].resize(sort + 1u, false); }
  custom_[k][sort] = std::move(p);
  custom_set_[k][sort] = true;
}

std::uint16_t MatterCatalog::find_material(std::string_view name) const {
  for (std::size_t i = 0; i < matter::kMaterials.size(); ++i)
    if (matter::kMaterials[i].live && matter::kMaterials[i].name == name) return static_cast<std::uint16_t>(i);
  return kNoMatter;
}

std::uint16_t MatterCatalog::find_item(std::string_view name) const {
  for (std::size_t i = 0; i < matter::kItems.size(); ++i)
    if (matter::kItems[i].live && matter::kItems[i].sort != 0 && matter::kItems[i].name == name) return matter::kItems[i].sort;
  return 0;
}

std::string_view MatterCatalog::item_name(std::uint16_t sort) const {
  for (const auto& row : matter::kItems) if (row.live && row.sort == sort && sort != 0) return row.name;
  return {};
}

std::uint16_t MatterCatalog::element_item(const Part& p, bool allow_material_only) const {
  // An element is a made product (some process makes it: a plank, a brick), not a utensil that happens to be one part.
  for (int pass = 0; pass < 2; ++pass) {
    std::uint16_t by_material = 0;
    for (std::size_t i = 0; i < items_.size(); ++i) {
      const Profile& it = items_[i];
      if (it.parts.size() != 1 || it.parts[0].material != p.material) continue;
      if (pass == 0 && it.made_by.empty()) continue;
      if (it.parts[0].form == p.form) return matter::kItems[i].sort;
      if (allow_material_only && !by_material) by_material = matter::kItems[i].sort;
    }
    if (by_material) return by_material;
  }
  return 0;
}

std::uint16_t MatterCatalog::piece_item(std::uint16_t material, ProcessId by, std::int32_t below_g) const {
  std::uint16_t best = 0;
  std::int32_t best_mass = -1;
  for (std::size_t i = 0; i < items_.size(); ++i) {
    const Profile& it = items_[i];
    if (it.parts.size() != 1 || it.parts[0].material != material || it.mass_g >= below_g) continue;
    if (std::find(it.made_by.begin(), it.made_by.end(), static_cast<std::uint16_t>(by)) == it.made_by.end()) continue;
    if (it.mass_g > best_mass) { best_mass = it.mass_g; best = matter::kItems[i].sort; }
  }
  return best;
}

std::uint16_t MatterCatalog::item_of_material(std::uint16_t material) const {
  // A made product (some process makes it) before a utensil; one part only before a composite item.
  for (int pass = 0; pass < 4; ++pass) {
    bool single = pass < 2, made = pass % 2 == 0;
    for (std::size_t i = 0; i < items_.size(); ++i) {
      const Profile& it = items_[i];
      if (it.parts.empty() || it.parts[0].material != material) continue;
      if (single && it.parts.size() != 1) continue;
      if (made && it.made_by.empty()) continue;
      return matter::kItems[i].sort;
    }
  }
  return 0;
}

}  // namespace em::act
