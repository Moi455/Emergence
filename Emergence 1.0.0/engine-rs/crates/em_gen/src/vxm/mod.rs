//! Chargeur `.vxm` v1 (docs/19a § 1) : le pont entre les générateurs Python validés et le moteur Rust.
//!
//! - `VxmModel` : un fichier lu strictement, six niveaux de détail, pivot au pied du tronc ;
//! - `PlacedModel` : le modèle posé sur la grille monde (pivot, quarts de tour, essence), en `VoxelSource` ;
//! - `VxmClasses` / `TintTable` : sorte + rampe -> classe de matière et 7 bits de teinte.

mod classes;
mod kind;
mod layer;
mod meta;
mod model;
mod parse;
mod placed;
mod ramps;
mod rotation;

pub use classes::{TintTable, VxmClasses};
pub use kind::VxmKind;
pub use layer::LodLayer;
pub use meta::VxmMeta;
pub use model::{LOD_COUNT, VxmModel, VxmPlan, VxmWarning};
pub use placed::PlacedModel;
pub use ramps::vegetation_ramps;
pub use rotation::QuarterTurns;
