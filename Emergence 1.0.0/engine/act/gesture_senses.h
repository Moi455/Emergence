// ActorSenses (T22, docs/14 section 4.3): what the executor of gestures may know of the world around the ACTOR. Every stop
// condition of the catalogue reads the PERCEPTION of the actor ("l'arbre paraît tombé"), and a gesture fails only on the spot
// when the actor perceives that nothing is there: the executor never reads the truth for either. ObserverSenses answers from
// the dossiers that the PerceptionEngine (T23) wrote for the actor; a test double answers from a script.
#pragma once
#include <cstdint>
#include <vector>

#include "emergence/act/entity_store.h"
#include "emergence/act/perception/perception_engine.h"

namespace em::act {

// What the actor perceives of one entity at this moment.
struct PerceivedThing {
  bool in_view = false;        // perceived now (a person, a beast, a thing): the actor SEES it
  Position at{};               // where it appears to be (valid when in_view)
  std::int32_t dist_mm = -1;   // apparent distance (valid when in_view)
  bool down = false;           // appears on the ground (ep_condition down, or lying / prone)
  bool still = false;          // appears motionless
  bool dead_obvious = false;   // obviously dead
  bool yields = false;         // appears to give way: on its knees, on the ground, or leaving
};

class ActorSenses {
 public:
  virtual ~ActorSenses() = default;
  virtual PerceivedThing perceive(EntityId actor, EntityId what) const = 0;
  virtual bool sees_kind(EntityId actor, std::uint32_t kind_symbol) const = 0;                  // c_sees
  virtual bool hears(EntityId actor, std::uint32_t concept_word) const = 0;                     // c_hears
  virtual bool addressed(EntityId actor) const = 0;                                             // c_addressed
  virtual bool attacked(EntityId actor) const = 0;                                              // c_attacked
  virtual bool stopped(EntityId actor) const = 0;                                               // c_stopped
  virtual bool state_seen(EntityId actor, EntityId what, std::uint32_t state_word) const = 0;   // c_state_seen
  virtual std::int32_t have_count(EntityId actor, std::uint32_t kind) const = 0;                // c_have (seen or believed)
  virtual bool unwatched(EntityId actor) const = 0;                                             // c_unwatched
};

// Reads the dossiers written by the PerceptionEngine for each Observer (entity_percept, percept, event_seen) through the
// ObserverMemory bindings (the engine-side link entity -> record). Bindings only hold what is perceived at the last tick.
// The position of a thing in view is rebuilt from the bearing and distance KEPT in its percept (never the true position).
// attacked() and stopped() are false here: the perception does not describe them yet; the body reports them (BodyEvent::Blow /
// Seized through GestureExecutor::notify), and c_attacked / c_stopped read that.
class ObserverSenses final : public ActorSenses {
 public:
  ObserverSenses(const EntityStore& store, std::vector<perception::Observer>& observers);
  PerceivedThing perceive(EntityId actor, EntityId what) const override;
  bool sees_kind(EntityId actor, std::uint32_t kind_symbol) const override;
  bool hears(EntityId actor, std::uint32_t concept_word) const override;
  bool addressed(EntityId actor) const override;
  bool attacked(EntityId actor) const override;
  bool stopped(EntityId) const override { return false; }
  bool state_seen(EntityId actor, EntityId what, std::uint32_t state_word) const override;
  std::int32_t have_count(EntityId actor, std::uint32_t kind) const override;
  bool unwatched(EntityId actor) const override;

 private:
  perception::Observer* find(EntityId actor) const;
  const EntityStore& store_;
  std::vector<perception::Observer*> by_entity_;   // sorted by entity
};

}  // namespace em::act
