#include "emergence/social/speech_router.h"

#include <algorithm>
#include <chrono>
#include <thread>

#include "pointer_util.h"

namespace em::social {

namespace {

const Parser& parser() {
  static const Parser p;
  return p;
}

// ---- a generic S-expression (the oracle's Node / str) ----------------------------------------------------------
struct Sx {
  bool list = false;
  std::string atom;        // a leaf
  std::vector<Sx> items;   // a list: items[0] is the head (a leaf)
};

bool parse_sx(std::string_view t, std::size_t& pos, Sx& out, int depth = 0) {
  while (pos < t.size() && t[pos] == ' ') ++pos;
  if (pos >= t.size() || depth > 64) return false;
  if (t[pos] == ')') return false;
  if (t[pos] != '(') {
    const std::size_t b = pos;
    while (pos < t.size() && t[pos] != ' ' && t[pos] != '(' && t[pos] != ')') ++pos;
    out.list = false;
    out.atom.assign(t.substr(b, pos - b));
    return true;
  }
  ++pos;
  out.list = true;
  for (;;) {
    while (pos < t.size() && t[pos] == ' ') ++pos;
    if (pos >= t.size()) return false;
    if (t[pos] == ')') { ++pos; break; }
    Sx child;
    if (!parse_sx(t, pos, child, depth + 1)) return false;
    out.items.push_back(std::move(child));
  }
  return !out.items.empty() && !out.items[0].list;
}

bool parse_whole(std::string_view t, Sx& out) {
  std::size_t pos = 0;
  if (!parse_sx(t, pos, out)) return false;
  while (pos < t.size() && t[pos] == ' ') ++pos;
  return pos == t.size();
}

void print_sx(const Sx& n, std::string& out) {
  if (!n.list) { out += n.atom; return; }
  out += '(';
  for (std::size_t i = 0; i < n.items.size(); ++i) {
    if (i) out += ' ';
    print_sx(n.items[i], out);
  }
  out += ')';
}

bool unfold_node(const Sx& n, int depth, Sx& out, const RecordLookup& expand, const std::function<void(std::string_view)>& on_cite) {
  if (!n.list) {
    if (!detail::is_cite(n.atom)) { out = n; return true; }
    if (!expand || depth > 2) return false;
    const TypedExpression* inner = expand(n.atom);
    if (!inner || !inner->ok()) return false;
    if (on_cite) on_cite(n.atom);
    Sx in;
    if (!parse_whole(inner->canonical_text(), in)) return false;
    return unfold_node(in, depth + 1, out, expand, on_cite);
  }
  if (n.items[0].atom == "that") {
    if (n.items.size() < 2) return false;
    return unfold_node(n.items[1], depth, out, expand, on_cite);
  }
  out.list = true;
  out.items.clear();
  out.items.push_back(n.items[0]);
  for (std::size_t i = 1; i < n.items.size(); ++i) {
    Sx c;
    if (!unfold_node(n.items[i], depth, c, expand, on_cite)) return false;
    out.items.push_back(std::move(c));
  }
  return true;
}

bool is_identity(std::string_view s) {
  std::string_view pre; std::uint32_t n;
  return detail::parse_pointer(s, pre, n) && (pre == "@E" || pre == "@G" || pre == "n:");
}

std::uint64_t fnv(std::uint64_t h, std::uint64_t v, int bytes = 8) {
  for (int i = 0; i < bytes; ++i) { h ^= (v >> (8 * i)) & 0xFF; h *= 1099511628211ull; }
  return h;
}
constexpr std::uint64_t kFnvBasis = 1469598103934665603ull;

}  // namespace

// ---- Perspective -------------------------------------------------------------------------------------------------

Perspective::Perspective(std::string speaker_key, std::string hearer_self) : key_(std::move(speaker_key)), self_(std::move(hearer_self)) {
  std::string_view pre; std::uint32_t n;
  valid_ = key_ == "@PLACE" || detail::parse_pointer(key_, pre, n);
}

std::string Perspective::text(std::string_view utterance) const {
  Sx root;
  if (!valid_ || !parse_whole(utterance, root) || !root.list) return {};
  struct Walk {
    const Perspective& p;
    void run(Sx& n, bool head) const {
      if (!n.list) {
        if (head) return;
        if (n.atom == "me") n.atom = p.key_;
        else if (n.atom == "you") n.atom = p.self_;
        return;
      }
      for (std::size_t i = 0; i < n.items.size(); ++i) run(n.items[i], i == 0);
    }
  } w{*this};
  w.run(root, false);
  std::string out;
  print_sx(root, out);
  return out;
}

// ---- freezing ----------------------------------------------------------------------------------------------------

std::optional<std::string> unfold_speech(const TypedExpression& utterance, const RecordLookup& expand,
                                         const std::function<void(std::string_view)>& on_cite) {
  Sx root, out;
  if (!parse_whole(utterance.canonical_text(), root) || !root.list) return std::nullopt;
  if (!unfold_node(root, 0, out, expand, on_cite)) return std::nullopt;
  std::string s;
  print_sx(out, s);
  return s;
}

std::vector<std::string> misheard_candidates(std::string_view unfolded_text) {
  std::vector<std::string> v;
  detail::for_each_token(unfolded_text, [&](std::string_view t) { if (is_identity(t)) v.emplace_back(t); });
  return v;
}

FreezeResult freeze_unfolded(std::string_view unfolded_text, const FreezeOptions& opt) {
  FreezeResult r;
  Sx root;
  if (!parse_whole(unfolded_text, root) || !root.list) return r;
  Perspective persp(opt.speaker_key);
  if (!persp.valid()) return r;
  int cand = 0;
  bool untranslated = false;
  struct Walk {
    const FreezeOptions& o; int& cand; bool& bad;
    void run(Sx& n, bool head) const {
      if (n.list) { for (std::size_t i = 0; i < n.items.size(); ++i) run(n.items[i], i == 0); return; }
      if (head) return;
      const std::string a = n.atom;
      if (is_identity(a) && cand++ == o.miss_index) { n.atom = "someone"; return; }
      if (a == "me") { n.atom = o.speaker_key; return; }
      if (a == "you") { n.atom = "me"; return; }
      if (a == "us") {
        if (!o.freeze_us) return;
        if (auto g = o.freeze_us()) n.atom = *g; else bad = true;
        return;
      }
      std::string_view pre; std::uint32_t num;
      if (detail::parse_pointer(a, pre, num) && (pre == "@E" || pre == "@G" || pre == "@T" || pre == "@L" || pre == "@V")) {
        std::optional<std::string> t = o.translate ? o.translate(a) : std::nullopt;
        if (t) n.atom = *t; else bad = true;
      }
    }
  } w{opt, cand, untranslated};
  w.run(root, false);
  if (untranslated) { r.status = FreezeStatus::untranslated; return r; }
  std::string text;
  print_sx(root, text);
  const TypedExpression e = parser().parse(text);
  if (!e.ok()) { r.status = FreezeStatus::invalid_for_hearer; return r; }
  r.status = FreezeStatus::ok;
  r.text = e.canonical_text();
  return r;
}

FreezeResult freeze_speech(const TypedExpression& utterance, const FreezeOptions& opt) {
  FreezeResult r;
  std::optional<std::string> text = opt.already_unfolded ? std::optional<std::string>(utterance.canonical_text())
                                                          : unfold_speech(utterance, opt.expand);
  if (!text) { r.status = FreezeStatus::unexpanded; return r; }
  return freeze_unfolded(*text, opt);
}

// ---- the router --------------------------------------------------------------------------------------------------

std::uint64_t SpeechReport::digest() const {
  std::uint64_t h = kFnvBasis;
  for (const HearCall& c : calls) {
    h = fnv(h, c.hearer, 4); h = fnv(h, c.speaker, 4); h = fnv(h, std::uint64_t(c.kind), 1); h = fnv(h, c.serial, 4);
    h = fnv(h, c.hops, 2); h = fnv(h, std::uint16_t(c.certainty), 2); h = fnv(h, std::uint64_t(c.when));
  }
  for (const SpeechRefusal& r : refusals) {
    h = fnv(h, r.speaker, 4); h = fnv(h, r.content, 4); h = fnv(h, std::uint64_t(r.reason), 1); h = fnv(h, std::uint64_t(r.when));
  }
  for (const NewFile& f : new_files) { h = fnv(h, f.hearer, 4); h = fnv(h, f.speaker, 4); h = fnv(h, f.file.serial, 4); }
  return h;
}

namespace {

constexpr std::uint8_t kSourceHeard = 1, kSourceTold = 2;
constexpr std::int16_t kNeutralImportance = 50;
constexpr std::uint8_t kKnownBySeen = 0, kKnownByName = 1, kKnownByDescribed = 2;

struct Fact {
  std::string symbol;
  char kind = 'E';           // E G T L V
  bool found = false;
  std::uint16_t name = 0, group_kind = 0;
  std::uint8_t known_by = kKnownByDescribed;
  std::string kind_word;     // @T and @L: the word of the speaker's record
};

struct Packet {
  EntityId speaker = 0;
  PropRef content = 0;
  GameTime when = 0;
  bool valid = false, allowed = false;
  Reason reason = Reason::ok;
  std::string unfolded, mood;
  std::uint32_t hops = 1;
  std::vector<Fact> facts;
  std::vector<HeardUtterance> hearers;   // by listener id
};

std::string symbol_text(std::uint32_t symbol) {
  if (symbol == 0) return {};
  if (symbol < gen::kWords.size()) return std::string(gen::kWords[symbol]);
  const std::size_t k = symbol - gen::kWords.size();
  return k < gen::kKinds.size() ? std::string(gen::kKinds[k]) : std::string();
}

void build_packet(const SpeechWorld& world, Packet& pk, std::span<const HeardUtterance> heard_all) {
  NpcBundle* sm = world.mind(pk.speaker);
  if (!sm || pk.content == 0) return;
  const Proposition prop = sm->propositions.get(pk.content);
  if (prop.empty()) return;
  const TypedExpression expr = parser().parse(Parser::to_text(prop));
  if (!expr.ok()) return;
  pk.valid = true;
  MindView view(*sm, pk.speaker, &world);
  PartyBindings pb;
  view.bind_pointers(expr.canonical_text(), pb);
  const std::vector<PartyBinding> bindings = pb.view();
  const Party speaker = view.self_party();
  std::vector<Party> hp;
  hp.reserve(pk.hearers.size());
  for (const HeardUtterance& h : pk.hearers) hp.push_back(world.party_seen_by(pk.speaker, h.listener));
  std::vector<const Party*> hptr;
  for (const Party& p : hp) hptr.push_back(&p);
  const Verdict v = Governor().check_utterance(expr, &speaker, bindings, hptr, view.lookup(), true);
  pk.reason = v.reason;
  if (!v.allowed) return;
  std::uint32_t max_hops = 0;
  auto on_cite = [&](std::string_view ref) {
    if (ref.size() > 1 && (ref[0] == 'b' || ref[0] == 'h')) {
      std::string_view pre; std::uint32_t n = 0;
      detail::parse_pointer(ref, pre, n);
      if (const gen::Belief* b = sm->state.belief_records.find(MRef{n})) max_hops = std::max<std::uint32_t>(max_hops, std::uint32_t(std::max(0, b->b_hops / 1000)));
    }
  };
  const std::optional<std::string> un = unfold_speech(expr, view.lookup(), on_cite);
  if (!un) { pk.reason = Reason::unexpanded; return; }
  pk.allowed = true;
  pk.unfolded = *un;
  pk.hops = std::min<std::uint32_t>(max_hops + 1, 255);
  const std::size_t sp = un->find(' ');
  pk.mood = un->substr(1, (sp == std::string::npos ? un->size() : sp) - 1);
  // facts about the speaker's pointers, taken from HIS mind (what he believes, never the truth)
  detail::for_each_token(*un, [&](std::string_view tok) {
    std::string_view pre; std::uint32_t n;
    if (!detail::parse_pointer(tok, pre, n)) return;
    if (pre != "@E" && pre != "@G" && pre != "@T" && pre != "@L" && pre != "@V") return;
    for (const Fact& f : pk.facts) if (f.symbol == tok) return;
    Fact f;
    f.symbol = std::string(tok);
    f.kind = pre[1];
    if (f.kind == 'E' || f.kind == 'G') {
      if (const gen::Relation* r = sm->state.relation_records.find(MRef{n})) {
        f.found = true; f.name = r->r_name_believed; f.group_kind = r->r_group_kind; f.known_by = r->r_known_by;
      }
    } else if (f.kind == 'T') {
      if (const gen::Percept* p = sm->state.percept_records.find(MRef{n})) { f.kind_word = symbol_text(p->pc_kind_seen); f.found = !f.kind_word.empty(); }
    } else if (f.kind == 'L') {
      if (const gen::Locus* l = sm->state.locus_records.find(MRef{n})) { f.kind_word = symbol_text(l->lc_kind); f.found = !f.kind_word.empty(); }
    }
    pk.facts.push_back(std::move(f));
  });
  (void)heard_all;
}

// The writes of ONE hearer for the packets that reached him.
class HearerTask {
 public:
  HearerTask(const SpeechWorld& w, const SpeechConfig& c, EntityId id, NpcBundle& m, std::vector<std::pair<std::string, std::uint32_t>>& memory)
      : world_(w), cfg_(c), id_(id), mind_(m), mem_(memory) {}

