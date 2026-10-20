#include "emergence/social/tokenizer/context_builder.h"

#include <algorithm>
#include <cmath>
#include <cstring>
#include <unordered_map>

#include "context_map_gen.h"
#include "emergence/social/catalogue_gen.h"
#include "emergence/social/language.h"
#include "emergence/social/npc_fields_gen.h"
#include "emergence/social/vocab_gen.h"
#include "tok2_gen.h"

namespace em::social::tok2 {
namespace tgen = em::social::tok2::gen;
namespace sgen = em::social::gen;

namespace {

// ---- the holders: where a variable lives in the NpcState (components, then pools, in the order of gen::visit_*)
enum Holder : int {
  kMindStatic, kMindDynamic, kBody, kNeeds, kLifecycle, kCarrier, kActivity, kBeliefs, kRelations, kMemory, kGoals,
  kBelief, kEntityPercept, kEpisode, kEventSeen, kGoal, kIntention, kLocus, kPercept, kPlacePercept, kRelation, kRequest,
  kSkill, kHolders
};

struct VarRef {
  int holder = -1;
  const sgen::FieldDesc* fd = nullptr;
  explicit operator bool() const { return fd != nullptr; }
};

std::int64_t read_raw(const sgen::FieldDesc& f, const unsigned char* base) {
  const unsigned char* p = base + f.offset;
  switch (f.type) {
    case sgen::ColType::Bool: case sgen::ColType::U8: return *p;
    case sgen::ColType::U16: { std::uint16_t v; std::memcpy(&v, p, 2); return v; }
    case sgen::ColType::I16: { std::int16_t v; std::memcpy(&v, p, 2); return v; }
    case sgen::ColType::I32: { std::int32_t v; std::memcpy(&v, p, 4); return v; }
    case sgen::ColType::Time: { PackedTime v; std::memcpy(&v, p, sizeof v); return GameTime(v); }
    case sgen::ColType::Entity: case sgen::ColType::List: case sgen::ColType::MRef: case sgen::ColType::Prop: {
      std::uint32_t v; std::memcpy(&v, p, 4); return v;
    }
  }
  return 0;
}

bool is_unknown(const sgen::FieldDesc& f, std::int64_t v) {
  switch (f.type) {
    case sgen::ColType::I16: return v == unknown::kI16;
    case sgen::ColType::I32: return v == unknown::kI32;
    case sgen::ColType::U8: return v == unknown::kU8;
    case sgen::ColType::U16: return v == unknown::kU16;
    case sgen::ColType::Time: return v == unknown::kTime;
    case sgen::ColType::List: case sgen::ColType::MRef: case sgen::ColType::Prop: return v == std::int64_t(unknown::kRef);
    default: return false;
  }
}

constexpr std::uint32_t kKeyMask = 0x7FFFFFu;   // bit 23 of a file serial only keeps a group apart from a person in the pool

template <class Pool>
const typename Pool::value_type* find_rec(const Pool& pool, std::uint32_t serial) {
  if (serial == 0) return nullptr;
  for (int i = 0; i < Pool::kCapacity; ++i)
    if (pool.slot_serial(i) == serial) return &pool.slot_record(i);
  return nullptr;
}

// A word id of the state: an index in kWords, then in kKinds. 0 is "none".
std::string_view word_text(std::uint32_t id) {
  if (id < sgen::kWords.size()) return sgen::kWords[id];
  const std::size_t k = id - sgen::kWords.size();
  return k < sgen::kKinds.size() ? sgen::kKinds[k] : std::string_view();
}

const char* ref_prefix(RefKind k) {
  switch (k) {
    case RefKind::entity: return "@E";
    case RefKind::thing: case RefKind::inv: return "@T";
    case RefKind::group: return "@G";
    case RefKind::locus: return "@L";
    case RefKind::event: return "@V";
    case RefKind::belief: return "b:";
    case RefKind::memory: return "m:";
    case RefKind::goal: return "g:";
    case RefKind::heard: return "h:";
    case RefKind::request: return "q:";
    case RefKind::commit: return "c:";
    case RefKind::plan: return "p:";
    default: return "";
  }
}

std::string make_key(const char* prefix, std::uint32_t n) {
  std::string k(prefix);
  k += std::to_string(n);
  return k;
}

constexpr double kQtyMax = 10000000.0;

}  // namespace

void Selection::clear() {
  beliefs.clear(); heard.clear(); memories.clear(); goals.clear(); plans.clear(); requests.clear(); events.clear();
  things.clear(); locus.clear(); groups.clear(); skills.clear(); persons.clear(); inv.clear(); commits.clear(); tastes.clear();
}

// =====================================================================================================================
struct ContextBuilder::Impl {
  struct ColBind {
    int col = 0;
    const ColumnDef* cd = nullptr;
    VarRef v;
    bool look = false;          // ENTITY dist, dir, look.*: carried only by a person who is present
    bool sparse_true = false;   // emitted only when true (b_unintelligible)
    bool name = false;          // r_name_believed: a name number, not a word
    bool gesture = false;       // ev_gesture: an index of the gesture registry
  };
  struct TypeBind {
    int ti = -1;
    std::vector<ColBind> cols;
  };
  struct Cx {
    const MindSource& src;
    const NpcBundle& m;
    BuildStats& st;
    std::vector<std::string>& cited;
  };

