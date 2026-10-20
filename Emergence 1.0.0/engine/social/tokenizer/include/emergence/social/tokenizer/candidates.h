// CandidateSelector (T28): the bounded lists of files the context selector may put in the dossier: 64 beliefs, 32
// memories, 24 persons (docs/10, docs/14 6.2). A simple salience, waiting for the learned "selector" head. It reads the
// NpcState ONLY through the views below, whose accessors exist for the variables that have a token in the catalogue
// (generated list gen::kTokenVars): no accessor to b_truth, b_origin_fact, m_fact_ref, r_true_entity, nor to any
// variable without a token. A test (tests/test_firewall.py) reads this file and the .cpp and fails on any other name.
// Deterministic: integers only; ties go to the most recent record (higher serial).
#pragma once
#include <array>
#include <cstdint>
#include <vector>

#include "emergence/social/npc_store.h"

namespace em::social::tok2 {

inline constexpr int kMaxBeliefCandidates = 64, kMaxMemoryCandidates = 32, kMaxPersonCandidates = 24, kMaxGroupCandidates = 8;

struct Candidate {
  MRef ref;                  // the NPC's own record (serial): the key of the dossier is b:<serial>, m:<serial>, @E<serial>
  std::int32_t salience;
};

struct Candidates {
  std::vector<Candidate> beliefs, memories, persons, groups;   // most salient first; at most 64, 32, 24, 8 (groups are files with a group kind)
  void clear() { beliefs.clear(); memories.clear(); persons.clear(); groups.clear(); }
};

class CandidateSelector {
 public:
  // `now`: game seconds. Reads nothing but the token views.
  void select(const em::social::gen::NpcState& npc, GameTime now, Candidates& out) const;
};

}  // namespace em::social::tok2
