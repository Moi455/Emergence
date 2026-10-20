//! Lumière du feuillage (L10 étendue, docs/19 § 4 et § 5) : translucidité du soleil à travers les feuilles, liseré de
//! contre-jour, saturation et ombres colorées.
//!
//! - [`FoliageLightParams`] : réglages validés, et référence CPU de la translucidité ;
//! - [`FoliageThicknessPass`] : passe compute qui compte, pour chaque pixel de feuille, le feuillage traversé le long
//!   du soleil (grille de voxels, borné) ; l'éclairage ([`crate::LightingPass`]) la lit ([`noms`]).

mod params;
mod thickness;

pub use params::{FoliageLightParams, LeafLightSample};
pub use thickness::{FoliageThicknessPass, noms};
