// Godot-facing wrapper of the engine core. Godot never touches voxels
// directly: it asks the core and receives plain data (meshes, textures of
// quads, collision triangles).
//
// Coordinates: Godot positions are relative to an anchor on the map
// (floating origin, so float precision stays at the millimetre over 20 km):
// godot.x = x - anchor_x, godot.y = y, godot.z = -(z - anchor_z), in metres,
// with x east, z north, y up from sea level (docs/interfaces.md § 1).
#pragma once
#include <atomic>
#include <condition_variable>
#include <deque>
#include <map>
#include <memory>
#include <mutex>
#include <thread>
#include <vector>

#include <godot_cpp/classes/array_mesh.hpp>
#include <godot_cpp/classes/image_texture.hpp>
#include <godot_cpp/classes/ref_counted.hpp>
#include <godot_cpp/variant/array.hpp>
#include <godot_cpp/variant/dictionary.hpp>
#include <godot_cpp/variant/packed_vector3_array.hpp>
#include <godot_cpp/variant/vector3.hpp>

#include "emergence/mesh/chunk_cache.h"
#include "emergence/mesh/terrain_streamer.h"
#include "emergence/terrain/worldgen_source.h"
#include "emergence/world/world_plan.h"
#include "emergence/worldgen/worldgen.h"

namespace em_godot {

class EmergenceWorld : public godot::RefCounted {
  GDCLASS(EmergenceWorld, godot::RefCounted)

 public:
  ~EmergenceWorld() override;

  // Generates the world plan and the fine generator; returns timings,
  // fingerprint and settlements (id, kind, x_m, z_m, height_m).
  godot::Dictionary generate(int64_t seed, int64_t size_m);
  godot::String fingerprint() const;

  // Floating origin, in map metres.
  void set_anchor(double x_m, double z_m);
  godot::Vector3 to_godot(double x_m, double y_m, double z_m) const;
  godot::Vector3 to_map(const godot::Vector3& p) const;  // (x east, y up, z north) in metres

  // Ground height (metres above sea level) below a Godot position, before edits.
  double ground_height(const godot::Vector3& p) const;

  // LOD ring streaming on a worker thread. params: lods, half, ao_max_lod.
  void start_streaming(const godot::Dictionary& params);
  void stop_streaming();
  void set_view(const godot::Vector3& p);
  // Finished regions since the last call, at most max_regions. Each is a
  // Dictionary: key (String), lod, removed, quad_count, quads (ImageTexture,
  // RGBA8, 2 texels per quad, 2048 texels per row), origin (Vector3, Godot
  // position of the region's min corner), cell (voxel size in metres),
  // size (region edge in metres).
  godot::Array poll_regions(int64_t max_regions);
  godot::Dictionary streaming_stats() const;

  // Shared index mesh for the vertex-pulling shader: `quads` quads of 4
  // vertices whose x is the vertex number, 2 triangles each.
  static godot::Ref<godot::ArrayMesh> quad_index_mesh(int64_t quads);
  // Material colours, 64 x 8 texels (class = x + 64 y), sRGB.
  static godot::Ref<godot::ImageTexture> material_palette();

  // Player edits (lod 0). Every voxel whose centre is within radius_m of p
  // becomes air (dig) or `material` (place). Returns the chunks changed.
  int64_t dig(const godot::Vector3& p, double radius_m);
  int64_t place(const godot::Vector3& p, double radius_m, const godot::String& material);
  // First solid 2 cm voxel along a ray: {hit, position, normal, material}.
  godot::Dictionary raycast(const godot::Vector3& from, const godot::Vector3& dir, double max_m);
  // Triangles of the lod-0 surface (no occlusion) of the chunks within
  // radius_chunks of p, for a ConcavePolygonShape3D.
  godot::PackedVector3Array collision_faces(const godot::Vector3& p, int64_t radius_chunks);

  // One-shot greedy mesh of one LOD ring (vertex colours), kept for the
  // terrain_view debugging scene.
  godot::Ref<godot::ArrayMesh> build_terrain_mesh(double x_m, double z_m, int64_t lod, int64_t inner, int64_t outer);
  godot::Dictionary last_mesh_stats() const { return stats_; }
  double surface_height_m(double x_m, double z_m) const;

 protected:
  static void _bind_methods();

 private:
  void worker_loop();
  int64_t edit(const godot::Vector3& p, double radius_m, em::VoxelId v);
  void voxel_of(const godot::Vector3& p, int64_t& vx, int64_t& vy, int64_t& vz) const;

  std::unique_ptr<em::WorldPlan> plan_;
  std::unique_ptr<em::wg::WorldGen> gen_;
  std::unique_ptr<em::WorldGenSource> source_;
  std::unique_ptr<em::ChunkCache> cache_;
  std::unique_ptr<em::TerrainStreamer> streamer_;
  double anchor_x_ = 0, anchor_z_ = 0;

  // The worker runs streamer batches under mutex_; everything else that
  // touches cache_ or streamer_ takes it too.
  mutable std::mutex mutex_;
  std::condition_variable wake_;
  std::thread worker_;
  std::atomic<bool> running_{false};
  bool view_dirty_ = false;
  int64_t view_x_ = 0, view_z_ = 0;
  std::deque<em::RegionUpdate> ready_;
  std::mutex ready_mutex_;
  std::map<em::LodChunk, std::vector<float>> collision_;  // per lod-0 chunk, triangles in chunk-local voxels

  godot::Dictionary stats_;
};

}  // namespace em_godot
