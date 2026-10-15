// Rates of the laws of matter in processes per second: the laws alone (read + emit), then with the bus and the store.
// Usage: bench_matter_laws [n]
#include <chrono>
#include <cstdio>
#include <cstdlib>

#include "../tests/matter_rig.h"

using namespace em::act;
using em::act::rig::World;

namespace {
struct Spec { const char* name; const char* target; const char* tool; Manner manner; std::int32_t speed; bool joint; };
}

int main(int argc, char** argv) {
  const int n = argc > 1 ? std::atoi(argv[1]) : 20000;
  const Spec specs[] = {
      {"cut", "log", "knife", Manner::Slice, 0, false},
      {"split", "log", "battle_axe", Manner::Strike, 6000, false},
      {"fracture", "stone_block", "sledgehammer", Manner::Strike, 9000, false},
      {"crush", "wheat_sack", "sledgehammer", Manner::Strike, 5000, false},
      {"disassemble", "door", "sledgehammer", Manner::Strike, 6000, true},
      {"carve", "log", "knife", Manner::Carve, 0, false},
      {"abrade", "hatchet", "whetstone", Manner::Rub, 0, false},
  };
  std::printf("%-12s %14s %18s\n", "process", "laws /s", "bus+store /s");
  for (const Spec& sp : specs) {
    World w;
    ProcessEngine eng(w.catalog, w.store, w.ground);
    EntityId tool = w.spawn_item(sp.tool, {-5000, 0, 0});
    std::vector<Contact> cs;
    for (int i = 0; i < n; ++i) {
      EntityId t = w.spawn_item(sp.target, {(i % 300) * 3000, 0, (i / 300) * 3000});
      Contact c;
      c.author = 1000 + static_cast<std::uint32_t>(i); c.tool = tool; c.target = t; c.manner = sp.manner; c.speed_mm_s = sp.speed; c.at_joint = sp.joint;
      cs.push_back(c);
    }
    auto t0 = std::chrono::steady_clock::now();
    std::vector<Emission> out;
    auto reps = eng.on_contacts(cs, w.tick + 1, out);
    auto t1 = std::chrono::steady_clock::now();
    w.submit_flush(out);
    auto t2 = std::chrono::steady_clock::now();
    int done = 0;
    for (const auto& r : reps) done += r.outcome == Outcome::Done || r.outcome == Outcome::Progress;
    double law = std::chrono::duration<double>(t1 - t0).count(), full = std::chrono::duration<double>(t2 - t0).count();
    std::printf("%-12s %14.0f %18.0f   (%d/%d took effect, %zu operations)\n", sp.name, n / law, n / full, done, n, out.size());
  }
  // Time laws: margins, collapse, falls over a world of n bodies.
  World w;
  ProcessEngine eng(w.catalog, w.store, w.ground);
  for (int i = 0; i < n; ++i) w.spawn_item("brick", {(i % 300) * 3000, 0, (i / 300) * 3000});
  auto t0 = std::chrono::steady_clock::now();
  std::vector<Emission> out;
  eng.tick_time(w.tick + 1, out);
  double s = std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count();
  std::printf("tick_time over %d bodies: %.1f ms (%.0f bodies/s)\n", n, s * 1000, n / s);
  return 0;
}
