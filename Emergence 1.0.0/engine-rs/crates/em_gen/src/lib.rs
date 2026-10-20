//! Générateurs paramétriques, chargeur .vxm, port Rust de voxel_tree et voxel_bush.
//!
//! - `generator` : les traits `Generator` et `GenPlan` (docs/19 § 2.5) ;
//! - `vxm` : le chargeur du format d'échange `.vxm` v1 et le modèle posé sur la grille monde (L08) ;
//! - `bati` : les recettes du mur de pierre, de la poutre, du poteau et du toit (L23p), posées comme `VoxelSource` ;
//! - `scene` : la scène statique minimale du labo (sol plat + modèles posés), qui donne ses chunks au rendu.

#![forbid(unsafe_code)]
#![deny(clippy::float_arithmetic)]

pub mod bati;
pub mod error;
pub mod generator;
pub mod scene;
pub mod vxm;

pub use bati::{
    Axis, BeamConfig, BeamGenerator, BuildingClasses, DensePlan, Draw, GeneratorRegistry, PlacedPlan,
    PlanGrid, PostConfig, PostGenerator, PostShape, RoofConfig, RoofGenerator, StoneWallConfig,
    StoneWallGenerator,
};
pub use error::{GenError, VxmError};
pub use generator::{GenParams, GenPlan, Generator, GeneratorId};
pub use scene::{StaticScene, StaticSceneBuilder};
pub use vxm::{
    PlacedModel, QuarterTurns, VxmClasses, VxmKind, VxmMeta, VxmModel, VxmWarning, vegetation_ramps,
};
