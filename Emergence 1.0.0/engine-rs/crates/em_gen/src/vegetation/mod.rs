//! Famille VÉGÉTATION des générateurs paramétriques (L30, L31, L32) : port Rust, entièrement entier, de
//! `tools/vegetation/voxel_tree.py` et `voxel_bush.py` (squelette, épaisseurs, amas de feuilles, couleurs par
//! rampe), plus les silhouettes lointaines et les recettes nommées.
//!
//! - `fx` : virgule fixe Q16 (unité = voxel de 5 cm), tirages, bruit de valeur ;
//! - `species` : les essences (`engine/data/species.toml`) ;
//! - `skeleton` : la croissance (trait `Architecture` : tronc ou touffe multi-tiges) ;
//! - `frame` : échelle, modèle des tuyaux, chicots, racines ;
//! - `blob`, `bark`, `topiary` : rastérisation par densité du feuillage, du bois et de la taille topiaire ;
//! - `plan` : le plan, rastérisable fenêtre par fenêtre à tout niveau ;
//! - `generators` : `TreeGenerator`, `BushGenerator`.

pub mod bark;
pub mod blob;
pub mod compose;
pub mod crops;
pub mod extra;
pub mod frame;
pub mod fx;
pub mod generators;
pub mod measure;
pub mod plan;
pub mod registre;
pub mod skeleton;
pub mod species;
pub mod topiary;

pub use compose::{CompositePlan, HedgeGenerator, HedgeParams};
pub use crops::{
    CropClasses, CropGenerator, CropKind, CropParams, CropPlan, FernGenerator, FernParams, MushroomGenerator,
    MushroomParams, SmallAsset,
};
pub use extra::{FallenLogGenerator, LogParams, StumpGenerator, StumpParams, TreeSilhouetteGenerator};
pub use generators::{BushGenerator, BushParams, TreeGenerator, TreeParams};
pub use plan::{PlanStats, PlantPlan, PlantRequest};
pub use registre::{register_default, scene_ramps};
pub use species::{Season, Species, SpeciesTable};
pub use topiary::TopiaryShape;
