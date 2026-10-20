//! Recette du POTEAU : fût de section ronde ou carrée, fil vertical, anneaux dans la teinte, socle et chapiteau
//! simples (planches carrées plus larges que le fût), sans aucun chanfrein.
//!
//! Repère local : x et z de 0 à `diameter + 4` (le fût est centré, le chapiteau déborde de 2 voxels de chaque
//! côté), y vers le haut : socle (1 voxel), fût de `height` voxels, chapiteau de 3 voxels au-dessus.

use std::sync::Arc;

use em_core::{VoxelBox, VoxelCoord, VoxelValue};
use em_material::{GrainAxis, tint_wood};
use serde::{Deserialize, Serialize};

use super::beam::phase_anneau;
use super::classes::BuildingClasses;
use super::draw::Draw;
use super::grid::{DensePlan, PlanGrid};
use crate::error::GenError;
use crate::generator::{GenParams, GenPlan, Generator, GeneratorId};

/// Forme de la section du fût.
#[derive(Copy, Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum PostShape {
    /// Section carrée.
    Square,
    /// Section ronde (disque de voxels).
    Round,
}

/// Paramètres du poteau. Configuration validée par `validate`.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct PostConfig {
    /// Forme de la section.
    pub shape: PostShape,
    /// Diamètre (ou côté) du fût, en voxels : 7 = 35 cm.
    pub diameter: u32,
    /// Hauteur du fût, en voxels : 44 = 2,2 m.
    pub height: u32,
    /// Ajoute le socle et le chapiteau.
    pub capital: bool,
}

impl Default for PostConfig {
    fn default() -> Self {
        Self {
            shape: PostShape::Round,
            diameter: 7,
            height: 44,
            capital: true,
        }
    }
}

impl PostConfig {
    /// Vérifie les bornes.
    pub fn validate(&self) -> Result<(), GenError> {
        let ok = |c: bool, m: &str| {
            if c {
                Ok(())
            } else {
                Err(GenError::BadParams(format!("poteau : {m}")))
            }
        };
        ok(
            (3..=24).contains(&self.diameter),
            "diamètre hors de 3..=24 voxels",
        )?;
        ok((4..=400).contains(&self.height), "hauteur hors de 4..=400 voxels")
    }

    /// Paramètres de générateur de cette configuration.
    pub fn to_params(&self) -> Result<GenParams, GenError> {
        GenParams::json(GeneratorId::POST, 1, self)
    }

    /// Hauteur du socle (voxels) : 1 avec chapiteau, sinon 0.
    pub const fn base_height(&self) -> u32 {
        if self.capital { 1 } else { 0 }
    }

    /// Côté de l'emprise au sol (chapiteau compris).
    pub const fn footprint(&self) -> u32 {
        self.diameter + 4
    }
}

/// Le générateur de poteau.
#[derive(Clone, Debug)]
pub struct PostGenerator {
    classes: BuildingClasses,
}

impl PostGenerator {
    /// Crée le générateur avec ses classes de matière (injectées).
    pub fn new(classes: BuildingClasses) -> Self {
        Self { classes }
    }
}

impl Generator for PostGenerator {
    fn id(&self) -> GeneratorId {
        GeneratorId::POST
    }

    fn version(&self) -> u32 {
        1
    }

    fn plan(&self, params: &GenParams, seed: u64) -> Result<Arc<dyn GenPlan>, GenError> {
        let cfg: PostConfig = params.decode_json(GeneratorId::POST)?;
        cfg.validate()?;
        Ok(Arc::new(construire(&cfg, &self.classes, seed)?))
    }
}

fn construire(cfg: &PostConfig, classes: &BuildingClasses, seed: u64) -> Result<DensePlan, GenError> {
    let (d, h, w) = (cfg.diameter as i32, cfg.height as i32, cfg.footprint() as i32);
    let socle = cfg.base_height() as i32;
    let haut_total = socle + h + if cfg.capital { 3 } else { 0 };
    let mut g = PlanGrid::new(
        VoxelBox::new(VoxelCoord::new(0, 0, 0), VoxelCoord::new(w, haut_total, w))
            .map_err(|e| GenError::BadParams(e.to_string()))?,
    )?;
    let base = Draw::new(seed, 0x50_4F53).below(16);
    let marge = (w - d) / 2;
    // fût : fil vertical, anneaux concentriques ; bois de bout sur la première et la dernière tranche
    for y in socle..socle + h {
        for x in 0..d {
            for z in 0..d {
                let (cx, cz) = (2 * x - (d - 1), 2 * z - (d - 1));
                if cfg.shape == PostShape::Round && cx * cx + cz * cz > d * d {
                    continue;
                }
                let phase = phase_anneau(x, z, d, base, true);
                let bout = !cfg.capital && (y == socle || y == socle + h - 1);
                let axe = if bout {
                    GrainAxis::End as u8
                } else {
                    GrainAxis::Y as u8
                };
                g.set(
                    VoxelCoord::new(marge + x, y, marge + z),
                    VoxelValue::new(classes.wood(), tint_wood(axe, phase)),
                );
            }
        }
    }
    if cfg.capital {
        let ornement = |axe: u8, v: u8| VoxelValue::new(classes.trim(), tint_wood(axe, v));
        // socle (1 voxel, 2 de plus que le fût) et chapiteau : un voxel large de d + 2 puis deux de d + 4
        let plaque = |g: &mut PlanGrid, y: i32, cote: i32, valeur: VoxelValue| {
            let o = (w - cote) / 2;
            for x in o..o + cote {
                for z in o..o + cote {
                    g.set(VoxelCoord::new(x, y, z), valeur);
                }
            }
        };
        plaque(&mut g, 0, d + 2, ornement(GrainAxis::End as u8, 3));
        plaque(&mut g, socle + h, d + 2, ornement(GrainAxis::X as u8, 6));
        plaque(&mut g, socle + h + 1, d + 4, ornement(GrainAxis::X as u8, 9));
        plaque(&mut g, socle + h + 2, d + 4, ornement(GrainAxis::End as u8, 12));
    }
    DensePlan::new(g, vec![classes.wood(), classes.trim()])
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn configuration_validee_et_emprise() {
        let c = PostConfig::default();
        assert!(c.validate().is_ok());
        assert_eq!(c.footprint(), 11);
        assert!(
            PostConfig {
                diameter: 2,
                ..c.clone()
            }
            .validate()
            .is_err()
        );
        assert!(PostConfig { height: 3, ..c }.validate().is_err());
    }
}
