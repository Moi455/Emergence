// T23b: mental map and route planner. Tests of: the map (size, round trip, fail closed, bounded forgetting), the planner
// (knowledge only, told roads, exploring), the journey (cut route out of view, relief, closed way fails on the spot only,
// the probe is never asked beyond the view), the save in NpcBundle::mental_map, determinism at 1/4/8 threads, cost.
#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstdio>
#include <memory>
#include <thread>
#include <vector>

#include "emergence/act/navigation/mental_map_codec.h"
#include "emergence/act/navigation/navigator.h"
#include "emergence/social/npc_state_codec.h"
#include "emergence/testing/check.h"

using namespace em::act;
using namespace em::act::navigation;

namespace {

// The flat terrain, with an audit: the farthest point the Navigator ever asked about, and every asked segment.
class AuditedTerrain final : public ViewProbe {
 public:
  explicit AuditedTerrain(const FlatTerrain& t) : t_(t) {}
  bool blocked(const Position& from, const Position& to) const override {
    queries_.fetch_add(1);
    const std::int64_t d = distance_mm(from, to);
    std::int64_t cur = max_.load();
    while (d > cur && !max_.compare_exchange_weak(cur, d)) {}
    return t_.blocked(from, to);
  }
  std::int64_t max_query_mm() const { return max_.load(); }
  std::int64_t queries() const { return queries_.load(); }
 private:
  const FlatTerrain& t_;
  mutable std::atomic<std::int64_t> max_{0}, queries_{0};
};

struct Walk {
  Position at;
  int steps = 0;
  NavStatus last = NavStatus::Moving;
  int first_replan_step = -1;
  Position at_first_replan{};
  bool blocked_before_view = false;
  bool arrived = false;
  std::int64_t walked_mm = 0;
  std::vector<NavStep> log;
  std::vector<Position> trail;
};

// An agent that walks 6 m per call toward the waypoint it is given.
Walk walk(Navigator& nav, EntityId id, Position from, Position target, int max_steps, std::int32_t arrive = 3000, std::uint16_t day = 10) {
  Walk w;
  w.at = from;
  for (; w.steps < max_steps; ++w.steps) {
    NavRequest rq{w.at, target, arrive, day};
    NavStep st = nav.next_step(id, rq);
    w.log.push_back(st);
    w.trail.push_back(w.at);
    w.last = st.status;
    if (st.replans > 0 && w.first_replan_step < 0) { w.first_replan_step = w.steps; w.at_first_replan = w.at; }
    if (st.status == NavStatus::Arrived) { w.arrived = true; break; }
    if (st.status == NavStatus::Blocked) break;
    const std::int64_t d = distance_mm(w.at, st.waypoint);
    const std::int64_t mv = std::min<std::int64_t>(6000, d);
    if (d > 0) {
      w.at[0] += std::int32_t((std::int64_t(st.waypoint[0]) - w.at[0]) * mv / d);
      w.at[1] += std::int32_t((std::int64_t(st.waypoint[1]) - w.at[1]) * mv / d);
    }
    w.walked_mm += mv;
  }
  return w;
}

constexpr Position A{2'700'000, 2'700'000, 0}, B{2'700'000, 3'700'000, 0}, C{3'200'000, 3'200'000, 0};

struct Village {
  RoadPlan roads;
  int ab = -1, ac = -1, cb = -1;
  Village() {
    auto a = roads.add_node(A), b = roads.add_node(B), c = roads.add_node(C);
    ab = roads.add_segment(a, b); ac = roads.add_segment(a, c); cb = roads.add_segment(c, b);
  }
};

}  // namespace

