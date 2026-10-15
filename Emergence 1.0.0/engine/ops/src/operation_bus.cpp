#include "emergence/ops/operation_bus.h"

#include <algorithm>
#include <tuple>
#include <utility>

namespace em::ops {

void OperationBus::add_applier(Applier* applier) {
  std::lock_guard<std::mutex> lock(mutex_);
  appliers_.push_back(applier);
}

SubmitResult OperationBus::submit(Operation op, std::uint32_t decision_seq, std::uint32_t k) {
  std::lock_guard<std::mutex> lock(mutex_);
  ++stats_.submitted;
  SubmitResult r = SubmitResult::Accepted;
  if (op.version == 0 || op.version > kCurrentVersion) r = SubmitResult::RejectedBadVersion;
  else if (op.kind == 0 || op.kind > kMaxKnownKind) r = SubmitResult::RejectedUnknownKind;
  else if (op.payload.size() > kMaxPayloadBytes) r = SubmitResult::RejectedPayloadTooLarge;
  else if (has_flushed_ && op.tick <= flushed_through_) r = SubmitResult::RejectedStaleTick;
  if (r != SubmitResult::Accepted) {
    ++stats_.rejected_at_submit;
    return r;
  }
  op.version = kCurrentVersion;
  pending_.push_back({{op.tick, op.author, decision_seq, k}, std::move(op)});
  return r;
}

std::size_t OperationBus::flush(std::uint64_t up_to_tick) {
  std::vector<Entry> batch;
  std::vector<Applier*> appliers;
  {
    std::lock_guard<std::mutex> lock(mutex_);
    auto mid = std::partition(pending_.begin(), pending_.end(),
                              [&](const Entry& e) { return e.key.tick <= up_to_tick; });
    batch.assign(std::make_move_iterator(pending_.begin()), std::make_move_iterator(mid));
    pending_.erase(pending_.begin(), mid);
    appliers = appliers_;
    if (up_to_tick != UINT64_MAX || !batch.empty()) {
      // Ticks up to the largest one flushed are closed; later submissions for them are refused.
      std::uint64_t closed = up_to_tick;
      if (up_to_tick == UINT64_MAX) {
        closed = 0;
        for (const Entry& e : batch) closed = std::max(closed, e.key.tick);
      }
      flushed_through_ = has_flushed_ ? std::max(flushed_through_, closed) : closed;
      has_flushed_ = true;
    }
  }
  // Total order: the key, then every remaining header field, then the payload bytes. Two operations
  // that compare equal are byte-identical (op_id and seq are assigned below), so their relative
  // order cannot be observed; stable_sort is only the last resort.
  std::stable_sort(batch.begin(), batch.end(), [](const Entry& a, const Entry& b) {
    if (key_less(a.key, b.key)) return true;
    if (key_less(b.key, a.key)) return false;
    const Operation& x = a.op;
    const Operation& y = b.op;
    return std::tie(x.kind, x.process, x.gesture, x.flags, x.noise, x.sight, x.trace, x.reserved,
                    x.cause, x.payload) <
           std::tie(y.kind, y.process, y.gesture, y.flags, y.noise, y.sight, y.trace, y.reserved,
                    y.cause, y.payload);
  });
  for (Applier* a : appliers) next_op_id_ = std::max(next_op_id_, a->last_op_id() + 1);
  BusStats local;
  std::uint64_t tick = 0;
  std::uint32_t seq = 0;
  bool first = true;
  for (Entry& e : batch) {
    if (first || e.op.tick != tick) {
      tick = e.op.tick;
      seq = 0;
      first = false;
    }
    e.op.seq = seq++;
    e.op.op_id = next_op_id_++;
    ++local.flushed;
    for (Applier* a : appliers) {
      switch (a->apply(e.op)) {
        case ApplyStatus::Applied: ++local.applied; break;
        case ApplyStatus::Deferred: ++local.deferred; break;
        case ApplyStatus::Ignored: ++local.ignored; break;
        case ApplyStatus::Rejected: ++local.rejected_by_applier; break;
      }
    }
  }
  for (Applier* a : appliers) a->end_of_flush();
  std::lock_guard<std::mutex> lock(mutex_);
  stats_.flushed += local.flushed;
  stats_.applied += local.applied;
  stats_.deferred += local.deferred;
  stats_.ignored += local.ignored;
  stats_.rejected_by_applier += local.rejected_by_applier;
  return batch.size();
}

std::size_t OperationBus::pending() const {
  std::lock_guard<std::mutex> lock(mutex_);
  return pending_.size();
}

BusStats OperationBus::stats() const {
  std::lock_guard<std::mutex> lock(mutex_);
  return stats_;
}

}  // namespace em::ops
