// ContextBuilder (T28b): the NPC's own state -> the DecisionContext (the dossiers of one decision) that the Tokenizer of T28
// turns into the arrays the Transformer reads. No JSON in between. Everything the engine needs to feed the model.
//
//   ContextBuilder cb(tokenizer);                        // builds its tables once; immutable, shareable between threads
//   ContextBuilder::Workspace ws;                        // scratch owned by the caller, one per thread
//   MindSource src{&bundle, now, wake, links};           // the NPC's mind, the clock, why it wakes, perception links
//   DecisionContext ctx;
//   cb.build(src, ws, ctx);                              // select (salience), then assemble the records
//   tokenizer.encode(ctx, enc);                          // T28
//
// What it reads. Only the NPC's OWN dossiers, through the variables that have a token in the catalogue (the generated list
// tok2::gen::kSources, context_map_gen.h): beliefs, memories, mental files of people and groups, what it perceives (entity_percept,
// percept, place_percept, event_seen), goals, intentions, requests, skills, its body, needs, mind. Never the truth
// (b_truth, b_origin_fact, m_fact_ref, r_true_entity, wealth_objective... have no accessor here). A test (test_context_builder)
// rewrites every variable that has no token and checks that the context does not change.
//
// Selection. The dossier has 128 tokens at most and a budget per type (12 beliefs, 9 memories, 10 persons, 4 goals...).
// CandidateSelector (T28) ranks the beliefs (64), memories (32) and persons (24) by an integer salience; the builder keeps the
// best of each, ties to the most recent record. Whatever the dossier does not carry stays reachable as a GHOST: a pointer from a
// carried record to a record of the NPC's mind that is not in the dossier is written with its key and added to known_keys, and
// the tokenizer numbers it 129 + k. The record that woke the NPC (WAKE.trigger) is always carried.
//
// Conventions of the state that the catalogue does not fix yet (flagged in docs/15, T28b):
//  - UNKNOWN. A field the NPC does not know is stored with its in-band marker (namespace unknown): INT16_MIN, INT32_MIN,
//    0xFF (enum), 0xFFFF (word), INT64_MIN (time), 0xFFFFFFFF (pointer, list, proposition). A zero is a known zero. A bool has
//    no marker; b_unintelligible is the one sparse flag (emitted only when true). A person not present carries no
//    distance, direction or look (the oracle's rule).
//  - POINTERS. An MRef is a serial of a record of the NPC. The kind of record is a tag in the top byte (RefKind); without tag the
//    kind is the first kind the field accepts (a belief's informant is a person). "Me" and "here" are the tags self / place.
//  - WORDS. A u16 word id is an index in gen::kWords, then gen::kKinds (id - kWords.size()); 0 is "none". A name
//    (r_name_believed) holds the name number (n:<id>).
//  - PACKED. A direction (ep_dir, pc_dir, lc_dir) is sin and cos in thousandths, two int16 (high, low). time_felt is cos (11
//    bits), sin (11 bits), certainty in thousandths (10 bits). A list of vector components (props, held, reputation) is words
//    (a component name: true) and pairs {0x80000000 | component index, int32 thousandths}, objects separated by 0xFFFFFFFF.
//    i_step_targets may start with a header item (bit 31) holding the target of the whole plan (PLAN.target):
//    SKIP IT when walking the steps (plan_target_header.h, shared with the executor).
//  - SERIALS. A pool serial is at most 2^23 - 1 (RecordPool::kSerialMax): the top byte of an MRef is the kind tag; bit 23 is
//    only used to tell a group file from a person file.
//  - LISTS OF RECORDS. heard_unprocessed: pairs (number of the key h:<number>, serial of the belief). inv_seen: records of 10 words (a percept: serial, kind,
//    color, age, amount, depth, owner, props, state, file certainty). commitments_seen: records of 10 words (serial, proposition,
//    counterparty, mine, status, deadline lo/hi, when lo/hi, witnesses). tastes: pairs (concept word, attitude in tenths).
//  - The keys: @E<relation serial>, @G<group serial> (bit 23 of a serial is not part of a key number: it keeps a group apart from a person in the pool), @T<percept or inv serial>, @L, @V, b:, m:, g:, h:, q:, p:, k:, c:, t:<rank>;
//    a person perceived but not filed is @E<kStrangerBase + percept serial>.
// Deterministic: integers only, no clock, no random; the same state gives the same context bit for bit.
#pragma once
#include <climits>
#include <cstdint>
#include <memory>
#include <span>
#include <string>
#include <string_view>
#include <vector>

#include "emergence/social/npc_state_codec.h"
#include "emergence/social/plan_target_header.h"
#include "emergence/social/tokenizer/candidates.h"
#include "emergence/social/tokenizer/tokenizer.h"

