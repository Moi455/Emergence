#include "gesture_executor.h"

#include <algorithm>
#include <cstdlib>
#include <thread>

#include "emergence/act/perception/trig.h"
#include "emergence/social/plan_target_header.h"

namespace em::act {
namespace detail {
namespace {

using perception::atan2_mrad;
using perception::isqrt;
using social::NpcBundle;
using social::gen::Gesture;

constexpr std::size_t kGestureCount = social::gen::kGestures.size();
constexpr std::int16_t kUnconsciousBelow = 20;      // the perception's own threshold (consciousness in tenths)
constexpr std::int32_t kTurnMinMrad = 100;          // a change of facing smaller than this is not worth an operation
constexpr std::uint8_t kPostureStanding = 0, kPostureWalking = 1, kPostureRunning = 2, kPostureSitting = 3, kPostureKneeling = 4,
                       kPostureCrouching = 5, kPostureLying = 6, kPostureClimbing = 8, kPostureSwimming = 9, kPostureGuard = 10;

}  // namespace

// ---- what every behaviour may read and write -------------------------------------------------------------------------------
struct Deps {
  const EntityStore& store;
  const ContactResolver& resolver;
  const ActorSenses& senses;
  ExecutorNavigation& nav;
  const social::Governor& governor;
  const MindAccess& minds;
  const IngestTable& ingest;
  ExecutorVars vars;
  std::array<std::uint16_t, kGestureCount> gesture_word{};   // id of the gesture's name in kWords (PLAN.steps holds words)
  Deps(const EntityStore& s, const ContactResolver& r, const ActorSenses& se, ExecutorNavigation& n, const social::Governor& g,
       const MindAccess& m, const IngestTable& i)
      : store(s), resolver(r), senses(se), nav(n), governor(g), minds(m), ingest(i) {
    for (std::size_t i2 = 0; i2 < kGestureCount; ++i2) {
      for (std::size_t w = 0; w < social::gen::kWords.size(); ++w)
        if (social::gen::kWords[w] == social::gen::kGestureNames[i2]) { gesture_word[i2] = static_cast<std::uint16_t>(w); break; }
    }
  }
};

struct Ctx {
  const Deps& d;
  std::uint64_t tick;
  social::GameTime now;
  StepOutput& out;
  ExecutorStats& st;
  // the execution being advanced
  GestureExecution* e = nullptr;
  NpcBundle* mind = nullptr;
  Position me{};
  std::uint32_t k = 0;

  Ctx(const Deps& deps, std::uint64_t t, social::GameTime n, StepOutput& o, ExecutorStats& s) : d(deps), tick(t), now(n), out(o), st(s) {}

  EntityId actor() const { return e->d.actor; }
  int pv(std::string_view name) const {
    const int i = param_index(e->gesture, name);
    return i < 0 ? -1 : e->d.call.value[static_cast<std::size_t>(i)];
  }
  PerceivedThing perceive(EntityId what) const { return what ? d.senses.perceive(actor(), what) : PerceivedThing{}; }
  std::int64_t horizontal_mm(const Position& a, const Position& b) const {
    const std::int64_t dx = std::int64_t{a[0]} - b[0], dy = std::int64_t{a[1]} - b[1];
    return static_cast<std::int64_t>(isqrt(static_cast<std::uint64_t>(dx * dx + dy * dy)));
  }
  bool discreet() const { return pv("stealth") == 1; }

