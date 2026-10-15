#include <algorithm>
#include <cstdio>
#include <filesystem>
#include <thread>
#include <random>
#if defined(__unix__)
#include <sys/wait.h>
#include <unistd.h>
#endif
#include <vector>

#include "emergence/ops/digest.h"
#include "emergence/ops/op_journal.h"
#include "emergence/ops/operation_bus.h"
#include "emergence/testing/check.h"

#define CHECK_N(a, b) CHECK_EQ(static_cast<long long>(a), static_cast<long long>(b))

using namespace em::ops;
namespace fs = std::filesystem;

namespace {

fs::path temp_path(const char* name) {
  fs::path p = fs::temp_directory_path() / (std::string("em_test_ops_") + name + ".oplg");
  fs::remove(p);
  return p;
}

// Deterministic op from (author, n): no rand().
Operation make_op(std::uint32_t author, std::uint32_t n, std::uint64_t tick) {
  Operation op;
  op.tick = tick;
  op.author = author;
  op.kind = static_cast<std::uint16_t>(1 + (author + n) % kMaxKnownKind);
  op.cause = (std::uint64_t{author} << 20) | n;
  op.flags = kFlagEntities;
  op.noise = static_cast<std::uint8_t>(n % 11);
  PayloadWriter w;
  w.u32(author).u32(n).i32(-static_cast<std::int32_t>(n)).u64(tick * 7919 + n);
  op.payload = w.take();
  return op;
}

// Records applied operations and keeps a running digest.
class Recorder final : public Applier {
 public:
  std::string_view name() const override { return "Recorder"; }
  ApplyStatus apply(const Operation& op) override {
    seen.push_back(op);
    digest.add(encode(op));
    return ApplyStatus::Applied;
  }
  std::uint64_t fingerprint() const override { return digest.value(); }
  std::vector<Operation> seen;
  em::ops::Fnv64 digest;
};

// Submits the same 4000 operations, from `threads` threads, and returns the journal file fingerprint.
std::uint64_t run_workload(int threads, const fs::path& path, std::vector<Operation>* seen = nullptr) {
  OperationBus bus;
  OpJournal journal;
  Recorder rec;
  CHECK(journal.open(path) == JournalStatus::Ok);
  bus.add_applier(&rec);
  bus.add_applier(&journal);
  const std::uint32_t authors = 40, per_author = 100;
  std::vector<std::thread> pool;
  for (int t = 0; t < threads; ++t)
    pool.emplace_back([&, t] {
      for (std::uint32_t a = 1 + t; a <= authors; a += threads)
        for (std::uint32_t n = 0; n < per_author; ++n)
          CHECK(bus.submit(make_op(a, n, 1 + n / 20), n, 0) == SubmitResult::Accepted);
    });
  for (auto& th : pool) th.join();
  CHECK_N(bus.flush(), authors * per_author);
  journal.close();
  if (seen) *seen = rec.seen;
  return OpJournal::scan(path).fingerprint;
}

}  // namespace

TEST(codec_roundtrip_and_layout) {
  Operation op = make_op(7, 3, 99);
  op.op_id = 12345;
  op.seq = 9;
  op.process = 5;
  op.gesture = 6;
  auto bytes = encode(op);
  CHECK_N(bytes.size(), kHeaderBytes + op.payload.size());
  CHECK_N(bytes[0], 12345 & 0xFF);   // little-endian op_id first
  CHECK_N(bytes[39], kCurrentVersion);
  Operation back;
  std::size_t used = 0;
  CHECK(decode(bytes, back, used) == DecodeStatus::Ok);
  CHECK_N(used, bytes.size());
  CHECK(back == op);
  // Every strict prefix is Truncated, never a crash or a wrong success.
  for (std::size_t n = 0; n < bytes.size(); ++n)
    CHECK(decode(std::span<const std::uint8_t>(bytes.data(), n), back, used) == DecodeStatus::Truncated);
  PayloadReader r(op.payload);
  std::uint32_t a, b; std::int32_t c; std::uint64_t d;
  CHECK(r.u32(a) && r.u32(b) && r.i32(c) && r.u64(d));
  CHECK_N(a, 7); CHECK_N(b, 3); CHECK_N(c, -3); CHECK_N(r.remaining(), 0);
  CHECK(!r.u8(reinterpret_cast<std::uint8_t&>(a)));
}

