// RoadPlan: the roads of the world PLAN (nodes and straight segments), shared by every NPC. It is geometry only: the
// planner reads a segment only when the NPC's mental map says the NPC knows it. Created with the world (T47).
#pragma once
#include <cstdint>
#include <vector>

#include "emergence/act/navigation/navigation_types.h"

namespace em::act::navigation {

inline constexpr int kMaxSegments = 512;   // one bit per segment in the mental map

class RoadPlan {
 public:
  struct Segment { std::uint16_t a, b; };
  std::uint16_t add_node(const Position& p) { nodes_.push_back(p); return std::uint16_t(nodes_.size() - 1); }
  // Returns the segment index, or -1 when the plan is full / a node is unknown.
  int add_segment(std::uint16_t a, std::uint16_t b);
  std::size_t segment_count() const { return segs_.size(); }
  const Segment& segment(int i) const { return segs_[std::size_t(i)]; }
  const Position& node(std::uint16_t n) const { return nodes_[n]; }
  std::int64_t length_mm(int seg) const { return distance_mm(node(segs_[std::size_t(seg)].a), node(segs_[std::size_t(seg)].b)); }
  // Segments with an end in the tile (indices, in creation order). Empty for a tile without a node.
  const std::vector<std::uint16_t>& segments_at(std::int32_t tile) const;

 private:
  std::vector<Position> nodes_;
  std::vector<Segment> segs_;
  std::vector<std::vector<std::uint16_t>> by_tile_;   // sized lazily; indexed by tile
};

}  // namespace em::act::navigation
