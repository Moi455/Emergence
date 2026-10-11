// The C++ governor must agree with its Python oracle (catalogue/tools/governor.py) on every shared vector (the
// REASON CODE, not only allowed / refused), and must hold the hard rule D10 on its own.
#include <algorithm>
#include <array>
#include <cstdio>
#include <iterator>
#include <limits>
#include <span>
#include <vector>

#include "emergence/social/governor.h"
#include "emergence/testing/check.h"

using namespace em::social;

#include "governor_vectors.inc"

namespace {

const Party* pal(int i) { return i < 0 ? nullptr : &kPalette[i]; }
constexpr int kShown = 5;   // mismatches printed per test

WriteRequest request(gen::Var var, int old_value, int proposed, std::uint32_t target = 0) {
  WriteRequest r;
  r.var = var;
  r.old_value = static_cast<std::int16_t>(old_value);
  r.proposed = static_cast<std::int16_t>(proposed);
  r.target = target;
  return r;
}

}  // namespace

// ---- the generated tables --------------------------------------------------------------------------------

TEST(gesture_table_is_sorted_like_the_model_gesture_head) {
  CHECK(std::is_sorted(gen::kGestureNames.begin(), gen::kGestureNames.end()));
  CHECK_EQ(gen::kGestureNames.size(), gen::kGestures.size());
  CHECK_EQ(static_cast<std::size_t>(gen::Gesture::kCount), gen::kGestures.size());
  for (std::size_t i = 0; i < gen::kGestures.size(); ++i) CHECK(gen::kGestures[i].id == gen::kGestureNames[i]);
  CHECK(gen::kGestureNames[static_cast<std::size_t>(gen::Gesture::touch)] == "touch");
}

TEST(variable_table_is_sorted_and_flags_self_holders) {
  CHECK(std::is_sorted(gen::kVarNames.begin(), gen::kVarNames.end()));
  const auto& need = gen::kVariables[static_cast<std::size_t>(gen::Var::need_intimacy)];
  const auto& relation = gen::kVariables[static_cast<std::size_t>(gen::Var::r_attraction)];
  CHECK(need.intimate && need.self_holder);
  CHECK(relation.intimate && !relation.self_holder);
}

TEST(a_call_starts_with_every_value_absent) {
  GestureCall call;
  for (int i = 0; i < gen::kMaxParams; ++i) CHECK_EQ(call.value[i], -1);
}

// ---- ages ------------------------------------------------------------------------------------------------

TEST(ages_are_floored_toward_minor) {
  CHECK_EQ(Party::from_years(17.96), 179);
  CHECK_EQ(Party::from_years(17.94), 179);
  CHECK_EQ(Party::from_years(18.0), 180);
  CHECK_EQ(Party::from_years(18.04), 180);
  CHECK_EQ(Party::from_years(std::numeric_limits<double>::quiet_NaN()), -1);
  CHECK_EQ(Party::from_years(std::numeric_limits<double>::infinity()), -1);
  CHECK_EQ(Party::from_years(-3.0), -1);
  CHECK_EQ(Party::from_years(1.0e9), -1);                         // absurd: unknown, a possible minor (review 10)
  CHECK_EQ(Party::from_years(1.0e308), -1);
  const Party just_under{179, 179, 179, true}, of_age{180, 180, 180, true}, thing{5, 5, 5, false, false};
  CHECK(just_under.may_be_minor());
  CHECK(!of_age.may_be_minor());
  CHECK(!thing.may_be_minor());                                   // a thing is never a minor
}

TEST(palette_ages_match_from_years) {
  int mismatches = 0;
  for (std::size_t i = 0; i < std::size(kPalette); ++i) {
    const Party& p = kPalette[i];
    const std::int16_t want[3] = {p.real_age, p.believed_age, p.apparent_age};
    for (int k = 0; k < 3; ++k)
      if (Party::from_years(kPaletteYears[i][k]) != want[k]) ++mismatches;
  }
  CHECK_EQ(mismatches, 0);
}

