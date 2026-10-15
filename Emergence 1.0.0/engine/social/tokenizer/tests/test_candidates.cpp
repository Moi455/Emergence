// CandidateSelector: bounded, deterministic, and blind to the objective fields of the state (D10 / no_truth_in_tokens).
#include <memory>

#include "emergence/social/tokenizer/candidates.h"
#include "emergence/testing/check.h"

using namespace em::social;
using namespace em::social::tok2;

namespace {

void fill(gen::NpcState& s, int beliefs, int memories, int persons, std::uint32_t poison) {
  for (int i = 0; i < beliefs; ++i) {
    gen::Belief b;
    b.b_importance = std::int16_t((i * 7) % 100);
    b.b_certainty = std::int16_t((i * 13) % 100);
    b.b_acquired = GameTime(i * 3600);
    b.b_truth = poison & 1;              // objective: must change nothing
    b.b_origin_fact = poison * 7 + EntityId(i);
    s.belief_records.add(b, [](const gen::Belief&) { return 0; });
  }
  for (int i = 0; i < memories; ++i) {
    gen::Episode m;
    m.m_importance = std::int16_t((i * 11) % 100);
    m.m_vividness = std::int16_t((i * 5) % 100);
    m.m_when = GameTime(i * 7200);
    m.m_fact_ref = poison * 3 + EntityId(i);
    s.episode_records.add(m, [](const gen::Episode&) { return 0; });
  }
  for (int i = 0; i < persons; ++i) {
    gen::Relation r;
    r.r_present = i % 3 == 0;
    r.r_familiarity = std::int16_t((i * 9) % 100);
    r.r_true_entity = poison * 5 + EntityId(i);
    s.relation_records.add(r, [](const gen::Relation&) { return 0; });
  }
}

}  // namespace

TEST(candidates_are_bounded_and_ordered) {
  auto s = std::make_unique<gen::NpcState>();
  fill(*s, 200, 100, 80, 0);
  Candidates c;
  CandidateSelector().select(*s, 1000000, c);
  CHECK_EQ(int(c.beliefs.size()), kMaxBeliefCandidates);
  CHECK_EQ(int(c.memories.size()), kMaxMemoryCandidates);
  CHECK_EQ(int(c.persons.size()), kMaxPersonCandidates);
  for (std::size_t i = 1; i < c.beliefs.size(); ++i) CHECK(c.beliefs[i - 1].salience >= c.beliefs[i].salience);
  CHECK(c.persons[0].salience >= 200);   // someone present comes first
}

TEST(candidates_ignore_objective_fields) {
  auto a = std::make_unique<gen::NpcState>(), b = std::make_unique<gen::NpcState>();
  fill(*a, 150, 90, 60, 0);
  fill(*b, 150, 90, 60, 0xABCDEF1);   // same mind, other truth
  Candidates ca, cb;
  CandidateSelector().select(*a, 500000, ca);
  CandidateSelector().select(*b, 500000, cb);
  bool same = ca.beliefs.size() == cb.beliefs.size() && ca.memories.size() == cb.memories.size() && ca.persons.size() == cb.persons.size();
  for (std::size_t i = 0; same && i < ca.beliefs.size(); ++i) same = ca.beliefs[i].ref == cb.beliefs[i].ref && ca.beliefs[i].salience == cb.beliefs[i].salience;
  for (std::size_t i = 0; same && i < ca.memories.size(); ++i) same = ca.memories[i].ref == cb.memories[i].ref;
  for (std::size_t i = 0; same && i < ca.persons.size(); ++i) same = ca.persons[i].ref == cb.persons[i].ref;
  CHECK(same);
}

TEST(candidates_small_state_keeps_everything) {
  auto s = std::make_unique<gen::NpcState>();
  fill(*s, 5, 0, 2, 0);
  Candidates c;
  CandidateSelector().select(*s, 0, c);
  CHECK_EQ(int(c.beliefs.size()), 5);
  CHECK_EQ(int(c.memories.size()), 0);
  CHECK_EQ(int(c.persons.size()), 2);
}

EMERGENCE_TEST_MAIN()
