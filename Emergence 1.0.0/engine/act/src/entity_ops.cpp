#include "emergence/act/entity_ops.h"

namespace em::act {
namespace {
ops::Operation base(ops::OpKind kind, std::uint64_t tick, std::uint32_t author) {
  ops::Operation op;
  op.tick = tick;
  op.author = author;
  op.kind = static_cast<std::uint16_t>(kind);
  op.flags = ops::kFlagEntities;
  return op;
}
}  // namespace

ops::Operation make_spawn(std::uint64_t tick, std::uint32_t author, std::uint16_t kind, const Position& pos_mm,
                          EntityId holder, std::uint16_t sort, EntityId expected) {
  ops::Operation op = base(ops::OpKind::Spawn, tick, author);
  ops::PayloadWriter w;
  w.u32(expected).u16(kind).i32(pos_mm[0]).i32(pos_mm[1]).i32(pos_mm[2]).u32(holder).u16(sort);
  op.payload = w.take();
  return op;
}

ops::Operation make_destroy(std::uint64_t tick, std::uint32_t author, EntityId entity) {
  ops::Operation op = base(ops::OpKind::Destroy, tick, author);
  op.payload = ops::PayloadWriter().u32(entity).take();
  return op;
}

ops::Operation make_move(std::uint64_t tick, std::uint32_t author, EntityId entity, const Position& to_mm, EntityId holder) {
  ops::Operation op = base(ops::OpKind::Move, tick, author);
  op.payload = ops::PayloadWriter().u32(entity).i32(to_mm[0]).i32(to_mm[1]).i32(to_mm[2]).u32(holder).take();
  return op;
}

ops::Operation make_delta(std::uint64_t tick, std::uint32_t author, EntityId entity, std::uint16_t var,
                          std::int32_t old_value, std::int32_t new_value) {
  ops::Operation op = base(ops::OpKind::EntityDelta, tick, author);
  op.payload = ops::PayloadWriter().u32(entity).u16(var).i32(old_value).i32(new_value).take();
  return op;
}

}  // namespace em::act
