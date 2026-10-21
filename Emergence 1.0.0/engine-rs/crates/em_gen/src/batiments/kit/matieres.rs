//! Les classes de matière des bâtiments, props et rochers, injectées dans chaque générateur (aucune globale).
//!
//! Les numéros 1 à 36 viennent de `materials.csv` et de `material_render.toml` (L23p) ; 37 à 57 sont les classes
//! ajoutées par L35 à L37 dans `material_render.toml` (jamais dans `materials.csv`, catalogue du jeu). Un test
//! compare `standard()` à la vraie table par NOM.

use em_core::{MaterialId, VoxelValue};
use em_material::{MaterialTable, tint_stone, tint_wood};

use crate::error::GenError;

macro_rules! matieres {
    ($( $champ:ident = $id:literal, $nom:literal, $doc:literal; )+) => {
        /// Les classes de matière utilisées par les recettes de L35 à L37.
        #[derive(Copy, Clone, Debug, PartialEq, Eq)]
        pub struct Matieres {
            $( #[doc = $doc] pub $champ: MaterialId, )+
        }

        impl Matieres {
            /// Numéros du catalogue (un test les compare à la vraie table).
            pub const fn standard() -> Self {
                Self { $( $champ: MaterialId::new($id), )+ }
            }

            /// Cherche chaque classe par son nom dans une table de matières.
            pub fn from_table(table: &MaterialTable) -> Result<Self, GenError> {
                Ok(Self {
                    $( $champ: table
                        .by_name($nom)
                        .ok_or_else(|| GenError::MatiereAbsente($nom.to_owned()))?, )+
                })
            }

            /// Priorité de réduction des niveaux grossiers : toutes les classes, sans doublon.
            pub fn priority(&self) -> Vec<MaterialId> {
                vec![ $( self.$champ, )+ ]
            }

            /// Noms des classes, dans l'ordre de `priority`.
            pub const NOMS: &'static [&'static str] = &[ $( $nom, )+ ];
        }
    };
}

matieres! {
    turf = 1, "turf", "Herbe.";
    dirt = 2, "dirt", "Terre.";
    clay = 3, "clay", "Argile.";
    sand = 4, "sand", "Sable.";
    gravel = 5, "gravel", "Gravier.";
    limestone = 8, "limestone", "Calcaire.";
    sandstone = 9, "sandstone", "Grès.";
    granite = 10, "granite", "Granit.";
    slate = 11, "slate", "Ardoise.";
    basalt = 12, "basalt", "Basalte.";
    oak_raw = 15, "oak_raw", "Chêne brut.";
    oak_planks = 16, "oak_planks", "Planches de chêne.";
    plaster = 17, "plaster", "Plâtre blanc.";
    roof_tile = 18, "roof_tile", "Tuile rouge.";
    thatch = 19, "thatch", "Chaume.";
    cut_stone = 20, "cut_stone", "Pierre taillée chaude (joints bruns).";
    wood_trim = 21, "wood_trim", "Bois d'ornement.";
    wood_trim_worn = 22, "wood_trim_worn", "Bois usé (bardeau).";
    brick = 24, "brick", "Brique.";
    red_brick = 25, "red_brick", "Brique rouge.";
    rubble = 26, "rubble_masonry", "Moellons.";
    iron = 27, "iron", "Fer.";
    glass = 28, "glass", "Verre.";
    cobble = 32, "cobblestone", "Pavés.";
    cloth = 33, "cloth", "Toile.";
    moss = 36, "moss", "Mousse.";
    timber = 37, "timber", "Colombage brun sombre.";
    stone_grey = 38, "stone_grey", "Pierre grise (pièces numérotées).";
    stone_dark = 39, "stone_dark", "Pierre sombre (pièces numérotées).";
    paint_green = 40, "paint_green", "Peinture verte (volets).";
    paint_blue = 41, "paint_blue", "Peinture bleue.";
    paint_red = 42, "paint_red", "Peinture rouge.";
    fabric_a = 43, "fabric_a", "Étoffe : rouge, bleu, vert (teintes 0, 63, 127).";
    fabric_b = 44, "fabric_b", "Étoffe : jaune, violet, blanc cassé.";
    flower_a = 45, "flower_a", "Fleurs : blanc, jaune, rose.";
    flower_b = 46, "flower_b", "Fleurs : violet, rouge, orangé.";
    glow = 47, "glow", "Flamme de lanterne (émissive).";
    ember = 48, "ember", "Braise (émissive).";
    brass = 49, "brass", "Laiton.";
    leather = 50, "leather", "Cuir.";
    ceramic = 51, "ceramic", "Terre cuite (pots, vaisselle).";
    wax = 52, "wax", "Cire, papier.";
    plaster_ochre = 53, "plaster_ochre", "Plâtre ocre.";
    hay = 54, "hay", "Foin.";
    rock_grey = 55, "rock_grey", "Roche grise (blocs numérotés).";
    rock_warm = 56, "rock_warm", "Roche chaude (blocs numérotés).";
    coal = 57, "coal", "Charbon.";
}

/// Les trois teintes franches d'une classe à rampe de trois couleurs.
#[derive(Copy, Clone, Debug, PartialEq, Eq)]
pub enum Ton {
    /// Couleur sombre (teinte 0).
    Sombre,
    /// Couleur moyenne (teinte 63).
    Moyen,
    /// Couleur claire (teinte 127).
    Clair,
}

impl Ton {
    /// Teinte ramp128 de ce ton.
    pub const fn teinte(self) -> u8 {
        match self {
            Ton::Sombre => 0,
            Ton::Moyen => 63,
            Ton::Clair => 127,
        }
    }
}

/// Valeur d'un voxel : classe + teinte (7 bits, tronquée).
#[inline]
pub const fn val(m: MaterialId, teinte: u8) -> VoxelValue {
    VoxelValue::new(m, teinte & 127)
}

/// Valeur d'un voxel d'une classe à trois couleurs, ton franc.
#[inline]
pub const fn ton(m: MaterialId, t: Ton) -> VoxelValue {
    VoxelValue::new(m, t.teinte())
}

/// Voxel de bois (classe à fil `wood_axis`) : axe 0 = x, 1 = y, 2 = z, 3 = bout ; `variante` 0..31 (bits 0-3
/// anneau, bit 4 nœud). Le ton de chaque fibre vient de la colonne de fibre dans le rendu en mode voxel.
#[inline]
pub const fn bois(m: MaterialId, axe: u8, variante: u8) -> VoxelValue {
    VoxelValue::new(m, tint_wood(axe & 3, variante & 31))
}

/// Voxel de pierre : numéro de pièce 1..127 (0 = mortier).
#[inline]
pub const fn pierre(m: MaterialId, piece: u8) -> VoxelValue {
    VoxelValue::new(m, tint_stone(piece & 127))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn les_classes_standard_sont_sans_doublon() {
        let mut p = Matieres::standard().priority();
        let n = p.len();
        p.sort();
        p.dedup();
        assert_eq!(p.len(), n);
        assert_eq!(Matieres::NOMS.len(), n);
    }
}
