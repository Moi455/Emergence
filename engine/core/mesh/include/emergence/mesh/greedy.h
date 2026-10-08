// Binary greedy meshing (roadmap M3, architecture_v1 § 4): faces of a 64^3
// chunk merged into rectangles of the same material class (tint is read by
// the shader from the brick, architecture § 3.2). Occupancy is handled as
// 64-bit columns, so face detection is a few bit operations per column.
#pragma once
#include <array>
#include <cstdint>
#include <vector>

#include "emergence/world/chunk.h"

namespace em {

enum class FaceDir : uint8_t { PosX = 0, NegX, PosY, NegY, PosZ, NegZ };

// One quad in 8 bytes, read directly by the vertex shader (vertex pulling):
// bits 0-5 x, 6-11 y, 12-17 z (chunk-local cell of the face origin),
// 18-23 w-1, 24-29 h-1 (extent along the two in-plane axes),
// 30-32 direction, 33-41 material class, 42-49 corner ambient occlusion
// (2 bits per corner, 3 = open: (u-, v-), (u+, v-), (u-, v+), (u+, v+)),
// 50-58 chunk inside its 8^3 render region (x + 8 z + 64 y, set by the
// streamer), 59-63 reserved.
// In-plane axes (u = w, v = h): X faces (z, y), Y faces (x, z), Z faces (x, y).
struct Quad {
  uint64_t bits = 0;

  static Quad make(int x, int y, int z, int w, int h, FaceDir d, MaterialClass cls, uint8_t ao = 0xFF);
  int x() const { return static_cast<int>(bits & 63); }
  int y() const { return static_cast<int>((bits >> 6) & 63); }
  int z() const { return static_cast<int>((bits >> 12) & 63); }
  int w() const { return static_cast<int>((bits >> 18) & 63) + 1; }
  int h() const { return static_cast<int>((bits >> 24) & 63) + 1; }
  FaceDir dir() const { return static_cast<FaceDir>((bits >> 30) & 7); }
  MaterialClass cls() const { return static_cast<MaterialClass>((bits >> 33) & 511); }
  int ao(int corner) const { return static_cast<int>((bits >> (42 + 2 * corner)) & 3); }
  int region_slot() const { return static_cast<int>((bits >> 50) & 511); }
  void set_region_slot(int slot) { bits = (bits & ~(uint64_t{511} << 50)) | static_cast<uint64_t>(slot & 511) << 50; }
};
static_assert(sizeof(Quad) == 8);

// Solidity of the voxel layer just outside each face of the chunk, as 64
// rows of 64 bits, in the same in-plane order as the quads of that face:
// X faces: row = y, bit = z; Y faces: row = z, bit = x; Z faces: row = y, bit = x.
// A set bit hides the chunk's face there. Default: all empty (faces kept).
struct ChunkBorders {
  std::array<std::array<uint64_t, 64>, 6> solid{};
};

// Opaque test per class; transparent classes (glass, leaves) are meshed
// separately later. For now every non-air class is opaque.
struct MeshStats {
  size_t faces = 0;  // unit faces before merging
  size_t quads = 0;  // after merging
};

// Appends the quads of `chunk` (grouped by direction, in direction order) to out.
// With ambient_occlusion, faces only merge when their corner occlusion matches
// (about twice as many quads on rough ground); without, every corner is open.
// Occlusion across the chunk's edges and corners (not faces) counts as open.
MeshStats mesh_chunk(const Chunk& chunk, const ChunkBorders& borders, std::vector<Quad>& out,
                     bool ambient_occlusion = true);

// Border layer of `neighbor` that faces `chunk` across direction d of chunk.
void border_from_neighbor(const Chunk& neighbor, FaceDir d, std::array<uint64_t, 64>& out);

// Level of detail: a chunk whose cells are 2x2x2 blocks of the 8 children
// (child index = cx + 2*cz + 4*cy). A cell is solid if at least 4 of its 8
// voxels are solid (keeps thin walls visible from one side while avoiding
// bloat), with the most frequent solid class. Missing children are air.
void downsample(const std::array<const Chunk*, 8>& children, Chunk& out);

}  // namespace em
