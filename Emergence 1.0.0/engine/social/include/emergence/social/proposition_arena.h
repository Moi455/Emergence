// Per-NPC arena of propositions (docs/14 section 7.4, T06).
// The state records do not hold a 100-byte Proposition any more: they hold a PropRef (4 bytes) into this arena, a
// fixed 20 KiB array of 5120 words. The Proposition of 20 symbols stays the type of EXCHANGE (parser, codec,
// governor): put() packs it, get() unpacks it.
//
// A symbol takes ONE word: tag (3 bits, 0..6) | children (5 bits, 0..19) | value (24 bits). A block is the symbols of one
// proposition in prefix order, with no header (the length lives in the PropRef).
//   PropRef = epoch (14 bits) << 18 | length (5 bits) << 13 | (offset + 1) (13 bits);   0 = empty.
// Placement is a bump: deterministic, no allocation, no address-dependent order. Space is only recovered by collect(),
// which copies the live blocks down in the order its caller visits them and bumps the epoch, so that a PropRef taken
// before a collection reads as EMPTY afterwards (never as another proposition). Aliasing needs 2^14 collections
// between taking a reference and using it: documented, not detected.
// A full arena never aborts and never allocates: put() answers 0 (and the owner applies the law of forgetting, see
// NpcBundle::store_proposition, which then retries). refused() counts the propositions that could not be kept at all.
#pragma once
#include <array>
#include <cstddef>
#include <cstdint>

#include "emergence/social/state_types.h"

namespace em::social {

using PropRef = std::uint32_t;   // handle into the NPC's PropositionArena (0 = empty)

class PropositionArena {
 public:
  static constexpr std::size_t kBudgetBytes = 20 * 1024;
  static constexpr std::size_t kWords = kBudgetBytes / sizeof(std::uint32_t);   // 5120
  static constexpr std::uint32_t kEpochMax = (1u << 14) - 1;

  // Stores a copy. 0 when the proposition is empty, ill formed (children counts that are not one tree, a tag above 7
  // or more than 31 children) or when there is no room: the caller tells the cases apart with can_hold().
  PropRef put(const Proposition& p) {
    if (p.empty() || !packable(p) || !p.well_formed()) return 0;
    const std::size_t n = static_cast<std::size_t>(p.size());
    if (kWords - used_ < n) return 0;
    for (std::size_t i = 0; i < n; ++i) words_[used_ + i] = pack(p.symbol(int(i)), p.children(int(i)));
    const PropRef ref = make_ref(epoch_, n, used_);
    used_ += n;
    return ref;
  }
  // The proposition behind a reference; empty for 0, a stale reference or a corrupt block.
  Proposition get(PropRef ref) const {
    Proposition p;
    std::size_t off = 0, len = 0;
    if (!locate(ref, off, len)) return p;
    for (std::size_t i = 0; i < len; ++i) p.push(symbol_of(words_[off + i]), children_of(words_[off + i]));
    if (!p.well_formed()) return Proposition{};
    return p;
  }
  bool valid(PropRef ref) const { std::size_t o, l; return locate(ref, o, l); }
  std::size_t length(PropRef ref) const { std::size_t o, l; return locate(ref, o, l) ? l : 0; }
  // True when a proposition of `symbols` symbols fits right now (without a collection).
  bool has_room(std::size_t symbols) const { return kWords - used_ >= symbols; }

  // Compaction: `visit(f)` must call f(PropRef&) once for EVERY PropRef that is still alive, in a deterministic order.
  // Live blocks are copied down in that order and the references rewritten; a reference that is no longer valid is
  // set to 0. Costs one pass over the live words and a 20 KiB stack buffer; no heap.
  template <class Visit>
  void collect(Visit&& visit) {
    std::array<std::uint32_t, kWords> next;
    std::size_t n = 0;
    const std::uint32_t epoch = epoch_ % kEpochMax + 1;
    visit([&](PropRef& ref) {
      std::size_t off = 0, len = 0;
      if (!locate(ref, off, len)) { ref = 0; return; }
      for (std::size_t i = 0; i < len; ++i) next[n + i] = words_[off + i];
      ref = make_ref(epoch, len, n);
      n += len;
    });
    for (std::size_t i = 0; i < n; ++i) words_[i] = next[i];
    used_ = n;
    epoch_ = epoch;
    ++collections_;
  }

  void reset() { *this = PropositionArena{}; }
  void note_refused() { ++refused_; }
  void note_reclaimed() { ++reclaimed_; }

  std::size_t used_words() const { return used_; }
  std::size_t used_bytes() const { return used_ * sizeof(std::uint32_t); }
  static constexpr std::size_t capacity_bytes() { return kBudgetBytes; }
  std::size_t refused() const { return refused_; }          // propositions lost for lack of room, after the law of forgetting
  std::size_t reclaimed() const { return reclaimed_; }      // records forgotten by the law to make room
  std::size_t collections() const { return collections_; }
  double fill() const { return double(used_) / double(kWords); }

 private:
  static bool packable(const Proposition& p) {
    for (int i = 0; i < p.size(); ++i)
      if (Proposition::tag(p.symbol(i)) > 7 || p.children(i) > 31) return false;
    return true;
  }
  static std::uint32_t pack(std::uint32_t symbol, std::uint8_t children) {
    return (symbol >> 24) << 29 | std::uint32_t(children) << 24 | Proposition::value(symbol);
  }
  static std::uint32_t symbol_of(std::uint32_t w) { return (w >> 29) << 24 | (w & 0xFFFFFF); }
  static std::uint8_t children_of(std::uint32_t w) { return std::uint8_t((w >> 24) & 31); }
  static PropRef make_ref(std::uint32_t epoch, std::size_t len, std::size_t off) {
    return epoch << 18 | std::uint32_t(len) << 13 | std::uint32_t(off + 1);
  }
  bool locate(PropRef ref, std::size_t& off, std::size_t& len) const {
    if (ref == 0 || (ref >> 18) != epoch_) return false;
    len = (ref >> 13) & 31;
    off = (ref & 0x1FFF) - 1;   // the low 13 bits are never 0 in a reference made here; 0 wraps and fails the bound
    return len >= 1 && len <= std::size_t(Proposition::kMax) && off < kWords && off + len <= used_;
  }

  std::array<std::uint32_t, kWords> words_{};
  std::uint32_t epoch_ = 1;
  std::uint32_t used_ = 0;
  std::uint32_t refused_ = 0, reclaimed_ = 0, collections_ = 0;
};

}  // namespace em::social
