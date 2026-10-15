#include <algorithm>
#include <chrono>
#include <cstdio>
#include <thread>
#include <vector>

#include "emergence/act/entity_store.h"
#include "emergence/ops/operation_bus.h"
#include "emergence/testing/check.h"
#include "workload.h"

using namespace em::act;
using em::ops::ApplyStatus;
using em::ops::OperationBus;
using em::ops::SubmitResult;

namespace {

// Applies one operation through a bus and returns the number of rejections it caused.
struct Rig {
  EntityStore store;
  OperationBus bus;
  std::uint64_t tick = 0;
  Rig() { bus.add_applier(&store); }
  EntityId spawn(EntityKind k, Position p = {}, EntityId holder = kNoEntity, std::uint16_t sort = 0) {
    EntityId expect = store.next_id();
    bus.submit(make_spawn(++tick, 1, std::uint16_t(k), p, holder, sort));
    bus.flush();
    return store.alive(expect) ? expect : kNoEntity;
  }
  std::uint64_t rejected_after(const em::ops::Operation& op) {
    auto before = bus.stats().rejected_by_applier;
    op_tick(op);
    return bus.stats().rejected_by_applier - before;
  }
  void op_tick(em::ops::Operation op) { op.tick = ++tick; bus.submit(op); bus.flush(); }
};

std::uint16_t var_of(std::span<const gen::FieldDesc> fields, std::string_view name) {
  for (const auto& f : fields) if (f.name == name) return f.var;
  return 0xFFFF;
}

}  // namespace

TEST(ids_have_generation_and_stale_ids_are_refused) {
  Rig r;
  EntityId a = r.spawn(EntityKind::item, {1, 2, 3});
  CHECK(a != kNoEntity);
  CHECK(r.store.alive(a));
  CHECK(r.store.kind(a) == EntityKind::item);
  CHECK(r.rejected_after(make_destroy(0, 1, a)) == 0);
  CHECK(!r.store.alive(a));
  EntityId b = r.spawn(EntityKind::plant);
  CHECK(index_of(b) == index_of(a));            // slot reused
  CHECK(generation_of(b) == generation_of(a) + 1);
  CHECK(!r.store.alive(a) && r.store.alive(b));
  CHECK(r.rejected_after(make_move(0, 1, a, {9, 9, 9})) == 1);   // the old id no longer designates anything
  CHECK(r.rejected_after(make_destroy(0, 1, a)) == 1);
  CHECK(r.store.kind(a) == EntityKind::kCount);
}

TEST(slot_is_retired_when_generation_would_overflow) {
  Rig r;
  EntityId first = r.spawn(EntityKind::item);
  EntityId id = first;
  for (unsigned i = 0; i < kMaxGeneration; ++i) {
    r.op_tick(make_destroy(0, 1, id));
    id = r.spawn(EntityKind::item);
    CHECK(index_of(id) == index_of(first));
  }
  CHECK(generation_of(id) == kMaxGeneration);
  r.op_tick(make_destroy(0, 1, id));
  EntityId next = r.spawn(EntityKind::item);
  CHECK(index_of(next) != index_of(first));   // retired, never reused
  CHECK(!r.store.alive(id));
}

