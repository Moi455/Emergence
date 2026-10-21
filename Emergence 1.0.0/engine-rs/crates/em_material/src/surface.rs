//! Paramètres de SURFACE par voxel (L33, exigence de Monsieur du 21 oct. 2026) : granulométrie, porosité, réflexion.
//!
//! Un octet par voxel, DÉRIVÉ de la classe de matière et d'un hachage de la position (rien n'est stocké dans les
//! voxels), porté jusqu'au shader par les sommets du maillage :
//!
//! ```text
//!  bits 7-6 : granulométrie (0..3) amplitude de variation de couleur entre voxels voisins de la classe
//!  bits 5-3 : porosité      (0..7) retient l'humidité (assombrit) et la mousse
//!  bits 2-0 : réflexion     (0..7) brillance spéculaire douce du soleil (pierre mouillée, métal ; pas le bois sec)
//! ```
//!
//! La couleur reste PLATE par voxel : l'humidité n'ajoute qu'un facteur d'assombrissement constant sur tout le
//! voxel, jamais un motif sous-voxel. Tout est entier (aucun flottant), déterministe, indépendant de l'ordre.

use crate::style::{MaterialMode, StyleSheet};
use crate::table::{CLASS_COUNT, MaterialDef, MaterialTable};
use crate::tint::TintMode;
use em_core::VoxelCoord;
use em_core::hash::{hash_combine, hash3};
use em_core::ids::{MaterialId, VoxelValue};
use em_core::q16::Q16;

/// Facteur d'assombrissement d'un voxel mouillé (Q16).
const ASSOMBRI_MOUILLE: i64 = 47_186; // 0,72
/// Réflexion ajoutée par l'humidité.
const BRILLANCE_MOUILLE: u8 = 3;
/// Séparation de graine du champ d'humidité.
const GRAINE_HUMIDITE: u64 = 0x4855_4D49_4449_5445; // « HUMIDITE »
/// Les cellules d'humidité mesurent 8 x 8 x 8 voxels (40 cm) : des plaques, pas du bruit voxel par voxel.
const CELLULE_HUMIDITE_SHIFT: u32 = 3;

/// Les trois paramètres de surface d'un voxel.
#[derive(Copy, Clone, Debug, Default, PartialEq, Eq)]
pub struct SurfaceParams {
    grain: u8,
    porosity: u8,
    reflection: u8,
}

impl SurfaceParams {
    /// Construit les paramètres ; chaque valeur est bornée à son champ (grain 0..3, porosité et réflexion 0..7).
    pub const fn new(grain: u8, porosity: u8, reflection: u8) -> Self {
        Self {
            grain: if grain > 3 { 3 } else { grain },
            porosity: if porosity > 7 { 7 } else { porosity },
            reflection: if reflection > 7 { 7 } else { reflection },
        }
    }

    /// Lit un octet rangé par `pack` (tout octet est valide).
    pub const fn unpack(octet: u8) -> Self {
        Self {
            grain: octet >> 6,
            porosity: (octet >> 3) & 7,
            reflection: octet & 7,
        }
    }

    /// L'octet de paramètres de matière du sommet.
    pub const fn pack(self) -> u8 {
        (self.grain << 6) | (self.porosity << 3) | self.reflection
    }

    /// Granulométrie, 0 (lisse) à 3 (très tranchée).
    pub const fn grain(self) -> u8 {
        self.grain
    }

    /// Porosité, 0 (étanche) à 7 (éponge).
    pub const fn porosity(self) -> u8 {
        self.porosity
    }

    /// Réflexion, 0 (mat) à 7 (brillant).
    pub const fn reflection(self) -> u8 {
        self.reflection
    }
}

/// Résultat d'évaluation de la surface d'un voxel.
#[derive(Copy, Clone, Debug, PartialEq, Eq)]
pub struct SurfaceSample {
    params: SurfaceParams,
    tone: Q16,
    wet: bool,
    relief: u8,
}

impl SurfaceSample {
    /// Paramètres de surface (déjà augmentés par l'humidité).
    pub const fn params(&self) -> SurfaceParams {
        self.params
    }

