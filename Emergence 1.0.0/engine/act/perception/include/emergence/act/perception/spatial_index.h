// SpatialIndex: hash grid of the entities of the EntityStore (cells of 8 m by default), rebuilt at each tick from the
// store. Candidates for an observer = the cells around it, never the whole world (a cost in O(n^2) is the trap of T23).
// Order: cells are visited row by row, the entities of a cell by increasing EntityId, so the candidates always come in
// the same order, whatever the threads or the addresses.
#pragma once
#include <cstdint>
#include <vector>

#include "emergence/act/entity_store.h"

namespace em::act::perception {

class SpatialIndex {
 public:
  struct Entry {
    EntityId id = 0;
    Position pos{};
    gen::EntityKind kind = gen::EntityKind::kCount;
    std::uint16_t sort = 0;
  };

  explicit SpatialIndex(std::int32_t cell_mm = 8000) : cell_(cell_mm) {}

  // Indexes every entity that lies on the ground or in a place (holder == 0) and whose kind can be perceived.
  void build(const EntityStore& store);
  std::size_t size() const { return entries_.size(); }

  // f(const Entry&) for every entry whose cell touches the square of half-side radius_mm around `centre`
  // (the caller does the exact distance test).
  template <class F>
  void query(const Position& centre, std::int64_t radius_mm, F&& f) const {
    const std::int32_t x0 = cell_of(std::int32_t(centre[0] - radius_mm)), x1 = cell_of(std::int32_t(centre[0] + radius_mm));
    const std::int32_t y0 = cell_of(std::int32_t(centre[1] - radius_mm)), y1 = cell_of(std::int32_t(centre[1] + radius_mm));
    for (std::int32_t cy = y0; cy <= y1; ++cy)
      for (std::int32_t cx = x0; cx <= x1; ++cx) {
        const Span s = lookup(key(cx, cy));
        for (std::uint32_t i = s.begin; i < s.end; ++i) f(entries_[i]);
      }
  }

 private:
  struct Span { std::uint32_t begin = 0, end = 0; };
  struct Slot { std::uint64_t key = 0; Span span; bool used = false; };
  std::int32_t cell_of(std::int32_t mm) const { return mm >= 0 ? mm / cell_ : -((-mm + cell_ - 1) / cell_); }
  static std::uint64_t key(std::int32_t cx, std::int32_t cy) { return (std::uint64_t(std::uint32_t(cx)) << 32) | std::uint32_t(cy); }
  Span lookup(std::uint64_t k) const;

  std::int32_t cell_;
  std::vector<Entry> entries_;   // sorted by (cell key, id)
  std::vector<Slot> table_;      // open addressing, power-of-two size
  std::uint64_t mask_ = 0;
};

}  // namespace em::act::perception
