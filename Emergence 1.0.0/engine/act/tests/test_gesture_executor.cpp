// T22: the executor of gestures. Tests of: the generated timing table, the state machine on the 40 gestures, each family
// (movement, grasping, striking -> contact -> law -> operation, eating and drinking -> NpcLaws, speaking -> SpeechRouter,
// looking and listening -> perception), the stop conditions and their order, interruption, no failure at a distance,
// the plan facts (i_status, i_step_progress, i_attempts), D10, kTaskCompression, the felling of an oak, determinism with 1,
// 4 and 8 threads and 500 NPC over one game day.
#include <algorithm>
#include <chrono>
#include <cstdio>

#include "emergence/act/perception/perception_engine.h"
#include "emergence/act/navigation/navigator.h"
#include "emergence/social/speech_router.h"
#include "emergence/social/speech_router.h"
#include "emergence/testing/check.h"
#include "gesture_rig.h"
#include "gesture_workload.h"
#include "navigator_adapter.h"

using namespace em::act;
using namespace em::act::grig;
namespace social = em::social;
namespace ops = em::ops;

namespace {

constexpr Position kOrigin{0, 0, 0};

std::uint16_t word_of(Gesture g) {
  for (std::size_t i = 0; i < social::gen::kWords.size(); ++i)
    if (social::gen::kWords[i] == social::gen::kGestureNames[static_cast<std::size_t>(g)]) return static_cast<std::uint16_t>(i);
  return 0;
}

// An intention of 'gestures' steps (no targets) in the mind of an actor.
social::MRef add_plan(NpcBundle& m, std::initializer_list<Gesture> steps, social::GameTime now = 0) {
  std::vector<std::uint32_t> words, targets;
  for (Gesture g : steps) { words.push_back(word_of(g)); targets.push_back(0); }
  social::gen::Intention rec;
  rec.i_steps = m.side.put(words);
  rec.i_step_targets = m.side.put(targets);
  rec.i_status = 0;
  return m.state.intention_records.add(rec, now);
}

}  // namespace

// ---- the generated timing table ----------------------------------------------------------------------------------------

TEST(timing_table_is_the_catalogue) {
  CHECK_EQ(timing_gen::kGestureTiming.size(), std::size_t(40));
  CHECK_EQ(timing_gen::kDurationLevels.size(), std::size_t(3));
  CHECK_EQ(duration_level_game_s(kLevelBrief), 120);
  CHECK_EQ(duration_level_game_s(kLevelAWhile), 1800);
  CHECK_EQ(duration_level_game_s(kLevelLong), 7200);
  CHECK_EQ(timing_of(Gesture::strike).cadence_ms, 900);
  CHECK_EQ(timing_of(Gesture::go).cadence_ms, 800);
  CHECK(timing_of(Gesture::go).natural_end && !timing_of(Gesture::strike).natural_end);
  int productive = 0;
  for (std::size_t i = 0; i < 40; ++i) {
    const GestureTiming& t = timing_of(static_cast<Gesture>(i));
    CHECK(t.cadence_ms >= 250 && t.cadence_ms <= 2000);
    productive += t.productive;
  }
  CHECK_EQ(productive, 6);   // operate, scoop, work, tie, shape, channel
  CHECK(timing_of(Gesture::work).productive && !timing_of(Gesture::strike).productive);
  // `until` is the parameter of exactly strike, grab, sleep, wait.
  for (std::size_t i = 0; i < 40; ++i) {
    const Gesture g = static_cast<Gesture>(i);
    const bool expected = g == Gesture::strike || g == Gesture::grab || g == Gesture::sleep || g == Gesture::wait;
    CHECK(timing_of(g).has_until == expected);
  }
  CHECK(timing_of(Gesture::rest).has_duration && timing_of(Gesture::work).has_duration && timing_of(Gesture::search).has_duration);
  // A cycle clock keeps the remainder: 900 ms cycles over 9 ticks of 1000 ms are exactly 10 cycles.
  CycleClock c;
  std::uint32_t n = 0;
  for (int i = 0; i < 9; ++i) n += c.advance(900);
  CHECK_EQ(n, 10u);
  CHECK_EQ(c.remainder_ms(), 0u);
  IngestTable table(MatterCatalog{});
  MatterCatalog cat;
  CHECK(table.nutrition(cat.find_item("bread_loaf")) == 7 && table.hydration(cat.find_item("water_jug")) == 7);
}

// ---- movement -----------------------------------------------------------------------------------------------------------

TEST(go_walks_at_real_speed_and_ends_on_arrival) {
  Rig r;
  const EntityId a = r.person(kOrigin);
  Dec d(a, Gesture::go);
  d.with("relation", "toward").with("pace", "walk").destination({100000, 0, 0}).given("target");
  CHECK(r.start(d).status == BeginStatus::Started);
  const int ticks = r.run(a);
  const ExecutionReport* rep = r.report_of(a);
  CHECK(rep && rep->outcome == ExecOutcome::Done);
  // 100 m at 1.3 m/s = 77 s of real time = 77 ticks (docs/14 4.4: 1 km is about 12 min 50 s).
  CHECK(ticks >= 76 && ticks <= 80);
  const Position p = r.w.store.position_mm(a);
  CHECK(p[0] >= 99000 && p[0] <= 100000);
  CHECK(r.ex->stats().ended[0] == 1);
}

TEST(run_is_faster_than_walk_and_sets_the_exertion) {
  Rig r;
  const EntityId a = r.person(kOrigin), b = r.person({0, 50000, 0});
  Dec da(a, Gesture::go), db(b, Gesture::go);
  da.with("pace", "walk").destination({60000, 0, 0}).given("target");
  db.with("pace", "run").destination({60000, 50000, 0}).given("target");
  r.start(da);
  r.start(db);
  bool saw_running = false, saw_walking = false;
  int ta = 0, tb = 0;
  for (int i = 0; i < 100 && (r.ex->busy(a) || r.ex->busy(b)); ++i) {
    const StepOutput& o = r.tick();
    for (const ExertionFact& x : o.exertion) {
      saw_running |= x.npc == b && x.exertion == social::Exertion::kRunning;
      saw_walking |= x.npc == a && x.exertion == social::Exertion::kWalking;
    }
    if (r.ex->busy(a)) ++ta;
    if (r.ex->busy(b)) ++tb;
  }
  CHECK(saw_running && saw_walking && tb < ta);
}

// ---- grasping ------------------------------------------------------------------------------------------------------------

TEST(take_put_give_move_things_through_operations) {
  Rig r;
  const EntityId a = r.person(kOrigin), b = r.person({1000, 0, 0});
  const EntityId knife = r.w.spawn_item("knife", {800, 0, 0});
  Dec take(a, Gesture::take);
  take.target(knife);
  CHECK(r.start(take).status == BeginStatus::Started);
  r.run(a);
  std::printf("  take: outcome %s cause %d\n", to_string(r.report_of(a)->outcome), int(r.report_of(a)->cause));
  CHECK(r.report_of(a)->outcome == ExecOutcome::Done);
  CHECK(r.w.store.holder(knife) == a);
  Dec give(a, Gesture::give);
  give.target(knife).other(b);
  r.start(give);
  r.run(a);
  CHECK(r.report_of(a)->outcome == ExecOutcome::Done && r.w.store.holder(knife) == b);
  // b puts it down on the ground at its feet.
  Dec put(b, Gesture::put);
  put.target(knife);
  r.start(put);
  r.run(b);
  CHECK(r.w.store.holder(knife) == kNoEntity && r.report_of(b)->outcome == ExecOutcome::Done);
  // A thing nobody can lift is not taken: a failure the actor feels on the spot.
  r.w.catalog.set_profile(EntityKind::structure, 4, [] { Profile p; p.mass_g = 3000000; p.size = {1000, 1000, 1000}; return p; }());
  const EntityId rock = r.w.spawn(EntityKind::structure, {600, 0, 0}, 4);
  Dec heavy(a, Gesture::take);
  heavy.target(rock);
  r.start(heavy);
  r.run(a);
  CHECK(r.report_of(a)->outcome == ExecOutcome::Failed && r.report_of(a)->cause == Cause::NotLiftable);
  CHECK(r.w.store.holder(rock) == kNoEntity);
}

