// Builders for the entity operations of docs/14 section 4.6 (Spawn, Destroy, Move, EntityDelta). The EntityStore
// changes only through these operations, delivered by the OperationBus.
//   Spawn       { u32 entity (0 = let the store allocate; else it must be the id the store would give),
//                 u16 kind (EntityKind), i32 pos_mm[3], u32 holder (0 = on the ground) [, u16 sort] }
//   Destroy     { u32 entity }
//   Move        { u32 entity, i32 to_mm[3], u32 holder }
//   EntityDelta { u32 entity, u16 var (var_registry.json index), i32 old, i32 new }
#pragma once
#include <array>
#include <cstdint>

#include "emergence/act/entity_id.h"
#include "emergence/ops/operation.h"

namespace em::act {

using Position = std::array<std::int32_t, 3>;   // millimetres

ops::Operation make_spawn(std::uint64_t tick, std::uint32_t author, std::uint16_t kind, const Position& pos_mm,
                          EntityId holder = kNoEntity, std::uint16_t sort = 0, EntityId expected = kNoEntity);
ops::Operation make_destroy(std::uint64_t tick, std::uint32_t author, EntityId entity);
ops::Operation make_move(std::uint64_t tick, std::uint32_t author, EntityId entity, const Position& to_mm,
                         EntityId holder = kNoEntity);
ops::Operation make_delta(std::uint64_t tick, std::uint32_t author, EntityId entity, std::uint16_t var,
                          std::int32_t old_value, std::int32_t new_value);

}  // namespace em::act
