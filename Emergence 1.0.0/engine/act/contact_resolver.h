// ContactResolver (T18, docs/14 section 4.5): which entities touch, and with which PROPERTIES. It reads what a thing
// can do (cuts, impacts, digs, binds, sharpens, graspable) from its parts and its mass, never the name of the gesture or
// of the tool: an object nobody has seen acts through its properties (P28). It only reads the EntityStore.
//
// Geometry: positions are millimetres, y is up, the position is the centre of the BASE of the entity, the size comes
// from its Profile. A body rests on another when its base is within kSupportToleranceMm of the other's top and their
// footprints overlap; it rests on the ground when its base is within the tolerance of GroundModel::height_mm (the voxel
// world will implement it; FlatGround is the default). Iteration is by slot order and every sort is by id: the result
// never depends on a thread, an address or a hash order.
#pragma once
#include <algorithm>
#include <cstdint>
#include <climits>
#include <span>
#include <vector>

#include "emergence/act/entity_store.h"
#include "matter_catalog.h"

namespace em::act {

inline constexpr std::int32_t kSupportToleranceMm = 20;
inline constexpr std::int32_t kMinImpactMassG = 300;       // a thing lighter than this does not "hit hard"
inline constexpr std::int32_t kMinDiggerMassG = 500;
inline constexpr std::int32_t kMaxGraspMassG = 25000;
inline constexpr std::int32_t kMaxGraspSizeMm = 1500;
inline constexpr std::int32_t kTenderMaxHardness = 35;     // "matière tendre" of the process cut (hardness 0..100)
// Calibrations (to be measured against the voxel world, docs/14): break energy = toughness x cross-section (cm2) x 8 mJ;
// bearing capacity = toughness x footprint (cm2) x 50 g.
inline constexpr std::int64_t kBreakMjPerToughnessCm2 = 8;
inline constexpr std::int64_t kCapacityGPerToughnessCm2 = 50;

class GroundModel {
 public:
  virtual ~GroundModel() = default;
  virtual std::int32_t height_mm(std::int32_t x, std::int32_t z) const = 0;
};
class FlatGround final : public GroundModel {
 public:
  explicit FlatGround(std::int32_t h = 0) : h_(h) {}
  std::int32_t height_mm(std::int32_t, std::int32_t) const override { return h_; }
 private:
  std::int32_t h_;
};

// How the contact is made (the "manière" of the gesture), not who or what makes it.
enum class Manner : std::uint8_t { Strike, Slice, Carve, Press, Rub, Dig, Turn, Join, Lash };

struct Contact {
  std::uint32_t author = 0;          // the acting entity (0 = law of the world)
  std::uint32_t decision_seq = 0;    // the author's own counter (total order of the bus)
  EntityId tool = kNoEntity;         // what is held and applied (0 = bare hands)
  EntityId target = kNoEntity;       // what is touched
  EntityId other = kNoEntity;        // second thing of a Join or a Lash
  Manner manner = Manner::Strike;
  std::int32_t speed_mm_s = 0;       // speed of the tool at contact (strike)
  bool at_joint = false;             // the blow is aimed at the joints of a built thing
  bool productive = false;           // the gesture is productive: kTaskCompression applies to its work (P37)
  Position at{};                     // where, when the target is not an entity (voxel world)
  std::uint16_t voxel_material = kNoMatter;   // material of the voxel touched when target == 0
};

struct Affordances {
  bool cuts = false, impacts = false, digs = false, binds = false, sharpens = false, graspable = false;
};

// What the resolver knows about one thing in a contact.
struct Facet {
  EntityId id = kNoEntity;
  gen::EntityKind kind = gen::EntityKind::kCount;
  std::uint16_t sort = 0;
  const Profile* profile = nullptr;
  Position pos{};
  std::uint16_t material = kNoMatter;
  std::int32_t mass_g = 0;
  std::int32_t hardness = 0, toughness = 0;
  Cohesion cohesion = Cohesion::natural;
  std::int64_t break_mj = 0;         // energy needed to break it
  Affordances aff{};
  bool valid() const { return profile != nullptr; }
};

struct Resolved {
  Facet tool, target, other;
  std::int64_t energy_mj = 0;        // kinetic energy of the tool at contact (millijoules)
};

struct Body {
  EntityId id = kNoEntity;
  gen::EntityKind kind = gen::EntityKind::kCount;
  std::uint16_t sort = 0;
  Position pos{};                    // centre of the base
  Extent ext{};
  const Profile* profile = nullptr;
  std::int32_t top() const { return static_cast<std::int32_t>(std::clamp<std::int64_t>(std::int64_t{pos[1]} + ext.y, INT32_MIN, INT32_MAX)); }
};

struct TouchPair {                   // a rests on b (a above b), or they overlap
  EntityId upper, lower;
};

// Result of one pass over the world: the bodies in slot order, what each rests on, the load each carries.
struct SupportMap {
  std::vector<Body> bodies;                           // slot order
  std::vector<std::vector<std::uint32_t>> below;      // indices into bodies, ascending id
  std::vector<std::uint8_t> on_ground;
  std::vector<std::int64_t> load_above_g;             // mass carried by body i, transitive, shared among supporters
  std::vector<std::int32_t> margin_permille;          // 1000 = nothing carried; <= 0 = overloaded
  std::vector<std::pair<std::uint64_t, std::uint32_t>> grid;   // (cell, body), sorted
  std::int32_t index_of(EntityId id) const;           // -1 when absent
  bool unsupported(std::size_t i) const { return !on_ground[i] && below[i].empty(); }
};

class ContactResolver {
 public:
  ContactResolver(const MatterCatalog& catalog, const EntityStore& store, const GroundModel& ground)
      : catalog_(catalog), store_(store), ground_(ground) {}

