// NpcStateCodec: round trip of 500 filled NPCs, reading by names, closed refusals, measured duration.
#include <algorithm>
#include <chrono>
#include <cstdio>
#include <cstring>
#include <fstream>

#include "emergence/social/npc_state_codec.h"
#include "emergence/testing/check.h"

using namespace em::social;
using gen::ColType;

namespace {

struct Rng {   // SplitMix64: fixed seed, no std::random
  std::uint64_t s;
  std::uint64_t next() {
    std::uint64_t z = (s += 0x9E3779B97F4A7C15ull);
    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ull;
    z = (z ^ (z >> 27)) * 0x94D049BB133111EBull;
    return z ^ (z >> 31);
  }
  std::uint32_t below(std::uint32_t n) { return std::uint32_t(next() % n); }
};

// Fills one field through its descriptor (the same table the codec reads).
std::int64_t draw(Rng& rng, const gen::FieldDesc& f) {   // uniform in the catalogue bounds of the column
  const std::uint64_t width = std::uint64_t(f.max - f.min) + 1;
  return f.min + std::int64_t(rng.next() % width);
}

void fill_field(Rng& rng, SideTable& side, const gen::FieldDesc& f, unsigned char* base) {
  unsigned char* p = base + f.offset;
  switch (f.type) {
    case ColType::Bool: *p = std::uint8_t(draw(rng, f)); break;
    case ColType::U8: *p = std::uint8_t(draw(rng, f)); break;
    case ColType::U16: { auto v = std::uint16_t(draw(rng, f)); std::memcpy(p, &v, 2); break; }
    case ColType::I16: { auto v = std::int16_t(draw(rng, f)); std::memcpy(p, &v, 2); break; }
    case ColType::I32: { auto v = std::int32_t(draw(rng, f)); std::memcpy(p, &v, 4); break; }
    case ColType::Entity: { auto v = std::uint32_t(draw(rng, f)); std::memcpy(p, &v, 4); break; }
    case ColType::MRef: { auto v = rng.below(2); std::memcpy(p, &v, 4); break; }   // 0 or 1: every NPC issues serial 1
    case ColType::Time: { auto v = draw(rng, f); std::memcpy(p, &v, 8); break; }
    case ColType::List: {
      std::uint32_t items[6];
      const std::uint32_t n = rng.below(7);
      for (std::uint32_t i = 0; i < n; ++i) items[i] = std::uint32_t(rng.next());
      ListRef ref = side.put(std::span<const std::uint32_t>(items, n));   // 0 when empty or the table is full
      std::memcpy(p, &ref, 4);
      break;
    }
    case ColType::Prop: {   // a well formed tree: one root with k leaves
      auto& pr = *reinterpret_cast<Proposition*>(p);
      pr = Proposition{};
      if (rng.below(4) == 0) break;
      const std::uint8_t k = std::uint8_t(rng.below(5));
      pr.push(Proposition::make(Proposition::kWord, rng.below(unsigned(gen::kWords.size()))), k);
      for (int i = 0; i < k; ++i) {
        if (rng.below(2)) pr.push(Proposition::make(Proposition::kKind, rng.below(unsigned(gen::kKinds.size()))), 0);
        else pr.push(Proposition::make(Proposition::kNumber, rng.below(1000)), 0);
      }
      break;
    }
  }
}

void fill_cells(Rng& rng, SideTable& side, const gen::ComponentDesc& d, unsigned char* base) {
  for (const auto& f : d.fields) fill_field(rng, side, f, base);
}

std::unique_ptr<NpcBundle> make_npc(std::uint64_t seed) {
  Rng rng{seed};
  auto npc = std::make_unique<NpcBundle>();
  gen::visit_components(npc->state, [&](const gen::ComponentDesc& d, auto& c) {
    fill_cells(rng, npc->side, d, reinterpret_cast<unsigned char*>(&c));
  });
  gen::visit_pools(npc->state, [&](const gen::ComponentDesc& d, auto& pool) {
    using T = typename std::decay_t<decltype(pool)>::value_type;
    const int cap = std::decay_t<decltype(pool)>::kCapacity;
    // sometimes more additions than slots: forgetting, serials above the capacity
    const int adds = rng.below(3) == 0 ? cap + int(rng.below(40)) : std::max(1, int(rng.below(unsigned(cap) + 1)));
    for (int i = 0; i < adds; ++i) {
      T rec{};
      fill_cells(rng, npc->side, d, reinterpret_cast<unsigned char*>(&rec));
      pool.add(rec, [](const T& r) { return int(reinterpret_cast<const std::uintptr_t&>(r) & 0) + 0; });   // all equal: oldest goes
      if (rng.below(8) == 0 && pool.size() > 0) {   // a removal now and then: holes in the slots
        pool.remove(MRef{pool.slot_serial(int(rng.below(unsigned(cap))))});
      }
    }
  });
  npc->ledger = WriteLedger(100, 5);
  const std::uint32_t nl = rng.below(20);
  for (std::uint32_t i = 0; i < nl; ++i) {
    auto v = static_cast<gen::Var>(rng.below(unsigned(gen::kVariables.size())));
    npc->ledger.add_today(v, rng.below(50), std::int32_t(rng.below(100)));
    npc->ledger.add_this_year(v, rng.below(50), std::int32_t(rng.below(100)));
  }
  npc->mental_map.resize(rng.below(40));
  for (auto& b : npc->mental_map) b = std::uint8_t(rng.next());
  return npc;
}

std::vector<std::unique_ptr<NpcBundle>> make_world(int n) {
  std::vector<std::unique_ptr<NpcBundle>> w;
  for (int i = 0; i < n; ++i) w.push_back(make_npc(0xC0FFEEull + std::uint64_t(i) * 7919));
  return w;
}

std::vector<std::uint64_t> prints(const std::vector<std::unique_ptr<NpcBundle>>& w) {
  std::vector<std::uint64_t> p;
  for (auto& n : w) p.push_back(NpcStateCodec::fingerprint(*n));
  return p;
}

// Replaces the payload of a framed section (the CRC is recomputed).
std::vector<std::uint8_t> reframe(std::uint32_t tag, std::span<const std::uint8_t> framed, std::vector<std::uint8_t> payload) {
  (void)framed;
  return NpcStateCodec::wrap_section(tag, 1, payload);
}
std::vector<std::uint8_t> payload_of(const std::vector<std::uint8_t>& framed) { return {framed.begin() + 20, framed.end()}; }

std::size_t find_name(const std::vector<std::uint8_t>& b, const char* name) {   // [u16 len][name] pattern
  const std::size_t n = std::strlen(name);
  std::vector<std::uint8_t> pat{std::uint8_t(n), 0};
  pat.insert(pat.end(), name, name + n);
  for (std::size_t i = 0; i + pat.size() <= b.size(); ++i)
    if (std::memcmp(b.data() + i, pat.data(), pat.size()) == 0) return i;
  return b.size();
}

}  // namespace

