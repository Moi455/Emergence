#include "emergence/social/governor.h"

#include <algorithm>
#include <cmath>
#include <cstdlib>
#include <limits>

namespace em::social {
namespace {

constexpr int kAdultTenths = gen::kAdultAgeYears * 10;
const Party kUnknown{};

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

// ---- Party -----------------------------------------------------------------------------------------------

bool Party::may_be_minor() const {
  if (!person) return false;
  if (!resolved) return true;
  for (std::int16_t a : {real_age, believed_age, apparent_age})
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
    case Reason::kCount: break;
  }
  return "?";
}

// ---- WriteLedger -----------------------------------------------------------------------------------------

void WriteLedger::roll(std::int32_t day, std::int32_t life_year) {
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

bool WriteLedger::restore(std::int32_t day, std::int32_t life_year, std::span<const LedgerEntry> saved) {
  size_ = 0;
  entries_.fill(LedgerEntry{});
  bool good = saved.size() <= kCapacity;
  for (std::size_t i = 0; good && i < saved.size(); ++i) {
    const LedgerEntry& e = saved[i];
    good = e.reserved == 0 && e.var < gen::kVariables.size() && e.day_moved >= 0 && e.day_moved <= kMaxMoved &&
           e.year_moved >= 0 && e.year_moved <= kMaxMoved && e.day_stamp <= day && e.year_stamp <= life_year;
    for (std::size_t j = 0; good && j < i; ++j)
      good = !(saved[j].target == saved[i].target && saved[j].var == saved[i].var);
  }
  day_ = day;
  life_year_ = life_year;
  lock_day_ = lock_year_ = !good;                 // a corrupt save locks the bounds, it never refills them
  if (!good) return false;
  std::copy(saved.begin(), saved.end(), entries_.begin());
  size_ = saved.size();
  return true;
}

// ---- Governor: writes ------------------------------------------------------------------------------------

Verdict Governor::check_write(const WriteRequest& r, WriteLedger& ledger) const {
  const auto idx = static_cast<std::size_t>(r.var);
  if (idx >= gen::kVariables.size()) return refuse(Reason::unknown_variable);
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
  if (gi >= gen::kGestures.size()) return refuse(Reason::unknown_gesture);
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
    const bool valid = p.type == gen::ParamType::enum_ ? (val >= 0 && val < p.n_values) : val == 0;
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

}  // namespace em::social
