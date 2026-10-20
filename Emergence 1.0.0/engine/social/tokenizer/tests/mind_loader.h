// The reverse loader of the T28b tests: the dossiers of a decision (a DecisionContext of the oracle, quantised to the grid of
// the state) -> an NpcBundle (state, side table, proposition arena), the perception links, the wake and the selection the
// oracle made. It is TEST CODE: the engine never turns dossiers into a state. It writes the conventions of context_builder.h.
//
// What cannot be put in the state is counted, with the reason, in LoadedMind::lost (never silently dropped).
#pragma once
#include <algorithm>
#include <cmath>
#include <cstring>
#include <map>
#include <memory>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <vector>

#include "context_map_gen.h"
#include "emergence/social/catalogue_gen.h"
#include "emergence/social/language.h"
#include "emergence/social/npc_fields_gen.h"
#include "emergence/social/tokenizer/context_builder.h"
#include "emergence/social/vocab_gen.h"
#include "tok2_gen.h"

namespace em::social::tok2::testing {
namespace tgen = em::social::tok2::gen;
namespace sgen = em::social::gen;

struct LoadedMind {
  std::unique_ptr<NpcBundle> bundle;
  std::vector<FileLink> links;
  WakeInput wake;
  Selection selection;
  GameTime now = 0;
  std::vector<std::string> lost;     // what the state could not hold, with the reason
};

class MindLoader {
 public:
  explicit MindLoader(const Tokenizer& tk) : tk_(tk) {
    auto dummy = std::make_unique<sgen::NpcState>();
    int h = 0;
    const auto reg = [&](const sgen::ComponentDesc& d, auto&) {
      for (const sgen::FieldDesc& f : d.fields) vars_.emplace(f.name, Var{h, &f});
      ++h;
    };
    sgen::visit_components(*dummy, reg);
    sgen::visit_pools(*dummy, reg);
    lvar_.resize(std::size_t(tgen::kNumTypes));
    for (int ti = 0; ti < tgen::kNumTypes; ++ti) lvar_[std::size_t(ti)].resize(std::size_t(tgen::kTypes[ti].col_n));
    const auto bind = [&](const tgen::SourceDef& r, bool only_plan) {
      if (r.var.empty()) return;
      const int ti = tk_.type_index(r.type), col = tk_.column(ti, r.field);
      if (ti < 0 || col < 0) return;
      if (only_plan && !(r.field == "progress" || r.field == "commitment" || r.field == "goal")) return;
      const auto it = vars_.find(r.var);
      if (it != vars_.end()) lvar_[std::size_t(ti)][std::size_t(col)] = it->second;
    };
    for (const auto& r : tgen::kSources) bind(r, false);
    for (const auto& r : tgen::kDerivedSources) bind(r, true);
    for (std::size_t i = 0; i < sgen::kWords.size(); ++i) words_.emplace(sgen::kWords[i], std::uint32_t(i));
    for (std::size_t i = 0; i < sgen::kKinds.size(); ++i) words_.emplace(sgen::kKinds[i], std::uint32_t(sgen::kWords.size() + i));
  }

