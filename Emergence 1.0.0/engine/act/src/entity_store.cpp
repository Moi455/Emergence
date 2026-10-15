#include "emergence/act/entity_store.h"

#include <cstring>
#include <utility>

#include "emergence/ops/digest.h"
#include "emergence/ops/operation.h"

namespace em::act {

using ops::ApplyStatus;
using ops::OpKind;
using ops::PayloadReader;

namespace {

constexpr std::uint32_t kMagic = 0x53544E45u;   // "ENTS"
constexpr std::size_t kKinds = static_cast<std::size_t>(EntityKind::kCount);

std::int64_t read_raw(const gen::FieldDesc& d, const std::uint8_t* base) {
  const std::uint8_t* p = base + d.offset;
  switch (d.type) {
    case gen::FieldType::Bool: case gen::FieldType::U8: return *p;
    case gen::FieldType::I16: { std::int16_t v; std::memcpy(&v, p, 2); return v; }
    case gen::FieldType::U16: { std::uint16_t v; std::memcpy(&v, p, 2); return v; }
    case gen::FieldType::I32: { std::int32_t v; std::memcpy(&v, p, 4); return v; }
    case gen::FieldType::U32: { std::uint32_t v; std::memcpy(&v, p, 4); return v; }
    case gen::FieldType::I64: { std::int64_t v; std::memcpy(&v, p, 8); return v; }
  }
  return 0;
}

void write_raw(const gen::FieldDesc& d, std::uint8_t* base, std::int64_t value) {
  std::uint8_t* p = base + d.offset;
  switch (d.type) {
    case gen::FieldType::Bool: *p = value ? 1 : 0; return;
    case gen::FieldType::U8: *p = static_cast<std::uint8_t>(value); return;
    case gen::FieldType::I16: { auto v = static_cast<std::int16_t>(value); std::memcpy(p, &v, 2); return; }
    case gen::FieldType::U16: { auto v = static_cast<std::uint16_t>(value); std::memcpy(p, &v, 2); return; }
    case gen::FieldType::I32: { auto v = static_cast<std::int32_t>(value); std::memcpy(p, &v, 4); return; }
    case gen::FieldType::U32: { auto v = static_cast<std::uint32_t>(value); std::memcpy(p, &v, 4); return; }
    case gen::FieldType::I64: std::memcpy(p, &value, 8); return;
  }
}

class Out {
 public:
  explicit Out(std::vector<std::uint8_t>& b) : b_(b) {}
  void u8(std::uint8_t v) { b_.push_back(v); }
  void le(std::uint64_t v, int bytes) { for (int i = 0; i < bytes; ++i) b_.push_back(std::uint8_t(v >> (8 * i))); }
 private:
  std::vector<std::uint8_t>& b_;
};

class In {
 public:
  explicit In(std::span<const std::uint8_t> b) : b_(b) {}
  bool le(std::uint64_t& v, int bytes) {
    if (b_.size() - pos_ < std::size_t(bytes)) return false;
    v = 0;
    for (int i = 0; i < bytes; ++i) v |= std::uint64_t(b_[pos_ + i]) << (8 * i);
    pos_ += bytes;
    return true;
  }
  bool done() const { return pos_ == b_.size(); }
  std::size_t remaining() const { return b_.size() - pos_; }
 private:
  std::span<const std::uint8_t> b_;
  std::size_t pos_ = 0;
};

const gen::FieldDesc* find_field(std::span<const gen::FieldDesc> fields, std::uint16_t var) {
  for (const auto& f : fields)
    if (f.var == var) return &f;
  return nullptr;
}

}  // namespace

const char* to_string(LoadStatus s) {
  switch (s) {
    case LoadStatus::Ok: return "ok";
    case LoadStatus::Truncated: return "truncated";
    case LoadStatus::BadMagic: return "bad magic";
    case LoadStatus::BadVersion: return "unsupported version";
    case LoadStatus::SchemaMismatch: return "schema mismatch";
    case LoadStatus::Corrupt: return "corrupt";
  }
  return "?";
}

const EntityStore::Slot* EntityStore::slot_of(EntityId id) const {
  const std::uint32_t idx = index_of(id);
  if (idx == 0 || idx > slots_.size()) return nullptr;
  const Slot& s = slots_[idx - 1];
  return (s.state == kAlive && s.generation == generation_of(id)) ? &s : nullptr;
}

EntityKind EntityStore::kind(EntityId id) const {
  const Slot* s = slot_of(id);
  return s ? static_cast<EntityKind>(s->kind) : EntityKind::kCount;
}
std::uint16_t EntityStore::sort(EntityId id) const { const Slot* s = slot_of(id); return s ? s->sort : 0; }
std::uint64_t EntityStore::created_tick(EntityId id) const { const Slot* s = slot_of(id); return s ? std::uint64_t(s->created_tick) : 0; }
Position EntityStore::position_mm(EntityId id) const { const Slot* s = slot_of(id); return s ? s->pos : Position{}; }
EntityId EntityStore::holder(EntityId id) const { const Slot* s = slot_of(id); return s ? s->holder : kNoEntity; }
std::uint32_t EntityStore::held_count(EntityId id) const { const Slot* s = slot_of(id); return s ? s->held : 0; }

EntityId EntityStore::next_id() const {
  if (!free_.empty()) return make_entity_id(free_.front() + 1, slots_[free_.front()].generation);
  if (slots_.size() >= kIndexMask) return kNoEntity;
  return make_entity_id(std::uint32_t(slots_.size() + 1), 0);
}

bool EntityStore::holder_ok(EntityId self, EntityId holder) const {
  if (holder == kNoEntity) return true;
  // Walk up the holder chain; it cannot be longer than the number of living entities unless it loops, and a loop
  // through `self` is exactly what a move under one's own descendant would create.
  EntityId cur = holder;
  for (std::size_t steps = 0; cur != kNoEntity; ++steps) {
    const Slot* s = slot_of(cur);
    if (!s || cur == self || steps > alive_ || !gen::kKindHasSpatial[s->kind]) return false;
    cur = s->holder;
  }
  return true;
}

bool EntityStore::read_var(EntityId id, std::uint16_t var, std::int64_t& value) const {
  const Slot* s = slot_of(id);
  if (!s) return false;
  bool ok = false;
  gen::dispatch(static_cast<EntityKind>(s->kind), tables_, [&](const auto& t) {
    const gen::FieldDesc* f = find_field(gen::kKindFields[s->kind], var);
    if (!f) return;
    value = read_raw(*f, reinterpret_cast<const std::uint8_t*>(&t.rows[s->row]));
    ok = true;
  });
  return ok;
}

// --- Applier -----------------------------------------------------------------------------------------------------
ApplyStatus EntityStore::apply(const ops::Operation& op) {
  switch (op.op_kind()) {
    case OpKind::Spawn: return do_spawn(op);
    case OpKind::Destroy: return do_destroy(op);
    case OpKind::Move: return do_move(op);
    case OpKind::EntityDelta: return do_delta(op);
    default: return ApplyStatus::Ignored;
  }
}

ApplyStatus EntityStore::do_spawn(const ops::Operation& op) {
  PayloadReader r(op.payload);
  std::uint32_t expected = 0, holder = 0;
  std::uint16_t kind = 0, sort = 0;
  std::int32_t x = 0, y = 0, z = 0;
  if (!(r.u32(expected) && r.u16(kind) && r.i32(x) && r.i32(y) && r.i32(z) && r.u32(holder))) return ApplyStatus::Rejected;
  if (r.remaining() == 2) { if (!r.u16(sort)) return ApplyStatus::Rejected; }
  if (r.remaining() != 0 || kind >= kKinds) return ApplyStatus::Rejected;
  const EntityId id = next_id();
  if (id == kNoEntity || (expected != kNoEntity && expected != id)) return ApplyStatus::Rejected;
  if (!holder_ok(kNoEntity, holder)) return ApplyStatus::Rejected;   // a new entity holds nothing: no cycle possible
  if (holder != kNoEntity && !gen::kKindHasSpatial[kind]) return ApplyStatus::Rejected;   // only a placed thing can be held
  const std::uint32_t slot_no = index_of(id) - 1;
  if (slot_no == slots_.size()) slots_.emplace_back(); else free_.pop_front();
  Slot& s = slots_[slot_no];
  s.created_tick = static_cast<std::int64_t>(op.tick);
  s.pos = {x, y, z};
  s.holder = holder;
  s.held = 0;
  s.kind = kind;
  s.sort = sort;
  s.state = kAlive;
  gen::dispatch(static_cast<EntityKind>(kind), tables_, [&](auto& t) {
    s.row = std::uint32_t(t.rows.size());
    t.rows.emplace_back();
    t.slot_of_row.push_back(slot_no);
  });
  if (holder != kNoEntity) ++slot_of(holder)->held;
  ++alive_;
  ++stats_.spawned;
  return ApplyStatus::Applied;
}

ApplyStatus EntityStore::do_destroy(const ops::Operation& op) {
  PayloadReader r(op.payload);
  std::uint32_t id = 0;
  if (!r.u32(id) || r.remaining() != 0) return ApplyStatus::Rejected;
  Slot* s = slot_of(id);
  if (!s || s->held != 0) return ApplyStatus::Rejected;   // what an entity holds must be moved or destroyed first
  const std::uint32_t slot_no = index_of(id) - 1;
  gen::dispatch(static_cast<EntityKind>(s->kind), tables_, [&](auto& t) {
    const std::uint32_t last = std::uint32_t(t.rows.size() - 1);
    if (s->row != last) {
      t.rows[s->row] = std::move(t.rows[last]);
      t.slot_of_row[s->row] = t.slot_of_row[last];
      slots_[t.slot_of_row[s->row]].row = s->row;
    }
    t.rows.pop_back();
    t.slot_of_row.pop_back();
  });
  if (s->holder != kNoEntity) --slot_of(s->holder)->held;
  s->holder = kNoEntity;
  s->pos = {};
  if (s->generation >= kMaxGeneration) {
    s->state = kRetired;   // the slot is never reused: no id can ever be ambiguous
  } else {
    ++s->generation;
    s->state = kFree;
    free_.push_back(slot_no);
  }
  --alive_;
  ++stats_.destroyed;
  return ApplyStatus::Applied;
}

ApplyStatus EntityStore::do_move(const ops::Operation& op) {
  PayloadReader r(op.payload);
  std::uint32_t id = 0, holder = 0;
  std::int32_t x = 0, y = 0, z = 0;
  if (!(r.u32(id) && r.i32(x) && r.i32(y) && r.i32(z) && r.u32(holder)) || r.remaining() != 0) return ApplyStatus::Rejected;
  Slot* s = slot_of(id);
  if (!s || !gen::kKindHasSpatial[s->kind] || !holder_ok(id, holder)) return ApplyStatus::Rejected;
  if (holder != s->holder) {
    if (s->holder != kNoEntity) --slot_of(s->holder)->held;
    if (holder != kNoEntity) ++slot_of(holder)->held;
    s->holder = holder;
  }
  s->pos = {x, y, z};
  ++stats_.moved;
  return ApplyStatus::Applied;
}

ApplyStatus EntityStore::do_delta(const ops::Operation& op) {
  PayloadReader r(op.payload);
  std::uint32_t id = 0;
  std::uint16_t var = 0;
  std::int32_t old_value = 0, new_value = 0;
  if (!(r.u32(id) && r.u16(var) && r.i32(old_value) && r.i32(new_value)) || r.remaining() != 0) return ApplyStatus::Rejected;
  Slot* s = slot_of(id);
  if (!s) return ApplyStatus::Rejected;
  const gen::FieldDesc* f = find_field(gen::kKindFields[s->kind], var);
  if (!f || !f->delta || new_value < f->lo || new_value > f->hi) return ApplyStatus::Rejected;
  bool ok = false;
  gen::dispatch(static_cast<EntityKind>(s->kind), tables_, [&](auto& t) {
    auto* base = reinterpret_cast<std::uint8_t*>(&t.rows[s->row]);
    if (read_raw(*f, base) != old_value) return;   // the writer saw another state: refused, the journal keeps it
    write_raw(*f, base, new_value);
    ok = true;
  });
  if (!ok) return ApplyStatus::Rejected;
  ++stats_.deltas;
  return ApplyStatus::Applied;
}

// --- save / load -------------------------------------------------------------------------------------------------
void EntityStore::serialize(std::vector<std::uint8_t>& bytes) const {
  Out o(bytes);
  o.le(kMagic, 4);
  o.le(kFormatVersion, 4);
  o.le(gen::kWorldSchemaFingerprint, 8);
  o.le(slots_.size(), 4);
  o.le(free_.size(), 4);
  for (std::uint32_t f : free_) o.le(f, 4);
  for (const Slot& s : slots_) {
    o.u8(s.state);
    o.le(s.generation, 2);
    if (s.state != kAlive) continue;
    o.le(s.kind, 2);
    o.le(s.sort, 2);
    o.le(std::uint64_t(s.created_tick), 8);
    for (int i = 0; i < 3; ++i) o.le(std::uint32_t(s.pos[i]), 4);
    o.le(s.holder, 4);
    gen::dispatch(static_cast<EntityKind>(s.kind), tables_, [&](const auto& t) {
      const auto* base = reinterpret_cast<const std::uint8_t*>(&t.rows[s.row]);
      for (const gen::FieldDesc& f : gen::kKindFields[s.kind]) o.le(std::uint64_t(read_raw(f, base)), f.size);
    });
  }
  o.le(ops::crc32(bytes), 4);   // over everything above
}

std::uint64_t EntityStore::fingerprint() const {
  std::vector<std::uint8_t> bytes;
  serialize(bytes);
  ops::Fnv64 h;
  h.add(bytes);
  return h.value();
}

LoadStatus EntityStore::load(std::span<const std::uint8_t> bytes) {
  In in(bytes);
  std::uint64_t magic = 0, version = 0, schema = 0, n_slots = 0, n_free = 0;
  if (!in.le(magic, 4)) return LoadStatus::Truncated;
  if (magic != kMagic) return LoadStatus::BadMagic;
  if (!in.le(version, 4) || !in.le(schema, 8) || !in.le(n_slots, 4) || !in.le(n_free, 4)) return LoadStatus::Truncated;
  if (version != kFormatVersion) return LoadStatus::BadVersion;
  if (schema != gen::kWorldSchemaFingerprint) return LoadStatus::SchemaMismatch;
  if (n_slots > kIndexMask || n_free > n_slots) return LoadStatus::Corrupt;
  // Bounds BEFORE any allocation: a slot takes at least 3 bytes, a free-list entry 4, and the CRC 4.
  if (n_slots * 3 + n_free * 4 + 4 > in.remaining()) return LoadStatus::Truncated;
  {
    std::uint64_t stored = 0;
    In tail(bytes.subspan(bytes.size() - 4));
    tail.le(stored, 4);
    if (stored != ops::crc32(bytes.first(bytes.size() - 4))) return LoadStatus::Corrupt;
    const std::size_t used = bytes.size() - in.remaining();
    bytes = bytes.first(bytes.size() - 4);   // the CRC is checked: parse the rest without it
    in = In(bytes.subspan(used));
  }

  EntityStore fresh;
  fresh.slots_.resize(n_slots);
  fresh.free_.resize(n_free);
  for (auto& f : fresh.free_) {
    std::uint64_t v = 0;
    if (!in.le(v, 4)) return LoadStatus::Truncated;
    if (v >= n_slots) return LoadStatus::Corrupt;
    f = std::uint32_t(v);
  }
  for (std::uint32_t i = 0; i < n_slots; ++i) {
    Slot& s = fresh.slots_[i];
    std::uint64_t st = 0, g = 0, k = 0, so = 0, tick = 0, p = 0, h = 0;
    if (!in.le(st, 1) || !in.le(g, 2)) return LoadStatus::Truncated;
    if (st > kRetired || g > kMaxGeneration) return LoadStatus::Corrupt;
    s.state = std::uint8_t(st);
    s.generation = std::uint16_t(g);
    if (st != kAlive) continue;
    if (!(in.le(k, 2) && in.le(so, 2) && in.le(tick, 8))) return LoadStatus::Truncated;
    if (k >= kKinds) return LoadStatus::Corrupt;
    s.kind = std::uint16_t(k);
    s.sort = std::uint16_t(so);
    s.created_tick = std::int64_t(tick);
    for (int c = 0; c < 3; ++c) {
      if (!in.le(p, 4)) return LoadStatus::Truncated;
      s.pos[c] = std::int32_t(std::uint32_t(p));
    }
    if (!in.le(h, 4)) return LoadStatus::Truncated;
    s.holder = EntityId(h);
    LoadStatus status = LoadStatus::Ok;
    gen::dispatch(static_cast<EntityKind>(k), fresh.tables_, [&](auto& t) {
      s.row = std::uint32_t(t.rows.size());
      t.rows.emplace_back();
      t.slot_of_row.push_back(i);
      auto* base = reinterpret_cast<std::uint8_t*>(&t.rows.back());
      for (const gen::FieldDesc& f : gen::kKindFields[k]) {
        std::uint64_t raw = 0;
        if (!in.le(raw, f.size)) { status = LoadStatus::Truncated; return; }
        std::int64_t v = raw;
        if (f.type == gen::FieldType::I16) v = std::int16_t(raw);
        else if (f.type == gen::FieldType::I32) v = std::int32_t(raw);
        else if (f.type == gen::FieldType::I64) v = std::int64_t(raw);
        if (v < f.lo || v > f.hi) { status = LoadStatus::Corrupt; return; }
        write_raw(f, base, v);
      }
    });
    if (status != LoadStatus::Ok) return status;
    ++fresh.alive_;
  }
  if (!in.done()) return LoadStatus::Corrupt;
  // free list: free slots only, each once; every free or retired slot is accounted for
  std::size_t n_free_slots = 0;
  for (const Slot& s : fresh.slots_) n_free_slots += s.state == kFree;
  if (n_free_slots != fresh.free_.size()) return LoadStatus::Corrupt;
  for (std::uint32_t f : fresh.free_) {
    if (fresh.slots_[f].state != kFree) return LoadStatus::Corrupt;
    fresh.slots_[f].state = kRetired;   // temporary mark: a repeated entry then fails the check above
  }
  for (std::uint32_t f : fresh.free_) {
    if (fresh.slots_[f].state != kRetired) return LoadStatus::Corrupt;
  }
  for (std::uint32_t f : fresh.free_) fresh.slots_[f].state = kFree;
  // Holders: alive, spatial, no cycle, whatever the depth. Linear: each chain is walked once (0 = unseen, 1 = on the
  // current walk, 2 = known to end on the ground).
  std::vector<std::uint8_t> mark(n_slots, 0);
  std::vector<std::uint32_t> walk;
  for (std::uint32_t i = 0; i < n_slots; ++i) {
    walk.clear();
    std::uint32_t cur = i;
    while (true) {
      const Slot& s = fresh.slots_[cur];
      if (s.state != kAlive || mark[cur] == 2) break;
      if (mark[cur] == 1) return LoadStatus::Corrupt;   // a loop
      mark[cur] = 1;
      walk.push_back(cur);
      if (s.holder == kNoEntity) break;
      const Slot* h = fresh.slot_of(s.holder);
      if (!h || !gen::kKindHasSpatial[h->kind] || !gen::kKindHasSpatial[s.kind]) return LoadStatus::Corrupt;
      cur = index_of(s.holder) - 1;
    }
    for (std::uint32_t w : walk) mark[w] = 2;
  }
  for (const Slot& s : fresh.slots_)
    if (s.state == kAlive && s.holder != kNoEntity) ++fresh.slot_of(s.holder)->held;
  *this = std::move(fresh);
  return LoadStatus::Ok;
}

std::size_t EntityStore::memory_bytes() const {
  std::size_t total = slots_.capacity() * sizeof(Slot) + free_.size() * sizeof(std::uint32_t);
  for (std::size_t k = 0; k < kKinds; ++k) {
    gen::dispatch(static_cast<EntityKind>(k), tables_, [&](const auto& t) {
      total += t.rows.capacity() * sizeof(typename std::decay_t<decltype(t.rows)>::value_type) +
               t.slot_of_row.capacity() * sizeof(std::uint32_t);
    });
  }
  return total;
}

}  // namespace em::act
