// Throughput of the tokenizer in decisions per second (one thread), from records already in memory (the game path) and
// from JSON text (the training path), plus determinism (two passes, same digests; two threads, same digests).
// usage: bench_tok2 corpus.jsonl [n]
#include <chrono>
#include <cstdio>
#include <fstream>
#include <thread>
#include <vector>

#include "emergence/social/tokenizer/tokenizer.h"

using namespace em::social::tok2;
using Clock = std::chrono::steady_clock;

int main(int argc, char** argv) {
  if (argc < 2) return 2;
  const std::size_t want = argc > 2 ? std::size_t(std::atoi(argv[2])) : 2000;
  Tokenizer tk;
  std::vector<std::string> texts;
  std::vector<DecisionContext> ctxs;
  std::ifstream in(argv[1]);
  std::string line;
  while (texts.size() < want && std::getline(in, line)) {
    if (line.find("\"name\":\"sit_") == std::string::npos) continue;
    const Value rec = parse_json(line);
    const Value& c = *rec.find("context");
    // re-read through the text path: the record text is the context object itself
    std::size_t at = line.find("\"context\":") + 10, end = line.rfind(",\"expect\"");
    texts.push_back(line.substr(at, end - at));
    ctxs.push_back(tk.load_context(c));
  }
  const int reps = 5;
  Encoded enc;
  std::vector<std::uint32_t> d1(ctxs.size()), d2(ctxs.size());
  auto t0 = Clock::now();
  for (int r = 0; r < reps; ++r)
    for (std::size_t i = 0; i < ctxs.size(); ++i) tk.encode(ctxs[i], enc);
  for (std::size_t i = 0; i < ctxs.size(); ++i) { tk.encode(ctxs[i], enc); d1[i] = enc.digest(); }
  double s = std::chrono::duration<double>(Clock::now() - t0).count();
  const double per = s / (reps * ctxs.size());
  std::printf("encode from records, cold (parser every time): %zu situations x %d: %.1f us/decision = %.0f decisions/s (1 thread)\n",
              ctxs.size(), reps, per * 1e6, 1.0 / per);
  t0 = Clock::now();
  for (std::size_t i = 0; i < ctxs.size(); ++i) { tk.encode(ctxs[i], enc); d2[i] = enc.digest(); }
  s = std::chrono::duration<double>(Clock::now() - t0).count();
  std::printf("encode + crc32 digest: %.1f us/decision\n", s / ctxs.size() * 1e6);
  {   // steady state: the same NPC decides again, its propositions are already validated (one cache per thread)
    PropCache cache;
    for (std::size_t i = 0; i < ctxs.size(); ++i) tk.encode(ctxs[i], enc, &cache);   // warm-up pass
    t0 = Clock::now();
    bool eq = true;
    for (int r = 0; r < reps; ++r)
      for (std::size_t i = 0; i < ctxs.size(); ++i) { tk.encode(ctxs[i], enc, &cache); if (r == 0) eq = eq && enc.digest() == d1[i]; }
    s = std::chrono::duration<double>(Clock::now() - t0).count();
    std::printf("encode, validated propositions cached: %.1f us/decision = %.0f decisions/s (digests %s)\n",
                s / (reps * ctxs.size()) * 1e6, reps * ctxs.size() / s, eq ? "equal" : "DIFFERENT");
  }
  t0 = Clock::now();
  for (std::size_t i = 0; i < texts.size(); ++i) { tk.encode(tk.load_context(texts[i]), enc); }
  s = std::chrono::duration<double>(Clock::now() - t0).count();
  std::printf("JSON text -> arrays: %.1f us/decision = %.0f decisions/s\n", s / texts.size() * 1e6, texts.size() / s);
  bool same = d1 == d2;
  std::vector<std::uint32_t> da(ctxs.size()), db(ctxs.size());
  auto work = [&](std::vector<std::uint32_t>& out) {
    Encoded e;
    for (std::size_t i = 0; i < ctxs.size(); ++i) { tk.encode(ctxs[i], e); out[i] = e.digest(); }
  };
  std::thread ta(work, std::ref(da)), tb(work, std::ref(db));
  ta.join(); tb.join();
  same = same && da == d1 && db == d1;
  std::printf("determinism (two passes, two threads): %s\n", same ? "identical" : "DIFFERENT");
  return same ? 0 : 1;
}
