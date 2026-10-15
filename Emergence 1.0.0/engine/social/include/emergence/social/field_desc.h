// Descriptors of the generated NPC state fields (hand-written types; the tables are generated into npc_fields_gen.h).
// The save codec reads a field by its NAME and its storage type, never by copying a struct.
#pragma once
#include <cstddef>
#include <cstdint>
#include <span>
#include <string_view>

namespace em::social::gen {

// Storage type of a field. The numeric codes are written in the save file: append only, never renumber.
enum class ColType : std::uint8_t {
  Bool = 1, U8 = 2, U16 = 3, I16 = 4, I32 = 5, Entity = 6, Time = 7, List = 8, MRef = 9, Prop = 10,
};

struct FieldDesc {
  std::string_view name;   // the catalogue variable id
  ColType type;
  std::size_t offset;      // offsetof in the generated struct
  std::size_t size;        // sizeof of the field
  std::int64_t min, max;   // inclusive bounds of a valid stored value (from the catalogue); checked at load
};

struct ComponentDesc {
  std::string_view name;               // the kind: a component id of the catalogue
  bool record;                         // true: a pool of records; false: one flat struct per NPC
  int capacity;                        // records per NPC (0 for a flat component)
  std::span<const FieldDesc> fields;
};

}  // namespace em::social::gen
