// EntityStore (T15, docs/14 section 4.7): the non-voxel world (objects, plants, animals, structures, water, fire,
// places...), always simulated, loaded or not. Components are generated from the catalogue (gen::*, world_gen.h).
//
// The store is an Applier of the OperationBus (subscriber no. 1): Spawn, Destroy, Move and EntityDelta are the ONLY
// ways it changes; every public member below is a read. Determinism: ids are allocated in the bus order (free slots
// reused last-in first-out, generation raised on reuse), rows are swap-removed in the bus order, iteration and the
// serialisation go by slot number (a free slot is reused first-in first-out); no address, clock or hash-map order is ever read. Positions are millimetres.
// The position and the holder are NOT components: read_var() and EntityDelta never see them, only Move changes
// them (a holder must be alive and of a kind that has the spatial component; no limit on the depth of nesting).
#pragma once
#include <array>
#include <cstdint>
#include <deque>
#include <span>
#include <utility>
#include <vector>

#include "emergence/act/entity_id.h"
#include "emergence/act/entity_ops.h"
#include "emergence/act/world_gen.h"
#include "emergence/ops/applier.h"

namespace em::act {

using gen::ComponentId;
using gen::EntityKind;

// Dense rows of one kind; slot_of_row[i] is the slot number (0-based) of rows[i].
template <class Data>
struct KindTable {
  std::vector<Data> rows;
  std::vector<std::uint32_t> slot_of_row;
};

enum class LoadStatus : std::uint8_t {
  Ok, Truncated, BadMagic, BadVersion, SchemaMismatch, Corrupt,
};
const char* to_string(LoadStatus s);

struct StoreStats {
  std::uint64_t spawned = 0, destroyed = 0, moved = 0, deltas = 0;
};

class EntityStore final : public ops::Applier {
 public:
  static constexpr std::uint32_t kFormatVersion = 1;

  // --- Applier -----------------------------------------------------------------------------------------------
  std::string_view name() const override { return "EntityStore"; }
  ops::ApplyStatus apply(const ops::Operation& op) override;
  std::uint64_t fingerprint() const override;   // FNV-1a 64 of serialize()

  // --- reads -------------------------------------------------------------------------------------------------
  bool alive(EntityId id) const { return slot_of(id) != nullptr; }
  EntityKind kind(EntityId id) const;                  // EntityKind::kCount when the entity does not exist
  std::uint16_t sort(EntityId id) const;
  std::uint64_t created_tick(EntityId id) const;
  Position position_mm(EntityId id) const;
  EntityId holder(EntityId id) const;                  // 0 = on the ground
  std::uint32_t held_count(EntityId id) const;         // entities that name this one as holder
  std::size_t size() const { return alive_; }
  std::size_t slot_count() const { return slots_.size(); }
  EntityId next_id() const;                            // the id the next Spawn will receive (0 when full)
  const StoreStats& stats() const { return stats_; }

  // The generated component C of an entity, or nullptr when it does not exist or its kind has no such component.
  template <class C>
  const C* component(EntityId id) const {
    const Slot* s = slot_of(id);
    const C* out = nullptr;
    if (!s) return out;
    gen::dispatch(static_cast<EntityKind>(s->kind), tables_, [&](const auto& t) { out = gen::find_component(t.rows[s->row], gen::Tag<C>{}); });
    return out;
  }
  // Any scalar variable by catalogue index (Var of var_registry.json); false when absent or not scalar.
  bool read_var(EntityId id, std::uint16_t var, std::int64_t& value) const;

  // Calls f(EntityId, EntityKind) for every living entity, in slot order (independent of creation history of threads).
  template <class F>
  void for_each(F&& f) const {
    for (std::size_t i = 0; i < slots_.size(); ++i)
      if (slots_[i].state == kAlive) f(make_entity_id(std::uint32_t(i + 1), slots_[i].generation), static_cast<EntityKind>(slots_[i].kind));
  }
  template <class F>
  void for_each_of(EntityKind k, F&& f) const {
    for_each([&](EntityId id, EntityKind kk) { if (kk == k) f(id); });
  }

  // --- save / load (by slot, field descriptors; refuses another schema, never guesses) --------------------------
  void serialize(std::vector<std::uint8_t>& out) const;
  std::vector<std::uint8_t> serialize() const { std::vector<std::uint8_t> v; serialize(v); return v; }
  LoadStatus load(std::span<const std::uint8_t> bytes);   // on failure the store is left untouched

  // Heap bytes held (capacity of slots, free list, rows); divide by size() for a per-entity figure.
  std::size_t memory_bytes() const;

 private:
  enum : std::uint8_t { kFree = 0, kAlive = 1, kRetired = 2 };
  struct Slot {
    std::int64_t created_tick = 0;
    std::array<std::int32_t, 3> pos{};
    EntityId holder = kNoEntity;
    std::uint32_t row = 0;
    std::uint32_t held = 0;
    std::uint16_t kind = 0, sort = 0, generation = 0;
    std::uint8_t state = kFree;
  };
  using Tables = gen::Tables<KindTable>;

  const Slot* slot_of(EntityId id) const;
  Slot* slot_of(EntityId id) { return const_cast<Slot*>(std::as_const(*this).slot_of(id)); }
  bool holder_ok(EntityId self, EntityId holder) const;   // alive, spatial, and not self or a descendant of self (no depth limit)
  ops::ApplyStatus do_spawn(const ops::Operation& op);
  ops::ApplyStatus do_destroy(const ops::Operation& op);
  ops::ApplyStatus do_move(const ops::Operation& op);
  ops::ApplyStatus do_delta(const ops::Operation& op);

  std::vector<Slot> slots_;
  std::deque<std::uint32_t> free_;   // slot numbers (0-based), reused first-in first-out (wear spread over all slots)
  Tables tables_;
  std::size_t alive_ = 0;
  StoreStats stats_;
};

}  // namespace em::act
