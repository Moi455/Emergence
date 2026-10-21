//! Rendu par maillage raster (L33) : les chunks sont maillés par `em_mesh` (faces visibles, occlusion ambiante par
//! sommet baked, couleurs plates évaluées une fois), rastérisés avec une profondeur, éclairés dans le fragment
//! (soleil de l'atmosphère, ambiance de l'hémisphère du ciel, ombres en cascades RASTER de L11, spéculaire doux,
//! translucidité du feuillage par épaisseur cuite). Remplace le tracé compute comme base du rendu ; le tracé de L09 à
//! L14 reste disponible en option.
//!
//! - [`MeshWorld`] : les quads sur le GPU, partagés entre la scène et les passes ;
//! - [`MeshAmbientPass`] : l'ambiance du ciel des six faces (une texture 7 x 1 par image) ;
//! - [`MeshShadowPass`] : les cascades d'ombre rastérisées (placement stable de L11) ;
//! - [`MeshRenderer`] : la passe principale (couleur + profondeur + lumière).

mod ambient;
mod frustum;
mod renderer;
pub mod shaders;
mod shadow;
mod world;

pub use ambient::{AMBIANCE, MeshAmbientPass};
pub use frustum::Frustum;
pub use renderer::{MeshRenderer, noms as noms_rendu};
pub use shadow::{MeshShadowPass, boite_dans_fenetre, matrice_cascade, noms as noms_ombres};
pub use world::{ChunkBox, ChunkGpu, DrawChunk, MeshWorld, MeshWorldState, MeshWorldStats};
