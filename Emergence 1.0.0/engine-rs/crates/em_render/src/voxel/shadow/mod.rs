//! Ombres du soleil en cascades stables (L11, docs/19 § 5.3), remplies par traversée de la grille voxel.
//!
//! - [`ShadowParams`] : réglages validés ;
//! - [`SunBasis`] et [`CascadePlacement`] : géométrie et calage sur le réseau de texels (CPU, `f64`) ;
//! - [`ShadowPlanner`] : décide des tuiles à remplir (CPU) ;
//! - [`ShadowCascades`] : la passe GPU qui les remplit ; l'éclairage ([`crate::LightingPass`]) les échantillonne.

mod grid;
mod params;
mod pass;
mod planner;

pub use grid::{CRAN_PLAN_M, CascadePlacement, PLAN_M, SOLEIL_Y_MIN, SunBasis};
pub use params::{Regeneration, ShadowParams, TUILE};
pub use pass::{ShadowCascades, ShadowControl, noms};
pub use planner::{FramePlan, Generation, ShadowPlanner, TileJob};
