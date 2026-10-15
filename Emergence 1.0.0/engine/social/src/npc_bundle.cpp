// NpcBundle: the proposition arena of one NPC and its law of forgetting (T06, docs/14 section 7.4).
#include "emergence/social/npc_state_codec.h"

namespace em::social {

namespace {

// One record that could be forgotten to free arena words.
struct Candidate {
  bool found = false;
  int pool = 0;             // 0 = belief, 1 = episode (the order breaks a tie between pools)
  MRef ref;
  std::int32_t score = 0;
  bool is_protected = false;
};

// `rank` is "lower score first, then lower serial, then the earlier pool".
bool better(const Candidate& a, const Candidate& b) {
  if (!b.found) return true;
  if (a.score != b.score) return a.score < b.score;
  if (a.ref.serial != b.ref.serial) return a.ref.serial < b.ref.serial;
  return a.pool < b.pool;
}

template <class Pool, class Prop>
void scan(Pool& pool, int index, Prop&& prop_of, GameTime now, Candidate& loose, Candidate& held) {
  pool.for_each([&](MRef r, auto& rec) {
    if (prop_of(rec) == 0) return;   // forgetting a record without proposition frees nothing
    const auto kind = gen::forgetting_kind(rec);
    Candidate c{true, index, r, gen::forgetting_score(kind, rec, now), gen::forgetting_protected(kind, rec)};
    Candidate& slot = c.is_protected ? held : loose;
    if (better(c, slot)) slot = c;
  });
}

}  // namespace

void NpcBundle::collect_propositions() {
  propositions.collect([&](auto&& visit) { for_each_prop_ref(visit); });
}

PropRef NpcBundle::store_proposition(const Proposition& p, GameTime now) {
  if (p.empty()) return 0;
  const auto size = static_cast<std::size_t>(p.size());
  if (!p.well_formed() || size > PropositionArena::kWords) { propositions.note_refused(); return 0; }
  if (PropRef r = propositions.put(p)) return r;
  collect_propositions();   // garbage first: records overwritten or forgotten since the last compaction
  for (;;) {
    if (PropRef r = propositions.put(p)) return r;
    Candidate loose, held;   // the worst unprotected record, and the worst protected one
    scan(state.belief_records, 0, [](const gen::Belief& b) { return b.b_proposition; }, now, loose, held);
    scan(state.episode_records, 1, [](const gen::Episode& e) { return e.m_content; }, now, loose, held);
    const Candidate& pick = loose.found ? loose : held;   // protected records only when every other one is gone
    if (!pick.found) break;
    if (pick.pool == 0) state.belief_records.forget(pick.ref, pick.is_protected);
    else state.episode_records.forget(pick.ref, pick.is_protected);
    propositions.note_reclaimed();
    collect_propositions();
  }
  propositions.note_refused();   // nothing left to forget: the proposition is not kept, and that is counted
  return 0;
}

}  // namespace em::social