  bool load(const DecisionContext& ctx, GameTime now, bool stubs, LoadedMind& L) const {
    L.bundle = std::make_unique<NpcBundle>();
    L.now = now;
    L.lost.clear();
    L.links.clear();
    L.selection.clear();
    L.wake = WakeInput{};
    NpcBundle& B = *L.bundle;
    sgen::NpcState& st = B.state;
    Ctx c{L, B, now, {}, {}};
    sgen::visit_components(st, [&](const sgen::ComponentDesc& d, auto& comp) { mark_unknown(reinterpret_cast<unsigned char*>(&comp), d); });
    for (const Record& r : ctx.records) {
      c.type_of[r.key] = r.type;
      if (r.type == "INV") c.inv_keys.insert(r.key);
    }
    std::vector<std::uint32_t> inv_words, commit_words, heard_words, taste_words;
    int slot[kHolders] = {};
    std::uint32_t max_serial[kHolders] = {};
    for (const Record& r : ctx.records) {
      const std::uint32_t n = key_number(r.key);
      const std::string& t = r.type;
      if (t == "SELF" || t == "SELF_MIND" || t == "SELF_STATE") {
        for (const Field& f : r.fields) {
          if (f.value.is_null()) continue;
          const Var& v = lvar_[std::size_t(r.type_index)][std::size_t(f.col)];
          if (!v.fd) { c.lose(r, f, "no variable"); continue; }
          write(c, flat_base(st, v.holder), v, tk_.column_def(r.type_index, f.col), f.value, r, f);
        }
      } else if (t == "ENTITY" || t == "GROUP") {
        const bool group = t == "GROUP";
        sgen::Relation rel{};
        sgen::EntityPercept ep{};
        mark_unknown(reinterpret_cast<unsigned char*>(&rel), sgen::kRelationDesc);
        mark_unknown(reinterpret_cast<unsigned char*>(&ep), sgen::kEntityPerceptDesc);
        bool present = false;
        for (const Field& f : r.fields) {
          if (f.value.is_null()) continue;
          const Var& v = lvar_[std::size_t(r.type_index)][std::size_t(f.col)];
          if (!v.fd) { c.lose(r, f, "no variable"); continue; }
          unsigned char* base = v.holder == kRelation ? reinterpret_cast<unsigned char*>(&rel) : reinterpret_cast<unsigned char*>(&ep);
          write(c, base, v, tk_.column_def(r.type_index, f.col), f.value, r, f);
          if (tk_.column_def(r.type_index, f.col).name == "present" && f.value.is_bool()) present = f.value.as_bool();
        }
        const std::uint32_t serial = group ? (n | 0x800000u) : n;
        add(st.relation_records, slot[kRelation], serial, rel, max_serial[kRelation], c, r);
        if (group) {
          L.selection.groups.push_back(serial);
        } else {
          Selection::Person p{serial, 0};
          if (present) {
            add(st.entity_percept_records, slot[kEntityPercept], n, ep, max_serial[kEntityPercept], c, r);
            L.links.push_back({n, make_ref(RefKind::entity, serial)});
            p.percept = n;
          }
          L.selection.persons.push_back(p);
        }
      } else if (t == "THING") {
        sgen::Percept p{};
        mark_unknown(reinterpret_cast<unsigned char*>(&p), sgen::kPerceptDesc);
        fill_record(c, r, reinterpret_cast<unsigned char*>(&p));
        add(st.percept_records, slot[kPercept], n, p, max_serial[kPercept], c, r);
        L.selection.things.push_back(n);
      } else if (t == "INV") {
        sgen::Percept p{};
        mark_unknown(reinterpret_cast<unsigned char*>(&p), sgen::kPerceptDesc);
        fill_record(c, r, reinterpret_cast<unsigned char*>(&p));
        const auto wide = [](std::uint32_t v, std::uint32_t marker) { return v == marker ? unknown::kRef : v; };
        const std::uint32_t x[kInvStride] = {n, wide(p.pc_kind_seen, unknown::kU16), wide(p.pc_color_seen, unknown::kU16),
                                              wide(p.pc_age_seen, unknown::kU16), wide(p.pc_amount_seen, unknown::kU8),
                                              wide(p.pc_depth_seen, unknown::kU8), p.pc_owner_believed.serial, p.pc_props_seen,
                                              p.pc_state_seen,
                                              p.pc_file_certainty == unknown::kI16 ? unknown::kRef : std::uint32_t(std::int32_t(p.pc_file_certainty))};
        inv_words.insert(inv_words.end(), x, x + kInvStride);
        L.selection.inv.push_back(int(L.selection.inv.size()));
      } else if (t == "LOCUS") {
        sgen::Locus p{};
        mark_unknown(reinterpret_cast<unsigned char*>(&p), sgen::kLocusDesc);
        fill_record(c, r, reinterpret_cast<unsigned char*>(&p));
        add(st.locus_records, slot[kLocus], n, p, max_serial[kLocus], c, r);
        L.selection.locus.push_back(n);
      } else if (t == "PLACE") {
        sgen::PlacePercept p{};
        mark_unknown(reinterpret_cast<unsigned char*>(&p), sgen::kPlacePerceptDesc);
        fill_record(c, r, reinterpret_cast<unsigned char*>(&p));
        add(st.place_percept_records, slot[kPlacePercept], 1, p, max_serial[kPlacePercept], c, r);
      } else if (t == "BELIEF" || t == "HEARD") {
        sgen::Belief p{};
        mark_unknown(reinterpret_cast<unsigned char*>(&p), sgen::kBeliefDesc);
        fill_record(c, r, reinterpret_cast<unsigned char*>(&p));
        const std::uint32_t serial = t == "HEARD" ? 100000u + n : n;
        add(st.belief_records, slot[kBelief], serial, p, max_serial[kBelief], c, r);
        if (t == "HEARD") { heard_words.push_back(n); heard_words.push_back(serial); L.selection.heard.push_back(n); }
        else L.selection.beliefs.push_back(n);
      } else if (t == "MEMORY") {
        sgen::Episode p{};
        mark_unknown(reinterpret_cast<unsigned char*>(&p), sgen::kEpisodeDesc);
        fill_record(c, r, reinterpret_cast<unsigned char*>(&p));
        add(st.episode_records, slot[kEpisode], n, p, max_serial[kEpisode], c, r);
        L.selection.memories.push_back(n);
      } else if (t == "GOAL") {
        sgen::Goal p{};
        mark_unknown(reinterpret_cast<unsigned char*>(&p), sgen::kGoalDesc);
        fill_record(c, r, reinterpret_cast<unsigned char*>(&p));
        add(st.goal_records, slot[kGoal], n, p, max_serial[kGoal], c, r);
        L.selection.goals.push_back(n);
      } else if (t == "PLAN") {
        load_plan(c, r, n, slot[kIntention], max_serial[kIntention]);
        L.selection.plans.push_back(n);
      } else if (t == "REQUEST") {
        sgen::Request p{};
        mark_unknown(reinterpret_cast<unsigned char*>(&p), sgen::kRequestDesc);
        fill_record(c, r, reinterpret_cast<unsigned char*>(&p));
        add(st.request_records, slot[kRequest], n, p, max_serial[kRequest], c, r);
        L.selection.requests.push_back(n);
      } else if (t == "SKILL") {
        sgen::Skill p{};
        mark_unknown(reinterpret_cast<unsigned char*>(&p), sgen::kSkillDesc);
        fill_record(c, r, reinterpret_cast<unsigned char*>(&p));
        add(st.skill_records, slot[kSkill], n, p, max_serial[kSkill], c, r);
        L.selection.skills.push_back(n);
      } else if (t == "EVENT") {
        sgen::EventSeen p{};
        mark_unknown(reinterpret_cast<unsigned char*>(&p), sgen::kEventSeenDesc);
        fill_record(c, r, reinterpret_cast<unsigned char*>(&p));
        add(st.event_seen_records, slot[kEventSeen], n, p, max_serial[kEventSeen], c, r);
        L.selection.events.push_back(n);
      } else if (t == "COMMIT") {
        load_commit(c, r, n, commit_words);
        L.selection.commits.push_back(int(L.selection.commits.size()));
      } else if (t == "TASTE") {
        std::uint32_t concept_id = unknown::kRef;
        std::int32_t att = unknown::kI32;
        for (const Field& f : r.fields) {
          const std::string_view fn = tk_.column_def(r.type_index, f.col).name;
          if (fn == "concept" && f.value.is_string()) concept_id = word_id(f.value.as_string(), c, r, f);
          if (fn == "attitude" && f.value.is_number()) att = std::int32_t(std::llround(f.value.as_number() * 10.0));
        }
        taste_words.push_back(concept_id);
        taste_words.push_back(std::uint32_t(att));
        L.selection.tastes.push_back(int(L.selection.tastes.size()));
      } else if (t == "WAKE") {
        load_wake(c, r);
      }
    }
    put_list(c, st.beliefs.inv_seen, inv_words, "inv_seen");
    put_list(c, st.goals.commitments_seen, commit_words, "commitments_seen");
    put_list(c, st.beliefs.heard_unprocessed, heard_words, "heard_unprocessed");
    put_list(c, st.mind_static.tastes, taste_words, "tastes");
    // the files the oracle's mind knows and the dossier did not carry (ghost targets): stubs, so that they exist as files
    if (stubs) {
      for (const std::string& k : ctx.known_keys) {
        if (c.type_of.count(k) || k.rfind("@E", 0) != 0) continue;
        sgen::Relation rel{};
        mark_unknown(reinterpret_cast<unsigned char*>(&rel), sgen::kRelationDesc);
        rel.r_present = false;
        add(st.relation_records, slot[kRelation], key_number(k), rel, max_serial[kRelation], c, Record{});
      }
    }
    restore(st.belief_records, max_serial[kBelief]);
    restore(st.entity_percept_records, max_serial[kEntityPercept]);
    restore(st.episode_records, max_serial[kEpisode]);
    restore(st.event_seen_records, max_serial[kEventSeen]);
    restore(st.goal_records, max_serial[kGoal]);
    restore(st.intention_records, max_serial[kIntention]);
    restore(st.locus_records, max_serial[kLocus]);
    restore(st.percept_records, max_serial[kPercept]);
    restore(st.place_percept_records, max_serial[kPlacePercept]);
    restore(st.relation_records, max_serial[kRelation]);
    restore(st.request_records, max_serial[kRequest]);
    restore(st.skill_records, max_serial[kSkill]);
    return true;
  }

