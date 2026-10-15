#include <algorithm>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <thread>

#include "emergence/social/vocab_gen.h"
#include "emergence/testing/check.h"
#include "matter_rig.h"

using namespace em::act;
using em::act::rig::World;
using gen::EntityKind;

namespace {

struct Run {
  LawReport rep;
  std::vector<Emission> out;
};

// Plays one contact: the engine reads, the bus applies.
Run play(World& w, ProcessEngine& eng, const Contact& c) {
  Run r;
  TouchedSet t;
  if (std::getenv("MATTER_TRACE")) { Resolved q = eng.resolver().resolve(c); std::printf("  [trace] tool %d cuts %d target %d hard %d mass %d tool=%u target=%u\n", q.tool.valid(), q.tool.aff.cuts, q.target.valid(), q.target.hardness, q.target.mass_g, c.tool, c.target); }
  r.rep = eng.on_contact(c, w.tick + 1, t, r.out);
  if (std::getenv("MATTER_TRACE")) std::printf("  [trace] process %d outcome %s ops %zu\n", int(r.rep.process), to_string(r.rep.outcome), r.out.size());
  w.submit_flush(r.out);
  return r;
}

Contact strike(EntityId tool, EntityId target, std::int32_t speed, bool joint = false) {
  Contact c;
  c.author = 7; c.tool = tool; c.target = target; c.manner = Manner::Strike; c.speed_mm_s = speed; c.at_joint = joint;
  return c;
}

Profile structure_profile(std::int32_t mass_g, Extent size, std::vector<Part> parts) {
  Profile p;
  p.mass_g = mass_g; p.size = size; p.parts = std::move(parts);
  return p;
}

std::uint16_t mat(const MatterCatalog& c, const char* n) { return c.find_material(n); }

}  // namespace

TEST(the_table_matches_the_catalogue_and_every_law_has_its_process) {
  using P = ProcessId;
  CHECK(matter::kProcesses.size() == static_cast<std::size_t>(P::kCount));
  World w;
  ProcessEngine eng(w.catalog, w.store, w.ground);
  auto have = eng.contact_processes();
  for (P p : {P::Cut, P::Split, P::Fracture, P::Crush, P::Extract, P::Till, P::Assemble, P::Bind, P::Carve, P::Disassemble, P::Abrade}) {
    CHECK(std::find(have.begin(), have.end(), p) != have.end());
    CHECK(MatterCatalog::process(p).live);
  }
  CHECK(MatterCatalog::process(P::Collapse).clock == matter::Clock::real);   // matter.toml: collapse runs on the real clock
  CHECK(MatterCatalog::process(P::Cut).clock == matter::Clock::game);
  CHECK(w.item("beam") != 0 && w.item("door") != 0 && w.item("plank") != 0);
  CHECK(w.catalog.find_material("oak_planks") != kNoMatter);
  CHECK(MatterCatalog::material(mat(w.catalog, "oak_planks")).cohesion == Cohesion::built);
  CHECK(MatterCatalog::material(mat(w.catalog, "oak_raw")).cohesion == Cohesion::natural);
  CHECK(kTaskCompression == 16);
}