  explicit Impl(const Tokenizer& tk_) : tk(tk_) {
    // the table var -> (holder, descriptor), from the generated descriptors of the state
    auto dummy = std::make_unique<sgen::NpcState>();
    int h = 0;
    const auto reg = [&](const sgen::ComponentDesc& d, auto&) {
      for (const sgen::FieldDesc& f : d.fields) vars.emplace(f.name, VarRef{h, &f});
      ++h;
    };
    sgen::visit_components(*dummy, reg);
    sgen::visit_pools(*dummy, reg);

    const auto bind_rows = [&](const tgen::SourceDef* rows, std::size_t n, bool derived) {
      for (std::size_t i = 0; i < n; ++i) {
        const auto& r = rows[i];
        if (r.var.empty()) continue;
        const int ti = tk.type_index(r.type);
        const int col = tk.column(ti, r.field);
        if (ti < 0 || col < 0) continue;
        const auto it = vars.find(r.var);
        ColBind cb;
        cb.col = col;
        cb.cd = &tk.column_def(ti, col);
        if (it != vars.end()) cb.v = it->second;
        cb.look = (r.type == "ENTITY") && (r.field == "dist" || r.field == "dir" || r.field.substr(0, 5) == "look.");
        cb.sparse_true = r.var == "b_unintelligible";
        cb.name = r.var == "r_name_believed";
        cb.gesture = r.var == "ev_gesture";
        auto& tb = types[std::size_t(ti)];
        tb.ti = ti;
        if (derived) derived_cols[{ti, col}] = cb; else tb.cols.push_back(cb);
      }
    };
    types.resize(std::size_t(tgen::kNumTypes));
    bind_rows(tgen::kSources, std::size(tgen::kSources), false);
    bind_rows(tgen::kDerivedSources, std::size(tgen::kDerivedSources), true);
    // PLAN.progress, commitment and goal are plain fields of the intention: generic columns
    for (auto it = derived_cols.begin(); it != derived_cols.end();) {
      const auto& [key, cb] = *it;
      const std::string_view f = tk.column_def(key.first, key.second).name;
      if (tk.type_def(key.first).name == "PLAN" && (f == "progress" || f == "commitment" || f == "goal")) {
        types[std::size_t(key.first)].cols.push_back(cb);
        it = derived_cols.erase(it);
      } else {
        ++it;
      }
    }
    ti_belief = tk.type_index("BELIEF"); ti_commit = tk.type_index("COMMIT"); ti_entity = tk.type_index("ENTITY");
    ti_event = tk.type_index("EVENT"); ti_goal = tk.type_index("GOAL"); ti_group = tk.type_index("GROUP");
    ti_heard = tk.type_index("HEARD"); ti_inv = tk.type_index("INV"); ti_locus = tk.type_index("LOCUS");
    ti_memory = tk.type_index("MEMORY"); ti_place = tk.type_index("PLACE"); ti_plan = tk.type_index("PLAN");
    ti_request = tk.type_index("REQUEST"); ti_self = tk.type_index("SELF"); ti_self_mind = tk.type_index("SELF_MIND");
    ti_self_state = tk.type_index("SELF_STATE"); ti_skill = tk.type_index("SKILL"); ti_taste = tk.type_index("TASTE");
    ti_thing = tk.type_index("THING"); ti_wake = tk.type_index("WAKE");
    // kinds of record -> token type id (for the ref_types masks)
    const char* names[] = {"", "ENTITY", "THING", "INV", "GROUP", "LOCUS", "EVENT", "BELIEF", "MEMORY", "GOAL", "HEARD", "REQUEST",
                           "COMMIT", "PLAN", "SELF", "PLACE"};
    for (int k = 1; k < int(RefKind::kCount); ++k) kind_type_id[k] = tk.type_def(tk.type_index(names[k])).id;
    for (int k = 1; k < int(RefKind::kCount); ++k) type_id_kind[kind_type_id[k]] = RefKind(k);
    // columns of the derived and special records
    const auto col = [&](int ti, const char* f) { return tk.column(ti, f); };
    plan_step = col(ti_plan, "step"); plan_next = col(ti_plan, "next"); plan_target = col(ti_plan, "target");
    wake_mode = col(ti_wake, "mode"); wake_cause = col(ti_wake, "cause"); wake_trigger = col(ti_wake, "trigger");
    wake_urgency = col(ti_wake, "urgency"); wake_budget = col(ti_wake, "budget"); wake_temperament = col(ti_wake, "temperament");
    wake_outcome = col(ti_wake, "outcome");
    entity_present = col(ti_entity, "present");
    // state variables read by the selection (all have a token)
    for (const char* n : {"b_proposition", "m_content", "g_desired", "q_content", "g_status", "g_priority", "i_status", "i_commitment",
                          "q_since", "k_self_estimate", "pc_dist", "lc_dist", "ev_age", "r_present", "i_steps", "i_step_index",
                          "i_step_targets", "heard_unprocessed", "inv_seen", "commitments_seen", "tastes", "g_deadline"}) {
      const auto it = vars.find(n);
      if (it != vars.end()) sel_vars.emplace(n, it->second);
    }
    goal_active = enum_index(ti_goal, "status", "active");
    plan_running = enum_index(ti_plan, "status", "running");
    plan_blocked = enum_index(ti_plan, "status", "blocked");
    plan_suspended = enum_index(ti_plan, "status", "suspended");
    commit_status_col = col(ti_commit, "status");
  }

  int enum_index(int ti, const char* field, const char* value) const {
    const ColumnDef& cd = tk.column_def(ti, tk.column(ti, field));
    for (int i = 0; i < cd.values_n; ++i)
      if (tgen::kStrings[tgen::kStringStart[cd.values_at] + i] == value) return i;
    return -1;
  }

  // ---- kinds and keys
  // The kind a pointer designates: its tag, or the first kind the field accepts.
  RefKind kind_of(MRef r, const ColumnDef* cd) const {
    RefKind k = ref_kind(r);
    if (k == RefKind::kCount) return k;
    if (k == RefKind::none && cd && cd->ref_types) {
      for (int id = 1; id <= tgen::kMaxTypeId; ++id)
        if ((cd->ref_types >> id) & 1) { const RefKind c = type_id_kind[id]; if (c != RefKind::none) return c; }
    }
    return k;
  }
  // false: unknown or unusable. key "" : nobody.
  bool ref_key(MRef r, const ColumnDef* cd, Cx& cx, std::string& key) const {
    if (r.serial == unknown::kRef) return false;
    if (r.serial == 0) { key.clear(); return true; }
    const RefKind k = kind_of(r, cd);
    if (k == RefKind::none || k >= RefKind::kCount) return false;
    if (cd && cd->ref_types && !((cd->ref_types >> kind_type_id[int(k)]) & 1)) { ++cx.st.dropped_pointers; return false; }
    if (k == RefKind::self) { key = "me"; return true; }
    if (k == RefKind::place) { key = "@PLACE"; cx.cited.emplace_back(key); return true; }
    if (ref_serial(r) == 0) return false;
    key = make_key(ref_prefix(k), ref_serial(r) & kKeyMask);
    if (cx.cited.empty() || cx.cited.back() != key) cx.cited.push_back(key);
    return true;
  }

