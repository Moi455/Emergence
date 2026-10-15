// The law of forgetting (T05): parity with the Python oracle, protection, a full store, independence from the truth.
#include <cstdio>

#include "emergence/social/clock.h"
#include "emergence/social/npc_store.h"
#include "emergence/testing/check.h"
#include "forgetting_parity.inc"

using namespace em::social;

namespace {
constexpr GameTime kNow = kParityNow;

struct Fnv {   // FNV-1a 64, like tools/forgetting.py
  std::uint64_t h = 0xcbf29ce484222325ull;
  void byte(std::uint8_t b) { h = (h ^ b) * 0x100000001b3ull; }
  void score(std::int32_t s, bool prot) {
    const auto u = static_cast<std::uint32_t>(s);
    for (int i = 0; i < 4; ++i) byte(static_cast<std::uint8_t>(u >> (8 * i)));
    byte(prot ? 1 : 0);
  }
};

template <class Rec>
void hash_one(Fnv& f, gen::RecordKind kind, gen::SplitMix64& rng) {
  Rec r;
  gen::forgetting_randomize(r, rng, kNow);
  f.score(gen::forgetting_score(kind, r, kNow), gen::forgetting_protected(kind, r));
}
}  // namespace

TEST(season_is_the_clock_season) {
  CHECK_EQ(gen::kSeasonSeconds, WorldClock::kRealSecondsPerSeason * WorldClock::kGamePerReal);
}

TEST(parity_with_the_python_oracle) {
  gen::SplitMix64 rng{kParitySeed};
  Fnv f;
  for (int i = 0; i < kParityRecords; ++i) {
    switch (static_cast<gen::RecordKind>(i % int(gen::RecordKind::kCount))) {
#define KIND(K, T) case gen::RecordKind::K: hash_one<gen::T>(f, gen::RecordKind::K, rng); break;
      KIND(belief, Belief) KIND(relation, Relation) KIND(episode, Episode) KIND(goal, Goal)
      KIND(intention, Intention) KIND(request, Request) KIND(skill, Skill) KIND(percept, Percept)
      KIND(event_seen, EventSeen) KIND(entity_percept, EntityPercept) KIND(place_percept, PlacePercept)
      KIND(locus, Locus)
#undef KIND
      default: CHECK(false);
    }
  }
  std::printf("  %d enregistrements, empreinte %016llx\n", kParityRecords, static_cast<unsigned long long>(f.h));
  CHECK(f.h == kParityHash);
}

TEST(twelve_kinds_one_capacity_each) {
  CHECK_EQ(int(gen::RecordKind::kCount), 12);
  CHECK_EQ(gen::kRecordCapacity[int(gen::RecordKind::belief)], 384);
  CHECK_EQ(gen::kRecordCapacity[int(gen::RecordKind::episode)], 128);
}

TEST(the_score_never_reads_the_truth) {
  gen::Belief a, b;
  a.b_importance = b.b_importance = 30;
  b.b_truth = true;
  b.b_origin_fact = 987654;
  CHECK_EQ(gen::forgetting_score(gen::RecordKind::belief, a, kNow), gen::forgetting_score(gen::RecordKind::belief, b, kNow));
  gen::Episode e1, e2;
  e2.m_fact_ref = 4242;
  CHECK_EQ(gen::forgetting_score(gen::RecordKind::episode, e1, kNow), gen::forgetting_score(gen::RecordKind::episode, e2, kNow));
  gen::Relation r1, r2;
  r2.r_true_entity = 77;
  CHECK_EQ(gen::forgetting_score(gen::RecordKind::relation, r1, kNow), gen::forgetting_score(gen::RecordKind::relation, r2, kNow));
}