// ---- vectors from the Python oracle ----------------------------------------------------------------------

TEST(write_vectors_match_oracle) {
  Governor g;
  WriteLedger led;
  int seq = -1, mismatches = 0;
  std::size_t index = 0;
  CHECK(std::size(kWrites) > 1000);
  for (const WriteCase& c : kWrites) {
    if (c.seq != seq) { led = WriteLedger(); seq = c.seq; }
    led.roll(c.day, c.life_year);
    WriteRequest r = request(c.var, c.old_v, c.proposed, static_cast<std::uint32_t>(c.target));
    r.intimate_target = pal(c.intimate_target);
    r.actor = pal(c.actor);
    r.creating = c.creating;
    const Verdict v = g.check_write(r, led);
    if (v.reason != c.reason || v.allowed != c.allowed || v.value != c.value) {
      if (++mismatches <= kShown)
        std::printf("  write #%zu (seq %d): got %.*s allowed=%d value=%d, expected %.*s allowed=%d value=%d\n", index,
                    c.seq, static_cast<int>(to_string(v.reason).size()), to_string(v.reason).data(), v.allowed, v.value,
                    static_cast<int>(to_string(c.reason).size()), to_string(c.reason).data(), c.allowed, c.value);
    }
    ++index;
  }
  CHECK_EQ(mismatches, 0);
}

TEST(check_writes_vectors_match_oracle) {
  Governor g;
  int mismatches = 0;
  CHECK(std::size(kWritesCases) > 100);
  for (const WritesCase& c : kWritesCases) {
    std::array<WriteKey, 10> keys{};
    std::array<Verdict, 10> out{};
    std::size_t expected_kept = 0;
    for (int i = 0; i < c.n; ++i) {
      keys[i] = {static_cast<std::uint32_t>(c.target[i]), c.var[i]};
      if (c.reason[i] == Reason::ok) ++expected_kept;
    }
    const std::size_t kept = g.check_writes(std::span<const WriteKey>(keys.data(), c.n), out);
    if (kept != expected_kept || kept > kWritesPerDecision) ++mismatches;
    for (int i = 0; i < c.n; ++i)
      if (out[i].reason != c.reason[i] || out[i].allowed != (c.reason[i] == Reason::ok)) ++mismatches;
  }
  CHECK_EQ(mismatches, 0);
}

TEST(gesture_vectors_match_oracle) {
  Governor g;
  int mismatches = 0;
  std::size_t index = 0;
  CHECK(std::size(kGestureCases) > 1000);
  for (const GestureCase& c : kGestureCases) {
    GestureCall call;
    call.gesture = c.gesture;
    for (int i = 0; i < gen::kMaxParams; ++i) {
      call.value[i] = c.value[i];
      call.party[i] = pal(c.party[i]);
    }
    const Verdict v = g.check_gesture(call, pal(c.actor), c.executed);
    if (v.reason != c.reason || v.allowed != (c.reason == Reason::ok)) {
      if (++mismatches <= kShown)
        std::printf("  gesture #%zu (%.*s): got %.*s, expected %.*s\n", index,
                    static_cast<int>(c.gesture < gen::Gesture::kCount ? gen::kGestureNames[static_cast<std::size_t>(c.gesture)].size() : 1),
                    c.gesture < gen::Gesture::kCount ? gen::kGestureNames[static_cast<std::size_t>(c.gesture)].data() : "?",
                    static_cast<int>(to_string(v.reason).size()), to_string(v.reason).data(),
                    static_cast<int>(to_string(c.reason).size()), to_string(c.reason).data());
    }
    ++index;
  }
  CHECK_EQ(mismatches, 0);
}

// ---- hard rule D10 (refusals) ----------------------------------------------------------------------------

