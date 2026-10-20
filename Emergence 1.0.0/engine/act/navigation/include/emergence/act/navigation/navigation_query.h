// NavigationQuery: what the gesture executor (T22) asks to move an NPC, and NavigationFeed: how perception (T23) and
// speech (T24) feed the mental map. Both are implemented by Navigator (navigator.h). The rule (P51): a move uses what the
// NPC knows; a failure is reported only ON THE SPOT, once the obstacle is in view.
#pragma once
#include <cstdint>

#include "emergence/act/entity_id.h"
#include "emergence/act/navigation/mental_map.h"

namespace em::act::navigation {

enum class NavStatus : std::uint8_t {
  Moving,     // walk to `waypoint`
  Exploring,  // same, but into ground the NPC has never walked (it follows its belief)
  Arrived,    // within `arrive_mm` of the believed target
  Blocked,    // (never from afar, never for an unregistered NPC or a missing route: those explore) the way is closed AS SEEN from where the NPC stands (never reported from afar): the executor fails `blocked`
};

struct NavRequest {
  Position at;                    // where the NPC is (its own body, not a belief)
  Position target;                // where the NPC BELIEVES the target is (from its dossiers)
  std::int32_t arrive_mm = 1500;  // arrival distance
  std::uint16_t day = 0;          // game day (obstacle expiry, fading of places)
};

struct NavStep {
  NavStatus status = NavStatus::Moving;
  Position waypoint{};            // the next point to walk to (a short leg inside the view when avoiding)
  std::int64_t remaining_mm = 0;  // straight distance to the believed target
  std::uint8_t replans = 0;       // replans on this journey: a route found closed on the spot
};

class NavigationQuery {
 public:
  virtual ~NavigationQuery() = default;
  // The next step of `npc` toward the believed target. The journey is kept between calls and replanned when the target
  // changes or an obstacle is met. Called once per NPC at a time; distinct NPCs may be called from several threads.
  virtual NavStep next_step(EntityId npc, const NavRequest& req) = 0;
  // The NPC drops its journey (gesture finished or interrupted).
  virtual void cancel(EntityId npc) = 0;
};

class NavigationFeed {
 public:
  virtual ~NavigationFeed() = default;
  virtual void see_position(EntityId npc, const Position& p) = 0;
  virtual void see_place(EntityId npc, PlaceKey key, const Position& p, std::uint16_t day) = 0;
  virtual void hear_place(EntityId npc, PlaceKey key, const Position& p, std::uint8_t certainty, std::uint16_t day) = 0;
  virtual void hear_segment(EntityId npc, int segment) = 0;
  virtual void hear_obstacle(EntityId npc, const Position& a, const Position& b, std::uint16_t day) = 0;
  // The believed position of a place, if the NPC knows it (and its present certainty).
  virtual bool believed_place(EntityId npc, PlaceKey key, std::uint16_t day, Position& pos, std::uint8_t& certainty) const = 0;
};

}  // namespace em::act::navigation
