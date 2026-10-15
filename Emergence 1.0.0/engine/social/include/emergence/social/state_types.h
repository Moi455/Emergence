// Basic types of the NPC state (hand-written; the component structs themselves are generated from catalogue/).
#pragma once
#include <algorithm>
#include <array>
#include <concepts>
#include <cstdint>

namespace em::social {

using EntityId = std::uint32_t;   // objective id: engine only, never read by the model
using GameTime = std::int64_t;    // game seconds (D30: a day is 1 h 30 real)
using ListRef = std::uint32_t;    // handle into a side table of variable-size data (0 = empty)

// A game time STORED in a record: the same 64 bits as a GameTime, kept as two 32-bit halves so that the alignment is 4,
// not 8. Records then need no 8-byte tail padding (about 1 KiB per NPC, T06). Converts to and from GameTime implicitly;
// the save codec copies the 8 bytes (little-endian: the same bytes as an int64).
class PackedTime {
 public:
  constexpr PackedTime() = default;
  constexpr PackedTime(GameTime t) : lo_(std::uint32_t(std::uint64_t(t))), hi_(std::uint32_t(std::uint64_t(t) >> 32)) {}
  constexpr operator GameTime() const { return static_cast<GameTime>(std::uint64_t(hi_) << 32 | lo_); }
  constexpr PackedTime& operator+=(GameTime d) { return *this = GameTime(*this) + d; }
  constexpr PackedTime& operator-=(GameTime d) { return *this = GameTime(*this) - d; }

 private:
  std::uint32_t lo_ = 0, hi_ = 0;
};
static_assert(sizeof(PackedTime) == 8 && alignof(PackedTime) == 4);

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
// persistent serial. When the pool is full, the law of forgetting (catalogue/data/forgetting.toml, generated as
// gen::forgetting_score / gen::forgetting_protected) picks the record to drop: the lowest score, a tie drops the oldest
// serial, and a protected record is spared while any other record can go. A pool whose records are ALL protected does
// not refuse the addition (decision of 15 Oct. 2026): it evicts the worst protected record (same law of score, a tie
// drops the oldest) and counts it in evicted_protected(), so that an NPC never stops forming memories. The capacity is
// the compiled N (fixed in v1).
template <class T, int N>
class RecordPool {
 public:
  static constexpr int kCapacity = N;
  using value_type = T;

  // The law of the catalogue: found by ADL on the generated record type T (forgetting_kind/score/protected).
  // `now` (game seconds) dates the recencies of the score: it has NO default, a forgotten date would silently make
  // every recency worth 100.
  MRef add(const T& rec, GameTime now) {
    const auto kind = forgetting_kind(rec);
    return add(rec, [&](const T& r) { return forgetting_score(kind, r, now); },
               [&](const T& r) { return forgetting_protected(kind, r); });
  }
  template <class Score>
    requires std::invocable<Score&, const T&>
  MRef add(const T& rec, Score&& score) {
    return add(rec, score, [](const T&) { return false; });
  }
  template <class Score, class Protected>
  MRef add(const T& rec, Score&& score, Protected&& is_protected) {
    int slot = -1;
    for (int i = 0; i < N; ++i)
      if (serial_[i] == 0) { slot = i; break; }
    if (slot < 0) {                       // full: forget the lowest-scored unprotected record (ties: the oldest serial)
      int worst_protected = -1;
      for (int i = 0; i < N; ++i) {
        int& best = is_protected(items_[i]) ? worst_protected : slot;
        if (best < 0) { best = i; continue; }
        const auto si = score(items_[i]), s0 = score(items_[best]);
        if (si < s0 || (si == s0 && serial_[i] < serial_[best])) best = i;
      }
      if (slot < 0) {                     // everything is protected: the worst of them goes, and it is counted
        slot = worst_protected;
        ++evicted_protected_;
      }
      --count_;
      ++forgotten_;
    }
    items_[slot] = rec;
    serial_[slot] = ++next_serial_;
    ++count_;
    return MRef{serial_[slot]};
  }
  int forgotten() const { return forgotten_; }                    // records dropped by the law (protected ones included)
  int evicted_protected() const { return evicted_protected_; }   // of which protected, because every record was

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
  // Drops a record BECAUSE the law of forgetting chose it (not a plain remove): counted in forgotten(), and in
  // evicted_protected() when it was protected. Used to free room elsewhere (the proposition arena, T06).
  bool forget(MRef r, bool was_protected) {
    if (!remove(r)) return false;
    ++forgotten_;
    if (was_protected) ++evicted_protected_;
    return true;
  }
  template <class F>
  void for_each(F&& f) {
    for (int i = 0; i < N; ++i)
      if (serial_[i] != 0) f(MRef{serial_[i]}, items_[i]);
  }
  int size() const { return count_; }

  // Persistence (T04): read and rebuild a pool slot by slot, keeping the serials, the slots and the counters.
  // The save codec uses these; nothing else should.
  bool slot_used(int slot) const { return slot >= 0 && slot < N && serial_[slot] != 0; }
  std::uint32_t slot_serial(int slot) const { return serial_[slot]; }
  const T& slot_record(int slot) const { return items_[slot]; }
  T& slot_record_mut(int slot) { return items_[slot]; }   // load-time sanitising only
  std::uint32_t next_serial() const { return next_serial_; }
  void clear() { *this = RecordPool{}; }
  // Fills a FREE slot with a record of a given serial (> 0). Uniqueness of the serials is checked once by restore_counters. False = refused (slot busy or out of range).
  bool restore_slot(int slot, std::uint32_t serial, const T& rec) {
    if (slot < 0 || slot >= N || serial == 0 || serial_[slot] != 0) return false;
    items_[slot] = rec;
    serial_[slot] = serial;
    ++count_;
    return true;
  }
  // Sets the counters once the slots are restored; next_serial must be at least the highest serial, or a serial would repeat.
  bool restore_counters(std::uint32_t next_serial, int forgotten, int evicted_protected) {
    std::array<std::uint32_t, N> used{};
    int n = 0;
    for (int i = 0; i < N; ++i) {
      if (serial_[i] > next_serial) return false;
      if (serial_[i] != 0) used[n++] = serial_[i];
    }
    std::sort(used.begin(), used.begin() + n);
    for (int i = 1; i < n; ++i)
      if (used[i] == used[i - 1]) return false;   // a serial twice: a corrupt save
    if (forgotten < 0 || evicted_protected < 0) return false;
    next_serial_ = next_serial;
    forgotten_ = forgotten;
    evicted_protected_ = evicted_protected;
    return true;
  }

 private:
  std::array<T, N> items_{};
  std::array<std::uint32_t, N> serial_{};
  std::uint32_t next_serial_ = 0;
  int count_ = 0;
  int evicted_protected_ = 0;
  int forgotten_ = 0;
};

}  // namespace em::social
