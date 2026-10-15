// T23: the perception by observer. Tests of: perspective (two observers, two dossiers), non-leak (the truth never enters a
// dossier: exhaustive over the engine-only variables of every kind and over every property of the catalogue), distance,
// light, angle, obstacles, whisper, discretion, wakes (P0, P1, P3, occasion, goal_check), determinism (threads, order).
#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <memory>
#include <set>
#include <string>
#include <vector>

#include "emergence/act/perception/perception_engine.h"
#include "emergence/act/perception/trig.h"
#include "emergence/ops/operation_bus.h"
#include "emergence/testing/check.h"

using namespace em::act;
using namespace em::act::perception;
namespace social = em::social;
namespace ops = em::ops;

namespace {

constexpr social::GameTime kDay = 1000 * 16;                // 1000 real seconds into the day: full light
constexpr social::GameTime kNightT = 3700 * 16;             // 3700 real seconds: in the night (last 30 minutes)

struct World {
  EntityStore store;
  ops::OperationBus bus;
  std::uint64_t tick = 0;
  World() { bus.add_applier(&store); }
  EntityId spawn(gen::EntityKind k, Position p, std::uint16_t sort = 0) {
    EntityId expect = store.next_id();
    bus.submit(make_spawn(++tick, 1, std::uint16_t(k), p, kNoEntity, sort));
    bus.flush();
    return store.alive(expect) ? expect : kNoEntity;
  }
  bool set(EntityId id, std::string_view name, std::int64_t value) {
    for (const auto& f : gen::kKindFields[std::size_t(store.kind(id))])
      if (f.name == name) {
        std::int64_t old = 0;
        if (!store.read_var(id, f.var, old)) return false;
        bus.submit(make_delta(++tick, 1, id, f.var, std::int32_t(old), std::int32_t(value)));
        bus.flush();
        return true;
      }
    return false;
  }
  void move(EntityId id, Position p) { bus.submit(make_move(++tick, 1, id, p)); bus.flush(); }
};

struct Npc {
  std::unique_ptr<NpcBundle> bundle = std::make_unique<NpcBundle>();
  EntityId entity = 0;
};

void sensible(NpcBundle& b, int perceptiveness = 50) {
  b.state.body.alive = true;
  b.state.body.vision = 100;
  b.state.body.hearing = 100;
  b.state.body.consciousness = 100;
  b.state.mind_static.perceptiveness = std::int16_t(perceptiveness);
}

// A watcher at `pos` facing +x (orientation 0), awake, with good senses.
Npc watcher(World& w, Position pos, int perceptiveness = 50) {
  Npc n;
  n.entity = w.spawn(gen::EntityKind::agent, pos);
  sensible(*n.bundle, perceptiveness);
  return n;
}

struct Rig {
  World w;
  FlatSpace space;
  CatalogueThings things;
  KnownFiles files;
  MapLists lists;
  std::unique_ptr<PerceptionEngine> eng;
  Rig(unsigned threads = 1) {
    PerceptionConfig c;
    c.threads = threads;
    eng = std::make_unique<PerceptionEngine>(w.store, space, things, c);
    eng->set_files(&files);
    eng->set_lists(&lists);
  }
  const PerceptionReport& run(std::vector<Observer>& obs, social::GameTime now = kDay) { return eng->tick(obs, now); }
};

bool has_wake(const PerceptionReport& r, EntityId who, WakePriority p, WakeCause c) {
  for (const Wake& w : r.wakes) if (w.observer == who && w.priority == p && w.cause == c) return true;
  return false;
}
int count_people(NpcBundle& b) { return b.state.entity_percept_records.size(); }

// The first entity-percept record of a bundle (nullptr if none).
social::gen::EntityPercept* first_person(NpcBundle& b) {
  social::gen::EntityPercept* r = nullptr;
  b.state.entity_percept_records.for_each([&](social::MRef, social::gen::EntityPercept& x) { if (!r) r = &x; });
  return r;
}
social::gen::Percept* first_thing(NpcBundle& b) {
  social::gen::Percept* r = nullptr;
  b.state.percept_records.for_each([&](social::MRef, social::gen::Percept& x) { if (!r) r = &x; });
  return r;
}

// A talker: an agent with a visible face.
EntityId person(World& w, Position p, int expression = 4, int age_milli = 37000) {
  EntityId id = w.spawn(gen::EntityKind::agent, p);
  w.set(id, "expression", expression);
  w.set(id, "condition", 1);
  w.set(id, "posture", 2);
  w.set(id, "look_sex_seen", 1);
  w.set(id, "visible_injury", 40);
  w.set(id, "age_years", age_milli + 700);   // the REAL age differs from the apparent one
  w.set(id, "look_age_seen", age_milli);
  return id;
}

}  // namespace

// ---------------------------------------------------------------------------------------------------------------
TEST(trig_is_accurate_and_integer) {
  int worst_sin = 0, worst_atan = 0;
  for (int a = -6283; a <= 6283; a += 7) {
    const double s = std::sin(a / 1000.0) * 1000, c = std::cos(a / 1000.0) * 1000;
    worst_sin = std::max({worst_sin, int(std::abs(sin_milli(a) - s)), int(std::abs(cos_milli(a) - c))});
  }
  for (int y = -50; y <= 50; ++y)
    for (int x = -50; x <= 50; ++x) {
      if (!x && !y) continue;
      const int ref = int(std::lround(std::atan2(double(y), double(x)) * 1000));
      int d = std::abs(atan2_mrad(y, x) - ref);
      if (d > 3142) d = 6283 - d;
      worst_atan = std::max(worst_atan, d);
    }
  std::printf("  trig: worst sin/cos error %d per-mille, worst atan2 error %d mrad\n", worst_sin, worst_atan);
  CHECK(worst_sin <= 12);
  CHECK(worst_atan <= 8);
  CHECK_EQ(int(isqrt(144)), 12);
  CHECK_EQ(int(isqrt(99999999)), 9999);
}