 private:
  using Holder = int;
  enum : int {
    kMindStatic, kMindDynamic, kBody, kNeeds, kLifecycle, kCarrier, kActivity, kBeliefs, kRelations, kMemory, kGoals,
    kBelief, kEntityPercept, kEpisode, kEventSeen, kGoal, kIntention, kLocus, kPercept, kPlacePercept, kRelation, kRequest,
    kSkill, kHolders
  };
  struct Var {
    int holder = -1;
    const sgen::FieldDesc* fd = nullptr;
  };
  struct Ctx {
    LoadedMind& L;
    NpcBundle& B;
    GameTime now;
    std::unordered_map<std::string, std::string> type_of;
    std::unordered_set<std::string> inv_keys;
    void lose(const Record& r, const Field& f, const std::string& why) {
      const std::string fn = f.col >= 0 ? "col" + std::to_string(f.col) : f.name;
      L.lost.push_back(r.type + "." + fn + ": " + why);
    }
  };

  static unsigned char* flat_base(sgen::NpcState& st, int h) {
    switch (h) {
      case kMindStatic: return reinterpret_cast<unsigned char*>(&st.mind_static);
      case kMindDynamic: return reinterpret_cast<unsigned char*>(&st.mind_dynamic);
      case kBody: return reinterpret_cast<unsigned char*>(&st.body);
      case kNeeds: return reinterpret_cast<unsigned char*>(&st.needs);
      case kLifecycle: return reinterpret_cast<unsigned char*>(&st.lifecycle);
      case kCarrier: return reinterpret_cast<unsigned char*>(&st.carrier);
      case kActivity: return reinterpret_cast<unsigned char*>(&st.activity);
      case kBeliefs: return reinterpret_cast<unsigned char*>(&st.beliefs);
      case kRelations: return reinterpret_cast<unsigned char*>(&st.relations);
      case kMemory: return reinterpret_cast<unsigned char*>(&st.memory);
      case kGoals: return reinterpret_cast<unsigned char*>(&st.goals);
      default: return nullptr;
    }
  }

