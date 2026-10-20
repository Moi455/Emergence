// A* on the mental map only. This file includes no header of the world (ctest navigation_planner_no_world).
#include "emergence/act/navigation/route_planner.h"

#include <algorithm>
#include <vector>

namespace em::act::navigation {

namespace {

constexpr std::int64_t kOrtho = kTileMm, kDiag = 362'039;   // 256 m * sqrt(2), rounded
constexpr int kCostRoad = 1, kCostWalked = 2, kCostUnknown = 6;
constexpr std::int64_t kToldPenalty = 8 * kTileMm;   // hearsay obstacle: a bounded surcharge (about 2 km of walking), never a closed way
constexpr int kCostWeighted = 4;   // weighted A* (heuristic x4) when no road is known: within 2x of the best cost, far fewer expansions

struct Item { std::int64_t f; std::uint16_t tile; };
struct Later { bool operator()(const Item& a, const Item& b) const { return a.f != b.f ? a.f > b.f : a.tile > b.tile; } };

struct Scratch {
  std::array<std::uint32_t, kTileCount> seen{}, closed{};
  std::array<std::int64_t, kTileCount> g{};
  std::array<std::uint16_t, kTileCount> parent{};
  std::array<std::int16_t, kTileCount> via{};
  std::vector<Item> heap;
  std::uint32_t stamp = 0;
};

// Lower bound of the remaining cost: tiles of Chebyshev distance, minus one for the road nodes that sit anywhere in a tile.
// `min_cost`: 1 (admissible) when the NPC knows a road; else 4, a weighted A* (cost within 2x of the best).
std::int64_t heuristic(std::int32_t a, std::int32_t b, int min_cost) {
  const int dx = std::abs(a % kTilesPerSide - b % kTilesPerSide), dy = std::abs(a / kTilesPerSide - b / kTilesPerSide);
  return std::int64_t(std::max(0, std::max(dx, dy) - 1)) * kTileMm * min_cost;
}

}  // namespace

Plan RoutePlanner::plan(const MentalMap& map, std::uint16_t day, const Position& from, const Position& believed_target) const {
  Plan out;
  const int min_cost = (roads_ && map.known_segment_count() > 0) ? kCostRoad : kCostWeighted;
  const std::int32_t start = clamped_tile_of(from), goal = clamped_tile_of(believed_target);
  if (start == goal) { out.status = PlanStatus::Found; return out; }

  thread_local Scratch sc;
  if (++sc.stamp == 0) { sc.seen.fill(0); sc.closed.fill(0); sc.stamp = 1; }
  const std::uint32_t cur = sc.stamp;
  sc.heap.clear();

  auto relax = [&](std::int32_t from_t, std::int32_t to_t, std::int64_t cost, int segment) {
    const auto edge = map.edge_state(from_t, to_t, day);
    if (edge == MentalMap::Edge::Seen) return;
    if (edge == MentalMap::Edge::Told) cost += kToldPenalty;
    const std::int64_t ng = sc.g[std::size_t(from_t)] + cost;
    if (sc.seen[std::size_t(to_t)] == cur && sc.g[std::size_t(to_t)] <= ng) return;
    sc.seen[std::size_t(to_t)] = cur;
    sc.g[std::size_t(to_t)] = ng;
    sc.parent[std::size_t(to_t)] = std::uint16_t(from_t);
    sc.via[std::size_t(to_t)] = std::int16_t(segment);
    sc.heap.push_back({ng + heuristic(to_t, goal, min_cost), std::uint16_t(to_t)});
    std::push_heap(sc.heap.begin(), sc.heap.end(), Later{});
  };

  sc.seen[std::size_t(start)] = cur;
  sc.g[std::size_t(start)] = 0;
  sc.heap.push_back({heuristic(start, goal, min_cost), std::uint16_t(start)});

  while (!sc.heap.empty()) {
    std::pop_heap(sc.heap.begin(), sc.heap.end(), Later{});
    const Item it = sc.heap.back();
    sc.heap.pop_back();
    const std::int32_t t = it.tile;
    if (sc.closed[std::size_t(t)] == cur) continue;
    sc.closed[std::size_t(t)] = cur;
    if (t == goal) break;
    if (++out.expansions > limits_.max_expansions) { out.status = PlanStatus::OverBudget; return out; }

    const int tx = t % kTilesPerSide, ty = t / kTilesPerSide;
    for (int dy = -1; dy <= 1; ++dy)
      for (int dx = -1; dx <= 1; ++dx) {
        if (!dx && !dy) continue;
        const int nx = tx + dx, ny = ty + dy;
        if (nx < 0 || ny < 0 || nx >= kTilesPerSide || ny >= kTilesPerSide) continue;
        const std::int32_t n = ny * kTilesPerSide + nx;
        if (sc.closed[std::size_t(n)] == cur) continue;
        relax(t, n, (dx && dy ? kDiag : kOrtho) * (map.tile_walked(n) ? kCostWalked : kCostUnknown), -1);
      }
    if (roads_)
      for (std::uint16_t seg : roads_->segments_at(t)) {
        if (!map.knows_segment(seg)) continue;   // a road the NPC does not know does not exist for it
        const auto& s = roads_->segment(seg);
        const std::int32_t ta = clamped_tile_of(roads_->node(s.a)), tb = clamped_tile_of(roads_->node(s.b));
        const std::int32_t n = ta == t ? tb : ta;
        if (n == t || sc.closed[std::size_t(n)] == cur) continue;
        relax(t, n, roads_->length_mm(seg) * kCostRoad, seg);
      }
  }

  if (sc.closed[std::size_t(goal)] != cur) { out.status = PlanStatus::Unreachable; return out; }
  std::array<RouteStep, kMaxRouteSteps> rev{};
  int n = 0;
  for (std::int32_t t = goal; t != start; t = sc.parent[std::size_t(t)]) {
    if (n == kMaxRouteSteps) { out.status = PlanStatus::OverBudget; return out; }
    rev[std::size_t(n++)] = {std::uint16_t(t), sc.via[std::size_t(t)], sc.via[std::size_t(t)] < 0 && !map.tile_walked(t)};
  }
  for (int i = 0; i < n; ++i) out.steps[std::size_t(i)] = rev[std::size_t(n - 1 - i)];
  out.count = std::uint16_t(n);
  out.cost = sc.g[std::size_t(goal)];
  out.status = PlanStatus::Found;
  return out;
}

}  // namespace em::act::navigation
