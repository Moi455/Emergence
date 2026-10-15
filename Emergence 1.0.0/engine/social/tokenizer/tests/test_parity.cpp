// tok-2 parity: the C++ tokenizer against the Python oracle on JSONL files {name, context, expect}.
//   expect = {digest (crc32 hex), n, ghosts[]}  or  {error: "TokenError"}
// usage: test_tok2_parity file.jsonl [file2.jsonl ...]   (the golden cases of ai/tok2 and the shared corpus)
#include <chrono>
#include <cstdio>
#include <fstream>
#include <string>
#include <vector>

#include "emergence/social/tokenizer/tokenizer.h"

using namespace em::social::tok2;

int main(int argc, char** argv) {
  Tokenizer tk;
  std::printf("layout %016llx interface %016llx\n", (unsigned long long)tk.layout_fingerprint(), (unsigned long long)tk.interface_fingerprint());
  long total = 0, bad = 0, refused = 0;
  auto t0 = std::chrono::steady_clock::now();
  for (int a = 1; a < argc; ++a) {
    std::ifstream in(argv[a]);
    if (!in) { std::printf("cannot open %s\n", argv[a]); return 2; }
    std::string line;
    Encoded enc;
    while (std::getline(in, line)) {
      if (line.empty()) continue;
      ++total;
      const Value rec = parse_json(line);
      const std::string name = rec.find("name")->as_string();
      const Value& expect = *rec.find("expect");
      std::string got_err;
      bool ok = false;
      try {
        const DecisionContext ctx = tk.load_context(*rec.find("context"));
        ok = tk.try_encode(ctx, enc, &got_err);
      } catch (const TokenError& e) { got_err = e.what(); }
      bool fail = false;
      if (const Value* err = expect.find("error")) {
        (void)err;
        ++refused;
        if (ok) { std::printf("FAIL %s: oracle refuses, C++ encodes\n", name.c_str()); fail = true; }
      } else if (!ok) {
        std::printf("FAIL %s: oracle encodes, C++ refuses: %s\n", name.c_str(), got_err.c_str());
        fail = true;
      } else {
        char hex[16];
        std::snprintf(hex, sizeof hex, "%08x", enc.digest());
        if (expect.find("digest")->as_string() != hex || double(enc.n) != expect.find("n")->as_number()) {
          std::printf("FAIL %s: digest %s n %u, expected %s n %g\n", name.c_str(), hex, enc.n,
                      expect.find("digest")->as_string().c_str(), expect.find("n")->as_number());
          fail = true;
        }
        const auto& g = expect.find("ghosts")->items();
        if (g.size() != enc.ghosts.size()) fail = true;
        else for (std::size_t i = 0; i < g.size(); ++i) fail = fail || g[i].as_string() != enc.ghosts[i];
        if (fail && std::string(hex) == expect.find("digest")->as_string()) std::printf("FAIL %s: ghosts differ\n", name.c_str());
      }
      bad += fail;
    }
  }
  const double s = std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count();
  std::printf("%ld cases (%ld refusals), %ld mismatches, %.2f s\n", total, refused, bad, s);
  return bad == 0 && total > 0 ? 0 : 1;
}