  static void mark_unknown(unsigned char* base, const sgen::ComponentDesc& d) {
    for (const sgen::FieldDesc& f : d.fields) {
      unsigned char* p = base + f.offset;
      switch (f.type) {
        case sgen::ColType::I16: { const std::int16_t v = unknown::kI16; std::memcpy(p, &v, 2); break; }
        case sgen::ColType::I32: { const std::int32_t v = unknown::kI32; std::memcpy(p, &v, 4); break; }
        case sgen::ColType::U8: *p = unknown::kU8; break;
        case sgen::ColType::U16: { const std::uint16_t v = unknown::kU16; std::memcpy(p, &v, 2); break; }
        case sgen::ColType::Time: { const PackedTime v(unknown::kTime); std::memcpy(p, &v, sizeof v); break; }
        case sgen::ColType::MRef: case sgen::ColType::List: case sgen::ColType::Prop: {
          const std::uint32_t v = unknown::kRef; std::memcpy(p, &v, 4); break;
        }
        default: break;
      }
    }
  }

  static std::uint32_t key_number(const std::string& key) {
    std::size_t i = 0;
    while (i < key.size() && !(key[i] >= '0' && key[i] <= '9')) ++i;
    return i < key.size() ? std::uint32_t(std::stoul(key.substr(i))) : 0;
  }