TEST(resolver_reads_properties_not_names) {
  World w;
  ProcessEngine eng(w.catalog, w.store, w.ground);
  EntityId axe = w.spawn_item("felling_axe", {0, 0, 0});
  EntityId knife = w.spawn_item("knife", {1000, 0, 0});
  EntityId loaf = w.spawn_item("bread", {2000, 0, 0});
  Contact c = strike(axe, knife, 5000);
  Resolved r = eng.resolver().resolve(c);
  CHECK(r.tool.aff.cuts && r.tool.aff.impacts && !r.tool.aff.digs);   // edge + mass; iron does not dig iron
  CHECK(r.energy_mj == 2500ll * 5000 * 5000 / 2000000);
  CHECK(r.target.aff.cuts && !r.target.aff.impacts);                // a knife is light
  CHECK(eng.resolver().resolve(strike(axe, loaf, 100)).tool.aff.digs);   // harder than bread
  Resolved r2 = eng.resolver().resolve(strike(loaf, axe, 1000));
  CHECK(!r2.tool.aff.cuts && !r2.tool.aff.digs);
  // An object nobody has seen: a profile registered with a blade form acts as a cutter.
  Profile odd;
  odd.mass_g = 600; odd.parts = {{rig::form_of("blade"), mat(w.catalog, "glass")}, {rig::form_of("grip"), mat(w.catalog, "oak_raw")}};
  w.catalog.set_profile(EntityKind::item, 5000, odd);
  EntityId shard = w.spawn(EntityKind::item, {3000, 0, 0}, 5000);
  CHECK(eng.resolver().resolve(strike(shard, loaf, 1000)).tool.aff.cuts);
}

TEST(touching_finds_what_rests_on_what_in_a_stable_order) {
  World w;
  w.catalog.set_profile(EntityKind::structure, 1, structure_profile(200000, {400, 1000, 400}, {{rig::form_of("block"), mat(w.catalog, "cut_stone")}}));
  ProcessEngine eng(w.catalog, w.store, w.ground);
  EntityId pillar = w.spawn(EntityKind::structure, {0, 0, 0}, 1);
  EntityId stone = w.spawn_item("stone_loose", {50, 1000, 0});
  EntityId far = w.spawn_item("stone_loose", {5000, 0, 0});
  auto pairs = eng.resolver().touching();
  CHECK(pairs.size() == 1 && pairs[0].upper == stone && pairs[0].lower == pillar);
  SupportMap m = eng.resolver().support_map();
  CHECK(m.on_ground[m.index_of(pillar)] && m.on_ground[m.index_of(far)] && !m.on_ground[m.index_of(stone)]);
  CHECK(m.load_above_g[m.index_of(pillar)] == w.catalog.profile(EntityKind::item, w.item("stone_loose"))->mass_g);
}

TEST(cut_a_beam_drops_what_it_carried) {
  World w;
  w.catalog.set_profile(EntityKind::structure, 1, structure_profile(300000, {400, 1000, 400}, {{rig::form_of("block"), mat(w.catalog, "cut_stone")}}));
  Profile beam = *w.catalog.profile(EntityKind::item, w.item("beam"));
  beam.size = {2600, 300, 300};
  w.catalog.set_profile(EntityKind::item, w.item("beam"), beam);
  ProcessEngine eng(w.catalog, w.store, w.ground);
  w.spawn(EntityKind::structure, {0, 0, 0}, 1);
  w.spawn(EntityKind::structure, {2000, 0, 0}, 1);
  EntityId b = w.spawn_item("beam", {1000, 1000, 0});
  EntityId crate = w.spawn_item("stone_loose", {1000, 1300, 0});
  EntityId knife = w.spawn_item("knife", {900, 0, 500});
  // Standing: nothing moves.
  std::vector<Emission> idle;
  eng.tick_time(w.tick + 1, idle);
  for (const auto& e : idle) CHECK(e.op.kind != static_cast<std::uint16_t>(em::ops::OpKind::Move));
  w.submit_flush(idle);
  CHECK(w.store.position_mm(crate)[1] == 1300);
  Contact c; c.author = 7; c.tool = knife; c.target = b; c.manner = Manner::Slice;
  // A knife against a 40 kg oak beam: soft enough, the edge is harder.
  Run r = play(w, eng, c);
  CHECK(r.rep.process == ProcessId::Cut && r.rep.outcome == Outcome::Done);
  CHECK(!w.store.alive(b));
  CHECK(w.count_sort(w.item("branch")) >= 2);
  // The clock of the world lets the carried thing fall, in a few steps at most.
  for (int i = 0; i < 4; ++i) {
    std::vector<Emission> e;
    eng.tick_time(w.tick + 1, e);
    w.submit_flush(e);
  }
  CHECK(w.store.alive(crate) && w.store.position_mm(crate)[1] == 0);
  // Pieces resting on a post stayed there, those over nothing reached the ground.
  bool any_on_post = false, any_on_ground = false;
  w.store.for_each([&](EntityId id, EntityKind) {
    if (w.store.sort(id) != w.item("branch")) return;
    std::int32_t y = w.store.position_mm(id)[1];
    any_on_post |= y == 1000; any_on_ground |= y == 0;
  });
  CHECK(any_on_post && any_on_ground);
}