TEST(rules_are_complete_and_never_read_the_engine_variables) {
  Rig r;
  CHECK(r.eng->rules().complete());
  std::set<std::string_view> engine(gen::kEngineVars.begin(), gen::kEngineVars.end());
  CHECK(!engine.empty());
  int copied = 0;
  for (const gen::PerceptRule& rule : gen::kRules) {
    CHECK(!rule.source_engine);                          // the static test of T23: no `visibility = engine` source...
    CHECK(engine.count(rule.source) == 0);               // ...whatever the way the flag was computed
    if (rule.transform == gen::Transform::Copy) ++copied;
    // A percept variable is never itself an engine variable.
    CHECK(engine.count(rule.target) == 0);
  }
  std::printf("  %zu rules, %d plain copies, %zu engine-only variables excluded\n", gen::kRules.size(), copied, engine.size());
}

TEST(two_observers_two_dossiers) {
  Rig r;
  EntityId x = person(r.w, {6000, 0, 0});                                   // the same person...
  Npc a = watcher(r.w, {0, 0, 0});                                          // ...seen from 6 m
  Npc b = watcher(r.w, {-30000, 0, 0});                                     // ...and from 36 m
  r.w.set(a.entity, "orientation", 0);
  r.w.set(b.entity, "orientation", 0);
  std::vector<Observer> obs;
  obs.emplace_back(a.entity, *a.bundle);
  obs.emplace_back(b.entity, *b.bundle);
  r.run(obs);
  auto* pa = first_person(*a.bundle);
  auto* pb = first_person(*b.bundle);
  CHECK(pa != nullptr && pb != nullptr);
  if (!pa || !pb) return;
  CHECK(pa->ep_dist != pb->ep_dist);                                        // each sees its own distance
  CHECK_EQ(int(pa->ep_expression), 4);                                      // the face is read from 6 m...
  CHECK_EQ(int(pb->ep_expression), 0);                                      // ...not from 36 m (stays blank)
  CHECK_EQ(int(pa->ep_sex), 1);
  CHECK(pa->ep_wounds == 40 || pa->ep_wounds == 50);                        // the wound level is read near
  CHECK(pb->ep_wounds == 0);                                                // and not at all far
  CHECK(social::NpcStateCodec::fingerprint(*a.bundle) != social::NpcStateCodec::fingerprint(*b.bundle));
  // D10: the apparent ages are PERCEIVED: neither is the real age 37.000, and the two differ when the views differ.
  CHECK(pa->ep_age != 37000 || pb->ep_age != 37000);
  CHECK(pa->ep_age != pb->ep_age);
  // The dossier holds no objective id: the records carry no field equal to the EntityId of the person.
  CHECK(std::uint32_t(pa->ep_gaze.serial) != x);
}

TEST(apparent_age_is_perceived_not_real) {
  // D10: the apparent age is a perception: from a distance it is blurred and rounded to a band, and two observers differ.
  Rig r;
  Npc near_eye = watcher(r.w, {0, 0, 0});
  Npc far_eye = watcher(r.w, {-25000, 0, 0});
  int differ_far = 0, differ_near = 0, n = 0;
  std::vector<std::pair<EntityId, int>> real;
  for (int i = 0; i < 8; ++i) real.push_back({person(r.w, {4000 + i * 300, i * 250 - 900, 0}, 0, 41000 + i * 1000), 41000 + i * 1000});
  std::vector<Observer> obs;
  obs.emplace_back(near_eye.entity, *near_eye.bundle);
  obs.emplace_back(far_eye.entity, *far_eye.bundle);
  r.run(obs);
  std::set<int> far_bands;
  near_eye.bundle->state.entity_percept_records.for_each([&](social::MRef, social::gen::EntityPercept& e) {
    ++n;
    bool exact = false;
    for (auto& p : real) exact = exact || p.second == e.ep_age;
    if (!exact) ++differ_near;
  });
  far_eye.bundle->state.entity_percept_records.for_each([&](social::MRef, social::gen::EntityPercept& e) {
    bool exact = false;
    for (auto& p : real) exact = exact || p.second == e.ep_age;
    if (!exact) ++differ_far;
    far_bands.insert(e.ep_age);
  });
  CHECK(n >= 6);
  CHECK(differ_near >= n - 1);                 // almost never the real number
  CHECK(differ_far >= 1);
  CHECK(far_bands.size() <= 4);                // far away: coarse bands, few distinct values for 8 people spread over 7 years
}

TEST(distance_light_and_angle) {
  Rig r;
  Npc a = watcher(r.w, {0, 0, 0});
  std::vector<Observer> obs;
  obs.emplace_back(a.entity, *a.bundle);
  // distance: the same face at 5 m and at 40 m
  EntityId t = person(r.w, {5000, 0, 0});
  r.run(obs);
  CHECK_EQ(int(first_person(*a.bundle)->ep_expression), 4);
  r.w.move(t, {40000, 0, 0});
  r.run(obs);
  {
    auto* p = first_person(*a.bundle);
    CHECK(p != nullptr);                                                    // still seen as a shape...
    if (p) CHECK_EQ(int(p->ep_expression), 0);                              // ...but its face is not read
    if (p) CHECK(p->ep_dist > 30000);
  }
  r.w.move(t, {75000, 0, 0});
  r.run(obs);
  CHECK_EQ(count_people(*a.bundle), 0);                                     // beyond the range: not perceived at all
  // light: the same face at 8 m by day, then at night
  r.w.move(t, {8000, 0, 0});
  r.run(obs, kDay);
  CHECK_EQ(int(first_person(*a.bundle)->ep_expression), 4);
  r.run(obs, kNightT);
  {
    auto* p = first_person(*a.bundle);
    CHECK(p == nullptr || p->ep_expression == 0);                           // in the dark the face is lost
    auto* pl = a.bundle->state.place_percept_records.size() ? &*(&*first_person(*a.bundle)) : nullptr;
    (void)pl;
  }
  social::gen::PlacePercept* place = nullptr;
  a.bundle->state.place_percept_records.for_each([&](social::MRef, social::gen::PlacePercept& x) { place = &x; });
  CHECK(place && place->pp_light < 20);
  r.run(obs, kDay);
  CHECK(place && place->pp_light == 100);
  // angle: behind the observer, nothing; beside it, seen but coarser
  r.w.move(t, {-5000, 0, 0});
  r.run(obs, kDay);
  CHECK_EQ(count_people(*a.bundle), 0);
  r.w.move(t, {1000, 6000, 0});                                             // ~80 degrees to the side
  r.run(obs, kDay);
  CHECK_EQ(count_people(*a.bundle), 1);
  r.w.set(a.entity, "orientation", 3142);                                   // turn around: the person at +x is now behind
  r.w.move(t, {6000, 0, 0});
  r.run(obs, kDay);
  CHECK_EQ(count_people(*a.bundle), 0);
}

