// NpcStateCodec: see the header. Little-endian, fixed-width, no struct copied as a block.
#include "emergence/social/npc_state_codec.h"
#include "emergence/social/vocab_gen.h"

#include <algorithm>
#include <array>
#include <bit>
#include <cstring>
#include <limits>
#include <unordered_map>
#include <unordered_set>

namespace em::social {

using gen::ColType;
using gen::ComponentDesc;
using gen::FieldDesc;

namespace {

// ---- bytes -------------------------------------------------------------------------------------------------

class Writer {
 public:
  Writer() { buf_.reserve(1 << 12); }
  void u8(std::uint8_t v) { buf_.push_back(v); }
  void u16(std::uint16_t v) { put(&v, 2); }
  void u32(std::uint32_t v) { put(&v, 4); }
  void u64(std::uint64_t v) { put(&v, 8); }
  void str(std::string_view s) { u16(std::uint16_t(s.size())); bytes(std::span(reinterpret_cast<const std::uint8_t*>(s.data()), s.size())); }
  void bytes(std::span<const std::uint8_t> b) { buf_.insert(buf_.end(), b.begin(), b.end()); }
  std::vector<std::uint8_t>& data() { return buf_; }

 private:
  void put(const void* p, std::size_t n) {
    const auto* b = static_cast<const std::uint8_t*>(p);
    buf_.insert(buf_.end(), b, b + n);
  }
  std::vector<std::uint8_t> buf_;
};
static_assert(std::endian::native == std::endian::little, "the save format is little-endian: add byte swaps for a big-endian target");

// A read past the end returns 0 and sets bad(): the caller checks it before trusting what it read.
class Reader {
 public:
  explicit Reader(std::span<const std::uint8_t> d) : d_(d) {}
  std::uint64_t le(int n) {
    if (bad_ || d_.size() - p_ < std::size_t(n)) { bad_ = true; return 0; }
    std::uint64_t v = 0;
    std::memcpy(&v, d_.data() + p_, std::size_t(n));   // little-endian host (asserted below)
    p_ += std::size_t(n);
    return v;
  }
  std::uint8_t u8() { return std::uint8_t(le(1)); }
  std::uint16_t u16() { return std::uint16_t(le(2)); }
  std::uint32_t u32() { return std::uint32_t(le(4)); }
  std::uint64_t u64() { return le(8); }
  std::string str() {
    const std::size_t n = u16();
    if (bad_ || d_.size() - p_ < n) { bad_ = true; return {}; }
    std::string s(reinterpret_cast<const char*>(d_.data() + p_), n);
    p_ += n;
    return s;
  }
  std::span<const std::uint8_t> bytes(std::size_t n) {
    if (bad_ || d_.size() - p_ < n) { bad_ = true; return {}; }
    auto s = d_.subspan(p_, n);
    p_ += n;
    return s;
  }
  std::size_t left() const { return d_.size() - p_; }
  bool bad() const { return bad_; }
  void fail() { bad_ = true; }

