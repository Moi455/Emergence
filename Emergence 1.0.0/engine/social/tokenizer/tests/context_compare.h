// Deep comparison of the values of two dossiers (tests of the ContextBuilder).
#pragma once
#include <cstdio>
#include <string>

#include "emergence/social/tokenizer/tokenizer.h"
#include "emergence/social/tokenizer/value.h"

namespace em::social::tok2::testing {

inline bool same(const Value& a, const Value& b) {
  if (a.kind() != b.kind()) return false;
  switch (a.kind()) {
    case Value::Kind::null: return true;
    case Value::Kind::boolean: return a.as_bool() == b.as_bool();
    case Value::Kind::number: return a.as_number() == b.as_number();
    case Value::Kind::string: return a.as_string() == b.as_string();
    case Value::Kind::list:
      if (a.items().size() != b.items().size()) return false;
      for (std::size_t i = 0; i < a.items().size(); ++i) if (!same(a.items()[i], b.items()[i])) return false;
      return true;
    case Value::Kind::dict:
      if (a.members().size() != b.members().size()) return false;
      for (const auto& [k, v] : a.members()) { const Value* o = b.find(k); if (!o || !same(v, *o)) return false; }
      return true;
  }
  return false;
}

inline std::string show(const Value& v) {
  switch (v.kind()) {
    case Value::Kind::null: return "null";
    case Value::Kind::boolean: return v.as_bool() ? "true" : "false";
    case Value::Kind::number: { char b[40]; std::snprintf(b, sizeof b, "%.9g", v.as_number()); return b; }
    case Value::Kind::string: return "\"" + v.as_string() + "\"";
    case Value::Kind::list: { std::string s = "["; for (const auto& i : v.items()) s += show(i) + ","; return s + "]"; }
    case Value::Kind::dict: { std::string s = "{"; for (const auto& [k, i] : v.members()) s += k + ":" + show(i) + ","; return s + "}"; }
  }
  return "?";
}


// Same records in the same order, same fields (by column), same values, same known keys.
inline bool same_context(const DecisionContext& a, const DecisionContext& b) {
  if (a.records.size() != b.records.size() || a.known_keys != b.known_keys) return false;
  for (std::size_t i = 0; i < a.records.size(); ++i) {
    const Record &x = a.records[i], &y = b.records[i];
    if (x.type != y.type || x.key != y.key || x.fields.size() != y.fields.size()) return false;
    for (const Field& f : x.fields) {
      bool found = false;
      for (const Field& g : y.fields) if (g.col == f.col) { found = same(f.value, g.value); break; }
      if (!found) return false;
    }
  }
  return true;
}

inline const Record* find_record(const DecisionContext& c, const std::string& key) {
  for (const Record& r : c.records) if (r.key == key) return &r;
  return nullptr;
}
inline const Value* field_of(const Tokenizer& tk, const Record& r, const char* name) {
  const int col = tk.column(r.type_index, name);
  for (const Field& f : r.fields) if (f.col == col) return &f.value;
  return nullptr;
}
inline int count_type(const DecisionContext& c, const std::string& type) {
  int n = 0;
  for (const Record& r : c.records) n += r.type == type;
  return n;
}

}  // namespace em::social::tok2::testing
