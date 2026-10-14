#include "emergence/social/side_table.h"

#include <cstring>

namespace em::social {

ListRef Remap::map(ListRef old_ref) const {
  auto it = std::lower_bound(pairs_.begin(), pairs_.end(), std::pair<ListRef, ListRef>{old_ref, 0});
  return (it != pairs_.end() && it->first == old_ref) ? it->second : 0;
}

void SideTable::reset() {
  words_.fill(0);
  starts_.reset();
  end_ = live_words_ = live_count_ = truncated_ = 0;
  gens_.fill(0);
}

bool SideTable::locate(ListRef ref, std::size_t& offset) const {
  if (ref == 0) return false;
  const std::size_t off = (ref & 0xFFFu) - 1;
  if (off >= end_ || !starts_.test(off)) return false;
  const std::uint32_t h = words_[off];
  if (!(h & kLive) || ((h >> 11) & kGenMax) != (ref >> 12)) return false;
  offset = off;
  return true;
}

bool SideTable::valid(ListRef ref) const {
  std::size_t off;
  return locate(ref, off);
}

std::span<const std::uint32_t> SideTable::get(ListRef ref) const {
  std::size_t off;
  if (!locate(ref, off)) return {};
  return {words_.data() + off + 1, words_[off] & 0x7FFu};
}

ListRef SideTable::put(std::span<const std::uint32_t> items, std::size_t max_items) {
  std::size_t n = std::min({items.size(), max_items, kMaxItems});
  bool cut = n < items.size();
  if (n == 0) {
    if (cut) ++truncated_;
    return 0;
  }
  // Largest block available (free blocks and the untouched tail), in words.
  std::size_t largest = kWords - end_;
  for (std::size_t o = 0; o < end_; o += block_words(words_[o]))
    if (!(words_[o] & kLive)) largest = std::max(largest, block_words(words_[o]));
  if (largest < 2) {
    ++truncated_;
    return 0;
  }
  if (n + 1 > largest) {
    n = largest - 1;
    cut = true;
  }
  if (cut) ++truncated_;
  // First fit by offset.
  std::size_t at = kWords;
  for (std::size_t o = 0; o < end_; o += block_words(words_[o])) {
    if (!(words_[o] & kLive) && block_words(words_[o]) >= n + 1) {
      at = o;
      break;
    }
  }
  if (at == kWords) {
    at = end_;
    end_ += n + 1;
  } else {
    const std::size_t total = block_words(words_[at]);
    if (total > n + 1) words_[at + n + 1] = static_cast<std::uint32_t>(total - (n + 1));   // free remainder
  }
  const std::uint32_t gen = bump_gen(at);
  words_[at] = live_header(gen, n);
  std::memcpy(words_.data() + at + 1, items.data(), n * sizeof(std::uint32_t));
  starts_.set(at);
  live_words_ += n + 1;
  ++live_count_;
  return make_ref(gen, at);
}

void SideTable::release(ListRef ref) {
  std::size_t off;
  if (!locate(ref, off)) return;
  const std::size_t total = block_words(words_[off]);
  std::fill_n(words_.begin() + off, total, 0u);
  words_[off] = static_cast<std::uint32_t>(total);
  starts_.reset(off);
  live_words_ -= total;
  --live_count_;
  coalesce();
}

void SideTable::coalesce() {
  std::size_t o = 0;
  while (o < end_) {
    const std::size_t sz = block_words(words_[o]);
    if (!(words_[o] & kLive)) {
      std::size_t next = o + sz;
      std::size_t total = sz;
      while (next < end_ && !(words_[next] & kLive)) {
        const std::size_t s2 = block_words(words_[next]);
        words_[next] = 0;
        total += s2;
        next += s2;
      }
      if (next >= end_) {   // trailing free space returns to the tail
        std::fill_n(words_.begin() + o, total, 0u);
        end_ = o;
        return;
      }
      words_[o] = static_cast<std::uint32_t>(total);
      o += total;
    } else {
      o += sz;
    }
  }
}

void SideTable::compact(Remap& remap) {
  remap.pairs_.clear();
  std::size_t dst = 0;
  std::size_t o = 0;
  const std::size_t old_end = end_;
  starts_.reset();
  while (o < old_end) {
    const std::size_t sz = block_words(words_[o]);
    if (words_[o] & kLive) {
      const std::uint32_t old_gen = (words_[o] >> 11) & kGenMax;
      const std::uint32_t gen = bump_gen(dst);   // every surviving block gets a fresh reference
      if (dst != o) std::memmove(words_.data() + dst, words_.data() + o, sz * sizeof(std::uint32_t));
      words_[dst] = live_header(gen, sz - 1);
      remap.pairs_.emplace_back(make_ref(old_gen, o), make_ref(gen, dst));
      starts_.set(dst);
      dst += sz;
    }
    o += sz;
  }
  std::fill(words_.begin() + dst, words_.begin() + old_end, 0u);
  end_ = dst;
  std::sort(remap.pairs_.begin(), remap.pairs_.end());
}

std::uint64_t SideTable::layout_hash() const {
  std::uint64_t h = 1469598103934665603ull;
  auto mix = [&h](std::uint64_t v) {
    for (int i = 0; i < 8; ++i) {
      h ^= (v >> (8 * i)) & 0xFFu;
      h *= 1099511628211ull;
    }
  };
  for (std::size_t i = 0; i < end_; ++i) mix(words_[i]);
  mix(end_); mix(live_words_); mix(live_count_); mix(truncated_);
  for (std::size_t i = 0; i < kWords; ++i) mix(gens_[i]);
  return h;
}

}  // namespace em::social