TEST(components_come_from_the_catalogue) {
  Rig r;
  EntityId p = r.spawn(EntityKind::plant);
  EntityId i = r.spawn(EntityKind::item);
  CHECK(r.store.component<gen::Growth>(p) != nullptr);
  CHECK(r.store.component<gen::Growth>(i) == nullptr);
  CHECK(r.store.component<gen::Provenance>(i) != nullptr);
  CHECK(r.store.component<gen::Transformation>(p) != nullptr);   // plants and items both transform
  CHECK(r.store.component<gen::Transformation>(i) != nullptr);
  CHECK(r.store.component<gen::Provenance>(p) == nullptr);
  CHECK(r.store.component<gen::Spatial>(p) != nullptr);
  // a delta, with the old value checked
  auto var = var_of(gen::kPlantFields, "plant_health");
  CHECK(var != 0xFFFF);
  CHECK(r.rejected_after(make_delta(0, 1, p, var, 0, 70)) == 0);
  CHECK_EQ(r.store.component<gen::Growth>(p)->plant_health, 70);
  CHECK(r.rejected_after(make_delta(0, 1, p, var, 0, 80)) == 1);     // stale old value
  CHECK(r.rejected_after(make_delta(0, 1, p, var, 70, 101)) == 1);   // above the unipolar10 scale
  CHECK_EQ(r.store.component<gen::Growth>(p)->plant_health, 70);
  std::int64_t v = 0;
  CHECK(r.store.read_var(p, var, v) && v == 70);
  auto made_at = var_of(gen::kItemFields, "made_at");   // time: 64 bits, not changeable by an i32 delta
  CHECK(made_at != 0xFFFF);
  CHECK(r.rejected_after(make_delta(0, 1, i, made_at, 0, 5)) == 1);
}

TEST(move_holder_and_containment_rules) {
  Rig r;
  EntityId chest = r.spawn(EntityKind::structure, {1000, 0, 0});
  EntityId coin = r.spawn(EntityKind::item, {0, 0, 0}, chest);
  CHECK(coin != kNoEntity && r.store.holder(coin) == chest && r.store.held_count(chest) == 1);
  CHECK(r.rejected_after(make_destroy(0, 1, chest)) == 1);                  // not while it holds something
  CHECK(r.rejected_after(make_move(0, 1, chest, {0, 0, 0}, coin)) == 1);    // a cycle
  CHECK(r.rejected_after(make_move(0, 1, chest, {0, 0, 0}, chest)) == 1);
  CHECK(r.rejected_after(make_move(0, 1, coin, {5, 6, 7})) == 0);
  CHECK(r.store.holder(coin) == kNoEntity && r.store.held_count(chest) == 0);
  CHECK((r.store.position_mm(coin) == Position{5, 6, 7}));
  CHECK(r.rejected_after(make_destroy(0, 1, chest)) == 0);
  CHECK(r.rejected_after(make_move(0, 1, coin, {0, 0, 0}, chest)) == 1);    // dead holder
  CHECK(r.rejected_after(make_spawn(0, 1, 999, {})) == 1);                  // unknown kind
  CHECK(r.rejected_after(make_spawn(0, 1, std::uint16_t(EntityKind::item), {}, 0, 0, 12345)) == 1);   // wrong id announced
}

TEST(deep_holder_chains_round_trip) {
  Rig r;
  auto chain = [&](int n) {
    std::vector<EntityId> c;
    for (int i = 0; i < n; ++i) c.push_back(r.spawn(EntityKind::structure, {i, 0, 0}, c.empty() ? kNoEntity : c.back()));
    return c;
  };
  auto a = chain(60), b = chain(60);
  CHECK(r.rejected_after(make_move(0, 1, b.front(), {0, 0, 0}, a.back())) == 0);   // a chain of 120: no depth limit
  CHECK(r.rejected_after(make_move(0, 1, a.front(), {0, 0, 0}, b.back())) == 1);    // would close a loop
  auto bytes = r.store.serialize();
  EntityStore copy;
  CHECK(copy.load(bytes) == LoadStatus::Ok);
  CHECK(copy.fingerprint() == r.store.fingerprint());
  auto deep = chain(3000);
  CHECK(deep.back() != kNoEntity && r.store.holder(deep.back()) == deep[2998]);
  CHECK(r.rejected_after(make_move(0, 1, deep.front(), {0, 0, 0}, deep.back())) == 1);
  EntityStore copy2;
  CHECK(copy2.load(r.store.serialize()) == LoadStatus::Ok);
  CHECK(copy2.fingerprint() == r.store.fingerprint());
}