  void emit(ops::Operation op, std::uint8_t noise, std::uint8_t sight) {
    op.gesture = static_cast<std::uint16_t>(e->gesture);
    op.noise = noise;
    op.sight = sight;
    out.emissions.push_back({std::move(op), e->d.decision_seq, k++});
    ++st.emissions;
  }
  void move_entity(EntityId who, const Position& to, EntityId holder, std::uint8_t noise, std::uint8_t sight) {
    emit(make_move(tick, actor(), who, to, holder), noise, sight);
  }
  // A change of a scalar variable: the old value is read in the store (the store refuses a delta whose old value is stale).
  bool delta(EntityId who, std::uint16_t var, std::int64_t new_value, std::uint8_t noise = 0, std::uint8_t sight = 0) {
    if (var == 0xFFFF) return false;
    std::int64_t old = 0;
    if (!d.store.read_var(who, var, old) || old == new_value) return false;
    emit(make_delta(tick, actor(), who, var, static_cast<std::int32_t>(old), static_cast<std::int32_t>(new_value)), noise, sight);
    return true;
  }
  void set_posture(std::uint8_t p) {
    if (p == e->posture) return;
    e->posture = p;
    delta(actor(), d.vars.posture, p, 0, 5);
  }
  void face(const Position& toward) {
    const std::int64_t dx = std::int64_t{toward[0]} - me[0], dy = std::int64_t{toward[1]} - me[1];
    if (dx == 0 && dy == 0) return;
    const std::int32_t a = atan2_mrad(dy, dx);
    if (std::abs(perception::wrap_angle(std::int64_t{a} - e->facing_mrad)) < kTurnMinMrad) return;
    if (delta(actor(), d.vars.orientation, a, 0, 5)) e->facing_mrad = a;
  }
  // An Act operation: the perceptible trace of a gesture that has no material effect (docs/14 4.6).
  void act(std::uint8_t noise, std::uint8_t sight, bool speech) {
    ops::Operation op;
    op.tick = tick;
    op.author = actor();
    op.kind = static_cast<std::uint16_t>(ops::OpKind::Act);
    op.flags = static_cast<std::uint8_t>(ops::kFlagEntities | (speech ? ops::kFlagSpeech : 0));
    ops::PayloadWriter w;
    w.u16(static_cast<std::uint16_t>(e->gesture));
    for (std::size_t i = 0; i < 8; ++i) w.u8(i < e->d.call.value.size() ? static_cast<std::uint8_t>(e->d.call.value[i]) : 0xFF);
    w.u32(e->d.target).u32(e->d.tool).u32(e->d.other).u32(e->d.content);
    op.payload = w.take();
    emit(std::move(op), noise, discreet() ? std::uint8_t(std::min<int>(sight, 2)) : sight);
  }
  Contact contact(Manner m, bool at_joint = false) const {
    Contact c;
    c.author = actor();
    c.decision_seq = e->d.decision_seq;
    c.tool = e->d.tool;
    c.target = e->d.target;
    c.other = e->d.other;
    c.manner = m;
    const int in = pv("intensity");
    c.speed_mm_s = kBlowSpeedMmS[in < 0 ? 2 : std::min(in, 4)];
    c.at_joint = at_joint;
    c.productive = timing_of(e->gesture).productive;
    c.at = e->d.has_destination ? e->d.destination : Position{};
    return c;
  }
};

struct CycleResult {
  bool fail = false;
  ExecOutcome outcome = ExecOutcome::Failed;
  Cause cause = Cause::None;
  bool end = false;   // the gesture has nothing more to do (its natural end)
  static CycleResult failed(Cause c, ExecOutcome o = ExecOutcome::Failed) { return {true, o, c, false}; }
  static CycleResult ended() { return {false, ExecOutcome::Done, Cause::None, true}; }
};

class Behavior {
 public:
  virtual ~Behavior() = default;
  // The entity the actor walks to (the thing aimed at, the recipient...); 0 = a place (destination) or nothing.
  virtual EntityId approach_entity(const GestureExecution& e) const { return e.d.target; }
  virtual bool needs_approach(const Ctx&, const GestureExecution&) const { return false; }
  virtual std::int32_t stop_within_mm(const Ctx&, const GestureExecution&) const { return kReachMm; }
  virtual std::int32_t speed_mm_s(const Ctx&, const GestureExecution&) const { return kPaceSpeedMmS[1]; }
  virtual bool away(const Ctx&, const GestureExecution&) const { return false; }
  // On the spot, the actor must PERCEIVE this entity or the gesture fails (it is not there).
  virtual EntityId presence_entity(const GestureExecution& e) const { return approach_entity(e); }
  virtual social::Exertion exertion(const GestureExecution&) const { return social::Exertion::kStanding; }
  virtual std::uint8_t posture(const GestureExecution&) const { return kPostureStanding; }
  // True when the gesture is complete after this many cycles (only read when it ends naturally).
  virtual bool complete(const Ctx&, const GestureExecution& e) const { return e.cycles >= 1; }
  virtual CycleResult cycle(Ctx& c) const = 0;
};

namespace {

// ---- movement -------------------------------------------------------------------------------------------------------------
class MoveBehavior final : public Behavior {
 public:
  bool needs_approach(const Ctx&, const GestureExecution& e) const override { return e.gesture != Gesture::jump; }
  std::int32_t stop_within_mm(const Ctx& c, const GestureExecution& e) const override {
    if (e.gesture == Gesture::go) {
      const int s = c.pv("stop_at");
      if (s >= 0 && s < 4) return kStopAtMm[s];
      return e.d.target ? kReachMm : kArrivedMm;
    }
    return e.d.target ? kReachMm : kArrivedMm;
  }
  std::int32_t speed_mm_s(const Ctx& c, const GestureExecution& e) const override {
    const int pace = c.pv("pace");
    const std::int32_t walk = kPaceSpeedMmS[pace < 0 ? 1 : std::min(pace, 3)];
    switch (e.gesture) {
      case Gesture::climb: return walk * kClimbSpeedPermille / 1000;
      case Gesture::swim: return kSwimSpeedMmS;
      default: return walk;
    }
  }
  bool away(const Ctx& c, const GestureExecution& e) const override { return e.gesture == Gesture::go && c.pv("relation") == 2; }
  EntityId presence_entity(const GestureExecution& e) const override {
    // Going to a person or a thing: it must be there on arrival; going to a place or away from something: nothing to find.
    if (e.gesture == Gesture::mount) return e.d.target;
    return e.d.target;
  }
  social::Exertion exertion(const GestureExecution& e) const override {
    if (e.gesture == Gesture::climb || e.gesture == Gesture::swim) return social::Exertion::kHeavyWork;
    return social::Exertion::kWalking;
  }
  std::uint8_t posture(const GestureExecution& e) const override {
    return e.gesture == Gesture::climb ? kPostureClimbing : e.gesture == Gesture::swim ? kPostureSwimming : kPostureStanding;
  }
  CycleResult cycle(Ctx& c) const override {
    if (c.e->gesture == Gesture::mount) {   // get_on / get_off
      const bool get_on = c.pv("mode") != 1;
      c.move_entity(c.actor(), c.me, get_on ? c.e->d.target : kNoEntity, 1, 5);
    }
    return CycleResult::ended();   // go, climb, swim: the arrival is the end
  }
};

class JumpBehavior final : public Behavior {
 public:
  social::Exertion exertion(const GestureExecution&) const override { return social::Exertion::kHeavyWork; }
  CycleResult cycle(Ctx& c) const override {
    Position to = c.me;
    const Position* toward = c.e->d.has_destination ? &c.e->d.destination : c.e->d.has_believed_at ? &c.e->d.believed_at : nullptr;
    const int in = c.pv("intensity");
    const std::int32_t len = kJumpMm[in < 0 ? 2 : std::min(in, 4)];
    if (toward) {
      const std::int64_t dx = std::int64_t{(*toward)[0]} - c.me[0], dy = std::int64_t{(*toward)[1]} - c.me[1];
      const std::int64_t d = static_cast<std::int64_t>(isqrt(static_cast<std::uint64_t>(dx * dx + dy * dy)));
      if (d > 0) {
        const std::int64_t m = std::min<std::int64_t>(len, d);
        to[0] = static_cast<std::int32_t>(c.me[0] + dx * m / d);
        to[1] = static_cast<std::int32_t>(c.me[1] + dy * m / d);
      }
    }
    c.move_entity(c.actor(), to, kNoEntity, 3, 6);
    return CycleResult::ended();
  }
};

class PostureBehavior final : public Behavior {
 public:
  std::uint8_t posture(const GestureExecution& e) const override { return value_of(e); }
  CycleResult cycle(Ctx& c) const override {
    c.set_posture(value_of(*c.e));
    return CycleResult::ended();
  }