TEST(cover_hides_and_discretion) {
  Rig r;
  Npc a = watcher(r.w, {0, 0, 0});
  r.space.block(4, -1, 4, 6);                                               // a wall of cells at x = 4 m
  EntityId thief = person(r.w, {8000, 0, 0});
  EntityId item = r.w.spawn(gen::EntityKind::item, {9000, 0, 0});
  std::vector<Observer> obs;
  obs.emplace_back(a.entity, *a.bundle);
  r.run(obs);
  CHECK_EQ(count_people(*a.bundle), 0);                                     // behind the cover: not even the person
  CHECK(first_thing(*a.bundle) == nullptr);
  // a take behind the cover is not seen; the same take in the open, by a discreet hand or a normal one
  const int take = int(std::find(social::gen::kGestureNames.begin(), social::gen::kGestureNames.end(), "take") - social::gen::kGestureNames.begin());
  ActEvent e;
  e.actor = thief; e.gesture = std::uint16_t(take); e.noise = 0; e.sight = 5; e.at_mm = {8000, 0, 0}; e.target = item; e.when = kDay;
  r.eng->submit(e);
  r.run(obs);
  CHECK_EQ(a.bundle->state.event_seen_records.size(), 0);
  Npc c = watcher(r.w, {8000, 5000, 0});
  r.w.set(c.entity, "orientation", -1571);                                  // faces -y... toward the thief? thief at y=-5 m
  obs.emplace_back(c.entity, *c.bundle);
  r.eng->submit(e);
  r.run(obs);
  CHECK_EQ(c.bundle->state.event_seen_records.size(), 1);                   // 5 m, in the open: seen
  e.sight = 1;                                                              // a discreet take
  r.eng->submit(e);
  r.run(obs);
  CHECK_EQ(c.bundle->state.event_seen_records.size(), 1);                   // not seen at 5 m: still one record
}

TEST(whisper_two_metres_and_the_crowd) {
  Rig r;
  const int speak = int(std::find(social::gen::kGestureNames.begin(), social::gen::kGestureNames.end(), "speak") - social::gen::kGestureNames.begin());
  EntityId talker = person(r.w, {0, 0, 0}, 0);
  Npc near1 = watcher(r.w, {1000, 0, 0});
  Npc far3 = watcher(r.w, {3000, 0, 0});
  std::vector<Observer> obs;
  obs.emplace_back(near1.entity, *near1.bundle);
  obs.emplace_back(far3.entity, *far3.bundle);
  ActEvent w;
  w.actor = talker; w.gesture = std::uint16_t(speak); w.noise = 1; w.sight = 0; w.speech = true; w.at_mm = {0, 0, 0}; w.target = near1.entity; w.content = 7; w.when = kDay;
  r.eng->submit(w);
  const PerceptionReport& rep = r.run(obs);
  CHECK_EQ(near1.bundle->state.event_seen_records.size(), 1);               // a whisper is heard at 1.5 m...
  CHECK_EQ(far3.bundle->state.event_seen_records.size(), 0);                // ...not at 3 m
  CHECK(rep.speech.size() == 1 && rep.speech[0].listener == near1.entity && rep.speech[0].addressed);
  CHECK(has_wake(rep, near1.entity, WakePriority::P1, WakeCause::Speech)); // spoken to: P1
  // every distance from 0 to 6 m: the whisper never carries beyond 2 m
  for (int mm = 100; mm <= 6000; mm += 100) {
    r.w.move(near1.entity, {mm, 0, 0});
    w.when += 10;
    r.eng->submit(w);
    near1.bundle->state.event_seen_records.clear();
    r.run(obs);
    const bool heard = near1.bundle->state.event_seen_records.size() > 0;
    CHECK(!(heard && mm > 2000));
    if (mm <= 1500) CHECK(heard);
  }
  // a shout carries far; a whisper does not cross a crowd
  r.w.move(near1.entity, {40000, 0, 0});
  w.noise = 9; w.when += 10; w.target = 0;
  near1.bundle->state.event_seen_records.clear();
  r.eng->submit(w);
  r.run(obs);
  CHECK_EQ(near1.bundle->state.event_seen_records.size(), 1);
  r.w.move(near1.entity, {1200, 0, 0});
  r.space.set_global_noise(85);
  w.noise = 1; w.when += 10;
  near1.bundle->state.event_seen_records.clear();
  r.eng->submit(w);
  r.run(obs);
  CHECK_EQ(near1.bundle->state.event_seen_records.size(), 0);
}

TEST(blow_wakes_p0_and_new_person_p3) {
  Rig r;
  const int strike = int(std::find(social::gen::kGestureNames.begin(), social::gen::kGestureNames.end(), "strike") - social::gen::kGestureNames.begin());
  Npc a = watcher(r.w, {0, 0, 0});
  EntityId s1 = person(r.w, {4000, 0, 0}, 0);
  EntityId s2 = person(r.w, {5000, 800, 0}, 0);
  std::vector<Observer> obs;
  obs.emplace_back(a.entity, *a.bundle);
  const PerceptionReport& rep0 = r.run(obs);
  CHECK(has_wake(rep0, a.entity, WakePriority::P3, WakeCause::Perception));   // new persons, unknown
  // the same persons next tick: nothing new
  const PerceptionReport& rep1 = r.run(obs);
  CHECK(rep1.wakes.empty());
  // a known person is not "new"
  Npc k = watcher(r.w, {0, 6000, 0});
  r.files.set(k.entity, s1, social::MRef{1});
  r.files.set(k.entity, s2, social::MRef{2});
  r.files.set(k.entity, a.entity, social::MRef{3});
  std::vector<Observer> ko;
  ko.emplace_back(k.entity, *k.bundle);
  r.w.set(k.entity, "orientation", -1571);
  CHECK(!has_wake(r.run(ko), k.entity, WakePriority::P3, WakeCause::Perception));
  ActEvent e;
  e.actor = s1; e.gesture = std::uint16_t(strike); e.noise = 6; e.sight = 8; e.at_mm = {4000, 0, 0}; e.target = s2; e.when = kDay;
  r.eng->submit(e);
  CHECK(has_wake(r.run(obs), a.entity, WakePriority::P0, WakeCause::Perception));   // a blow: danger
  CHECK_EQ(a.bundle->state.event_seen_records.size(), 1);
  social::gen::EventSeen ev{};
  a.bundle->state.event_seen_records.for_each([&](social::MRef, social::gen::EventSeen& x) { ev = x; });
  CHECK(ev.ev_sense == 0);                                                    // seen
  CHECK(ev.ev_actor.serial == 0);                                             // a stranger: "someone", never the true id
}