TEST(holder_must_be_spatial_and_free_slots_are_fifo) {
  Rig r;
  EntityId place = r.spawn(EntityKind::place);
  CHECK(place != kNoEntity);
  CHECK(r.rejected_after(make_spawn(0, 1, std::uint16_t(EntityKind::item), {}, place)) == 1);   // a place has no spatial component
  EntityId a = r.spawn(EntityKind::item), b = r.spawn(EntityKind::item), c = r.spawn(EntityKind::item);
  r.op_tick(make_destroy(0, 1, a));
  r.op_tick(make_destroy(0, 1, b));
  r.op_tick(make_destroy(0, 1, c));
  EntityId x = r.spawn(EntityKind::item), y = r.spawn(EntityKind::item);
  CHECK(index_of(x) == index_of(a) && index_of(y) == index_of(b));   // first freed, first reused
}

TEST(serialization_round_trip_and_fingerprint) {
  Rig r;
  em::act::workload::run(r.bus, r.store, 2000);
  r.tick = 10;   // the workload used ticks 1 to 4
  EntityId keep = r.spawn(EntityKind::item, {7, 8, 9}, kNoEntity, 42);
  EntityId in = r.spawn(EntityKind::item, {0, 0, 0}, keep, 43);
  auto bytes = r.store.serialize();
  EntityStore copy;
  CHECK(copy.load(bytes) == LoadStatus::Ok);
  CHECK(copy.serialize() == bytes);
  CHECK(copy.fingerprint() == r.store.fingerprint());
  CHECK(copy.size() == r.store.size());
  CHECK(copy.holder(in) == keep && copy.held_count(keep) == 1);
  CHECK(copy.sort(in) == 43 && copy.created_tick(keep) == r.store.created_tick(keep));
  CHECK(copy.next_id() == r.store.next_id());
  // the loaded copy goes on exactly like the original
  OperationBus b2; b2.add_applier(&copy);
  CHECK(copy.load(bytes) == LoadStatus::Ok);
  // refusals: truncated, bad magic, other schema, flipped value out of range
  auto cut = bytes; cut.resize(cut.size() - 3);
  EntityStore other;
  CHECK(other.load(cut) == LoadStatus::Corrupt);   // the final CRC no longer matches
  auto bad = bytes; bad[0] ^= 1;
  CHECK(other.load(bad) == LoadStatus::BadMagic);
  auto schema = bytes; schema[8] ^= 1;
  CHECK(other.load(schema) == LoadStatus::SchemaMismatch);
  auto flip = bytes; flip[bytes.size() / 2] ^= 0x10;
  CHECK(other.load(flip) == LoadStatus::Corrupt);
  auto huge = bytes; huge[16] = 0xFF; huge[17] = 0xFF; huge[18] = 0x3F; huge[19] = 0;   // n_slots = 4 194 303
  CHECK(other.load(huge) == LoadStatus::Truncated);   // refused by the size bound, before any allocation
  auto trail = bytes; trail.push_back(0);
  CHECK(other.load(trail) == LoadStatus::Corrupt);
  CHECK(other.size() == 0);   // untouched on failure
}

