// T21: the laws the ENGINE applies to the state of one NPC at every tick (docs/14 laws of the body and the mind).
//
// What it does: hunger, thirst, sleep debt, exhaustion, cold and heat, load, pain, bleeding and blood, healing, breath,
// the return of the emotions to the baseline mood (at the pace of the temperament), the slow fading of the attitudes,
// the sharpness of the memories, the mastery of the techniques, the ageing on the LifeClock.
// What it NEVER does: judge or decide in place of the model. No law reacts to an event ("he was insulted, so anger"):
// the model makes the emotions JUMP; the engine only brings them back, and lets the body weigh on them.
//
// Determinism: integer arithmetic only, no random draw. Every fractional part is kept in a per-NPC Residue
// (micro-units), which is PART OF THE NPC RECORD: NpcBundle::laws_residue, saved in the LAWS section (an addition: a
// save without it reloads with a zero residue). ONE STEP for the engine: kTickS = 16 game s = 1 real s. step() cuts any
// multiple of kTickS into ticks of kTickS and REFUSES (LawReport::refused, state untouched) any other duration, because
// the first-order returns are Euler schemes whose result depends on the step.
//
// AGE CONTRACT: life_clock (game seconds lived) is the truth of the age; age_years and life_stage derive from it.
// At creation call NpcLaws::set_age(); a state with life_clock == 0 and age_years > 0 is reconciled by
// reconcile_age() (the declared age wins ONLY in that never-initialised case). enforce_d10() must be called at load and
// after every application of T_step writes of the model: need_intimacy is 0 for a real age below kAdultAgeYears.
//
// KNOWN GAPS (backlog in catalogue/ETAT.md, T21): no death or damage by thirst, hunger, cold, heat, old age (only
// danger flags, and death by blood < 40 % or breath 0); `alive` is written by step() on those two causes only; no law
// for r_obligation, r_rivalry, b_importance (they have a T_step rate but the catalogue words no engine drift);
// illnesses, immunities, pregnancy, fecundity, height, body_mass, wounds, permanent_marks left to T34. Time constants come from
// WorldClock / LifeClock; the T_step caps (`rate` per game day) are READ from the generated catalogue tables.
// T21b: EVERY numeric parameter of the laws (rates per hour, half-lives, fractions, thresholds) is a variable of the
// catalogue (catalogue/data/laws.toml, generated into laws_gen.h as gen::kLaws) and npc_laws.cpp reads it at compile time;
// only the physics and the time of the world (WorldClock, LifeClock, ln 2) stay constants of the code. The table
// "variable -> law" is the catalogue's too: a law that lists the variable, or the variable's `no_law_reason`.
#pragma once
#include <array>
#include <cstdint>
#include <span>
#include <string_view>
#include <vector>

#include "emergence/social/clock.h"
#include "emergence/social/npc_state_gen.h"
#include "emergence/social/state_types.h"

