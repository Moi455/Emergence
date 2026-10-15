#include <algorithm>

#include "contact_laws.h"

namespace em::act {
namespace {

constexpr std::int32_t kMaxPieces = 6;
constexpr std::int32_t kSplitEnergyDivisor = 32;     // a split along the grain needs 1/32 of the break energy
constexpr std::int32_t kJointEnergyDivisor = 8;      // a joint gives way at 1/8 of the break energy
constexpr std::int32_t kCrushEnergyDivisor = 4;
constexpr std::int32_t kCarveStrokePermille = 25;    // per stroke, before kTaskCompression

bool manner_is(const Contact& c, Manner m) { return c.manner == m; }

// Common precondition: a living, described target that no other law changed in this step.
bool usable_target(const Resolved& r, const Emitter& out) { return r.target.valid() && !out.touched(r.target.id); }

class CutLaw final : public ContactLaw {
 public:
  ProcessId process() const override { return ProcessId::Cut; }
  bool contact(const LawContext& ctx, const Contact& c, const Resolved& r, Emitter& out, LawReport& rep) const override {
    if (!manner_is(c, Manner::Slice) || !usable_target(r, out) || !r.tool.valid() || !r.tool.aff.cuts) return false;
    // "matière tendre": softer than the edge, and not a fluid.
    if (r.target.hardness > kTenderMaxHardness || r.tool.profile->edge_hardness <= r.target.hardness) return false;
    if (r.target.cohesion == Cohesion::fluid || r.target.material == kNoMatter) return false;
    Body b = ctx.resolver.body(c.target);
    std::uint16_t piece = ctx.catalog.piece_item(r.target.material, ProcessId::Cut, b.profile->mass_g);
    if (!piece) return false;
    const Profile* pp = ctx.catalog.profile(gen::EntityKind::item, piece);
    std::int32_t n = clamp_count(b.profile->mass_g / std::max(pp->mass_g, 1), 2, 4);
    out.process(ProcessId::Cut, 2, 4);
    out.destroy(c.target);
    spawn_pieces(out, b, piece, n);
    rep = {ProcessId::Cut, Outcome::Done, out.count(), {}};
    return true;
  }
};

class SplitLaw final : public ContactLaw {
 public:
  ProcessId process() const override { return ProcessId::Split; }
  bool contact(const LawContext& ctx, const Contact& c, const Resolved& r, Emitter& out, LawReport& rep) const override {
    if (!manner_is(c, Manner::Strike) || !usable_target(r, out) || !r.tool.valid()) return false;
    if (!(r.tool.profile->flags & matter::kFormEdge) || !r.tool.aff.impacts) return false;
    if (!consumes_material(ProcessId::Split, r.target.material)) return false;
    if (r.energy_mj * kSplitEnergyDivisor < r.target.break_mj) return false;
    const auto& row = MatterCatalog::process(ProcessId::Split);
    std::uint16_t piece = row.n_produces ? ctx.catalog.item_of_material(row.produces[0]) : 0;
    if (!piece) return false;
    Body b = ctx.resolver.body(c.target);
    const Profile* pp = ctx.catalog.profile(gen::EntityKind::item, piece);
    std::int32_t n = clamp_count(b.profile->mass_g / std::max(pp->mass_g, 1), 2, kMaxPieces);
    out.process(ProcessId::Split, 5, 5);
    out.destroy(c.target);
    spawn_pieces(out, b, piece, n);
    rep = {ProcessId::Split, Outcome::Done, out.count(), {}};
    return true;
  }
};

class FractureLaw final : public ContactLaw {
 public:
  ProcessId process() const override { return ProcessId::Fracture; }
  bool contact(const LawContext& ctx, const Contact& c, const Resolved& r, Emitter& out, LawReport& rep) const override {
    if ((!manner_is(c, Manner::Strike) && !manner_is(c, Manner::Press)) || !usable_target(r, out) || !r.tool.valid()) return false;
    if (r.target.break_mj <= 0) return false;
    Body b = ctx.resolver.body(c.target);
    if (r.energy_mj > r.target.break_mj) {
      shatter(ctx, b, out, ProcessId::Fracture);
      rep = {ProcessId::Fracture, Outcome::Done, out.count(), {}};
      return true;
    }
    // Not enough: the integrity falls (only a structure keeps one; the sheet of an object has none yet).
    if (b.kind == gen::EntityKind::structure && ctx.vars.visible_damage != 0xFFFF) {
      const auto* st = ctx.store.component<gen::Stability>(c.target);
      std::int32_t add = static_cast<std::int32_t>(r.energy_mj * 100 / r.target.break_mj);
      std::int32_t now = st ? st->visible_damage : 0;
      std::int32_t to = std::min(100, now + add);
      if (add > 0 && to != now) {
        out.process(ProcessId::Fracture, 3, 4);
        out.delta(c.target, ctx.vars.visible_damage, now, to);
        rep = {ProcessId::Fracture, Outcome::Progress, out.count(), {}};
        return true;
      }
    }
    return false;
  }
};

class CrushLaw final : public ContactLaw {
 public:
  ProcessId process() const override { return ProcessId::Crush; }
  bool contact(const LawContext& ctx, const Contact& c, const Resolved& r, Emitter& out, LawReport& rep) const override {
    if ((!manner_is(c, Manner::Strike) && !manner_is(c, Manner::Press)) || !usable_target(r, out) || !r.tool.valid()) return false;
    if (!r.tool.aff.impacts || !consumes_material(ProcessId::Crush, r.target.material)) return false;
    if (r.energy_mj * kCrushEnergyDivisor < r.target.break_mj) return false;
    const auto& row = MatterCatalog::process(ProcessId::Crush);
    std::uint16_t product = row.n_produces ? ctx.catalog.item_of_material(row.produces[0]) : 0;
    if (!product) return false;
    Body b = ctx.resolver.body(c.target);
    const Profile* pp = ctx.catalog.profile(gen::EntityKind::item, product);
    // Mass is kept: as many products as the target weighs in products (at least one).
    std::int32_t n = clamp_count(b.profile->mass_g / std::max(pp->mass_g, 1), 1, 8);
    out.process(ProcessId::Crush, 4, 3);
    out.destroy(c.target);
    spawn_pieces(out, b, product, n);
    rep = {ProcessId::Crush, Outcome::Done, out.count(), {}};
    return true;
  }
};

class CarveLaw final : public ContactLaw {
 public:
  ProcessId process() const override { return ProcessId::Carve; }
  bool contact(const LawContext& ctx, const Contact& c, const Resolved& r, Emitter& out, LawReport& rep) const override {
    if (!manner_is(c, Manner::Carve) || !usable_target(r, out) || !r.tool.valid() || !r.tool.aff.cuts) return false;
    if (r.tool.profile->edge_hardness <= r.target.hardness) return false;
    if (r.target.cohesion == Cohesion::fluid || r.target.cohesion == Cohesion::loose) return false;
    const auto* tr = ctx.store.component<gen::Transformation>(c.target);
    if (!tr || ctx.vars.process_progress == 0xFFFF) return false;
    std::int32_t now = tr->process_progress;
    std::int32_t gain = compressed_work(kCarveStrokePermille, c.productive);
    std::int32_t to = std::min(1000, now + gain);
    out.process(ProcessId::Carve, 2, 3);
    if (to >= 1000) {
      out.delta(c.target, ctx.vars.process_progress, now, 0);   // the shape is done: the progress restarts
      rep = {ProcessId::Carve, Outcome::Done, out.count(), {}};
    } else {
      out.delta(c.target, ctx.vars.process_progress, now, to);
      rep = {ProcessId::Carve, Outcome::Progress, out.count(), {}};
    }
    return true;
  }
};

class DisassembleLaw final : public ContactLaw {
 public:
  ProcessId process() const override { return ProcessId::Disassemble; }
  bool contact(const LawContext& ctx, const Contact& c, const Resolved& r, Emitter& out, LawReport& rep) const override {
    if (!manner_is(c, Manner::Strike) || !c.at_joint || !usable_target(r, out) || !r.tool.valid() || !r.tool.aff.impacts) return false;
    if (r.target.cohesion != Cohesion::built || r.target.profile->parts.size() < 2) return false;   // natural: it only fractures
    if (r.energy_mj * kJointEnergyDivisor < r.target.break_mj) return false;
    Body b = ctx.resolver.body(c.target);
    std::vector<std::uint16_t> elements;
    for (const Part& part : r.target.profile->parts) {
      // Exact element always; the same material alone only for the materials the process hands back (planks, bricks).
      std::uint16_t s = ctx.catalog.element_item(part, false);
      if (!s && consumes_material(ProcessId::Disassemble, part.material)) s = ctx.catalog.element_item(part, true);
      if (s) elements.push_back(s);
    }
    if (elements.empty()) return false;
    out.process(ProcessId::Disassemble, 6, 5);
    out.destroy(c.target);
    std::int32_t n = static_cast<std::int32_t>(elements.size());
    for (std::int32_t i = 0; i < n; ++i) out.spawn(gen::EntityKind::item, spread_position(b, i, n), elements[static_cast<std::size_t>(i)]);
    rep = {ProcessId::Disassemble, Outcome::Done, out.count(), {}};
    return true;
  }
};

}  // namespace

std::uint32_t shatter(const LawContext& ctx, const Body& b, Emitter& out, ProcessId by) {
  const auto& row = MatterCatalog::process(by == ProcessId::Collapse ? ProcessId::Collapse : ProcessId::Fracture);
  std::uint16_t debris = row.n_produces ? ctx.catalog.item_of_material(row.produces[0]) : 0;
  out.process(by, 6, 5);
  out.destroy(b.id);
  std::uint32_t before = out.count();
  if (debris) {
    const Profile* dp = ctx.catalog.profile(gen::EntityKind::item, debris);
    std::int32_t n = clamp_count(b.profile->mass_g / std::max(dp->mass_g, 1), 1, kMaxPieces);
    spawn_pieces(out, b, debris, n);
  }
  return out.count() - before;
}

std::vector<std::unique_ptr<ContactLaw>> make_contact_laws();   // defined in join_laws.cpp

namespace laws_detail {
std::unique_ptr<ContactLaw> make_cut() { return std::make_unique<CutLaw>(); }
std::unique_ptr<ContactLaw> make_split() { return std::make_unique<SplitLaw>(); }
std::unique_ptr<ContactLaw> make_fracture() { return std::make_unique<FractureLaw>(); }
std::unique_ptr<ContactLaw> make_crush() { return std::make_unique<CrushLaw>(); }
std::unique_ptr<ContactLaw> make_carve() { return std::make_unique<CarveLaw>(); }
std::unique_ptr<ContactLaw> make_disassemble() { return std::make_unique<DisassembleLaw>(); }
}  // namespace laws_detail

}  // namespace em::act
