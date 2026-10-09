// Internal pieces of the world plan generator, shared between its .cpp files.
#pragma once
#include <array>
#include <cstdint>
#include <vector>

#include "emergence/world/world_plan.h"

namespace em::plan {

// Frontier geometry at a world position.
struct FrontierSample {
  std::array<int64_t, 4> depth_mm{};   // signed depth into each side's march
  std::array<int64_t, 4> weight_q16{}; // terrain blend weight of each side
};

class Relief {
 public:
  explicit Relief(const WorldParams& p);
  // Pre-erosion terrain height. min_wavelength_mm drops octaves finer than
  // needed for the caller's resolution (never compute beyond needed precision).
  int64_t height_mm(int64_t x_mm, int64_t z_mm, int64_t min_wavelength_mm, FrontierSample* fs) const;
  FrontierSample frontier(int64_t x_mm, int64_t z_mm) const;
  // Scales a horizontal distance given for the 20 km map.
  int64_t L(int64_t mm) const { return (mm * scale_q16_) >> 16; }
  int64_t moisture_q16(int64_t x_mm, int64_t z_mm, const FrontierSample& fs) const;

 private:
  int64_t side_height(FrontierKind kind, int64_t base, int64_t depth_mm, int64_t x, int64_t z,
                      int64_t min_wl) const;
  WorldParams p_;
  int64_t scale_q16_;
  int64_t size_mm_;
};

int octaves_for(int64_t wavelength_mm, int64_t min_wavelength_mm, int max_octaves);

// Erosion and hydrology (erosion.cpp).
void erode(WorldPlan& plan, const std::vector<uint16_t>& rain_q8, int iterations);
void compute_hydrology(WorldPlan& plan, const std::vector<uint16_t>& rain_q8);

// Settlements and roads (settlements.cpp).
void place_settlements(WorldPlan& plan);
void build_roads(WorldPlan& plan);

// Backdrop beyond the map (backdrop.cpp).
void build_backdrop(WorldPlan& plan, const Relief& relief);

// Slope magnitude at a cell, per mille (rise over run * 1000).
int32_t slope_permille(const WorldPlan& plan, int32_t i, int32_t j);

}  // namespace em::plan
