// MatterCatalog (T18): what the laws of matter read about a thing, never its name. A Profile is the physical sheet of an
// entity sort (the index of its id in kKinds): mass, size, the parts (form + material) and what each form gives. Item sorts come from the generated
// table (matter_gen.h, from catalogue/data/items_*.toml); structures, plants and objects nobody has seen yet are
// registered with set_profile(). Everything is integer: grams, millimetres, per-mille.
#pragma once
#include <array>
#include <cstdint>
#include <span>
#include <string_view>
#include <vector>

#include "emergence/act/entity_store.h"
#include "matter_gen.h"

namespace em::act {

using matter::Cohesion;
using matter::ProcessId;
inline constexpr std::uint16_t kNoMatter = matter::kNoMatter;

struct Extent { std::int32_t x = 0, y = 0, z = 0; };   // full size in mm; y is up

struct Part { std::uint16_t form = 0, material = kNoMatter; };

inline constexpr std::int32_t kMaxMassG = 100000000;   // 100 t: bounds every product of the integer laws
inline constexpr std::int32_t kMaxSizeMm = 100000;      // 100 m

struct Profile {
  std::uint16_t sort = 0;                // canonical sort: index of the id in kKinds (vocab_registry.json)
  std::int32_t mass_g = 0;
  Extent size{};                         // 0 on an axis = derived from mass and density (a cube)
  std::vector<Part> parts;               // first part = main material
  std::vector<std::uint16_t> made_by;    // ProcessId that make this sort (items)
  // Derived by MatterCatalog::finish(): the union of the form bits of the parts, and the hardest material of the
  // parts that give edge / point / abrasiveness / binds.
  std::uint8_t flags = 0;
  std::int16_t edge_hardness = 0, point_hardness = 0, abrasive_hardness = 0, binds_toughness = 0, max_hardness = 0;
  std::uint16_t main_material() const { return parts.empty() ? kNoMatter : parts[0].material; }
};

class MatterCatalog {
 public:
  MatterCatalog();   // loads every item sort of the generated table

  // Sheet of the entity sort, or nullptr (unknown sort: the laws see nothing to act on, they never guess).
  const Profile* profile(gen::EntityKind kind, std::uint16_t sort) const;
  // Registers or replaces a profile (derives the flags and the size). Not thread-safe: call before simulating.
  void set_profile(gen::EntityKind kind, std::uint16_t sort, Profile p);

  static const matter::MaterialRow& material(std::uint16_t id) { return matter::kMaterials[id]; }
  static const matter::ProcessRow& process(ProcessId id) { return matter::kProcesses[static_cast<std::size_t>(id)]; }
  std::uint16_t find_material(std::string_view name) const;   // kNoMatter when absent
  std::uint16_t find_item(std::string_view name) const;       // item sort (1-based), 0 when absent
  std::string_view item_name(std::uint16_t sort) const;

  // Sorts the laws hand out, found by properties:
  //  - the item that is exactly this part (same form and material), else exactly this material in one part; 0 if none.
  std::uint16_t element_item(const Part& p, bool allow_material_only = true) const;
  //  - the heaviest single-material item of `material`, made by `by`, strictly lighter than below_g; 0 if none.
  std::uint16_t piece_item(std::uint16_t material, ProcessId by, std::int32_t below_g) const;
  //  - the first item whose only part is `material` (what a process `produces` becomes in the world); 0 if none.
  std::uint16_t item_of_material(std::uint16_t material) const;

 private:
  void finish(Profile& p) const;
  std::vector<Profile> items_;                                   // index = registry index of matter_registry.json
  std::vector<std::uint32_t> by_sort_;                           // kKinds index -> items_ index + 1 (0 = none)
  std::array<std::vector<Profile>, gen::kEntityKindNames.size()> custom_;   // index = sort (dense, sparse sorts leave empty profiles)
  std::array<std::vector<bool>, gen::kEntityKindNames.size()> custom_set_;
};

// Integer cube root (floor).
std::int32_t icbrt(std::uint64_t v);

}  // namespace em::act
