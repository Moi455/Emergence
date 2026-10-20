// ResolverFrame (T22): THE adapter between the frame of the executor and the frame of the laws of matter.
//
// ONE convention outside T18: z UP, x and y horizontal (the frame of the perception's SpaceQuery, of the navigation and of the
// executor; positions in the EntityStore are in that frame). ContactResolver, ProcessEngine and their laws (T18) work with y UP
// (horizontal x and z, ground_at(x, z), pos[1] = height). They are NOT rewritten: everything that crosses the boundary is
// converted here, by swapping the axes y <-> z.
//   * The resolver reads positions in the entity store, so it is given a MIRROR store (store()), kept in step by this class as
//     an Applier of the bus (register it AFTER the EntityStore, before anything else that needs it): every Spawn and Move is
//     replayed with y and z swapped, every other operation as it is. Same operation stream, same ids.
//   * Contacts go to the resolver through to_resolver(); the emissions that come back go to the world through to_world().
//   * A ground given in the executor's frame (HeightField: height at x, y) becomes a GroundModel through ZUpGround.
// The mirror doubles the entity memory: acceptable for the 500 NPC village, to be revisited (T18b) if the resolver learns a frame.
#pragma once
#include <vector>

#include "contact_resolver.h"
#include "emergence/act/entity_store.h"
#include "emergence/ops/applier.h"
#include "laws/law_kit.h"

namespace em::act {

inline Position swap_yz(const Position& p) { return {p[0], p[2], p[1]}; }

// The ground in the executor's frame: height (z, mm) at the horizontal point (x, y).
class HeightField {
 public:
  virtual ~HeightField() = default;
  virtual std::int32_t height_mm(std::int32_t x, std::int32_t y) const = 0;
};

// A GroundModel (resolver frame) over a HeightField (executor frame).
class ZUpGround final : public GroundModel {
 public:
  explicit ZUpGround(const HeightField& h) : h_(h) {}
  std::int32_t height_mm(std::int32_t x, std::int32_t z_resolver) const override { return h_.height_mm(x, z_resolver); }

 private:
  const HeightField& h_;
};

class ResolverFrame final : public ops::Applier {
 public:
  std::string_view name() const override { return "ResolverFrame"; }
  ops::ApplyStatus apply(const ops::Operation& op) override;

  // The store the ContactResolver / ProcessEngine must be built on.
  const EntityStore& store() const { return mirror_; }

  static Contact to_resolver(Contact c);
  static Emission to_world(Emission e);
  static std::vector<Contact> to_resolver(const std::vector<Contact>& cs);
  static std::vector<Emission> to_world(std::vector<Emission> es);

 private:
  EntityStore mirror_;
};

}  // namespace em::act
