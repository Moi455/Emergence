//! Conversion sorte + rampe -> `VoxelValue` : classe de matière et 7 bits de teinte (docs/19a § 1.4 et § 5.3).

use em_core::{MaterialId, VoxelValue};
use em_material::{MaterialTable, tint_vegetation};

use super::kind::VxmKind;
use crate::error::GenError;

/// Les quatre classes de matière qu'un modèle `.vxm` utilise.
#[derive(Copy, Clone, Debug, PartialEq, Eq)]
pub struct VxmClasses {
    bark: MaterialId,
    leaves: MaterialId,
    petal: MaterialId,
    fruit: MaterialId,
}

impl VxmClasses {
    /// Numéros du catalogue : `leaves` 30, `bark` 31 (`materials.csv`), `petal` 34 et `fruit` 35
    /// (`material_render.toml`, ajoutées par L06). Un test les compare à la vraie table.
    pub const fn standard() -> Self {
        Self {
            bark: MaterialId::new(31),
            leaves: MaterialId::new(30),
            petal: MaterialId::new(34),
            fruit: MaterialId::new(35),
        }
    }

    /// Cherche les quatre classes par leur nom dans une table de matières.
    pub fn from_table(table: &MaterialTable) -> Result<Self, GenError> {
        let par_nom = |nom: &str| {
            table
                .by_name(nom)
                .ok_or_else(|| GenError::MatiereAbsente(nom.to_owned()))
        };
        Ok(Self {
            bark: par_nom("bark")?,
            leaves: par_nom("leaves")?,
            petal: par_nom("petal")?,
            fruit: par_nom("fruit")?,
        })
    }

    /// Classe d'une sorte : écorce et rameau -> `bark`, feuille -> `leaves`, fleur -> `petal`, fruit -> `fruit`.
    pub const fn class_of(&self, kind: VxmKind) -> MaterialId {
        match kind {
            VxmKind::Bark | VxmKind::Twig => self.bark,
            VxmKind::Leaf => self.leaves,
            VxmKind::Flower => self.petal,
            VxmKind::Fruit => self.fruit,
        }
    }
}

/// Valeur de voxel de chaque couple (sorte, variante) pour une essence : table de 5 × 4 entrées bâtie une fois.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct TintTable {
    values: [VoxelValue; 20],
}

impl TintTable {
    /// Bâtit la table pour la case d'essence `species_slot` (0..=31).
    pub fn new(classes: &VxmClasses, species_slot: u8) -> Result<Self, GenError> {
        if species_slot > 31 {
            return Err(GenError::UnknownSpecies(species_slot));
        }
        let mut values = [VoxelValue::AIR; 20];
        for kind in VxmKind::ALL {
            for variant in 0..4_u8 {
                values[kind.index() * 4 + usize::from(variant)] =
                    VoxelValue::new(classes.class_of(kind), tint_vegetation(species_slot, variant));
            }
        }
        Ok(Self { values })
    }

    /// Valeur du voxel de cette sorte et de cette variante (0..=3).
    pub fn value(&self, kind: VxmKind, variant: u8) -> VoxelValue {
        self.values[kind.index() * 4 + usize::from(variant & 3)]
    }
}