    /// Facteur à multiplier à l'albédo (Q16 ; 1 = inchangé, moins pour un voxel mouillé).
    pub const fn tone(&self) -> Q16 {
        self.tone
    }

    /// Vrai si le voxel est mouillé.
    pub const fn is_wet(&self) -> bool {
        self.wet
    }

    /// Force du relief sous-voxel de la classe, 0 (lisse : métal, verre) à 7 (froissé : pierre, bois).
    pub const fn relief(&self) -> u8 {
        self.relief
    }
}

/// Ce qu'on sait d'une classe, calculé UNE fois depuis la table.
#[derive(Copy, Clone, Debug)]
struct ClasseSurface {
    seed: u64,
    grain: u8,
    porosity: u8,
    reflection: u8,
    /// Relief sous-voxel 0..7 (`relief` de `material_render.toml` : 0 lisse, 1 = 7).
    relief: u8,
    /// Seuil (sur 65 536) sous lequel une cellule d'humidité est mouillée ; 0 = la classe ne se mouille pas.
    seuil_humide: u32,
}

/// Modèle de surface des 512 classes : construit depuis la table et la feuille de style, lu par le mailleur.
#[derive(Clone, Debug)]
pub struct SurfaceModel {
    classes: Vec<ClasseSurface>,
}

impl SurfaceModel {
    /// Calcule la surface de chaque classe de la table.
    pub fn new(table: &MaterialTable, style: &StyleSheet) -> Self {
        let defaut = ClasseSurface {
            seed: 0,
            grain: 0,
            porosity: 0,
            reflection: 0,
            relief: 0,
            seuil_humide: 0,
        };
        let mut classes = vec![defaut; CLASS_COUNT];
        for def in table.iter() {
            classes[usize::from(def.id().get())] = Self::classe(def, style);
        }
        Self { classes }
    }

    /// Porosité de la classe selon sa catégorie et sa densité.
    fn porosite(def: &MaterialDef) -> u8 {
        let densite = i64::from(def.density_kg_m3());
        let r = def.render();
        let vitreux = r.roughness().raw() < 13_107; // rugosité < 0,2 : verre, métal poli
        if vitreux {
            return 0;
        }
        // une pierre est d'autant plus poreuse qu'elle est légère : granite 2700 -> 3, calcaire 2500 -> 5
        let pierre = ((3_300 - densite) / 120).clamp(1, 6) as u8;
        match def.category() {
            "metal" | "gas" => 0,
            "rock" | "mineral" => pierre,
            "building" if densite >= 2_200 => pierre,
            "building" => 5,
            "soil" => 5,
            "wood" => 4,
            "plant" => 3,
            "textile" => 6,
            _ => 2,
        }
    }

    fn classe(def: &MaterialDef, style: &StyleSheet) -> ClasseSurface {
        let r = def.render();
        let porosity = Self::porosite(def);
        let gloss = 65_536 - r.roughness().raw().clamp(0, 65_536);
        // la brillance de base dépend de la famille : le métal et le verre brillent, le bois sec, la terre et le tissu non
        let (facteur, mouillable) = match def.category() {
            "metal" => (65_536, false),
            "rock" | "mineral" => (52_428, true),
            "building" if r.roughness().raw() < 13_107 => (65_536, false),
            "building" if def.density_kg_m3() >= 2_200 => (52_428, true),
            "building" => (26_214, false),
            "wood" => (26_214, false),
            "soil" | "plant" => (19_660, false),
            "textile" | "gas" => (0, false),
            _ => (32_768, false),
        };
        let reflection = ((gloss * facteur / 65_536 * 7 + 32_768) / 65_536).clamp(0, 7) as u8;
        // granulométrie : amplitude de variation de couleur entre voxels voisins
        let amplitude = if style.mode_of(def.id()) == MaterialMode::VoxelPixel {
            let p = style.params_of(def.id());
            p.block_spread.raw() + 2 * p.voxel_jitter.raw() + p.run_contrast.raw()
        } else {
            r.albedo_var().raw() + 2 * r.voxel_jitter().raw()
        };
        let grain = match amplitude {
            a if a < 5_243 => 0,  // < 8 %
            a if a < 13_107 => 1, // < 20 %
            a if a < 26_214 => 2, // < 40 %
            _ => 3,
        };
        // une cellule est mouillée avec une probabilité de 9 % par point de porosité (45 % pour la porosité 5)
        let seuil_humide = if mouillable {
            u32::from(porosity) * 5_900
        } else {
            0
        };
        ClasseSurface {
            seed: def.class_seed(),
            grain,
            porosity,
            reflection,
            relief: ((r.relief().raw().clamp(0, 65_536) * 7 + 32_768) / 65_536) as u8,
            seuil_humide,
        }
    }