TEST(round_trip_500_npcs_same_logical_fingerprint_and_timing) {
  auto world = make_world(500);
  const auto before = prints(world);
  std::size_t forgotten = 0, lists = 0;
  for (auto& n : world) { forgotten += std::size_t(n->state.belief_records.forgotten()); lists += n->side.live_lists(); }
  CHECK(forgotten > 0 && lists > 0);

  const auto name = NpcStateCodec::save_name_section();
  const auto ms = [](auto a, auto b) { return std::chrono::duration<double, std::milli>(b - a).count(); };
  // best of 5 runs: the machine is shared with builds and other jobs, the minimum is the cost of the code
  double save_ms = 1e9, load_ms = 1e9, best = 1e9;
  std::vector<std::uint8_t> npcs;
  std::vector<std::unique_ptr<NpcBundle>> back;
  LoadReport rep;
  for (int run = 0; run < 5; ++run) {
    const auto t0 = std::chrono::steady_clock::now();
    npcs = NpcStateCodec::save_npcs_section(world);
    const auto t1 = std::chrono::steady_clock::now();
    back.clear();
    rep = NpcStateCodec::load(name, npcs, 100, 5, back);
    const auto t2 = std::chrono::steady_clock::now();
    if (ms(t0, t2) < best) { best = ms(t0, t2); save_ms = ms(t0, t1); load_ms = ms(t1, t2); }
  }
  CHECK(rep.ok);
  CHECK_EQ(back.size(), 500u);
  CHECK(rep.unknown_columns == 0 && rep.absent_columns == 0 && rep.dropped_propositions == 0 && rep.dropped_ledger_entries == 0);
  CHECK(rep.out_of_range_values == 0 && rep.invalid_propositions == 0 && rep.dangling_refs == 0);
  CHECK_EQ(rep.ledger_rejected, 0u);
  CHECK_EQ(rep.lost_lists, 0u);
  CHECK(prints(back) == before);
  // an independent look at a few values (the fingerprint alone could hide a codec symmetric error)
  for (int i : {0, 123, 499}) {
    CHECK(back[i]->state.mind_static.altruism == world[i]->state.mind_static.altruism);
    CHECK(back[i]->state.belief_records.size() == world[i]->state.belief_records.size());
    CHECK(back[i]->state.belief_records.next_serial() == world[i]->state.belief_records.next_serial());
    CHECK(back[i]->state.belief_records.forgotten() == world[i]->state.belief_records.forgotten());
    CHECK(back[i]->mental_map == world[i]->mental_map);
    CHECK(back[i]->ledger.entries().size() == world[i]->ledger.entries().size());
  }
  std::printf("  500 PNJ : %zu octets ; sauvegarde %.1f ms + chargement %.1f ms = %.1f ms (meilleur de 5 ; cible <= 200 ms [Estime])\n",
              npcs.size(), save_ms, load_ms, save_ms + load_ms);
  std::ofstream("t04_timing.txt") << "500 NPC save+load (best of 5): " << save_ms << " ms + " << load_ms << " ms = " << save_ms + load_ms
                                  << " ms, " << npcs.size() << " bytes\n";
  CHECK(save_ms + load_ms <= 600.0);   // hard guard against a regression; the 200 ms target is read in the output
}

