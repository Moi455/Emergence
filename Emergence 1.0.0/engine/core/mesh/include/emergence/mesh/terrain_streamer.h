// Terrain around the viewer as nested rings of levels of detail (roadmap M3,
// architecture § 5): level L uses voxels of 2 cm << L in chunks of 1.28 m << L.
//
// Layout: level L covers a square of chunk columns aligned on level L+1
// chunks, [2 (c' - k), 2 (c' + k) + 1] where c' is the viewer's chunk at
// level L+1, minus the square drawn by level L-1, which is exactly
// [c - k, c + k] in level L chunks. The squares nest without overlap or gap.
// A chunk next to a column that its level does not draw is closed by a wall
// on that side (open_sides of ChunkCache::mesh): these skirts hide the cracks
// between rings, and sit below the finer ring's surface.
//
// Output: render regions of 8 x 8 x 8 chunks of one level, each a flat list
// of 8-byte quads tagged with their chunk slot (Quad::region_slot), ready for
// a vertex-pulling shader. Only regions whose content changed are re-sent.
#pragma once
#include <cstdint>
#include <map>
#include <set>
#include <tuple>
#include <vector>

#include "emergence/mesh/chunk_cache.h"

namespace em {

struct StreamerParams {
  int lods = 6;                 // levels 0..lods-1; 6 reaches ~700 m with k = 8
  int half = 8;                 // k: half-size of each level's hole, in chunks of that level
  // Corner occlusion up to this level (8 cm voxels by default): it doubles the
  // quads, and beyond ~100 m it is too small to see. -1 turns it off.
  int ao_max_lod = 2;
  int64_t above_ground_vox = 2000;  // trees and buildings up to 40 m above the ground
  int64_t below_ground_vox = 100;   // 2 m under the lowest ground of a column
};

struct RegionKey {
  int lod = 0;
  int32_t x = 0, y = 0, z = 0;  // in regions of 8 chunks of that level
  auto tie() const { return std::tie(lod, x, y, z); }
  bool operator<(const RegionKey& o) const { return tie() < o.tie(); }
};

struct RegionUpdate {
  RegionKey key;
  bool removed = false;
  std::vector<Quad> quads;
};

struct StreamerStats {
  size_t regions = 0, quads = 0, chunks_meshed = 0, chunks_generated = 0;
  double ms = 0, plan_ms = 0, generate_ms = 0, mesh_ms = 0;
};

class TerrainStreamer {
 public:
  static constexpr int kRegionChunks = 8;

  TerrainStreamer(ChunkCache& cache, StreamerParams params = {});

  // Viewer position in 2 cm voxels (x east, z north).
  void set_view(int64_t vx, int64_t vz);
  // Rebuilds changed regions, finest level and nearest first, until about
  // budget_ms has been spent (at least one region column per call).
  // Returns true when everything is up to date.
  bool update(double budget_ms, std::vector<RegionUpdate>& out);
  // Lod-0 chunks changed by an edit: their region columns are rebuilt.
  void mark_edited(const std::vector<LodChunk>& chunks);

  size_t pending() const { return queue_.size(); }
  const StreamerParams& params() const { return p_; }
  StreamerStats totals() const { return totals_; }

  struct Rect {
    int64_t x0 = 0, z0 = 0, x1 = -1, z1 = -1;  // inclusive, empty when x1 < x0
    bool empty() const { return x1 < x0 || z1 < z0; }
    bool contains(int64_t x, int64_t z) const { return x >= x0 && x <= x1 && z >= z0 && z <= z1; }
    Rect clip(const Rect& o) const { return {std::max(x0, o.x0), std::max(z0, o.z0), std::min(x1, o.x1), std::min(z1, o.z1)}; }
    auto tie() const { return std::tie(x0, z0, x1, z1); }
    bool operator==(const Rect& o) const { return tie() == o.tie(); }
  };
  Rect box(int lod) const { return box_[static_cast<size_t>(lod)]; }
  Rect hole(int lod) const { return hole_[static_cast<size_t>(lod)]; }
  bool drawn(int lod, int64_t x, int64_t z) const;

 private:
  using ColumnKey = std::tuple<int, int32_t, int32_t>;  // lod, region x, region z
  struct Built {
    std::vector<Rect> sig;    // box and hole clipped to the region (plus one column)
    std::set<int32_t> ys;     // region rows sent
  };
  struct Meshed {
    uint8_t open = 0;
    std::vector<Quad> quads;
  };
  struct Job {
    LodChunk key;
    uint8_t open = 0;
    const std::vector<Quad>* quads = nullptr;
  };
  std::vector<Rect> signature(int lod, int32_t rx, int32_t rz) const;
  // Chunks to draw in one region column, and the chunks their borders read.
  void plan(const ColumnKey& col, std::vector<Job>& jobs, std::vector<LodChunk>& needed) const;
  void build(const std::vector<ColumnKey>& cols, std::vector<RegionUpdate>& out);

  ChunkCache& cache_;
  StreamerParams p_;
  std::vector<Rect> box_, hole_;
  int64_t view_x_ = 0, view_z_ = 0;
  std::map<ColumnKey, Built> built_;
  std::map<LodChunk, Meshed> meshed_;  // quads per chunk, reused while borders hold
  std::set<ColumnKey> forced_;
  std::vector<ColumnKey> queue_;  // sorted, next at the back
  StreamerStats totals_;
};

}  // namespace em
