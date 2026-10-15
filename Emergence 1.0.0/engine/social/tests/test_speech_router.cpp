// T24: the speech between minds. Parity of the pure part with the Python oracle (shapes.Perspective, governor._unfold,
// language) on shared vectors; the router on small worlds (translation by what the SPEAKER believes, never the truth;
// a rumour keeps its hops; D10 refusals reach nobody; unintelligible and missed words); determinism at 1, 4 and 8
// threads; throughput. D10 REFUSAL tests only: the intimate sentence below is refused, never produced for play.
#include <chrono>
#include <cstdio>
#include <map>
#include <memory>
#include <string>
#include <vector>

#include "emergence/social/speech_router.h"
#include "emergence/testing/check.h"

using namespace em::social;

#include "speech_vectors.inc"

namespace {

const Parser& parser() {
  static const Parser p;
  return p;
}

Proposition prop_of(std::string_view text, bool bare = false) {
  Proposition p;
  const TypedExpression e = parser().parse(text, {.bare = bare});
  CHECK(e.ok());
  CHECK(e.to_proposition(p) == ConvertStatus::ok);
  return p;
}

constexpr std::int16_t kAdultTenths = 300;

Party adult_party() { return Party{kAdultTenths, kAdultTenths, kAdultTenths, true, true, true}; }
Party child_party() { return Party{100, 100, 100, true, true, true}; }

class TestWorld final : public SpeechWorld {
 public:
  NpcBundle& add(EntityId id, Party p = adult_party()) {
    auto b = std::make_unique<NpcBundle>();
    b->state.body.alive = true;
    minds_[id] = std::move(b);
    parties_[id] = p;
    return *minds_[id];
  }
  NpcBundle& at(EntityId id) { return *minds_.at(id); }
  void know(EntityId hearer, EntityId speaker, MRef file) { files_[{hearer, speaker}] = file; }
  NpcBundle* mind(EntityId who) const override {
    auto it = minds_.find(who);
    return it == minds_.end() ? nullptr : it->second.get();
  }
  MRef file_of(EntityId h, EntityId s) const override {
    auto it = files_.find({h, s});
    return it == files_.end() ? MRef{} : it->second;
  }
  Party party_seen_by(EntityId, EntityId who) const override {
    auto it = parties_.find(who);
    return it == parties_.end() ? Party{} : it->second;
  }
  void learn(const std::vector<NewFile>& nf) { for (const NewFile& f : nf) files_[{f.hearer, f.speaker}] = f.file; }
  std::map<EntityId, std::unique_ptr<NpcBundle>> minds_;
  std::map<EntityId, Party> parties_;
  std::map<std::pair<EntityId, EntityId>, MRef> files_;
};

MRef add_person(NpcBundle& m, std::uint16_t name, EntityId truth, std::uint8_t known_by = 0) {
  gen::Relation r;
  r.r_name_believed = name; r.r_true_entity = truth; r.r_known_by = known_by; r.r_id_certainty = 90;
  return m.state.relation_records.add(r, 0);
}

PropRef say(NpcBundle& m, std::string_view text) { return m.store_proposition(prop_of(text), 100); }

MRef add_belief(NpcBundle& m, std::string_view bare, int hops, std::uint8_t source = 0) {
  gen::Belief b;
  b.b_proposition = m.store_proposition(prop_of(bare, true), 50);
  b.b_polarity = true; b.b_certainty = 80; b.b_hops = hops * 1000; b.b_source = source;
  return m.state.belief_records.add(b, 50);
}

HeardUtterance heard(EntityId l, EntityId s, PropRef c, std::uint16_t clarity = 900, bool addressed = true, GameTime when = 100) {
  return {l, s, c, clarity, addressed, clarity >= 300, when};
}

std::string belief_text(NpcBundle& m, MRef b) {
  const gen::Belief* r = m.state.belief_records.find(b);
  return r ? Parser::to_text(m.propositions.get(r->b_proposition)) : std::string("<none>");
}

std::vector<std::pair<MRef, gen::Belief>> beliefs(NpcBundle& m) {
  std::vector<std::pair<MRef, gen::Belief>> v;
  m.state.belief_records.for_each([&](MRef r, gen::Belief& b) { v.emplace_back(r, b); });
  return v;
}

}  // namespace

