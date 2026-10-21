//! `em_material` : la table des matières du laboratoire (docs/19 § 4.6, docs/19a § 5.3 et § 6.2).
//!
//! Deux côtés, séparés par la fonctionnalité Cargo `gpu` qu'active `em_render` :
//! - le côté « vérité » (toujours compilé, **sans flottant**, sans `HashMap`) : identifiants, noms, propriétés
//!   physiques et d'aspect en entiers/Q16, sens des 7 bits de teinte par classe, rampes, référence CPU de la
//!   couleur d'un voxel à sa position monde ;
//! - le côté `gpu` : le paquet de matières (`MaterialGpu`, 64 octets) et les tampons de rampes, où les flottants
//!   n'apparaissent qu'à la frontière GPU (docs/19 § 2.4).

#![forbid(unsafe_code)]
#![deny(clippy::float_arithmetic)]

pub mod color;
pub mod error;
pub mod eval;
pub mod noise;
pub mod pixel;
pub mod style;
pub mod surface;
pub mod table;
pub mod tint;
pub mod vegetation;

#[cfg(feature = "gpu")]
pub mod gpu;

pub use color::{LinearRgb, Ramp3, SrgbTable};
pub use error::MaterialError;
pub use eval::{EvalContext, MaterialEvaluator, VoxelSample, eval_albedo_cpu};
pub use noise::{Frequency, ValueNoise, WorldPoint};
pub use pixel::{
    DirectPixelRule, PixelInput, PixelRule, PixelTone, RUN_SHIFT, StonePixelRule, WoodPixelRule,
};
pub use style::{
    GRANULOMETRIE_DEFAUT, GRANULOMETRIE_MAX, MaterialMode, PixelOverride, PixelParams, StyleConfig,
    StyleSheet,
};
pub use surface::{SurfaceModel, SurfaceParams, SurfaceSample};
pub use table::{CLASS_COUNT, MaterialDef, MaterialFlags, MaterialTable, RenderProps};
pub use tint::{
    GrainAxis, RampSelect, Shade, ShadeInput, TintMode, TintRule, tint_stone, tint_vegetation, tint_wood,
    untint_vegetation, untint_wood,
};
pub use vegetation::{MAX_SPECIES, RampRole, VegetationRamps};

#[cfg(feature = "gpu")]
pub use gpu::{GpuMaterialPacket, MATERIAL_WGSL, MaterialGpu};
