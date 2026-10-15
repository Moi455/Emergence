// tok-2 in C++ (T28): the records of one decision (the NPC's mind files) -> the fixed-shape arrays the Transformer reads.
// Port of ai/tok2 (the ORACLE): same arrays bit for bit (Encoded::digest), same refusals. One tokenizer, in the game and
// in training (through tokenizer_capi.h). The tables are generated (tok2_gen.h) from the oracle's layout.
//
//   Tokenizer tk;                                          // builds the lookups once; immutable, shareable between threads
//   DecisionContext ctx = tk.load_context(json_text);      // canonical DecisionContext JSON (header checked)
//   Encoded enc; std::string why;
//   if (!tk.try_encode(ctx, enc, &why)) ...                // refusal = the oracle's TokenError
//   enc.digest();                                          // crc32 chain, as Encoded.digest() of Python
//
// Records come from the NPC's mind ONLY (percepts, beliefs, memories...): nothing in this module reads the objective
// state of the world (rule no_truth_in_tokens, D10 of the project). A Record's fields are addressed by column index
// (Tokenizer::column), so an engine builder never compares names.
#pragma once
#include <array>
#include <cstdint>
#include <memory>
#include <optional>
#include <string>
#include <string_view>
#include <unordered_map>
#include <vector>

#include "emergence/social/language.h"
#include "emergence/social/tokenizer/tables.h"
#include "emergence/social/tokenizer/value.h"

namespace em::social::tok2 {

inline constexpr int kMaxTokens = 128, kPropLen = 20, kNumWidth = 65, kCatWidth = 38, kPtrWidth = 6;
inline constexpr int kGhostBase = 129, kGhostSlots = 32, kGhostOverflow = 161;

// IEEE binary16 bits of a double, rounded once (nearest even), +0 when the half is zero.
std::uint16_t to_half_bits(double x);
double half_bits_to_double(std::uint16_t h);
// zlib.crc32(data, crc): chain by passing the previous result.
std::uint32_t crc32_update(std::uint32_t crc, const void* data, std::size_t n);

struct Field {
  std::int32_t col = -1;      // index in the columns of the record's type; -1: a name the type does not have
  std::string name;           // kept only when col < 0 (the refusal names it)
  Value value;                // null = unknown
};

struct Record {
  std::string type;           // token type name (ENTITY, BELIEF...)
  std::string key;            // how it is designated: @E3, b:7, me...
  std::int32_t type_index = -1;   // index in gen::kTypes (-1: unknown type, refused at encoding)
  std::vector<Field> fields;
};

struct DecisionContext {
  std::vector<Record> records;
  bool has_known_keys = false;            // false: the keys of the records
  bool known_keys_valid = true;           // false: a known_keys item was not a string
  std::vector<std::string> known_keys;    // the keys of everything the NPC's mind holds (ghosts are known, not carried)
};

// The arrays of one decision. Row r is token slot r + 1. All values little endian; num and prop_num are binary16 bits.
struct Encoded {
  std::uint32_t n = 0;
  std::array<std::uint8_t, kMaxTokens> type_id;
  std::array<std::array<std::uint16_t, kNumWidth>, kMaxTokens> num;
  std::array<std::array<std::uint8_t, kNumWidth>, kMaxTokens> known;
  std::array<std::array<std::int16_t, kCatWidth>, kMaxTokens> cat;
  std::array<std::array<std::uint8_t, kCatWidth>, kMaxTokens> cat_known;
  std::array<std::array<std::uint8_t, kPtrWidth>, kMaxTokens> ptr;
  std::array<std::array<std::uint8_t, kPtrWidth>, kMaxTokens> ptr_known;
  std::array<std::array<std::int16_t, kPropLen>, kMaxTokens> prop_sym;
  std::array<std::array<std::uint8_t, kPropLen>, kMaxTokens> prop_arity, prop_depth, prop_slot;
  std::array<std::array<std::uint16_t, kPropLen>, kMaxTokens> prop_num;
  std::vector<std::string> keys;          // slot - 1 -> key
  std::vector<std::string> names;         // <name k> -> the name it stands for in this decision
  std::vector<std::string> ghosts;        // k -> the key of ghost 129 + k (never shown to the model)

  Encoded() { clear(); }
  void clear();
  // zlib.crc32 chained over pack('<I', n) then each array in C order (type_id, num, known, cat, cat_known, ptr,
  // ptr_known, prop_sym, prop_arity, prop_depth, prop_slot, prop_num), little endian: Encoded.digest() of the oracle.
  std::uint32_t digest() const;
};

// Memo of the validated propositions (keyed by text, mood and the kinds of the pointers it cites). Owned by the caller,
// one per thread: the tokenizer stays immutable. An NPC's beliefs persist from one decision to the next, so the hit
// rate is high in the game. Using one never changes an output.
struct PropPos {          // one validated symbol position of a proposition
  int id = 0;
  std::uint8_t arity = 0, depth = 0;
  std::uint16_t num = 0;  // binary16 bits
  int kind = 0;           // 0 plain, 1 name (aliased per decision), 2 pointer
  std::string text;       // the name or the pointer
};
struct PropEntry { std::vector<PropPos> pos; };

class PropCache {
 public:
  std::size_t size() const { return map.size(); }
  void clear() { map.clear(); }
  std::unordered_map<std::string, PropEntry> map;
};

class Tokenizer {
 public:
  Tokenizer();
  ~Tokenizer();
  Tokenizer(const Tokenizer&) = delete;
  Tokenizer& operator=(const Tokenizer&) = delete;

  // ---- identity of the format
  std::uint64_t interface_fingerprint() const;
  std::uint64_t layout_fingerprint() const;
  std::uint64_t vocab_fingerprint() const;
  std::string header_json() const;        // {"interface":..,"layout":..,"schema":"tok2-context-1"}

  // ---- records
  int type_index(std::string_view type) const;                                // -1: unknown
  int column(int type_index, std::string_view field) const;                   // -1: unknown
  const TypeDef& type_def(int type_index) const;
  const ColumnDef& column_def(int type_index, int col) const;
  int symbol_id(std::string_view symbol) const;                               // -1: not a symbol of the vocabulary
  // Parses canonical DecisionContext JSON (Python DecisionContext.dumps). Throws TokenError.
  DecisionContext load_context(std::string_view json) const;
  DecisionContext load_context(const Value& parsed) const;
  Record make_record(std::string_view type, std::string_view key, const Value& fields) const;   // fields: a dict

  // ---- encoding
  void encode(const DecisionContext& ctx, Encoded& out, PropCache* cache = nullptr) const;   // throws TokenError
  bool try_encode(const DecisionContext& ctx, Encoded& out, std::string* why = nullptr, PropCache* cache = nullptr) const;

  struct Impl;
 private:
  std::unique_ptr<Impl> impl_;
};

}  // namespace em::social::tok2
