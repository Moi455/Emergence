// Internal helpers of the speech router and the mind writer: pointers of the inner language as text ("@E3", "b:7").
#pragma once
#include <cstdint>
#include <string>
#include <string_view>

namespace em::social::detail {

// "@E3" -> prefix "@E", number 3. Prefixes: @E @T @G @L @V @PLACE b: m: g: h: q: c: n:. False when not a pointer.
inline bool parse_pointer(std::string_view s, std::string_view& prefix, std::uint32_t& number) {
  std::size_t p = 0;
  if (s.size() >= 3 && s[0] == '@' && (s[1] == 'E' || s[1] == 'T' || s[1] == 'G' || s[1] == 'L' || s[1] == 'V')) p = 2;
  else if (s.size() >= 3 && std::string_view("bmghqcn").find(s[0]) != std::string_view::npos && s[1] == ':') p = 2;
  else return false;
  prefix = s.substr(0, p);
  std::uint64_t n = 0;
  if (p >= s.size()) return false;
  for (std::size_t i = p; i < s.size(); ++i) {
    if (s[i] < '0' || s[i] > '9') return false;
    n = n * 10 + std::uint64_t(s[i] - '0');
    if (n > 0xFFFFFFFFull) return false;
  }
  number = static_cast<std::uint32_t>(n);
  return true;
}

inline bool is_cite(std::string_view s) {   // b: m: g: h: q: c: or @V (governor.py CITE)
  std::string_view pre; std::uint32_t n;
  if (!parse_pointer(s, pre, n)) return false;
  return pre == "@V" || (pre.size() == 2 && pre[1] == ':' && pre[0] != 'n');
}

// Calls f(token) for every symbol of a canonical text (parentheses and spaces are separators).
template <class F>
void for_each_token(std::string_view text, F&& f) {
  std::size_t i = 0;
  while (i < text.size()) {
    while (i < text.size() && (text[i] == '(' || text[i] == ')' || text[i] == ' ')) ++i;
    std::size_t j = i;
    while (j < text.size() && text[j] != '(' && text[j] != ')' && text[j] != ' ') ++j;
    if (j > i) f(text.substr(i, j - i));
    i = j;
  }
}

}  // namespace em::social::detail
