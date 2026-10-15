#include "emergence/social/governor.h"
#include "emergence/social/vocab_gen.h"

#include <algorithm>
#include <cmath>
#include <cstdlib>
#include <cstring>
#include <limits>
#include <memory>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <utility>
#include <vector>

namespace em::social {
namespace {

constexpr int kAdultTenths = gen::kAdultAgeYears * 10;
const Party kUnknown{};
const Party kThing{-1, -1, -1, true, false, true};   // a stone, a house: never a minor, never a party of D10

bool numeric(gen::Scale s) {
  return s == gen::Scale::bipolar10 || s == gen::Scale::unipolar10 || s == gen::Scale::qty || s == gen::Scale::ratio;
}

void bounds(gen::Scale s, int& lo, int& hi) {
  lo = std::numeric_limits<std::int16_t>::min();
  hi = std::numeric_limits<std::int16_t>::max();
  if (s == gen::Scale::bipolar10) { lo = -100; hi = 100; }
  if (s == gen::Scale::unipolar10) { lo = 0; hi = 100; }
}

bool bit(std::uint16_t mask, int index) { return index >= 0 && index < 16 && ((mask >> index) & 1u) != 0; }

Verdict refuse(Reason r) { return {false, 0, r}; }

}  // namespace

bool condition_is_live(gen::Condition c) {
  const auto i = static_cast<std::size_t>(c);
  return i < gen::kConditionLive.size() && gen::kConditionLive[i];
}

// ---- Party -----------------------------------------------------------------------------------------------

bool Party::may_be_minor() const {
  if (!person) return false;
  if (!resolved) return true;
  for (std::int16_t a : {real_age, believed_age, perceived ? apparent_age : static_cast<std::int16_t>(kAdultTenths)})
    if (a < 0 || a < kAdultTenths) return true;     // unknown counts as minor (deny by default)
  return false;
}

std::int16_t Party::from_years(double years) {
  if (!std::isfinite(years)) return -1;
  const double t = std::floor(years * 10.0);
  if (t < 0.0) return -1;
  if (t > std::numeric_limits<std::int16_t>::max()) return -1;   // absurd: unknown, a possible minor
  return static_cast<std::int16_t>(t);
}

std::string_view to_string(Reason r) {
  switch (r) {
    case Reason::ok: return "ok";
    case Reason::jump: return "jump";
    case Reason::step: return "step";
    case Reason::slow: return "slow";
    case Reason::clipped: return "clipped";
    case Reason::unknown_variable: return "unknown_variable";
    case Reason::engine_owned: return "engine_owned";
    case Reason::structured: return "structured";
    case Reason::non_finite: return "non_finite";
    case Reason::no_writer: return "no_writer";
    case Reason::unknown_gesture: return "unknown_gesture";
    case Reason::invalid_value: return "invalid_value";
    case Reason::d10_intimate: return "d10_intimate";
    case Reason::d10_value: return "d10_value";
    case Reason::d10_person: return "d10_person";
    case Reason::d10_whitelist: return "d10_whitelist";
    case Reason::duplicate: return "duplicate";
    case Reason::too_many_writes: return "too_many_writes";
    case Reason::ledger_full: return "ledger_full";
    case Reason::d10_hearer: return "d10_hearer";
    case Reason::unexpanded: return "unexpanded";
    case Reason::kCount: break;
  }
  return "?";
}

// ---- WriteLedger -----------------------------------------------------------------------------------------

void WriteLedger::roll(std::int32_t day, std::int32_t life_year) {
  if (!synced_) {                                 // the first roll adopts the engine's clock (review 15)
    synced_ = true;
    if (day != day_) { day_ = day; lock_day_ = false; }
    if (life_year != life_year_) { life_year_ = life_year; lock_year_ = false; }
    return;
  }
  if (day > day_ && std::int64_t{day} - day_ <= gen::kMaxDayJump) { day_ = day; lock_day_ = false; }
  if (life_year > life_year_ && std::int64_t{life_year} - life_year_ <= gen::kMaxYearJump) {
    life_year_ = life_year;
    lock_year_ = false;
  }
}

std::size_t WriteLedger::find(gen::Var v, std::uint32_t target) const {
  for (std::size_t i = 0; i < size_; ++i)
    if (entries_[i].target == target && entries_[i].var == static_cast<std::uint16_t>(v)) return i;
  return size_;
}

bool WriteLedger::live(const LedgerEntry& e) const {
  return (e.day_moved != 0 && e.day_stamp == day_) || (e.year_moved != 0 && e.year_stamp == life_year_);
}

LedgerEntry* WriteLedger::acquire(gen::Var v, std::uint32_t target) {
  if (const std::size_t hit = find(v, target); hit < size_) return &entries_[hit];
  LedgerEntry* slot = nullptr;
  for (std::size_t i = 0; i < size_ && !slot; ++i)
    if (!live(entries_[i])) slot = &entries_[i];            // the first dead slot, in index order
  if (!slot) {
    if (size_ == kCapacity) return nullptr;
    slot = &entries_[size_++];
  }
  *slot = LedgerEntry{};
  slot->target = target;
  slot->var = static_cast<std::uint16_t>(v);
  return slot;
}

std::int32_t WriteLedger::moved_today(gen::Var v, std::uint32_t target) const {
  const std::size_t i = find(v, target);
  return i < size_ && entries_[i].day_stamp == day_ ? entries_[i].day_moved : 0;
}

std::int32_t WriteLedger::moved_this_year(gen::Var v, std::uint32_t target) const {
  const std::size_t i = find(v, target);
  return i < size_ && entries_[i].year_stamp == life_year_ ? entries_[i].year_moved : 0;
}

bool WriteLedger::add_today(gen::Var v, std::uint32_t target, std::int32_t amount) {
  if (lock_day_) return false;
  LedgerEntry* e = acquire(v, target);
  if (!e) return false;
  if (e->day_stamp != day_) { e->day_stamp = day_; e->day_moved = 0; }
  e->day_moved += amount;
  return true;
}

bool WriteLedger::add_this_year(gen::Var v, std::uint32_t target, std::int32_t amount) {
  if (lock_year_) return false;
  LedgerEntry* e = acquire(v, target);
  if (!e) return false;
  if (e->year_stamp != life_year_) { e->year_stamp = life_year_; e->year_moved = 0; }
  e->year_moved += amount;
  return true;
}

bool WriteLedger::restore(std::int32_t now_day, std::int32_t now_life_year, std::span<const LedgerEntry> saved) {
  bool good = saved.size() <= kCapacity;          // validate first: `saved` may alias entries_
  for (std::size_t i = 0; good && i < saved.size(); ++i) {
    const LedgerEntry& e = saved[i];
    good = e.reserved == 0 && e.var < gen::kVariables.size() && e.day_moved >= 0 && e.day_moved <= kMaxMoved &&
           e.year_moved >= 0 && e.year_moved <= kMaxMoved && e.day_stamp <= now_day && e.year_stamp <= now_life_year;
    for (std::size_t j = 0; good && j < i; ++j)
      good = !(saved[j].target == saved[i].target && saved[j].var == saved[i].var);
  }
  const std::size_t n = good ? saved.size() : 0;
  if (n > 0) std::memmove(entries_.data(), saved.data(), n * sizeof(LedgerEntry));
  std::fill(entries_.begin() + static_cast<std::ptrdiff_t>(n), entries_.end(), LedgerEntry{});
  size_ = n;
  day_ = now_day;
  life_year_ = now_life_year;
  synced_ = true;
  lock_day_ = lock_year_ = !good;                 // a corrupt save locks the bounds, it never refills them
  return good;
}

// ---- Governor: writes ------------------------------------------------------------------------------------

Verdict Governor::check_write(const WriteRequest& r, WriteLedger& ledger) const {
  const auto idx = static_cast<std::size_t>(r.var);
  if (idx >= gen::kVariables.size() || gen::kVariables[idx].retired) return refuse(Reason::unknown_variable);
  const gen::VariableSpec& v = gen::kVariables[idx];
  const bool jump = (v.writers & gen::writer::T_jump) != 0, stepw = (v.writers & gen::writer::T_step) != 0;
  const bool sloww = (v.writers & gen::writer::T_slow) != 0;
  if (v.engine_only || !(jump || stepw || sloww)) return refuse(Reason::engine_owned);
  if (!numeric(v.scale)) return refuse(Reason::structured);   // enums, words, pointers: check_value / check_record

  const int o = r.old_value;
  int want = r.proposed;
  if (v.intimate && want > (r.creating ? 0 : o)) {
    // One's own drive (mind, needs, body): only the actor matters. Otherwise the other person counts too.
    const Party& a = r.actor ? *r.actor : kUnknown;
    const Party& t = r.intimate_target ? *r.intimate_target : kUnknown;
    if (a.may_be_minor() || (!v.self_holder && t.may_be_minor())) return refuse(Reason::d10_intimate);
  }
  int lo, hi;
  bounds(v.scale, lo, hi);
  want = std::clamp(want, lo, hi);
  const int delta = want - o;
  if (jump && (r.creating || !stepw)) return {true, static_cast<std::int16_t>(want), Reason::jump};

  int limit, used;
  Reason book;
  if (stepw) { limit = v.rate_tenths; used = ledger.moved_today(r.var, r.target); book = Reason::step; }
  else if (sloww) { limit = v.slow_tenths; used = ledger.moved_this_year(r.var, r.target); book = Reason::slow; }
  else return refuse(Reason::no_writer);

  int d = std::clamp(delta, -int(v.step_tenths), int(v.step_tenths));
  const int left = std::max(0, limit - used);
  d = std::clamp(d, -left, left);
  if (d != 0) {
    const bool recorded = stepw ? ledger.add_today(r.var, r.target, std::abs(d))
                                : ledger.add_this_year(r.var, r.target, std::abs(d));
    if (!recorded) return {false, static_cast<std::int16_t>(o), Reason::ledger_full};   // deny, move nothing
  }
  return {d != 0 || delta == 0, static_cast<std::int16_t>(o + d), d == delta ? book : Reason::clipped};
}

std::size_t Governor::check_writes(std::span<const WriteKey> keys, std::span<Verdict> out) const {
  if (out.size() < keys.size()) {
    for (Verdict& v : out) v = refuse(Reason::invalid_value);
    return 0;
  }
  const std::size_t n = keys.size();
  std::size_t unique = 0, kept = 0;
  for (std::size_t i = 0; i < n; ++i) {
    bool dup = false;
    for (std::size_t j = 0; j < i && !dup; ++j) dup = keys[j] == keys[i];
    if (dup) { out[i] = refuse(Reason::duplicate); continue; }
    if (unique++ < kWritesPerDecision) { out[i] = {true, 0, Reason::ok}; ++kept; }
    else out[i] = refuse(Reason::too_many_writes);
  }
  return kept;
}

// ---- Governor: gestures ----------------------------------------------------------------------------------

Verdict Governor::check_gesture(const GestureCall& call, const Party* actor, bool executed) const {
  const auto gi = static_cast<std::size_t>(call.gesture);
  if (gi >= gen::kGestures.size() || gen::kGestures[gi].retired) return refuse(Reason::unknown_gesture);
  const gen::GestureSpec& g = gen::kGestures[gi];

  // 1. Every given value must be a valid index; with `executed`, every non-optional param must be given.
  for (int i = 0; i < gen::kMaxParams; ++i) {
    const int val = call.value[i];
    if (i >= g.n_params) {
      if (val != -1) return refuse(Reason::invalid_value);       // a value for a param the gesture does not have
      continue;
    }
    const gen::ParamSpec& p = g.params[i];
    if (val == -1) {
      if (executed && !p.optional) return refuse(Reason::invalid_value);
      continue;
    }
    const bool valid = p.type == gen::ParamType::enum_ ? (val >= 0 && val < p.n_values && bit(p.valid_mask, val)) : val == 0;
    if (!valid) return refuse(Reason::invalid_value);
  }
  for (int i = 0; i < g.n_params; ++i)                          // content: check_utterance, not ported yet
    if (g.params[i].type == gen::ParamType::expression && call.value[i] == 0) return refuse(Reason::structured);

  // 2. The persons involved: the actor, each party param that is given (a missing non-optional party param of a
  //    contact gesture counts an UNKNOWN person). A thing never counts.
  int persons = 1;
  bool minor = (actor ? *actor : kUnknown).may_be_minor();
  for (int i = 0; i < g.n_params; ++i) {
    const gen::ParamSpec& p = g.params[i];
    if (!p.party) continue;
    const bool given = call.value[i] >= 0 || call.party[i] != nullptr;
    const Party* party;
    if (given) party = call.party[i] ? call.party[i] : &kUnknown;
    else if (g.contact && !p.optional && p.accepts_agent) party = &kUnknown;
    else continue;
    if (!party->person) continue;
    ++persons;
    if (party->may_be_minor()) minor = true;
  }
  if (!minor) return {true, 0, Reason::ok};

  // 3. A possible minor is involved (D10).
  if (g.intimate) return refuse(Reason::d10_intimate);
  for (int i = 0; i < g.n_params; ++i) {
    const gen::ParamSpec& p = g.params[i];
    if (p.type == gen::ParamType::enum_ && call.value[i] >= 0 && bit(p.intimate_mask, call.value[i]))
      return refuse(Reason::d10_value);
  }
  if (g.contact && persons > 1) {
    if (!g.minor_person_ok) return refuse(Reason::d10_person);
    for (int i = 0; i < g.n_params; ++i) {
      const gen::ParamSpec& p = g.params[i];
      if (!p.whitelisted) continue;
      if (call.value[i] < 0 || !bit(p.minor_mask, call.value[i])) return refuse(Reason::d10_whitelist);
    }
  }
  return {true, 0, Reason::ok};
}

// ---- Governor: speech and records (T14) -------------------------------------------------------------------
//
// The content is read from the canonical text of the validated expression (TypedExpression keeps its tree
// private): a small tree is rebuilt here, once per expression and once per cited record.
namespace {

using sv = std::string_view;

// The words D10 looks at, generated by catalogue/tools/governor_vectors.py from the Python oracle:
// kNodeIntimate = concept, variable, interpretation or manner flagged intimate; kHearerSensitive = intimate manner,
// intimate gesture or intimate variable (an intimate ACT or DESIRE, which is never said to a possible minor).
constexpr std::uint8_t kNodeIntimate = 1, kHearerSensitive = 2;
struct WordFlag { sv word; std::uint8_t flags; };
#include "governor_words.inc"

std::uint8_t word_flags(sv w) {
  const auto it = std::lower_bound(std::begin(kWordFlags), std::end(kWordFlags), w,
                                   [](const WordFlag& f, sv x) { return f.word < x; });
  return it != std::end(kWordFlags) && it->word == w ? it->flags : std::uint8_t{0};
}

bool all_digits(sv s) {   // ASCII digits only, at least one
  if (s.empty()) return false;
  for (const char c : s)
    if (c < '0' || c > '9') return false;
  return true;
}

// ^(@E\d+|@T\d+|@G\d+|@L\d+|@V\d+|@PLACE|[bmghqc]:\d+|n:\d+)\Z
bool is_pointer(sv s) {
  if (s == "@PLACE") return true;
  if (s.size() >= 3 && s[0] == '@') return sv("ETGLV").find(s[1]) != sv::npos && all_digits(s.substr(2));
  return s.size() >= 3 && s[1] == ':' && sv("bmghqcn").find(s[0]) != sv::npos && all_digits(s.substr(2));
}

// ^([bmghqc]:|@V)[0-9]+$ : a cited record or perceived event; its frozen content is what is said.
bool is_cite(sv s) {
  if (s.size() >= 3 && s[0] == '@') return s[1] == 'V' && all_digits(s.substr(2));
  return s.size() >= 3 && s[1] == ':' && sv("bmghqc").find(s[0]) != sv::npos && all_digits(s.substr(2));
}

bool is_ref_word(sv s) {
  static constexpr sv words[] = {"me", "you", "us", "someone", "anyone", "everyone", "no_one", "this", "here",
                                 "the_one", "somewhere", "nowhere", "something", "nothing"};
  return std::find(std::begin(words), std::end(words), s) != std::end(words);
}

const std::unordered_set<sv>& kinds() {
  static const std::unordered_set<sv> set = [] {
    std::unordered_set<sv> k;
    for (const auto& name : gen::kKinds) k.insert(name);
    return k;
  }();
  return set;
}

const gen::GestureSpec* find_gesture(sv id) {
  static const std::unordered_map<sv, std::size_t> index = [] {
    std::unordered_map<sv, std::size_t> m;
    for (std::size_t i = 0; i < gen::kGestures.size(); ++i)
      if (!gen::kGestures[i].retired) m.emplace(gen::kGestures[i].id, i);
    return m;
  }();
  const auto it = index.find(id);
  return it == index.end() ? nullptr : &gen::kGestures[it->second];
}

// The tree of an expression: a symbol (leaf) or a list (head + children).
class Tree {
 public:
  struct Item { std::uint32_t off = 0, len = 0; std::int32_t node = -1; };   // node >= 0: a list
  struct Node { Item head; std::uint32_t first = 0, n = 0; };