// ---- striking: contact -> law -> operation -------------------------------------------------------------------------------

TEST(strike_makes_contacts_and_the_law_of_matter_does_the_rest) {
  Rig r;
  const EntityId a = r.person(kOrigin);
  const EntityId axe = r.w.spawn_item("battle_axe", kOrigin);
  const EntityId log = r.w.spawn_item("log", {1200, 0, 0});
  r.w.bus.submit(make_move(++r.w.tick, 1, axe, kOrigin, a));
  r.w.bus.flush();
  const std::size_t planks_before = r.w.count_sort(r.w.item("plank"));
  Dec d(a, Gesture::strike);
  d.target(log).tool(axe).with("intensity", "hard").with("motion", "swing").until(Condition::c_target_gone, log);
  d.raw().manner = Manner::Strike;
  CHECK(r.start(d).status == BeginStatus::Started);
  const int ticks = r.run(a);
  CHECK(ticks >= 1 && ticks < 10);
  CHECK(!r.w.store.alive(log));                                       // the split law fired, through the bus
  CHECK(r.w.count_sort(r.w.item("plank")) > planks_before);
  CHECK(r.report_of(a)->outcome == ExecOutcome::Done);                // until c_target_gone held: seen from the dossier
  CHECK(r.ex->stats().contacts >= 1);
}

// ---- eating and drinking: an operation reaches NpcLaws -------------------------------------------------------------------

TEST(eat_and_drink_lower_the_needs_through_operations_and_npc_laws_goes_on) {
  Rig r;
  const EntityId a = r.person(kOrigin);
  NpcBundle& mind = *r.minds.mind(a);
  r.set(a, "hunger", 60);
  r.set(a, "thirst", 50);
  mind.state.needs.hunger = 60;
  mind.state.needs.thirst = 50;
  const EntityId bread = r.w.spawn_item("bread_loaf", kOrigin);
  const EntityId jug = r.w.spawn_item("water_jug", kOrigin);
  r.w.bus.submit(make_move(++r.w.tick, 1, bread, kOrigin, a));
  r.w.bus.submit(make_move(++r.w.tick, 1, jug, kOrigin, a));
  r.w.bus.flush();
  Dec eat(a, Gesture::eat);
  eat.target(bread).with("amount", "all");
  r.start(eat);
  const int ticks = r.run(a);
  CHECK(r.report_of(a)->outcome == ExecOutcome::Done);
  CHECK(ticks >= 3);                                            // three portions of 1.2 s
  CHECK_EQ(r.get(a, "hunger"), 60 - 7 * kTenthsPerFoodPoint);   // nutrition 7 -> 21 tenths
  CHECK_EQ(mind.state.needs.hunger, 60 - 7 * kTenthsPerFoodPoint);   // mirrored into the dossier by the operation
  CHECK(!r.w.store.alive(bread));
  Dec drink(a, Gesture::drink);
  drink.target(jug).with("amount", "some");
  r.start(drink);
  r.run(a);
  CHECK_EQ(r.get(a, "thirst"), 50 - 7 * kTenthsPerFoodPoint * 2 / 3);
  CHECK(r.w.store.alive(jug));                                  // 'some' does not finish the jug
  // NpcLaws::step goes on from the state the gesture left (standing for one tick: hunger rises a little, never jumps back).
  social::NpcLaws::Residue res;
  social::LawEnvironment env;
  env.now = 100016;
  const auto before = mind.state.needs.hunger;
  social::NpcLaws::step(mind.state, res, env, social::NpcLaws::kTickS);
  CHECK(mind.state.needs.hunger >= before && mind.state.needs.hunger <= before + 2);
  mind.state.body.alive = true;   // (the bare state of this test is not a living NPC: put it back for the rest)
  mind.state.body.consciousness = 100;
  // A thing that cannot be eaten does nothing and the actor perceives it.
  const EntityId knife = r.w.spawn_item("knife", kOrigin);
  r.w.bus.submit(make_move(++r.w.tick, 1, knife, kOrigin, a));
  r.w.bus.flush();
  Dec bad(a, Gesture::eat);
  bad.target(knife).with("amount", "little");
  r.start(bad);
  r.run(a);
  std::printf("  eat knife: outcome %s cause %d\n", to_string(r.report_of(a)->outcome), int(r.report_of(a)->cause));
  CHECK(r.report_of(a)->outcome == ExecOutcome::Failed && r.report_of(a)->cause == Cause::NothingHappened);
}

// ---- stop conditions and their order -------------------------------------------------------------------------------------

TEST(stop_order_until_then_decision_head_then_natural_end_then_a_while) {
  Rig r;
  Script s;
  r.use(s);
  const EntityId a = r.person(kOrigin), t = r.person({1000, 0, 0});
  s.seen[t] = PerceivedThing{true, {1000, 0, 0}, 1000};
  // (1) strike: `until c_done` ends after ONE blow although the head of the decision says "target gone".
  Dec d1(a, Gesture::strike);
  d1.target(t).with("intensity", "light").until(Condition::c_done).stop(Condition::c_target_gone, t);
  r.start(d1);
  r.run(a);
  CHECK(r.report_of(a)->outcome == ExecOutcome::Done && r.report_of(a)->cycles == 1);
  // (2) look has no `until`: the head of the decision stops it.
  Dec d2(a, Gesture::look);
  d2.target(t).stop(Condition::c_elapsed, 0, 90);
  r.start(d2);
  const int n2 = r.run(a);
  CHECK(r.report_of(a)->outcome == ExecOutcome::Done);
  CHECK(n2 >= 5 && n2 <= 7);   // 90 s of game = 5.6 ticks
  // (3) natural_end: a single touch ends by itself.
  Dec d3(a, Gesture::examine);
  d3.target(t);
  r.start(d3);
  r.run(a);
  CHECK(r.report_of(a)->outcome == ExecOutcome::Done && r.report_of(a)->cycles == 1);
  // (4) nothing stops a look: a_while (1 800 game s = 113 ticks) -> limit_reached, which decides nothing.
  Dec d4(a, Gesture::look);
  d4.target(t);
  r.start(d4);
  const int n4 = r.run(a);
  CHECK(r.report_of(a)->outcome == ExecOutcome::LimitReached);
  CHECK(n4 >= 112 && n4 <= 114);
  // A chosen duration is the bound the model asked for: reaching it is "done".
  Dec d5(a, Gesture::rest);
  d5.with("duration", "brief");
  r.start(d5);
  const int n5 = r.run(a);
  CHECK(r.report_of(a)->outcome == ExecOutcome::Done);
  CHECK(n5 >= 7 && n5 <= 9);   // 120 s of game = 7.5 ticks
  // A decision with a stop head does not get the a_while bound: only the condition (or an interruption) ends it.
  Dec d6(a, Gesture::look);
  d6.target(t).stop(Condition::c_target_down, t);
  r.start(d6);
  const int n6 = r.run(a, 300);
  CHECK(n6 == 300 && r.ex->busy(a));
}

