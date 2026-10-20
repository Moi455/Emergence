//! Briques, chunks, sources et puits de voxels, empreintes (docs/19 § 2.2).
//!
//! Stockage creux : une brique 8³ uniforme n'alloue rien, une brique mixte porte une palette de 1 à 16
//! bits, un chunk 64³ est fait de 512 briques et n'en alloue la table qu'au premier écart. Tout est
//! déterministe : formes canoniques, empreintes FNV-1a sur l'ordre canonique des clés (`BTreeMap`,
//! jamais `HashMap`), aucune dépendance à l'ordre d'insertion ni au nombre de fils.

#![forbid(unsafe_code)]
#![deny(clippy::float_arithmetic)]

pub mod brick;
pub mod chunk;
pub mod composite;
pub mod error;
pub mod flat;
pub mod occupancy;
pub mod reduce;
pub mod region;
pub mod source;
pub mod sparse;
pub mod writer;

pub use brick::{BRICK_VOLUME, Brick};
pub use chunk::{CHUNK_BRICKS, CHUNK_VOLUME, Chunk, ChunkClass, ChunkHint};
pub use composite::{CompositeLayer, CompositeMode, CompositeSource};
pub use error::{ChunkError, CompositeError, DecodeError};
pub use flat::FlatSource;
pub use occupancy::OccupancyColumns;
pub use reduce::{ReduceRule, reduce_2x};
pub use region::{ChunkEdits, Region};
pub use source::{PutMode, VoxelSink, VoxelSource};
pub use sparse::SparseWorld;
pub use writer::ChunkWriter;
