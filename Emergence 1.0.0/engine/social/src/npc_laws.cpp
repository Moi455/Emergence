// T21: laws of the body and of the mind applied by the engine (see npc_laws.h). Integer arithmetic only.
#include "emergence/social/npc_laws.h"

#include <algorithm>
#include <cstdlib>

#include "emergence/social/catalogue_gen.h"
#include "emergence/social/laws_gen.h"
#include "emergence/social/npc_state_codec.h"

namespace em::social {
namespace {

using Body = gen::Body;
constexpr std::int64_t kMicro = 1'000'000;
constexpr std::int64_t kHourS = 3'600;
constexpr std::int64_t kDayS = WorldClock::kGameSecondsPerDay;

// A duration given in REAL seconds, as the catalogue words it ("tens of seconds real"), in game seconds.
constexpr std::int64_t real_s(std::int64_t s) { return s * WorldClock::kGamePerReal; }

// ---------------------------------------------------------------------------------------------------------------
// The parameters of the laws (T21b). EVERY rate, half-life, fraction and threshold is a variable of the catalogue
// (catalogue/data/laws.toml, generated into laws_gen.h: gen::kLaws): none is written here. A parameter the catalogue does
// not declare is a COMPILE error (gen::law_param is not constexpr when it is missing). Rates are in thousandths of a
// stored unit per game hour (tenths of the charter scale for the 0..10 variables: 9'000 = 0.9 point per game hour).
// What stays in the code, on purpose: the physics and the time of the world (WorldClock: 1 real s = 16 game s, the day, the
// calendar year; LifeClock: the bounds of the ages; ln 2 for the half-lives; the scales 0..100 and permille), and the
// SHAPE of each law (which facts it reads, in which order), documented in the catalogue by `form`, `depends_on`, `reads`.
// ---------------------------------------------------------------------------------------------------------------
constexpr std::int64_t P(std::string_view law, std::string_view name) { return gen::law_param(law, name); }
constexpr std::int32_t P32(std::string_view law, std::string_view name) { return static_cast<std::int32_t>(gen::law_param(law, name)); }
constexpr std::int64_t game_h(std::string_view law, std::string_view name) { return P(law, name) * kHourS; }
constexpr std::int64_t real_of(std::string_view law, std::string_view name) { return real_s(P(law, name)); }
// A half-life or a time constant, in game seconds, whatever unit the catalogue words it in (its name says it).
constexpr std::int64_t life_s(std::string_view law) {
  if (gen::find_law_param(law, "half_life_real_s")) return real_of(law, "half_life_real_s");
  if (gen::find_law_param(law, "half_life_game_h")) return game_h(law, "half_life_game_h");
  return P(law, "half_life_game_s");
}

constexpr int kExertions = 6;   // sleeping, lying awake, standing, walking, running, heavy work (the order of Exertion)
constexpr auto kHungerRate = gen::law_exertion<kExertions>("hunger_rise");
constexpr std::int64_t kLoadHungerDivisor = P("hunger_rise", "load_divisor");   // permille of load / n added to the hunger rate
constexpr auto kThirstRate = gen::law_exertion<kExertions>("thirst_rise");
constexpr std::int32_t kHotAboveMilliC = P32("thirst_rise", "hot_above_milli_c"), kHotPermillePerDegree = P32("thirst_rise", "hot_permille_per_degree"),
                       kHotMaxPermille = P32("thirst_rise", "hot_max_permille");
constexpr std::int64_t kFamineHunger = P("reserves_fast", "famine_hunger"), kFedHunger = P("reserves_fast", "fed_hunger"),
                       kThirstCritical = P("reserves_fast", "thirst_critical");
constexpr std::int64_t kReservesFallRate = P("reserves_fast", "fall_rate"), kReservesRiseRate = P("reserves_fast", "rise_rate");
constexpr auto kExhaustionTargetWide = gen::law_exertion<kExertions>("exhaustion_relax");   // tenths
constexpr std::int64_t kExhaustionRiseTauS = game_h("exhaustion_relax", "rise_tau_game_h"), kExhaustionFallTauS = P("exhaustion_relax", "fall_tau_game_s");
constexpr std::int32_t kLoadExhaustionDivisor = P32("exhaustion_relax", "load_divisor");   // tenths added to the target per permille/n
constexpr std::int64_t kEnduranceBasePermille = P("exhaustion_relax", "endurance_base_permille"), kEndurancePerPointPermille = P("exhaustion_relax", "endurance_per_point_permille");
constexpr std::int64_t kSleepyAwakeRate = P("sleep_debt", "awake_rate");           // per game hour awake
constexpr std::int32_t kSleepyNightPermille = P32("sleep_debt", "night_permille");
constexpr std::int32_t kSleepyPerExhaustionPermille = P32("sleep_debt", "per_exhaustion_permille");   // per tenth of exhaustion
constexpr std::int64_t kSleepyDuringSleep = P("sleep_debt", "during_sleep_rate");
constexpr std::int64_t kSleepyLyingAwake = P("sleep_debt", "lying_awake_rate");
constexpr auto kEffortHeat = gen::law_exertion<kExertions>("body_temperature_follow");   // milli-degrees
constexpr std::int32_t kBodyTempMilliC = P32("body_temperature_follow", "body_milli_c"), kComfortAirMilliC = P32("body_temperature_follow", "comfort_air_milli_c"),
                       kTempGainPermille = P32("body_temperature_follow", "gain_permille");
constexpr std::int64_t kBodyTempTauS = game_h("body_temperature_follow", "tau_game_h");
constexpr std::int32_t kBodyTempMinMilliC = P32("body_temperature_follow", "min_milli_c"), kBodyTempMaxMilliC = P32("body_temperature_follow", "max_milli_c");
constexpr std::int32_t kColdDanger = P32("body_temperature_follow", "cold_danger_milli_c"), kHeatDanger = P32("body_temperature_follow", "heat_danger_milli_c");
constexpr std::int32_t kComfortMilliCPerTenth = P32("thermal_comfort_derived", "milli_c_per_tenth");   // 3 degrees = the whole scale
constexpr std::int64_t kPainTauS = real_of("pain_fade", "tau_real_s");
constexpr std::int64_t kBleedingTauS = real_of("bleeding_clot", "tau_real_s");
constexpr std::int64_t kBloodLossPerBleedTenth = P("blood_balance", "loss_per_bleed_tenth");   // thousandths of milli-percent per hour, per tenth of bleeding
constexpr std::int64_t kBloodRegen = P("blood_balance", "regen");
constexpr std::int32_t kBloodFull = P32("blood_balance", "full_milli_pct"), kBloodWeak = P32("blood_balance", "weak_milli_pct");   // milli-percent
constexpr std::int32_t kBloodDeath = P32("death_thresholds", "blood_milli_pct");
constexpr std::int64_t kAsphyxiaDeathS = P("death_thresholds", "breath_zero_game_s");
constexpr std::int64_t kBreathLossRate = P("breath_balance", "loss_rate");
constexpr std::int64_t kBreathTauS = real_of("breath_balance", "tau_real_s");
constexpr std::int64_t kBreathLow = P("breath_balance", "low_below");
constexpr std::int64_t kConsciousnessDownTauS = P("consciousness_follow", "down_tau_game_s"), kConsciousnessUpTauS = P("consciousness_follow", "up_tau_game_s");
constexpr std::int32_t kSleepConsciousness = P32("consciousness_follow", "sleep_level");
constexpr std::int64_t kConsIntoxDivisor = P("consciousness_follow", "intoxication_divisor"), kConsPainOnset = P("consciousness_follow", "pain_onset"),
                       kConsPainWeight = P("consciousness_follow", "pain_weight"), kConsBloodDivisor = P("consciousness_follow", "blood_divisor"),
                       kConsBreathFactor = P("consciousness_follow", "breath_factor");
constexpr std::int64_t kIntoxicationFall = P("intoxication_wear_off", "fall_rate");
constexpr std::int64_t kDeclinePerAgeTenthMilli = P("ageing_decline", "decline_per_age_tenth_milli");   // thousandths of a stored unit lost per tenth of a year of age at full senescence
constexpr std::int32_t kSenescenceFromAgeTenths = P32("senescence_derived", "from_age_tenths"), kSenescenceFullAgeTenths = P32("senescence_derived", "full_age_tenths");
constexpr std::int64_t kFamineCollapseRate = P("famine_collapse", "rate");
constexpr std::int64_t kStressRisePerPoint = P("stress_balance", "rise_per_point");
constexpr std::int64_t kStressFearFloor = P("stress_balance", "fear_floor"), kStressEmotionDivisor = P("stress_balance", "emotion_divisor");
constexpr std::int64_t kStressHungerOnset = P("stress_balance", "hunger_onset"), kStressThirstOnset = P("stress_balance", "thirst_onset"),
                       kStressSleepOnset = P("stress_balance", "sleepiness_onset");
constexpr std::int64_t kStressDrainSleep = P("stress_balance", "drain_sleep"), kStressDrainTalk = P("stress_balance", "drain_talk"), kStressDrainRest = P("stress_balance", "drain_rest");
constexpr std::int64_t kMoodTauS = game_h("mood_average", "tau_game_h"), kMoodGoodDivisor = P("mood_average", "good_divisor"), kMoodBadDivisor = P("mood_average", "bad_divisor");
constexpr std::int64_t kEnergyTauS = game_h("mood_energy_derived", "tau_game_h"), kEnergyBase = P("mood_energy_derived", "base"),
                       kEnergyEmotionDivisor = P("mood_energy_derived", "emotion_divisor"), kEnergySleepDivisor = P("mood_energy_derived", "sleepiness_divisor"),
                       kEnergyHungerDivisor = P("mood_energy_derived", "hunger_divisor"), kEnergyIntoxDivisor = P("mood_energy_derived", "intoxication_divisor");
constexpr std::int64_t kMobBase = P("mobility_derived", "base"), kMobExhaustionWeight = P("mobility_derived", "exhaustion_weight"),
                       kMobLoadOver = P("mobility_derived", "load_over_permille"), kMobLoadDivisor = P("mobility_derived", "load_divisor"),
                       kMobPainOnset = P("mobility_derived", "pain_onset"), kMobPainWeight = P("mobility_derived", "pain_weight"),
                       kMobIntoxWeight = P("mobility_derived", "intoxication_weight");
constexpr std::int64_t kManBase = P("manipulation_derived", "base"), kManPainOnset = P("manipulation_derived", "pain_onset"),
                       kManPainWeight = P("manipulation_derived", "pain_weight"), kManIntoxWeight = P("manipulation_derived", "intoxication_weight"),
                       kManColdBelow = P("manipulation_derived", "cold_below_milli_c"), kManColdDivisor = P("manipulation_derived", "cold_divisor");

// Emotions: half-life of the return (game seconds) and the target kind (the SHAPE stays here, the numbers are the catalogue's).
// The catalogue words the pace: "tens of seconds real" (fear), "ten seconds real" (surprise), "minutes real" (anger, confusion),
// "slowly" (anxiety, sadness, shame, guilt), "very slowly, days of game" (grief). Emotions without words use emotion_generic.
// The pace of the temperament (emotion_pace): the half-life is divided by (base + per_point x resilience) / 1000.
constexpr std::int64_t kEmotionPaceBase = P("emotion_pace", "base_permille"), kEmotionPacePerResilience = P("emotion_pace", "per_resilience_permille");
enum class EmoTarget : std::uint8_t { kZero, kJoyBase, kSadBase, kFear, kAnxiety, kAnger, kConfusion, kBoredom };
struct EmoLaw {
  std::string_view name;
  std::int16_t gen::MindDynamic::* field;
  std::int64_t half_life_s;
  EmoTarget target;
};
constexpr std::int64_t kGenericHalfLifeS = life_s("emotion_generic");
constexpr std::int64_t kFearPainAbove = P("emotion_fear", "pain_above"), kFearPainDivisor = P("emotion_fear", "pain_divisor");
constexpr std::int64_t kAnxPainAbove = P("emotion_anxiety", "pain_above"), kAnxPainDivisor = P("emotion_anxiety", "pain_divisor"), kAnxSicknessDivisor = P("emotion_anxiety", "sickness_divisor");
constexpr std::int64_t kAngerCap = P("emotion_anger", "cap"), kAngerPainAbove = P("emotion_anger", "pain_above"), kAngerPainDivisor = P("emotion_anger", "pain_divisor"),
                       kAngerHungerAbove = P("emotion_anger", "hunger_above"), kAngerHungerDivisor = P("emotion_anger", "hunger_divisor"),
                       kAngerSleepAbove = P("emotion_anger", "sleepiness_above"), kAngerSleepDivisor = P("emotion_anger", "sleepiness_divisor"),
                       kAngerIntoxDivisor = P("emotion_anger", "intoxication_divisor");
constexpr std::int64_t kConfCap = P("emotion_confusion", "cap"), kConfIntoxDivisor = P("emotion_confusion", "intoxication_divisor"),
                       kConfFeverAbove = P("emotion_confusion", "fever_above_milli_c"), kConfFeverDivisor = P("emotion_confusion", "fever_divisor"),
                       kConfConsciousnessDivisor = P("emotion_confusion", "consciousness_divisor");
constexpr std::int64_t kBoredomLevel = P("emotion_boredom", "level");
constexpr auto kEmotions = std::to_array<EmoLaw>({
    {"fear", &gen::MindDynamic::fear, life_s("emotion_fear"), EmoTarget::kFear},
    {"anxiety", &gen::MindDynamic::anxiety, life_s("emotion_anxiety"), EmoTarget::kAnxiety},
    {"anger", &gen::MindDynamic::anger, life_s("emotion_anger"), EmoTarget::kAnger},
    {"joy", &gen::MindDynamic::joy, life_s("emotion_joy"), EmoTarget::kJoyBase},
    {"sadness", &gen::MindDynamic::sadness, life_s("emotion_sadness"), EmoTarget::kSadBase},
    {"grief", &gen::MindDynamic::grief, life_s("emotion_grief"), EmoTarget::kZero},
    {"disgust", &gen::MindDynamic::disgust, life_s("emotion_disgust"), EmoTarget::kZero},
    {"surprise", &gen::MindDynamic::surprise, life_s("emotion_surprise"), EmoTarget::kZero},
    {"shame", &gen::MindDynamic::shame, life_s("emotion_shame"), EmoTarget::kZero},
    {"guilt", &gen::MindDynamic::guilt, life_s("emotion_guilt"), EmoTarget::kZero},
    {"pride", &gen::MindDynamic::pride, kGenericHalfLifeS, EmoTarget::kZero},
    {"jealousy", &gen::MindDynamic::jealousy, kGenericHalfLifeS, EmoTarget::kZero},
    {"envy", &gen::MindDynamic::envy, kGenericHalfLifeS, EmoTarget::kZero},
    {"tenderness", &gen::MindDynamic::tenderness, kGenericHalfLifeS, EmoTarget::kZero},
    {"gratitude", &gen::MindDynamic::gratitude, kGenericHalfLifeS, EmoTarget::kZero},
    {"contempt", &gen::MindDynamic::contempt, kGenericHalfLifeS, EmoTarget::kZero},
    {"boredom", &gen::MindDynamic::boredom, life_s("emotion_boredom"), EmoTarget::kBoredom},
    {"confusion", &gen::MindDynamic::confusion, life_s("emotion_confusion"), EmoTarget::kConfusion},
});

// Psychological drives: the engine moves them by a fraction of the T_step `rate` of the variable (per game day).
enum class DriveKind : std::uint8_t { kCompany, kIntimacy, kEsteem, kAutonomy, kAchievement, kNovelty, kSecurity, kAcquisition, kPlay, kMeaning };
struct DriveLaw {
  std::string_view name;
  std::int16_t gen::MindDynamic::* field;
  DriveKind kind;
};
constexpr auto kDrives = std::to_array<DriveLaw>({
    {"need_company", &gen::MindDynamic::need_company, DriveKind::kCompany},
    {"need_intimacy", &gen::MindDynamic::need_intimacy, DriveKind::kIntimacy},
    {"need_esteem", &gen::MindDynamic::need_esteem, DriveKind::kEsteem},
    {"need_autonomy", &gen::MindDynamic::need_autonomy, DriveKind::kAutonomy},
    {"need_achievement", &gen::MindDynamic::need_achievement, DriveKind::kAchievement},
    {"need_novelty", &gen::MindDynamic::need_novelty, DriveKind::kNovelty},
    {"need_security", &gen::MindDynamic::need_security, DriveKind::kSecurity},
    {"need_acquisition", &gen::MindDynamic::need_acquisition, DriveKind::kAcquisition},
    {"need_play", &gen::MindDynamic::need_play, DriveKind::kPlay},
    {"need_meaning", &gen::MindDynamic::need_meaning, DriveKind::kMeaning},
});
constexpr std::int64_t kSelfRegardPermille = P("drift_to_trait", "permille");
constexpr std::int64_t kCompanyConvTarget = P("drive_company", "conversing_target"), kCompanyConvPermille = P("drive_company", "conversing_permille"),
                       kCompanyAloneTarget = P("drive_company", "alone_target"), kCompanyAloneBase = P("drive_company", "alone_base_permille"),
                       kCompanyAlonePerSoc = P("drive_company", "alone_per_sociability"), kCompanyAloneCap = P("drive_company", "alone_cap_permille");
constexpr std::int64_t kIntimacyTarget = P("drive_intimacy", "target"), kIntimacyPermille = P("drive_intimacy", "permille");
constexpr std::int64_t kEsteemTarget = P("drive_esteem", "target"), kEsteemPermille = P("drive_esteem", "permille");
constexpr std::int64_t kAutoRestrainedTarget = P("drive_autonomy", "restrained_target"), kAutoRestrainedPermille = P("drive_autonomy", "restrained_permille"),
                       kAutoFreeTarget = P("drive_autonomy", "free_target"), kAutoFreePermille = P("drive_autonomy", "free_permille");
constexpr std::int64_t kAchievementTarget = P("drive_achievement", "target"), kAchievementPermille = P("drive_achievement", "permille");
constexpr std::int64_t kNoveltyRepTarget = P("drive_novelty", "repetitive_target"), kNoveltyRepBase = P("drive_novelty", "repetitive_base_permille"),
                       kNoveltyRepPerInq = P("drive_novelty", "repetitive_per_inquisitiveness"), kNoveltyRepCap = P("drive_novelty", "repetitive_cap_permille"),
                       kNoveltyCalmTarget = P("drive_novelty", "calm_target"), kNoveltyCalmPermille = P("drive_novelty", "calm_permille");
constexpr std::int64_t kSecNeedTarget = P("drive_security", "need_target"), kSecNeedPermille = P("drive_security", "need_permille"),
                       kSecCalmTarget = P("drive_security", "calm_target"), kSecCalmPermille = P("drive_security", "calm_permille"),
                       kSecHungerOnset = P("drive_security", "hunger_onset"), kSecThirstOnset = P("drive_security", "thirst_onset"),
                       kSecDiscomfortOnset = P("drive_security", "discomfort_onset"), kSecPainOnset = P("drive_security", "pain_onset");
constexpr std::int64_t kAcquisitionCeiling = P("drive_acquisition", "ceiling"), kAcquisitionPermille = P("drive_acquisition", "permille");
constexpr std::int64_t kPlayWorkTarget = P("drive_play", "working_target"), kPlayWorkPermille = P("drive_play", "working_permille"),
                       kPlayIdleTarget = P("drive_play", "idle_target"), kPlayIdlePermille = P("drive_play", "idle_permille");
constexpr std::int64_t kMeaningTarget = P("drive_meaning", "target"), kMeaningPermille = P("drive_meaning", "permille");

// Residue slots.
enum Slot : int {
  kSHunger, kSThirst, kSReserves, kSExhaustion, kSSleepiness, kSBodyTemp, kSPain, kSBleeding, kSBlood, kSBreath,
  kSConsciousness, kSIntox, kSMoodValence, kSMoodEnergy, kSStress, kSSelfRegard, kSStrength, kSEndurance, kSAgility,
  kSVision, kSFamineStrength, kSFamineRobust, kSBody = 24,
  kSEmotion = 24, kSDrive = 48, kSEnd = 58
};
static_assert(kSEmotion + int(kEmotions.size()) <= kSDrive);
static_assert(kSDrive + int(kDrives.size()) <= kSEnd && kSEnd <= NpcLaws::Residue::kSlots);

// ---------------------------------------------------------------------------------------------------------------
// Arithmetic helpers
// ---------------------------------------------------------------------------------------------------------------
std::int64_t clamp64(std::int64_t v, std::int64_t lo, std::int64_t hi) { return v < lo ? lo : (v > hi ? hi : v); }

// Adds a signed amount in millionths of a unit to a stored field, keeping the fraction in `resid`.
template <class T>
void nudge(T& field, std::int32_t& resid, std::int64_t micro, std::int64_t lo, std::int64_t hi) {
  const std::int64_t acc = std::int64_t(resid) + micro;
  const std::int64_t whole = acc / kMicro;   // truncation toward zero: symmetric for rises and falls
  std::int64_t v = std::int64_t(field) + whole;
  std::int64_t rest = acc - whole * kMicro;
  if (v <= lo) { v = lo; if (rest < 0) rest = 0; }
  if (v >= hi) { v = hi; if (rest > 0) rest = 0; }
  field = static_cast<T>(v);
  resid = static_cast<std::int32_t>(rest);
}
// Rate in thousandths of a unit per game hour over dt seconds, in millionths of a unit.
std::int64_t by_rate(std::int64_t rate_milli_per_hour, std::int64_t dt) { return rate_milli_per_hour * dt * 5 / 18; }
// First-order return toward a target with time constant tau.
std::int64_t toward(std::int64_t value, std::int64_t target, std::int64_t tau_s, std::int64_t dt) {
  const std::int64_t gap = (target - value) * kMicro;
  return dt >= tau_s ? gap : gap * dt / tau_s;
}
// Exponential return with a half-life: ln 2 = 0.693.
std::int64_t toward_half(std::int64_t value, std::int64_t target, std::int64_t half_life_s, std::int64_t dt) {
  const std::int64_t gap = (target - value) * kMicro;
  const std::int64_t part = gap * 693 / 1000 * dt / half_life_s;
  return std::abs(part) > std::abs(gap) ? gap : part;
}

int var_index(std::string_view id) {
  for (std::size_t i = 0; i < gen::kVarNames.size(); ++i)
    if (gen::kVarNames[i] == id) return int(i);
  return -1;
}
// The T_step cap `rate` of a variable, in tenths per game day, READ from the generated catalogue.
std::int64_t cap_tenths_per_day(std::string_view id) {
  const int i = var_index(id);
  return i < 0 ? 0 : gen::kVariables[std::size_t(i)].rate_tenths;
}

// Moves a stored value toward `target` by at most `permille`/1000 of the T_step cap of the variable, per game day.
void drift(std::int16_t& field, std::int32_t& resid, std::string_view id, std::int64_t target, std::int64_t permille, std::int64_t dt,
           std::int64_t lo = 0, std::int64_t hi = 100) {
  const std::int64_t step = cap_tenths_per_day(id) * kMicro * dt / kDayS * permille / 1000;
  const std::int64_t gap = (target - field) * kMicro - resid;
  nudge(field, resid, clamp64(gap, -step, step), lo, hi);
}

std::int64_t pos(std::int64_t v) { return v > 0 ? v : 0; }

// ---------------------------------------------------------------------------------------------------------------
// One slice of at most kSubstepS seconds.
// ---------------------------------------------------------------------------------------------------------------
void body_slice(gen::NpcState& n, NpcLaws::Residue& r, const LawEnvironment& env, std::int64_t dt, LawReport& rep) {
  auto& b = n.body;
  auto& nd = n.needs;
  auto& md = n.mind_dynamic;
  const int ex = int(env.exertion);
  const bool asleep = env.exertion == Exertion::kSleeping;
  const bool lying = env.exertion == Exertion::kLyingAwake;
  auto& m = r.micro;

  // Hunger and thirst: with the effort, the load, the heat.
  std::int64_t hunger = kHungerRate[ex];
  if (env.exertion == Exertion::kWalking || env.exertion == Exertion::kRunning) hunger = hunger * (1'000 + env.load_permille / kLoadHungerDivisor) / 1'000;
  std::int64_t thirst = kThirstRate[ex];
  if (env.air_milli_c > kHotAboveMilliC)
    thirst = thirst * std::min<std::int64_t>(kHotMaxPermille, 1'000 + (env.air_milli_c - kHotAboveMilliC) / 1'000 * kHotPermillePerDegree) / 1'000;
  nudge(nd.hunger, m[kSHunger], by_rate(hunger, dt), 0, 100);
  nudge(nd.thirst, m[kSThirst], by_rate(thirst, dt), 0, 100);

  // Reserves: fall in prolonged fasting, rise back when fed.
  if (nd.hunger >= kFamineHunger) nudge(nd.reserves, m[kSReserves], by_rate(-kReservesFallRate, dt), 0, 100);
  else if (nd.hunger <= kFedHunger && nd.thirst < kThirstCritical) nudge(nd.reserves, m[kSReserves], by_rate(kReservesRiseRate, dt), 0, 100);

  // Exhaustion: toward the level of the effort (load and endurance weigh on it), faster down than up.
  std::int64_t target = kExhaustionTargetWide[ex];
  if (target > 0) {
    target += (env.exertion == Exertion::kStanding ? 0 : env.load_permille / kLoadExhaustionDivisor);
    target = target * (kEnduranceBasePermille - kEndurancePerPointPermille * b.endurance) / 1'000;
  }
  target = clamp64(target, 0, 100);
  nudge(nd.exhaustion, m[kSExhaustion], toward(nd.exhaustion, target, target > nd.exhaustion ? kExhaustionRiseTauS : kExhaustionFallTauS, dt), 0, 100);

  // Sleep debt: only sleep repays it.
  std::int64_t sleepy;
  if (asleep) sleepy = kSleepyDuringSleep;
  else if (lying) sleepy = kSleepyLyingAwake;
  else {
    sleepy = kSleepyAwakeRate * (1'000 + nd.exhaustion * kSleepyPerExhaustionPermille) / 1'000;
    if (env.night) sleepy = sleepy * kSleepyNightPermille / 1'000;
  }
  nudge(nd.sleepiness, m[kSSleepiness], by_rate(sleepy, dt), 0, 100);

  // Temperature of the body: follows the air through the clothing and the effort; derived comfort.
  std::int64_t air_gap = (env.air_milli_c - kComfortAirMilliC) * kTempGainPermille / 1'000;
  const std::int64_t ins = clamp64(env.insulation_permille, 0, 1'000);
  air_gap = air_gap < 0 ? air_gap * (1'000 - ins) / 1'000 : air_gap * (1'000 + ins) / 1'000;
  const std::int64_t temp_target = kBodyTempMilliC + air_gap + kEffortHeat[ex];
  nudge(b.body_temperature, m[kSBodyTemp], toward(b.body_temperature, clamp64(temp_target, kBodyTempMinMilliC, kBodyTempMaxMilliC), kBodyTempTauS, dt), kBodyTempMinMilliC, kBodyTempMaxMilliC);
  nd.thermal_comfort = std::int16_t(clamp64((std::int64_t(b.body_temperature) - kBodyTempMilliC) / kComfortMilliCPerTenth, -100, 100));

  // Pain and bleeding: the wounds keep a part, the rest fades.
  nudge(b.pain, m[kSPain], toward(b.pain, std::max<std::int64_t>(env.wound_ache_tenths, 0), kPainTauS, dt), 0, 100);
  nudge(b.bleeding, m[kSBleeding], toward(b.bleeding, std::max<std::int64_t>(env.open_bleeding_tenths, 0), kBleedingTauS, dt), 0, 100);

  // Blood: lost with the bleeding, slowly regained when nothing bleeds and the reserves allow.
  if (b.bleeding > 0) nudge(b.blood_volume, m[kSBlood], by_rate(-kBloodLossPerBleedTenth * b.bleeding, dt), 0, kBloodFull);
  else if (nd.reserves > 0) nudge(b.blood_volume, m[kSBlood], by_rate(kBloodRegen, dt), 0, kBloodFull);

  // Breath.
  if (env.asphyxiating) nudge(b.breath, m[kSBreath], by_rate(-kBreathLossRate, dt), 0, 100);
  else nudge(b.breath, m[kSBreath], toward(b.breath, 100, kBreathTauS, dt), 0, 100);
  r.breath_zero_s = b.breath == 0 ? r.breath_zero_s + dt : 0;

  // Intoxication wears off in hours.
  nudge(b.intoxication, m[kSIntox], by_rate(-kIntoxicationFall, dt), 0, 100);

  // Consciousness: what the body allows (sleep, blood, pain, drug, breath).
  std::int64_t cons = asleep ? kSleepConsciousness : 100;
  cons -= b.intoxication / kConsIntoxDivisor;
  cons -= pos(b.pain - kConsPainOnset) * kConsPainWeight;
  if (b.blood_volume < kBloodWeak) cons -= (kBloodWeak - b.blood_volume) / kConsBloodDivisor;
  if (b.breath < kBreathLow) cons = std::min<std::int64_t>(cons, b.breath * kConsBreathFactor);
  cons = clamp64(cons, 0, 100);
  nudge(b.consciousness, m[kSConsciousness], toward(b.consciousness, cons, cons < b.consciousness ? kConsciousnessDownTauS : kConsciousnessUpTauS, dt), 0, 100);

  // Famine: strength and robustness collapse while the reserves are empty (5 tenths per game day).
  if (nd.reserves == 0) {
    nudge(b.strength, m[kSFamineStrength], by_rate(-kFamineCollapseRate, dt), 0, 100);
    nudge(b.robustness, m[kSFamineRobust], by_rate(-kFamineCollapseRate, dt), 0, 100);
  }

  // Emotions return toward the baseline mood at the pace of the temperament; the body weighs on some of them.
  const std::int64_t speed = kEmotionPaceBase + kEmotionPacePerResilience * n.mind_static.resilience;   // permille
  const std::int64_t base = n.mind_static.baseline_mood;
  for (std::size_t i = 0; i < kEmotions.size(); ++i) {
    const EmoLaw& e = kEmotions[i];
    std::int16_t& v = md.*(e.field);
    std::int64_t t = 0;
    switch (e.target) {
      case EmoTarget::kZero: break;
      case EmoTarget::kJoyBase: t = pos(base); break;
      case EmoTarget::kSadBase: t = pos(-base); break;
      case EmoTarget::kFear: t = pos(b.pain - kFearPainAbove) / kFearPainDivisor; break;
      case EmoTarget::kAnxiety: t = pos(b.pain - kAnxPainAbove) / kAnxPainDivisor + b.sickness_felt / kAnxSicknessDivisor; break;
      case EmoTarget::kAnger:
        t = std::min<std::int64_t>(kAngerCap, pos(b.pain - kAngerPainAbove) / kAngerPainDivisor + pos(nd.hunger - kAngerHungerAbove) / kAngerHungerDivisor +
                                          pos(nd.sleepiness - kAngerSleepAbove) / kAngerSleepDivisor + b.intoxication / kAngerIntoxDivisor);
        break;
      case EmoTarget::kConfusion:
        t = std::min<std::int64_t>(kConfCap, b.intoxication / kConfIntoxDivisor + pos(b.body_temperature - kConfFeverAbove) / kConfFeverDivisor +
                                          (100 - b.consciousness) / kConfConsciousnessDivisor);
        break;
      case EmoTarget::kBoredom: t = (env.repetitive || lying || env.exertion == Exertion::kStanding) ? kBoredomLevel : 0; break;
    }
    t = std::min<std::int64_t>(t, 100);
    nudge(v, m[kSEmotion + int(i)], toward_half(v, t, e.half_life_s * 1'000 / speed, dt), 0, 100);
  }

  // Mood, energy, tension (derived from the state; the engine keeps them current).
  {
    const std::int64_t good = (md.joy + md.tenderness + md.gratitude + md.pride) / kMoodGoodDivisor;
    const std::int64_t bad = (md.fear + md.anger + md.sadness + md.grief + md.shame + md.guilt) / kMoodBadDivisor;
    nudge(md.mood_valence, m[kSMoodValence], toward(md.mood_valence, clamp64(base + good - bad, -100, 100), kMoodTauS, dt), -100, 100);
    const std::int64_t energy = kEnergyBase + (md.joy + md.anger + md.fear) / kEnergyEmotionDivisor - nd.sleepiness / kEnergySleepDivisor -
                                nd.hunger / kEnergyHungerDivisor - b.intoxication / kEnergyIntoxDivisor;
    nudge(md.mood_energy, m[kSMoodEnergy], toward(md.mood_energy, clamp64(energy, 0, 100), kEnergyTauS, dt), 0, 100);
    std::int64_t stress = pos((md.fear + md.anxiety + md.anger) / kStressEmotionDivisor - kStressFearFloor) * kStressRisePerPoint +
                          (pos(nd.hunger - kStressHungerOnset) + pos(nd.thirst - kStressThirstOnset) + pos(nd.sleepiness - kStressSleepOnset)) * kStressRisePerPoint;
    if (asleep) stress -= kStressDrainSleep;
    else if (lying) stress -= kStressDrainRest;
    if (env.conversing) stress -= kStressDrainTalk;
    nudge(md.stress, m[kSStress], by_rate(stress, dt), 0, 100);
  }

  // Drives: a fraction of the T_step cap of each variable, per game day.
  const bool awake = !asleep;
  const bool working = env.exertion == Exertion::kHeavyWork;
  const bool body_need = nd.hunger >= kSecHungerOnset || nd.thirst >= kSecThirstOnset || std::abs(nd.thermal_comfort) >= kSecDiscomfortOnset || b.pain >= kSecPainOnset ||
                         (env.night && !env.sheltered);
  const auto& ms = n.mind_static;
  for (std::size_t i = 0; i < kDrives.size(); ++i) {
    const DriveLaw& d = kDrives[i];
    std::int16_t& v = md.*(d.field);
    std::int32_t& res = m[kSDrive + int(i)];
    switch (d.kind) {
      case DriveKind::kCompany:
        if (env.conversing) drift(v, res, d.name, kCompanyConvTarget, kCompanyConvPermille, dt);
        else if (env.alone) drift(v, res, d.name, kCompanyAloneTarget, std::min<std::int64_t>(kCompanyAloneCap, kCompanyAloneBase + kCompanyAlonePerSoc * ms.sociability), dt);
        break;
      case DriveKind::kIntimacy:
        if (NpcLaws::real_age_tenths(n) < gen::kAdultAgeYears * 10) { v = 0; res = 0; }   // D10: nothing before the adult age
        else drift(v, res, d.name, kIntimacyTarget, kIntimacyPermille, dt);
        break;
      case DriveKind::kEsteem: drift(v, res, d.name, kEsteemTarget, kEsteemPermille, dt); break;
      case DriveKind::kAutonomy: env.restrained ? drift(v, res, d.name, kAutoRestrainedTarget, kAutoRestrainedPermille, dt) : drift(v, res, d.name, kAutoFreeTarget, kAutoFreePermille, dt); break;
      case DriveKind::kAchievement: if (awake && !working) drift(v, res, d.name, kAchievementTarget, kAchievementPermille, dt); break;
      case DriveKind::kNovelty:
        env.repetitive ? drift(v, res, d.name, kNoveltyRepTarget, std::min<std::int64_t>(kNoveltyRepCap, kNoveltyRepBase + kNoveltyRepPerInq * ms.inquisitiveness), dt)
                       : drift(v, res, d.name, kNoveltyCalmTarget, kNoveltyCalmPermille, dt);
        break;
      case DriveKind::kSecurity: body_need ? drift(v, res, d.name, kSecNeedTarget, kSecNeedPermille, dt) : drift(v, res, d.name, kSecCalmTarget, kSecCalmPermille, dt); break;
      case DriveKind::kAcquisition: drift(v, res, d.name, kAcquisitionCeiling - ms.greed_avoidance, kAcquisitionPermille, dt); break;
      case DriveKind::kPlay:
        if (working) drift(v, res, d.name, kPlayWorkTarget, kPlayWorkPermille, dt);
        else if (awake) drift(v, res, d.name, kPlayIdleTarget, kPlayIdlePermille, dt);
        break;
      case DriveKind::kMeaning: drift(v, res, d.name, kMeaningTarget, kMeaningPermille, dt); break;
    }
  }
  drift(md.self_regard, m[kSSelfRegard], "self_regard", ms.assurance, kSelfRegardPermille, dt, -100, 100);

  // Derived capacities of the body (the wounds of the limbs are in the wound list, not read here).
  b.mobility = std::int16_t(clamp64(kMobBase - nd.exhaustion * kMobExhaustionWeight - pos(env.load_permille - kMobLoadOver) / kMobLoadDivisor -
                                    pos(b.pain - kMobPainOnset) * kMobPainWeight - b.intoxication * kMobIntoxWeight, 0, 1'000));
  b.manipulation = std::int16_t(clamp64(kManBase - pos(b.pain - kManPainOnset) * kManPainWeight - b.intoxication * kManIntoxWeight -
                                        pos(kManColdBelow - env.air_milli_c) / kManColdDivisor, 0, 1'000));

  // Facts for the engine.
  if (b.body_temperature < kColdDanger) rep.danger |= danger::kCold;
  if (b.body_temperature > kHeatDanger) rep.danger |= danger::kHeat;
  if (nd.reserves == 0) rep.danger |= danger::kFamine;
  if (nd.thirst >= kThirstCritical) rep.danger |= danger::kDehydrated;
  if (b.blood_volume < kBloodWeak) rep.danger |= danger::kBloodLow;
  if (b.breath < kBreathLow) rep.danger |= danger::kNoBreath;
  // Death follows from the body (body.toml): blood below 40 %, breath at zero for too long.
  if (b.blood_volume < kBloodDeath) { rep.died = true; rep.cause = DeathCause::kBlood; }
  else if (r.breath_zero_s >= kAsphyxiaDeathS) { rep.died = true; rep.cause = DeathCause::kAsphyxia; }
  if (rep.died) b.alive = false;
}

// Stage boundaries (tenths of years): adult from kAdultAgeYears (generated), teen and elder from the LifeClock stages (the
// time of the world, code); the end of infancy (3 years) is the catalogue's (law life_stage_threshold).
constexpr std::int32_t kInfantEndTenths = P32("life_stage_threshold", "infant_end_tenths");
constexpr std::int32_t kTeenStartTenths = LifeClock::kStages[0].to_tenths, kElderStartTenths = LifeClock::kStages[2].to_tenths;
static_assert(LifeClock::kStages[1].to_tenths == gen::kAdultAgeYears * 10, "the LifeClock adulthood must start at the D10 age");
LifeStage stage_of(std::int32_t age) {
  return age < kInfantEndTenths ? LifeStage::kInfant : age < kTeenStartTenths ? LifeStage::kChild
       : age < gen::kAdultAgeYears * 10 ? LifeStage::kTeen : age < kElderStartTenths ? LifeStage::kAdult : LifeStage::kElder;
}
std::int32_t senescence_of(std::int32_t age) {
  return std::int32_t(clamp64((std::int64_t(age) - kSenescenceFromAgeTenths) * 100 / (kSenescenceFullAgeTenths - kSenescenceFromAgeTenths), 0, 100));
}
// Inverse of LifeClock::age_tenths: the smallest real seconds lived that give this age.
std::int64_t lived_real_for(std::int32_t age) {
  std::int64_t r = 0;
  for (const auto& st : LifeClock::kStages) {
    if (age < st.to_tenths) return r + std::int64_t(age - st.from_tenths) * st.real_seconds / (st.to_tenths - st.from_tenths) + 1;
    r += st.real_seconds;
  }
  return r;
}

// Ageing on the LifeClock: life_clock holds the game seconds lived.
void ageing_slice(gen::NpcState& n, NpcLaws::Residue& r, std::int64_t dt) {
  auto& l = n.lifecycle;
  l.life_clock += dt;
  const std::int64_t lived_real = std::int64_t(GameTime(l.life_clock)) / WorldClock::kGamePerReal;
  const std::int32_t age = LifeClock::age_tenths(lived_real);
  l.age_years = age * 100;   // milli-years
  l.life_stage = std::uint8_t(stage_of(age));
  l.senescence = std::int16_t(senescence_of(age));
  if (l.senescence > 0) {   // the declines follow the age gained in this slice, scaled by the senescence
    // age gained in this slice, in millionths of tenths of years, from the rate of the current stage
    std::int64_t gained = 0;
    for (const auto& st : LifeClock::kStages)
      if (age >= st.from_tenths && age <= st.to_tenths) {
        gained = std::int64_t(st.to_tenths - st.from_tenths) * kMicro * dt / (st.real_seconds * WorldClock::kGamePerReal);
        break;
      }
    const std::int64_t loss = gained * kDeclinePerAgeTenthMilli / 1'000 * l.senescence / 100;
    nudge(n.body.strength, r.micro[kSStrength], -loss, 0, 100);
    nudge(n.body.endurance, r.micro[kSEndurance], -loss, 0, 100);
    nudge(n.body.agility, r.micro[kSAgility], -loss, 0, 100);
    nudge(n.body.vision, r.micro[kSVision], -loss, 0, 100);
  }
}

// ---------------------------------------------------------------------------------------------------------------
// Slow laws, once per game day: attitudes, memories, mastery.
// ---------------------------------------------------------------------------------------------------------------
std::int64_t days_since(GameTime now, GameTime then) { return then >= now ? 0 : (now - then) / kDayS; }

// Moves toward zero by the larger of one tenth and the exponential share of the half-life (in game days).
void fade_to_zero(std::int16_t& v, std::int64_t half_life_days, int days) {
  for (int d = 0; d < days && v != 0; ++d) {
    const std::int64_t share = std::abs(std::int64_t(v)) * 693 / 1000 / std::max<std::int64_t>(half_life_days, 1);
    const std::int64_t step = std::max<std::int64_t>(1, share);
    v = std::int16_t(v > 0 ? std::max<std::int64_t>(0, v - step) : std::min<std::int64_t>(0, v + step));
  }
}

constexpr std::int64_t kYearDays = WorldClock::kRealSecondsPerYear * WorldClock::kGamePerReal / kDayS;   // calendar year in game days (4): the time of the world, code
constexpr std::int64_t kAttitudeHalfLifeYears = P("attitude_fade", "half_life_years"), kResentmentHalfLifeYears = P("resentment_fade", "half_life_years"),
                       kFamiliarityHalfLifeYears = P("familiarity_balance", "half_life_years");
constexpr std::int64_t kResentBasePermille = P("resentment_fade", "forgiveness_base_permille"), kResentPerPointPermille = P("resentment_fade", "forgiveness_per_point_permille");
constexpr std::int64_t kFearHalfLifeDays = P("fear_fade", "half_life_game_days");
constexpr std::int64_t kMemoryHalfLifeDays = P("memory_fade", "half_life_game_days");
constexpr std::int64_t kMemCapBasePermille = P("memory_fade", "capacity_base_permille"), kMemCapPerPointPermille = P("memory_fade", "capacity_per_point_permille"),
                       kMemRehearsalCap = P("memory_fade", "rehearsal_cap_permille");
constexpr std::int64_t kPracticeGraceDays = P("mastery_practice", "grace_game_days");
constexpr std::int64_t kPracticeRate = P("mastery_practice", "rate");   // thousandths of a tenth of mastery per game hour of practice
constexpr std::int64_t kMasterWatchingPermille = P("mastery_practice", "master_watching_permille");
constexpr std::int64_t kMasteryCeiling = P("mastery_practice", "ceiling"), kMasteryDecayPerDay = P("mastery_practice", "decay_per_day");
constexpr std::int64_t kFamiliaritySecondsPerTenth = P("familiarity_balance", "seconds_per_tenth"), kFamiliarityPerExchange = P("familiarity_balance", "per_exchange");

}  // namespace

// ---------------------------------------------------------------------------------------------------------------
LawReport NpcLaws::step(gen::NpcState& npc, Residue& res, const LawEnvironment& env, std::int64_t dt_s) {
  LawReport rep;
  if (!npc.body.alive) { rep.died = true; return rep; }
  if (dt_s <= 0 || dt_s % kTickS != 0) { rep.refused = dt_s != 0; return rep; }
  std::int64_t left = dt_s;
  while (left > 0 && npc.body.alive) {
    left -= kTickS;
    ageing_slice(npc, res, kTickS);
    body_slice(npc, res, env, kTickS, rep);
    res.slow_elapsed_s += kTickS;
    if (res.slow_elapsed_s >= kSlowCadenceS) {   // inside the loop: the result does not depend on how ticks are grouped in calls
      const int days = int(res.slow_elapsed_s / kSlowCadenceS);
      res.slow_elapsed_s -= std::int64_t(days) * kSlowCadenceS;
      slow_pass(npc, env.now - left, days);
    }
  }
  if (!npc.body.alive) rep.died = true;
  return rep;
}

void NpcLaws::set_age(gen::NpcState& npc, std::int32_t age_tenths) {
  auto& l = npc.lifecycle;
  l.life_clock = GameTime(lived_real_for(std::max(age_tenths, 0)) * WorldClock::kGamePerReal);
  l.age_years = LifeClock::age_tenths(std::int64_t(GameTime(l.life_clock)) / WorldClock::kGamePerReal) * 100;
  l.life_stage = std::uint8_t(stage_of(l.age_years / 100));
  l.senescence = std::int16_t(senescence_of(l.age_years / 100));
}
void NpcLaws::reconcile_age(gen::NpcState& npc) {
  auto& l = npc.lifecycle;
  if (GameTime(l.life_clock) == 0 && l.age_years > 0) { set_age(npc, l.age_years / 100); return; }   // never initialised: the declared age
  const std::int32_t age = LifeClock::age_tenths(std::int64_t(GameTime(l.life_clock)) / WorldClock::kGamePerReal);
  l.age_years = age * 100;
  l.life_stage = std::uint8_t(stage_of(age));
  l.senescence = std::int16_t(senescence_of(age));
}
std::int32_t NpcLaws::real_age_tenths(gen::NpcState& npc) {
  reconcile_age(npc);
  return npc.lifecycle.age_years / 100;
}
bool NpcLaws::enforce_d10(gen::NpcState& npc) {
  if (real_age_tenths(npc) >= gen::kAdultAgeYears * 10 || npc.mind_dynamic.need_intimacy == 0) return false;
  npc.mind_dynamic.need_intimacy = 0;
  return true;
}

std::vector<std::uint8_t> NpcLaws::save_residues(std::span<const Residue* const> residues) {
  std::vector<std::uint8_t> b;
  auto put = [&](std::uint64_t v, int n) { for (int i = 0; i < n; ++i) b.push_back(std::uint8_t(v >> (8 * i))); };
  put(residues.size(), 4);
  for (const Residue* r : residues) {
    for (auto v : r->micro) put(std::uint32_t(v), 4);
    for (auto v : r->practice_micro) put(std::uint32_t(v), 4);
    put(std::uint64_t(r->breath_zero_s), 8);
    put(std::uint64_t(r->slow_elapsed_s), 8);
  }
  return NpcStateCodec::wrap_section(kTagLaws, NpcStateCodec::kVersion, b);
}

bool NpcLaws::load_residues(std::span<const std::uint8_t> section, std::vector<Residue>& out, std::size_t expected_npcs) {
  std::span<const std::uint8_t> p;
  if (NpcStateCodec::unwrap_section(section, kTagLaws, p) != Refusal::None) return false;
  constexpr std::size_t kOne = (Residue::kSlots + 32) * 4 + 16;
  if (p.size() < 4) return false;
  std::size_t pos = 0;
  auto get = [&](int n) { std::uint64_t v = 0; for (int i = 0; i < n; ++i) v |= std::uint64_t(p[pos++]) << (8 * i); return v; };
  const std::uint64_t count = get(4);
  if (count != expected_npcs || p.size() != 4 + count * kOne) return false;
  std::vector<Residue> tmp(count);
  for (Residue& r : tmp) {
    for (auto& v : r.micro) v = std::int32_t(std::uint32_t(get(4)));
    for (auto& v : r.practice_micro) v = std::int32_t(std::uint32_t(get(4)));
    r.breath_zero_s = std::int64_t(get(8));
    r.slow_elapsed_s = std::int64_t(get(8));
    for (auto v : r.micro) if (v <= -1'000'000 || v >= 1'000'000) return false;   // a residue is a fraction of a unit
  }
  out = std::move(tmp);
  return true;
}

void NpcLaws::slow_pass(gen::NpcState& npc, GameTime now, int days) {
  const std::int64_t forgiv = npc.mind_static.forgiveness;
  const std::int64_t memcap = npc.mind_static.memory_capacity;
  npc.relation_records.for_each([&](MRef, gen::Relation& r) {
    const std::int64_t quiet = days_since(now, GameTime(r.r_last_contact));
    if (r.r_fear != 0) fade_to_zero(r.r_fear, kFearHalfLifeDays, days);
    if (GameTime(r.r_last_contact) == 0 || quiet * kDayS < kGraceSinceContactS) return;   // "years without contact"
    for (std::int16_t* a : {&r.r_affection, &r.r_trust, &r.r_respect, &r.r_attraction}) fade_to_zero(*a, kAttitudeHalfLifeYears * kYearDays, days);
    // The less inclined to forgive, the slower the resentment fades.
    fade_to_zero(r.r_resentment, kResentmentHalfLifeYears * kYearDays * (kResentBasePermille - kResentPerPointPermille * forgiv) / 1'000, days);
    fade_to_zero(r.r_familiarity, kFamiliarityHalfLifeYears * kYearDays, days);
  });
  npc.episode_records.for_each([&](MRef, gen::Episode& e) {
    if (e.m_defining) return;
    const std::int64_t rehearsed = std::min<std::int64_t>(kMemRehearsalCap, e.m_rehearsals);
    const std::int64_t hl = kMemoryHalfLifeDays * (kMemCapBasePermille + kMemCapPerPointPermille * memcap) / 1'000 * (1'000 + rehearsed) / 1'000;
    fade_to_zero(e.m_vividness, std::max<std::int64_t>(hl, 1), days);
  });
  npc.skill_records.for_each([&](MRef, gen::Skill& k) {
    if (days_since(now, GameTime(k.k_last_practice)) > kPracticeGraceDays && k.k_mastery > 0) k.k_mastery = std::int16_t(k.k_mastery - std::min<std::int64_t>(days * kMasteryDecayPerDay, k.k_mastery));
  });
}

void NpcLaws::practice(gen::Skill& skill, Residue& res, GameTime now, std::int64_t seconds, bool master_watching) {
  if (seconds <= 0) return;
  std::int64_t rate = kPracticeRate * (kMasteryCeiling - skill.k_mastery) / kMasteryCeiling;   // diminishing returns near the top
  if (master_watching) rate = rate * kMasterWatchingPermille / 1'000;
  nudge(skill.k_mastery, res.practice_micro[skill.k_technique & 31], by_rate(rate, seconds), 0, 100);
  skill.k_last_practice = now;
}

void NpcLaws::spend_time_together(gen::Relation& rel, GameTime now, std::int64_t seconds, int exchanges) {
  const std::int64_t gain = seconds / kFamiliaritySecondsPerTenth + exchanges * kFamiliarityPerExchange;   // one tenth per half game hour together, one per exchange
  rel.r_familiarity = std::int16_t(std::min<std::int64_t>(100, rel.r_familiarity + gain));
  rel.r_last_contact = now;
}

// ---------------------------------------------------------------------------------------------------------------
// The table "variable -> law".
// ---------------------------------------------------------------------------------------------------------------
// The table "variable -> law" comes from the catalogue (gen::kLaws, gen::kNoLaw): a law that writes the variable, or the
// reason why there is none (the variable's `no_law_reason`). A variable in neither is a gap that tools/laws.py refuses.
LawInfo NpcLaws::law_for(std::string_view variable) {
  if (const gen::LawSpec* l = gen::law_of(variable)) return {variable, l->id, l->note};
  if (const gen::NoLawSpec* n = gen::no_law_of(variable)) return {variable, {}, n->reason};
  return {variable, {}, "undeclared: neither a law nor a no_law_reason in the catalogue"};
}

std::vector<LawInfo> NpcLaws::law_table() {
  std::vector<LawInfo> t;
  for (std::size_t i = 0; i < gen::kVariables.size(); ++i) {
    const auto& v = gen::kVariables[i];
    if (v.retired || !(v.writers & gen::writer::engine)) continue;
    t.push_back(law_for(v.id));
  }
  return t;
}

}  // namespace em::social