TEST(cut_a_standing_tree_gives_logs) {
  World w;
  Profile tree;
  tree.mass_g = 600000; tree.size = {600, 9000, 600}; tree.parts = {{rig::form_of("lump"), mat(w.catalog, "oak_raw")}};
  w.catalog.set_profile(EntityKind::plant, 1, tree);
  ProcessEngine eng(w.catalog, w.store, w.ground);
  EntityId t = w.spawn(EntityKind::plant, {0, 0, 0}, 1);
  EntityId axe = w.spawn_item("felling_axe", {500, 0, 0});
  Contact c; c.author = 3; c.tool = axe; c.target = t; c.manner = Manner::Slice;
  Run r = play(w, eng, c);
  CHECK(r.rep.process == ProcessId::Cut && r.rep.outcome == Outcome::Done);
  CHECK(!w.store.alive(t) && w.count_sort(w.item("log")) >= 2);    // the heaviest lighter piece made by cut
}

TEST(split_a_log_gives_planks) {
  World w;
  ProcessEngine eng(w.catalog, w.store, w.ground);
  EntityId log = w.spawn_item("log", {0, 0, 0});
  EntityId axe = w.spawn_item("battle_axe", {900, 0, 0});
  Run weak = play(w, eng, strike(axe, log, 800));              // too slow
  CHECK(weak.rep.outcome == Outcome::NoEffect && w.store.alive(log));
  Run r = play(w, eng, strike(axe, log, 6000));
  CHECK(r.rep.process == ProcessId::Split && r.rep.outcome == Outcome::Done);
  CHECK(!w.store.alive(log) && w.count_sort(w.item("plank")) == 6);
}

TEST(fracture_breaks_above_toughness_and_damages_below) {
  World w;
  w.catalog.set_profile(EntityKind::structure, 2, structure_profile(2000000, {2000, 2500, 300}, {{rig::form_of("block"), mat(w.catalog, "granite")}}));
  ProcessEngine eng(w.catalog, w.store, w.ground);
  EntityId block = w.spawn_item("stone_block", {0, 0, 0});
  EntityId mace = w.spawn_item("sledgehammer", {900, 0, 0});
  Run r = play(w, eng, strike(mace, block, 9000));
  CHECK(r.rep.process == ProcessId::Fracture && r.rep.outcome == Outcome::Done);
  CHECK(!w.store.alive(block) && w.count_sort(w.item("rubble")) >= 1);
  EntityId wall = w.spawn(EntityKind::structure, {5000, 0, 0}, 2);
  Run soft = play(w, eng, strike(mace, wall, 9000));
  CHECK(soft.rep.process == ProcessId::Fracture && soft.rep.outcome == Outcome::Progress);
  CHECK(w.store.alive(wall) && w.store.component<gen::Stability>(wall)->visible_damage > 0);
}

TEST(crush_grain_gives_flour) {
  World w;
  ProcessEngine eng(w.catalog, w.store, w.ground);
  EntityId grain = w.spawn_item("wheat_sack", {0, 0, 0});
  EntityId mace = w.spawn_item("sledgehammer", {900, 0, 0});
  Run r = play(w, eng, strike(mace, grain, 5000));
  CHECK(r.rep.process == ProcessId::Crush && r.rep.outcome == Outcome::Done);
  CHECK(!w.store.alive(grain) && w.count_sort(w.item("flour_sack")) >= 1);
}

