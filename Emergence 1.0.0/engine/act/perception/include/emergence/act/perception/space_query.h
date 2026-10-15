// SpaceQuery: what the perception needs to know about the SPACE between an observer and what it looks at: is the view
// blocked, does the sound pass, how bright is it, is it a room. The voxel world answers these questions (occupancy grid
// of 32 cm, docs/14 section 4.8, 6.1); it is entrusted to another team, so the perception depends only on this
// interface. FlatSpace is the simple implementation for tests and benches (a flat grid), NOT a voxel code.
//
// Conventions: positions are millimetres (em::act::Position), x and y horizontal, z up. A query is const, pure and
// deterministic (no clock, no random source); it may be called from several threads at once.
#pragma once
#include <cstdint>
#include <unordered_map>
#include <vector>

#include "emergence/act/entity_ops.h"
#include "emergence/social/state_types.h"

namespace em::act::perception {

using em::act::Position;
using em::social::GameTime;

class SpaceQuery {
 public:
  virtual ~SpaceQuery() = default;
  // Share (per-mille) of the view that stays clear on the line `eye` -> `target`: 1000 = clear, 0 = fully hidden
  // (a wall, a crate, a hedge in between). Leaves are partial. The cells where the two points stand do not count.
  virtual std::uint16_t sight_transmission(const Position& eye, const Position& target) const = 0;
  // Share (per-mille) of a sound made at `source` that reaches `listener` (walls and doors muffle it).
  virtual std::uint16_t sound_transmission(const Position& source, const Position& listener) const = 0;
  // Light at a point, 0 (dark) to 100 (full day), tenths of the charter scale, at the game time `now`.
  virtual std::int16_t light_at(const Position& p, GameTime now) const = 0;
  // Ambient noise (crowd, forge, rain, river) at a point, 0..100: it covers voices and steps.
  virtual std::int16_t ambient_noise_at(const Position& p) const = 0;
  virtual bool indoors(const Position& p) const = 0;
  // Fog or mist between the observer and what it sees, per-mille (0 = clear air).
  virtual std::uint16_t fog_permille(const Position& p) const = 0;
};

// A flat grid of square cells (default 1 m). Each cell may hold a cover (opacity and sound block, per-mille), a roof, a
// light override or a noise level. Daylight follows the world clock (clock.h): full by day, dusk and dawn over 5 real
// minutes, 12 % by night.
class FlatSpace final : public SpaceQuery {
 public:
  explicit FlatSpace(std::int32_t cell_mm = 1000) : cell_(cell_mm) {}

  struct Cell {
    std::uint16_t opacity = 0;       // 0 clear .. 1000 opaque
    std::uint16_t sound_block = 0;   // 0 open .. 1000 mute
    bool roof = false;
    std::int16_t light = -1;         // -1 = daylight of the clock, else a fixed level
    std::int16_t noise = 0;
  };
  Cell& cell_at(std::int32_t cx, std::int32_t cy) { return cells_[key(cx, cy)]; }
  // A solid block of cells [x0..x1] x [y0..y1] (cell coordinates).
  void block(std::int32_t x0, std::int32_t y0, std::int32_t x1, std::int32_t y1, std::uint16_t opacity = 1000, std::uint16_t sound_block = 700);
  void roof(std::int32_t x0, std::int32_t y0, std::int32_t x1, std::int32_t y1, std::int16_t light = 40);
  void set_fog(std::uint16_t permille) { fog_ = permille; }
  void set_global_noise(std::int16_t n) { noise_ = n; }
  std::int32_t cell_of(std::int32_t mm) const { return mm >= 0 ? mm / cell_ : -((-mm + cell_ - 1) / cell_); }

  std::uint16_t sight_transmission(const Position& eye, const Position& target) const override { return ray(eye, target, true); }
  std::uint16_t sound_transmission(const Position& source, const Position& listener) const override { return ray(source, listener, false); }
  std::int16_t light_at(const Position& p, GameTime now) const override;
  std::int16_t ambient_noise_at(const Position& p) const override;
  bool indoors(const Position& p) const override;
  std::uint16_t fog_permille(const Position&) const override { return fog_; }

  // Daylight of the world clock at `now`, 0..100.
  static std::int16_t daylight(GameTime now);

 private:
  static std::uint64_t key(std::int32_t cx, std::int32_t cy) { return (std::uint64_t(std::uint32_t(cx)) << 32) | std::uint32_t(cy); }
  const Cell* find(std::int32_t cx, std::int32_t cy) const;
  std::uint16_t ray(const Position& a, const Position& b, bool sight) const;

  std::int32_t cell_;
  std::unordered_map<std::uint64_t, Cell> cells_;   // looked up by key only, never iterated (determinism)
  std::uint16_t fog_ = 0;
  std::int16_t noise_ = 0;
};

}  // namespace em::act::perception
