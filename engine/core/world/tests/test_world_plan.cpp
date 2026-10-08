#include <algorithm>
#include <cstdio>
#include <cstdlib>

#include "emergence/base/fingerprint.h"
#include "emergence/base/parallel.h"
#include "emergence/testing/check.h"
#include "emergence/world/world_plan.h"

using namespace em;

namespace {

// Small maps keep the tests fast; the layout is the 20 km one, scaled.
const WorldPlan& small_plan() {
  static const WorldPlan p = generate_world_plan(WorldParams::scaled(7, 4096));
  return p;
}

bool is_neighbour(const WorldPlan& p, uint32_t a, uint32_t b) {
  int ai = static_cast<int>(a % static_cast<uint32_t>(p.n)), aj = static_cast<int>(a / static_cast<uint32_t>(p.n));
  int bi = static_cast<int>(b % static_cast<uint32_t>(p.n)), bj = static_cast<int>(b / static_cast<uint32_t>(p.n));
  return std::abs(ai - bi) <= 1 && std::abs(aj - bj) <= 1 && a != b;
}

}  // namespace

TEST(plan_is_deterministic_across_threads) {
  WorldParams wp = WorldParams::scaled(11, 2048);
  set_worker_count(1);
  uint64_t a = generate_world_plan(wp).fingerprint();
  set_worker_count(4);
  uint64_t b = generate_world_plan(wp).fingerprint();
  set_worker_count(0);
  CHECK_EQ(a, b);
  CHECK(a != generate_world_plan(WorldParams::scaled(12, 2048)).fingerprint());
}

TEST(plan_golden_fingerprint) {
  // Pinned reference: a change here means every world changed. Bump
  // kWorldGeneratorVersion and update the value on purpose, never silently.
  std::printf("  small plan fingerprint %s\n", to_hex(small_plan().fingerprint()).c_str());
  CHECK_EQ(small_plan().fingerprint(), 0x4a49eb06561e8c9dULL);
}

TEST(frontiers_layout) {
  const WorldPlan& p = small_plan();
  int mid = p.n / 2;
  CHECK_EQ(p.march_side[p.idx(0, mid)], static_cast<uint8_t>(Side::West));
  CHECK_EQ(p.march_side[p.idx(p.n - 1, mid)], static_cast<uint8_t>(Side::East));
  CHECK_EQ(p.march_side[p.idx(mid, p.n - 1)], static_cast<uint8_t>(Side::North));
  CHECK_EQ(p.march_side[p.idx(mid, 0)], static_cast<uint8_t>(Side::South));
  CHECK_EQ(p.march_side[p.idx(mid, mid)], static_cast<uint8_t>(Side::None));
  CHECK_EQ(p.hostility_q16(p.idx(mid, mid)), 65536);
  // Hostility at the edge is about 2^10 (doubling every 300 m over 3 km).
  int64_t h_edge = p.hostility_q16(p.idx(0, mid)) >> 16;
  std::printf("  hostility at west edge: %lld, depth %d m\n", static_cast<long long>(h_edge), p.march_depth_m[p.idx(0, mid)]);
  CHECK(h_edge > 50 && h_edge < 20000);
  CHECK(p.flags[p.idx(0, mid)] & kFlagSea);
  CHECK(!(p.flags[p.idx(p.n - 1, mid)] & kFlagSea));
  // Mountains on the north edge are the highest ground.
  int32_t north = 0, south = 0;
  for (int i = 0; i < p.n; ++i) {
    north = std::max(north, p.height_mm[p.idx(i, p.n - 1)]);
    south = std::max(south, p.height_mm[p.idx(i, 0)]);
  }
  CHECK(north > 2'000'000);
  CHECK(north > south);
}

TEST(drainage_reaches_an_outlet) {
  const WorldPlan& p = small_plan();
  int stuck = 0;
  for (int32_t j = 1; j < p.n; j += 37)
    for (int32_t i = 1; i < p.n; i += 41) {
      size_t c = p.idx(i, j);
      int steps = 0;
      while (p.receiver[c] != kNoReceiver && steps < p.n * p.n) {
        int32_t ci = static_cast<int32_t>(c % static_cast<size_t>(p.n)) + kDirDi[p.receiver[c]];
        int32_t cj = static_cast<int32_t>(c / static_cast<size_t>(p.n)) + kDirDj[p.receiver[c]];
        c = p.idx(ci, cj);
        ++steps;
      }
      int32_t ci = static_cast<int32_t>(c % static_cast<size_t>(p.n)), cj = static_cast<int32_t>(c / static_cast<size_t>(p.n));
      bool outlet = ci == 0 || cj == 0 || ci == p.n - 1 || cj == p.n - 1 || p.height_mm[c] < 0;
      stuck += !outlet;
    }
  CHECK_EQ(stuck, 0);
}

TEST(settlements_and_roads) {
  const WorldPlan& p = small_plan();
  CHECK_EQ(p.settlements.size(), 5u);
  for (const auto& s : p.settlements) {
    size_t c = p.idx(s.i, s.j);
    CHECK(!(p.flags[c] & (kFlagSea | kFlagLake | kFlagRiver)));
    if (s.kind == SettlementKind::Town) CHECK_EQ(p.march_side[c], static_cast<uint8_t>(Side::None));
  }
  CHECK_EQ(p.roads.size(), 8u);
  for (const auto& r : p.roads) {
    const auto& a = p.settlements[static_cast<size_t>(r.from)];
    const auto& b = p.settlements[static_cast<size_t>(r.to)];
    CHECK_EQ(r.cells.front(), p.idx(a.i, a.j));
    CHECK_EQ(r.cells.back(), p.idx(b.i, b.j));
    bool ok = true;
    for (size_t k = 1; k < r.cells.size(); ++k) ok &= is_neighbour(p, r.cells[k - 1], r.cells[k]);
    for (uint32_t c : r.cells) ok &= !(p.flags[c] & (kFlagSea | kFlagLake));
    CHECK(ok);
  }
}

TEST(full_map_under_30_seconds) {
  // Roadmap M1 criterion (measured here on the build machine, not on the
  // reference laptop): plan of 20 x 20 km, backdrop included, < 30 s.
  if (std::getenv("EMERGENCE_SKIP_SLOW")) return;
  WorldPlan p = generate_world_plan(WorldParams{});
  std::printf("  20 km plan: %.0f ms, fingerprint %s\n", p.timings.total_ms, to_hex(p.fingerprint()).c_str());
  CHECK(p.timings.total_ms < 30000.0);
  CHECK_EQ(p.fingerprint(), 0x6a24a0d52057c0dfULL);
}

EMERGENCE_TEST_MAIN()
