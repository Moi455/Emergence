// Throughput of the executor of gestures: 500 NPC over one game day (5 400 ticks of 16 game seconds), 1 to 8 threads.
#include <chrono>
#include <cstdio>

#include "gesture_workload.h"

int main() {
  using namespace em::act;
  for (unsigned threads : {1u, 2u, 4u, 8u}) {
    const auto t0 = std::chrono::steady_clock::now();
    const gwork::Result r = gwork::run(threads, 500, 5400, 256);
    const double s = std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count();
    std::printf("threads %u: executor.step alone %.3f s (%.1f us/tick, %.0f cycles/s, %.0f gestures/s)\n", threads, r.step_seconds,
                1e6 * r.step_seconds / 5400, double(r.cycles) / r.step_seconds, double(r.gestures) / r.step_seconds);
    std::printf("threads %u: %.2f s for 5400 ticks (%.2f ms/tick), %llu gestures (%.0f/s), %llu cycles (%.0f/s), %llu operations, %llu contacts, digest %016llx\n",
                threads, s, 1000.0 * s / 5400, static_cast<unsigned long long>(r.gestures), double(r.gestures) / s,
                static_cast<unsigned long long>(r.cycles), double(r.cycles) / s, static_cast<unsigned long long>(r.emissions),
                static_cast<unsigned long long>(r.contacts), static_cast<unsigned long long>(r.chain));
  }
  return 0;
}
