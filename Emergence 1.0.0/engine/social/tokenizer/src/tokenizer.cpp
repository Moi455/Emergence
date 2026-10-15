#include "emergence/social/tokenizer/tokenizer.h"

#include <algorithm>
#include <bit>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <deque>
#include <map>

#include "tok2_gen.h"

namespace em::social::tok2 {
namespace {

constexpr double kEpsilon = 1e-9;
constexpr double kQtyMax = 10000000.0;
constexpr int kBagCap = 6, kPtrListCap = 4, kMaxText = 1000;

static_assert(gen::kMaxTokens == kMaxTokens && gen::kPropLen == kPropLen && gen::kNumWidth == kNumWidth &&
              gen::kCatWidth == kCatWidth && gen::kPtrWidth == kPtrWidth, "tok2_gen.h changed: update tokenizer.h");

[[noreturn]] void refuse(const std::string& m) { throw TokenError(m); }

// Where a value comes from, for the refusal message only (built lazily: the happy path allocates nothing).
struct Where {
  std::string_view a, b, c;
  std::string str() const {
    std::string r(a);
    if (!b.empty()) { r += '.'; r += b; }
    if (!c.empty()) { r += '.'; r += c; }
    return r;
  }
};
std::string operator+(const Where& w, const char* s) { return w.str() + s; }

std::string shorten(std::string_view s, std::size_t n = 40) {
  std::string out;
  for (char c : s.substr(0, n)) out += (c >= 0x20 && c < 0x7f) ? c : '?';
  return out;
}

// ------------------------------------------------------------------------------------------------ keys
bool is_num(std::string_view s) {   // 0 | [1-9][0-9]{0,11}
  if (s.empty() || s.size() > 12) return false;
  if (s[0] == '0') return s.size() == 1;
  for (char c : s) if (c < '0' || c > '9') return false;
  return true;
}
bool is_key(std::string_view k) {
  if (k == "me" || k == "me.mind" || k == "me.state" || k == "wake" || k == "@PLACE") return true;
  if (k.size() >= 3 && k[0] == '@' && (k[1] == 'E' || k[1] == 'T' || k[1] == 'G' || k[1] == 'L' || k[1] == 'V')) return is_num(k.substr(2));
  if (k.size() >= 3 && k[1] == ':' && std::string_view("bmghqcpkt").find(k[0]) != std::string_view::npos) return is_num(k.substr(2));
  return false;
}
bool is_name(std::string_view s) { return s.size() >= 3 && s[0] == 'n' && s[1] == ':' && is_num(s.substr(2)); }
bool is_ascii_digits(std::string_view s) {
  if (s.empty()) return false;
  for (char c : s) if (c < '0' || c > '9') return false;
  return true;
}
// POINTER of catalogue/tools/language.py: ASCII digits, any count of them.
bool is_pointer_sym(std::string_view s) {
  if (s == "@PLACE") return true;
  if (s.size() >= 3 && s[0] == '@' && std::string_view("ETGLV").find(s[1]) != std::string_view::npos) return is_ascii_digits(s.substr(2));
  if (s.size() >= 3 && s[1] == ':' && std::string_view("bmghqcn").find(s[0]) != std::string_view::npos) return is_ascii_digits(s.substr(2));
  return false;
}
bool is_count(std::string_view s, double* out) {
  if (!is_num(s)) return false;
  std::uint64_t v = 0;
  for (char c : s) v = v * 10 + std::uint64_t(c - '0');
  if (v > 10000000u) return false;
  *out = double(v);
  return true;
}

// ------------------------------------------------------------------------------------------------ numbers
struct Scalar {
  double d = 0;
  bool is_bool = false;
};

double bounded(double x, double lo, double hi, const Where& where) {
  if (lo <= x && x <= hi) return x;
  if (lo - kEpsilon <= x && x < lo) return lo;
  if (hi < x && x <= hi + kEpsilon) return hi;
  refuse(where + ": value outside [" + std::to_string(lo) + ", " + std::to_string(hi) + "]");
}
double signed_log(double x) { return std::copysign(std::log1p(std::fabs(x)), x); }

Scalar coerce(const Value& v, const Where& where) {
  if (v.is_bool()) return {v.as_bool() ? 1.0 : 0.0, true};
  if (v.is_number()) {
    if (!std::isfinite(v.as_number())) refuse(where + ": finite number expected");
    return {v.as_number(), false};
  }
  refuse(where + ": a number expected");
}

double apply_scale(NumScale scale, const Scalar& x, const Where& where) {
  if (x.is_bool) {
    if (scale != NumScale::boolean) refuse(where + ": a bool for a non-bool field");
    return x.d;
  }
  double r;
  switch (scale) {
    case NumScale::boolean: refuse(where + ": bool expected");
    case NumScale::bipolar10: r = bounded(x.d, -10, 10, where) / 10; break;
    case NumScale::unipolar10: r = bounded(x.d, 0, 10, where) / 10; break;
    case NumScale::ratio: r = bounded(x.d, 0, 1, where); break;
    case NumScale::unit: r = bounded(x.d, -1, 1, where); break;
    case NumScale::qty: r = std::log1p(bounded(x.d, 0, kQtyMax, where)); break;
    case NumScale::qty_signed: r = signed_log(bounded(x.d, -kQtyMax, kQtyMax, where)); break;
    case NumScale::time: r = std::log1p(bounded(x.d, 0, kQtyMax, where)); break;
    case NumScale::time_until: r = signed_log(bounded(x.d, -kQtyMax, kQtyMax, where)); break;
    default: refuse(where + ": no numeric encoding");
  }
  return r + 0.0;
}

}  // namespace

// ------------------------------------------------------------------------------------------------ binary16
std::uint16_t to_half_bits(double x) {
  const std::uint64_t b = std::bit_cast<std::uint64_t>(x);
  const std::uint16_t sign = std::uint16_t((b >> 63) << 15);
  const int exp = int((b >> 52) & 0x7ff);
  const std::uint64_t mant = b & ((1ull << 52) - 1);
  if (exp == 0x7ff) return std::uint16_t(sign | 0x7c00 | (mant ? 0x200 : 0));
  if (exp == 0) return 0;                              // zero and double subnormals: far below half's range
  const int e = exp - 1023;
  std::uint32_t mag;
  if (e > 15) {
    mag = 0x7c00;
  } else if (e >= -14) {
    std::uint32_t hm = std::uint32_t(mant >> 42);
    const std::uint64_t rem = mant & ((1ull << 42) - 1), half = 1ull << 41;
    if (rem > half || (rem == half && (hm & 1))) ++hm;
    mag = (std::uint32_t(e + 15) << 10) + hm;
    if (mag >= 0x7c00) mag = 0x7c00;
  } else if (e >= -25) {
    const std::uint64_t full = (1ull << 52) | mant;
    const int shift = 42 + (-14 - e);
    std::uint32_t hm = std::uint32_t(full >> shift);
    const std::uint64_t rem = full & ((1ull << shift) - 1), half = 1ull << (shift - 1);
    if (rem > half || (rem == half && (hm & 1))) ++hm;
    mag = hm;
  } else {
    mag = 0;
  }
  return mag == 0 ? std::uint16_t(0) : std::uint16_t(sign | mag);   // a zero after rounding is +0.0
}

double half_bits_to_double(std::uint16_t h) {
  const int s = h >> 15, e = (h >> 10) & 0x1f, m = h & 0x3ff;
  double v;
  if (e == 0) v = std::ldexp(double(m), -24);
  else if (e == 31) v = m ? NAN : INFINITY;
  else v = std::ldexp(double(m | 0x400), e - 25);
  return s ? -v : v;
}

// ------------------------------------------------------------------------------------------------ crc32
namespace {
const std::array<std::uint32_t, 256>& crc_table() {
  static const auto t = [] {
    std::array<std::uint32_t, 256> a{};
    for (std::uint32_t i = 0; i < 256; ++i) {
      std::uint32_t c = i;
      for (int k = 0; k < 8; ++k) c = (c & 1) ? 0xEDB88320u ^ (c >> 1) : c >> 1;
      a[i] = c;
    }
    return a;
  }();
  return t;
}
}  // namespace
std::uint32_t crc32_update(std::uint32_t crc, const void* data, std::size_t n) {
  const auto& t = crc_table();
  const auto* p = static_cast<const unsigned char*>(data);
  crc = ~crc;
  for (std::size_t i = 0; i < n; ++i) crc = t[(crc ^ p[i]) & 0xff] ^ (crc >> 8);
  return ~crc;
}

void Encoded::clear() {
  n = 0;
  type_id.fill(0);
  for (auto& r : num) r.fill(0);
  for (auto& r : known) r.fill(0);
  for (auto& r : cat) r.fill(0);
  for (auto& r : cat_known) r.fill(0);
  for (auto& r : ptr) r.fill(0);
  for (auto& r : ptr_known) r.fill(0);
  for (auto& r : prop_sym) r.fill(0);
  for (auto& r : prop_arity) r.fill(0);
  for (auto& r : prop_depth) r.fill(0);
  for (auto& r : prop_slot) r.fill(0);
  for (auto& r : prop_num) r.fill(0);
  keys.clear(); names.clear(); ghosts.clear();
}

std::uint32_t Encoded::digest() const {
  static_assert(std::endian::native == std::endian::little, "digest hashes the in-memory little-endian bytes");
  const std::uint32_t nn = n;
  std::uint32_t c = crc32_update(0, &nn, 4);
  c = crc32_update(c, type_id.data(), sizeof type_id);
  c = crc32_update(c, num.data(), sizeof num);
  c = crc32_update(c, known.data(), sizeof known);
  c = crc32_update(c, cat.data(), sizeof cat);
  c = crc32_update(c, cat_known.data(), sizeof cat_known);
  c = crc32_update(c, ptr.data(), sizeof ptr);
  c = crc32_update(c, ptr_known.data(), sizeof ptr_known);
  c = crc32_update(c, prop_sym.data(), sizeof prop_sym);
  c = crc32_update(c, prop_arity.data(), sizeof prop_arity);
  c = crc32_update(c, prop_depth.data(), sizeof prop_depth);
  c = crc32_update(c, prop_slot.data(), sizeof prop_slot);
  c = crc32_update(c, prop_num.data(), sizeof prop_num);
  return c;
}

// ------------------------------------------------------------------------------------------------ Tokenizer::Impl
struct Tokenizer::Impl {
  Parser parser;
  std::unordered_map<std::string_view, int> vocab;           // symbol -> id
  std::unordered_map<std::string_view, int> types;           // type name -> index in gen::kTypes
  std::vector<std::unordered_map<std::string_view, int>> cols;   // per type: field name -> column index
  int type_by_id[gen::kMaxTypeId + 1];