TEST(wrong_crc_is_refused) {
  auto world = make_world(3);
  auto name = NpcStateCodec::save_name_section();
  auto npcs = NpcStateCodec::save_npcs_section(world);
  std::vector<std::unique_ptr<NpcBundle>> back;
  npcs[npcs.size() / 2] ^= 0x40;
  auto rep = NpcStateCodec::load(name, npcs, 100, 5, back);
  CHECK(!rep.ok && rep.refusal == Refusal::BadCrc && back.empty());
  npcs = NpcStateCodec::save_npcs_section(world);
  name[name.size() - 3] ^= 1;
  rep = NpcStateCodec::load(name, npcs, 100, 5, back);
  CHECK(!rep.ok && rep.refusal == Refusal::BadCrc);
  npcs = NpcStateCodec::save_npcs_section(world);
  npcs.resize(npcs.size() - 5);
  rep = NpcStateCodec::load(NpcStateCodec::save_name_section(), npcs, 100, 5, back);
  CHECK(!rep.ok && rep.refusal == Refusal::Truncated);
}

TEST(unknown_column_ignored_absent_column_initial_type_change_refused) {
  auto world = make_world(4);
  const auto name = NpcStateCodec::save_name_section();
  const auto npcs = NpcStateCodec::save_npcs_section(world);
  auto pl = payload_of(npcs);
  const std::size_t at = find_name(pl, "altruism");
  CHECK(at < pl.size());
  auto renamed = pl;
  renamed[at + 2 + 7] = 'X';   // "altruisX": unknown to this build, and "altruism" is now absent
  std::vector<std::unique_ptr<NpcBundle>> back;
  auto rep = NpcStateCodec::load(name, reframe(NpcStateCodec::kTagNpcs, npcs, renamed), 100, 5, back);
  CHECK(rep.ok);
  CHECK_EQ(rep.unknown_columns, 1u);
  CHECK_EQ(rep.absent_columns, 1u);
  CHECK_EQ(back.size(), 4u);
  CHECK_EQ(int(back[0]->state.mind_static.altruism), 0);   // initial value
  CHECK(back[0]->state.mind_static.anxiousness == world[0]->state.mind_static.anxiousness);   // the others are intact

  auto retyped = pl;
  retyped[at + 2 + 8] = std::uint8_t(ColType::Bool);   // i16 -> bool: a change of meaning
  back.clear();
  rep = NpcStateCodec::load(name, reframe(NpcStateCodec::kTagNpcs, npcs, retyped), 100, 5, back);
  CHECK(!rep.ok && rep.refusal == Refusal::TypeChanged && back.empty());
  CHECK(rep.detail == "mind_static.altruism");
}

