#include "law_kit.h"

#include <algorithm>

namespace em::act {

const char* to_string(Outcome o) {
  switch (o) {
    case Outcome::NoEffect: return "NoEffect";
    case Outcome::Done: return "Done";
    case Outcome::Progress: return "Progress";
    case Outcome::Snapped: return "Snapped";
    case Outcome::Conflict: return "Conflict";
    case Outcome::DelegatedToVoxels: return "DelegatedToVoxels";
  }
  return "?";
}

bool TouchedSet::contains(EntityId id) const { return std::binary_search(sorted_.begin(), sorted_.end(), id); }
void TouchedSet::add(EntityId id) {
  auto it = std::lower_bound(sorted_.begin(), sorted_.end(), id);
  if (it == sorted_.end() || *it != id) sorted_.insert(it, id);
}

void Emitter::push(ops::Operation op) {
  op.process = process_;
  op.noise = noise_;
  op.sight = sight_;
  out_.push_back({std::move(op), seq_, k_++});
  ++emitted_;
}
void Emitter::spawn(gen::EntityKind kind, const Position& pos, std::uint16_t sort, EntityId holder) {
  push(make_spawn(tick_, author_, static_cast<std::uint16_t>(kind), pos, holder, sort));
}
void Emitter::destroy(EntityId id) { touched_.add(id); push(make_destroy(tick_, author_, id)); }
void Emitter::move(EntityId id, const Position& to, EntityId holder) { touched_.add(id); push(make_move(tick_, author_, id, to, holder)); }
void Emitter::delta(EntityId id, std::uint16_t var, std::int32_t o, std::int32_t n) { touched_.add(id); push(make_delta(tick_, author_, id, var, o, n)); }

LawVars::LawVars() : load_margin(0xFFFF), visible_damage(0xFFFF), process_progress(0xFFFF) {
  for (const auto& f : gen::kStructureFields) {
    if (f.name == "load_margin") load_margin = f.var;
    else if (f.name == "visible_damage") visible_damage = f.var;
    else if (f.name == "process_progress") process_progress = f.var;
  }
}

std::int32_t clamp_count(std::int64_t v, std::int32_t lo, std::int32_t hi) {
  return static_cast<std::int32_t>(std::clamp<std::int64_t>(v, lo, hi));
}

Position spread_position(const Body& b, std::int32_t i, std::int32_t n) {
  Position p = b.pos;
  std::int64_t off = std::int64_t{2 * i + 1 - n} * (std::max(b.ext.x, b.ext.z)) / (2 * n);
  auto sat = [](std::int64_t v) { return static_cast<std::int32_t>(std::clamp<std::int64_t>(v, INT32_MIN, INT32_MAX)); };
  if (b.ext.x >= b.ext.z) p[0] = sat(std::int64_t{p[0]} + off); else p[2] = sat(std::int64_t{p[2]} + off);
  return p;
}

void spawn_pieces(Emitter& out, const Body& from, std::uint16_t sort, std::int32_t n) {
  for (std::int32_t i = 0; i < n; ++i) out.spawn(gen::EntityKind::item, spread_position(from, i, n), sort);
}

bool consumes_material(ProcessId p, std::uint16_t material) {
  const auto& row = MatterCatalog::process(p);
  for (std::uint8_t i = 0; i < row.n_consumes; ++i) if (row.consumes[i] == material) return true;
  return false;
}

}  // namespace em::act