  Impl() {
    for (int i = 0; i < gen::kVocabSize; ++i) vocab.emplace(gen::kVocabulary[i], i);
    cols.resize(gen::kNumTypes);
    std::fill(std::begin(type_by_id), std::end(type_by_id), -1);
    for (int t = 0; t < gen::kNumTypes; ++t) {
      const TypeDef& td = gen::kTypes[t];
      types.emplace(td.name, t);
      type_by_id[td.id] = t;
      for (int c = 0; c < td.col_n; ++c) cols[t].emplace(gen::kColumns[td.col_at + c].name, c);
    }
  }
  bool key_ok(const TypeDef& t, std::string_view key) const {
    if (!is_key(key)) return false;
    if (t.fixed_key) return key == t.key;
    return key.substr(0, t.key.size()) == t.key;
  }
  bool is_word(std::string_view s) const {
    const auto it = vocab.find(s);
    return it != vocab.end() && gen::kVocabIsWord[it->second];
  }
};

Tokenizer::Tokenizer() : impl_(std::make_unique<Impl>()) {}
Tokenizer::~Tokenizer() = default;

std::uint64_t Tokenizer::interface_fingerprint() const { return gen::kInterfaceFingerprint; }
std::uint64_t Tokenizer::layout_fingerprint() const { return gen::kLayoutFingerprint; }
std::uint64_t Tokenizer::vocab_fingerprint() const { return gen::kVocabFingerprint; }
std::string Tokenizer::header_json() const {
  char buf[128];
  std::snprintf(buf, sizeof buf, "{\"interface\":\"%016llx\",\"layout\":\"%016llx\",\"schema\":\"tok2-context-1\"}",
                (unsigned long long)gen::kInterfaceFingerprint, (unsigned long long)gen::kLayoutFingerprint);
  return buf;
}
int Tokenizer::type_index(std::string_view type) const {
  const auto it = impl_->types.find(type);
  return it == impl_->types.end() ? -1 : it->second;
}
int Tokenizer::column(int ti, std::string_view field) const {
  if (ti < 0) return -1;
  const auto& m = impl_->cols[std::size_t(ti)];
  const auto it = m.find(field);
  return it == m.end() ? -1 : it->second;
}
const TypeDef& Tokenizer::type_def(int ti) const { return gen::kTypes[ti]; }
const ColumnDef& Tokenizer::column_def(int ti, int col) const { return gen::kColumns[gen::kTypes[ti].col_at + col]; }
int Tokenizer::symbol_id(std::string_view s) const {
  const auto it = impl_->vocab.find(s);
  return it == impl_->vocab.end() ? -1 : it->second;
}

Record Tokenizer::make_record(std::string_view type, std::string_view key, const Value& fields) const {
  Record r;
  r.type = std::string(type);
  r.key = std::string(key);
  r.type_index = type_index(type);
  for (const auto& [name, v] : fields.members()) {
    const int c = column(r.type_index, name);
    Field* slot = nullptr;
    for (auto& f : r.fields) if (c >= 0 ? f.col == c : (f.col < 0 && f.name == name)) { slot = &f; break; }   // last one wins
    if (slot == nullptr) { r.fields.emplace_back(); slot = &r.fields.back(); }
    slot->col = c;
    slot->name = c < 0 ? name : std::string();
    slot->value = v;
  }
  return r;
}

DecisionContext Tokenizer::load_context(std::string_view json) const { return load_context(parse_json(json)); }

DecisionContext Tokenizer::load_context(const Value& d) const {
  if (!d.is_dict()) refuse("a serialized context is {header, records, known_keys}");
  const Value* header = d.find("header");
  const Value* records = d.find("records");
  const Value* known = d.find("known_keys");
  std::size_t distinct = 0;   // member names, duplicates collapsed
  for (std::size_t i = 0; i < d.members().size(); ++i) {
    bool dup = false;
    for (std::size_t j = 0; j < i; ++j) dup = dup || d.members()[j].first == d.members()[i].first;
    distinct += dup ? 0 : 1;
  }
  if (!header || !records || !known || distinct != 3) refuse("a serialized context is {header, records, known_keys}");
  const Value want = parse_json(header_json());
  bool same = header->is_dict();
  if (same) {
    std::size_t hd = 0;
    for (std::size_t i = 0; i < header->members().size(); ++i) {
      bool dup = false;
      for (std::size_t j = 0; j < i; ++j) dup = dup || header->members()[j].first == header->members()[i].first;
      hd += dup ? 0 : 1;
    }
    same = hd == want.members().size();
    for (const auto& [k, v] : want.members()) {
      const Value* h = header->find(k);
      same = same && h && h->is_string() && h->as_string() == v.as_string();
    }
  }
  if (!same) refuse("this context was written for another tokenizer (header)");
  if (!records->is_list()) refuse("records must be a list");
  if (!known->is_null() && !known->is_list()) refuse("known_keys must be a list or null");
  DecisionContext ctx;
  for (const Value& r : records->items()) {
    if (!r.is_dict()) refuse("a record is {type, key, fields}");
    const Value *t = r.find("type"), *k = r.find("key"), *f = r.find("fields");
    std::size_t distinct_r = 0;
    for (std::size_t i = 0; i < r.members().size(); ++i) {
      bool dup = false;
      for (std::size_t j = 0; j < i; ++j) dup = dup || r.members()[j].first == r.members()[i].first;
      distinct_r += dup ? 0 : 1;
    }
    if (!t || !k || !f || distinct_r != 3 || !f->is_dict()) refuse("a record is {type, key, fields}");
    if (!t->is_string() || !k->is_string()) refuse("a record's type and key are strings");
    ctx.records.push_back(make_record(t->as_string(), k->as_string(), *f));
  }
  if (known->is_list()) {
    ctx.has_known_keys = true;
    for (const Value& k : known->items()) {
      if (!k.is_string()) { ctx.known_keys_valid = false; continue; }
      ctx.known_keys.push_back(k.as_string());
    }
  }
  return ctx;
}

// ------------------------------------------------------------------------------------------------ the encoder of one decision
namespace {

// Open-addressing table string_view -> int, sized once for a decision (no node allocation).
class KeyTable {
 public:
  explicit KeyTable(std::size_t expected) {
    std::size_t cap = 16;
    while (cap < expected * 2) cap <<= 1;
    t_.assign(cap, Entry{});
    mask_ = cap - 1;
  }
  // true when inserted; false when the key was already there (the stored value is kept)
  bool insert(std::string_view k, int v) {
    for (std::size_t i = hash(k) & mask_;; i = (i + 1) & mask_) {
      if (!t_[i].used) { t_[i] = {k, v, true}; return true; }
      if (t_[i].k == k) return false;
    }
  }
  int find(std::string_view k) const {
    for (std::size_t i = hash(k) & mask_;; i = (i + 1) & mask_) {
      if (!t_[i].used) return -1;
      if (t_[i].k == k) return t_[i].v;
    }
  }
  bool contains(std::string_view k) const { return find(k) >= 0; }

