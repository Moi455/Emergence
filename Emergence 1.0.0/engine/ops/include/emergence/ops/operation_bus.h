// OperationBus: ordered queue of operations (docs/14 section 4.6). Producers (any thread) call
// submit(); the owner calls flush() once per step. flush() sorts the pending operations in the
// total order (tick, author, decision_seq, k, kind, payload), assigns op_id and seq, then hands
// each one to every registered Applier in registration order. Result: the same set of submissions
// gives the same operation stream whatever the number of threads or their interleaving.
#pragma once
#include <cstddef>
#include <cstdint>
#include <mutex>
#include <vector>

#include "emergence/ops/applier.h"
#include "emergence/ops/operation.h"

namespace em::ops {

enum class SubmitResult : std::uint8_t {
  Accepted,
  RejectedUnknownKind,      // kind 0 or not in this build's registry
  RejectedBadVersion,
  RejectedPayloadTooLarge,
  RejectedStaleTick,        // tick already flushed: the order would no longer be total
};

struct BusStats {
  std::uint64_t submitted = 0, rejected_at_submit = 0, flushed = 0;
  std::uint64_t applied = 0, deferred = 0, ignored = 0, rejected_by_applier = 0;
};

class OperationBus {
 public:
  // Appliers are not owned and must outlive the bus. Fixed order = registration order.
  void add_applier(Applier* applier);

  // Thread-safe. decision_seq and k are the producer's own counters (per author); op_id and seq
  // of the argument are ignored and overwritten at flush.
  SubmitResult submit(Operation op, std::uint32_t decision_seq = 0, std::uint32_t k = 0);

  // Applies, in order, every pending operation whose tick <= up_to_tick. Single caller at a time.
  // Returns the number of operations flushed.
  std::size_t flush(std::uint64_t up_to_tick = UINT64_MAX);

  std::size_t pending() const;
  std::uint64_t next_op_id() const { return next_op_id_; }
  // Normally automatic: flush() continues after the highest Applier::last_op_id() (reopened journal).
  // Explicit override, e.g. after a replay into appliers that keep no journal.
  void set_next_op_id(std::uint64_t id) { next_op_id_ = id; }
  BusStats stats() const;

 private:
  struct Entry {
    OrderKey key;
    Operation op;
  };
  mutable std::mutex mutex_;
  std::vector<Entry> pending_;
  std::vector<Applier*> appliers_;
  std::uint64_t next_op_id_ = 1;
  bool has_flushed_ = false;
  std::uint64_t flushed_through_ = 0;
  BusStats stats_;
};

}  // namespace em::ops
