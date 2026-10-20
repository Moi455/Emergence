// Shared by test_gesture_executor and bench_gesture_executor: a world (store + bus), the minds of the NPCs, test doubles for
// the senses (TRUTH-peeking, tests only: the real thing is ObserverSenses over the PerceptionEngine) and a builder of decisions.
#pragma once
#include <chrono>
#include <cstdio>
#include <map>
#include <memory>
#include <set>
#include <string_view>
#include <vector>

#include "gesture_executor.h"
#include "resolver_frame.h"
#include "matter_rig.h"

namespace em::act::grig {

using social::GameTime;
using social::NpcBundle;

// TEST DOUBLE: sees everything within `range_mm` unless hidden. It reads the store because a test needs perfect eyes; the
// executor must never be given this outside tests.
class TruthEyes final : public ActorSenses {
 public:
  explicit TruthEyes(const EntityStore& store, std::int32_t range_mm = 60000) : store_(store), range_(range_mm) {}
  void hide(EntityId e) { hidden_.insert(e); }
  void show(EntityId e) { hidden_.erase(e); }
  void set_range(std::int32_t r) { range_ = r; }
  PerceivedThing perceive(EntityId actor, EntityId what) const override {
    PerceivedThing p;
    if (!what || !store_.alive(what) || !store_.alive(actor) || hidden_.count(what)) return p;
    const Position a = store_.position_mm(actor), b = store_.position_mm(what);
    const std::int64_t dx = std::int64_t{a[0]} - b[0], dy = std::int64_t{a[1]} - b[1];
    const std::int64_t d2 = dx * dx + dy * dy;
    if (d2 > std::int64_t{range_} * range_) return p;
    p.in_view = true;
    p.at = b;
    p.dist_mm = static_cast<std::int32_t>(__builtin_sqrt(static_cast<double>(d2)));
    if (const auto* app = store_.component<gen::Appearance>(what)) {
      p.down = app->condition == 2 || app->posture == 6 || app->posture == 7;
      p.dead_obvious = app->condition == 4;
      p.still = app->condition == 3 || p.dead_obvious;
      p.yields = p.down || app->posture == 4;
    }
    return p;
  }
  bool sees_kind(EntityId, std::uint32_t) const override { return false; }
  bool hears(EntityId, std::uint32_t) const override { return false; }
  bool addressed(EntityId) const override { return false; }
  bool attacked(EntityId) const override { return false; }
  bool stopped(EntityId) const override { return false; }
  bool state_seen(EntityId, EntityId, std::uint32_t) const override { return false; }
  std::int32_t have_count(EntityId, std::uint32_t) const override { return 0; }
  bool unwatched(EntityId) const override { return true; }

 private:
  const EntityStore& store_;
  std::int32_t range_;
  std::set<EntityId> hidden_;
};

// TEST DOUBLE: every answer is scripted.
class Script final : public ActorSenses {
 public:
  std::map<EntityId, PerceivedThing> seen;
  std::set<std::uint32_t> kinds, concepts;
  std::set<std::pair<EntityId, std::uint32_t>> states;
  std::int32_t held = 0;
  bool is_addressed = false, is_attacked = false, is_stopped = false, is_unwatched = true;
  PerceivedThing perceive(EntityId, EntityId what) const override {
    auto it = seen.find(what);
    return it == seen.end() ? PerceivedThing{} : it->second;
  }
  bool sees_kind(EntityId, std::uint32_t k) const override { return kinds.count(k) != 0; }
  bool hears(EntityId, std::uint32_t c) const override { return concepts.count(c) != 0; }
  bool addressed(EntityId) const override { return is_addressed; }
  bool attacked(EntityId) const override { return is_attacked; }
  bool stopped(EntityId) const override { return is_stopped; }
  bool state_seen(EntityId, EntityId w, std::uint32_t s) const override { return states.count({w, s}) != 0; }
  std::int32_t have_count(EntityId, std::uint32_t) const override { return held; }
  bool unwatched(EntityId) const override { return is_unwatched; }
};

class Minds final : public MindAccess {
 public:
  NpcBundle& add(EntityId id) {
    auto b = std::make_unique<NpcBundle>();
    b->state.body.alive = true;
    b->state.body.consciousness = 100;
    b->state.body.vision = 100;
    b->state.body.hearing = 100;
    minds_[id] = std::move(b);
    return *minds_[id];
  }
  NpcBundle* mind(EntityId who) const override {
    auto it = minds_.find(who);
    return it == minds_.end() ? nullptr : it->second.get();
  }

