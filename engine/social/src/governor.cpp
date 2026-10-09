#include "emergence/social/governor.h"

#include <algorithm>
#include <cstdlib>

namespace em::social {
namespace {

constexpr std::int16_t kAdultTenths = gen::kAdultAgeYears * 10;
const Party kUnknown{};

bool numeric(gen::Scale s) {
  return s == gen::Scale::bipolar10 || s == gen::Scale::unipolar10 || s == gen::Scale::qty || s == gen::Scale::ratio;
}

void bounds(gen::Scale s, int& lo, int& hi) {
  lo = -32768; hi = 32767;
  if (s == gen::Scale::bipolar10) { lo = -100; hi = 100; }
  if (s == gen::Scale::unipolar10) { lo = 0; hi = 100; }
}

}  // namespace

bool Party::may_be_minor() const {
  if (!resolved) return true;
  for (std::int16_t a : {real_age, believed_age, apparent_age})
    if (a < 0 || a < kAdultTenths) return true;     // unknown counts as minor (deny by default)
  return false;
}

void WriteLedger::roll(std::int32_t day, std::int32_t life_year) {
  if (day != day_index_) { day_index_ = day; day_.clear(); }
  if (life_year != life_year_) { life_year_ = life_year; year_.clear(); }
}

Verdict Governor::check_write(gen::Var var, std::int16_t old_value, std::int16_t proposed, WriteLedger& ledger,
                              std::uint32_t target, const Party* intimate_target, const Party* actor,
                              bool creating) const {
  const auto idx = static_cast<std::size_t>(var);
  if (idx >= gen::kVariables.size()) return {false, 0, Reason::unknown_variable};
  const gen::VariableSpec& v = gen::kVariables[idx];
  const bool model = v.writers & (gen::writer::T_jump | gen::writer::T_step | gen::writer::T_slow);
  if (v.engine_only || !model) return {false, 0, Reason::engine_owned};
  if (!numeric(v.scale)) return {false, 0, Reason::structured};
  int o = old_value, want = proposed;
  if (v.intimate && want > o) {
    const Party& t = intimate_target ? *intimate_target : kUnknown;
    const Party& a = actor ? *actor : kUnknown;
    if (a.may_be_minor() || t.may_be_minor()) return {false, 0, Reason::d10_intimate};
  }
  int lo, hi;
  bounds(v.scale, lo, hi);
  want = std::clamp(want, lo, hi);
  const int delta = want - o;
  const bool jump = v.writers & gen::writer::T_jump, stepw = v.writers & gen::writer::T_step;
  if (jump && (creating || !stepw)) return {true, static_cast<std::int16_t>(want), Reason::jump};
  int limit;
  std::int32_t* used;
  Reason book;
  if (stepw) { limit = v.rate_tenths; used = &ledger.day_moved(var, target); book = Reason::step; }
  else if (v.writers & gen::writer::T_slow) { limit = v.slow_tenths; used = &ledger.year_moved(var, target); book = Reason::slow; }
  else return {false, 0, Reason::no_writer};
  int d = std::clamp(delta, -int(v.step_tenths), int(v.step_tenths));
  const int left = std::max(0, limit - *used);
  d = std::clamp(d, -left, left);
  *used += std::abs(d);
  return {d != 0 || delta == 0, static_cast<std::int16_t>(o + d), d == delta ? book : Reason::clipped};
}

Verdict Governor::check_gesture(const GestureCall& call, const Party* actor) const {
  const auto gi = static_cast<std::size_t>(call.gesture);
  if (gi >= gen::kGestures.size()) return {false, 0, Reason::unknown_gesture};
  const gen::GestureSpec& g = gen::kGestures[gi];
  bool minor = (actor ? *actor : kUnknown).may_be_minor();
  int involved = 1;
  for (int i = 0; i < g.n_params; ++i) {
    const gen::ParamSpec& p = g.params[i];
    if (!p.party) continue;
    if (call.value[i] < 0 && call.party[i] == nullptr) continue;
    ++involved;
    if ((call.party[i] ? *call.party[i] : kUnknown).may_be_minor()) minor = true;
  }
  if (!minor) return {true, 0, Reason::ok};
  for (int i = 0; i < g.n_params; ++i) {
    const int val = call.value[i];
    if (val >= 0 && (g.params[i].intimate_mask >> val & 1)) return {false, 0, Reason::d10_value};
  }
  if (g.contact && involved > 1) {
    if (!g.minor_person_ok) return {false, 0, Reason::d10_person};
    for (int i = 0; i < g.n_params; ++i) {
      const gen::ParamSpec& p = g.params[i];
      if (!p.whitelisted) continue;
      const int val = call.value[i];
      if (val < 0 || !(p.minor_mask >> val & 1)) return {false, 0, Reason::d10_whitelist};
    }
  }
  return {true, 0, Reason::ok};
}

}  // namespace em::social
