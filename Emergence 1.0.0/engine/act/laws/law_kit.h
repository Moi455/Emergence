// The kit of the laws of matter (T18): what a ProcessLaw receives and how it speaks. A law NEVER touches the world: it
// reads (LawContext) and emits Operations (Emitter) that the OperationBus applies in its total order. Integer only.
#pragma once
#include <cstdint>
#include <vector>

#include "../contact_resolver.h"
#include "emergence/act/entity_ops.h"
#include "emergence/ops/operation_bus.h"

namespace em::act {

// kTaskCompression (P37, docs/14 4.5): work on matter by cycle x 16 so that a job lasts its real-life duration in game
// time. Applies only to PRODUCTIVE gestures, never to bodily harm.
inline constexpr std::int32_t kTaskCompression = 16;
constexpr std::int32_t compressed_work(std::int32_t work, bool productive) { return productive ? work * kTaskCompression : work; }

enum class Outcome : std::uint8_t {
  NoEffect,            // the physics of the contact does not reach the process
  Done,                // the process happened: operations emitted
  Progress,            // work accumulated on the target (a slow process: carve, abrade)
  Snapped,             // the binding gave way
  Conflict,            // another contact of the same step already changed the target (the first in bus order wins)
  DelegatedToVoxels,   // the target is terrain: the voxel world (T17) applies it from `voxel`
};
const char* to_string(Outcome o);

struct VoxelRequest {
  bool valid = false;
  ProcessId process = ProcessId::kCount;
  Position at{};
  std::uint16_t material = kNoMatter;
  std::int32_t depth_mm = 0;
};

struct LawReport {
  ProcessId process = ProcessId::kCount;
  Outcome outcome = Outcome::NoEffect;
  std::uint32_t ops = 0;
  VoxelRequest voxel{};
};

// An operation ready for the bus with its order keys (author is in the operation).
struct Emission {
  ops::Operation op;
  std::uint32_t decision_seq = 0, k = 0;
};

// Per step: the entities already changed by an emission (a second law may not change them in the same step).
class TouchedSet {
 public:
  bool contains(EntityId id) const;
  void add(EntityId id);
 private:
  std::vector<EntityId> sorted_;
};

class Emitter {
 public:
  Emitter(std::vector<Emission>& out, TouchedSet& touched, std::uint64_t tick, std::uint32_t author,
          std::uint32_t decision_seq, std::uint32_t first_k = 0)
      : out_(out), touched_(touched), tick_(tick), author_(author), seq_(decision_seq), k_(first_k) {}
  void process(ProcessId p, std::uint8_t noise, std::uint8_t sight) { process_ = static_cast<std::uint16_t>(p); noise_ = noise; sight_ = sight; }
  void spawn(gen::EntityKind kind, const Position& pos, std::uint16_t sort, EntityId holder = kNoEntity);
  void destroy(EntityId id);
  void move(EntityId id, const Position& to, EntityId holder = kNoEntity);
  void delta(EntityId id, std::uint16_t var, std::int32_t old_value, std::int32_t new_value);
  std::uint32_t count() const { return emitted_; }
  std::uint32_t next_k() const { return k_; }
  bool touched(EntityId id) const { return touched_.contains(id); }
 private:
  void push(ops::Operation op);
  std::vector<Emission>& out_;
  TouchedSet& touched_;
  std::uint64_t tick_;
  std::uint32_t author_, seq_, k_;
  std::uint32_t emitted_ = 0;
  std::uint16_t process_ = ops::kNone16;
  std::uint8_t noise_ = 0, sight_ = 0;
};

// Variable indices (var_registry.json) the laws write, found by catalogue name in the generated field tables.
struct LawVars {
  std::uint16_t load_margin, visible_damage, process_progress;
  LawVars();
};

struct LawContext {
  const ContactResolver& resolver;
  const MatterCatalog& catalog;
  const EntityStore& store;
  const LawVars& vars;
  std::uint64_t tick;
};

// A law of matter. contact() fires when the PHYSICS of the contact meets the trigger of the process; it returns false
// when it does not apply (the engine then tries the next law). It decides nothing about whether the act is good.
class ContactLaw {
 public:
  virtual ~ContactLaw() = default;
  virtual ProcessId process() const = 0;
  virtual bool contact(const LawContext& ctx, const Contact& c, const Resolved& r, Emitter& out, LawReport& rep) const = 0;
};

// Shared helpers of the laws.
std::int32_t clamp_count(std::int64_t v, std::int32_t lo, std::int32_t hi);
// Position of the i-th of n pieces spread along the longest horizontal axis of the body, on its base level.
Position spread_position(const Body& b, std::int32_t i, std::int32_t n);
// Pieces a body falls apart into: spawns n entities of `sort` (kind item) where it stood.
void spawn_pieces(Emitter& out, const Body& from, std::uint16_t sort, std::int32_t n);
// Is the material one of the process inputs (consumes)?
bool consumes_material(ProcessId p, std::uint16_t material);

}  // namespace em::act
