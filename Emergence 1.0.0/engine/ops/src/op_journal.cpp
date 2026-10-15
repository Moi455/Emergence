#include "emergence/ops/op_journal.h"

#include <algorithm>
#include <cstring>
#include <system_error>

#if defined(__unix__) || defined(__APPLE__)
#include <fcntl.h>
#include <unistd.h>
#endif

namespace em::ops {
namespace {

constexpr char kFileMagic[8] = {'E', 'M', 'O', 'P', 'L', 'G', 0, 0};
constexpr std::uint32_t kBlockMagic = 0x4B42504Fu;   // 'O','P','B','K' little-endian

void put32(std::vector<std::uint8_t>& o, std::uint32_t v) {
  for (int i = 0; i < 4; ++i) o.push_back(static_cast<std::uint8_t>(v >> (8 * i)));
}
void put64(std::vector<std::uint8_t>& o, std::uint64_t v) {
  for (int i = 0; i < 8; ++i) o.push_back(static_cast<std::uint8_t>(v >> (8 * i)));
}
std::uint32_t get32(const std::uint8_t* p) {
  return static_cast<std::uint32_t>(p[0]) | (static_cast<std::uint32_t>(p[1]) << 8) |
         (static_cast<std::uint32_t>(p[2]) << 16) | (static_cast<std::uint32_t>(p[3]) << 24);
}

std::vector<std::uint8_t> file_header() {
  std::vector<std::uint8_t> h(kFileMagic, kFileMagic + 8);
  put32(h, kJournalFormatVersion);
  put32(h, 0);
  return h;
}

bool read_all(const std::filesystem::path& path, std::vector<std::uint8_t>& data) {
  std::FILE* f = std::fopen(path.string().c_str(), "rb");
  if (!f) return false;
  std::uint8_t chunk[1 << 16];
  std::size_t n;
  while ((n = std::fread(chunk, 1, sizeof chunk, f)) > 0) data.insert(data.end(), chunk, chunk + n);
  const bool ok = !std::ferror(f);
  std::fclose(f);
  return ok;
}

// True if some offset >= from holds a complete block: magic, sane header, body present, CRC good.
bool valid_block_after(const std::vector<std::uint8_t>& d, std::size_t from) {
  for (std::size_t o = from; o + kBlockHeaderBytes <= d.size(); ++o) {
    const std::uint8_t* h = d.data() + o;
    if (get32(h) != kBlockMagic) continue;
    const std::uint32_t count = get32(h + 4), body = get32(h + 8);
    if (count == 0 || count > kBlockOps || d.size() - o - kBlockHeaderBytes < body) continue;
    if (crc32(std::span<const std::uint8_t>(h + kBlockHeaderBytes, body)) == get32(h + 12)) return true;
  }
  return false;
}

std::uint64_t get64(const std::uint8_t* p) {
  return static_cast<std::uint64_t>(get32(p)) | (static_cast<std::uint64_t>(get32(p + 4)) << 32);
}

// fsync of the directory holding path, so the new file name itself survives a crash.
bool sync_directory(const std::filesystem::path& path) {
#if defined(__unix__) || defined(__APPLE__)
  std::filesystem::path dir = path.parent_path();
  if (dir.empty()) dir = ".";
  const int fd = ::open(dir.string().c_str(), O_RDONLY);
  if (fd < 0) return false;
  const bool ok = ::fsync(fd) == 0;
  ::close(fd);
  return ok;
#else
  (void)path;
  return true;
#endif
}

}  // namespace

const char* to_string(JournalStatus s) {
  switch (s) {
    case JournalStatus::Ok: return "ok";
    case JournalStatus::TruncatedTail: return "truncated tail";
    case JournalStatus::BadMagic: return "bad magic";
    case JournalStatus::UnsupportedFormat: return "unsupported format";
    case JournalStatus::BadCrc: return "bad crc";
    case JournalStatus::BadOperation: return "bad operation";
    case JournalStatus::NonMonotonic: return "non-monotonic op_id";
    case JournalStatus::IoError: return "i/o error";
  }
  return "?";
}

JournalScan OpJournal::scan(const std::filesystem::path& path, std::vector<Operation>* out) {
  JournalScan r;
  std::vector<std::uint8_t> data;
  if (!read_all(path, data)) {
    r.status = JournalStatus::IoError;
    return r;
  }
  r.file_bytes = data.size();
  if (data.size() < kFileHeaderBytes) {
    // A header cut by a crash at creation is a truncated tail of an empty journal.
    const bool prefix = std::memcmp(data.data(), kFileMagic, std::min<std::size_t>(data.size(), 8)) == 0;
    r.status = prefix ? JournalStatus::TruncatedTail : JournalStatus::BadMagic;
    return r;
  }
  if (std::memcmp(data.data(), kFileMagic, 8) != 0) {
    r.status = JournalStatus::BadMagic;
    return r;
  }
  if (get32(data.data() + 8) != kJournalFormatVersion) {
    r.status = JournalStatus::UnsupportedFormat;
    return r;
  }
  std::size_t pos = kFileHeaderBytes;
  r.good_bytes = pos;
  Fnv64 fp;
  while (pos < data.size()) {
    if (data.size() - pos < kBlockHeaderBytes) { r.status = JournalStatus::TruncatedTail; break; }
    const std::uint8_t* h = data.data() + pos;
    const std::uint32_t count = get32(h + 4), body = get32(h + 8), crc = get32(h + 12);
    if (get32(h) != kBlockMagic || count == 0 || count > kBlockOps) {
      // Garbage or zeros: a torn tail, unless a valid block follows (then it is mid-file damage).
      r.status = valid_block_after(data, pos + 1) ? JournalStatus::BadMagic : JournalStatus::TruncatedTail;
      break;
    }
    if (data.size() - pos - kBlockHeaderBytes < body) { r.status = JournalStatus::TruncatedTail; break; }
    std::span<const std::uint8_t> bs(h + kBlockHeaderBytes, body);
    if (crc32(bs) != crc) { r.status = JournalStatus::BadCrc; break; }
    // Decode the whole block before accepting any of it.
    std::vector<Operation> block;
    Fnv64 bfp = fp;
    std::size_t off = 0;
    bool bad = false;
    std::uint64_t last = r.last_op_id;
    for (std::uint32_t i = 0; i < count && !bad; ++i) {
      Operation op;
      std::size_t used = 0;
      if (decode(bs.subspan(off), op, used) != DecodeStatus::Ok) { r.status = JournalStatus::BadOperation; bad = true; break; }
      if (i == 0 && op.op_id != get64(h + 16)) { r.status = JournalStatus::BadOperation; bad = true; break; }
      if (op.op_id <= last) { r.status = JournalStatus::NonMonotonic; bad = true; break; }
      last = op.op_id;
      bfp.add(bs.subspan(off, used));
      off += used;
      block.push_back(std::move(op));
    }
    if (!bad && off != body) { r.status = JournalStatus::BadOperation; bad = true; }
    if (bad) break;
    fp = bfp;
    r.last_op_id = last;
    r.ops += count;
    ++r.blocks;
    pos += kBlockHeaderBytes + body;
    r.good_bytes = pos;
    if (out) for (Operation& op : block) out->push_back(std::move(op));
  }
  r.fingerprint = fp.value();
  return r;
}

JournalScan OpJournal::replay(const std::filesystem::path& path, Applier& applier) {
  std::vector<Operation> ops;
  JournalScan r = scan(path, &ops);
  if (r.status != JournalStatus::Ok && r.status != JournalStatus::TruncatedTail) return r;
  for (const Operation& op : ops) applier.apply(op);
  return r;
}

OpJournal::~OpJournal() { close(); }

JournalStatus OpJournal::open(const std::filesystem::path& path) {
  close();
  std::error_code ec;
  std::uint64_t keep = 0;
  if (std::filesystem::exists(path, ec)) {
    JournalScan s = scan(path);
    const bool empty_header_cut = s.status == JournalStatus::TruncatedTail && s.good_bytes == 0;
    if (s.status != JournalStatus::Ok && s.status != JournalStatus::TruncatedTail) return s.status;
    if (!empty_header_cut) {
      if (s.status == JournalStatus::TruncatedTail) {
        std::filesystem::resize_file(path, s.good_bytes, ec);
        if (ec) return JournalStatus::IoError;
      }
      ops_ = s.ops;
      last_op_id_ = s.last_op_id;
      fingerprint_ = Fnv64(s.fingerprint);
      keep = s.good_bytes;
    }
  }
  file_ = std::fopen(path.string().c_str(), keep ? "ab" : "wb");
  if (!file_) return JournalStatus::IoError;
  if (!keep) {
    ops_ = 0; last_op_id_ = 0; fingerprint_ = Fnv64();
    const auto h = file_header();
    if (std::fwrite(h.data(), 1, h.size(), file_) != h.size() || !sync_file() || !sync_directory(path)) {
      close();
      return JournalStatus::IoError;
    }
  }
  return JournalStatus::Ok;
}

ApplyStatus OpJournal::apply(const Operation& op) {
  if (!file_ || op.op_id <= last_op_id_) return ApplyStatus::Rejected;   // the bus never sends a stale id
  const std::size_t before = buffer_.size();
  encode(op, buffer_);
  fingerprint_.add(std::span<const std::uint8_t>(buffer_).subspan(before));
  if (buffered_ops_ == 0) first_buffered_id_ = op.op_id;
  ++buffered_ops_;
  ++ops_;
  last_op_id_ = op.op_id;
  if (buffered_ops_ >= kBlockOps && !write_block()) return ApplyStatus::Rejected;
  return ApplyStatus::Applied;
}

bool OpJournal::write_block() {
  if (buffered_ops_ == 0) return true;
  std::vector<std::uint8_t> h;
  h.reserve(kBlockHeaderBytes);
  put32(h, kBlockMagic);
  put32(h, buffered_ops_);
  put32(h, static_cast<std::uint32_t>(buffer_.size()));
  put32(h, crc32(buffer_));
  put64(h, first_buffered_id_);
  const long start = std::ftell(file_);
  const bool ok = std::fwrite(h.data(), 1, h.size(), file_) == h.size() &&
                  std::fwrite(buffer_.data(), 1, buffer_.size(), file_) == buffer_.size();
  if (!ok) {
    // Keep the operations buffered for a retry, and drop whatever part of the block reached the file.
    io_error_ = true;
    std::fflush(file_);
#if defined(__unix__) || defined(__APPLE__)
    if (start >= 0 && ::ftruncate(::fileno(file_), start) == 0) std::fseek(file_, start, SEEK_SET);
#endif
    return false;
  }
  io_error_ = false;
  buffer_.clear();
  buffered_ops_ = 0;
  return true;
}

bool OpJournal::flush() {
  if (!file_) return false;
  if (!write_block()) return false;
  return sync_file();
}

bool OpJournal::sync_file() {
  if (std::fflush(file_) != 0) return false;
#if defined(__unix__) || defined(__APPLE__)
  if (::fsync(::fileno(file_)) != 0) return false;
#endif
  return true;
}

void OpJournal::close() {
  if (!file_) return;
  flush();
  std::fclose(file_);
  file_ = nullptr;
}

}  // namespace em::ops