 private:
  struct Entry { std::string_view k; int v = 0; bool used = false; };
  static std::size_t hash(std::string_view k) {
    std::uint64_t h = 1469598103934665603ull;
    for (unsigned char c : k) h = (h ^ c) * 1099511628211ull;
    return std::size_t(h ^ (h >> 29));
  }
  std::vector<Entry> t_;
  std::size_t mask_ = 0;
};

struct Pending {
  int row, block, col;       // block 0: ptr, 1: prop
  const std::string* key;
};

class Encoder {
 public:
  Encoder(const Tokenizer& tk, const Tokenizer::Impl& im, const DecisionContext& ctx, Encoded& enc, PropCache* cache)
      : tk_(tk), im_(im), ctx_(ctx), enc_(enc), cache_(cache) {}

  void run() {
    enc_.clear();
    check_known();
    order();
    for (std::size_t r = 0; r < rows_.size(); ++r) write_record(int(r), *rows_[r]);
    finalize();
  }

 private:
  struct Slot { int row; };

  void check_known() {
    known_tab_.emplace(ctx_.has_known_keys ? ctx_.known_keys.size() : ctx_.records.size());
    known_ = &*known_tab_;
    if (ctx_.has_known_keys) {
      if (!ctx_.known_keys_valid) refuse("known_keys: items are not record keys");
      for (const auto& k : ctx_.known_keys) {
        if (!is_key(k)) refuse("known_keys: " + shorten(k) + " is not a record key");
        known_->insert(std::string_view(k), 1);
      }
    } else {
      for (const auto& r : ctx_.records) {
        if (!is_key(r.key)) refuse("known_keys: " + shorten(r.key) + " is not a record key");
        known_->insert(std::string_view(r.key), 1);
      }
    }
  }

