// The governor of the social engine: it sits between the model and the world and only CLIPS or REFUSES, never
// decides. Port of catalogue/tools/governor.py (the oracle: tests/governor_vectors.inc are generated from it).
// Values are TENTHS of the charter scale (the engine stores tenths). Hard rule D10 is deny-by-default: an
// unknown or unresolved person, or an unknown age, counts as a possible minor.
#pragma once
#include <array>
#include <cstddef>
#include <cstdint>
#include <span>
#include <string_view>
#include <type_traits>

#include "emergence/social/catalogue_gen.h"

namespace em::social {

// At most this many writes are kept per decision (governor.py WRITES_PER_DECISION).
inline constexpr std::size_t kWritesPerDecision = 4;

// One participant of a gesture, a write or an utterance. Ages are in tenths of years, -1 = unknown.
struct Party {
  std::int16_t real_age = -1;
  std::int16_t believed_age = -1;   // what the actor believes (no belief = unknown)
  std::int16_t apparent_age = -1;   // what the actor perceives
  bool resolved = false;            // tied to a seen, recognised person (not known only by name or description)
  bool person = true;               // false = a thing (a stone, a house): never a minor, never a party of D10

  bool may_be_minor() const;

  // Years -> tenths of years, FLOORED (toward "minor"): 17.96 years -> 179, never 180. A non-finite, negative or
  // absurd age (beyond the 16-bit range) gives -1: unknown, a possible minor (deny by default).
  static std::int16_t from_years(double years);
};

// The stable reason codes, the same names as the Python codes (governor.py Verdict.code).
enum class Reason : std::uint8_t {
  ok, jump, step, slow, clipped,
  unknown_variable, engine_owned, structured, non_finite, no_writer,
  unknown_gesture, invalid_value,
  d10_intimate, d10_value, d10_person, d10_whitelist,
  duplicate, too_many_writes, ledger_full,
  kCount
};

std::string_view to_string(Reason r);   // the Python code, e.g. "d10_value"

struct Verdict {
  bool allowed = false;
  std::int16_t value = 0;           // the clipped value (tenths) for a write; 0 when the write is refused outright
  Reason reason = Reason::ok;
};

// What one (target, variable) pair has already moved. Plain data with a fixed layout: it is what is saved.
struct LedgerEntry {
  std::uint32_t target = 0;         // PERSISTENT id of the mental file (never a token slot)
  std::uint16_t var = 0;            // gen::Var
  std::uint16_t reserved = 0;       // always 0
  std::int32_t day_stamp = 0;       // game day on which day_moved counts
  std::int32_t year_stamp = 0;      // life-year in which year_moved counts
  std::int32_t day_moved = 0;       // tenths moved on day_stamp (T_step writers)
  std::int32_t year_moved = 0;      // tenths moved in year_stamp (T_slow writers)
};
static_assert(sizeof(LedgerEntry) == 24 && std::is_trivially_copyable_v<LedgerEntry>);

// Per-NPC memory of what the model already moved, for the per-game-day and per-life-year bounds. A small flat
// table, deterministic, no allocation: an entry whose stamp is not the current day (or life-year) reads as zero
// and its slot is reused. Time never goes back (review 11): roll() ignores an earlier value, so an oscillating
// clock cannot refill the bounds; a bogus far-future day freezes them (deny, never a bound that resets).
// When the table holds kCapacity live entries a write to a NEW (target, variable) cannot be recorded and is
// refused (Reason::ledger_full, nothing moves): deny, never a bound that silently disappears.
class WriteLedger {
 public:
  static constexpr std::size_t kCapacity = gen::kLedgerCapacity;

  void roll(std::int32_t day, std::int32_t life_year);
  std::int32_t day() const { return day_; }
  std::int32_t life_year() const { return life_year_; }

  std::int32_t moved_today(gen::Var v, std::uint32_t target) const;
  std::int32_t moved_this_year(gen::Var v, std::uint32_t target) const;
  bool add_today(gen::Var v, std::uint32_t target, std::int32_t amount);       // false = table full
  bool add_this_year(gen::Var v, std::uint32_t target, std::int32_t amount);   // false = table full

  // Save / load. restore() refuses (returns false, leaves the ledger empty) more than kCapacity entries, a
  // duplicated (target, variable), a non-zero `reserved`, an unknown variable, a moved amount outside
  // [0, kMaxMoved] or a stamp later than the day / life-year restored.
  static constexpr std::int32_t kMaxMoved = 1 << 20;
  std::span<const LedgerEntry> entries() const { return {entries_.data(), size_}; }
  bool restore(std::int32_t day, std::int32_t life_year, std::span<const LedgerEntry> saved);

 private:
  std::size_t find(gen::Var v, std::uint32_t target) const;   // index, or size_ when absent
  LedgerEntry* acquire(gen::Var v, std::uint32_t target);
  bool live(const LedgerEntry& e) const;

  std::array<LedgerEntry, kCapacity> entries_{};
  std::size_t size_ = 0;
  std::int32_t day_ = 0, life_year_ = 0;
};

// One write proposed by the model.
struct WriteRequest {
  gen::Var var{};
  std::int16_t old_value = 0;                  // tenths
  std::int16_t proposed = 0;                   // tenths
  std::uint32_t target = 0;                    // persistent id of the mental file (0 for the actor himself)
  const Party* intimate_target = nullptr;      // the other person of an intimate variable (null = unknown)
  const Party* actor = nullptr;                // null = unknown
  bool creating = false;                       // the record is being created by this write
};

// (target, variable) of a sparse write; the value is not needed to rank the writes.
struct WriteKey {
  std::uint32_t target = 0;
  gen::Var var{};
  friend bool operator==(const WriteKey&, const WriteKey&) = default;
};

// A gesture as the model emitted it: one value index per parameter, in the order of GestureSpec::params.
//   -1             absent
//   enum param     0 <= v < n_values
//   any other      v == 0 means "given"
// Anything else is Reason::invalid_value. For every GIVEN party param, party[i] must be what it designates: a
// person, or a thing as Party{.person = false}; null counts as an unknown person (a possible minor). An absent
// non-optional party param of a contact gesture counts as an unknown person only if it may designate an agent.
// The model's own outputs are always checked with executed = true (every non-optional param present).
struct GestureCall {
  gen::Gesture gesture{};
  std::array<std::int8_t, gen::kMaxParams> value;
  std::array<const Party*, gen::kMaxParams> party{};

  GestureCall() { value.fill(-1); }
};

class Governor {
 public:
  Verdict check_write(const WriteRequest& request, WriteLedger& ledger) const;

  // executed = the model's own output: every non-optional param must be present. A gesture whose EXPRESSION
  // param is given (speak, write) is refused (Reason::structured): its content goes through check_utterance,
  // which is not ported yet (review 10). The oracle checks the content inside check_gesture.
  Verdict check_gesture(const GestureCall& call, const Party* actor, bool executed = false) const;

  // Sparse writes: one per (target, variable), the first kWritesPerDecision kept. out[i] is the verdict of
  // keys[i]: ok (kept), duplicate, or too_many_writes; returns how many are kept. `out` shorter than `keys`:
  // every out[i] is refused (invalid_value) and nothing is kept; out[keys.size()..] is left untouched.
  std::size_t check_writes(std::span<const WriteKey> keys, std::span<Verdict> out) const;
};

}  // namespace em::social