 private:
  std::map<EntityId, std::unique_ptr<NpcBundle>> minds_;
};

inline int value_index(Gesture g, std::string_view param, std::string_view value) {
  const auto& spec = social::gen::kGestures[static_cast<std::size_t>(g)];
  for (int p = 0; p < spec.n_params; ++p) {
    const auto& ps = spec.params[static_cast<std::size_t>(p)];
    if (ps.name != param) continue;
    for (int v = 0; v < ps.n_values; ++v) if (ps.values[static_cast<std::size_t>(v)] == value) return v;
  }
  return -1;
}

// Builds a GestureDecision by parameter names. Every given ref parameter that may designate a person is bound to an adult.
class Dec {
 public:
  Dec(EntityId actor, Gesture g, std::uint32_t seq = 1) {
    d_.actor = actor;
    d_.decision_seq = seq;
    d_.call.gesture = g;
    d_.actor_party = social::Party{300, 300, 310, true};
  }
  Dec& with(std::string_view param, std::string_view value) {
    const int i = param_index(d_.call.gesture, param);
    const int v = value_index(d_.call.gesture, param, value);
    if (i >= 0 && v >= 0) d_.call.value[static_cast<std::size_t>(i)] = static_cast<std::int8_t>(v);
    return *this;
  }
  Dec& given(std::string_view param) {   // a ref / condition / expression parameter that is present
    const int i = param_index(d_.call.gesture, param);
    if (i >= 0) d_.call.value[static_cast<std::size_t>(i)] = 0;
    return *this;
  }
  Dec& target(EntityId t) { d_.target = t; given_first_ref(0); return *this; }
  Dec& other(EntityId t) { d_.other = t; given_first_ref(1); return *this; }
  Dec& tool(EntityId t) { d_.tool = t; return *this; }
  Dec& believed(Position p) { d_.believed_at = p; d_.has_believed_at = true; return *this; }
  Dec& destination(Position p) { d_.destination = p; d_.has_destination = true; return *this; }
  Dec& until(Condition c, EntityId e = 0, std::int32_t q = 0, std::uint32_t w = 0) {
    StopCondition s; s.cond = c; s.entity = e; s.qty = q; s.word = w;
    d_.until = s;
    given("until");
    return *this;
  }
  Dec& stop(Condition c, EntityId e = 0, std::int32_t q = 0, std::uint32_t w = 0) {
    StopCondition s; s.cond = c; s.entity = e; s.qty = q; s.word = w;
    d_.stop = s;
    return *this;
  }
  Dec& plan(social::MRef p, std::uint32_t target_ref = 0) { d_.plan = p; d_.target_ref = target_ref; return *this; }
  // A content the SpeechRouter judged (check_utterance said = true): allowed. `unvalidated` removes the verdict.
  Dec& content(std::uint32_t c) {
    d_.content = c;
    given("content");
    d_.content_verdict = social::Verdict{true, 0, social::Reason::ok};
    return *this;
  }
  Dec& unvalidated() { d_.content_verdict.reset(); return *this; }
  GestureDecision& raw() { return d_; }
  const GestureDecision& get() const { return d_; }