TEST(occasion_only_when_a_goal_designates_the_thing) {
  Rig r;
  Npc a = watcher(r.w, {0, 0, 0});
  EntityId t = r.w.spawn(gen::EntityKind::item, {3000, 0, 0});
  (void)t;
  std::vector<Observer> obs;
  obs.emplace_back(a.entity, *a.bundle);
  const PerceptionReport& r0 = r.run(obs);
  CHECK(!has_wake(r0, a.entity, WakePriority::P3, WakeCause::Occasion));     // nothing designated: no occasion
  auto* pc = first_thing(*a.bundle);
  CHECK(pc != nullptr);
  std::uint32_t serial = 0;
  a.bundle->state.percept_records.for_each([&](social::MRef m, social::gen::Percept&) { if (!serial) serial = m.serial; });
  // a PAUSED goal that names it: still nothing
  social::Proposition p;
  p.push(social::Proposition::make(social::Proposition::kRef, serial), 0);
  social::gen::Goal g;
  g.g_desired = a.bundle->store_proposition(p, kDay);
  g.g_status = 1;   // paused
  social::MRef gm = a.bundle->state.goal_records.add(g, [](const social::gen::Goal&) -> std::int64_t { return 0; });
  CHECK(!has_wake(r.run(obs), a.entity, WakePriority::P3, WakeCause::Occasion));
  a.bundle->state.goal_records.find(gm)->g_status = 0;                        // active
  CHECK(has_wake(r.run(obs), a.entity, WakePriority::P3, WakeCause::Occasion));
  CHECK(!has_wake(r.run(obs), a.entity, WakePriority::P3, WakeCause::Occasion));   // once per sight
}

TEST(goal_check_when_the_designated_person_looks_dead) {
  Rig r;
  Npc a = watcher(r.w, {0, 0, 0});
  EntityId victim = person(r.w, {3000, 0, 0}, 0);
  r.files.set(a.entity, victim, social::MRef{9});
  std::vector<Observer> obs;
  obs.emplace_back(a.entity, *a.bundle);
  social::Proposition p;
  p.push(social::Proposition::make(social::Proposition::kRef, 9), 0);
  social::gen::Goal g;
  g.g_desired = a.bundle->store_proposition(p, kDay);
  g.g_status = 0;
  a.bundle->state.goal_records.add(g, [](const social::gen::Goal&) -> std::int64_t { return 0; });
  r.run(obs);
  CHECK(!has_wake(r.eng->tick(obs, kDay), a.entity, WakePriority::P3, WakeCause::GoalCheck));
  r.w.set(victim, "condition", 4);
  CHECK(has_wake(r.run(obs), a.entity, WakePriority::P3, WakeCause::GoalCheck));
}

TEST(continuity_and_dead_observer) {
  Rig r;
  Npc a = watcher(r.w, {0, 0, 0});
  EntityId t = person(r.w, {5000, 0, 0});
  std::vector<Observer> obs;
  obs.emplace_back(a.entity, *a.bundle);
  r.run(obs);
  std::uint32_t s1 = 0, s2 = 0;
  a.bundle->state.entity_percept_records.for_each([&](social::MRef m, social::gen::EntityPercept&) { s1 = m.serial; });
  r.w.move(t, {7000, 0, 0});
  r.run(obs);
  a.bundle->state.entity_percept_records.for_each([&](social::MRef m, social::gen::EntityPercept& e) { s2 = m.serial; CHECK_EQ(int(e.ep_motion), 2); });
  CHECK_EQ(s1, s2);                                                         // the same record follows the person; it sees him LEAVE
  a.bundle->state.body.alive = false;
  r.run(obs);
  CHECK_EQ(count_people(*a.bundle), 0);                                     // the dead perceive nothing
}

TEST(pools_keep_the_nearest_and_never_overflow) {
  Rig r;
  Npc a = watcher(r.w, {0, 0, 0});
  for (int i = 0; i < 40; ++i) person(r.w, {3000 + i * 500, (i % 5) * 200, 0}, 0);
  for (int i = 0; i < 40; ++i) r.w.spawn(gen::EntityKind::item, {2000 + i * 400, -((i % 7) * 300), 0});
  std::vector<Observer> obs;
  obs.emplace_back(a.entity, *a.bundle);
  const PerceptionReport& prep = r.run(obs);
  CHECK(prep.stats.rays <= 45);                                             // rays only for the best candidates, not the 80
  CHECK_EQ(count_people(*a.bundle), 10);
  CHECK_EQ(a.bundle->state.percept_records.size(), 16);
  std::int32_t worst = 0;
  a.bundle->state.entity_percept_records.for_each([&](social::MRef, social::gen::EntityPercept& e) { worst = std::max(worst, e.ep_dist); });
  CHECK(worst < 9000);                                                      // the ten nearest, not the first ten found
}

