#include "emergence/social/tokenizer/value.h"

#include <cerrno>
#include <cmath>
#include <cstdlib>

namespace em::social::tok2 {
namespace {

constexpr int kMaxDepth = 200;

class JsonReader {
 public:
  explicit JsonReader(std::string_view t) : t_(t) {}
  Value document() {
    Value v = value(0);
    ws();
    if (p_ != t_.size()) fail("trailing characters");
    return v;
  }

 private:
  [[noreturn]] void fail(const char* what) const { throw TokenError(std::string("not JSON: ") + what); }
  void ws() { while (p_ < t_.size() && (t_[p_] == ' ' || t_[p_] == '\t' || t_[p_] == '\n' || t_[p_] == '\r')) ++p_; }
  bool eat(char c) { if (p_ < t_.size() && t_[p_] == c) { ++p_; return true; } return false; }
  bool word(std::string_view w) { if (t_.substr(p_, w.size()) == w) { p_ += w.size(); return true; } return false; }

  Value value(int depth) {
    if (depth > kMaxDepth) fail("nested too deeply");
    ws();
    if (p_ >= t_.size()) fail("unexpected end");
    const char c = t_[p_];
    if (c == '{') return object(depth);
    if (c == '[') return array(depth);
    if (c == '"') return Value::string(str());
    if (word("true")) return Value::boolean(true);
    if (word("false")) return Value::boolean(false);
    if (word("null")) return Value();
    return number();
  }
  Value object(int depth) {
    ++p_;
    Value v = Value::dict();
    ws();
    if (eat('}')) return v;
    for (;;) {
      ws();
      if (p_ >= t_.size() || t_[p_] != '"') fail("object key");
      std::string k = str();
      ws();
      if (!eat(':')) fail("':' expected");
      v.members().emplace_back(std::move(k), value(depth + 1));
      ws();
      if (eat(',')) continue;
      if (eat('}')) return v;
      fail("',' or '}' expected");
    }
  }
  Value array(int depth) {
    ++p_;
    Value v = Value::list();
    ws();
    if (eat(']')) return v;
    for (;;) {
      v.items().push_back(value(depth + 1));
      ws();
      if (eat(',')) continue;
      if (eat(']')) return v;
      fail("',' or ']' expected");
    }
  }
  static void utf8(std::string& out, std::uint32_t cp) {
    if (cp < 0x80) out += char(cp);
    else if (cp < 0x800) { out += char(0xC0 | cp >> 6); out += char(0x80 | (cp & 0x3F)); }
    else if (cp < 0x10000) { out += char(0xE0 | cp >> 12); out += char(0x80 | ((cp >> 6) & 0x3F)); out += char(0x80 | (cp & 0x3F)); }
    else { out += char(0xF0 | cp >> 18); out += char(0x80 | ((cp >> 12) & 0x3F)); out += char(0x80 | ((cp >> 6) & 0x3F)); out += char(0x80 | (cp & 0x3F)); }
  }
  std::uint32_t hex4() {
    if (p_ + 4 > t_.size()) fail("bad escape");
    std::uint32_t v = 0;
    for (int i = 0; i < 4; ++i) {
      const char c = t_[p_++];
      v <<= 4;
      if (c >= '0' && c <= '9') v |= std::uint32_t(c - '0');
      else if (c >= 'a' && c <= 'f') v |= std::uint32_t(c - 'a' + 10);
      else if (c >= 'A' && c <= 'F') v |= std::uint32_t(c - 'A' + 10);
      else fail("bad escape");
    }
    return v;
  }
  std::string str() {
    ++p_;
    std::string out;
    for (;;) {
      if (p_ >= t_.size()) fail("unterminated string");
      const unsigned char c = static_cast<unsigned char>(t_[p_++]);
      if (c == '"') return out;
      if (c < 0x20) fail("control character in string");
      if (c != '\\') { out += char(c); continue; }
      if (p_ >= t_.size()) fail("bad escape");
      const char e = t_[p_++];
      switch (e) {
        case '"': out += '"'; break;
        case '\\': out += '\\'; break;
        case '/': out += '/'; break;
        case 'b': out += '\b'; break;
        case 'f': out += '\f'; break;
        case 'n': out += '\n'; break;
        case 'r': out += '\r'; break;
        case 't': out += '\t'; break;
        case 'u': {
          std::uint32_t cp = hex4();
          if (cp >= 0xD800 && cp < 0xDC00 && t_.substr(p_, 2) == "\\u") {
            const std::size_t save = p_;
            p_ += 2;
            const std::uint32_t lo = hex4();
            if (lo >= 0xDC00 && lo < 0xE000) cp = 0x10000 + ((cp - 0xD800) << 10) + (lo - 0xDC00);
            else p_ = save;
          }
          utf8(out, cp);
          break;
        }
        default: fail("bad escape");
      }
    }
  }
  Value number() {
    const std::size_t start = p_;
    eat('-');
    if (p_ >= t_.size()) fail("number");
    if (t_[p_] == '0') ++p_;
    else if (t_[p_] >= '1' && t_[p_] <= '9') { while (p_ < t_.size() && t_[p_] >= '0' && t_[p_] <= '9') ++p_; }
    else fail("unexpected character");
    if (eat('.')) {
      const std::size_t d = p_;
      while (p_ < t_.size() && t_[p_] >= '0' && t_[p_] <= '9') ++p_;
      if (p_ == d) fail("number");
    }
    if (p_ < t_.size() && (t_[p_] == 'e' || t_[p_] == 'E')) {
      ++p_;
      if (p_ < t_.size() && (t_[p_] == '+' || t_[p_] == '-')) ++p_;
      const std::size_t d = p_;
      while (p_ < t_.size() && t_[p_] >= '0' && t_[p_] <= '9') ++p_;
      if (p_ == d) fail("number");
    }
    const std::string s(t_.substr(start, p_ - start));
    return Value::number(std::strtod(s.c_str(), nullptr));   // correctly rounded, like Python's float()
  }

  std::string_view t_;
  std::size_t p_ = 0;
};

}  // namespace

Value parse_json(std::string_view text) { return JsonReader(text).document(); }

}  // namespace em::social::tok2
