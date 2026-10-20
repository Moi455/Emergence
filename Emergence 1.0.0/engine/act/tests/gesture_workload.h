// A deterministic village for the executor: n NPC who, as soon as a gesture ends, "decide" the next one from a hash (no
// rand(), no clock): walking, taking, eating, drinking, working, striking, sleeping, resting, looking, speaking. Shared by the
// test (1/4/8 threads give the same digest; 500 NPC over one game day) and by the bench.
#pragma once
#include <cstdint>
#include <vector>

#include "gesture_rig.h"

namespace em::act::gwork {

struct Result {
  std::uint64_t chain = 0, store_fingerprint = 0;
  double step_seconds = 0;
  std::uint64_t gestures = 0, cycles = 0, emissions = 0, contacts = 0, store_alive = 0, refused = 0, failed = 0;
};

inline std::uint32_t mix(std::uint32_t x) {
  x ^= x >> 16; x *= 0x7feb352dU; x ^= x >> 15; x *= 0x846ca68bU; x ^= x >> 16;
  return x;
}

inline Result run(unsigned threads, unsigned npcs, unsigned ticks, std::size_t min_per_thread = 8) {
  using namespace grig;
  Rig r(threads, FlatNavigation{}, min_per_thread);
  std::vector<EntityId> people, logs, foods, jugs;
  const unsigned cols = 25;
  for (unsigned i = 0; i < npcs; ++i) {
    const Position p{static_cast<std::int32_t>((i % cols) * 15000), static_cast<std::int32_t>((i / cols) * 15000), 0};
    people.push_back(r.person(p));
  }
  const EntityId axe_proto = kNoEntity;
  (void)axe_proto;
  std::vector<EntityId> axes;
  for (unsigned i = 0; i < npcs; ++i) {
    const Position p = r.w.store.position_mm(people[i]);
    const EntityId food = r.w.spawn_item("bread_loaf", p), jug = r.w.spawn_item("water_jug", p), axe = r.w.spawn_item("felling_axe", p);
    for (EntityId e : {food, jug, axe}) r.w.bus.submit(make_move(++r.w.tick, 1, e, p, people[i]));
    foods.push_back(food); jugs.push_back(jug); axes.push_back(axe);
    logs.push_back(r.w.spawn_item("log", {p[0] + 3000, p[1] + 2000, 0}));
    r.minds.mind(people[i])->state.needs.hunger = static_cast<std::int16_t>(30 + mix(i) % 50);
  }
  r.w.bus.flush();
  std::vector<std::uint32_t> counter(npcs, 0);
  for (unsigned t = 0; t < ticks; ++t) {
    for (unsigned i = 0; i < npcs; ++i) {
      const EntityId a = people[i];
      if (r.ex->busy(a)) continue;
      const std::uint32_t h = mix(i * 7919u + counter[i]++ * 104729u + 17u);
      const std::uint32_t pick = h % 10;
      const Position here = r.w.store.position_mm(a);
      Dec d(a, Gesture::wait, counter[i]);
      switch (pick) {
        case 0: case 1: {
          d = Dec(a, Gesture::go, counter[i]);
          d.with("pace", (h >> 8) % 4 == 0 ? "run" : "walk").destination({static_cast<std::int32_t>(h % 300000), static_cast<std::int32_t>((h >> 9) % 150000), 0}).given("target");
          break;
        }
        case 2: d = Dec(a, Gesture::eat, counter[i]); d.target(foods[i]).with("amount", "all"); break;
        case 3: d = Dec(a, Gesture::drink, counter[i]); d.target(jugs[i]).with("amount", "some"); break;
        case 4: {
          d = Dec(a, Gesture::work, counter[i]);
          d.target(logs[(i + 1) % npcs]).tool(axes[i]).with("motion", "saw").with("duration", "brief");
          d.believed(r.w.store.position_mm(logs[(i + 1) % npcs]));
          break;
        }
        case 5: d = Dec(a, Gesture::rest, counter[i]); d.with("duration", "brief"); break;
        case 6: d = Dec(a, Gesture::look, counter[i]); d.target(people[(i + 1) % npcs]).stop(Condition::c_elapsed, 0, 64); break;
        case 7: {
          d = Dec(a, Gesture::speak, counter[i]);
          d.target(people[(i + 1) % npcs]).with("volume", "normal").with("tone", "calm").content(3);
          d.believed(r.w.store.position_mm(people[(i + 1) % npcs]));
          break;
        }
        case 8: d = Dec(a, Gesture::sleep, counter[i]); d.destination(here).until(Condition::c_elapsed, 0, 400); break;
        default: {
          d = Dec(a, Gesture::strike, counter[i]);
          d.target(logs[(i + 2) % npcs]).tool(axes[i]).with("intensity", "firm").with("motion", "swing").until(Condition::c_elapsed, 0, 160);
          d.believed(r.w.store.position_mm(logs[(i + 2) % npcs]));
        }
      }
      r.start(d);
    }
    r.tick();
  }
  Result out;
  out.chain = r.digest_chain;
  out.step_seconds = r.step_seconds;
  out.store_fingerprint = r.w.store.fingerprint();
  const ExecutorStats& s = r.ex->stats();
  for (int i = 0; i < 5; ++i) out.gestures += s.ended[i];
  out.failed = s.ended[1] + s.ended[2];
  out.refused = s.refused;
  out.cycles = s.cycles;
  out.emissions = s.emissions;
  out.contacts = s.contacts;
  out.store_alive = r.w.store.size();
  return out;
}

}  // namespace em::act::gwork