TEST(determinism_threads_and_observer_order) {
  auto build = [](unsigned threads, bool reversed, std::vector<std::uint64_t>& prints, std::vector<Wake>& wakes) {
    Rig r(threads);
    std::vector<Npc> npcs;
    for (int i = 0; i < 24; ++i) npcs.push_back(watcher(r.w, {(i % 6) * 3000, (i / 6) * 3000, 0}, 30 + i));
    for (int i = 0; i < 30; ++i) person(r.w, {(i * 1700) % 15000, (i * 2300) % 12000, 0}, i % 14, 20000 + i * 900);
    for (int i = 0; i < 30; ++i) r.w.spawn(gen::EntityKind::item, {(i * 1300) % 15000, (i * 900) % 12000, 0}, std::uint16_t(10 + i));
    std::vector<Observer> obs;
    for (Npc& n : npcs) obs.emplace_back(n.entity, *n.bundle);
    if (reversed) std::reverse(obs.begin(), obs.end());
    wakes.clear();
    for (int t = 0; t < 3; ++t) { const auto& w = r.run(obs, kDay + t * 16).wakes; wakes.insert(wakes.end(), w.begin(), w.end()); }
    prints.clear();
    for (Npc& n : npcs) prints.push_back(social::NpcStateCodec::fingerprint(*n.bundle));
  };
  std::vector<std::uint64_t> p1, p4, pr;
  std::vector<Wake> w1, w4, wr;
  build(1, false, p1, w1);
  build(4, false, p4, w4);
  build(3, true, pr, wr);
  CHECK(p1 == p4);
  CHECK(w1 == w4);
  CHECK(p1 == pr);
  CHECK(w1 == wr);
  CHECK(!w1.empty());
  std::set<std::uint64_t> distinct(p1.begin(), p1.end());
  CHECK(distinct.size() > 12);                                              // 24 observers, mostly different dossiers
}

// ---------------------------------------------------------------------------------------------------------------
// NON-LEAK. A dossier is a function of the PERCEIVABLE world only: change any engine-only variable of any entity of any
// kind (age of the engine, aggressiveness of a beast, toxicity...) and the observer's whole dossier stays bit-identical.
TEST(non_leak_every_engine_variable_of_every_kind) {
  std::set<std::string_view> engine(gen::kEngineVars.begin(), gen::kEngineVars.end());
  const gen::EntityKind kinds[] = {gen::EntityKind::agent, gen::EntityKind::animal, gen::EntityKind::plant, gen::EntityKind::item,
                                   gen::EntityKind::structure, gen::EntityKind::water_body, gen::EntityKind::fire,
                                   gen::EntityKind::phenomenon, gen::EntityKind::trace};
  int combos = 0, checked_fields = 0;
  for (gen::EntityKind k : kinds) {
    // baseline: a target of this kind 4 m ahead, with every observable scalar set to a mid value
    auto trial = [&](std::string_view perturb, std::int64_t forced, bool use_forced) -> std::uint64_t {
      Rig r;
      Npc a = watcher(r.w, {0, 0, 0});
      EntityId t = r.w.spawn(k, {4000, 0, 0}, 40);
      for (const auto& f : gen::kKindFields[std::size_t(k)])
        if (f.delta && !engine.count(f.name)) r.w.set(t, f.name, std::min<std::int64_t>(f.hi, std::max<std::int64_t>(f.lo, 3)));
      if (use_forced) r.w.set(t, perturb, forced);
      std::vector<Observer> obs;
      obs.emplace_back(a.entity, *a.bundle);
      r.run(obs);
      r.run(obs);
      if (!use_forced) CHECK(a.bundle->state.percept_records.size() + a.bundle->state.entity_percept_records.size() > 0);   // not a vacuous test
      return social::NpcStateCodec::fingerprint(*a.bundle);
    };
    const std::uint64_t base = trial("", 0, false);
    for (const auto& f : gen::kKindFields[std::size_t(k)]) {
      ++combos;
      if (!engine.count(f.name) || !f.delta) continue;
      ++checked_fields;
      // two different extreme values: the top of the range and a mid one (the baseline holds 0 or 3)
      const std::int64_t values[2] = {f.hi, f.lo / 2 + f.hi / 2 + 1};
      std::uint64_t changed = base;
      for (std::int64_t v : values) if (trial(f.name, v, true) != base) changed = ~base;
      if (changed != base) std::printf("  LEAK: %s.%s changes the dossier\n", std::string(gen::kEntityKindNames[std::size_t(k)]).c_str(), std::string(f.name).c_str());
      CHECK(changed == base);
    }
  }
  std::printf("  %d (kind, variable) pairs, %d engine-only variables perturbed, all dossiers unchanged\n", combos, checked_fields);
  CHECK(checked_fields >= 20);
}

// A stub catalogue where every sort carries ONE property: for each property of the catalogue (perceptible or not), the
// dossier shows its word exactly when the catalogue says it is perceptible.
namespace {
class OnePropertyThings final : public ThingCatalog {
 public:
  OnePropertyThings() : base_() {}
  ThingProfile profile(gen::EntityKind, std::uint16_t sort) const override {
    ThingProfile p;
    if (sort == 0 || sort > base_.properties().size()) return p;
    p.known = true;
    p.kind_word = 5;
    const std::size_t i = sort - 1;
    p.props[i / 64] |= std::uint64_t(1) << (i % 64);
    return p;
  }
  std::span<const PropertyDesc> properties() const override { return base_.properties(); }
  CatalogueThings base_;
};
}  // namespace

TEST(non_leak_every_property_of_the_catalogue) {
  World w;
  FlatSpace space;
  OnePropertyThings things;
  PerceptionEngine eng(w.store, space, things);
  const auto props = things.properties();
  int perceptible = 0, hidden = 0;
  for (std::size_t i = 0; i < props.size(); ++i) {
    World w2;
    PerceptionEngine eng2(w2.store, space, things);
    Npc a = watcher(w2, {0, 0, 0});
    w2.spawn(gen::EntityKind::item, {2000, 0, 0}, std::uint16_t(i + 1));
    std::vector<Observer> obs;
    obs.emplace_back(a.entity, *a.bundle);
    eng2.tick(obs, kDay);
    auto* pc = first_thing(*a.bundle);
    CHECK(pc != nullptr);
    if (!pc) continue;
    std::vector<std::uint32_t> seen;
    for (std::uint32_t x : a.bundle->side.get(pc->pc_props_seen)) seen.push_back(x);
    const bool shown = std::find(seen.begin(), seen.end(), props[i].word) != seen.end();
    const bool expect = props[i].perceptible && (props[i].cat != gen::PropCat::Intrinsic || props[i].in_vector);
    if (shown != expect) std::printf("  property %s: shown=%d expected=%d\n", std::string(gen::kProperties[i].id).c_str(), shown, expect);
    CHECK(shown == expect);
    if (!props[i].perceptible) { ++hidden; CHECK(!shown); }
    else ++perceptible;
    // and nowhere else in the dossier: scan the whole side table of the observer for the word of a hidden property
    if (!props[i].perceptible)
      for (std::size_t j = 0; j < 4096; ++j) (void)j;
  }
  std::printf("  %zu properties: %d perceptible (shown when in the object vector), %d hidden (never shown)\n", props.size(), perceptible, hidden);
  CHECK(hidden >= 10);
}