TEST(every_condition_of_the_catalogue_is_read_in_the_perception_of_the_actor) {
  Rig r;
  Script s;
  r.use(s);
  const EntityId a = r.person(kOrigin), t = r.person({1000, 0, 0}), tool = r.w.spawn_item("knife", kOrigin);
  NpcBundle& mind = *r.minds.mind(a);
  auto run_stop = [&](Condition c, EntityId e = 0, std::int32_t q = 0, std::uint32_t w = 0, int max_ticks = 6) {
    Dec d(a, Gesture::wait);
    d.until(c, e, q, w);
    d.raw().until->at = {0, 0, 0};
    r.start(d);
    const int n = r.run(a, max_ticks);
    const bool ended = !r.ex->busy(a) && r.report_of(a) && r.report_of(a)->outcome == ExecOutcome::Done;
    if (!ended) { r.ex->begin(Dec(a, Gesture::stop).get(), r.now, r.w.tick + 1); r.run(a); }
    return std::pair<bool, int>(ended, n);
  };
  // False before, true after, for each condition.
  CHECK(!run_stop(Condition::c_target_down, t).first);
  s.seen[t].in_view = true; s.seen[t].down = true;
  CHECK(run_stop(Condition::c_target_down, t).first);
  s.seen[t].down = false; s.seen[t].still = true;
  CHECK(run_stop(Condition::c_target_still, t).first);
  s.seen[t].still = false; s.seen[t].yields = true;
  CHECK(run_stop(Condition::c_target_yields, t).first);
  s.seen[t].yields = false; s.seen[t].dist_mm = 1000;
  CHECK(run_stop(Condition::c_target_near, t).first);       // c_target_near
  s.seen[t].dist_mm = 9000;
  CHECK(!run_stop(Condition::c_target_near, t).first);
  CHECK(run_stop(Condition::c_sees_ref, t).first);
  CHECK(!run_stop(Condition::c_target_gone, t).first);
  s.seen.erase(t);
  CHECK(run_stop(Condition::c_target_gone, t).first);
  CHECK(!run_stop(Condition::c_attacked).first);
  s.is_attacked = true;
  CHECK(run_stop(Condition::c_attacked).first);
  s.is_attacked = false;
  CHECK(!run_stop(Condition::c_addressed).first);
  s.is_addressed = true;
  CHECK(run_stop(Condition::c_addressed).first);
  s.is_addressed = false;
  CHECK(!run_stop(Condition::c_stopped).first);
  s.is_stopped = true;
  CHECK(run_stop(Condition::c_stopped).first);
  s.is_stopped = false;
  CHECK(!run_stop(Condition::c_sees, 0, 0, 77).first);
  s.kinds.insert(77);
  CHECK(run_stop(Condition::c_sees, 0, 0, 77).first);
  CHECK(!run_stop(Condition::c_hears, 0, 0, 5).first);
  s.concepts.insert(5);
  CHECK(run_stop(Condition::c_hears, 0, 0, 5).first);
  CHECK(!run_stop(Condition::c_state_seen, t, 0, 9).first);
  s.states.insert({t, 9});
  CHECK(run_stop(Condition::c_state_seen, t, 0, 9).first);
  // c_have: at least N things seen in the hands or believed in a container.
  s.held = 1;
  CHECK(!run_stop(Condition::c_have, 0, 2, 3).first);
  s.held = 2;
  CHECK(run_stop(Condition::c_have, 0, 2, 3).first);
  // c_unwatched: nobody seems to look at me.
  s.is_unwatched = false;
  CHECK(!run_stop(Condition::c_unwatched).first);
  s.is_unwatched = true;
  CHECK(run_stop(Condition::c_unwatched).first);
  // The body: pain, hunger, thirst, exhaustion, rest, hands.
  mind.state.body.pain = 50;
  CHECK(!run_stop(Condition::c_pain_above, 0, 60).first);
  CHECK(run_stop(Condition::c_pain_above, 0, 40).first);
  mind.state.needs.hunger = 70;
  CHECK(run_stop(Condition::c_hunger_above, 0, 60).first && !run_stop(Condition::c_hunger_above, 0, 80).first);
  mind.state.needs.thirst = 70;
  CHECK(run_stop(Condition::c_thirst_above, 0, 60).first && !run_stop(Condition::c_thirst_above, 0, 80).first);
  mind.state.needs.exhaustion = 70;
  CHECK(run_stop(Condition::c_exhausted, 0, 60).first && !run_stop(Condition::c_exhausted, 0, 80).first);
  mind.state.needs.sleepiness = 90;
  CHECK(!run_stop(Condition::c_rested).first);
  mind.state.needs.sleepiness = 0;
  mind.state.needs.exhaustion = 0;
  CHECK(run_stop(Condition::c_rested).first);
  CHECK(!run_stop(Condition::c_hands_full).first);
  mind.state.carrier.load_ratio = 1000;
  CHECK(run_stop(Condition::c_hands_full).first);
  // Time: elapsed seconds, and the clock of the day.
  CHECK(run_stop(Condition::c_elapsed, 0, 32, 0, 6).first);
  CHECK(!run_stop(Condition::c_elapsed, 0, 5000, 0, 6).first);
  // c_reached: the place is where the actor stands.
  CHECK(run_stop(Condition::c_reached).first);
  // c_done: once.  c_tool_broken: the tool in hand is gone.
  Dec dt(a, Gesture::work);
  dt.target(t).tool(tool).with("duration", "long").until(Condition::c_tool_broken);   // `work` has no until: the head would; use stop
  Dec dt2(a, Gesture::look);
  dt2.stop(Condition::c_tool_broken);
  dt2.raw().tool = tool;
  r.start(dt2);
  r.run(a, 3);
  CHECK(r.ex->busy(a));
  r.w.bus.submit(make_destroy(++r.w.tick, 1, tool));
  r.w.bus.flush();
  r.run(a, 3);
  CHECK(!r.ex->busy(a) && r.report_of(a)->outcome == ExecOutcome::Done);
  // c_time: the first time the clock of the day reaches the hour (here 2 h of game later).
  Dec dc(a, Gesture::wait);
  dc.until(Condition::c_time);
  dc.raw().until->time = (r.now % 86400) + 7200;
  r.start(dc);
  const int nt = r.run(a, 1000);
  CHECK(!r.ex->busy(a) && nt >= 449 && nt <= 451);   // 7 200 s = 450 ticks
}

// ---- interruption -------------------------------------------------------------------------------------------------------

TEST(a_blow_interrupts_but_a_p0_wake_stops_nothing) {
  Rig r;
  Script s;
  r.use(s);
  const EntityId a = r.person(kOrigin);
  Dec d(a, Gesture::work);
  d.with("duration", "long").destination({0, 0, 0});
  d.raw().target = 0;
  r.start(d);
  r.run(a, 3);
  CHECK(r.ex->busy(a));
  CHECK(!r.ex->on_wake(a, perception::WakePriority::P0));   // calls the model; the execution goes on
  CHECK(!r.ex->on_wake(a, perception::WakePriority::P1));
  r.tick();
  CHECK(r.ex->busy(a) && r.ex->find(a)->phase == Phase::Perform);
  r.ex->notify(a, BodyEvent::Blow);   // hit_react
  r.tick();
  CHECK(!r.ex->busy(a));
  const ExecutionReport* rep = r.report_of(a);
  CHECK(rep && rep->outcome == ExecOutcome::Interrupted && rep->cause == Cause::Blow);
  // Unconsciousness (the dossier) interrupts as well.
  Dec d2(a, Gesture::look);
  d2.stop(Condition::c_elapsed, 0, 99999);
  r.start(d2);
  r.tick();
  r.minds.mind(a)->state.body.consciousness = 5;
  r.tick();
  CHECK(!r.ex->busy(a) && r.report_of(a)->cause == Cause::Unconscious);
}

// ---- P51: a gesture fails only on the spot -------------------------------------------------------------------------------