 private:
  static std::uint8_t value_of(const GestureExecution& e) {   // stand, sit, kneel, crouch, lie_down
    const int i = param_index(Gesture::set_posture, "posture");
    const int v = i < 0 ? 0 : e.d.call.value[static_cast<std::size_t>(i)];
    constexpr std::uint8_t table[5] = {kPostureStanding, kPostureSitting, kPostureKneeling, kPostureCrouching, kPostureLying};
    return table[v < 0 ? 0 : std::min(v, 4)];
  }
};

// ---- grasping -------------------------------------------------------------------------------------------------------------
class GraspBehavior final : public Behavior {
 public:
  EntityId approach_entity(const GestureExecution& e) const override {
    switch (e.gesture) {
      case Gesture::take: return e.d.target;
      case Gesture::put: case Gesture::give: case Gesture::pour: return e.d.other;   // where / to whom / into what
      default: return kNoEntity;
    }
  }
  bool needs_approach(const Ctx& c, const GestureExecution& e) const override {
    if (e.gesture == Gesture::take) return true;
    if (e.gesture == Gesture::put) return e.d.other != kNoEntity || e.d.has_destination;
    if (e.gesture == Gesture::give || e.gesture == Gesture::pour) return e.d.other != kNoEntity;
    (void)c;
    return false;
  }
  bool complete(const Ctx&, const GestureExecution& e) const override { return e.cycles >= 1; }
  social::Exertion exertion(const GestureExecution&) const override { return social::Exertion::kStanding; }
  CycleResult cycle(Ctx& c) const override {
    GestureExecution& e = *c.e;
    const EntityStore& store = c.d.store;
    const std::uint8_t noise = c.discreet() ? 1 : 2, sight = c.discreet() ? 2 : 6;
    switch (e.gesture) {
      case Gesture::take: {
        Contact probe;   // the physics answers: can a hand close on it and lift it?
        probe.target = e.d.target;
        const Resolved res = c.d.resolver.resolve(probe);
        if (!res.target.valid() || !res.target.aff.graspable) return CycleResult::failed(Cause::NotLiftable);
        c.move_entity(e.d.target, c.me, c.actor(), noise, sight);
        c.act(noise, sight, false);
        return CycleResult::ended();
      }
      case Gesture::put: {
        if (!held(c, e.d.target)) return CycleResult::failed(Cause::ToolLost);
        Position at = c.me;
        if (const PerceivedThing w = c.perceive(e.d.other); w.in_view) at = w.at;   // where it is SEEN, not where it is
        else if (e.d.has_destination) at = e.d.destination;
        c.move_entity(e.d.target, at, kNoEntity, noise, sight);
        c.act(noise, sight, false);
        return CycleResult::ended();
      }
      case Gesture::give: {
        if (!held(c, e.d.target)) return CycleResult::failed(Cause::ToolLost);
        const PerceivedThing to = c.perceive(e.d.other);
        if (!to.in_view || c.horizontal_mm(c.me, to.at) > kReachMm + kArrivedMm * 2) return CycleResult::failed(Cause::TargetAbsent);
        c.move_entity(e.d.target, to.at, e.d.other, 1, 6);
        c.act(1, 6, false);
        return CycleResult::ended();
      }
      case Gesture::throw_: {
        if (!held(c, e.d.target)) return CycleResult::failed(Cause::ToolLost);
        const PerceivedThing aimed = c.perceive(e.d.other);
        Position at = aimed.in_view ? aimed.at : e.d.has_destination ? e.d.destination : e.d.has_believed_at ? e.d.believed_at : c.me;
        c.move_entity(e.d.target, at, kNoEntity, 4, 8);
        c.act(4, 8, false);
        if (e.d.other) {   // the thrown thing hits what it was thrown at: the physics decides
          Contact k = c.contact(Manner::Strike);
          k.tool = e.d.target;
          k.target = e.d.other;
          c.out.contacts.push_back(k);
          ++c.st.contacts;
        }
        return CycleResult::ended();
      }
      case Gesture::pour: {
        const EntityId from = e.d.target, into = e.d.other;
        std::int64_t have = 0;
        if (!held(c, from)) return CycleResult::failed(Cause::ToolLost);
        if (into && !c.perceive(into).in_view) return CycleResult::failed(Cause::TargetAbsent);   // nothing there to pour into
        if (!store.alive(from) || !store.read_var(from, c.d.vars.water_volume, have) || have <= 0) return CycleResult::failed(Cause::NothingHappened);
        const int a = c.pv("amount");
        const std::int64_t share = a == 0 ? 333 : a == 1 ? 666 : 1000;
        const std::int64_t q = std::max<std::int64_t>(1, have * share / 1000);
        c.delta(from, c.d.vars.water_volume, have - q, 1, 6);
        std::int64_t in_vol = 0;
        if (into && store.read_var(into, c.d.vars.water_volume, in_vol)) c.delta(into, c.d.vars.water_volume, in_vol + q, 1, 6);
        c.act(1, 6, false);
        return CycleResult::ended();
      }
      case Gesture::wear: {
        if (!held(c, e.d.target)) return CycleResult::failed(Cause::ToolLost);
        c.act(0, 4, false);   // the garment stays held by the actor (worn lists are the dossier's business)
        return CycleResult::ended();
      }
      default: return CycleResult::ended();
    }
  }

 private:
  static bool held(const Ctx& c, EntityId item) { return item != kNoEntity && c.d.store.alive(item) && c.d.store.holder(item) == c.actor(); }
};

// ---- contact: the physics decides what the blow does ---------------------------------------------------------------------
class ContactBehavior final : public Behavior {
 public:
  EntityId approach_entity(const GestureExecution& e) const override { return e.gesture == Gesture::guard ? kNoEntity : e.d.target; }
  bool needs_approach(const Ctx&, const GestureExecution& e) const override {
    return e.gesture != Gesture::guard && (e.d.target != kNoEntity || e.d.has_destination);
  }
  EntityId presence_entity(const GestureExecution& e) const override { return e.gesture == Gesture::guard ? kNoEntity : e.d.target; }
  social::Exertion exertion(const GestureExecution& e) const override {
    if (e.gesture == Gesture::guard || e.gesture == Gesture::examine || e.gesture == Gesture::search || e.gesture == Gesture::touch)
      return social::Exertion::kStanding;
    return social::Exertion::kHeavyWork;
  }
  std::uint8_t posture(const GestureExecution& e) const override { return e.gesture == Gesture::guard ? kPostureGuard : kPostureStanding; }
  CycleResult cycle(Ctx& c) const override {
    GestureExecution& e = *c.e;
    if (e.gesture == Gesture::guard) {
      if (e.cycles == 0) c.act(0, 8, false);
      return {};
    }
    // The tool must still be in hand: a tool that is gone broke (c_tool_broken), one that is elsewhere was lost.
    if (e.d.tool != kNoEntity) {
      if (!c.d.store.alive(e.d.tool)) return CycleResult::failed(Cause::ToolBroken);
      if (c.d.store.holder(e.d.tool) != c.actor()) return CycleResult::failed(Cause::ToolLost);
    }
    const bool joint = e.gesture == Gesture::channel && c.pv("intent") == 1;
    const Manner m = e.d.manner ? *e.d.manner : manner_of(e.gesture, motion_value(c));
    c.out.contacts.push_back(c.contact(m, joint));
    ++c.st.contacts;
    const bool blow = e.gesture == Gesture::strike || e.gesture == Gesture::push || e.gesture == Gesture::pull || e.gesture == Gesture::grab;
    if (blow) c.act(e.gesture == Gesture::strike ? 6 : 3, 8, false);
    else if (e.cycles == 0) c.act(timing_of(e.gesture).productive ? 4 : 1, 6, false);
    return {};
  }