  // ---- conversions
  static double clamp_to(double x, double lo, double hi, Cx& cx) {
    if (x < lo) { ++cx.st.clamped; return lo; }
    if (x > hi) { ++cx.st.clamped; return hi; }
    return x;
  }
  bool number_of(NumScale ns, const sgen::FieldDesc& fd, std::int64_t raw, Cx& cx, double& x) const {
    switch (ns) {
      case NumScale::boolean: x = raw != 0; return true;
      case NumScale::bipolar10: x = clamp_to(double(raw) / 10.0, -10.0, 10.0, cx); return true;
      case NumScale::unipolar10: x = clamp_to(double(raw) / 10.0, 0.0, 10.0, cx); return true;
      case NumScale::ratio: x = clamp_to(double(raw) / 1000.0, 0.0, 1.0, cx); return true;
      case NumScale::unit: x = clamp_to(double(raw) / 1000.0, -1.0, 1.0, cx); return true;
      case NumScale::qty: x = clamp_to(double(raw) / 1000.0, 0.0, kQtyMax, cx); return true;
      case NumScale::qty_signed: x = clamp_to(double(raw) / 1000.0, -kQtyMax, kQtyMax, cx); return true;
      case NumScale::time: {
        const std::int64_t d = fd.type == sgen::ColType::Time ? cx.src.now - raw : raw;
        x = clamp_to(double(std::max<std::int64_t>(0, d)) / 3600.0, 0.0, kQtyMax, cx);
        return true;
      }
      case NumScale::time_until: {
        const std::int64_t d = fd.type == sgen::ColType::Time ? raw - cx.src.now : raw;
        x = clamp_to(double(d) / 3600.0, -kQtyMax, kQtyMax, cx);
        return true;
      }
    }
    return false;
  }
  static bool in_words(const ColumnDef& cd, std::string_view s) {
    if (cd.words_n == 0) return true;
    for (int i = 0; i < cd.words_n; ++i)
      if (tgen::kStrings[tgen::kStringStart[cd.words_at] + i] == s) return true;
    return false;
  }
  static int comp_index(const ColumnDef& cd, std::string_view name) {
    for (int i = 0; i < cd.comp_n; ++i)
      if (tgen::kComponents[cd.comp_at + i].name == name) return i;
    return -1;
  }
  double comp_value(const Component& c, std::int64_t milli, Cx& cx) const {
    const double x = double(milli) / 1000.0;
    switch (c.scale) {
      case NumScale::unit: return clamp_to(x, -1.0, 1.0, cx);
      case NumScale::ratio: return clamp_to(x, 0.0, 1.0, cx);
      case NumScale::bipolar10: return clamp_to(x, -10.0, 10.0, cx);
      case NumScale::unipolar10: return clamp_to(x, 0.0, 10.0, cx);
      case NumScale::qty_signed: return clamp_to(x, -kQtyMax, kQtyMax, cx);
      default: return clamp_to(x, 0.0, kQtyMax, cx);
    }
  }
  static void set_member(Value& dict, std::string_view name, Value v) {
    for (auto& m : dict.members())
      if (m.first == name) { m.second = std::move(v); return; }
    dict.members().emplace_back(std::string(name), std::move(v));
  }
  // One object of a list of vector components, from items[i] up to the next object end.
  void decode_object(std::span<const std::uint32_t> items, std::size_t& i, const ColumnDef& cd, Value& dict, Cx& cx) const {
    while (i < items.size()) {
      const std::uint32_t it = items[i++];
      if (it == kObjectEnd) return;
      if (it & kValuedItem) {
        const int c = int(it & 0x7F);
        if (i >= items.size()) return;
        const std::int32_t milli = std::int32_t(items[i++]);
        if (c >= cd.comp_n) continue;
        const Component& comp = tgen::kComponents[cd.comp_at + c];
        set_member(dict, comp.name, comp.scale == NumScale::boolean ? Value::boolean(milli != 0) : Value::number(comp_value(comp, milli, cx)));
      } else {
        const std::string_view w = word_text(it);
        const int c = comp_index(cd, w);
        if (c >= 0 && tgen::kComponents[cd.comp_at + c].scale == NumScale::boolean) set_member(dict, w, Value::boolean(true));
      }
    }
  }
  static int sext(std::uint32_t v, int bits) { const std::uint32_t m = 1u << (bits - 1); return int((v ^ m) - m); }

  bool value_of(const ColBind& cb, const unsigned char* base, Cx& cx, Value& out) const {
    const ColumnDef& cd = *cb.cd;
    const sgen::FieldDesc& fd = *cb.v.fd;
    const std::int64_t raw = read_raw(fd, base);
    if (is_unknown(fd, raw)) return false;
    const SideTable& side = cx.m.side;
    switch (cd.codec) {
      case Codec::scalar: {
        double x = 0;
        if (!number_of(cd.scale, fd, raw, cx, x)) return false;
        out = cd.scale == NumScale::boolean ? Value::boolean(raw != 0) : Value::number(x);
        return true;
      }
      case Codec::symbol: {
        if (cd.is_enum) {
          if (raw < 0 || raw >= cd.values_n) return false;
          out = Value::string(std::string(tgen::kStrings[tgen::kStringStart[cd.values_at] + raw]));
          return true;
        }
        if (cb.name) { out = Value::string("n:" + std::to_string(raw)); return true; }
        if (cb.gesture) {
          if (raw < 0 || raw >= std::int64_t(sgen::kGestureNames.size())) return false;
          out = Value::string(std::string(sgen::kGestureNames[std::size_t(raw)]));
          return true;
        }
        if (raw == 0) { out = Value::string(std::string()); return true; }
        const std::string_view w = word_text(std::uint32_t(raw));
        if (w.empty() || !in_words(cd, w)) return false;
        out = Value::string(std::string(w));
        return true;
      }
      case Codec::bag: {
        Value list = Value::list();
        for (const std::uint32_t it : side.get(ListRef(raw))) {
          if (int(list.items().size()) >= 6) break;
          if (cd.is_enum) {
            if (int(it) >= cd.values_n) continue;
            list.items().push_back(Value::string(std::string(tgen::kStrings[tgen::kStringStart[cd.values_at] + it])));
          } else {
            const std::string_view w = word_text(it);        // in a list 0 is the first word, not "none"
            if (w.empty() || !in_words(cd, w)) continue;
            list.items().push_back(Value::string(std::string(w)));
          }
        }
        out = std::move(list);
        return true;
      }
      case Codec::pointer: {
        std::string key;
        if (!ref_key(MRef{std::uint32_t(raw)}, &cd, cx, key)) return false;
        out = Value::string(std::move(key));
        return true;
      }
      case Codec::pointer_list: {
        Value list = Value::list();
        std::string key;
        for (const std::uint32_t it : side.get(ListRef(raw))) {
          if (int(list.items().size()) >= 4) break;
          if (it == 0 || !ref_key(MRef{it}, &cd, cx, key) || key.empty()) continue;
          list.items().push_back(Value::string(key));
        }
        out = std::move(list);
        return true;
      }
      case Codec::proposition: {
        if (raw == 0) return false;
        std::string text;
        if (!proposition_text(PropRef(raw), cx, text)) return false;
        out = Value::string(std::move(text));
        return true;
      }
      case Codec::vector: {
        if (fd.type == sgen::ColType::I32) {     // a packed direction (sin, cos) or a felt time (sin, cos, certainty)
          const std::uint32_t u = std::uint32_t(raw);
          Value d = Value::dict();
          if (cd.comp_n == 2) {
            d.members().emplace_back(std::string(tgen::kComponents[cd.comp_at].name), Value::number(double(std::int16_t(u >> 16)) / 1000.0));
            d.members().emplace_back(std::string(tgen::kComponents[cd.comp_at + 1].name), Value::number(double(std::int16_t(u & 0xFFFF)) / 1000.0));
          } else if (cd.comp_n == 3) {
            d.members().emplace_back(std::string(tgen::kComponents[cd.comp_at].name), Value::number(double(sext((u >> 11) & 0x7FF, 11)) / 1000.0));
            d.members().emplace_back(std::string(tgen::kComponents[cd.comp_at + 1].name), Value::number(double(sext(u & 0x7FF, 11)) / 1000.0));
            d.members().emplace_back(std::string(tgen::kComponents[cd.comp_at + 2].name), Value::number(clamp_to(double((u >> 22) & 0x3FF) / 1000.0, 0.0, 1.0, cx)));
          } else {
            return false;
          }
          out = std::move(d);
          return true;
        }
        const std::span<const std::uint32_t> items = side.get(ListRef(raw));
        if (cd.multi) {
          Value list = Value::list();
          std::size_t i = 0;
          while (i < items.size()) {
            Value obj = Value::dict();
            decode_object(items, i, cd, obj, cx);
            list.items().push_back(std::move(obj));
          }
          out = std::move(list);
          return true;
        }
        if (items.empty()) return false;
        Value d = Value::dict();
        std::size_t i = 0;
        decode_object(items, i, cd, d, cx);
        out = std::move(d);
        return true;
      }
    }
    return false;
  }

