// The inner language (T13): parity of the C++ validator with the Python oracle on the shared vectors
// (language_vectors.inc, written by catalogue/tools/language_vectors.py), conversion to and from a Proposition,
// and the throughput of the parser.
#include <chrono>
#include <cstdio>
#include <cstring>
#include <string>

#include "emergence/social/language.h"
#include "emergence/testing/check.h"
#include "language_vectors.inc"

using namespace em::social;

namespace {
std::string join(const std::vector<LangProblem>& ps) {
  std::string s;
  for (const auto p : ps) { if (!s.empty()) s += ','; s += to_string(p); }
  return s;
}
std::string join(const std::vector<std::string>& v) {
  std::string s;
  for (const auto& x : v) { if (!s.empty()) s += ','; s += x; }
  return s;
}
PointerKinds parse_kinds(const char* spec) {
  PointerKinds out;
  std::string s = spec;
  std::size_t i = 0;
  while (i < s.size()) {
    std::size_t j = s.find(';', i);
    if (j == std::string::npos) j = s.size();
    const std::string item = s.substr(i, j - i);
    const auto eq = item.find('=');
    if (eq != std::string::npos) out[item.substr(0, eq)] = item.substr(eq + 1);
    i = j + 1;
  }
  return out;
}
}  // namespace

TEST(language_parity_with_the_python_oracle) {
  const Parser parser;
  int bad = 0, valid = 0, converted = 0, unconvertible = 0, with_intimate = 0, of_bad = 0;
  for (int i = 0; i < kLangVectorCount; ++i) {
    const LangVector& v = kLangVectors[i];
    const PointerKinds pk = parse_kinds(v.pointer_kinds);
    ParseOptions opt;
    opt.bare = v.bare;
    opt.pointer_kinds = &pk;
    const TypedExpression e = parser.parse(v.text, opt);
    const std::string codes = join(e.problems());
    of_bad += codes.find("of_bad") != std::string::npos;
    if (codes != v.codes) {
      if (++bad <= 10) std::printf("  vector %d: %s\n    expected [%s] got [%s]\n", i, v.text, v.codes, codes.c_str());
      continue;
    }
    if (!e.ok()) continue;
    ++valid;
    with_intimate += *v.intimate != 0;
    const std::string intimate = join(e.intimate_symbols());
    const std::string canon = *v.canonical ? v.canonical : v.text;
    if (intimate != v.intimate || e.canonical_text() != canon) {
      if (++bad <= 10) std::printf("  vector %d: %s\n    intimate [%s] vs [%s], canonical [%s]\n", i, v.text, v.intimate, intimate.c_str(), e.canonical_text().c_str());
      continue;
    }
    Proposition p;
    const ConvertStatus st = e.to_proposition(p);
    if (st == ConvertStatus::ok) {
      ++converted;
      const bool citation = e.canonical_text().find('(') == std::string::npos;
      if (!p.well_formed() || (!citation && Parser::to_text(p) != canon) || (citation && Parser::to_text(p) != canon)) {
        if (++bad <= 10) std::printf("  vector %d: %s\n    round trip gave [%s]\n", i, v.text, Parser::to_text(p).c_str());
      }
    } else {
      ++unconvertible;   // a count, pointer or name beyond its field, or a non-canonical number: refused, never wrapped
    }
  }
  std::printf("  %d vectors, %d valid (%d converted to a Proposition, %d out of range or non-canonical), %d mismatches\n",
              kLangVectorCount, valid, converted, unconvertible, bad);
  std::printf("  %d valid vectors carry intimate symbols (D10 detection, parity on intimate_symbols())\n", with_intimate);
  CHECK_EQ(bad, 0);
  CHECK(with_intimate >= 80);   // the catalogue flags 8 words; ~350 vectors use them, the rest are refused
  CHECK_EQ(of_bad, 0);   // of_bad is unreachable in the oracle too: see language.h
  CHECK(valid > 20000);
  CHECK(converted > valid * 9 / 10);
}

