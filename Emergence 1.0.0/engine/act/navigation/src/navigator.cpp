#include "emergence/act/navigation/navigator.h"

#include <algorithm>

#include "emergence/act/navigation/mental_map_codec.h"

namespace em::act::navigation {

Navigator::Navigator(const RoadPlan* roads, const ViewProbe& probe, NavigatorConfig cfg)
    : roads_(roads), probe_(probe), cfg_(cfg), planner_(roads, cfg.planner) {}

Navigator::Slot* Navigator::find(EntityId id) {
  auto it = std::lower_bound(slots_.begin(), slots_.end(), id, [](const Slot& s, EntityId v) { return s.id < v; });
  return it != slots_.end() && it->id == id ? &*it : nullptr;
}
const Navigator::Slot* Navigator::find(EntityId id) const { return const_cast<Navigator*>(this)->find(id); }

MentalMap& Navigator::add_npc(EntityId npc) {
  auto it = std::lower_bound(slots_.begin(), slots_.end(), npc, [](const Slot& s, EntityId v) { return s.id < v; });
  if (it == slots_.end() || it->id != npc) it = slots_.insert(it, Slot{npc, MentalMap{}, Journey{}});
  return it->map;
}
MentalMap* Navigator::map(EntityId npc) { Slot* s = find(npc); return s ? &s->map : nullptr; }
const MentalMap* Navigator::map(EntityId npc) const { const Slot* s = find(npc); return s ? &s->map : nullptr; }

bool Navigator::sync_to_bundle(EntityId npc, std::vector<std::uint8_t>& bytes) const {
  const Slot* s = find(npc);
  if (!s) return false;
  MentalMapCodec::store(s->map, bytes);
  return true;
}
bool Navigator::sync_from_bundle(EntityId npc, const std::vector<std::uint8_t>& bytes) {
  MentalMap loaded;
  if (!MentalMapCodec::load(bytes, loaded)) return false;   // refused: the live map is left as it was
  add_npc(npc);
  Slot* s = find(npc);
  s->map = loaded;
  s->journey = Journey{};   // the journey is NOT saved: the NPC replans from what it knows when it resumes
  return true;
}

void Navigator::cancel(EntityId npc) { if (Slot* s = find(npc)) s->journey = Journey{}; }

Position Navigator::waypoint_of(const Journey& j, std::size_t index) const {
  if (index >= j.tail) return j.target;   // nothing known beyond: walk the believed direction, not tile centres
  const RouteStep& st = j.plan.steps[index];
  if (st.segment >= 0 && roads_) {
    const auto& seg = roads_->segment(st.segment);
    return clamped_tile_of(roads_->node(seg.b)) == st.tile ? roads_->node(seg.b) : roads_->node(seg.a);
  }
  return tile_center(st.tile);
}

bool Navigator::replan(Slot& s, const NavRequest& req, std::int32_t from_tile) {
  Journey& j = s.journey;
  j.plan = planner_.plan(s.map, req.day, req.at, j.target);
  j.cursor = 0;
  j.leg_from = from_tile;
  j.detour_mm = 0; j.has_last = false;
  j.tail = j.plan.count;
  while (j.tail > 0 && j.plan.steps[std::size_t(j.tail) - 1].unknown) --j.tail;
  return j.plan.status == PlanStatus::Found;
}

bool Navigator::clear_leg(const Position& at, const Position& goal, Journey& j, Position& out) const {
  const std::int64_t dist = distance_mm(at, goal);
  if (dist == 0) { out = goal; return true; }
  const std::int64_t dx = goal[0] - at[0], dy = goal[1] - at[1];
  auto point = [&](std::int64_t fwd, std::int64_t lat) {   // fwd along the heading, lat to the left, both in mm
    return Position{std::int32_t(at[0] + (dx * fwd - dy * lat) / dist), std::int32_t(at[1] + (dy * fwd + dx * lat) / dist), at[2]};
  };
  const std::int64_t look = std::min<std::int64_t>(dist, cfg_.view_mm);
  if (!probe_.blocked(at, point(look, 0))) { j.detour_mm = 0; j.has_last = false; out = goal; return true; }
  // The detour is bounded by the distance actually walked beside the obstacle, not by the number of calls.
  if (j.has_last) j.detour_mm += std::int32_t(distance_mm(at, j.last_at));
  j.last_at = at; j.has_last = true;
  if (j.detour_mm >= cfg_.max_detour_mm) return false;
  // Something blocks the way within view: try a short leg beside it, on the side taken last time first.
  const std::int64_t half = cfg_.view_mm / 2;
  const std::int64_t fwd_full = std::min<std::int64_t>(dist, half);
  for (std::int64_t off = half / 4; off <= half; off *= 2)
    for (std::int64_t fwd : {fwd_full, fwd_full / 2, std::int64_t(0)})
      for (int k = 0; k < 2; ++k) {
        const int sgn = k == 0 ? j.side : -j.side;
        const Position q = point(fwd, sgn * off);
        if (probe_.blocked(at, q)) continue;
        j.side = std::int8_t(sgn);
        out = q;
        return true;
      }
  return false;
}

NavStep Navigator::next_step(EntityId npc, const NavRequest& req) {
  NavStep r;
  r.waypoint = req.at;
  Slot* s = find(npc);
  if (!s) {   // not registered: nothing is known, so it follows its belief; "blocked" is only ever said on the spot, in view of the obstacle
    r.status = NavStatus::Exploring;
    r.waypoint = req.target;
    r.remaining_mm = distance_mm(req.at, req.target);
    return r;
  }
  MentalMap& m = s->map;
  Journey& j = s->journey;
  m.see_position(req.at);
  r.remaining_mm = distance_mm(req.at, req.target);
  if (r.remaining_mm <= req.arrive_mm) { j = Journey{}; r.status = NavStatus::Arrived; return r; }

  const std::int32_t here = clamped_tile_of(req.at);
  if (!j.active || j.target != req.target) {
    j = Journey{};
    j.active = true;
    j.target = req.target;
    replan(*s, req, here);   // no plan (unreachable / over budget): it walks toward its belief and explores; the verdict is for the spot
  } else if (j.plan.status != PlanStatus::Found && here != j.leg_from) {
    replan(*s, req, here);   // retry from the new tile: what it has seen since may have changed the picture
  }

  for (;;) {   // each pass either returns or counts one more closed way: bounded by max_replans
    // Reached steps: a road node within reach, or (for a plain step) being in the tile of this step or a later one.
    for (int i = int(j.plan.count) - 1; i >= int(j.cursor); --i) {
      const RouteStep& st = j.plan.steps[std::size_t(i)];
      const bool in_tile = st.segment < 0 && st.tile == here;
      bool near = false;
      if (st.segment >= 0 && roads_) {
        near = distance_mm(req.at, waypoint_of(j, std::size_t(i))) <= cfg_.reach_mm;
      }
      if (in_tile || near) {
        for (int k = int(j.cursor); k <= i; ++k)
          if (j.plan.steps[std::size_t(k)].segment >= 0) m.see_segment(j.plan.steps[std::size_t(k)].segment);   // walked it
        j.cursor = std::uint16_t(i + 1);
        j.leg_from = st.tile;
        j.detour_mm = 0; j.has_last = false;
        break;
      }
    }
    const Position goal = waypoint_of(j, j.cursor);
    Position wp;
    if (clear_leg(req.at, goal, j, wp)) {
      // Seen open: a told obstacle on the crossing that this leg takes is disproved (hearsay is checked by the eyes).
      if (j.cursor < j.plan.count && distance_mm(req.at, goal) <= cfg_.view_mm)
        m.disprove_obstacle(j.leg_from, std::int32_t(j.plan.steps[j.cursor].tile));
      r.waypoint = wp;
      r.replans = j.replans;
      r.status = (j.plan.status != PlanStatus::Found || (j.cursor < j.plan.count && j.plan.steps[j.cursor].unknown)) ? NavStatus::Exploring : NavStatus::Moving;
      return r;
    }
    // The way is closed AS SEEN from here (the obstacle is within the view distance): learn it, then replan or fail on the spot.
    const std::int32_t next = j.cursor < j.plan.count ? std::int32_t(j.plan.steps[j.cursor].tile) : clamped_tile_of(j.target);
    m.see_obstacle(j.leg_from, next, req.day);
    // (the obstacle is in view here: failing is allowed)
    if (++j.replans > cfg_.max_replans || !replan(*s, req, here)) {
      r.replans = j.replans;
      j = Journey{};
      r.status = NavStatus::Blocked;
      return r;
    }
  }
}

void Navigator::see_position(EntityId npc, const Position& p) { if (Slot* s = find(npc)) s->map.see_position(p); }
void Navigator::see_place(EntityId npc, PlaceKey key, const Position& p, std::uint16_t day) { if (Slot* s = find(npc)) s->map.see_place(key, p, day); }
void Navigator::hear_place(EntityId npc, PlaceKey key, const Position& p, std::uint8_t certainty, std::uint16_t day) {
  if (Slot* s = find(npc)) s->map.hear_place(key, p, certainty, day);
}
void Navigator::hear_segment(EntityId npc, int segment) { if (Slot* s = find(npc)) s->map.hear_segment(segment); }
void Navigator::hear_obstacle(EntityId npc, const Position& a, const Position& b, std::uint16_t day) {
  if (Slot* s = find(npc)) s->map.hear_obstacle(clamped_tile_of(a), clamped_tile_of(b), day);
}
bool Navigator::believed_place(EntityId npc, PlaceKey key, std::uint16_t day, Position& pos, std::uint8_t& certainty) const {
  const Slot* s = find(npc);
  const MentalMap::Place* p = s ? s->map.place(key) : nullptr;
  if (!p) return false;
  pos = {p->x, p->y, 0};
  certainty = s->map.place_certainty(*p, day);
  return true;
}

}  // namespace em::act::navigation