// ---- parity with the Python oracle --------------------------------------------------------------------------------

TEST(perspective_matches_oracle) {
  int bad = 0;
  for (const PerspectiveCase& c : kPerspectiveCases) {
    const std::string got = Perspective(c.key).text(c.text);
    if (got != c.expected && ++bad <= 5) std::printf("  perspective \"%s\" key %s: got \"%s\" expected \"%s\"\n", c.text, c.key, got.c_str(), c.expected);
  }
  std::printf("  perspective vectors: %zu cases, %d mismatches\n", std::size(kPerspectiveCases), bad);
  CHECK(std::size(kPerspectiveCases) >= 500);
  CHECK_EQ(bad, 0);
}

TEST(freeze_matches_oracle) {
  std::map<std::string, TypedExpression, std::less<>> lib;
  for (const auto& r : kSpeechLibrary) lib.emplace(r[0], parser().parse(r[1], {.bare = true}));
  RecordLookup look = [&](std::string_view ref) -> const TypedExpression* {
    auto it = lib.find(ref);
    return it == lib.end() ? nullptr : &it->second;
  };
  int bad = 0, by_status[4] = {};
  for (const FreezeCase& c : kFreezeCases) {
    const TypedExpression e = parser().parse(c.text);
    CHECK(e.ok());
    FreezeOptions o;
    o.speaker_key = c.key;
    if (c.expand) o.expand = look;
    o.miss_index = c.miss;
    o.translate = [&](std::string_view s) -> std::optional<std::string> {
      for (int i = 0; i < c.n_map; ++i) if (s == c.map[i].from) return std::string(c.map[i].to);
      return std::nullopt;
    };
    if (c.us_key) {
      const std::string us = c.us_key;
      o.freeze_us = [us]() -> std::optional<std::string> { return us.empty() ? std::nullopt : std::optional<std::string>(us); };
    }
    const FreezeResult r = freeze_speech(e, o);
    ++by_status[static_cast<int>(r.status)];
    if ((int(r.status) != c.status || r.text != c.expected) && ++bad <= 6)
      std::printf("  freeze \"%s\": status %d \"%s\", expected %d \"%s\"\n", c.text, int(r.status), r.text.c_str(), c.status, c.expected);
  }
  std::printf("  freeze vectors: %zu cases (ok %d, unexpanded %d, untranslated %d, invalid %d), %d mismatches\n", std::size(kFreezeCases),
              by_status[0], by_status[1], by_status[2], by_status[3], bad);
  CHECK(std::size(kFreezeCases) >= 3000);
  CHECK(by_status[0] > 1500 && by_status[1] > 0 && by_status[2] > 0 && by_status[3] > 0);
  CHECK_EQ(bad, 0);
}

TEST(misheard_candidates_match_oracle) {
  std::map<std::string, TypedExpression, std::less<>> lib;
  for (const auto& r : kSpeechLibrary) lib.emplace(r[0], parser().parse(r[1], {.bare = true}));
  RecordLookup look = [&](std::string_view ref) -> const TypedExpression* {
    auto it = lib.find(ref);
    return it == lib.end() ? nullptr : &it->second;
  };
  int bad = 0;
  for (const MisheardCase& c : kMisheardCases) {
    const auto un = unfold_speech(parser().parse(c.text), look);
    CHECK(un.has_value());
    if (!un) continue;
    const auto got = misheard_candidates(*un);
    bool same = got.size() >= std::size_t(c.n);
    for (int i = 0; same && i < c.n; ++i) same = got[i] == c.ids[i];
    if (!same) ++bad;
  }
  CHECK(std::size(kMisheardCases) >= 300);
  CHECK_EQ(bad, 0);
}

// ---- the router ---------------------------------------------------------------------------------------------------