TEST(disassemble_a_door_gives_elements_but_natural_matter_only_fractures) {
  World w;
  ProcessEngine eng(w.catalog, w.store, w.ground);
  EntityId door = w.spawn_item("door", {0, 0, 0});
  EntityId mace = w.spawn_item("mace", {900, 0, 0});
  EntityId sledge0 = w.spawn_item("sledgehammer", {1500, 0, 0});
  Run r = play(w, eng, strike(sledge0, door, 6000, true));
  CHECK(r.rep.process == ProcessId::Disassemble && r.rep.outcome == Outcome::Done);
  CHECK(!w.store.alive(door) && w.count_sort(w.item("plank")) >= 1);
  // Aimed at the joints of a log (natural, one part): no disassembly.
  EntityId log = w.spawn_item("log", {3000, 0, 0});
  Run n = play(w, eng, strike(mace, log, 6000, true));
  CHECK(n.rep.process != ProcessId::Disassemble);
  // A wall of bricks: eight bricks come back.
  w.catalog.set_profile(EntityKind::structure, 3, structure_profile(2000000, {2000, 2000, 300},
      std::vector<Part>(8, Part{rig::form_of("block"), mat(w.catalog, "brick")})));
  EntityId wall = w.spawn(EntityKind::structure, {8000, 0, 0}, 3);
  EntityId sledge = w.spawn_item("sledgehammer", {7000, 0, 0});
  Run d = play(w, eng, strike(sledge, wall, 9000, true));
  CHECK(d.rep.process == ProcessId::Disassemble && d.rep.outcome == Outcome::Done);
  CHECK(!w.store.alive(wall) && w.count_sort(w.item("brick")) == 8);
}

TEST(extract_and_till_go_to_the_voxel_world_or_uproot_a_plant) {
  World w;
  Profile bush;
  bush.mass_g = 20000; bush.parts = {{rig::form_of("lump"), mat(w.catalog, "oak_raw")}};
  w.catalog.set_profile(EntityKind::plant, 1, bush);
  ProcessEngine eng(w.catalog, w.store, w.ground);
  EntityId pick = w.spawn_item("pickaxe", {0, 0, 0});
  EntityId hoe = w.spawn_item("hoe", {500, 0, 0});
  Contact dig; dig.author = 2; dig.tool = pick; dig.manner = Manner::Dig; dig.at = {100, -500, 100}; dig.voxel_material = mat(w.catalog, "dirt");
  Run e = play(w, eng, dig);
  CHECK(e.rep.process == ProcessId::Extract && e.rep.outcome == Outcome::DelegatedToVoxels && e.rep.voxel.valid && e.out.empty());
  Contact turn; turn.author = 2; turn.tool = hoe; turn.manner = Manner::Turn; turn.at = {0, -200, 0}; turn.voxel_material = mat(w.catalog, "dirt");
  Run t = play(w, eng, turn);
  CHECK(t.rep.process == ProcessId::Till && t.rep.outcome == Outcome::DelegatedToVoxels && t.out.empty());
  turn.voxel_material = mat(w.catalog, "granite");     // rock is not tilled
  CHECK(play(w, eng, turn).rep.outcome == Outcome::NoEffect);
  EntityId b = w.spawn(EntityKind::plant, {3000, 0, 0}, 1);
  Contact up; up.author = 2; up.tool = pick; up.target = b; up.manner = Manner::Dig;
  Run u = play(w, eng, up);
  CHECK(u.rep.process == ProcessId::Extract && u.rep.outcome == Outcome::Done && !w.store.alive(b));
}

