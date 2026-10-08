// Splits [begin, end) across worker threads. Each index must be independent
// (pure function of its inputs), so the result never depends on scheduling.
#pragma once
#include <cstdint>
#include <functional>

namespace em {

// Number of threads used by parallel_for (default: hardware concurrency).
void set_worker_count(int n);
int worker_count();

void parallel_for(int64_t begin, int64_t end, const std::function<void(int64_t, int64_t)>& body);

// Same contract, one index at a time handed to whichever thread is free:
// for items of very uneven cost (chunks).
void parallel_each(int64_t begin, int64_t end, const std::function<void(int64_t)>& body);

}  // namespace em