TEST(language_proposition_fields) {
  const Parser parser;
  const auto conv = [&](const char* t, bool bare, Proposition& p) { return parser.parse(t, {.bare = bare}).to_proposition(p); };
  Proposition p;
  CHECK(conv("(owns me @T1)", true, p) == ConvertStatus::ok);
  CHECK_EQ(p.size(), 3);
  CHECK(Parser::to_text(p) == std::string("(owns me @T1)"));
  CHECK(Proposition::tag(p.symbol(2)) == Proposition::kRef);
  CHECK(conv("(has @E1 silver_coin:3)", true, p) == ConvertStatus::ok);
  CHECK(Proposition::tag(p.symbol(2)) == Proposition::kKindQty);
  CHECK(Parser::to_text(p) == std::string("(has @E1 silver_coin:3)"));
  CHECK(conv("b:7", true, p) == ConvertStatus::ok);
  CHECK(Parser::to_text(p) == std::string("b:7"));
  CHECK(conv("(owns me @T1048576)", true, p) == ConvertStatus::out_of_range);
  CHECK(conv("(owns me @T01)", true, p) == ConvertStatus::noncanonical);
  CHECK(conv("(owns me no_such_word)", true, p) == ConvertStatus::not_valid);
  CHECK(Parser::to_text(Proposition()).empty());
}

TEST(language_of_bad_is_unreachable) {
  // (of QUANTITY GROUP): the group is a list or a symbol, so the last branch of the oracle never runs.
  const Parser parser;
  for (const char* t : {"(assert (dead (of 2 x y)))", "(assert (dead (of 2)))", "(assert (dead (of)))", "(assert (dead (of 2 (dead @E1))))"})
  {
      const TypedExpression e = parser.parse(t);
      for (const auto p : e.problems()) CHECK(p != LangProblem::of_bad);
    }
}

TEST(language_refusals_have_stable_codes) {
  const Parser parser;
  const auto code = [&](const char* t, bool bare = false) { return join(parser.parse(t, {.bare = bare}).problems()); };
  CHECK(code("(owns me)", true) == std::string("pred_arity"));
  CHECK(code("(assert (owns me @T1)") == std::string("parse_missing_close"));
  CHECK(code("(owns me @T1)") == std::string("utt_head"));
  CHECK(code("(assert (owns me @T\xd9\xa3))") == std::string("charset"));
  CHECK(code(std::string(1001, 'a').c_str()) == std::string("too_long"));
  CHECK(std::string(to_string(LangProblem::pointers_max)) == std::string("pointers_max"));
}

TEST(language_throughput) {
  const Parser parser;
  std::vector<PointerKinds> pks(static_cast<std::size_t>(kLangVectorCount));
  for (int i = 0; i < kLangVectorCount; ++i) pks[static_cast<std::size_t>(i)] = parse_kinds(kLangVectors[i].pointer_kinds);
  using clock = std::chrono::steady_clock;
  long n = 0, n_valid = 0, sink = 0;
  const auto t0 = clock::now();
  for (int round = 0; round < 4; ++round)
    for (int i = 0; i < kLangVectorCount; ++i) {
      ParseOptions opt;
      opt.bare = kLangVectors[i].bare;
      opt.pointer_kinds = &pks[static_cast<std::size_t>(i)];
      const TypedExpression e = parser.parse(kLangVectors[i].text, opt);
      Proposition p;
      if (e.ok()) { ++n_valid; sink += static_cast<long>(e.to_proposition(p) == ConvertStatus::ok); }
      sink += static_cast<long>(e.problems().size());
      ++n;
    }
  const double s = std::chrono::duration<double>(clock::now() - t0).count();
  std::printf("  throughput: %ld expressions (%ld valid, with conversion) in %.3f s = %.0f propositions/s (%.1f us each) [%ld]\n",
              n, n_valid, s, static_cast<double>(n) / s, s / static_cast<double>(n) * 1e6, sink);
  CHECK(n / s > 20000.0);   // the game needs a few hundred per second; this is a safety margin, not a target
}

EMERGENCE_TEST_MAIN()