    /// Surface d'un voxel : paramètres de sa classe, plus l'humidité de sa cellule de 40 cm (hachage de la position
    /// ENTIÈRE et de la classe : aucune coordonnée locale, aucun stockage).
    pub fn evaluate(&self, value: VoxelValue, voxel: VoxelCoord, lod: u8) -> SurfaceSample {
        let c = &self.classes[usize::from(value.material().get())];
        let mut reflection = c.reflection;
        let mut tone = Q16::ONE;
        let mut wet = false;
        if c.seuil_humide > 0 {
            let cellule = |v: i32| i64::from(v >> CELLULE_HUMIDITE_SHIFT);
            let h = hash3(
                hash_combine(c.seed ^ GRAINE_HUMIDITE, u64::from(lod)),
                cellule(voxel.x),
                cellule(voxel.y),
                cellule(voxel.z),
            );
            if ((h >> 48) as u32) < c.seuil_humide {
                wet = true;
                tone = Q16::from_raw(ASSOMBRI_MOUILLE);
                reflection = (reflection + BRILLANCE_MOUILLE).min(7);
            }
        }
        SurfaceSample {
            params: SurfaceParams::new(c.grain, c.porosity, reflection),
            tone,
            wet,
            relief: c.relief,
        }
    }

    /// Classe de matière sans étage de teinte : sert aux essais.
    pub fn base_params(&self, classe: MaterialId) -> SurfaceParams {
        let c = &self.classes[usize::from(classe.get())];
        SurfaceParams::new(c.grain, c.porosity, c.reflection)
    }

    /// Vrai si la famille de teinte de la classe a une règle de pierre (utile aux recettes qui posent de la mousse).
    pub fn is_stone_like(table: &MaterialTable, classe: MaterialId) -> bool {
        table.get(classe).render().tint_mode() == TintMode::StonePiece
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn l_octet_fait_l_aller_retour_et_les_champs_sont_bornes() {
        for g in 0..4_u8 {
            for p in 0..8_u8 {
                for r in 0..8_u8 {
                    let s = SurfaceParams::new(g, p, r);
                    assert_eq!(SurfaceParams::unpack(s.pack()), s);
                }
            }
        }
        let s = SurfaceParams::new(9, 99, 200);
        assert_eq!((s.grain(), s.porosity(), s.reflection()), (3, 7, 7));
        for octet in 0..=255_u8 {
            assert_eq!(SurfaceParams::unpack(octet).pack(), octet);
        }
    }

    #[test]
    fn le_relief_par_classe_vient_de_la_table_et_le_metal_est_lisse() {
        let racine = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../../engine/data");
        let table = MaterialTable::load(
            &racine.join("materials.csv"),
            &racine.join("material_render.toml"),
        )
        .unwrap();
        let modele = SurfaceModel::new(&table, &StyleSheet::continuous());
        let relief = |nom: &str| {
            let id = table.by_name(nom).unwrap();
            modele
                .evaluate(VoxelValue::new(id, 0), VoxelCoord::new(0, 0, 0), 0)
                .relief()
        };
        assert_eq!((relief("iron"), relief("glass")), (0, 0), "métal et verre lisses");
        assert_eq!(
            (relief("cut_stone"), relief("oak_raw")),
            (7, 7),
            "pierre et bois froissés"
        );
        assert!(relief("plaster") > 0 && relief("plaster") < relief("roof_tile"));
        assert!(relief("roof_tile") < relief("cut_stone"));
        assert!(relief("turf") <= 2, "l'herbe a peu de relief");
    }
}
