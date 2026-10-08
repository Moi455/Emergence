// Godot-facing wrapper of the world generator. Godot never touches voxels
// directly: it asks the core and receives plain data.
#pragma once
#include <memory>

#include <godot_cpp/classes/array_mesh.hpp>
#include <godot_cpp/classes/ref_counted.hpp>
#include <godot_cpp/variant/dictionary.hpp>

#include "emergence/mesh/chunk_cache.h"
#include "emergence/world/chunk_gen.h"
#include "emergence/world/world_plan.h"

namespace em_godot {

class EmergenceWorld : public godot::RefCounted {
  GDCLASS(EmergenceWorld, godot::RefCounted)

 public:
  // Generates the world plan; returns timings, fingerprint and settlements.
  godot::Dictionary generate(int64_t seed, int64_t size_m);
  // Terrain surface height in metres at a world position (x east, z north).
  double surface_height_m(double x_m, double z_m) const;
  godot::String fingerprint() const;
  // Greedy-meshed terrain of one LOD ring around (x_m, z_m): chunks whose
  // horizontal index distance to the centre chunk is in [inner, outer).
  // Vertices are relative to (x_m, surface, z_m) in Godot axes (z flipped).
  godot::Ref<godot::ArrayMesh> build_terrain_mesh(double x_m, double z_m, int64_t lod, int64_t inner, int64_t outer);
  godot::Dictionary last_mesh_stats() const { return stats_; }

 protected:
  static void _bind_methods();

 private:
  std::unique_ptr<em::WorldPlan> plan_;
  std::unique_ptr<em::ChunkGenerator> gen_;
  std::unique_ptr<em::ChunkCache> cache_;
  godot::Dictionary stats_;
};

}  // namespace em_godot
