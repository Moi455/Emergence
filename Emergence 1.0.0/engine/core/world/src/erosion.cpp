// Hydraulic erosion and hydrology on the plan grid, integer only.
//  - Priority-Flood + epsilon (Barnes et al. 2014) gives every cell a strictly
//    downhill path to an outlet (map edge or sea), so rivers cross lakes.
//  - Drainage area accumulates from upstream to downstream.
//  - Stream-power incision with the implicit scheme of Braun & Willett 2013
//    (unconditionally stable), then a thermal pass that caps slopes.
// Ties are always broken by cell index, so the result never depends on the
// container implementation or on threads.
#include <algorithm>
#include <cstring>
#include <deque>
#include <queue>

#include "emergence/base/fixed.h"
#include "emergence/base/parallel.h"
#include "plan_internal.h"

namespace em::plan {

namespace {

struct Entry {
  int32_t h;
  uint32_t idx;
  bool operator>(const Entry& o) const { return h != o.h ? h > o.h : idx > o.idx; }
};
using MinHeap = std::priority_queue<Entry, std::vector<Entry>, std::greater<Entry>>;

// Fills depressions. With epsilon = 1 mm every non-outlet cell gets a strictly
// lower neighbour; with epsilon = 0 the result is the lake surface.
void priority_flood(const WorldPlan& p, const std::vector<int32_t>& h, std::vector<int32_t>& filled,
                    std::vector<uint8_t>& outlet, int32_t epsilon) {
  const int32_t n = p.n;
  const size_t N = h.size();
  filled = h;
  outlet.assign(N, 0);
  std::vector<uint8_t> closed(N, 0);
  MinHeap open;
  std::deque<uint32_t> pit;
  for (int32_t j = 0; j < n; ++j) {
    for (int32_t i = 0; i < n; ++i) {
      size_t c = p.idx(i, j);
      bool edge = i == 0 || j == 0 || i == n - 1 || j == n - 1;
      if (edge || h[c] < 0) {
        closed[c] = 1;
        outlet[c] = 1;
        open.push({h[c], static_cast<uint32_t>(c)});
      }
    }
  }
  while (!open.empty() || !pit.empty()) {
    uint32_t c;
    if (!pit.empty()) {
      c = pit.front();
      pit.pop_front();
    } else {
      c = open.top().idx;
      open.pop();
    }
    int32_t ci = static_cast<int32_t>(c % static_cast<uint32_t>(n));
    int32_t cj = static_cast<int32_t>(c / static_cast<uint32_t>(n));
    for (int d = 0; d < 8; ++d) {
      int32_t ni = ci + kDirDi[static_cast<size_t>(d)], nj = cj + kDirDj[static_cast<size_t>(d)];
      if (!p.in_map(ni, nj)) continue;
      size_t nb = p.idx(ni, nj);
      if (closed[nb]) continue;
      closed[nb] = 1;
      if (filled[nb] <= filled[c] + epsilon) {
        filled[nb] = filled[c] + epsilon;
        pit.push_back(static_cast<uint32_t>(nb));
      } else {
        open.push({filled[nb], static_cast<uint32_t>(nb)});
      }
    }
  }
}

// Steepest strictly-downhill neighbour on the filled surface.
void compute_receivers(const WorldPlan& p, const std::vector<int32_t>& filled, const std::vector<uint8_t>& outlet,
                       std::vector<uint8_t>& receiver) {
  const int32_t n = p.n;
  receiver.assign(filled.size(), kNoReceiver);
  parallel_for(0, n, [&](int64_t j0, int64_t j1) {
    for (int32_t j = static_cast<int32_t>(j0); j < j1; ++j) {
      for (int32_t i = 0; i < n; ++i) {
        size_t c = p.idx(i, j);
        if (outlet[c]) continue;
        int64_t best = 0;
        uint8_t best_d = kNoReceiver;
        for (int d = 0; d < 8; ++d) {
          int32_t ni = i + kDirDi[static_cast<size_t>(d)], nj = j + kDirDj[static_cast<size_t>(d)];
          if (!p.in_map(ni, nj)) continue;
          int64_t drop = int64_t{filled[c]} - filled[p.idx(ni, nj)];
          if (drop <= 0) continue;
          // Compare drop / distance; diagonal distance is sqrt(2) ~ 1414/1000.
          int64_t grade = (d & 1) ? drop * 1000 : drop * 1414;
          if (grade > best) {
            best = grade;
            best_d = static_cast<uint8_t>(d);
          }
        }
        receiver[c] = best_d;
      }
    }
  });
}

// Cells sorted by filled height ascending (downstream first), ties by index.
void sort_cells(const std::vector<int32_t>& filled, std::vector<uint32_t>& order) {
  const size_t N = filled.size();
  std::vector<uint64_t> keys(N);
  for (size_t c = 0; c < N; ++c)
    keys[c] = (static_cast<uint64_t>(static_cast<int64_t>(filled[c]) + (int64_t{1} << 31)) << 24) | c;
  std::sort(keys.begin(), keys.end());
  order.resize(N);
  for (size_t k = 0; k < N; ++k) order[k] = static_cast<uint32_t>(keys[k] & 0xFFFFFF);
}

size_t receiver_index(const WorldPlan& p, size_t c, uint8_t d) {
  int32_t i = static_cast<int32_t>(c % static_cast<size_t>(p.n)) + kDirDi[d];
  int32_t j = static_cast<int32_t>(c / static_cast<size_t>(p.n)) + kDirDj[d];
  return p.idx(i, j);
}

void accumulate(const WorldPlan& p, const std::vector<uint32_t>& order, const std::vector<uint8_t>& receiver,
                const std::vector<uint16_t>& rain_q8, std::vector<uint32_t>& flow_m2) {
  const uint64_t cell_area_m2 = static_cast<uint64_t>(p.params.cell_m) * static_cast<uint64_t>(p.params.cell_m);
  std::vector<uint64_t> acc(order.size());
  for (size_t c = 0; c < acc.size(); ++c) acc[c] = (cell_area_m2 * rain_q8[c]) >> 8;
  for (size_t k = order.size(); k-- > 0;) {
    uint32_t c = order[k];
    if (receiver[c] != kNoReceiver) acc[receiver_index(p, c, receiver[c])] += acc[c];
  }
  flow_m2.resize(acc.size());
  for (size_t c = 0; c < acc.size(); ++c) flow_m2[c] = static_cast<uint32_t>(std::min<uint64_t>(acc[c], UINT32_MAX));
}

}  // namespace

void erode(WorldPlan& p, const std::vector<uint16_t>& rain_q8, int iterations) {
  const int32_t n = p.n;
  const size_t N = p.height_mm.size();
  const int64_t cell_mm = p.cell_mm;
  // Incision coefficient K (Q16) in F = K * sqrt(A) / distance.
  const int64_t k_q16 = 600;  // ~0.009
  // Thermal erosion: slopes steeper than ~55 degrees collapse.
  const int64_t talus_mm = cell_mm * 14 / 10;
  // Below this catchment, slopes are shaped by hillslope processes, not
  // channels (avoids parallel grooves on smooth slopes).
  const int64_t sc = p.params.scale_q16();
  const uint32_t min_incision_m2 = static_cast<uint32_t>(((20000 * sc) >> 16) * sc >> 16);

  std::vector<int32_t> filled;
  std::vector<uint8_t> outlet, receiver;
  std::vector<uint32_t> order, flow;
  std::vector<int32_t> next(N);

  for (int it = 0; it < iterations; ++it) {
    priority_flood(p, p.height_mm, filled, outlet, 1);
    compute_receivers(p, filled, outlet, receiver);
    sort_cells(filled, order);
    accumulate(p, order, receiver, rain_q8, flow);

    // Implicit stream power, downstream first.
    auto& h = p.height_mm;
    for (size_t k = 0; k < N; ++k) {
      uint32_t c = order[k];
      uint8_t d = receiver[c];
      if (d == kNoReceiver) continue;
      size_t r = receiver_index(p, c, d);
      if (h[c] <= h[r] || flow[c] < min_incision_m2) continue;
      int64_t dist = (d & 1) ? cell_mm * 1414 / 1000 : cell_mm;
      int64_t f = (k_q16 * static_cast<int64_t>(isqrt64(flow[c])) * 1000) / dist;
      h[c] = static_cast<int32_t>((int64_t{h[c]} * kOne + f * h[r]) / (kOne + f));
    }

    // Thermal pass (Jacobi, 4 neighbours): conservative and order-independent.
    parallel_for(0, n, [&](int64_t j0, int64_t j1) {
      static constexpr int di[4] = {1, -1, 0, 0};
      static constexpr int dj[4] = {0, 0, 1, -1};
      for (int32_t j = static_cast<int32_t>(j0); j < j1; ++j) {
        for (int32_t i = 0; i < n; ++i) {
          size_t c = p.idx(i, j);
          int64_t delta = 0;
          for (int q = 0; q < 4; ++q) {
            int32_t ni = i + di[q], nj = j + dj[q];
            if (!p.in_map(ni, nj)) continue;
            int64_t diff = int64_t{h[c]} - h[p.idx(ni, nj)];
            if (diff > talus_mm) delta -= (diff - talus_mm) / 8;
            else if (diff < -talus_mm) delta += (-diff - talus_mm) / 8;
          }
          next[c] = static_cast<int32_t>(h[c] + delta);
        }
      }
    });
    std::memcpy(h.data(), next.data(), N * sizeof(int32_t));

    // Sediment settles in closed depressions: each pass fills 35% of their
    // depth, so only deep basins survive as lakes.
    for (size_t c = 0; c < N; ++c)
      if (!outlet[c] && filled[c] > h[c]) h[c] += static_cast<int32_t>((int64_t{filled[c]} - h[c]) * 35 / 100);
  }
}

void compute_hydrology(WorldPlan& p, const std::vector<uint16_t>& rain_q8) {
  const int32_t n = p.n;
  const size_t N = p.height_mm.size();
  const auto& h = p.height_mm;
  p.flags.assign(N, 0);
  p.water_mm.assign(N, WorldPlan::kNoWater);

  // Sea: below sea level and connected to the map edge.
  {
    std::deque<uint32_t> q;
    for (int32_t j = 0; j < n; ++j)
      for (int32_t i = 0; i < n; ++i) {
        size_t c = p.idx(i, j);
        bool edge = i == 0 || j == 0 || i == n - 1 || j == n - 1;
        if (edge && h[c] < 0) {
          p.flags[c] |= kFlagSea;
          q.push_back(static_cast<uint32_t>(c));
        }
      }
    while (!q.empty()) {
      uint32_t c = q.front();
      q.pop_front();
      int32_t ci = static_cast<int32_t>(c % static_cast<uint32_t>(n)), cj = static_cast<int32_t>(c / static_cast<uint32_t>(n));
      for (int d = 0; d < 8; d += 2) {
        int32_t ni = ci + kDirDi[static_cast<size_t>(d)], nj = cj + kDirDj[static_cast<size_t>(d)];
        if (!p.in_map(ni, nj)) continue;
        size_t nb = p.idx(ni, nj);
        if (h[nb] < 0 && !(p.flags[nb] & kFlagSea)) {
          p.flags[nb] |= kFlagSea;
          q.push_back(static_cast<uint32_t>(nb));
        }
      }
    }
    for (size_t c = 0; c < N; ++c)
      if (p.flags[c] & kFlagSea) p.water_mm[c] = 0;
  }

  // Lakes: depressions of the final terrain, kept when large enough.
  {
    std::vector<int32_t> lake;
    std::vector<uint8_t> outlet;
    priority_flood(p, h, lake, outlet, 0);
    std::vector<uint8_t> seen(N, 0);
    std::vector<uint32_t> comp;
    for (size_t s = 0; s < N; ++s) {
      if (seen[s] || p.flags[s] & kFlagSea || lake[s] - h[s] < 300) continue;
      comp.clear();
      comp.push_back(static_cast<uint32_t>(s));
      seen[s] = 1;
      for (size_t k = 0; k < comp.size(); ++k) {
        uint32_t c = comp[k];
        int32_t ci = static_cast<int32_t>(c % static_cast<uint32_t>(n)), cj = static_cast<int32_t>(c / static_cast<uint32_t>(n));
        for (int d = 0; d < 8; d += 2) {
          int32_t ni = ci + kDirDi[static_cast<size_t>(d)], nj = cj + kDirDj[static_cast<size_t>(d)];
          if (!p.in_map(ni, nj)) continue;
          size_t nb = p.idx(ni, nj);
          if (!seen[nb] && !(p.flags[nb] & kFlagSea) && lake[nb] - h[nb] >= 300) {
            seen[nb] = 1;
            comp.push_back(static_cast<uint32_t>(nb));
          }
        }
      }
      if (static_cast<int32_t>(comp.size()) < p.params.lake_min_cells) continue;
      // Dry climates keep their basins dry (playas): rain below ~0.35.
      uint64_t rain = 0;
      for (uint32_t c : comp) rain += rain_q8[c];
      if (rain < comp.size() * 90) continue;
      for (uint32_t c : comp) {
        p.flags[c] |= kFlagLake;
        p.water_mm[c] = lake[c];
      }
    }
  }

  // Final drainage: receivers and rain-weighted catchment, then rivers.
  std::vector<int32_t> filled;
  std::vector<uint8_t> outlet;
  std::vector<uint32_t> order;
  priority_flood(p, h, filled, outlet, 1);
  compute_receivers(p, filled, outlet, p.receiver);
  sort_cells(filled, order);
  accumulate(p, order, p.receiver, rain_q8, p.flow_m2);
  const uint32_t threshold = static_cast<uint32_t>(
      (int64_t{p.params.river_min_catchment_m2} * p.params.scale_q16() >> 16) * p.params.scale_q16() >> 16);
  for (size_t c = 0; c < N; ++c) {
    if (p.flags[c] & (kFlagSea | kFlagLake)) continue;
    if (p.flow_m2[c] >= threshold) {
      p.flags[c] |= kFlagRiver;
      p.water_mm[c] = h[c];
    }
  }
}

}  // namespace em::plan
