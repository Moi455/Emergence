// bench_navigation [npcs] [known_tiles] [reps]: cost of planning for N NPCs (long routes across the 20 km plan, partial
// knowledge), and of one Navigator step per NPC (journey kept). Prints the best of `reps`.
#include <algorithm>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <vector>

#include "emergence/act/navigation/navigator.h"

using namespace em::act::navigation;

int main(int argc, char** argv) {
  const int n = argc > 1 ? std::atoi(argv[1]) : 500, known = argc > 2 ? std::atoi(argv[2]) : 300, reps = argc > 3 ? std::atoi(argv[3]) : 7;
  RoadPlan roads;
  auto a = roads.add_node({2'700'000, 2'700'000, 0}), b = roads.add_node({9'000'000, 9'000'000, 0});
  roads.add_segment(a, b);
  std::uint64_t s = 99;
  auto rnd = [&](std::uint32_t m) { s = s * 6364136223846793005ull + 1442695040888963407ull; return std::uint32_t(s >> 33) % m; };
  auto pos = [&] { return Position{std::int32_t(rnd(19'000)) * 1000, std::int32_t(rnd(19'000)) * 1000, 0}; };
  std::vector<MentalMap> maps(static_cast<std::size_t>(n));
  std::vector<Position> from, to;
  for (auto& m : maps) { for (int i = 0; i < known; ++i) m.see_position(pos()); if (rnd(2)) m.see_segment(0); from.push_back(pos()); to.push_back(pos()); }
  RoutePlanner pl(&roads);
  double best = 1e9; std::uint64_t exp = 0; int over = 0;
  for (int r = 0; r < reps; ++r) {
    exp = 0; over = 0;
    const auto t0 = std::chrono::steady_clock::now();
    for (int i = 0; i < n; ++i) { Plan p = pl.plan(maps[std::size_t(i)], 5, from[std::size_t(i)], to[std::size_t(i)]); exp += p.expansions; over += p.status != PlanStatus::Found; }
    best = std::min(best, std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0).count());
  }
  std::printf("plan: %d NPCs, %d known tiles each: best %.2f ms (%.1f us per plan), %llu expansions, %d not found\n", n, known, best, best * 1000 / n, (unsigned long long)exp, over);

  FlatTerrain ground;
  Navigator nav(&roads, ground);
  for (int i = 0; i < n; ++i) nav.add_npc(em::act::EntityId(i + 1));
  std::vector<Position> at = from;
  double step_best = 1e9;
  for (int r = 0; r < reps; ++r) {
    const auto t0 = std::chrono::steady_clock::now();
    for (int i = 0; i < n; ++i) {
      NavStep st = nav.next_step(em::act::EntityId(i + 1), NavRequest{at[std::size_t(i)], to[std::size_t(i)], 3000, 5});
      at[std::size_t(i)] = st.waypoint;
    }
    step_best = std::min(step_best, std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0).count());
  }
  std::printf("next_step (journey kept, one per NPC): best %.3f ms for %d NPCs\n", step_best, n);
  std::printf("memory per NPC: sizeof(MentalMap)=%zu, sizeof(Plan)=%zu\n", sizeof(MentalMap), sizeof(Plan));
}
