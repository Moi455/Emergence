// Integer hashing used for every random draw in world generation.
// Never use rand() or <random> distributions: they differ across platforms.
#pragma once
#include <cstdint>

namespace em {

// splitmix64 finalizer: good avalanche, cheap, identical everywhere.
constexpr uint64_t mix64(uint64_t x) {
  x ^= x >> 30;
  x *= 0xbf58476d1ce4e5b9ULL;
  x ^= x >> 27;
  x *= 0x94d049bb133111ebULL;
  x ^= x >> 31;
  return x;
}

constexpr uint64_t hash_combine(uint64_t h, uint64_t v) {
  return mix64(h ^ (v * 0x9e3779b97f4a7c15ULL + 0x632be59bd9b4e019ULL));
}

constexpr uint64_t hash2(uint64_t seed, int64_t x, int64_t y) {
  return hash_combine(hash_combine(seed, static_cast<uint64_t>(x)), static_cast<uint64_t>(y));
}

constexpr uint64_t hash3(uint64_t seed, int64_t x, int64_t y, int64_t z) {
  return hash_combine(hash2(seed, x, y), static_cast<uint64_t>(z));
}

// Each generation layer derives its own seed so that adding a layer never
// shifts the draws of another one.
enum class Layer : uint64_t {
  Frontier = 1, CoreRelief, Mountain, Desert, Forest, Sea, Moisture, Geology,
  Snowline, Detail, Backdrop, Biome, Strata,
};

constexpr uint64_t layer_seed(uint64_t world_seed, Layer layer) {
  return hash_combine(mix64(world_seed), static_cast<uint64_t>(layer) * 0xd6e8feb86659fd93ULL);
}

}  // namespace em
