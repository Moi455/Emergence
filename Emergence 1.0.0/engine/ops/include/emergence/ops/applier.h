// Applier: a subscriber of the OperationBus. The bus calls every applier, in registration order,
// for every operation, in the total order of the bus. T17 plugs VoxelOpApplier here (loaded chunk:
// Applied now; unloaded region: Deferred into the RegionDeltaStore). An Applier must not read
// clocks or random sources, and must not touch another applier's state: that is the only way the
// world changes (invariant I4).
#pragma once
#include <cstdint>
#include <string_view>

#include "emergence/ops/operation.h"

namespace em::ops {

enum class ApplyStatus : std::uint8_t {
  Applied,    // took effect now
  Deferred,   // kept for later (e.g. region not loaded); will take effect at load
  Ignored,    // not concerned by this operation
  Rejected,   // concerned but refused (counted by the bus; the operation stays in the journal)
};

class Applier {
 public:
  virtual ~Applier() = default;
  virtual std::string_view name() const = 0;
  virtual ApplyStatus apply(const Operation& op) = 0;
  // Optional state digest for replay checks; 0 when the applier keeps no state to compare.
  virtual std::uint64_t fingerprint() const { return 0; }
  // Highest op_id this applier already holds (a reopened journal); the bus continues after it.
  virtual std::uint64_t last_op_id() const { return 0; }
  // Called by the bus once per flush(), after the last operation of the batch (durability point).
  virtual void end_of_flush() {}
};

}  // namespace em::ops