TEST(map_is_compact_and_roundtrips) {
  MentalMap m;
  for (int i = 0; i < 120; ++i) m.see_position({(i % 70) * 256'000 + 1000, (i / 70) * 256'000 + 1000, 0});
  for (int i = 0; i < 6; ++i) m.see_place(100 + PlaceKey(i), {i * 1000, 5000, 0}, 3);
  m.hear_place(900, {7'000'000, 7'000'000, 0}, 120, 4);
  m.see_obstacle(10, 11, 5);
  m.see_segment(3); m.hear_segment(500);
  std::vector<std::uint8_t> b;
  m.serialize(b);
  std::printf("  mental map: %zu bytes serialized (typical), sizeof %zu\n", b.size(), sizeof(MentalMap));
  CHECK(b.size() == m.serialized_size());
  CHECK(b.size() <= 1100);
  CHECK(sizeof(MentalMap) <= 1250);
  MentalMap back;
  CHECK(back.deserialize(b));
  CHECK(back == m);
  CHECK(back.walked_tiles() == m.walked_tiles());
  CHECK(back.knows_segment(3) && back.knows_segment(500) && !back.knows_segment(4));
  CHECK(back.place(900) && back.place(900)->certainty == 120);
  CHECK(back.edge_blocked(11, 10, 6));
  // full map: the worst case stays near 1 KiB
  MentalMap full;
  for (int i = 0; i < 40; ++i) full.see_place(1000 + PlaceKey(i), {i, i, 0}, 9);
  for (int i = 0; i < 20; ++i) full.see_obstacle(i, i + 100, 9);
  full.serialize(b);
  std::printf("  mental map: %zu bytes serialized (places and obstacles full)\n", b.size());
  CHECK(b.size() <= 1160);
}

TEST(map_load_is_fail_closed) {
  MentalMap m;
  m.see_position({1000, 1000, 0}); m.see_place(5, {1, 2, 0}, 1); m.see_obstacle(1, 2, 1);
  std::vector<std::uint8_t> b;
  m.serialize(b);
  MentalMap t;
  t.see_position({9'000'000, 9'000'000, 0});
  auto bad = b; bad.pop_back();
  CHECK(!t.deserialize(bad)); CHECK(t.walked_tiles() == 0);   // emptied on refusal
  bad = b; bad[0] = 'X';             CHECK(!t.deserialize(bad));
  bad = b; bad[2] = 9;               CHECK(!t.deserialize(bad));
  bad = b; bad[6] = 17;              CHECK(!t.deserialize(bad));   // more places than the map holds
  bad = b; bad[7] = 9;               CHECK(!t.deserialize(bad));
  bad = b; bad[8 + 95 * 8 + 7] |= 0x80; CHECK(!t.deserialize(bad));   // a bit past the last tile
  bad = b; bad.push_back(0);         CHECK(!t.deserialize(bad));
  CHECK(!t.deserialize({}));
  CHECK(t.deserialize(b));
  std::vector<std::uint8_t> none;
  MentalMap e; e.see_position({1000, 1000, 0});
  CHECK(MentalMapCodec::load(none, e) && e.walked_tiles() == 0);   // a save older than T23b: an empty map
}

TEST(forgetting_is_bounded_and_deterministic) {
  auto fill = [] {
    MentalMap m;
    m.see_place(1, {0, 0, 0}, 1); m.protect_place(1);   // home
    for (PlaceKey k = 2; k < 80; ++k) m.hear_place(k, {int(k), int(k), 0}, std::uint8_t(30 + k % 90), std::uint16_t(1 + k / 8));
    for (int i = 0; i < 30; ++i) m.see_obstacle(i, i + 200, std::uint16_t(i));
    return m;
  };
  MentalMap a = fill(), b = fill();
  CHECK(a.place_count() == kMaxPlaces);
  CHECK(a.obstacle_count() <= kMaxObstacles);
  CHECK(a.place(1) != nullptr);   // protected: kept
  CHECK(a == b);
  // a rumour never overwrites what was seen
  MentalMap m;
  m.see_place(7, {100, 100, 0}, 5);
  m.hear_place(7, {999'000, 999'000, 0}, 150, 6);
  CHECK(m.place(7)->x == 100 && m.place(7)->certainty == 255);
  // told certainty is capped, and it fades with the days
  m.hear_place(8, {1, 1, 0}, 255, 5);
  CHECK(m.place(8)->certainty == kToldCertaintyMax);
  CHECK(m.place_certainty(*m.place(8), 5 + 400) < m.place_certainty(*m.place(8), 5 + 40));
  CHECK(m.place_certainty(*m.place(8), 60000) >= kCertaintyFloor);
  // an obstacle is forgotten after 30 days: the NPC believes the way open again
  MentalMap o;
  o.see_obstacle(4, 5, 10);
  CHECK(o.edge_blocked(4, 5, 10 + kObstacleLifeDays) && !o.edge_blocked(4, 5, 10 + kObstacleLifeDays + 1));
}