  // The text of a proposition of the arena; cites its pointers (they may be ghosts).
  bool proposition_text(PropRef ref, Cx& cx, std::string& text) const {
    const Proposition p = cx.m.propositions.get(ref);
    if (p.empty()) return false;
    text = Parser::to_text(p);
    if (text.empty()) return false;
    for (int i = 0; i < p.size(); ++i) {
      const std::uint32_t s = p.symbol(i);
      if (Proposition::tag(s) != Proposition::kRef) continue;
      const std::uint32_t code = Proposition::value(s) >> 20, num = Proposition::value(s) & 0xFFFFF;
      if (code == 0 || code > std::uint32_t(tgen::kNumPointerKinds) || code == 6) continue;   // @PLACE is always carried
      std::string key = make_key(tgen::kPointerKinds[code - 1], num);
      if (cx.cited.empty() || cx.cited.back() != key) cx.cited.push_back(std::move(key));
    }
    return true;
  }

  // ---- records
  void fill(Record& r, const TypeBind& tb, const unsigned char* const* bases, Cx& cx, bool skip_look) const {
    for (const ColBind& cb : tb.cols) {
      if (!cb.v) continue;
      const unsigned char* base = bases[cb.v.holder];
      if (!base || (skip_look && cb.look)) continue;
      if (cb.sparse_true && read_raw(*cb.v.fd, base) == 0) continue;
      Field f;
      f.col = cb.col;
      if (value_of(cb, base, cx, f.value)) r.fields.push_back(std::move(f));
    }
  }
  Record& add(DecisionContext& out, int ti, std::string key) const {
    out.records.emplace_back();
    Record& r = out.records.back();
    r.type = std::string(tgen::kTypes[ti].name);
    r.type_index = ti;
    r.key = std::move(key);
    return r;
  }
  static void put(Record& r, int col, Value v) {
    Field f;
    f.col = col;
    f.value = std::move(v);
    r.fields.push_back(std::move(f));
  }

  // ---- the selection helpers
  std::int64_t sel_raw(const char* name, const unsigned char* base) const {
    const auto it = sel_vars.find(name);
    return it == sel_vars.end() ? 0 : read_raw(*it->second.fd, base);
  }
  static std::int32_t known16(std::int64_t v) { return v == unknown::kI16 ? 0 : std::int32_t(v); }
  bool prop_ok(const NpcBundle& m, std::uint32_t ref) const { return ref != 0 && ref != unknown::kRef && m.propositions.length(ref) > 0; }