namespace {

// A touch call with the parameters set by name; `manner` and the others are value indices of the catalogue.
GestureCall touch_call(const Party* target, int with, int zone, int manner) {
  GestureCall call;
  call.gesture = gen::Gesture::touch;
  const gen::GestureSpec& t = gen::kGestures[static_cast<std::size_t>(gen::Gesture::touch)];
  for (int i = 0; i < t.n_params; ++i) {
    const auto& p = t.params[i];
    if (p.name == "target") { call.value[i] = 0; call.party[i] = target; }
    if (p.name == "manner") call.value[i] = static_cast<std::int8_t>(manner);
    if (p.name == "with") call.value[i] = static_cast<std::int8_t>(with);
    if (p.name == "contact_zone") call.value[i] = static_cast<std::int8_t>(zone);
  }
  return call;
}

}  // namespace

TEST(d10_romantic_touch_refused_with_a_child) {
  Governor g;
  const Party adult{300, 300, 310, true}, child{90, 90, 90, true};
  const Verdict v = g.check_gesture(touch_call(&child, 0, 4, 3), &adult);   // romantic manner, hand, hands
  CHECK(!v.allowed);
  CHECK(v.reason == Reason::d10_value);
}

TEST(d10_unknown_or_name_only_person_counts_as_a_minor) {
  Governor g;
  const Party adult{300, 300, 310, true}, name_only{250, 250, 250, false}, just_under{179, 179, 179, true};
  CHECK(!g.check_gesture(touch_call(&name_only, 0, 4, 3), &adult).allowed);
  CHECK(!g.check_gesture(touch_call(&just_under, 0, 4, 3), &adult).allowed);
  CHECK(!g.check_gesture(touch_call(nullptr, 0, 4, 3), &adult).allowed);    // the target is not identified
  CHECK(!g.check_gesture(touch_call(&adult, 0, 4, 3), nullptr).allowed);    // the actor is unknown
}

TEST(d10_whitelisted_params_are_required_with_a_minor) {
  Governor g;
  const Party adult{300, 300, 310, true}, child{90, 90, 90, true};
  GestureCall call = touch_call(&child, 0, 4, 3);
  const gen::GestureSpec& t = gen::kGestures[static_cast<std::size_t>(gen::Gesture::touch)];
  for (int i = 0; i < t.n_params; ++i)
    if (t.params[i].whitelisted) call.value[i] = -1;
  CHECK(!g.check_gesture(call, &adult).allowed);
}

TEST(a_thing_never_counts_as_a_party_but_a_child_does) {
  Governor g;
  const Party adult{300, 300, 310, true}, child{90, 90, 90, true}, thing{-1, -1, -1, true, false};
  GestureCall call;
  call.gesture = gen::Gesture::search;                       // search is a contact gesture that may not involve a minor
  const gen::GestureSpec& s = gen::kGestures[static_cast<std::size_t>(gen::Gesture::search)];
  for (int i = 0; i < s.n_params; ++i)
    if (s.params[i].party) { call.value[i] = 0; call.party[i] = &thing; }
  CHECK(g.check_gesture(call, &adult).allowed);
  for (int i = 0; i < s.n_params; ++i)
    if (s.params[i].party) call.party[i] = &child;
  const Verdict v = g.check_gesture(call, &adult);
  CHECK(!v.allowed);
  CHECK(v.reason == Reason::d10_person);
}

TEST(d10_party_param_left_out_of_a_contact_gesture_counts_an_unknown_person) {
  Governor g;
  const Party adult{300, 300, 310, true};
  GestureCall call;
  call.gesture = gen::Gesture::search;
  const Verdict v = g.check_gesture(call, &adult);           // the person is missing altogether
  CHECK(!v.allowed);
  CHECK(v.reason == Reason::d10_person);
}

