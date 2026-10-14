// Backdrop beyond the map edge (architecture § 2.2, monde_horizon.md): relief
// at 128 m out to about 50 km, then 512 m out to the horizon of a 3 km summit
// (~200 km). Never voxelised; inside the map it copies the eroded plan.
#include <algorithm>

#include "emergence/base/parallel.h"
#include "plan_internal.h"

namespace em::plan {

namespace {

void fill_layer(const WorldPlan& p, const Relief& relief, BackdropLayer& layer, int64_t cell_mm, int32_t n) {
  const int64_t size_mm = int64_t{p.params.size_m} * 1000;
  layer.cell_mm = cell_mm;
  layer.n = n;
  layer.origin_x_mm = size_mm / 2 - cell_mm * n / 2;
  layer.origin_z_mm = layer.origin_x_mm;
  layer.height_mm.assign(static_cast<size_t>(n) * static_cast<size_t>(n), 0);
  parallel_for(0, n, [&](int64_t j0, int64_t j1) {
    for (int64_t j = j0; j < j1; ++j) {
      for (int64_t i = 0; i < n; ++i) {
        int64_t x = layer.origin_x_mm + i * cell_mm, z = layer.origin_z_mm + j * cell_mm;
        int64_t h;
        if (x >= 0 && z >= 0 && x < size_mm && z < size_mm) h = p.height_at_mm(x, z);
        else h = relief.height_mm(x, z, cell_mm * 2, nullptr);
        layer.height_mm[static_cast<size_t>(j * n + i)] = static_cast<int32_t>(h);
      }
    }
  });
}

}  // namespace

void build_backdrop(WorldPlan& p, const Relief& relief) {
  // Distances scale with small test maps so the layout stays the same.
  const int64_t sc = p.params.scale_q16();
  fill_layer(p, relief, p.near_backdrop, std::max<int64_t>((128'000 * sc) >> 16, p.cell_mm), 800);
  fill_layer(p, relief, p.far_backdrop, std::max<int64_t>((512'000 * sc) >> 16, p.cell_mm), 800);
}

}  // namespace em::plan
