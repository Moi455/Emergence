// The contact laws of matter 1 (T18): separate (cut, split, fracture, crush, carve, disassemble), take (extract, till),
// assemble (assemble, bind) and abrade. Each one is a ContactLaw: it fires when the properties of the contact meet the
// trigger of its process in catalogue/data/matter.toml, and it emits Operations. No law names a tool: they read
// cuts / impacts / digs / binds / sharpens, hardness, toughness, cohesion and mass.
#pragma once
#include <memory>
#include <vector>

#include "law_kit.h"

namespace em::act {

// The laws in the fixed order in which the engine offers a contact to them (specific before general).
std::vector<std::unique_ptr<ContactLaw>> make_contact_laws();

// Debris and elements: used by the contact laws and by the fall of a body (collapse).
// Destroys the body and spawns the pieces its fall or blow makes; returns the number of spawned entities.
std::uint32_t shatter(const LawContext& ctx, const Body& b, Emitter& out, ProcessId by);

}  // namespace em::act