  template <class Pool, class Rec>
  void add(Pool& pool, int& slot, std::uint32_t serial, const Rec& rec, std::uint32_t& max_serial, Ctx& c, const Record& r) const {
    if (!pool.restore_slot(slot, serial, rec)) { c.L.lost.push_back(r.type + " " + r.key + ": pool full or serial reused"); return; }
    ++slot;
    max_serial = std::max(max_serial, serial);
  }
  template <class Pool>
  static void restore(Pool& pool, std::uint32_t max_serial) { pool.restore_counters(max_serial, 0, 0); }

  void put_list(Ctx& c, ListRef& dst, const std::vector<std::uint32_t>& items, const char* what) const {
    if (items.empty()) return;     // the marker stays: unknown (an absent list)
    dst = c.B.side.put(items);
    if (dst == 0) c.L.lost.push_back(std::string(what) + ": side table full");
  }

  std::uint32_t word_id(const std::string& s, Ctx& c, const Record& r, const Field& f) const {
    if (s.empty()) return 0;
    const auto it = words_.find(s);
    if (it == words_.end()) { c.lose(r, f, "word '" + s + "' is not a symbol of the state"); return unknown::kRef; }
    return it->second;
  }

  // key -> tagged MRef
  MRef ref_of(const std::string& key, Ctx& c) const {
    if (key.empty()) return MRef{0};
    if (key == "me") return make_ref(RefKind::self, 0);
    if (key == "@PLACE") return make_ref(RefKind::place, 0);
    const std::uint32_t n = key_number(key);
    if (key.rfind("@E", 0) == 0) return make_ref(RefKind::entity, n);
    if (key.rfind("@T", 0) == 0) return make_ref(c.inv_keys.count(key) ? RefKind::inv : RefKind::thing, n);
    if (key.rfind("@G", 0) == 0) return make_ref(RefKind::group, n);
    if (key.rfind("@L", 0) == 0) return make_ref(RefKind::locus, n);
    if (key.rfind("@V", 0) == 0) return make_ref(RefKind::event, n);
    if (key.rfind("b:", 0) == 0) return make_ref(RefKind::belief, n);
    if (key.rfind("m:", 0) == 0) return make_ref(RefKind::memory, n);
    if (key.rfind("g:", 0) == 0) return make_ref(RefKind::goal, n);
    if (key.rfind("h:", 0) == 0) return make_ref(RefKind::heard, n);
    if (key.rfind("q:", 0) == 0) return make_ref(RefKind::request, n);
    if (key.rfind("c:", 0) == 0) return make_ref(RefKind::commit, n);
    if (key.rfind("p:", 0) == 0) return make_ref(RefKind::plan, n);
    return kUnknownRef;
  }

  static void set_i16(unsigned char* p, std::int64_t v) { const std::int16_t x = std::int16_t(v); std::memcpy(p, &x, 2); }
  static void set_i32(unsigned char* p, std::int64_t v) { const std::int32_t x = std::int32_t(v); std::memcpy(p, &x, 4); }
  static void set_u32(unsigned char* p, std::uint32_t v) { std::memcpy(p, &v, 4); }
  static void set_time(unsigned char* p, GameTime v) { const PackedTime x(v); std::memcpy(p, &x, sizeof x); }

  void fill_record(Ctx& c, const Record& r, unsigned char* base) const {
    for (const Field& f : r.fields) {
      if (f.value.is_null()) continue;          // unknown: the marker stays
      const Var& v = lvar_[std::size_t(r.type_index)][std::size_t(f.col)];
      if (!v.fd) { c.lose(r, f, "no variable"); continue; }
      write(c, base, v, tk_.column_def(r.type_index, f.col), f.value, r, f);
    }
  }

