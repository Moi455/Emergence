// The mental map in the reserved place of the NPCS section (NpcBundle::mental_map, T04): opaque bytes for the codec,
// the map's own versioned format here. An empty field (a save older than T23b) loads an empty map.
#pragma once
#include <cstdint>
#include <vector>

#include "emergence/act/navigation/mental_map.h"

namespace em::act::navigation {

struct MentalMapCodec {
  // Replaces `bytes` with the map (no allocation growth beyond ~1.2 KiB).
  static void store(const MentalMap& map, std::vector<std::uint8_t>& bytes) { map.serialize(bytes); }
  // False (and `map` emptied) when the bytes are malformed; true and an empty map for no bytes at all.
  static bool load(const std::vector<std::uint8_t>& bytes, MentalMap& map) {
    if (bytes.empty()) { map = MentalMap{}; return true; }
    return map.deserialize(bytes);
  }
};

}  // namespace em::act::navigation
