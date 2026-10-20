//! Les recettes du bâti (L23p) : mur de pierre, poutre, poteau et toit de bardeaux, générés en voxels de 5 cm
//! par des `Generator` déterministes (graine -> voxels, aucun flottant, aucun `HashMap`).
//!
//! Le LOOK « pixel art vrai » vient d'ici : la recette POSE la variation de couleur entre voxels (numéro de pierre
//! par bloc, mortier d'un voxel, anneaux et nœuds du bois, ton de chaque tuile, mousse), dans les 7 bits de teinte.
//! Le mode de matière `VoxelPixel` d'`em_material` n'a plus qu'à la lire.
//!
//! - `classes` : les classes de matière utilisées (injectées dans chaque générateur) ;
//! - `grid` : la grille dense d'un plan et sa pyramide de niveaux de détail ;
//! - `draw` : un flux de tirages étiqueté, dérivé de la graine ;
//! - `wall`, `beam`, `post`, `roof` : les quatre générateurs et leurs configurations validées ;
//! - `placed` : un plan posé dans le monde, servi comme `VoxelSource` ;
//! - `registry` : le registre des générateurs par nom.

pub mod beam;
pub mod classes;
pub mod draw;
pub mod grid;
pub mod placed;
pub mod post;
pub mod registry;
pub mod roof;
pub mod wall;

pub use beam::{Axis, BeamConfig, BeamGenerator};
pub use classes::BuildingClasses;
pub use draw::Draw;
pub use grid::{DensePlan, PlanGrid};
pub use placed::PlacedPlan;
pub use post::{PostConfig, PostGenerator, PostShape};
pub use registry::GeneratorRegistry;
pub use roof::{RoofConfig, RoofGenerator};
pub use wall::{StoneWallConfig, StoneWallGenerator};
