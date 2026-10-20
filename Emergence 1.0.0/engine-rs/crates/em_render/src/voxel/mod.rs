//! Rendu des voxels (L09, docs/19 § 4) : la grille de briques sur le GPU (`VoxelGpuWorld`), sa diffusion
//! (`ClipmapStreamer`), le tracé primaire en compute (`VoxelTracePass`), la matière continue en coordonnées monde
//! (`VoxelMaterialPass`), la fusion des profondeurs (`DepthMergePass`) et l'éclairage (`LightingPass`) et les ombres du soleil en cascades (`ShadowCascades`, L11).
//!
//! Responsabilités (docs/19 § 2.7, règle 6) : le streamer décide quoi charger, le monde possède la mémoire GPU,
//! les passes dessinent ; aucun ne fait le travail d'un autre.

pub mod alloc;
pub mod camera;
mod depth;
pub mod gbuffer;
pub mod gpu;
mod light;
mod material_pass;
pub mod materials;
pub mod pack;
pub mod shaders;
pub mod shadow;
mod streamer;
mod trace;
mod world;

pub use camera::{Projection, VoxelCamera};
pub use depth::DepthMergePass;
pub use gbuffer::noms;
pub use light::{DebugView, LightSettings, LightingPass};
pub use material_pass::VoxelMaterialPass;
pub use materials::{GpuMaterials, MaterialBindings};
pub use shadow::{Regeneration, ShadowCascades, ShadowControl, ShadowParams};
pub use streamer::{ClipmapStreamer, StreamReport};
pub use trace::VoxelTracePass;
pub use world::{ChunkFlags, ClipmapConfig, GpuWorldStats, UploadOutcome, VoxelGpuWorld, WorldBindings};