  // The vector components of an object, in the list format of context_builder.h.
  void encode_object(const ColumnDef& cd, const Value& d, std::vector<std::uint32_t>& items, Ctx& c, const Record& r, const Field& f) const {
    for (const auto& [name, val] : d.members()) {
      int comp = -1;
      for (int i = 0; i < cd.comp_n; ++i) if (tgen::kComponents[cd.comp_at + i].name == name) comp = i;
      if (comp < 0) { c.lose(r, f, "unknown component " + name); continue; }
      const Component& cc = tgen::kComponents[cd.comp_at + comp];
      if (cc.scale == NumScale::boolean) {
        const auto it = words_.find(name);
        if (val.as_bool() && it != words_.end() && it->second < sgen::kWords.size()) { items.push_back(it->second); continue; }
        items.push_back(kValuedItem | std::uint32_t(comp));
        items.push_back(val.as_bool() ? 1u : 0u);
      } else {
        items.push_back(kValuedItem | std::uint32_t(comp));
        items.push_back(std::uint32_t(std::int32_t(std::llround(val.as_number() * 1000.0))));
      }
    }
  }

  void write(Ctx& c, unsigned char* base, const Var& v, const ColumnDef& cd, const Value& val, const Record& r, const Field& f) const {
    unsigned char* p = base + v.fd->offset;
    const sgen::ColType ft = v.fd->type;
    switch (cd.codec) {
      case Codec::scalar: {
        const double x = val.is_bool() ? (val.as_bool() ? 1.0 : 0.0) : val.as_number();
        switch (cd.scale) {
          case NumScale::boolean: *p = x != 0; return;
          case NumScale::bipolar10: case NumScale::unipolar10: set_i16(p, std::llround(x * 10.0)); return;
          case NumScale::ratio: case NumScale::unit: set_i16(p, std::llround(x * 1000.0)); return;
          case NumScale::qty: case NumScale::qty_signed: set_i32(p, std::llround(x * 1000.0)); return;
          case NumScale::time: set_time(p, c.now - std::llround(x * 3600.0)); return;
          case NumScale::time_until: set_time(p, c.now + std::llround(x * 3600.0)); return;
        }
        return;
      }
      case Codec::symbol: {
        const std::string& s = val.as_string();
        if (cd.is_enum) {
          for (int i = 0; i < cd.values_n; ++i)
            if (tgen::kStrings[tgen::kStringStart[cd.values_at] + i] == s) { *p = std::uint8_t(i); return; }
          c.lose(r, f, "enum value " + s);
          return;
        }
        std::uint16_t id = 0;
        if (var_is(v, "r_name_believed")) id = std::uint16_t(key_number(s));
        else if (var_is(v, "ev_gesture")) {
          id = unknown::kU16;
          for (std::size_t i = 0; i < sgen::kGestureNames.size(); ++i) if (sgen::kGestureNames[i] == s) id = std::uint16_t(i);
        } else {
          const std::uint32_t w = word_id(s, c, r, f);
          id = w > 0xFFFE ? unknown::kU16 : std::uint16_t(w);
        }
        std::memcpy(p, &id, 2);
        return;
      }
      case Codec::bag: {
        std::vector<std::uint32_t> items;
        for (const Value& it : val.items()) {
          if (cd.is_enum) {
            for (int i = 0; i < cd.values_n; ++i) if (tgen::kStrings[tgen::kStringStart[cd.values_at] + i] == it.as_string()) items.push_back(std::uint32_t(i));
          } else {
            items.push_back(word_id(it.as_string(), c, r, f));
          }
        }
        set_u32(p, items.empty() ? 0 : list_put(c, items, r, f));
        return;
      }
      case Codec::pointer: set_u32(p, ref_of(val.as_string(), c).serial); return;
      case Codec::pointer_list: {
        std::vector<std::uint32_t> items;
        for (const Value& it : val.items()) items.push_back(ref_of(it.as_string(), c).serial);
        set_u32(p, items.empty() ? 0 : list_put(c, items, r, f));
        return;
      }
      case Codec::proposition: {
        ParseOptions opt;
        opt.bare = !cd.utterance;
        const TypedExpression e = parser_.parse(val.as_string(), opt);
        Proposition prop;
        if (!e.ok() || e.to_proposition(prop) != ConvertStatus::ok) { c.lose(r, f, "proposition not accepted by the parser: " + val.as_string()); return; }
        const PropRef ref = c.B.propositions.put(prop);
        if (ref == 0) { c.lose(r, f, "proposition arena full"); return; }
        set_u32(p, ref);
        return;
      }
      case Codec::vector: {
        if (ft == sgen::ColType::I32) {
          const auto get = [&](int i) { const Value* m = val.find(tgen::kComponents[cd.comp_at + i].name); return m && m->is_number() ? std::llround(m->as_number() * 1000.0) : 0ll; };
          if (cd.comp_n == 2) {
            set_i32(p, std::int32_t((std::uint32_t(std::uint16_t(std::int16_t(get(0)))) << 16) | std::uint16_t(std::int16_t(get(1)))));
          } else if (cd.comp_n == 3) {
            const std::uint32_t u = (std::uint32_t(get(2)) & 0x3FF) << 22 | (std::uint32_t(get(0)) & 0x7FF) << 11 | (std::uint32_t(get(1)) & 0x7FF);
            set_i32(p, std::int32_t(u));
          }
          return;
        }
        std::vector<std::uint32_t> items;
        if (cd.multi) {
          for (const Value& obj : val.items()) { encode_object(cd, obj, items, c, r, f); items.push_back(kObjectEnd); }
          if (!val.items().empty() && items.size() == 1) {}      // an empty object: just the end marker
        } else {
          encode_object(cd, val, items, c, r, f);
        }
        set_u32(p, items.empty() ? 0 : list_put(c, items, r, f));
        return;
      }
    }
  }

