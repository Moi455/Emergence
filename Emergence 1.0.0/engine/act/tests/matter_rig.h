// Shared by test_matter_laws and bench_matter_laws: a world (store + bus), a catalogue and the engine.
#pragma once
#include <string_view>
#include <vector>

#include "emergence/act/entity_store.h"
#include "emergence/ops/operation_bus.h"
#include "process_engine.h"

namespace em::act::rig {

inline std::uint16_t form_of(std::string_view name) {
  for (std::size_t i = 0; i < matter::kForms.size(); ++i) if (matter::kForms[i].name == name) return static_cast<std::uint16_t>(i);
  return 0xFFFF;
}

struct World {
  EntityStore store;
  ops::OperationBus bus;
  MatterCatalog catalog;
  FlatGround ground;
  std::uint64_t tick = 0;
  World() { bus.add_applier(&store); }

  std::uint16_t item(std::string_view name) const { return catalog.find_item(name); }
  EntityId spawn(gen::EntityKind k, Position p, std::uint16_t sort) {
    EntityId id = store.next_id();
    bus.submit(make_spawn(++tick, 1, static_cast<std::uint16_t>(k), p, kNoEntity, sort));
    bus.flush();
    return store.alive(id) ? id : kNoEntity;
  }
  EntityId spawn_item(std::string_view name, Position p) { return spawn(gen::EntityKind::item, p, item(name)); }
  std::size_t count_sort(std::uint16_t sort) const {
    std::size_t n = 0;
    store.for_each([&](EntityId id, gen::EntityKind) { if (store.sort(id) == sort) ++n; });
    return n;
  }
  void submit_flush(const std::vector<Emission>& e) {
    ++tick;
    ProcessEngine::submit_all(bus, e);
    bus.flush();
  }
};

}  // namespace em::act::rig