  void run(const Packet& pk, const HeardUtterance& h, std::vector<HearCall>& calls, std::vector<NewFile>& files, SpeechStats& st);

 private:
  MRef make_referent(std::uint16_t name, std::uint8_t known_by, std::uint16_t group_kind, GameTime now) {
    gen::Relation r;
    r.r_name_believed = name;
    r.r_known_by = known_by;
    r.r_group_kind = group_kind;
    return mind_.state.relation_records.add(r, now);   // r_true_entity stays 0: nothing true is written here
  }
  std::uint32_t find_by_name(std::uint16_t name, bool group, std::uint16_t group_kind) {
    std::uint32_t best = 0;
    mind_.state.relation_records.for_each([&](MRef ref, gen::Relation& r) {
      if (r.r_name_believed != name) return;
      if (group ? (r.r_group_kind != group_kind) : (r.r_group_kind != 0)) return;
      if (best == 0 || ref.serial < best) best = ref.serial;
    });
    return best;
  }

  const SpeechWorld& world_;
  const SpeechConfig& cfg_;
  EntityId id_;
  NpcBundle& mind_;
  // (speaker, symbol) -> last referent created, kept by the router between ticks (see SpeechRouter::memory_)
  std::vector<std::pair<std::string, std::uint32_t>>& mem_;
  std::uint32_t remembered(const std::string& key) {
    for (auto& p : mem_) if (p.first == key && mind_.state.relation_records.find(MRef{p.second})) return p.second;
    return 0;
  }
  void remember(const std::string& key, std::uint32_t serial) {
    for (auto it = mem_.begin(); it != mem_.end(); ++it) if (it->first == key) { mem_.erase(it); break; }
    mem_.emplace_back(key, serial);
    if (mem_.size() > 32) mem_.erase(mem_.begin());
  }
};

void HearerTask::run(const Packet& pk, const HeardUtterance& h, std::vector<HearCall>& calls, std::vector<NewFile>& files, SpeechStats& st) {
  const GameTime now = h.when;
  auto emit = [&](HearKind k, std::uint32_t serial, std::uint16_t hops, std::int16_t cert) {
    calls.push_back({id_, pk.speaker, k, serial, hops, cert, now});
  };
  // 1. who spoke, in MY mind
  std::uint32_t spk = world_.file_of(id_, pk.speaker).serial;
  if (spk && !mind_.state.relation_records.find(MRef{spk})) spk = 0;
  const std::string skey_mem = "S" + std::to_string(pk.speaker);
  if (!spk) spk = remembered(skey_mem);
  if (!spk) {
    spk = make_referent(0, kKnownByDescribed, 0, now).serial;
    remember(skey_mem, spk);
    files.push_back({id_, pk.speaker, MRef{spk}});
    emit(HearKind::referent, spk, 0, 0);
    ++st.referents;
  }
  const std::int16_t clarity_cert = static_cast<std::int16_t>(std::min<int>(h.clarity, 1000) / 10);
  const std::uint8_t source = h.addressed ? kSourceTold : kSourceHeard;
  auto add_belief = [&](PropRef ref, bool unintelligible, std::uint16_t hops, std::int16_t cert) {
    gen::Belief b;
    b.b_proposition = ref; b.b_polarity = true; b.b_certainty = cert; b.b_importance = kNeutralImportance;
    b.b_source = source; b.b_informant = MRef{spk}; b.b_hops = std::int32_t(hops) * 1000;
    b.b_acquired = now; b.b_confirmed = now; b.b_unintelligible = unintelligible;
    const MRef ser = mind_.state.belief_records.add(b, now);
    std::vector<std::uint32_t> list;
    const auto cur = mind_.side.get(mind_.state.beliefs.heard_unprocessed);
    list.assign(cur.begin(), cur.end());
    list.push_back(ser.serial);
    while (list.size() > cfg_.heard_cap) list.erase(list.begin());
    mind_.side.release(mind_.state.beliefs.heard_unprocessed);
    mind_.state.beliefs.heard_unprocessed = mind_.side.put(list);
    emit(unintelligible ? HearKind::unintelligible : HearKind::belief, ser.serial, hops, cert);
    return ser;
  };
  auto unintelligible = [&] {
    add_belief(0, true, 1, clarity_cert);
    ++st.unintelligible;
  };
  if (!h.intelligible || h.clarity < cfg_.min_clarity) { unintelligible(); return; }

  // 2. which identity (if any) I fail to catch: a hash of the speech and of me, never a random draw
  int miss = -1;
  const std::vector<std::string> cands = misheard_candidates(pk.unfolded);
  if (h.clarity < cfg_.clear_clarity && !cands.empty()) {
    std::uint64_t x = fnv(kFnvBasis, id_, 4);
    x = fnv(x, pk.speaker, 4); x = fnv(x, pk.content, 4); x = fnv(x, std::uint64_t(pk.when)); x = fnv(x, 0x6D697373);
    const unsigned p = (cfg_.clear_clarity - h.clarity) * 1000u / (cfg_.clear_clarity - cfg_.min_clarity);   // per-mille
    if (x % 1000 < p) miss = static_cast<int>((x >> 20) % cands.size());
  }
  // 3. translate the pointers of the speaker through what HE believes about each of them
  const std::string skey = "@E" + std::to_string(spk);
  std::vector<std::pair<std::string, std::optional<std::string>>> tr;
  std::vector<std::uint32_t> named_files;
  for (const Fact& f : pk.facts) {
    std::optional<std::string> out;
    if (f.kind == 'T' || f.kind == 'L') {
      if (f.found) out = f.kind_word;
    } else if (f.kind == 'E' || f.kind == 'G') {
      bool is_missed = false;
      if (miss >= 0 && static_cast<std::size_t>(miss) < cands.size() && cands[miss] == f.symbol) {
        // the missed identity is replaced by `someone` in the text; only count it as missed if it is the ONLY mention
        is_missed = true;
        int mentions = 0;
        for (const std::string& c : cands) mentions += c == f.symbol;
        if (mentions != 1) is_missed = false;
      }
      if (f.found && !is_missed) {
        const bool group = f.kind == 'G';
        std::uint32_t ser = f.name ? find_by_name(f.name, group, f.group_kind) : 0;
        if (!ser) {
          const std::string key = std::to_string(pk.speaker) + ":" + f.symbol;
          ser = remembered(key);
          if (!ser) {
            ser = make_referent(f.name, f.name ? kKnownByName : kKnownByDescribed, group ? f.group_kind : 0, now).serial;
            remember(key, ser);
            emit(HearKind::referent, ser, 0, 0);
            ++st.referents;
          }
        }
        out = std::string(group ? "@G" : "@E") + std::to_string(ser);
        named_files.push_back(ser);
      }
    }
    tr.emplace_back(f.symbol, std::move(out));
  }
  FreezeOptions fo;
  fo.speaker_key = skey;
  fo.already_unfolded = true;
  fo.miss_index = miss;
  fo.translate = [&](std::string_view sym) -> std::optional<std::string> {
    for (auto& p : tr) if (p.first == sym) return p.second;
    return std::nullopt;
  };
  // `us`: frozen now into a group referent: the speaker, the people he names, and me when he speaks to me
  const bool has_us = [&] { bool u = false; detail::for_each_token(pk.unfolded, [&](std::string_view t) { u = u || t == "us"; }); return u; }();
  if (has_us) {
    fo.freeze_us = [&]() -> std::optional<std::string> {
      std::vector<std::uint32_t> members{spk};
      for (std::uint32_t f : named_files) if (std::find(members.begin(), members.end(), f) == members.end()) members.push_back(f);
      std::sort(members.begin() + 1, members.end());
      const MRef g = make_referent(0, kKnownByDescribed, 0, now);
      if (gen::Relation* r = mind_.state.relation_records.find(g)) {
        r->r_group_members = mind_.side.put(members);
        r->r_group_size = std::int32_t(members.size() + (h.addressed ? 1 : 0)) * 1000;
      }
      emit(HearKind::group, g.serial, 0, 0);
      ++st.groups;
      return "@G" + std::to_string(g.serial);
    };
  }
  const FreezeResult fr = freeze_unfolded(pk.unfolded, fo);
  if (fr.status != FreezeStatus::ok) { if (fr.status == FreezeStatus::untranslated) ++st.untranslated; unintelligible(); return; }
  // What he asserted is kept as the BARE proposition ("he told me that P": a belief told, whose informant is noted), so that
  // it can be cited and relayed; any other mood (request, offer, ask...) keeps the whole utterance.
  Proposition prop;
  std::string kept = fr.text;
  bool bare = false;
  if (pk.mood == "assert" && kept.size() > 9 && kept.compare(0, 8, "(assert ") == 0 && kept.back() == ')') {
    const std::string inner = kept.substr(8, kept.size() - 9);
    if (parser().parse(inner, {.bare = true}).ok()) { kept = inner; bare = true; }
  }
  if (parser().parse(kept, {.bare = bare}).to_proposition(prop) != ConvertStatus::ok) { unintelligible(); return; }
  const PropRef ref = mind_.store_proposition(prop, now);
  if (ref == 0) { unintelligible(); return; }
  std::int16_t cert = clarity_cert;
  if (miss >= 0) { cert = std::max<std::int16_t>(0, cert - 10); ++st.missed_words; }
  add_belief(ref, false, static_cast<std::uint16_t>(pk.hops), cert);
  ++st.deliveries;
  if (pk.mood == "request" && h.addressed) {
    const PropRef qref = mind_.store_proposition(prop, now);
    if (qref) {
      gen::Request q;
      q.q_content = qref; q.q_from = MRef{spk}; q.q_since = now;
      const MRef qs = mind_.state.request_records.add(q, now);
      emit(HearKind::request, qs.serial, 0, 0);
      ++st.requests;
    }
  }
}

template <class F>
void parallel_for(std::size_t n, unsigned threads, F&& f) {
  if (threads <= 1 || n < 2) { for (std::size_t i = 0; i < n; ++i) f(i); return; }
  const unsigned t = std::min<std::size_t>(threads, n);
  std::vector<std::thread> pool;
  for (unsigned k = 0; k < t; ++k)
    pool.emplace_back([&, k] { for (std::size_t i = k; i < n; i += t) f(i); });   // interleaved: the results are indexed, order is irrelevant
  for (auto& th : pool) th.join();
}

}  // namespace

const SpeechReport& SpeechRouter::route(std::span<const HeardUtterance> heard) {
  report_ = SpeechReport{};
  // speeches: (when, speaker, content), hearers by listener
  std::vector<HeardUtterance> all(heard.begin(), heard.end());
  std::sort(all.begin(), all.end(), [](const HeardUtterance& a, const HeardUtterance& b) {
    if (a.when != b.when) return a.when < b.when;
    if (a.speaker != b.speaker) return a.speaker < b.speaker;
    if (a.content != b.content) return a.content < b.content;
    if (a.listener != b.listener) return a.listener < b.listener;
    return a.clarity > b.clarity;
  });
  std::vector<Packet> packets;
  for (const HeardUtterance& h : all) {
    if (h.listener == h.speaker) continue;
    if (packets.empty() || packets.back().when != h.when || packets.back().speaker != h.speaker || packets.back().content != h.content) {
      Packet p; p.speaker = h.speaker; p.content = h.content; p.when = h.when;
      packets.push_back(std::move(p));
    }
    auto& hs = packets.back().hearers;
    if (hs.empty() || hs.back().listener != h.listener) hs.push_back(h);
  }
  parallel_for(packets.size(), cfg_.threads, [&](std::size_t i) { build_packet(world_, packets[i], all); });
  for (const Packet& pk : packets) {
    ++report_.stats.speeches;
    if (!pk.valid) { ++report_.stats.invalid; continue; }
    if (!pk.allowed) {
      ++report_.stats.refused;
      ++report_.stats.refused_by_reason[static_cast<std::size_t>(pk.reason)];
      report_.refusals.push_back({pk.speaker, pk.content, pk.reason, pk.when, pk.hearers.size()});
    }
  }
  // hearers: each one receives the packets that reached him, in packet order
  std::vector<std::pair<EntityId, std::vector<std::pair<std::uint32_t, std::uint32_t>>>> per;   // hearer -> (packet, hearer index)
  {
    std::map<EntityId, std::vector<std::pair<std::uint32_t, std::uint32_t>>> m;
    for (std::uint32_t i = 0; i < packets.size(); ++i) {
      if (!packets[i].allowed) continue;
      for (std::uint32_t j = 0; j < packets[i].hearers.size(); ++j) m[packets[i].hearers[j].listener].emplace_back(i, j);
    }
    for (auto& kv : m) per.emplace_back(kv.first, std::move(kv.second));
  }
  struct Out { std::vector<HearCall> calls; std::vector<NewFile> files; SpeechStats st; };
  std::vector<Out> outs(per.size());
  std::vector<std::vector<std::pair<std::string, std::uint32_t>>*> mem(per.size());
  for (std::size_t k = 0; k < per.size(); ++k) mem[k] = &memory_[per[k].first];   // entries made before the threads start
  parallel_for(per.size(), cfg_.threads, [&](std::size_t k) {
    NpcBundle* m = world_.mind(per[k].first);
    if (!m) return;
    HearerTask task(world_, cfg_, per[k].first, *m, *mem[k]);
    for (auto [pi, hi] : per[k].second) task.run(packets[pi], packets[pi].hearers[hi], outs[k].calls, outs[k].files, outs[k].st);
  });
  SpeechStats& s = report_.stats;
  for (Out& o : outs) {
    report_.calls.insert(report_.calls.end(), o.calls.begin(), o.calls.end());
    report_.new_files.insert(report_.new_files.end(), o.files.begin(), o.files.end());
    s.deliveries += o.st.deliveries; s.unintelligible += o.st.unintelligible; s.requests += o.st.requests;
    s.referents += o.st.referents; s.groups += o.st.groups; s.missed_words += o.st.missed_words; s.untranslated += o.st.untranslated;
  }
  return report_;
}

}  // namespace em::social
