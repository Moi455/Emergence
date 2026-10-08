// worldgen_tool: benchmarks and viewer exports for the fine generator.
//   worldgen_tool bench  [--seed N] [--size M]
//   worldgen_tool export [--seed N] [--size M] --out DIR
#include <algorithm>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <map>
#include <string>
#include <vector>

#include "emergence/base/fingerprint.h"
#include "emergence/base/fixed.h"
#include "emergence/base/hash.h"
#include "emergence/base/image.h"
#include "emergence/base/parallel.h"
#include "emergence/base/timer.h"
#include "emergence/worldgen/worldgen.h"

using namespace em;
using namespace em::wg;

namespace {

struct Args {
  uint64_t seed = 42;
  int32_t size = 20000;
  std::string out = "worldgen_export";
};

Args parse(int argc, char** argv) {
  Args a;
  for (int i = 2; i < argc; ++i) {
    std::string k = argv[i];
    auto next = [&]() -> const char* { return i + 1 < argc ? argv[++i] : ""; };
    if (k == "--seed") a.seed = std::strtoull(next(), nullptr, 10);
    else if (k == "--size") a.size = std::atoi(next());
    else if (k == "--out") a.out = next();
    else if (k == "--threads") set_worker_count(std::atoi(next()));
  }
  return a;
}

WorldParams params_of(const Args& a) {
  return a.size == 20000 ? [&] { WorldParams p; p.seed = a.seed; return p; }() : WorldParams::scaled(a.seed, a.size);
}

ChunkKey key_at(const WorldGen& g, int64_t x, int64_t z, int lod, int dy = 0) {
  int64_t S = chunk_mm(lod);
  int64_t h = g.ground_mm(x, z, lod);
  return {static_cast<int32_t>(x / S), static_cast<int32_t>(floor_div(h, S)) + dy, static_cast<int32_t>(z / S),
          static_cast<uint8_t>(lod)};
}

struct Site {
  std::string id, name;
  int64_t x, z;  // centre, mm
};

// Places worth showing: each settlement, a forest edge, the giant forest,
// a cave mouth, the mountains, the desert, the coast.
std::vector<Site> pick_sites(const WorldGen& g) {
  const WorldPlan& p = g.plan();
  const int64_t map = int64_t{p.n} * p.cell_mm;
  std::vector<Site> s;
  for (const auto& pad : g.settlement_pads()) {
    static const char* names[] = {"Port de pêche", "Village forestier", "Village minier", "Oasis des sauniers", "Bourg du marché"};
    s.push_back({std::string("pad_") + settlement_name(pad.kind), names[static_cast<int>(pad.kind)], pad.x_mm, pad.z_mm});
  }
  auto find_cell = [&](auto pred) -> int64_t {
    for (int64_t k = 0; k < static_cast<int64_t>(p.biome.size()); ++k) {
      uint64_t c = (static_cast<uint64_t>(k) * 2654435761ULL + 12345) % p.biome.size();
      if (pred(c)) return static_cast<int64_t>(c);
    }
    return -1;
  };
  auto add_cell = [&](const char* id, const char* name, int64_t c) {
    if (c < 0) return;
    s.push_back({id, name, (c % p.n) * p.cell_mm, (c / p.n) * p.cell_mm});
  };
  int forest = -1;
  for (int k = 0; k < 4; ++k)
    if (p.params.frontier[static_cast<size_t>(k)] == FrontierKind::Forest) forest = k;
  add_cell("forest_edge", "Lisière de la forêt profonde", find_cell([&](uint64_t c) {
             return p.biome[c] == static_cast<uint8_t>(Biome::DeepForest) && p.march_side[c] == forest && p.march_depth_m[c] > 0 &&
                    p.march_depth_m[c] < 300;
           }));
  add_cell("giants", "Arbres géants, au fond de la marche", find_cell([&](uint64_t c) {
             return p.biome[c] == static_cast<uint8_t>(Biome::DeepForest) && p.march_side[c] == forest &&
                    p.march_depth_m[c] > (2000 * p.params.scale_q16() >> 16);
           }));
  add_cell("mountain", "Contreforts de la montagne", find_cell([&](uint64_t c) {
             return p.biome[c] == static_cast<uint8_t>(Biome::Foothills) && p.march_side[c] == static_cast<uint8_t>(Side::North);
           }));
  add_cell("desert", "Dunes du désert", find_cell([&](uint64_t c) {
             return p.biome[c] == static_cast<uint8_t>(Biome::Desert) && p.march_depth_m[c] > 500;
           }));
  add_cell("coast", "Côte et plage", find_cell([&](uint64_t c) { return p.biome[c] == static_cast<uint8_t>(Biome::Beach); }));
  add_cell("meadow", "Prairie au détail de 2 cm", find_cell([&](uint64_t c) {
             return p.biome[c] == static_cast<uint8_t>(Biome::Woodland) && p.march_side[c] == static_cast<uint8_t>(Side::None);
           }));
  for (const auto& c : g.cave_segments()) {
    int64_t gy = g.ground_mm(c.bx, c.bz, 0);
    if (c.by > gy && c.ay < gy - 3000 && c.bx > 0 && c.bx < map &&
        p.biome[p.idx(static_cast<int32_t>(c.bx / p.cell_mm), static_cast<int32_t>(c.bz / p.cell_mm))] != static_cast<uint8_t>(Biome::DeepForest)) {
      s.push_back({"cave", "Entrée de grotte", (c.ax + c.bx) / 2, (c.az + c.bz) / 2});
      break;
    }
  }
  return s;
}

// ------------------------------------------------------------------- bench

int cmd_bench(const Args& a) {
  Timer t;
  WorldPlan plan = generate_world_plan(params_of(a));
  double plan_ms = t.ms();
  t.reset();
  WorldGen g(plan);
  double gen_ms = t.ms();
  CaveStats cs = g.cave_stats();
  std::printf("seed %llu, map %d m: plan %.0f ms, fine generator setup %.0f ms (caves: %zu systems, %zu segments, %zu chambers, %zu entrances)\n",
              static_cast<unsigned long long>(a.seed), a.size, plan_ms, gen_ms, cs.systems, cs.segments, cs.chambers, cs.entrances);
  set_worker_count(1);
  std::vector<VoxelId> vox(kChunkVoxels);
  auto sites = pick_sites(g);
  std::printf("%-22s %4s %8s %8s %8s %8s\n", "site (8x8 chunks)", "lod", "ground", "+1 up", "+3 up", "-4 down");
  for (const auto& s : sites) {
    for (int lod : {0, 2}) {
      double ms[4] = {};
      int dys[4] = {0, 1, 3, -4};
      for (int d = 0; d < 4; ++d) {
        Timer tt;
        for (int j = 0; j < 8; ++j)
          for (int i = 0; i < 8; ++i)
            g.generate(key_at(g, s.x + i * chunk_mm(lod) * 3, s.z + j * chunk_mm(lod) * 3, lod, dys[d]), vox.data());
        ms[d] = tt.ms() / 64;
      }
      std::printf("%-22s %4d %8.3f %8.3f %8.3f %8.3f  ms/chunk\n", s.id.c_str(), lod, ms[0], ms[1], ms[2], ms[3]);
    }
  }
  Timer tc;
  int64_t n = 0;
  for (int j = 0; j < 100; ++j)
    for (int i = 0; i < 100; ++i)
      for (int y = 0; y < 400; y += 7) {
        g.classify({i * 97, y - 390, j * 97, 0});
        ++n;
      }
  std::printf("classify: %.2f us per chunk\n", tc.ms() * 1000.0 / static_cast<double>(n));
  return 0;
}

// ------------------------------------------------------------------ export

void put_u16(std::vector<uint8_t>& b, uint32_t v) {
  b.push_back(static_cast<uint8_t>(v));
  b.push_back(static_cast<uint8_t>(v >> 8));
}
void put_i32(std::vector<uint8_t>& b, int32_t v) {
  for (int i = 0; i < 4; ++i) b.push_back(static_cast<uint8_t>(static_cast<uint32_t>(v) >> (8 * i)));
}

bool write_file(const std::string& path, const std::vector<uint8_t>& data) {
  std::ofstream o(path, std::ios::binary);
  o.write(reinterpret_cast<const char*>(data.data()), static_cast<std::streamsize>(data.size()));
  return static_cast<bool>(o);
}


// Map layers, downsampled by `step` plan cells. Little-endian, row j = z.
void export_map(const WorldGen& g, const std::string& dir, int step, std::string* json) {
  const WorldPlan& p = g.plan();
  const int32_t m = (p.n + step - 1) / step;
  std::vector<uint8_t> b;
  for (int32_t j = 0; j < m; ++j)
    for (int32_t i = 0; i < m; ++i) {
      size_t c = p.idx(std::min(i * step, p.n - 1), std::min(j * step, p.n - 1));
      put_u16(b, static_cast<uint16_t>(static_cast<int16_t>(p.height_mm[c] / 250)));  // quarter metres
    }
  for (int32_t j = 0; j < m; ++j)
    for (int32_t i = 0; i < m; ++i) {
      size_t c = p.idx(std::min(i * step, p.n - 1), std::min(j * step, p.n - 1));
      int32_t w = p.water_mm[c];
      put_u16(b, static_cast<uint16_t>(static_cast<int16_t>(w == WorldPlan::kNoWater ? -32768 : w / 250)));
    }
  auto layer = [&](auto fn) {
    for (int32_t j = 0; j < m; ++j)
      for (int32_t i = 0; i < m; ++i) b.push_back(fn(p.idx(std::min(i * step, p.n - 1), std::min(j * step, p.n - 1))));
  };
  layer([&](size_t c) { return p.biome[c]; });
  layer([&](size_t c) { return p.rock[c]; });
  // Flags: OR over the block so thin rivers and roads survive downsampling.
  for (int32_t j = 0; j < m; ++j)
    for (int32_t i = 0; i < m; ++i) {
      uint8_t f = 0;
      for (int b2 = 0; b2 < step; ++b2)
        for (int a2 = 0; a2 < step; ++a2) {
          int32_t ci = std::min(i * step + a2, p.n - 1), cj = std::min(j * step + b2, p.n - 1);
          f |= p.flags[p.idx(ci, cj)];
        }
      b.push_back(f);
    }
  layer([&](size_t c) {  // log2 of hostility, in sixteenths
    int64_t h = p.hostility_q16(c);
    int v = 0;
    while (h > kOne && v < 255) {
      h = (h * 61858) >> 16;  // divide by 2^(1/16)
      ++v;
    }
    return static_cast<uint8_t>(v);
  });
  layer([&](size_t c) { return p.march_side[c]; });
  write_file(dir + "/map.bin", b);

  // Far backdrop, quarter metres.
  std::vector<uint8_t> bd;
  const BackdropLayer& far = p.far_backdrop;
  for (int32_t v : far.height_mm) put_u16(bd, static_cast<uint16_t>(static_cast<int16_t>(std::clamp(v / 250, -32000, 32000))));
  write_file(dir + "/backdrop.bin", bd);

  char buf[512];
  std::snprintf(buf, sizeof buf,
                "\"map\":{\"n\":%d,\"step\":%d,\"cell_m\":%d,\"size_m\":%lld,\"seed\":%llu,\"plan_fingerprint\":\"%s\"},"
                "\"backdrop\":{\"n\":%d,\"cell_m\":%lld,\"origin_x_m\":%lld,\"origin_z_m\":%lld},",
                m, step, p.params.cell_m, static_cast<long long>(int64_t{p.n} * p.cell_mm / 1000),
                static_cast<unsigned long long>(p.params.seed), to_hex(p.fingerprint()).c_str(), far.n,
                static_cast<long long>(far.cell_mm / 1000), static_cast<long long>(far.origin_x_mm / 1000),
                static_cast<long long>(far.origin_z_mm / 1000));
  *json += buf;
  *json += "\"settlements\":[";
  for (size_t i = 0; i < g.settlement_pads().size(); ++i) {
    const auto& s = g.settlement_pads()[i];
    std::snprintf(buf, sizeof buf, "%s{\"kind\":\"%s\",\"x\":%.1f,\"z\":%.1f,\"h\":%.1f,\"r\":%.0f}", i ? "," : "",
                  settlement_name(s.kind), s.x_mm / 1000.0, s.z_mm / 1000.0, s.height_mm / 1000.0, s.radius_mm / 1000.0);
    *json += buf;
  }
  *json += "],\"roads\":[";
  for (size_t r = 0; r < p.roads.size(); ++r) {
    *json += r ? ",[" : "[";
    const auto& cells = p.roads[r].cells;
    for (size_t k = 0; k < cells.size(); k += 2) {
      std::snprintf(buf, sizeof buf, "%s%d,%d", k ? "," : "", static_cast<int>(cells[k] % static_cast<uint32_t>(p.n)),
                    static_cast<int>(cells[k] / static_cast<uint32_t>(p.n)));
      *json += buf;
    }
    *json += "]";
  }
  *json += "],";
  // Caves: segments as [x, z, y] in metres (plan for the map overlay).
  std::vector<uint8_t> cv;
  for (const auto& c : g.cave_segments()) {
    put_i32(cv, static_cast<int32_t>(c.ax / 100));
    put_i32(cv, static_cast<int32_t>(c.az / 100));
    put_i32(cv, static_cast<int32_t>(c.bx / 100));
    put_i32(cv, static_cast<int32_t>(c.bz / 100));
    put_u16(cv, static_cast<uint16_t>(static_cast<int16_t>((c.ay + c.by) / 2000)));
    put_u16(cv, static_cast<uint16_t>(std::max(c.ra, c.rb) / 100));
  }
  write_file(dir + "/caves.bin", cv);
  CaveStats cs = g.cave_stats();
  std::snprintf(buf, sizeof buf, "\"caves\":{\"systems\":%zu,\"segments\":%zu,\"chambers\":%zu,\"entrances\":%zu},", cs.systems,
                cs.segments, cs.chambers, cs.entrances);
  *json += buf;
}

// A site: voxels of a square region, as runs per column (bottom to top):
// header, then per column: run count (u16), then per run: start (u16, voxels
// from the site floor), length (u16), voxel (u16).
struct SiteStats {
  size_t runs = 0, chunks = 0, generated = 0;
  double ms = 0;
};

SiteStats export_site(const WorldGen& g, const Site& s, int lod, int chunks_side, const std::string& path, std::string* json) {
  SiteStats st;
  Timer t;
  const int64_t S = chunk_mm(lod), v = voxel_mm(lod);
  const int32_t cx0 = static_cast<int32_t>(s.x / S) - chunks_side / 2, cz0 = static_cast<int32_t>(s.z / S) - chunks_side / 2;
  const int N = chunks_side * kChunkSize;
  // Vertical range: lowest ground minus 3 m to the tallest tree top.
  int64_t lo = INT64_MAX, hi = INT64_MIN;
  for (int j = 0; j <= 8; ++j)
    for (int i = 0; i <= 8; ++i) {
      int64_t gy = g.ground_mm(cx0 * S + (i * chunks_side * S) / 8, cz0 * S + (j * chunks_side * S) / 8, lod);
      lo = std::min(lo, gy);
      hi = std::max(hi, gy);
    }
  std::vector<TreeInstance> trees;
  g.trees_in(cx0 * S - 80000, cz0 * S - 80000, (cx0 + chunks_side) * S + 80000, (cz0 + chunks_side) * S + 80000, &trees);
  int64_t top = hi + 4000;
  for (const auto& tr : trees) top = std::max(top, tr.y_mm + (int64_t{tr.height_mm} * 115) / 100);
  if (s.id == "cave") {  // look into the mouth: from 14 m below the lowest ground to 6 m above the highest
    top = hi + 6000;
    lo -= 11000;
  }
  int32_t cy0 = static_cast<int32_t>(floor_div(lo - 3000, S));
  int32_t cy1 = static_cast<int32_t>(floor_div(top, S));
  if (cy1 - cy0 > 40) cy1 = cy0 + 40;
  const int H = (cy1 - cy0 + 1) * kChunkSize;
  std::vector<std::vector<uint16_t>> cols(static_cast<size_t>(N) * static_cast<size_t>(N));
  std::vector<VoxelId> vox(kChunkVoxels);
  std::vector<VoxelId> prev(static_cast<size_t>(N) * static_cast<size_t>(N), 0xFFFF);
  std::vector<int> run_start(static_cast<size_t>(N) * static_cast<size_t>(N), 0);
  for (int32_t cy = cy0; cy <= cy1; ++cy)
    for (int32_t cz = cz0; cz < cz0 + chunks_side; ++cz)
      for (int32_t cx = cx0; cx < cx0 + chunks_side; ++cx) {
        ChunkInfo info = g.generate({cx, cy, cz, static_cast<uint8_t>(lod)}, vox.data());
        ++st.chunks;
        st.generated += info.kind == ChunkKind::Mixed;
        for (int z = 0; z < kChunkSize; ++z)
          for (int x = 0; x < kChunkSize; ++x) {
            size_t col = static_cast<size_t>((cz - cz0) * kChunkSize + z) * static_cast<size_t>(N) +
                         static_cast<size_t>((cx - cx0) * kChunkSize + x);
            for (int y = 0; y < kChunkSize; ++y) {
              VoxelId vv = vox[voxel_index(x, y, z)];
              int gy = (cy - cy0) * kChunkSize + y;
              if (vv != prev[col]) {
                if (prev[col] != 0xFFFF && prev[col] != kAir) {
                  cols[col].push_back(static_cast<uint16_t>(run_start[col]));
                  cols[col].push_back(static_cast<uint16_t>(gy - run_start[col]));
                  cols[col].push_back(prev[col]);
                }
                prev[col] = vv;
                run_start[col] = gy;
              }
            }
          }
      }
  for (size_t col = 0; col < cols.size(); ++col)
    if (prev[col] != kAir && prev[col] != 0xFFFF) {
      cols[col].push_back(static_cast<uint16_t>(run_start[col]));
      cols[col].push_back(static_cast<uint16_t>(H - run_start[col]));
      cols[col].push_back(prev[col]);
    }
  // Keep only what can be seen: a run survives if air touches it from above,
  // below or a side (the site edges count as air, so they show a cut through
  // the layers); buried parts are clipped and flagged (bit 15 of the start)
  // so that the viewer draws no bottom face there.
  auto lowest_air_in = [&](int i, int j, int lo, int hi) -> int {  // first air y in [lo, hi) of column, or hi
    if (i < 0 || j < 0 || i >= N || j >= N) return lo;
    const auto& r = cols[static_cast<size_t>(j) * static_cast<size_t>(N) + static_cast<size_t>(i)];
    int y = lo;
    for (size_t k = 0; k < r.size(); k += 3) {
      int s0 = r[k], e0 = r[k] + r[k + 1];
      if (e0 <= y) continue;
      if (s0 > y) return y < hi ? y : hi;
      y = e0;
      if (y >= hi) return hi;
    }
    return y < hi ? y : hi;
  };
  std::vector<uint8_t> b;
  for (int j = 0; j < N; ++j)
    for (int i = 0; i < N; ++i) {
      const auto& r = cols[static_cast<size_t>(j) * static_cast<size_t>(N) + static_cast<size_t>(i)];
      std::vector<uint16_t> keep;
      for (size_t k = 0; k < r.size(); k += 3) {
        int s0 = r[k], e0 = r[k] + r[k + 1];
        bool top = e0 < H && !(k + 3 < r.size() && r[k + 3] == e0);
        bool bottom = s0 > 0 && !(k >= 3 && r[k - 3] + r[k - 2] == s0);
        int lo = bottom ? s0 : e0;
        if (top) lo = std::min(lo, e0 - 1);
        lo = std::min({lo, lowest_air_in(i - 1, j, s0, e0), lowest_air_in(i + 1, j, s0, e0), lowest_air_in(i, j - 1, s0, e0),
                       lowest_air_in(i, j + 1, s0, e0)});
        if (lo >= e0) continue;
        // Bit 15: the voxel below this run's start is solid (clipped, or resting on a buried run).
        keep.push_back(static_cast<uint16_t>(lo | ((lo > s0 || !bottom) ? 0x8000 : 0)));
        keep.push_back(static_cast<uint16_t>(e0 - lo));
        keep.push_back(r[k + 2]);
      }
      put_u16(b, static_cast<uint32_t>(keep.size() / 3));
      for (uint16_t w : keep) put_u16(b, w);
      st.runs += keep.size() / 3;
    }
  write_file(path, b);
  st.ms = t.ms();
  int32_t wl = g.water_mm(s.x, s.z);
  std::string water = wl == WorldPlan::kNoWater ? "null" : std::to_string(wl / 1000.0);
  char buf[768];
  std::snprintf(buf, sizeof buf,
                "{\"id\":\"%s\",\"name\":\"%s\",\"file\":\"%s.bin\",\"lod\":%d,\"voxel_mm\":%lld,\"n\":%d,\"h\":%d,"
                "\"x0_m\":%.2f,\"z0_m\":%.2f,\"y0_m\":%.2f,\"water_m\":%s,\"trees\":%zu,\"chunks\":%zu,\"ms\":%.0f}",
                s.id.c_str(), s.name.c_str(), s.id.c_str(), lod, static_cast<long long>(v), N, H, cx0 * S / 1000.0,
                cz0 * S / 1000.0, cy0 * S / 1000.0, water.c_str(), trees.size(), st.chunks, st.ms);
  *json += buf;
  return st;
}

// Vertical cross-section through the ground, as a PNG (materials coloured).
void export_slice(const WorldGen& g, int64_t x0, int64_t z, int64_t len_m, int64_t ylo_m, int64_t yhi_m, int lod,
                  const std::string& path, const MaterialTable& mt) {
  const int64_t S = chunk_mm(lod), v = voxel_mm(lod);
  const int64_t ylo = ylo_m * 1000, yhi = yhi_m * 1000;
  const int W = static_cast<int>(len_m * 1000 / v), Hh = static_cast<int>((yhi - ylo) / v);
  std::vector<uint8_t> rgb(static_cast<size_t>(W) * static_cast<size_t>(Hh) * 3, 0);
  std::vector<VoxelId> vox(kChunkVoxels);
  const int32_t cz = static_cast<int32_t>(z / S);
  const int zi = static_cast<int>((z - cz * S) / v);
  for (int32_t cx = static_cast<int32_t>(x0 / S); cx * S < x0 + len_m * 1000; ++cx)
    for (int32_t cy = static_cast<int32_t>(floor_div(ylo, S)); cy * S < yhi; ++cy) {
      g.generate({cx, cy, cz, static_cast<uint8_t>(lod)}, vox.data());
      for (int y = 0; y < kChunkSize; ++y)
        for (int x = 0; x < kChunkSize; ++x) {
          int64_t wx = cx * S + x * v, wy = cy * S + y * v;
          int px = static_cast<int>((wx - x0) / v), py = Hh - 1 - static_cast<int>((wy - ylo) / v);
          if (px < 0 || px >= W || py < 0 || py >= Hh) continue;
          VoxelId vv = vox[voxel_index(x, y, zi)];
          uint32_t c = vv == kAir ? 0xbcd4e6 : mt.get(voxel_class(vv)).color;
          int64_t wl = g.water_mm(wx, z);
          if (vv == kAir && wl != WorldPlan::kNoWater && wy < wl) c = 0x2f6f9f;
          size_t o = (static_cast<size_t>(py) * static_cast<size_t>(W) + static_cast<size_t>(px)) * 3;
          rgb[o] = static_cast<uint8_t>(c >> 16);
          rgb[o + 1] = static_cast<uint8_t>(c >> 8);
          rgb[o + 2] = static_cast<uint8_t>(c);
        }
    }
  write_png_rgb(path, W, Hh, rgb);
}

// Plan view of a cave system: the rock at height y, with every gallery and
// chamber within +/- band metres projected on top, coloured by depth.
void export_hslice(const WorldGen& g, int64_t x0, int64_t z0, int64_t len_m, int64_t y, int64_t band_m, int lod,
                   const std::string& path, const MaterialTable& mt) {
  const int64_t S = chunk_mm(lod), v = voxel_mm(lod);
  const int Wd = static_cast<int>(len_m * 1000 / v);
  const size_t px_count = static_cast<size_t>(Wd) * static_cast<size_t>(Wd);
  std::vector<uint32_t> base(px_count, 0x808080);
  std::vector<int64_t> cave_y(px_count, INT64_MIN);
  std::vector<VoxelId> vox(kChunkVoxels);
  const int64_t ylo = y - band_m * 1000, yhi = y + band_m * 1000;
  for (int32_t cy = static_cast<int32_t>(floor_div(ylo, S)); cy * S < yhi; ++cy)
    for (int32_t cz = static_cast<int32_t>(z0 / S); cz * S < z0 + len_m * 1000; ++cz)
      for (int32_t cx = static_cast<int32_t>(x0 / S); cx * S < x0 + len_m * 1000; ++cx) {
        g.generate({cx, cy, cz, static_cast<uint8_t>(lod)}, vox.data());
        for (int z = 0; z < kChunkSize; ++z)
          for (int x = 0; x < kChunkSize; ++x) {
            int64_t wx = cx * S + x * v, wz = cz * S + z * v;
            int px = static_cast<int>((wx - x0) / v), py = Wd - 1 - static_cast<int>((wz - z0) / v);
            if (px < 0 || px >= Wd || py < 0 || py >= Wd) continue;
            size_t o = static_cast<size_t>(py) * static_cast<size_t>(Wd) + static_cast<size_t>(px);
            int64_t gy = -1;
            for (int yy = 0; yy < kChunkSize; ++yy) {
              int64_t wy = cy * S + yy * v + v / 2;
              if (wy < ylo || wy >= yhi) continue;
              VoxelId vv = vox[voxel_index(x, yy, z)];
              if (wy <= y && wy + v > y && vv != kAir) base[o] = mt.get(voxel_class(vv)).color;
              if (vv == kAir) {
                if (gy < 0) gy = g.ground_mm(wx, wz, lod);
                if (wy < gy - 3000 && wy > cave_y[o]) cave_y[o] = wy;
              }
            }
          }
      }
  std::vector<uint8_t> rgb(px_count * 3);
  for (size_t o = 0; o < px_count; ++o) {
    uint32_t c = base[o];
    int r = static_cast<int>(c >> 16 & 255) * 7 / 10, gg = static_cast<int>(c >> 8 & 255) * 7 / 10, b = static_cast<int>(c & 255) * 7 / 10;
    if (cave_y[o] != INT64_MIN) {  // deep = violet, high = pale blue
      int t = static_cast<int>(clamp64((cave_y[o] - ylo) * 255 / (yhi - ylo), 0, 255));
      r = 40 + t * 150 / 255; gg = 30 + t * 190 / 255; b = 110 + t * 140 / 255;
    }
    rgb[o * 3] = static_cast<uint8_t>(r);
    rgb[o * 3 + 1] = static_cast<uint8_t>(gg);
    rgb[o * 3 + 2] = static_cast<uint8_t>(b);
  }
  write_png_rgb(path, Wd, Wd, rgb);
}

int cmd_export(const Args& a) {
  Timer total;
  std::filesystem::create_directories(a.out);
  WorldPlan plan = generate_world_plan(params_of(a));
  WorldGen g(plan);
  std::string json = "{";
  char buf[256];
  std::snprintf(buf, sizeof buf, "\"generator\":{\"plan_version\":%u,\"chunk_version\":%u,\"plan_ms\":%.0f},",
                plan.generator_version, kChunkGenVersion, plan.timings.total_ms);
  json += buf;
  export_map(g, a.out, 2, &json);

  const MaterialTable& mt = MaterialTable::builtin();
  json += "\"materials\":[";
  bool first = true;
  for (MaterialClass c = 0; c < kMaxClasses; ++c) {
    if (!mt.has(c)) continue;
    std::snprintf(buf, sizeof buf, "%s{\"id\":%d,\"name\":\"%s\",\"color\":\"%06x\"}", first ? "" : ",", c, mt.get(c).name.c_str(),
                  mt.get(c).color);
    json += buf;
    first = false;
  }
  json += "],\"sites\":[";
  // Level of detail and size (in chunks) per site.
  std::map<std::string, std::pair<int, int>> sizes = {
      {"pad_town", {4, 12}}, {"pad_port", {4, 10}}, {"pad_foresters", {4, 10}}, {"pad_miners", {4, 10}}, {"pad_oasis", {4, 10}},
      {"forest_edge", {2, 8}}, {"giants", {4, 8}}, {"mountain", {3, 8}}, {"desert", {3, 8}}, {"coast", {3, 8}},
      {"meadow", {0, 8}}, {"cave", {1, 10}}};
  auto sites = pick_sites(g);
  first = true;
  for (const auto& s : sites) {
    auto it = sizes.find(s.id);
    if (it == sizes.end()) continue;
    if (!first) json += ",";
    first = false;
    SiteStats st = export_site(g, s, it->second.first, it->second.second, a.out + "/" + s.id + ".bin", &json);
    std::printf("site %-14s lod %d: %zu chunks, %zu runs, %.0f ms\n", s.id.c_str(), it->second.first, st.chunks, st.runs, st.ms);
  }
  json += "],\"slices\":[";
  // Cross-sections: one shallow at 16 cm through a cave system, one deep at 64 cm.
  first = true;
  int k = 0;
  for (const auto& c : g.cave_segments()) {
    int64_t gy = g.ground_mm(c.ax, c.az, 0);
    if (gy - c.ay > 60000 || c.ay > gy - 10000) continue;
    int64_t yc = c.ay / 1000;
    int64_t x0 = std::max<int64_t>(c.ax - 100000, 0);
    std::string name = "slice_cave_" + std::to_string(k);
    int64_t ylo = yc - 40, yhi = gy / 1000 + 30;
    export_slice(g, x0, c.az, 200, ylo, yhi, 3, a.out + "/" + name + ".png", mt);
    std::snprintf(buf, sizeof buf, "%s{\"file\":\"%s.png\",\"x0\":%.0f,\"z\":%.0f,\"len\":200,\"ylo\":%lld,\"yhi\":%lld,\"voxel_cm\":16}",
                  first ? "" : ",", name.c_str(), x0 / 1000.0, c.az / 1000.0, static_cast<long long>(ylo), static_cast<long long>(yhi));
    json += buf;
    first = false;
    if (++k == 1) break;
  }
  {
    // Plan view through the largest cave system, at the depth of its middle segment.
    std::map<uint32_t, std::vector<const CaveSegment*>> by_sys;
    for (const auto& c : g.cave_segments()) by_sys[c.system].push_back(&c);
    const std::vector<const CaveSegment*>* best = nullptr;
    for (const auto& [id, v] : by_sys)
      if (!best || v.size() > best->size()) best = &v;
    if (best) {
      std::vector<int64_t> ys;
      int64_t sx = 0, sz = 0;
      for (const auto* c : *best) { ys.push_back(c->ay); sx += c->ax; sz += c->az; }
      std::sort(ys.begin(), ys.end());
      int64_t y = ys[ys.size() / 2], cx = sx / static_cast<int64_t>(best->size()), cz = sz / static_cast<int64_t>(best->size());
      int64_t x0 = std::max<int64_t>(cx - 150000, 0), z0 = std::max<int64_t>(cz - 150000, 0);
      export_hslice(g, x0, z0, 300, y, 40, 4, a.out + "/slice_plan.png", mt);
      std::snprintf(buf, sizeof buf, ",{\"file\":\"slice_plan.png\",\"plan\":true,\"x0\":%.0f,\"z\":%.0f,\"len\":300,\"y\":%.0f,\"segments\":%zu,\"band\":40,\"voxel_cm\":32}",
                    x0 / 1000.0, z0 / 1000.0, y / 1000.0, best->size());
      json += buf;
    }
  }
  {
    const auto& pads = g.settlement_pads();
    int64_t z = pads.empty() ? plan.n * plan.cell_mm / 2 : pads.front().z_mm;
    int64_t x0 = std::max<int64_t>(pads.empty() ? 0 : pads.front().x_mm - 600000, 0);
    export_slice(g, x0, z, 1200, -500, 450, 5, a.out + "/slice_deep.png", mt);
    std::snprintf(buf, sizeof buf, "%s{\"file\":\"slice_deep.png\",\"x0\":%.0f,\"z\":%.0f,\"len\":1200,\"ylo\":-500,\"yhi\":450,\"voxel_cm\":64}",
                  first ? "" : ",", x0 / 1000.0, z / 1000.0);
    json += buf;
  }
  json += "]}";
  std::ofstream(a.out + "/world.json") << json;
  std::printf("export done in %.1f s -> %s\n", total.ms() / 1000.0, a.out.c_str());
  return 0;
}

}  // namespace

int main(int argc, char** argv) {
  if (argc < 2) {
    std::printf("usage: worldgen_tool bench|export [--seed N] [--size M] [--out DIR] [--threads T]\n");
    return 2;
  }
  Args a = parse(argc, argv);
  std::string cmd = argv[1];
  if (cmd == "bench") return cmd_bench(a);
  if (cmd == "export") return cmd_export(a);
  std::printf("unknown command %s\n", cmd.c_str());
  return 2;
}
