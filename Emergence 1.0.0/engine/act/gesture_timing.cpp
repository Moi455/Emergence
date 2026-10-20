#include "gesture_timing.h"

#include <algorithm>

#include "emergence/social/vocab_gen.h"

namespace em::act {
namespace {

using social::gen::ParamType;

constexpr bool names_match() {
  for (std::size_t i = 0; i < social::gen::kGestureNames.size(); ++i)
    if (social::gen::kGestureNames[i] != timing_gen::kGestureTiming[i].id) return false;
  return true;
}
static_assert(timing_gen::kGestureTiming.size() == social::gen::kGestureNames.size());
static_assert(names_match(), "gesture_timing_gen.h is out of step with the gesture registry: run catalogue/tools/gen_act_timing.py");

std::array<GestureTiming, social::gen::kGestures.size()> build_table() {
  std::array<GestureTiming, social::gen::kGestures.size()> t{};
  for (std::size_t i = 0; i < t.size(); ++i) {
    const auto& row = timing_gen::kGestureTiming[i];
    const auto& spec = social::gen::kGestures[i];
    t[i].natural_end = row.natural_end;
    t[i].productive = row.productive;
    t[i].cadence_ms = row.cadence_ms;
    t[i].family = spec.family;
    for (int p = 0; p < spec.n_params; ++p) {
      const auto& ps = spec.params[static_cast<std::size_t>(p)];
      if (ps.type == ParamType::condition) t[i].has_until = true;
      if (ps.name == "duration" || ps.name == "thoroughness" || ps.type == ParamType::duration) t[i].has_duration = true;
      if (ps.name == "amount") t[i].has_amount = true;
    }
  }
  return t;
}

}  // namespace

const GestureTiming& timing_of(Gesture g) {
  static const auto table = build_table();
  return table[static_cast<std::size_t>(g)];
}

int param_index(Gesture g, std::string_view name) {
  const auto& spec = social::gen::kGestures[static_cast<std::size_t>(g)];
  for (int p = 0; p < spec.n_params; ++p)
    if (spec.params[static_cast<std::size_t>(p)].name == name) return p;
  return -1;
}

std::int64_t duration_level_game_s(int level) {
  const int n = static_cast<int>(timing_gen::kDurationLevels.size());
  return timing_gen::kDurationLevels[static_cast<std::size_t>(std::clamp(level, 0, n - 1))].game_s;
}

IngestTable::IngestTable(const MatterCatalog& catalog) {
  nutrition_.assign(social::gen::kKinds.size(), 0);
  hydration_.assign(social::gen::kKinds.size(), 0);
  for (const auto& row : timing_gen::kIngestibles) {
    const std::uint16_t sort = catalog.find_item(row.id);
    if (sort == 0 || sort >= nutrition_.size()) continue;
    nutrition_[sort] = static_cast<std::int8_t>(row.nutrition);
    hydration_[sort] = static_cast<std::int8_t>(row.hydration);
  }
}

Manner manner_of(Gesture g, int v) {
  switch (g) {
    case Gesture::strike: return Manner::Strike;
    case Gesture::push: case Gesture::pull: case Gesture::grab: case Gesture::touch: case Gesture::examine:
    case Gesture::search: case Gesture::blow: return Manner::Press;
    case Gesture::work:   // press, rub, stir, squeeze, saw, twist
      switch (v) {
        case 1: return Manner::Rub;
        case 4: return Manner::Slice;
        case 5: return Manner::Turn;
        default: return Manner::Press;
      }
    case Gesture::tie:    // knot, lash, sew, bind
      return (v == 2 || v == 3) ? Manner::Join : Manner::Lash;
    case Gesture::shape: return Manner::Carve;
    case Gesture::channel:   // assemble, disassemble, mend, shape
      switch (v) {
        case 1: return Manner::Strike;
        case 3: return Manner::Carve;
        default: return Manner::Join;
      }
    case Gesture::scoop: return Manner::Dig;
    case Gesture::operate: return Manner::Turn;
    default: return Manner::Press;
  }
}

}  // namespace em::act
