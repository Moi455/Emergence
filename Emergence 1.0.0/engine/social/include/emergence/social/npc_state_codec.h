// Save and load of the NPC state: sections NAME and NPCS v1 of the EMSV file (docs/14 section 7.6).
// - Read BY NAMES: a saved column the build does not know is skipped and counted; a column the save lacks keeps its
//   initial value; a change of type is refused (only a widening i16 -> i32 or u8 -> u16 is accepted).
// - No raw struct copy: every field goes through the generated descriptors (npc_fields_gen.h), so the compaction of
//   the state (T06) or a new column never breaks an old save.
// - Lists (ListRef) are saved as their CONTENT and put back in a fresh SideTable; propositions (PropRef since T06) are saved as the 20-symbol exchange type, with their
//   word and kind symbols as indices of the NAME tables, and translated back by name on load.
// - Values are validated against the bounds of the catalogue (FieldDesc::min / max): a value outside is reset to the
//   initial one and counted, never kept. A structural error (kind, slot, serial) refuses the whole load, and `out` is emptied.
// - Fail closed: a wrong CRC, a truncated or malformed section, a type change: nothing is loaded.
#pragma once
#include <cstddef>
#include <cstdint>
#include <memory>
#include <span>
#include <string>
#include <vector>

#include "emergence/social/governor.h"
#include "emergence/social/npc_laws.h"
#include "emergence/social/npc_fields_gen.h"
#include "emergence/social/npc_state_gen.h"
#include "emergence/social/proposition_arena.h"
#include "emergence/social/side_table.h"
#include "emergence/social/vocab_gen.h"

namespace em::social {

// Everything the save keeps for one NPC.
struct NpcBundle {
  gen::NpcState state;
  SideTable side;                          // targets of the ListRef fields
  PropositionArena propositions;           // targets of the PropRef fields (T06)
  WriteLedger ledger;                      // what the model already moved (restored by WriteLedger::restore)
  std::vector<std::uint8_t> mental_map;    // reserved: the mental map, filled by T23b (opaque bytes)
  NpcLaws::Residue laws_residue;           // fractions kept by the laws of the tick (T21); saved in the LAWS section, not in NPCS

  // Keeps a proposition for a record field. When the arena is full: first a compaction (garbage left by overwritten
  // or forgotten records), then the law of forgetting of the catalogue frees the worst belief or episode that holds a
  // proposition (a protected one only when every candidate is protected, counted in evicted_protected()), and so on.
  // Never aborts, never allocates. Returns 0 (counted in propositions.refused()) only when nothing more can go.
  // Put the returned reference in a record of this NPC BEFORE the next call: a compaction only keeps the references
  // that a record holds.
  PropRef store_proposition(const Proposition& p, GameTime now);
  Proposition proposition(PropRef ref) const { return propositions.get(ref); }
  // Compaction of the arena: keeps what the records of this NPC reference, in the order of the descriptors.
  void collect_propositions();
  // Calls f(PropRef&) for every proposition reference held by a flat component or a used slot of a pool.
  template <class F>
  void for_each_prop_ref(F&& f);
};

template <class F>
void NpcBundle::for_each_prop_ref(F&& f) {
  auto walk = [&](const gen::ComponentDesc& d, unsigned char* base) {
    for (const gen::FieldDesc& fd : d.fields)
      if (fd.type == gen::ColType::Prop) f(*reinterpret_cast<PropRef*>(base + fd.offset));
  };
  gen::visit_components(state, [&](const gen::ComponentDesc& d, auto& c) { walk(d, reinterpret_cast<unsigned char*>(&c)); });
  gen::visit_pools(state, [&](const gen::ComponentDesc& d, auto& pool) {
    for (int i = 0; i < std::decay_t<decltype(pool)>::kCapacity; ++i)
      if (pool.slot_used(i)) walk(d, reinterpret_cast<unsigned char*>(&pool.slot_record_mut(i)));
  });
}

// The NAME tables: the names behind every numeric id, in the order of this build.
struct NameTables {
  std::vector<std::string> gestures, conditions, variables, words, kinds;
  static NameTables current();
};

enum class Refusal : std::uint8_t {
  None, BadTag, BadVersion, Truncated, BadCrc, Malformed, TypeChanged, CapacityExceeded, NameTableMissing,
};

struct LoadReport {
  bool ok = false;
  Refusal refusal = Refusal::None;
  std::string detail;                    // what was refused (a kind.column for a type change)
  std::size_t npcs = 0;
  std::size_t unknown_components = 0;    // saved kinds this build does not have (skipped)
  std::size_t unknown_columns = 0;       // saved columns this build does not have (skipped)
  std::size_t absent_columns = 0;        // columns of this build the save lacks (initial value)
  std::size_t widened_columns = 0;       // columns read through an accepted widening
  std::size_t dropped_propositions = 0;  // propositions with a word or kind the NAME table no longer knows (emptied)
  std::size_t invalid_propositions = 0;  // malformed propositions (tag outside 1..6, children counts that are not one tree): emptied
  std::size_t arena_overflow_propositions = 0;   // valid propositions that did not fit the 20 KiB arena (a save older than T06 can hold more): emptied
  std::size_t out_of_range_values = 0;   // values outside the catalogue bounds of their column: reset to the initial value
  std::size_t dangling_refs = 0;         // MRef above every serial the NPC ever issued: reset to 0
  std::size_t dropped_ledger_entries = 0;
  std::size_t lost_lists = 0;            // lists that did not fit the fresh side table
  std::size_t ledger_rejected = 0;       // NPCs whose ledger restore() refused (their bounds are locked)
};

class NpcStateCodec {
 public:
  static constexpr std::uint32_t kTagName = 'N' | 'A' << 8 | 'M' << 16 | 'E' << 24;
  static constexpr std::uint32_t kTagNpcs = 'N' | 'P' << 8 | 'C' << 16 | 'S' << 24;
  static constexpr std::uint16_t kVersion = 1;

  // ---- section frame: u32 tag | u16 version | u16 flags | u64 length | u32 crc32 | bytes
  static std::vector<std::uint8_t> wrap_section(std::uint32_t tag, std::uint16_t version, std::span<const std::uint8_t> payload);
  // Checks the tag, the version (<= kVersion), the length and the CRC; `payload` points into `bytes`.
  static Refusal unwrap_section(std::span<const std::uint8_t> bytes, std::uint32_t tag, std::span<const std::uint8_t>& payload);
  static std::uint32_t crc32(std::span<const std::uint8_t> bytes);

  // ---- save (framed sections)
  static std::vector<std::uint8_t> save_name_section(const NameTables& names = NameTables::current());
  static std::vector<std::uint8_t> save_npcs_section(std::span<const std::unique_ptr<NpcBundle>> npcs);

  // ---- load: all or nothing. `now_day` / `now_life_year` are the ENGINE's clock, given to WriteLedger::restore().
  static LoadReport load(std::span<const std::uint8_t> name_section, std::span<const std::uint8_t> npcs_section,
                         std::int32_t now_day, std::int32_t now_life_year, std::vector<std::unique_ptr<NpcBundle>>& out);

  // Logical fingerprint (FNV-1a 64 of the canonical encoding): identical for two NPCs that hold the same content,
  // whatever their memory layout (slots and serials of the pools and the CONTENT of the lists count, not the addresses).
  static std::uint64_t fingerprint(const NpcBundle& npc);
};

}  // namespace em::social
