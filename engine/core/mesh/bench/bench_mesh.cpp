// Roadmap M3 measurements on real terrain: greedy meshing time and quad
// counts per chunk, at LOD 0 (2 cm), 1 (4 cm) and 2 (8 cm), then an estimate
// of the quads and memory of all LOD rings out to 640 m.
#include <algorithm>
#include <cstdio>
#include <cstdlib>
#include <map>
#include <tuple>
#include <vector>

#include "emergence/base/fixed.h"
#include "emergence/base/hash.h"
#include "emergence/base/timer.h"
#include "emergence/mesh/greedy.h"
#include "emergence/world/chunk_gen.h"
#include "emergence/world/materials.h"
#include "emergence/world/world_plan.h"

using namespace em;

namespace {

struct Source {
  const ChunkGenerator& gen;
  std::map<std::tuple<int, int, int, int>, Chunk> cache;

  const Chunk& get(int lod, int x, int y, int z) {
    auto key = std::make_tuple(lod, x, y, z);
    auto it = cache.find(key);
    if (it != cache.end()) return it->second;
    Chunk c;
    if (lod == 0) {
      VoxelId v = kAir;
      auto kind = gen.classify({x, y, z}, &v);
      if (kind == ChunkGenerator::Kind::Mixed) gen.generate({x, y, z}, c);
      else c.clear(v);
    } else {
      std::array<const Chunk*, 8> kids{};
      std::array<Chunk, 8> tmp;
      for (int k = 0; k < 8; ++k) {
        tmp[static_cast<size_t>(k)] = get(lod - 1, 2 * x + (k & 1), 2 * y + (k >> 2), 2 * z + ((k >> 1) & 1));
        kids[static_cast<size_t>(k)] = &tmp[static_cast<size_t>(k)];
      }
      downsample(kids, c);
    }
    c.coord = {x, y, z};
    return cache.emplace(key, std::move(c)).first->second;
  }
};

}  // namespace

int main(int argc, char** argv) {
  int samples = argc > 1 ? std::atoi(argv[1]) : 60;
  WorldPlan plan = generate_world_plan(WorldParams{1});
  ChunkGenerator gen(plan, MaterialTable::builtin());
  double quads_per_chunk[3] = {0, 0, 0};
  for (int lod = 0; lod <= 2; ++lod) {
    Source src{gen, {}};
    std::vector<double> times;
    size_t quads = 0, faces = 0, meshed = 0;
    int n = lod == 2 ? samples / 4 : samples;
    for (int k = 0; k < n; ++k) {
      int64_t vx = static_cast<int64_t>(mix64(static_cast<uint64_t>(k) * 2 + 11) % static_cast<uint64_t>(gen.map_voxels()));
      int64_t vz = static_cast<int64_t>(mix64(static_cast<uint64_t>(k) * 2 + 12) % static_cast<uint64_t>(gen.map_voxels()));
      int32_t s = gen.surface_voxel_y(vx, vz);
      int64_t size = int64_t{kChunkSize} << lod;
      int cx = static_cast<int>(vx / size), cy = static_cast<int>(floor_div(s, size)), cz = static_cast<int>(vz / size);
      const Chunk& c = src.get(lod, cx, cy, cz);
      ChunkBorders b;
      const int nb[6][3] = {{1, 0, 0}, {-1, 0, 0}, {0, 1, 0}, {0, -1, 0}, {0, 0, 1}, {0, 0, -1}};
      for (int d = 0; d < 6; ++d)
        border_from_neighbor(src.get(lod, cx + nb[d][0], cy + nb[d][1], cz + nb[d][2]), static_cast<FaceDir>(d),
                             b.solid[static_cast<size_t>(d)]);
      std::vector<Quad> q;
      Timer t;
      MeshStats st = mesh_chunk(c, b, q);
      times.push_back(t.ms());
      quads += st.quads;
      faces += st.faces;
      ++meshed;
    }
    std::sort(times.begin(), times.end());
    double sum = 0;
    for (double t : times) sum += t;
    quads_per_chunk[lod] = static_cast<double>(quads) / static_cast<double>(meshed);
    std::printf("LOD %d (%d cm voxels, chunk %.2f m): mesh %.3f ms mean, %.3f ms p95; %.0f quads/chunk (%.0f unit faces, x%.1f merge), %.1f KB\n",
                lod, 2 << lod, 1.28 * (1 << lod), sum / static_cast<double>(meshed), times[times.size() * 95 / 100],
                quads_per_chunk[lod], static_cast<double>(faces) / static_cast<double>(meshed),
                static_cast<double>(faces) / static_cast<double>(quads), quads_per_chunk[lod] * 8 / 1024);
  }
  // Ring estimate (architecture § 5): ring k uses 2^k x 2 cm voxels from
  // R(k-1) to R(k) = 10 m * 2^k; surface chunks ~ annulus area / chunk area,
  // x1.5 for the vertical relief. Quads per chunk beyond LOD 2 taken as LOD 2's.
  double total_quads = 0, total_chunks = 0;
  for (int k = 0; k <= 6; ++k) {
    double r1 = 10.0 * (1 << k), r0 = k == 0 ? 0 : 10.0 * (1 << (k - 1));
    double side = 1.28 * (1 << k);
    double chunks = 3.14159 * (r1 * r1 - r0 * r0) / (side * side) * 1.5;
    total_chunks += chunks;
    total_quads += chunks * quads_per_chunk[std::min(k, 2)];
  }
  std::printf("Rings to 640 m: ~%.0f chunks, ~%.2f M quads, ~%.0f MB of quads (8 B each), estimate\n", total_chunks,
              total_quads / 1e6, total_quads * 8 / 1048576.0);
  return 0;
}
