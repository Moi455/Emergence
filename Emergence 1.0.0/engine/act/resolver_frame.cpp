#include "resolver_frame.h"

namespace em::act {
namespace {

// Spawn { u32 expected, u16 kind, i32 x, y, z, u32 holder [, u16 sort] } and Move { u32 entity, i32 x, y, z, u32 holder }:
// the same payload with y and z swapped. Anything malformed is passed on untouched (the store refuses it as it would).
ops::Operation swapped(const ops::Operation& op) {
  if (op.op_kind() != ops::OpKind::Spawn && op.op_kind() != ops::OpKind::Move) return op;
  ops::PayloadReader r(op.payload);
  std::uint32_t id = 0, holder = 0;
  std::uint16_t kind = 0, sort = 0;
  std::int32_t x = 0, y = 0, z = 0;
  const bool spawn = op.op_kind() == ops::OpKind::Spawn;
  bool ok = r.u32(id);
  if (ok && spawn) ok = r.u16(kind);
  ok = ok && r.i32(x) && r.i32(y) && r.i32(z) && r.u32(holder);
  const bool has_sort = spawn && r.remaining() == 2;
  if (ok && has_sort) ok = r.u16(sort);
  if (!ok || r.remaining() != 0) return op;
  ops::Operation out = op;
  ops::PayloadWriter w;
  w.u32(id);
  if (spawn) w.u16(kind);
  w.i32(x).i32(z).i32(y).u32(holder);
  if (has_sort) w.u16(sort);
  out.payload = w.take();
  return out;
}

}  // namespace

ops::ApplyStatus ResolverFrame::apply(const ops::Operation& op) { return mirror_.apply(swapped(op)); }

Contact ResolverFrame::to_resolver(Contact c) {
  c.at = swap_yz(c.at);
  return c;
}

Emission ResolverFrame::to_world(Emission e) {
  e.op = swapped(e.op);
  return e;
}

std::vector<Contact> ResolverFrame::to_resolver(const std::vector<Contact>& cs) {
  std::vector<Contact> out;
  out.reserve(cs.size());
  for (const Contact& c : cs) out.push_back(to_resolver(c));
  return out;
}

std::vector<Emission> ResolverFrame::to_world(std::vector<Emission> es) {
  for (Emission& e : es) e = to_world(std::move(e));
  return es;
}

}  // namespace em::act
