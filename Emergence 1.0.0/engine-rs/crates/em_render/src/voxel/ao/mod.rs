//! Occlusion ambiante tracée dans la grille voxel (L14, docs/19 § 5).
//!
//! - [`AmbientOcclusionParams`] : réglages validés, et fonctions CPU miroirs du WGSL (hachage, directions, poids) ;
//! - [`occlusion_cpu`] : référence CPU (DDA `f64`) que les essais GPU comparent ;
//! - [`AmbientOcclusionPass`] : la passe GPU (tracé des rayons puis filtre bilatéral) ; l'éclairage la lit.

mod params;
mod pass;
mod reference;

pub use params::{AmbientOcclusionParams, VOXEL_M, local_direction, position_hash};
pub use pass::{AmbientOcclusionPass, BruteAo, FORMAT_BRUTE, FORMAT_OCCLUSION, noms};
pub use reference::{SurfacePoint, occlusion_cpu};