TEST(a_speech_becomes_a_told_belief_with_translated_pointers) {
  TestWorld w;
  NpcBundle& a = w.add(1); NpcBundle& b = w.add(2);
  const MRef victim = add_person(a, 5, 30);               // @E<victim>: "the one named 5"
  const PropRef c = say(a, "(assert (dead @E" + std::to_string(victim.serial) + "))");
  SpeechRouter r(w);
  const HeardUtterance h = heard(2, 1, c);
  const SpeechReport& rep = r.route(std::span(&h, 1));
  CHECK_EQ(rep.stats.deliveries, 1u);
  CHECK(rep.refusals.empty());
  CHECK_EQ(rep.new_files.size(), 1u);                     // B did not know A: a referent was created for the speaker
  auto bs = beliefs(b);
  CHECK_EQ(bs.size(), 1u);
  if (bs.size() != 1) return;
  const gen::Belief& be = bs[0].second;
  CHECK(be.b_source == 2);                                 // told (addressed)
  CHECK_EQ(be.b_hops, 1000);
  CHECK(!be.b_unintelligible);
  CHECK_EQ(be.b_informant.serial, rep.new_files[0].file.serial);
  CHECK_EQ(be.b_certainty, 90);
  // the victim is a NEW referent in B's mind, named 5, not linked to anyone true
  std::uint32_t ref = 0;
  b.state.relation_records.for_each([&](MRef m, gen::Relation& rr) { if (rr.r_name_believed == 5) ref = m.serial; });
  CHECK(ref != 0);
  CHECK(belief_text(b, bs[0].first) == "(dead @E" + std::to_string(ref) + ")");
  b.state.relation_records.for_each([&](MRef, gen::Relation& rr) { CHECK_EQ(rr.r_true_entity, 0u); });
  const auto list = b.side.get(b.state.beliefs.heard_unprocessed);
  CHECK_EQ(list.size(), 1u);
  // the same speech into a hearer who knows A: no new file
  TestWorld w2;
  w2.add(1); NpcBundle& b2 = w2.add(2);
  const MRef fa = add_person(b2, 0, 1);
  w2.know(2, 1, fa);
  add_person(w2.at(1), 5, 30);
  const PropRef c2 = say(w2.at(1), "(assert (dead @E1))");
  SpeechRouter r2(w2);
  const HeardUtterance h2 = heard(2, 1, c2);
  CHECK(r2.route(std::span(&h2, 1)).new_files.empty());
  auto bs2 = beliefs(b2);
  CHECK_EQ(bs2.size(), 1u);
  CHECK_EQ(bs2[0].second.b_informant.serial, fa.serial);
}

TEST(a_mistaken_speaker_is_transmitted_as_the_one_he_calls_aldric) {
  // A calls "Aldric" (name 5) the file whose TRUE entity is Bob (30). B knows Bob by the name 6 (his file, true entity 30)
  // and does not know any Aldric: B must get a referent named 5, never Bob's file.
  TestWorld w;
  NpcBundle& a = w.add(1); NpcBundle& b = w.add(2);
  const MRef aldric = add_person(a, 5, 30);
  const MRef bob_b = add_person(b, 6, 30);
  const PropRef c = say(a, "(assert (dead @E" + std::to_string(aldric.serial) + "))");
  SpeechRouter r(w);
  const HeardUtterance h = heard(2, 1, c);
  r.route(std::span(&h, 1));
  auto bs = beliefs(b);
  CHECK_EQ(bs.size(), 1u);
  const std::string t = belief_text(b, bs[0].first);
  CHECK(t.find("@E" + std::to_string(bob_b.serial) + ")") == std::string::npos);
  std::uint32_t ref = 0;
  b.state.relation_records.for_each([&](MRef m, gen::Relation& rr) { if (rr.r_name_believed == 5) { ref = m.serial; CHECK_EQ(rr.r_true_entity, 0u); CHECK(rr.r_known_by == 1); } });
  CHECK(ref != 0);
  CHECK(t == "(dead @E" + std::to_string(ref) + ")");
  CHECK_EQ(b.state.relation_records.find(bob_b)->r_name_believed, 6);   // Bob's file untouched
  // if B knows ANOTHER person named 5 (Aldric, true entity 31), "the one he calls Aldric" is B's Aldric
  TestWorld w2;
  w2.add(1); NpcBundle& b2 = w2.add(2);
  const MRef ald2 = add_person(w2.at(1), 5, 30);
  const MRef bob2 = add_person(b2, 6, 30);
  const MRef true_ald = add_person(b2, 5, 31);
  const PropRef c2 = say(w2.at(1), "(assert (dead @E" + std::to_string(ald2.serial) + "))");
  SpeechRouter r2(w2);
  const HeardUtterance h2 = heard(2, 1, c2);
  r2.route(std::span(&h2, 1));
  auto bs2 = beliefs(b2);
  CHECK_EQ(bs2.size(), 1u);
  CHECK(belief_text(b2, bs2[0].first) == "(dead @E" + std::to_string(true_ald.serial) + ")");
  (void)bob2;
}