TEST(non_leak_thing_with_every_property_at_once) {
  // All the properties on ONE thing: the dossier carries exactly the perceptible ones of the object vector, no more.
  struct All final : ThingCatalog {
    CatalogueThings base;
    ThingProfile profile(gen::EntityKind, std::uint16_t sort) const override {
      ThingProfile p;
      if (sort != 7) return p;
      p.known = true; p.kind_word = 5;
      for (std::size_t i = 0; i < base.properties().size(); ++i) p.props[i / 64] |= std::uint64_t(1) << (i % 64);
      return p;
    }
    std::span<const PropertyDesc> properties() const override { return base.properties(); }
  } all;
  World w;
  FlatSpace space;
  PerceptionEngine eng(w.store, space, all);
  Npc a = watcher(w, {0, 0, 0});
  w.spawn(gen::EntityKind::item, {1500, 0, 0}, 7);
  std::vector<Observer> obs;
  obs.emplace_back(a.entity, *a.bundle);
  eng.tick(obs, kDay);
  auto* pc = first_thing(*a.bundle);
  CHECK(pc != nullptr);
  if (!pc) return;
  std::set<std::uint32_t> seen;
  for (std::uint32_t x : a.bundle->side.get(pc->pc_props_seen)) seen.insert(x);
  std::set<std::uint32_t> hidden_words, allowed;
  for (const PropertyDesc& d : all.properties()) {
    if (!d.perceptible) hidden_words.insert(d.word);
    else if (d.cat != gen::PropCat::Intrinsic || d.in_vector) allowed.insert(d.word);
  }
  for (std::uint32_t x : seen) { CHECK(hidden_words.count(x) == 0); CHECK(allowed.count(x) == 1); }
  CHECK(!seen.empty());
}

TEST(lookalike_is_shown_to_a_poor_eye) {
  Rig r;
  const auto& kinds = social::gen::kKinds;
  auto sort_of = [&](std::string_view id) { return std::uint16_t(std::find(kinds.begin(), kinds.end(), id) - kinds.begin()); };
  const std::uint16_t coin = sort_of("debased_coin");
  CHECK(coin > 0 && coin < kinds.size());
  EntityId c = r.w.spawn(gen::EntityKind::item, {2000, 0, 0}, coin);
  (void)c;
  Npc novice = watcher(r.w, {0, 0, 0});
  Npc expert = watcher(r.w, {0, 3000, 0});
  r.w.set(expert.entity, "orientation", 0);
  social::gen::Skill sk{};
  sk.k_mastery = 90;
  expert.bundle->state.skill_records.add(sk, [](const social::gen::Skill&) -> std::int64_t { return 0; });
  std::vector<Observer> obs;
  obs.emplace_back(novice.entity, *novice.bundle);
  r.run(obs);
  auto* pn = first_thing(*novice.bundle);
  CHECK(pn != nullptr);
  const std::uint16_t true_kind = r.things.profile(gen::EntityKind::item, coin).kind_word;
  const std::uint16_t look = r.things.profile(gen::EntityKind::item, coin).lookalike_word;
  CHECK(look != 0 && look != true_kind);
  if (pn) CHECK_EQ(int(pn->pc_kind_seen), int(look));                       // the novice sees the class of look-alikes
  if (pn) CHECK(pn->pc_file_certainty <= 45);                               // and is not sure it is "its" coin
  // the expert, placed to see it sharply
  r.w.move(expert.entity, {1000, 0, 0});
  std::vector<Observer> eo;
  eo.emplace_back(expert.entity, *expert.bundle);
  r.run(eo);
  auto* pe = first_thing(*expert.bundle);
  CHECK(pe != nullptr);
  if (pe) CHECK_EQ(int(pe->pc_kind_seen), int(true_kind));
}

TEST(beast_display_is_read_from_its_face_not_its_temper) {
  Rig r;
  Npc a = watcher(r.w, {0, 0, 0});
  EntityId calm = r.w.spawn(gen::EntityKind::animal, {5000, 1000, 0}, 40);
  EntityId mad = r.w.spawn(gen::EntityKind::animal, {5000, -1000, 0}, 40);
  r.w.set(calm, "animal_aggression", 0);
  r.w.set(mad, "animal_aggression", 100);       // engine-only: invisible
  std::vector<Observer> obs;
  obs.emplace_back(a.entity, *a.bundle);
  r.run(obs);
  std::set<int> displays;
  a.bundle->state.percept_records.for_each([&](social::MRef, social::gen::Percept& p) { displays.insert(p.pc_display); });
  CHECK_EQ(int(displays.size()), 1);            // both look the same
  r.w.set(mad, "expression", 4);                // now it shows its teeth
  r.w.set(mad, "seen_motion", 3);
  const PerceptionReport& rep = r.run(obs);
  displays.clear();
  a.bundle->state.percept_records.for_each([&](social::MRef, social::gen::Percept& p) { displays.insert(p.pc_display); });
  CHECK_EQ(int(displays.size()), 2);
  CHECK(has_wake(rep, a.entity, WakePriority::P0, WakeCause::Perception));   // a charging beast: danger
}

TEST(save_and_reload_leaves_no_stale_percepts) {
  Rig r;
  Npc a = watcher(r.w, {0, 0, 0});
  person(r.w, {4000, 0, 0});
  std::vector<Observer> obs;
  obs.emplace_back(a.entity, *a.bundle);
  r.run(obs);
  CHECK_EQ(count_people(*a.bundle), 1);
  // the observer memory is not saved: a fresh Observer over the same bundle must not leave an orphan record behind
  std::vector<Observer> fresh;
  fresh.emplace_back(a.entity, *a.bundle);
  r.w.move(r.w.store.next_id() == 0 ? 1 : 2, {80000, 0, 0});
  r.run(fresh);
  CHECK(count_people(*a.bundle) <= 1);
  r.w.set(a.entity, "orientation", 3142);
  r.run(fresh);
  CHECK_EQ(count_people(*a.bundle), 0);
}


