// PerceptionEngine (T23, docs/14 section 6.1): for each OBSERVER, what it sees, hears and feels of the entities of the
// EntityStore (people, beasts, objects, buildings, plants, water, fire, traces), of the acts of others and of the place
// it stands in, written into ITS OWN dossiers (NpcState: entity_percept, percept, place_percept, event_seen) and nowhere
// else. The NPC never reads the truth: every field comes from a perceptible variable of the world (PerceptRules, generated
// from the catalogue), filtered by distance, light, angle, obstacles (SpaceQuery), attention (SELF_STATE.attention) and the
// observer's own senses. Two observers of the same thing get two different dossiers.
//
// Determinism: the observers are served in increasing EntityId order, the candidates in the order of the SpatialIndex,
// the blur is a hash of (observer, target, field, time bucket), the reports are merged in observer order. The result is
// the same with 1 or n threads (each observer reads the world and writes only its own bundle). No rand(), no clock.
//
// Identity: a percept holds NO objective id. The link percept record -> entity lives in the ObserverMemory (engine side,
// not saved: rebuilt in one tick), the link to a mental file comes from the FileDirectory, and only when the observer
// is sure enough of who it is (r_id_certainty).
//
// Wakes (docs/14 section 5): P0 danger perceived (a blow, a cry, a charging beast, a fire), P1 spoken to, P3 a new person,
// a loud noise, an occasion (the perceived thing is designated by an ACTIVE goal of the NPC), a goal_check (the perceived
// person a goal designates is obviously dead). They are computed on the dossiers of the NPC, not on the truth.
#pragma once
#include <array>
#include <cstdint>
#include <map>
#include <span>
#include <string_view>
#include <unordered_map>
#include <vector>

#include "emergence/act/entity_store.h"
#include "emergence/act/perception/acuity.h"
#include "emergence/act/perception/percept_rules.h"
#include "emergence/act/perception/space_query.h"
#include "emergence/act/perception/spatial_index.h"
#include "emergence/social/npc_state_codec.h"

namespace em::act::perception {

using em::social::MRef;
using em::social::NpcBundle;

// Which mental file (a Relation record) an observer has for someone, if any: the NPC's own knowledge, set by whoever
// introduces people (the speech router, the first meeting). The perception only reads it.
class FileDirectory {
 public:
  virtual ~FileDirectory() = default;
  virtual MRef file_of(EntityId observer, EntityId target) const = 0;
};

class KnownFiles final : public FileDirectory {
 public:
  void set(EntityId observer, EntityId target, MRef file) { files_[key(observer, target)] = file; }
  MRef file_of(EntityId observer, EntityId target) const override {
    auto it = files_.find(key(observer, target));
    return it == files_.end() ? MRef{} : it->second;
  }

 private:
  static std::uint64_t key(EntityId o, EntityId t) { return (std::uint64_t(o) << 32) | t; }
  std::unordered_map<std::uint64_t, MRef> files_;   // looked up by key only
};

// The lists the world keeps per entity (Appearance.attire_seen, held_seen, involuntary_signs...): handles into a world
// side table that the EntityStore does not hold yet (T15). Whoever owns that table answers here. Items are word ids of
// kKinds, most salient first; `held_seen` holds the EntityIds of what is in the hands.
class WorldLists {
 public:
  virtual ~WorldLists() = default;
  virtual std::span<const std::uint32_t> list(EntityId entity, std::string_view variable) const = 0;
};

class MapLists final : public WorldLists {
 public:
  void set(EntityId e, std::string_view variable, std::vector<std::uint32_t> items) { lists_[{e, std::string(variable)}] = std::move(items); }
  std::span<const std::uint32_t> list(EntityId e, std::string_view variable) const override {
    auto it = lists_.find({e, std::string(variable)});
    return it == lists_.end() ? std::span<const std::uint32_t>{} : std::span<const std::uint32_t>(it->second);
  }

 private:
  std::map<std::pair<EntityId, std::string>, std::vector<std::uint32_t>> lists_;
};

// What the engine remembers about one entity it perceives, for ONE observer (never saved, never shown to the model).
struct Binding {
  EntityId entity = 0;
  std::uint32_t ep_serial = 0, pc_serial = 0;   // serials of the records in the observer's pools (0 = none)
  std::int32_t last_dist_mm = -1;
  em::social::GameTime last_seen = 0;
  std::uint8_t last_condition = 0;
  std::uint8_t fired = 0;                        // wakes already sent for this sight (kFired*)
};
inline constexpr std::uint8_t kFiredNew = 1, kFiredOccasion = 2, kFiredGoalCheck = 4, kFiredDanger = 8;

struct ObserverMemory {
  std::vector<Binding> bindings;   // sorted by entity
};

// One NPC that perceives: its entity in the EntityStore (position, orientation, body) and its bundle (dossiers).
class Observer {
 public:
  Observer(EntityId entity, NpcBundle& mind) : entity_(entity), mind_(&mind) {}
  EntityId entity() const { return entity_; }
  NpcBundle& mind() { return *mind_; }
  const NpcBundle& mind() const { return *mind_; }
  ObserverMemory& memory() { return memory_; }