 private:
  std::span<const std::uint8_t> d_;
  std::size_t p_ = 0;
  bool bad_ = false;
};

constexpr std::uint32_t kNameWords = 'W' | 'O' << 8 | 'R' << 16 | 'D' << 24;
constexpr std::uint32_t kNameKinds = 'K' | 'I' << 8 | 'N' << 16 | 'D' << 24;
constexpr std::uint32_t kNameVars = 'V' | 'A' << 8 | 'R' << 16 | 'S' << 24;
constexpr std::uint32_t kNameGestures = 'G' | 'E' << 8 | 'S' << 16 | 'T' << 24;
constexpr std::uint32_t kNameConditions = 'C' | 'O' << 8 | 'N' << 16 | 'D' << 24;

std::uint64_t fnv1a64(std::span<const std::uint8_t> b) {
  std::uint64_t h = 0xcbf29ce484222325ull;
  for (std::uint8_t c : b) { h ^= c; h *= 0x100000001b3ull; }
  return h;
}

// ---- descriptors in a fixed order (flat components, then pools) -------------------------------------------

const std::vector<const ComponentDesc*>& all_descs() {
  static const std::vector<const ComponentDesc*> v = [] {
    std::vector<const ComponentDesc*> d;
    auto s = std::make_unique<gen::NpcState>();
    gen::visit_components(*s, [&](const ComponentDesc& c, auto&) { d.push_back(&c); });
    gen::visit_pools(*s, [&](const ComponentDesc& c, auto&) { d.push_back(&c); });
    return d;
  }();
  return v;
}

// ---- encoding of one NPC -----------------------------------------------------------------------------------

struct ListEnc {
  const SideTable* side;
  const PropositionArena* props;                    // behind the PropRef fields
  std::vector<ListRef> order;                       // lists in order of first use
  std::unordered_map<ListRef, std::uint32_t> index; // ref -> 1-based index
  std::uint32_t of(ListRef ref) {
    if (ref == 0 || side->get(ref).empty()) return 0;
    auto [it, fresh] = index.try_emplace(ref, std::uint32_t(order.size() + 1));
    if (fresh) order.push_back(ref);
    return it->second;
  }
};

void write_cells(Writer& w, const ComponentDesc& d, const unsigned char* base, ListEnc& le) {
  for (const FieldDesc& f : d.fields) {
    const unsigned char* p = base + f.offset;
    switch (f.type) {
      case ColType::Bool: w.u8(*p != 0 ? 1 : 0); break;
      case ColType::U8: w.u8(*p); break;
      case ColType::U16: { std::uint16_t v; std::memcpy(&v, p, 2); w.u16(v); break; }
      case ColType::I16: { std::uint16_t v; std::memcpy(&v, p, 2); w.u16(v); break; }
      case ColType::I32: { std::uint32_t v; std::memcpy(&v, p, 4); w.u32(v); break; }
      case ColType::Entity: case ColType::MRef: { std::uint32_t v; std::memcpy(&v, p, 4); w.u32(v); break; }
      case ColType::Time: { std::uint64_t v; std::memcpy(&v, p, 8); w.u64(v); break; }
      case ColType::List: { ListRef v; std::memcpy(&v, p, 4); w.u32(le.of(v)); break; }
      case ColType::Prop: {
        PropRef ref;
        std::memcpy(&ref, p, 4);
        const Proposition pr = le.props->get(ref);   // the wire format is the one of the 20-symbol exchange type
        w.u8(std::uint8_t(pr.size()));
        for (int i = 0; i < pr.size(); ++i) { w.u32(pr.symbol(i)); w.u8(pr.children(i)); }
        break;
      }
    }
  }
}

template <class Pool>
void write_pool(Writer& w, const ComponentDesc& d, const Pool& pool, ListEnc& le) {
  w.u32(pool.next_serial());
  w.u32(std::uint32_t(pool.forgotten()));
  w.u32(std::uint32_t(pool.evicted_protected()));
  w.u32(std::uint32_t(pool.size()));
  for (int i = 0; i < Pool::kCapacity; ++i) {
    if (!pool.slot_used(i)) continue;
    w.u32(std::uint32_t(i));
    w.u32(pool.slot_serial(i));
    write_cells(w, d, reinterpret_cast<const unsigned char*>(&pool.slot_record(i)), le);
  }
}

void encode_npc(Writer& out, const NpcBundle& npc) {
  ListEnc le{&npc.side, &npc.propositions, {}, {}};
  Writer body;
  gen::visit_components(npc.state, [&](const ComponentDesc& d, const auto& c) {
    write_cells(body, d, reinterpret_cast<const unsigned char*>(&c), le);
  });
  gen::visit_pools(npc.state, [&](const ComponentDesc& d, const auto& pool) { write_pool(body, d, pool, le); });
  body.u32(std::uint32_t(npc.ledger.day()));
  body.u32(std::uint32_t(npc.ledger.life_year()));
  const auto entries = npc.ledger.entries();
  body.u32(std::uint32_t(entries.size()));
  for (const LedgerEntry& e : entries) {
    body.u32(e.target);
    body.u32(e.var);   // gen::Var == index in kVarNames == index in the NAME variables table
    body.u32(std::uint32_t(e.day_stamp));
    body.u32(std::uint32_t(e.year_stamp));
    body.u32(std::uint32_t(e.day_moved));
    body.u32(std::uint32_t(e.year_moved));
  }
  body.u32(std::uint32_t(npc.mental_map.size()));
  body.bytes(npc.mental_map);

  out.u32(std::uint32_t(le.order.size()));
  for (ListRef ref : le.order) {
    const auto items = npc.side.get(ref);
    out.u16(std::uint16_t(items.size()));
    for (std::uint32_t v : items) out.u32(v);
  }
  out.bytes(body.data());
}

// ---- decoding ----------------------------------------------------------------------------------------------

struct SavedCol {
  std::string name;
  ColType type{};
  const FieldDesc* cur = nullptr;   // null = unknown column
};
struct SavedComp {
  std::string name;
  bool record = false;
  std::uint32_t capacity = 0;
  std::vector<SavedCol> cols;
  const ComponentDesc* cur = nullptr;   // null = unknown kind
};

constexpr std::uint32_t kNone = std::numeric_limits<std::uint32_t>::max();

struct LoadCtx {
  std::vector<std::uint32_t> word_map, kind_map, var_map;   // saved index -> index in this build (kNone = gone)
  std::vector<std::vector<std::uint32_t>> lists;
  std::vector<ListRef> list_refs;
  std::vector<bool> list_done;
  SideTable* side = nullptr;
  PropositionArena* props = nullptr;
  LoadReport* rep = nullptr;
  Refusal refusal = Refusal::None;
  std::string detail;
  void refuse(Refusal r, std::string d = {}) { if (refusal == Refusal::None) { refusal = r; detail = std::move(d); } }
};

struct Cell {
  std::int64_t i = 0;
  Proposition p;
};

bool compatible(ColType saved, ColType cur) {
  return saved == cur || (saved == ColType::I16 && cur == ColType::I32) || (saved == ColType::U8 && cur == ColType::U16);
}
bool valid_type(std::uint8_t t) { return t >= 1 && t <= 10; }

void read_cell(Reader& r, ColType t, Cell& c, LoadCtx& cx) {
  switch (t) {
    case ColType::Bool: case ColType::U8: c.i = r.u8(); break;
    case ColType::U16: c.i = r.u16(); break;
    case ColType::I16: c.i = std::int16_t(r.u16()); break;
    case ColType::I32: c.i = std::int32_t(r.u32()); break;
    case ColType::Entity: case ColType::MRef: case ColType::List: c.i = r.u32(); break;
    case ColType::Time: c.i = std::int64_t(r.u64()); break;
    case ColType::Prop: {
      c.p = Proposition{};
      const unsigned n = r.u8();
      if (n == 0) return;
      if (n > unsigned(Proposition::kMax)) { r.fail(); return; }
      Proposition p;
      bool gone = false;
      for (unsigned k = 0; k < n && !r.bad(); ++k) {
        std::uint32_t sym = r.u32();
        const std::uint8_t arity = r.u8();
        const auto tag = Proposition::tag(sym);
        if (tag == Proposition::kWord || tag == Proposition::kKind) {   // translated through the NAME tables
          const auto& map = tag == Proposition::kWord ? cx.word_map : cx.kind_map;
          const std::uint32_t v = Proposition::value(sym);
          if (v >= map.size() || map[v] == kNone) gone = true;
          else sym = Proposition::make(tag, map[v]);
        }
        p.push(sym, arity);
      }
      bool tags_ok = true;
      for (int k = 0; k < p.size(); ++k) {
        const auto tg = Proposition::tag(p.symbol(k));
        tags_ok = tags_ok && tg >= Proposition::kWord && tg <= Proposition::kName;
      }
      if (n > 0 && (!tags_ok || !p.well_formed())) { ++cx.rep->invalid_propositions; return; }
      if (gone) { ++cx.rep->dropped_propositions; return; }   // a word that no longer exists: the proposition is emptied
      c.p = p;
      break;
    }
  }
}

void store_cell(unsigned char* base, const FieldDesc& f, const Cell& c, LoadCtx& cx, Reader& r) {
  unsigned char* p = base + f.offset;
  if (f.type != ColType::Prop && f.type != ColType::List && (c.i < f.min || c.i > f.max)) {
    ++cx.rep->out_of_range_values;   // the field keeps its initial value
    return;
  }
  switch (f.type) {
    case ColType::Bool: *p = c.i != 0; break;
    case ColType::U8: *p = std::uint8_t(c.i); break;
    case ColType::U16: { auto v = std::uint16_t(c.i); std::memcpy(p, &v, 2); break; }
    case ColType::I16: { auto v = std::int16_t(c.i); std::memcpy(p, &v, 2); break; }
    case ColType::I32: { auto v = std::int32_t(c.i); std::memcpy(p, &v, 4); break; }
    case ColType::Entity: case ColType::MRef: { auto v = std::uint32_t(c.i); std::memcpy(p, &v, 4); break; }
    case ColType::Time: { auto v = std::int64_t(c.i); std::memcpy(p, &v, 8); break; }
    case ColType::Prop: {   // packed into the NPC's arena, in reading order: deterministic
      PropRef ref = 0;
      if (!c.p.empty()) {
        ref = cx.props->put(c.p);
        if (ref == 0) ++cx.rep->arena_overflow_propositions;   // an old save can hold more than the arena: never a failure
      }
      std::memcpy(p, &ref, 4);
      break;
    }
    case ColType::List: {
      ListRef ref = 0;
      const std::uint64_t idx = std::uint64_t(c.i);
      if (idx > cx.lists.size()) { r.fail(); return; }
      if (idx != 0) {
        if (!cx.list_done[idx - 1]) {   // put lazily, in reading order: deterministic
          cx.list_refs[idx - 1] = cx.side->put(cx.lists[idx - 1]);
          cx.list_done[idx - 1] = true;
          if (cx.list_refs[idx - 1] == 0) ++cx.rep->lost_lists;
        }
        ref = cx.list_refs[idx - 1];
      }
      std::memcpy(p, &ref, 4);
      break;
    }
  }
}

// Reads the cells of one record or flat struct in the SAVED column order; base = null skips them.
void read_cells(Reader& r, const SavedComp& sc, unsigned char* base, LoadCtx& cx) {
  Cell c;   // one cell reused for the whole record (a Proposition is not free to build)
  for (const SavedCol& col : sc.cols) {
    read_cell(r, col.type, c, cx);
    if (r.bad()) return;
    if (base && col.cur) store_cell(base, *col.cur, c, cx, r);
  }
}

template <class Pool>
void read_pool(Reader& r, const SavedComp& sc, Pool* pool, LoadCtx& cx) {
  using T = typename Pool::value_type;
  const std::uint32_t next = r.u32(), forgotten = r.u32(), evicted = r.u32(), count = r.u32();
  if (r.bad() || count > r.left() / 8) { r.fail(); return; }
  if (pool && count > std::uint32_t(Pool::kCapacity)) { cx.refuse(Refusal::CapacityExceeded, sc.name); return; }
  for (std::uint32_t i = 0; i < count && !r.bad(); ++i) {
    const std::uint32_t slot = r.u32(), serial = r.u32();
    T tmp{};
    read_cells(r, sc, pool ? reinterpret_cast<unsigned char*>(&tmp) : nullptr, cx);
    if (r.bad() || !pool) continue;
    if (slot >= std::uint32_t(Pool::kCapacity)) { cx.refuse(Refusal::CapacityExceeded, sc.name); return; }
    if (!pool->restore_slot(int(slot), serial, tmp)) { cx.refuse(Refusal::Malformed, sc.name + ": slot or serial"); return; }
  }
  if (pool && !r.bad() && cx.refusal == Refusal::None &&
      !pool->restore_counters(next, int(forgotten), int(evicted)))
    cx.refuse(Refusal::Malformed, sc.name + ": counters");
}

// An MRef names a record the NPC itself issued: above every serial of its pools, it can only be corrupt.
void sanitize_refs(NpcBundle& npc, LoadReport& rep) {
  std::uint32_t top = 0;
  gen::visit_pools(npc.state, [&](const ComponentDesc&, const auto& pool) { top = std::max(top, pool.next_serial()); });
  auto fix = [&](const ComponentDesc& d, unsigned char* base) {
    for (const FieldDesc& f : d.fields) {
      if (f.type != ColType::MRef) continue;
      std::uint32_t v;
      std::memcpy(&v, base + f.offset, 4);
      if (v > top) { v = 0; std::memcpy(base + f.offset, &v, 4); ++rep.dangling_refs; }
    }
  };
  gen::visit_components(npc.state, [&](const ComponentDesc& d, auto& c) { fix(d, reinterpret_cast<unsigned char*>(&c)); });
  gen::visit_pools(npc.state, [&](const ComponentDesc& d, auto& pool) {
    for (int i = 0; i < std::decay_t<decltype(pool)>::kCapacity; ++i)
      if (pool.slot_used(i)) fix(d, reinterpret_cast<unsigned char*>(&pool.slot_record_mut(i)));
  });
}

bool read_name_table(Reader& r, std::vector<std::string>& out) {
  const std::uint32_t n = r.u32();
  if (r.bad() || n > r.left() / 2) return false;
  out.reserve(n);
  for (std::uint32_t i = 0; i < n; ++i) out.push_back(r.str());
  return !r.bad();
}

std::vector<std::uint32_t> map_by_name(const std::vector<std::string>& saved, std::span<const std::string_view> current) {
  std::unordered_map<std::string_view, std::uint32_t> now;
  for (std::uint32_t i = 0; i < current.size(); ++i) now.emplace(current[i], i);
  std::vector<std::uint32_t> m(saved.size(), kNone);
  for (std::size_t i = 0; i < saved.size(); ++i)
    if (auto it = now.find(saved[i]); it != now.end()) m[i] = it->second;
  return m;
}

LoadReport refused(LoadReport rep, Refusal why, std::string detail = {}) {
  rep.ok = false;
  rep.refusal = why;
  rep.detail = std::move(detail);
  return rep;
}

}  // namespace

// ---- public ------------------------------------------------------------------------------------------------

NameTables NameTables::current() {
  NameTables t;
  for (auto s : gen::kGestureNames) t.gestures.emplace_back(s);
  for (auto s : gen::kConditionNames) t.conditions.emplace_back(s);
  for (auto s : gen::kVarNames) t.variables.emplace_back(s);
  for (auto s : gen::kWords) t.words.emplace_back(s);
  for (auto s : gen::kKinds) t.kinds.emplace_back(s);
  return t;
}

std::uint32_t NpcStateCodec::crc32(std::span<const std::uint8_t> bytes) {
  static const std::array<std::uint32_t, 256> table = [] {
    std::array<std::uint32_t, 256> t{};
    for (std::uint32_t i = 0; i < 256; ++i) {
      std::uint32_t c = i;
      for (int k = 0; k < 8; ++k) c = (c & 1) ? 0xEDB88320u ^ (c >> 1) : c >> 1;
      t[i] = c;
    }
    return t;
  }();
  std::uint32_t c = 0xFFFFFFFFu;
  for (std::uint8_t b : bytes) c = table[(c ^ b) & 0xFF] ^ (c >> 8);
  return c ^ 0xFFFFFFFFu;
}

std::vector<std::uint8_t> NpcStateCodec::wrap_section(std::uint32_t tag, std::uint16_t version, std::span<const std::uint8_t> payload) {
  Writer w;
  w.u32(tag);
  w.u16(version);
  w.u16(0);
  w.u64(payload.size());
  w.u32(crc32(payload));
  w.bytes(payload);
  return std::move(w.data());
}

Refusal NpcStateCodec::unwrap_section(std::span<const std::uint8_t> bytes, std::uint32_t tag, std::span<const std::uint8_t>& payload) {
  Reader r(bytes);
  const std::uint32_t t = r.u32();
  const std::uint16_t version = r.u16();
  r.u16();   // flags: none defined in v1, ignored
  const std::uint64_t len = r.u64();
  const std::uint32_t crc = r.u32();
  if (r.bad()) return Refusal::Truncated;
  if (t != tag) return Refusal::BadTag;
  if (version == 0 || version > kVersion) return Refusal::BadVersion;
  if (len > r.left()) return Refusal::Truncated;
  payload = r.bytes(std::size_t(len));
  return crc32(payload) == crc ? Refusal::None : Refusal::BadCrc;
}

std::vector<std::uint8_t> NpcStateCodec::save_name_section(const NameTables& names) {
  Writer w;
  const std::pair<std::uint32_t, const std::vector<std::string>*> tables[] = {
      {kNameGestures, &names.gestures}, {kNameConditions, &names.conditions}, {kNameVars, &names.variables},
      {kNameWords, &names.words}, {kNameKinds, &names.kinds}};
  w.u32(std::uint32_t(std::size(tables)));
  for (const auto& [id, v] : tables) {
    w.u32(id);
    w.u32(std::uint32_t(v->size()));
    for (const std::string& s : *v) w.str(s);
  }
  return wrap_section(kTagName, kVersion, w.data());
}

std::vector<std::uint8_t> NpcStateCodec::save_npcs_section(std::span<const std::unique_ptr<NpcBundle>> npcs) {
  Writer w;
  const auto& descs = all_descs();
  w.u32(std::uint32_t(descs.size()));
  for (const ComponentDesc* d : descs) {
    w.str(d->name);
    w.u8(d->record ? 1 : 0);
    w.u32(std::uint32_t(d->capacity));
    w.u32(std::uint32_t(d->fields.size()));
    for (const FieldDesc& f : d->fields) { w.str(f.name); w.u8(std::uint8_t(f.type)); }
  }
  w.u32(std::uint32_t(npcs.size()));
  for (const auto& n : npcs) encode_npc(w, *n);
  return wrap_section(kTagNpcs, kVersion, w.data());
}

std::uint64_t NpcStateCodec::fingerprint(const NpcBundle& npc) {
  Writer w;
  encode_npc(w, npc);
  return fnv1a64(w.data());
}

LoadReport NpcStateCodec::load(std::span<const std::uint8_t> name_section, std::span<const std::uint8_t> npcs_section,
                               std::int32_t now_day, std::int32_t now_life_year,
                               std::vector<std::unique_ptr<NpcBundle>>& out) {
  out.clear();   // a refusal leaves nothing behind
  LoadReport rep;
  LoadCtx cx;
  cx.rep = &rep;

  // NAME: the tables that give a meaning back to the indices of the NPCS section.
  std::span<const std::uint8_t> payload;
  if (Refusal e = unwrap_section(name_section, kTagName, payload); e != Refusal::None) return refused(rep, e, "NAME");
  {
    Reader r(payload);
    const std::uint32_t nt = r.u32();
    std::vector<std::string> words, kinds, vars;
    bool has_words = false, has_kinds = false, has_vars = false;
    for (std::uint32_t i = 0; i < nt && !r.bad(); ++i) {
      const std::uint32_t id = r.u32();
      std::vector<std::string> tab;
      if (!read_name_table(r, tab)) return refused(rep, Refusal::Truncated, "NAME");
      if (id == kNameWords) { words = std::move(tab); has_words = true; }
      else if (id == kNameKinds) { kinds = std::move(tab); has_kinds = true; }
      else if (id == kNameVars) { vars = std::move(tab); has_vars = true; }   // other tables: not needed here
    }
    if (r.bad()) return refused(rep, Refusal::Truncated, "NAME");
    if (!has_words || !has_kinds || !has_vars) return refused(rep, Refusal::NameTableMissing, "NAME");
    cx.word_map = map_by_name(words, gen::kWords);
    cx.kind_map = map_by_name(kinds, gen::kKinds);
    cx.var_map = map_by_name(vars, gen::kVarNames);
  }

  if (Refusal e = unwrap_section(npcs_section, kTagNpcs, payload); e != Refusal::None) return refused(rep, e, "NPCS");
  Reader r(payload);

  // Schema of the save: kinds and columns by name, with their storage types.
  const auto& descs = all_descs();
  std::vector<SavedComp> comps;
  const std::uint32_t ncomp = r.u32();
  if (r.bad() || ncomp > r.left() / 8) return refused(rep, Refusal::Truncated, "NPCS schema");
  std::unordered_set<std::string> seen_comp;
  for (std::uint32_t i = 0; i < ncomp; ++i) {
    SavedComp sc;
    sc.name = r.str();
    sc.record = r.u8() != 0;
    sc.capacity = r.u32();
    const std::uint32_t ncol = r.u32();
    if (r.bad() || ncol > r.left() / 3 || !seen_comp.insert(sc.name).second) return refused(rep, Refusal::Malformed, "NPCS schema");
    for (const ComponentDesc* d : descs)
      if (d->name == sc.name) sc.cur = d;
    if (sc.cur && sc.cur->record != sc.record) return refused(rep, Refusal::TypeChanged, sc.name + ": flat/record");
    if (!sc.cur) ++rep.unknown_components;
    std::unordered_set<std::string> seen_col;
    for (std::uint32_t k = 0; k < ncol; ++k) {
      SavedCol col;
      col.name = r.str();
      const std::uint8_t t = r.u8();
      if (r.bad() || !valid_type(t) || !seen_col.insert(col.name).second) return refused(rep, Refusal::Malformed, "NPCS schema");
      col.type = static_cast<ColType>(t);
      if (sc.cur) {
        for (const FieldDesc& f : sc.cur->fields)
          if (f.name == col.name) col.cur = &f;
        if (col.cur && !compatible(col.type, col.cur->type)) return refused(rep, Refusal::TypeChanged, sc.name + "." + col.name);
        if (!col.cur) ++rep.unknown_columns;
        else if (col.type != col.cur->type) ++rep.widened_columns;
      }
      sc.cols.push_back(std::move(col));
    }
    if (sc.cur)
      for (const FieldDesc& f : sc.cur->fields) {
        bool found = false;
        for (const SavedCol& c : sc.cols) found = found || c.cur == &f;
        if (!found) ++rep.absent_columns;
      }
    comps.push_back(std::move(sc));
  }
  for (const ComponentDesc* d : descs) {   // a kind the save lacks entirely: every column is absent
    if (!seen_comp.contains(std::string(d->name))) rep.absent_columns += d->fields.size();
  }
  if (r.bad()) return refused(rep, Refusal::Truncated, "NPCS schema");

  const std::uint32_t nnpc = r.u32();
  if (r.bad() || nnpc > r.left() / 16) return refused(rep, Refusal::Truncated, "NPCS count");
  std::vector<std::unique_ptr<NpcBundle>> loaded;
  loaded.reserve(nnpc);
  for (std::uint32_t n = 0; n < nnpc; ++n) {
    auto npc = std::make_unique<NpcBundle>();
    cx.side = &npc->side;
    cx.props = &npc->propositions;
    cx.lists.clear();
    const std::uint32_t nl = r.u32();
    if (r.bad() || nl > r.left() / 2) return refused(rep, Refusal::Truncated, "NPCS lists");
    cx.lists.resize(nl);
    for (auto& l : cx.lists) {
      const std::size_t len = r.u16();
      if (r.bad() || len * 4 > r.left()) return refused(rep, Refusal::Truncated, "NPCS lists");
      l.resize(len);
      for (auto& v : l) v = r.u32();
    }
    cx.list_refs.assign(nl, 0);
    cx.list_done.assign(nl, false);

    for (const SavedComp& sc : comps) {
      if (sc.record) {
        bool done = false;
        gen::visit_pools(npc->state, [&](const ComponentDesc& d, auto& pool) {
          if (&d == sc.cur) { read_pool(r, sc, &pool, cx); done = true; }
        });
        if (!done) read_pool<RecordPool<gen::Skill, 1>>(r, sc, nullptr, cx);   // unknown kind: parsed and dropped
      } else {
        unsigned char* base = nullptr;
        gen::visit_components(npc->state, [&](const ComponentDesc& d, auto& c) {
          if (&d == sc.cur) base = reinterpret_cast<unsigned char*>(&c);
        });
        read_cells(r, sc, base, cx);
      }
      if (cx.refusal != Refusal::None) return refused(rep, cx.refusal, cx.detail);
      if (r.bad()) return refused(rep, Refusal::Truncated, "NPC " + std::to_string(n) + " " + sc.name);
    }

    sanitize_refs(*npc, rep);

    // The ledger goes through its own restore(): the engine's clock, never the saved one.
    r.u32(); r.u32();   // saved day and life-year: informative only
    const std::uint32_t ne = r.u32();
    if (r.bad() || ne > r.left() / 24) return refused(rep, Refusal::Truncated, "NPCS ledger");
    std::vector<LedgerEntry> entries;
    for (std::uint32_t i = 0; i < ne; ++i) {
      LedgerEntry e;
      e.target = r.u32();
      const std::uint32_t var = r.u32();
      e.day_stamp = std::int32_t(r.u32());
      e.year_stamp = std::int32_t(r.u32());
      e.day_moved = std::int32_t(r.u32());
      e.year_moved = std::int32_t(r.u32());
      if (r.bad()) break;
      if (var >= cx.var_map.size() || cx.var_map[var] == kNone) { ++rep.dropped_ledger_entries; continue; }
      e.var = std::uint16_t(cx.var_map[var]);
      entries.push_back(e);
    }
    const std::uint32_t mm = r.u32();
    if (r.bad() || mm > r.left()) return refused(rep, Refusal::Truncated, "NPCS mental map");
    auto mmb = r.bytes(mm);
    npc->mental_map.assign(mmb.begin(), mmb.end());
    if (!npc->ledger.restore(now_day, now_life_year, entries)) ++rep.ledger_rejected;
    loaded.push_back(std::move(npc));
  }
  if (r.bad()) return refused(rep, Refusal::Truncated, "NPCS");
  if (r.left() != 0) return refused(rep, Refusal::Malformed, "NPCS trailing bytes");
  rep.npcs = loaded.size();
  rep.ok = true;
  out = std::move(loaded);
  return rep;
}

}  // namespace em::social
