// All NPCs of the world, each with its generated state (components and record pools).
#pragma once
#include <cstddef>
#include <memory>
#include <vector>

#include "emergence/social/npc_state_gen.h"

namespace em::social {

class NpcStore {
 public:
  explicit NpcStore(std::size_t capacity) { npcs_.reserve(capacity); }
  std::size_t add() {
    npcs_.push_back(std::make_unique<gen::NpcState>());
    return npcs_.size() - 1;
  }
  gen::NpcState& operator[](std::size_t i) { return *npcs_[i]; }
  std::size_t size() const { return npcs_.size(); }
  static constexpr std::size_t bytes_per_npc() { return sizeof(gen::NpcState); }

 private:
  std::vector<std::unique_ptr<gen::NpcState>> npcs_;   // stable addresses
};

}  // namespace em::social
