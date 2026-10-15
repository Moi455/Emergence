// T14: the C++ governor judges SPEECH and RECORDS (check_utterance, check_record: D10, P30) and must agree with the
// Python oracle (catalogue/tools/governor.py) on every shared vector, reason code included. The vectors are
// governor_speech_vectors.inc, written by catalogue/tools/governor_vectors.py. D10 refusal tests only: the intimate
// sentences below are REFUSED, never produced for play.
#include <chrono>
#include <cstdio>
#include <map>
#include <string>
#include <vector>

#include "emergence/social/governor.h"
#include "emergence/social/language.h"
#include "emergence/testing/check.h"

using namespace em::social;

#include "governor_vectors.inc"
#include "governor_speech_vectors.inc"

namespace {

const Party* pal(int i) { return i < 0 ? nullptr : &kPalette[i]; }

const Parser& parser() {
  static const Parser p;
  return p;
}

// The library of cited records, parsed once as BARE propositions.
const std::map<std::string, TypedExpression, std::less<>>& library() {
  static const auto lib = [] {
    std::map<std::string, TypedExpression, std::less<>> m;
    for (const SpeechRecord& r : kSpeechRecords) m.emplace(r.ref, parser().parse(r.text, {.bare = true}));
    return m;
  }();
  return lib;
}

const RecordLookup& lookup() {
  static const RecordLookup f = [](std::string_view ref) -> const TypedExpression* {
    const auto it = library().find(ref);
    return it == library().end() ? nullptr : &it->second;
  };
  return f;
}

Verdict run(const SpeechCase& c, const TypedExpression& e, bool with_expand = true) {
  Governor g;
  std::vector<PartyBinding> parties;
  for (int i = 0; i < c.n_parties; ++i) parties.push_back({c.parties[i].symbol, pal(c.parties[i].party)});
  std::vector<const Party*> hearers;
  for (int i = 0; i < c.n_hearers; ++i) hearers.push_back(pal(c.hearers[i]));
  const RecordLookup none;
  const RecordLookup& expand = c.expand && with_expand ? lookup() : none;
  if (c.op < 2) return g.check_utterance(e, pal(c.speaker), parties, hearers, expand, c.op == 0);
  const auto kind = c.op < 7 ? static_cast<RecordKind>(c.op - 2) : static_cast<RecordKind>(99);
  return g.check_record(kind, e, pal(c.speaker), parties, expand);
}

}  // namespace

TEST(speech_vectors_match_oracle) {
  CHECK(std::size(kSpeechCases) >= 5000);
  int mismatches = 0, allowed = 0, refused = 0;
  std::map<std::string, int> by_reason;
  std::size_t index = 0;
  for (const SpeechCase& c : kSpeechCases) {
    const TypedExpression e = parser().parse(c.text, {.bare = c.bare});
    const Verdict v = run(c, e);
    (v.allowed ? allowed : refused)++;
    ++by_reason[std::string(to_string(v.reason))];
    if (v.reason != c.reason) {
      if (++mismatches <= 8)
        std::printf("  speech #%zu \"%s\" op=%d: got %.*s, expected %.*s\n", index, c.text, c.op,
                    static_cast<int>(to_string(v.reason).size()), to_string(v.reason).data(),
                    static_cast<int>(to_string(c.reason).size()), to_string(c.reason).data());
    }
    ++index;
  }
  std::printf("  speech vectors: %zu cases, %d allowed, %d refused, %d mismatches (", std::size(kSpeechCases), allowed,
              refused, mismatches);
  for (const auto& [reason, n] : by_reason) std::printf(" %s=%d", reason.c_str(), n);
  std::printf(" )\n");
  CHECK_EQ(mismatches, 0);
}

TEST(speech_throughput_in_decisions_per_second) {
  std::vector<TypedExpression> parsed;
  for (const SpeechCase& c : kSpeechCases) parsed.push_back(parser().parse(c.text, {.bare = c.bare}));
  const int rounds = 20;
  int sink = 0;
  auto t0 = std::chrono::steady_clock::now();
  for (int r = 0; r < rounds; ++r)
    for (std::size_t i = 0; i < std::size(kSpeechCases); ++i) sink += run(kSpeechCases[i], parsed[i]).allowed;
  const double check_s = std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count();
  t0 = std::chrono::steady_clock::now();
  for (int r = 0; r < rounds; ++r)
    for (const SpeechCase& c : kSpeechCases) {
      const TypedExpression e = parser().parse(c.text, {.bare = c.bare});
      sink += run(c, e).allowed;
    }
  const double both_s = std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count();
  const double n = static_cast<double>(rounds) * static_cast<double>(std::size(kSpeechCases));
  std::printf("  throughput: %.0f decisions/s (check only, %.2f us each), %.0f decisions/s (parse + check, %.2f us each) [%d]\n",
              n / check_s, 1e6 * check_s / n, n / both_s, 1e6 * both_s / n, sink > 0);
  CHECK(n / check_s > 1000.0);
}

// ---- D10 refusals (tests de refus uniquement) ------------------------------------------------------------