namespace em::social::tok2 {

namespace unknown {   // the in-band "unknown" markers of the state
inline constexpr std::int16_t kI16 = INT16_MIN;
inline constexpr std::int32_t kI32 = INT32_MIN;
inline constexpr std::uint8_t kU8 = 0xFF;
inline constexpr std::uint16_t kU16 = 0xFFFF;
inline constexpr GameTime kTime = INT64_MIN;
inline constexpr std::uint32_t kRef = 0xFFFFFFFFu;   // MRef serial, ListRef, PropRef
}  // namespace unknown

// The kind of record an MRef designates (top byte of the serial). none: the first kind the field accepts.
enum class RefKind : std::uint8_t {
  none = 0, entity, thing, inv, group, locus, event, belief, memory, goal, heard, request, commit, plan, self, place, kCount
};
inline constexpr MRef make_ref(RefKind k, std::uint32_t serial = 0) { return MRef{(std::uint32_t(k) << 24) | (serial & 0xFFFFFFu)}; }
inline constexpr RefKind ref_kind(MRef r) { return r.serial == unknown::kRef ? RefKind::kCount : RefKind(r.serial >> 24); }
inline constexpr std::uint32_t ref_serial(MRef r) { return r.serial & 0xFFFFFFu; }
inline constexpr MRef kUnknownRef{unknown::kRef};

inline constexpr std::uint32_t kStrangerBase = 1u << 19;      // @E key of a person perceived but not filed: base + percept serial
inline constexpr std::uint32_t kObjectEnd = 0xFFFFFFFFu;      // ends one object in a list of vectors
inline constexpr std::uint32_t kValuedItem = 0x80000000u;     // {kValuedItem | component, thousandths}
// kPlanTargetHeader, is_target_header, strip_target_header, skip_target_header: plan_target_header.h (shared with the executor T22)
inline constexpr int kInvStride = 10, kCommitStride = 10, kTasteStride = 2;

enum class WakeMode : std::uint8_t { act, listen, reflect };
enum class WakeCause : std::uint8_t { perception, speech, request, body, plan, timer, routine, goal_check, occasion, idle };
enum class WakeOutcome : std::int8_t { none = -1, done, failed, blocked, interrupted, limit_reached };

// Why the NPC wakes now (the scheduler writes it; nothing here is the truth of the world).
struct WakeInput {
  WakeMode mode = WakeMode::act;
  WakeCause cause = WakeCause::idle;
  MRef trigger{};                  // the record that woke it (tagged): event, heard, request, goal, plan, commit, person or group
  int urgency_tenths = 0;          // 0..100
  int budget = 0;                  // thinking steps still granted (w_think_budget)
  int temperament_tenths = 50;     // village_temperament, 0 sages .. 100 fools (a setting of the game, public)
  WakeOutcome outcome = WakeOutcome::none;
};

// The link the perception keeps between a person it sees (an entity_percept record) and the mental file the NPC has for him.
struct FileLink {
  std::uint32_t percept = 0;       // serial in entity_percept_records
  MRef file{};                     // serial in relation_records (0: not filed)
};

struct MindSource {
  const NpcBundle* mind = nullptr;
  GameTime now = 0;                // game seconds
  WakeInput wake;
  std::span<const FileLink> links;
};

// The records chosen for the dossier, in dossier order (most salient first). Serials of the NPC's own pools; lists by position.
struct Selection {
  struct Person { std::uint32_t relation = 0, percept = 0; };   // relation 0: a stranger; percept 0: not in sight
  std::vector<std::uint32_t> beliefs, heard, memories, goals, plans, requests, events, things, locus, groups, skills;
  std::vector<Person> persons;
  std::vector<int> inv, commits, tastes;   // positions in the lists of the side table
  void clear();
};

struct BuildStats {
  std::uint32_t records = 0;
  std::uint32_t clamped = 0;          // values outside their scale brought back to the bound (an engine defect)
  std::uint32_t dropped_pointers = 0; // pointers to a kind of record the field does not accept
  std::uint32_t skipped = 0;          // candidates without a readable proposition
};

class ContextBuilder {
 public:
  struct Workspace {
    Candidates candidates;
    Selection selection;
    std::vector<std::string> cited;      // keys of every pointer written (carried or not)
    BuildStats stats;
  };

  explicit ContextBuilder(const Tokenizer& tk);
  ~ContextBuilder();
  ContextBuilder(const ContextBuilder&) = delete;
  ContextBuilder& operator=(const ContextBuilder&) = delete;

  // Salience selection, then assembly. `out` is overwritten.
  void build(const MindSource& src, Workspace& ws, DecisionContext& out) const;
  // The two halves: the selection can be given by someone else (a learned selector, a test).
  void select(const MindSource& src, Workspace& ws) const;
  void assemble(const MindSource& src, Workspace& ws, DecisionContext& out) const;

  const Tokenizer& tokenizer() const { return tk_; }

  // Names of the variables the builder reads (the generated TokenView) and, for tests, the table var -> holder.
  struct Impl;
  const Impl& impl() const { return *impl_; }

 private:
  const Tokenizer& tk_;
  std::unique_ptr<Impl> impl_;
};

}  // namespace em::social::tok2