TEST(a_rumour_of_three_relays_keeps_three_hops) {
  TestWorld w;
  for (EntityId i = 1; i <= 4; ++i) w.add(i);
  NpcBundle& a = w.at(1);
  const MRef who = add_person(a, 5, 30);
  const MRef seen = add_belief(a, "(dead @E" + std::to_string(who.serial) + ")", 0);   // A saw it (0 hops)
  SpeechRouter r(w);
  MRef cur = seen;
  for (EntityId from = 1; from < 4; ++from) {
    const PropRef c = say(w.at(from), "(assert b:" + std::to_string(cur.serial) + ")");
    const HeardUtterance h = heard(from + 1, from, c, 900, true, 100 + from);
    const SpeechReport& rep = r.route(std::span(&h, 1));
    w.learn(rep.new_files);
    if (rep.stats.deliveries != 1) std::printf("  relay %u: refusals %zu unint %llu invalid %llu\n", unsigned(from), rep.refusals.size(), (unsigned long long)rep.stats.unintelligible, (unsigned long long)rep.stats.invalid);
    CHECK_EQ(rep.stats.deliveries, 1u);
    auto bs = beliefs(w.at(from + 1));
    CHECK_EQ(bs.size(), 1u);
    if (bs.size() != 1) return;
    CHECK_EQ(bs[0].second.b_hops, int(from) * 1000);
    cur = bs[0].first;
  }
  auto last = beliefs(w.at(4));
  CHECK_EQ(last[0].second.b_hops, 3000);
  CHECK(last[0].second.b_source == 2);
}

TEST(d10_refuses_for_everyone_when_one_hearer_may_be_a_minor) {
  TestWorld w;
  w.add(1); w.add(2); w.add(3, child_party()); w.add(4);
  NpcBundle& a = w.at(1);
  const MRef p1 = add_person(a, 5, 2), p2 = add_person(a, 6, 4);
  const std::string intimate = "(assert (did @E" + std::to_string(p1.serial) + " touch @E" + std::to_string(p2.serial) + " (how romantic)))";
  const PropRef c = say(a, intimate);
  SpeechRouter r(w);
  HeardUtterance hs[3] = {heard(2, 1, c), heard(3, 1, c), heard(4, 1, c)};
  const SpeechReport& rep = r.route(hs);
  CHECK_EQ(rep.stats.refused, 1u);
  CHECK(rep.refusals.size() == 1 && rep.refusals[0].reason == Reason::d10_hearer);
  CHECK(rep.calls.empty() && rep.new_files.empty());
  for (EntityId i : {2, 3, 4}) { CHECK(beliefs(w.at(i)).empty()); CHECK_EQ(w.at(i).state.relation_records.size(), 0); }
  // a hearer unknown to the world (no mind, no party): a possible minor
  TestWorld w2;
  w2.add(1);
  const MRef q1 = add_person(w2.at(1), 5, 2), q2 = add_person(w2.at(1), 6, 4);
  w2.parties_[2] = adult_party(); w2.add(2);
  const PropRef c2 = say(w2.at(1), "(assert (did @E" + std::to_string(q1.serial) + " touch @E" + std::to_string(q2.serial) + " (how romantic)))");
  SpeechRouter r2(w2);
  HeardUtterance hs2[2] = {heard(2, 1, c2), heard(99, 1, c2)};
  const SpeechReport& rep2 = r2.route(hs2);
  CHECK(rep2.refusals.size() == 1);
  CHECK(beliefs(w2.at(2)).empty());
  // a person of the speech whose file the speaker does not resolve is an unknown person: refused too
  TestWorld w3;
  w3.add(1); w3.add(2);
  const PropRef c3 = say(w3.at(1), "(assert (did @E7 touch @E8 (how romantic)))");
  SpeechRouter r3(w3);
  const HeardUtterance h3 = heard(2, 1, c3);
  CHECK(r3.route(std::span(&h3, 1)).refusals.size() == 1);
  CHECK(beliefs(w3.at(2)).empty());
}

