// bench_perception [observers] [entities] [threads] [side_m] [ticks] [walls] [cadence]: cost of one perception step. A deterministic village
// (no rand, no clock in the simulation): `observers` NPCs and `entities` other things (people, beasts, items, plants,
// buildings) spread on a square of `side_m` metres, with some walls. Prints the time per tick, the pairs examined, the
// observers x entities per second and the per-NPC cost. Target (docs/15 T23): 500 NPCs in < 10 ms per tick [Estime].
#include <algorithm>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <memory>
#include <vector>

#include "emergence/act/perception/perception_engine.h"
#include "emergence/ops/operation_bus.h"

using namespace em::act;
using namespace em::act::perception;

static std::uint32_t mix(std::uint32_t x) {
  x ^= x >> 16; x *= 0x7feb352dU; x ^= x >> 15; x *= 0x846ca68bU; x ^= x >> 16;
  return x;
}

int main(int argc, char** argv) {
  const int n_obs = argc > 1 ? std::atoi(argv[1]) : 500;
  const int n_ent = argc > 2 ? std::atoi(argv[2]) : 3000;
  const unsigned threads = argc > 3 ? unsigned(std::atoi(argv[3])) : 1;
  const int side_m = argc > 4 ? std::atoi(argv[4]) : 300;
  const int ticks = argc > 5 ? std::atoi(argv[5]) : 20;
  const int walls = argc > 6 ? std::atoi(argv[6]) : side_m / 4;   // 0 = an empty space: the engine's own cost without the rays
  EntityStore store;
  em::ops::OperationBus bus;
  bus.add_applier(&store);
  std::uint64_t tick = 0;
  auto pos = [&](std::uint32_t i, std::uint32_t salt) {
    return Position{std::int32_t(mix(i * 2 + salt) % std::uint32_t(side_m * 1000)), std::int32_t(mix(i * 2 + 1 + salt * 7) % std::uint32_t(side_m * 1000)), 0};
  };
  std::vector<EntityId> who;
  for (int i = 0; i < n_obs; ++i) {
    bus.submit(make_spawn(++tick, 1, std::uint16_t(gen::EntityKind::agent), pos(i, 1)));
    bus.flush();
  }
  store.for_each([&](EntityId id, gen::EntityKind) { who.push_back(id); });
  static constexpr gen::EntityKind kinds[] = {gen::EntityKind::agent, gen::EntityKind::animal, gen::EntityKind::item, gen::EntityKind::item,
                                              gen::EntityKind::plant, gen::EntityKind::structure, gen::EntityKind::item};
  for (int i = 0; i < n_ent; ++i) bus.submit(make_spawn(++tick, 1 + i % 50, std::uint16_t(kinds[mix(i) % 7]), pos(i, 5), kNoEntity, std::uint16_t(10 + mix(i + 3) % 200)));
  bus.flush();
  FlatSpace space;
  for (int i = 0; i < walls; ++i) space.block(int(mix(i) % side_m), int(mix(i + 99) % side_m), int(mix(i) % side_m) + 6, int(mix(i + 99) % side_m));   // walls
  CatalogueThings things;
  const unsigned cadence = argc > 7 ? unsigned(std::atoi(argv[7])) : 1;
  PerceptionConfig cfg;
  cfg.threads = threads;
  cfg.cadence = cadence;
  PerceptionEngine eng(store, space, things, cfg);
  std::vector<std::unique_ptr<em::social::NpcBundle>> minds;
  std::vector<Observer> obs;
  for (int i = 0; i < n_obs; ++i) {
    minds.push_back(std::make_unique<em::social::NpcBundle>());
    auto& b = *minds.back();
    b.state.body.alive = true; b.state.body.vision = 90; b.state.body.hearing = 80; b.state.body.consciousness = 100;
    b.state.mind_static.perceptiveness = std::int16_t(20 + mix(i) % 60);
    obs.emplace_back(who[std::size_t(i)], b);
  }
  eng.tick(obs, 20000);   // warm-up: the records are created
  std::vector<double> ms;
  PerceptionStats last;
  for (int t = 0; t < ticks; ++t) {
    auto t0 = std::chrono::steady_clock::now();
    const PerceptionReport& rep = eng.tick(obs, 20000 + 16 * (t + 1));
    ms.push_back(std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0).count());
    last = rep.stats;
  }
  std::sort(ms.begin(), ms.end());
  const double med = ms[ms.size() / 2], best = ms.front(), worst = ms.back();
  const double pairs_world = double(n_obs) * double(store.size());
  std::printf("%d observers, %zu entities alive, %u thread(s), %d m side, cadence %u\n", n_obs, store.size(), threads, side_m, cadence);
  std::printf("tick: best %.2f ms, median %.2f ms, worst %.2f ms   (%.1f us per NPC at the median)\n", best, med, worst, med * 1000 / n_obs);
  std::printf("candidates examined per tick: %llu (people kept %llu, things kept %llu); grid cull: %.1f%% of the %.0f observer x entity pairs\n",
              (unsigned long long)last.candidates, (unsigned long long)last.perceived_people, (unsigned long long)last.perceived_things,
              100.0 * (1.0 - double(last.candidates) / pairs_world), pairs_world);
  std::printf("phases (CPU, summed over the NPCs): scan %.2f ms (%llu line-of-sight queries), write %.2f ms\n", double(last.scan_ns) / 1e6,
              (unsigned long long)last.rays, double(last.write_ns) / 1e6);
  std::printf("throughput: %.1f M candidates/s, %.0f M observer x entity pairs/s (counting the culled ones)\n",
              double(last.candidates) / (med / 1000) / 1e6, pairs_world / (med / 1000) / 1e6);
  return 0;
}