TEST(future_version_and_kind_refused) {
  Operation op = make_op(1, 1, 1);
  auto bytes = encode(op);
  Operation out;
  std::size_t used = 0;
  auto v = bytes; v[39] = kCurrentVersion + 1;
  CHECK(decode(v, out, used) == DecodeStatus::UnsupportedVersion);
  v[39] = 0;
  CHECK(decode(v, out, used) == DecodeStatus::UnsupportedVersion);
  auto k = bytes; k[32] = static_cast<std::uint8_t>(kMaxKnownKind + 1);
  CHECK(decode(k, out, used) == DecodeStatus::UnknownKind);
  OperationBus bus;
  Operation future = op; future.kind = kMaxKnownKind + 1;
  CHECK(bus.submit(future) == SubmitResult::RejectedUnknownKind);
  future = op; future.version = 2;
  CHECK(bus.submit(future) == SubmitResult::RejectedBadVersion);
  CHECK_N(bus.pending(), 0);
}

TEST(bus_total_order_and_ids) {
  OperationBus bus;
  Recorder rec;
  bus.add_applier(&rec);
  // Submitted in a scrambled order; expected order is (tick, author, decision_seq, k).
  bus.submit(make_op(9, 0, 2), 0, 0);
  bus.submit(make_op(3, 0, 2), 1, 0);
  bus.submit(make_op(3, 1, 2), 0, 1);
  bus.submit(make_op(3, 2, 2), 0, 0);
  bus.submit(make_op(5, 0, 1), 0, 0);
  CHECK_N(bus.flush(1), 1);   // only tick 1
  CHECK_N(bus.flush(), 4);
  CHECK_N(rec.seen.size(), 5);
  CHECK_N(rec.seen[0].author, 5);
  CHECK_N(rec.seen[1].author, 3); CHECK_N(rec.seen[1].payload[4], 2);   // (3, ds0, k0)
  CHECK_N(rec.seen[2].payload[4], 1);                                    // (3, ds0, k1)
  CHECK_N(rec.seen[3].payload[4], 0); CHECK_N(rec.seen[3].author, 3);   // (3, ds1, k0)
  CHECK_N(rec.seen[4].author, 9);
  for (std::size_t i = 0; i < 5; ++i) CHECK_N(rec.seen[i].op_id, i + 1);
  CHECK_N(rec.seen[0].seq, 0); CHECK_N(rec.seen[1].seq, 0); CHECK_N(rec.seen[4].seq, 3);
  // A closed tick refuses new operations.
  CHECK(bus.submit(make_op(1, 0, 2)) == SubmitResult::RejectedStaleTick);
  CHECK(bus.submit(make_op(1, 0, 3)) == SubmitResult::Accepted);
}

TEST(eight_threads_same_journal_as_one) {
  std::vector<Operation> s1, s8;
  const auto p1 = temp_path("t1"), p8 = temp_path("t8");
  const std::uint64_t f1 = run_workload(1, p1, &s1);
  const std::uint64_t f8 = run_workload(8, p8, &s8);
  CHECK_N(s1.size(), 4000);
  CHECK(f1 == f8);
  CHECK(s1 == s8);
  CHECK(run_workload(3, temp_path("t3")) == f1);
  std::printf("  journal fingerprint %016llx\n", static_cast<unsigned long long>(f1));
}

TEST(replay_gives_identical_fingerprint) {
  const auto p = temp_path("replay");
  std::vector<Operation> live;
  const std::uint64_t f = run_workload(4, p, &live);
  Recorder rec;
  JournalScan s = OpJournal::replay(p, rec);
  CHECK(s.status == JournalStatus::Ok);
  CHECK_N(s.ops, 4000);
  CHECK_N(s.blocks, 1);   // 4000 < 4096: one partial block written at close
  CHECK(rec.seen == live);
  CHECK(s.fingerprint == f);
  Recorder live_rec;
  for (const auto& op : live) live_rec.apply(op);
  CHECK(live_rec.fingerprint() == rec.fingerprint());
}

