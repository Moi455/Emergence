// Settlement sites and roads (architecture § 2.3): a market town near the
// centre, one village near each frontier, then roads found by A* over the
// plan with slope and river-crossing costs. All choices are argmax / argmin
// with ties broken by cell index.
#include <algorithm>
#include <deque>
#include <queue>

#include "emergence/base/fixed.h"
#include "plan_internal.h"

namespace em::plan {

int32_t slope_permille(const WorldPlan& p, int32_t i, int32_t j) {
  auto H = [&](int32_t a, int32_t b) {
    a = std::clamp(a, 0, p.n - 1);
    b = std::clamp(b, 0, p.n - 1);
    return int64_t{p.height_mm[p.idx(a, b)]};
  };
  int64_t dx = (H(i + 1, j) - H(i - 1, j)) * 1000 / (2 * p.cell_mm);
  int64_t dz = (H(i, j + 1) - H(i, j - 1)) * 1000 / (2 * p.cell_mm);
  return static_cast<int32_t>(isqrt64(static_cast<uint64_t>(dx * dx + dz * dz)));
}

namespace {

constexpr int64_t M = 1000;

// Distance in cells to the nearest cell matching mask (4-neighbour BFS), capped.
std::vector<uint16_t> distance_to(const WorldPlan& p, uint8_t mask, uint16_t cap) {
  std::vector<uint16_t> dist(p.flags.size(), cap);
  std::deque<uint32_t> q;
  for (size_t c = 0; c < p.flags.size(); ++c)
    if (p.flags[c] & mask) {
      dist[c] = 0;
      q.push_back(static_cast<uint32_t>(c));
    }
  while (!q.empty()) {
    uint32_t c = q.front();
    q.pop_front();
    if (dist[c] + 1 >= cap) continue;
    int32_t ci = static_cast<int32_t>(c % static_cast<uint32_t>(p.n)), cj = static_cast<int32_t>(c / static_cast<uint32_t>(p.n));
    for (int d = 0; d < 8; d += 2) {
      int32_t ni = ci + kDirDi[static_cast<size_t>(d)], nj = cj + kDirDj[static_cast<size_t>(d)];
      if (!p.in_map(ni, nj)) continue;
      size_t nb = p.idx(ni, nj);
      if (dist[nb] > dist[c] + 1) {
        dist[nb] = static_cast<uint16_t>(dist[c] + 1);
        q.push_back(static_cast<uint32_t>(nb));
      }
    }
  }
  return dist;
}

Side side_of(const WorldParams& wp, FrontierKind k) {
  for (int s = 0; s < 4; ++s)
    if (wp.frontier[static_cast<size_t>(s)] == k) return static_cast<Side>(s);
  return Side::None;
}

// Coordinate along a side's edge, and the depth of a cell into that side.
int64_t along_mm(const WorldPlan& p, Side s, int32_t i, int32_t j) {
  return (s == Side::West || s == Side::East ? j : i) * p.cell_mm;
}

}  // namespace

void place_settlements(WorldPlan& p) {
  const int32_t n = p.n;
  const WorldParams& wp = p.params;
  const int64_t sc = wp.scale_q16();
  auto L = [&](int64_t mm) { return (mm * sc) >> 16; };
  const int64_t size_mm = int64_t{wp.size_m} * M;
  const uint16_t cap = 64;
  auto d_water = distance_to(p, kFlagRiver | kFlagLake, cap);
  auto d_sea = distance_to(p, kFlagSea, cap);

  // Depth of a cell into a given side's march, recomputed from the stored
  // per-cell values only when the cell belongs to that side; otherwise use the
  // relief's frontier sampling through march_depth (core cells store the
  // nearest side). For placement we need the depth into a specific side.
  Relief relief(wp);

  struct Want {
    SettlementKind kind;
    FrontierKind frontier;
    int64_t depth_lo, depth_hi;
  };
  const Want wants[5] = {
      {SettlementKind::Town, FrontierKind::Sea, 0, 0},
      {SettlementKind::Port, FrontierKind::Sea, L(-1200 * M), L(200 * M)},
      {SettlementKind::Miners, FrontierKind::Mountain, L(-2600 * M), L(-600 * M)},
      {SettlementKind::Oasis, FrontierKind::Desert, L(-1400 * M), L(-150 * M)},
      {SettlementKind::Foresters, FrontierKind::Forest, L(-1500 * M), L(-250 * M)},
  };

  // Local roughness: sum of slopes over a 5 x 5 window.
  std::vector<int32_t> slope(p.height_mm.size()), rough(p.height_mm.size(), 0);
  for (int32_t j = 0; j < n; ++j)
    for (int32_t i = 0; i < n; ++i) slope[p.idx(i, j)] = slope_permille(p, i, j);
  for (int32_t j = 2; j < n - 2; ++j)
    for (int32_t i = 2; i < n - 2; ++i) {
      int32_t sum = 0;
      for (int32_t b = -2; b <= 2; ++b)
        for (int32_t a = -2; a <= 2; ++a) sum += slope[p.idx(i + a, j + b)];
      rough[p.idx(i, j)] = sum;
    }
  const int64_t max_wander = L(800 * M);

  p.settlements.clear();
  for (const Want& w : wants) {
    Side side = side_of(wp, w.frontier);
    int64_t best_score = INT64_MIN;
    size_t best = SIZE_MAX;
    for (int32_t j = 2; j < n - 2; ++j) {
      for (int32_t i = 2; i < n - 2; ++i) {
        size_t c = p.idx(i, j);
        if (p.flags[c] & (kFlagSea | kFlagLake | kFlagRiver)) continue;
        int64_t x = int64_t{i} * p.cell_mm, z = int64_t{j} * p.cell_mm;
        int64_t h = p.height_mm[c];
        int64_t score = 0;
        if (w.kind == SettlementKind::Town) {
          int64_t dx = x - size_mm / 2, dz = z - size_mm / 2;
          int64_t r = static_cast<int64_t>(isqrt64(static_cast<uint64_t>(dx * dx + dz * dz)));
          if (r > L(2500 * M)) continue;
          score -= r / std::max<int64_t>(L(10 * M), 1);  // centrality
        } else {
          if (side == Side::None) continue;
          int64_t along = along_mm(p, side, i, j);
          if (along < size_mm * 3 / 10 || along > size_mm * 7 / 10) continue;
          int64_t edge_dist = side == Side::West ? x : side == Side::East ? size_mm - x
                              : side == Side::North ? size_mm - z : z;
          int64_t width = int64_t{wp.march_width_m[static_cast<size_t>(side)]} * M;
          if (width - edge_dist < w.depth_lo - max_wander || width - edge_dist > w.depth_hi + max_wander) continue;
          FrontierSample fs = relief.frontier(x, z);
          int64_t depth = fs.depth_mm[static_cast<size_t>(side)];
          if (depth < w.depth_lo || depth > w.depth_hi) continue;
          if (w.kind == SettlementKind::Port) {
            if (d_sea[c] > 6 || h < 2 * M || h > 30 * M) continue;
            score += 400 - 40 * d_sea[c];
          }
          if (w.kind == SettlementKind::Miners && (h < 250 * M || h > 1400 * M)) continue;
        }
        // Flat ground, close to fresh water, but not in it.
        score -= rough[c] / 25 * 4;
        int64_t water = d_water[c];
        if (water >= 2) score += std::max<int64_t>(0, 600 - 15 * water);
        if (w.kind == SettlementKind::Oasis) score += std::max<int64_t>(0, 1500 - 60 * water);
        if (score > best_score) {
          best_score = score;
          best = c;
        }
      }
    }
    if (best == SIZE_MAX) continue;  // no valid site: reported by tests, never silently moved
    Settlement s;
    s.kind = w.kind;
    s.i = static_cast<int32_t>(best % static_cast<size_t>(n));
    s.j = static_cast<int32_t>(best / static_cast<size_t>(n));
    s.height_mm = p.height_mm[best];
    p.settlements.push_back(s);
    int32_t r = static_cast<int32_t>(std::max<int64_t>(L(120 * M) / p.cell_mm, 2));
    for (int32_t b = -r; b <= r; ++b)
      for (int32_t a = -r; a <= r; ++a)
        if (a * a + b * b <= r * r && p.in_map(s.i + a, s.j + b)) p.flags[p.idx(s.i + a, s.j + b)] |= kFlagSettlement;
  }
}

namespace {

struct Node {
  int64_t f;
  uint32_t idx;
  bool operator>(const Node& o) const { return f != o.f ? f > o.f : idx > o.idx; }
};

bool find_road(WorldPlan& p, size_t from, size_t to, std::vector<uint32_t>& path) {
  const int32_t n = p.n;
  const size_t N = p.height_mm.size();
  std::vector<int64_t> g(N, INT64_MAX);
  std::vector<uint8_t> came(N, kNoReceiver), closed(N, 0);
  std::priority_queue<Node, std::vector<Node>, std::greater<Node>> open;
  const int32_t ti = static_cast<int32_t>(to % static_cast<size_t>(n)), tj = static_cast<int32_t>(to / static_cast<size_t>(n));
  auto heuristic = [&](int32_t i, int32_t j) {
    int64_t dx = abs64(i - ti), dz = abs64(j - tj);
    int64_t octile = 1000 * max64(dx, dz) + 414 * min64(dx, dz);
    return octile * 4 / 10;  // existing roads cost 0.4: stays admissible
  };
  g[from] = 0;
  open.push({heuristic(static_cast<int32_t>(from % static_cast<size_t>(n)), static_cast<int32_t>(from / static_cast<size_t>(n))),
             static_cast<uint32_t>(from)});
  while (!open.empty()) {
    uint32_t c = open.top().idx;
    open.pop();
    if (closed[c]) continue;
    closed[c] = 1;
    if (c == to) break;
    int32_t ci = static_cast<int32_t>(c % static_cast<uint32_t>(n)), cj = static_cast<int32_t>(c / static_cast<uint32_t>(n));
    for (int d = 0; d < 8; ++d) {
      int32_t ni = ci + kDirDi[static_cast<size_t>(d)], nj = cj + kDirDj[static_cast<size_t>(d)];
      if (!p.in_map(ni, nj)) continue;
      size_t nb = p.idx(ni, nj);
      if (closed[nb] || (p.flags[nb] & (kFlagSea | kFlagLake))) continue;
      int64_t base = (d & 1) ? 1414 : 1000;
      int64_t dist_mm = (d & 1) ? p.cell_mm * 1414 / 1000 : p.cell_mm;
      int64_t grade = abs64(int64_t{p.height_mm[nb]} - p.height_mm[c]) * 1000 / dist_mm;  // per mille
      int64_t cost = base * (1000 + grade * 4 + grade * grade / 40) / 1000;
      if (grade > 450) cost *= 20;
      if (p.flags[nb] & kFlagRiver) cost += 12000;  // a bridge or a ford
      if (p.flags[nb] & kFlagRoad) cost = cost * 4 / 10;
      int64_t ng = g[c] + cost;
      if (ng < g[nb]) {
        g[nb] = ng;
        came[nb] = static_cast<uint8_t>(d);
        open.push({ng + heuristic(ni, nj), static_cast<uint32_t>(nb)});
      }
    }
  }
  if (!closed[to]) return false;
  path.clear();
  for (size_t c = to; c != from;) {
    path.push_back(static_cast<uint32_t>(c));
    uint8_t d = came[c];
    int32_t i = static_cast<int32_t>(c % static_cast<size_t>(n)) - kDirDi[d];
    int32_t j = static_cast<int32_t>(c / static_cast<size_t>(n)) - kDirDj[d];
    c = p.idx(i, j);
  }
  path.push_back(static_cast<uint32_t>(from));
  std::reverse(path.begin(), path.end());
  return true;
}

}  // namespace

void build_roads(WorldPlan& p) {
  p.roads.clear();
  auto find = [&](SettlementKind k) {
    for (size_t s = 0; s < p.settlements.size(); ++s)
      if (p.settlements[s].kind == k) return static_cast<int32_t>(s);
    return -1;
  };
  const SettlementKind ring[4] = {SettlementKind::Port, SettlementKind::Miners, SettlementKind::Oasis,
                                  SettlementKind::Foresters};
  std::vector<std::pair<int32_t, int32_t>> links;
  int32_t town = find(SettlementKind::Town);
  for (SettlementKind k : ring) links.push_back({town, find(k)});
  for (int r = 0; r < 4; ++r) links.push_back({find(ring[r]), find(ring[(r + 1) % 4])});
  for (auto [a, b] : links) {
    if (a < 0 || b < 0) continue;
    const Settlement& sa = p.settlements[static_cast<size_t>(a)];
    const Settlement& sb = p.settlements[static_cast<size_t>(b)];
    Road road;
    road.from = a;
    road.to = b;
    if (!find_road(p, p.idx(sa.i, sa.j), p.idx(sb.i, sb.j), road.cells)) continue;
    for (size_t k = 0; k < road.cells.size(); ++k) {
      p.flags[road.cells[k]] |= kFlagRoad;
      if (k > 0) {
        uint32_t c0 = road.cells[k - 1], c1 = road.cells[k];
        bool diag = (c0 % static_cast<uint32_t>(p.n)) != (c1 % static_cast<uint32_t>(p.n)) &&
                    (c0 / static_cast<uint32_t>(p.n)) != (c1 / static_cast<uint32_t>(p.n));
        road.length_m += (diag ? p.cell_mm * 1414 / 1000 : p.cell_mm) / 1000;
      }
    }
    p.roads.push_back(std::move(road));
  }
}

}  // namespace em::plan