TEST(propositions_are_translated_through_the_name_table) {
  auto npc = std::make_unique<NpcBundle>();
  Proposition p;
  p.push(Proposition::make(Proposition::kWord, 3), 1);
  p.push(Proposition::make(Proposition::kWord, 4), 0);
  gen::Belief b;
  b.b_proposition = p;
  npc->state.belief_records.add(b, [](const gen::Belief&) { return 0; });
  Proposition q;   // uses word 10: that one disappears from the NAME table
  q.push(Proposition::make(Proposition::kWord, 10), 0);
  gen::Belief b2;
  b2.b_proposition = q;
  npc->state.belief_records.add(b2, [](const gen::Belief&) { return 0; });
  std::vector<std::unique_ptr<NpcBundle>> world;
  world.push_back(std::move(npc));
  const auto npcs = NpcStateCodec::save_npcs_section(world);

  NameTables names = NameTables::current();
  std::swap(names.words[3], names.words[4]);          // the saved world numbered these two words the other way round
  names.words[10] = "word_that_was_removed";
  std::vector<std::unique_ptr<NpcBundle>> back;
  const auto rep = NpcStateCodec::load(NpcStateCodec::save_name_section(names), npcs, 100, 5, back);
  CHECK(rep.ok);
  CHECK_EQ(rep.dropped_propositions, 1u);
  int seen = 0;
  back[0]->state.belief_records.for_each([&](MRef, gen::Belief& r) {
    if (r.b_proposition.size() == 2) {
      ++seen;
      CHECK_EQ(Proposition::value(r.b_proposition.symbol(0)), 4u);   // saved 3 -> its name is now number 4
      CHECK_EQ(Proposition::value(r.b_proposition.symbol(1)), 3u);
    } else {
      CHECK(r.b_proposition.empty());
    }
  });
  CHECK_EQ(seen, 1);
}

TEST(ledger_goes_through_restore_with_the_engine_clock) {
  auto world = make_world(1);
  const auto name = NpcStateCodec::save_name_section();
  const auto npcs = NpcStateCodec::save_npcs_section(world);
  std::vector<std::unique_ptr<NpcBundle>> back;
  // the engine's clock is EARLIER than the saved stamps: restore() refuses and locks, the load itself succeeds
  const auto rep = NpcStateCodec::load(name, npcs, 50, 1, back);
  CHECK(rep.ok);
  CHECK_EQ(rep.ledger_rejected, 1u);
  CHECK_EQ(back[0]->ledger.entries().size(), 0u);
  CHECK_EQ(back[0]->ledger.day(), 50);
}

namespace {

// Hand-built NPCS payload with a reduced schema (one component, a few columns) and one NPC: the way to feed the loader
// a type or a value no honest save would hold.
struct Col { const char* name; ColType type; };
struct Hand {
  std::vector<std::uint8_t> b;
  void u8(std::uint8_t v) { b.push_back(v); }
  void u16(std::uint16_t v) { u8(std::uint8_t(v)); u8(std::uint8_t(v >> 8)); }
  void u32(std::uint32_t v) { u16(std::uint16_t(v)); u16(std::uint16_t(v >> 16)); }
  void str(const char* s) { u16(std::uint16_t(std::strlen(s))); for (; *s; ++s) u8(std::uint8_t(*s)); }
};
// cells: already encoded bytes of the record or flat struct
std::vector<std::uint8_t> hand_npcs(const char* comp, bool record, std::initializer_list<Col> cols, const std::vector<std::uint8_t>& cells) {
  Hand h;
  h.u32(1);
  h.str(comp); h.u8(record); h.u32(0); h.u32(std::uint32_t(cols.size()));
  for (const Col& c : cols) { h.str(c.name); h.u8(std::uint8_t(c.type)); }
  h.u32(1);          // one NPC
  h.u32(0);          // no list
  if (record) { h.u32(1); h.u32(0); h.u32(0); h.u32(1); h.u32(0); h.u32(1); }   // next serial 1, 1 record: slot 0, serial 1
  h.b.insert(h.b.end(), cells.begin(), cells.end());
  h.u32(0); h.u32(0); h.u32(0);   // ledger: day, year, no entry
  h.u32(0);                       // mental map
  return NpcStateCodec::wrap_section(NpcStateCodec::kTagNpcs, 1, h.b);
}

LoadReport load_hand(const std::vector<std::uint8_t>& npcs, std::vector<std::unique_ptr<NpcBundle>>& back) {
  return NpcStateCodec::load(NpcStateCodec::save_name_section(), npcs, 100, 5, back);
}

// Every value of an NPC must be inside the bounds of its column.
long out_of_bounds(NpcBundle& npc) {
  long bad = 0;
  std::uint32_t top = 0;
  gen::visit_pools(npc.state, [&](const gen::ComponentDesc&, const auto& pool) { top = std::max(top, pool.next_serial()); });
  auto check = [&](const gen::ComponentDesc& d, const unsigned char* base) {
    for (const auto& f : d.fields) {
      const unsigned char* p = base + f.offset;
      std::int64_t v = 0;
      switch (f.type) {
        case ColType::Bool: case ColType::U8: v = *p; break;
        case ColType::U16: { std::uint16_t x; std::memcpy(&x, p, 2); v = x; break; }
        case ColType::I16: { std::int16_t x; std::memcpy(&x, p, 2); v = x; break; }
        case ColType::I32: { std::int32_t x; std::memcpy(&x, p, 4); v = x; break; }
        case ColType::Entity: { std::uint32_t x; std::memcpy(&x, p, 4); v = x; break; }
        case ColType::MRef: { std::uint32_t x; std::memcpy(&x, p, 4); v = x; if (x > top) ++bad; break; }
        case ColType::Time: std::memcpy(&v, p, 8); break;
        case ColType::List: continue;
        case ColType::Prop: {
          const auto& pr = *reinterpret_cast<const Proposition*>(p);
          if (!pr.empty() && !pr.well_formed()) ++bad;
          for (int i = 0; i < pr.size(); ++i) {
            const auto tg = Proposition::tag(pr.symbol(i));
            if (tg < Proposition::kWord || tg > Proposition::kName) ++bad;
            if (tg == Proposition::kWord && Proposition::value(pr.symbol(i)) >= gen::kWords.size()) ++bad;
            if (tg == Proposition::kKind && Proposition::value(pr.symbol(i)) >= gen::kKinds.size()) ++bad;
          }
          continue;
        }
      }
      if (v < f.min || v > f.max) ++bad;
    }
  };
  gen::visit_components(npc.state, [&](const gen::ComponentDesc& d, auto& c) { check(d, reinterpret_cast<const unsigned char*>(&c)); });
  gen::visit_pools(npc.state, [&](const gen::ComponentDesc& d, auto& pool) {
    for (int i = 0; i < std::decay_t<decltype(pool)>::kCapacity; ++i)
      if (pool.slot_used(i)) check(d, reinterpret_cast<const unsigned char*>(&pool.slot_record(i)));
  });
  return bad;
}

}  // namespace

