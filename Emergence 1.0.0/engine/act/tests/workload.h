// Deterministic workload shared by the test and the bench (no rand(), no clock): N entities created, moved, changed
// and destroyed through the operation bus.
#pragma once
#include <cstdint>
#include <vector>

#include "emergence/act/entity_store.h"
#include "emergence/ops/operation_bus.h"

namespace em::act::workload {

struct Counts { std::uint64_t spawn = 0, move = 0, delta = 0, destroy = 0, ops = 0; };

inline std::uint32_t mix(std::uint32_t x) {   // small integer hash
  x ^= x >> 16; x *= 0x7feb352dU; x ^= x >> 15; x *= 0x846ca68bU; x ^= x >> 16;
  return x;
}

// Kinds that carry a position, so that every entity can be moved.
inline std::uint16_t movable_kind(std::uint32_t i) {
  static constexpr gen::EntityKind kinds[] = {gen::EntityKind::agent, gen::EntityKind::animal, gen::EntityKind::plant,
                                              gen::EntityKind::item, gen::EntityKind::structure};
  return static_cast<std::uint16_t>(kinds[mix(i) % 5]);
}

// Phase 1 (tick 1): n spawns; phase 2 (tick 2): every entity moves; phase 3: a delta on every plant/item; phase 4: half die.
inline Counts run(ops::OperationBus& bus, EntityStore& store, std::uint32_t n) {
  Counts c;
  std::vector<EntityId> ids(n);
  for (std::uint32_t i = 0; i < n; ++i)
    bus.submit(make_spawn(1, 1 + i % 500, movable_kind(i), {std::int32_t(i), std::int32_t(mix(i) & 0xFFFF), 0}, kNoEntity, std::uint16_t(i & 0xFF)), i);
  c.spawn = bus.flush(1);
  std::uint32_t k = 0;
  store.for_each([&](EntityId id, gen::EntityKind) { ids[k++] = id; });
  for (std::uint32_t i = 0; i < n; ++i)
    bus.submit(make_move(2, 1 + i % 500, ids[i], {std::int32_t(i) + 1000, std::int32_t(mix(i + 7) & 0xFFFF), 50}), i);
  c.move = bus.flush(2);
  // plant growth stage: variable index of "plant_health" is looked up by the caller's descriptors
  std::uint16_t var = 0;
  for (const auto& f : gen::kPlantFields) if (f.name == "plant_health") var = f.var;
  for (std::uint32_t i = 0; i < n; ++i)
    if (store.kind(ids[i]) == gen::EntityKind::plant)
      bus.submit(make_delta(3, 1 + i % 500, ids[i], var, 0, std::int32_t(1 + mix(i) % 100)), i);
  c.delta = bus.flush(3);
  for (std::uint32_t i = 0; i < n; i += 2) bus.submit(make_destroy(4, 1 + i % 500, ids[i]), i);
  c.destroy = bus.flush(4);
  c.ops = c.spawn + c.move + c.delta + c.destroy;
  return c;
}

}  // namespace em::act::workload
