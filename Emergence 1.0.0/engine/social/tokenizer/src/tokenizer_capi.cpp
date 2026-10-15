#include "emergence/social/tokenizer/tokenizer_capi.h"

#include <cstdio>
#include <cstring>
#include <exception>
#include <string>

#include "emergence/social/tokenizer/mask.h"
#include "emergence/social/tokenizer/tokenizer.h"
#include "tok2_gen.h"

using namespace em::social::tok2;

struct em_tok2 {
  Tokenizer tokenizer;
  FeasibilityMask mask{tokenizer};
  PropCache cache;
  Encoded scratch;
};

namespace {
constexpr int kArrays = 12;
struct ArrayInfo { const char* name; std::size_t bytes; int itemsize; int cols; };
constexpr ArrayInfo kInfo[kArrays] = {
    {"type_id", sizeof(Encoded::type_id), 1, 0},
    {"num", sizeof(Encoded::num), 2, kNumWidth},
    {"known", sizeof(Encoded::known), 1, kNumWidth},
    {"cat", sizeof(Encoded::cat), 2, kCatWidth},
    {"cat_known", sizeof(Encoded::cat_known), 1, kCatWidth},
    {"ptr", sizeof(Encoded::ptr), 1, kPtrWidth},
    {"ptr_known", sizeof(Encoded::ptr_known), 1, kPtrWidth},
    {"prop_sym", sizeof(Encoded::prop_sym), 2, kPropLen},
    {"prop_arity", sizeof(Encoded::prop_arity), 1, kPropLen},
    {"prop_depth", sizeof(Encoded::prop_depth), 1, kPropLen},
    {"prop_slot", sizeof(Encoded::prop_slot), 1, kPropLen},
    {"prop_num", sizeof(Encoded::prop_num), 2, kPropLen},
};

std::size_t offset_of(int i) {
  std::size_t o = 0;
  for (int k = 0; k < i; ++k) o += kInfo[k].bytes;
  return o;
}
std::size_t total() { return offset_of(kArrays); }

const void* array_ptr(const Encoded& e, int i) {
  switch (i) {
    case 0: return e.type_id.data(); case 1: return e.num.data(); case 2: return e.known.data(); case 3: return e.cat.data();
    case 4: return e.cat_known.data(); case 5: return e.ptr.data(); case 6: return e.ptr_known.data(); case 7: return e.prop_sym.data();
    case 8: return e.prop_arity.data(); case 9: return e.prop_depth.data(); case 10: return e.prop_slot.data(); default: return e.prop_num.data();
  }
}
void* array_ptr_mut(Encoded& e, int i) { return const_cast<void*>(array_ptr(e, i)); }

void pack(const Encoded& e, void* buffer) {
  auto* b = static_cast<unsigned char*>(buffer);
  for (int i = 0; i < kArrays; ++i) { std::memcpy(b, array_ptr(e, i), kInfo[i].bytes); b += kInfo[i].bytes; }
}
void unpack(const void* buffer, Encoded& e) {
  const auto* b = static_cast<const unsigned char*>(buffer);
  for (int i = 0; i < kArrays; ++i) { std::memcpy(array_ptr_mut(e, i), b, kInfo[i].bytes); b += kInfo[i].bytes; }
}
void put_err(char* err, std::size_t cap, const std::string& m) {
  if (!err || cap == 0) return;
  std::snprintf(err, cap, "%s", m.c_str());
}

int encode_one(em_tok2* h, const char* json, std::size_t len, void* buffer, em_tok2_info* info, char* err, std::size_t cap) {
  try {
    const DecisionContext ctx = h->tokenizer.load_context(std::string_view(json, len));
    h->tokenizer.encode(ctx, h->scratch, &h->cache);
    pack(h->scratch, buffer);
    if (info) {
      info->n = h->scratch.n;
      info->digest = h->scratch.digest();
      info->n_ghosts = std::uint32_t(h->scratch.ghosts.size());
      info->reserved = 0;
    }
    return 0;
  } catch (const TokenError& e) {
    put_err(err, cap, e.what());
    return 1;
  } catch (const std::exception& e) {
    put_err(err, cap, std::string("internal error: ") + e.what());
    return 1;
  } catch (...) {
    put_err(err, cap, "internal error");
    return 1;
  }
}
}  // namespace

