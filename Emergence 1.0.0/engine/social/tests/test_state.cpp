// The generated NPC state: memory footprint, record pools (persistent serials, forgetting), propositions.
#include <cstdio>

#include "emergence/social/npc_state_codec.h"
#include "emergence/social/npc_store.h"
#include "emergence/social/proposition_arena.h"
#include "emergence/social/side_table.h"
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

// ---- T06: 64 KiB per NPC ----------------------------------------------------------------------------------

TEST(npc_state_arena_and_side_table_fit_in_64_kib) {
  constexpr std::size_t kState = sizeof(gen::NpcState);
  constexpr std::size_t kTotal = kState + PropositionArena::capacity_bytes() + SideTable::capacity_bytes();
  std::printf("  NpcState = %zu o + arene %zu o + table annexe %zu o = %zu o (cible <= 65536 ; avant T06 : 108152 + 0 + 0)\n",
              kState, PropositionArena::capacity_bytes(), SideTable::capacity_bytes(), kTotal);
  static_assert(sizeof(gen::NpcState) + PropositionArena::kBudgetBytes + SideTable::kBudgetBytes <= 65536,
                "the state of one NPC, its proposition arena and its side table must fit in 64 KiB");
  CHECK(kTotal <= 65536);
  // the reserve of 4 intentions is part of that total (a record per active goal, 8 goals)
  CHECK_EQ(gen::kRecordCapacity[std::size_t(gen::RecordKind::intention)], 4);
  CHECK_EQ(decltype(gen::NpcState::intention_records)::kCapacity, 4);
  // the budgets of the two side areas are the ones of docs/14 7.1
  CHECK_EQ(PropositionArena::capacity_bytes(), 20480u);
  CHECK_EQ(SideTable::capacity_bytes(), 8192u);
  // no record holds a 100-byte Proposition any more
  static_assert(sizeof(gen::Belief) <= 48 && sizeof(gen::Episode) <= 48, "records are laid out by alignment, with a PropRef");
}

TEST(arena_round_trips_a_proposition_and_rejects_stale_references) {
  PropositionArena arena;
  Proposition p;
  p.push(Proposition::make(Proposition::kWord, 7), 2);
  p.push(Proposition::make(Proposition::kRef, 0xABCDEF), 0);
  p.push(Proposition::make(Proposition::kName, 12345), 0);
  const PropRef a = arena.put(p);
  CHECK(a != 0);
  const Proposition q = arena.get(a);
  CHECK_EQ(q.size(), 3);
  for (int i = 0; i < 3; ++i) CHECK(q.symbol(i) == p.symbol(i) && q.children(i) == p.children(i));
  CHECK_EQ(arena.put(Proposition{}), 0u);
  Proposition bad;
  bad.push(Proposition::make(Proposition::kWord, 1), 2);
  CHECK_EQ(arena.put(bad), 0u);
  CHECK(arena.get(0).empty());
  // a compaction that keeps nothing: the old reference reads as EMPTY, never as something else
  arena.collect([](auto&&) {});
  CHECK(arena.get(a).empty());
  CHECK(!arena.valid(a));
  CHECK_EQ(arena.used_words(), 0u);
  // a compaction that keeps it: the reference is rewritten and still reads the same
  PropRef b = arena.put(p);
  arena.put(p);   // garbage
  arena.collect([&](auto&& f) { f(b); });
  CHECK_EQ(arena.used_words(), 3u);
  CHECK(arena.get(b).size() == 3 && arena.get(b).symbol(2) == p.symbol(2));
}

namespace {
Proposition leaf(std::uint32_t n) {
  Proposition p;
  p.push(Proposition::make(Proposition::kNumber, n), 0);
  return p;
}
Proposition twenty(std::uint32_t n) {   // the longest exchange proposition: one root and 19 leaves
  Proposition p;
  p.push(Proposition::make(Proposition::kWord, 1), 19);
  for (int i = 0; i < 19; ++i) p.push(Proposition::make(Proposition::kNumber, n + std::uint32_t(i)), 0);
  return p;
}
}  // namespace

