// MentalMap (T23b, docs/14 section 4.8, P51): what ONE NPC knows or believes of the space. Nothing else: no truth.
// It is fed by what the NPC perceived (see_*) and what it was told (hear_*, with their uncertainty), and by the
// obstacles it met. Compact (about 1 KiB), serializable (the reserved place of the NPCS section, T04), bounded and
// deterministic forgetting. It is not part of NpcState.
//   - tiles walked : one bit per 256 m tile (6 084 bits)
//   - roads known  : one bit per segment of the RoadPlan (512 bits); a told segment enters here too (a belief)
//   - places       : up to 16 places (a key of the NPC's LOCUS, a believed position, a certainty 0..255)
//   - obstacles    : up to 8 crossings between two tiles met (or told) as impassable, forgotten after 30 days
#pragma once
#include <array>
#include <cstdint>
#include <span>
#include <vector>

#include "emergence/act/navigation/navigation_types.h"
#include "emergence/act/navigation/road_plan.h"

namespace em::act::navigation {

using PlaceKey = std::uint32_t;                       // opaque to the map: the caller maps it to its LOCUS record
inline constexpr int kMaxPlaces = 16;
inline constexpr int kMaxObstacles = 8;
inline constexpr int kMaxToldObstacles = 4;          // hearsay can never take more than half of the slots
inline constexpr std::uint16_t kObstacleLifeDays = 30;
inline constexpr std::uint8_t kSeenCertainty = 255;   // seen with one's own eyes
inline constexpr std::uint8_t kToldCertaintyMax = 200;// what was told never beats what was seen
inline constexpr std::uint8_t kCertaintyFloor = 8;    // a place fades to this, it is only evicted by a newer one

class MentalMap {
 public:
  struct Place {
    PlaceKey key = 0;
    std::int32_t x = 0, y = 0;       // believed position, mm
    std::uint8_t certainty = 0;      // at `day`
    bool protected_ = false;         // home, workplace: evicted last, never overwritten by hearsay once seen
    bool seen = false;               // seen with one's own eyes (hearsay cannot overwrite a protected seen place)
    std::uint16_t day = 0;           // last day seen or told
  };
  struct Obstacle { std::uint16_t from, to; std::uint16_t day; bool told; };
  enum class Edge : std::uint8_t { Open, Told, Seen };   // Told = hearsay: a bounded surcharge, never a closed way

  // ---- feeding: what was perceived
  bool see_position(const Position& p);                                   // marks the tile walked; true if new
  void see_place(PlaceKey key, const Position& p, std::uint16_t day);
  void see_segment(int segment);                                          // walked a road
  void see_obstacle(std::int32_t from_tile, std::int32_t to_tile, std::uint16_t day);
  void forget_place(PlaceKey key);                                        // arrived, it is not there
  // ---- feeding: what was told (T24); the certainty is the NPC's own trust in the teller, capped at 200
  void hear_place(PlaceKey key, const Position& p, std::uint8_t certainty, std::uint16_t day);
  void hear_segment(int segment);
  void hear_obstacle(std::int32_t from_tile, std::int32_t to_tile, std::uint16_t day);
  void protect_place(PlaceKey key, bool on = true);

  // ---- reading
  bool tile_walked(std::int32_t tile) const { return tile >= 0 && tile < kTileCount && (visited_[std::size_t(tile) >> 6] >> (tile & 63)) & 1u; }
  bool knows_segment(int seg) const { return seg >= 0 && seg < kMaxSegments && (roads_[std::size_t(seg) >> 6] >> (seg & 63)) & 1u; }
  int known_segment_count() const;
  bool edge_blocked(std::int32_t a, std::int32_t b, std::uint16_t day) const { return edge_state(a, b, day) == Edge::Seen; }   // seen: closed
  Edge edge_state(std::int32_t a, std::int32_t b, std::uint16_t day) const;      // either order
  void disprove_obstacle(std::int32_t a, std::int32_t b);   // seen open in view: a told obstacle goes (a seen one is kept)
  const Place* place(PlaceKey key) const;
  // The certainty now (fades with the days since it was seen or told).
  std::uint8_t place_certainty(const Place& p, std::uint16_t day) const;
  int place_count() const { return place_count_; }
  const Place& place_at(int i) const { return places_[std::size_t(i)]; }
  int obstacle_count() const { return obstacle_count_; }
  int walked_tiles() const;

  // ---- save (the opaque bytes of NpcBundle::mental_map). load() is fail closed: false leaves *this empty.
  std::size_t serialized_size() const;
  void serialize(std::vector<std::uint8_t>& out) const;
  bool deserialize(std::span<const std::uint8_t> bytes);
  std::uint64_t fingerprint() const;                                      // FNV-1a 64 of the canonical bytes
  bool operator==(const MentalMap& o) const { return fingerprint() == o.fingerprint(); }

 private:
  void learn_place(PlaceKey key, const Position& p, std::uint8_t certainty, std::uint16_t day, bool seen);
  void add_obstacle(std::int32_t from_tile, std::int32_t to_tile, std::uint16_t day, bool told);

  std::array<std::uint64_t, (kTileCount + 63) / 64> visited_{};
  std::array<std::uint64_t, kMaxSegments / 64> roads_{};
  std::array<Place, kMaxPlaces> places_{};
  std::array<Obstacle, kMaxObstacles> obstacles_{};
  std::uint16_t last_day_ = 0;
  std::uint8_t place_count_ = 0, obstacle_count_ = 0;
};

}  // namespace em::act::navigation
