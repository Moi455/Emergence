// T21: laws of the body and of the mind applied by the engine (see npc_laws.h). Integer arithmetic only.
#include "emergence/social/npc_laws.h"

#include <algorithm>
#include <cstdlib>

#include "emergence/social/catalogue_gen.h"
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
// The parameters of the body laws. Rates are in thousandths of a stored unit per game hour (tenths of the charter
// scale for the 0..10 variables: 9'000 = 0.9 point per game hour). Rhythm of D30: about three meals and one sleep of
// about 8 h per game day (16 h of day, 8 h of night).
// ---------------------------------------------------------------------------------------------------------------
constexpr int kExertions = 6;   // sleeping, lying awake, standing, walking, running, heavy work
constexpr std::array<std::int64_t, kExertions> kHungerRate = {2'000, 3'500, 4'500, 9'000, 14'000, 11'000};
constexpr std::array<std::int64_t, kExertions> kThirstRate = {4'000, 8'000, 9'000, 16'000, 26'000, 20'000};
constexpr std::array<std::int32_t, kExertions> kExhaustionTarget = {0, 0, 5, 50, 95, 70};   // tenths
constexpr std::array<std::int32_t, kExertions> kEffortHeat = {-200, 0, 100, 300, 1'000, 700};   // milli-degrees
constexpr std::int64_t kExhaustionRiseTauS = kHourS;
constexpr std::int64_t kExhaustionFallTauS = kHourS / 2;   // a few real minutes
constexpr std::int64_t kSleepyAwakeRate = 4'500;           // per game hour awake
constexpr std::int32_t kSleepyNightPermille = 1'300;
constexpr std::int32_t kSleepyPerExhaustionPermille = 2;   // per tenth of exhaustion
constexpr std::int64_t kSleepyDuringSleep = -12'000;
constexpr std::int64_t kSleepyLyingAwake = -1'500;
constexpr std::int32_t kHotAboveMilliC = 25'000, kHotPermillePerDegree = 50, kHotMaxPermille = 2'000;
constexpr std::int32_t kLoadHungerDivisor = 4;             // permille of load / 4 added to the hunger rate
constexpr std::int32_t kLoadExhaustionDivisor = 20;        // tenths added to the exhaustion target per permille/20
constexpr std::int64_t kFamineHunger = 80, kFedHunger = 40, kThirstCritical = 90;
constexpr std::int64_t kReservesFallRate = 1'667;          // 4 points per game day while starving
constexpr std::int64_t kReservesRiseRate = 833;            // 2 points per game day when fed
constexpr std::int32_t kBodyTempMilliC = 37'000, kComfortAirMilliC = 20'000, kTempGainPermille = 120;
constexpr std::int64_t kBodyTempTauS = 2 * kHourS;
constexpr std::int32_t kColdDanger = 33'000, kHeatDanger = 41'000;
constexpr std::int32_t kComfortMilliCPerTenth = 30;        // 3 degrees = the whole scale
constexpr std::int64_t kPainTauS = real_s(120);
constexpr std::int64_t kBleedingTauS = real_s(60);
constexpr std::int64_t kBloodLossPerBleedTenth = 300'000;  // thousandths of milli-percent per hour, per tenth of bleeding
constexpr std::int64_t kBloodRegen = 1'000'000;            // 1 % per game hour
constexpr std::int32_t kBloodFull = 100'000, kBloodWeak = 60'000, kBloodDeath = 40'000;   // milli-percent
constexpr std::int64_t kBreathLossRate = 562'500;          // the whole scale in 640 game seconds (40 s real)
constexpr std::int64_t kBreathTauS = real_s(4);
constexpr std::int64_t kAsphyxiaDeathS = 180;
constexpr std::int64_t kConsciousnessDownTauS = 120, kConsciousnessUpTauS = 600;
constexpr std::int32_t kSleepConsciousness = 20;
constexpr std::int64_t kIntoxicationFall = 15'000;         // 1.5 points per game hour
constexpr std::int64_t kDeclinePerAgeTenthMilli = 25;      // thousandths of a stored unit lost per tenth of a year of age at full senescence
constexpr std::int32_t kSenescenceFromAgeTenths = 400, kSenescenceFullAgeTenths = 750;
constexpr std::int64_t kStressDrainSleep = 6'000, kStressDrainTalk = 2'000, kStressDrainRest = 1'500;
constexpr std::int64_t kStressRisePerPoint = 60;
constexpr std::int64_t kFamineCollapseRate = 208;          // 5 tenths per game day while the reserves are empty

// Emotions: half-life of the return (game seconds) and the target kind. The catalogue words the pace: "tens of seconds
// real" (fear), "ten seconds real" (surprise), "minutes real" (anger, confusion), "slowly" (anxiety, sadness, shame,
// guilt), "very slowly, days of game" (grief). Emotions without words use the generic pace (six game hours).
enum class EmoTarget : std::uint8_t { kZero, kJoyBase, kSadBase, kFear, kAnxiety, kAnger, kConfusion, kBoredom };
struct EmoLaw {
  std::string_view name;
  std::int16_t gen::MindDynamic::* field;
  std::int64_t half_life_s;
  EmoTarget target;
};
constexpr std::int64_t kGenericHalfLifeS = 6 * kHourS;
constexpr auto kEmotions = std::to_array<EmoLaw>({
    {"fear", &gen::MindDynamic::fear, real_s(30), EmoTarget::kFear},
    {"anxiety", &gen::MindDynamic::anxiety, 6 * kHourS, EmoTarget::kAnxiety},
    {"anger", &gen::MindDynamic::anger, real_s(180), EmoTarget::kAnger},
    {"joy", &gen::MindDynamic::joy, 3 * kHourS, EmoTarget::kJoyBase},
    {"sadness", &gen::MindDynamic::sadness, 12 * kHourS, EmoTarget::kSadBase},
    {"grief", &gen::MindDynamic::grief, 72 * kHourS, EmoTarget::kZero},
    {"disgust", &gen::MindDynamic::disgust, real_s(60), EmoTarget::kZero},
    {"surprise", &gen::MindDynamic::surprise, real_s(10), EmoTarget::kZero},
    {"shame", &gen::MindDynamic::shame, 12 * kHourS, EmoTarget::kZero},
    {"guilt", &gen::MindDynamic::guilt, 24 * kHourS, EmoTarget::kZero},
    {"pride", &gen::MindDynamic::pride, kGenericHalfLifeS, EmoTarget::kZero},
    {"jealousy", &gen::MindDynamic::jealousy, kGenericHalfLifeS, EmoTarget::kZero},
    {"envy", &gen::MindDynamic::envy, kGenericHalfLifeS, EmoTarget::kZero},
    {"tenderness", &gen::MindDynamic::tenderness, kGenericHalfLifeS, EmoTarget::kZero},
    {"gratitude", &gen::MindDynamic::gratitude, kGenericHalfLifeS, EmoTarget::kZero},
    {"contempt", &gen::MindDynamic::contempt, kGenericHalfLifeS, EmoTarget::kZero},
    {"boredom", &gen::MindDynamic::boredom, 4 * kHourS, EmoTarget::kBoredom},
    {"confusion", &gen::MindDynamic::confusion, real_s(180), EmoTarget::kConfusion},
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
  std::int64_t target = kExhaustionTarget[ex];
  if (target > 0) {
    target += (env.exertion == Exertion::kStanding ? 0 : env.load_permille / kLoadExhaustionDivisor);
    target = target * (1'400 - 6 * b.endurance) / 1'000;
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
  nudge(b.body_temperature, m[kSBodyTemp], toward(b.body_temperature, clamp64(temp_target, 20'000, 45'000), kBodyTempTauS, dt), 20'000, 45'000);
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
  cons -= b.intoxication / 2;
  cons -= pos(b.pain - 80) * 3;
  if (b.blood_volume < kBloodWeak) cons -= (kBloodWeak - b.blood_volume) / 500;
  if (b.breath < 30) cons = std::min<std::int64_t>(cons, b.breath * 2);
  cons = clamp64(cons, 0, 100);
  nudge(b.consciousness, m[kSConsciousness], toward(b.consciousness, cons, cons < b.consciousness ? kConsciousnessDownTauS : kConsciousnessUpTauS, dt), 0, 100);

  // Famine: strength and robustness collapse while the reserves are empty (5 tenths per game day).
  if (nd.reserves == 0) {
    nudge(b.strength, m[kSFamineStrength], by_rate(-kFamineCollapseRate, dt), 0, 100);
    nudge(b.robustness, m[kSFamineRobust], by_rate(-kFamineCollapseRate, dt), 0, 100);
  }

  // Emotions return toward the baseline mood at the pace of the temperament; the body weighs on some of them.
  const std::int64_t speed = 600 + 8 * n.mind_static.resilience;   // permille
  const std::int64_t base = n.mind_static.baseline_mood;
  for (std::size_t i = 0; i < kEmotions.size(); ++i) {
    const EmoLaw& e = kEmotions[i];
    std::int16_t& v = md.*(e.field);
    std::int64_t t = 0;
    switch (e.target) {
      case EmoTarget::kZero: break;
      case EmoTarget::kJoyBase: t = pos(base); break;
      case EmoTarget::kSadBase: t = pos(-base); break;
      case EmoTarget::kFear: t = pos(b.pain - 60) / 2; break;
      case EmoTarget::kAnxiety: t = pos(b.pain - 40) / 3 + b.sickness_felt / 4; break;
      case EmoTarget::kAnger:
        t = std::min<std::int64_t>(40, pos(b.pain - 50) / 4 + pos(nd.hunger - 70) / 3 + pos(nd.sleepiness - 70) / 3 + b.intoxication / 5);
        break;
      case EmoTarget::kConfusion: t = std::min<std::int64_t>(60, b.intoxication / 2 + pos(b.body_temperature - 38'500) / 50 + (100 - b.consciousness) / 2); break;
      case EmoTarget::kBoredom: t = (env.repetitive || lying || env.exertion == Exertion::kStanding) ? 60 : 0; break;
    }
    t = std::min<std::int64_t>(t, 100);
    nudge(v, m[kSEmotion + int(i)], toward_half(v, t, e.half_life_s * 1'000 / speed, dt), 0, 100);
  }

  // Mood, energy, tension (derived from the state; the engine keeps them current).
  {
    const std::int64_t good = (md.joy + md.tenderness + md.gratitude + md.pride) / 4;
    const std::int64_t bad = (md.fear + md.anger + md.sadness + md.grief + md.shame + md.guilt) / 4;
    nudge(md.mood_valence, m[kSMoodValence], toward(md.mood_valence, clamp64(base + good - bad, -100, 100), 3 * kHourS, dt), -100, 100);
    const std::int64_t energy = 50 + (md.joy + md.anger + md.fear) / 3 - nd.sleepiness / 2 - nd.hunger / 5 - b.intoxication / 2;
    nudge(md.mood_energy, m[kSMoodEnergy], toward(md.mood_energy, clamp64(energy, 0, 100), kHourS, dt), 0, 100);
    std::int64_t stress = pos((md.fear + md.anxiety + md.anger) / 3 - 20) * kStressRisePerPoint * 10 +
                          (pos(nd.hunger - 70) + pos(nd.thirst - 70) + pos(nd.sleepiness - 80)) * kStressRisePerPoint * 10;
    if (asleep) stress -= kStressDrainSleep;
    else if (lying) stress -= kStressDrainRest;
    if (env.conversing) stress -= kStressDrainTalk;
    nudge(md.stress, m[kSStress], by_rate(stress, dt), 0, 100);
  }

  // Drives: a fraction of the T_step cap of each variable, per game day.
  const bool awake = !asleep;
  const bool working = env.exertion == Exertion::kHeavyWork;
  const bool body_need = nd.hunger >= 70 || nd.thirst >= 70 || std::abs(nd.thermal_comfort) >= 60 || b.pain >= 50 || (env.night && !env.sheltered);
  const auto& ms = n.mind_static;
  for (std::size_t i = 0; i < kDrives.size(); ++i) {
    const DriveLaw& d = kDrives[i];
    std::int16_t& v = md.*(d.field);
    std::int32_t& res = m[kSDrive + int(i)];
    switch (d.kind) {
      case DriveKind::kCompany:
        if (env.conversing) drift(v, res, d.name, 0, 1'000, dt);
        else if (env.alone) drift(v, res, d.name, 100, std::min<std::int64_t>(1'000, 500 + 5 * ms.sociability), dt);
        break;
      case DriveKind::kIntimacy:
        if (NpcLaws::real_age_tenths(n) < gen::kAdultAgeYears * 10) { v = 0; res = 0; }   // D10: nothing before the adult age
        else drift(v, res, d.name, 50, 300, dt);
        break;
      case DriveKind::kEsteem: drift(v, res, d.name, 100, 200, dt); break;
      case DriveKind::kAutonomy: env.restrained ? drift(v, res, d.name, 100, 1'000, dt) : drift(v, res, d.name, 0, 500, dt); break;
      case DriveKind::kAchievement: if (awake && !working) drift(v, res, d.name, 100, 400, dt); break;
      case DriveKind::kNovelty:
        env.repetitive ? drift(v, res, d.name, 100, std::min<std::int64_t>(1'000, 400 + 4 * ms.inquisitiveness), dt) : drift(v, res, d.name, 0, 600, dt);
        break;
      case DriveKind::kSecurity: body_need ? drift(v, res, d.name, 100, 800, dt) : drift(v, res, d.name, 0, 400, dt); break;
      case DriveKind::kAcquisition: drift(v, res, d.name, 100 - ms.greed_avoidance, 200, dt); break;
      case DriveKind::kPlay:
        if (working) drift(v, res, d.name, 100, 600, dt);
        else if (awake) drift(v, res, d.name, 0, 300, dt);
        break;
      case DriveKind::kMeaning: drift(v, res, d.name, 50, 100, dt); break;
    }
  }
  drift(md.self_regard, m[kSSelfRegard], "self_regard", ms.assurance, 300, dt, -100, 100);

  // Derived capacities of the body (the wounds of the limbs are in the wound list, not read here).
  b.mobility = std::int16_t(clamp64(1'000 - nd.exhaustion * 4 - pos(env.load_permille - 1'000) / 2 - pos(b.pain - 50) * 4 - b.intoxication * 2, 0, 1'000));
  b.manipulation = std::int16_t(clamp64(1'000 - pos(b.pain - 50) * 4 - b.intoxication * 3 - pos(15'000 - env.air_milli_c) / 100, 0, 1'000));

  // Facts for the engine.
  if (b.body_temperature < kColdDanger) rep.danger |= danger::kCold;
  if (b.body_temperature > kHeatDanger) rep.danger |= danger::kHeat;
  if (nd.reserves == 0) rep.danger |= danger::kFamine;
  if (nd.thirst >= kThirstCritical) rep.danger |= danger::kDehydrated;
  if (b.blood_volume < kBloodWeak) rep.danger |= danger::kBloodLow;
  if (b.breath < 30) rep.danger |= danger::kNoBreath;
  // Death follows from the body (body.toml): blood below 40 %, breath at zero for too long.
  if (b.blood_volume < kBloodDeath) { rep.died = true; rep.cause = DeathCause::kBlood; }
  else if (r.breath_zero_s >= kAsphyxiaDeathS) { rep.died = true; rep.cause = DeathCause::kAsphyxia; }
  if (rep.died) b.alive = false;
}

// Stage boundaries (tenths of years): adult from kAdultAgeYears (generated), teen and elder from the LifeClock stages;
// the end of infancy (3 years) is NOT in a generated table yet (backlog: generate it from life_stage).
constexpr std::int32_t kInfantEndTenths = 30;
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

constexpr std::int64_t kYearDays = WorldClock::kRealSecondsPerYear * WorldClock::kGamePerReal / kDayS;   // calendar year in game days (4)
constexpr std::int64_t kAttitudeHalfLifeYears = 2, kResentmentHalfLifeYears = 3, kFamiliarityHalfLifeYears = 4;
constexpr std::int64_t kFearHalfLifeDays = 1;
constexpr std::int64_t kMemoryHalfLifeDays = 6;
constexpr std::int64_t kPracticeGraceDays = 3;
constexpr std::int64_t kPracticeRate = 1'500;          // thousandths of a tenth of mastery per game hour of practice
constexpr std::int64_t kMasterWatchingPermille = 2'000;

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
    fade_to_zero(r.r_resentment, kResentmentHalfLifeYears * kYearDays * (1'500 - 10 * forgiv) / 1'000, days);
    fade_to_zero(r.r_familiarity, kFamiliarityHalfLifeYears * kYearDays, days);
  });
  npc.episode_records.for_each([&](MRef, gen::Episode& e) {
    if (e.m_defining) return;
    const std::int64_t rehearsed = std::min<std::int64_t>(3'000, e.m_rehearsals);
    const std::int64_t hl = kMemoryHalfLifeDays * (500 + 10 * memcap) / 1'000 * (1'000 + rehearsed) / 1'000;
    fade_to_zero(e.m_vividness, std::max<std::int64_t>(hl, 1), days);
  });
  npc.skill_records.for_each([&](MRef, gen::Skill& k) {
    if (days_since(now, GameTime(k.k_last_practice)) > kPracticeGraceDays && k.k_mastery > 0) k.k_mastery = std::int16_t(k.k_mastery - std::min<int>(days, k.k_mastery));
  });
}

void NpcLaws::practice(gen::Skill& skill, Residue& res, GameTime now, std::int64_t seconds, bool master_watching) {
  if (seconds <= 0) return;
  std::int64_t rate = kPracticeRate * (110 - skill.k_mastery) / 110;   // diminishing returns near the top
  if (master_watching) rate = rate * kMasterWatchingPermille / 1'000;
  nudge(skill.k_mastery, res.practice_micro[skill.k_technique & 31], by_rate(rate, seconds), 0, 100);
  skill.k_last_practice = now;
}

void NpcLaws::spend_time_together(gen::Relation& rel, GameTime now, std::int64_t seconds, int exchanges) {
  const std::int64_t gain = seconds / 1'800 + exchanges;   // one tenth per half game hour together, one per exchange
  rel.r_familiarity = std::int16_t(std::min<std::int64_t>(100, rel.r_familiarity + gain));
  rel.r_last_contact = now;
}

// ---------------------------------------------------------------------------------------------------------------
// The table "variable -> law".
// ---------------------------------------------------------------------------------------------------------------
namespace {
struct Explicit { std::string_view id, law, note; };
constexpr auto kLaws = std::to_array<Explicit>({
    {"hunger", "hunger_rise", "rises with time, effort, load; falls only by eating (action)"},
    {"thirst", "thirst_rise", "rises faster in the heat and with the effort; falls only by drinking (action)"},
    {"reserves", "reserves_fast", "falls in prolonged fasting, rises when fed"},
    {"exhaustion", "exhaustion_relax", "toward the level of the effort; recovers in minutes real"},
    {"sleepiness", "sleep_debt", "rises awake (more at night, with exhaustion); only sleep repays it"},
    {"thermal_comfort", "thermal_comfort_derived", "derived from the body temperature"},
    {"body_temperature", "body_temperature_follow", "follows air, clothing insulation and effort; fever needs the illness list (no law yet)"},
    {"pain", "pain_fade", "fades toward the ache kept by the open wounds"},
    {"bleeding", "bleeding_clot", "clots toward the bleeding of the open wounds"},
    {"blood_volume", "blood_balance", "falls with the bleeding, regained slowly; below 40 % death"},
    {"breath", "breath_balance", "falls when asphyxiating, returns otherwise; zero for 180 s kills"},
    {"consciousness", "consciousness_follow", "follows sleep, blood, pain, drug, breath"},
    {"intoxication", "intoxication_wear_off", "wears off in hours"},
    {"strength", "famine_and_ageing", "collapses in famine; declines with senescence"},
    {"endurance", "ageing_decline", "declines with senescence"},
    {"agility", "ageing_decline", "declines with senescence"},
    {"vision", "ageing_decline", "declines with senescence (the eye wound is in the wound list)"},
    {"robustness", "famine_collapse", "collapses in famine"},
    {"mobility", "mobility_derived", "derived from exhaustion, load, pain, drug"},
    {"manipulation", "manipulation_derived", "derived from pain, drug, cold"},
    {"life_clock", "life_clock_advance", "advances with the game time"},
    {"age_years", "life_clock_age", "derived from the life clock (LifeClock)"},
    {"life_stage", "life_clock_stage", "derived from the age: infant < 3, child < 14, teen < 18, adult < 60"},
    {"senescence", "senescence_derived", "derived from the age (40 to 75 years)"},
    {"fear", "emotion_return", "returns toward what the pain keeps up, in tens of seconds real"},
    {"anxiety", "emotion_return", "returns slowly; pain and felt illness keep it up"},
    {"anger", "emotion_return", "returns in minutes real; pain, hunger, lack of sleep, drug push the target up"},
    {"joy", "emotion_return", "returns toward the baseline mood"},
    {"sadness", "emotion_return", "returns slowly toward the baseline mood"},
    {"grief", "emotion_return", "returns very slowly, over days of game"},
    {"disgust", "emotion_return", "returns fast"},
    {"surprise", "emotion_return", "returns in about ten seconds real"},
    {"shame", "emotion_return", "returns slowly"},
    {"guilt", "emotion_return", "returns slowly at the pace of the temperament"},
    {"pride", "emotion_return", "generic pace (the catalogue words none)"},
    {"jealousy", "emotion_return", "generic pace (the catalogue words none)"},
    {"envy", "emotion_return", "generic pace (the catalogue words none)"},
    {"tenderness", "emotion_return", "generic pace (the catalogue words none)"},
    {"gratitude", "emotion_return", "generic pace (the catalogue words none)"},
    {"contempt", "emotion_return", "generic pace (the catalogue words none)"},
    {"boredom", "emotion_return", "rises with repetition and inaction (objective), returns otherwise"},
    {"confusion", "emotion_return", "drug, fever and blows to the head keep it up (the body), returns in minutes real"},
    {"self_regard", "drift_to_trait", "returns slowly toward the trait `assurance`, under the T_step cap"},
    {"need_company", "drive_company", "rises alone (faster if sociable), falls talking; under the T_step cap"},
    {"need_intimacy", "drive_intimacy", "0 before the adult age (D10); slow drift; under the cap"},
    {"need_esteem", "drive_esteem", "slow rise; under the cap"},
    {"need_autonomy", "drive_autonomy", "rises when restrained (physical fact); under the cap"},
    {"need_achievement", "drive_achievement", "rises awake without heavy work; the end of an intention (event) is the model's"},
    {"need_novelty", "drive_novelty", "rises with the routine (faster if inquisitive); under the cap"},
    {"need_security", "drive_security", "the body only: hunger, thirst, cold, pain, no shelter at night; under the cap"},
    {"need_acquisition", "drive_acquisition", "slow drift toward the greed of the trait; under the cap"},
    {"need_play", "drive_play", "rises with the work time; under the cap"},
    {"need_meaning", "drive_meaning", "very slow drift; under the cap"},
    {"mood_valence", "mood_average", "sliding average of the emotions over hours of game, pulled to the baseline"},
    {"mood_energy", "mood_energy_derived", "sleepiness, hunger, drug, emotions"},
    {"stress", "stress_balance", "accumulates while fear, anxiety, anger and unmet needs last; sleep and company drain it"},
    {"r_affection", "attitude_fade", "slow fade toward 0 after a year of calendar without contact"},
    {"r_trust", "attitude_fade", "slow fade toward 0 after a year without contact"},
    {"r_respect", "attitude_fade", "slow fade toward 0 after a year without contact"},
    {"r_attraction", "attitude_fade", "slow fade (D10 is applied by the governor)"},
    {"r_resentment", "attitude_fade", "slower fade the less the person forgives"},
    {"r_fear", "attitude_fade", "falls slowly (half-life one game day)"},
    {"r_familiarity", "familiarity_balance", "rises with time together and exchanges; falls slowly without contact"},
    {"m_vividness", "memory_fade", "falls with time at the pace of the memory trait; rehearsals slow it; defining memories keep it"},
    {"k_mastery", "mastery_practice", "rises with practice, twice as fast in front of a master; falls slowly without practice"},
});
constexpr std::string_view reason_for_holder(std::string_view h) {
  if (h == "belief" || h == "beliefs") return "written by perception/the executor on events (T05/T22), no slow law";
  if (h == "goal" || h == "intention" || h == "request" || h == "agreement_terms") return "execution facts written by the executor (T15/T22), no time law";
  if (h == "episode") return "written when the memory is recorded; only m_vividness has a law";
  if (h == "relation") return "written on events (perception, speech); only attitudes, fear and familiarity have a law";
  if (h == "skill" || h == "trace_record") return "written by the practice or the trace system (T18)";
  if (h == "carrier" || h == "spatial") return "written by the executor of gestures and the navigation (T22/T23)";
  if (h == "lifecycle") return "conception, gestation, birth: laws of life (T34), not the laws of the tick";
  if (h == "body" || h == "mind_static") return "slow or list trait: no law in T21 (needs the side tables or the generated parameters)";
  return "world, matter or society variable: law of another task (T18, T23, T34)";
}
}  // namespace

LawInfo NpcLaws::law_for(std::string_view variable) {
  for (const auto& e : kLaws)
    if (e.id == variable) return {e.id, e.law, e.note};
  const int i = var_index(variable);
  const std::string_view h = i < 0 ? std::string_view{} : gen::kVariables[std::size_t(i)].holder;
  return {variable, {}, reason_for_holder(h)};
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
