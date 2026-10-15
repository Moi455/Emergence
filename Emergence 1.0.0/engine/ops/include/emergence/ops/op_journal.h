// OpJournal: append-only operation log (docs/14 section 4.9), also an Applier (subscriber 6).
//
// File layout, little-endian:
//   file header (16 bytes): "EMOPLG\0\0", u32 format_version (=1), u32 reserved
//   block*: u32 block_magic 'OPBK', u32 op_count (1..4096), u32 body_bytes, u32 crc32(body),
//           u64 first_op_id, body = op_count encoded operations back to back
// Operations are buffered and written 4096 at a time (or at flush()). A crash leaves at most a
// truncated last block: scan() reports it, open() cuts it and resumes. A block whose CRC is wrong
// is never skipped nor repaired: the journal is refused. Operations of a future version or of an
// unknown kind are refused as well (BadOperation). A last block with an invalid header (garbage
// or zeros after a crash) is a truncated tail too, unless a valid block follows it (then: refused).
// Durability: the bus flushes the journal at the end of every flush() (fwrite + fflush + fsync, the
// directory too at creation). Remaining loss window: operations applied by a bus flush() that
// has not returned, and whatever the OS/disk acknowledged fsync for but did not persist.
#pragma once
#include <cstdint>
#include <cstdio>
#include <filesystem>
#include <string>
#include <vector>

#include "emergence/ops/applier.h"
#include "emergence/ops/digest.h"
#include "emergence/ops/operation.h"

namespace em::ops {

inline constexpr std::uint32_t kJournalFormatVersion = 1;
inline constexpr std::uint32_t kBlockOps = 4096;
inline constexpr std::size_t kFileHeaderBytes = 16;
inline constexpr std::size_t kBlockHeaderBytes = 24;

enum class JournalStatus : std::uint8_t {
  Ok,
  TruncatedTail,      // clean blocks followed by an incomplete one (crash); recoverable
  BadMagic,
  UnsupportedFormat,  // file format version from the future
  BadCrc,
  BadOperation,       // an operation of an unknown version/kind, or malformed
  NonMonotonic,       // op_id not strictly increasing
  IoError,
};
const char* to_string(JournalStatus s);

struct JournalScan {
  JournalStatus status = JournalStatus::Ok;
  std::uint64_t ops = 0;             // operations in the clean blocks
  std::uint64_t blocks = 0;
  std::uint64_t last_op_id = 0;      // 0 when empty
  std::uint64_t good_bytes = 0;      // length of the clean prefix (file header included)
  std::uint64_t file_bytes = 0;
  std::uint64_t fingerprint = 0;     // FNV-1a over the encoded bytes of every clean operation
};

class OpJournal final : public Applier {
 public:
  OpJournal() = default;
  ~OpJournal() override;
  OpJournal(const OpJournal&) = delete;
  OpJournal& operator=(const OpJournal&) = delete;

  // Creates the file, or resumes an existing one (cutting a truncated tail). Any other status
  // leaves the journal closed and the file untouched.
  JournalStatus open(const std::filesystem::path& path);
  bool is_open() const { return file_ != nullptr; }
  // Writes the buffered partial block and flushes the stream to the OS.
  bool flush();
  void close();

  std::string_view name() const override { return "OpJournal"; }
  ApplyStatus apply(const Operation& op) override;   // appends; Rejected if closed or I/O error
  std::uint64_t fingerprint() const override { return fingerprint_.value(); }

  std::uint64_t ops_written() const { return ops_; }       // including the buffered ones
  std::uint64_t last_op_id() const override { return last_op_id_; }
  void end_of_flush() override { flush(); }   // one durability point per bus step
  bool io_error() const { return io_error_; }   // sticky: a block write failed, ops stay buffered

  // Reads the file without modifying it. If out is non-null, receives the clean operations.
  static JournalScan scan(const std::filesystem::path& path, std::vector<Operation>* out = nullptr);
  // Feeds every clean operation of the file, in order, to the applier. Refuses a bad journal
  // before applying anything; a truncated tail is accepted (status TruncatedTail).
  static JournalScan replay(const std::filesystem::path& path, Applier& applier);

 private:
  bool write_block();
  bool sync_file();
  bool io_error_ = false;
  std::FILE* file_ = nullptr;
  std::vector<std::uint8_t> buffer_;   // encoded operations of the open block
  std::uint32_t buffered_ops_ = 0;
  std::uint64_t first_buffered_id_ = 0;
  std::uint64_t ops_ = 0, last_op_id_ = 0;
  Fnv64 fingerprint_;
};

}  // namespace em::ops