TEST(d10_attraction_never_rises_toward_a_minor) {
  Governor g;
  WriteLedger led;
  const Party adult{300, 300, 310, true}, child{90, 90, 90, true};
  WriteRequest r = request(gen::Var::r_attraction, 0, 5, 2);
  r.actor = &adult; r.intimate_target = &child;
  CHECK(g.check_write(r, led).reason == Reason::d10_intimate);
  r.intimate_target = nullptr;                               // deny by default
  CHECK(g.check_write(r, led).reason == Reason::d10_intimate);
  r.intimate_target = &adult;
  CHECK(g.check_write(r, led).allowed);
}

TEST(d10_own_drive_looks_at_the_actor_only_and_creation_compares_with_zero) {
  Governor g;
  WriteLedger led;
  const Party adult{300, 300, 310, true}, child{90, 90, 90, true};
  WriteRequest r = request(gen::Var::need_intimacy, 0, 5);
  r.actor = &adult; r.intimate_target = &child;             // the target does not matter for one's own drive
  CHECK(g.check_write(r, led).allowed);
  r.actor = &child;
  CHECK(g.check_write(r, led).reason == Reason::d10_intimate);
  WriteRequest c = request(gen::Var::r_attraction, 50, 20);  // lowered, but the record is being created
  c.actor = &child; c.intimate_target = &adult; c.creating = true;
  CHECK(g.check_write(c, led).reason == Reason::d10_intimate);
  c.creating = false;                                        // a decrease is never refused by D10
  CHECK(g.check_write(c, led).allowed);
}

// ---- values, writes, ledger ------------------------------------------------------------------------------

TEST(engine_owns_the_body) {
  Governor g;
  WriteLedger led;
  const Verdict v = g.check_write(request(gen::Var::pain, 20, 0, 1), led);
  CHECK(!v.allowed);
  CHECK(v.reason == Reason::engine_owned);
}

TEST(unknown_variable_and_unknown_gesture_are_refused) {
  Governor g;
  WriteLedger led;
  CHECK(g.check_write(request(gen::Var::kCount, 0, 1), led).reason == Reason::unknown_variable);
  GestureCall call;
  call.gesture = gen::Gesture::kCount;
  CHECK(g.check_gesture(call, nullptr).reason == Reason::unknown_gesture);
}

TEST(gesture_value_indices_are_validated) {
  Governor g;
  const Party adult{300, 300, 310, true};
  const gen::GestureSpec& t = gen::kGestures[static_cast<std::size_t>(gen::Gesture::touch)];
  int enum_param = -1;
  for (int i = 0; i < t.n_params; ++i)
    if (t.params[i].type == gen::ParamType::enum_) enum_param = i;
  CHECK(enum_param >= 0);
  GestureCall call;
  call.gesture = gen::Gesture::touch;
  call.value[enum_param] = static_cast<std::int8_t>(t.params[enum_param].n_values);       // one past the last value
  CHECK(g.check_gesture(call, &adult).reason == Reason::invalid_value);
  call.value[enum_param] = -2;
  CHECK(g.check_gesture(call, &adult).reason == Reason::invalid_value);
  call.value[enum_param] = -1;
  call.value[t.n_params] = 0;                                                              // a param touch does not have
  CHECK(g.check_gesture(call, &adult).reason == Reason::invalid_value);
}

TEST(executed_gesture_needs_every_non_optional_param) {
  Governor g;
  const Party adult{300, 300, 310, true};
  GestureCall call;
  call.gesture = gen::Gesture::wait;                         // a gesture without contact: nothing else to refuse
  const gen::GestureSpec& w = gen::kGestures[static_cast<std::size_t>(gen::Gesture::wait)];
  CHECK(g.check_gesture(call, &adult, false).allowed);
  bool needs = false;
  for (int i = 0; i < w.n_params; ++i) needs = needs || !w.params[i].optional;
  CHECK(needs);
  CHECK(g.check_gesture(call, &adult, true).reason == Reason::invalid_value);
  for (int i = 0; i < w.n_params; ++i)
    call.value[i] = 0;
  CHECK(g.check_gesture(call, &adult, true).allowed);
}

