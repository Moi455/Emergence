// Pre-erosion relief: an inhabited core of rolling hills, and one march per
// side whose terrain is shaped by its depth (sea floor sinking, mountains
// rising to 3 km, desert plateau with dunes, forest hills). The same function
// continues past the map edge for the backdrop.
#include <algorithm>

#include "emergence/base/fixed.h"
#include "emergence/base/hash.h"
#include "emergence/base/noise.h"
#include "plan_internal.h"

namespace em::plan {

namespace {
constexpr int64_t M = 1000;  // millimetres per metre
}

int octaves_for(int64_t wavelength_mm, int64_t min_wavelength_mm, int max_octaves) {
  int o = 0;
  while (o < max_octaves && (wavelength_mm >> o) >= min_wavelength_mm) ++o;
  return std::max(o, 1);
}

Relief::Relief(const WorldParams& p) : p_(p), scale_q16_(p.scale_q16()), size_mm_(int64_t{p.size_m} * M) {}

FrontierSample Relief::frontier(int64_t x, int64_t z) const {
  FrontierSample fs;
  for (int s = 0; s < 4; ++s) {
    int64_t dist_to_edge, along;
    switch (static_cast<Side>(s)) {
      case Side::West: dist_to_edge = x; along = z; break;
      case Side::North: dist_to_edge = size_mm_ - z; along = x; break;
      case Side::East: dist_to_edge = size_mm_ - x; along = z; break;
      default: dist_to_edge = z; along = x; break;
    }
    // The inner limit is never a straight line: it wanders by up to ~1 km,
    // with bays and headlands down to a few hundred metres.
    uint64_t seed = hash_combine(layer_seed(p_.seed, Layer::Frontier), static_cast<uint64_t>(s));
    int64_t wander = fbm2(seed, to_noise(along, L(5000 * M)), to_noise(dist_to_edge, L(5000 * M)), 5);
    int64_t width = int64_t{p_.march_width_m[static_cast<size_t>(s)]} * M;
    wander = (wander * kOne) / (kOne + abs64(wander));  // soft clamp: never more than 2 km
    fs.depth_mm[static_cast<size_t>(s)] = width + ((wander * L(2000 * M)) >> 16) - dist_to_edge;
    FrontierKind kind = p_.frontier[static_cast<size_t>(s)];
    int64_t lo = kind == FrontierKind::Sea ? L(-300 * M) : L(-1200 * M);
    int64_t hi = kind == FrontierKind::Sea ? L(400 * M) : L(600 * M);
    fs.weight_q16[static_cast<size_t>(s)] = qsmoothstep(lo, hi, fs.depth_mm[static_cast<size_t>(s)]);
  }
  return fs;
}

int64_t Relief::side_height(FrontierKind kind, int64_t base, int64_t d, int64_t x, int64_t z,
                            int64_t min_wl) const {
  switch (kind) {
    case FrontierKind::Sea: {
      // Shelf sinking to about -200 m at the map edge, deeper beyond it.
      int64_t unscaled = (std::max<int64_t>(d, 0) * kOne) / scale_q16_;
      int64_t floor = -(15 * M + (unscaled * 62) / 1000);
      uint64_t s = layer_seed(p_.seed, Layer::Sea);
      floor += (fbm2(s, to_noise(x, L(2500 * M)), to_noise(z, L(2500 * M)), octaves_for(L(2500 * M), min_wl, 4)) * 15 * M) >> 16;
      // Distant islands and coasts, only past the map edge (backdrop).
      int64_t sea_width = 0;
      for (int s2 = 0; s2 < 4; ++s2)
        if (p_.frontier[static_cast<size_t>(s2)] == FrontierKind::Sea) sea_width = int64_t{p_.march_width_m[static_cast<size_t>(s2)]} * M;
      int64_t beyond = d - sea_width;
      if (beyond > 0) {
        int64_t isl = ridged2(hash_combine(s, 7), to_noise(x, L(9000 * M)), to_noise(z, L(9000 * M)),
                              octaves_for(L(9000 * M), min_wl, 5));
        int64_t lift = qsmoothstep(kOne * 55 / 100, kOne * 80 / 100, isl);
        floor = qlerp(floor, 400 * M, (lift * qramp(0, L(8000 * M), beyond)) >> 16);
      }
      return floor;
    }
    case FrontierKind::Desert: {
      uint64_t s = layer_seed(p_.seed, Layer::Desert);
      // Plateau continuous with the core edge, slowly rising into the march.
      int64_t plateau = base + 10 * M + ((60 * M * qramp(0, L(3000 * M), d)) >> 16) +
                        ((fbm2(s, to_noise(x, L(5000 * M)), to_noise(z, L(5000 * M)),
                               octaves_for(L(5000 * M), min_wl, 4)) * 25 * M) >> 16);
      int64_t dune_amp = 8 * M + ((25 * M * qramp(0, L(3000 * M), d)) >> 16);
      int64_t dunes = ridged2(hash_combine(s, 1), to_noise(x, L(420 * M)), to_noise(z, L(260 * M)),
                              octaves_for(L(420 * M), min_wl, 2));
      return plateau + ((dunes * dune_amp) >> 16);
    }
    case FrontierKind::Forest: {
      uint64_t s = layer_seed(p_.seed, Layer::Forest);
      int64_t amp = 60 * M + ((140 * M * qramp(0, L(3000 * M), d)) >> 16);
      int64_t hills = fbm2(s, to_noise(x, L(2500 * M)), to_noise(z, L(2500 * M)), octaves_for(L(2500 * M), min_wl, 5));
      return base + 40 * M + ((abs64(hills) * amp * 2) >> 16);
    }
    case FrontierKind::Mountain:
      return base;  // mountains are additive, see height_mm
  }
  return base;
}

int64_t Relief::height_mm(int64_t x, int64_t z, int64_t min_wl, FrontierSample* out) const {
  FrontierSample fs = frontier(x, z);
  if (out) *out = fs;

  // Inhabited core: rolling hills and valleys between 10 and 300 m.
  uint64_t cs = layer_seed(p_.seed, Layer::CoreRelief);
  int64_t n1 = fbm2(cs, to_noise(x, L(7000 * M)), to_noise(z, L(7000 * M)), octaves_for(L(7000 * M), min_wl, 5));
  int64_t n2 = fbm2(hash_combine(cs, 1), to_noise(x, L(1800 * M)), to_noise(z, L(1800 * M)),
                    octaves_for(L(1800 * M), min_wl, 5));
  int64_t hilly = qsmoothstep(-kOne / 4, kOne / 2, fbm2(hash_combine(cs, 2), to_noise(x, L(5000 * M)),
                                                       to_noise(z, L(5000 * M)), 2));
  int64_t ridges = ridged2(hash_combine(cs, 3), to_noise(x, L(3000 * M)), to_noise(z, L(3000 * M)),
                           octaves_for(L(3000 * M), min_wl, 4));
  int64_t h = 140 * M + ((n1 * 110 * M) >> 16) + ((n2 * 35 * M) >> 16) + ((((ridges * 90 * M) >> 16) * hilly) >> 16);
  h = std::max<int64_t>(h, 12 * M);

  // Regional tilt: the land rises away from the sea, so rivers drain to it.
  for (int s = 0; s < 4; ++s) {
    if (p_.frontier[static_cast<size_t>(s)] != FrontierKind::Sea) continue;
    h += (170 * M * qramp(0, L(14000 * M), -fs.depth_mm[static_cast<size_t>(s)])) >> 16;
  }

  // Lowlands toward the sea: the core flattens as it nears the coast.
  for (int s = 0; s < 4; ++s) {
    if (p_.frontier[static_cast<size_t>(s)] != FrontierKind::Sea) continue;
    int64_t c = qramp(L(-3000 * M), 0, fs.depth_mm[static_cast<size_t>(s)]);
    h = h - ((h * ((c * 85) / 100)) >> 16);
  }

  // Blend toward each march's own terrain (desert and forest first, sea last
  // so that coasts win in the corners).
  const FrontierKind order[3] = {FrontierKind::Desert, FrontierKind::Forest, FrontierKind::Sea};
  for (FrontierKind k : order) {
    for (int s = 0; s < 4; ++s) {
      if (p_.frontier[static_cast<size_t>(s)] != k) continue;
      int64_t w = fs.weight_q16[static_cast<size_t>(s)];
      if (w == 0) continue;
      h = qlerp(h, side_height(k, h, fs.depth_mm[static_cast<size_t>(s)], x, z, min_wl), w);
    }
  }

  // Mountains: additive ridged massif whose envelope rises from the foothills
  // (2.5 km inside the core) to 3 km at the map edge and 6 km far beyond.
  for (int s = 0; s < 4; ++s) {
    if (p_.frontier[static_cast<size_t>(s)] != FrontierKind::Mountain) continue;
    int64_t width = int64_t{p_.march_width_m[static_cast<size_t>(s)]} * M;
    int64_t m = fs.depth_mm[static_cast<size_t>(s)] + L(2500 * M);
    if (m <= 0) continue;
    int64_t edge = width + L(2500 * M);
    int64_t envelope = ((3000 * M * qsmoothstep(0, edge, m)) >> 16) +
                       ((3000 * M * qsmoothstep(edge, 2 * edge, m)) >> 16);
    uint64_t ms = layer_seed(p_.seed, Layer::Mountain);
    int64_t r = ridged2(ms, to_noise(x, L(3500 * M)), to_noise(z, L(3500 * M)), octaves_for(L(3500 * M), min_wl, 7));
    h += (envelope * (kOne * 30 / 100 + ((r * 75) / 100))) >> 16;
  }
  return h;
}

int64_t Relief::moisture_q16(int64_t x, int64_t z, const FrontierSample& fs) const {
  // Prevailing wind from the sea: wet on the sea side, dry toward the desert.
  int64_t m = kOne * 6 / 10;
  for (int s = 0; s < 4; ++s) {
    int64_t d = fs.depth_mm[static_cast<size_t>(s)];
    switch (p_.frontier[static_cast<size_t>(s)]) {
      case FrontierKind::Sea: m += (qramp(L(-14000 * M), 0, d) * 35) / 100; break;
      case FrontierKind::Desert: m -= (qramp(L(-6000 * M), L(1000 * M), d) * 55) / 100; break;
      case FrontierKind::Forest: m += (qramp(L(-3000 * M), L(1000 * M), d) * 25) / 100; break;
      case FrontierKind::Mountain: m += (qramp(L(-3000 * M), 0, d) * 15) / 100; break;
    }
  }
  uint64_t s = layer_seed(p_.seed, Layer::Moisture);
  m += (fbm2(s, to_noise(x, L(4000 * M)), to_noise(z, L(4000 * M)), 3) * 15) / 100;
  return clamp64(m, kOne / 20, kOne * 13 / 10);
}

}  // namespace em::plan
