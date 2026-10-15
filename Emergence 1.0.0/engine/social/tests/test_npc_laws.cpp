// T21: the laws of the body and of the mind (NpcLaws): the 60 h walk, determinism, caps, granularity, the table.
#include <cstdio>
#include <memory>
#include <set>
#include <string>

#include "emergence/social/catalogue_gen.h"
#include "emergence/social/laws_gen.h"
#include "emergence/social/npc_laws.h"
#include "emergence/social/npc_state_codec.h"
#include "emergence/testing/check.h"

using namespace em::social;

namespace {

int var_index_of(std::string_view id) {
  for (std::size_t i = 0; i < gen::kVarNames.size(); ++i)
    if (gen::kVarNames[i] == id) return int(i);
  return -1;
}

std::unique_ptr<gen::NpcState> make_adult() {
  auto n = std::make_unique<gen::NpcState>();
  n->body.alive = true;
  n->body.blood_volume = 100'000;
  n->body.body_temperature = 37'000;
  n->body.breath = 100;
  n->body.consciousness = 100;
  n->body.strength = 70;
  n->body.endurance = 50;
  n->body.agility = 60;
  n->body.vision = 80;
  n->body.robustness = 60;
  n->needs.reserves = 100;
  n->needs.hunger = 20;
  n->needs.thirst = 20;
  n->mind_static.resilience = 50;
  n->mind_static.assurance = 20;
  n->mind_static.sociability = 50;
  n->mind_static.forgiveness = 50;
  n->mind_static.memory_capacity = 50;
  n->lifecycle.life_clock = GameTime(40LL * 3'600 * WorldClock::kGamePerReal);   // 40 h lived: adult
  return n;
}

// FNV-1a over the fields the laws write (field by field: no padding is read).
struct Hash {
  std::uint64_t h = 1469598103934665603ull;
  void add(std::int64_t v) {
    for (int i = 0; i < 8; ++i) { h ^= std::uint64_t(v >> (8 * i)) & 0xFF; h *= 1099511628211ull; }
  }
};
std::uint64_t fingerprint(const gen::NpcState& n, const NpcLaws::Residue& r) {
  Hash x;
  const auto& b = n.body; const auto& d = n.needs; const auto& m = n.mind_dynamic; const auto& l = n.lifecycle;
  for (std::int64_t v : {std::int64_t(b.blood_volume), std::int64_t(b.body_temperature), std::int64_t(b.pain), std::int64_t(b.bleeding),
                         std::int64_t(b.breath), std::int64_t(b.consciousness), std::int64_t(b.intoxication), std::int64_t(b.strength),
                         std::int64_t(b.endurance), std::int64_t(b.agility), std::int64_t(b.vision), std::int64_t(b.robustness),
                         std::int64_t(b.mobility), std::int64_t(b.manipulation), std::int64_t(b.alive), std::int64_t(d.hunger),
                         std::int64_t(d.thirst), std::int64_t(d.reserves), std::int64_t(d.exhaustion), std::int64_t(d.sleepiness),
                         std::int64_t(d.thermal_comfort), std::int64_t(m.fear), std::int64_t(m.anger), std::int64_t(m.joy),
                         std::int64_t(m.sadness), std::int64_t(m.stress), std::int64_t(m.mood_valence), std::int64_t(m.mood_energy),
                         std::int64_t(m.need_company), std::int64_t(m.need_security), std::int64_t(m.need_novelty),
                         std::int64_t(m.need_play), std::int64_t(m.self_regard), std::int64_t(l.age_years),
                         std::int64_t(l.life_stage), std::int64_t(l.senescence), std::int64_t(GameTime(l.life_clock))})
    x.add(v);
  for (auto v : r.micro) x.add(v);
  x.add(r.slow_elapsed_s);
  return x.h;
}

struct WalkStats {
  int hunger_min = 1000, hunger_max = -1000, thirst_max = 0, sleepy_max = 0, exh_max = 0, exh_min = 1000;
  int meals = 0, drinks = 0, asleep_ticks = 0, temp_min = 100'000, temp_max = 0;
  int reserves_min = 1000;
  bool in_range = true;
  std::uint64_t fp = 0;
};

// The traveller of the seed-1 road: walks all the day, sleeps the whole night (the policy of the MODEL, here a stub),
// eats at hunger 6, drinks at thirst 5. The engine only lets the body live.
WalkStats walk(std::int64_t game_hours, bool never_sleeps, int tick_real_s, bool resume_each_hour = false) {
  auto npc = make_adult();
  NpcLaws::Residue res;
  WorldClock clock;
  WalkStats s;
  const std::int64_t ticks = game_hours * 3'600 / WorldClock::kGamePerReal / tick_real_s;
  for (std::int64_t i = 0; i < ticks; ++i) {
    clock.advance_real(tick_real_s);
    LawEnvironment env;
    env.now = clock.now();
    env.night = clock.night();
    env.exertion = (env.night && !never_sleeps) ? Exertion::kSleeping : Exertion::kWalking;
    env.load_permille = 300;
    env.air_milli_c = 15'000;
    env.insulation_permille = 400;
    env.alone = true;
    env.repetitive = true;
    NpcLaws::step(*npc, res, env, std::int64_t(tick_real_s) * WorldClock::kGamePerReal);
    if (resume_each_hour && (i + 1) * tick_real_s % 225 == 0) {   // every game hour (225 real s): save and reload the residue
      const NpcLaws::Residue* one[] = {&res};
      std::vector<NpcLaws::Residue> back;
      CHECK(NpcLaws::load_residues(NpcLaws::save_residues(one), back, 1));
      res = back[0];
    }
    auto& n = npc->needs;
    if (n.hunger >= 60) { n.hunger = std::int16_t(n.hunger - 50); ++s.meals; }       // the action `eat`
    if (n.thirst >= 50) { n.thirst = std::int16_t(n.thirst - 60 < 0 ? 0 : n.thirst - 60); ++s.drinks; }   // the action `drink`
    if (env.exertion == Exertion::kSleeping) ++s.asleep_ticks;
    s.hunger_min = std::min<int>(s.hunger_min, n.hunger); s.hunger_max = std::max<int>(s.hunger_max, n.hunger);
    s.thirst_max = std::max<int>(s.thirst_max, n.thirst);
    s.sleepy_max = std::max<int>(s.sleepy_max, n.sleepiness);
    s.exh_max = std::max<int>(s.exh_max, n.exhaustion); s.exh_min = std::min<int>(s.exh_min, n.exhaustion);
    s.reserves_min = std::min<int>(s.reserves_min, n.reserves);
    s.temp_min = std::min<int>(s.temp_min, npc->body.body_temperature); s.temp_max = std::max<int>(s.temp_max, npc->body.body_temperature);
    for (int v : {int(n.hunger), int(n.thirst), int(n.sleepiness), int(n.exhaustion), int(n.reserves), int(npc->body.pain), int(npc->mind_dynamic.stress),
                  int(npc->mind_dynamic.fear), int(npc->body.consciousness)})
      if (v < 0 || v > 100) s.in_range = false;
  }
  s.fp = fingerprint(*npc, res);
  return s;
}

}  // namespace

TEST(walk_60_hours) {
  const WalkStats s = walk(60, false, 1);
  const double days = 60.0 / 24.0;
  std::printf("60 h walk: meals %d (%.1f/day), drinks %d (%.1f/day), asleep %.1f h/day (real s counted as game 16 s), hunger %.1f..%.1f, "
              "thirst max %.1f, sleepiness max %.1f, exhaustion %.1f..%.1f, reserves min %.1f, body temp %.2f..%.2f C\n",
              s.meals, s.meals / days, s.drinks, s.drinks / days, s.asleep_ticks * 16.0 / 3600.0 / days, s.hunger_min / 10.0, s.hunger_max / 10.0,
              s.thirst_max / 10.0, s.sleepy_max / 10.0, s.exh_min / 10.0, s.exh_max / 10.0, s.reserves_min / 10.0,
              s.temp_min / 1000.0, s.temp_max / 1000.0);
  CHECK(s.in_range);
  CHECK(s.meals >= 6 && s.meals <= 10);                       // about three meals per game day (2.5 days)
  CHECK(s.drinks >= 8 && s.drinks <= 20);
  CHECK(s.asleep_ticks * 16 >= 2 * 7 * 3'600 && s.asleep_ticks * 16 <= 2 * 9 * 3'600);   // two nights of about 8 h
  CHECK(s.hunger_max < 80 && s.thirst_max < 70);              // no saturation
  CHECK(s.sleepy_max >= 60 && s.sleepy_max < 100);            // a real sleep debt that the night repays, never pinned at 10
  CHECK(s.exh_max >= 30 && s.exh_max <= 80);                  // a walk tires but does not break
  CHECK(s.reserves_min >= 90);
  CHECK(s.temp_min > 35'000 && s.temp_max < 38'500);
}

TEST(no_sleep_saturates_in_range) {
  const WalkStats s = walk(60, true, 1);
  std::printf("60 h walk WITHOUT sleep: sleepiness max %.1f (clamped), in_range=%d\n", s.sleepy_max / 10.0, int(s.in_range));
  CHECK(s.in_range);
  CHECK_EQ(s.sleepy_max, 100);
}

TEST(determinism_and_granularity) {
  const WalkStats a = walk(60, false, 1), b = walk(60, false, 1);
  CHECK_EQ(a.fp, b.fp);
  CHECK_EQ(a.meals, b.meals);
  const WalkStats c = walk(60, false, 30), d = walk(60, false, 30);   // 30 s real = 480 game s per tick
  CHECK_EQ(c.fp, d.fp);
  std::printf("fingerprint 1 s ticks: %016llx ; 30 s ticks: %016llx\n", (unsigned long long)a.fp, (unsigned long long)c.fp);
  CHECK(std::abs(a.meals - c.meals) <= 1);
  CHECK(std::abs(a.drinks - c.drinks) <= 2);
  CHECK_EQ(a.fp, 0xa5e6d02d66f98b7full);   // pinned: the trajectory of the 60 h walk (1 s ticks)
  CHECK_EQ(c.fp, 0x3b8b14f94ea5f026ull);  // pinned: 30 s calls = 30 ticks of 16 s: same law, other decision grain
}

TEST(residue_saved_and_resumed_equals_continuous_run) {
  const WalkStats continuous = walk(60, false, 1), resumed = walk(60, false, 1, true);
  CHECK_EQ(continuous.fp, resumed.fp);
  // the residue is part of the NPC record, absent from an old save: a missing LAWS section means a zero residue
  NpcBundle bundle;
  CHECK(bundle.laws_residue == NpcLaws::Residue{});
  const NpcLaws::Residue* one[] = {&bundle.laws_residue};
  auto sec = NpcLaws::save_residues(one);
  std::vector<NpcLaws::Residue> back;
  CHECK(!NpcLaws::load_residues(sec, back, 2));      // wrong NPC count: refused
  sec[sec.size() - 1] ^= 1;
  CHECK(!NpcLaws::load_residues(sec, back, 1));      // corrupted: refused (CRC)
}

TEST(one_step_only) {
  auto a = make_adult(), b = make_adult(), c = make_adult();
  a->mind_dynamic.fear = 90; b->mind_dynamic.fear = 90; c->mind_dynamic.fear = 90;
  NpcLaws::Residue ra, rb, rc;
  LawEnvironment env; env.now = 1'000'000;
  CHECK(!NpcLaws::step(*a, ra, env, 0).died);
  CHECK(NpcLaws::step(*a, ra, env, 17).refused);               // not a multiple of the tick: refused, untouched
  CHECK_EQ(a->mind_dynamic.fear, 90);
  for (int i = 0; i < 60; ++i) NpcLaws::step(*b, rb, env, 16);   // 60 calls of 1 tick
  NpcLaws::step(*c, rc, env, 960);                                // 1 call of 60 ticks
  CHECK_EQ(b->mind_dynamic.fear, c->mind_dynamic.fear);          // same trajectory whatever the grouping
  CHECK(ra == NpcLaws::Residue{} && rb == rc);
  std::printf("fear 90 after 960 game s: %d (60x16 s = 1x960 s)\n", int(c->mind_dynamic.fear));
}

TEST(d10_and_age_contract) {
  auto adult = make_adult();
  adult->lifecycle.life_clock = GameTime(0);
  adult->lifecycle.age_years = 30'000;                // declared 30 years, clock never initialised
  adult->mind_dynamic.need_intimacy = 40;
  CHECK(!NpcLaws::enforce_d10(*adult));               // reconciled: really an adult, nothing reset
  CHECK_EQ(adult->mind_dynamic.need_intimacy, 40);
  CHECK(NpcLaws::real_age_tenths(*adult) >= 299 && NpcLaws::real_age_tenths(*adult) <= 301);
  NpcLaws::Residue r;
  LawEnvironment env; env.now = 1;
  NpcLaws::step(*adult, r, env, 16);
  CHECK_EQ(adult->lifecycle.life_stage, int(LifeStage::kAdult));
  auto teen = make_adult();
  NpcLaws::set_age(*teen, 150);
  CHECK_EQ(teen->lifecycle.life_stage, int(LifeStage::kTeen));
  teen->mind_dynamic.need_intimacy = 30;              // a T_step write of the model between two ticks
  CHECK(NpcLaws::enforce_d10(*teen));
  CHECK_EQ(teen->mind_dynamic.need_intimacy, 0);
  auto kid = make_adult();
  NpcLaws::set_age(*kid, 179);
  kid->mind_dynamic.need_intimacy = 10;
  CHECK(NpcLaws::enforce_d10(*kid));                  // 17.9 years: still a minor
  NpcLaws::set_age(*kid, 180);
  kid->mind_dynamic.need_intimacy = 10;
  CHECK(!NpcLaws::enforce_d10(*kid));                 // 18.0: adult
}

TEST(drives_never_exceed_the_t_step_cap) {
  auto npc = make_adult();
  NpcLaws::Residue res;
  WorldClock clock;
  const std::int16_t before[] = {npc->mind_dynamic.need_company, npc->mind_dynamic.need_esteem, npc->mind_dynamic.need_novelty,
                                 npc->mind_dynamic.need_security, npc->mind_dynamic.need_play, npc->mind_dynamic.self_regard};
  for (int i = 0; i < 60 * 3'600; ++i) {
    clock.advance_real(1);
    LawEnvironment env; env.now = clock.now(); env.alone = true; env.repetitive = true; env.exertion = Exertion::kHeavyWork;
    NpcLaws::step(*npc, res, env, WorldClock::kGamePerReal);
  }
  const double days = 60.0 * 16 / 24.0;   // 3'600*60 real s = 60 real h = 40 game days
  (void)days;
  const double game_days = 60.0 * 3600 * 16 / 86400.0;
  const auto& m = npc->mind_dynamic;
  const std::int16_t after[] = {m.need_company, m.need_esteem, m.need_novelty, m.need_security, m.need_play, m.self_regard};
  const char* names[] = {"need_company", "need_esteem", "need_novelty", "need_security", "need_play", "self_regard"};
  for (int i = 0; i < 6; ++i) {
    int cap = 0;
    for (std::size_t k = 0; k < gen::kVarNames.size(); ++k) if (gen::kVarNames[k] == names[i]) cap = gen::kVariables[k].rate_tenths;
    CHECK(cap > 0);
    CHECK(std::abs(after[i] - before[i]) <= cap * game_days + 1);
  }
}

TEST(emotions_return_and_minors_have_no_intimacy) {
  auto npc = make_adult();
  NpcLaws::Residue res;
  npc->mind_static.baseline_mood = 30;
  npc->mind_dynamic.fear = 90; npc->mind_dynamic.anger = 80; npc->mind_dynamic.grief = 90; npc->mind_dynamic.surprise = 90;
  WorldClock clock;
  auto run = [&](int real_s) {
    for (int i = 0; i < real_s; ++i) {
      clock.advance_real(1);
      LawEnvironment env; env.now = clock.now(); env.exertion = Exertion::kStanding;
      NpcLaws::step(*npc, res, env, WorldClock::kGamePerReal);
    }
  };
  run(10);
  CHECK(npc->mind_dynamic.surprise < 60);               // ~10 s real half-life
  run(120);
  CHECK(npc->mind_dynamic.fear < 20 && npc->mind_dynamic.surprise <= 2);   // fear gone in minutes real
  CHECK(npc->mind_dynamic.anger < 60 && npc->mind_dynamic.anger > 5);       // anger in minutes real
  CHECK(npc->mind_dynamic.grief > 85);                  // grief lasts days of game
  run(3'600);
  CHECK(npc->mind_dynamic.grief < 80);
  CHECK(npc->mind_dynamic.joy >= 20 && npc->mind_dynamic.joy <= 30);   // returns toward the baseline mood
  auto child = make_adult();
  child->lifecycle.life_clock = GameTime(5LL * 3'600 * WorldClock::kGamePerReal);
  child->mind_dynamic.need_intimacy = 40;
  NpcLaws::Residue r2;
  LawEnvironment env; env.now = 1;
  NpcLaws::step(*child, r2, env, 16);
  CHECK_EQ(child->lifecycle.life_stage, 1);
  CHECK_EQ(child->mind_dynamic.need_intimacy, 0);
}

TEST(blood_pain_and_death) {
  auto npc = make_adult();
  NpcLaws::Residue res;
  npc->body.pain = 80;
  LawEnvironment env; env.now = 1; env.open_bleeding_tenths = 60; env.wound_ache_tenths = 30;
  int ticks = 0;
  LawReport rep;
  while (npc->body.alive && ticks < 100'000) { rep = NpcLaws::step(*npc, res, env, 16); ++ticks; }
  std::printf("bleeding 6.0: dead after %.2f game h (blood floor 40 %%)\n", ticks * 16 / 3600.0);
  CHECK(!npc->body.alive);
  CHECK(rep.died && rep.cause == DeathCause::kBlood);
  CHECK(npc->body.pain < 40);                     // the pain fell toward the ache of the wounds
  auto calm = make_adult();
  NpcLaws::Residue r2;
  LawEnvironment ok; ok.now = 1;
  calm->body.blood_volume = 70'000;
  for (int i = 0; i < 3'600; ++i) NpcLaws::step(*calm, r2, ok, 16);   // 16 game hours without bleeding
  CHECK(calm->body.blood_volume > 80'000 && calm->body.alive);
}

TEST(mastery_faster_with_a_master) {
  gen::Skill a{}, b{};
  NpcLaws::Residue ra, rb;
  for (int i = 0; i < 400; ++i) {
    NpcLaws::practice(a, ra, i * 60, 60, false);
    NpcLaws::practice(b, rb, i * 60, 60, true);
  }
  std::printf("mastery after 400 min: alone %d, with master %d (tenths)\n", a.k_mastery, b.k_mastery);
  CHECK(a.k_mastery > 0);
  CHECK(b.k_mastery > a.k_mastery);
  CHECK(b.k_mastery <= 100);
}

TEST(attitudes_memories_fade_slowly) {
  auto npc = make_adult();
  gen::Relation r{};
  r.r_affection = 60; r.r_resentment = 60; r.r_familiarity = 50; r.r_fear = 40;
  r.r_last_contact = 1;
  const MRef rr = npc->relation_records.add(r, 0);
  gen::Relation q = r;
  const GameTime t0 = 1;
  npc->mind_static.forgiveness = 90;
  NpcLaws::slow_pass(*npc, t0 + 2 * 86'400, 2);    // 2 game days: within the grace, only the fear falls
  CHECK_EQ(npc->relation_records.find(rr)->r_affection, 60);
  CHECK(npc->relation_records.find(rr)->r_fear < 40);
  NpcLaws::slow_pass(*npc, t0 + 20 * 86'400, 5);   // long after the calendar year of silence
  CHECK(npc->relation_records.find(rr)->r_affection < 60);
  CHECK(npc->relation_records.find(rr)->r_resentment < 60);
  auto strict = make_adult();
  strict->mind_static.forgiveness = 5;
  const MRef rs = strict->relation_records.add(q, 0);
  NpcLaws::slow_pass(*strict, t0 + 20 * 86'400, 5);
  CHECK(strict->relation_records.find(rs)->r_resentment > npc->relation_records.find(rr)->r_resentment);   // the less he forgives, the slower
  gen::Episode e{};
  e.m_vividness = 80;
  const MRef er = npc->episode_records.add(e, 0);
  e.m_defining = true;
  const MRef ed = npc->episode_records.add(e, 0);
  NpcLaws::slow_pass(*npc, 10 * 86'400, 5);
  CHECK(npc->episode_records.find(er)->m_vividness < 80);
  CHECK_EQ(npc->episode_records.find(ed)->m_vividness, 80);
}

TEST(law_table_covers_every_engine_variable) {
  int with_law = 0, without = 0;
  std::set<std::string> engine_ids;
  for (std::size_t i = 0; i < gen::kVariables.size(); ++i) {
    const auto& v = gen::kVariables[i];
    if (v.retired || !(v.writers & gen::writer::engine)) continue;
    engine_ids.insert(std::string(v.id));
  }
  const auto table = NpcLaws::law_table();
  CHECK_EQ(table.size(), engine_ids.size());
  for (const auto& e : table) {
    CHECK(!e.note.empty());   // a law, or the stated reason why there is none
    (e.law.empty() ? without : with_law)++;
  }
  // every named law belongs to a real engine variable
  for (const auto& e : table) if (!e.law.empty()) CHECK(engine_ids.count(std::string(e.variable)) == 1);
  std::printf("table variable -> law: %d engine variables, %d with a law, %d 'no law'\n", with_law + without, with_law, without);
  CHECK(with_law >= 55);
  CHECK(NpcLaws::law_for("hunger").law == "hunger_rise");
  CHECK(NpcLaws::law_for("alive").law == "death_thresholds");   // T21b: alive is written by step(), so it has a law
  CHECK(NpcLaws::law_for("world_without_law_xx").law.empty());
}

// T21b: the numbers of the laws are the catalogue's (laws.toml -> gen::kLaws), not constants of the code.
TEST(laws_come_from_the_catalogue) {
  CHECK(gen::kLaws.size() >= 50);
  std::set<std::string> engine_ids;
  for (std::size_t i = 0; i < gen::kVariables.size(); ++i)
    if (!gen::kVariables[i].retired && (gen::kVariables[i].writers & gen::writer::engine)) engine_ids.insert(std::string(gen::kVariables[i].id));
  for (const auto& l : gen::kLaws) {
    CHECK(!l.unit.empty() && !l.doc_ref.empty() && !l.note.empty());
    CHECK(l.basis == gen::LawBasis::physics || l.basis == gen::LawBasis::design);
    CHECK(gen::find_law(l.id) == &l);
    for (auto v : l.variables) {
      CHECK(var_index_of(v) >= 0);
      CHECK(!gen::no_law_of(v));   // a variable has a law OR a reason, never both
    }
  }
  for (const auto& id : engine_ids) CHECK(gen::law_of(id) != nullptr || gen::no_law_of(id) != nullptr);   // none left undeclared
  for (const auto& n : gen::kNoLaw) CHECK(!n.reason.empty() && gen::law_of(n.variable) == nullptr);
  // One game hour standing still: the hunger rises by the catalogue rate of the effort "standing" (no constant in the engine).
  const auto* hunger = gen::find_law("hunger_rise");
  CHECK(hunger != nullptr && hunger->by_exertion.size() == 6);
  auto n = make_adult();
  n->needs.hunger = 0; n->needs.reserves = 100;
  NpcLaws::Residue r;
  LawEnvironment env; env.now = 1'000'000; env.exertion = Exertion::kStanding;
  NpcLaws::step(*n, r, env, 3'600);
  CHECK_EQ(std::int64_t(n->needs.hunger), hunger->by_exertion[2] / 1'000);
  std::printf("hunger after 1 h standing: %d tenths (catalogue rate %lld per thousand)\n", int(n->needs.hunger), (long long)hunger->by_exertion[2]);
}

EMERGENCE_TEST_MAIN()
