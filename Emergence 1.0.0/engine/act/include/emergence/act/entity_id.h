// EntityId of the non-voxel world (T15): an objective, stable identifier with a generation.
// 22 bits of slot number (1-based, so that 0 is "no entity") and 10 bits of generation. A slot is reused after
// its entity is destroyed, with the generation raised by one: an old id never designates the new entity. A slot whose
// generation would overflow is retired for good, so that an id is never ambiguous. Nothing here depends on an address.
#pragma once
#include <cstdint>

namespace em::act {

using EntityId = std::uint32_t;   // same 32 bits as em::social::EntityId and the `entity` of an Operation payload
inline constexpr EntityId kNoEntity = 0;
inline constexpr unsigned kIndexBits = 22;
inline constexpr unsigned kGenerationBits = 10;
inline constexpr std::uint32_t kIndexMask = (1u << kIndexBits) - 1;
inline constexpr std::uint32_t kMaxGeneration = (1u << kGenerationBits) - 1;

constexpr std::uint32_t index_of(EntityId id) { return id & kIndexMask; }              // 1-based
constexpr std::uint32_t generation_of(EntityId id) { return id >> kIndexBits; }
constexpr EntityId make_entity_id(std::uint32_t index, std::uint32_t generation) {
  return (generation << kIndexBits) | (index & kIndexMask);
}

}  // namespace em::act
