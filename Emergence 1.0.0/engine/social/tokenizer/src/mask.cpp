#include "emergence/social/tokenizer/mask.h"

#include "tok2_gen.h"

namespace em::social::tok2 {

static_assert(gen::kNumGestures == kMaskGestures, "tok2_gen.h changed: update mask.h");

int MaskResult::feasible_count() const {
  int n = 0;
  for (const auto& g : gestures) n += g.feasible;
  return n;
}

FeasibilityMask::FeasibilityMask(const Tokenizer& tk) {
  const int e = tk.type_index("ENTITY");
  present_col_ = tk.column_def(e, tk.column(e, "present")).col;
  type_entity_ = tk.type_def(e).id;
  type_thing_ = tk.type_def(tk.type_index("THING")).id;
  type_inv_ = tk.type_def(tk.type_index("INV")).id;
  type_self_ = tk.type_def(tk.type_index("SELF")).id;
  for (const char* n : {"take", "grab", "strike", "push", "pull"}) {
    const int g = gesture_index(n);
    if (g >= 0) self_excluded_[std::size_t(g)] = true;
  }
}

const char* FeasibilityMask::gesture_name(int g) const { return gen::kGestureMasks[g].name.data(); }
int FeasibilityMask::gesture_index(std::string_view name) const {
  for (int g = 0; g < gen::kNumGestures; ++g) if (gen::kGestureMasks[g].name == name) return g;
  return -1;
}

void FeasibilityMask::compute(const Encoded& enc, MaskResult& out) const {
  for (int g = 0; g < gen::kNumGestures; ++g) {
    const GestureMaskDef& def = gen::kGestureMasks[g];
    GestureMask& gm = out.gestures[std::size_t(g)];
    gm = GestureMask{};
    bool feasible = true;
    for (int k = 0; k < def.n_refs; ++k) {
      const RefParamDef& rp = def.refs[k];
      RefMask& rm = gm.refs[std::size_t(k)];
      rm.used = true;
      rm.optional = rp.optional;
      rm.direction = rp.accepts_direction;
      rm.form = rp.accepts_form;
      if (rp.optional) rm.allowed.set(0);
      bool any = false;
      for (std::uint32_t r = 0; r < enc.n; ++r) {
        const int tid = enc.type_id[r];
        if (tid >= 32 || !((rp.type_mask >> tid) & 1)) continue;   // a corrupt type id (buffer from outside) matches nothing
        if (tid == type_thing_ || tid == type_inv_) {
          const int col = tid == type_thing_ ? rp.req_col_thing : rp.req_col_inv;
          // the dossier says the object LACKS the property: known and zero (unknown does not forbid)
          if (col >= 0 && enc.known[r][std::size_t(col)] && enc.num[r][std::size_t(col)] == 0) continue;
        } else if (tid == type_self_ && def.contact && rp.party && self_excluded_[std::size_t(g)]) {
          continue;   // one does not take, grab, strike, push or pull oneself (but one touches, examines, searches, ties, dresses oneself)
        } else if (tid == type_entity_ && def.contact && rp.party) {
          if (enc.known[r][std::size_t(present_col_)] && enc.num[r][std::size_t(present_col_)] == 0) continue;   // known absent
        }
        rm.allowed.set(r + 1);
        any = true;
      }
      if (!rp.optional && !any && !rp.accepts_direction && !rp.accepts_form) feasible = false;
    }
    gm.feasible = feasible;
  }
}

}  // namespace em::social::tok2