TEST(a_target_moved_out_of_sight_fails_the_gesture_only_once_on_the_spot) {
  Rig r;
  r.eyes.set_range(20000);   // the actor sees 20 m
  const EntityId a = r.person(kOrigin);
  NpcBundle& mind = *r.minds.mind(a);
  const EntityId item = r.w.spawn_item("knife", {100000, 0, 0});   // 100 m away: out of sight
  const social::MRef plan = add_plan(mind, {Gesture::take, Gesture::go});
  Dec d(a, Gesture::take);
  d.target(item).believed({100000, 0, 0}).plan(plan);
  CHECK(r.start(d).status == BeginStatus::Started);
  // The item is moved far away (out of sight of everything) while the actor walks to where it BELIEVES it is.
  r.w.bus.submit(make_move(++r.w.tick, 1, item, {500000, 0, 0}, kNoEntity));
  r.w.bus.flush();
  int fail_tick = -1, arrive_tick = -1;
  for (int i = 0; i < 400 && r.ex->busy(a); ++i) {
    r.tick();
    const Position p = r.w.store.position_mm(a);
    if (arrive_tick < 0 && p[0] >= 100000 - kReachMm) arrive_tick = i;
    if (!r.ex->busy(a)) fail_tick = i;
    // Never a failure while far from the believed place.
    if (!r.ex->busy(a)) CHECK(p[0] >= 100000 - kReachMm - 1);
  }
  const ExecutionReport* rep = r.report_of(a);
  CHECK(rep && rep->outcome == ExecOutcome::Failed && rep->cause == Cause::TargetAbsent);
  CHECK(arrive_tick > 50 && fail_tick >= arrive_tick);   // it walked the whole way first
  CHECK_EQ(rep->attempts, 1);
  const auto* rec = mind.state.intention_records.find(plan);
  CHECK(rec && rec->i_status == 2 && rec->i_attempts == 1000);   // blocked, one attempt: a fact, not a verdict
  CHECK(rec->i_step_index == 0);                                 // the step is not over
}

TEST(a_closed_route_is_discovered_only_when_it_comes_into_sight) {
  FlatNavigation nav(15000);
  nav.cut({60000, 0, 0}, 3000);
  Rig r(1, std::move(nav));
  const EntityId a = r.person(kOrigin);
  Dec d(a, Gesture::go);
  d.with("pace", "walk").destination({120000, 0, 0}).given("target");
  r.start(d);
  int ticks = 0;
  while (r.ex->busy(a) && ticks < 300) { r.tick(); ++ticks; }
  const ExecutionReport* rep = r.report_of(a);
  CHECK(rep && rep->outcome == ExecOutcome::Blocked && rep->cause == Cause::PathBlocked);
  const Position p = r.w.store.position_mm(a);
  CHECK(p[0] > 60000 - 3000 - 15000 - 2000 && p[0] < 60000 - 3000);   // stopped within sight of the cut, not before
  CHECK(ticks > 25);                                                  // it did walk until it saw the obstacle
}

// ---- plan facts -----------------------------------------------------------------------------------------------------------

TEST(the_plan_record_gets_facts_only) {
  Rig r;
  const EntityId a = r.person(kOrigin);
  NpcBundle& mind = *r.minds.mind(a);
  const social::MRef plan = add_plan(mind, {Gesture::go, Gesture::look});
  const social::MRef other = add_plan(mind, {Gesture::eat});
  mind.state.intention_records.find(other)->i_status = 0;   // running
  Dec d(a, Gesture::go);
  d.with("pace", "walk").destination({20000, 0, 0}).given("target").plan(plan);
  r.start(d);
  const auto* rec = mind.state.intention_records.find(plan);
  CHECK(rec->i_status == 0 && rec->i_step_started == r.now);        // running: the gesture IS PLAN.next
  CHECK(mind.state.intention_records.find(other)->i_status == 1);   // the other running plan is suspended
  int last = -1;
  bool monotonic = true;
  while (r.ex->busy(a)) {
    r.tick();
    if (r.ex->busy(a)) { monotonic &= rec->i_step_progress >= last; last = rec->i_step_progress; }
  }
  CHECK(monotonic && last > 0 && last < 1000);
  CHECK_EQ(rec->i_step_progress, 1000);
  CHECK_EQ(rec->i_step_index, 1000);   // the step is over: PLAN.next is now `look`
  CHECK(rec->i_status == 0 && rec->i_attempts == 0);
  // The second step is the last: the plan is done (a fact: the steps are used up), not "goal reached".
  Dec d2(a, Gesture::look);
  d2.stop(Condition::c_done).plan(plan);
  r.start(d2);
  r.run(a);
  CHECK(rec->i_status == 3 && rec->i_step_index == 2000);
  // Choosing another gesture than PLAN.next suspends the running plan.
  const social::MRef p3 = add_plan(mind, {Gesture::eat});
  Dec d3(a, Gesture::look);
  d3.stop(Condition::c_done);
  r.start(d3);
  r.run(a);
  CHECK(mind.state.intention_records.find(p3)->i_status == 1);
}

// ---- the five outcomes and the governor ---------------------------------------------------------------------------------

TEST(outcomes_are_execution_facts_and_the_governor_refuses_properly) {
  Rig r;
  const EntityId a = r.person(kOrigin), child = r.person({600, 0, 0});
  // D10: a romantic touch of a child is refused before anything runs.
  Dec d(a, Gesture::touch);
  d.target(child).with("with", "hand").with("contact_zone", "hands").with("manner", "romantic").with("duration", "brief");
  d.raw().call.party[0] = nullptr;
  social::Party kid{90, 90, 90, true};
  const GestureDecision& g = d.get();
  GestureDecision refused = g;
  refused.call.party[static_cast<std::size_t>(param_index(Gesture::touch, "target"))] = &kid;
  refused.actor_party = r.adult;
  const BeginResult br = r.ex->begin(refused, r.now, r.w.tick + 1);
  CHECK(br.status == BeginStatus::Refused && !br.verdict.allowed);
  CHECK(!r.ex->busy(a));
  const StepOutput& o = r.tick();
  CHECK(o.emissions.empty() && o.contacts.empty());
  CHECK(o.reports.size() == 1 && o.reports[0].refused && o.reports[0].outcome == ExecOutcome::Failed && o.reports[0].cause == Cause::Refused);
  CHECK(o.reports[0].refusal == br.verdict.reason);
  // An unidentified person counts as a possible minor: the same deny-by-default.
  GestureDecision unknown = refused;
  unknown.call.party[static_cast<std::size_t>(param_index(Gesture::touch, "target"))] = nullptr;
  CHECK(r.ex->begin(unknown, r.now, r.w.tick + 1).status == BeginStatus::Refused);
  // The same touch, gentle, of an adult is carried out.
  const EntityId friend_ = r.person({800, 0, 0});
  Dec ok(a, Gesture::touch);
  ok.target(friend_).with("with", "hand").with("contact_zone", "hands").with("manner", "gentle").with("duration", "brief");
  CHECK(r.start(ok).status == BeginStatus::Started);
  r.run(a);
  CHECK(r.report_of(a)->outcome == ExecOutcome::Done);
  // The five outcomes of w_outcome all exist and none says "goal reached".
  CHECK(std::string(to_string(ExecOutcome::Done)) == "done" && std::string(to_string(ExecOutcome::Failed)) == "failed");
  CHECK(std::string(to_string(ExecOutcome::Blocked)) == "blocked" && std::string(to_string(ExecOutcome::Interrupted)) == "interrupted");
  CHECK(std::string(to_string(ExecOutcome::LimitReached)) == "limit_reached");
  // A gesture of an actor that does not exist is invalid, not refused.
  GestureDecision ghost = refused;
  ghost.actor = 123456;
  CHECK(r.ex->begin(ghost, r.now, 1).status == BeginStatus::Invalid);
}

// ---- time: kTaskCompression and the felling of an oak --------------------------------------------------------------------