 private:
  EntityId entity_;
  NpcBundle* mind_;
  ObserverMemory memory_;
};

// An act of someone, as the world knows it: the TRUTH (ids), from which each witness gets its own EventSeen.
// noise and sight are the perceptibility 0..10 of the Operation header (a whisper: noise 1; a discreet take: sight 2).
struct ActEvent {
  EntityId actor = 0;
  std::uint16_t gesture = 0xFFFF;      // id in the gesture registry (social::gen::Gesture)
  std::uint8_t noise = 0, sight = 5;
  std::array<std::uint8_t, 8> manner{};
  EntityId target = 0, with = 0, from_to = 0;
  Position at_mm{};
  std::uint32_t content = 0;           // PropRef of the speaker's arena for a speech/writing (opaque to the perception)
  bool speech = false;
  em::social::GameTime when = 0;
};

// Builds the event of an Operation of kind Act (payload: u16 gesture, u8 manner[8], u32 target[3], u32 content). The
// actor is the author; its position is read in the store. False when the operation is not a well-formed Act.
bool decode_act(const ops::Operation& op, const EntityStore& store, ActEvent& out);

enum class WakePriority : std::uint8_t { P0 = 0, P1 = 1, P3 = 3 };
enum class WakeCause : std::uint8_t { Perception, Speech, Occasion, GoalCheck };

// A reason to wake the NPC's mind. `about` is the serial of a record of ITS OWN dossiers (never an objective id).
struct Wake {
  EntityId observer = 0;
  WakePriority priority = WakePriority::P3;
  WakeCause cause = WakeCause::Perception;
  std::uint32_t about = 0;
  std::uint8_t urgency = 0;   // 0..10
  bool operator==(const Wake&) const = default;
};

// What a listener heard of a speech: for the speech router (T24), which turns it into HEARD. ENGINE channel: the
// speaker's id is the truth, the router translates it into the listener's pointers.
struct HeardSpeech {
  EntityId listener = 0, speaker = 0;
  std::uint32_t content = 0;
  std::uint16_t clarity = 0;
  bool addressed = false, intelligible = false;
  em::social::GameTime when = 0;
  bool operator==(const HeardSpeech&) const = default;
};

struct PerceptionStats {
  std::uint64_t observers = 0, candidates = 0, perceived_people = 0, perceived_things = 0, events_seen = 0, events_heard = 0;
  std::uint64_t rays = 0;                 // line-of-sight queries made to the SpaceQuery
  std::uint64_t scan_ns = 0, write_ns = 0;   // CPU time of the two phases summed over the observers (informative: a clock, never read by the logic)
};

struct PerceptionReport {
  std::vector<Wake> wakes;            // in observer order, then in the order of discovery
  std::vector<HeardSpeech> speech;
  PerceptionStats stats;
};

struct PerceptionConfig {
  std::int32_t cell_mm = 8000;
  std::int32_t eye_height_mm = 1600;
  int max_people = 10;          // the capacity of the entity_percept pool
  int max_things = 16;          // the capacity of the percept pool
  int max_events = 6;           // the capacity of the event_seen pool
  unsigned cadence = 1;         // 1 = every observer rescans at every tick; n = one tick out of n (staggered by EntityId)
  unsigned threads = 1;         // 1 = in the caller's thread; the result is identical for any value
  em::social::GameTime dt_s = 16;   // game seconds per tick (NpcLaws::kTickS): the unit of the motion seen
};

class PerceptionEngine {
 public:
  PerceptionEngine(const EntityStore& store, const SpaceQuery& space, const ThingCatalog& things, PerceptionConfig cfg = {});

  void set_files(const FileDirectory* files) { files_ = files; }
  void set_lists(const WorldLists* lists) { lists_ = lists; }

  // Queues an act for the witnesses of the next tick.
  void submit(const ActEvent& e) { events_.push_back(e); }

  // One perception step for all observers. The report stays valid until the next tick.
  const PerceptionReport& tick(std::span<Observer> observers, em::social::GameTime now);

  const PerceptRules& rules() const { return rules_; }
  const PerceptionConfig& config() const { return cfg_; }

 private:
  struct Scratch;
  struct Out;
  void observe(Observer& obs, em::social::GameTime now, std::span<const ActEvent> events, Scratch& sc, Out& out) const;

  const EntityStore& store_;
  const SpaceQuery& space_;
  const ThingCatalog& things_;
  PerceptionConfig cfg_;
  PerceptRules rules_;
  Vocabulary vocab_;
  SpatialIndex index_;
  const FileDirectory* files_ = nullptr;
  const WorldLists* lists_ = nullptr;
  std::vector<ActEvent> events_;
  PerceptionReport report_;
  std::int32_t air_milli_c_ = 20000;
  std::vector<std::vector<std::uint32_t>> prop_words_;   // perceptible words of each sort (cache)
};

}  // namespace em::act::perception
