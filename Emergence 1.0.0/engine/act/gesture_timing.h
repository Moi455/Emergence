// Gesture timing (T22, docs/14 section 4.4): what the catalogue says about HOW LONG a gesture lasts, read from the generated
// table (gesture_timing_gen.h, from actions.toml): cadence_ms, natural_end, productive and the chosen durations. The engine
// has no other clock rule: no gesture is timed by a constant of the code.
//
//  * One engine tick = 16 game seconds = 1000 ms of real time (NpcLaws::kTickS). A cycle (a blow, a stride, a sip) lasts
//    cadence_ms of REAL time; CycleClock turns the 1000 ms of a tick into whole cycles and keeps the remainder.
//  * Work on matter is counted per cycle and multiplied by kTaskCompression for the PRODUCTIVE gestures only
//    (compressed_work), so that a job lasts its real-life duration in game time; bodily harm is never compressed.
//  * Chosen durations (brief, a_while, long) are game seconds (kDurationLevels).
//
// Calibrations (estimated, to be measured against the voxel world; they are not rules of behaviour): the speeds of the paces,
// the reach, the blow speeds and the volumes. They live here, named, and nowhere else.
#pragma once
#include <cstdint>
#include <string_view>
#include <vector>

#include "emergence/social/catalogue_gen.h"
#include "emergence/social/npc_laws.h"
#include "gesture_timing_gen.h"
#include "laws/law_kit.h"
#include "matter_catalog.h"

namespace em::act {

using social::gen::Condition;
using social::gen::Gesture;

inline constexpr std::int64_t kTickGameS = social::NpcLaws::kTickS;   // 16
inline constexpr std::int64_t kTickRealMs = 1000;
static_assert(kTickGameS == 16);

struct GestureTiming {
  bool natural_end = false;
  bool productive = false;
  std::uint16_t cadence_ms = 1000;
  bool has_until = false;      // the gesture has a parameter of type condition (strike, grab, sleep, wait)
  bool has_duration = false;   // the gesture has a chosen-duration parameter (brief, a_while, long)
  bool has_amount = false;     // the gesture has an amount parameter (little, some, all)
  social::gen::Family family{};
};

const GestureTiming& timing_of(Gesture g);

// Index of the parameter of that name in the gesture's spec, or -1. The chosen-duration parameter is `duration`, or
// `thoroughness` for search.
int param_index(Gesture g, std::string_view name);

// Game seconds of a chosen duration level (0 brief, 1 a_while, 2 long); the a_while level is also the mechanical limit
// of a gesture that has nothing to stop it (docs/14 4.3, order of stop: until, decision head, natural_end, a_while).
std::int64_t duration_level_game_s(int level);
inline constexpr int kLevelBrief = 0, kLevelAWhile = 1, kLevelLong = 2;

// Whole cycles that complete during one tick; the remainder (ms) is carried to the next one.
class CycleClock {
 public:
  std::uint32_t advance(std::uint32_t cadence_ms, std::uint32_t elapsed_ms = kTickRealMs) {
    acc_ += elapsed_ms;
    const std::uint32_t n = acc_ / cadence_ms;
    acc_ -= n * cadence_ms;
    return n;
  }
  std::uint32_t remainder_ms() const { return acc_; }

 private:
  std::uint32_t acc_ = 0;
};

// ---- calibrations ---------------------------------------------------------------------------------------------------------
inline constexpr std::int32_t kPaceSpeedMmS[4] = {700, 1300, 1900, 3500};   // slow, walk (docs/14 4.4: 1.3 m/s), brisk, run
inline constexpr std::int32_t kClimbSpeedPermille = 300;                      // of the walking speed
inline constexpr std::int32_t kSwimSpeedMmS = 800;
inline constexpr std::uint32_t kNoEffectCycles = 3;                         // contacts without effect before a gesture is felt to fail
inline constexpr std::int32_t kReachMm = 1500;                               // a hand reaches this far from the body
inline constexpr std::int32_t kStopAtMm[4] = {600, 2000, 3000, 0};           // touch, near, talk, sight (sight: stop when seen)
inline constexpr std::int32_t kArrivedMm = 400;                              // "arrived" at a point
inline constexpr std::int32_t kNearMm = 3000;                                // c_target_near: within hand or voice reach
inline constexpr std::int32_t kBlowSpeedMmS[5] = {800, 2000, 4000, 6000, 9000};   // faint .. full, speed of the tool at contact
inline constexpr std::uint8_t kVolumeNoise[5] = {1, 2, 4, 7, 9};             // whisper .. shout, perceptibility 0..10
inline constexpr std::int32_t kJumpMm[5] = {400, 800, 1200, 1800, 2500};     // faint .. full
inline constexpr std::int32_t kTenthsPerFoodPoint = 3;                       // one point (0..10) of nutrition or hydration, in tenths of hunger or thirst
inline constexpr std::int32_t kRestedSleepinessMaxTenths = 10;               // c_rested: sleepiness at most 1.0 and exhaustion at most 2.0
inline constexpr std::int32_t kRestedExhaustionMaxTenths = 20;

// Nutrition and hydration of the item sorts, resolved once against the matter catalogue (sort = index in kKinds).
class IngestTable {
 public:
  explicit IngestTable(const MatterCatalog& catalog);
  std::int32_t nutrition(std::uint16_t sort) const { return sort < nutrition_.size() ? nutrition_[sort] : 0; }
  std::int32_t hydration(std::uint16_t sort) const { return sort < hydration_.size() ? hydration_[sort] : 0; }

 private:
  std::vector<std::int8_t> nutrition_, hydration_;
};

// The contact manner a gesture makes with its parameters (strike -> Strike, work/saw -> Slice, work/rub -> Rub ...).
// `value(param)` is the value index the model chose (-1 absent).
Manner manner_of(Gesture g, int motion_or_mode_value);

}  // namespace em::act