TEST(felling_an_oak_takes_125_blows_and_about_two_real_minutes) {
  Rig r;
  r.fell_sink = true;
  const EntityId a = r.person(kOrigin);
  const EntityId axe = r.w.spawn_item("felling_axe", kOrigin);
  r.w.bus.submit(make_move(++r.w.tick, 1, axe, kOrigin, a));
  r.w.bus.flush();
  Profile tree;
  tree.mass_g = 600000; tree.size = {600, 9000, 600}; tree.parts = {{rig::form_of("lump"), r.w.catalog.find_material("oak_raw")}};
  r.w.catalog.set_profile(EntityKind::plant, 1, tree);
  const EntityId oak = r.w.spawn(EntityKind::plant, {1200, 0, 0}, 1);
  r.felling[oak] = 2000;   // 2 000 blows of real-life work (docs/14 4.4: 125 blows x kTaskCompression 16)
  Dec d(a, Gesture::work);
  d.target(oak).tool(axe).with("motion", "saw").with("intensity", "firm").with("duration", "long").stop(Condition::c_target_gone, oak);
  CHECK(r.start(d).status == BeginStatus::Started);
  const int ticks = r.run(a, 2000);
  const ExecutionReport* rep = r.report_of(a);
  CHECK(rep && rep->outcome == ExecOutcome::Done && !r.w.store.alive(oak));
  // docs/14 4.4: about 125 blows of 900 ms = 112.5 s of real time = 1 800 s of game time. Within 20 %.
  CHECK(rep->cycles >= 100 && rep->cycles <= 150);
  CHECK(ticks >= 90 && ticks <= 135);
  const std::int64_t game_s = rep->ended - rep->started;
  CHECK(game_s >= 1440 && game_s <= 2160);
  std::printf("  oak: %u blows, %d real s, %lld game s\n", rep->cycles, ticks, static_cast<long long>(game_s));
}

TEST(kTaskCompression_applies_to_productive_gestures_only) {
  // The same 2 000 units of work: a productive gesture needs 16 times fewer cycles than a non-productive one.
  auto cycles_for = [](Gesture g, std::string_view motion_param, std::string_view motion) {
    Rig r;
    r.fell_sink = true;
    const EntityId a = r.person(kOrigin);
    const EntityId tool = r.w.spawn_item("felling_axe", kOrigin);
    r.w.bus.submit(make_move(++r.w.tick, 1, tool, kOrigin, a));
    r.w.bus.flush();
    const EntityId block = r.w.spawn_item("log", {1000, 0, 0});
    r.felling[block] = 800;
    Dec d(a, g);
    d.target(block).tool(tool).with("intensity", "firm").with("duration", "long").stop(Condition::c_target_gone, block);
    if (!motion_param.empty()) d.with(motion_param, motion);
    r.start(d);
    r.run(a, 3000);
    return r.report_of(a) ? r.report_of(a)->cycles : 0u;
  };
  const std::uint32_t productive = cycles_for(Gesture::work, "motion", "saw");
  const std::uint32_t plain = cycles_for(Gesture::strike, "", "");
  CHECK_EQ(productive, 50u);          // 800 / 16
  CHECK_EQ(plain, 800u);
  CHECK_EQ(plain, productive * static_cast<std::uint32_t>(kTaskCompression));
  CHECK(compressed_work(5, true) == 80 && compressed_work(5, false) == 5);
}

// ---- perception: looking, listening, speaking ------------------------------------------------------------------------------

namespace {
struct PerceptionRig {
  Rig r;
  perception::FlatSpace space;
  perception::CatalogueThings things;
  std::unique_ptr<perception::PerceptionEngine> eng;
  std::vector<perception::Observer> observers;
  PerceptionRig() {
    perception::PerceptionConfig cfg;
    eng = std::make_unique<perception::PerceptionEngine>(r.w.store, space, things, cfg);
  }
  void see(std::vector<EntityId> who) {
    observers.clear();
    for (EntityId e : who) observers.emplace_back(e, *r.minds.mind(e));
  }
  const perception::PerceptionReport& perceive() { return eng->tick(observers, r.now); }
};
constexpr social::GameTime kDayT = 1000 * 16;
}  // namespace

TEST(looking_turns_the_head_so_that_the_perception_sees_what_was_behind) {
  PerceptionRig p;
  const EntityId a = p.r.person(kOrigin), t = p.r.person({-6000, 0, 0});   // behind the actor (it faces +x)
  p.r.now = kDayT;
  p.see({a});
  ObserverSenses senses(p.r.w.store, p.observers);
  p.r.use(senses);
  p.perceive();
  CHECK(!senses.perceive(a, t).in_view);                                   // not seen from behind
  Dec d(a, Gesture::look);
  d.target(t).believed({-6000, 0, 0}).with("mode", "watch").stop(Condition::c_elapsed, 0, 48);
  p.r.start(d);
  int acts = 0;
  p.r.tick();                                                               // the facing delta goes through the bus
  for (const Emission& e : p.r.last_emissions) acts += e.op.op_kind() == ops::OpKind::Act && e.op.gesture == static_cast<std::uint16_t>(Gesture::look);
  p.r.now = kDayT;
  p.perceive();
  CHECK(senses.perceive(a, t).in_view);                                    // looking is what made it visible
  CHECK(p.r.get(a, "orientation") > 2500 || p.r.get(a, "orientation") < -2500);
  // The gaze itself is an Act operation that witnesses perceive.
  CHECK(acts >= 1);
}

TEST(speaking_reaches_the_speech_router_through_the_perception) {
  PerceptionRig p;
  const EntityId a = p.r.person(kOrigin), b = p.r.person({1500, 0, 0});
  p.r.now = kDayT;
  p.see({a, b});
  ObserverSenses senses(p.r.w.store, p.observers);
  p.r.use(senses);
  p.perceive();
  // The speaker's content lives in ITS arena; the executor carries only the reference.
  social::NpcBundle& mind_a = *p.r.minds.mind(a);
  social::NpcBundle& mind_b = *p.r.minds.mind(b);
  const social::Parser parser;
  social::Proposition prop;
  social::gen::Relation victim;   // a person the speaker knows by the name 5 (his own file, never the truth)
  victim.r_name_believed = 5;
  victim.r_id_certainty = 90;
  const social::MRef file = mind_a.state.relation_records.add(victim, 0);
  const social::TypedExpression said = parser.parse("(assert (dead @E" + std::to_string(file.serial) + "))");
  CHECK(said.ok() && said.to_proposition(prop) == social::ConvertStatus::ok);
  const std::uint32_t content = mind_a.store_proposition(prop, 100);
  Dec d(a, Gesture::speak);
  d.target(b).with("volume", "normal").with("tone", "calm").content(content);
  CHECK(p.r.start(d).status == BeginStatus::Started);
  perception::ActEvent ev;
  bool found = false;
  for (int i = 0; i < 4 && !found; ++i) {
    p.r.tick();
    for (const Emission& e : p.r.last_emissions)
      if (e.op.op_kind() == ops::OpKind::Act) {
        CHECK(e.op.flags & ops::kFlagSpeech);
        CHECK(e.op.gesture == static_cast<std::uint16_t>(Gesture::speak));
        CHECK(e.op.noise == kVolumeNoise[2]);
        found = perception::decode_act(e.op, p.r.w.store, ev);
      }
  }
  CHECK(found && ev.speech && ev.content == content && ev.target == b);
  // The act reaches the listener through the perception, which hands it to the router.
  p.r.now = kDayT;
  p.eng->submit(ev);
  const perception::PerceptionReport& rep = p.perceive();
  CHECK(rep.speech.size() == 1 && rep.speech[0].listener == b && rep.speech[0].speaker == a && rep.speech[0].addressed);
  // ... and the router writes a HEARD belief in the listener's mind (told, one hop), never the truth of who said it.
  struct RouterWorld final : social::SpeechWorld {
    Minds* minds;
    social::NpcBundle* mind(EntityId who) const override { return minds->mind(who); }
    social::MRef file_of(EntityId, EntityId) const override { return {}; }
    social::Party party_seen_by(EntityId, EntityId) const override { return social::Party{300, 300, 310, true, true, true}; }
  } world;
  world.minds = &p.r.minds;
  social::SpeechRouter router(world);
  std::vector<social::HeardUtterance> heard;
  for (const perception::HeardSpeech& h : rep.speech)
    heard.push_back({h.listener, h.speaker, h.content, h.clarity, h.addressed, h.intelligible, h.when});
  const social::SpeechReport& sr = router.route(heard);
  CHECK(sr.stats.deliveries == 1 && sr.refusals.empty());
  int beliefs = 0;
  mind_b.state.belief_records.for_each([&](social::MRef, social::gen::Belief& be) { ++beliefs; CHECK(be.b_source == 2 && be.b_hops == 1000); });
  CHECK_EQ(beliefs, 1);
}