  const Tokenizer& tk;
  std::unordered_map<std::string_view, VarRef> vars;
  std::unordered_map<std::string_view, VarRef> sel_vars;
  std::vector<TypeBind> types;
  struct PairHash { std::size_t operator()(const std::pair<int, int>& p) const { return std::size_t(p.first) * 1000003u + std::size_t(p.second); } };
  std::unordered_map<std::pair<int, int>, ColBind, PairHash> derived_cols;
  int ti_belief = -1, ti_commit = -1, ti_entity = -1, ti_event = -1, ti_goal = -1, ti_group = -1, ti_heard = -1, ti_inv = -1,
      ti_locus = -1, ti_memory = -1, ti_place = -1, ti_plan = -1, ti_request = -1, ti_self = -1, ti_self_mind = -1,
      ti_self_state = -1, ti_skill = -1, ti_taste = -1, ti_thing = -1, ti_wake = -1;
  int plan_step = -1, plan_next = -1, plan_target = -1, wake_mode = -1, wake_cause = -1, wake_trigger = -1, wake_urgency = -1,
      wake_budget = -1, wake_temperament = -1, wake_outcome = -1, entity_present = -1, commit_status_col = -1;
  int goal_active = -1, plan_running = -1, plan_blocked = -1, plan_suspended = -1;
  int kind_type_id[int(RefKind::kCount)] = {};
  RefKind type_id_kind[tgen::kMaxTypeId + 1] = {};
};

ContextBuilder::ContextBuilder(const Tokenizer& tk) : tk_(tk), impl_(std::make_unique<Impl>(tk)) {}
ContextBuilder::~ContextBuilder() = default;

// =====================================================================================================================
// Selection
namespace {
template <class T>
void pin(std::vector<T>& v, const T& x, std::size_t cap) {
  if (std::find(v.begin(), v.end(), x) != v.end()) return;
  v.insert(v.begin(), x);
  if (v.size() > cap) v.resize(cap);
}
}  // namespace

void ContextBuilder::select(const MindSource& src, Workspace& ws) const {
  const Impl& im = *impl_;
  const NpcBundle& m = *src.mind;
  const sgen::NpcState& st = m.state;
  Selection& sel = ws.selection;
  sel.clear();
  CandidateSelector().select(st, src.now, ws.candidates);
  const Candidates& cands = ws.candidates;
  const auto tdef = [&](int ti) { return std::size_t(tgen::kTypes[ti].count); };

  // what he has just heard: the belief serials of heard_unprocessed (HEARD), kept out of the beliefs
  const auto heard_list = [&]() -> std::span<const std::uint32_t> {
    const ListRef r = st.beliefs.heard_unprocessed;
    return r == unknown::kRef ? std::span<const std::uint32_t>() : m.side.get(r);
  }();
  const auto is_heard_belief = [&](std::uint32_t serial) {
    for (std::size_t i = 1; i < heard_list.size(); i += 2) if (heard_list[i] == serial) return true;
    return false;
  };
  for (std::size_t i = 0; i + 1 < heard_list.size(); i += 2) {   // pairs (number of the key h:<number>, serial of the belief)
    const auto* b = find_rec(st.belief_records, heard_list[i + 1]);
    if (!b) continue;
    if (!im.prop_ok(m, b->b_proposition)) { ++ws.stats.skipped; continue; }
    if (sel.heard.size() < tdef(im.ti_heard)) sel.heard.push_back(heard_list[i]);
  }
  for (const Candidate& c : cands.beliefs) {
    if (sel.beliefs.size() >= tdef(im.ti_belief)) break;
    if (is_heard_belief(c.ref.serial)) continue;
    const auto* b = find_rec(st.belief_records, c.ref.serial);
    if (!b || !im.prop_ok(m, b->b_proposition)) { ++ws.stats.skipped; continue; }
    sel.beliefs.push_back(c.ref.serial);
  }
  for (const Candidate& c : cands.memories) {
    if (sel.memories.size() >= tdef(im.ti_memory)) break;
    const auto* e = find_rec(st.episode_records, c.ref.serial);
    if (!e || !im.prop_ok(m, e->m_content)) { ++ws.stats.skipped; continue; }
    sel.memories.push_back(c.ref.serial);
  }

  // people: the files the salience keeps, joined to what he sees of them; whoever he sees without a file comes as a stranger
  struct Scored { std::int32_t s; Selection::Person p; };
  std::vector<Scored> people;
  people.reserve(cands.persons.size() + 10);
  const auto link_of = [&](std::uint32_t percept) -> std::uint32_t {
    for (const FileLink& l : src.links)
      if (l.percept == percept) return ref_serial(l.file);
    return 0;
  };
  for (const Candidate& c : cands.persons) {
    std::uint32_t percept = 0;
    for (const FileLink& l : src.links)
      if (ref_serial(l.file) == c.ref.serial && find_rec(st.entity_percept_records, l.percept)) { percept = l.percept; break; }
    people.push_back({c.salience, {c.ref.serial, percept}});
  }
  const auto& ep = st.entity_percept_records;
  for (int i = 0; i < ep.kCapacity; ++i) {
    if (!ep.slot_used(i)) continue;
    const std::uint32_t serial = ep.slot_serial(i), file = link_of(serial);
    bool listed = false;
    for (const Scored& p : people) listed = listed || p.p.percept == serial;
    if (listed) continue;
    const bool filed = file != 0 && find_rec(st.relation_records, file) != nullptr;
    people.push_back({200, {filed ? file : 0, serial}});
  }
  std::sort(people.begin(), people.end(), [](const Scored& a, const Scored& b) {
    if (a.s != b.s) return a.s > b.s;
    if (a.p.relation != b.p.relation) return a.p.relation > b.p.relation;
    return a.p.percept > b.p.percept;
  });
  for (const Scored& p : people) {
    if (sel.persons.size() >= tdef(im.ti_entity)) break;
    sel.persons.push_back(p.p);
  }
  for (const Candidate& c : cands.groups) {
    if (sel.groups.size() >= tdef(im.ti_group)) break;
    sel.groups.push_back(c.ref.serial);
  }

  // things seen (nearest first), places known (nearest first), events (latest first)
  {
    const auto& pp = st.percept_records;
    std::vector<std::pair<std::int64_t, std::uint32_t>> v;
    for (int i = 0; i < pp.kCapacity; ++i) {
      if (!pp.slot_used(i)) continue;
      const std::int64_t d = im.sel_raw("pc_dist", reinterpret_cast<const unsigned char*>(&pp.slot_record(i)));
      v.emplace_back(d == unknown::kI32 ? INT64_MAX : d, pp.slot_serial(i));
    }
    std::sort(v.begin(), v.end());
    for (const auto& x : v) if (sel.things.size() < tdef(im.ti_thing)) sel.things.push_back(x.second);
    const auto& lp = st.locus_records;
    v.clear();
    for (int i = 0; i < lp.kCapacity; ++i) {
      if (!lp.slot_used(i)) continue;
      const std::int64_t d = im.sel_raw("lc_dist", reinterpret_cast<const unsigned char*>(&lp.slot_record(i)));
      v.emplace_back(d == unknown::kI32 ? INT64_MAX : d, lp.slot_serial(i));
    }
    std::sort(v.begin(), v.end());
    for (const auto& x : v) if (sel.locus.size() < tdef(im.ti_locus)) sel.locus.push_back(x.second);
    const auto& evp = st.event_seen_records;
    v.clear();
    for (int i = 0; i < evp.kCapacity; ++i) {
      if (!evp.slot_used(i)) continue;
      const std::int64_t t = im.sel_raw("ev_age", reinterpret_cast<const unsigned char*>(&evp.slot_record(i)));
      v.emplace_back(t == unknown::kTime ? INT64_MAX : -t, UINT32_MAX - evp.slot_serial(i));   // latest first, then the highest serial
    }
    std::sort(v.begin(), v.end());
    for (const auto& x : v) if (sel.events.size() < tdef(im.ti_event)) sel.events.push_back(UINT32_MAX - x.second);
  }

  // goals: the active ones, by priority; plans: running, blocked, suspended; requests: latest; skills: the best estimated
  {
    std::vector<std::pair<std::int64_t, std::uint32_t>> v;   // sort key (descending), serial
    const auto rank = [&](auto& pool, auto&& score, std::vector<std::uint32_t>& dst, std::size_t cap) {
      v.clear();
      for (int i = 0; i < pool.kCapacity; ++i)
        if (pool.slot_used(i)) v.emplace_back(score(pool.slot_record(i)), pool.slot_serial(i));
      std::sort(v.begin(), v.end(), [](const auto& a, const auto& b) { return a.first != b.first ? a.first > b.first : a.second > b.second; });
      for (const auto& x : v) if (dst.size() < cap) dst.push_back(x.second);
    };
    rank(st.goal_records, [&](const sgen::Goal& g) {
      const auto* b = reinterpret_cast<const unsigned char*>(&g);
      return (im.sel_raw("g_status", b) == im.goal_active ? 100000 : 0) + 100 * Impl::known16(im.sel_raw("g_priority", b));
    }, sel.goals, tdef(im.ti_goal));
    rank(st.intention_records, [&](const sgen::Intention& g) {
      const auto* b = reinterpret_cast<const unsigned char*>(&g);
      const std::int64_t s = im.sel_raw("i_status", b);
      return (s == im.plan_running ? 3000 : s == im.plan_blocked ? 2000 : s == im.plan_suspended ? 1000 : 0) + Impl::known16(im.sel_raw("i_commitment", b));
    }, sel.plans, tdef(im.ti_plan));
    rank(st.request_records, [&](const sgen::Request& q) {
      const std::int64_t t = im.sel_raw("q_since", reinterpret_cast<const unsigned char*>(&q));
      return t == unknown::kTime ? INT64_MIN + 1 : t;
    }, sel.requests, tdef(im.ti_request));
    rank(st.skill_records, [&](const sgen::Skill& k) { return std::int64_t(Impl::known16(im.sel_raw("k_self_estimate", reinterpret_cast<const unsigned char*>(&k)))); },
         sel.skills, tdef(im.ti_skill));
  }

  // lists of records: in the order the state keeps them (most salient first)
  const auto list_n = [&](ListRef r, int stride) -> int {
    return r == unknown::kRef || r == 0 ? 0 : int(m.side.get(r).size()) / stride;
  };
  for (int i = 0, n = list_n(st.beliefs.inv_seen, kInvStride); i < n && i < int(tdef(im.ti_inv)); ++i) sel.inv.push_back(i);
  for (int i = 0, n = list_n(st.goals.commitments_seen, kCommitStride); i < n && i < int(tdef(im.ti_commit)); ++i) sel.commits.push_back(i);
  for (int i = 0, n = list_n(st.mind_static.tastes, kTasteStride); i < n && i < int(tdef(im.ti_taste)); ++i) sel.tastes.push_back(i);

  // whoever woke him is carried
  const MRef trig = src.wake.trigger;
  const std::uint32_t ts = ref_serial(trig);
  switch (ref_kind(trig)) {
    case RefKind::event: if (find_rec(st.event_seen_records, ts)) pin(sel.events, ts, tdef(im.ti_event)); break;
    case RefKind::heard:
      for (std::size_t i = 0; i + 1 < heard_list.size(); i += 2)
        if (heard_list[i] == ts && find_rec(st.belief_records, heard_list[i + 1])) { pin(sel.heard, ts, tdef(im.ti_heard)); break; }
      break;
    case RefKind::request: if (find_rec(st.request_records, ts)) pin(sel.requests, ts, tdef(im.ti_request)); break;
    case RefKind::goal: if (find_rec(st.goal_records, ts)) pin(sel.goals, ts, tdef(im.ti_goal)); break;
    case RefKind::plan: if (find_rec(st.intention_records, ts)) pin(sel.plans, ts, tdef(im.ti_plan)); break;
    case RefKind::group: {
      const std::uint32_t file = find_rec(st.relation_records, ts | 0x800000u) ? (ts | 0x800000u) : find_rec(st.relation_records, ts) ? ts : 0;
      if (file) pin(sel.groups, file, tdef(im.ti_group));
      break;
    }
    case RefKind::entity: {
      const std::uint32_t file = find_rec(st.relation_records, ts) ? ts : 0;
      if (file) {
        bool in = false;
        for (const auto& p : sel.persons) in = in || p.relation == file;
        if (!in) {
          std::uint32_t percept = 0;
          for (const FileLink& l : src.links) if (ref_serial(l.file) == file && find_rec(st.entity_percept_records, l.percept)) { percept = l.percept; break; }
          sel.persons.insert(sel.persons.begin(), {file, percept});
          if (sel.persons.size() > tdef(im.ti_entity)) sel.persons.resize(tdef(im.ti_entity));
        }
      }
      break;
    }
    case RefKind::commit: {
      const ListRef r = st.goals.commitments_seen;
      if (r == unknown::kRef || r == 0) break;
      const auto items = m.side.get(r);
      for (int i = 0; i * kCommitStride < int(items.size()); ++i)
        if (items[std::size_t(i * kCommitStride)] == ts) { pin(sel.commits, i, tdef(im.ti_commit)); break; }
      break;
    }
    default: break;
  }
}

// =====================================================================================================================
// Assembly
void ContextBuilder::assemble(const MindSource& src, Workspace& ws, DecisionContext& out) const {
  const Impl& im = *impl_;
  const NpcBundle& m = *src.mind;
  const sgen::NpcState& st = m.state;
  const Selection& sel = ws.selection;
  Impl::Cx cx{src, m, ws.stats, ws.cited};
  ws.cited.clear();
  out.records.clear();
  out.known_keys.clear();
  out.has_known_keys = true;
  out.known_keys_valid = true;
  out.records.reserve(100);

  const unsigned char* bases[kHolders] = {};
  const auto reset = [&] { std::fill(std::begin(bases), std::end(bases), nullptr); };
  const auto at = [](const auto& x) { return reinterpret_cast<const unsigned char*>(&x); };
  const auto emit = [&](int ti, std::string key) -> Record& {
    Record& r = im.add(out, ti, std::move(key));
    ++ws.stats.records;
    return r;
  };

  // the NPC itself
  reset();
  bases[kMindStatic] = at(st.mind_static); bases[kMindDynamic] = at(st.mind_dynamic); bases[kBody] = at(st.body);
  bases[kNeeds] = at(st.needs); bases[kLifecycle] = at(st.lifecycle); bases[kCarrier] = at(st.carrier);
  bases[kActivity] = at(st.activity); bases[kBeliefs] = at(st.beliefs); bases[kRelations] = at(st.relations);
  bases[kMemory] = at(st.memory); bases[kGoals] = at(st.goals);
  im.fill(emit(im.ti_self, "me"), im.types[std::size_t(im.ti_self)], bases, cx, false);
  im.fill(emit(im.ti_self_mind, "me.mind"), im.types[std::size_t(im.ti_self_mind)], bases, cx, false);
  im.fill(emit(im.ti_self_state, "me.state"), im.types[std::size_t(im.ti_self_state)], bases, cx, false);

  // the place
  {
    reset();
    Record& r = emit(im.ti_place, "@PLACE");
    const auto& pp = st.place_percept_records;
    for (int i = 0; i < pp.kCapacity; ++i)
      if (pp.slot_used(i)) { bases[kPlacePercept] = at(pp.slot_record(i)); break; }
    im.fill(r, im.types[std::size_t(im.ti_place)], bases, cx, false);
  }

  // persons
  for (const Selection::Person& p : sel.persons) {
    reset();
    const auto* rel = find_rec(st.relation_records, p.relation);
    const auto* ep = find_rec(st.entity_percept_records, p.percept);
    if (!rel && !ep) continue;
    bases[kRelation] = rel ? at(*rel) : nullptr;
    bases[kEntityPercept] = ep ? at(*ep) : nullptr;
    Record& r = emit(im.ti_entity, make_key("@E", rel ? p.relation & kKeyMask : kStrangerBase + p.percept));
    const bool present = rel ? rel->r_present : true;
    im.fill(r, im.types[std::size_t(im.ti_entity)], bases, cx, !present);
    if (!rel) Impl::put(r, im.entity_present, Value::boolean(true));
  }
  // things
  for (const std::uint32_t s : sel.things) {
    const auto* pc = find_rec(st.percept_records, s);
    if (!pc) continue;
    reset();
    bases[kPercept] = at(*pc);
    im.fill(emit(im.ti_thing, make_key("@T", s)), im.types[std::size_t(im.ti_thing)], bases, cx, false);
  }
  // what he carries (records of the list inv_seen, read as percepts)
  if (!sel.inv.empty() && st.beliefs.inv_seen != unknown::kRef) {
    const auto items = m.side.get(st.beliefs.inv_seen);
    for (const int i : sel.inv) {
      if ((std::size_t(i) + 1) * kInvStride > items.size()) continue;
      const std::uint32_t* w = &items[std::size_t(i) * kInvStride];
      sgen::Percept p;
      p.pc_dir = unknown::kI32; p.pc_dist = unknown::kI32; p.pc_file = kUnknownRef; p.pc_owner_believed = MRef{w[6]};
      p.pc_props_seen = w[7]; p.pc_state_seen = w[8];
      p.pc_age_seen = std::uint16_t(w[3]); p.pc_color_seen = std::uint16_t(w[2]); p.pc_kind_seen = std::uint16_t(w[1]);
      p.pc_file_certainty = w[9] == unknown::kRef ? unknown::kI16 : std::int16_t(std::int32_t(w[9])); p.pc_amount_seen = std::uint8_t(w[4]); p.pc_depth_seen = std::uint8_t(w[5]);
      p.pc_display = unknown::kU8; p.pc_motion = unknown::kU8;
      reset();
      bases[kPercept] = at(p);
      im.fill(emit(im.ti_inv, make_key("@T", w[0])), im.types[std::size_t(im.ti_inv)], bases, cx, false);
    }
  }
  // places he knows
  for (const std::uint32_t s : sel.locus) {
    const auto* l = find_rec(st.locus_records, s);
    if (!l) continue;
    reset();
    bases[kLocus] = at(*l);
    im.fill(emit(im.ti_locus, make_key("@L", s)), im.types[std::size_t(im.ti_locus)], bases, cx, false);
  }
  // groups (files with a group kind)
  for (const std::uint32_t s : sel.groups) {
    const auto* g = find_rec(st.relation_records, s);
    if (!g) continue;
    reset();
    bases[kRelation] = at(*g);
    im.fill(emit(im.ti_group, make_key("@G", s & kKeyMask)), im.types[std::size_t(im.ti_group)], bases, cx, false);
  }
  // beliefs, and what he has just heard (a belief not yet judged)
  for (const std::uint32_t s : sel.beliefs) {
    const auto* b = find_rec(st.belief_records, s);
    if (!b) continue;
    reset();
    bases[kBelief] = at(*b);
    im.fill(emit(im.ti_belief, make_key("b:", s)), im.types[std::size_t(im.ti_belief)], bases, cx, false);
  }
  const auto heard_items = st.beliefs.heard_unprocessed == unknown::kRef ? std::span<const std::uint32_t>() : m.side.get(st.beliefs.heard_unprocessed);
  for (const std::uint32_t s : sel.heard) {
    std::uint32_t belief = 0;
    for (std::size_t i = 0; i + 1 < heard_items.size(); i += 2) if (heard_items[i] == s) { belief = heard_items[i + 1]; break; }
    const auto* b = find_rec(st.belief_records, belief);
    if (!b) continue;
    reset();
    bases[kBelief] = at(*b);
    im.fill(emit(im.ti_heard, make_key("h:", s)), im.types[std::size_t(im.ti_heard)], bases, cx, false);
  }
  for (const std::uint32_t s : sel.memories) {
    const auto* e = find_rec(st.episode_records, s);
    if (!e) continue;
    reset();
    bases[kEpisode] = at(*e);
    im.fill(emit(im.ti_memory, make_key("m:", s)), im.types[std::size_t(im.ti_memory)], bases, cx, false);
  }
  for (const std::uint32_t s : sel.goals) {
    const auto* g = find_rec(st.goal_records, s);
    if (!g) continue;
    reset();
    bases[kGoal] = at(*g);
    im.fill(emit(im.ti_goal, make_key("g:", s)), im.types[std::size_t(im.ti_goal)], bases, cx, false);
  }
  // plans: the generic fields of the intention, then the step, the next step and the target of the whole plan
  for (const std::uint32_t s : sel.plans) {
    const auto* in = find_rec(st.intention_records, s);
    if (!in) continue;
    reset();
    bases[kIntention] = at(*in);
    Record& r = emit(im.ti_plan, make_key("p:", s));
    im.fill(r, im.types[std::size_t(im.ti_plan)], bases, cx, false);
    const auto steps_it = im.vars.find("i_steps"), idx_it = im.vars.find("i_step_index"), tg_it = im.vars.find("i_step_targets");
    const std::int64_t steps_ref = read_raw(*steps_it->second.fd, at(*in)), idx_raw = read_raw(*idx_it->second.fd, at(*in));
    if (steps_ref != std::int64_t(unknown::kRef) && idx_raw != unknown::kI32) {
      const auto steps = m.side.get(ListRef(steps_ref));
      const std::int64_t k = idx_raw / 1000;
      const auto word = [&](std::int64_t i, int col) {
        if (i < 0 || i > std::int64_t(steps.size())) return;
        if (i == std::int64_t(steps.size())) { Impl::put(r, col, Value::string(std::string())); return; }   // past the last: the plan ends
        const std::string_view w = word_text(steps[std::size_t(i)]);
        if (!w.empty()) Impl::put(r, col, Value::string(std::string(w)));
      };
      word(k, im.plan_step);
      word(k + 1, im.plan_next);
    }
    const std::int64_t tg_ref = read_raw(*tg_it->second.fd, at(*in));
    if (tg_ref != std::int64_t(unknown::kRef) && tg_ref != 0) {
      const auto items = m.side.get(ListRef(tg_ref));
      if (!items.empty() && is_target_header(items[0])) {
        std::string key;
        const ColumnDef& cd = tk_.column_def(im.ti_plan, im.plan_target);
        if (im.ref_key(MRef{strip_target_header(items[0])}, &cd, cx, key)) Impl::put(r, im.plan_target, Value::string(std::move(key)));
      }
    }
  }
  for (const std::uint32_t s : sel.requests) {
    const auto* q = find_rec(st.request_records, s);
    if (!q) continue;
    reset();
    bases[kRequest] = at(*q);
    im.fill(emit(im.ti_request, make_key("q:", s)), im.types[std::size_t(im.ti_request)], bases, cx, false);
  }
  // agreements he remembers (records of the list commitments_seen)
  if (!sel.commits.empty() && st.goals.commitments_seen != unknown::kRef) {
    const auto items = m.side.get(st.goals.commitments_seen);
    for (const int i : sel.commits) {
      if ((std::size_t(i) + 1) * kCommitStride > items.size()) continue;
      const std::uint32_t* w = &items[std::size_t(i) * kCommitStride];
      Record& r = emit(im.ti_commit, make_key("c:", w[0]));
      const auto col = [&](const char* f) { return tk_.column(im.ti_commit, f); };
      std::string key;
      if (im.ref_key(MRef{w[2]}, &tk_.column_def(im.ti_commit, col("counterparty")), cx, key)) Impl::put(r, col("counterparty"), Value::string(std::move(key)));
      if (w[3] != unknown::kRef) Impl::put(r, col("mine"), Value::boolean(w[3] != 0));
      if (w[1] != 0 && w[1] != unknown::kRef) {
        std::string text;
        if (im.proposition_text(PropRef(w[1]), cx, text)) Impl::put(r, col("prop"), Value::string(std::move(text)));
      }
      const ColumnDef& sc = tk_.column_def(im.ti_commit, im.commit_status_col);
      if (w[4] != unknown::kRef && int(w[4]) < sc.values_n)
        Impl::put(r, im.commit_status_col, Value::string(std::string(tgen::kStrings[tgen::kStringStart[sc.values_at] + w[4]])));
      const auto until = [&](const char* f, std::uint32_t lo, std::uint32_t hi) {
        const GameTime t = GameTime((std::uint64_t(hi) << 32) | lo);
        if (t == unknown::kTime) return;
        double x = 0;
        if (im.number_of(NumScale::time_until, sgen::FieldDesc{"", sgen::ColType::Time, 0, 8, 0, 0}, t, cx, x)) Impl::put(r, col(f), Value::number(x));
      };
      until("deadline", w[5], w[6]);
      until("when", w[7], w[8]);
      if (w[9] != unknown::kRef) {
        Value list = Value::list();
        const ColumnDef& wc = tk_.column_def(im.ti_commit, col("witnesses"));
        for (const std::uint32_t it : m.side.get(ListRef(w[9]))) {
          if (list.items().size() >= 4) break;
          if (it != 0 && im.ref_key(MRef{it}, &wc, cx, key) && !key.empty()) list.items().push_back(Value::string(key));
        }
        Impl::put(r, col("witnesses"), std::move(list));
      }
    }
  }
  for (const std::uint32_t s : sel.skills) {
    const auto* k = find_rec(st.skill_records, s);
    if (!k) continue;
    reset();
    bases[kSkill] = at(*k);
    im.fill(emit(im.ti_skill, make_key("k:", s)), im.types[std::size_t(im.ti_skill)], bases, cx, false);
  }
  // singular tastes: pairs (concept word, attitude in tenths)
  if (!sel.tastes.empty() && st.mind_static.tastes != unknown::kRef) {
    const auto items = m.side.get(st.mind_static.tastes);
    int rank = 0;
    for (const int i : sel.tastes) {
      if ((std::size_t(i) + 1) * kTasteStride > items.size()) continue;
      Record& r = emit(im.ti_taste, make_key("t:", std::uint32_t(++rank)));
      const std::uint32_t concept_id = items[std::size_t(i) * kTasteStride];
      const std::int32_t att = std::int32_t(items[std::size_t(i) * kTasteStride + 1]);
      if (concept_id != unknown::kRef) {
        const std::string_view w = word_text(concept_id);
        if (!w.empty()) Impl::put(r, tk_.column(im.ti_taste, "concept"), Value::string(std::string(w)));
      }
      if (att != unknown::kI32) Impl::put(r, tk_.column(im.ti_taste, "attitude"), Value::number(Impl::clamp_to(double(att) / 10.0, -10.0, 10.0, cx)));
    }
  }
  // what he has just perceived
  for (const std::uint32_t s : sel.events) {
    const auto* e = find_rec(st.event_seen_records, s);
    if (!e) continue;
    reset();
    bases[kEventSeen] = at(*e);
    im.fill(emit(im.ti_event, make_key("@V", s)), im.types[std::size_t(im.ti_event)], bases, cx, false);
  }

  // why he wakes
  {
    const WakeInput& w = src.wake;
    Record& r = emit(im.ti_wake, "wake");
    const auto en = [&](int col, int idx) {
      const ColumnDef& cd = tk_.column_def(im.ti_wake, col);
      if (idx >= 0 && idx < cd.values_n) Impl::put(r, col, Value::string(std::string(tgen::kStrings[tgen::kStringStart[cd.values_at] + idx])));
    };
    en(im.wake_mode, int(w.mode));
    en(im.wake_cause, int(w.cause));
    std::string key;
    if (w.trigger.serial == 0) key.clear();
    if (w.trigger.serial == 0 || im.ref_key(w.trigger, &tk_.column_def(im.ti_wake, im.wake_trigger), cx, key))
      Impl::put(r, im.wake_trigger, Value::string(std::move(key)));
    Impl::put(r, im.wake_urgency, Value::number(Impl::clamp_to(double(w.urgency_tenths) / 10.0, 0.0, 10.0, cx)));
    Impl::put(r, im.wake_budget, Value::number(Impl::clamp_to(double(w.budget), 0.0, kQtyMax, cx)));
    Impl::put(r, im.wake_temperament, Value::number(Impl::clamp_to(double(w.temperament_tenths) / 10.0, 0.0, 10.0, cx)));
    if (w.outcome != WakeOutcome::none) en(im.wake_outcome, int(w.outcome));
  }

  // known_keys: every record carried, and every pointer written (a pointer to what the dossier does not carry is a ghost)
  std::sort(ws.cited.begin(), ws.cited.end());
  ws.cited.erase(std::unique(ws.cited.begin(), ws.cited.end()), ws.cited.end());
  out.known_keys.reserve(out.records.size() + ws.cited.size());
  for (const Record& r : out.records) out.known_keys.push_back(r.key);
  for (std::string& k : ws.cited) out.known_keys.push_back(std::move(k));
  ws.cited.clear();
}

void ContextBuilder::build(const MindSource& src, Workspace& ws, DecisionContext& out) const {
  select(src, ws);
  assemble(src, ws, out);
}

}  // namespace em::social::tok2
