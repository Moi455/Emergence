#include "emergence/act/navigation/mental_map.h"

#include <algorithm>
#include <bit>
#include <cstring>

namespace em::act::navigation {

namespace {
constexpr std::uint8_t kMagic0 = 'M', kMagic1 = 'M', kFormat = 1;
constexpr std::size_t kHeader = 8;
constexpr std::size_t kPlaceBytes = 16, kObstacleBytes = 6;
constexpr std::size_t kVisitedWords = (kTileCount + 63) / 64, kRoadWords = kMaxSegments / 64;

struct Writer {
  std::vector<std::uint8_t>& o;
  void u8(std::uint8_t v) { o.push_back(v); }
  void u16(std::uint16_t v) { u8(std::uint8_t(v)); u8(std::uint8_t(v >> 8)); }
  void u32(std::uint32_t v) { u16(std::uint16_t(v)); u16(std::uint16_t(v >> 16)); }
  void u64(std::uint64_t v) { u32(std::uint32_t(v)); u32(std::uint32_t(v >> 32)); }
};
struct Reader {
  std::span<const std::uint8_t> b; std::size_t i = 0;
  std::uint8_t u8() { return b[i++]; }
  std::uint16_t u16() { std::uint16_t lo = u8(); return std::uint16_t(lo | u8() << 8); }
  std::uint32_t u32() { std::uint32_t lo = u16(); return lo | std::uint32_t(u16()) << 16; }
  std::uint64_t u64() { std::uint64_t lo = u32(); return lo | std::uint64_t(u32()) << 32; }
};
}  // namespace

bool MentalMap::see_position(const Position& p) {
  const std::int32_t t = tile_of(p);
  if (t == kNoTile) return false;
  std::uint64_t& w = visited_[std::size_t(t) >> 6];
  const std::uint64_t bit = std::uint64_t(1) << (t & 63);
  const bool fresh = (w & bit) == 0;
  w |= bit;
  return fresh;
}

void MentalMap::see_segment(int seg) { if (seg >= 0 && seg < kMaxSegments) roads_[std::size_t(seg) >> 6] |= std::uint64_t(1) << (seg & 63); }
void MentalMap::hear_segment(int seg) { see_segment(seg); }

int MentalMap::known_segment_count() const {
  int n = 0;
  for (std::uint64_t w : roads_) n += std::popcount(w);
  return n;
}

int MentalMap::walked_tiles() const {
  int n = 0;
  for (std::uint64_t w : visited_) n += std::popcount(w);
  return n;
}

const MentalMap::Place* MentalMap::place(PlaceKey key) const {
  for (int i = 0; i < place_count_; ++i) if (places_[std::size_t(i)].key == key) return &places_[std::size_t(i)];
  return nullptr;
}

std::uint8_t MentalMap::place_certainty(const Place& p, std::uint16_t day) const {
  if (day <= p.day || p.certainty <= kCertaintyFloor) return p.certainty;
  const int fade = int(day - p.day) / 4;   // one point every 4 days
  return std::uint8_t(std::max<int>(kCertaintyFloor, int(p.certainty) - fade));
}

void MentalMap::learn_place(PlaceKey key, const Position& p, std::uint8_t certainty, std::uint16_t day, bool seen) {
  last_day_ = std::max(last_day_, day);
  for (int i = 0; i < place_count_; ++i) {
    Place& e = places_[std::size_t(i)];
    if (e.key != key) continue;
    // A fresher or surer knowledge replaces; a vaguer rumour never overwrites what is better known, and hearsay never
    // overwrites a place that is both seen and protected (home, workplace).
    if (!seen && e.seen && e.protected_) return;
    if (certainty >= place_certainty(e, last_day_)) { e.x = p[0]; e.y = p[1]; e.certainty = certainty; e.day = day; e.seen = seen; }
    return;
  }
  Place n; n.key = key; n.x = p[0]; n.y = p[1]; n.certainty = certainty; n.day = day; n.seen = seen;
  if (place_count_ < kMaxPlaces) { places_[place_count_++] = n; return; }
  // Full: bounded deterministic forgetting. Victim = unprotected first, then lowest present certainty, oldest, lowest key.
  int victim = 0;
  auto worse = [&](const Place& a, const Place& b) {   // is a a better victim than b?
    if (a.protected_ != b.protected_) return !a.protected_;
    const auto ca = place_certainty(a, last_day_), cb = place_certainty(b, last_day_);
    if (ca != cb) return ca < cb;
    if (a.day != b.day) return a.day < b.day;
    return a.key < b.key;
  };
  for (int i = 1; i < kMaxPlaces; ++i) if (worse(places_[std::size_t(i)], places_[std::size_t(victim)])) victim = i;
  places_[std::size_t(victim)] = n;
}

void MentalMap::see_place(PlaceKey key, const Position& p, std::uint16_t day) { learn_place(key, p, kSeenCertainty, day, true); }
void MentalMap::hear_place(PlaceKey key, const Position& p, std::uint8_t certainty, std::uint16_t day) {
  learn_place(key, p, std::min<std::uint8_t>(certainty, kToldCertaintyMax), day, false);
}
void MentalMap::forget_place(PlaceKey key) {
  for (int i = 0; i < place_count_; ++i)
    if (places_[std::size_t(i)].key == key) {
      for (int j = i; j + 1 < place_count_; ++j) places_[std::size_t(j)] = places_[std::size_t(j) + 1];
      places_[std::size_t(--place_count_)] = Place{};
      return;
    }
}
void MentalMap::protect_place(PlaceKey key, bool on) {
  for (int i = 0; i < place_count_; ++i) if (places_[std::size_t(i)].key == key) places_[std::size_t(i)].protected_ = on;
}

void MentalMap::add_obstacle(std::int32_t a, std::int32_t b, std::uint16_t day, bool told) {
  if (a < 0 || b < 0 || a >= kTileCount || b >= kTileCount || a == b) return;
  last_day_ = std::max(last_day_, day);
  // drop the expired; a duplicate is NOT refreshed by hearsay (repeating a rumour never prolongs it), only seen again
  int w = 0;
  bool known = false;
  for (int i = 0; i < obstacle_count_; ++i) {
    Obstacle o = obstacles_[std::size_t(i)];
    if (last_day_ - o.day > kObstacleLifeDays) continue;
    if ((o.from == a && o.to == b) || (o.from == b && o.to == a)) {
      known = true;
      if (!told) { o.day = std::max(o.day, day); o.told = false; }   // seen: confirmed, and a rumour becomes a fact
    }
    obstacles_[std::size_t(w++)] = o;
  }
  obstacle_count_ = std::uint8_t(w);
  if (known) return;
  auto drop = [&](int idx) {
    for (int j = idx; j + 1 < obstacle_count_; ++j) obstacles_[std::size_t(j)] = obstacles_[std::size_t(j) + 1];
    --obstacle_count_;
  };
  auto oldest = [&](bool want_told) {   // the oldest (first among equals) of the kind, or -1
    int best = -1;
    for (int i = 0; i < obstacle_count_; ++i)
      if (obstacles_[std::size_t(i)].told == want_told && (best < 0 || obstacles_[std::size_t(i)].day < obstacles_[std::size_t(best)].day)) best = i;
    return best;
  };
  if (told) {
    int n_told = 0;
    for (int i = 0; i < obstacle_count_; ++i) n_told += obstacles_[std::size_t(i)].told;
    if (n_told >= kMaxToldObstacles) drop(oldest(true));          // hearsay only displaces hearsay
    if (obstacle_count_ >= kMaxObstacles) return;                 // and never a thing seen
  } else if (obstacle_count_ >= kMaxObstacles) {
    const int t = oldest(true);
    drop(t >= 0 ? t : oldest(false));                             // a rumour goes before a fact
  }
  obstacles_[obstacle_count_++] = {std::uint16_t(a), std::uint16_t(b), day, told};
}
void MentalMap::see_obstacle(std::int32_t a, std::int32_t b, std::uint16_t day) { add_obstacle(a, b, day, false); }
void MentalMap::hear_obstacle(std::int32_t a, std::int32_t b, std::uint16_t day) { add_obstacle(a, b, day, true); }

void MentalMap::disprove_obstacle(std::int32_t a, std::int32_t b) {
  for (int i = 0; i < obstacle_count_; ++i) {
    const Obstacle& o = obstacles_[std::size_t(i)];
    if (o.told && ((o.from == a && o.to == b) || (o.from == b && o.to == a))) {
      for (int j = i; j + 1 < obstacle_count_; ++j) obstacles_[std::size_t(j)] = obstacles_[std::size_t(j) + 1];
      --obstacle_count_;
      return;
    }
  }
}

MentalMap::Edge MentalMap::edge_state(std::int32_t a, std::int32_t b, std::uint16_t day) const {
  Edge r = Edge::Open;
  for (int i = 0; i < obstacle_count_; ++i) {
    const Obstacle& o = obstacles_[std::size_t(i)];
    if (day > o.day && day - o.day > kObstacleLifeDays) continue;
    if ((o.from == a && o.to == b) || (o.from == b && o.to == a)) { if (!o.told) return Edge::Seen; r = Edge::Told; }
  }
  return r;
}

std::size_t MentalMap::serialized_size() const {
  return kHeader + kVisitedWords * 8 + kRoadWords * 8 + std::size_t(place_count_) * kPlaceBytes + std::size_t(obstacle_count_) * kObstacleBytes;
}

void MentalMap::serialize(std::vector<std::uint8_t>& out) const {
  out.clear();
  out.reserve(serialized_size());
  Writer w{out};
  w.u8(kMagic0); w.u8(kMagic1); w.u8(kFormat); w.u8(0);
  w.u16(last_day_); w.u8(place_count_); w.u8(obstacle_count_);
  for (std::uint64_t v : visited_) w.u64(v);
  for (std::uint64_t v : roads_) w.u64(v);
  for (int i = 0; i < place_count_; ++i) {
    const Place& p = places_[std::size_t(i)];
    w.u32(p.key); w.u32(std::uint32_t(p.x)); w.u32(std::uint32_t(p.y)); w.u8(p.certainty); w.u8(std::uint8_t((p.protected_ ? 1 : 0) | (p.seen ? 2 : 0))); w.u16(p.day);
  }
  for (int i = 0; i < obstacle_count_; ++i) {
    const Obstacle& o = obstacles_[std::size_t(i)];
    w.u16(o.from); w.u16(std::uint16_t(o.to | (o.told ? 0x8000 : 0))); w.u16(o.day);
  }
}

bool MentalMap::deserialize(std::span<const std::uint8_t> bytes) {
  MentalMap m;
  auto fail = [&] { *this = MentalMap{}; return false; };
  if (bytes.size() < kHeader) return fail();
  Reader r{bytes};
  if (r.u8() != kMagic0 || r.u8() != kMagic1 || r.u8() != kFormat || r.u8() != 0) return fail();
  m.last_day_ = r.u16();
  const unsigned np = r.u8(), no = r.u8();
  if (np > unsigned(kMaxPlaces) || no > unsigned(kMaxObstacles)) return fail();
  if (bytes.size() != kHeader + kVisitedWords * 8 + kRoadWords * 8 + np * kPlaceBytes + no * kObstacleBytes) return fail();
  for (auto& v : m.visited_) v = r.u64();
  for (auto& v : m.roads_) v = r.u64();
  const int spare = int(kVisitedWords * 64) - kTileCount;   // bits past the last tile must be zero (canonical form)
  if (spare > 0 && (m.visited_.back() >> (64 - spare)) != 0) return fail();
  for (unsigned i = 0; i < np; ++i) {
    Place& p = m.places_[i];
    p.key = r.u32(); p.x = std::int32_t(r.u32()); p.y = std::int32_t(r.u32()); p.certainty = r.u8();
    const std::uint8_t pr = r.u8(); p.day = r.u16();
    if (pr > 3 || p.day > m.last_day_) return fail();
    p.protected_ = (pr & 1) != 0; p.seen = (pr & 2) != 0;
    for (unsigned j = 0; j < i; ++j) if (m.places_[j].key == p.key) return fail();
  }
  for (unsigned i = 0; i < no; ++i) {
    Obstacle& o = m.obstacles_[i];
    o.from = r.u16(); const std::uint16_t to = r.u16(); o.day = r.u16();
    o.told = (to & 0x8000) != 0; o.to = std::uint16_t(to & 0x7FFF);
    if (o.from >= kTileCount || o.to >= kTileCount || o.from == o.to) return fail();
  }
  m.place_count_ = std::uint8_t(np); m.obstacle_count_ = std::uint8_t(no);
  *this = m;
  return true;
}

std::uint64_t MentalMap::fingerprint() const {
  std::vector<std::uint8_t> b;
  serialize(b);
  std::uint64_t h = 1469598103934665603ull;
  for (std::uint8_t c : b) { h ^= c; h *= 1099511628211ull; }
  return h;
}

}  // namespace em::act::navigation
