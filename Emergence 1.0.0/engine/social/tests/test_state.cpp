// The generated NPC state: memory footprint, record pools (persistent serials, forgetting), propositions.
#include <cstdio>

#include "emergence/social/npc_store.h"
#include "emergence/testing/check.h"

using namespace em::social;

TEST(footprint_of_500_npcs) {
  NpcStore store(500);
  for (int i = 0; i < 500; ++i) store.add();
  const double mb = 500.0 * NpcStore::bytes_per_npc() / (1024.0 * 1024.0);
  std::printf("  NpcState = %zu octets ; 500 PNJ = %.1f Mo\n", NpcStore::bytes_per_npc(), mb);
  CHECK(store.size() == 500);
  CHECK(mb < 64.0);
}

TEST(pool_forgets_the_least_important) {
  RecordPool<gen::Belief, 384> pool;
  auto score = [](const gen::Belief& b) { return int(b.b_importance); };
  MRef keep{};
  for (int i = 0; i < 384; ++i) {
    gen::Belief b;
    b.b_importance = static_cast<std::int16_t>(i == 7 ? 100 : 10 + (i % 50));
    MRef r = pool.add(b, score);
    if (i == 7) keep = r;
  }
  CHECK_EQ(pool.size(), 384);
  gen::Belief fresh;
  fresh.b_importance = 90;
  MRef r = pool.add(fresh, score);
  CHECK_EQ(pool.size(), 384);
  CHECK(pool.find(r) != nullptr);
  CHECK(pool.find(keep) != nullptr);
  CHECK(pool.remove(r));
  CHECK(pool.find(r) == nullptr);
}

TEST(proposition_is_one_tree) {
  Proposition p;
  CHECK(p.push(Proposition::make(Proposition::kWord, 1), 3));
  CHECK(p.push(Proposition::make(Proposition::kRef, 42), 0));
  CHECK(p.push(Proposition::make(Proposition::kWord, 2), 0));
  CHECK(p.push(Proposition::make(Proposition::kWord, 3), 0));
  CHECK(p.well_formed());
  Proposition bad;
  bad.push(Proposition::make(Proposition::kWord, 1), 2);
  CHECK(!bad.well_formed());
}

EMERGENCE_TEST_MAIN()
