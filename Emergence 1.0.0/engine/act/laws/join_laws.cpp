#include <algorithm>

#include "contact_laws.h"

namespace em::act {
namespace laws_detail {
std::unique_ptr<ContactLaw> make_cut();
std::unique_ptr<ContactLaw> make_split();
std::unique_ptr<ContactLaw> make_fracture();
std::unique_ptr<ContactLaw> make_crush();
std::unique_ptr<ContactLaw> make_carve();
std::unique_ptr<ContactLaw> make_disassemble();
}  // namespace laws_detail

namespace {

constexpr std::int32_t kAbradeStrokePermille = 8;   // per stroke, before kTaskCompression and the grit bonus
constexpr std::int32_t kExtractDepthMm = 500;
constexpr std::int32_t kTillDepthMm = 250;

bool is_soil(std::uint16_t material) {
  return material != kNoMatter && material < matter::kMaterials.size() && matter::kMaterials[material].tillable;
}

// extract: a digging tool on the terrain (voxel world: delegated) or on a rooted plant (uprooted: it becomes nothing here,
// the plant is gone and the ground bare).
class ExtractLaw final : public ContactLaw {
 public:
  ProcessId process() const override { return ProcessId::Extract; }
  bool contact(const LawContext& ctx, const Contact& c, const Resolved& r, Emitter& out, LawReport& rep) const override {
    if (c.manner != Manner::Dig || !r.tool.valid() || !r.tool.aff.digs) return false;
    if (c.target == kNoEntity) {
      if (c.voxel_material >= matter::kMaterials.size()) return false;
      rep = {ProcessId::Extract, Outcome::DelegatedToVoxels, 0, {true, ProcessId::Extract, c.at, c.voxel_material, kExtractDepthMm}};
      return true;
    }
    if (!r.target.valid() || out.touched(r.target.id)) return false;
    if (r.target.kind == gen::EntityKind::terrain) {
      rep = {ProcessId::Extract, Outcome::DelegatedToVoxels, 0, {true, ProcessId::Extract, r.target.pos, r.target.material, kExtractDepthMm}};
      return true;
    }
    if (r.target.kind != gen::EntityKind::plant) return false;
    (void)ctx;
    out.process(ProcessId::Extract, 3, 4);
    out.destroy(c.target);
    rep = {ProcessId::Extract, Outcome::Done, out.count(), {}};
    return true;
  }
};

// till: a digging tool on soil. The soil is voxels: the request goes to the voxel world.
class TillLaw final : public ContactLaw {
 public:
  ProcessId process() const override { return ProcessId::Till; }
  bool contact(const LawContext&, const Contact& c, const Resolved& r, Emitter&, LawReport& rep) const override {
    if (c.manner != Manner::Turn || !r.tool.valid() || !r.tool.aff.digs || c.target != kNoEntity) return false;
    if (!is_soil(c.voxel_material)) return false;
    rep = {ProcessId::Till, Outcome::DelegatedToVoxels, 0, {true, ProcessId::Till, c.at, c.voxel_material, kTillDepthMm}};
    return true;
  }
};

// assemble: a graspable piece is set on top of another; the stability of the whole then follows from the supports.
class AssembleLaw final : public ContactLaw {
 public:
  ProcessId process() const override { return ProcessId::Assemble; }
  bool contact(const LawContext& ctx, const Contact& c, const Resolved& r, Emitter& out, LawReport& rep) const override {
    if (c.manner != Manner::Join || !r.target.valid() || !r.other.valid() || c.target == c.other) return false;
    if (out.touched(c.target) || out.touched(c.other) || !r.other.aff.graspable) return false;
    for (const Facet* f : {&r.target, &r.other})
      if (f->cohesion == Cohesion::fluid || f->cohesion == Cohesion::loose) return false;
    Body base = ctx.resolver.body(c.target), piece = ctx.resolver.body(c.other);
    if (!base.profile || !piece.profile) return false;
    Position to{base.pos[0], base.top(), base.pos[2]};
    if (ctx.store.holder(c.other) == kNoEntity && piece.pos == to) return false;   // already there
    out.process(ProcessId::Assemble, 3, 4);
    out.move(c.other, to);
    rep = {ProcessId::Assemble, Outcome::Done, out.count(), {}};
    return true;
  }
};

// bind: a lashing (binds) around two things. The thing lashed is carried by the other; the cord is used up. It holds
// while the weight does not exceed the toughness of the cord times its mass; else it snaps and the cord is lost.
class BindLaw final : public ContactLaw {
 public:
  ProcessId process() const override { return ProcessId::Bind; }
  bool contact(const LawContext& ctx, const Contact& c, const Resolved& r, Emitter& out, LawReport& rep) const override {
    if (c.manner != Manner::Lash || !r.tool.valid() || !r.tool.aff.binds || !r.target.valid() || !r.other.valid()) return false;
    if (c.target == c.other || c.tool == c.other || c.tool == c.target || out.touched(c.target) || out.touched(c.other) || out.touched(c.tool)) return false;
    if (ctx.store.holder(c.target) == c.other) return false;   // would make a cycle
    std::int64_t capacity_g = static_cast<std::int64_t>(r.tool.profile->binds_toughness) * r.tool.mass_g;
    out.process(ProcessId::Bind, 1, 3);
    out.destroy(c.tool);
    if (r.other.mass_g > capacity_g) {
      rep = {ProcessId::Bind, Outcome::Snapped, out.count(), {}};
      return true;
    }
    out.move(c.other, r.target.pos, c.target);
    rep = {ProcessId::Bind, Outcome::Done, out.count(), {}};
    return true;
  }
};

// abrade: a thing that sharpens (abrasive face harder than the target) rubbed on another: work accumulates in the
// transformation of the target; the grit above the target's hardness works faster.
class AbradeLaw final : public ContactLaw {
 public:
  ProcessId process() const override { return ProcessId::Abrade; }
  bool contact(const LawContext& ctx, const Contact& c, const Resolved& r, Emitter& out, LawReport& rep) const override {
    if (c.manner != Manner::Rub || !r.tool.valid() || !r.tool.aff.sharpens || !r.target.valid() || out.touched(c.target)) return false;
    // A stone's hardness is that of its mass; its quartz grains bite harder: the grit counts double.
    std::int32_t grit = 2 * r.tool.profile->abrasive_hardness;
    if (grit < r.target.hardness) return false;
    const auto* tr = ctx.store.component<gen::Transformation>(c.target);
    if (!tr || ctx.vars.process_progress == 0xFFFF) return false;
    std::int32_t bonus = std::clamp(1 + (grit - r.target.hardness) / 10, 1, 8);
    std::int32_t gain = compressed_work(kAbradeStrokePermille * bonus, c.productive);
    std::int32_t now = tr->process_progress, to = std::min(1000, now + gain);
    out.process(ProcessId::Abrade, 2, 2);
    if (to >= 1000) {
      out.delta(c.target, ctx.vars.process_progress, now, 0);
      rep = {ProcessId::Abrade, Outcome::Done, out.count(), {}};
    } else {
      out.delta(c.target, ctx.vars.process_progress, now, to);
      rep = {ProcessId::Abrade, Outcome::Progress, out.count(), {}};
    }
    return true;
  }
};

}  // namespace

std::vector<std::unique_ptr<ContactLaw>> make_contact_laws() {
  std::vector<std::unique_ptr<ContactLaw>> v;
  v.push_back(laws_detail::make_disassemble());
  v.push_back(laws_detail::make_split());
  v.push_back(laws_detail::make_cut());
  v.push_back(laws_detail::make_carve());
  v.push_back(laws_detail::make_crush());
  v.push_back(laws_detail::make_fracture());
  v.push_back(std::make_unique<ExtractLaw>());
  v.push_back(std::make_unique<TillLaw>());
  v.push_back(std::make_unique<AssembleLaw>());
  v.push_back(std::make_unique<BindLaw>());
  v.push_back(std::make_unique<AbradeLaw>());
  return v;
}

}  // namespace em::act
