// Navigator: the NavigationQuery and NavigationFeed of T23b. Holds one MentalMap and one journey per NPC. The only
// consultation of the world is the ViewProbe, asked about points within `view_mm` of the NPC (the rest of the route is
// planned on the mental map alone).
#pragma once
#include <cstdint>
#include <vector>

#include "emergence/act/navigation/navigation_query.h"
#include "emergence/act/navigation/route_planner.h"
#include "emergence/act/navigation/view_probe.h"

namespace em::act::navigation {

struct NavigatorConfig {
  std::int32_t view_mm = 24'000;       // how far the NPC sees an obstacle
  std::int32_t reach_mm = 8'000;       // a road node / waypoint counts as reached within this
  std::uint8_t max_replans = 6;        // closed ways met on one journey before it fails on the spot
  std::int32_t max_detour_mm = 300'000;// walked beside an obstacle in view before the crossing is held closed
  PlannerLimits planner{};
};

class Navigator final : public NavigationQuery, public NavigationFeed {
 public:
  Navigator(const RoadPlan* roads, const ViewProbe& probe, NavigatorConfig cfg = {});

  // Registers an NPC (not thread-safe: do it before the parallel steps). Returns its map.
  MentalMap& add_npc(EntityId npc);
  MentalMap* map(EntityId npc);
  const MentalMap* map(EntityId npc) const;
  std::size_t npc_count() const { return slots_.size(); }

  // ---- save (T04): the live map is HERE, not in the bundle. Call sync_to_bundle(npc, bundle.mental_map) before every save
  // (it also feeds the bundle fingerprint) and sync_from_bundle after a load. The journey is not saved: on resume the NPC
  // replans from its map (same destination, same knowledge), which is documented and tested.
  bool sync_to_bundle(EntityId npc, std::vector<std::uint8_t>& bytes) const;
  bool sync_from_bundle(EntityId npc, const std::vector<std::uint8_t>& bytes);   // not thread-safe (registers the NPC)

  NavStep next_step(EntityId npc, const NavRequest& req) override;
  void cancel(EntityId npc) override;

  void see_position(EntityId npc, const Position& p) override;
  void see_place(EntityId npc, PlaceKey key, const Position& p, std::uint16_t day) override;
  void hear_place(EntityId npc, PlaceKey key, const Position& p, std::uint8_t certainty, std::uint16_t day) override;
  void hear_segment(EntityId npc, int segment) override;
  void hear_obstacle(EntityId npc, const Position& a, const Position& b, std::uint16_t day) override;
  bool believed_place(EntityId npc, PlaceKey key, std::uint16_t day, Position& pos, std::uint8_t& certainty) const override;

 private:
  struct Journey {
    bool active = false;
    Position target{};
    Plan plan;
    std::uint16_t cursor = 0;
    std::uint16_t tail = 0;            // from this step on, every step is unknown ground
    std::int32_t leg_from = kNoTile;   // the tile the current leg started from
    std::uint8_t replans = 0;
    std::int32_t detour_mm = 0;        // walked beside the obstacle in view
    Position last_at{};
    bool has_last = false;
    std::int8_t side = 1;              // the side the last avoidance took (sticky)
  };
  struct Slot { EntityId id; MentalMap map; Journey journey; };

  Slot* find(EntityId id);
  const Slot* find(EntityId id) const;
  bool replan(Slot& s, const NavRequest& req, std::int32_t from_tile);
  Position waypoint_of(const Journey& j, std::size_t index) const;
  // A leg of at most the view distance toward `goal`, or a sidestep around what is seen; false if every try is closed.
  bool clear_leg(const Position& at, const Position& goal, Journey& j, Position& out) const;

  const RoadPlan* roads_;
  const ViewProbe& probe_;
  NavigatorConfig cfg_;
  RoutePlanner planner_;
  std::vector<Slot> slots_;   // sorted by id
};

}  // namespace em::act::navigation