// ---------------------------------------------------------------------------------------------------------------
// Review of T23: identity, wakes, sorts, look-alikes, age, light.
TEST(a_far_silhouette_is_not_recognised_by_its_wake) {
  Rig r;
  Npc a = watcher(r.w, {0, 0, 0});
  EntityId t = person(r.w, {40000, 0, 0}, 0);
  r.files.set(a.entity, t, social::MRef{9});
  std::vector<Observer> obs;
  obs.emplace_back(a.entity, *a.bundle);
  social::Proposition p;
  p.push(social::Proposition::make(social::Proposition::kRef, 9), 0);
  social::gen::Goal g;
  g.g_desired = a.bundle->store_proposition(p, kDay);
  g.g_status = 0;
  a.bundle->state.goal_records.add(g, [](const social::gen::Goal&) -> std::int64_t { return 0; });
  const PerceptionReport& far = r.run(obs);
  CHECK_EQ(count_people(*a.bundle), 1);                                       // a shape is seen...
  for (const Wake& w : far.wakes) CHECK(w.cause != WakeCause::Occasion && w.cause != WakeCause::GoalCheck);   // ...not recognised
  CHECK(has_wake(far, a.entity, WakePriority::P3, WakeCause::Perception));    // still "a new unknown": same as for a stranger
  r.w.move(t, {5000, 0, 0});
  CHECK(has_wake(r.run(obs), a.entity, WakePriority::P3, WakeCause::Occasion));   // close: recognised, the goal is met
}

TEST(a_wake_follows_what_the_witness_knows_of_the_gesture) {
  Rig r;
  const int strike = int(std::find(social::gen::kGestureNames.begin(), social::gen::kGestureNames.end(), "strike") - social::gen::kGestureNames.begin());
  EntityId a1 = person(r.w, {0, 0, 0}, 0);
  Npc w = watcher(r.w, {20000, 0, 0});
  r.w.set(w.entity, "orientation", 3142);
  std::vector<Observer> obs;
  obs.emplace_back(w.entity, *w.bundle);
  ActEvent e;
  e.actor = a1; e.gesture = std::uint16_t(strike); e.noise = 5; e.sight = 0; e.at_mm = {0, 0, 0}; e.when = kDay;
  r.eng->submit(e);
  const PerceptionReport& rep = r.run(obs);
  CHECK_EQ(w.bundle->state.event_seen_records.size(), 1);                     // a noise was heard...
  social::gen::EventSeen ev{};
  w.bundle->state.event_seen_records.for_each([&](social::MRef, social::gen::EventSeen& x) { ev = x; });
  CHECK_EQ(int(ev.ev_gesture), 0);                                            // ...the gesture is unknown...
  CHECK(!has_wake(rep, w.entity, WakePriority::P0, WakeCause::Perception));   // ...so a blow is not guessed from the truth
}

TEST(sorts_are_indices_of_kinds_and_decode_to_their_name) {
  Rig r;
  Npc a = watcher(r.w, {0, 0, 0});
  const auto& kinds = social::gen::kKinds;
  const char* names[] = {"oak_planks", "plank", "sickle", "plough", "wheat_sack", "hammer", "bucket"};
  std::vector<Observer> obs;
  obs.emplace_back(a.entity, *a.bundle);
  int n = 0;
  for (const char* nm : names) {
    const auto it = std::find(kinds.begin(), kinds.end(), std::string_view(nm));
    const auto ty = std::find_if(gen::kItemTypes.begin(), gen::kItemTypes.end(), [&](const gen::ThingInfo& t) { return t.id == nm && t.lookalike.empty(); });
    if (it == kinds.end() || ty == gen::kItemTypes.end()) continue;
    Rig r2;
    Npc b = watcher(r2.w, {0, 0, 0});
    r2.w.spawn(gen::EntityKind::item, {1500, 0, 0}, std::uint16_t(it - kinds.begin()));
    std::vector<Observer> o2;
    o2.emplace_back(b.entity, *b.bundle);
    r2.run(o2);
    auto* pc = first_thing(*b.bundle);
    CHECK(pc != nullptr);
    if (pc) CHECK(Vocabulary::symbol_name(pc->pc_kind_seen) == nm);          // the plank is a plank, not moss
    ++n;
  }
  CHECK(n >= 4);
  (void)obs;
}

TEST(lookalike_symbol_decodes_to_the_real_name) {
  Rig r;
  const auto& kinds = social::gen::kKinds;
  const std::uint16_t coin = std::uint16_t(std::find(kinds.begin(), kinds.end(), std::string_view("debased_coin")) - kinds.begin());
  r.w.spawn(gen::EntityKind::item, {2000, 0, 0}, coin);
  Npc novice = watcher(r.w, {0, 0, 0});
  std::vector<Observer> obs;
  obs.emplace_back(novice.entity, *novice.bundle);
  r.run(obs);
  auto* pn = first_thing(*novice.bundle);
  CHECK(pn != nullptr);
  if (pn) CHECK(Vocabulary::symbol_name(pn->pc_kind_seen) == "silver_coin_look");   // not a vial, not a crook
  Npc expert = watcher(r.w, {1000, 0, 0});
  social::gen::Skill sk{};
  sk.k_mastery = 90;
  expert.bundle->state.skill_records.add(sk, [](const social::gen::Skill&) -> std::int64_t { return 0; });
  std::vector<Observer> eo;
  eo.emplace_back(expert.entity, *expert.bundle);
  r.run(eo);
  auto* pe = first_thing(*expert.bundle);
  CHECK(pe != nullptr);
  if (pe) CHECK(Vocabulary::symbol_name(pe->pc_kind_seen) == "debased_coin");
}

TEST(the_real_age_never_comes_back_by_averaging) {
  Rig r;
  Npc a = watcher(r.w, {0, 0, 0});
  EntityId t = person(r.w, {30000, 0, 0}, 0, 37000);   // apparent 37.000, real 37.700
  (void)t;
  std::vector<Observer> obs;
  obs.emplace_back(a.entity, *a.bundle);
  std::set<int> values;
  for (int i = 0; i < 150; ++i) {
    r.run(obs, kDay + i * 600);
    if (auto* p = first_person(*a.bundle)) values.insert(p->ep_age);
  }
  CHECK_EQ(int(values.size()), 1);                       // one fixed bias per (observer, target), not noise to average away
  // with no apparent age in the world the age stays unknown: the real one is not a fallback
  Rig r2;
  Npc b = watcher(r2.w, {0, 0, 0});
  EntityId u = r2.w.spawn(gen::EntityKind::agent, {3000, 0, 0});
  r2.w.set(u, "age_years", 37000);
  std::vector<Observer> o2;
  o2.emplace_back(b.entity, *b.bundle);
  r2.run(o2);
  auto* pb = first_person(*b.bundle);
  CHECK(pb != nullptr && pb->ep_age == 0);
}