TEST(multi_block_journal) {
  const auto p = temp_path("multi");
  OperationBus bus;
  OpJournal j;
  CHECK(j.open(p) == JournalStatus::Ok);
  bus.add_applier(&j);
  for (std::uint32_t n = 0; n < 10000; ++n) bus.submit(make_op(1, n, 1 + n / 100), n, 0);
  bus.flush();
  j.close();
  JournalScan s = OpJournal::scan(p);
  CHECK(s.status == JournalStatus::Ok);
  CHECK_N(s.ops, 10000);
  CHECK_N(s.blocks, 3);   // 4096 + 4096 + 1808
  CHECK_N(s.last_op_id, 10000);
}

TEST(truncated_by_crash_then_resumed) {
  const auto p = temp_path("crash");
  {
    OperationBus bus;
    OpJournal j;
    CHECK(j.open(p) == JournalStatus::Ok);
    bus.add_applier(&j);
    for (std::uint32_t n = 0; n < 5000; ++n) bus.submit(make_op(1, n, 1), n, 0);
    bus.flush();
    j.close();   // blocks: 4096 + 904
  }
  const auto full = fs::file_size(p);
  const JournalScan whole = OpJournal::scan(p);
  CHECK_N(whole.ops, 5000);
  // Simulate a crash in the middle of the second block: cut the file at several places.
  const auto q = temp_path("crash_cut");
  for (std::uint64_t cut : {full - 1, full - 100, whole.good_bytes - 1}) {
    fs::copy_file(p, q, fs::copy_options::overwrite_existing);
    fs::resize_file(q, cut);
    JournalScan s = OpJournal::scan(q);
    CHECK(s.status == JournalStatus::TruncatedTail);
    CHECK_N(s.ops, 4096);
    CHECK_N(s.last_op_id, 4096);
  }
  // Resume: open cuts the torn block, then the bus continues after the last durable op_id.
  fs::copy_file(p, q, fs::copy_options::overwrite_existing);
  fs::resize_file(q, full - 50);
  OpJournal j;
  CHECK(j.open(q) == JournalStatus::Ok);
  CHECK_N(j.ops_written(), 4096);
  CHECK_N(j.last_op_id(), 4096);
  OperationBus bus;
  bus.add_applier(&j);
  // no set_next_op_id: the bus continues after the reopened journal by itself
  for (std::uint32_t n = 4096; n < 5000; ++n) bus.submit(make_op(1, n, 2), n, 0);
  bus.flush();
  j.close();
  JournalScan s = OpJournal::scan(q);
  CHECK(s.status == JournalStatus::Ok);
  CHECK_N(s.ops, 5000);
  CHECK_N(s.last_op_id, 5000);
  // Same op_ids as the uncrashed journal, and the stream differs only by tick: ids are contiguous.
  std::vector<Operation> ops;
  OpJournal::scan(q, &ops);
  for (std::size_t i = 0; i < ops.size(); ++i) CHECK_N(ops[i].op_id, i + 1);
  // A journal cut inside its file header is restarted empty.
  const auto h = temp_path("crash_hdr");
  fs::copy_file(p, h, fs::copy_options::overwrite_existing);
  fs::resize_file(h, 5);
  OpJournal j2;
  CHECK(j2.open(h) == JournalStatus::Ok);
  CHECK_N(j2.ops_written(), 0);
}

TEST(wrong_crc_refused) {
  const auto p = temp_path("crc");
  run_workload(2, p);
  const auto size = fs::file_size(p);
  std::vector<std::uint8_t> data(size);
  {
    std::FILE* f = std::fopen(p.string().c_str(), "rb");
    CHECK(std::fread(data.data(), 1, size, f) == size);
    std::fclose(f);
  }
  data[kFileHeaderBytes + kBlockHeaderBytes + 60] ^= 0x01;   // flip one body bit
  {
    std::FILE* f = std::fopen(p.string().c_str(), "wb");
    std::fwrite(data.data(), 1, size, f);
    std::fclose(f);
  }
  CHECK(OpJournal::scan(p).status == JournalStatus::BadCrc);
  Recorder rec;
  CHECK(OpJournal::replay(p, rec).status == JournalStatus::BadCrc);
  CHECK_N(rec.seen.size(), 0);   // nothing applied from a corrupt journal
  OpJournal j;
  CHECK(j.open(p) == JournalStatus::BadCrc);
  CHECK(!j.is_open());
  CHECK_N(fs::file_size(p), size);   // untouched
}

