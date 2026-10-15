// MindWriter (T24, docs/14 section 7): applies to the mind of ONE NPC the bounded writes the model asks for, always
// through the governor. It never decides: it carries out what the governor lets through, clipped to its bounds.
//
//  * at most kWritesPerDecision (4) writes per decision, one per (target, variable): Governor::check_writes;
//  * T_jump / T_step / T_slow, the per-decision step and the per-game-day / per-life-year rate: Governor::check_write
//    with the NPC's own WriteLedger (rolled to the game day and the life-year of `now`);
//  * D10: a rising intimate variable is refused when the actor, or the other person of the file, may be a minor;
//    NpcLaws::enforce_d10 is called at the end of every application (need_intimacy is 0 below the adult age);
//  * records (belief, goal, memory) written by the model go through Governor::check_record (said = false).
// Only I16 fields (tenths of the charter scale) are written here; any other storage is refused (Reason::structured).
// The truth (real ages) comes from a PartySource and is only used to REFUSE, never written in a dossier.
#pragma once
#include <deque>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

#include "emergence/social/governor.h"
#include "emergence/social/npc_state_codec.h"

namespace em::social {

// Who a person is for D10: ages (real = the truth, used only to refuse). `judge` is the NPC whose belief and eye
// fill believed_age and apparent_age; an unknown entity must answer Party{} (ages -1: a possible minor).
class PartySource {
 public:
  virtual ~PartySource() = default;
  virtual Party party_seen_by(EntityId judge, EntityId who) const = 0;
};

// One write asked by the model, as the decoder hands it over: target "self" or a pointer of the NPC's own mind
// (@E3 / @G3 a relation, b:7 / h:7 a belief, m:2 a memory, g:1 a goal), the variable and the new value in TENTHS.
struct WriteIntent {
  gen::Var var{};
  std::string target = "self";
  std::int16_t value = 0;
};

struct WriteOutcome {
  gen::Var var{};
  std::string target;
  Verdict verdict;
  std::int16_t old_value = 0, new_value = 0;
  bool applied = false;   // the stored value moved
};

struct MindWriteReport {
  std::vector<WriteOutcome> outcomes;   // in the order of the intents
  std::size_t kept = 0;                 // intents kept by the 4-writes rule
  std::size_t applied = 0;
  bool d10_reset = false;               // NpcLaws::enforce_d10 reset need_intimacy
};

struct RecordOutcome {
  Verdict verdict;
  MRef ref;               // the new record, serial 0 when refused or when nothing could be stored
};

// Symbols of the speaker's content bound to the Parties the governor needs (D10). Owns its strings.
struct PartyBindings {
  std::deque<std::string> symbols;
  std::vector<Party> parties;
  std::vector<PartyBinding> view() const;
};

// Read-only view of one NPC's mind for the governor: frozen copies of its cited records and the parties of its
// pointers. Memoised, so NOT shared between threads (make one per task).
class MindView {
 public:
  MindView(const NpcBundle& mind, EntityId self, const PartySource* parties);
  const NpcBundle& mind() const { return *mind_; }
  EntityId self() const { return self_; }
  // The frozen copy of "b:7" / "m:2" / "g:1" / "h:3" / "q:4" as a BARE proposition, null when there is none
  // (a missing record, @V and c: have no copy yet).
  const TypedExpression* frozen_copy(std::string_view ref) const;
  RecordLookup lookup() const;
  // Adds the @E pointers of `text` (and of the copies it cites, up to the governor's depth) to `out`.
  void bind_pointers(std::string_view text, PartyBindings& out, int depth = 0) const;
  Party self_party() const;
  // The party of the person file @E<serial> of this mind (unknown when there is no such file or no truth source).
  Party file_party(std::uint32_t serial) const;

 private:
  const NpcBundle* mind_;
  EntityId self_;
  const PartySource* parties_;
  mutable std::deque<std::pair<std::string, std::optional<TypedExpression>>> copies_;   // deque: stable addresses
};

class MindWriter {
 public:
  explicit MindWriter(const PartySource* parties = nullptr) : parties_(parties) {}

  MindWriteReport apply(NpcBundle& mind, EntityId self, GameTime now, std::span<const WriteIntent> intents) const;

  // A belief (inferred), a goal or a memory written by the model, judged by check_record. kind: belief, goal, memory.
  RecordOutcome write_record(NpcBundle& mind, EntityId self, GameTime now, RecordKind kind, std::string_view expression) const;

 private:
  const PartySource* parties_;
  Governor governor_;
};

}  // namespace em::social