TEST(sparse_writes_keep_one_per_key_and_four_per_decision) {
  Governor g;
  const WriteKey keys[] = {{1, gen::Var::fear}, {1, gen::Var::fear}, {2, gen::Var::fear}, {1, gen::Var::anger},
                           {3, gen::Var::fear}, {4, gen::Var::fear}, {2, gen::Var::fear}, {5, gen::Var::fear}};
  std::array<Verdict, 8> out{};
  CHECK_EQ(g.check_writes(keys, out), kWritesPerDecision);
  const Reason want[] = {Reason::ok, Reason::duplicate, Reason::ok, Reason::ok, Reason::ok,
                         Reason::too_many_writes, Reason::duplicate, Reason::too_many_writes};
  for (std::size_t i = 0; i < out.size(); ++i) CHECK(out[i].reason == want[i]);
}

TEST(relation_steps_then_hits_the_daily_rate_then_rolls_over) {
  Governor g;
  WriteLedger led;
  int x = 0;
  for (int i = 0; i < 40; ++i) {
    WriteRequest r = request(gen::Var::r_affection, x, x + 100, 7);
    const Verdict v = g.check_write(r, led);
    x = v.value;
  }
  const gen::VariableSpec& spec = gen::kVariables[static_cast<std::size_t>(gen::Var::r_affection)];
  CHECK_EQ(x, spec.rate_tenths);
  CHECK_EQ(led.moved_today(gen::Var::r_affection, 7), spec.rate_tenths);
  CHECK_EQ(led.moved_today(gen::Var::r_affection, 8), 0);       // another target has its own account
  led.roll(1, 0);
  CHECK_EQ(led.moved_today(gen::Var::r_affection, 7), 0);       // a new day, a new account
  const int before = x;
  x = g.check_write(request(gen::Var::r_affection, x, x + 100, 7), led).value;
  CHECK(x > before);
  led.roll(0, 0);                                               // time never goes back (review 11)
  CHECK_EQ(led.day(), 1);
  CHECK(led.moved_today(gen::Var::r_affection, 7) > 0);         // an oscillating clock refills nothing
  const std::vector<LedgerEntry> saved(led.entries().begin(), led.entries().end());
  WriteLedger copy;                                             // and what was saved restores
  CHECK(copy.restore(led.day(), led.life_year(), saved));
  CHECK_EQ(copy.moved_today(gen::Var::r_affection, 7), led.moved_today(gen::Var::r_affection, 7));
}

TEST(ledger_can_be_saved_and_restored) {
  Governor g;
  WriteLedger a;
  for (std::uint32_t t = 1; t <= 3; ++t) g.check_write(request(gen::Var::r_affection, 0, 100, t), a);
  g.check_write(request(gen::Var::assurance, 0, 100, 0), a);
  a.roll(0, 2);
  g.check_write(request(gen::Var::assurance, 0, 100, 0), a);
  const std::vector<LedgerEntry> saved(a.entries().begin(), a.entries().end());
  WriteLedger b;
  CHECK(b.restore(a.day(), a.life_year(), saved));
  CHECK_EQ(b.entries().size(), a.entries().size());
  const Verdict va = g.check_write(request(gen::Var::r_affection, 0, 100, 1), a);
  const Verdict vb = g.check_write(request(gen::Var::r_affection, 0, 100, 1), b);
  CHECK(va.reason == vb.reason && va.value == vb.value);
  std::vector<LedgerEntry> twice = saved;
  twice.push_back(saved.front());                               // a duplicated (target, variable) is refused
  CHECK(!b.restore(0, 0, twice));
  CHECK_EQ(b.entries().size(), std::size_t{0});
  std::vector<LedgerEntry> bad = saved;
  bad.front().reserved = 1;
  CHECK(!b.restore(0, 0, bad));
  // review 10: a saved ledger is untrusted input
  const auto refused = [&](auto mutate) {
    std::vector<LedgerEntry> v = saved;
    mutate(v.front());
    return !b.restore(a.day(), a.life_year(), v) && b.entries().empty();
  };
  CHECK(refused([](LedgerEntry& e) { e.day_moved = std::numeric_limits<std::int32_t>::min(); }));
  CHECK(refused([](LedgerEntry& e) { e.year_moved = -1; }));
  CHECK(refused([](LedgerEntry& e) { e.day_moved = WriteLedger::kMaxMoved + 1; }));
  CHECK(refused([](LedgerEntry& e) { e.var = static_cast<std::uint16_t>(gen::kVariables.size()); }));
  CHECK(refused([&](LedgerEntry& e) { e.day_stamp = a.day() + 1; }));
  CHECK(refused([&](LedgerEntry& e) { e.year_stamp = a.life_year() + 1; }));
  CHECK(b.restore(a.day(), a.life_year(), saved));
}

