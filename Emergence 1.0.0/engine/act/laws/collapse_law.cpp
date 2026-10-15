#include "collapse_law.h"

#include <algorithm>

#include "contact_laws.h"

namespace em::act {

TickReport CollapseLaw::run(const LawContext& ctx, Emitter& out) const {
  TickReport rep;
  SupportMap map = ctx.resolver.support_map();
  rep.bodies = static_cast<std::uint32_t>(map.bodies.size());
  const auto& row = MatterCatalog::process(ProcessId::Collapse);
  std::uint16_t debris = row.n_produces ? ctx.catalog.item_of_material(row.produces[0]) : 0;
  std::vector<std::uint8_t> gone(map.bodies.size(), 0);

  // 1. margins and collapses (structures), in id order.
  for (std::size_t i = 0; i < map.bodies.size(); ++i) {
    const Body& b = map.bodies[i];
    if (b.kind != gen::EntityKind::structure) continue;
    std::int32_t margin = map.margin_permille[i];
    if (margin <= 0) {
      out.process(ProcessId::Collapse, 9, 7);
      out.destroy(b.id);
      if (debris) {
        const Profile* dp = ctx.catalog.profile(gen::EntityKind::item, debris);
        std::int32_t n = clamp_count(b.profile->mass_g / std::max(dp->mass_g, 1), 1, 8);
        spawn_pieces(out, b, debris, n);
      }
      gone[i] = 1;
      ++rep.collapsed;
      continue;
    }
    const auto* st = ctx.store.component<gen::Stability>(b.id);
    if (st && st->load_margin != margin && ctx.vars.load_margin != 0xFFFF) {
      out.process(ProcessId::Collapse, 0, 0);
      out.delta(b.id, ctx.vars.load_margin, st->load_margin, margin);
      ++rep.margins_written;
    }
  }

  // 2. what rests on nothing falls.
  for (std::size_t i = 0; i < map.bodies.size(); ++i) {
    const Body& b = map.bodies[i];
    if (gone[i] || !map.unsupported(i) || out.touched(b.id)) continue;
    std::int32_t land = ctx.resolver.landing_mm(map, i);
    std::int64_t h = std::int64_t{b.pos[1]} - land;
    if (h <= kSupportToleranceMm) continue;
    std::int64_t energy = ContactResolver::fall_energy_mj(b.profile->mass_g, h);
    std::int64_t brk = ContactResolver::break_energy_mj(*b.profile);
    if (brk > 0 && energy > brk) {
      Body landed = b;
      landed.pos[1] = land;
      shatter(ctx, landed, out, ProcessId::Collapse);
      ++rep.shattered;
      ++rep.fell;
      continue;
    }
    out.process(ProcessId::Collapse, 4, 5);
    out.move(b.id, {b.pos[0], land, b.pos[2]});
    ++rep.fell;
    if (b.kind == gen::EntityKind::structure && brk > 0 && ctx.vars.visible_damage != 0xFFFF) {
      const auto* st = ctx.store.component<gen::Stability>(b.id);
      std::int32_t add = static_cast<std::int32_t>(energy * 100 / brk);
      std::int32_t now = st ? st->visible_damage : 0;
      if (add > 0 && now < 100) out.delta(b.id, ctx.vars.visible_damage, now, std::min(100, now + add));
    }
  }
  return rep;
}

}  // namespace em::act