TEST(assemble_stacks_and_bind_carries) {
  World w;
  ProcessEngine eng(w.catalog, w.store, w.ground);
  EntityId b1 = w.spawn_item("brick", {0, 0, 0});
  EntityId b2 = w.spawn_item("brick", {3000, 0, 0});
  Contact a; a.author = 4; a.target = b1; a.other = b2; a.manner = Manner::Join;
  Run r = play(w, eng, a);
  const Body base = eng.resolver().body(b1);
  CHECK(r.rep.process == ProcessId::Assemble && r.rep.outcome == Outcome::Done);
  CHECK(w.store.position_mm(b2) == (Position{0, base.top(), 0}));
  CHECK(eng.resolver().touching().size() == 1);
  CHECK(play(w, eng, a).rep.outcome == Outcome::NoEffect);          // already there
  // Bind: a rope lashes a plank to a post; it is carried by it. A rope too weak snaps.
  EntityId rope = w.spawn_item("rope", {6000, 0, 0});
  EntityId plank = w.spawn_item("plank", {6500, 0, 0});
  EntityId post = w.spawn_item("post", {7000, 0, 0});
  Contact l; l.author = 4; l.tool = rope; l.target = post; l.other = plank; l.manner = Manner::Lash;
  Run lr = play(w, eng, l);
  CHECK(lr.rep.process == ProcessId::Bind && lr.rep.outcome == Outcome::Done);
  CHECK(w.store.holder(plank) == post && !w.store.alive(rope));
  EntityId thread = w.spawn_item("needle_thread", {9000, 0, 0});
  EntityId anchor = w.spawn_item("anchor", {9500, 0, 0});
  Contact l2; l2.author = 4; l2.tool = thread; l2.target = post; l2.other = anchor; l2.manner = Manner::Lash;
  Run snap = play(w, eng, l2);
  CHECK(snap.rep.outcome == Outcome::Snapped && w.store.holder(anchor) == kNoEntity && !w.store.alive(thread));
}

TEST(carve_and_abrade_accumulate_work_and_compression_is_sixteen) {
  World w;
  ProcessEngine eng(w.catalog, w.store, w.ground);
  EntityId log = w.spawn_item("log", {0, 0, 0});
  EntityId knife = w.spawn_item("knife", {500, 0, 0});
  Contact c; c.author = 5; c.tool = knife; c.target = log; c.manner = Manner::Carve;
  Run r = play(w, eng, c);
  CHECK(r.rep.process == ProcessId::Carve && r.rep.outcome == Outcome::Progress);
  std::int32_t slow = w.store.component<gen::Transformation>(log)->process_progress;
  CHECK(slow == 25);
  EntityId log2 = w.spawn_item("log", {2000, 0, 0});
  c.target = log2; c.productive = true;
  play(w, eng, c);
  CHECK(w.store.component<gen::Transformation>(log2)->process_progress == 25 * kTaskCompression);
  // To the end: the progress restarts and the work is reported as done.
  Outcome last = Outcome::NoEffect;
  for (int i = 0; i < 2; ++i) last = play(w, eng, c).rep.outcome;
  CHECK(last == Outcome::Done && w.store.component<gen::Transformation>(log2)->process_progress == 0);
  // Abrade: a whetstone on a blade.
  EntityId stone = w.spawn_item("whetstone", {4000, 0, 0});
  EntityId hatchet = w.spawn_item("hatchet", {4500, 0, 0});
  Contact ab; ab.author = 5; ab.tool = stone; ab.target = hatchet; ab.manner = Manner::Rub;
  Run a = play(w, eng, ab);
  CHECK(a.rep.process == ProcessId::Abrade && a.rep.outcome == Outcome::Progress);
  CHECK(w.store.component<gen::Transformation>(hatchet)->process_progress > 0);
}

