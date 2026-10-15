// A JSON-like value (null, bool, number, string, list, dict) and a strict JSON parser: what a DecisionContext is made of.
#pragma once
#include <cstdint>
#include <memory>
#include <stdexcept>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

namespace em::social::tok2 {

// The one exception of the tokenizer: every refusal of an input (a TokenError of the oracle).
class TokenError : public std::runtime_error {
 public:
  using std::runtime_error::runtime_error;
};

class Value {
 public:
  enum class Kind : std::uint8_t { null, boolean, number, string, list, dict };
  using Member = std::pair<std::string, Value>;

  Value() = default;
  static Value boolean(bool b) { Value v; v.kind_ = Kind::boolean; v.b_ = b; return v; }
  static Value number(double d) { Value v; v.kind_ = Kind::number; v.d_ = d; return v; }
  static Value string(std::string s) { Value v; v.kind_ = Kind::string; v.s_ = std::move(s); return v; }
  static Value list() { Value v; v.kind_ = Kind::list; return v; }
  static Value dict() { Value v; v.kind_ = Kind::dict; return v; }

  Kind kind() const { return kind_; }
  bool is_null() const { return kind_ == Kind::null; }
  bool is_bool() const { return kind_ == Kind::boolean; }
  bool is_number() const { return kind_ == Kind::number; }
  bool is_string() const { return kind_ == Kind::string; }
  bool is_list() const { return kind_ == Kind::list; }
  bool is_dict() const { return kind_ == Kind::dict; }
  bool as_bool() const { return b_; }
  double as_number() const { return d_; }
  const std::string& as_string() const { return s_; }
  const std::vector<Value>& items() const { return items_; }
  std::vector<Value>& items() { return items_; }
  const std::vector<Member>& members() const { return members_; }
  std::vector<Member>& members() { return members_; }
  // dict: the member `name` (the last one wins, as json.loads does), or nullptr.
  const Value* find(std::string_view name) const {
    for (auto it = members_.rbegin(); it != members_.rend(); ++it)
      if (it->first == name) return &it->second;
    return nullptr;
  }

 private:
  Kind kind_ = Kind::null;
  bool b_ = false;
  double d_ = 0;
  std::string s_;
  std::vector<Value> items_;
  std::vector<Member> members_;
};

// Parses one JSON document (RFC 8259, plus the NaN/Infinity tokens of Python are refused). Throws TokenError.
Value parse_json(std::string_view text);

}  // namespace em::social::tok2
