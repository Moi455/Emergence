// GestureExecutor (T22, docs/14 sections 4.3 and 4.4): the gesture the model DECIDED, executed in time. A decision (gesture,
// parameters, manner, stop condition, plan) becomes an execution that approaches what the actor BELIEVES, performs its
// cycles at the cadence of the catalogue (16 game seconds per tick, cadence_ms of real time per cycle), and ends by
//   1. the `until` parameter of the gesture,  2. the stop condition of the decision,  3. natural_end,
//   4. the a_while limit (limit_reached: a mechanical bound that wakes the model, it decides nothing).
// A chosen duration (brief, a_while, long) is the bound the model asked for: reaching it is "done".
//
// WHAT IT PRODUCES, never a hidden effect: Contacts for the ContactResolver / ProcessEngine (the physics decides what a blow
// does), Emissions (Operations with their bus order keys) for movement, taking, putting, eating, speaking, and an
// ExecutionReport at the end of each gesture. WHAT IT NEVER DOES: judge that a goal is reached, read the truth for a stop
// condition or for a failure (P51: a gesture fails only ON THE SPOT, when the actor perceives that nothing is there; the
// terrain comes through NavigationQuery, the perception through ActorSenses), choose a gesture.
//
// FACTS WRITTEN in the actor's plan record (the intention of its dossier): i_status (running, suspended, blocked, done),
// i_step_started, i_step_progress, i_step_index, i_attempts. w_outcome travels in the ExecutionReport (WAKE.outcome).
// Every gesture goes first through the governor (check_gesture, D10); a refusal is proper: nothing runs, the reason stays in
// the engine journal (ExecutionReport::refusal) and is never written in a dossier.
//
// Determinism: one execution per actor, served in increasing EntityId order; outputs of each execution are merged in that
// order whatever the number of threads (an execution reads the world and writes only its own dossier).
#pragma once
#include <cstdint>
#include <map>
#include <memory>
#include <span>
#include <vector>

#include "contact_resolver.h"
#include "emergence/act/entity_store.h"
#include "emergence/act/perception/perception_engine.h"
#include "emergence/ops/applier.h"
#include "emergence/social/npc_state_codec.h"
#include "gesture_execution.h"
#include "gesture_senses.h"
#include "gesture_timing.h"
#include "executor_navigation.h"

namespace em::act {

namespace detail {
struct Deps;
struct Ctx;
class Behavior;
}  // namespace detail

// The dossiers of the NPCs (null = an actor without a mind: its plan and needs are not written).
class MindAccess {
 public:
  virtual ~MindAccess() = default;
  virtual social::NpcBundle* mind(EntityId who) const = 0;
};

struct ExecutorConfig {
  unsigned threads = 1;   // 1 = in the caller's thread; the output is identical for any value
  std::size_t min_per_thread = 256;   // an execution costs well under a microsecond: fewer than this per thread is not worth a thread
};

struct StepOutput {
  std::vector<Emission> emissions;      // operations for the bus, in actor order
  std::vector<Contact> contacts;        // for ProcessEngine::on_contacts
  std::vector<ExecutionReport> reports; // the end of the gestures of this tick
  std::vector<ExertionFact> exertion;   // what every active actor did to its body (NpcLaws)
  void clear() { emissions.clear(); contacts.clear(); reports.clear(); exertion.clear(); }
  std::uint64_t digest() const;         // FNV-1a 64 over everything above: equal for any number of threads
};

enum class BeginStatus : std::uint8_t { Started, Refused, Invalid };
struct BeginResult {
  BeginStatus status = BeginStatus::Started;
  social::Verdict verdict;   // the governor's verdict (engine journal only)
};

struct ExecutorStats {
  std::uint64_t begun = 0, refused = 0, invalid = 0, cycles = 0, steps = 0, contacts = 0, emissions = 0;
  std::uint64_t ended[5] = {};   // by ExecOutcome
};

// Variable indices of the entity store that the executor writes, found by catalogue name (no number in the code).
struct ExecutorVars {
  std::uint16_t hunger = 0xFFFF, thirst = 0xFFFF, exhaustion = 0xFFFF, sleepiness = 0xFFFF;
  std::uint16_t posture = 0xFFFF, orientation = 0xFFFF, water_volume = 0xFFFF;
  ExecutorVars();
};

class GestureExecutor {
 public:
  GestureExecutor(const EntityStore& store, const ContactResolver& resolver, const ActorSenses& senses,
                  ExecutorNavigation& navigation, const social::Governor& governor, const MindAccess& minds,
                  const IngestTable& ingest, ExecutorConfig cfg = {});
  ~GestureExecutor();

  // Starts the gesture decided by the model, replacing the actor's current one. The governor checks it first (D10): a refusal
  // starts nothing and queues an ExecutionReport{refused} for the next step. The decision's party pointers are used here only.
  BeginResult begin(const GestureDecision& decision, social::GameTime now, std::uint64_t tick);

  // What the laws of matter answered to the contacts of the last step (ProcessEngine::on_contacts, same order): a gesture whose
  // contacts keep having NO EFFECT on a thing (a door that does not open, a blow that leaves no mark) ends `failed` on the spot
  // after kNoEffectCycles cycles, and c_blocked reads true meanwhile. A fact felt by the actor, never a verdict on the goal.
  void contact_results(std::span<const Contact> contacts, std::span<const LawReport> reports);

  // The body interrupts physically (a blow, a fall, unconsciousness, a hold): the gesture ends `interrupted` at the next step.
  void notify(EntityId actor, BodyEvent event);

  // A wake of any priority (P0 danger, P1 spoken to...) calls the model but stops NOTHING: returns false, the execution goes on.
  bool on_wake(EntityId actor, perception::WakePriority priority);

  // One tick (16 game seconds): advances every execution. The output stays valid until the next call.
  const StepOutput& step(std::uint64_t tick, social::GameTime now);

  const GestureExecution* find(EntityId actor) const;
  bool busy(EntityId actor) const { return find(actor) != nullptr; }
  std::size_t active() const { return running_.size(); }
  const ExecutorStats& stats() const { return stats_; }

 private:
  std::unique_ptr<detail::Deps> deps_;
  ExecutorConfig cfg_;
  std::map<EntityId, GestureExecution> running_;   // ordered by actor: deterministic
  std::vector<ExecutionReport> refused_;           // reports of the gestures the governor refused, sent at the next step
  StepOutput out_;
  ExecutorStats stats_;
};

// Mirrors the changes of the needs of an actor (hunger, thirst, exhaustion, sleepiness: EntityDelta operations) into the
// dossier of the NPC, so that NpcLaws::step goes on from the state the gesture left. It is an Applier of the bus (register it
// AFTER the EntityStore): the effect of eating reaches NpcLaws through an operation, not through a back door.
class NpcNeedsApplier final : public ops::Applier {
 public:
  NpcNeedsApplier(const EntityStore& store, const MindAccess& minds) : store_(store), minds_(minds) {}
  std::string_view name() const override { return "NpcNeedsApplier"; }
  ops::ApplyStatus apply(const ops::Operation& op) override;

 private:
  const EntityStore& store_;
  const MindAccess& minds_;
  ExecutorVars vars_;
};

}  // namespace em::act
