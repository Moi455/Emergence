//! Les classes de matière du bâti, injectées dans chaque générateur (aucune globale).

use em_core::MaterialId;
use em_material::MaterialTable;

use crate::error::GenError;

/// Les classes qu'utilisent les recettes du bâti.
#[derive(Copy, Clone, Debug, PartialEq, Eq)]
pub struct BuildingClasses {
    stone: MaterialId,
    wood: MaterialId,
    trim: MaterialId,
    roof: MaterialId,
    moss: MaterialId,
}

impl BuildingClasses {
    /// Numéros du catalogue : `cut_stone` 20, `oak_raw` 15, `wood_trim` 21, `slate` 11 (`materials.csv`) et `moss`
    /// 36 (`material_render.toml`, ajoutée par L23p). Un test les compare à la vraie table.
    pub const fn standard() -> Self {
        Self {
            stone: MaterialId::new(20),
            wood: MaterialId::new(15),
            trim: MaterialId::new(21),
            roof: MaterialId::new(11),
            moss: MaterialId::new(36),
        }
    }

    /// Cherche les cinq classes par leur nom dans une table de matières.
    pub fn from_table(table: &MaterialTable) -> Result<Self, GenError> {
        let par_nom = |nom: &str| {
            table
                .by_name(nom)
                .ok_or_else(|| GenError::MatiereAbsente(nom.to_owned()))
        };
        Ok(Self {
            stone: par_nom("cut_stone")?,
            wood: par_nom("oak_raw")?,
            trim: par_nom("wood_trim")?,
            roof: par_nom("slate")?,
            moss: par_nom("moss")?,
        })
    }

    /// Pierre taillée (pierres et mortier : le mortier est la teinte 0).
    pub const fn stone(&self) -> MaterialId {
        self.stone
    }
    /// Bois brut (poutres, fût du poteau).
    pub const fn wood(&self) -> MaterialId {
        self.wood
    }
    /// Bois d'ornement (chapiteau, socle).
    pub const fn trim(&self) -> MaterialId {
        self.trim
    }
    /// Couverture (bardeaux d'ardoise).
    pub const fn roof(&self) -> MaterialId {
        self.roof
    }
    /// Mousse.
    pub const fn moss(&self) -> MaterialId {
        self.moss
    }
}