// ---- the 40 gestures: the state machine ----------------------------------------------------------------------------------

TEST(the_state_machine_runs_all_40_gestures_to_an_end) {
  int started = 0, ended = 0;
  std::map<std::string, ExecOutcome> outcome;
  for (std::size_t gi = 0; gi < 40; ++gi) {
    const Gesture g = static_cast<Gesture>(gi);
    Rig r;
    const EntityId a = r.person(kOrigin), t = r.person({1200, 0, 0});
    const EntityId knife = r.w.spawn_item("knife", {200, 0, 0}), bread = r.w.spawn_item("bread_loaf", {300, 0, 0});
    const EntityId jug = r.w.spawn_item("water_jug", {400, 0, 0});
    for (EntityId e : {knife, bread, jug}) r.w.bus.submit(make_move(++r.w.tick, 1, e, kOrigin, a));
    r.w.bus.flush();
    Dec d(a, g);
    // Plausible values: the first value of every enum, a person as the first ref, an item as the second.
    const auto& spec = social::gen::kGestures[gi];
    for (int p = 0; p < spec.n_params; ++p) {
      const auto& ps = spec.params[static_cast<std::size_t>(p)];
      if (ps.type == social::gen::ParamType::enum_ && !ps.optional) d.raw().call.value[static_cast<std::size_t>(p)] = 0;
    }
    switch (g) {
      case Gesture::go: d.destination({20000, 0, 0}).given("target"); break;
      case Gesture::climb: case Gesture::swim: d.destination({5000, 0, 0}).given("target"); break;
      case Gesture::jump: d.destination({5000, 0, 0}); break;
      case Gesture::mount: d.target(t); break;
      case Gesture::eat: d.target(bread); break;
      case Gesture::drink: d.target(jug); break;
      case Gesture::give: d.target(knife).other(t); break;
      case Gesture::put: d.target(knife).destination({100, 0, 0}); break;
      case Gesture::throw_: d.target(knife).other(t); break;
      case Gesture::pour: d.target(jug).other(t); break;
      case Gesture::wear: d.target(knife); break;
      case Gesture::pull: case Gesture::push: case Gesture::take: case Gesture::touch: case Gesture::grab: case Gesture::examine:
      case Gesture::search: case Gesture::speak: case Gesture::operate: case Gesture::tie: case Gesture::work: case Gesture::scoop:
      case Gesture::shape: case Gesture::channel: case Gesture::blow: case Gesture::read: case Gesture::write: case Gesture::strike:
        d.target(g == Gesture::take ? bread : t); break;
      case Gesture::look: case Gesture::listen: case Gesture::guard: d.target(t); break;
      case Gesture::sleep: d.destination({0, 0, 0}); break;
      default: break;
    }
    if (g == Gesture::speak || g == Gesture::write) d.content(5);
    // Everything that lasts gets a way to stop (as a decision always does): 5 minutes of game time.
    d.stop(Condition::c_elapsed, 0, 300);
    if (timing_of(g).has_until) d.until(Condition::c_elapsed, 0, 300);
    const BeginResult br = r.start(d);
    if (br.status != BeginStatus::Started) { std::printf("  gesture %s: begin refused (%d)\n", social::gen::kGestureNames[gi].data(), int(br.status)); continue; }
    ++started;
    Phase last = Phase::Pending;
    bool order_ok = true;
    int n = 0;
    while (r.ex->busy(a) && n < 200) {
      r.tick();
      ++n;
      if (const GestureExecution* e = r.ex->find(a)) { order_ok &= static_cast<int>(e->phase) >= static_cast<int>(last); last = e->phase; }
    }
    const ExecutionReport* rep = r.report_of(a);
    if (!rep || r.ex->busy(a)) { std::printf("  gesture %s did not end\n", social::gen::kGestureNames[gi].data()); continue; }
    ++ended;
    CHECK(order_ok);
    CHECK_EQ(r.reports.size(), std::size_t(1));
    CHECK(rep->gesture == g && rep->started <= rep->ended);
    outcome[std::string(social::gen::kGestureNames[gi])] = rep->outcome;
  }
  std::printf("  state machine: %d/40 started, %d ended\n", started, ended);
  CHECK_EQ(started, 40);
  CHECK_EQ(ended, 40);
  // No gesture ends by "limit_reached" here (each had its stop) and a person who is simply there never makes anything fail.
  for (const auto& [name, o] : outcome) {
    if (o == ExecOutcome::LimitReached || o == ExecOutcome::Interrupted) std::printf("  unexpected outcome %s: %s\n", name.c_str(), to_string(o));
    CHECK(o != ExecOutcome::LimitReached && o != ExecOutcome::Interrupted);
  }
}

// ---- determinism and load --------------------------------------------------------------------------------------------------

TEST(same_digest_with_1_4_and_8_threads) {
  gwork::Result r1 = gwork::run(1, 120, 1200);
  gwork::Result r4 = gwork::run(4, 120, 1200);
  gwork::Result r8 = gwork::run(8, 120, 1200);
  CHECK(r1.chain == r4.chain && r1.chain == r8.chain);
  CHECK(r1.store_fingerprint == r4.store_fingerprint && r1.store_fingerprint == r8.store_fingerprint);
  CHECK(r1.gestures == r4.gestures && r1.gestures == r8.gestures && r1.gestures > 200);
  std::printf("  digest %016llx, %llu gestures ended\n", static_cast<unsigned long long>(r1.chain), static_cast<unsigned long long>(r1.gestures));
}

TEST(500_npc_one_game_day_does_not_crash_and_reports_the_throughput) {
  const auto t0 = std::chrono::steady_clock::now();
  gwork::Result r = gwork::run(4, 500, 5400);   // 5 400 ticks of 16 game s = one game day
  const double s = std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count();
  CHECK(r.gestures > 5000);
  CHECK(r.store_alive > 500);
  std::printf("  500 NPC x 1 game day: %llu gestures ended, %llu cycles, %llu operations, %llu contacts in %.2f s (%.0f gestures/s, %.0f cycles/s)\n",
              static_cast<unsigned long long>(r.gestures), static_cast<unsigned long long>(r.cycles), static_cast<unsigned long long>(r.emissions),
              static_cast<unsigned long long>(r.contacts), s, double(r.gestures) / s, double(r.cycles) / s);
}