  void order() {
    std::vector<std::vector<const Record*>> by_type(std::size_t(gen::kNumTypes));
    rows_.reserve(ctx_.records.size());
    KeyTable seen(ctx_.records.size());
    for (const Record& rec : ctx_.records) {
      if (rec.type_index < 0) refuse("unknown token type " + shorten(rec.type));
      const TypeDef& t = gen::kTypes[rec.type_index];
      if (!im_.key_ok(t, rec.key)) refuse(rec.type + ": key " + shorten(rec.key) + " does not match '" + std::string(t.key) + "'");
      if (!seen.insert(rec.key, 1)) refuse("key " + shorten(rec.key) + " used twice in one decision");
      if (!known_->contains(rec.key)) refuse(rec.type + ": key " + shorten(rec.key) + " is not in known_keys");
      by_type[std::size_t(rec.type_index)].push_back(&rec);
    }
    // registry order = increasing type id
    for (int id = 1; id <= gen::kMaxTypeId; ++id) {
      const int ti = im_.type_by_id[id];
      if (ti < 0) continue;
      const auto& v = by_type[std::size_t(ti)];
      if (int(v.size()) > gen::kTypes[ti].count) refuse(std::string(gen::kTypes[ti].name) + ": too many records for its token budget");
      for (const Record* r : v) rows_.push_back(r);
    }
    for (const char* mandatory : {"SELF", "PLACE"})
      if (by_type[std::size_t(tk_.type_index(mandatory))].empty()) refuse(std::string("a decision needs a ") + mandatory + " record");
    if (rows_.size() > std::size_t(kMaxTokens)) refuse("more records than tokens");
    slots_tab_.emplace(rows_.size());
    slots_ = &*slots_tab_;
    enc_.keys.reserve(rows_.size());
    for (std::size_t i = 0; i < rows_.size(); ++i) {
      slots_->insert(std::string_view(rows_[i]->key), int(i) + 1);
      enc_.keys.push_back(rows_[i]->key);
      const Record& r = *rows_[i];
      const int tid = gen::kTypes[r.type_index].id;
      if (r.type == "THING" || r.type == "INV" || r.type == "LOCUS") {
        const int kc = tk_.column(r.type_index, "kind");
        for (const auto& f : r.fields)
          if (f.col == kc && f.value.is_string() && !f.value.as_string().empty()) kinds_[r.key] = f.value.as_string();
      }
      (void)tid;
    }
    enc_.n = std::uint32_t(rows_.size());
  }

