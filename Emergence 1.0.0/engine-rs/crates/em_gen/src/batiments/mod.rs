//! Les BÂTIMENTS paramétriques (L35) : des recettes à graine qui donnent un plan par parties, rastérisé fenêtre par
//! fenêtre (jamais de grille dense du bâtiment). `maison` est le port Rust du générateur de maison de Monsieur
//! (`générateurs de voxels/nouvelle référence.html`) ; `kit` est la trousse commune aux familles bâtiments, props et
//! rochers.

// Les recettes sont des PORTS fidèles de règles écrites en coordonnées entières : les bornes explicites
// (`a >= 5 && a < 10`) restent lisibles comme dans le générateur d'origine.
#![allow(
    clippy::manual_range_contains,
    clippy::too_many_arguments,
    clippy::needless_range_loop,
    clippy::collapsible_if,
    clippy::int_plus_one,
    clippy::identity_op
)]

pub mod catalogue;
pub mod ids;
pub mod kit;
pub mod maison;
pub mod registre;
pub mod village;

pub use catalogue::{AssetCatalogue, AssetRecipe};
pub use kit::matieres::Matieres;
pub use kit::plan::{Part, Placement, ShapePlan};
pub use kit::window::Window;
pub use maison::{HouseConfig, HouseGenerator, HouseModel};
pub use registre::registre_complet;
pub use village::{BuildingGenerator, VillageConfig};
