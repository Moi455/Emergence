//! Générateurs paramétriques, chargeur .vxm, port Rust de voxel_tree et voxel_bush.
//!
//! - `generator` : les traits `Generator` et `GenPlan` (docs/19 § 2.5) ;
//! - `vxm` : le chargeur du format d'échange `.vxm` v1 et le modèle posé sur la grille monde (L08) ;
//! - `scene` : la scène statique minimale du labo (sol plat + modèles posés), qui donne ses chunks au rendu.

#![forbid(unsafe_code)]
#![deny(clippy::float_arithmetic)]

pub mod error;
pub mod generator;
pub mod scene;
pub mod vxm;

pub use error::{GenError, VxmError};
pub use generator::{GenParams, GenPlan, Generator, GeneratorId};
pub use scene::{StaticScene, StaticSceneBuilder};
pub use vxm::{
    PlacedModel, QuarterTurns, VxmClasses, VxmKind, VxmMeta, VxmModel, VxmWarning, vegetation_ramps,
};