  std::uint32_t list_put(Ctx& c, const std::vector<std::uint32_t>& items, const Record& r, const Field& f) const {
    const ListRef ref = c.B.side.put(items);
    if (ref == 0) { c.lose(r, f, "side table full"); return unknown::kRef; }
    return ref;
  }
  static bool var_is(const Var& v, std::string_view name) { return v.fd->name == name; }

  void load_plan(Ctx& c, const Record& r, std::uint32_t n, int& slot, std::uint32_t& max_serial) const {
    sgen::Intention p{};
    mark_unknown(reinterpret_cast<unsigned char*>(&p), sgen::kIntentionDesc);
    const Value *step = nullptr, *next = nullptr, *target = nullptr, *steps = nullptr, *targets = nullptr;
    for (const Field& f : r.fields) {
      if (f.value.is_null()) continue;
      const std::string_view fn = tk_.column_def(r.type_index, f.col).name;
      if (fn == "step") { step = &f.value; continue; }
      if (fn == "next") { next = &f.value; continue; }
      if (fn == "target") { target = &f.value; continue; }
      if (fn == "steps") steps = &f.value;
      if (fn == "step_targets") targets = &f.value;
      const Var& v = lvar_[std::size_t(r.type_index)][std::size_t(f.col)];
      if (!v.fd) { c.lose(r, f, "no variable"); continue; }
      write(c, reinterpret_cast<unsigned char*>(&p), v, tk_.column_def(r.type_index, f.col), f.value, r, f);
    }
    if (steps && step && next) {
      const auto& s = steps->items();
      long k = -1;
      for (std::size_t i = 0; i < s.size(); ++i) {
        const std::string want_next = i + 1 < s.size() ? s[i + 1].as_string() : std::string();
        if (s[i].as_string() == step->as_string() && want_next == next->as_string()) { k = long(i); break; }
      }
      if (k < 0) c.L.lost.push_back("PLAN " + r.key + ": step/next are not consecutive steps");
      else set_i32(reinterpret_cast<unsigned char*>(&p) + indexed("i_step_index"), k * 1000);
    }
    if (target) {
      const MRef t = ref_of(target->as_string(), c);
      std::vector<std::uint32_t> items;
      items.push_back(kPlanTargetHeader | t.serial);
      if (targets) for (const Value& it : targets->items()) items.push_back(ref_of(it.as_string(), c).serial);
      const ListRef ref = c.B.side.put(items);
      if (ref == 0) c.L.lost.push_back("PLAN " + r.key + ": side table full");
      std::memcpy(reinterpret_cast<unsigned char*>(&p) + indexed("i_step_targets"), &ref, 4);
      if (!targets) c.L.lost.push_back("PLAN " + r.key + ": a target without step_targets");
    }
    add(c.B.state.intention_records, slot, n, p, max_serial, c, r);
  }
  std::size_t indexed(std::string_view name) const { return vars_.at(name).fd->offset; }

