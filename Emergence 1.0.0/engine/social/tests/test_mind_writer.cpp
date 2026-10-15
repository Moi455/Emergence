// T24: MindWriter. The model's writes pass the governor: at most 4 per decision, T_jump / T_step / T_slow bounds,
// D10 (a rising intimate variable with a possible minor is refused), enforce_d10 after every application.
// D10 REFUSAL tests only.
#include <cstdio>
#include <map>
#include <memory>

#include "emergence/social/mind_writer.h"
#include "emergence/testing/check.h"

using namespace em::social;

namespace {

gen::Var var(std::string_view id) {
  for (std::size_t i = 0; i < gen::kVarNames.size(); ++i)
    if (gen::kVarNames[i] == id) return static_cast<gen::Var>(i);
  CHECK(false);
  return gen::Var{};
}

class Parties final : public PartySource {
 public:
  Party party_seen_by(EntityId, EntityId who) const override {
    auto it = m.find(who);
    return it == m.end() ? Party{} : it->second;
  }
  std::map<EntityId, Party> m;
};

std::unique_ptr<NpcBundle> adult() {
  auto b = std::make_unique<NpcBundle>();
  b->state.body.alive = true;
  NpcLaws::set_age(b->state, 300);
  return b;
}

MRef person(NpcBundle& b, EntityId truth, std::uint8_t known_by = 0) {
  gen::Relation r;
  r.r_true_entity = truth; r.r_known_by = known_by;
  return b.state.relation_records.add(r, 0);
}

std::string at(MRef r) { return "@E" + std::to_string(r.serial); }

}  // namespace

