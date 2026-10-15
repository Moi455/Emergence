// FeasibilityMask (T28): which gestures and which pointers are possible FOR THE NPC, computed on the arrays of the
// tokenizer only (what he perceives and believes), never on the world. A thing he believes is not graspable is masked
// even if it is; a thing he has no information on is not masked. What the world refuses fails physically, on the spot,
// and that failure is perceived (docs/14 section 4.3). Rules, from the catalogue (`requires`, `contact`, `party_params`):
//  - a pointer parameter accepts the record types its `accepts` classes can stand for (same table as the student's
//    ref_type_ok) and "nobody" only when optional; a direction or a form is offered only when `accepts` says so;
//  - a THING or INV that the dossier says LACKS the property `requires` asks for (known flag set, value 0) is masked;
//  - the touched party of a contact gesture (`party_params`) is not a person known absent (ENTITY.present = false), and
//    is not oneself for take, grab, strike, push and pull (touch, examine, search, tie and wear on oneself stay possible:
//    touching one's own wound, bandaging oneself);
//  - a gesture is feasible when each mandatory pointer parameter has at least one candidate (or a direction/form).
#pragma once
#include <array>
#include <bitset>
#include <cstdint>

#include "emergence/social/tokenizer/tokenizer.h"

namespace em::social::tok2 {

inline constexpr int kMaskGestures = 40, kMaskRefs = 3, kPointerSpace = kMaxTokens + 1;   // index 0 = nobody, 1..128 = token slot

struct RefMask {
  bool used = false;                  // the gesture has a k-th pointer parameter
  bool optional = false;
  bool direction = false, form = false;
  std::bitset<kPointerSpace> allowed;   // bit 0: nobody; bit s: the token of slot s
};

struct GestureMask {
  bool feasible = false;
  std::array<RefMask, kMaskRefs> refs;
};

struct MaskResult {
  std::array<GestureMask, kMaskGestures> gestures;
  int feasible_count() const;
};

class FeasibilityMask {
 public:
  explicit FeasibilityMask(const Tokenizer& tk);
  const char* gesture_name(int g) const;
  int gesture_index(std::string_view name) const;   // -1: unknown
  // Reads only `enc` (the decision's dossier as tokenized).
  void compute(const Encoded& enc, MaskResult& out) const;

 private:
  int present_col_ = -1;
  std::array<bool, kMaskGestures> self_excluded_{};
  int type_thing_ = 0, type_inv_ = 0, type_entity_ = 0, type_self_ = 0;
};

}  // namespace em::social::tok2
