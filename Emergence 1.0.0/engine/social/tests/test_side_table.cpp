// SideTable: 1M random operations against a std::vector oracle, determinism, stale references.
#include <cstdint>
#include <cstdio>
#include <vector>

#include "emergence/social/side_table.h"
#include "emergence/testing/check.h"

using namespace em::social;

namespace {
struct Rng {   // fixed-seed xorshift64*, no std::random dependence
  std::uint64_t s;
  std::uint32_t next() {
    s ^= s >> 12; s ^= s << 25; s ^= s >> 27;
    return static_cast<std::uint32_t>((s * 2685821657736338717ull) >> 32);
  }
};
struct Entry { ListRef ref; std::vector<std::uint32_t> data; };

struct Outcome { std::uint64_t hash; long mismatches; std::size_t truncs; std::size_t compactions; };

Outcome run(std::uint64_t seed, int ops) {
  Rng rng{seed};
  SideTable t;
  std::vector<Entry> live;
  std::vector<ListRef> dead;
  Outcome out{0, 0, 0, 0};
  for (int i = 0; i < ops; ++i) {
    const std::uint32_t r = rng.next() % 100;
    if (r < 38) {
      std::vector<std::uint32_t> v(rng.next() % 40);
      for (auto& x : v) x = rng.next();
      const std::size_t cap = (rng.next() % 4 == 0) ? 1 + rng.next() % 20 : SideTable::kNoLimit;
      const ListRef ref = t.put(v, cap);
      if (v.size() > cap) v.resize(cap);
      auto got = t.get(ref);
      if (ref == 0) {
        if (!v.empty() && got.size() != 0) ++out.mismatches;
        // nothing fitted: compact and retry once
        if (!v.empty()) {
          Remap rm;
          t.compact(rm);
          ++out.compactions;
          for (auto& e : live) e.ref = rm.map(e.ref);
          const ListRef again = t.put(v, cap);
          auto g2 = t.get(again);
          if (again != 0) {
            if (g2.size() > v.size()) ++out.mismatches;
            v.resize(g2.size());
            live.push_back({again, v});
          }
        }
      } else {
        if (got.size() > v.size()) { ++out.mismatches; continue; }
        v.resize(got.size());   // truncation is a prefix: verified below by comparing content
        live.push_back({ref, v});
      }
    } else if (r < 76 && !live.empty()) {
      const std::size_t k = rng.next() % live.size();
      dead.push_back(live[k].ref);
      t.release(live[k].ref);
      live[k] = live.back();
      live.pop_back();
    } else if (r < 77) {
      Remap rm;
      t.compact(rm);
      ++out.compactions;
      for (auto& e : live) e.ref = rm.map(e.ref);
      for (auto& d : dead) d = rm.map(d);
    } else if (!live.empty()) {
      const Entry& e = live[rng.next() % live.size()];
      auto g = t.get(e.ref);
      if (g.size() != e.data.size()) { ++out.mismatches; continue; }
      for (std::size_t j = 0; j < g.size(); ++j) if (g[j] != e.data[j]) { ++out.mismatches; break; }
    }
    if ((i & 1023) == 0) {   // full audit
      std::size_t words = 0;
      for (const auto& e : live) {
        auto g = t.get(e.ref);
        if (g.size() != e.data.size()) { ++out.mismatches; continue; }
        for (std::size_t j = 0; j < g.size(); ++j) if (g[j] != e.data[j]) { ++out.mismatches; break; }
        words += g.size() + 1;
      }
      if (t.live_lists() != live.size() || t.bytes() != words * 4) ++out.mismatches;
      if (t.bytes() > SideTable::capacity_bytes()) ++out.mismatches;
    }
  }
  out.hash = t.layout_hash();
  out.truncs = t.truncated_lists();
  return out;
}
}  // namespace

TEST(million_operations_match_oracle) {
  const Outcome o = run(0x9E3779B97F4A7C15ull, 1000000);
  std::printf("  1 000 000 operations : %ld ecarts, %zu troncatures, %zu compactions, empreinte %016llx\n",
              o.mismatches, o.truncs, o.compactions, static_cast<unsigned long long>(o.hash));
  CHECK_EQ(o.mismatches, 0);
}

TEST(layout_identical_on_two_runs) {
  const Outcome a = run(12345, 200000);
  const Outcome b = run(12345, 200000);
  CHECK(a.hash == b.hash);
  CHECK_EQ(a.mismatches, 0);
}

TEST(stale_reference_detected) {
  SideTable t;
  const std::uint32_t d[3] = {1, 2, 3};
  const ListRef a = t.put(d);
  CHECK(t.valid(a));
  t.release(a);
  CHECK(!t.valid(a));
  CHECK(t.get(a).empty());
  const ListRef b = t.put(d);   // same offset, new generation
  CHECK(b != a);
  CHECK(!t.valid(a));
  CHECK(t.valid(b));
  CHECK(t.get(0).empty());
}

TEST(stale_after_compact_and_midblock_ref) {
  SideTable t;
  const std::uint32_t d[4] = {0x80000000u, 0x80010004u, 7, 8};   // items that look like headers
  const ListRef a = t.put(d);
  const ListRef b = t.put(d);
  t.release(a);
  Remap rm;
  t.compact(rm);
  CHECK(!t.valid(b));                 // old reference now pendante
  const ListRef nb = rm.map(b);
  CHECK(t.valid(nb));
  CHECK_EQ(t.get(nb).size(), 4u);
  CHECK_EQ(rm.map(a), 0u);
  CHECK(!t.valid((nb & 0xFF000000u) | ((nb & 0xFFFFFFu) + 1)));   // mid-block
}

TEST(budget_and_truncation) {
  SideTable t;
  std::vector<std::uint32_t> big(3000, 5);
  const ListRef r = t.put(big);
  CHECK_EQ(t.get(r).size(), SideTable::kWords - 1u);
  CHECK_EQ(t.truncated_lists(), 1u);
  CHECK_EQ(t.put(big), 0u);
  CHECK(t.bytes() <= SideTable::capacity_bytes());
}

TEST(no_aliasing_after_many_put_release) {
  for (int cycles : {255, 256, 257, 4096, 70000}) {
    SideTable t;
    const std::uint32_t a[3] = {1, 2, 3}, b[3] = {9, 8, 7};
    const ListRef old_ref = t.put(a);
    t.release(old_ref);
    for (int i = 0; i < cycles; ++i) {
      const ListRef r = t.put(b);
      CHECK(r != old_ref);
      t.release(r);
    }
    const ListRef live = t.put(b);   // lands on the same offset
    CHECK(!t.valid(old_ref));
    CHECK(t.get(old_ref).empty());
    CHECK(t.valid(live));
  }
}

TEST(generation_wraps_only_after_full_turn) {
  SideTable t;
  const std::uint32_t a[1] = {1}, b[1] = {2};
  const ListRef old_ref = t.put(a);
  t.release(old_ref);
  bool aliased_early = false;
  const std::uint32_t full = (1u << 20) - 1;   // creations at offset 0 per full turn
  for (std::uint32_t i = 1; i < full; ++i) {
    const ListRef r = t.put(b);
    if (t.valid(old_ref)) aliased_early = true;
    t.release(r);
  }
  CHECK(!aliased_early);
  // Creation number 2^20 at this offset (second turn) reuses the first generation: documented limit.
  const ListRef wrap = t.put(b);
  CHECK(wrap == old_ref);
}

EMERGENCE_TEST_MAIN()