TEST(a_gesture_that_changes_nothing_fails_on_the_spot_but_a_blow_on_a_body_does_not) {
  Rig r;
  const EntityId a = r.person(kOrigin), victim = r.person({1000, 0, 0});
  r.w.catalog.set_profile(EntityKind::structure, 5, [] { Profile p; p.mass_g = 2000000; p.size = {2000, 2500, 300}; return p; }());
  const EntityId block = r.w.spawn_item("stone_block", {1000, 3000, 0});
  // Bare hands on a block of stone: the laws of matter answer NoEffect each time; after kNoEffectCycles the actor feels it.
  Dec d(a, Gesture::strike);
  d.target(block).with("intensity", "light").with("with", "fist");
  r.start(d);
  int blocked_seen = 0;
  for (int i = 0; i < 20 && r.ex->busy(a); ++i) {
    r.tick();
    if (r.ex->busy(a) && r.ex->find(a)->no_effect > 0) ++blocked_seen;
  }
  const ExecutionReport* rep = r.report_of(a);
  CHECK(rep && rep->outcome == ExecOutcome::Failed && rep->cause == Cause::NothingHappened && rep->cycles == kNoEffectCycles);
  CHECK(blocked_seen >= 1);
  // A person who is hit: the laws of matter say nothing of bodies (damage is T34's), so the blows go on until the stop.
  Dec b(a, Gesture::strike);
  b.target(victim).with("intensity", "firm").until(Condition::c_elapsed, 0, 160);
  r.start(b);
  r.run(a, 100);
  CHECK(r.report_of(a)->outcome == ExecOutcome::Done && r.report_of(a)->cycles > kNoEffectCycles);
}

// ---- review of T22: one frame, the content of speech, the senses, the wiring, the replacement of a gesture ---------------------

TEST(one_frame_between_the_executor_and_the_laws_of_matter) {
  Rig r;
  const EntityId a = r.person(kOrigin);
  // Walking along y (horizontal in the executor's frame, z up) never changes the height seen by the resolver (its y).
  Dec go(a, Gesture::go);
  go.with("pace", "walk").destination({0, 30000, 0}).given("target");
  r.start(go);
  r.run(a);
  const Position world = r.w.store.position_mm(a), seen_by_laws = r.frame.store().position_mm(a);
  CHECK(world[1] >= 29000 && world[2] == 0);
  CHECK(seen_by_laws[1] == 0 && seen_by_laws[2] == world[1] && seen_by_laws[0] == world[0]);   // y and z swapped, height untouched
  // The ground of the executor's frame (height at x, y) answers the resolver's (x, z) question.
  struct Slope final : HeightField { std::int32_t height_mm(std::int32_t x, std::int32_t y) const override { return x / 100 + y / 10; } } slope;
  ZUpGround ground(slope);
  CHECK_EQ(ground.height_mm(1000, 5000), 10 + 500);
  CHECK(swap_yz({1, 2, 3}) == Position({1, 3, 2}));
  // A blow within reach on the executor's side (the log is 1.2 m away along y) lands on the resolver's side: the split law
  // fires, and the pieces come back into the world frame (on the ground: z = 0, near y = 31 200).
  const EntityId axe = r.w.spawn_item("battle_axe", world);
  r.w.bus.submit(make_move(++r.w.tick, 1, axe, world, a));
  r.w.bus.flush();
  const EntityId log = r.w.spawn_item("log", {world[0], world[1] + 1200, 0});
  Dec hit(a, Gesture::strike);
  hit.target(log).tool(axe).with("intensity", "hard").with("motion", "swing").until(Condition::c_target_gone, log);
  hit.raw().manner = Manner::Strike;
  r.start(hit);
  r.run(a);
  CHECK(!r.w.store.alive(log) && r.report_of(a)->outcome == ExecOutcome::Done);
  bool pieces_on_ground = false;
  r.w.store.for_each([&](EntityId id, gen::EntityKind) {
    if (r.w.store.sort(id) == r.w.item("plank")) {
      const Position p = r.w.store.position_mm(id);
      pieces_on_ground = p[2] == 0 && p[1] > world[1] && p[1] < world[1] + 3000;
    }
  });
  CHECK(pieces_on_ground);
  // The mirror follows the world: same entities.
  CHECK_EQ(r.frame.store().size(), r.w.store.size());
}

TEST(the_content_of_a_speech_needs_the_verdict_of_the_utterance_check) {
  Rig r;
  const EntityId a = r.person(kOrigin), b = r.person({1500, 0, 0});
  Dec bare(a, Gesture::speak);
  bare.target(b).with("volume", "normal").with("tone", "calm").content(9).unvalidated();
  CHECK(r.start(bare).status == BeginStatus::Refused);
  const StepOutput& o = r.tick();
  CHECK(o.emissions.empty() && o.contacts.empty() && !r.ex->busy(a));
  CHECK(o.reports.size() == 1 && o.reports[0].refused && o.reports[0].cause == Cause::Refused);
  Dec denied(a, Gesture::write);
  denied.target(b).content(9);
  denied.raw().content_verdict = social::Verdict{false, 0, social::Reason::d10_hearer};
  const BeginResult br = r.start(denied);
  CHECK(br.status == BeginStatus::Refused && br.verdict.reason == social::Reason::d10_hearer);
  CHECK(r.tick().emissions.empty());
  Dec ok(a, Gesture::speak);
  ok.target(b).with("volume", "low").with("tone", "calm").content(9);
  CHECK(r.start(ok).status == BeginStatus::Started);
}

TEST(a_replaced_or_refused_gesture_ends_the_previous_one_with_a_report) {
  Rig r;
  const EntityId a = r.person(kOrigin);
  Dec first(a, Gesture::look);
  first.stop(Condition::c_elapsed, 0, 99999);
  r.start(first);
  r.tick();
  Dec second(a, Gesture::rest);
  second.with("duration", "brief");
  r.start(second);
  const StepOutput& o = r.tick();
  bool replaced = false;
  for (const ExecutionReport& rep : o.reports) replaced |= rep.gesture == Gesture::look && rep.outcome == ExecOutcome::Interrupted && rep.cause == Cause::Replaced;
  CHECK(replaced);
  CHECK(r.ex->find(a) && r.ex->find(a)->gesture == Gesture::rest);
  // A refusal does not leave the old gesture running either.
  const EntityId kid = r.person({900, 0, 0});
  GestureDecision touch = Dec(a, Gesture::touch).target(kid).with("with", "hand").with("contact_zone", "hands").with("manner", "romantic").with("duration", "brief").get();
  for (std::size_t i = 0; i < touch.call.value.size(); ++i) if (touch.call.value[i] < 0) touch.call.value[i] = 0;
  social::Party child{90, 90, 90, true};
  touch.call.party[static_cast<std::size_t>(param_index(Gesture::touch, "target"))] = &child;
  touch.actor_party = r.adult;
  CHECK(r.ex->begin(touch, r.now, r.w.tick + 1).status == BeginStatus::Refused);
  CHECK(!r.ex->busy(a));
  const StepOutput& o2 = r.tick();
  bool interrupted = false, refused = false;
  for (const ExecutionReport& rep : o2.reports) {
    interrupted |= rep.gesture == Gesture::rest && rep.cause == Cause::Replaced;
    refused |= rep.refused;
  }
  CHECK(interrupted && refused);
}

