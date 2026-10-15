// ProcessEngine (T18, docs/14 section 4.5): applies the PROCESSES of the catalogue (matter.toml) as Operations. It is a
// pure reader of the EntityStore: it never changes the world, it returns Emissions that the caller submits to the
// OperationBus (submit_all), which applies them in its total order. Same contacts and same world give the same
// emissions whatever the threads; two contacts on the same thing in one batch: the first in the order of a hash of
// (tick, author, decision_seq) wins (fair: no author id is favoured), the other reports Outcome::Conflict.
//
// It judges nothing and chooses nothing: a contact either meets the physics of a process or it does not; whether the
// act is good, forbidden or wise is the business of the witnesses' models (D28), never computed here.
// Scope: entities (objects, structures, plants). Terrain voxels are the voxel world's: extract / till on terrain come
// back as a VoxelRequest in the report, no operation is emitted for them.
#pragma once
#include <memory>
#include <span>
#include <vector>

#include "contact_resolver.h"
#include "laws/collapse_law.h"
#include "laws/contact_laws.h"
#include "laws/law_kit.h"

namespace em::act {

class ProcessEngine {
 public:
  ProcessEngine(const MatterCatalog& catalog, const EntityStore& store, const GroundModel& ground);

  // One contact: offered to the laws in a fixed order, the first whose trigger the properties meet fires.
  // `emitted` shares the touched set across a batch (see on_contacts); use a fresh TouchedSet for a lone contact.
  LawReport on_contact(const Contact& c, std::uint64_t tick, TouchedSet& touched, std::vector<Emission>& out) const;

  // A batch: sorted by hash(tick, author, decision_seq) (then by content) and processed in that order, so the result does not depend on
  // the order in which the contacts were collected (threads). reports[i] answers contacts[i] (input order).
  std::vector<LawReport> on_contacts(std::span<const Contact> contacts, std::uint64_t tick, std::vector<Emission>& out) const;

  // The laws on the clock "real": margins, collapse, falls. Author = law of the world.
  TickReport tick_time(std::uint64_t tick, std::vector<Emission>& out) const;

  // Hands the emissions to the bus (any thread). Returns the number accepted.
  static std::size_t submit_all(ops::OperationBus& bus, std::span<const Emission> emissions);

  const ContactResolver& resolver() const { return resolver_; }
  // Every law of the engine, to check it against the table of the catalogue.
  std::vector<ProcessId> contact_processes() const;

 private:
  LawContext context(std::uint64_t tick) const { return {resolver_, catalog_, store_, vars_, tick}; }
  const MatterCatalog& catalog_;
  const EntityStore& store_;
  ContactResolver resolver_;
  LawVars vars_;
  std::vector<std::unique_ptr<ContactLaw>> laws_;
  CollapseLaw collapse_;
};

// FNV-1a 64 over the canonical encoding of the emissions (for determinism checks).
std::uint64_t fingerprint(std::span<const Emission> emissions);

}  // namespace em::act