extern "C" {

em_tok2* em_tok2_create(void) {
  try { return new em_tok2(); } catch (...) { return nullptr; }
}
void em_tok2_destroy(em_tok2* h) { delete h; }

uint64_t em_tok2_layout_fingerprint(void) { return gen::kLayoutFingerprint; }
uint64_t em_tok2_interface_fingerprint(void) { return gen::kInterfaceFingerprint; }
uint64_t em_tok2_vocab_fingerprint(void) { return gen::kVocabFingerprint; }

size_t em_tok2_buffer_size(void) { return total(); }
int em_tok2_array_count(void) { return kArrays; }
const char* em_tok2_array_name(int i) { return i >= 0 && i < kArrays ? kInfo[i].name : nullptr; }
size_t em_tok2_array_offset(int i) { return i >= 0 && i < kArrays ? offset_of(i) : 0; }
size_t em_tok2_array_bytes(int i) { return i >= 0 && i < kArrays ? kInfo[i].bytes : 0; }
int em_tok2_array_itemsize(int i) { return i >= 0 && i < kArrays ? kInfo[i].itemsize : 0; }
int em_tok2_array_rows(void) { return kMaxTokens; }
int em_tok2_array_cols(int i) { return i >= 0 && i < kArrays ? kInfo[i].cols : 0; }

int em_tok2_encode_json(em_tok2* h, const char* json, size_t len, void* buffer, em_tok2_info* info, char* err, size_t err_cap) {
  if (!h || !json || !buffer) { put_err(err, err_cap, "null argument"); return 2; }
  return encode_one(h, json, len, buffer, info, err, err_cap);
}

int em_tok2_encode_batch(em_tok2* h, const char* const* jsons, const size_t* lens, int count, void* buffers,
                         em_tok2_info* infos, int* status) {
  if (!h || !jsons || !lens || !buffers || count < 0) return -1;
  int ok = 0;
  const std::size_t sz = total();
  for (int i = 0; i < count; ++i) {
    em_tok2_info local{};
    if (jsons[i] == nullptr) {   // a null text is a refusal of that item, not a crash
      if (infos) infos[i] = em_tok2_info{};
      if (status) status[i] = 2;
      continue;
    }
    const int rc = encode_one(h, jsons[i], lens[i], static_cast<unsigned char*>(buffers) + std::size_t(i) * sz, &local, nullptr, 0);
    if (infos) infos[i] = local;
    if (status) status[i] = rc;
    ok += rc == 0;
  }
  return ok;
}

int em_tok2_feasibility(em_tok2* h, const void* buffer, uint32_t n, uint8_t* out_gesture, uint8_t* out_refs, uint8_t* out_flags) {
  if (!h || !buffer || n > uint32_t(kMaxTokens)) return 2;
  try {
    unpack(buffer, h->scratch);
    h->scratch.n = n;
    for (uint32_t r = 0; r < n; ++r)
      if (h->scratch.type_id[r] > 31) return 2;   // corrupt buffer: a type id outside the 5-bit table (type_mask is 32 bits)
    MaskResult r;
    h->mask.compute(h->scratch, r);
    for (int g = 0; g < kMaskGestures; ++g) {
      const GestureMask& gm = r.gestures[std::size_t(g)];
      if (out_gesture) out_gesture[g] = gm.feasible;
      for (int k = 0; k < kMaskRefs; ++k) {
        const RefMask& rm = gm.refs[std::size_t(k)];
        if (out_flags) out_flags[g * kMaskRefs + k] = std::uint8_t(rm.used | rm.optional << 1 | rm.direction << 2 | rm.form << 3);
        if (out_refs) for (int s = 0; s < kPointerSpace; ++s) out_refs[(g * kMaskRefs + k) * kPointerSpace + s] = rm.allowed[std::size_t(s)];
      }
    }
    return 0;
  } catch (...) {
    return 1;
  }
}
int em_tok2_gesture_count(void) { return kMaskGestures; }
const char* em_tok2_gesture_name(int g) {
  static const Tokenizer tk;
  static const FeasibilityMask m(tk);
  return g >= 0 && g < kMaskGestures ? m.gesture_name(g) : nullptr;
}

uint16_t em_tok2_to_half(double x) { return to_half_bits(x); }
uint32_t em_tok2_crc32(uint32_t crc, const void* data, size_t len) {
  return crc32_update(crc, data, len);
}

}  // extern "C"