 private:
  void given_first_ref(int nth) {
    const auto& spec = social::gen::kGestures[static_cast<std::size_t>(d_.call.gesture)];
    int seen = 0;
    for (int p = 0; p < spec.n_params; ++p)
      if (spec.params[static_cast<std::size_t>(p)].type == social::gen::ParamType::ref) {
        if (seen++ == nth) { d_.call.value[static_cast<std::size_t>(p)] = 0; return; }
      }
  }
  GestureDecision d_;
};

// Everything a test needs: the world, the minds, the executor and the glue that applies its output tick by tick.
struct Rig {
  rig::World w;
  TruthEyes eyes{w.store};
  FlatNavigation nav;
  ExecutorNavigation* navp = &nav;
  social::Governor governor;
  Minds minds;
  IngestTable ingest{w.catalog};
  ResolverFrame frame;                       // the laws of matter live in y-up: they read the mirror store of the frame adapter
  struct FlatHeight final : HeightField { std::int32_t height_mm(std::int32_t, std::int32_t) const override { return 0; } } flat;
  ZUpGround zground{flat};
  ContactResolver resolver{w.catalog, frame.store(), zground};
  ProcessEngine proc{w.catalog, frame.store(), zground};
  NpcNeedsApplier needs{w.store, minds};
  const ActorSenses* senses = &eyes;
  std::unique_ptr<GestureExecutor> ex;
  social::Party adult{300, 300, 310, true}, thing{.person = false};
  GameTime now = 100000;   // game seconds
  std::uint64_t digest_chain = 1469598103934665603ull;
  std::uint64_t reports_total = 0;
  double step_seconds = 0;                   // time spent inside GestureExecutor::step (informative, never read by the logic)
  std::vector<ExecutionReport> reports;      // all the reports so far
  std::vector<Contact> last_contacts;
  std::vector<Emission> last_emissions;
  std::map<EntityId, std::int64_t> felling;  // test sink: work left on a tree (see fell_sink)
  bool fell_sink = false;
  std::size_t min_per_thread_ = 8;

  explicit Rig(unsigned threads = 1, FlatNavigation navigation = FlatNavigation{}, std::size_t min_per_thread = 8)
      : nav(std::move(navigation)), min_per_thread_(min_per_thread) {
    w.bus.add_applier(&frame);
    w.bus.add_applier(&needs);
    rebuild(threads);
  }
  void rebuild(unsigned threads) {
    ExecutorConfig cfg;
    cfg.threads = threads;
    cfg.min_per_thread = min_per_thread_;   // tests: really split small worlds across threads
    ex = std::make_unique<GestureExecutor>(w.store, resolver, *senses, *navp, governor, minds, ingest, cfg);
  }
  void use(const ActorSenses& s, unsigned threads = 1) { senses = &s; rebuild(threads); }
  void use_nav(ExecutorNavigation& n, unsigned threads = 1) { navp = &n; rebuild(threads); }

  EntityId person(Position p, bool with_mind = true) {
    const EntityId id = w.spawn(gen::EntityKind::agent, p, 0);
    if (with_mind) minds.add(id);
    return id;
  }
  bool set(EntityId id, std::string_view name, std::int64_t value) {
    for (const auto& f : gen::kKindFields[std::size_t(w.store.kind(id))])
      if (f.name == name) {
        std::int64_t old = 0;
        if (!w.store.read_var(id, f.var, old)) return false;
        w.bus.submit(make_delta(++w.tick, 1, id, f.var, std::int32_t(old), std::int32_t(value)));
        w.bus.flush();
        return true;
      }
    return false;
  }
  std::int64_t get(EntityId id, std::string_view name) const {
    for (const auto& f : gen::kKindFields[std::size_t(w.store.kind(id))])
      if (f.name == name) { std::int64_t v = 0; w.store.read_var(id, f.var, v); return v; }
    return -1;
  }

