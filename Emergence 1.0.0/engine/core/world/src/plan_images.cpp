// Debug maps of the world plan. Not part of the simulation truth: floats are
// fine here.
#include <algorithm>
#include <cmath>

#include "emergence/base/image.h"
#include "emergence/world/world_plan.h"

namespace em {

namespace {

struct Rgb {
  float r, g, b;
};

Rgb biome_color(Biome b) {
  switch (b) {
    case Biome::Ocean: return {0.10f, 0.22f, 0.42f};
    case Biome::Beach: return {0.86f, 0.80f, 0.60f};
    case Biome::Marsh: return {0.38f, 0.45f, 0.33f};
    case Biome::Meadow: return {0.50f, 0.66f, 0.32f};
    case Biome::Woodland: return {0.30f, 0.50f, 0.22f};
    case Biome::DeepForest: return {0.13f, 0.30f, 0.14f};
    case Biome::Steppe: return {0.72f, 0.68f, 0.42f};
    case Biome::Desert: return {0.90f, 0.78f, 0.52f};
    case Biome::Foothills: return {0.52f, 0.55f, 0.36f};
    case Biome::Alpine: return {0.55f, 0.60f, 0.45f};
    case Biome::Rock: return {0.52f, 0.50f, 0.48f};
    case Biome::Snow: return {0.95f, 0.96f, 0.98f};
    case Biome::LakeBed: return {0.20f, 0.40f, 0.60f};
    default: return {1, 0, 1};
  }
}

uint8_t to8(float v) { return static_cast<uint8_t>(std::clamp(v, 0.0f, 1.0f) * 255.0f + 0.5f); }

float shade(const std::vector<int32_t>& h, int n, int i, int j, float cell_mm, float exaggeration) {
  auto H = [&](int a, int b) {
    a = std::clamp(a, 0, n - 1);
    b = std::clamp(b, 0, n - 1);
    return static_cast<float>(h[static_cast<size_t>(b) * static_cast<size_t>(n) + static_cast<size_t>(a)]);
  };
  float dx = (H(i + 1, j) - H(i - 1, j)) / (2 * cell_mm) * exaggeration;
  float dz = (H(i, j + 1) - H(i, j - 1)) / (2 * cell_mm) * exaggeration;
  // Light from the north-west, 45 degrees up.
  float nx = -dx, ny = 1.0f, nz = -dz;
  float len = std::sqrt(nx * nx + ny * ny + nz * nz);
  float l = (nx * -0.5f + ny * 0.7071f + nz * 0.5f) / len;
  return std::clamp(0.35f + 0.85f * l, 0.0f, 1.3f);
}

void put(std::vector<uint8_t>& img, int w, int x, int y, Rgb c) {
  size_t o = (static_cast<size_t>(y) * static_cast<size_t>(w) + static_cast<size_t>(x)) * 3;
  img[o] = to8(c.r);
  img[o + 1] = to8(c.g);
  img[o + 2] = to8(c.b);
}

bool write_relief(const WorldPlan& p, const std::string& path) {
  const int n = p.n;
  std::vector<uint8_t> img(static_cast<size_t>(n) * static_cast<size_t>(n) * 3);
  for (int j = 0; j < n; ++j) {
    for (int i = 0; i < n; ++i) {
      size_t c = p.idx(i, j);
      Rgb col = biome_color(static_cast<Biome>(p.biome[c]));
      float s = shade(p.height_mm, n, i, j, static_cast<float>(p.cell_mm), 2.0f);
      if (p.flags[c] & kFlagSea) {
        float depth = std::min(1.0f, static_cast<float>(-p.height_mm[c]) / 200000.0f);
        col = {0.18f - 0.10f * depth, 0.36f - 0.18f * depth, 0.58f - 0.20f * depth};
        s = 1.0f;
      } else if (p.flags[c] & kFlagLake) {
        col = {0.22f, 0.45f, 0.68f};
        s = 1.0f;
      } else if (p.flags[c] & kFlagRiver) {
        float f = std::min(1.0f, std::log10(static_cast<float>(p.flow_m2[c]) / 1.0e6f + 1.0f));
        col = {0.25f - 0.1f * f, 0.48f - 0.1f * f, 0.78f};
        s = 1.0f;
      }
      col = {col.r * s, col.g * s, col.b * s};
      if (p.flags[c] & kFlagRoad) col = {0.45f, 0.28f, 0.15f};
      // March limit: thin dark line where the depth crosses zero.
      if (i > 0 && j > 0) {
        bool in = p.march_side[c] != static_cast<uint8_t>(Side::None);
        bool l = p.march_side[p.idx(i - 1, j)] != static_cast<uint8_t>(Side::None);
        bool d = p.march_side[p.idx(i, j - 1)] != static_cast<uint8_t>(Side::None);
        if (in != l || in != d) col = {0.85f, 0.15f, 0.10f};
      }
      put(img, n, i, n - 1 - j, col);
    }
  }
  for (const auto& s : p.settlements) {
    int r = std::max(3, n / 160);
    for (int b = -r; b <= r; ++b)
      for (int a = -r; a <= r; ++a) {
        int x = s.i + a, y = n - 1 - (s.j + b);
        if (x < 0 || y < 0 || x >= n || y >= n) continue;
        bool border = std::abs(a) == r || std::abs(b) == r;
        put(img, n, x, y, border ? Rgb{0, 0, 0} : (s.kind == SettlementKind::Town ? Rgb{1, 0.85f, 0.1f} : Rgb{0.9f, 0.1f, 0.1f}));
      }
  }
  return write_png_rgb(path, n, n, img);
}

bool write_hostility(const WorldPlan& p, const std::string& path) {
  const int n = p.n;
  std::vector<uint8_t> img(static_cast<size_t>(n) * static_cast<size_t>(n) * 3);
  for (int j = 0; j < n; ++j) {
    for (int i = 0; i < n; ++i) {
      size_t c = p.idx(i, j);
      float h = static_cast<float>(p.hostility_q16(c)) / 65536.0f;
      float t = std::log2(h) / 10.0f;  // 0 at H=1, 1 at H=1024
      Rgb col = {0.2f + 0.8f * t, 0.8f - 0.7f * t, 0.3f - 0.2f * t};
      if (p.march_side[c] == static_cast<uint8_t>(Side::None)) col = {0.85f, 0.88f, 0.80f};
      float s = shade(p.height_mm, n, i, j, static_cast<float>(p.cell_mm), 1.0f);
      put(img, n, i, n - 1 - j, {col.r * s, col.g * s, col.b * s});
    }
  }
  return write_png_rgb(path, n, n, img);
}

bool write_backdrop(const WorldPlan& p, const BackdropLayer& b, const std::string& path) {
  const int n = b.n;
  if (n == 0) return true;
  std::vector<uint8_t> img(static_cast<size_t>(n) * static_cast<size_t>(n) * 3);
  const int64_t size_mm = int64_t{p.params.size_m} * 1000;
  for (int j = 0; j < n; ++j) {
    for (int i = 0; i < n; ++i) {
      float h = static_cast<float>(b.height_mm[static_cast<size_t>(j) * static_cast<size_t>(n) + static_cast<size_t>(i)]) / 1000.0f;
      Rgb col;
      if (h < 0) col = {0.12f, 0.25f, 0.48f};
      else if (h < 400) col = {0.45f + h / 2000.0f, 0.60f, 0.35f};
      else if (h < 2200) col = {0.55f, 0.52f, 0.42f};
      else col = {0.93f, 0.94f, 0.96f};
      float s = h < 0 ? 1.0f : shade(b.height_mm, n, i, j, static_cast<float>(b.cell_mm), 3.0f);
      col = {col.r * s, col.g * s, col.b * s};
      int64_t x = b.origin_x_mm + i * b.cell_mm, z = b.origin_z_mm + j * b.cell_mm;
      bool on_edge = (std::llabs(x) < b.cell_mm || std::llabs(x - size_mm) < b.cell_mm) && z >= 0 && z <= size_mm;
      on_edge = on_edge || ((std::llabs(z) < b.cell_mm || std::llabs(z - size_mm) < b.cell_mm) && x >= 0 && x <= size_mm);
      if (on_edge) col = {0.9f, 0.1f, 0.1f};
      put(img, n, i, n - 1 - j, col);
    }
  }
  return write_png_rgb(path, n, n, img);
}

}  // namespace

bool write_plan_images(const WorldPlan& plan, const std::string& dir) {
  bool ok = write_relief(plan, dir + "/plan_relief.png");
  ok = write_hostility(plan, dir + "/plan_hostility.png") && ok;
  ok = write_backdrop(plan, plan.near_backdrop, dir + "/backdrop_near_128m.png") && ok;
  ok = write_backdrop(plan, plan.far_backdrop, dir + "/backdrop_far_512m.png") && ok;
  return ok;
}

}  // namespace em
