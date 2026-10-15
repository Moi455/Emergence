#include "emergence/act/perception/perception_engine.h"

#include <algorithm>
#include <chrono>
#include <cstdlib>
#include <thread>
#include <tuple>

#include "emergence/act/perception/trig.h"
#include "emergence/social/catalogue_gen.h"
#include "emergence/social/vocab_gen.h"

namespace em::act::perception {

namespace social = em::social;
using social::GameTime;

namespace {

// Salts of the blur: one per field, so that two fields of the same target do not share their error.
enum Salt : std::uint32_t { kSaltDist = 1, kSaltAge, kSaltSex, kSaltWounds, kSaltDir, kSaltTie };
constexpr std::uint16_t kNotice = 50;   // below this clarity, nothing of the entity reaches the observer
constexpr GameTime kBucketS = 600;      // the blur is stable for 10 game minutes

// Enum indices of the percept variables (catalogue values lists).
namespace ep { constexpr std::uint8_t kActive = 0, kMotionless = 3, kObviouslyDead = 4; }
namespace mo { constexpr std::uint8_t kStill = 0, kApproaching = 1, kLeaving = 2, kRunning = 3; }
namespace pm { constexpr std::uint8_t kStill = 0, kApproaching = 1, kLeaving = 2; }
namespace dsp { constexpr std::uint8_t kCalm = 0, kAlert = 2, kFleeing = 3, kGrowling = 4, kBaring = 5, kCharging = 6, kPlaying = 8; }
namespace sense { constexpr std::uint8_t kSeen = 0, kHeard = 1, kFelt = 2; }

std::int64_t kind_range_mm(gen::EntityKind k) {
  switch (k) {
    case gen::EntityKind::agent: case gen::EntityKind::animal: case gen::EntityKind::water_body: return 60000;
    case gen::EntityKind::structure: case gen::EntityKind::fire: return 80000;
    case gen::EntityKind::plant: case gen::EntityKind::phenomenon: return 40000;
    case gen::EntityKind::item: return 25000;
    case gen::EntityKind::trace: return 8000;
    default: return 0;
  }
}
bool is_person_like(gen::EntityKind k) { return k == gen::EntityKind::agent || k == gen::EntityKind::animal; }
// Where a target is looked at: the chest of a living thing, the base of the rest (mm above its position).
std::int32_t body_height(gen::EntityKind k) { return is_person_like(k) ? 1200 : 400; }

std::int32_t pack_dir(std::int32_t off_mrad) {
  const std::int32_t s = sin_milli(off_mrad), c = cos_milli(off_mrad);
  return static_cast<std::int32_t>((std::uint32_t(std::uint16_t(std::int16_t(s))) << 16) | std::uint16_t(std::int16_t(c)));
}

std::span<const std::uint32_t> list_of(const WorldLists* l, EntityId e, std::string_view var) {
  return l ? l->list(e, var) : std::span<const std::uint32_t>{};
}

}  // namespace

// ---------------------------------------------------------------------------------------------------------------
struct PerceptionEngine::Out {
  std::vector<Wake> wakes;
  std::vector<HeardSpeech> speech;
  PerceptionStats st;
  void clear() { wakes.clear(); speech.clear(); st = {}; }
};

struct Seen {
  EntityId id = 0;
  gen::EntityKind kind = gen::EntityKind::kCount;
  std::uint16_t sort = 0;
  Position pos{};
  std::int32_t dist = 0, off = 0;
  std::uint16_t clarity = 0;     // the bound (nothing in the way) until the ray is drawn, then the exact clarity
  bool attended = false;
  std::int32_t trans = -1;       // share of the view that is clear; -1 = ray not drawn yet
  std::uint32_t tie = 0;         // hash of (observer, id): breaks ties without ranking by EntityId
};

struct PerceptionEngine::Scratch {
  std::vector<Seen> cands, people, things;
  std::vector<std::uint32_t> pidx, tidx;
  std::vector<Binding> next;
  std::vector<std::uint32_t> serials, refs, tmp;
};

// ---------------------------------------------------------------------------------------------------------------
bool decode_act(const ops::Operation& op, const EntityStore& store, ActEvent& out) {
  if (op.op_kind() != ops::OpKind::Act) return false;
  ops::PayloadReader r(op.payload);
  std::uint16_t g = 0;
  std::uint32_t t[3] = {0, 0, 0}, content = 0;
  ActEvent e;
  if (!r.u16(g)) return false;
  for (auto& m : e.manner) if (!r.u8(m)) return false;
  for (auto& x : t) if (!r.u32(x)) return false;
  if (!r.u32(content) || r.remaining() != 0) return false;
  e.actor = op.author;
  e.gesture = op.gesture != ops::kNone16 ? op.gesture : g;
  e.noise = op.noise > 10 ? 10 : op.noise;
  e.sight = op.sight > 10 ? 10 : op.sight;
  e.target = t[0]; e.with = t[1]; e.from_to = t[2];
  e.content = content;
  e.speech = (op.flags & ops::kFlagSpeech) != 0;
  e.when = static_cast<GameTime>(op.tick);
  if (!store.alive(e.actor)) return false;
  e.at_mm = store.position_mm(e.actor);
  out = e;
  return true;
}

namespace {
std::vector<std::uint32_t> visible_words(const ThingProfile& tp, std::span<const PropertyDesc> props);
}

PerceptionEngine::PerceptionEngine(const EntityStore& store, const SpaceQuery& space, const ThingCatalog& things, PerceptionConfig cfg)
    : store_(store), space_(space), things_(things), cfg_(cfg), index_(cfg.cell_mm) {
  // The object vector of every sort, computed once (the catalogue does not change during the game).
  prop_words_.resize(social::gen::kKinds.size());
  for (std::size_t sort = 1; sort < prop_words_.size(); ++sort)
    prop_words_[sort] = visible_words(things_.profile(gen::EntityKind::item, std::uint16_t(sort)), things_.properties());
}

namespace {

struct Ctx {
  const EntityStore& store;
  const SpaceQuery& space;
  const ThingCatalog& things;
  const PerceptRules& rules;
  const Vocabulary& vocab;
  const FileDirectory* files;
  const WorldLists* lists;
  const SenseProfile& sp;
  NpcBundle& bundle;
  EntityId self;
  GameTime now;
  std::int32_t air_milli_c;
  const std::vector<std::vector<std::uint32_t>>* words;   // visible_words by sort (a cache built once)
  int mastery;    // best mastery of the observer, 0..100
  bool ok(Field f, std::uint16_t clarity) const { return clarity >= rules.min_clarity(f); }
};

// The first part of a list in proportion to the clarity (the nearer and clearer, the more of it is seen); empty below `min`.
std::span<const std::uint32_t> prefix_for(std::span<const std::uint32_t> items, std::uint16_t clarity, std::uint16_t min) {
  if (items.empty() || clarity < min) return {};
  const std::size_t n = std::max<std::size_t>(1, (items.size() * clarity + 999) / 1000);
  return items.first(std::min(n, items.size()));
}

// Makes the list `ref` of the observer hold `items`: kept as it is when it already does (no churn of the side table),
// else released and rewritten. An empty `items` empties the field.
void set_list(NpcBundle& b, social::ListRef& ref, std::span<const std::uint32_t> items) {
  if (items.empty()) { if (ref) { b.side.release(ref); ref = 0; } return; }
  const auto cur = b.side.get(ref);
  if (ref && cur.size() == items.size() && std::equal(cur.begin(), cur.end(), items.begin())) return;
  b.side.release(ref);
  ref = b.side.put(items);
}

void release(NpcBundle& b, social::ListRef& r) { b.side.release(r); r = 0; }
void release_all(NpcBundle& b, social::gen::EntityPercept& r) {
  release(b, r.ep_attire); release(b, r.ep_build); release(b, r.ep_health);
  release(b, r.ep_held); release(b, r.ep_marks); release(b, r.ep_signs);
}
void release_all(NpcBundle& b, social::gen::Percept& r) { release(b, r.pc_props_seen); release(b, r.pc_state_seen); }

// A record is rewritten from zero at every tick, except its lists (they are compared and replaced by set_list).
void reset_keep_lists(social::gen::EntityPercept& r) {
  const social::ListRef a = r.ep_attire, bl = r.ep_build, h = r.ep_health, he = r.ep_held, m = r.ep_marks, sg = r.ep_signs;
  r = social::gen::EntityPercept{};
  r.ep_attire = a; r.ep_build = bl; r.ep_health = h; r.ep_held = he; r.ep_marks = m; r.ep_signs = sg;
}
void reset_keep_lists(social::gen::Percept& r) {
  const social::ListRef p = r.pc_props_seen, s = r.pc_state_seen;
  r = social::gen::Percept{};
  r.pc_props_seen = p; r.pc_state_seen = s;
}

// The perceptible words of a sort, most useful first: the uses, then the states, then the magnitudes of the object vector.
std::vector<std::uint32_t> visible_words(const ThingProfile& tp, std::span<const PropertyDesc> props) {
  std::vector<std::uint32_t> words;
  if (!tp.known) return words;
  for (int pass = 0; pass < 3; ++pass)
    for (std::size_t i = 0; i < props.size(); ++i) {
      if (!(tp.props[i / 64] >> (i % 64) & 1) || !props[i].perceptible || props[i].word == 0) continue;
      const gen::PropCat cat = props[i].cat;
      const int p = cat == gen::PropCat::Affordance ? 0 : cat == gen::PropCat::State ? 1 : 2;
      if (p != pass || (cat == gen::PropCat::Intrinsic && !props[i].in_vector)) continue;
      words.push_back(props[i].word);
    }
  return words;
}

std::uint8_t quantize_amount(std::int64_t v, std::uint16_t clarity) {   // none, few, some, many, unknown
  if (clarity < 250) return 4;
  if (v <= 0) return 0;
  return v < 2000 ? 1 : v < 6000 ? 2 : 3;
}

std::uint8_t display_of(std::uint8_t expression, std::uint8_t motion, std::uint8_t posture, std::uint16_t clarity) {
  // Only what shows from outside: the face (expression), the stride (motion), the stance (posture). The aggressiveness
  // and the fear of humans of the beast (engine-only) are never read.
  switch (expression) {
    case 4: return motion == 3 ? dsp::kCharging : (clarity >= 600 ? dsp::kBaring : dsp::kGrowling);   // anger
    case 5: return dsp::kFleeing;                                                                     // fear
    case 9: return dsp::kAlert;                                                                       // surprise
    case 2: case 1: return dsp::kPlaying;                                                             // laugh, smile
    default: break;
  }
  return (posture == 5 && motion == 1) ? std::uint8_t(7) : dsp::kCalm;   // crouching and coming on: stalking
}

// The motion seen from where the observer stands: from the stride (velocity) and from the change of distance since
// the last time it looked, never from an intention.
std::uint8_t motion_of(std::int64_t speed_mm_s, std::int32_t dist, std::int32_t prev_dist, bool person) {
  if (person && speed_mm_s >= 3000) return mo::kRunning;
  if (prev_dist >= 0) {
    const std::int32_t d = dist - prev_dist;
    if (d <= -250) return mo::kApproaching;
    if (d >= 250) return mo::kLeaving;
  }
  return mo::kStill;
}

// The direction is only as exact as the view: up to ~17 degrees of error when the clarity is at the threshold of notice.
std::int32_t dir_error(const Ctx& c, const Seen& s) {
  return static_cast<std::int32_t>(std::int64_t(acuity::noise_pm(c.self, s.id, kSaltDir, std::uint32_t(c.now / kBucketS))) * (1000 - s.clarity) / 1000 * 300 / 1000);
}

void fill_person(const Ctx& c, const Seen& s, const Binding& prev, social::gen::EntityPercept& r) {
  const std::uint16_t cl = s.clarity;
  const std::uint32_t bucket = std::uint32_t(c.now / kBucketS);
  const auto* app = c.store.component<gen::Appearance>(s.id);
  const auto* spa = c.store.component<gen::Spatial>(s.id);
  // distance and direction: seen with a little error that grows when the view is poor
  const std::int64_t derr = std::int64_t(acuity::noise_pm(c.self, s.id, kSaltDist, bucket)) * (1000 - cl) / 1000 * s.dist / 10000;
  r.ep_dist = static_cast<std::int32_t>(std::max<std::int64_t>(0, s.dist + derr));
  r.ep_dir = pack_dir(s.off + dir_error(c, s));
  if (!app) return;
  if (c.ok(Field::ep_condition, cl)) {
    r.ep_condition = (app->condition == ep::kObviouslyDead && cl < 300) ? ep::kMotionless : app->condition;
  }
  if (c.ok(Field::ep_posture, cl)) r.ep_posture = app->posture;
  if (c.ok(Field::ep_motion, cl)) r.ep_motion = motion_of(spa ? std::abs(spa->velocity) : 0, s.dist, prev.last_dist_mm, true);
  if (c.ok(Field::ep_expression, cl)) r.ep_expression = app->expression;
  if (c.ok(Field::ep_sex, cl)) {
    r.ep_sex = app->look_sex_seen;
    if (cl < 500 && r.ep_sex != 2 && acuity::noise_pm(c.self, s.id, kSaltSex, bucket) < 0) r.ep_sex = 2;   // unclear
  }
  if (c.ok(Field::ep_wounds, cl)) {
    std::int16_t w = app->visible_injury;
    if (cl < 600) w = std::int16_t((w + 12) / 25 * 25);   // coarse levels from afar
    r.ep_wounds = w;
  }
  if (c.ok(Field::ep_age, cl) && app->look_age_seen != 0) {
    // D10: the age is PERCEIVED, never the real one. Only the world's APPARENT age (look_age_seen) is a source: without it
    // the age stays unknown (0). It is blurred by distance and light with a FIXED bias per (observer, target), the same
    // for every time slice, so that averaging many looks never converges on anything but the apparent age; then rounded to
    // a band that widens as the view worsens.
    const std::int64_t base = app->look_age_seen;
    const std::int64_t err = std::int64_t(acuity::noise_pm(c.self, s.id, kSaltAge, 0)) * (1000 - cl) / 1000 * 6;
    const std::int64_t band = 1000 + std::int64_t(1000 - cl) * 8;
    r.ep_age = static_cast<std::int32_t>(std::max<std::int64_t>(0, (base + err + band / 2) / band * band));
  }
  if (c.lists) {
    set_list(c.bundle, r.ep_attire, prefix_for(list_of(c.lists, s.id, "attire_seen"), cl, c.rules.min_clarity(Field::ep_attire)));
    set_list(c.bundle, r.ep_build, prefix_for(list_of(c.lists, s.id, "look_build_seen"), cl, c.rules.min_clarity(Field::ep_build)));
    set_list(c.bundle, r.ep_health, prefix_for(list_of(c.lists, s.id, "symptoms"), cl, c.rules.min_clarity(Field::ep_health)));
    set_list(c.bundle, r.ep_marks, prefix_for(list_of(c.lists, s.id, "look_marks_seen"), cl, c.rules.min_clarity(Field::ep_marks)));
    set_list(c.bundle, r.ep_signs, prefix_for(list_of(c.lists, s.id, "involuntary_signs"), cl, c.rules.min_clarity(Field::ep_signs)));
  }
  if (c.lists && c.ok(Field::ep_held, cl)) {   // what is in the hands, by its uses: the perceptible affordances of each held thing
    std::vector<std::uint32_t> words;
    const auto props = c.things.properties();
    for (std::uint32_t held : list_of(c.lists, s.id, "held_seen")) {
      if (!c.store.alive(held) || c.store.holder(held) != s.id) continue;   // the truth is checked, only a held thing counts
      const ThingProfile tp = c.things.profile(c.store.kind(held), c.store.sort(held));
      for (std::size_t i = 0; i < props.size() && words.size() < 8; ++i)
        if ((tp.props[i / 64] >> (i % 64) & 1) && props[i].perceptible && props[i].cat == gen::PropCat::Affordance && props[i].word != 0 &&
            std::find(words.begin(), words.end(), props[i].word) == words.end())
          words.push_back(props[i].word);
    }
    set_list(c.bundle, r.ep_held, words);
  } else if (r.ep_held) {
    set_list(c.bundle, r.ep_held, {});
  }
  // ep_gaze (what he is seen looking at) stays empty: only one of the observer's OWN records could answer, and looking at
  // the observer itself has no record to designate (open point: a SELF pointer in the catalogue). The rule exists (>= 700).
}

void fill_thing(const Ctx& c, const Seen& s, const Binding& prev, social::gen::Percept& r) {
  const std::uint16_t cl = s.clarity;
  const std::uint32_t bucket = std::uint32_t(c.now / kBucketS);
  const std::int64_t derr = std::int64_t(acuity::noise_pm(c.self, s.id, kSaltDist, bucket)) * (1000 - cl) / 1000 * s.dist / 10000;
  r.pc_dist = static_cast<std::int32_t>(std::max<std::int64_t>(0, s.dist + derr));
  r.pc_dir = pack_dir(s.off + dir_error(c, s));
  const auto* spa = c.store.component<gen::Spatial>(s.id);
  const bool living = is_person_like(s.kind);
  r.pc_motion = motion_of(spa ? std::abs(spa->velocity) : 0, s.dist, prev.last_dist_mm, false);
  if (living && r.pc_motion == mo::kRunning) r.pc_motion = pm::kStill;
  if (!c.ok(Field::pc_motion, cl)) r.pc_motion = 0;
  // The kind: the look-alike class for a poor eye, the true sort only if the view is clear AND the observer is skilled.
  const ThingProfile tp = c.things.profile(s.kind, s.sort);
  std::uint16_t kind_word = 0;
  if (tp.known) {
    const bool sure = tp.lookalike_word == 0 || (cl >= 800 && c.mastery >= 60);
    kind_word = sure ? tp.kind_word : tp.lookalike_word;
  } else {
    kind_word = c.vocab.symbol(gen::kEntityKindNames[std::size_t(s.kind)]);
  }
  if (c.ok(Field::pc_kind_seen, cl)) r.pc_kind_seen = kind_word;
  if (tp.known && c.ok(Field::pc_color_seen, cl) && c.sp.light >= 30) r.pc_color_seen = tp.color_word;   // no colour in the dark
  if (tp.known && c.ok(Field::pc_props_seen, cl)) {
    // The object vector: only the PERCEPTIBLE properties (never the toxicity, the power, the key's lock...); the nearer and
    // clearer, the more of them.
    std::vector<std::uint32_t> own;
    const std::vector<std::uint32_t>* words = (c.words && s.sort < c.words->size()) ? &(*c.words)[s.sort] : nullptr;
    if (!words) { own = visible_words(tp, c.things.properties()); words = &own; }
    set_list(c.bundle, r.pc_props_seen, prefix_for(*words, cl, 0));
  } else if (r.pc_props_seen) {
    set_list(c.bundle, r.pc_props_seen, {});
  }
  if (s.kind == gen::EntityKind::structure && c.ok(Field::pc_state_seen, cl)) {
    if (const auto* st = c.store.component<gen::Stability>(s.id)) {
      const char* w = st->visible_damage < 20 ? "intact" : st->visible_damage < 50 ? "damaged" : st->visible_damage < 80 ? "cracked" : "shattered";
      const std::uint32_t id = c.vocab.kind(w);
      if (id) set_list(c.bundle, r.pc_state_seen, std::span<const std::uint32_t>(&id, 1));
    }
  } else if (r.pc_state_seen) {
    set_list(c.bundle, r.pc_state_seen, {});
  }
  if (c.ok(Field::pc_amount_seen, cl)) {
    if (const auto* g = c.store.component<gen::Growth>(s.id)) r.pc_amount_seen = quantize_amount(g->plant_yield, cl);
    else if (const auto* su = c.store.component<gen::Substance>(s.id)) r.pc_amount_seen = quantize_amount(su->water_volume, cl);
  }
  if (const auto* fl = c.store.component<gen::Flow>(s.id); fl && c.ok(Field::pc_depth_seen, cl))
    r.pc_depth_seen = fl->water_level < 500 ? 0 : fl->water_level < 1100 ? 1 : fl->water_level < 2000 ? 2 : 3;
  if (s.kind == gen::EntityKind::animal && c.ok(Field::pc_display, cl))
    if (const auto* app = c.store.component<gen::Appearance>(s.id))
      r.pc_display = display_of(app->expression, app->seen_motion, app->posture, cl);
  // The mental file of the thing, if the observer has one AND is sure enough it is that one. A look-alike lowers the
  // certainty (a coin like mine?), never raises it.
  std::uint16_t cert = cl;
  if (tp.known && tp.lookalike_word != 0 && !(cl >= 800 && c.mastery >= 60)) cert = std::min<std::uint16_t>(cert, 450);
  r.pc_file_certainty = static_cast<std::int16_t>(cert / 10);
  if (c.files && cert >= c.rules.min_clarity(Field::pc_file)) r.pc_file = c.files->file_of(c.self, s.id);
}

}  // namespace

// ---------------------------------------------------------------------------------------------------------------
void PerceptionEngine::observe(Observer& obs, GameTime now, std::span<const ActEvent> events, Scratch& sc, Out& out) const {
  NpcBundle& b = obs.mind();
  auto& st = b.state;
  ObserverMemory& mem = obs.memory();
  ++out.st.observers;
  const auto t_start = std::chrono::steady_clock::now();

  SenseProfile sp;
  sp.vision = st.body.vision; sp.hearing = st.body.hearing; sp.perceptiveness = st.mind_static.perceptiveness;
  sp.consciousness = st.body.consciousness; sp.attention = st.mind_dynamic.attention;
  sp.awake = st.body.alive && sp.consciousness >= 20 && store_.alive(obs.entity());
  Position self_pos{};
  if (sp.awake) {
    self_pos = store_.position_mm(obs.entity());
    sp.eye = {self_pos[0], self_pos[1], self_pos[2] + cfg_.eye_height_mm};
    if (const auto* spa = store_.component<gen::Spatial>(obs.entity())) sp.facing_mrad = spa->orientation;
    sp.light = space_.light_at(sp.eye, now);
    sp.fog_pm = space_.fog_permille(sp.eye);
  }

  auto drop_binding = [&](const Binding& bd) {
    if (bd.ep_serial) { if (auto* r = st.entity_percept_records.find({bd.ep_serial})) release_all(b, *r); st.entity_percept_records.remove({bd.ep_serial}); }
    if (bd.pc_serial) { if (auto* r = st.percept_records.find({bd.pc_serial})) release_all(b, *r); st.percept_records.remove({bd.pc_serial}); }
  };
  if (!sp.awake) {   // asleep, dead or knocked out: nothing is perceived "now"; the dossiers of the moment are emptied
    for (const Binding& bd : mem.bindings) drop_binding(bd);
    mem.bindings.clear();
    return;
  }

  auto find_binding = [&](EntityId e) -> const Binding* {
    auto it = std::lower_bound(mem.bindings.begin(), mem.bindings.end(), e, [](const Binding& x, EntityId v) { return x.entity < v; });
    return (it != mem.bindings.end() && it->entity == e) ? &*it : nullptr;
  };
  auto is_attended = [&](EntityId e, std::int64_t dist = 0) {
    if (sp.attention.serial == 0) return false;
    if (const Binding* bd = find_binding(e); bd && (bd->ep_serial == sp.attention.serial || bd->pc_serial == sp.attention.serial)) return true;
    // A known file only draws the attention of someone close enough to be recognised (never a far silhouette).
    return files_ && dist <= 15000 && files_->file_of(obs.entity(), e).serial == sp.attention.serial;
  };

  // Cadence: with cadence n, an observer rescans its surroundings one tick out of n (staggered by its id); the acts of
  // others are witnessed at every tick whatever the cadence.
  const bool do_scan = cfg_.cadence <= 1 || (std::uint64_t(obs.entity()) + std::uint64_t(now / std::max<GameTime>(cfg_.dt_s, 1))) % cfg_.cadence == 0;
  std::size_t crowd = std::size_t(st.entity_percept_records.size());
  auto t_scanned = t_start;
  if (do_scan) {
  // --- 1. the candidates around the observer: the grid, then the exact tests (distance, angle, obstacles) ----------
  sc.people.clear();
  sc.things.clear();
  // Light: the observer sees by the light around the TARGET too (a torch beside someone lights him for a far watcher), so
  // the cheap culls use the best case (full daylight) and the real light is read only for what survives them.
  SenseProfile bright = sp;
  bright.light = 100;
  const std::int64_t reach = acuity::sight_range_mm(bright, 80000);
  // Per observer, once: how far each kind can be seen, and where it faces (so the cheap tests need no division).
  // Even with every bonus (x1.56) a clarity below kNotice is not noticed: beyond 82.2 % of the range, no further test.
  std::array<std::int64_t, std::size_t(gen::EntityKind::kCount)> notice_d2{};
  for (std::size_t k = 0; k < notice_d2.size(); ++k) {
    const std::int64_t r = acuity::sight_range_mm(bright, kind_range_mm(gen::EntityKind(k))) * 822 / 1000;
    notice_d2[k] = r * r;
  }
  const std::int64_t fx = cos_milli(sp.facing_mrad), fy = sin_milli(sp.facing_mrad);
  sc.cands.clear();
  index_.query(sp.eye, reach, [&](const SpatialIndex::Entry& e) {
    if (e.id == obs.entity()) return;
    ++out.st.candidates;
    const std::int64_t dx = e.pos[0] - sp.eye[0], dy = e.pos[1] - sp.eye[1], dz = e.pos[2] + body_height(e.kind) - sp.eye[2];
    const std::int64_t d2 = dx * dx + dy * dy + dz * dz;
    if (d2 >= notice_d2[std::size_t(e.kind)]) return;
    // Behind the observer (more than 100 degrees off its facing, cos^2 = 0.0302) and not within arm's reach: not seen.
    const std::int64_t dot = dx * fx + dy * fy;   // x 1000
    if (dot < 0 && dot * dot > (dx * dx + dy * dy) * 1000000 * 30 / 1000 && d2 >= std::int64_t(acuity::kNearMm) * acuity::kNearMm) return;
    const std::int64_t dist = static_cast<std::int64_t>(isqrt(static_cast<std::uint64_t>(d2)));
    const std::int32_t off = (dx == 0 && dy == 0) ? 0 : wrap_angle(std::int64_t(atan2_mrad(dy, dx)) - sp.facing_mrad);
    if (acuity::angle_factor(off, dist) == 0) return;
    const bool att = is_attended(e.id, dist);
    SenseProfile local = sp;
    local.light = std::int16_t(std::max<int>(sp.light, space_.light_at(Position{e.pos[0], e.pos[1], e.pos[2] + body_height(e.kind)}, now)));
    // The cheap bound (nothing in the way): the line of sight is drawn later, for the best candidates only.
    const std::uint16_t bound = acuity::sight_clarity(local, dist, off, 1000, att, kind_range_mm(e.kind));
    if (bound < kNotice) return;
    Seen s{e.id, e.kind, e.sort, e.pos, std::int32_t(dist), off, bound, att, -1, 0};
    s.tie = static_cast<std::uint32_t>(acuity::noise_pm(obs.entity(), e.id, kSaltTie, 0) + 1000);
    sc.cands.push_back(s);
  });
  auto better = [](const Seen& a, const Seen& b) {
    if (a.attended != b.attended) return a.attended;
    if (a.clarity != b.clarity) return a.clarity > b.clarity;
    return a.tie != b.tie ? a.tie < b.tie : a.id < b.id;   // a hash first, so that no one is favoured for a low EntityId
  };
  sc.pidx.clear(); sc.tidx.clear();
  for (std::uint32_t i = 0; i < sc.cands.size(); ++i) {
    if (is_person_like(sc.cands[i].kind)) sc.pidx.push_back(i);
    if (sc.cands[i].kind != gen::EntityKind::agent) sc.tidx.push_back(i);
  }
  // Best bound first; the ray is drawn only until the pool is full (not for the whole crowd), and a hidden one is skipped.
  auto pick = [&](std::vector<std::uint32_t>& idx, std::size_t cap, std::vector<Seen>& dst) {
    dst.clear();
    std::sort(idx.begin(), idx.end(), [&](std::uint32_t x, std::uint32_t y) { return better(sc.cands[x], sc.cands[y]); });
    for (std::uint32_t i : idx) {
      if (dst.size() >= cap) break;
      Seen& s = sc.cands[i];
      if (s.trans < 0) {
        ++out.st.rays;
        s.trans = space_.sight_transmission(sp.eye, Position{s.pos[0], s.pos[1], s.pos[2] + body_height(s.kind)});
      }
      if (s.trans == 0) continue;
      SenseProfile local = sp;
      local.light = std::int16_t(std::max<int>(sp.light, space_.light_at(Position{s.pos[0], s.pos[1], s.pos[2] + body_height(s.kind)}, now)));
      const std::uint16_t cl = acuity::sight_clarity(local, s.dist, s.off, std::uint16_t(s.trans), s.attended, kind_range_mm(s.kind));
      if (cl < kNotice) continue;
      Seen k = s;
      k.clarity = cl;
      dst.push_back(k);
    }
    std::sort(dst.begin(), dst.end(), better);
  };
  pick(sc.pidx, std::size_t(cfg_.max_people), sc.people);
  pick(sc.tidx, std::size_t(cfg_.max_things), sc.things);
  t_scanned = std::chrono::steady_clock::now();
  out.st.scan_ns += std::uint64_t(std::chrono::duration_cast<std::chrono::nanoseconds>(t_scanned - t_start).count());

  // --- 2. what this NPC is after (its ACTIVE goals designate records of its own) ---------------------------------------
  sc.refs.clear();
  st.goal_records.for_each([&](MRef, social::gen::Goal& g) {
    if (g.g_status != 0 || g.g_desired == 0) return;
    const social::Proposition p = b.propositions.get(g.g_desired);
    for (int i = 0; i < p.size(); ++i)
      if (social::Proposition::tag(p.symbol(i)) == social::Proposition::kRef) sc.refs.push_back(social::Proposition::value(p.symbol(i)));
  });
  auto designated = [&](std::uint32_t serial) { return serial != 0 && std::find(sc.refs.begin(), sc.refs.end(), serial) != sc.refs.end(); };

  // --- 3. reconcile the dossiers: update the records of what is still seen, drop the others, open the new ----------
  const Ctx c{store_, space_, things_, rules_, vocab_, files_, lists_, sp, b, obs.entity(), now, air_milli_c_, &prop_words_, 0};
  int mastery = 0;
  st.skill_records.for_each([&](MRef, social::gen::Skill& k) { mastery = std::max<int>(mastery, k.k_mastery); });
  Ctx cc = c;
  cc.mastery = mastery;

  sc.next.clear();
  auto touch = [&](const Seen& s) -> Binding& {
    for (Binding& n : sc.next) if (n.entity == s.id) return n;
    Binding nb;
    if (const Binding* old = find_binding(s.id)) nb = *old;
    nb.entity = s.id;
    sc.next.push_back(nb);
    return sc.next.back();
  };
  // Records of what is no longer seen go first, to make room.
  auto still_seen = [&](EntityId e, bool person) {
    for (const Seen& s : person ? sc.people : sc.things) if (s.id == e) return true;
    return false;
  };
  for (Binding& bd : mem.bindings) {
    if (bd.ep_serial && !still_seen(bd.entity, true)) {
      if (auto* r = st.entity_percept_records.find({bd.ep_serial})) release_all(b, *r);
      st.entity_percept_records.remove({bd.ep_serial});
      bd.ep_serial = 0;
    }
    if (bd.pc_serial && !still_seen(bd.entity, false)) {
      if (auto* r = st.percept_records.find({bd.pc_serial})) release_all(b, *r);
      st.percept_records.remove({bd.pc_serial});
      bd.pc_serial = 0;
    }
  }
  // Records the engine does not know (a loaded save, a foreign writer) are not "perceived now": removed.
  {
    sc.serials.clear();
    for (const Binding& bd : mem.bindings) { if (bd.ep_serial) sc.serials.push_back(bd.ep_serial); }
    std::sort(sc.serials.begin(), sc.serials.end());
    sc.tmp.clear();
    st.entity_percept_records.for_each([&](MRef m, social::gen::EntityPercept&) { if (!std::binary_search(sc.serials.begin(), sc.serials.end(), m.serial)) sc.tmp.push_back(m.serial); });
    for (std::uint32_t sn : sc.tmp) { if (auto* r = st.entity_percept_records.find({sn})) release_all(b, *r); st.entity_percept_records.remove({sn}); }
    sc.serials.clear();
    for (const Binding& bd : mem.bindings) { if (bd.pc_serial) sc.serials.push_back(bd.pc_serial); }
    std::sort(sc.serials.begin(), sc.serials.end());
    sc.tmp.clear();
    st.percept_records.for_each([&](MRef m, social::gen::Percept&) { if (!std::binary_search(sc.serials.begin(), sc.serials.end(), m.serial)) sc.tmp.push_back(m.serial); });
    for (std::uint32_t sn : sc.tmp) { if (auto* r = st.percept_records.find({sn})) release_all(b, *r); st.percept_records.remove({sn}); }
  }
  const auto zero_person = [](const social::gen::EntityPercept&) -> std::int64_t { return 0; };
  const auto zero_thing = [](const social::gen::Percept&) -> std::int64_t { return 0; };
  crowd = 0;
  for (const Seen& s : sc.people) {
    Binding& nb = touch(s);
    social::gen::EntityPercept* r = nb.ep_serial ? st.entity_percept_records.find({nb.ep_serial}) : nullptr;
    const bool fresh = (r == nullptr);
    if (fresh) { nb.ep_serial = st.entity_percept_records.add(social::gen::EntityPercept{}, zero_person).serial; r = st.entity_percept_records.find({nb.ep_serial}); }
    if (!r) continue;
    reset_keep_lists(*r);
    fill_person(cc, s, nb, *r);
    if (s.kind == gen::EntityKind::agent) ++crowd;
    ++out.st.perceived_people;
    // The file is used only if the observer is sure enough of WHO it is (the same clarity as for the actor of an act).
    const std::uint32_t file = (files_ && s.clarity >= rules_.min_clarity(Field::ev_actor)) ? files_->file_of(obs.entity(), s.id).serial : 0;
    // New person, obviously dead person a goal designates.
    if (fresh && !(nb.fired & kFiredNew) && file == 0) { out.wakes.push_back({obs.entity(), WakePriority::P3, WakeCause::Perception, nb.ep_serial, 4}); nb.fired |= kFiredNew; }
    else if (fresh) nb.fired |= kFiredNew;
    if (!(nb.fired & kFiredOccasion) && (designated(nb.ep_serial) || designated(file))) {
      out.wakes.push_back({obs.entity(), WakePriority::P3, WakeCause::Occasion, designated(file) ? file : nb.ep_serial, 5});
      nb.fired |= kFiredOccasion;
    }
    if (r->ep_condition == ep::kObviouslyDead && !(nb.fired & kFiredGoalCheck) && (designated(nb.ep_serial) || designated(file))) {
      out.wakes.push_back({obs.entity(), WakePriority::P3, WakeCause::GoalCheck, designated(file) ? file : nb.ep_serial, 6});
      nb.fired |= kFiredGoalCheck;
    }
    nb.last_dist_mm = s.dist; nb.last_seen = now; nb.last_condition = r->ep_condition;
  }
  for (const Seen& s : sc.things) {
    Binding& nb = touch(s);
    social::gen::Percept* r = nb.pc_serial ? st.percept_records.find({nb.pc_serial}) : nullptr;
    const bool fresh = (r == nullptr);
    if (fresh) { nb.pc_serial = st.percept_records.add(social::gen::Percept{}, zero_thing).serial; r = st.percept_records.find({nb.pc_serial}); }
    if (!r) continue;
    reset_keep_lists(*r);
    fill_thing(cc, s, nb, *r);
    ++out.st.perceived_things;
    const std::uint32_t file = r->pc_file.serial;
    if (!(nb.fired & kFiredOccasion) && (designated(nb.pc_serial) || designated(file))) {
      out.wakes.push_back({obs.entity(), WakePriority::P3, WakeCause::Occasion, designated(file) ? file : nb.pc_serial, 5});
      nb.fired |= kFiredOccasion;
    }
    // A danger shown from outside: a fire close by, a beast that charges.
    const bool danger = (s.kind == gen::EntityKind::fire && r->pc_dist < 8000) || (s.kind == gen::EntityKind::animal && r->pc_display == dsp::kCharging);
    if (danger && !(nb.fired & kFiredDanger)) { out.wakes.push_back({obs.entity(), WakePriority::P0, WakeCause::Perception, nb.pc_serial, 8}); nb.fired |= kFiredDanger; }
    if (!danger) nb.fired &= std::uint8_t(~kFiredDanger);
    nb.last_dist_mm = s.dist; nb.last_seen = now;
  }
  std::sort(sc.next.begin(), sc.next.end(), [](const Binding& x, const Binding& y) { return x.entity < y.entity; });
  mem.bindings.swap(sc.next);

  // --- 4. the place as this observer perceives it -------------------------------------------------------------------------
  {
    social::gen::PlacePercept* pr = nullptr;
    st.place_percept_records.for_each([&](MRef, social::gen::PlacePercept& r) { if (!pr) pr = &r; });
    if (!pr) { auto m = st.place_percept_records.add(social::gen::PlacePercept{}, [](const social::gen::PlacePercept&) -> std::int64_t { return 0; }); pr = st.place_percept_records.find(m); }
    if (pr) {
      pr->pp_indoors = space_.indoors(sp.eye);
      pr->pp_light = sp.light;
      pr->pp_noise = static_cast<std::int16_t>(space_.ambient_noise_at(sp.eye) * std::clamp<int>(sp.hearing, 0, 100) / 100);
      pr->pp_crowd_seen = static_cast<std::int32_t>(crowd * 1000);
      const std::int32_t t = air_milli_c_;
      pr->pp_air_felt = t < 0 ? 0 : t < 8000 ? 1 : t < 15000 ? 2 : t < 22000 ? 3 : t < 30000 ? 4 : 5;
    }
  }

  }   // do_scan

  // --- 5. the acts of others: seen, heard or felt by THIS observer ----------------------------------------------------------
  for (const ActEvent& e : events) {
    if (e.actor == obs.entity()) continue;
    const std::int64_t dx = e.at_mm[0] - sp.eye[0], dy = e.at_mm[1] - sp.eye[1], dz = e.at_mm[2] + 1200 - sp.eye[2];
    const std::int64_t dist = static_cast<std::int64_t>(isqrt(static_cast<std::uint64_t>(dx * dx + dy * dy + dz * dz)));
    const std::int32_t off = (dx == 0 && dy == 0) ? 0 : wrap_angle(std::int64_t(atan2_mrad(dy, dx)) - sp.facing_mrad);
    const bool family_known = e.gesture < social::gen::kGestures.size();
    const social::gen::Family fam = family_known ? social::gen::kGestures[e.gesture].family : social::gen::Family::meta;
    std::uint16_t sight_cl = 0, hear_cl = 0;
    if (e.sight > 0) {
      const Position at{e.at_mm[0], e.at_mm[1], e.at_mm[2] + 1200};
      sight_cl = acuity::sight_clarity(sp, dist, off, space_.sight_transmission(sp.eye, at), is_attended(e.actor, dist), 60000);
    }
    if (e.noise > 0)
      hear_cl = acuity::hearing_clarity(sp, dist, e.noise, space_.sound_transmission(e.at_mm, sp.eye), space_.ambient_noise_at(sp.eye));
    const std::uint16_t need = static_cast<std::uint16_t>(300 + (10 - std::min<int>(e.sight, 10)) * 80);   // discretion asks for a clearer view
    const bool contact = fam == social::gen::Family::grasp || fam == social::gen::Family::force || fam == social::gen::Family::care;
    const bool felt = e.target == obs.entity() && contact;
    const bool seen = e.sight > 0 && sight_cl >= need;
    const bool heard = !seen && hear_cl >= 150;
    if (!seen && !heard && !felt) continue;
    social::gen::EventSeen ev;
    ev.ev_age = e.when;
    ev.ev_count = 1000;
    ev.ev_among = static_cast<std::int32_t>(std::max<std::size_t>(crowd, 1) * 1000);
    ev.ev_sense = felt && !seen ? sense::kFelt : seen ? sense::kSeen : sense::kHeard;
    const bool gesture_known = seen ? sight_cl >= rules_.min_clarity(Field::ev_gesture) : heard ? hear_cl >= 400 : true;
    if (gesture_known && e.gesture < social::gen::kGestureNames.size()) ev.ev_gesture = vocab_.word(social::gen::kGestureNames[e.gesture]);
    auto point = [&](EntityId who) -> MRef {   // the observer's own record for someone: a known file, else the percept it has now
      if (who == 0 || who == obs.entity() || !seen) return MRef{};
      if (files_ && sight_cl >= rules_.min_clarity(Field::ev_actor)) if (MRef f = files_->file_of(obs.entity(), who); f.serial) return f;
      if (const Binding* bd = find_binding(who)) return MRef{bd->pc_serial ? bd->pc_serial : bd->ep_serial};
      return MRef{};
    };
    if (seen && files_ && sight_cl >= rules_.min_clarity(Field::ev_actor)) ev.ev_actor = files_->file_of(obs.entity(), e.actor);
    ev.ev_target = point(e.target);
    ev.ev_with = point(e.with);
    ev.ev_from_to = point(e.from_to);
    const MRef rec = st.event_seen_records.add(ev, [](const social::gen::EventSeen& x) -> std::int64_t { return social::GameTime(x.ev_age); });
    if (seen) ++out.st.events_seen; else ++out.st.events_heard;
    // wakes, from the dossier just written (the act as it was perceived)
    // The wake follows what the dossier says: a blow only if the gesture is KNOWN to the witness, else the noise alone.
    const bool known_force = ev.ev_gesture != 0 && fam == social::gen::Family::force;
    if (known_force) out.wakes.push_back({obs.entity(), WakePriority::P0, WakeCause::Perception, rec.serial, felt ? std::uint8_t(10) : std::uint8_t(9)});
    else if (e.noise >= 9) out.wakes.push_back({obs.entity(), WakePriority::P0, WakeCause::Perception, rec.serial, 7});
    else if (e.noise >= 7 && !e.speech) out.wakes.push_back({obs.entity(), WakePriority::P3, WakeCause::Perception, rec.serial, 5});
    if (e.speech && (seen || heard)) {
      const std::uint16_t cl = std::max(hear_cl, std::uint16_t(0));
      if (cl >= 150) {
        const bool addressed = e.target == obs.entity();
        const bool intelligible = cl >= 300;
        out.speech.push_back({obs.entity(), e.actor, e.content, cl, addressed, intelligible, e.when});
        if (addressed && intelligible) out.wakes.push_back({obs.entity(), WakePriority::P1, WakeCause::Speech, rec.serial, 8});
      }
    }
  }
  out.st.write_ns += std::uint64_t(std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now() - t_scanned).count());
}

