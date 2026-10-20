// ContextBuilder (T28b): the selection (bounded, by salience, deterministic), the ghosts, the wake, the unknown markers, the
// pointer kinds, and above all the firewall: the context never depends on a variable that has no token (the truth).
#include <cstring>
#include <memory>
#include <set>
#include <string>

#include "context_compare.h"
#include "context_map_gen.h"
#include "tok2_gen.h"
#include "emergence/social/language.h"
#include "emergence/social/npc_fields_gen.h"
#include "emergence/social/tokenizer/context_builder.h"
#include "emergence/testing/check.h"

using namespace em::social;
using namespace em::social::tok2;
using namespace em::social::tok2::testing;
namespace tgen = em::social::tok2::gen;
namespace sgen = em::social::gen;

namespace {

constexpr GameTime kNow = 50'000'000;

const Tokenizer& tokenizer() { static const Tokenizer tk; return tk; }
const ContextBuilder& builder() { static const ContextBuilder cb(tokenizer()); return cb; }
const Parser& parser() { static const Parser p; return p; }

// An NPC mind built by hand. Every record is the NPC's own; `poison` changes the TRUTH only.
struct Rig {
  std::unique_ptr<NpcBundle> bundle = std::make_unique<NpcBundle>();
  std::vector<FileLink> links;
  WakeInput wake;
  ContextBuilder::Workspace ws;

  sgen::NpcState& st() { return bundle->state; }
  PropRef prop(const char* text, bool bare = true) {
    ParseOptions opt;
    opt.bare = bare;
    const TypedExpression e = parser().parse(text, opt);
    Proposition p;
    CHECK(e.ok());
    CHECK(e.to_proposition(p) == ConvertStatus::ok);
    const PropRef r = bundle->propositions.put(p);
    CHECK(r != 0);
    return r;
  }
  MRef belief(const char* text, int importance, int certainty, GameTime age_s, std::uint32_t poison = 0) {
    sgen::Belief b;
    b.b_proposition = prop(text);
    b.b_importance = std::int16_t(importance);
    b.b_certainty = std::int16_t(certainty);
    b.b_acquired = kNow - age_s;
    b.b_polarity = true;
    b.b_truth = poison & 1;
    b.b_origin_fact = poison * 7;
    return st().belief_records.add(b, [](const sgen::Belief&) { return 0; });
  }
  MRef person(int familiarity, bool present, std::uint32_t poison = 0) {
    sgen::Relation r;
    r.r_familiarity = std::int16_t(familiarity);
    r.r_present = present;
    r.r_true_entity = poison * 5;
    return st().relation_records.add(r, [](const sgen::Relation&) { return 0; });
  }
  MRef memory(const char* text, int importance, GameTime age_s, std::uint32_t poison = 0) {
    sgen::Episode m;
    m.m_content = prop(text);
    m.m_importance = std::int16_t(importance);
    m.m_when = kNow - age_s;
    m.m_fact_ref = poison * 3;
    return st().episode_records.add(m, [](const sgen::Episode&) { return 0; });
  }
  void build(DecisionContext& out, bool encode_too = true) {
    MindSource src{bundle.get(), kNow, wake, links};
    builder().build(src, ws, out);
    if (encode_too) {
      Encoded enc;
      std::string why;
      CHECK(tokenizer().try_encode(out, enc, &why));
      if (!why.empty()) std::printf("  refused: %s\n", why.c_str());
    }
  }
};

}  // namespace

TEST(an_empty_mind_still_builds_a_valid_dossier) {
  Rig r;
  DecisionContext ctx;
  r.build(ctx);
  CHECK(find_record(ctx, "me") != nullptr);
  CHECK(find_record(ctx, "@PLACE") != nullptr);
  CHECK(find_record(ctx, "wake") != nullptr);
  CHECK(count_type(ctx, "BELIEF") == 0);
}

