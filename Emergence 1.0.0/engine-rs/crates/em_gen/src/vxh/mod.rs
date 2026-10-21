//! Chargeur `.vxh` (L34) : les maisons de Monsieur, cuites hors ligne par `tools/maisons/cuire.sh` depuis son
//! générateur JavaScript, lues ici avec la même rigueur que les `.vxm`.
//!
//! - `VxhModel` : une grille dense lue strictement (en-tête de 32 octets, zlib borné, invariants vérifiés) ;
//! - `HouseClasses` : matériau du générateur (1 pierre/métal, 2 bois, 3 plâtre, 4 végétal/sol, 5 toit) + teinte
//!   -> classe de matière du laboratoire (`cut_stone`, `iron`, `oak_raw`, `plaster`, `turf`, `dirt`, `slate`,
//!   `roof_tile`, bardeau, `glass`...), sans toucher à `materials.csv` ;
//! - `PlacedHouse` : la maison posée sur la grille monde, en `VoxelSource`. La COULEUR exacte du générateur
//!   (RGB565) reste lisible par position (`PlacedHouse::cell_at`) : un voxel de 16 bits ne porte que la classe et 7 bits
//!   de nuance, la teinte voulue par Monsieur est rendue par le colorieur du labo qui interroge la maison.

mod classes;
mod model;
mod placed;

pub use classes::HouseClasses;
pub use model::{VxhCell, VxhFlags, VxhMaterial, VxhModel};
pub use placed::PlacedHouse;
