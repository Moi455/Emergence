// Tiny dependency-free test harness: TEST(name) { CHECK(...); } and
// EMERGENCE_TEST_MAIN() at the end of the file.
#pragma once
#include <cstdio>
#include <functional>
#include <string>
#include <vector>

namespace em::testing {

struct Case {
  const char* name;
  std::function<void()> fn;
};

inline std::vector<Case>& registry() {
  static std::vector<Case> r;
  return r;
}
inline int& failures() {
  static int f = 0;
  return f;
}
struct Registrar {
  Registrar(const char* name, std::function<void()> fn) { registry().push_back({name, std::move(fn)}); }
};

inline int run_all(int argc, char** argv) {
  std::string filter = argc > 1 ? argv[1] : "";
  int ran = 0;
  for (auto& c : registry()) {
    if (!filter.empty() && std::string(c.name).find(filter) == std::string::npos) continue;
    int before = failures();
    c.fn();
    ++ran;
    std::printf("%s %s\n", failures() == before ? "[ OK ]" : "[FAIL]", c.name);
  }
  std::printf("%d tests, %d failed checks\n", ran, failures());
  return failures() == 0 ? 0 : 1;
}

}  // namespace em::testing

#define EM_CAT2(a, b) a##b
#define EM_CAT(a, b) EM_CAT2(a, b)
#define TEST(name)                                                              \
  static void EM_CAT(test_fn_, name)();                                         \
  static ::em::testing::Registrar EM_CAT(test_reg_, name)(#name, EM_CAT(test_fn_, name)); \
  static void EM_CAT(test_fn_, name)()

#define CHECK(cond)                                                             \
  do {                                                                          \
    if (!(cond)) {                                                              \
      ++::em::testing::failures();                                              \
      std::printf("  %s:%d: CHECK(%s) failed\n", __FILE__, __LINE__, #cond);    \
    }                                                                           \
  } while (0)

#define CHECK_EQ(a, b)                                                          \
  do {                                                                          \
    auto va_ = (a);                                                             \
    auto vb_ = (b);                                                             \
    if (!(va_ == vb_)) {                                                        \
      ++::em::testing::failures();                                              \
      std::printf("  %s:%d: CHECK_EQ(%s, %s) failed: %lld vs %lld\n", __FILE__, __LINE__, #a, #b, \
                  static_cast<long long>(va_), static_cast<long long>(vb_));    \
    }                                                                           \
  } while (0)

#define EMERGENCE_TEST_MAIN() \
  int main(int argc, char** argv) { return ::em::testing::run_all(argc, argv); }