namespace em::social {

// What the NPC is doing to its body this tick: a FACT supplied by the executor of gestures (never a judgement).
enum class Exertion : std::uint8_t { kSleeping, kLyingAwake, kStanding, kWalking, kRunning, kHeavyWork };

// The physical surroundings and facts of the tick (all objective, none is a decision).
struct LawEnvironment {
  GameTime now = 0;                         // game seconds at the END of the tick
  Exertion exertion = Exertion::kStanding;
  std::int32_t load_permille = 0;           // load carried / capacity, x1000 (load_ratio)
  std::int32_t air_milli_c = 20'000;        // air temperature, milli-degrees Celsius
  std::int32_t insulation_permille = 0;     // warmth of the clothing, 0..1000
  bool night = false;
  bool sheltered = true;                    // under a roof or in a shelter
  bool alone = false;                       // nobody within earshot
  bool conversing = false;                  // talking with someone (objective count)
  bool restrained = false;                  // held, tied or locked up
  bool repetitive = false;                  // same places, same gestures (objective count)
  bool asphyxiating = false;                // under water, in smoke, throat squeezed
  std::int16_t wound_ache_tenths = 0;       // pain kept up by the open wounds (from the wound list)
  std::int16_t open_bleeding_tenths = 0;    // bleeding of the open wounds (from the wound list)
};

enum class LifeStage : std::uint8_t { kInfant, kChild, kTeen, kAdult, kElder };   // value order of life_stage

enum class DeathCause : std::uint8_t { kNone, kBlood, kAsphyxia };

// Danger flags: facts for the engine and the executor, not orders.
namespace danger {
inline constexpr std::uint32_t kCold = 1, kHeat = 2, kFamine = 4, kBloodLow = 8, kNoBreath = 16, kDehydrated = 32;
}

struct LawReport {
  bool died = false;
  bool refused = false;   // dt was not a multiple of kTickS: nothing was done
  DeathCause cause = DeathCause::kNone;
  std::uint32_t danger = 0;
};

// One line of the table "variable -> law": every variable written by the engine has a law or the mention "no law".
struct LawInfo {
  std::string_view variable;
  std::string_view law;      // name of the law; empty = no law
  std::string_view note;     // what the law does, or why there is none
};

class NpcLaws {
 public:
  static constexpr std::int64_t kTickS = WorldClock::kGamePerReal;   // THE step of the engine: 16 game s = 1 real s
  static constexpr std::int64_t kSlowCadenceS = 86'400;        // the slow laws (attitudes, memories, mastery) run once per game day
  static constexpr std::int64_t kGraceSinceContactS = WorldClock::kRealSecondsPerYear * WorldClock::kGamePerReal;   // one calendar year

  // Fractional parts kept between ticks (one per NPC; saved with the NPC, otherwise at most one unit is lost).
  struct Residue {
    static constexpr int kSlots = 96;
    std::array<std::int32_t, kSlots> micro{};              // millionths of a stored unit
    std::array<std::int32_t, 32> practice_micro{};         // by technique
    std::int64_t breath_zero_s = 0;
    std::int64_t slow_elapsed_s = 0;
    bool operator==(const Residue&) const = default;
  };

  // Advances the NPC by dt game seconds, a multiple of kTickS (else refused). A dead NPC is not touched.
  static LawReport step(gen::NpcState& npc, Residue& res, const LawEnvironment& env, std::int64_t dt_s);

  // Facts reported by the executor of gestures, with their own laws.
  // Practice: mastery rises with the seconds practised, faster in front of a master who shows and corrects.
  static void practice(gen::Skill& skill, Residue& res, GameTime now, std::int64_t seconds, bool master_watching);
  // Time spent together and exchanges: familiarity rises (it only falls, slowly, without contact).
  static void spend_time_together(gen::Relation& rel, GameTime now, std::int64_t seconds, int exchanges);

  // Age contract (see above). set_age: life_clock, age_years, life_stage, senescence from an age in tenths of years.
  static void set_age(gen::NpcState& npc, std::int32_t age_tenths);
  static void reconcile_age(gen::NpcState& npc);
  // Real age in tenths of years (from life_clock, reconciled first).
  static std::int32_t real_age_tenths(gen::NpcState& npc);
  // D10: need_intimacy = 0 below the adult age. True if something was reset.
  static bool enforce_d10(gen::NpcState& npc);

  // Save/load of the residues: section LAWS (v1), one residue per NPC in the order of the NPCS section.
  static constexpr std::uint32_t kTagLaws = 'L' | 'A' << 8 | 'W' << 16 | 'S' << 24;
  static std::vector<std::uint8_t> save_residues(std::span<const Residue* const> residues);
  // False (and `out` unchanged) if the section is malformed, has the wrong CRC or another NPC count.
  static bool load_residues(std::span<const std::uint8_t> section, std::vector<Residue>& out, std::size_t expected_npcs);

  // The slow laws on their own (called by step() once per game day of elapsed time; public for tests).
  static void slow_pass(gen::NpcState& npc, GameTime now, int days);

  // The table "variable -> law" (every variable of the catalogue written by `engine`).
  static std::vector<LawInfo> law_table();
  static LawInfo law_for(std::string_view variable);
};

}  // namespace em::social