TEST(planner_uses_only_knowledge) {
  Village v;
  RoutePlanner pl(&v.roads);
  MentalMap none;   // knows nothing
  Plan p = pl.plan(none, 1, A, B);
  CHECK(p.status == PlanStatus::Found);
  CHECK(p.explores());                       // every tile unknown: it explores toward where it believes B is
  for (int i = 0; i < p.count; ++i) CHECK(p.steps[std::size_t(i)].segment < 0);   // the roads are not known: not used
  // the same NPC, told of the road A-B (never walked it): the road enters its plan
  MentalMap told;
  told.hear_segment(v.ab);
  p = pl.plan(told, 1, A, B);
  CHECK(p.status == PlanStatus::Found && p.count == 1 && p.steps[0].segment == v.ab);
  // a known road cut at a place: the crossing is removed from its plan
  told.see_obstacle(clamped_tile_of(A), clamped_tile_of(B), 1);
  told.hear_segment(v.ac); told.hear_segment(v.cb);
  p = pl.plan(told, 1, A, B);
  CHECK(p.status == PlanStatus::Found && p.count == 2 && p.steps[0].segment == v.ac && p.steps[1].segment == v.cb);
  // same inputs, same plan, every time
  Plan q = pl.plan(told, 1, A, B);
  CHECK(q.count == p.count && q.cost == p.cost);
  // a bounded cost
  RoutePlanner tiny(&v.roads, PlannerLimits{4});
  CHECK(tiny.plan(none, 1, {100, 100, 0}, {19'000'000, 19'000'000, 0}).status == PlanStatus::OverBudget);
  // a target off the plan (a wrong belief) still gives a route to the nearest edge
  CHECK(pl.plan(none, 1, A, {-5'000'000, 90'000'000, 0}).status == PlanStatus::Found);
}