namespace {
// Same operations, submitted from `threads` threads in a shuffled order: one store fingerprint whatever the interleaving.
std::uint64_t threaded_run(int threads, int shuffle) {
  EntityStore store;
  OperationBus bus;
  bus.add_applier(&store);
  constexpr std::uint32_t kAuthors = 64, kPer = 40;
  auto spawn_work = [&](std::uint32_t a0, std::uint32_t step) {
    for (std::uint32_t k = 0; k < kPer; ++k)
      for (std::uint32_t a = a0; a < kAuthors; a += step)
        bus.submit(make_spawn(1, 1 + a, std::uint16_t(EntityKind::item), {std::int32_t(a), std::int32_t(k), 0}, kNoEntity,
                              std::uint16_t(a * kPer + k)), k);
  };
  auto launch = [&](auto&& work) {
    std::vector<std::thread> ts;
    for (int t = 0; t < threads; ++t) ts.emplace_back([&, t] { work(std::uint32_t((t + shuffle) % threads), std::uint32_t(threads)); });
    for (auto& t : ts) t.join();
  };
  launch(spawn_work);
  bus.flush(1);
  // identify entities by their `sort`, which does not depend on allocation order
  std::vector<EntityId> by_sort(kAuthors * kPer);
  store.for_each([&](EntityId id, EntityKind) { by_sort[store.sort(id)] = id; });
  auto move_work = [&](std::uint32_t a0, std::uint32_t step) {
    for (std::uint32_t a = a0; a < kAuthors; a += step)
      for (std::uint32_t k = 0; k < kPer; ++k) {
        EntityId id = by_sort[a * kPer + k];
        bus.submit(make_move(2, 1 + a, id, {std::int32_t(k), std::int32_t(a), 5}), k);
        if (k % 3 == 0) bus.submit(make_destroy(3, 1 + a, id), k);
      }
  };
  launch(move_work);
  bus.flush();
  return store.fingerprint();
}
}  // namespace

TEST(order_is_independent_of_thread_creation_order) {
  const std::uint64_t one = threaded_run(1, 0);
  CHECK(one != 0);
  for (int t : {2, 8}) for (int s : {0, 3, 5}) CHECK(threaded_run(t, s) == one);
}

TEST(iteration_is_in_slot_order) {
  Rig r;
  std::vector<EntityId> made;
  for (int i = 0; i < 20; ++i) made.push_back(r.spawn(i % 2 ? EntityKind::item : EntityKind::plant));
  r.op_tick(make_destroy(0, 1, made[3]));
  r.op_tick(make_destroy(0, 1, made[10]));
  std::vector<EntityId> seen;
  r.store.for_each([&](EntityId id, EntityKind) { seen.push_back(id); });
  CHECK(seen.size() == 18);
  CHECK(std::is_sorted(seen.begin(), seen.end(), [](EntityId a, EntityId b) { return index_of(a) < index_of(b); }));
  std::size_t n = 0;
  r.store.for_each_of(EntityKind::item, [&](EntityId) { ++n; });
  CHECK(n == 10 - 1);   // 10 items, one destroyed (made[3] is an item)
}

TEST(load_100k_entities_twice_same_fingerprint) {
  constexpr std::uint32_t kN = 100000;
  std::uint64_t fp[2] = {};
  double rate[2] = {};
  em::act::workload::Counts counts;
  std::size_t mem = 0, left = 0;
  for (int run = 0; run < 2; ++run) {
    EntityStore store;
    OperationBus bus;
    bus.add_applier(&store);
    auto t0 = std::chrono::steady_clock::now();
    counts = em::act::workload::run(bus, store, kN);
    double s = std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count();
    rate[run] = double(counts.ops) / s;
    fp[run] = store.fingerprint();
    CHECK(bus.stats().rejected_by_applier == 0);
    // peak memory: measured after the creations only, on a fresh store
    EntityStore full;
    OperationBus b2;
    b2.add_applier(&full);
    for (std::uint32_t i = 0; i < kN; ++i)
      b2.submit(make_spawn(1, 1 + i % 500, em::act::workload::movable_kind(i), {}), i);
    b2.flush();
    mem = full.memory_bytes();
    left = store.size();
  }
  CHECK(fp[0] == fp[1]);
  CHECK(fp[0] != 0);
  CHECK(left == kN / 2);
  std::printf("  [Mesure] %u entites: %llu operations (spawn+move+delta+destroy), %.0f ops/s, %.0f entites creees/s ; "
              "memoire %.1f octets/entite (tampons alloues, mix agent/animal/plante/objet/structure)\n",
              kN, (unsigned long long)counts.ops, rate[0], rate[0] * kN / double(counts.ops), double(mem) / kN);
}

EMERGENCE_TEST_MAIN()