TEST(collapse_when_the_margin_reaches_zero) {
  World w;
  w.catalog.set_profile(EntityKind::structure, 1, structure_profile(800000, {400, 400, 400}, {{rig::form_of("frame"), mat(w.catalog, "oak_planks")}}));
  w.catalog.set_profile(EntityKind::item, 6000, structure_profile(5000000, {380, 380, 380}, {{rig::form_of("lump"), mat(w.catalog, "granite")}}));
  ProcessEngine eng(w.catalog, w.store, w.ground);
  EntityId shed = w.spawn(EntityKind::structure, {0, 0, 0}, 1);
  EntityId sound = w.spawn(EntityKind::structure, {5000, 0, 0}, 1);
  EntityId rock = w.spawn(EntityKind::item, {0, 400, 0}, 6000);
  EntityId small = w.spawn_item("stone_loose", {5000, 400, 0});
  std::vector<Emission> e;
  TickReport rep = eng.tick_time(w.tick + 1, e);
  w.submit_flush(e);
  CHECK(rep.collapsed == 1 && rep.margins_written == 1);
  CHECK(!w.store.alive(shed) && w.store.alive(sound));
  std::int32_t m = w.store.component<gen::Stability>(sound)->load_margin;     // stored margin follows the load
  CHECK(m > 0 && m < 1000);
  CHECK(w.count_sort(w.item("rubble")) >= 1);
  CHECK(w.store.position_mm(rock)[1] == 400);         // still in the air for this step...
  e.clear();
  TickReport rep2 = eng.tick_time(w.tick + 1, e);
  w.submit_flush(e);
  CHECK(rep2.fell >= 1 && rep2.shattered >= 1);       // ...then it falls and, 5 t on its own break energy, shatters or lands
  CHECK(!w.store.alive(rock) || w.store.position_mm(rock)[1] == 0);
  CHECK(w.store.position_mm(small)[1] == 400);        // the light load on the sound structure stays
}

TEST(two_contacts_on_the_same_thing_the_first_in_order_wins) {
  World w;
  ProcessEngine eng(w.catalog, w.store, w.ground);
  EntityId log = w.spawn_item("log", {0, 0, 0});
  EntityId axe = w.spawn_item("battle_axe", {900, 0, 0});
  Contact late = strike(axe, log, 6000); late.author = 20; late.decision_seq = 1;
  Contact early = strike(axe, log, 6000); early.author = 10; early.decision_seq = 9;
  std::vector<Contact> cs{late, early};
  std::vector<Emission> out;
  auto reps = eng.on_contacts(cs, w.tick + 1, out);
  CHECK((reps[0].outcome == Outcome::Done) != (reps[1].outcome == Outcome::Done));
  CHECK(reps[0].outcome == Outcome::Conflict || reps[1].outcome == Outcome::Conflict);
  w.submit_flush(out);
  CHECK(w.count_sort(w.item("plank")) == 6);          // not 12
}

namespace {
// 64 independent jobs: 32 logs split, 32 doors disassembled.
struct Job {
  World w;
  std::vector<Contact> contacts;
  std::unique_ptr<ProcessEngine> eng;
  Job() {
    EntityId axe = w.spawn_item("battle_axe", {-2000, 0, 0});
    EntityId mace = w.spawn_item("sledgehammer", {-3000, 0, 0});
    for (int i = 0; i < 64; ++i) {
      bool log = i % 2 == 0;
      EntityId t = w.spawn_item(log ? "log" : "door", {i * 3000, 0, 0});
      Contact c = strike(log ? axe : mace, t, 6000, !log);
      c.author = 100 + static_cast<std::uint32_t>(i); c.decision_seq = static_cast<std::uint32_t>(i);
      contacts.push_back(c);
    }
    eng = std::make_unique<ProcessEngine>(w.catalog, w.store, w.ground);
  }
};
}  // namespace