TEST(a_recency_counts_in_seasons) {
  gen::Episode fresh, one, old;
  fresh.m_when = kNow;
  one.m_when = kNow - 4 * gen::kSeasonSeconds;   // one half-life
  old.m_when = kNow - 40 * gen::kSeasonSeconds;
  const auto sf = gen::forgetting_score(gen::RecordKind::episode, fresh, kNow);
  const auto s1 = gen::forgetting_score(gen::RecordKind::episode, one, kNow);
  CHECK_EQ(sf, 30 * 100);   // weight 30 (3 points of 1000) x recency 100
  CHECK_EQ(s1, 30 * 50);
  CHECK_EQ(gen::forgetting_score(gen::RecordKind::episode, old, kNow), 0);
}

TEST(a_defining_memory_is_never_forgotten) {
  RecordPool<gen::Episode, 128> pool;
  gen::Episode keep;
  keep.m_defining = true;   // lowest score of all: it would be the first to go
  keep.m_importance = 0;
  const MRef kept = pool.add(keep, kNow);
  CHECK(kept.serial != 0);
  for (int i = 0; i < 1000; ++i) {
    gen::Episode e;
    e.m_importance = static_cast<std::int16_t>(10 + i % 80);
    e.m_when = kNow - (i % 20) * gen::kSeasonSeconds;
    pool.add(e, kNow);
    CHECK(pool.find(kept) != nullptr);
  }
  CHECK_EQ(pool.size(), 128);
  CHECK_EQ(pool.evicted_protected(), 0);   // the defining memory was spared because others could go
  CHECK(pool.forgotten() > 800);
}

TEST(a_full_pool_of_protected_memories_evicts_the_worst_protected_and_counts) {
  RecordPool<gen::Episode, 128> pool;
  MRef weakest{}, oldest_tie{};
  for (int i = 0; i < 128; ++i) {
    gen::Episode e;
    e.m_defining = true;
    e.m_importance = static_cast<std::int16_t>(50 + i % 40);
    e.m_when = kNow;
    if (i == 77) e.m_importance = 1;   // the weakest of the protected: the one to go
    const MRef r = pool.add(e, kNow);
    CHECK(r.serial != 0);
    if (i == 77) weakest = r;
    if (i == 0) oldest_tie = r;
  }
  CHECK_EQ(pool.evicted_protected(), 0);
  gen::Episode more;
  more.m_defining = true;
  more.m_importance = 100;
  more.m_when = kNow;
  const MRef added = pool.add(more, kNow);
  CHECK(added.serial != 0);                 // the NPC keeps forming memories: no refusal
  CHECK(pool.find(weakest) == nullptr);     // the worst protected record went
  CHECK(pool.find(oldest_tie) != nullptr);
  CHECK(pool.find(added) != nullptr);
  CHECK_EQ(pool.evicted_protected(), 1);
  CHECK_EQ(pool.size(), 128);
  // equal scores among protected records: the oldest serial goes
  RecordPool<gen::Episode, 4> ties;
  MRef first{};
  for (int i = 0; i < 4; ++i) {
    gen::Episode e;
    e.m_defining = true;
    e.m_importance = 30;
    e.m_when = kNow;
    const MRef r = ties.add(e, kNow);
    if (i == 0) first = r;
  }
  gen::Episode e;
  e.m_defining = true;
  e.m_importance = 30;
  e.m_when = kNow;
  CHECK(ties.add(e, kNow).serial != 0);
  CHECK(ties.find(first) == nullptr);
  CHECK_EQ(ties.evicted_protected(), 1);
  CHECK_EQ(ties.size(), 4);
}

TEST(a_tie_forgets_the_oldest) {
  RecordPool<gen::Skill, 26> pool;
  MRef first{};
  for (int i = 0; i < 26; ++i) {
    gen::Skill k;
    k.k_mastery = 5;
    k.k_last_practice = kNow;
    const MRef r = pool.add(k, kNow);
    if (i == 0) first = r;
  }
  gen::Skill k;
  k.k_mastery = 5;
  k.k_last_practice = kNow;
  const MRef r = pool.add(k, kNow);
  CHECK(pool.find(first) == nullptr);
  CHECK(pool.find(r) != nullptr);
}

EMERGENCE_TEST_MAIN()
