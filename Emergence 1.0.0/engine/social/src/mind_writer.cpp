#include "emergence/social/mind_writer.h"

#include <algorithm>
#include <cstring>

#include "pointer_util.h"

namespace em::social {

namespace {

const Parser& parser() {
  static const Parser p;
  return p;
}

constexpr std::uint8_t kSourceInferred = 4;   // index of `inferred` in the source list of language_core.toml
constexpr std::int16_t kNeutralImportance = 50;

// Where a variable lives: the field descriptor and the record (or flat component) that holds it.
struct Slot {
  unsigned char* base = nullptr;
  const gen::FieldDesc* field = nullptr;
  const gen::Relation* relation = nullptr;   // set when the holder is a relation (for the D10 other person)
};

std::string_view holder_of_pointer(std::string_view prefix) {
  if (prefix == "@E" || prefix == "@G") return "relation";
  if (prefix == "b:" || prefix == "h:") return "belief";
  if (prefix == "m:") return "episode";
  if (prefix == "g:") return "goal";
  return {};
}

bool locate(gen::NpcState& s, std::string_view holder, std::uint32_t serial, std::string_view var_id, Slot& out) {
  auto pick = [&](const gen::ComponentDesc& d, unsigned char* base) {
    for (const gen::FieldDesc& fd : d.fields)
      if (fd.name == var_id) { out.base = base; out.field = &fd; return; }
  };
  if (serial == 0) {
    gen::visit_components(s, [&](const gen::ComponentDesc& d, auto& c) {
      if (!out.base && d.name == holder) pick(d, reinterpret_cast<unsigned char*>(&c));
    });
  } else {
    gen::visit_pools(s, [&](const gen::ComponentDesc& d, auto& pool) {
      if (out.base || d.name != holder) return;
      if (auto* rec = pool.find(MRef{serial})) {
        pick(d, reinterpret_cast<unsigned char*>(rec));
        if constexpr (std::is_same_v<std::decay_t<decltype(*rec)>, gen::Relation>) out.relation = rec;
      }
    });
  }
  return out.base != nullptr;
}

}  // namespace

std::vector<PartyBinding> PartyBindings::view() const {
  std::vector<PartyBinding> v;
  v.reserve(symbols.size());
  for (std::size_t i = 0; i < symbols.size(); ++i) v.push_back({symbols[i], &parties[i]});
  return v;
}

MindView::MindView(const NpcBundle& mind, EntityId self, const PartySource* parties) : mind_(&mind), self_(self), parties_(parties) {}

const TypedExpression* MindView::frozen_copy(std::string_view ref) const {
  for (auto& c : copies_)
    if (c.first == ref) return c.second ? &*c.second : nullptr;
  std::string_view pre; std::uint32_t n = 0;
  std::optional<TypedExpression> out;
  if (detail::parse_pointer(ref, pre, n) && n != 0) {
    auto& st = const_cast<NpcBundle*>(mind_)->state;   // read only: RecordPool::find is not const
    PropRef pr = 0;
    if (pre == "b:" || pre == "h:") { if (auto* r = st.belief_records.find(MRef{n})) pr = r->b_proposition; }
    else if (pre == "m:") { if (auto* r = st.episode_records.find(MRef{n})) pr = r->m_content; }
    else if (pre == "g:") { if (auto* r = st.goal_records.find(MRef{n})) pr = r->g_desired; }
    else if (pre == "q:") { if (auto* r = st.request_records.find(MRef{n})) pr = r->q_content; }
    if (pr) {
      const std::string text = Parser::to_text(mind_->propositions.get(pr));
      if (!text.empty()) {
        TypedExpression e = parser().parse(text, {.bare = true});
        if (e.ok()) out = std::move(e);
      }
    }
  }
  copies_.emplace_back(std::string(ref), std::move(out));
  return copies_.back().second ? &*copies_.back().second : nullptr;
}

RecordLookup MindView::lookup() const {
  return [this](std::string_view ref) { return frozen_copy(ref); };
}

Party MindView::file_party(std::uint32_t serial) const {
  auto& st = const_cast<NpcBundle*>(mind_)->state;
  const gen::Relation* r = st.relation_records.find(MRef{serial});
  if (!r || !parties_ || r->r_true_entity == 0) return Party{};
  Party p = parties_->party_seen_by(self_, r->r_true_entity);
  p.resolved = p.resolved && r->r_known_by == 0;   // known by name only or described: not resolved
  return p;
}

Party MindView::self_party() const { return parties_ ? parties_->party_seen_by(self_, self_) : Party{}; }

void MindView::bind_pointers(std::string_view text, PartyBindings& out, int depth) const {
  detail::for_each_token(text, [&](std::string_view tok) {
    std::string_view pre; std::uint32_t n;
    if (!detail::parse_pointer(tok, pre, n)) return;
    if (pre == "@E") {
      if (std::find(out.symbols.begin(), out.symbols.end(), tok) != out.symbols.end()) return;
      const gen::Relation* r = const_cast<NpcBundle*>(mind_)->state.relation_records.find(MRef{n});
      if (!r || r->r_true_entity == 0 || !parties_) return;   // unbound: an unknown person (a possible minor)
      out.symbols.emplace_back(tok);
      out.parties.push_back(file_party(n));
    } else if (detail::is_cite(tok) && depth < 3) {
      if (const TypedExpression* c = frozen_copy(tok)) bind_pointers(c->canonical_text(), out, depth + 1);
    }
  });
}

MindWriteReport MindWriter::apply(NpcBundle& mind, EntityId self, GameTime now, std::span<const WriteIntent> intents) const {
  MindWriteReport rep;
  rep.outcomes.resize(intents.size());
  gen::NpcState& st = mind.state;
  const std::int32_t age = NpcLaws::real_age_tenths(st);
  mind.ledger.roll(static_cast<std::int32_t>(now / WorldClock::kGameSecondsPerDay), age / 10);
  const Party actor = Party{static_cast<std::int16_t>(std::clamp(age, 0, 32000)), static_cast<std::int16_t>(std::clamp(age, 0, 32000)),
                            static_cast<std::int16_t>(std::clamp(age, 0, 32000)), true, true, true};
  MindView view(mind, self, parties_);

  struct Resolved { Slot slot; std::uint32_t serial = 0; bool ok = false; };
  std::vector<Resolved> res(intents.size());
  std::vector<WriteKey> keys(intents.size());
  for (std::size_t i = 0; i < intents.size(); ++i) {
    const WriteIntent& w = intents[i];
    rep.outcomes[i].var = w.var;
    rep.outcomes[i].target = w.target;
    std::uint32_t serial = 0;
    std::string_view holder;
    const std::size_t vi = static_cast<std::size_t>(w.var);
    if (vi < gen::kVariables.size()) {
      holder = gen::kVariables[vi].holder;
      if (w.target != "self") {
        std::string_view pre; std::uint32_t n;
        if (detail::parse_pointer(w.target, pre, n) && holder_of_pointer(pre) == holder) serial = n;
        else holder = {};
      } else if (gen::kVariables[vi].holder == "belief" || gen::kVariables[vi].holder == "relation" ||
                 gen::kVariables[vi].holder == "goal" || gen::kVariables[vi].holder == "episode") {
        holder = {};   // a record variable needs a pointer
      }
    }
    keys[i] = {serial, w.var};
    res[i].serial = serial;
    if (!holder.empty() && (serial != 0 || w.target == "self")) res[i].ok = locate(st, holder, serial, gen::kVarNames[vi], res[i].slot);
  }
  // An intent whose target does not resolve is refused alone: it has no key, does not count among the 4 and cannot make
  // a later write of the same variable a duplicate.
  std::vector<std::size_t> valid;
  std::vector<WriteKey> vkeys;
  for (std::size_t i = 0; i < intents.size(); ++i)
    if (res[i].ok) { valid.push_back(i); vkeys.push_back(keys[i]); }
  std::vector<Verdict> vkept(valid.size());
  rep.kept = Governor().check_writes(vkeys, vkept);
  std::vector<Verdict> kept(intents.size(), Verdict{false, 0, Reason::invalid_value});
  for (std::size_t j = 0; j < valid.size(); ++j) kept[valid[j]] = vkept[j];
  for (std::size_t i = 0; i < intents.size(); ++i) {
    WriteOutcome& o = rep.outcomes[i];
    if (!kept[i].allowed) { o.verdict = kept[i]; continue; }
    const Resolved& r = res[i];
    if (r.slot.field->type != gen::ColType::I16) { o.verdict = {false, 0, Reason::structured}; continue; }
    std::int16_t old = 0;
    std::memcpy(&old, r.slot.base + r.slot.field->offset, sizeof old);
    WriteRequest rq;
    rq.var = intents[i].var;
    rq.old_value = old;
    rq.proposed = intents[i].value;
    rq.target = r.serial;
    rq.actor = &actor;
    Party other;
    if (r.slot.relation) {
      other = view.file_party(r.serial);
      rq.intimate_target = &other;
    }
    o.old_value = old;
    o.verdict = governor_.check_write(rq, mind.ledger);
    o.new_value = old;
    if (o.verdict.allowed) {
      o.new_value = o.verdict.value;
      std::memcpy(r.slot.base + r.slot.field->offset, &o.new_value, sizeof o.new_value);
      o.applied = o.new_value != old;
      rep.applied += o.applied;
    }
  }
  rep.d10_reset = NpcLaws::enforce_d10(st);
  return rep;
}

RecordOutcome MindWriter::write_record(NpcBundle& mind, EntityId self, GameTime now, RecordKind kind, std::string_view expression) const {
  RecordOutcome out;
  if (kind != RecordKind::belief && kind != RecordKind::goal && kind != RecordKind::memory) {
    out.verdict = {false, 0, Reason::invalid_value};
    return out;
  }
  const TypedExpression e = parser().parse(expression, {.bare = true});
  MindView view(mind, self, parties_);
  PartyBindings pb;
  view.bind_pointers(e.canonical_text(), pb);
  const std::vector<PartyBinding> bindings = pb.view();
  Party me = view.self_party();
  if (!parties_) {
    const std::int32_t age = NpcLaws::real_age_tenths(mind.state);
    me = Party{static_cast<std::int16_t>(std::clamp(age, 0, 32000)), static_cast<std::int16_t>(std::clamp(age, 0, 32000)),
               static_cast<std::int16_t>(std::clamp(age, 0, 32000)), true, true, true};
  }
  out.verdict = governor_.check_record(kind, e, &me, bindings, view.lookup());
  if (!out.verdict.allowed) return out;
  Proposition prop;
  if (e.to_proposition(prop) != ConvertStatus::ok) { out.verdict = {false, 0, Reason::invalid_value}; return out; }
  const PropRef ref = mind.store_proposition(prop, now);
  if (ref == 0) { out.verdict = {false, 0, Reason::ledger_full}; return out; }
  if (kind == RecordKind::belief) {
    gen::Belief b;
    b.b_proposition = ref; b.b_polarity = true; b.b_certainty = 50; b.b_importance = kNeutralImportance;
    b.b_source = kSourceInferred; b.b_acquired = now; b.b_confirmed = now;
    out.ref = mind.state.belief_records.add(b, now);
  } else if (kind == RecordKind::goal) {
    gen::Goal g;
    g.g_desired = ref; g.g_since = now;
    out.ref = mind.state.goal_records.add(g, now);
  } else {
    gen::Episode m;
    m.m_content = ref; m.m_when = now;
    out.ref = mind.state.episode_records.add(m, now);
  }
  return out;
}

}  // namespace em::social