namespace {
const Party kAdult{300, 300, 300, true};
const Party kAdult2{450, 440, 460, true};
const Party kChild{90, 90, 90, true};
const Party kUnknownPerson{};
const Party kLooksYoung{250, 250, 160, true};

constexpr const char* kActAdultsOnly = "(assert (did @E1 touch @E2 (how romantic)))";   // docs/09 section 3, step 1
}  // namespace

TEST(d10_an_intimate_act_between_adults_is_refused_when_told_to_a_possible_minor) {
  Governor g;
  const TypedExpression e = parser().parse(kActAdultsOnly);
  CHECK(e.ok());
  const PartyBinding who[] = {{"@E1", &kAdult}, {"@E2", &kAdult2}};
  const Party* adults[] = {&kAdult2};
  CHECK(g.check_utterance(e, &kAdult, who, adults).allowed);                        // told to an adult: fine
  for (const Party* h : {&kChild, &kUnknownPerson, &kLooksYoung}) {
    const Party* heard[] = {&kAdult2, h};
    const Verdict v = g.check_utterance(e, &kAdult, who, heard);
    CHECK(!v.allowed);
    CHECK(v.reason == Reason::d10_hearer);
  }
  CHECK(g.check_utterance(e, &kAdult, who).reason == Reason::d10_hearer);          // unknown hearers
  const Party* null_hearer[] = {nullptr};
  CHECK(g.check_utterance(e, &kAdult, who, null_hearer).reason == Reason::d10_hearer);
}

TEST(d10_a_private_thought_is_not_a_speech_but_its_participants_still_count) {
  Governor g;
  const TypedExpression e = parser().parse("(did @E1 touch @E2 (how romantic))", {.bare = true});
  const PartyBinding adults[] = {{"@E1", &kAdult}, {"@E2", &kAdult2}};
  const PartyBinding with_child[] = {{"@E1", &kAdult}, {"@E2", &kChild}};
  CHECK(g.check_record(RecordKind::belief, e, &kAdult, adults).allowed);          // no hearer in a record
  CHECK(!g.check_record(RecordKind::belief, e, &kAdult, with_child).allowed);   // d10_value: the gesture itself
  CHECK(!g.check_record(RecordKind::belief, e, &kAdult).allowed);                 // unbound = unknown person
  CHECK(g.check_utterance(e, &kAdult, adults, {}, {}, false).allowed);                     // said = false
  CHECK(g.check_record(static_cast<RecordKind>(9), e, &kAdult, adults).reason == Reason::invalid_value);
}

TEST(d10_links_and_judgements_stay_social_facts_for_a_child_to_hear) {
  Governor g;
  const PartyBinding adults[] = {{"@E1", &kAdult}, {"@E2", &kAdult2}};
  const Party* child[] = {&kChild};
  for (const char* t : {"(assert (link @E1 spouse @E2))", "(assert (link @E1 lover @E2))"}) {
    const TypedExpression e = parser().parse(t);
    CHECK(e.ok());
    CHECK(g.check_utterance(e, &kAdult, adults, child).allowed);                    // P30, O22
  }
  const TypedExpression lover = parser().parse("(assert (link @E1 lover @E2))");
  const PartyBinding minor_lover[] = {{"@E1", &kAdult}, {"@E2", &kChild}};
  CHECK(g.check_utterance(lover, &kAdult, minor_lover, child).reason == Reason::d10_intimate);   // a child as a lover
}

TEST(a_cited_record_is_unfolded_and_checked_as_said_once_per_reference) {
  Governor g;
  const TypedExpression act = parser().parse("(did @E1 touch @E2 (how romantic))", {.bare = true});
  const TypedExpression chain = parser().parse("(believes @E2 b:1)", {.bare = true});
  int calls = 0;
  const RecordLookup expand = [&](std::string_view ref) -> const TypedExpression* {
    ++calls;
    return ref == "b:1" ? &act : ref == "b:2" ? &chain : nullptr;
  };
  const PartyBinding who[] = {{"@E1", &kAdult}, {"@E2", &kAdult2}};
  const Party* child[] = {&kChild};
  const TypedExpression says = parser().parse("(assert (did me speak (to @E2) (says (that b:2))))");
  CHECK(says.ok());
  CHECK(g.check_utterance(says, &kAdult, who, child, expand).reason == Reason::d10_hearer);    // b:2 -> b:1, unfolded
  CHECK(g.check_utterance(says, &kAdult, who, child).reason == Reason::unexpanded);            // no copy: refused
  const TypedExpression twice = parser().parse("(assert (and b:1 b:1))");
  calls = 0;
  g.check_utterance(twice, &kAdult, who, child, expand);
  CHECK_EQ(calls, 1);                                                                            // one lookup per reference
}

TEST(an_invalid_expression_is_refused) {
  Governor g;
  const TypedExpression e = parser().parse("(assert (no_such_word @E1))");
  CHECK(!e.ok());
  CHECK(g.check_utterance(e, &kAdult).reason == Reason::invalid_value);
}

EMERGENCE_TEST_MAIN()
