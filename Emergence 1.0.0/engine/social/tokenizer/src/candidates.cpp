#include "emergence/social/tokenizer/candidates.h"

#include <algorithm>
#include <climits>
#include <cstdlib>

namespace em::social::tok2 {
namespace {

// A field the NPC does not know is stored with an in-band marker (context_builder.h, namespace unknown): it weighs nothing.
std::int32_t known(std::int16_t v) { return v == INT16_MIN ? 0 : v; }
GameTime known(PackedTime t) { const GameTime g = t; return g == INT64_MIN ? 0 : g; }

// ---- the token views: one accessor per variable that has a token (tenths of the charter scale, game seconds)
class BeliefView {
 public:
  explicit BeliefView(const gen::Belief& b) : b_(b) {}
  int certainty() const { return known(b_.b_certainty); }      // BELIEF.certainty
  int importance() const { return known(b_.b_importance); }    // BELIEF.importance
  bool contradicted() const { return b_.b_contradicted; }   // BELIEF.contradicted
  GameTime acquired() const { return known(b_.b_acquired); }   // BELIEF.age
 private:
  const gen::Belief& b_;
};
class MemoryView {
 public:
  explicit MemoryView(const gen::Episode& m) : m_(m) {}
  int importance() const { return known(m_.m_importance); }    // MEMORY.importance
  int vividness() const { return known(m_.m_vividness); }      // MEMORY.vividness
  int valence() const { return known(m_.m_valence); }          // MEMORY.valence
  bool defining() const { return m_.m_defining; }       // MEMORY.defining
  GameTime when() const { return known(m_.m_when); }           // MEMORY.age
 private:
  const gen::Episode& m_;
};
class PersonView {
 public:
  explicit PersonView(const gen::Relation& r) : r_(r) {}
  bool present() const { return r_.r_present; }              // ENTITY.present
  int familiarity() const { return known(r_.r_familiarity); }       // ENTITY.rel.familiarity
  int affection() const { return known(r_.r_affection); }           // ENTITY.rel.affection
  int fear() const { return known(r_.r_fear); }                     // ENTITY.rel.fear
  int resentment() const { return known(r_.r_resentment); }         // ENTITY.rel.resentment
  int trust() const { return known(r_.r_trust); }                   // ENTITY.rel.trust
  bool is_group() const { return r_.r_group_kind != 0 && r_.r_group_kind != 0xFFFF; }   // GROUP.kind: a file of a group
 private:
  const gen::Relation& r_;
};

std::int32_t recency(GameTime now, GameTime then) {   // 100 now, 50 after a game day, towards 0
  const std::int64_t age = std::max<std::int64_t>(0, now - then);
  return std::int32_t(100 * 86400 / (86400 + age));
}

void keep_best(std::vector<Candidate>& v, std::size_t cap) {
  const auto better = [](const Candidate& a, const Candidate& b) {
    return a.salience != b.salience ? a.salience > b.salience : a.ref.serial > b.ref.serial;
  };
  if (v.size() > cap) {
    std::nth_element(v.begin(), v.begin() + std::ptrdiff_t(cap), v.end(), better);
    v.resize(cap);
  }
  std::sort(v.begin(), v.end(), better);
}

}  // namespace

void CandidateSelector::select(const gen::NpcState& npc, GameTime now, Candidates& out) const {
  out.clear();
  const auto& bp = npc.belief_records;
  for (int i = 0; i < bp.kCapacity; ++i) {
    if (!bp.slot_used(i)) continue;
    const BeliefView b(bp.slot_record(i));
    std::int32_t s = 3 * b.importance() + 2 * b.certainty() + recency(now, b.acquired());
    if (b.contradicted()) s -= 100;
    out.beliefs.push_back({MRef{bp.slot_serial(i)}, s});
  }
  const auto& mp = npc.episode_records;
  for (int i = 0; i < mp.kCapacity; ++i) {
    if (!mp.slot_used(i)) continue;
    const MemoryView m(mp.slot_record(i));
    std::int32_t s = 3 * m.importance() + 2 * m.vividness() + std::abs(m.valence()) + recency(now, m.when());
    if (m.defining()) s += 50;
    out.memories.push_back({MRef{mp.slot_serial(i)}, s});
  }
  const auto& rp = npc.relation_records;
  for (int i = 0; i < rp.kCapacity; ++i) {
    if (!rp.slot_used(i)) continue;
    const PersonView p(rp.slot_record(i));
    if (p.is_group()) {
      const std::int32_t g = (p.present() ? 200 : 0) + std::abs(p.affection()) + p.fear() + p.resentment() + std::abs(p.trust());
      out.groups.push_back({MRef{rp.slot_serial(i)}, g});
      continue;
    }
    std::int32_t s = (p.present() ? 200 : 0) + 2 * p.familiarity() + std::abs(p.affection()) + p.fear() + p.resentment();
    out.persons.push_back({MRef{rp.slot_serial(i)}, s});
  }
  keep_best(out.beliefs, kMaxBeliefCandidates);
  keep_best(out.memories, kMaxMemoryCandidates);
  keep_best(out.persons, kMaxPersonCandidates);
  keep_best(out.groups, kMaxGroupCandidates);
}

}  // namespace em::social::tok2
