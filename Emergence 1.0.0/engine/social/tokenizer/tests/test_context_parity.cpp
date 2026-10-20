// T28b parity: the sampler situations (quantised to the grid of the state, expectations from the Python oracle) are loaded
// into an NpcState by the reverse loader, the ContextBuilder rebuilds the dossiers, the Tokenizer encodes them, and the arrays
// (their crc32, the number of tokens, the ghosts) must be the oracle's.
//
//   test_context_parity corpus.jsonl [--selection=forced|salience|both] [--limit=N] [--bench=SECONDS] [--verbose=N]
//
//   forced   : the dossier carries exactly the records the sampler carried, in its order (tests the whole construction: values,
//              keys, ghosts, unknown fields, the wake, lists; not the choice)
//   salience : the integer salience chooses (the real path). Differences of CHOICE with the sampler are measured and listed.
#include <algorithm>
#include <chrono>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <map>
#include <set>
#include <string>
#include <vector>

#include "emergence/social/tokenizer/context_builder.h"
#include "context_compare.h"
#include "mind_loader.h"

using namespace em::social;
using namespace em::social::tok2;
using em::social::tok2::testing::same;
using em::social::tok2::testing::show;

namespace {

struct Tally {
  long cases = 0, ok = 0, bad = 0, refused = 0, lost_cases = 0, same_set = 0, diff_set = 0, same_order = 0, canon_ok = 0, clamped = 0, dropped = 0, skipped = 0;
  std::map<std::string, long> field_diffs, lost, omitted, added;
  double load_s = 0, build_s = 0, encode_s = 0;
};

// field-by-field comparison of the rebuilt dossiers against the oracle's context
void diff_contexts(const DecisionContext& want, const DecisionContext& got, const Tokenizer& tk, Tally& t, std::vector<std::string>* sample) {
  std::map<std::string, const Record*> g;
  for (const Record& r : got.records) g[r.key] = &r;
  std::set<std::string> seen;
  for (const Record& w : want.records) {
    seen.insert(w.key);
    const auto it = g.find(w.key);
    if (it == g.end()) { ++t.field_diffs[w.type + ":record missing"]; if (sample) sample->push_back("missing record " + w.key); continue; }
    std::map<int, const Value*> gf;
    for (const Field& f : it->second->fields) gf[f.col] = &f.value;
    std::set<int> cols;
    for (const Field& f : w.fields) {
      cols.insert(f.col);
      if (f.value.is_null() || (f.value.is_dict() && f.value.members().empty())) {      // null and {} both mean "unknown": same arrays
        const auto o = gf.find(f.col);
        if (o != gf.end()) { ++t.field_diffs[w.type + "." + std::string(tk.column_def(w.type_index, f.col).name) + " extra(unknown in the oracle)"]; }
        continue;
      }
      const std::string name = w.type + "." + std::string(tk.column_def(w.type_index, f.col).name);
      const auto o = gf.find(f.col);
      if (o == gf.end()) { ++t.field_diffs[name + " missing"]; if (sample) sample->push_back(w.key + " " + name + " missing, want " + show(f.value)); }
      else if (!same(f.value, *o->second)) { ++t.field_diffs[name + " differs"]; if (sample) sample->push_back(w.key + " " + name + " want " + show(f.value) + " got " + show(*o->second)); }
    }
    for (const auto& [c, v] : gf)
      if (!cols.count(c)) { const std::string name = w.type + "." + std::string(tk.column_def(w.type_index, c).name); ++t.field_diffs[name + " extra"]; if (sample) sample->push_back(w.key + " " + name + " extra " + show(*v)); }
  }
  for (const Record& r : got.records)
    if (!seen.count(r.key)) { ++t.field_diffs[r.type + ":record extra"]; if (sample) sample->push_back("extra record " + r.key); }
}

// keys in the natural order of their number: b:2 before b:10
bool key_less(const std::string& p, const std::string& q) {
  const auto split = [](const std::string& k) { const std::size_t i = k.find_first_of("0123456789"); return std::make_pair(k.substr(0, i), i == std::string::npos ? 0ul : std::stoul(k.substr(i))); };
  return split(p) < split(q);
}

}  // namespace