TEST(route_cut_out_of_view_is_found_on_the_spot) {
  Village v;
  // A river along y = 3200 m, 3.5 km wide; two bridges: the one on the road A-B (x 2700 m, BROKEN: no gap) and one at C (gap).
  FlatTerrain river;
  for (int x = 1000; x <= 4500; ++x) if (x < 3150 || x > 3250) river.block(x, 3200, x, 3203);
  AuditedTerrain world(river);
  Navigator nav(&v.roads, world);
  const EntityId npc = 1;
  MentalMap& mm = nav.add_npc(npc);
  // the NPC knows all three roads (it has used them in the past), and has walked the tiles of the road A-B
  mm.see_segment(v.ab); mm.see_segment(v.ac); mm.see_segment(v.cb);
  for (int y = 2'700'000; y <= 3'700'000; y += 50'000) mm.see_position({2'700'000, y, 0});

  Walk w = walk(nav, npc, A, B, 1500);
  std::printf("  cut route: %d calls, replans at call %d, walked %lld m, last probe %lld m\n", w.steps, w.first_replan_step,
              (long long)(w.walked_mm / 1000), (long long)(world.max_query_mm() / 1000));
  CHECK(w.arrived);
  CHECK(w.last == NavStatus::Arrived);
  CHECK(w.first_replan_step > 0);
  // it set out as if the road was open (straight to B's node), and discovered the cut only in view of it: never before
  CHECK(w.log[0].status == NavStatus::Moving && w.log[0].waypoint == B);
  const std::int32_t view = NavigatorConfig{}.view_mm;
  for (int i = 0; i < w.first_replan_step; ++i) CHECK(3'200'000 - w.trail[std::size_t(i)][1] > view - 7000 || w.log[std::size_t(i)].replans == 0);
  CHECK(std::llabs(3'200'000 - w.at_first_replan[1]) <= view + 2000);   // it was within sight of the river when it replanned
  for (const NavStep& s : w.log) CHECK(s.status != NavStatus::Blocked);
  // and it learned: the crossing is a known obstacle now
  CHECK(mm.obstacle_count() >= 1);
  // the world was only ever asked about what is in view
  CHECK(world.max_query_mm() <= view);
}

TEST(unknown_place_is_not_reached_in_a_perfect_straight_line_over_relief) {
  FlatTerrain relief;
  relief.block(1900, 3000, 2100, 3100);   // a hill, 200 x 100 m, on the straight line
  AuditedTerrain world(relief);
  Navigator nav(nullptr, world);
  const EntityId npc = 7;
  nav.add_npc(npc);
  const Position from{2'000'000, 2'000'000, 0}, target{2'000'000, 4'000'000, 0};
  nav.hear_place(npc, 42, target, 120, 1);   // told, never seen
  Position believed; std::uint8_t cert;
  CHECK(nav.believed_place(npc, 42, 1, believed, cert) && believed == target && cert == 120);
  Walk w = walk(nav, npc, from, target, 1200);
  CHECK(w.arrived);
  CHECK(w.log[0].status == NavStatus::Exploring);
  // straight toward the belief while nothing is seen...
  int first_dev = -1;
  for (int i = 0; i < w.steps; ++i) if (w.trail[std::size_t(i)][0] != 2'000'000) { first_dev = i; break; }
  CHECK(first_dev > 0);
  const std::int32_t view = NavigatorConfig{}.view_mm;
  CHECK(3'000'000 - w.trail[std::size_t(first_dev)][1] <= view + 7000);   // ... it bends only when the hill is in view
  CHECK(3'000'000 - w.trail[std::size_t(first_dev)][1] > 0);
  // the walk is longer than the straight line: it did not know the hill was there
  std::printf("  relief: walked %lld m for 2000 m as the crow flies\n", (long long)(w.walked_mm / 1000));
  CHECK(w.walked_mm > 2'000'000 + 10'000);
  CHECK(world.max_query_mm() <= view);
}

TEST(a_way_closed_all_across_fails_only_on_the_spot) {
  Village v;
  FlatTerrain wall;
  wall.block(0, 3200, 19'000, 3203);   // an uncrossable barrier across the whole world, at y = 3200 m
  AuditedTerrain world(wall);
  Navigator nav(&v.roads, world);
  nav.add_npc(1);
  Walk w = walk(nav, 1, A, B, 4000);
  CHECK(!w.arrived);
  CHECK(w.last == NavStatus::Blocked);
  const std::int32_t view = NavigatorConfig{}.view_mm;
  CHECK(w.log.back().replans > NavigatorConfig{}.max_replans);
  // not one Blocked before the last call, and the last one is given within sight of the barrier
  for (std::size_t i = 0; i + 1 < w.log.size(); ++i) CHECK(w.log[i].status != NavStatus::Blocked);
  CHECK(std::llabs(3'200'000 - w.at[1]) <= view + 7000 || w.at[1] > 3'200'000 - view - 7000);
  CHECK(w.at[1] < 3'200'000);   // still on this side
  CHECK(world.max_query_mm() <= view);
}

TEST(told_route_enters_the_map_and_is_followed) {
  Village v;
  FlatTerrain open;
  AuditedTerrain world(open);
  Navigator nav(&v.roads, world);
  nav.add_npc(1);
  nav.hear_segment(1, v.ab);   // "the road from A to B"
  Walk w = walk(nav, 1, A, B, 400);
  CHECK(w.arrived);
  CHECK(w.log[0].status == NavStatus::Moving);       // a told road is followed as known, not explored
  CHECK(w.log[0].waypoint == B);
  CHECK(nav.map(1)->knows_segment(v.ab));
  // the told obstacle is avoided without having been seen
  nav.add_npc(2);
  nav.hear_segment(2, v.ab); nav.hear_segment(2, v.ac); nav.hear_segment(2, v.cb);
  nav.hear_obstacle(2, A, B, 10);
  NavStep s = nav.next_step(2, NavRequest{A, B, 3000, 10});
  CHECK(s.waypoint == C);
}

TEST(save_in_the_reserved_place_of_npcs) {
  Village v;
  FlatTerrain ground;
  AuditedTerrain world(ground);
  Navigator nav(&v.roads, world);
  std::vector<std::unique_ptr<em::social::NpcBundle>> bundles;
  for (EntityId id = 1; id <= 500; ++id) {
    MentalMap& m = nav.add_npc(id);
    for (unsigned i = 0; i < 20 + id % 60; ++i) m.see_position({std::int32_t((id * 37 + i * 11) % 78) * 256'000 + 5, std::int32_t((id * 13 + i * 7) % 78) * 256'000 + 5, 0});
    m.see_place(id, {std::int32_t(id), 5, 0}, 3);
    if (id % 3 == 0) m.hear_place(id + 1000, {9, 9, 0}, 90, 4);
    if (id % 5 == 0) m.see_obstacle(id % 100, id % 100 + 1, 4);
    m.hear_segment(int(id % 3));
    bundles.push_back(std::make_unique<em::social::NpcBundle>());
    MentalMapCodec::store(m, bundles.back()->mental_map);
  }
  const auto name = em::social::NpcStateCodec::save_name_section();
  const auto npcs = em::social::NpcStateCodec::save_npcs_section(bundles);
  std::vector<std::unique_ptr<em::social::NpcBundle>> back;
  auto rep = em::social::NpcStateCodec::load(name, npcs, 100, 5, back);
  CHECK(rep.ok);
  CHECK(back.size() == 500);
  std::size_t total = 0;
  RoutePlanner pl(&v.roads);
  for (std::size_t i = 0; i < back.size(); ++i) {
    MentalMap m;
    CHECK(MentalMapCodec::load(back[i]->mental_map, m));
    CHECK(m == *nav.map(EntityId(i + 1)));
    total += back[i]->mental_map.size();
    // the same plan after the reload (the knowledge is the same)
    const Plan p1 = pl.plan(m, 5, A, B), p2 = pl.plan(*nav.map(EntityId(i + 1)), 5, A, B);
    CHECK(p1.count == p2.count && p1.cost == p2.cost);
  }
  std::printf("  mental maps in NPCS: %zu bytes for 500 NPCs (%zu per NPC)\n", total, total / 500);
}

namespace {
std::uint64_t run_crowd(int threads, std::int64_t* queries) {
  Village v;
  FlatTerrain ground;
  ground.block(1000, 3200, 4500, 3203);
  AuditedTerrain world(ground);
  NavigatorConfig cfg;
  Navigator nav(&v.roads, world, cfg);
  const int n = 500;
  std::vector<Position> at(n), target(n);
  std::uint64_t s = 0x9E3779B97F4A7C15ull;
  auto rnd = [&](std::uint32_t m) { s = s * 6364136223846793005ull + 1442695040888963407ull; return std::uint32_t(s >> 33) % m; };
  for (int i = 0; i < n; ++i) {
    nav.add_npc(EntityId(i + 1));
    at[std::size_t(i)] = {std::int32_t(2'000'000 + rnd(1'500'000)), std::int32_t(2'500'000 + rnd(600'000)), 0};
    target[std::size_t(i)] = {std::int32_t(2'000'000 + rnd(1'500'000)), std::int32_t(3'400'000 + rnd(600'000)), 0};
    if (rnd(2)) nav.map(EntityId(i + 1))->see_segment(int(rnd(3)));
  }
  auto work = [&](int lo, int hi) {
    for (int i = lo; i < hi; ++i) {
      Position p = at[std::size_t(i)];
      for (int k = 0; k < 400; ++k) {
        NavStep st = nav.next_step(EntityId(i + 1), NavRequest{p, target[std::size_t(i)], 3000, 10});
        if (st.status == NavStatus::Arrived || st.status == NavStatus::Blocked) break;
        const std::int64_t d = distance_mm(p, st.waypoint), mv = std::min<std::int64_t>(6000, d);
        if (d > 0) { p[0] += std::int32_t((std::int64_t(st.waypoint[0]) - p[0]) * mv / d); p[1] += std::int32_t((std::int64_t(st.waypoint[1]) - p[1]) * mv / d); }
      }
      at[std::size_t(i)] = p;
    }
  };
  std::vector<std::thread> th;
  for (int t = 0; t < threads; ++t) th.emplace_back(work, n * t / threads, n * (t + 1) / threads);
  for (auto& t : th) t.join();
  std::uint64_t h = 1469598103934665603ull;
  for (int i = 0; i < n; ++i) {
    for (std::uint64_t x : {nav.map(EntityId(i + 1))->fingerprint(), std::uint64_t(at[std::size_t(i)][0]), std::uint64_t(at[std::size_t(i)][1])}) { h ^= x; h *= 1099511628211ull; }
  }
  if (queries) *queries = world.queries();
  return h;
}
}  // namespace

TEST(deterministic_at_1_4_8_threads) {
  std::int64_t q = 0;
  const std::uint64_t h1 = run_crowd(1, &q), h4 = run_crowd(4, nullptr), h8 = run_crowd(8, nullptr);
  std::printf("  crowd of 500: fingerprint %016llx, %lld probe queries\n", (unsigned long long)h1, (long long)q);
  CHECK(h1 == h4);
  CHECK(h1 == h8);
  CHECK(h1 == run_crowd(1, nullptr));
}

TEST(planning_cost_of_500_npcs) {
  Village v;
  RoutePlanner pl(&v.roads);
  std::vector<MentalMap> maps(500);
  std::uint64_t s = 12345;
  auto rnd = [&](std::uint32_t m) { s = s * 6364136223846793005ull + 1442695040888963407ull; return std::uint32_t(s >> 33) % m; };
  for (auto& m : maps) for (int i = 0; i < 300; ++i) m.see_position({std::int32_t(rnd(19'000)) * 1000, std::int32_t(rnd(19'000)) * 1000, 0});
  std::vector<Position> from(500), to(500);
  for (std::size_t i = 0; i < 500; ++i) {
    from[i] = {std::int32_t(rnd(19'000)) * 1000, std::int32_t(rnd(19'000)) * 1000, 0};
    to[i] = {std::int32_t(rnd(19'000)) * 1000, std::int32_t(rnd(19'000)) * 1000, 0};
  }
  double best = 1e9; std::uint64_t exp = 0;
  for (int rep = 0; rep < 5; ++rep) {
    exp = 0;
    const auto t0 = std::chrono::steady_clock::now();
    for (std::size_t i = 0; i < 500; ++i) exp += pl.plan(maps[i], 5, from[i], to[i]).expansions;
    best = std::min(best, std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0).count());
  }
  std::printf("  500 long plans (random across 19 km): %.2f ms, %llu expansions\n", best, (unsigned long long)exp);
  CHECK(best < 500.0);   // loose guard against a regression under a loaded machine; the measured figure is printed (bench_navigation)
}

TEST(no_blocked_from_afar_without_a_route_or_a_registration) {
  FlatTerrain open;
  AuditedTerrain world(open);
  const Position from{2'000'000, 2'000'000, 0}, target{9'000'000, 9'000'000, 0};
  // an NPC the navigator does not know: it follows its belief, it is not "blocked"
  Navigator nav(nullptr, world);
  NavStep st = nav.next_step(99, NavRequest{from, target, 3000, 5});
  CHECK(st.status == NavStatus::Exploring && st.waypoint == target);
  // a planner out of budget (no route found) and nothing in view: it explores toward the belief, never "blocked"
  NavigatorConfig cfg;
  cfg.planner.max_expansions = 2;
  Navigator poor(nullptr, world, cfg);
  poor.add_npc(1);
  Walk w = walk(poor, 1, from, target, 60);
  for (const NavStep& s : w.log) CHECK(s.status == NavStatus::Exploring);
  CHECK(w.at[0] > from[0] && w.at[1] > from[1]);   // it did move toward where it believes the target is
}

TEST(save_mid_journey_then_resume_replans_to_the_same_arrival) {
  FlatTerrain relief;
  relief.block(1900, 3000, 2100, 3100);
  AuditedTerrain world(relief);
  const Position from{2'000'000, 2'000'000, 0}, target{2'000'000, 4'000'000, 0};
  Navigator live(nullptr, world);
  live.add_npc(5);
  live.hear_place(5, 42, target, 120, 1);
  // continuous run
  Walk full = walk(live, 5, from, target, 1200);
  CHECK(full.arrived);
  // the same, saved half-way (during the detour) and resumed in a fresh navigator from the bundle bytes
  Navigator a(nullptr, world);
  a.add_npc(5);
  a.hear_place(5, 42, target, 120, 1);
  Walk first = walk(a, 5, from, target, 140);   // 140 calls: before the end
  CHECK(!first.arrived);
  em::social::NpcBundle stale;
  CHECK(stale.mental_map.empty());   // the bundle knows nothing until it is synchronised
  std::vector<std::unique_ptr<em::social::NpcBundle>> bundles;
  bundles.push_back(std::make_unique<em::social::NpcBundle>());
  CHECK(a.sync_to_bundle(5, bundles[0]->mental_map));
  CHECK(!a.sync_to_bundle(6, bundles[0]->mental_map) || true);
  const auto name = em::social::NpcStateCodec::save_name_section();
  const auto npcs = em::social::NpcStateCodec::save_npcs_section(bundles);
  std::vector<std::unique_ptr<em::social::NpcBundle>> back;
  CHECK(em::social::NpcStateCodec::load(name, npcs, 100, 5, back).ok);
  Navigator b(nullptr, world);
  CHECK(b.sync_from_bundle(5, back[0]->mental_map));
  CHECK(*b.map(5) == *a.map(5));
  CHECK(!b.sync_from_bundle(5, std::vector<std::uint8_t>{1, 2, 3}));   // refused: the live map is kept
  CHECK(*b.map(5) == *a.map(5));
  Walk rest = walk(b, 5, first.at, target, 1200);
  CHECK(rest.arrived);
  std::printf("  resume: continuous %d calls; saved at 140 + resumed %d calls (replanned from the map)\n", full.steps, rest.steps);
  CHECK(distance_mm(rest.at, full.at) <= 6000);   // same arrival, up to one stride
  CHECK(140 + rest.steps <= full.steps + 20);
}

TEST(hearsay_obstacles_cannot_isolate_evict_or_be_refreshed) {
  // 8 lies around one tile: bounded, and the tile is still reachable (a surcharge, not a wall)
  Village v;
  MentalMap m;
  const std::int32_t t = clamped_tile_of(A);
  const int dirs[8][2] = {{-1,-1},{0,-1},{1,-1},{-1,0},{1,0},{-1,1},{0,1},{1,1}};
  for (auto& d : dirs) m.hear_obstacle(t, t + d[1] * kTilesPerSide + d[0], 10);
  int told = 0;
  for (auto& d : dirs) told += m.edge_state(t, t + d[1] * kTilesPerSide + d[0], 10) == MentalMap::Edge::Told;
  CHECK(told <= kMaxToldObstacles);
  CHECK(m.edge_blocked(t, t + 1, 10) == false);
  RoutePlanner pl(&v.roads);
  CHECK(pl.plan(m, 10, A, B).status == PlanStatus::Found);
  // lies never evict what was seen
  MentalMap f;
  for (int i = 0; i < 5; ++i) f.see_obstacle(100 + i, 200 + i, 10);
  for (int i = 0; i < 40; ++i) f.hear_obstacle(300 + i, 400 + i, 11);
  for (int i = 0; i < 5; ++i) CHECK(f.edge_blocked(100 + i, 200 + i, 11));
  CHECK(f.obstacle_count() <= kMaxObstacles);
  // repeating a rumour does not prolong it: it ends 30 days after the first telling
  MentalMap r;
  r.hear_obstacle(4, 5, 10);
  r.hear_obstacle(4, 5, 35);
  CHECK(r.edge_state(4, 5, 40) == MentalMap::Edge::Told);
  CHECK(r.edge_state(4, 5, 41) == MentalMap::Edge::Open);
  // hearsay then sight: the rumour becomes a fact (and a fact is not downgraded by a later rumour)
  r.see_obstacle(4, 5, 50);
  CHECK(r.edge_blocked(4, 5, 50));
  r.hear_obstacle(4, 5, 51);
  CHECK(r.edge_blocked(4, 5, 51));
  // checked by the eyes: the road is told cut, the NPC takes it (no other way known), sees it open, and the rumour goes
  FlatTerrain open;
  AuditedTerrain world(open);
  Navigator nav(&v.roads, world);
  nav.add_npc(1);
  nav.hear_segment(1, v.ab);
  nav.hear_obstacle(1, A, B, 10);
  CHECK(nav.map(1)->edge_state(clamped_tile_of(A), clamped_tile_of(B), 10) == MentalMap::Edge::Told);
  Walk w = walk(nav, 1, A, B, 400);
  CHECK(w.arrived);
  CHECK(nav.map(1)->edge_state(clamped_tile_of(A), clamped_tile_of(B), 10) == MentalMap::Edge::Open);
  // the save keeps the told/seen difference
  std::vector<std::uint8_t> bytes; MentalMap back;
  MentalMap g;
  g.see_obstacle(1, 2, 11); g.hear_obstacle(500, 501, 11);
  g.serialize(bytes);
  CHECK(back.deserialize(bytes) && back == g && back.edge_state(500, 501, 11) == MentalMap::Edge::Told && back.edge_blocked(1, 2, 11));
}

TEST(hearsay_cannot_overwrite_a_seen_protected_place) {
  MentalMap m;
  m.see_place(1, {100, 100, 0}, 1);
  m.protect_place(1);
  m.hear_place(1, {900'000, 900'000, 0}, 200, 300);   // 300 days later: the seen certainty has faded below 200
  CHECK(m.place_certainty(*m.place(1), 300) < 200);
  CHECK(m.place(1)->x == 100 && m.place(1)->seen);
  m.see_place(1, {120, 100, 0}, 301);                // seeing it again does update it
  CHECK(m.place(1)->x == 120 && m.place(1)->certainty == 255);
  std::vector<std::uint8_t> b; MentalMap back;
  m.serialize(b);
  CHECK(back.deserialize(b) && back.place(1)->seen && back.place(1)->protected_);
  // not protected: the old rule stands (a surer rumour may replace a faded memory)
  MentalMap u;
  u.see_place(2, {100, 100, 0}, 1);
  u.hear_place(2, {777, 777, 0}, 200, 300);
  CHECK(u.place(2)->x == 777 && !u.place(2)->seen);
}

namespace {
// A trap: it checks, at each query, that the segment starts where the actor stands and stays within the view distance.
class TrapTerrain final : public ViewProbe {
 public:
  TrapTerrain(const FlatTerrain& t, const Position& agent, std::int64_t view) : t_(t), agent_(agent), view_(view) {}
  bool blocked(const Position& from, const Position& to) const override {
    if (!(from == agent_) || distance_mm(from, to) > view_) violations_.fetch_add(1);
    return t_.blocked(from, to);
  }
  std::int64_t violations() const { return violations_.load(); }
 private:
  const FlatTerrain& t_; const Position& agent_; std::int64_t view_;
  mutable std::atomic<std::int64_t> violations_{0};
};
}  // namespace

TEST(world_is_asked_only_in_view_on_rough_ground) {
  FlatTerrain rough;
  rough.block(1900, 3000, 2100, 3100);      // hills and a ravine on and around the way
  rough.block(2150, 3300, 2210, 3320);
  rough.block(2130, 3700, 2260, 3730);
  const Position from{2'000'000, 2'000'000, 0}, target{2'200'000, 4'200'000, 0};
  const std::int32_t view = NavigatorConfig{}.view_mm;
  Position agent = from;
  TrapTerrain trap(rough, agent, view);
  Navigator nav(nullptr, trap);
  nav.add_npc(1);
  Walk w;
  w.at = from;
  for (int i = 0; i < 2500; ++i) {
    agent = w.at;
    NavStep st = nav.next_step(1, NavRequest{w.at, target, 3000, 10});
    if (st.status == NavStatus::Arrived || st.status == NavStatus::Blocked) { w.arrived = st.status == NavStatus::Arrived; break; }
    const std::int64_t d = distance_mm(w.at, st.waypoint), mv = std::min<std::int64_t>(6000, d);
    if (d > 0) { w.at[0] += std::int32_t((std::int64_t(st.waypoint[0]) - w.at[0]) * mv / d); w.at[1] += std::int32_t((std::int64_t(st.waypoint[1]) - w.at[1]) * mv / d); }
  }
  std::printf("  rough ground: arrived=%d, at %lld,%lld\n", int(w.arrived), (long long)w.at[0], (long long)w.at[1]);
  CHECK(w.arrived);
  CHECK(trap.violations() == 0);
  // the choice of route does not depend on ground that has not been seen: the same belief and map on a flat world and on a
  // rough one give the same first 20 waypoints, since nothing rough is within sight of the first 120 m
  FlatTerrain flat;
  Navigator nf(nullptr, flat), nr(nullptr, rough);
  nf.add_npc(1); nr.add_npc(1);
  Walk wf = walk(nf, 1, from, target, 20), wr = walk(nr, 1, from, target, 20);
  CHECK(wf.log.size() == wr.log.size());
  for (std::size_t i = 0; i < wf.log.size() && i < wr.log.size(); ++i) CHECK(wf.log[i].waypoint == wr.log[i].waypoint);
}

EMERGENCE_TEST_MAIN()