TEST(a_citation_without_a_copy_is_refused_unexpanded) {
  TestWorld w;
  w.add(1); w.add(2);
  const PropRef c = say(w.at(1), "(assert b:99)");
  SpeechRouter r(w);
  const HeardUtterance h = heard(2, 1, c);
  const SpeechReport& rep = r.route(std::span(&h, 1));
  CHECK(rep.refusals.size() == 1 && rep.refusals[0].reason == Reason::unexpanded);
  CHECK(beliefs(w.at(2)).empty());
}

TEST(an_unintelligible_speech_is_a_belief_without_content) {
  TestWorld w;
  w.add(1); NpcBundle& b = w.add(2);
  add_person(w.at(1), 5, 30);
  const PropRef c = say(w.at(1), "(assert (dead @E1))");
  SpeechRouter r(w);
  const HeardUtterance h = heard(2, 1, c, 200, true);
  const SpeechReport& rep = r.route(std::span(&h, 1));
  CHECK_EQ(rep.stats.unintelligible, 1u);
  auto bs = beliefs(b);
  CHECK_EQ(bs.size(), 1u);
  CHECK(bs[0].second.b_unintelligible);
  CHECK_EQ(bs[0].second.b_proposition, 0u);
  CHECK(bs[0].second.b_informant.serial != 0);          // he knows WHO spoke to him, not what
  CHECK_EQ(b.state.request_records.size(), 0);
}

TEST(a_stranger_who_speaks_at_every_tick_keeps_one_referent) {
  TestWorld w;
  w.add(1); NpcBundle& b = w.add(2);
  const MRef nameless = add_person(w.at(1), 0, 30, 2);   // a person the speaker only describes
  const PropRef c = say(w.at(1), "(assert (dead @E" + std::to_string(nameless.serial) + "))");
  SpeechRouter r(w);
  for (int t = 0; t < 12; ++t) {
    const HeardUtterance h = heard(2, 1, c, 900, true, 100 + t);
    r.route(std::span(&h, 1));                            // the world does NOT learn the file: the router must remember it
  }
  CHECK_EQ(b.state.relation_records.size(), 2);          // the speaker and the nameless person, once each
  CHECK_EQ(b.state.belief_records.size(), 12);
}

TEST(a_refused_speech_writes_nothing_anywhere) {
  TestWorld w;
  w.add(1); w.add(2); w.add(3, child_party());
  const MRef p1 = add_person(w.at(1), 5, 2), p2 = add_person(w.at(1), 6, 3);
  const PropRef c = say(w.at(1), "(assert (did @E" + std::to_string(p1.serial) + " touch @E" + std::to_string(p2.serial) + " (how romantic)))");
  std::uint64_t before[3];
  for (EntityId i = 1; i <= 3; ++i) before[i - 1] = NpcStateCodec::fingerprint(w.at(i));
  SpeechRouter r(w);
  HeardUtterance hs[2] = {heard(2, 1, c), heard(3, 1, c)};
  const SpeechReport& rep = r.route(hs);
  CHECK_EQ(rep.refusals.size(), 1u);                     // it lives in the report (engine journal) ...
  for (EntityId i = 1; i <= 3; ++i) CHECK(NpcStateCodec::fingerprint(w.at(i)) == before[i - 1]);   // ... and in no mind
}