TEST(check_writes_with_a_short_output_keeps_nothing) {
  Governor g;
  const std::array<WriteKey, 6> keys{WriteKey{1, gen::Var::r_affection}, WriteKey{2, gen::Var::r_affection},
                                     WriteKey{3, gen::Var::r_affection}, WriteKey{4, gen::Var::r_affection},
                                     WriteKey{5, gen::Var::r_affection}, WriteKey{6, gen::Var::r_affection}};
  std::array<Verdict, 3> out{};
  CHECK_EQ(g.check_writes(keys, out), std::size_t{0});
  for (const Verdict& v : out) CHECK(!v.allowed && v.reason == Reason::invalid_value);
}

TEST(an_absent_param_that_cannot_be_a_person_is_not_an_unknown_person) {
  Governor g;                                                   // review 11: put without `where`, adult actor
  GestureCall call;
  call.gesture = gen::Gesture::put;
  const gen::GestureSpec& spec = gen::kGestures[static_cast<std::size_t>(gen::Gesture::put)];
  const Party thing{-1, -1, -1, true, false};
  for (int i = 0; i < spec.n_params; ++i)
    if (spec.params[i].name == "item") { call.value[i] = 0; call.party[i] = &thing; }
  CHECK(g.check_gesture(call, &kPalette[0]).reason == Reason::ok);
}

TEST(speech_content_is_refused_until_the_language_port) {
  Governor g;
  GestureCall call;
  call.gesture = gen::Gesture::speak;
  const gen::GestureSpec& spec = gen::kGestures[static_cast<std::size_t>(gen::Gesture::speak)];
  int content = -1;
  for (int i = 0; i < spec.n_params; ++i)
    if (spec.params[i].type == gen::ParamType::expression) content = i;
  CHECK(content >= 0);
  call.value[content] = 0;
  CHECK(g.check_gesture(call, &kPalette[0]).reason == Reason::structured);
}

TEST(a_full_ledger_denies_a_new_key_until_entries_expire) {
  Governor g;
  WriteLedger led;
  for (std::uint32_t t = 1; t <= WriteLedger::kCapacity; ++t)
    CHECK(g.check_write(request(gen::Var::r_affection, 0, 100, t), led).allowed);
  const Verdict full = g.check_write(request(gen::Var::r_affection, 0, 100, 1000), led);
  CHECK(!full.allowed);
  CHECK(full.reason == Reason::ledger_full);                    // explicit, not a silent clip (review 10)
  CHECK_EQ(full.value, 0);
  led.roll(1, 0);                                               // a new game day: the old entries are dead
  CHECK(g.check_write(request(gen::Var::r_affection, 0, 100, 1000), led).allowed);
  CHECK_EQ(led.entries().size(), WriteLedger::kCapacity);       // a dead slot was reused, the table did not grow
}

EMERGENCE_TEST_MAIN()