  void write_record(int r, const Record& rec) {
    const TypeDef& t = gen::kTypes[rec.type_index];
    enc_.type_id[std::size_t(r)] = t.id;
    const Value* byc[64] = {};
    for (const auto& f : rec.fields) {
      if (f.col < 0) refuse(rec.type + " " + shorten(rec.key) + ": unknown field " + shorten(f.name, 30));
      byc[f.col] = &f.value;
    }
    // AbsentEntityRule: a person who is not here has no distance, direction or appearance.
    if (rec.type == "ENTITY") {
      const int pc = tk_.column(rec.type_index, "present");
      if (byc[pc] && byc[pc]->is_bool() && !byc[pc]->as_bool()) {
        for (int c = 0; c < t.col_n; ++c) {
          const std::string_view n = gen::kColumns[t.col_at + c].name;
          if ((n == "dist" || n == "dir" || n.substr(0, 5) == "look.") && byc[c] && !byc[c]->is_null())
            refuse("ENTITY " + shorten(rec.key) + ": present=False but carries " + std::string(n));
        }
      }
    }
    row_key_ = &rec.key;
    for (int c = 0; c < t.col_n; ++c) {
      const Value* v = byc[c];
      if (v == nullptr || v->is_null()) continue;
      write_column(r, rec, gen::kColumns[t.col_at + c], *v);
    }
  }

  // ---- symbols
  int name_id(const std::string& name) {
    int k = -1;
    for (std::size_t i = 0; i < enc_.names.size(); ++i) if (enc_.names[i] == name) { k = int(i); break; }
    if (k < 0) {
      k = int(enc_.names.size());
      if (k < gen::kNameSlots) enc_.names.push_back(name);
    }
    return (k >= 0 && k < gen::kNameSlots) ? gen::kName0Id + k : gen::kNameOtherId;
  }
  int symbol_id(const Value& v, const ColumnDef& cd, const Where& where) {
    if (!v.is_string()) refuse(where + ": a symbol expected");
    const std::string& s = v.as_string();
    if (cd.is_enum) {
      if (cd.values_n) {
        bool ok = false;
        for (int i = 0; i < cd.values_n; ++i) ok = ok || gen::kStrings[gen::kStringStart[cd.values_at] + i] == s;
        if (!ok) refuse(where + ": " + shorten(s) + " is not one of its values");
      }
    } else if (is_name(s)) {
      return name_id(s);
    } else if (cd.words_n) {
      bool ok = false;
      for (int i = 0; i < cd.words_n; ++i) ok = ok || gen::kStrings[gen::kStringStart[cd.words_at] + i] == s;
      if (!ok) refuse(where + ": " + shorten(s) + " is not one of its words");
    }
    const auto it = im_.vocab.find(s);
    if (it == im_.vocab.end() || !gen::kVocabIsWord[it->second]) refuse(where + ": unknown word " + shorten(s));
    return it->second;
  }

