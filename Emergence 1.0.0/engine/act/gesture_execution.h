// GestureExecution (T22, docs/14 section 4.3): the state of ONE gesture while it lasts, and the data that go in and out of
// the executor. A decision of the model (gesture + parameters + manner + stop condition + plan) becomes a GestureDecision; the
// execution walks PENDING -> APPROACH -> PERFORM -> FINISHED | FAILED and ends with an ExecutionReport whose outcome is a FACT
// OF EXECUTION seen on the spot (done, failed, blocked, interrupted, limit_reached), never a verdict on the goal.
#pragma once
#include <array>
#include <cstdint>
#include <optional>
#include <vector>

#include "emergence/act/entity_id.h"
#include "emergence/act/entity_ops.h"
#include "emergence/social/governor.h"
#include "emergence/social/npc_laws.h"
#include "emergence/social/state_types.h"
#include "gesture_timing.h"
#include "laws/law_kit.h"

namespace em::act {

enum class Phase : std::uint8_t { Pending, Approach, Perform, Finished, Failed };

// WAKE.outcome (w_outcome): the order of the values of settings.toml.
enum class ExecOutcome : std::uint8_t { Done, Failed, Blocked, Interrupted, LimitReached };
const char* to_string(ExecOutcome o);

// The cause the actor PERCEIVES ("it is not there", "the way is closed"), never an invisible one.
enum class Cause : std::uint8_t {
  None,
  TargetAbsent,      // on the spot, the actor sees that what it came for is not there
  PathBlocked,       // the actor sees the way closed
  Lost,              // the route leads nowhere the actor knows
  NotLiftable,       // the hand closes and nothing comes (too heavy, too big, not a thing to take)
  ToolBroken,        // the tool in hand broke
  ToolLost,          // the tool is no longer in hand
  NothingHappened,   // the gesture produced no perceived effect
  Blow,              // a blow received (hit_react)
  Fall,
  Unconscious,
  Seized,            // someone took hold of the actor
  Refused,           // the governor refused the gesture (engine journal only: never shown to the model)
  Replaced,          // the model chose another gesture: this one stops (explicit report, no hidden replacement)
};

enum class BodyEvent : std::uint8_t { Blow, Fall, Unconscious, Seized };

// A stop condition: a condition of conditions.toml and its arguments, already resolved by the decoder of the decision.
// `qty` is in the unit of the variable it compares (tenths of the charter scale; game seconds for c_elapsed; a count for c_have).
struct StopCondition {
  Condition cond = Condition::c_done;
  EntityId entity = 0;           // c_target_*, c_sees_ref, c_state_seen
  std::uint32_t word = 0;        // c_sees (kind symbol), c_hears (concept), c_state_seen (state word), c_have (kind)
  std::int32_t qty = 0;
  social::GameTime time = 0;     // c_time: seconds from midnight
  Position at{};                 // c_reached: the place
};

struct GestureDecision {
  EntityId actor = 0;
  std::uint32_t decision_seq = 0;            // the actor's own counter (total order of the bus)
  social::GestureCall call;                  // one value index per parameter: the governor checks it. Party pointers are used at begin() only.
  social::Party actor_party;                 // the actor, for D10
  EntityId target = 0, tool = 0, other = 0;  // what is aimed at, what is held and applied, the second thing (to, into, where)
  Position believed_at{};                    // where the actor BELIEVES the target is (LOCUS, last seen)
  bool has_believed_at = false;
  Position destination{};                    // a place or a direction already resolved to a point
  bool has_destination = false;
  std::optional<StopCondition> until;        // the `until` parameter of the gesture (strike, grab, sleep, wait)
  std::optional<StopCondition> stop;         // the decision's stop head (valid for any gesture that lasts)
  std::optional<Manner> manner;              // absent: derived from the parameters (manner_of)
  social::MRef plan{};                       // the intention record this step belongs to (0 = no plan)
  std::uint32_t target_ref = 0;              // serial of the pointer the model chose (compared with PLAN.next)
  std::uint32_t content = 0;                 // PropRef of a speech or a writing (opaque to the executor)
  // D10 on the CONTENT of speak / write: the verdict of Governor::check_utterance (the SpeechRouter, T24, with the real hearers). A
  // speak / write that carries a content without an allowing verdict is REFUSED by begin(): nothing is emitted.
  std::optional<social::Verdict> content_verdict;
  bool operator==(const GestureDecision&) const = delete;
};

// The end of a gesture (docs/14 4.3): `ExecutionReport {npc, gesture, outcome, tick, cause}` -> WAKE P2.
struct ExecutionReport {
  EntityId npc = 0;
  Gesture gesture{};
  ExecOutcome outcome = ExecOutcome::Done;   // w_outcome
  Cause cause = Cause::None;
  std::uint64_t tick = 0;
  social::GameTime started = 0, ended = 0;
  std::uint32_t cycles = 0;
  std::int32_t attempts = 0;                 // i_attempts after this end
  social::MRef plan{};
  bool refused = false;                      // engine journal only: the governor refused, nothing was executed
  social::Reason refusal = social::Reason::ok;   // engine journal only; NEVER written in a dossier or shown to the model
  bool operator==(const ExecutionReport&) const = default;
};

// What the actor does to its body this tick: a fact for NpcLaws::step (LawEnvironment::exertion).
struct ExertionFact {
  EntityId npc = 0;
  social::Exertion exertion = social::Exertion::kStanding;
  bool operator==(const ExertionFact&) const = default;
};

// The state of one execution (one per actor).
struct GestureExecution {
  GestureDecision d;
  Gesture gesture{};
  Phase phase = Phase::Pending;
  social::GameTime started = 0;               // i_step_started
  social::GameTime performing_since = 0;
  std::uint64_t started_tick = 0;
  CycleClock clock;
  std::uint32_t cycles = 0;
  std::int64_t limit_s = 0;                   // game seconds after which the execution stops (a_while, or the chosen duration)
  bool limit_is_chosen = false;               // the duration was CHOSEN by the model: reaching it is "done"
  Position goal{};
  std::int32_t approach_total_mm = 0;
  std::int32_t approach_left_mm = 0;
  bool blocked_seen = false;                  // c_blocked: the actor saw the way closed during this tick
  std::int32_t facing_mrad = 0;
  std::uint8_t posture = 0;
  std::optional<BodyEvent> pending_event;
  std::uint32_t no_effect = 0;                // consecutive contacts that changed nothing (reported by the laws of matter)
  bool tracks_plan = false;                   // the chosen gesture IS PLAN.next: its facts go to the plan record
  bool vanished = false;                      // the actor no longer exists: dropped without a report
  ExecOutcome outcome = ExecOutcome::Done;
  Cause cause = Cause::None;
};

}  // namespace em::act