  // The facts of a contact: properties of the tool and the targets, and the energy of the blow.
  Resolved resolve(const Contact& c) const;
  Facet facet(EntityId id) const;
  Body body(EntityId id) const;                        // profile == nullptr when the entity has no sheet

  // Every body (item, structure, plant with a sheet, not held) and who rests on whom. One pass.
  SupportMap support_map() const;
  // Pairs (upper rests on lower), sorted by (upper, lower).
  std::vector<TouchPair> touching() const;

  // Height at which body i of the map would come to rest if it fell now (ground or the highest top under it).
  std::int32_t landing_mm(const SupportMap& m, std::size_t i) const;
  std::int32_t ground_at(const Body& b) const { return ground_.height_mm(b.pos[0], b.pos[2]); }
  const MatterCatalog& catalog() const { return catalog_; }
  const EntityStore& store() const { return store_; }
  const GroundModel& ground() const { return ground_; }

  // Energy (mJ) of a fall of h_mm for a mass; 0.981 mJ per g.mm... integer: m_g * h_mm * 981 / 100000.
  static std::int64_t fall_energy_mj(std::int64_t mass_g, std::int64_t h_mm) {   // saturated: 100 t, 10 km at most
    return std::clamp<std::int64_t>(mass_g, 0, kMaxMassG) * std::clamp<std::int64_t>(h_mm, 0, 10000000) * 981 / 100000;
  }
  // Energy (mJ) of a mass moving at v_mm_s: m_g * v^2 / 2 / 1e6.
  static std::int64_t kinetic_energy_mj(std::int64_t mass_g, std::int64_t v_mm_s) {   // saturated: 100 t, 100 m/s at most
    std::int64_t v = std::clamp<std::int64_t>(v_mm_s, -100000, 100000);
    return std::clamp<std::int64_t>(mass_g, 0, kMaxMassG) * v * v / 2000000;
  }
  static std::int64_t break_energy_mj(const Profile& p);
  static std::int64_t capacity_g(const Profile& p);

 private:
  Affordances affordances(const Profile& p, std::int32_t target_hardness) const;
  const MatterCatalog& catalog_;
  const EntityStore& store_;
  const GroundModel& ground_;
};

}  // namespace em::act