TEST(determinism_by_fingerprint_independent_of_order_and_threads) {
  std::uint64_t ref_emit = 0, ref_world = 0;
  {
    Job j;
    std::vector<Emission> out;
    auto reps = j.eng->on_contacts(j.contacts, j.w.tick + 1, out);
    for (const auto& r : reps) CHECK(r.outcome == Outcome::Done);
    ref_emit = fingerprint(out);
    j.w.submit_flush(out);
    ref_world = j.w.store.fingerprint();
    CHECK(ref_emit != 0 && ref_world != 0);
  }
  // The contacts arrive in any order (as collected by threads): same emissions, same world.
  for (std::uint32_t seed : {1u, 2u, 3u}) {
    Job j;
    std::uint32_t s = seed * 2654435761u;
    for (std::size_t i = j.contacts.size(); i > 1; --i) { s = s * 1664525u + 1013904223u; std::swap(j.contacts[i - 1], j.contacts[(s >> 8) % i]); }
    std::vector<Emission> out;
    j.eng->on_contacts(j.contacts, j.w.tick + 1, out);
    CHECK(fingerprint(out) == ref_emit);
    j.w.submit_flush(out);
    CHECK(j.w.store.fingerprint() == ref_world);
  }
  // Threads each play their own slice and submit to the bus concurrently.
  for (unsigned threads : {1u, 2u, 4u, 8u}) {
    Job j;
    std::uint64_t tick = j.w.tick + 1;
    std::vector<std::thread> pool;
    for (unsigned t = 0; t < threads; ++t)
      pool.emplace_back([&, t] {
        for (std::size_t i = t; i < j.contacts.size(); i += threads) {
          std::vector<Emission> out;
          TouchedSet touched;
          j.eng->on_contact(j.contacts[i], tick, touched, out);
          ProcessEngine::submit_all(j.w.bus, out);
        }
      });
    for (auto& th : pool) th.join();
    j.w.bus.flush();
    CHECK(j.w.store.fingerprint() == ref_world);
  }
}

TEST(rates_in_processes_per_second) {
  World w;
  ProcessEngine eng(w.catalog, w.store, w.ground);
  EntityId axe = w.spawn_item("battle_axe", {-2000, 0, 0});
  constexpr int kN = 20000;
  std::vector<Contact> cs;
  for (int i = 0; i < kN; ++i) {
    EntityId t = w.spawn_item("log", {(i % 200) * 3000, 0, (i / 200) * 3000});
    Contact c = strike(axe, t, 6000);
    c.author = 1000 + static_cast<std::uint32_t>(i);
    cs.push_back(c);
  }
  auto t0 = std::chrono::steady_clock::now();
  std::vector<Emission> out;
  eng.on_contacts(cs, w.tick + 1, out);
  auto t1 = std::chrono::steady_clock::now();
  w.submit_flush(out);
  auto t2 = std::chrono::steady_clock::now();
  double law = std::chrono::duration<double>(t1 - t0).count(), full = std::chrono::duration<double>(t2 - t0).count();
  std::printf("  %d splits: laws %.0f processes/s, with bus and store %.0f processes/s (%zu operations)\n", kN, kN / law, kN / full, out.size());
  CHECK(kN / full > 1000.0);
}

TEST(sort_is_the_index_in_kKinds_and_products_carry_it) {
  using namespace em::social::gen;
  World w;
  auto kinds_index = [](std::string_view n) -> int {
    for (std::size_t i = 0; i < kKinds.size(); ++i) if (kKinds[i] == n) return static_cast<int>(i);
    return -1;
  };
  for (const char* n : {"plank", "beam", "log", "door", "brick", "rubble", "flour_sack", "knife"}) CHECK(int(w.item(n)) == kinds_index(n));
  CHECK(w.item("plank") == 406 && w.catalog.item_name(w.item("plank")) == "plank");
  ProcessEngine eng(w.catalog, w.store, w.ground);
  EntityId log = w.spawn_item("log", {0, 0, 0});
  EntityId axe = w.spawn_item("battle_axe", {900, 0, 0});
  play(w, eng, strike(axe, log, 6000));                       // cut/split product
  std::size_t planks = 0;
  w.store.for_each([&](EntityId id, EntityKind k) { if (k == EntityKind::item && w.store.sort(id) == kinds_index("plank")) ++planks; });
  CHECK(planks == 6);
  EntityId door = w.spawn_item("door", {3000, 0, 0});
  EntityId sl = w.spawn_item("sledgehammer", {4000, 0, 0});
  play(w, eng, strike(sl, door, 6000, true));                 // disassemble product
  CHECK(w.count_sort(static_cast<std::uint16_t>(kinds_index("plank"))) > 6);
}