TEST(the_selection_is_bounded_and_keeps_the_most_salient) {
  Rig r;
  for (int i = 0; i < 200; ++i) r.belief("(at me @L1)", i % 100, 50, 3600 * (i % 7));
  for (int i = 0; i < 100; ++i) r.memory("(past (did me look @E1))", i % 100, 7200);
  for (int i = 0; i < 80; ++i) r.person(i % 100, i % 5 == 0);
  DecisionContext ctx;
  r.build(ctx);
  CHECK_EQ(count_type(ctx, "BELIEF"), 12);
  CHECK_EQ(count_type(ctx, "MEMORY"), 9);
  CHECK_EQ(count_type(ctx, "ENTITY"), 10);
  CHECK(int(ctx.records.size()) <= kMaxTokens);
  // the best belief by the integer salience of CandidateSelector is carried
  Candidates c;
  CandidateSelector().select(r.st(), kNow, c);
  std::set<std::string> want;
  for (int i = 0; i < 12; ++i) want.insert("b:" + std::to_string(c.beliefs[std::size_t(i)].ref.serial));
  for (const Record& rec : ctx.records) if (rec.type == "BELIEF") CHECK(want.count(rec.key) == 1);
  // the people present come first
  const Record* first = nullptr;
  for (const Record& rec : ctx.records) if (rec.type == "ENTITY") { first = &rec; break; }
  CHECK(first != nullptr);
  const Value* present = field_of(tokenizer(), *first, "present");
  CHECK(present && present->as_bool());
}

TEST(a_pointer_to_a_record_the_dossier_does_not_carry_is_a_ghost) {
  Rig r;
  const MRef far = r.person(0, false);                    // filed, never salient
  for (int i = 0; i < 40; ++i) r.person(90, true);         // fills the ten places of the people
  const std::string text = "(at @E" + std::to_string(far.serial) + " @L1)";
  r.belief(text.c_str(), 100, 100, 0);
  DecisionContext ctx;
  r.build(ctx, false);
  CHECK(find_record(ctx, "@E" + std::to_string(far.serial)) == nullptr);
  bool known = false;
  for (const std::string& k : ctx.known_keys) known = known || k == "@E" + std::to_string(far.serial);
  CHECK(known);
  Encoded enc;
  std::string why;
  CHECK(tokenizer().try_encode(ctx, enc, &why));
  CHECK_EQ(int(enc.ghosts.size()), 2);           // the person and the place @L1: neither is carried
  bool person_ghost = false;
  for (const std::string& g : enc.ghosts) person_ghost = person_ghost || g == "@E" + std::to_string(far.serial);
  CHECK(person_ghost);
}

TEST(the_record_that_woke_the_npc_is_always_carried) {
  Rig r;
  MRef low;
  for (int i = 0; i < 8; ++i) {
    sgen::Goal g;
    g.g_desired = r.prop("(at me @L1)");
    g.g_priority = std::int16_t(i == 3 ? 1 : 90);
    g.g_status = 0;
    const MRef ref = r.st().goal_records.add(g, [](const sgen::Goal&) { return 0; });
    if (i == 3) low = ref;
  }
  DecisionContext ctx;
  r.wake.trigger = make_ref(RefKind::goal, low.serial);
  r.wake.cause = WakeCause::goal_check;
  r.wake.mode = WakeMode::reflect;
  r.wake.budget = 3;
  r.wake.urgency_tenths = 41;
  r.wake.temperament_tenths = 89;
  r.build(ctx);
  CHECK_EQ(count_type(ctx, "GOAL"), 4);
  CHECK(find_record(ctx, "g:" + std::to_string(low.serial)) != nullptr);
  const Record* w = find_record(ctx, "wake");
  CHECK(w != nullptr);
  const Tokenizer& tk = tokenizer();
  CHECK(field_of(tk, *w, "trigger")->as_string() == "g:" + std::to_string(low.serial));
  CHECK(field_of(tk, *w, "cause")->as_string() == "goal_check");
  CHECK(field_of(tk, *w, "mode")->as_string() == "reflect");
  CHECK(field_of(tk, *w, "budget")->as_number() == 3.0);
  CHECK(field_of(tk, *w, "urgency")->as_number() == 4.1);
  CHECK(field_of(tk, *w, "temperament")->as_number() == 8.9);
  CHECK(field_of(tk, *w, "outcome") == nullptr);
  r.wake.outcome = WakeOutcome::blocked;
  r.build(ctx);
  CHECK(field_of(tk, *find_record(ctx, "wake"), "outcome")->as_string() == "blocked");
}