TEST(widening_i16_to_i32_is_accepted) {
  Hand c;
  c.u16(std::uint16_t(std::int16_t(-1234)));
  std::vector<std::unique_ptr<NpcBundle>> back;
  const auto rep = load_hand(hand_npcs("body", false, {{"blood_volume", ColType::I16}}, c.b), back);
  CHECK(rep.ok);
  CHECK_EQ(rep.widened_columns, 1u);
  CHECK_EQ(back[0]->state.body.blood_volume, -1234);
  // the reverse (narrowing) is a change of meaning: refused
  Hand d;
  d.u32(7);
  const auto rep2 = load_hand(hand_npcs("body", false, {{"pain", ColType::I32}}, d.b), back);
  CHECK(!rep2.ok && rep2.refusal == Refusal::TypeChanged && back.empty());
}

TEST(out_of_range_values_fall_back_to_the_initial_value_and_are_counted) {
  std::vector<std::unique_ptr<NpcBundle>> back;
  {   // enum out of bounds (zones has 16 values) and a ratio above 1000
    Hand c;
    c.u8(200);
    c.u16(5000);
    c.u16(700);   // a valid ratio next to it
    const auto rep = load_hand(hand_npcs("body", false, {{"zones", ColType::U8}, {"mobility", ColType::I16}, {"manipulation", ColType::I16}}, c.b), back);
    CHECK(rep.ok);
    CHECK_EQ(rep.out_of_range_values, 2u);
    CHECK_EQ(int(back[0]->state.body.zones), 0);
    CHECK_EQ(int(back[0]->state.body.mobility), 0);
    CHECK_EQ(int(back[0]->state.body.manipulation), 700);
  }
  {   // a bool that is 2, a tenth-scale value of 101
    Hand c;
    c.u8(2);
    c.u16(101);
    const auto rep = load_hand(hand_npcs("body", false, {{"alive", ColType::Bool}, {"pain", ColType::I16}}, c.b), back);
    CHECK(rep.ok && rep.out_of_range_values == 2);
    CHECK(!back[0]->state.body.alive && back[0]->state.body.pain == 0);
  }
  {   // a reference to a record never issued
    Hand c;
    c.u32(99);
    const auto rep = load_hand(hand_npcs("mind_dynamic", false, {{"attention", ColType::MRef}}, c.b), back);
    CHECK(rep.ok && rep.dangling_refs == 1);
    CHECK_EQ(back[0]->state.mind_dynamic.attention.serial, 0u);
  }
}