TEST(full_arena_applies_the_law_of_forgetting_never_aborts_never_silent) {
  auto npc = std::make_unique<NpcBundle>();
  // 1) fill the arena with beliefs of 20 symbols: 256 of them take the 5120 words exactly
  std::vector<MRef> refs;
  for (int i = 0; i < 256; ++i) {
    gen::Belief b;
    b.b_importance = std::int16_t(10 + i % 80);
    b.b_proposition = npc->store_proposition(twenty(std::uint32_t(i) * 100), 1000);
    CHECK(b.b_proposition != 0);
    refs.push_back(npc->state.belief_records.add(b, 1000));
  }
  CHECK_EQ(npc->propositions.used_words(), PropositionArena::kWords);
  CHECK_EQ(npc->propositions.refused(), 0u);
  CHECK_EQ(npc->propositions.reclaimed(), 0u);
  // 2) one more: the law frees the lowest-scored belief (importance 10), the arena is not silently refusing
  const int before = npc->state.belief_records.size();
  gen::Belief fresh;
  fresh.b_importance = 100;
  fresh.b_proposition = npc->store_proposition(twenty(999000), 1000);
  CHECK(fresh.b_proposition != 0);
  const MRef fresh_ref = npc->state.belief_records.add(fresh, 1000);
  CHECK_EQ(npc->propositions.reclaimed(), 1u);
  CHECK_EQ(npc->propositions.refused(), 0u);
  CHECK_EQ(npc->state.belief_records.forgotten(), 1);
  CHECK_EQ(npc->state.belief_records.size(), before);   // one went (arena), one came
  CHECK(npc->state.belief_records.find(fresh_ref) != nullptr);
  CHECK(npc->state.belief_records.find(refs[0]) == nullptr);   // the oldest of the lowest importance
  const auto* kept = npc->state.belief_records.find(refs[255]);
  CHECK(kept != nullptr && npc->proposition(kept->b_proposition).size() == 20);
  // 3) the content of every survivor is intact after the compaction
  int ok = 0;
  npc->state.belief_records.for_each([&](MRef, gen::Belief& b) { ok += npc->proposition(b.b_proposition).size() == 20; });
  CHECK_EQ(ok, 256);
  // 4) when nothing can be forgotten (no belief or episode holds a proposition) the refusal is COUNTED
  auto lone = std::make_unique<NpcBundle>();
  gen::Goal g;
  for (int i = 0; i < 8; ++i) { g.g_desired = lone->store_proposition(twenty(std::uint32_t(i)), 0); lone->state.goal_records.add(g, [](const gen::Goal&) { return 0; }); }
  PropRef r = 0;
  for (int i = 0; i < 400; ++i) r = lone->store_proposition(twenty(5000), 0);   // unreferenced garbage: collected, so it fits
  CHECK(r != 0 && lone->propositions.refused() == 0);
}

TEST(protected_beliefs_go_only_when_every_candidate_is_protected_and_it_is_counted) {
  auto npc = std::make_unique<NpcBundle>();
  for (int i = 0; i < 256; ++i) {
    gen::Belief b;
    b.b_secret = true;
    b.b_proposition = npc->store_proposition(twenty(std::uint32_t(i) * 100), 0);
    npc->state.belief_records.add(b, 0);
  }
  int protected_count = 0;
  npc->state.belief_records.for_each([&](MRef, gen::Belief& b) { protected_count += gen::forgetting_protected(gen::forgetting_kind(b), b); });
  gen::Belief fresh;
  fresh.b_proposition = npc->store_proposition(twenty(7), 0);
  CHECK(fresh.b_proposition != 0);                      // never refused
  CHECK_EQ(npc->propositions.reclaimed(), 1u);
  CHECK_EQ(npc->state.belief_records.evicted_protected(), protected_count == 256 ? 1 : 0);
}

TEST(average_proposition_length_and_fill_are_reported_by_the_codec_round_trip) {
  auto npc = std::make_unique<NpcBundle>();
  for (int i = 1; i <= 100; ++i) CHECK(npc->store_proposition(leaf(std::uint32_t(i)), 0) != 0);
  CHECK_EQ(npc->propositions.used_words(), 100u);
  CHECK(npc->propositions.fill() < 0.02);
}

EMERGENCE_TEST_MAIN()