TEST(unknown_is_not_zero) {
  Rig r;
  sgen::Belief b;
  b.b_proposition = r.prop("(at me @L1)");
  b.b_certainty = 0;                          // known: zero
  b.b_importance = unknown::kI16;             // unknown
  b.b_informant = MRef{0};                    // known: nobody
  b.b_source = unknown::kU8;                  // unknown
  b.b_told_to = unknown::kRef;                // unknown list
  b.b_hops = unknown::kI32;
  r.st().belief_records.add(b, [](const sgen::Belief&) { return 0; });
  DecisionContext ctx;
  r.build(ctx);
  const Record* rec = nullptr;
  for (const Record& x : ctx.records) if (x.type == "BELIEF") rec = &x;
  CHECK(rec != nullptr);
  const Tokenizer& tk = tokenizer();
  CHECK(field_of(tk, *rec, "certainty") && field_of(tk, *rec, "certainty")->as_number() == 0.0);
  CHECK(field_of(tk, *rec, "importance") == nullptr);
  CHECK(field_of(tk, *rec, "source") == nullptr);
  CHECK(field_of(tk, *rec, "shared") == nullptr);
  CHECK(field_of(tk, *rec, "hops") == nullptr);
  CHECK(field_of(tk, *rec, "informant") && field_of(tk, *rec, "informant")->as_string().empty());
  CHECK(field_of(tk, *rec, "unintelligible") == nullptr);       // the sparse flag: only when true
  CHECK(field_of(tk, *rec, "polarity") != nullptr);
}

TEST(a_pointer_of_another_kind_than_the_field_accepts_is_dropped_not_fatal) {
  Rig r;
  sgen::Belief b;
  b.b_proposition = r.prop("(at me @L1)");
  b.b_informant = make_ref(RefKind::thing, 3);     // the informant of a belief is a person
  r.st().belief_records.add(b, [](const sgen::Belief&) { return 0; });
  DecisionContext ctx;
  r.build(ctx);
  CHECK_EQ(int(r.ws.stats.dropped_pointers), 1);
  for (const Record& x : ctx.records) if (x.type == "BELIEF") CHECK(field_of(tokenizer(), x, "informant") == nullptr);
}

TEST(a_person_who_is_not_present_has_no_distance_and_no_look) {
  Rig r;
  sgen::Relation rel;
  rel.r_present = false;
  rel.r_familiarity = 50;
  const MRef file = r.st().relation_records.add(rel, [](const sgen::Relation&) { return 0; });
  sgen::EntityPercept ep;
  ep.ep_dist = 4000;
  ep.ep_age = 30000;
  const MRef seen = r.st().entity_percept_records.add(ep, [](const sgen::EntityPercept&) { return 0; });
  r.links.push_back({seen.serial, file});
  DecisionContext ctx;
  r.build(ctx);
  const Record* e = find_record(ctx, "@E" + std::to_string(file.serial));
  CHECK(e != nullptr);
  CHECK(field_of(tokenizer(), *e, "dist") == nullptr);
  CHECK(field_of(tokenizer(), *e, "look.age") == nullptr);
  CHECK(field_of(tokenizer(), *e, "present")->as_bool() == false);
}

TEST(a_person_seen_without_a_file_is_a_stranger) {
  Rig r;
  sgen::EntityPercept ep;
  ep.ep_dist = 12000;
  const MRef seen = r.st().entity_percept_records.add(ep, [](const sgen::EntityPercept&) { return 0; });
  DecisionContext ctx;
  r.build(ctx);
  const Record* e = find_record(ctx, "@E" + std::to_string(kStrangerBase + seen.serial));
  CHECK(e != nullptr);
  CHECK(field_of(tokenizer(), *e, "present")->as_bool());
  CHECK(field_of(tokenizer(), *e, "dist")->as_number() == 12.0);
  CHECK(field_of(tokenizer(), *e, "rel.trust") == nullptr);     // no file: nothing is known of the relation
}