TEST(a_jump_variable_moves_at_once_and_a_step_variable_is_bounded) {
  Parties pa; pa.m[1] = Party{300, 300, 300, true, true, true};
  auto n = adult();
  const MRef f = person(*n, 2);
  MindWriter w(&pa);
  const GameTime day0 = 1000;
  WriteIntent jump{var("anger"), "self", 80};
  auto rep = w.apply(*n, 1, day0, std::span(&jump, 1));
  CHECK(rep.outcomes[0].verdict.allowed && rep.outcomes[0].verdict.reason == Reason::jump);
  CHECK_EQ(n->state.mind_dynamic.anger, 80);
  // r_trust: step 5 per decision, rate 20 per game day
  std::int16_t total = 0;
  for (int i = 0; i < 6; ++i) {
    WriteIntent s{var("r_trust"), at(f), 100};
    rep = w.apply(*n, 1, day0 + i, std::span(&s, 1));
    total = n->state.relation_records.find(f)->r_trust;
  }
  CHECK_EQ(total, 20);                                   // 4 decisions x 5, then the daily rate is spent
  CHECK(rep.outcomes[0].verdict.reason == Reason::clipped && !rep.outcomes[0].applied);
  WriteIntent s{var("r_trust"), at(f), 100};
  rep = w.apply(*n, 1, day0 + 86'400, std::span(&s, 1));   // the next game day
  CHECK_EQ(n->state.relation_records.find(f)->r_trust, 25);
}

TEST(at_most_four_writes_per_decision_one_per_target_and_variable) {
  Parties pa;
  auto n = adult();
  MindWriter w(&pa);
  std::vector<WriteIntent> in;
  for (const char* v : {"anger", "fear", "joy", "sadness", "pride", "shame"}) in.push_back({var(v), "self", 30});
  in.push_back({var("anger"), "self", 10});                // a duplicate
  const MindWriteReport rep = w.apply(*n, 1, 1000, in);
  CHECK_EQ(rep.kept, 4u);
  CHECK_EQ(rep.applied, 4u);
  CHECK(rep.outcomes[4].verdict.reason == Reason::too_many_writes);
  CHECK(rep.outcomes[5].verdict.reason == Reason::too_many_writes);
  CHECK(rep.outcomes[6].verdict.reason == Reason::duplicate);
  CHECK_EQ(n->state.mind_dynamic.shame, 0);
  CHECK_EQ(n->state.mind_dynamic.anger, 30);
}

TEST(an_invalid_target_neither_counts_nor_makes_a_later_write_a_duplicate) {
  Parties pa;
  auto n = adult();
  MindWriter w(&pa);
  std::vector<WriteIntent> in;
  for (int i = 0; i < 5; ++i) in.push_back({var("anger"), "b:" + std::to_string(90 + i), 30});   // none resolves
  for (const char* v : {"anger", "fear", "joy", "sadness"}) in.push_back({var(v), "self", 30});
  const MindWriteReport rep = w.apply(*n, 1, 1000, in);
  for (int i = 0; i < 5; ++i) CHECK(rep.outcomes[i].verdict.reason == Reason::invalid_value);
  CHECK_EQ(rep.kept, 4u);
  CHECK_EQ(rep.applied, 4u);
  CHECK_EQ(n->state.mind_dynamic.anger, 30);
  CHECK_EQ(n->state.mind_dynamic.sadness, 30);
}

TEST(engine_owned_and_ill_targeted_writes_are_refused) {
  Parties pa;
  auto n = adult();
  const MRef f = person(*n, 2);
  MindWriter w(&pa);
  WriteIntent in[3] = {{var("b_hops"), "b:1", 5}, {var("r_trust"), "self", 5}, {var("r_trust"), "@E99", 5}};
  const MindWriteReport rep = w.apply(*n, 1, 1000, in);
  CHECK(!rep.outcomes[0].verdict.allowed);
  CHECK(rep.outcomes[1].verdict.reason == Reason::invalid_value);   // a relation variable needs a pointer
  CHECK(rep.outcomes[2].verdict.reason == Reason::invalid_value);   // no such file
  CHECK_EQ(rep.applied, 0u);
  (void)f;
}

TEST(d10_refuses_a_rising_attraction_toward_a_possible_minor) {
  Parties pa;
  pa.m[2] = Party{300, 300, 300, true, true, true};   // an adult
  pa.m[3] = Party{120, 120, 120, true, true, true};   // a child
  auto n = adult();
  const MRef adult_f = person(*n, 2), child_f = person(*n, 3), name_only = person(*n, 2, 1);
  MindWriter w(&pa);
  WriteIntent in[3] = {{var("r_attraction"), at(child_f), 30}, {var("r_attraction"), at(name_only), 30}, {var("r_attraction"), at(adult_f), 30}};
  const MindWriteReport rep = w.apply(*n, 1, 1000, in);
  CHECK(rep.outcomes[0].verdict.reason == Reason::d10_intimate);
  CHECK(rep.outcomes[1].verdict.reason == Reason::d10_intimate);   // not resolved: refused by default
  CHECK(rep.outcomes[2].verdict.allowed);
  CHECK_EQ(n->state.relation_records.find(child_f)->r_attraction, 0);
  // the actor himself a child: his own intimate drive cannot rise
  Parties pc; pc.m[1] = Party{120, 120, 120, true, true, true};
  auto kid = std::make_unique<NpcBundle>();
  kid->state.body.alive = true;
  NpcLaws::set_age(kid->state, 120);
  MindWriter wc(&pc);
  WriteIntent up{var("need_intimacy"), "self", 40};
  CHECK(wc.apply(*kid, 1, 1000, std::span(&up, 1)).outcomes[0].verdict.reason == Reason::d10_intimate);
  CHECK_EQ(kid->state.mind_dynamic.need_intimacy, 0);
  // enforce_d10 is branched at the end of every application: a stray value is reset
  kid->state.mind_dynamic.need_intimacy = 30;
  WriteIntent other{var("anger"), "self", 10};
  const MindWriteReport r2 = wc.apply(*kid, 1, 1000, std::span(&other, 1));
  CHECK(r2.d10_reset);
  CHECK_EQ(kid->state.mind_dynamic.need_intimacy, 0);
}

TEST(a_belief_written_by_the_model_goes_through_check_record) {
  Parties pa; pa.m[1] = Party{300, 300, 300, true, true, true};
  pa.m[2] = Party{300, 300, 300, true, true, true};
  pa.m[3] = Party{120, 120, 120, true, true, true};
  auto n = adult();
  const MRef ok_f = person(*n, 2), child_f = person(*n, 3);
  MindWriter w(&pa);
  const RecordOutcome good = w.write_record(*n, 1, 1000, RecordKind::belief, "(dead " + at(ok_f) + ")");
  CHECK(good.verdict.allowed && good.ref.serial != 0);
  CHECK_EQ(n->state.belief_records.size(), 1);
  const RecordOutcome bad = w.write_record(*n, 1, 1000, RecordKind::belief, "(did " + at(child_f) + " touch " + at(ok_f) + " (how romantic))");
  CHECK(!bad.verdict.allowed && (bad.verdict.reason == Reason::d10_intimate || bad.verdict.reason == Reason::d10_value));
  CHECK_EQ(n->state.belief_records.size(), 1);
  CHECK(!w.write_record(*n, 1, 1000, RecordKind::plan, "(dead @E1)").verdict.allowed);
}

EMERGENCE_TEST_MAIN()