 private:
  static int motion_value(const Ctx& c) {
    switch (c.e->gesture) {
      case Gesture::work: return c.pv("motion");
      case Gesture::tie: case Gesture::channel: return c.pv(c.e->gesture == Gesture::tie ? "mode" : "intent");
      default: return -1;
    }
  }
};

// ---- the body: eating, drinking, sleeping, resting ------------------------------------------------------------------------
class ConsumeBehavior final : public Behavior {
 public:
  EntityId approach_entity(const GestureExecution& e) const override { return e.d.target; }
  bool needs_approach(const Ctx& c, const GestureExecution& e) const override {
    if (e.gesture == Gesture::eat || e.gesture == Gesture::drink) return e.d.target && c.d.store.holder(e.d.target) != c.actor();
    if (e.gesture == Gesture::sleep) return e.d.has_destination || e.d.target != kNoEntity;
    return false;
  }
  EntityId presence_entity(const GestureExecution& e) const override {
    return ((e.gesture == Gesture::eat || e.gesture == Gesture::drink) && e.d.target && e.d.target != 0) ? e.d.target : kNoEntity;
  }
  social::Exertion exertion(const GestureExecution& e) const override {
    return e.gesture == Gesture::sleep ? social::Exertion::kSleeping : social::Exertion::kStanding;
  }
  std::uint8_t posture(const GestureExecution& e) const override {
    return e.gesture == Gesture::sleep ? kPostureLying : e.gesture == Gesture::rest ? kPostureSitting : kPostureStanding;
  }
  bool complete(const Ctx& c, const GestureExecution& e) const override {
    if (e.gesture == Gesture::eat || e.gesture == Gesture::drink) return e.cycles >= static_cast<std::uint32_t>(std::max(c.pv("amount"), 0)) + 1;   // little 1, some 2, all 3
    return e.cycles >= 1;
  }
  CycleResult cycle(Ctx& c) const override {
    GestureExecution& e = *c.e;
    if (e.gesture == Gesture::sleep || e.gesture == Gesture::rest) {
      c.set_posture(posture(e));
      return {};
    }
    // eat / drink: a third of the portion per cycle; the whole portion needs `all`.
    const EntityStore& store = c.d.store;
    const EntityId item = e.d.target;
    if (store.holder(item) != c.actor()) {   // not in hand: it must be SEEN within reach
      const PerceivedThing p = c.perceive(item);
      if (!p.in_view || c.horizontal_mm(c.me, p.at) > kReachMm + kArrivedMm * 2) return CycleResult::failed(Cause::TargetAbsent);
    } else if (!store.alive(item)) {
      return CycleResult::failed(Cause::TargetAbsent);   // the hand closes on nothing
    }
    const std::uint16_t sort = store.sort(item);
    const std::int32_t food = c.d.ingest.nutrition(sort), water = c.d.ingest.hydration(sort);
    if (food == 0 && water == 0) return CycleResult::failed(Cause::NothingHappened);   // nothing to eat or drink in it
    const EntityId who = e.d.other ? e.d.other : c.actor();
    const int amount = std::max(c.pv("amount"), 0);   // little 0, some 1, all 2: one third of the item per cycle
    auto lower = [&](std::uint16_t var, std::int32_t points) {
      if (var == 0xFFFF || points <= 0) return;
      std::int64_t now_v = 0;
      if (!store.read_var(who, var, now_v)) return;
      c.delta(who, var, std::max<std::int64_t>(0, now_v - std::int64_t{points} * kTenthsPerFoodPoint / 3), 1, 6);
    };
    if (e.gesture == Gesture::eat) lower(c.d.vars.hunger, food); else lower(c.d.vars.thirst, water);
    if (e.gesture == Gesture::eat && water > 0) lower(c.d.vars.thirst, water);   // a soup quenches a little as well
    c.act(e.gesture == Gesture::eat ? 1 : 0, 6, false);
    if (amount >= 2 && e.cycles + 1 >= 3) c.emit(make_destroy(c.tick, c.actor(), item), 0, 0);   // all of it: the item is consumed
    return {};
  }
};

// ---- perceiving ----------------------------------------------------------------------------------------------------------
class PerceiveBehavior final : public Behavior {
 public:
  // Reading needs the thing in hand or within reach and SEEN; looking and listening need nothing.
  EntityId approach_entity(const GestureExecution& e) const override { return e.gesture == Gesture::read ? e.d.target : kNoEntity; }
  bool needs_approach(const Ctx& c, const GestureExecution& e) const override {
    return e.gesture == Gesture::read && e.d.target && c.d.store.holder(e.d.target) != c.actor();
  }
  EntityId presence_entity(const GestureExecution& e) const override {
    return e.gesture == Gesture::read ? e.d.target : kNoEntity;
  }
  bool complete(const Ctx&, const GestureExecution& e) const override { return e.cycles >= 1; }
  CycleResult cycle(Ctx& c) const override {
    GestureExecution& e = *c.e;
    // Turn toward what is looked at or listened to: what is seen now, else where the actor believes it is.
    const PerceivedThing p = c.perceive(e.d.target);
    if (p.in_view) c.face(p.at);
    else if (e.d.has_believed_at) c.face(e.d.believed_at);
    else if (e.d.has_destination) c.face(e.d.destination);
    if (e.gesture == Gesture::read) {
      if (!e.d.target) return CycleResult::failed(Cause::TargetAbsent);
      c.act(0, 4, false);
    } else if (e.cycles == 0) {
      c.act(0, e.gesture == Gesture::look ? 7 : 3, false);   // a gaze is seen, a listener hardly
    }
    return {};
  }
};

// ---- communicating -------------------------------------------------------------------------------------------------------
class CommunicateBehavior final : public Behavior {
 public:
  EntityId approach_entity(const GestureExecution& e) const override {
    return (e.gesture == Gesture::speak || e.gesture == Gesture::write) ? e.d.target : kNoEntity;
  }
  bool needs_approach(const Ctx&, const GestureExecution& e) const override {
    return (e.gesture == Gesture::speak || e.gesture == Gesture::write) && e.d.target != kNoEntity;
  }
  std::int32_t stop_within_mm(const Ctx&, const GestureExecution& e) const override {
    return e.gesture == Gesture::speak ? kStopAtMm[2] : kReachMm;   // talking distance
  }
  EntityId presence_entity(const GestureExecution& e) const override { return approach_entity(e); }
  CycleResult cycle(Ctx& c) const override {
    GestureExecution& e = *c.e;
    const PerceivedThing p = c.perceive(e.d.target);
    if (p.in_view) c.face(p.at);
    switch (e.gesture) {
      case Gesture::speak: {
        const int v = c.pv("volume");
        c.act(kVolumeNoise[v < 0 ? 2 : std::min(v, 4)], 3, true);
        break;
      }
      case Gesture::sign: c.act(0, 8, false); break;
      case Gesture::write: c.act(1, 4, false); break;
      default: c.act(6, 7, false); break;   // perform: music, a dance, a tale
    }
    return e.gesture == Gesture::perform ? CycleResult{} : CycleResult::ended();
  }
};

class MetaBehavior final : public Behavior {
 public:
  EntityId approach_entity(const GestureExecution&) const override { return kNoEntity; }
  CycleResult cycle(Ctx&) const override { return {}; }
  bool complete(const Ctx&, const GestureExecution& e) const override { return e.cycles >= 1; }
};

const Behavior& behavior_of(Gesture g) {
  static const MoveBehavior move;
  static const JumpBehavior jump;
  static const PostureBehavior posture;
  static const GraspBehavior grasp;
  static const ContactBehavior contact;
  static const ConsumeBehavior consume;
  static const PerceiveBehavior perceive;
  static const CommunicateBehavior communicate;
  static const MetaBehavior meta;
  switch (g) {
    case Gesture::go: case Gesture::climb: case Gesture::swim: case Gesture::mount: return move;
    case Gesture::jump: return jump;
    case Gesture::set_posture: return posture;
    case Gesture::take: case Gesture::put: case Gesture::give: case Gesture::throw_: case Gesture::pour: case Gesture::wear: return grasp;
    case Gesture::operate: case Gesture::strike: case Gesture::push: case Gesture::pull: case Gesture::grab: case Gesture::guard:
    case Gesture::scoop: case Gesture::work: case Gesture::tie: case Gesture::blow: case Gesture::shape: case Gesture::channel:
    case Gesture::touch: case Gesture::search: case Gesture::examine: return contact;
    case Gesture::eat: case Gesture::drink: case Gesture::sleep: case Gesture::rest: return consume;
    case Gesture::look: case Gesture::listen: case Gesture::read: return perceive;
    case Gesture::speak: case Gesture::sign: case Gesture::write: case Gesture::perform: return communicate;
    case Gesture::wait: case Gesture::stop: case Gesture::kCount: break;
  }
  return meta;
}

// ---- stop conditions (conditions.toml), read in the PERCEPTION of the actor ------------------------------------------------
bool condition_holds(const Ctx& c, const GestureExecution& e, const StopCondition& s) {
  const social::gen::NpcState* st = c.mind ? &c.mind->state : nullptr;
  auto target = [&] { return c.perceive(s.entity); };
  switch (s.cond) {
    case Condition::c_done: return e.cycles >= 1;
    case Condition::c_reached: return c.horizontal_mm(c.me, s.at) <= kArrivedMm;
    case Condition::c_target_down: { const auto p = target(); return p.in_view && p.down; }
    case Condition::c_target_still: { const auto p = target(); return p.in_view && p.still; }
    case Condition::c_target_yields: { const auto p = target(); return p.in_view && p.yields; }
    case Condition::c_target_gone: return !target().in_view;
    case Condition::c_attacked: return e.pending_event == BodyEvent::Blow || c.d.senses.attacked(c.actor());
    case Condition::c_sees: return c.d.senses.sees_kind(c.actor(), s.word);
    case Condition::c_hears: return c.d.senses.hears(c.actor(), s.word);
    case Condition::c_addressed: return c.d.senses.addressed(c.actor());
    case Condition::c_pain_above: return st && st->body.pain > s.qty;
    case Condition::c_hunger_above: return st && st->needs.hunger > s.qty;
    case Condition::c_thirst_above: return st && st->needs.thirst > s.qty;
    case Condition::c_exhausted: return st && st->needs.exhaustion > s.qty;
    case Condition::c_tool_broken: return e.d.tool != kNoEntity && !c.d.store.alive(e.d.tool);
    case Condition::c_hands_full: return st && st->carrier.load_ratio >= 1000;
    case Condition::c_blocked: return e.blocked_seen || e.no_effect > 0;   // the way is closed, or my gesture does nothing
    case Condition::c_time: {
      // "it is <time>": the first moment at or after the start of the gesture when the clock of the day reaches the time.
      const std::int64_t day = social::WorldClock::kGameSecondsPerDay;
      std::int64_t at = e.started - e.started % day + s.time;
      if (at < e.started) at += day;
      return c.now >= at;
    }
    case Condition::c_elapsed: return c.now - e.started >= s.qty;
    case Condition::c_stopped: return e.pending_event == BodyEvent::Seized || c.d.senses.stopped(c.actor());
    case Condition::c_sees_ref: return target().in_view;
    case Condition::c_state_seen: return c.d.senses.state_seen(c.actor(), s.entity, s.word);
    case Condition::c_rested:
      return st && st->needs.sleepiness <= kRestedSleepinessMaxTenths && st->needs.exhaustion <= kRestedExhaustionMaxTenths;
    case Condition::c_have: return c.d.senses.have_count(c.actor(), s.word) >= s.qty;
    case Condition::c_unwatched: return c.d.senses.unwatched(c.actor());
    case Condition::c_target_near: { const auto p = target(); return p.in_view && p.dist_mm >= 0 && p.dist_mm <= kNearMm; }
    case Condition::kCount: break;
  }
  return false;
}

// Order of the stop (docs/14 4.3): the `until` of the gesture, else the stop head of the decision.
bool stops_now(const Ctx& c, const GestureExecution& e) {
  if (e.d.until) return condition_holds(c, e, *e.d.until);
  if (e.d.stop) return condition_holds(c, e, *e.d.stop);
  return false;
}

// ---- the facts written in the plan record of the actor's dossier -----------------------------------------------------------
enum PlanStatus : std::uint8_t { kRunning = 0, kSuspended = 1, kBlocked = 2, kDone = 3, kAbandoned = 4 };   // values of i_status

social::gen::Intention* plan_record(NpcBundle* m, social::MRef plan) { return (m && plan.serial) ? m->state.intention_records.find(plan) : nullptr; }

bool is_plan_next(const NpcBundle& m, const social::gen::Intention& rec, const GestureDecision& d, std::uint16_t gesture_word) {
  const auto steps = m.side.get(rec.i_steps);
  const std::int64_t idx = rec.i_step_index / 1000;
  if (idx < 0 || idx >= static_cast<std::int64_t>(steps.size()) || steps[static_cast<std::size_t>(idx)] != gesture_word) return false;
  // PROVISIONAL convention of the ContextBuilder (T28b), until the catalogue has a variable `i_target` (T28c): i_step_targets may
  // start with ONE header item (bit 31) holding the target of the whole plan; the target of step i is then items[i + 1].
  auto targets = m.side.get(rec.i_step_targets);
  targets = social::skip_target_header(targets);
  const std::uint32_t expected = idx < static_cast<std::int64_t>(targets.size()) ? targets[static_cast<std::size_t>(idx)] : 0;
  return expected == d.target_ref;
}

std::int32_t progress_permille(const Ctx& c, const GestureExecution& e) {
  std::int64_t approach = 1000, perform = 0;
  const bool approached = e.approach_total_mm > 0;
  if (approached) approach = e.phase == Phase::Approach ? 1000 - std::int64_t{e.approach_left_mm} * 1000 / e.approach_total_mm : 1000;
  if (e.phase == Phase::Perform || e.phase == Phase::Finished) {
    if (e.limit_s > 0) perform = std::min<std::int64_t>(999, (c.now - e.performing_since) * 1000 / e.limit_s);
    else perform = std::min<std::int64_t>(999, std::int64_t{e.cycles} * 1000 / std::max<std::int64_t>(1, c.pv("amount") >= 0 ? c.pv("amount") + 1 : 1));
  }
  const std::int64_t p = approached ? (e.phase == Phase::Approach ? approach / 2 : 500 + perform / 2) : perform;
  return static_cast<std::int32_t>(std::clamp<std::int64_t>(p, 0, 999));
}

void finish(Ctx& c, GestureExecution& e, ExecOutcome outcome, Cause cause) {
  e.outcome = outcome;
  e.cause = cause;
  c.d.nav.cancel(e.d.actor);
  e.phase = (outcome == ExecOutcome::Done || outcome == ExecOutcome::LimitReached) ? Phase::Finished : Phase::Failed;
  // The body goes back to standing unless the gesture IS the posture.
  if (e.gesture != Gesture::set_posture && e.posture != kPostureStanding) c.set_posture(kPostureStanding);
  ExecutionReport r;
  r.npc = e.d.actor;
  r.gesture = e.gesture;
  r.outcome = outcome;
  r.cause = cause;
  r.tick = c.tick;
  r.started = e.started;
  r.ended = c.now;
  r.cycles = e.cycles;
  r.plan = e.d.plan;
  std::int32_t attempts = 0;
  if (auto* rec = plan_record(c.mind, e.d.plan); rec && e.tracks_plan) {
    const bool step_fail = outcome == ExecOutcome::Failed || outcome == ExecOutcome::Blocked;
    if (outcome == ExecOutcome::Done) {
      rec->i_step_progress = 1000;
      rec->i_step_index += 1000;                     // the step is over: the next one is PLAN.next
      rec->i_attempts = 0;                           // attempts count the failures of ONE step
      const auto steps = c.mind->side.get(rec->i_steps);
      rec->i_status = (rec->i_step_index / 1000 >= static_cast<std::int64_t>(steps.size())) ? kDone : kRunning;
    } else if (step_fail) {
      rec->i_attempts += 1000;
      rec->i_status = kBlocked;                      // a fact seen on the spot, not a comparison with the goal
    }
    attempts = rec->i_attempts / 1000;
  }
  r.attempts = attempts;
  c.out.reports.push_back(r);
  ++c.st.ended[static_cast<std::size_t>(outcome)];
}

Cause cause_of(BodyEvent ev) {
  switch (ev) {
    case BodyEvent::Blow: return Cause::Blow;
    case BodyEvent::Fall: return Cause::Fall;
    case BodyEvent::Unconscious: return Cause::Unconscious;
    case BodyEvent::Seized: return Cause::Seized;
  }
  return Cause::None;
}

void write_progress(const Ctx& c, GestureExecution& e) {
  if (!e.tracks_plan) return;
  if (auto* rec = plan_record(c.mind, e.d.plan)) rec->i_step_progress = static_cast<std::int16_t>(progress_permille(c, e));
}

// The approach: ONE tick of walking toward what the actor believes (or sees), on the route it knows (ExecutorNavigation).
// Returns true when the execution ended during the approach.
bool approach(Ctx& c, GestureExecution& e, const Behavior& b) {
  const EntityId ae = b.approach_entity(e);
  Position goal{};
  bool have = false;
  PerceivedThing p;
  if (ae) {
    p = c.perceive(ae);
    if (p.in_view) { goal = p.at; have = true; e.d.believed_at = p.at; e.d.has_believed_at = true; }
    else if (e.d.has_believed_at) { goal = e.d.believed_at; have = true; }
  }
  if (!have && e.d.has_destination) { goal = e.d.destination; have = true; }
  if (!have && ae == kNoEntity && e.d.has_believed_at) { goal = e.d.believed_at; have = true; }
  if (!have) {   // nothing to walk to: the actor stands where it is; the presence check on the spot does the rest
    e.phase = Phase::Perform;
    e.performing_since = c.now;
    return false;
  }
  const bool away = b.away(c, e);
  // go ... stop_at=sight: the walk ends as soon as the target is seen.
  const bool till_sight = e.gesture == Gesture::go && c.pv("stop_at") == 3;
  if (till_sight && p.in_view) { e.phase = Phase::Perform; e.performing_since = c.now; return false; }
  const std::int32_t stop_within = till_sight ? kArrivedMm : b.stop_within_mm(c, e);
  const std::int32_t reach_mm = static_cast<std::int32_t>(std::int64_t{b.speed_mm_s(c, e)} * kTickRealMs / 1000);
  if (e.approach_total_mm == 0) e.approach_total_mm = std::max<std::int32_t>(1, static_cast<std::int32_t>(c.horizontal_mm(c.me, goal)));
  const MoveStep s = c.d.nav.step(e.d.actor, c.me, goal, reach_mm, stop_within, away);
  if (s.status == MoveStatus::Blocked) {
    e.blocked_seen = true;
    finish(c, e, ExecOutcome::Blocked, Cause::PathBlocked);   // the actor SEES the way closed: a failure on the spot
    return true;
  }
  if (s.status == MoveStatus::Lost) { finish(c, e, ExecOutcome::Failed, Cause::Lost); return true; }
  if (s.moved_mm > 0) {
    const int pace = c.pv("pace");
    const std::uint8_t noise = c.discreet() ? 1 : pace >= 3 ? 5 : pace == 2 ? 3 : 2;
    c.face(goal);
    c.set_posture(e.gesture == Gesture::go && pace == 3 ? kPostureRunning : b.posture(e) != kPostureStanding ? b.posture(e) : kPostureWalking);
    Position to = s.to;
    to[2] = c.me[2];
    c.move_entity(e.d.actor, to, kNoEntity, noise, c.discreet() ? 3 : 7);
    c.me = to;
  }
  e.approach_left_mm = static_cast<std::int32_t>(c.horizontal_mm(s.to, goal));
  if (!away && s.status == MoveStatus::Arrived) {
    e.phase = Phase::Perform;   // the gesture proper starts next tick, with the perception of the place the actor now stands in
    e.performing_since = c.now + kTickGameS;
    c.set_posture(kPostureStanding);
  }
  return false;
}

void advance(GestureExecution& e, Ctx& c) {
  c.e = &e;
  c.k = 0;
  c.mind = c.d.minds.mind(e.d.actor);
  const Behavior& b = behavior_of(e.gesture);
  const EntityStore& store = c.d.store;
  if (!store.alive(e.d.actor)) { e.phase = Phase::Failed; e.cause = Cause::None; e.vanished = true; return; }
  c.me = store.position_mm(e.d.actor);
  e.blocked_seen = false;

  // The body interrupts first (a blow received, a fall, unconsciousness, a hold): hit_react, not a thought.
  if (e.pending_event) {
    // A blow or a hold the model asked to wait for (stop on c_attacked / c_stopped) is the awaited condition, not an interruption.
    if (stops_now(c, e)) { finish(c, e, ExecOutcome::Done, Cause::None); return; }
    finish(c, e, ExecOutcome::Interrupted, cause_of(*e.pending_event));
    return;
  }
  if (c.mind && (!c.mind->state.body.alive || c.mind->state.body.consciousness < kUnconsciousBelow)) {
    finish(c, e, ExecOutcome::Interrupted, Cause::Unconscious);
    return;
  }

  if (e.phase == Phase::Pending) {
    e.phase = b.needs_approach(c, e) ? Phase::Approach : Phase::Perform;
    e.performing_since = c.now;
  }
  const GestureTiming& t = timing_of(e.gesture);

  // 1. and 2. the stop of the gesture (until) or of the decision, read in the actor's perception.
  if (stops_now(c, e)) { finish(c, e, ExecOutcome::Done, Cause::None); return; }

  if (e.phase == Phase::Approach) {
    social::Exertion x = social::Exertion::kWalking;   // walking to the place of the gesture
    if (e.gesture == Gesture::climb || e.gesture == Gesture::swim) x = social::Exertion::kHeavyWork;
    else if (e.gesture == Gesture::go && c.pv("pace") == 3) x = social::Exertion::kRunning;
    c.out.exertion.push_back({e.d.actor, x});
    if (approach(c, e, b)) return;
    write_progress(c, e);
    return;
  }

  // The gesture has had no effect for several cycles in a row (reported by the laws of matter): the actor feels it on the spot.
  if (e.no_effect >= kNoEffectCycles) { finish(c, e, ExecOutcome::Failed, Cause::NothingHappened); return; }

  // PERFORM. On the spot: the actor perceives whether what it came for is there; if it is not, the gesture fails HERE.
  // (What the actor holds in its own hands needs no sight to be there.)
  if (const EntityId pe = b.presence_entity(e);
      pe != kNoEntity && !(e.gesture == Gesture::go && b.away(c, e)) && c.d.store.holder(pe) != e.d.actor) {
    const PerceivedThing p = c.perceive(pe);
    if (!p.in_view) { finish(c, e, ExecOutcome::Failed, Cause::TargetAbsent); return; }
    // It moved while the actor was working: walk to it again rather than strike the air.
    if (e.gesture != Gesture::go && c.horizontal_mm(c.me, p.at) > b.stop_within_mm(c, e) + kArrivedMm * 2 && b.needs_approach(c, e)) {
      e.d.believed_at = p.at;
      e.d.has_believed_at = true;
      e.phase = Phase::Approach;
      e.approach_total_mm = 0;
      if (approach(c, e, b)) return;
      write_progress(c, e);
      return;
    }
  }
  c.out.exertion.push_back({e.d.actor, b.exertion(e)});
  c.set_posture(b.posture(e));

  // The cycles that complete in this tick (cadence_ms of real time each).
  const std::uint32_t n = e.clock.advance(t.cadence_ms);
  const bool chosen = e.limit_is_chosen;
  for (std::uint32_t i = 0; i < n; ++i) {
    const CycleResult r = b.cycle(c);
    ++e.cycles;
    ++c.st.cycles;
    if (r.fail) { finish(c, e, r.outcome, r.cause); return; }
    if (stops_now(c, e)) { finish(c, e, ExecOutcome::Done, Cause::None); return; }
    // 3. natural_end: the gesture finishes by itself (not when the model chose how long it lasts).
    if ((r.end || (t.natural_end && !chosen)) && (r.end || b.complete(c, e))) { finish(c, e, ExecOutcome::Done, Cause::None); return; }
  }
  // 4. the bound: a_while for a gesture that nothing stops, or the duration the model chose.
  if (e.limit_s > 0 && c.now + kTickGameS - e.performing_since >= e.limit_s) {
    finish(c, e, chosen ? ExecOutcome::Done : ExecOutcome::LimitReached, Cause::None);
    return;
  }
  write_progress(c, e);
}

}  // namespace
}  // namespace detail

// =================================================================================================================================
const char* to_string(ExecOutcome o) {
  switch (o) {
    case ExecOutcome::Done: return "done";
    case ExecOutcome::Failed: return "failed";
    case ExecOutcome::Blocked: return "blocked";
    case ExecOutcome::Interrupted: return "interrupted";
    case ExecOutcome::LimitReached: return "limit_reached";
  }
  return "?";
}

ExecutorVars::ExecutorVars() {
  auto find = [](std::string_view name) -> std::uint16_t {
    for (const auto& fields : gen::kKindFields)
      for (const auto& f : fields)
        if (f.name == name) return f.var;
    return 0xFFFF;
  };
  hunger = find("hunger");
  thirst = find("thirst");
  exhaustion = find("exhaustion");
  sleepiness = find("sleepiness");
  posture = find("posture");
  orientation = find("orientation");
  water_volume = find("water_volume");
}

GestureExecutor::GestureExecutor(const EntityStore& store, const ContactResolver& resolver, const ActorSenses& senses,
                                 ExecutorNavigation& navigation, const social::Governor& governor, const MindAccess& minds,
                                 const IngestTable& ingest, ExecutorConfig cfg)
    : deps_(std::make_unique<detail::Deps>(store, resolver, senses, navigation, governor, minds, ingest)), cfg_(cfg) {}

GestureExecutor::~GestureExecutor() = default;

BeginResult GestureExecutor::begin(const GestureDecision& dec, social::GameTime now, std::uint64_t tick) {
  using namespace detail;
  BeginResult res;
  const std::size_t gi = static_cast<std::size_t>(dec.call.gesture);
  auto live = [](const std::optional<StopCondition>& s) { return !s || social::condition_is_live(s->cond); };
  if (gi >= kGestureCount || !deps_->store.alive(dec.actor) || deps_->store.kind(dec.actor) != gen::EntityKind::agent || !live(dec.until) ||
      !live(dec.stop)) {
    ++stats_.invalid;
    res.status = BeginStatus::Invalid;
    return res;
  }
  // The governor first (D10). A gesture whose content is an expression (speak, write) is judged without its content here:
  // the content is judged once, with its real hearers, by the SpeechRouter.
  const auto& spec = social::gen::kGestures[gi];
  social::GestureCall call = dec.call;
  bool executed = true, has_content = dec.content != 0;
  for (int p = 0; p < spec.n_params; ++p)
    if (spec.params[static_cast<std::size_t>(p)].type == social::gen::ParamType::expression && call.value[static_cast<std::size_t>(p)] >= 0) {
      call.value[static_cast<std::size_t>(p)] = -1;
      executed = false;
      has_content = true;
    }
  res.verdict = deps_->governor.check_gesture(call, &dec.actor_party, executed);
  // D10 on the CONTENT: the executor does not judge words, it requires the verdict of check_utterance (SpeechRouter, T24).
  if (res.verdict.allowed && has_content && !(dec.content_verdict && dec.content_verdict->allowed)) {
    res.verdict = dec.content_verdict ? *dec.content_verdict : social::Verdict{false, 0, social::Reason::structured};
    res.verdict.allowed = false;
  }
  // The model chose a gesture: the one in progress ends here, explicitly (also when the new one is refused).
  auto end_previous = [&] {
    auto it = running_.find(dec.actor);
    if (it == running_.end()) return;
    const GestureExecution& old = it->second;
    ExecutionReport r;
    r.npc = old.d.actor;
    r.gesture = old.gesture;
    r.outcome = ExecOutcome::Interrupted;
    r.cause = Cause::Replaced;
    r.tick = tick;
    r.started = old.started;
    r.ended = now;
    r.cycles = old.cycles;
    r.plan = old.d.plan;
    refused_.push_back(r);   // queued reports leave with the next step
    deps_->nav.cancel(dec.actor);
    running_.erase(it);
  };
  if (!res.verdict.allowed) {
    ++stats_.refused;
    res.status = BeginStatus::Refused;
    end_previous();
    ExecutionReport r;
    r.npc = dec.actor;
    r.gesture = dec.call.gesture;
    r.outcome = ExecOutcome::Failed;
    r.cause = Cause::Refused;
    r.started = r.ended = now;
    r.tick = tick;
    r.plan = dec.plan;
    r.refused = true;
    r.refusal = res.verdict.reason;
    refused_.push_back(r);
    return res;
  }
  end_previous();

  GestureExecution e;
  e.d = dec;
  e.d.call.party.fill(nullptr);   // the pointers were valid for the check only
  e.gesture = dec.call.gesture;
  e.started = now;
  e.started_tick = tick;
  e.performing_since = now;

  // The plan: facts only. The chosen gesture is PLAN.next -> running; any other running plan of the actor -> suspended.
  if (social::NpcBundle* m = deps_->minds.mind(dec.actor)) {
    social::gen::Intention* mine = plan_record(m, dec.plan);
    e.tracks_plan = mine && is_plan_next(*m, *mine, dec, deps_->gesture_word[gi]);
    m->state.intention_records.for_each([&](social::MRef r, social::gen::Intention& rec) {
      if (rec.i_status == kRunning && !(e.tracks_plan && r.serial == dec.plan.serial)) rec.i_status = kSuspended;
    });
    if (e.tracks_plan) {
      mine->i_status = kRunning;
      mine->i_step_started = now;
      mine->i_step_progress = 0;
    }
  }

  // How long: a chosen duration is the bound; with nothing to stop it the gesture stops at a_while (limit_reached).
  const GestureTiming& t = timing_of(e.gesture);
  int di = param_index(e.gesture, "duration");
  if (di < 0) di = param_index(e.gesture, "thoroughness");
  const int level = di >= 0 ? dec.call.value[static_cast<std::size_t>(di)] : -1;
  if (level >= 0) {
    e.limit_s = duration_level_game_s(level);
    e.limit_is_chosen = true;
  } else if (!t.natural_end && !dec.until && !dec.stop) {
    e.limit_s = duration_level_game_s(kLevelAWhile);
  }
  running_[dec.actor] = std::move(e);
  ++stats_.begun;
  return res;
}

void GestureExecutor::contact_results(std::span<const Contact> contacts, std::span<const LawReport> reports) {
  const gen::EntityKind person = gen::EntityKind::agent;
  for (std::size_t i = 0; i < contacts.size() && i < reports.size(); ++i) {
    auto it = running_.find(contacts[i].author);
    if (it == running_.end()) continue;
    const EntityId t = contacts[i].target;
    // Blows on a body are the body model's business (damage, T34): "no effect" on a person or a beast is not a fact the laws of matter can state.
    const bool body = t != kNoEntity && (deps_->store.kind(t) == person || deps_->store.kind(t) == gen::EntityKind::animal);
    if (reports[i].outcome == Outcome::NoEffect && !body) ++it->second.no_effect;
    else it->second.no_effect = 0;
  }
}

void GestureExecutor::notify(EntityId actor, BodyEvent event) {
  auto it = running_.find(actor);
  if (it != running_.end() && !it->second.pending_event) it->second.pending_event = event;
}

bool GestureExecutor::on_wake(EntityId, perception::WakePriority) { return false; }   // a wake calls the model; the body stops nothing

const GestureExecution* GestureExecutor::find(EntityId actor) const {
  auto it = running_.find(actor);
  return it == running_.end() ? nullptr : &it->second;
}

const StepOutput& GestureExecutor::step(std::uint64_t tick, social::GameTime now) {
  using namespace detail;
  out_.clear();
  for (ExecutionReport& r : refused_) {
    r.tick = tick;
    out_.reports.push_back(r);
  }
  refused_.clear();
  std::vector<GestureExecution*> list;
  list.reserve(running_.size());
  for (auto& [id, e] : running_) list.push_back(&e);
  const std::size_t n = list.size();
  const unsigned parts_n = static_cast<unsigned>(std::max<std::size_t>(1, std::min<std::size_t>(cfg_.threads, n / std::max<std::size_t>(1, cfg_.min_per_thread))));
  struct Part {
    StepOutput out;
    ExecutorStats st;
  };
  std::vector<Part> parts(parts_n);
  auto run = [&](unsigned i) {
    const std::size_t lo = n * i / parts_n, hi = n * (i + 1) / parts_n;
    for (std::size_t j = lo; j < hi; ++j) {
      Ctx c(*deps_, tick, now, parts[i].out, parts[i].st);
      advance(*list[j], c);
    }
  };
  if (parts_n == 1) {
    run(0);
  } else {
    std::vector<std::thread> pool;
    for (unsigned i = 1; i < parts_n; ++i) pool.emplace_back(run, i);
    run(0);
    for (auto& t : pool) t.join();
  }
  for (Part& p : parts) {   // merged in actor order: the same bytes for any number of threads
    auto append = [](auto& dst, auto& src) { dst.insert(dst.end(), std::make_move_iterator(src.begin()), std::make_move_iterator(src.end())); };
    append(out_.emissions, p.out.emissions);
    append(out_.contacts, p.out.contacts);
    append(out_.reports, p.out.reports);
    append(out_.exertion, p.out.exertion);
    stats_.cycles += p.st.cycles;
    stats_.contacts += p.st.contacts;
    stats_.emissions += p.st.emissions;
    for (int i = 0; i < 5; ++i) stats_.ended[i] += p.st.ended[i];
  }
  stats_.steps += n;
  for (auto it = running_.begin(); it != running_.end();)
    it = (it->second.phase == Phase::Finished || it->second.phase == Phase::Failed) ? running_.erase(it) : std::next(it);
  return out_;
}

std::uint64_t StepOutput::digest() const {
  std::uint64_t h = 1469598103934665603ull;
  auto mix = [&](std::uint64_t v) {
    for (int i = 0; i < 8; ++i) { h ^= (v >> (8 * i)) & 0xFF; h *= 1099511628211ull; }
  };
  std::vector<std::uint8_t> bytes;
  for (const Emission& e : emissions) {
    bytes.clear();
    ops::encode(e.op, bytes);
    for (std::uint8_t b : bytes) { h ^= b; h *= 1099511628211ull; }
    mix(e.decision_seq);
    mix(e.k);
  }
  for (const Contact& c : contacts) {
    mix(c.author); mix(c.decision_seq); mix(c.tool); mix(c.target); mix(c.other); mix(static_cast<std::uint64_t>(c.manner));
    mix(static_cast<std::uint64_t>(c.speed_mm_s)); mix(c.at_joint); mix(c.productive);
  }
  for (const ExecutionReport& r : reports) {
    mix(r.npc); mix(static_cast<std::uint64_t>(r.gesture)); mix(static_cast<std::uint64_t>(r.outcome)); mix(static_cast<std::uint64_t>(r.cause));
    mix(r.tick); mix(static_cast<std::uint64_t>(r.started)); mix(static_cast<std::uint64_t>(r.ended)); mix(r.cycles);
    mix(static_cast<std::uint64_t>(r.attempts)); mix(r.refused);
  }
  for (const ExertionFact& x : exertion) { mix(x.npc); mix(static_cast<std::uint64_t>(x.exertion)); }
  return h;
}

ops::ApplyStatus NpcNeedsApplier::apply(const ops::Operation& op) {
  if (op.op_kind() != ops::OpKind::EntityDelta) return ops::ApplyStatus::Ignored;
  ops::PayloadReader r(op.payload);
  std::uint32_t entity = 0;
  std::uint16_t var = 0;
  std::int32_t old_v = 0, new_v = 0;
  if (!(r.u32(entity) && r.u16(var) && r.i32(old_v) && r.i32(new_v))) return ops::ApplyStatus::Ignored;
  if (var != vars_.hunger && var != vars_.thirst && var != vars_.exhaustion && var != vars_.sleepiness) return ops::ApplyStatus::Ignored;
  social::NpcBundle* m = minds_.mind(entity);
  std::int64_t stored = 0;
  if (!m || !store_.read_var(entity, var, stored) || stored != new_v) return ops::ApplyStatus::Ignored;   // the store refused it, or no mind
  auto& needs = m->state.needs;
  const auto v = static_cast<std::int16_t>(new_v);
  if (var == vars_.hunger) needs.hunger = v;
  else if (var == vars_.thirst) needs.thirst = v;
  else if (var == vars_.exhaustion) needs.exhaustion = v;
  else needs.sleepiness = v;
  return ops::ApplyStatus::Applied;
}

}  // namespace em::act