TEST(the_plan_reads_its_step_its_next_step_and_its_target) {
  Rig r;
  const auto word = [](const char* w) {
    for (std::size_t i = 0; i < sgen::kWords.size(); ++i) if (sgen::kWords[i] == w) return std::uint32_t(i);
    return 0u;
  };
  const std::uint32_t steps[] = {word("go"), word("look"), word("wait")};
  sgen::Intention in;
  in.i_steps = r.bundle->side.put(steps);
  in.i_step_index = 1000;                                     // on the step 1
  const std::uint32_t targets[] = {kPlanTargetHeader | make_ref(RefKind::locus, 3).serial, make_ref(RefKind::locus, 3).serial, make_ref(RefKind::place).serial};
  in.i_step_targets = r.bundle->side.put(targets);
  in.i_commitment = 25;
  in.i_step_progress = 630;
  in.i_serves = make_ref(RefKind::goal, 2);
  in.i_status = 0;
  in.i_repeat = 0;
  const MRef p = r.st().intention_records.add(in, [](const sgen::Intention&) { return 0; });
  DecisionContext ctx;
  r.build(ctx);
  const Record* rec = find_record(ctx, "p:" + std::to_string(p.serial));
  CHECK(rec != nullptr);
  const Tokenizer& tk = tokenizer();
  CHECK(field_of(tk, *rec, "step")->as_string() == "look");
  CHECK(field_of(tk, *rec, "next")->as_string() == "wait");
  CHECK(field_of(tk, *rec, "target")->as_string() == "@L3");
  CHECK(field_of(tk, *rec, "goal")->as_string() == "g:2");
  CHECK(field_of(tk, *rec, "progress")->as_number() == 0.63);
  CHECK(field_of(tk, *rec, "commitment")->as_number() == 2.5);
  CHECK(field_of(tk, *rec, "step_targets")->items().size() == 2);     // the header is not a step target
  in.i_step_index = 2000;                                     // the last step: the plan ends after it
  r.st().intention_records.remove(p);
  const MRef p2 = r.st().intention_records.add(in, [](const sgen::Intention&) { return 0; });
  r.build(ctx);
  rec = find_record(ctx, "p:" + std::to_string(p2.serial));
  CHECK(field_of(tk, *rec, "next")->as_string().empty());
}

TEST(the_same_state_gives_the_same_context) {
  Rig r;
  for (int i = 0; i < 100; ++i) r.belief("(at me @L1)", (i * 13) % 100, (i * 7) % 100, 3600 * (i % 11));
  for (int i = 0; i < 60; ++i) r.person((i * 17) % 100, i % 4 == 0);
  DecisionContext a, b, c;
  r.build(a);
  ContextBuilder::Workspace other;
  MindSource src{r.bundle.get(), kNow, r.wake, r.links};
  builder().build(src, other, b);
  r.build(c);
  CHECK(same_context(a, b));
  CHECK(same_context(a, c));
  Encoded e1, e2;
  tokenizer().encode(a, e1);
  tokenizer().encode(b, e2);
  CHECK_EQ(int(e1.digest()), int(e2.digest()));
}

// ---- the firewall: no variable without a token reaches the dossier
namespace {

struct Lcg {
  std::uint64_t s;
  std::uint32_t next() { s = s * 6364136223846793005ull + 1442695040888963407ull; return std::uint32_t(s >> 33); }
};

std::set<std::string_view> token_vars() {
  std::set<std::string_view> v;
  for (const auto& r : tgen::kSources) if (!r.var.empty()) v.insert(r.var);
  for (const auto& r : tgen::kDerivedSources) v.insert(r.var);
  for (const auto& r : tgen::kListRecords) v.insert(r.var);
  return v;
}

// Overwrites with noise every field of the state that has no token, in the flat components and in EVERY slot of every pool.
int scramble_truth(sgen::NpcState& st, std::uint32_t seed) {
  static const std::set<std::string_view> allowed = token_vars();
  Lcg g{seed};
  int n = 0;
  const auto scramble = [&](const sgen::ComponentDesc& d, unsigned char* base) {
    for (const sgen::FieldDesc& f : d.fields) {
      if (allowed.count(f.name)) continue;
      for (std::size_t i = 0; i < f.size; ++i) base[f.offset + i] = static_cast<unsigned char>(g.next());
      ++n;
    }
  };
  sgen::visit_components(st, [&](const sgen::ComponentDesc& d, auto& comp) { scramble(d, reinterpret_cast<unsigned char*>(&comp)); });
  sgen::visit_pools(st, [&](const sgen::ComponentDesc& d, auto& pool) {
    for (int i = 0; i < pool.kCapacity; ++i) scramble(d, reinterpret_cast<unsigned char*>(&pool.slot_record_mut(i)));
  });
  return n;
}

}  // namespace