TEST(malformed_propositions_are_emptied_and_counted) {
  std::vector<std::unique_ptr<NpcBundle>> back;
  auto run = [&](std::initializer_list<std::pair<std::uint32_t, std::uint8_t>> syms) {
    Hand c;
    c.u8(std::uint8_t(syms.size()));
    for (auto [sym, ar] : syms) { c.u32(sym); c.u8(ar); }
    c.u8(3);   // b_source next to it, valid
    return load_hand(hand_npcs("belief", true, {{"b_proposition", ColType::Prop}, {"b_source", ColType::U8}}, c.b), back);
  };
  auto belief = [&]() -> const gen::Belief& { return back[0]->state.belief_records.slot_record(0); };
  auto rep = run({{9u << 24 | 1, 0}});                       // tag 9
  CHECK(rep.ok && rep.invalid_propositions == 1 && belief().b_proposition.empty());
  CHECK_EQ(int(belief().b_source), 3);
  rep = run({{Proposition::make(Proposition::kWord, 1), 2}});   // promises two children, has none
  CHECK(rep.ok && rep.invalid_propositions == 1 && belief().b_proposition.empty());
  rep = run({{Proposition::make(Proposition::kNone, 1), 0}});   // tag 0
  CHECK(rep.ok && rep.invalid_propositions == 1);
  rep = run({{Proposition::make(Proposition::kNumber, 7), 0}, {Proposition::make(Proposition::kNumber, 8), 0}});   // two trees
  CHECK(rep.ok && rep.invalid_propositions == 1);
  rep = run({{Proposition::make(Proposition::kNumber, 7), 0}});   // a lone leaf is a valid tree
  CHECK(rep.ok && rep.invalid_propositions == 0 && belief().b_proposition.size() == 1);
}

TEST(refusal_empties_out) {
  auto world = make_world(2);
  auto npcs = NpcStateCodec::save_npcs_section(world);
  std::vector<std::unique_ptr<NpcBundle>> back;
  CHECK(NpcStateCodec::load(NpcStateCodec::save_name_section(), npcs, 100, 5, back).ok);
  CHECK_EQ(back.size(), 2u);
  npcs[npcs.size() / 2] ^= 1;
  CHECK(!NpcStateCodec::load(NpcStateCodec::save_name_section(), npcs, 100, 5, back).ok);
  CHECK(back.empty());
}

TEST(fuzz_2000_mutations_never_leave_an_out_of_bounds_value) {
  auto world = make_world(2);
  const auto name = NpcStateCodec::save_name_section();
  const auto npcs = NpcStateCodec::save_npcs_section(world);
  const auto pl = payload_of(npcs);
  Rng rng{0xFAB1Eull};
  int accepted = 0, refused_n = 0;
  long corrected = 0;
  for (int it = 0; it < 2000; ++it) {
    auto m = pl;
    const int edits = 1 + int(rng.below(4));
    for (int e = 0; e < edits; ++e) {
      // half of the mutations land in the schema header and the first records, where structure lives
      const std::size_t pos = rng.below(2) ? rng.below(std::uint32_t(std::min<std::size_t>(m.size(), 6000))) : rng.below(std::uint32_t(m.size()));
      switch (rng.below(3)) {
        case 0: m[pos] = std::uint8_t(rng.next()); break;
        case 1: m[pos] ^= std::uint8_t(1u << rng.below(8)); break;
        default: m[pos] = rng.below(2) ? 0xFF : 0x00; break;
      }
    }
    std::vector<std::unique_ptr<NpcBundle>> back;
    const auto rep = NpcStateCodec::load(name, reframe(NpcStateCodec::kTagNpcs, npcs, m), 100, 5, back);
    if (!rep.ok) { ++refused_n; CHECK(back.empty()); continue; }
    ++accepted;
    corrected += long(rep.out_of_range_values + rep.invalid_propositions + rep.dangling_refs + rep.dropped_propositions);
    for (auto& n : back) CHECK_EQ(out_of_bounds(*n), 0);
  }
  std::printf("  fuzz : %d acceptes, %d refuses, %ld valeurs ramenees a l'initial\n", accepted, refused_n, corrected);
  CHECK(accepted > 0 && refused_n > 0 && corrected > 0);
}

EMERGENCE_TEST_MAIN()