int main(int argc, char** argv) {
  if (argc < 2) { std::printf("usage: test_context_parity corpus.jsonl [--selection=forced|salience|both] [--limit=N] [--bench=S] [--verbose=N]\n"); return 2; }
  std::string mode = "both";
  long limit = -1, verbose = 3;
  double bench_s = 0, min_rate = 0;
  for (int i = 2; i < argc; ++i) {
    const std::string a = argv[i];
    if (a.rfind("--selection=", 0) == 0) mode = a.substr(12);
    else if (a.rfind("--limit=", 0) == 0) limit = std::stol(a.substr(8));
    else if (a.rfind("--bench=", 0) == 0) bench_s = std::stod(a.substr(8));
    else if (a.rfind("--min-rate=", 0) == 0) min_rate = std::stod(a.substr(11));
    else if (a.rfind("--verbose=", 0) == 0) verbose = std::stol(a.substr(10));
  }
  Tokenizer tk;
  ContextBuilder cb(tk);
  testing::MindLoader loader(tk);
  ContextBuilder::Workspace ws;
  PropCache cache;
  std::ifstream in(argv[1]);
  if (!in) { std::printf("cannot open %s\n", argv[1]); return 2; }
  std::vector<std::string> modes;
  if (mode == "both") modes = {"forced", "salience"}; else modes = {mode};

  struct Case { Value ctx_value; std::string name, digest; double n; GameTime now; std::vector<std::string> ghosts; };
  std::vector<Case> cases;
  std::string line;
  while (std::getline(in, line)) {
    if (line.empty()) continue;
    if (limit >= 0 && long(cases.size()) >= limit) break;
    Value rec = parse_json(line);
    Case c;
    c.name = rec.find("name")->as_string();
    c.now = GameTime(rec.find("now")->as_number());
    const Value& ex = *rec.find("expect");
    if (ex.find("error")) { c.digest = "error"; c.n = 0; }
    else {
      c.digest = ex.find("digest")->as_string();
      c.n = ex.find("n")->as_number();
      for (const Value& g : ex.find("ghosts")->items()) c.ghosts.push_back(g.as_string());
    }
    c.ctx_value = *rec.find("context");
    cases.push_back(std::move(c));
  }
  std::printf("%zu situations from %s\n", cases.size(), argv[1]);

  int exit_code = 0;
  for (const std::string& m : modes) {
    const bool forced = m == "forced";
    Tally t;
    std::vector<std::string> sample;
    std::set<std::string> printed;
    std::vector<testing::LoadedMind> keep;
    for (const Case& c : cases) {
      ++t.cases;
      const auto t0 = std::chrono::steady_clock::now();
      const DecisionContext want = tk.load_context(c.ctx_value);
      testing::LoadedMind L;
      loader.load(want, c.now, !forced, L);
      const auto t1 = std::chrono::steady_clock::now();
      if (!L.lost.empty()) {
        ++t.lost_cases;
        for (const std::string& s : L.lost) ++t.lost[s.substr(0, s.find(':') == std::string::npos ? s.size() : s.find(':'))];
      }
      MindSource src{L.bundle.get(), L.now, L.wake, L.links};
      DecisionContext got;
      ws.stats = BuildStats{};
      if (forced) { ws.selection = L.selection; cb.assemble(src, ws, got); }
      else cb.build(src, ws, got);
      const auto t2 = std::chrono::steady_clock::now();
      t.clamped += ws.stats.clamped; t.dropped += ws.stats.dropped_pointers; t.skipped += ws.stats.skipped;
      Encoded enc;
      std::string why;
      const bool ok = tk.try_encode(got, enc, &why, &cache);
      const auto t3 = std::chrono::steady_clock::now();
      t.load_s += std::chrono::duration<double>(t1 - t0).count();
      t.build_s += std::chrono::duration<double>(t2 - t1).count();
      t.encode_s += std::chrono::duration<double>(t3 - t2).count();
      char hex[16];
      std::snprintf(hex, sizeof hex, "%08x", ok ? enc.digest() : 0u);
      bool match = ok && c.digest == hex && double(enc.n) == c.n && enc.ghosts == c.ghosts;
      if (!ok) { ++t.refused; if (long(sample.size()) < verbose * 8) sample.push_back(c.name + ": REFUSED " + why); }
      if (match) { ++t.ok; ++t.same_set; ++t.same_order; ++t.canon_ok; continue; }
      std::vector<std::string> local;
      if (forced) {
        ++t.bad;
        diff_contexts(want, got, tk, t, &local);
        if (long(sample.size()) < verbose * 8) for (std::size_t i = 0; i < local.size() && i < 3; ++i) sample.push_back(c.name + ": " + local[i]);
        continue;
      }
      // the salience chooses (and orders) the dossier itself: compare the SETS of records, then the content up to the order
      std::set<std::string> a, b;
      for (const Record& r : want.records) a.insert(r.key);
      for (const Record& r : got.records) b.insert(r.key);
      std::set<std::string> kinds_differing;
      for (const std::string& k : a) if (!b.count(k)) { ++t.omitted[k.substr(0, k.find_first_of("0123456789"))]; kinds_differing.insert(k.substr(0, 2)); }
      for (const std::string& k : b) if (!a.count(k)) { ++t.added[k.substr(0, k.find_first_of("0123456789"))]; kinds_differing.insert(k.substr(0, 2)); }
      if (a != b) { ++t.diff_set; continue; }
      ++t.same_set;
      // per type, is the sequence the same?
      bool same_order = true;
      {
        const auto by_type = [](DecisionContext x) {
          std::stable_sort(x.records.begin(), x.records.end(), [](const Record& p, const Record& q) { return p.type_index < q.type_index; });
          return x;
        };
        const DecisionContext w2 = by_type(want), g2 = by_type(got);
        for (std::size_t i = 0; i < w2.records.size() && i < g2.records.size(); ++i) same_order = same_order && w2.records[i].key == g2.records[i].key;
      }
      // canonical order: by type, then by key number
      const auto canon = [&](DecisionContext x) {
        std::stable_sort(x.records.begin(), x.records.end(), [](const Record& p, const Record& q) {
          if (p.type_index != q.type_index) return p.type_index < q.type_index;
          return key_less(p.key, q.key);
        });
        Encoded e;
        std::string w;
        return tk.try_encode(x, e, &w) ? e.digest() : 0u;
      };
      if (same_order) ++t.same_order;
      if (canon(want) == canon(got)) { ++t.canon_ok; }
      else {
        ++t.bad;
        diff_contexts(want, got, tk, t, &local);
        if (long(sample.size()) < verbose * 8) for (std::size_t i = 0; i < local.size() && i < 3; ++i) sample.push_back(c.name + ": " + local[i]);
      }
    }
    std::printf("\n== selection %s ==\n", m.c_str());
    if (forced) {
      std::printf("%ld situations: %ld identical to the oracle (digest, tokens, ghosts), %ld differ, %ld refused by the tokenizer\n",
                  t.cases, t.ok, t.bad, t.refused);
    } else {
      std::printf("%ld situations, %ld refused by the tokenizer\n", t.cases, t.refused);
      std::printf("  same set of records as the oracle's dossier: %ld (%.1f %%); different set (a difference of CHOICE): %ld\n", t.same_set,
                  100.0 * double(t.same_set) / double(t.cases), t.diff_set);
      std::printf("  of the same-set situations: same order, identical to the oracle (digest): %ld; same tokens up to the order of the records: %ld; "
                  "content differs: %ld\n", t.same_order, t.canon_ok, t.bad);
      for (const auto& [k, v] : t.omitted) std::printf("  carried by the oracle, not chosen by the salience: %-4s %ld records\n", k.c_str(), v);
      for (const auto& [k, v] : t.added) std::printf("  chosen by the salience, not carried by the oracle: %-4s %ld records\n", k.c_str(), v);
    }
    std::printf("builder counters: %ld values clamped, %ld pointers dropped (kind not accepted), %ld candidates skipped (no proposition)\n",
                t.clamped, t.dropped, t.skipped);
    if (t.clamped || t.dropped || t.skipped) exit_code = 1;
    std::printf("state could not hold something in %ld situations\n", t.lost_cases);
    for (const auto& [k, v] : t.lost) std::printf("  lost %-40s %ld\n", k.c_str(), v);
    std::vector<std::pair<long, std::string>> fd;
    for (const auto& [k, v] : t.field_diffs) fd.emplace_back(v, k);
    std::sort(fd.rbegin(), fd.rend());
    for (std::size_t i = 0; i < fd.size() && i < 25; ++i) std::printf("  field %-50s %ld\n", fd[i].second.c_str(), fd[i].first);
    for (const std::string& s : sample) std::printf("  e.g. %s\n", s.c_str());
    std::printf("time per situation: load (test) %.0f us, build %.0f us, encode %.0f us\n", 1e6 * t.load_s / double(t.cases),
                1e6 * t.build_s / double(t.cases), 1e6 * t.encode_s / double(t.cases));
    if (t.bad || t.refused) exit_code = 1;
  }

  // determinism: the same state gives the same context bit for bit, with a fresh workspace and in another order
  {
    long diff = 0;
    ContextBuilder::Workspace w2;
    std::vector<std::unique_ptr<testing::LoadedMind>> loaded;
    for (std::size_t i = 0; i < cases.size() && i < 300; ++i) {
      auto L = std::make_unique<testing::LoadedMind>();
      loader.load(tk.load_context(cases[i].ctx_value), cases[i].now, true, *L);
      loaded.push_back(std::move(L));
    }
    std::vector<std::uint32_t> first;
    for (auto& L : loaded) {
      MindSource src{L->bundle.get(), L->now, L->wake, L->links};
      DecisionContext c1;
      Encoded e;
      cb.build(src, ws, c1);
      tk.try_encode(c1, e, nullptr, &cache);
      first.push_back(e.digest());
    }
    for (std::size_t k = loaded.size(); k-- > 0;) {
      MindSource src{loaded[k]->bundle.get(), loaded[k]->now, loaded[k]->wake, loaded[k]->links};
      DecisionContext c2;
      Encoded e;
      cb.build(src, w2, c2);
      tk.try_encode(c2, e);       // without the memo
      diff += e.digest() != first[k];
    }
    std::printf("\ndeterminism (300 states, two builders, reverse order, with and without the proposition memo): %ld differences\n", diff);
    if (diff) exit_code = 1;

    if (bench_s > 0) {
      DecisionContext ctx;
      Encoded enc;
      long n = 0;
      double build = 0, total = 0;
      const auto t0 = std::chrono::steady_clock::now();
      while (std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count() < bench_s) {
        for (auto& L : loaded) {
          MindSource src{L->bundle.get(), L->now, L->wake, L->links};
          const auto a = std::chrono::steady_clock::now();
          cb.build(src, ws, ctx);
          const auto b = std::chrono::steady_clock::now();
          tk.try_encode(ctx, enc, nullptr, &cache);
          const auto c = std::chrono::steady_clock::now();
          build += std::chrono::duration<double>(b - a).count();
          total += std::chrono::duration<double>(c - a).count();
          ++n;
        }
      }
      std::printf("throughput, 1 thread, %zu distinct states: build %.0f us, build + tokenize %.0f us => %.0f contexts/s (build alone %.0f/s)\n",
                  loaded.size(), 1e6 * build / double(n), 1e6 * total / double(n), double(n) / total, double(n) / build);
      if (min_rate > 0 && double(n) / total < min_rate) { std::printf("FAIL: below %.0f contexts/s\n", min_rate); exit_code = 1; }
    }
  }
  return exit_code;
}
