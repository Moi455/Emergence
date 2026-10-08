#include "emergence_world.h"

#include <algorithm>
#include <cstdlib>

#include <godot_cpp/core/class_db.hpp>
#include <godot_cpp/classes/mesh.hpp>
#include <godot_cpp/variant/array.hpp>
#include <godot_cpp/variant/packed_color_array.hpp>
#include <godot_cpp/variant/packed_int32_array.hpp>
#include <godot_cpp/variant/packed_vector3_array.hpp>

#include "emergence/base/fixed.h"
#include "emergence/base/hash.h"
#include "emergence/base/timer.h"

#include "emergence/base/fingerprint.h"
#include "emergence/world/materials.h"

namespace em_godot {

using godot::ClassDB;
using godot::D_METHOD;

godot::Dictionary EmergenceWorld::generate(int64_t seed, int64_t size_m) {
  em::WorldParams p = size_m == 20000 ? em::WorldParams{} : em::WorldParams::scaled(0, static_cast<int32_t>(size_m));
  p.seed = static_cast<uint64_t>(seed);
  cache_.reset();
  gen_.reset();
  plan_ = std::make_unique<em::WorldPlan>(em::generate_world_plan(p));
  gen_ = std::make_unique<em::ChunkGenerator>(*plan_, em::MaterialTable::builtin());
  cache_ = std::make_unique<em::ChunkCache>(*gen_);
  godot::Dictionary d;
  d["total_ms"] = plan_->timings.total_ms;
  d["fingerprint"] = fingerprint();
  godot::Array sites;
  for (const auto& s : plan_->settlements) {
    godot::Dictionary site;
    site["kind"] = godot::String(em::settlement_name(s.kind));
    site["x_m"] = static_cast<double>(s.i) * static_cast<double>(plan_->params.cell_m);
    site["z_m"] = static_cast<double>(s.j) * static_cast<double>(plan_->params.cell_m);
    site["height_m"] = static_cast<double>(s.height_mm) / 1000.0;
    sites.push_back(site);
  }
  d["settlements"] = sites;
  return d;
}

double EmergenceWorld::surface_height_m(double x_m, double z_m) const {
  if (!gen_) return 0.0;
  auto vx = static_cast<int64_t>(x_m * 50.0), vz = static_cast<int64_t>(z_m * 50.0);
  return static_cast<double>(gen_->surface_voxel_y(vx, vz)) * 0.02;
}

godot::String EmergenceWorld::fingerprint() const {
  return plan_ ? godot::String(em::to_hex(plan_->fingerprint()).c_str()) : godot::String();
}

godot::Ref<godot::ArrayMesh> EmergenceWorld::build_terrain_mesh(double x_m, double z_m, int64_t lod, int64_t inner,
                                                               int64_t outer) {
  godot::Ref<godot::ArrayMesh> mesh;
  mesh.instantiate();
  if (!gen_) return mesh;
  em::Timer timer;
  const em::MaterialTable& mats = em::MaterialTable::builtin();
  const int64_t size = int64_t{em::kChunkSize} << lod;  // chunk size in base voxels
  const int64_t vx = static_cast<int64_t>(x_m * 50.0), vz = static_cast<int64_t>(z_m * 50.0);
  const int64_t ccx = vx / size, ccz = vz / size;
  const double base_y = static_cast<double>(gen_->surface_voxel_y(vx, vz)) * 0.02;
  const double cell = 0.02 * static_cast<double>(int64_t{1} << lod);

  godot::PackedVector3Array verts, normals;
  godot::PackedColorArray colors;
  godot::PackedInt32Array indices;
  std::vector<em::Quad> quads;
  size_t chunk_count = 0, quad_count = 0;
  for (int64_t dz = -outer + 1; dz < outer; ++dz)
    for (int64_t dx = -outer + 1; dx < outer; ++dx) {
      if (std::max(std::llabs(dx), std::llabs(dz)) < inner) continue;
      int64_t cx = ccx + dx, cz = ccz + dz;
      if (cx < 0 || cz < 0) continue;
      int64_t mid_x = cx * size + size / 2, mid_z = cz * size + size / 2;
      if (mid_x >= gen_->map_voxels() || mid_z >= gen_->map_voxels()) continue;
      int64_t s = gen_->surface_voxel_y(mid_x, mid_z);
      int64_t cy0 = em::floor_div(s, size);
      for (int64_t cy = cy0 - 3; cy <= cy0 + 3; ++cy) {
        const em::Chunk& ch = cache_->get(static_cast<int>(lod), static_cast<int>(cx), static_cast<int>(cy), static_cast<int>(cz));
        em::VoxelId u = 0;
        if (ch.is_uniform(&u)) {
          // Uniform chunks only show faces against air neighbours; skip the
          // common cases (air, or solid with solid around) cheaply.
          if (u == em::kAir) continue;
        }
        quads.clear();
        cache_->mesh(static_cast<int>(lod), static_cast<int>(cx), static_cast<int>(cy), static_cast<int>(cz), quads);
        if (quads.empty()) continue;
        ++chunk_count;
        quad_count += quads.size();
        const double ox = static_cast<double>(cx * size) * 0.02 - x_m;
        const double oy = static_cast<double>(cy * size) * 0.02 - base_y;
        const double oz = static_cast<double>(cz * size) * 0.02 - z_m;
        for (const em::Quad& q : quads) {
          double px = q.x(), py = q.y(), pz = q.z(), w = q.w(), h = q.h();
          double c[4][3];
          godot::Vector3 n;
          switch (q.dir()) {
            case em::FaceDir::PosX: case em::FaceDir::NegX: {
              double fx = q.dir() == em::FaceDir::PosX ? px + 1 : px;
              double cc[4][3] = {{fx, py, pz}, {fx, py + h, pz}, {fx, py + h, pz + w}, {fx, py, pz + w}};
              std::copy(&cc[0][0], &cc[0][0] + 12, &c[0][0]);
              n = godot::Vector3(q.dir() == em::FaceDir::PosX ? 1 : -1, 0, 0);
              break;
            }
            case em::FaceDir::PosY: case em::FaceDir::NegY: {
              double fy = q.dir() == em::FaceDir::PosY ? py + 1 : py;
              double cc[4][3] = {{px, fy, pz}, {px + w, fy, pz}, {px + w, fy, pz + h}, {px, fy, pz + h}};
              std::copy(&cc[0][0], &cc[0][0] + 12, &c[0][0]);
              n = godot::Vector3(0, q.dir() == em::FaceDir::PosY ? 1 : -1, 0);
              break;
            }
            default: {
              double fz = q.dir() == em::FaceDir::PosZ ? pz + 1 : pz;
              double cc[4][3] = {{px, py, fz}, {px + w, py, fz}, {px + w, py + h, fz}, {px, py + h, fz}};
              std::copy(&cc[0][0], &cc[0][0] + 12, &c[0][0]);
              // World +z is north, Godot -z.
              n = godot::Vector3(0, 0, q.dir() == em::FaceDir::PosZ ? -1 : 1);
              break;
            }
          }
          uint32_t rgb = mats.get(q.cls()).color;
          uint64_t hsh = em::hash3(7, cx * 64 + q.x(), cy * 64 + q.y(), cz * 64 + q.z());
          float k = 0.97f + 0.03f * static_cast<float>(hsh & 1);
          godot::Color col(((rgb >> 16) & 255) / 255.0f * k, ((rgb >> 8) & 255) / 255.0f * k, (rgb & 255) / 255.0f * k);
          int32_t base = static_cast<int32_t>(verts.size());
          for (int v = 0; v < 4; ++v) {
            verts.push_back(godot::Vector3(static_cast<float>(ox + c[v][0] * cell), static_cast<float>(oy + c[v][1] * cell),
                                           static_cast<float>(-(oz + c[v][2] * cell))));
            normals.push_back(n);
            colors.push_back(col);
          }
          // Godot treats clockwise triangles as front faces: the geometric
          // normal (v1 - v0) x (v2 - v0) must point away from the face normal.
          godot::Vector3 v0 = verts[base], v1 = verts[base + 1], v2 = verts[base + 2];
          bool flip = (v1 - v0).cross(v2 - v0).dot(n) > 0;
          const int32_t tri_a[6] = {0, 1, 2, 0, 2, 3};
          const int32_t tri_b[6] = {0, 2, 1, 0, 3, 2};
          for (int32_t t : flip ? tri_b : tri_a) indices.push_back(base + t);
        }
      }
    }
  if (verts.size() > 0) {
    godot::Array arrays;
    arrays.resize(godot::Mesh::ARRAY_MAX);
    arrays[godot::Mesh::ARRAY_VERTEX] = verts;
    arrays[godot::Mesh::ARRAY_NORMAL] = normals;
    arrays[godot::Mesh::ARRAY_COLOR] = colors;
    arrays[godot::Mesh::ARRAY_INDEX] = indices;
    mesh->add_surface_from_arrays(godot::Mesh::PRIMITIVE_TRIANGLES, arrays);
  }
  stats_ = godot::Dictionary();
  stats_["chunks"] = static_cast<int64_t>(chunk_count);
  stats_["quads"] = static_cast<int64_t>(quad_count);
  stats_["ms"] = timer.ms();
  return mesh;
}

void EmergenceWorld::_bind_methods() {
  ClassDB::bind_method(D_METHOD("build_terrain_mesh", "x_m", "z_m", "lod", "inner", "outer"),
                       &EmergenceWorld::build_terrain_mesh);
  ClassDB::bind_method(D_METHOD("last_mesh_stats"), &EmergenceWorld::last_mesh_stats);
  ClassDB::bind_method(D_METHOD("generate", "seed", "size_m"), &EmergenceWorld::generate);
  ClassDB::bind_method(D_METHOD("surface_height_m", "x_m", "z_m"), &EmergenceWorld::surface_height_m);
  ClassDB::bind_method(D_METHOD("fingerprint"), &EmergenceWorld::fingerprint);
}

}  // namespace em_godot
