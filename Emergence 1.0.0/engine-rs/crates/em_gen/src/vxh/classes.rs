//! Matériau du générateur + teinte -> classe de matière du laboratoire (aucune modification de `materials.csv`).
//!
//! La classe donne les PROPRIÉTÉS (rugosité, relief, réflexion, humidité) ; la couleur voulue par Monsieur reste
//! celle du générateur et se lit par position (`PlacedHouse::cell_at`). Les 7 bits de teinte du voxel portent la
//! luminance de la couleur (0..127), une nuance de repli utile aux outils qui ne connaissent pas la maison.

use em_core::{MaterialId, VoxelValue};
use em_material::MaterialTable;

use super::model::{VxhCell, VxhMaterial};
use crate::error::GenError;

/// Les classes de matière qu'utilisent les maisons.
#[derive(Copy, Clone, Debug, PartialEq, Eq)]
pub struct HouseClasses {
    stone: MaterialId,
    iron: MaterialId,
    wood: MaterialId,
    plaster: MaterialId,
    turf: MaterialId,
    dirt: MaterialId,
    petal: MaterialId,
    slate: MaterialId,
    roof_tile: MaterialId,
    shingle: MaterialId,
    glass: MaterialId,
}

impl HouseClasses {
    /// Numéros du catalogue : `cut_stone` 20, `iron` 27, `oak_raw` 15, `plaster` 17, `turf` 1, `dirt` 2, `petal` 34,
    /// `slate` 11, `roof_tile` 18, `wood_trim_worn` 22 (bardeau de bois), `glass` 28. Un test les compare à la vraie table.
    pub const fn standard() -> Self {
        Self {
            stone: MaterialId::new(20),
            iron: MaterialId::new(27),
            wood: MaterialId::new(15),
            plaster: MaterialId::new(17),
            turf: MaterialId::new(1),
            dirt: MaterialId::new(2),
            petal: MaterialId::new(34),
            slate: MaterialId::new(11),
            roof_tile: MaterialId::new(18),
            shingle: MaterialId::new(22),
            glass: MaterialId::new(28),
        }
    }

    /// Cherche les classes par leur nom dans une table de matières.
    pub fn from_table(table: &MaterialTable) -> Result<Self, GenError> {
        let par_nom = |nom: &str| {
            table
                .by_name(nom)
                .ok_or_else(|| GenError::MatiereAbsente(nom.to_owned()))
        };
        Ok(Self {
            stone: par_nom("cut_stone")?,
            iron: par_nom("iron")?,
            wood: par_nom("oak_raw")?,
            plaster: par_nom("plaster")?,
            turf: par_nom("turf")?,
            dirt: par_nom("dirt")?,
            petal: par_nom("petal")?,
            slate: par_nom("slate")?,
            roof_tile: par_nom("roof_tile")?,
            shingle: par_nom("wood_trim_worn")?,
            glass: par_nom("glass")?,
        })
    }

    /// Classe de la cellule : matériau du générateur, affiné par la teinte (fer sombre et neutre, vert de l'herbe,
    /// ardoise froide, tuile rouge, bardeau brun).
    pub fn class_of(&self, cell: VxhCell) -> MaterialId {
        let [r, g, b] = cell.rgb8().map(i32::from);
        if cell.flags().glass() {
            return self.glass;
        }
        match cell.material() {
            VxhMaterial::Stone => {
                // Le fer (IRON 46,44,48) est sombre et neutre ; le mortier (68,60,52) est plus chaud : pierre.
                if r.max(g).max(b) <= 60 && r.max(g).max(b) - r.min(g).min(b) <= 10 {
                    self.iron
                } else {
                    self.stone
                }
            }
            VxhMaterial::Wood => self.wood,
            VxhMaterial::Plaster => self.plaster,
            VxhMaterial::Ground => {
                let vert = g * 100 > r * 106 && g * 100 > b * 125;
                match (vert, cell.flags().soft()) {
                    (true, _) => self.turf,
                    (false, true) => self.petal,
                    (false, false) => self.dirt,
                }
            }
            VxhMaterial::Roof => {
                let chaleur = r - b;
                if chaleur * 8 <= r {
                    self.slate
                } else if chaleur * 100 < r * 55 {
                    self.shingle
                } else {
                    self.roof_tile
                }
            }
        }
    }

    /// Valeur de voxel de la cellule : sa classe et sa luminance sur 7 bits.
    pub fn value_of(&self, cell: VxhCell) -> VoxelValue {
        let [r, g, b] = cell.rgb8().map(i32::from);
        let luma = (r * 77 + g * 150 + b * 29) >> 9; // 0..127
        VoxelValue::new(self.class_of(cell), luma as u8)
    }
}