TEST(future_operation_in_journal_refused) {
  // Hand-build a valid block (good CRC) holding an operation of a future version.
  const auto p = temp_path("future");
  run_workload(1, p);
  std::vector<std::uint8_t> file;
  {
    std::FILE* f = std::fopen(p.string().c_str(), "rb");
    std::uint8_t buf[4096]; std::size_t n;
    while ((n = std::fread(buf, 1, sizeof buf, f)) > 0) file.insert(file.end(), buf, buf + n);
    std::fclose(f);
  }
  Operation op = make_op(1, 0, 9);
  op.op_id = 1;
  auto body = encode(op);
  body[39] = 2;   // version from the future
  const std::uint32_t crc = crc32(body);
  std::vector<std::uint8_t> blk;
  auto put32 = [&](std::uint32_t v) { for (int i = 0; i < 4; ++i) blk.push_back(static_cast<std::uint8_t>(v >> (8 * i))); };
  put32(0x4B42504Fu); put32(1); put32(static_cast<std::uint32_t>(body.size())); put32(crc);
  for (int i = 0; i < 8; ++i) blk.push_back(i == 0 ? 1 : 0);
  blk.insert(blk.end(), body.begin(), body.end());
  file.resize(kFileHeaderBytes);   // header only
  file.insert(file.end(), blk.begin(), blk.end());
  {
    std::FILE* f = std::fopen(p.string().c_str(), "wb");
    std::fwrite(file.data(), 1, file.size(), f);
    std::fclose(f);
  }
  CHECK(OpJournal::scan(p).status == JournalStatus::BadOperation);
  OpJournal j;
  CHECK(j.open(p) == JournalStatus::BadOperation);
  // Journal file format from the future.
  file[8] = 9;
  std::FILE* f = std::fopen(p.string().c_str(), "wb");
  std::fwrite(file.data(), 1, file.size(), f);
  std::fclose(f);
  CHECK(OpJournal::scan(p).status == JournalStatus::UnsupportedFormat);
}

TEST(crc32_known_value) {
  const char* s = "123456789";
  CHECK_N(crc32(std::span<const std::uint8_t>(reinterpret_cast<const std::uint8_t*>(s), 9)), 0xCBF43926u);
}

TEST(ties_on_every_header_field_are_ordered) {
  // Operations equal on (tick, author, decision_seq, k, kind) and differing only by other fields.
  auto run = [](bool reversed) {
    OperationBus bus;
    Recorder rec;
    bus.add_applier(&rec);
    std::vector<Operation> v;
    for (std::uint64_t c = 100; c < 105; ++c) {
      Operation op = make_op(1, 0, 1);
      op.cause = c; op.noise = static_cast<std::uint8_t>(c % 3); op.gesture = static_cast<std::uint16_t>(c % 2);
      v.push_back(op);
    }
    for (std::uint8_t f = 0; f < 4; ++f) {
      Operation op = make_op(1, 0, 1);
      op.flags = f; op.sight = f; op.trace = f; op.process = f;
      v.push_back(op);
    }
    if (reversed) std::reverse(v.begin(), v.end());
    for (auto& op : v) bus.submit(op, 0, 0);
    bus.flush();
    return rec.seen;
  };
  const auto a = run(false), b = run(true);
  CHECK_N(a.size(), 9);
  CHECK(a == b);
  // Random permutations too (fixed seed: reproducible).
  std::mt19937 g(12345);
  for (int t = 0; t < 20; ++t) {
    OperationBus bus; Recorder rec; bus.add_applier(&rec);
    std::vector<Operation> v;
    for (std::uint64_t c = 0; c < 30; ++c) { Operation op = make_op(1, 0, 1); op.cause = c; op.trace = c % 4; v.push_back(op); }
    std::shuffle(v.begin(), v.end(), g);
    for (auto& op : v) bus.submit(op, 0, 0);
    bus.flush();
    for (std::size_t i = 1; i < rec.seen.size(); ++i) CHECK(rec.seen[i - 1].trace < rec.seen[i].trace ||
        (rec.seen[i - 1].trace == rec.seen[i].trace && rec.seen[i - 1].cause < rec.seen[i].cause));
  }
}

