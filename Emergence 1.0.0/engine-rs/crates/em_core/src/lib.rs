//! `em_core` : le noyau déterministe du laboratoire (docs/19 § 2.2).
//!
//! Entiers seulement : Q16 et ses fonctions, hachage et empreintes identiques au C++
//! (`engine/core/base`, `engine/ops`), coordonnées et clés, repères, identifiants,
//! lecture et écriture petit-boutistes. Aucune dépendance vers une autre crate du dépôt.

#![forbid(unsafe_code)]
#![deny(clippy::float_arithmetic)]

pub mod coords;
pub mod digest;
pub mod error;
pub mod frame;
pub mod hash;
pub mod ids;
pub mod io;
pub mod q16;

pub use coords::{
    BRICK_EDGE, CHUNK_EDGE, ChunkKey, Lod, REGION_CHUNKS_XZ, REGION_CHUNKS_Y, RegionKey, VOXEL_MM, VoxelBox,
    VoxelCoord, WORLD_BOTTOM_VOXEL, WORLD_SIZE_VOXELS, WORLD_TOP_VOXEL, brick_index, chunk_of, floor_div,
    region_of, voxel_index,
};
pub use digest::{Fnv64, crc32};
pub use error::CoreError;
pub use hash::{Layer, SplitMix64, hash_combine, hash2, hash3, layer_seed, mix64};
pub use ids::{EntityId, MaterialId, VoxelValue};
pub use io::{IoError, LeReader, LeWriter};
pub use q16::Q16;