  explicit Tree(const TypedExpression& e) : text_(e.canonical_text()) { root_ = read(); }

  Item root() const { return root_; }
  bool is_node(const Item& i) const { return i.node >= 0; }
  sv text(const Item& i) const { return sv(text_).substr(i.off, i.len); }
  sv head(const Item& i) const { return text(nodes_[static_cast<std::size_t>(i.node)].head); }
  std::uint32_t size(const Item& i) const { return i.node < 0 ? 0 : nodes_[static_cast<std::size_t>(i.node)].n; }
  Item arg(const Item& i, std::uint32_t k) const {
    const Node& n = nodes_[static_cast<std::size_t>(i.node)];
    return args_[n.first + k];
  }

 private:
  Item read() {
    while (pos_ < text_.size() && text_[pos_] == ' ') ++pos_;
    if (pos_ >= text_.size()) return {};
    if (text_[pos_] != '(') return symbol();
    ++pos_;
    Node node;
    node.head = symbol();
    std::vector<Item> kids;
    for (;;) {
      while (pos_ < text_.size() && text_[pos_] == ' ') ++pos_;
      if (pos_ >= text_.size()) break;
      if (text_[pos_] == ')') { ++pos_; break; }
      kids.push_back(read());
    }
    node.first = static_cast<std::uint32_t>(args_.size());
    node.n = static_cast<std::uint32_t>(kids.size());
    args_.insert(args_.end(), kids.begin(), kids.end());
    nodes_.push_back(node);
    Item it;
    it.node = static_cast<std::int32_t>(nodes_.size() - 1);
    return it;
  }
  Item symbol() {
    Item it;
    it.off = static_cast<std::uint32_t>(pos_);
    while (pos_ < text_.size() && text_[pos_] != ' ' && text_[pos_] != '(' && text_[pos_] != ')') ++pos_;
    it.len = static_cast<std::uint32_t>(pos_) - it.off;
    return it;
  }

