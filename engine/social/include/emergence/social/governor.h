// The governor of the social engine: it sits between the model and the world and only CLIPS or REFUSES, never
// decides. Port of catalogue/tools/governor.py (the oracle: tests/governor_vectors.inc are generated from it).
// Values are TENTHS of the charter scale (the engine stores tenths). Hard rule D10 is deny-by-default: an
// unknown or unresolved person, or an unknown age, counts as a possible minor.
#pragma once
#include <array>
#include <cstdint>
#include <unordered_map>

#include "emergence/social/catalogue_gen.h"

namespace em::social {

// One person involved in a gesture, a write or an utterance. Ages in tenths of years; -1 = unknown.
struct Party {
  std::int16_t real_age = -1;
  std::int16_t believed_age = -1;   // what the actor believes (no belief = unknown)
  std::int16_t apparent_age = -1;   // what the actor perceives
  bool resolved = false;            // tied to a seen, recognised person (not known only by name or description)

  bool may_be_minor() const;
};

enum class Reason : std::uint8_t {
  ok, jump, step, slow, clipped,
  unknown_variable, engine_owned, structured, no_writer,
  unknown_gesture, d10_intimate, d10_value, d10_person, d10_whitelist,
};

struct Verdict {
  bool allowed = false;
  std::int16_t value = 0;           // the clipped value (tenths) for a write
  Reason reason = Reason::ok;
};

// Per-NPC memory of what the model already moved, for the per-game-day and per-life-year bounds.
// The key is (variable, PERSISTENT id of the mental file), never a token slot.
class WriteLedger {
 public:
  void roll(std::int32_t day, std::int32_t life_year);
  std::int32_t& day_moved(gen::Var v, std::uint32_t target) { return day_[key(v, target)]; }
  std::int32_t& year_moved(gen::Var v, std::uint32_t target) { return year_[key(v, target)]; }

 private:
  static std::uint64_t key(gen::Var v, std::uint32_t t) { return (std::uint64_t(v) << 32) | t; }
  std::unordered_map<std::uint64_t, std::int32_t> day_, year_;
  std::int32_t day_index_ = 0, life_year_ = 0;
};

// A gesture as the model emitted it: one value index per parameter (-1 = absent; for a ref param any value >= 0
// means "given") and, for every param that designates a person, that person.
struct GestureCall {
  gen::Gesture gesture{};
  std::array<std::int8_t, gen::kMaxParams> value{-1, -1, -1, -1, -1, -1};
  std::array<const Party*, gen::kMaxParams> party{};
};

class Governor {
 public:
  Verdict check_write(gen::Var var, std::int16_t old_value, std::int16_t proposed, WriteLedger& ledger,
                      std::uint32_t target, const Party* intimate_target, const Party* actor, bool creating) const;
  Verdict check_gesture(const GestureCall& call, const Party* actor) const;
};

}  // namespace em::social
