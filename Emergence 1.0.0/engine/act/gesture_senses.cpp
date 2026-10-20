#include "gesture_senses.h"

#include <algorithm>

#include "emergence/act/perception/trig.h"

namespace em::act {
namespace {
// Value indices of the enumerations of perception.toml.
constexpr std::uint8_t kCondDown = 2, kCondMotionless = 3, kCondDead = 4;
constexpr std::uint8_t kPostureKneeling = 4, kPostureLying = 6, kPostureProne = 7;
constexpr std::uint8_t kMotionStill = 0, kMotionLeaving = 2;

// Where the actor SEES a thing: its own position, its facing, and the bearing and distance KEPT in the percept (blurred by the
// perception like everything else). The true position of the thing is never read.
Position apparent_position(const EntityStore& store, EntityId actor, std::uint32_t packed_dir, std::int32_t dist_mm) {
  Position me = store.position_mm(actor);
  std::int32_t facing = 0;
  if (const auto* sp = store.component<gen::Spatial>(actor)) facing = sp->orientation;
  const std::int16_t sn = static_cast<std::int16_t>(packed_dir >> 16), cs = static_cast<std::int16_t>(packed_dir & 0xFFFFu);
  const std::int32_t angle = perception::wrap_angle(std::int64_t{facing} + perception::atan2_mrad(sn, cs));
  me[0] += static_cast<std::int32_t>(std::int64_t{perception::cos_milli(angle)} * dist_mm / 1000);
  me[1] += static_cast<std::int32_t>(std::int64_t{perception::sin_milli(angle)} * dist_mm / 1000);
  return me;
}

const perception::Binding* binding_of(perception::Observer& o, EntityId what) {
  auto& b = o.memory().bindings;
  auto it = std::lower_bound(b.begin(), b.end(), what, [](const perception::Binding& x, EntityId e) { return x.entity < e; });
  return (it != b.end() && it->entity == what) ? &*it : nullptr;
}
}  // namespace

ObserverSenses::ObserverSenses(const EntityStore& store, std::vector<perception::Observer>& observers) : store_(store) {
  for (auto& o : observers) by_entity_.push_back(&o);
  std::sort(by_entity_.begin(), by_entity_.end(), [](auto* a, auto* b) { return a->entity() < b->entity(); });
}

perception::Observer* ObserverSenses::find(EntityId actor) const {
  auto it = std::lower_bound(by_entity_.begin(), by_entity_.end(), actor, [](auto* o, EntityId e) { return o->entity() < e; });
  return (it != by_entity_.end() && (*it)->entity() == actor) ? *it : nullptr;
}

PerceivedThing ObserverSenses::perceive(EntityId actor, EntityId what) const {
  PerceivedThing out;
  perception::Observer* o = find(actor);
  if (!o || !store_.alive(what)) return out;
  const perception::Binding* bd = binding_of(*o, what);
  if (!bd) return out;
  out.in_view = true;
  out.dist_mm = bd->last_dist_mm;
  out.at = store_.position_mm(actor);
  if (bd->ep_serial) {
    if (const auto* r = o->mind().state.entity_percept_records.find({bd->ep_serial})) {
      out.dist_mm = r->ep_dist;
      out.at = apparent_position(store_, actor, static_cast<std::uint32_t>(r->ep_dir), r->ep_dist);
      out.down = r->ep_condition == kCondDown || r->ep_posture == kPostureLying || r->ep_posture == kPostureProne;
      out.dead_obvious = r->ep_condition == kCondDead;
      out.still = r->ep_condition == kCondMotionless || out.dead_obvious || r->ep_motion == kMotionStill;
      out.yields = out.down || r->ep_posture == kPostureKneeling || r->ep_motion == kMotionLeaving;
    }
  }
  if (bd->pc_serial && !bd->ep_serial) {
    if (const auto* r = o->mind().state.percept_records.find({bd->pc_serial})) {
      out.dist_mm = r->pc_dist;
      out.at = apparent_position(store_, actor, static_cast<std::uint32_t>(r->pc_dir), r->pc_dist);
    }
  }
  return out;
}

bool ObserverSenses::sees_kind(EntityId actor, std::uint32_t kind_symbol) const {
  perception::Observer* o = find(actor);
  if (!o) return false;
  // Only what the last scan perceived counts: a binding older than the freshest one is a thing no longer in view.
  social::GameTime latest = 0;
  for (const auto& bd : o->memory().bindings) latest = std::max(latest, bd.last_seen);
  for (const auto& bd : o->memory().bindings) {
    if (!bd.pc_serial || bd.last_seen != latest) continue;
    if (const auto* p = o->mind().state.percept_records.find({bd.pc_serial}); p && p->pc_kind_seen == kind_symbol) return true;
  }
  return false;
}

bool ObserverSenses::hears(EntityId actor, std::uint32_t concept_word) const {
  // A sound heard is an event_seen of sense "heard" (ev_sense 1); its ev_gesture is the word of what was heard (a cry, a step,
  // speech). concept_word 0 = any sound.
  perception::Observer* o = find(actor);
  if (!o) return false;
  bool found = false;
  o->mind().state.event_seen_records.for_each([&](social::MRef, social::gen::EventSeen& e) {
    found |= (e.ev_sense == 1 && (concept_word == 0 || e.ev_gesture == concept_word));
  });
  return found;
}

bool ObserverSenses::addressed(EntityId actor) const {
  perception::Observer* o = find(actor);
  if (!o) return false;
  return o->mind().state.beliefs.heard_unprocessed != 0;   // something was said to the actor and waits to be read
}

bool ObserverSenses::attacked(EntityId) const { return false; }   // a blow arrives as a BodyEvent::Blow (hit_react)

bool ObserverSenses::state_seen(EntityId actor, EntityId what, std::uint32_t state_word) const {
  perception::Observer* o = find(actor);
  if (!o) return false;
  const perception::Binding* bd = binding_of(*o, what);
  if (!bd || !bd->pc_serial) return false;
  const auto* r = o->mind().state.percept_records.find({bd->pc_serial});
  if (!r) return false;
  for (std::uint32_t w : o->mind().side.get(r->pc_state_seen))
    if (w == state_word) return true;
  return false;
}

std::int32_t ObserverSenses::have_count(EntityId actor, std::uint32_t kind) const {
  perception::Observer* o = find(actor);
  if (!o) return 0;
  std::int32_t n = 0;
  for (std::uint32_t k : o->mind().side.get(o->mind().state.beliefs.own_held_seen)) n += (k == kind);
  return n;
}

bool ObserverSenses::unwatched(EntityId actor) const {
  perception::Observer* o = find(actor);
  if (!o) return true;
  bool watched = false;
  // A person seen looking at one of the actor's own records counts as watching (ep_gaze set).
  o->mind().state.entity_percept_records.for_each([&](social::MRef, social::gen::EntityPercept& e) { watched |= (e.ep_gaze.serial != 0); });
  return !watched;
}

}  // namespace em::act