  // ---- pointers
  void pointer(const Value& keyv, const Where& where, int row, int block, int col, std::uint32_t ref_types) {
    if (!keyv.is_string()) refuse(where + ": not a record key");
    const std::string& key = keyv.as_string();
    if (key.empty() && block == 0) return;
    if (!is_key(key)) refuse(where + ": " + shorten(key) + " is not a record key");
    if (block == 1 && key == *row_key_) refuse(where + ": the proposition of " + key + " cites itself");
    const int found = slots_->find(key);
    if (ref_types) {
      bool allowed = false;
      if (found > 0) {
        allowed = (ref_types >> gen::kTypes[rows_[std::size_t(found - 1)]->type_index].id) & 1;
      } else {
        for (int ti = 0; ti < gen::kNumTypes; ++ti)   // a ghost: the kinds its key can designate
          if (im_.key_ok(gen::kTypes[ti], key) && ((ref_types >> gen::kTypes[ti].id) & 1)) allowed = true;
      }
      if (!allowed) refuse(where + ": " + shorten(key) + " is a record of another kind than the field accepts");
    }
    auto& target_ptr = enc_.ptr[std::size_t(row)];
    auto& target_prop = enc_.prop_slot[std::size_t(row)];
    if (found > 0) {
      (block == 0 ? target_ptr[std::size_t(col)] : target_prop[std::size_t(col)]) = std::uint8_t(found);
    } else if (known_->contains(key)) {
      (block == 0 ? target_ptr[std::size_t(col)] : target_prop[std::size_t(col)]) = std::uint8_t(kGhostBase);
      pending_.push_back({row, block, col, &keyv.as_string()});
    } else {
      refuse(where + ": " + shorten(key) + " is not in the NPC's mind (known_keys)");
    }
  }

  void finalize() {
    std::sort(pending_.begin(), pending_.end(), [](const Pending& a, const Pending& b) {
      if (a.row != b.row) return a.row < b.row;
      if (a.block != b.block) return a.block < b.block;
      return a.col < b.col;
    });
    std::map<std::string_view, int> ghost;   // key -> k, or -1 beyond the 32nd
    for (const Pending& p : pending_) {
      auto it = ghost.find(*p.key);
      if (it == ghost.end()) {
        int k = -1;
        if (int(enc_.ghosts.size()) < kGhostSlots) { k = int(enc_.ghosts.size()); enc_.ghosts.push_back(*p.key); }
        it = ghost.emplace(std::string_view(*p.key), k).first;
      }
      const std::uint8_t slot = it->second < 0 ? std::uint8_t(kGhostOverflow) : std::uint8_t(kGhostBase + it->second);
      if (p.block == 0) enc_.ptr[std::size_t(p.row)][std::size_t(p.col)] = slot;
      else enc_.prop_slot[std::size_t(p.row)][std::size_t(p.col)] = slot;
    }
  }

  // ---- columns
  void write_column(int r, const Record& rec, const ColumnDef& cd, const Value& v) {
    const Where where{rec.type, cd.name, {}};
    const std::size_t R = std::size_t(r);
    switch (cd.codec) {
      case Codec::scalar:
        enc_.num[R][cd.col] = to_half_bits(apply_scale(cd.scale, coerce(v, where), where));
        enc_.known[R][cd.col] = 1;
        break;
      case Codec::vector: write_vector(R, cd, v, where); break;
      case Codec::symbol:
        if (v.is_string() && v.as_string().empty() && !cd.is_enum) enc_.cat[R][cd.col] = 0;   // a word set to "": known, none
        else enc_.cat[R][cd.col] = std::int16_t(symbol_id(v, cd, where));
        enc_.cat_known[R][cd.col] = 1;
        break;
      case Codec::bag: {
        if (!v.is_list()) refuse(where + ": a list expected");
        if (int(v.items().size()) > kBagCap) refuse(where + ": too many words");
        for (std::size_t i = 0; i < v.items().size(); ++i) enc_.cat[R][cd.col + i] = std::int16_t(symbol_id(v.items()[i], cd, where));
        for (int i = 0; i < kBagCap; ++i) enc_.cat_known[R][cd.col + i] = 1;
        break;
      }
      case Codec::pointer:
        pointer(v, where, r, 0, cd.col, cd.ref_types);
        enc_.ptr_known[R][cd.col] = 1;
        break;
      case Codec::pointer_list: {
        if (!v.is_list() || int(v.items().size()) > kPtrListCap) refuse(where + ": a list of at most 4 pointers expected");
        for (std::size_t i = 0; i < v.items().size(); ++i) {
          const Value& k = v.items()[i];
          if (k.is_string() && k.as_string().empty()) refuse(where + ": an empty pointer inside a list");
          pointer(k, where, r, 0, int(cd.col + i), cd.ref_types);
        }
        for (int i = 0; i < kPtrListCap; ++i) enc_.ptr_known[R][cd.col + i] = 1;
        break;
      }
      case Codec::proposition: write_proposition(r, v, where, cd.utterance); break;
    }
  }

