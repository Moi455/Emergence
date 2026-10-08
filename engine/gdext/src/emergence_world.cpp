#include "emergence_world.h"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdlib>
#include <cstring>

#include <godot_cpp/classes/image.hpp>
#include <godot_cpp/classes/mesh.hpp>
#include <godot_cpp/core/class_db.hpp>
#include <godot_cpp/variant/aabb.hpp>
#include <godot_cpp/variant/packed_byte_array.hpp>
#include <godot_cpp/variant/packed_color_array.hpp>
#include <godot_cpp/variant/packed_int32_array.hpp>
#include <godot_cpp/variant/packed_vector3_array.hpp>

#include "emergence/base/fingerprint.h"
#include "emergence/base/fixed.h"
#include "emergence/base/hash.h"
#include "emergence/base/timer.h"
#include "emergence/world/materials.h"

namespace em_godot {

using godot::ClassDB;
using godot::D_METHOD;

namespace {

constexpr double kVoxelM = 0.02;
constexpr int kTexW = 2048;  // texels per row of a quad texture (1024 quads)

// Corners of a quad in chunk-local voxel units, in the order (0,0), (w,0),
// (w,h), (0,h) of its (u, v) axes, and its outward normal (map axes).
void quad_corners(const em::Quad& q, double c[4][3], int n[3]) {
  double px = q.x(), py = q.y(), pz = q.z(), w = q.w(), h = q.h();
  n[0] = n[1] = n[2] = 0;
  switch (q.dir()) {
    case em::FaceDir::PosX: case em::FaceDir::NegX: {
      double fx = q.dir() == em::FaceDir::PosX ? px + 1 : px;
      double cc[4][3] = {{fx, py, pz}, {fx, py, pz + w}, {fx, py + h, pz + w}, {fx, py + h, pz}};
      std::memcpy(c, cc, sizeof cc);
      n[0] = q.dir() == em::FaceDir::PosX ? 1 : -1;
      break;
    }
    case em::FaceDir::PosY: case em::FaceDir::NegY: {
      double fy = q.dir() == em::FaceDir::PosY ? py + 1 : py;
      double cc[4][3] = {{px, fy, pz}, {px + w, fy, pz}, {px + w, fy, pz + h}, {px, fy, pz + h}};
      std::memcpy(c, cc, sizeof cc);
      n[1] = q.dir() == em::FaceDir::PosY ? 1 : -1;
      break;
    }
    default: {
      double fz = q.dir() == em::FaceDir::PosZ ? pz + 1 : pz;
      double cc[4][3] = {{px, py, fz}, {px + w, py, fz}, {px + w, py + h, fz}, {px, py + h, fz}};
      std::memcpy(c, cc, sizeof cc);
      n[2] = q.dir() == em::FaceDir::PosZ ? 1 : -1;
      break;
    }
  }
}

godot::String region_key(const em::RegionKey& k) {
  return godot::String::num_int64(k.lod) + ":" + godot::String::num_int64(k.x) + ":" + godot::String::num_int64(k.y) +
         ":" + godot::String::num_int64(k.z);
}

}  // namespace

EmergenceWorld::~EmergenceWorld() { stop_streaming(); }

godot::Dictionary EmergenceWorld::generate(int64_t seed, int64_t size_m) {
  stop_streaming();
  em::WorldParams p = size_m == 20000 ? em::WorldParams{} : em::WorldParams::scaled(0, static_cast<int32_t>(size_m));
  p.seed = static_cast<uint64_t>(seed);
  streamer_.reset();
  cache_.reset();
  source_.reset();
  gen_.reset();
  collision_.clear();
  em::Timer t;
  plan_ = std::make_unique<em::WorldPlan>(em::generate_world_plan(p));
  double plan_ms = t.ms();
  gen_ = std::make_unique<em::wg::WorldGen>(*plan_);
  source_ = std::make_unique<em::WorldGenSource>(*gen_);
  cache_ = std::make_unique<em::ChunkCache>(*source_);
  godot::Dictionary d;
  d["plan_ms"] = plan_ms;
  d["total_ms"] = t.ms();
  d["fingerprint"] = fingerprint();
  godot::Array sites;
  for (const auto& s : plan_->settlements) {
    godot::Dictionary site;
    site["id"] = godot::String(em::settlement_id(s.kind));
    site["kind"] = godot::String(em::settlement_name(s.kind));
    site["x_m"] = static_cast<double>(s.i * plan_->cell_mm) / 1000.0;
    site["z_m"] = static_cast<double>(s.j * plan_->cell_mm) / 1000.0;
    site["height_m"] = static_cast<double>(s.height_mm) / 1000.0;
    sites.push_back(site);
  }
  d["settlements"] = sites;
  return d;
}

godot::String EmergenceWorld::fingerprint() const {
  return plan_ ? godot::String(em::to_hex(plan_->fingerprint()).c_str()) : godot::String();
}

void EmergenceWorld::set_anchor(double x_m, double z_m) {
  anchor_x_ = x_m;
  anchor_z_ = z_m;
}

godot::Vector3 EmergenceWorld::to_godot(double x_m, double y_m, double z_m) const {
  return godot::Vector3(static_cast<float>(x_m - anchor_x_), static_cast<float>(y_m), static_cast<float>(-(z_m - anchor_z_)));
}

godot::Vector3 EmergenceWorld::to_map(const godot::Vector3& p) const {
  return godot::Vector3(static_cast<float>(p.x + anchor_x_), p.y, static_cast<float>(-p.z + anchor_z_));
}

void EmergenceWorld::voxel_of(const godot::Vector3& p, int64_t& vx, int64_t& vy, int64_t& vz) const {
  vx = static_cast<int64_t>(std::floor((p.x + anchor_x_) / kVoxelM));
  vy = static_cast<int64_t>(std::floor(p.y / kVoxelM));
  vz = static_cast<int64_t>(std::floor((-p.z + anchor_z_) / kVoxelM));
}

double EmergenceWorld::ground_height(const godot::Vector3& p) const {
  if (!source_) return 0.0;
  int64_t vx, vy, vz;
  voxel_of(p, vx, vy, vz);
  return static_cast<double>(source_->ground_voxel_y(vx, vz)) * kVoxelM;
}

double EmergenceWorld::surface_height_m(double x_m, double z_m) const {
  if (!source_) return 0.0;
  return static_cast<double>(source_->ground_voxel_y(static_cast<int64_t>(x_m * 50.0), static_cast<int64_t>(z_m * 50.0))) * kVoxelM;
}

// ---------------------------------------------------------------- streaming

void EmergenceWorld::start_streaming(const godot::Dictionary& params) {
  if (!cache_) return;
  stop_streaming();
  em::StreamerParams sp;
  if (params.has("lods")) sp.lods = static_cast<int>(static_cast<int64_t>(params["lods"]));
  if (params.has("half")) sp.half = static_cast<int>(static_cast<int64_t>(params["half"]));
  if (params.has("ao_max_lod")) sp.ao_max_lod = static_cast<int>(static_cast<int64_t>(params["ao_max_lod"]));
  streamer_ = std::make_unique<em::TerrainStreamer>(*cache_, sp);
  running_ = true;
  worker_ = std::thread([this] { worker_loop(); });
}

void EmergenceWorld::stop_streaming() {
  if (!worker_.joinable()) return;
  {
    std::lock_guard<std::mutex> lock(mutex_);
    running_ = false;
  }
  wake_.notify_all();
  worker_.join();
}

void EmergenceWorld::set_view(const godot::Vector3& p) {
  int64_t vx, vy, vz;
  voxel_of(p, vx, vy, vz);
  {
    std::lock_guard<std::mutex> lock(mutex_);
    if (vx == view_x_ && vz == view_z_ && streamer_ && streamer_->totals().regions > 0) return;
    view_x_ = vx;
    view_z_ = vz;
    view_dirty_ = true;
  }
  wake_.notify_all();
}

void EmergenceWorld::worker_loop() {
  std::unique_lock<std::mutex> lock(mutex_);
  int64_t applied_x = INT64_MIN, applied_z = INT64_MIN;
  while (running_) {
    if (view_dirty_) {
      view_dirty_ = false;
      // Re-plan only when the viewer changed lod-0 chunk: cheaper and enough.
      if (em::floor_div(view_x_, em::kChunkSize) != em::floor_div(applied_x, em::kChunkSize) ||
          em::floor_div(view_z_, em::kChunkSize) != em::floor_div(applied_z, em::kChunkSize)) {
        streamer_->set_view(view_x_, view_z_);
        applied_x = view_x_;
        applied_z = view_z_;
      }
    }
    if (streamer_->pending() == 0) {
      wake_.wait(lock, [this] { return !running_ || view_dirty_ || streamer_->pending() > 0; });
      continue;
    }
    std::vector<em::RegionUpdate> out;
    streamer_->update(0.0, out);  // one batch, then let edits and views in
    if (!out.empty()) {
      std::lock_guard<std::mutex> r(ready_mutex_);
      for (auto& u : out) ready_.push_back(std::move(u));
    }
    lock.unlock();
    std::this_thread::yield();
    lock.lock();
  }
}

godot::Array EmergenceWorld::poll_regions(int64_t max_regions) {
  std::vector<em::RegionUpdate> take;
  {
    std::lock_guard<std::mutex> r(ready_mutex_);
    while (!ready_.empty() && static_cast<int64_t>(take.size()) < max_regions) {
      take.push_back(std::move(ready_.front()));
      ready_.pop_front();
    }
  }
  godot::Array result;
  for (auto& u : take) {
    godot::Dictionary d;
    d["key"] = region_key(u.key);
    d["lod"] = u.key.lod;
    d["removed"] = u.removed;
    const double cell = kVoxelM * static_cast<double>(1 << u.key.lod);
    const double size = cell * em::kChunkSize * em::TerrainStreamer::kRegionChunks;
    d["cell"] = cell;
    d["size"] = size;
    // Map min corner of the region; its Godot position is the corner with
    // the largest map z (Godot z is flipped), so the shader adds -z.
    double x0 = static_cast<double>(u.key.x) * size, y0 = static_cast<double>(u.key.y) * size,
           z0 = static_cast<double>(u.key.z) * size;
    d["origin"] = to_godot(x0, y0, z0);
    d["quad_count"] = static_cast<int64_t>(u.quads.size());
    if (!u.removed && !u.quads.empty()) {
      const int64_t texels = static_cast<int64_t>(u.quads.size()) * 2;
      const int64_t rows = (texels + kTexW - 1) / kTexW;
      godot::PackedByteArray bytes;
      bytes.resize(rows * kTexW * 4);
      uint8_t* w = bytes.ptrw();
      std::memset(w, 0, static_cast<size_t>(bytes.size()));
      for (size_t i = 0; i < u.quads.size(); ++i) {
        uint64_t b = u.quads[i].bits;
        for (int k = 0; k < 8; ++k) w[i * 8 + static_cast<size_t>(k)] = static_cast<uint8_t>((b >> (8 * k)) & 255);
      }
      godot::Ref<godot::Image> img =
          godot::Image::create_from_data(kTexW, static_cast<int32_t>(rows), false, godot::Image::FORMAT_RGBA8, bytes);
      d["quads"] = godot::ImageTexture::create_from_image(img);
    }
    result.push_back(d);
  }
  return result;
}

godot::Dictionary EmergenceWorld::streaming_stats() const {
  godot::Dictionary d;
  std::lock_guard<std::mutex> lock(mutex_);
  if (!streamer_) return d;
  em::StreamerStats s = streamer_->totals();
  d["pending"] = static_cast<int64_t>(streamer_->pending());
  d["regions_sent"] = static_cast<int64_t>(s.regions);
  d["chunks_generated"] = static_cast<int64_t>(s.chunks_generated);
  d["chunks_meshed"] = static_cast<int64_t>(s.chunks_meshed);
  d["busy_ms"] = s.ms;
  d["cache_mb"] = static_cast<double>(cache_->memory_bytes()) / 1048576.0;
  return d;
}

godot::Ref<godot::ArrayMesh> EmergenceWorld::quad_index_mesh(int64_t quads) {
  godot::Ref<godot::ArrayMesh> mesh;
  mesh.instantiate();
  godot::PackedVector3Array verts;
  godot::PackedInt32Array idx;
  verts.resize(quads * 4);
  idx.resize(quads * 6);
  godot::Vector3* v = verts.ptrw();
  int32_t* ix = idx.ptrw();
  for (int64_t q = 0; q < quads; ++q) {
    for (int k = 0; k < 4; ++k) v[q * 4 + k] = godot::Vector3(static_cast<float>(q * 4 + k), 0, 0);
    const int32_t b = static_cast<int32_t>(q * 4);
    const int32_t t[6] = {0, 1, 2, 0, 2, 3};
    for (int k = 0; k < 6; ++k) ix[q * 6 + k] = b + t[k];
  }
  godot::Array arrays;
  arrays.resize(godot::Mesh::ARRAY_MAX);
  arrays[godot::Mesh::ARRAY_VERTEX] = verts;
  arrays[godot::Mesh::ARRAY_INDEX] = idx;
  mesh->add_surface_from_arrays(godot::Mesh::PRIMITIVE_TRIANGLES, arrays);
  return mesh;
}

godot::Ref<godot::ImageTexture> EmergenceWorld::material_palette() {
  const em::MaterialTable& mats = em::MaterialTable::builtin();
  godot::PackedByteArray bytes;
  bytes.resize(64 * 8 * 4);
  uint8_t* w = bytes.ptrw();
  for (int c = 0; c < 512; ++c) {
    uint32_t rgb = mats.has(static_cast<em::MaterialClass>(c)) ? mats.get(static_cast<em::MaterialClass>(c)).color : 0xff00ffu;
    w[c * 4] = static_cast<uint8_t>((rgb >> 16) & 255);
    w[c * 4 + 1] = static_cast<uint8_t>((rgb >> 8) & 255);
    w[c * 4 + 2] = static_cast<uint8_t>(rgb & 255);
    w[c * 4 + 3] = 255;
  }
  return godot::ImageTexture::create_from_image(godot::Image::create_from_data(64, 8, false, godot::Image::FORMAT_RGBA8, bytes));
}

// -------------------------------------------------------------------- edits

int64_t EmergenceWorld::edit(const godot::Vector3& p, double radius_m, em::VoxelId v) {
  if (!cache_) return 0;
  int64_t vx, vy, vz;
  voxel_of(p, vx, vy, vz);
  int64_t r = std::max<int64_t>(1, static_cast<int64_t>(std::llround(radius_m / kVoxelM)));
  std::lock_guard<std::mutex> lock(mutex_);
  auto changed = cache_->edit_sphere(vx, vy, vz, r, v);
  for (const auto& c : changed)
    for (int dz = -1; dz <= 1; ++dz)
      for (int dy = -1; dy <= 1; ++dy)
        for (int dx = -1; dx <= 1; ++dx) collision_.erase(em::LodChunk{0, c.x + dx, c.y + dy, c.z + dz});
  if (streamer_) streamer_->mark_edited(changed);
  wake_.notify_all();
  return static_cast<int64_t>(changed.size());
}

int64_t EmergenceWorld::dig(const godot::Vector3& p, double radius_m) { return edit(p, radius_m, em::kAir); }

int64_t EmergenceWorld::place(const godot::Vector3& p, double radius_m, const godot::String& material) {
  const em::Material* m = em::MaterialTable::builtin().find(material.utf8().get_data());
  if (!m) return 0;
  return edit(p, radius_m, em::make_voxel(m->id));
}

godot::Dictionary EmergenceWorld::raycast(const godot::Vector3& from, const godot::Vector3& dir, double max_m) {
  godot::Dictionary d;
  d["hit"] = false;
  if (!cache_ || dir.length_squared() == 0) return d;
  // Amanatides & Woo on the 2 cm grid, in map voxel units.
  double ox = (from.x + anchor_x_) / kVoxelM, oy = from.y / kVoxelM, oz = (-from.z + anchor_z_) / kVoxelM;
  godot::Vector3 nd = dir.normalized();
  double dx = nd.x, dy = nd.y, dz = -nd.z;
  int64_t x = static_cast<int64_t>(std::floor(ox)), y = static_cast<int64_t>(std::floor(oy)), z = static_cast<int64_t>(std::floor(oz));
  int sx = dx > 0 ? 1 : -1, sy = dy > 0 ? 1 : -1, sz = dz > 0 ? 1 : -1;
  auto t_to = [](double o, double dd, int64_t c, int s) {
    if (dd == 0) return 1e300;
    double edge = static_cast<double>(s > 0 ? c + 1 : c);
    return (edge - o) / dd;
  };
  double tx = t_to(ox, dx, x, sx), ty = t_to(oy, dy, y, sy), tz = t_to(oz, dz, z, sz);
  double ddx = dx == 0 ? 1e300 : std::abs(1 / dx), ddy = dy == 0 ? 1e300 : std::abs(1 / dy), ddz = dz == 0 ? 1e300 : std::abs(1 / dz);
  const double max_t = max_m / kVoxelM;
  int nx = 0, ny = 0, nz = 0;
  double t = 0;
  std::lock_guard<std::mutex> lock(mutex_);
  while (t <= max_t) {
    em::VoxelId v = cache_->voxel(x, y, z);
    if (v != em::kAir) {
      d["hit"] = true;
      godot::Vector3 hp(static_cast<float>((ox + dx * t) * kVoxelM - anchor_x_), static_cast<float>((oy + dy * t) * kVoxelM),
                        static_cast<float>(-((oz + dz * t) * kVoxelM - anchor_z_)));
      d["position"] = hp;
      d["normal"] = godot::Vector3(static_cast<float>(nx), static_cast<float>(ny), static_cast<float>(-nz));
      d["material"] = godot::String(em::MaterialTable::builtin().get(em::voxel_class(v)).name.c_str());
      return d;
    }
    if (tx < ty && tx < tz) {
      x += sx;
      t = tx;
      tx += ddx;
      nx = -sx, ny = 0, nz = 0;
    } else if (ty < tz) {
      y += sy;
      t = ty;
      ty += ddy;
      nx = 0, ny = -sy, nz = 0;
    } else {
      z += sz;
      t = tz;
      tz += ddz;
      nx = 0, ny = 0, nz = -sz;
    }
  }
  return d;
}

godot::PackedVector3Array EmergenceWorld::collision_faces(const godot::Vector3& p, int64_t radius_chunks) {
  godot::PackedVector3Array tris;
  if (!cache_) return tris;
  int64_t vx, vy, vz;
  voxel_of(p, vx, vy, vz);
  const int64_t N = em::kChunkSize;
  int64_t cx = em::floor_div(vx, N), cy = em::floor_div(vy, N), cz = em::floor_div(vz, N);
  std::lock_guard<std::mutex> lock(mutex_);
  std::vector<em::LodChunk> want;
  for (int64_t y = cy - radius_chunks; y <= cy + radius_chunks; ++y)
    for (int64_t z = cz - radius_chunks; z <= cz + radius_chunks; ++z)
      for (int64_t x = cx - radius_chunks; x <= cx + radius_chunks; ++x)
        want.push_back({0, static_cast<int32_t>(x), static_cast<int32_t>(y), static_cast<int32_t>(z)});
  // Forget chunks far away.
  for (auto it = collision_.begin(); it != collision_.end();) {
    const auto& k = it->first;
    bool near = std::llabs(k.x - cx) <= radius_chunks + 4 && std::llabs(k.y - cy) <= radius_chunks + 4 &&
                std::llabs(k.z - cz) <= radius_chunks + 4;
    it = near ? std::next(it) : collision_.erase(it);
  }
  std::vector<em::LodChunk> todo, gen;
  for (const auto& k : want)
    if (!collision_.count(k)) {
      em::VoxelId u = em::kAir;
      if (!cache_->find(0, k.x, k.y, k.z) && !cache_->edited(k) &&
          source_->classify(0, {k.x, k.y, k.z}, &u) == em::SourceKind::Air) {
        collision_[k] = {};
        continue;
      }
      todo.push_back(k);
      for (int d = 0; d < 6; ++d) {
        static const int nb[6][3] = {{1, 0, 0}, {-1, 0, 0}, {0, 1, 0}, {0, -1, 0}, {0, 0, 1}, {0, 0, -1}};
        gen.push_back({0, k.x + nb[d][0], k.y + nb[d][1], k.z + nb[d][2]});
      }
      gen.push_back(k);
    }
  cache_->prefetch(gen);
  for (const auto& k : todo) {
    std::vector<em::Quad> quads;
    cache_->mesh(0, k.x, k.y, k.z, quads, 0, false);
    std::vector<float>& f = collision_[k];
    for (const em::Quad& q : quads) {
      double c[4][3];
      int n[3];
      quad_corners(q, c, n);
      const int order[6] = {0, 1, 2, 0, 2, 3};
      for (int i : order)
        for (int a = 0; a < 3; ++a) f.push_back(static_cast<float>(c[i][a]));
    }
  }
  for (const auto& k : want) {
    const std::vector<float>& f = collision_[k];
    const double bx = static_cast<double>(k.x) * N, by = static_cast<double>(k.y) * N, bz = static_cast<double>(k.z) * N;
    for (size_t i = 0; i + 2 < f.size(); i += 3)
      tris.push_back(godot::Vector3(static_cast<float>((bx + f[i]) * kVoxelM - anchor_x_),
                                    static_cast<float>((by + f[i + 1]) * kVoxelM),
                                    static_cast<float>(-((bz + f[i + 2]) * kVoxelM - anchor_z_))));
  }
  return tris;
}

// ------------------------------------------------------- debugging scene

godot::Ref<godot::ArrayMesh> EmergenceWorld::build_terrain_mesh(double x_m, double z_m, int64_t lod, int64_t inner,
                                                               int64_t outer) {
  godot::Ref<godot::ArrayMesh> mesh;
  mesh.instantiate();
  if (!cache_) return mesh;
  std::lock_guard<std::mutex> lock(mutex_);
  em::Timer timer;
  const em::MaterialTable& mats = em::MaterialTable::builtin();
  const int64_t size = int64_t{em::kChunkSize} << lod;
  const int64_t vx = static_cast<int64_t>(x_m * 50.0), vz = static_cast<int64_t>(z_m * 50.0);
  const int64_t ccx = vx / size, ccz = vz / size;
  const double base_y = static_cast<double>(source_->ground_voxel_y(vx, vz)) * kVoxelM;
  const double cell = kVoxelM * static_cast<double>(int64_t{1} << lod);

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
      if (mid_x >= source_->map_voxels() || mid_z >= source_->map_voxels()) continue;
      int64_t s = source_->ground_voxel_y(mid_x, mid_z);
      int64_t cy0 = em::floor_div(s, size);
      for (int64_t cy = cy0 - 3; cy <= cy0 + 3; ++cy) {
        em::VoxelId u = 0;
        if (source_->classify(static_cast<int>(lod), {static_cast<int32_t>(cx), static_cast<int32_t>(cy), static_cast<int32_t>(cz)}, &u) ==
            em::SourceKind::Air)
          continue;
        quads.clear();
        cache_->mesh(static_cast<int>(lod), static_cast<int>(cx), static_cast<int>(cy), static_cast<int>(cz), quads);
        if (quads.empty()) continue;
        ++chunk_count;
        quad_count += quads.size();
        const double ox = static_cast<double>(cx * size) * kVoxelM - x_m;
        const double oy = static_cast<double>(cy * size) * kVoxelM - base_y;
        const double oz = static_cast<double>(cz * size) * kVoxelM - z_m;
        for (const em::Quad& q : quads) {
          double c[4][3];
          int n3[3];
          quad_corners(q, c, n3);
          godot::Vector3 n(static_cast<float>(n3[0]), static_cast<float>(n3[1]), static_cast<float>(-n3[2]));
          uint32_t rgb = mats.get(q.cls()).color;
          godot::Color col(((rgb >> 16) & 255) / 255.0f, ((rgb >> 8) & 255) / 255.0f, (rgb & 255) / 255.0f);
          int32_t base = static_cast<int32_t>(verts.size());
          for (int v = 0; v < 4; ++v) {
            float a = 0.45f + 0.55f * static_cast<float>(q.ao(v == 0 ? 0 : v == 1 ? 1 : v == 2 ? 3 : 2)) / 3.0f;
            verts.push_back(godot::Vector3(static_cast<float>(ox + c[v][0] * cell), static_cast<float>(oy + c[v][1] * cell),
                                           static_cast<float>(-(oz + c[v][2] * cell))));
            normals.push_back(n);
            colors.push_back(col * a);
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
  ClassDB::bind_method(D_METHOD("generate", "seed", "size_m"), &EmergenceWorld::generate);
  ClassDB::bind_method(D_METHOD("fingerprint"), &EmergenceWorld::fingerprint);
  ClassDB::bind_method(D_METHOD("set_anchor", "x_m", "z_m"), &EmergenceWorld::set_anchor);
  ClassDB::bind_method(D_METHOD("to_godot", "x_m", "y_m", "z_m"), &EmergenceWorld::to_godot);
  ClassDB::bind_method(D_METHOD("to_map", "p"), &EmergenceWorld::to_map);
  ClassDB::bind_method(D_METHOD("ground_height", "p"), &EmergenceWorld::ground_height);
  ClassDB::bind_method(D_METHOD("start_streaming", "params"), &EmergenceWorld::start_streaming);
  ClassDB::bind_method(D_METHOD("stop_streaming"), &EmergenceWorld::stop_streaming);
  ClassDB::bind_method(D_METHOD("set_view", "p"), &EmergenceWorld::set_view);
  ClassDB::bind_method(D_METHOD("poll_regions", "max_regions"), &EmergenceWorld::poll_regions);
  ClassDB::bind_method(D_METHOD("streaming_stats"), &EmergenceWorld::streaming_stats);
  ClassDB::bind_static_method("EmergenceWorld", D_METHOD("quad_index_mesh", "quads"), &EmergenceWorld::quad_index_mesh);
  ClassDB::bind_static_method("EmergenceWorld", D_METHOD("material_palette"), &EmergenceWorld::material_palette);
  ClassDB::bind_method(D_METHOD("dig", "p", "radius_m"), &EmergenceWorld::dig);
  ClassDB::bind_method(D_METHOD("place", "p", "radius_m", "material"), &EmergenceWorld::place);
  ClassDB::bind_method(D_METHOD("raycast", "from", "dir", "max_m"), &EmergenceWorld::raycast);
  ClassDB::bind_method(D_METHOD("collision_faces", "p", "radius_chunks"), &EmergenceWorld::collision_faces);
  ClassDB::bind_method(D_METHOD("build_terrain_mesh", "x_m", "z_m", "lod", "inner", "outer"),
                       &EmergenceWorld::build_terrain_mesh);
  ClassDB::bind_method(D_METHOD("last_mesh_stats"), &EmergenceWorld::last_mesh_stats);
  ClassDB::bind_method(D_METHOD("surface_height_m", "x_m", "z_m"), &EmergenceWorld::surface_height_m);
}

}  // namespace em_godot
