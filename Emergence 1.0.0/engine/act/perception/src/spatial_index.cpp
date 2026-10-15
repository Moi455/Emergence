#include "emergence/act/perception/spatial_index.h"

#include <algorithm>

namespace em::act::perception {

namespace {
std::uint64_t slot_hash(std::uint64_t k) {
  k ^= k >> 33; k *= 0xff51afd7ed558ccdull; k ^= k >> 33;
  return k;
}
bool perceivable(gen::EntityKind k) {
  switch (k) {
    case gen::EntityKind::agent: case gen::EntityKind::animal: case gen::EntityKind::plant: case gen::EntityKind::item:
    case gen::EntityKind::structure: case gen::EntityKind::water_body: case gen::EntityKind::fire:
    case gen::EntityKind::phenomenon: case gen::EntityKind::trace:
      return true;
    default:
      return false;   // terrain, place, world, fact, group, role, agreement: not "things seen"
  }
}
}  // namespace

void SpatialIndex::build(const EntityStore& store) {
  entries_.clear();
  store.for_each([&](EntityId id, gen::EntityKind k) {
    if (!perceivable(k) || store.holder(id) != kNoEntity) return;
    entries_.push_back({id, store.position_mm(id), k, store.sort(id)});
  });
  std::sort(entries_.begin(), entries_.end(), [&](const Entry& a, const Entry& b) {
    const std::uint64_t ka = key(cell_of(a.pos[0]), cell_of(a.pos[1])), kb = key(cell_of(b.pos[0]), cell_of(b.pos[1]));
    return ka != kb ? ka < kb : a.id < b.id;
  });
  std::size_t cap = 16;
  while (cap < entries_.size() * 2 + 2) cap <<= 1;
  table_.assign(cap, Slot{});
  mask_ = cap - 1;
  for (std::uint32_t i = 0; i < entries_.size();) {
    const std::uint64_t k = key(cell_of(entries_[i].pos[0]), cell_of(entries_[i].pos[1]));
    std::uint32_t j = i;
    while (j < entries_.size() && key(cell_of(entries_[j].pos[0]), cell_of(entries_[j].pos[1])) == k) ++j;
    std::uint64_t h = slot_hash(k) & mask_;
    while (table_[h].used) h = (h + 1) & mask_;
    table_[h] = {k, {i, j}, true};
    i = j;
  }
}

SpatialIndex::Span SpatialIndex::lookup(std::uint64_t k) const {
  if (table_.empty()) return {};
  std::uint64_t h = slot_hash(k) & mask_;
  while (table_[h].used) {
    if (table_[h].key == k) return table_[h].span;
    h = (h + 1) & mask_;
  }
  return {};
}

}  // namespace em::act::perception