  void write_vector(std::size_t R, const ColumnDef& cd, const Value& v, const Where& where) {
    const Component* comps = &gen::kComponents[cd.comp_at];
    const int n = cd.comp_n;
    auto index_of = [&](const std::string& name) {
      for (int i = 0; i < n; ++i) if (comps[i].name == name) return i;
      refuse(where + ": unknown component " + shorten(name, 30));
    };
    struct Slot2 { bool set = false; Scalar s; };
    std::vector<Slot2> out;
    out.resize(static_cast<std::size_t>(n));
    auto one = [&](const Value& d, std::vector<Slot2>& dst, bool pool) {
      for (const auto& [name, x] : d.members()) index_of(name);   // unknown components first, as the oracle
      std::vector<Slot2> mine;
      mine.resize(static_cast<std::size_t>(n));
      for (const auto& [name, x] : d.members()) { const int i = index_of(name); mine[std::size_t(i)] = {true, coerce(x, Where{where.a, where.b, name})}; }
      for (int i = 0; i < n; ++i) {
        if (!mine[std::size_t(i)].set) continue;
        const Where w{where.a, where.b, comps[i].name};
        if (pool) apply_scale(comps[i].scale, mine[std::size_t(i)].s, w);   // each item is checked on its own before pooling
        Slot2& p = dst[std::size_t(i)];
        if (!pool || !p.set) { p = mine[std::size_t(i)]; }
        else if (comps[i].pool_sum) p.s.d = p.s.d + mine[std::size_t(i)].s.d;
        else p.s.d = std::max(p.s.d, mine[std::size_t(i)].s.d);
      }
    };
    if (v.is_dict()) {
      one(v, out, false);
    } else if (v.is_list()) {
      if (v.items().empty()) {
        if (!cd.multi) refuse(where + ": [] is only meaningful for a list of vectors");
        for (int i = 0; i < n; ++i) { enc_.num[R][comps[i].col] = 0; enc_.known[R][comps[i].col] = 1; }
        return;
      }
      bool all_dict = true;
      for (const Value& it : v.items()) all_dict = all_dict && it.is_dict();
      if (!all_dict || !cd.multi) refuse(where + ": a dict component -> value is expected");
      for (const Value& it : v.items()) one(it, out, true);
    } else {
      refuse(where + ": a dict component -> value is expected");
    }
    for (int i = 0; i < n; ++i) {
      if (!out[std::size_t(i)].set) continue;
      const Where w{where.a, where.b, comps[i].name};
      enc_.num[R][comps[i].col] = to_half_bits(apply_scale(comps[i].scale, out[std::size_t(i)].s, w));
      enc_.known[R][comps[i].col] = 1;
    }
  }

  // ---- propositions
  struct Sym { std::string_view text; int arity, depth; bool head; };
  struct Walk {
    std::vector<std::string_view> toks;
    std::size_t p = 0;
    std::vector<Sym> seq;
  };
  static void tokenize(std::string_view t, std::vector<std::string_view>& out) {
    std::size_t i = 0;
    while (i < t.size()) {
      const char c = t[i];
      if (c == ' ' || c == '\t' || c == '\n' || c == '\r') { ++i; continue; }
      if (c == '(' || c == ')') { out.push_back(t.substr(i, 1)); ++i; continue; }
      std::size_t j = i;
      while (j < t.size() && t[j] != ' ' && t[j] != '\t' && t[j] != '\n' && t[j] != '\r' && t[j] != '(' && t[j] != ')') ++j;
      out.push_back(t.substr(i, j - i));
      i = j;
    }
  }
  static void expr(Walk& w, int depth) {   // the text is already validated: the structure is sound
    const std::string_view t = w.toks[w.p++];
    if (t != "(") { w.seq.push_back({t, 0, depth, false}); return; }
    const std::size_t at = w.seq.size();
    w.seq.push_back({w.toks[w.p++], 0, depth, true});
    int args = 0;
    while (w.toks[w.p] != ")") { expr(w, depth + 1); ++args; }
    ++w.p;
    w.seq[at].arity = args + 1;
  }