TEST(conflicts_are_fair_between_low_and_high_authors) {
  World w;
  ProcessEngine eng(w.catalog, w.store, w.ground);
  EntityId log = w.spawn_item("log", {0, 0, 0});
  EntityId axe = w.spawn_item("battle_axe", {900, 0, 0});
  int low_wins = 0;
  constexpr int kN = 400;
  for (int i = 0; i < kN; ++i) {
    Contact a = strike(axe, log, 6000), b = a;
    a.author = 1 + static_cast<std::uint32_t>(i % 7); a.decision_seq = static_cast<std::uint32_t>(i);
    b.author = 100000 + static_cast<std::uint32_t>(i % 5); b.decision_seq = static_cast<std::uint32_t>(i);
    std::vector<Contact> cs{b, a};
    std::vector<Emission> out;
    auto reps = eng.on_contacts(cs, static_cast<std::uint64_t>(i + 1), out);
    if (reps[1].outcome == Outcome::Done) ++low_wins;
  }
  CHECK(low_wins > kN * 35 / 100 && low_wins < kN * 65 / 100);
}

TEST(hostile_values_saturate_instead_of_overflowing) {
  World w;
  CHECK(ContactResolver::kinetic_energy_mj(INT32_MAX, INT32_MAX) > 0);
  CHECK(ContactResolver::kinetic_energy_mj(INT32_MAX, INT32_MAX) == ContactResolver::kinetic_energy_mj(kMaxMassG, 100000));
  CHECK(ContactResolver::fall_energy_mj(INT32_MAX, INT32_MAX) > 0);
  Profile odd;
  odd.mass_g = INT32_MAX; odd.size = {INT32_MAX, INT32_MAX, INT32_MAX};
  odd.parts = {{0xFFFF, 0xFFFF}, {rig::form_of("blade"), 0xFFFF}, {rig::form_of("blade"), 0x7000}};
  w.catalog.set_profile(EntityKind::item, 6001, odd);
  const Profile* p = w.catalog.profile(EntityKind::item, 6001);
  CHECK(p && p->mass_g == kMaxMassG && p->size.x == kMaxSizeMm && p->parts.size() == 2 && p->main_material() == kNoMatter);
  EntityId a = w.spawn(EntityKind::item, {2000000000, 2000000000, -2000000000}, 6001);
  EntityId b = w.spawn(EntityKind::item, {2000000000, 1999999000, -2000000000}, 6001);
  EntityId c = w.spawn(EntityKind::item, {-2000000000, -2000000000, 2000000000}, 6001);
  ProcessEngine eng(w.catalog, w.store, w.ground);
  SupportMap m = eng.resolver().support_map();
  CHECK(m.bodies.size() == 3 && a && b && c);
  std::vector<Emission> e;
  eng.tick_time(w.tick + 1, e);                      // no crash, no UB
  Contact hostile = strike(a, b, INT32_MAX);
  TouchedSet t;
  eng.on_contact(hostile, w.tick + 1, t, e);
  hostile.voxel_material = 0x7000; hostile.target = kNoEntity; hostile.manner = Manner::Dig;
  CHECK(eng.on_contact(hostile, w.tick + 1, t, e).outcome == Outcome::NoEffect);
  Contact lash; lash.tool = a; lash.other = a; lash.target = b; lash.manner = Manner::Lash;
  CHECK(eng.on_contact(lash, w.tick + 1, t, e).outcome == Outcome::NoEffect);
}

EMERGENCE_TEST_MAIN()