  void load_commit(Ctx& c, const Record& r, std::uint32_t n, std::vector<std::uint32_t>& words) const {
    std::uint32_t w[kCommitStride];
    for (std::uint32_t& x : w) x = unknown::kRef;
    w[0] = n;
    w[5] = w[7] = 0; w[6] = w[8] = 0x80000000u;   // INT64_MIN: lo = 0, hi = 0x80000000
    w[5] = 0; w[7] = 0;
    for (const Field& f : r.fields) {
      if (f.value.is_null()) continue;
      const ColumnDef& cd = tk_.column_def(r.type_index, f.col);
      const std::string_view fn = cd.name;
      const Value& v = f.value;
      if (fn == "counterparty") w[2] = ref_of(v.as_string(), c).serial;
      else if (fn == "mine") w[3] = v.as_bool() ? 1 : 0;
      else if (fn == "prop") {
        const TypedExpression e = parser_.parse(v.as_string(), ParseOptions{.bare = true});
        Proposition prop;
        if (!e.ok() || e.to_proposition(prop) != ConvertStatus::ok) { c.lose(r, f, "proposition not accepted by the parser"); continue; }
        const PropRef ref = c.B.propositions.put(prop);
        if (ref == 0) c.lose(r, f, "proposition arena full"); else w[1] = ref;
      } else if (fn == "status") {
        for (int i = 0; i < cd.values_n; ++i) if (tgen::kStrings[tgen::kStringStart[cd.values_at] + i] == v.as_string()) w[4] = std::uint32_t(i);
      } else if (fn == "deadline" || fn == "when") {
        const GameTime t = c.now + std::llround(v.as_number() * 3600.0);
        const int base = fn == "deadline" ? 5 : 7;
        w[base] = std::uint32_t(std::uint64_t(t)); w[base + 1] = std::uint32_t(std::uint64_t(t) >> 32);
      } else if (fn == "witnesses") {
        std::vector<std::uint32_t> items;
        for (const Value& it : v.items()) items.push_back(ref_of(it.as_string(), c).serial);
        w[9] = items.empty() ? 0 : list_put(c, items, r, f);
      }
    }
    // deadline and when unknown: INT64_MIN
    bool has_deadline = false, has_when = false;
    for (const Field& f : r.fields) {
      const std::string_view fn = tk_.column_def(r.type_index, f.col).name;
      has_deadline = has_deadline || fn == "deadline";
      has_when = has_when || fn == "when";
    }
    if (!has_deadline) { w[5] = 0; w[6] = 0x80000000u; }
    if (!has_when) { w[7] = 0; w[8] = 0x80000000u; }
    words.insert(words.end(), w, w + kCommitStride);
  }

  void load_wake(Ctx& c, const Record& r) const {
    WakeInput& w = c.L.wake;
    for (const Field& f : r.fields) {
      const ColumnDef& cd = tk_.column_def(r.type_index, f.col);
      const std::string_view fn = cd.name;
      const Value& v = f.value;
      const auto idx = [&] {
        for (int i = 0; i < cd.values_n; ++i) if (tgen::kStrings[tgen::kStringStart[cd.values_at] + i] == v.as_string()) return i;
        return -1;
      };
      if (fn == "mode") w.mode = WakeMode(idx());
      else if (fn == "cause") w.cause = WakeCause(idx());
      else if (fn == "trigger") w.trigger = ref_of(v.as_string(), c);
      else if (fn == "urgency") w.urgency_tenths = int(std::llround(v.as_number() * 10.0));
      else if (fn == "budget") w.budget = int(std::llround(v.as_number()));
      else if (fn == "temperament") w.temperament_tenths = int(std::llround(v.as_number() * 10.0));
      else if (fn == "outcome") w.outcome = WakeOutcome(idx());
    }
  }

  const Tokenizer& tk_;
  Parser parser_;
  std::unordered_map<std::string_view, Var> vars_;
  std::vector<std::vector<Var>> lvar_;
  std::unordered_map<std::string_view, std::uint32_t> words_;
};

}  // namespace em::social::tok2::testing