  PropEntry build_entry(const std::string& text, bool utterance, const Where& where) {
    ParseOptions opt;
    opt.bare = !utterance;
    opt.pointer_kinds = &kinds_;
    const TypedExpression e = im_.parser.parse(text, opt);
    if (!e.ok()) refuse(where + ": proposition refused (" + std::string(to_string(e.problems().front())) + ")");
    Walk w;
    tokenize(text, w.toks);
    expr(w, 0);
    if (int(w.seq.size()) > kPropLen) refuse(where + ": too many symbols");
    PropEntry pe;
    for (const Sym& s : w.seq) {
      PropPos pos;
      double num = 0;
      if (s.head) {
        pos.id = word_id(s.text, where);
      } else if (is_pointer_sym(s.text)) {
        if (s.text[0] == 'n') {
          if (!is_name(s.text)) refuse(where + ": not a canonical name");
          pos.kind = 1;
        } else {
          if (!is_key(s.text)) refuse(where + ": not a canonical pointer");
          pos.id = im_.vocab.at(s.text == "@PLACE" ? s.text : s.text.substr(0, 2));
          pos.kind = 2;
        }
        pos.text = std::string(s.text);
      } else if (is_ascii_digits(s.text)) {
        pos.id = gen::kNumId;
        num = count_of(s.text, where);
      } else if (const std::size_t colon = s.text.find(':'); colon != std::string_view::npos) {
        pos.id = word_id(s.text.substr(0, colon), where);
        num = count_of(s.text.substr(colon + 1), where);
      } else {
        pos.id = word_id(s.text, where);
      }
      pos.arity = std::uint8_t(s.arity);
      pos.depth = std::uint8_t(s.depth);
      pos.num = num != 0 ? to_half_bits(num) : std::uint16_t(0);
      pe.pos.push_back(std::move(pos));
    }
    return pe;
  }

  // The cache key: the text, the mood, and the kind of every pointer the text cites (it types the proposition).
  std::string cache_key(const std::string& text, bool utterance) const {
    std::string k(utterance ? "U" : "B");
    k += text;
    std::vector<std::string_view> toks;
    tokenize(text, toks);
    for (const auto t : toks) {
      if (t.size() < 3 || (t[0] != '@' && t[1] != ':')) continue;
      const auto it = kinds_.find(t);
      if (it != kinds_.end()) { k += '\x01'; k += it->second; }
    }
    return k;
  }

  void write_proposition(int r, const Value& v, const Where& where, bool utterance) {
    if (!v.is_string()) refuse(where + ": a proposition (text) expected");
    const std::string& text = v.as_string();
    const PropEntry* pe = nullptr;
    PropEntry local;
    if (cache_) {
      const std::string key = cache_key(text, utterance);
      auto it = cache_->map.find(key);
      if (it == cache_->map.end()) it = cache_->map.emplace(key, build_entry(text, utterance, where)).first;
      pe = &it->second;
    } else {
      local = build_entry(text, utterance, where);
      pe = &local;
    }
    const std::size_t R = std::size_t(r);
    for (std::size_t i = 0; i < pe->pos.size(); ++i) {
      const PropPos& p = pe->pos[i];
      enc_.prop_sym[R][i] = std::int16_t(p.kind == 1 ? name_id(p.text) : p.id);
      enc_.prop_arity[R][i] = p.arity;
      enc_.prop_depth[R][i] = p.depth;
      enc_.prop_num[R][i] = p.num;
      if (p.kind == 2) {
        pkeys_.push_back(Value::string(p.text));
        pointer(pkeys_.back(), where, r, 1, int(i), 0);
      }
    }
  }
  int word_id(std::string_view s, const Where& where) {
    const auto it = im_.vocab.find(s);
    if (it == im_.vocab.end() || !gen::kVocabIsWord[it->second]) refuse(where + ": unknown symbol " + shorten(s));
    return it->second;
  }
  static double count_of(std::string_view s, const Where& where) {
    double n;
    if (!is_count(s, &n)) refuse(where + ": " + shorten(s) + " is not a canonical count");
    return std::log1p(n + 1);
  }


  const Tokenizer& tk_;
  const Tokenizer::Impl& im_;
  const DecisionContext& ctx_;
  Encoded& enc_;
  PropCache* cache_;
  std::optional<KeyTable> known_tab_;
  KeyTable* known_ = nullptr;
  std::vector<const Record*> rows_;
  std::optional<KeyTable> slots_tab_;
  KeyTable* slots_ = nullptr;
  PointerKinds kinds_;
  std::vector<Pending> pending_;
  std::deque<Value> pkeys_;        // keys of propositions' pointers; pending_ holds addresses into it (stable)
  const std::string* row_key_ = nullptr;
};

}  // namespace

void Tokenizer::encode(const DecisionContext& ctx, Encoded& out, PropCache* cache) const { Encoder(*this, *impl_, ctx, out, cache).run(); }

bool Tokenizer::try_encode(const DecisionContext& ctx, Encoded& out, std::string* why, PropCache* cache) const {
  try {
    encode(ctx, out, cache);
    return true;
  } catch (const TokenError& e) {
    if (why) *why = e.what();
    return false;
  }
}

}  // namespace em::social::tok2