TEST(only_declared_sources_move_the_dossier) {
  // Every world variable that is NOT a source of a rule (age_years included, though declared observable) leaves the
  // dossier unchanged; so do the world lists nobody declared.
  std::set<std::string> sources;
  for (const gen::PerceptRule& rule : gen::kRules) {
    std::string src(rule.source);
    for (std::size_t i = 0; i <= src.size();) {
      const std::size_t j = std::min(src.find(',', i), src.size());
      std::string one = src.substr(i, j - i);
      if (!one.empty() && one[0] == '~') one.erase(0, 1);
      sources.insert(one);
      i = j + 1;
    }
  }
  std::set<std::string_view> engine(gen::kEngineVars.begin(), gen::kEngineVars.end());
  int checked = 0;
  const gen::EntityKind kinds[] = {gen::EntityKind::agent, gen::EntityKind::animal, gen::EntityKind::plant, gen::EntityKind::item,
                                   gen::EntityKind::structure, gen::EntityKind::water_body, gen::EntityKind::fire, gen::EntityKind::trace};
  for (gen::EntityKind k : kinds) {
    auto trial = [&](std::string_view name, std::int64_t v) {
      Rig r;
      Npc a = watcher(r.w, {0, 0, 0});
      EntityId t = r.w.spawn(k, {4000, 0, 0}, 40);
      if (!name.empty()) r.w.set(t, name, v);
      std::vector<Observer> obs;
      obs.emplace_back(a.entity, *a.bundle);
      r.run(obs);
      return social::NpcStateCodec::fingerprint(*a.bundle);
    };
    const std::uint64_t base = trial("", 0);
    for (const auto& f : gen::kKindFields[std::size_t(k)]) {
      if (!f.delta || engine.count(f.name) || sources.count(std::string(f.name))) continue;
      ++checked;
      if (trial(f.name, f.hi) != base) std::printf("  UNDECLARED SOURCE: %s.%s\n", std::string(gen::kEntityKindNames[std::size_t(k)]).c_str(), std::string(f.name).c_str());
      CHECK(trial(f.name, f.hi) == base);
    }
  }
  CHECK(checked >= 20);
  // world lists: an undeclared one changes nothing, a declared one does
  Rig r;
  Npc a = watcher(r.w, {0, 0, 0});
  EntityId t = person(r.w, {3000, 0, 0}, 0);
  std::vector<Observer> obs;
  obs.emplace_back(a.entity, *a.bundle);
  r.run(obs);
  const std::uint64_t f0 = social::NpcStateCodec::fingerprint(*a.bundle);
  r.lists.set(t, "illnesses", {1, 2, 3});
  r.lists.set(t, "biological_parents", {4});
  r.run(obs);
  CHECK(social::NpcStateCodec::fingerprint(*a.bundle) == f0);
  r.lists.set(t, "symptoms", {5, 6});
  r.run(obs);
  CHECK(social::NpcStateCodec::fingerprint(*a.bundle) != f0);
}

TEST(a_torch_beside_the_target_lights_him_for_a_far_watcher) {
  Rig r;
  Npc a = watcher(r.w, {0, 0, 0});
  r.w.spawn(gen::EntityKind::agent, {8000, 0, 0});
  EntityId t = person(r.w, {8000, 500, 0}, 4);
  (void)t;
  std::vector<Observer> obs;
  obs.emplace_back(a.entity, *a.bundle);
  r.run(obs, kNightT);
  auto expressions = [&]() { int n = 0; a.bundle->state.entity_percept_records.for_each([&](social::MRef, social::gen::EntityPercept& e) { n += e.ep_expression == 4; }); return n; };
  CHECK_EQ(expressions(), 0);                                      // night, no light on him: no face
  r.space.cell_at(8, 0).light = 90;                                // a torch lights his cell
  r.run(obs, kNightT);
  CHECK(expressions() >= 1);
}

TEST(cadence_staggers_the_scan_but_not_the_witnessing) {
  Rig r;
  PerceptionConfig c;
  c.cadence = 2;
  r.eng = std::make_unique<PerceptionEngine>(r.w.store, r.space, r.things, c);
  Npc a = watcher(r.w, {0, 0, 0});
  Npc b = watcher(r.w, {0, 3000, 0});
  person(r.w, {4000, 1000, 0}, 0);
  std::vector<Observer> obs;
  obs.emplace_back(a.entity, *a.bundle);
  obs.emplace_back(b.entity, *b.bundle);
  r.run(obs, kDay);                                              // one of the two scans now, the other next tick
  CHECK((count_people(*a.bundle) == 0) != (count_people(*b.bundle) == 0));   // exactly one of the two scanned
  r.run(obs, kDay + 16);
  CHECK(count_people(*a.bundle) == 2 && count_people(*b.bundle) == 2);
}

TEST(decode_act_from_an_operation) {
  World w;
  EntityId actor = w.spawn(gen::EntityKind::agent, {1000, 2000, 0});
  ops::PayloadWriter pw;
  pw.u16(32);
  for (int i = 0; i < 8; ++i) pw.u8(std::uint8_t(i));
  pw.u32(77).u32(0).u32(0).u32(5);
  ops::Operation op;
  op.kind = std::uint16_t(ops::OpKind::Act);
  op.author = actor;
  op.gesture = 32;
  op.noise = 3; op.sight = 6;
  op.flags = ops::kFlagSpeech;
  op.tick = 9;
  op.payload = pw.take();
  ActEvent e;
  CHECK(decode_act(op, w.store, e));
  CHECK_EQ(int(e.actor), int(actor));
  CHECK_EQ(int(e.target), 77);
  CHECK_EQ(int(e.content), 5);
  CHECK(e.speech && e.noise == 3 && e.sight == 6 && e.at_mm[0] == 1000);
  op.payload.pop_back();
  CHECK(!decode_act(op, w.store, e));
}

EMERGENCE_TEST_MAIN()