TEST(a_word_may_be_missed_when_the_clarity_is_low_never_when_it_is_high) {
  const std::uint16_t clarities[2] = {400, 900};
  int missed[2] = {0, 0}, intact[2] = {0, 0};
  for (int k = 0; k < 2; ++k) {
    TestWorld w;
    w.add(1);
    const MRef p = add_person(w.at(1), 5, 30);
    const PropRef c = say(w.at(1), "(assert (dead @E" + std::to_string(p.serial) + "))");
    std::vector<HeardUtterance> hs;
    for (EntityId i = 2; i < 202; ++i) { w.add(i); hs.push_back(heard(i, 1, c, clarities[k])); }
    SpeechRouter r(w);
    r.route(hs);
    for (EntityId i = 2; i < 202; ++i) {
      auto bs = beliefs(w.at(i));
      CHECK_EQ(bs.size(), 1u);
      const std::string t = belief_text(w.at(i), bs[0].first);
      (t == "(dead someone)" ? missed[k] : intact[k])++;
      if (t == "(dead someone)") CHECK(bs[0].second.b_certainty == clarities[k] / 10 - 10);
      else CHECK(bs[0].second.b_certainty == clarities[k] / 10);
    }
  }
  std::printf("  clarity 400: %d missed / %d intact; clarity 900: %d missed\n", missed[0], intact[0], missed[1]);
  CHECK(missed[0] > 20 && intact[0] > 20);
  CHECK_EQ(missed[1], 0);
}

TEST(us_is_frozen_into_a_group_and_a_request_becomes_a_request) {
  TestWorld w;
  w.add(1); NpcBundle& b = w.add(2);
  const MRef victim = add_person(w.at(1), 5, 30);
  const PropRef c = say(w.at(1), "(offer (future (caused us (dead @E" + std::to_string(victim.serial) + "))))");
  SpeechRouter r(w);
  const HeardUtterance h = heard(2, 1, c);
  const SpeechReport& rep = r.route(std::span(&h, 1));
  CHECK_EQ(rep.stats.groups, 1u);
  auto bs = beliefs(b);
  CHECK_EQ(bs.size(), 1u);
  const std::string t = belief_text(b, bs[0].first);
  CHECK(t.find(" us ") == std::string::npos && t.find("@G") != std::string::npos);
  bool found = false;
  b.state.relation_records.for_each([&](MRef, gen::Relation& rr) {
    if (rr.r_group_size == 3000) {                          // the speaker, the victim he names, and me
      found = true;
      CHECK_EQ(b.side.get(rr.r_group_members).size(), 2u);
    }
  });
  CHECK(found);
  // request
  const PropRef q = say(w.at(1), "(request (did you give silver_coin:3 (to me)))");
  const HeardUtterance hq = heard(2, 1, q, 900, true, 200);
  r.route(std::span(&hq, 1));
  CHECK_EQ(b.state.request_records.size(), 1);
  b.state.request_records.for_each([&](MRef, gen::Request& rq) {
    CHECK(Parser::to_text(b.propositions.get(rq.q_content)).substr(0, 14) == "(request (did ");
  });
  // overhearing (not addressed) a request does not make a request
  const PropRef q2 = say(w.at(1), "(request (did you give silver_coin:3 (to me)))");
  const HeardUtterance ho = heard(2, 1, q2, 900, false, 300);
  r.route(std::span(&ho, 1));
  CHECK_EQ(b.state.request_records.size(), 1);
}

