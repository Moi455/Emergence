#include "emergence/base/parallel.h"

#include <algorithm>
#include <thread>
#include <vector>

namespace em {

namespace {
int g_workers = 0;
}

void set_worker_count(int n) { g_workers = n; }

int worker_count() {
  if (g_workers > 0) return g_workers;
  unsigned hc = std::thread::hardware_concurrency();
  return hc == 0 ? 1 : static_cast<int>(hc);
}

void parallel_for(int64_t begin, int64_t end, const std::function<void(int64_t, int64_t)>& body) {
  int64_t n = end - begin;
  if (n <= 0) return;
  int64_t threads = std::min<int64_t>(worker_count(), n);
  if (threads <= 1) {
    body(begin, end);
    return;
  }
  std::vector<std::thread> pool;
  pool.reserve(static_cast<size_t>(threads - 1));
  int64_t step = (n + threads - 1) / threads;
  for (int64_t t = 1; t < threads; ++t) {
    int64_t b = begin + t * step, e = std::min(end, b + step);
    if (b < e) pool.emplace_back([&body, b, e] { body(b, e); });
  }
  body(begin, std::min(end, begin + step));
  for (auto& th : pool) th.join();
}

}  // namespace em