TEST(no_variable_without_a_token_reaches_the_dossier) {
  Rig r;
  for (int i = 0; i < 90; ++i) r.belief("(at me @L1)", (i * 13) % 100, (i * 7) % 100, 3600 * (i % 11), 1);
  for (int i = 0; i < 40; ++i) r.memory("(past (did me look @E1))", (i * 9) % 100, 7200, 1);
  for (int i = 0; i < 30; ++i) r.person((i * 17) % 100, i % 4 == 0, 1);
  for (int i = 0; i < 5; ++i) {
    sgen::Goal g;
    g.g_desired = r.prop("(at me @L1)");
    g.g_priority = std::int16_t(10 * i);
    r.st().goal_records.add(g, [](const sgen::Goal&) { return 0; });
    sgen::Skill k;
    k.k_self_estimate = std::int16_t(7 * i);
    k.k_technique = std::uint8_t(i);
    k.k_mastery = std::int16_t(99 - i);
    r.st().skill_records.add(k, [](const sgen::Skill&) { return 0; });
  }
  DecisionContext before, after;
  r.build(before);
  Encoded e1, e2;
  tokenizer().encode(before, e1);
  const int fields = scramble_truth(r.st(), 12345);
  CHECK(fields > 30);
  r.build(after);
  tokenizer().encode(after, e2);
  CHECK(same_context(before, after));
  CHECK_EQ(int(e1.digest()), int(e2.digest()));
  scramble_truth(r.st(), 777);                  // and again, other noise
  r.build(after);
  CHECK(same_context(before, after));
}

TEST(the_firewall_has_teeth_a_token_variable_does_change_the_dossier) {
  Rig r;
  r.belief("(at me @L1)", 50, 50, 0);
  DecisionContext before, after;
  r.build(before);
  r.st().needs.hunger = 77;                     // a variable WITH a token (SELF.need.hunger)
  r.build(after);
  CHECK(!same_context(before, after));
}

TEST(every_variable_the_builder_names_has_a_token_and_none_is_objective) {
  const std::set<std::string_view> allowed = token_vars();
  for (const std::string_view engine : tgen::kEngineVars) CHECK(allowed.count(engine) == 0);
  CHECK(allowed.size() > 100);
}

TEST(serials_never_overflow_into_the_kind_tag) {
  Rig r;
  r.belief("(at me @L1)", 50, 50, 0);
  const MRef last = r.st().belief_records.add(sgen::Belief{}, [](const sgen::Belief&) { return 0; });
  // force the counter to the limit: the next addition is refused cleanly and counted, nothing wraps into the top byte
  CHECK(r.st().belief_records.restore_counters(r.st().belief_records.next_serial(), 0, 0));
  sgen::RecordPool<sgen::Belief, 384> p;
  sgen::Belief b;
  CHECK(p.restore_slot(0, 5, b));
  CHECK(p.restore_counters(sgen::RecordPool<sgen::Belief, 384>::kSerialMax - 1, 0, 0));
  const MRef ok = p.add(b, [](const sgen::Belief&) { return 0; });
  CHECK_EQ(int(ok.serial), int(sgen::RecordPool<sgen::Belief, 384>::kSerialMax));
  CHECK((ok.serial >> 24) == 0);
  const MRef refused = p.add(b, [](const sgen::Belief&) { return 0; });
  CHECK_EQ(int(refused.serial), 0);
  CHECK_EQ(p.serial_refused(), 1);
  CHECK(p.size() == 2);
  CHECK(last.serial != 0);
  // and a tagged pointer keeps its tag whatever the serial
  const MRef t = make_ref(RefKind::entity, sgen::RecordPool<sgen::Belief, 384>::kSerialMax);
  CHECK(ref_kind(t) == RefKind::entity);
  CHECK_EQ(int(ref_serial(t)), int(sgen::RecordPool<sgen::Belief, 384>::kSerialMax));
}

TEST(the_plan_target_header_is_shared_and_skipped) {
  const std::uint32_t ref = make_ref(RefKind::locus, 3).serial;
  const std::uint32_t h = make_target_header(ref);
  CHECK(is_target_header(h));
  CHECK(!is_target_header(ref));
  CHECK_EQ(int(strip_target_header(h)), int(ref));
  const std::uint32_t with[] = {h, ref, ref};
  const std::uint32_t without[] = {ref, ref};
  CHECK_EQ(int(skip_target_header(with).size()), 2);
  CHECK_EQ(int(skip_target_header(without).size()), 2);
  CHECK(skip_target_header(std::span<const std::uint32_t>()).empty());
}

EMERGENCE_TEST_MAIN()
