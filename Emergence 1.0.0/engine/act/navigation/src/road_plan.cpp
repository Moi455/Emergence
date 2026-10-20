#include "emergence/act/navigation/road_plan.h"

namespace em::act::navigation {

int RoadPlan::add_segment(std::uint16_t a, std::uint16_t b) {
  if (a >= nodes_.size() || b >= nodes_.size() || a == b || segs_.size() >= std::size_t(kMaxSegments)) return -1;
  segs_.push_back({a, b});
  if (by_tile_.empty()) by_tile_.resize(std::size_t(kTileCount));
  const auto idx = std::uint16_t(segs_.size() - 1);
  const std::int32_t ta = clamped_tile_of(nodes_[a]), tb = clamped_tile_of(nodes_[b]);
  by_tile_[std::size_t(ta)].push_back(idx);
  if (tb != ta) by_tile_[std::size_t(tb)].push_back(idx);
  return int(idx);
}

const std::vector<std::uint16_t>& RoadPlan::segments_at(std::int32_t tile) const {
  static const std::vector<std::uint16_t> none;
  if (tile < 0 || std::size_t(tile) >= by_tile_.size()) return none;
  return by_tile_[std::size_t(tile)];
}

}  // namespace em::act::navigation
