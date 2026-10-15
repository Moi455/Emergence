// Throughput of submit + flush (sort, ids, journal with CRC) in operations per second.
#include <chrono>
#include <cstdio>
#include <filesystem>
#include <string>
#include <thread>
#include <vector>

#include "emergence/ops/op_journal.h"
#include "emergence/ops/operation_bus.h"

using namespace em::ops;

int main(int argc, char** argv) {
  const std::uint32_t total = argc > 1 ? static_cast<std::uint32_t>(std::stoul(argv[1])) : 1000000;
  const std::uint32_t authors = 500, per_tick = 20000;
  const auto path = std::filesystem::temp_directory_path() / "em_bench_ops.oplg";
  std::filesystem::remove(path);
  OperationBus bus;
  OpJournal journal;
  journal.open(path);
  bus.add_applier(&journal);
  using clock = std::chrono::steady_clock;
  double t_submit = 0, t_flush = 0;
  std::uint64_t tick = 0;
  for (std::uint32_t done = 0; done < total; done += per_tick) {
    ++tick;
    auto t0 = clock::now();
    for (std::uint32_t i = 0; i < per_tick; ++i) {
      Operation op;
      op.tick = tick;
      op.author = (i * 2654435761u) % authors;   // scrambled arrival order
      op.kind = static_cast<std::uint16_t>(1 + i % kMaxKnownKind);
      PayloadWriter w;
      w.u32(i).i32(-static_cast<std::int32_t>(i)).u64(tick);   // 16-byte payload
      op.payload = w.take();
      bus.submit(std::move(op), i, 0);
    }
    auto t1 = clock::now();
    bus.flush();
    auto t2 = clock::now();
    t_submit += std::chrono::duration<double>(t1 - t0).count();
    t_flush += std::chrono::duration<double>(t2 - t1).count();
  }
  journal.close();
  const std::uint64_t n = bus.stats().flushed;
  std::printf("ops=%llu submit=%.3fs (%.0f ops/s) flush+journal=%.3fs (%.0f ops/s) total=%.0f ops/s file=%.1f MiB\n",
              static_cast<unsigned long long>(n), t_submit, n / t_submit, t_flush, n / t_flush,
              n / (t_submit + t_flush), std::filesystem::file_size(path) / 1048576.0);
  std::filesystem::remove(path);
}