  BeginResult start(Dec& d) {
    GestureDecision& g = d.raw();
    const auto& spec = social::gen::kGestures[static_cast<std::size_t>(g.call.gesture)];
    // A decision of the model always carries every non-optional parameter: the first value of the ones the test left out.
    for (int p = 0; p < spec.n_params; ++p)
      if (!spec.params[static_cast<std::size_t>(p)].optional && g.call.value[static_cast<std::size_t>(p)] < 0) g.call.value[static_cast<std::size_t>(p)] = 0;
    int ref_no = 0;
    for (int p = 0; p < spec.n_params; ++p) {
      const auto& ps = spec.params[static_cast<std::size_t>(p)];
      if (ps.type != social::gen::ParamType::ref) continue;
      const EntityId e = ref_no == 0 ? g.target : g.other;
      ++ref_no;
      if (g.call.value[static_cast<std::size_t>(p)] < 0) continue;
      g.call.party[static_cast<std::size_t>(p)] = (e && w.store.kind(e) == gen::EntityKind::agent) ? &adult : &thing;
    }
    const BeginResult br = ex->begin(g, now, w.tick + 1);
    if (br.status != BeginStatus::Started && verbose)
      std::printf("  begin %s: status %d, reason %s\n", social::gen::kGestureNames[static_cast<std::size_t>(g.call.gesture)].data(),
                  int(br.status), social::to_string(br.verdict.reason).data());
    return br;
  }
  bool verbose = true;

  // One tick: the executor steps, its contacts go through the ProcessEngine, everything is submitted and flushed.
  const StepOutput& tick() {
    const std::uint64_t t = ++w.tick;
    const auto t0 = std::chrono::steady_clock::now();
    const StepOutput& out = ex->step(t, now);
    step_seconds += std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count();
    digest_chain = (digest_chain ^ out.digest()) * 1099511628211ull;
    std::vector<Emission> all = out.emissions;
    last_contacts = out.contacts;
    last_emissions = out.emissions;
    if (!out.contacts.empty()) {
      if (fell_sink) apply_fell_sink(out.contacts, t, all);
      else {
        std::vector<Emission> from_laws;
        const std::vector<LawReport> laws = proc.on_contacts(ResolverFrame::to_resolver(out.contacts), t, from_laws);
        for (Emission& e : from_laws) all.push_back(ResolverFrame::to_world(std::move(e)));
        ex->contact_results(out.contacts, laws);
      }
    }
    ProcessEngine::submit_all(w.bus, all);
    w.bus.flush();
    for (const ExecutionReport& r : out.reports) reports.push_back(r);
    reports_total += out.reports.size();
    now += kTickGameS;
    return out;
  }
  // Runs until the actor's execution ends (or max ticks); returns the number of ticks. The last report is reports.back().
  int run(EntityId actor, int max_ticks = 4000) {
    int n = 0;
    while (ex->busy(actor) && n < max_ticks) { tick(); ++n; }
    return n;
  }
  const ExecutionReport* report_of(EntityId actor) const {
    for (auto it = reports.rbegin(); it != reports.rend(); ++it) if (it->npc == actor) return &*it;
    return nullptr;
  }

  // TEST SINK for a thing that takes `units` of real-life work to fall (an oak: 2000 blows of an axe): each contact brings
  // compressed_work(1, productive) units; at zero the thing is destroyed through the bus. Physics of the laws of matter is
  // tested elsewhere (test_matter_laws); this isolates the TIME of the executor.
  void apply_fell_sink(const std::vector<Contact>& contacts, std::uint64_t t, std::vector<Emission>& all) {
    for (const Contact& c : contacts) {
      auto it = felling.find(c.target);
      if (it == felling.end() || !w.store.alive(c.target)) continue;
      it->second -= compressed_work(1, c.productive);
      if (it->second <= 0) {
        Emission e;
        e.op = make_destroy(t, c.author, c.target);
        e.decision_seq = c.decision_seq;
        e.k = 900;
        all.push_back(e);
        felling.erase(it);
      }
    }
  }
};

}  // namespace em::act::grig
