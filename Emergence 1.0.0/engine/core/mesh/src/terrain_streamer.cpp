#include "emergence/mesh/terrain_streamer.h"

#include <algorithm>

#include "emergence/base/fixed.h"
#include "emergence/base/parallel.h"
#include "emergence/base/timer.h"

namespace em {

namespace {
constexpr int R = TerrainStreamer::kRegionChunks;
const int kNb[6][3] = {{1, 0, 0}, {-1, 0, 0}, {0, 1, 0}, {0, -1, 0}, {0, 0, 1}, {0, 0, -1}};
}  // namespace

TerrainStreamer::TerrainStreamer(ChunkCache& cache, StreamerParams params)
    : cache_(cache), p_(params), box_(static_cast<size_t>(params.lods)), hole_(static_cast<size_t>(params.lods)) {}

bool TerrainStreamer::drawn(int lod, int64_t x, int64_t z) const {
  if (!box_[static_cast<size_t>(lod)].contains(x, z)) return false;
  if (hole_[static_cast<size_t>(lod)].contains(x, z)) return false;
  const int64_t size = int64_t{kChunkSize} << lod;
  const int64_t map = cache_.source().map_voxels();
  return x >= 0 && z >= 0 && x * size < map && z * size < map;
}

std::vector<TerrainStreamer::Rect> TerrainStreamer::signature(int lod, int32_t rx, int32_t rz) const {
  Rect area{int64_t{rx} * R - 1, int64_t{rz} * R - 1, int64_t{rx} * R + R, int64_t{rz} * R + R};
  Rect b = box_[static_cast<size_t>(lod)].clip(area), h = hole_[static_cast<size_t>(lod)].clip(area);
  if (b.empty()) b = Rect{};
  if (h.empty()) h = Rect{};
  return {b, h};
}

void TerrainStreamer::set_view(int64_t vx, int64_t vz) {
  view_x_ = vx;
  view_z_ = vz;
  const int64_t k = p_.half;
  for (int L = 0; L < p_.lods; ++L) {
    const int64_t size = int64_t{kChunkSize} << L;
    int64_t cx = floor_div(vx, size), cz = floor_div(vz, size);
    Rect b;
    if (L + 1 < p_.lods) {
      int64_t px = floor_div(vx, size * 2), pz = floor_div(vz, size * 2);
      b = {2 * (px - k), 2 * (pz - k), 2 * (px + k) + 1, 2 * (pz + k) + 1};
    } else {
      b = {cx - 2 * k, cz - 2 * k, cx + 2 * k + 1, cz + 2 * k + 1};
    }
    box_[static_cast<size_t>(L)] = b;
    hole_[static_cast<size_t>(L)] = L == 0 ? Rect{} : Rect{cx - k, cz - k, cx + k, cz + k};
  }
  // Which region columns need (re)building, and which disappear.
  std::set<ColumnKey> wanted;
  for (int L = 0; L < p_.lods; ++L) {
    const Rect& b = box_[static_cast<size_t>(L)];
    for (int64_t rz = floor_div(b.z0, R); rz <= floor_div(b.z1, R); ++rz)
      for (int64_t rx = floor_div(b.x0, R); rx <= floor_div(b.x1, R); ++rx)
        wanted.insert({L, static_cast<int32_t>(rx), static_cast<int32_t>(rz)});
  }
  queue_.clear();
  for (const auto& col : wanted) {
    auto it = built_.find(col);
    if (it == built_.end() || it->second.sig != signature(std::get<0>(col), std::get<1>(col), std::get<2>(col)) ||
        forced_.count(col))
      queue_.push_back(col);
  }
  for (const auto& [col, b] : built_)
    if (!wanted.count(col)) queue_.push_back(col);  // built() sends the removals
  // Finest level first, then nearest; next job at the back.
  auto dist = [&](const ColumnKey& c) {
    const int64_t size = (int64_t{kChunkSize} << std::get<0>(c)) * R;
    int64_t dx = std::get<1>(c) * size + size / 2 - view_x_, dz = std::get<2>(c) * size + size / 2 - view_z_;
    return std::max(std::llabs(dx), std::llabs(dz)) / size;
  };
  std::sort(queue_.begin(), queue_.end(), [&](const ColumnKey& a, const ColumnKey& b) {
    auto ka = std::make_tuple(std::get<0>(a), dist(a), a), kb = std::make_tuple(std::get<0>(b), dist(b), b);
    return ka > kb;
  });
  // Forget chunks far outside every square of their level.
  for (int L = 0; L < p_.lods; ++L) {
    const Rect& b = box_[static_cast<size_t>(L)];
    cache_.evict_outside(L, b.x0 - 3, b.z0 - 3, b.x1 + 3, b.z1 + 3);
  }
  for (auto it = meshed_.begin(); it != meshed_.end();) {
    const LodChunk& k = it->first;
    it = box_[static_cast<size_t>(k.lod)].contains(k.x, k.z) ? std::next(it) : meshed_.erase(it);
  }
}

void TerrainStreamer::mark_edited(const std::vector<LodChunk>& chunks) {
  for (const LodChunk& c : chunks)
    for (int d = -1; d < 6; ++d) {
      LodChunk n = c;
      if (d >= 0) {
        n.x += kNb[d][0];
        n.y += kNb[d][1];
        n.z += kNb[d][2];
      }
      meshed_.erase(n);
    }
  for (const LodChunk& c : chunks)
    for (int dz = -1; dz <= 1; ++dz)
      for (int dx = -1; dx <= 1; ++dx) {
        ColumnKey col{0, static_cast<int32_t>(floor_div(c.x + dx, R)), static_cast<int32_t>(floor_div(c.z + dz, R))};
        if (forced_.insert(col).second && std::find(queue_.begin(), queue_.end(), col) == queue_.end())
          queue_.push_back(col);  // edits jump the queue
      }
}

bool TerrainStreamer::update(double budget_ms, std::vector<RegionUpdate>& out) {
  Timer t;
  while (!queue_.empty()) {
    // A batch of columns of one level keeps every core busy.
    std::vector<ColumnKey> batch;
    const int lod = std::get<0>(queue_.back());
    while (!queue_.empty() && batch.size() < 6 && std::get<0>(queue_.back()) == lod) {
      batch.push_back(queue_.back());
      queue_.pop_back();
    }
    build(batch, out);
    if (t.ms() >= budget_ms) break;
  }
  totals_.ms += t.ms();
  return queue_.empty();
}

void TerrainStreamer::plan(const ColumnKey& col, std::vector<Job>& jobs, std::vector<LodChunk>& needed) const {
  const auto [L, rx, rz] = col;
  Rect area{int64_t{rx} * R, int64_t{rz} * R, int64_t{rx} * R + R - 1, int64_t{rz} * R + R - 1};
  const Rect in = box_[static_cast<size_t>(L)].clip(area);
  if (in.empty()) return;
  const ChunkSource& src = cache_.source();
  const int64_t size = int64_t{kChunkSize} << L;
  auto kind = [&](int64_t x, int64_t y, int64_t z) {
    VoxelId v = kAir;
    return src.classify(L, {static_cast<int32_t>(x), static_cast<int32_t>(y), static_cast<int32_t>(z)}, &v);
  };
  for (int64_t z = in.z0; z <= in.z1; ++z)
    for (int64_t x = in.x0; x <= in.x1; ++x) {
      if (!drawn(L, x, z)) continue;
      int64_t gmin = INT64_MAX, gmax = INT64_MIN;
      for (int sz = 0; sz <= 2; ++sz)
        for (int sx = 0; sx <= 2; ++sx) {
          int64_t gx = std::min(x * size + sx * (size - 1) / 2, src.map_voxels() - 1);
          int64_t gz = std::min(z * size + sz * (size - 1) / 2, src.map_voxels() - 1);
          int64_t g = src.ground_voxel_y(gx, gz);
          gmin = std::min(gmin, g);
          gmax = std::max(gmax, g);
        }
      // Down to 2 m under the lowest ground: caves deeper than that are not
      // visible from the surface and stay unmeshed until the viewer goes in.
      int64_t y0 = floor_div(gmin - p_.below_ground_vox, size), y1 = floor_div(gmax + p_.above_ground_vox, size);
      for (int64_t y = y0; y <= y1; ++y) {
        SourceKind k = kind(x, y, z);
        if (k == SourceKind::Air) continue;
        uint8_t open = 0;
        bool exposed = k == SourceKind::Mixed;
        size_t first_needed = needed.size();
        for (int d = 0; d < 6; ++d) {
          int64_t nx = x + kNb[d][0], ny = y + kNb[d][1], nz = z + kNb[d][2];
          SourceKind nk = kind(nx, ny, nz);
          bool lateral = kNb[d][1] == 0;
          if (nk != SourceKind::Solid) exposed = true;
          if (nk == SourceKind::Mixed) {
            if (lateral && !drawn(L, nx, nz)) open |= static_cast<uint8_t>(1 << d);
            else needed.push_back({L, static_cast<int32_t>(nx), static_cast<int32_t>(ny), static_cast<int32_t>(nz)});
          }
        }
        if (!exposed) {
          needed.resize(first_needed);
          continue;
        }
        LodChunk key{L, static_cast<int32_t>(x), static_cast<int32_t>(y), static_cast<int32_t>(z)};
        jobs.push_back({key, open, nullptr});
        needed.push_back(key);
      }
    }
}

void TerrainStreamer::build(const std::vector<ColumnKey>& cols, std::vector<RegionUpdate>& out) {
  // 1. Plan every column of the batch.
  std::vector<std::vector<Job>> jobs(cols.size());
  std::vector<LodChunk> needed;
  Timer tp;
  for (size_t c = 0; c < cols.size(); ++c) {
    forced_.erase(cols[c]);
    plan(cols[c], jobs[c], needed);
  }
  totals_.plan_ms += tp.ms();
  Timer tg;
  // 2. Generate what is missing, then mesh, both in parallel. Chunks whose
  // quads are cached with the same open sides are not meshed again.
  size_t before = cache_.size();
  std::vector<LodChunk> missing;
  for (const LodChunk& k : needed)
    if (!cache_.find(k.lod, k.x, k.y, k.z)) missing.push_back(k);
  cache_.prefetch(missing);
  totals_.chunks_generated += cache_.size() - before;
  totals_.generate_ms += tg.ms();
  Timer tm;
  std::vector<Job*> todo;
  for (auto& js : jobs)
    for (Job& j : js) {
      auto it = meshed_.find(j.key);
      if (it != meshed_.end() && it->second.open == j.open) j.quads = &it->second.quads;
      else todo.push_back(&j);
    }
  std::vector<Meshed> fresh(todo.size());
  parallel_each(0, static_cast<int64_t>(todo.size()), [&](int64_t i) {
    const Job& j = *todo[static_cast<size_t>(i)];
    Meshed& m = fresh[static_cast<size_t>(i)];
    m.open = j.open;
    cache_.mesh(j.key.lod, j.key.x, j.key.y, j.key.z, m.quads, j.open, j.key.lod <= p_.ao_max_lod);
  });
  totals_.chunks_meshed += todo.size();
  totals_.mesh_ms += tm.ms();
  for (size_t i = 0; i < todo.size(); ++i) {
    Meshed& slot = meshed_[todo[i]->key];
    slot = std::move(fresh[i]);
    todo[i]->quads = &slot.quads;
  }

  // 3. Per column: group by region row and tag each quad with its chunk slot.
  for (size_t c = 0; c < cols.size(); ++c) {
    const auto [L, rx, rz] = cols[c];
    std::map<int32_t, std::vector<Quad>> rows;
    for (const Job& j : jobs[c]) {
      if (j.quads->empty()) continue;
      const LodChunk& k = j.key;
      int slot = static_cast<int>((k.x - int64_t{rx} * R) + R * (k.z - int64_t{rz} * R) + R * R * (k.y - floor_div(k.y, R) * R));
      auto& dst = rows[static_cast<int32_t>(floor_div(k.y, R))];
      for (Quad q : *j.quads) {
        q.set_region_slot(slot);
        dst.push_back(q);
      }
    }
    Built& prev = built_[cols[c]];
    std::set<int32_t> ys;
    for (auto& [ry, qs] : rows) {
      ys.insert(ry);
      totals_.quads += qs.size();
      out.push_back({{L, rx, ry, rz}, false, std::move(qs)});
    }
    for (int32_t ry : prev.ys)
      if (!ys.count(ry)) out.push_back({{L, rx, ry, rz}, true, {}});
    totals_.regions += rows.size();
    Rect area{int64_t{rx} * R, int64_t{rz} * R, int64_t{rx} * R + R - 1, int64_t{rz} * R + R - 1};
    if (box_[static_cast<size_t>(L)].clip(area).empty()) {
      built_.erase(cols[c]);
      continue;
    }
    prev.ys = std::move(ys);
    prev.sig = signature(L, rx, rz);
  }
}

}  // namespace em