  std::string text_;
  std::size_t pos_ = 0;
  std::vector<Node> nodes_;
  std::vector<Item> args_;
  Item root_;
};

// One check of one expression: it owns the speaker, the bindings and the memo of the unfolded records.
class SpeechCheck {
 public:
  SpeechCheck(const Party* speaker, std::span<const PartyBinding> parties, const RecordLookup& expand)
      : speaker_(speaker ? speaker : &kUnknown), parties_(parties), expand_(expand) {}

  Verdict node(const Tree& t, const Tree::Item& it, int depth);
  bool said_sensitive(const Tree& t, const Tree::Item& it, int depth);

 private:
  struct Memo { std::string ref; std::unique_ptr<Tree> tree; };

  const Party* resolve(const Tree& t, const Tree::Item& it) const;
  const Tree* unfold(sv ref, int depth);
  void participants(const Tree& t, const Tree::Item& it, std::vector<const Party*>& out) const;
  void content_refs(const Tree& t, const Tree::Item& it, std::vector<const Party*>& out) const;
  Verdict described_gesture(const Tree& t, const Tree::Item& it, const gen::GestureSpec& spec) const;

  const Party* speaker_;
  std::span<const PartyBinding> parties_;
  const RecordLookup& expand_;
  std::vector<Memo> memo_;
};

const Party* SpeechCheck::resolve(const Tree& t, const Tree::Item& it) const {
  if (t.is_node(it)) return &kUnknown;                       // (described ...) or any node: not identified
  const sv ref = t.text(it);
  if (ref == "me") return speaker_;
  for (auto p = parties_.rbegin(); p != parties_.rend(); ++p)
    if (p->symbol == ref) return p->party ? p->party : &kUnknown;
  if (ref.starts_with("@T") || ref.starts_with("@L") || ref.starts_with("@PLACE") || ref.starts_with("@V") ||
      ref == "here" || ref == "this" || all_digits(ref))
    return &kThing;
  if (kinds().count(ref.substr(0, ref.find(':'))) != 0) return &kThing;
  return &kUnknown;
}

const Tree* SpeechCheck::unfold(sv ref, int depth) {
  if (!expand_ || depth > 2) return nullptr;
  for (const Memo& m : memo_)
    if (m.ref == ref) return m.tree.get();
  const TypedExpression* e = expand_(ref);
  memo_.push_back({std::string(ref), e && e->ok() ? std::make_unique<Tree>(*e) : nullptr});
  return memo_.back().tree.get();
}

void SpeechCheck::participants(const Tree& t, const Tree::Item& it, std::vector<const Party*>& out) const {
  std::vector<sv> roles = {"to", "with", "into"};
  if (t.size(it) > 1 && t.head(it) == "did" && !t.is_node(t.arg(it, 1)))
    if (const gen::GestureSpec* a = find_gesture(t.text(t.arg(it, 1))))
      for (int i = 0; i < a->n_params; ++i)
        if (a->params[i].type == gen::ParamType::ref) roles.push_back(a->params[i].name);
  const bool did = t.head(it) == "did";
  for (std::uint32_t k = 0; k < t.size(it); ++k) {
    const Tree::Item x = t.arg(it, k);
    if (!t.is_node(x)) {
      const sv s = t.text(x);
      if ((is_pointer(s) || is_ref_word(s)) && !is_cite(s)) out.push_back(resolve(t, x));   // a citation is a record
      continue;
    }
    const sv h = t.head(x);
    if (h == "described" || h == "of") { out.push_back(&kUnknown); continue; }
    if (t.size(x) > 0 && std::find(roles.begin(), roles.end(), h) != roles.end() &&
        (did || h == "to" || h == "with" || h == "into"))
      out.push_back(resolve(t, t.arg(x, 0)));
  }
}

void SpeechCheck::content_refs(const Tree& t, const Tree::Item& it, std::vector<const Party*>& out) const {
  if (!t.is_node(it)) {
    const sv s = t.text(it);
    if ((is_pointer(s) && !is_cite(s)) || is_ref_word(s)) out.push_back(resolve(t, it));
    return;
  }
  const sv h = t.head(it);
  if (h == "described" || h == "of") { out.push_back(&kUnknown); return; }
  for (std::uint32_t k = 0; k < t.size(it); ++k) content_refs(t, t.arg(it, k), out);
}

// A described gesture (did WHO GESTURE ...) is checked as the gesture it describes: the parts of the call are
// read the way governor.py _check_node reads them.
Verdict SpeechCheck::described_gesture(const Tree& t, const Tree::Item& it, const gen::GestureSpec& spec) const {
  GestureCall call;
  call.gesture = static_cast<gen::Gesture>(&spec - gen::kGestures.data());
  std::array<int, gen::kMaxParams> refs{};
  int n_refs = 0;
  for (int i = 0; i < spec.n_params; ++i)
    if (spec.params[i].type == gen::ParamType::ref) refs[static_cast<std::size_t>(n_refs++)] = i;
  const auto set_ref = [&](int param, const Party* party) {
    call.value[static_cast<std::size_t>(param)] = 0;
    call.party[static_cast<std::size_t>(param)] = party;
  };
  const auto frame_head = [&](const Tree::Item& x) {
    if (!t.is_node(x)) return false;
    const sv h = t.head(x);
    return h == "with" || h == "to" || h == "into" || h == "how" || h == "says";
  };
  std::uint32_t k = 2;
  if (k < t.size(it) && !frame_head(t.arg(it, k))) {
    if (n_refs > 0) set_ref(refs[0], resolve(t, t.arg(it, k)));
    ++k;
  }
  for (; k < t.size(it); ++k) {
    const Tree::Item r = t.arg(it, k);
    if (!t.is_node(r) || t.size(r) == 0) continue;
    const sv h = t.head(r);
    if (h == "how") {
      const Tree::Item v = t.arg(r, 0);
      if (t.is_node(v)) continue;
      for (int i = 0; i < spec.n_params; ++i) {
        const gen::ParamSpec& p = spec.params[i];
        if (p.type != gen::ParamType::enum_) continue;
        for (int j = 0; j < p.n_values; ++j)
          if (bit(p.valid_mask, j) && p.values[static_cast<std::size_t>(j)] == t.text(v)) call.value[static_cast<std::size_t>(i)] = static_cast<std::int8_t>(j);
      }
    } else {
      for (int q = 0; q < n_refs; ++q)
        if (spec.params[refs[static_cast<std::size_t>(q)]].name == h) set_ref(refs[static_cast<std::size_t>(q)], resolve(t, t.arg(r, 0)));
    }
  }
  return Governor().check_gesture(call, resolve(t, t.arg(it, 0)), false);
}

Verdict SpeechCheck::node(const Tree& t, const Tree::Item& it, int depth) {
  if (!t.is_node(it)) {
    if (!is_cite(t.text(it))) return {true, 0, Reason::ok};
    const Tree* inner = unfold(t.text(it), depth);   // a bare citation says the record too
    if (!inner) return refuse(Reason::unexpanded);
    return node(*inner, inner->root(), depth + 1);
  }
  const sv head = t.head(it);
  const std::uint32_t n = t.size(it);
  if (head == "that") return n > 0 ? node(t, t.arg(it, 0), depth) : refuse(Reason::unexpanded);
  if (head == "did" && n >= 2 && !t.is_node(t.arg(it, 1)))
    if (const gen::GestureSpec* spec = find_gesture(t.text(t.arg(it, 1)))) {
      const Verdict v = described_gesture(t, it, *spec);
      if (!v.allowed) return v;
    }
  // an intimate word in this node: every participant (its referring arguments) is checked
  bool intimate = (word_flags(head) & kNodeIntimate) != 0;
  for (std::uint32_t k = 0; k < n && !intimate; ++k)
    if (!t.is_node(t.arg(it, k))) intimate = (word_flags(t.text(t.arg(it, k))) & kNodeIntimate) != 0;
  if (intimate) {
    std::vector<const Party*> refs;
    participants(t, it, refs);
    for (std::uint32_t k = 0; k < n; ++k) {   // (qualifies m:1 adultery): the persons are those of the cited record
      const Tree::Item c = t.arg(it, k);
      if (t.is_node(c) || !is_cite(t.text(c))) continue;
      const Tree* inner = unfold(t.text(c), depth);
      if (!inner) return refuse(Reason::unexpanded);
      content_refs(*inner, inner->root(), refs);
    }
    for (const Party* p : refs)
      if (p->may_be_minor()) return refuse(Reason::d10_intimate);
  }
  for (std::uint32_t k = 0; k < n; ++k) {
    const Verdict v = node(t, t.arg(it, k), depth);
    if (!v.allowed) return v;
  }
  return {true, 0, Reason::ok};
}

// Every symbol the hearer receives, cited records unfolded: is one of them an intimate act or desire?
bool SpeechCheck::said_sensitive(const Tree& t, const Tree::Item& it, int depth) {
  if (!t.is_node(it)) {
    const sv s = t.text(it);
    if (is_cite(s))
      if (const Tree* inner = unfold(s, depth)) return said_sensitive(*inner, inner->root(), depth + 1);
    return (word_flags(s) & kHearerSensitive) != 0;
  }
  if (t.head(it) == "that" && t.size(it) > 0) return said_sensitive(t, t.arg(it, 0), depth);
  if ((word_flags(t.head(it)) & kHearerSensitive) != 0) return true;
  for (std::uint32_t k = 0; k < t.size(it); ++k)
    if (said_sensitive(t, t.arg(it, k), depth)) return true;
  return false;
}

}  // namespace

Verdict Governor::check_utterance(const TypedExpression& expression, const Party* speaker,
                                  std::span<const PartyBinding> parties, std::span<const Party* const> hearers,
                                  const RecordLookup& expand, bool said) const {
  if (!expression.ok()) return refuse(Reason::invalid_value);
  const Tree tree(expression);
  SpeechCheck check(speaker, parties, expand);
  if (said && check.said_sensitive(tree, tree.root(), 0)) {
    if (hearers.empty()) return refuse(Reason::d10_hearer);          // unknown hearers: a possible minor
    for (const Party* h : hearers)
      if ((h ? *h : kUnknown).may_be_minor()) return refuse(Reason::d10_hearer);
  }
  return check.node(tree, tree.root(), 0);
}

Verdict Governor::check_record(RecordKind kind, const TypedExpression& expression, const Party* owner,
                               std::span<const PartyBinding> parties, const RecordLookup& expand) const {
  if (static_cast<std::uint8_t>(kind) > static_cast<std::uint8_t>(RecordKind::plan)) return refuse(Reason::invalid_value);
  return check_utterance(expression, owner, parties, {}, expand, false);   // a record is not said
}

}  // namespace em::social
