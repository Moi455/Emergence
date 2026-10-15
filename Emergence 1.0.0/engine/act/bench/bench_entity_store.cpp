// bench_entity_store [n]: n entities created, moved, changed and half destroyed through the bus; prints rates and bytes.
#include <chrono>
#include <cstdio>
#include <cstdlib>

#include "../tests/workload.h"

int main(int argc, char** argv) {
  const std::uint32_t n = argc > 1 ? std::uint32_t(std::atol(argv[1])) : 100000;
  em::act::EntityStore store;
  em::ops::OperationBus bus;
  bus.add_applier(&store);
  auto t0 = std::chrono::steady_clock::now();
  auto c = em::act::workload::run(bus, store, n);
  double s = std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count();
  std::printf("%u entities: %llu ops in %.3f s = %.2f M ops/s (%.2f M entities created/s); alive %zu; fingerprint %016llx\n", n,
              (unsigned long long)c.ops, s, double(c.ops) / s / 1e6, double(n) / s / 1e6, store.size(),
              (unsigned long long)store.fingerprint());
  for (std::size_t k = 0; k < std::size_t(em::act::gen::EntityKind::kCount); ++k)
    std::printf("  %-10s Data %4zu bytes\n", std::string(em::act::gen::kEntityKindNames[k]).c_str(), em::act::gen::kKindDataBytes[k]);
  return 0;
}
