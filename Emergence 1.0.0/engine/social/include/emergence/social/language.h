// The inner language in C++ (T13): parser and TYPED validator of the S-expressions the NPCs write and read.
// Port of catalogue/tools/language.py (the ORACLE): same verdicts, same problems in the same order. Each problem
// has a stable code (LangProblem, to_string() = the code used by the shared vectors, tests/language_vectors.inc).
//
//   Parser parser;                                         // uses the generated vocabulary (src/language_tables.inc)
//   TypedExpression e = parser.parse("(offer (if ...))");  // utterance: (MOOD PROP) or (FORMULA [UTTERANCE])
//   TypedExpression r = parser.parse("(owns me @T1)", {.bare = true});   // content of a record: no mood
//   e.ok(); e.problems();                                  // empty list = valid
//   Proposition p; e.to_proposition(p);                    // symbols of vocab_gen.h (kWords / kKinds), <= 20
//   Parser::to_text(p);                                    // and back to the canonical text
//
// Limits: the grammar itself has none on a count or a pointer number (the oracle accepts silver_coin:99999);
// 8192 and more in a count (kKindQty), 2^20 in a pointer, 2^24 in a number or a name are refused ONLY by
// to_proposition() (ConvertStatus::out_of_range), never by parse(). LangProblem::of_bad is kept for the numbering of
// the codes but is unreachable, in the oracle (its last branch) and here; the test language_of_bad_is_unreachable
// and the vectors check that it never appears.
// No hazard, no float, no global mutable state: a Parser is immutable and may be shared between threads.
#pragma once
#include <cstdint>
#include <map>
#include <memory>
#include <string>
#include <string_view>
#include <vector>

#include "emergence/social/state_types.h"

namespace em::social {

// Stable codes of the problems (one per message of the Python validator). The order is the order of the shared
// vectors' code list; never reorder, only append.
enum class LangProblem : std::uint8_t {
  parse_trailing, parse_not_list, parse_end, parse_close, parse_head, parse_missing_close,
  too_many_symbols, hole_misplaced, too_deep,
  utt_not_list, mood_arity, formula_pointer, formula_extra, utt_head,
  not_proposition, second_mood, described_as_prop, logic_arity, that_target, wrap_arity, timeop_arity, not_predicate,
  pred_arity, arg_class,
  time_mark_node, span_shape, span_count, span_unit, for_duration, unknown_symbol, bad_quantity, not_time_mark,
  did_shape, not_gesture, gesture_target, too_many_roles, role_bad, role_twice, says_frame, says_shape, how_bad,
  role_shape, role_manner, role_none, role_accept, role_held,
  wh_outside, arg_cannot, arg_node,
  described_empty, described_order, described_words, described_expected, clause_head, clause_holes,
  of_expected, of_arity, of_quantity, of_group_head, of_not_group, of_bad,
  pointers_max,
  too_long, charset,   // checks of the wrapper (text limits of ai/tok2/proposition.py), before the grammar
  kCount
};
std::string_view to_string(LangProblem p);   // the stable code, e.g. "pred_arity"

inline constexpr int kLangMaxSymbols = 20, kLangMaxDepth = 2, kLangMaxPointers = 3, kLangMaxRoles = 3;
inline constexpr std::size_t kLangMaxText = 1000;

// pointer -> kind word of its record (@T1: knife, @L1: forest); gives the validator the class of a pointer.
using PointerKinds = std::map<std::string, std::string, std::less<>>;

struct ParseOptions {
  bool bare = false;                          // a bare proposition (record content), or a citation "b:7"
  const PointerKinds* pointer_kinds = nullptr;
};

enum class ConvertStatus : std::uint8_t {
  ok, not_valid,
  out_of_range,    // a pointer, name, number or count that does not fit its 24-bit field
  noncanonical,    // a leading zero, or "kind:" without a count: the text would not come back identical
};

// A validated (or refused) expression: the text, its tree, its problems.
class TypedExpression {
 public:
  bool ok() const { return problems_.empty(); }
  const std::vector<LangProblem>& problems() const { return problems_; }
  const std::string& text() const { return text_; }
  int symbol_count() const;                                  // heads and leaves (parentheses do not count)
  std::string canonical_text() const;                        // one space between symbols, none around parentheses
  std::vector<std::string> intimate_symbols() const;         // D10: symbols flagged intimate (the governor decides)
  ConvertStatus to_proposition(Proposition& out) const;      // prefix order + children counts; needs ok()

 private:
  friend class Parser;
  friend struct LangBuilder;   // parser, validator and converter (language.cpp)
  struct Item { std::uint32_t off = 0, len = 0; std::int32_t node = -1; };   // node >= 0: a list
  struct Node { Item head; std::uint32_t first = 0, n = 0; };                // args: args_[first .. first + n)
  std::string_view sv(const Item& i) const { return std::string_view(text_).substr(i.off, i.len); }
  void unparse(const Item& i, std::string& out) const;

  std::string text_;
  std::vector<Node> nodes_;
  std::vector<Item> args_;
  Item root_;
  std::vector<LangProblem> problems_;
};

class LanguageVocabulary;   // generated tables behind lookups (language.cpp)

class Parser {
 public:
  Parser();
  ~Parser();
  Parser(Parser&&) noexcept;
  Parser& operator=(Parser&&) noexcept;

  TypedExpression parse(std::string_view text, const ParseOptions& opt = {}) const;
  // The canonical text of a proposition (empty when it is not well formed).
  static std::string to_text(const Proposition& p);

 private:
  std::unique_ptr<LanguageVocabulary> vocab_;
};

}  // namespace em::social
