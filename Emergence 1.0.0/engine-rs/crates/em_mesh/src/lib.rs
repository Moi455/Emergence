//! `em_mesh` (L33) : le maillage des chunks. Transforme un chunk 64³ en FACES VISIBLES seulement, avec
//! l'occlusion ambiante par sommet de la référence de Monsieur (`nouvelle référence.html`, fonction `meshify`), la
//! diagonale du quad choisie selon l'occlusion (pas d'anisotropie) et la fusion gloutonne là où couleur ET occlusion
//! sont constantes. Pur et déterministe : aucun GPU, aucun `HashMap`, même octets à chaque fois, quel que soit le
//! nombre de fils.
//!
//! - [`Quad`] : une face (12 octets), la brique de base que le GPU lit ; [`Quad::vertex`] en donne les quatre
//!   sommets (position, normale, couleur sRGB8, occlusion 2 bits, octet de paramètres de matière) ;
//! - [`ChunkMesher`] : un chunk (et son voisinage `PaddedChunk`) vers un [`ChunkMesh`] ;
//! - [`VoxelColorer`] / [`MaterialColorer`] : la couleur PLATE d'un voxel, évaluée par `em_material` (mode
//!   `VoxelPixel` compris) une seule fois par voxel visible, jamais par face ;
//! - [`WorldMesher`] : remplit une région depuis une `VoxelSource` (chaque chunk une seule fois) et la maille en
//!   parallèle ;
//! - [`FoliageBaker`] : épaisseur de feuillage le long du soleil, par face (translucidité sans tracé).

#![forbid(unsafe_code)]

mod appearance;
mod error;
mod foliage;
mod mesh;
mod mesher;
mod padded;
mod quad;
mod world;

pub use appearance::{MaterialColorer, VoxelAppearance, VoxelColorer};
pub use error::MeshError;
pub use foliage::{BLOCKED_CODE, FoliageBaker};
pub use mesh::ChunkMesh;
pub use mesher::{ChunkMesher, MesherConfig};
pub use padded::{PADDED_EDGE, PaddedChunk};
pub use quad::{AO_FACTOR, CHUNK_EDGE, Face, Quad, QuadSpec, Vertex};
pub use world::WorldMesher;
