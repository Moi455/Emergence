// Per-NPC side table for variable-size lists of u32 (docs/14 section 7.3).
// A fixed 8 KiB word array holds blocks [header | items...]. A ListRef is
// (generation << 12) | (offset + 1); 0 means the empty list. The offset needs 12 bits
// (2048 words), the generation 20 bits. The generation is kept PER OFFSET and is bumped each
// time a block is created at that offset (put, or a block landing there during compact), and the
// live header repeats it, so a stale reference reads as empty. Aliasing needs exactly 2^20 - 1
// (1 048 575) block creations at the very same offset between taking a reference and using it:
// the counter then wraps 1..2^20-1 and an ancient reference would match again. This is
// documented, not detected; it is "never in practice" (owners remap refs on every compact). All placement is first-fit by offset: no address-dependent order.
#pragma once
#include <algorithm>
#include <array>
#include <bitset>
#include <cstddef>
#include <cstdint>
#include <span>
#include <utility>
#include <vector>

#include "emergence/social/state_types.h"

namespace em::social {

// Old-to-new reference map filled by SideTable::compact(); owners call map() on each ListRef they hold.
class Remap {
 public:
  ListRef map(ListRef old_ref) const;   // unknown or empty reference -> 0
  std::size_t size() const { return pairs_.size(); }

 private:
  friend class SideTable;
  std::vector<std::pair<ListRef, ListRef>> pairs_;   // sorted by old reference value
};

class SideTable {
 public:
  static constexpr std::size_t kBudgetBytes = 8 * 1024;
  static constexpr std::size_t kWords = kBudgetBytes / sizeof(std::uint32_t);
  static constexpr std::size_t kMaxItems = 0x7FF; static constexpr std::uint32_t kGenMax = (1u << 20) - 1;
  static constexpr std::size_t kNoLimit = static_cast<std::size_t>(-1);

  SideTable() { reset(); }

  // Stores a copy. Items must already be ordered most salient first: the list is cut to max_items
  // and then to what fits in the largest free block (prefix kept, never random). Nothing fits
  // or empty input -> 0. Any cut increments truncated_lists().
  ListRef put(std::span<const std::uint32_t> items, std::size_t max_items = kNoLimit);
  // Empty span for 0, a stale or invalid reference.
  std::span<const std::uint32_t> get(ListRef ref) const;
  bool valid(ListRef ref) const;
  void release(ListRef ref);          // stale or empty: no effect
  void compact(Remap& remap);         // slides live blocks down; fills remap
  void reset();

  std::size_t bytes() const { return live_words_ * sizeof(std::uint32_t); }   // live blocks incl. headers
  static constexpr std::size_t capacity_bytes() { return kBudgetBytes; }
  std::size_t live_lists() const { return live_count_; }
  std::size_t truncated_lists() const { return truncated_; }
  std::uint64_t layout_hash() const;  // fnv1a64 of words + counters: identical across identical runs

 private:
  // Header word: bit 31 = live; live: gen in bits 11..30, length in 0..10;
  // free: total block words (header included) in 0..23.
  static constexpr std::uint32_t kLive = 0x80000000u;
  static std::uint32_t live_header(std::uint32_t gen, std::size_t len) { return kLive | (gen << 11) | std::uint32_t(len); }
  static std::size_t block_words(std::uint32_t h) { return (h & kLive) ? 1 + (h & 0x7FFu) : (h & 0xFFFFFFu); }
  static ListRef make_ref(std::uint32_t gen, std::size_t offset) { return (gen << 12) | std::uint32_t(offset + 1); }
  bool locate(ListRef ref, std::size_t& offset) const;
  void coalesce();

  std::array<std::uint32_t, kWords> words_{};
  std::bitset<kWords> starts_;     // offsets where a live block header sits (guards against mid-block refs)
  std::size_t end_ = 0;            // words in use by blocks (live or free), tail beyond is untouched
  std::size_t live_words_ = 0;
  std::size_t live_count_ = 0;
  std::size_t truncated_ = 0;
  std::array<std::uint32_t, kWords> gens_{};   // per-offset generation counter (1..kGenMax, 0 = never used)
  std::uint32_t bump_gen(std::size_t offset) { gens_[offset] = gens_[offset] % kGenMax + 1; return gens_[offset]; }
};

}  // namespace em::social