TEST(the_executor_trusts_what_is_seen_not_what_is_true) {
  Rig r;
  Script s;
  r.use(s);
  const EntityId a = r.person(kOrigin);
  const EntityId bread = r.w.spawn_item("bread_loaf", {40000, 0, 0});   // really 40 m away...
  s.seen[bread] = PerceivedThing{true, {700, 0, 0}, 700};              // ...but the actor SEES it at 70 cm (a lie of the senses)
  r.set(a, "hunger", 60);
  Dec eat(a, Gesture::eat);
  eat.target(bread).with("amount", "little");
  r.start(eat);
  r.run(a);
  CHECK(r.report_of(a)->outcome == ExecOutcome::Done);   // it ate: reach is judged on the percept
  const EntityId jug = r.w.spawn_item("water_jug", {500, 0, 0});     // really at hand, but not seen
  Dec drink(a, Gesture::drink);
  drink.target(jug).with("amount", "little");
  r.start(drink);
  r.run(a);
  CHECK(r.report_of(a)->outcome == ExecOutcome::Failed && r.report_of(a)->cause == Cause::TargetAbsent);
  // read and pour act on the spot too: a book not seen is not read, nothing seen to pour into.
  const EntityId book = r.w.spawn_item("knife", {600, 0, 0});
  Dec read(a, Gesture::read);
  read.target(book);
  r.start(read);
  r.run(a);
  CHECK(r.report_of(a)->outcome == ExecOutcome::Failed && r.report_of(a)->cause == Cause::TargetAbsent);
  r.w.bus.submit(make_move(++r.w.tick, 1, jug, kOrigin, a));
  r.w.bus.flush();
  const EntityId basin = r.w.spawn_item("water_jug", {800, 0, 0});
  Dec pour(a, Gesture::pour);
  pour.target(jug).other(basin).with("amount", "some");
  r.start(pour);
  r.run(a);
  CHECK(r.report_of(a)->outcome == ExecOutcome::Failed && r.report_of(a)->cause == Cause::TargetAbsent);
  // give: the recipient is where he is SEEN to be; not seen, the gift is not made.
  const EntityId friend_ = r.person({900, 0, 0});
  Dec give(a, Gesture::give);
  give.target(jug).other(friend_);
  r.start(give);
  r.run(a);
  CHECK(r.report_of(a)->cause == Cause::TargetAbsent && r.w.store.holder(jug) == a);
  // c_attacked / c_stopped are the body's report: a blow awaited is "done", unexpected is "interrupted".
  Dec wait(a, Gesture::look);
  wait.stop(Condition::c_attacked);
  r.start(wait);
  r.tick();
  r.ex->notify(a, BodyEvent::Blow);
  r.tick();
  CHECK(r.report_of(a)->outcome == ExecOutcome::Done);
}

TEST(productive_gestures_alone_carry_the_compression_flag_into_their_contacts) {
  const Gesture productive[] = {Gesture::operate, Gesture::scoop, Gesture::work, Gesture::tie, Gesture::shape, Gesture::channel};
  for (Gesture g : productive) {
    Rig r;
    const EntityId a = r.person(kOrigin);
    const EntityId thing = r.w.spawn_item("log", {900, 0, 0});
    Dec d(a, g);
    d.target(thing).stop(Condition::c_elapsed, 0, 48);
    r.start(d);
    bool flagged = false, any = false;
    for (int i = 0; i < 6; ++i) { r.tick(); for (const Contact& c : r.last_contacts) { any = true; flagged |= c.productive; } }
    CHECK(any && flagged);
  }
  Rig r;
  const EntityId a = r.person(kOrigin), thing = r.w.spawn_item("log", {900, 0, 0});
  Dec d(a, Gesture::strike);
  d.target(thing).with("intensity", "light").until(Condition::c_elapsed, 0, 48);
  r.start(d);
  bool flagged = false;
  for (int i = 0; i < 6; ++i) { r.tick(); for (const Contact& c : r.last_contacts) flagged |= c.productive; }
  CHECK(!flagged);
}

TEST(the_senses_rebuild_positions_from_the_percept_and_forget_what_left_the_view) {
  PerceptionRig p;
  const EntityId a = p.r.person(kOrigin), t = p.r.person({8000, 3000, 0});
  const EntityId stone = p.r.w.spawn_item("knife", {5000, -1000, 0});
  p.r.now = kDayT;
  p.see({a});
  ObserverSenses senses(p.r.w.store, p.observers);
  p.r.use(senses);
  p.perceive();
  PerceivedThing seen = senses.perceive(a, t);
  CHECK(seen.in_view);
  CHECK(std::abs(seen.at[0] - 8000) < 1500 && std::abs(seen.at[1] - 3000) < 1500);
  // The person walks away; the actor has not looked again: what it knows is the percept, not the new truth.
  p.r.w.bus.submit(make_move(++p.r.w.tick, 1, t, {-20000, 0, 0}));
  p.r.w.bus.flush();
  seen = senses.perceive(a, t);
  CHECK(std::abs(seen.at[0] - 8000) < 1500);
  // sees_kind: what the last scan perceived, and nothing older.
  std::uint32_t kind = 0;
  p.observers[0].mind().state.percept_records.for_each([&](social::MRef, social::gen::Percept& pc) { if (!kind) kind = pc.pc_kind_seen; });
  CHECK(kind != 0 && senses.sees_kind(a, kind));
  p.r.w.bus.submit(make_move(++p.r.w.tick, 1, stone, {-90000, 0, 0}));
  p.r.w.bus.flush();
  p.perceive();
  CHECK(!senses.sees_kind(a, kind) || !senses.perceive(a, stone).in_view);
  CHECK(!senses.perceive(a, stone).in_view);
  // hears: a heard event named by its word.
  social::gen::EventSeen ev;
  ev.ev_sense = 1;
  ev.ev_gesture = 5;
  p.observers[0].mind().state.event_seen_records.add(ev, p.r.now);
  CHECK(senses.hears(a, 5) && !senses.hears(a, 6) && senses.hears(a, 0));
}

TEST(the_navigator_of_t23b_walks_a_gesture_around_a_closed_bridge_it_discovers_on_the_spot) {
  using namespace em::act::navigation;
  constexpr Position A{2'700'000, 2'700'000, 0}, B{2'700'000, 3'700'000, 0}, C{3'200'000, 3'200'000, 0};
  auto run_case = [&](bool gap, ExecOutcome& outcome, Cause& cause, Position& stopped_at, std::size_t& obstacles, int& ticks) {
    RoadPlan roads;
    auto na = roads.add_node(A), nb = roads.add_node(B), nc = roads.add_node(C);
    const int ab = roads.add_segment(na, nb), ac = roads.add_segment(na, nc), cb = roads.add_segment(nc, nb);
    FlatTerrain river;   // a river along y = 3200 m; the bridge of the road A-B is broken, the one at C is open (gap) or not
    for (int x = 1000; x <= 4500; ++x) if (!gap || x < 3150 || x > 3250) river.block(x, 3200, x, 3203);
    Navigator navigator(&roads, river);
    Rig r;
    const EntityId a = r.person(A);
    MentalMap& mm = navigator.add_npc(a);
    mm.see_segment(ab); mm.see_segment(ac); mm.see_segment(cb);
    for (int y = 2'700'000; y <= 3'700'000; y += 50'000) mm.see_position({2'700'000, y, 0});
    NavigatorAdapter adapter(navigator);
    adapter.set_day(10);
    r.use_nav(adapter);
    Dec d(a, Gesture::go);
    d.with("pace", "walk").with("stop_at", "near").destination(B).given("target");
    r.start(d);
    ticks = r.run(a, 6000);
    outcome = r.report_of(a)->outcome;
    cause = r.report_of(a)->cause;
    stopped_at = r.w.store.position_mm(a);
    obstacles = mm.obstacle_count();
  };
  ExecOutcome o{}; Cause c{}; Position at{}; std::size_t obs = 0; int ticks = 0;
  run_case(true, o, c, at, obs, ticks);   // an open crossing exists at C: it finds the cut, learns it, goes round
  CHECK(o == ExecOutcome::Done);
  CHECK(obs >= 1);
  CHECK(std::abs(at[0] - B[0]) < 4000 && std::abs(at[1] - B[1]) < 4000);
  CHECK(ticks > 600);
  run_case(false, o, c, at, obs, ticks);  // closed all across: it fails, but only once the river is in view
  CHECK(o == ExecOutcome::Blocked && c == Cause::PathBlocked);
  CHECK(at[1] < 3'200'000 && at[1] > 3'200'000 - NavigatorConfig{}.view_mm - 8000);
}

EMERGENCE_TEST_MAIN()