// ---------------------------------------------------------------------------------------------------------------
const PerceptionReport& PerceptionEngine::tick(std::span<Observer> observers, GameTime now) {
  report_.wakes.clear();
  report_.speech.clear();
  report_.stats = {};
  index_.build(store_);
  // The climate: the first entity of kind world, if any (a single weather station for v1).
  air_milli_c_ = 20000;
  bool have = false;
  store_.for_each_of(gen::EntityKind::world, [&](EntityId w) {
    if (have) return;
    if (const auto* cl = store_.component<gen::Climate>(w)) { air_milli_c_ = cl->air_temperature; have = true; }
  });
  // Events in a total order of their own, whatever the order of submission.
  std::vector<ActEvent> events = std::move(events_);
  events_.clear();
  std::sort(events.begin(), events.end(), [](const ActEvent& a, const ActEvent& b) {
    return std::tie(a.when, a.actor, a.gesture, a.target, a.with, a.from_to, a.content, a.noise, a.sight, a.speech, a.manner, a.at_mm) <
           std::tie(b.when, b.actor, b.gesture, b.target, b.with, b.from_to, b.content, b.noise, b.sight, b.speech, b.manner, b.at_mm);
  });
  // Observers in increasing EntityId order (a stable order that no thread or address changes).
  std::vector<std::uint32_t> order(observers.size());
  for (std::uint32_t i = 0; i < order.size(); ++i) order[i] = i;
  std::sort(order.begin(), order.end(), [&](std::uint32_t a, std::uint32_t b) {
    return observers[a].entity() != observers[b].entity() ? observers[a].entity() < observers[b].entity() : a < b;
  });
  std::vector<Out> outs(order.size());
  const unsigned nt = std::max(1u, std::min<unsigned>(cfg_.threads, unsigned(order.size() ? order.size() : 1)));
  auto work = [&](std::size_t lo, std::size_t hi) {
    Scratch sc;
    for (std::size_t i = lo; i < hi; ++i) observe(observers[order[i]], now, events, sc, outs[i]);
  };
  if (nt == 1) {
    work(0, order.size());
  } else {
    std::vector<std::thread> pool;
    const std::size_t chunk = (order.size() + nt - 1) / nt;
    for (unsigned t = 0; t < nt; ++t) pool.emplace_back(work, std::min(order.size(), t * chunk), std::min(order.size(), (t + 1) * chunk));
    for (auto& th : pool) th.join();
  }
  for (Out& o : outs) {
    report_.wakes.insert(report_.wakes.end(), o.wakes.begin(), o.wakes.end());
    report_.speech.insert(report_.speech.end(), o.speech.begin(), o.speech.end());
    report_.stats.observers += o.st.observers; report_.stats.candidates += o.st.candidates;
    report_.stats.perceived_people += o.st.perceived_people; report_.stats.perceived_things += o.st.perceived_things;
    report_.stats.events_seen += o.st.events_seen; report_.stats.events_heard += o.st.events_heard;
    report_.stats.rays += o.st.rays; report_.stats.scan_ns += o.st.scan_ns; report_.stats.write_ns += o.st.write_ns;
  }
  return report_;
}

}  // namespace em::act::perception