#if defined(__unix__)
TEST(process_exit_without_close_keeps_flushed_ops) {
  const auto p = temp_path("fork");
  pid_t pid = fork();
  if (pid == 0) {
    OperationBus bus;
    OpJournal j;
    if (j.open(p) != JournalStatus::Ok) _exit(2);
    bus.add_applier(&j);
    for (std::uint32_t n = 0; n < 100; ++n) bus.submit(make_op(1, n, 1), n, 0);
    bus.flush();
    _exit(0);   // no close(), no destructor: like a crash after the step
  }
  int st = 0;
  waitpid(pid, &st, 0);
  CHECK(WIFEXITED(st) && WEXITSTATUS(st) == 0);
  JournalScan s = OpJournal::scan(p);
  CHECK(s.status == JournalStatus::Ok);
  CHECK_N(s.ops, 100);
}
#endif

TEST(garbage_or_zero_tail_is_a_truncated_tail) {
  const auto base = temp_path("garbage_base");
  {
    OperationBus bus; OpJournal j; j.open(base); bus.add_applier(&j);
    for (std::uint32_t n = 0; n < 5000; ++n) bus.submit(make_op(1, n, 1), n, 0);
    bus.flush();
  }
  const auto good = fs::file_size(base);
  for (std::size_t len : {24, 100, 4096}) {
    for (int mode = 0; mode < 2; ++mode) {   // 0 = zeros, 1 = pseudo-random bytes
      const auto q = temp_path("garbage");
      fs::copy_file(base, q, fs::copy_options::overwrite_existing);
      std::vector<std::uint8_t> junk(len, 0);
      if (mode) { std::mt19937 g(7); for (auto& b : junk) b = static_cast<std::uint8_t>(g()); }
      std::FILE* f = std::fopen(q.string().c_str(), "ab");
      std::fwrite(junk.data(), 1, junk.size(), f);
      std::fclose(f);
      CHECK(OpJournal::scan(q).status == JournalStatus::TruncatedTail);
      OpJournal j;
      CHECK(j.open(q) == JournalStatus::Ok);
      CHECK_N(j.ops_written(), 5000);
      j.close();
      CHECK_N(fs::file_size(q), good);   // tail cut, valid blocks intact
      CHECK(OpJournal::scan(q).status == JournalStatus::Ok);
    }
  }
}

TEST(valid_block_after_invalid_block_is_refused) {
  const auto p = temp_path("midfile");
  {
    OperationBus bus; OpJournal j; j.open(p); bus.add_applier(&j);
    for (std::uint32_t n = 0; n < 9000; ++n) bus.submit(make_op(1, n, 1), n, 0);
    bus.flush();
  }
  std::vector<std::uint8_t> d(fs::file_size(p));
  std::FILE* f = std::fopen(p.string().c_str(), "rb");
  CHECK(std::fread(d.data(), 1, d.size(), f) == d.size());
  std::fclose(f);
  d[kFileHeaderBytes + 1] ^= 0xFF;   // break the magic of the first of three blocks
  f = std::fopen(p.string().c_str(), "wb");
  std::fwrite(d.data(), 1, d.size(), f);
  std::fclose(f);
  CHECK(OpJournal::scan(p).status == JournalStatus::BadMagic);
  OpJournal j;
  CHECK(j.open(p) == JournalStatus::BadMagic);
  CHECK_N(fs::file_size(p), d.size());
}

TEST(reopened_journal_continues_ids_automatically) {
  const auto p = temp_path("reopen");
  {
    OperationBus bus; OpJournal j; j.open(p); bus.add_applier(&j);
    for (std::uint32_t n = 0; n < 10; ++n) bus.submit(make_op(1, n, 1), n, 0);
    bus.flush();
  }
  OperationBus bus; OpJournal j; CHECK(j.open(p) == JournalStatus::Ok); bus.add_applier(&j);
  for (std::uint32_t n = 0; n < 5; ++n) bus.submit(make_op(1, n, 2), n, 0);
  bus.flush();
  CHECK_N(bus.stats().rejected_by_applier, 0);
  CHECK_N(bus.stats().applied, 5);
  CHECK_N(OpJournal::scan(p).last_op_id, 15);
}

EMERGENCE_TEST_MAIN()
