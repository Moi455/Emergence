// Basic types of the NPC state (hand-written; the component structs themselves are generated from catalogue/).
#pragma once
#include <array>
#include <cstdint>

namespace em::social {

using EntityId = std::uint32_t;   // objective id: engine only, never read by the model
using GameTime = std::int64_t;    // game seconds (D30: a day is 1 h 30 real)
using ListRef = std::uint32_t;    // handle into a side table of variable-size data (0 = empty)

// A persistent reference to one of the NPC's OWN records (a mental file, a belief, a memory...): never an
// objective id, never a token slot. serial 0 = none.
struct MRef {
  std::uint32_t serial = 0;
  bool operator==(const MRef&) const = default;
};

// A proposition of the inner language in prefix order: up to 20 symbols, each with its number of children.
// symbol = tag << 24 | value (24 bits).
class Proposition {
 public:
  enum Tag : std::uint8_t { kNone = 0, kWord = 1, kKind = 2, kKindQty = 3, kNumber = 4, kRef = 5, kName = 6 };
  static constexpr int kMax = 20;

  static constexpr std::uint32_t make(Tag t, std::uint32_t value) { return (std::uint32_t(t) << 24) | (value & 0xFFFFFF); }
  static constexpr Tag tag(std::uint32_t s) { return static_cast<Tag>(s >> 24); }
  static constexpr std::uint32_t value(std::uint32_t s) { return s & 0xFFFFFF; }

  bool push(std::uint32_t symbol, std::uint8_t children) {
    if (n_ >= kMax) return false;
    sym_[n_] = symbol;
    arity_[n_] = children;
    ++n_;
    return true;
  }
  int size() const { return n_; }
  std::uint32_t symbol(int i) const { return sym_[i]; }
  std::uint8_t children(int i) const { return arity_[i]; }
  bool empty() const { return n_ == 0; }
  // A proposition is well formed when the children counts describe exactly one tree.
  bool well_formed() const {
    int open = 1;
    for (int i = 0; i < n_; ++i) {
      if (open <= 0) return false;
      open += arity_[i] - 1;
    }
    return n_ > 0 && open == 0;
  }

 private:
  std::array<std::uint32_t, kMax> sym_{};
  std::array<std::uint8_t, kMax> arity_{};
  std::uint8_t n_ = 0;
};

// Fixed-capacity records of one kind for one NPC (beliefs, mental files, memories...). Each record gets a
// persistent serial; when the pool is full, the engine law of forgetting picks the record to drop (lowest score).
template <class T, int N>
class RecordPool {
 public:
  static constexpr int kCapacity = N;

  template <class Score>
  MRef add(const T& rec, Score&& score) {
    int slot = -1;
    for (int i = 0; i < N; ++i)
      if (serial_[i] == 0) { slot = i; break; }
    if (slot < 0) {                       // full: forget the lowest-scored record (ties: the oldest serial)
      slot = 0;
      for (int i = 1; i < N; ++i) {
        const auto si = score(items_[i]), s0 = score(items_[slot]);
        if (si < s0 || (si == s0 && serial_[i] < serial_[slot])) slot = i;
      }
      --count_;
    }
    items_[slot] = rec;
    serial_[slot] = ++next_serial_;
    ++count_;
    return MRef{serial_[slot]};
  }
  MRef add(const T& rec) { return add(rec, [](const T&) { return 0; }); }

  T* find(MRef r) {
    if (r.serial == 0) return nullptr;
    for (int i = 0; i < N; ++i)
      if (serial_[i] == r.serial) return &items_[i];
    return nullptr;
  }
  bool remove(MRef r) {
    for (int i = 0; i < N; ++i)
      if (r.serial != 0 && serial_[i] == r.serial) { serial_[i] = 0; --count_; return true; }
    return false;
  }
  template <class F>
  void for_each(F&& f) {
    for (int i = 0; i < N; ++i)
      if (serial_[i] != 0) f(MRef{serial_[i]}, items_[i]);
  }
  int size() const { return count_; }

 private:
  std::array<T, N> items_{};
  std::array<std::uint32_t, N> serial_{};
  std::uint32_t next_serial_ = 0;
  int count_ = 0;
};

}  // namespace em::social