namespace {

struct Village {
  TestWorld w;
  std::vector<HeardUtterance> heard;
  explicit Village(int npcs, int speeches, int hearers_each) {
    for (int i = 1; i <= npcs; ++i) {
      NpcBundle& m = w.add(i);
      for (int k = 0; k < 6; ++k) add_person(m, std::uint16_t(1 + (i + k) % 40), 1000 + (i + k) % 40);
    }
    for (int s = 0; s < speeches; ++s) {
      const EntityId sp = 1 + (s * 7) % npcs;
      NpcBundle& m = w.at(sp);
      const int a = 1 + s % 6, bb = 1 + (s / 6) % 6;
      std::string t;
      switch (s % 4) {
        case 0: t = "(assert (dead @E" + std::to_string(a) + "))"; break;
        case 1: t = "(request (did you give silver_coin:3 (to me)))"; break;
        case 2: t = "(offer (future (caused us (dead @E" + std::to_string(bb) + "))))"; break;
        default: t = "(assert (at @E" + std::to_string(a) + " @PLACE))"; break;
      }
      const PropRef c = m.store_proposition(prop_of(t), 100);
      for (int h = 1; h <= hearers_each; ++h) {
        const EntityId l = 1 + (sp - 1 + h * 13) % npcs;
        if (l == sp) continue;
        heard.push_back({l, sp, c, std::uint16_t(250 + (s * 31 + h * 97) % 750), h == 1, true, GameTime(100 + s / 50)});
        heard.back().intelligible = heard.back().clarity >= 300;
      }
    }
  }
  std::uint64_t fingerprint() const {
    std::uint64_t h = 1469598103934665603ull;
    for (const auto& kv : w.minds_) { h ^= NpcStateCodec::fingerprint(*kv.second); h *= 1099511628211ull; }
    return h;
  }
};

}  // namespace

TEST(the_result_is_the_same_with_1_4_and_8_threads) {
  std::uint64_t digest[3], print[3];
  std::size_t calls[3];
  const unsigned threads[3] = {1, 4, 8};
  for (int k = 0; k < 3; ++k) {
    Village v(60, 400, 5);
    SpeechConfig cfg; cfg.threads = threads[k];
    SpeechRouter r(v.w, cfg);
    const SpeechReport& rep = r.route(v.heard);
    digest[k] = rep.digest(); print[k] = v.fingerprint(); calls[k] = rep.calls.size();
  }
  std::printf("  1/4/8 threads: %zu calls, digest %016llx, minds %016llx\n", calls[0], (unsigned long long)digest[0], (unsigned long long)print[0]);
  CHECK(calls[0] > 1000);
  CHECK(digest[0] == digest[1] && digest[1] == digest[2]);
  CHECK(print[0] == print[1] && print[1] == print[2]);
}

TEST(throughput_in_speeches_per_second) {
  const unsigned threads[2] = {1, 8};
  for (unsigned t : threads) {
    Village v(500, 2000, 4);
    SpeechConfig cfg; cfg.threads = t;
    SpeechRouter r(v.w, cfg);
    const auto t0 = std::chrono::steady_clock::now();
    const SpeechReport& rep = r.route(v.heard);
    const double s = std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count();
    std::printf("  %u thread(s): %llu speeches, %zu hearings -> %.0f speeches/s, %.0f hearings/s (%llu refused, %llu unintelligible)\n", t,
                (unsigned long long)rep.stats.speeches, v.heard.size(), double(rep.stats.speeches) / s, double(v.heard.size()) / s,
                (unsigned long long)rep.stats.refused, (unsigned long long)rep.stats.unintelligible);
    CHECK(rep.stats.speeches == 2000);
  }
}

TEST(no_truth_in_the_hearers_dossiers) {
  Village v(60, 400, 5);
  SpeechRouter r(v.w);
  const std::size_t before = v.w.minds_.size();
  r.route(v.heard);
  std::size_t created = 0;
  for (auto& kv : v.w.minds_) {
    kv.second->state.relation_records.for_each([&](MRef, gen::Relation& rr) { if (rr.r_name_believed == 0 || rr.r_true_entity >= 1000) { /* own files */ } });
    kv.second->state.belief_records.for_each([&](MRef, gen::Belief& b) { CHECK_EQ(b.b_origin_fact, 0u); CHECK(!b.b_truth); ++created; });
  }
  CHECK(created > 0);
  CHECK_EQ(before, v.w.minds_.size());
}

EMERGENCE_TEST_MAIN()
