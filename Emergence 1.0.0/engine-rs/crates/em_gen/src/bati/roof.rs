//! Recette du petit TOIT de bardeaux (ou de tuiles) : quelques rangées en gradins, chaque tuile d'un ton qui lui est
//! propre (7 bits de teinte posés par la recette), un voxel sombre entre deux tuiles d'une rangée, et quelques
//! tuiles moussues.
//!
//! Repère local : x le long du faîtage, la pente monte vers +z (un voxel de haut tous les `run` voxels de
//! profondeur) ; la rangée `r` occupe z de `r × run` à `(r + 1) × run` et y de `r` à `r + thickness`. L'origine est
//! le coin bas de la première rangée (l'égout).

use std::sync::Arc;

use em_core::{VoxelBox, VoxelCoord, VoxelValue, hash_combine, hash3};
use serde::{Deserialize, Serialize};

use super::classes::BuildingClasses;
use super::draw::Draw;
use super::grid::{DensePlan, PlanGrid};
use crate::error::GenError;
use crate::generator::{GenParams, GenPlan, Generator, GeneratorId};

/// Teinte du voxel sombre entre deux tuiles.
const TON_JOINT: u8 = 3;

/// Paramètres du toit. Configuration validée par `validate`.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct RoofConfig {
    /// Largeur du toit le long du faîtage (voxels).
    pub width: u32,
    /// Nombre de rangées de tuiles.
    pub rows: u32,
    /// Profondeur d'une rangée (voxels de pente : un voxel de montée par rangée).
    pub run: u32,
    /// Épaisseur d'une tuile (voxels).
    pub thickness: u32,
    /// Longueur minimale d'une tuile (voxels, le voxel de joint non compris).
    pub tile_min: u32,
    /// Longueur maximale d'une tuile (voxels).
    pub tile_max: u32,
    /// Pourcentage de tuiles moussues.
    pub moss_percent: u32,
}

impl Default for RoofConfig {
    fn default() -> Self {
        Self {
            width: 68,
            rows: 9,
            run: 3,
            thickness: 2,
            tile_min: 4,
            tile_max: 8,
            moss_percent: 8,
        }
    }
}

impl RoofConfig {
    /// Vérifie les bornes.
    pub fn validate(&self) -> Result<(), GenError> {
        let ok = |c: bool, m: &str| {
            if c {
                Ok(())
            } else {
                Err(GenError::BadParams(format!("toit : {m}")))
            }
        };
        ok((8..=400).contains(&self.width), "largeur hors de 8..=400 voxels")?;
        ok((1..=60).contains(&self.rows), "rangées hors de 1..=60")?;
        ok((1..=8).contains(&self.run), "profondeur de rangée hors de 1..=8")?;
        ok((1..=6).contains(&self.thickness), "épaisseur hors de 1..=6")?;
        ok(
            self.tile_min >= 2 && self.tile_max >= self.tile_min && self.tile_max <= 30,
            "tuiles : 2 <= min <= max <= 30",
        )?;
        ok(self.moss_percent <= 100, "pourcentage de mousse hors de 0..=100")
    }

    /// Paramètres de générateur de cette configuration.
    pub fn to_params(&self) -> Result<GenParams, GenError> {
        GenParams::json(GeneratorId::ROOF, 1, self)
    }
}

/// Le générateur de toit.
#[derive(Clone, Debug)]
pub struct RoofGenerator {
    classes: BuildingClasses,
}

impl RoofGenerator {
    /// Crée le générateur avec ses classes de matière (injectées).
    pub fn new(classes: BuildingClasses) -> Self {
        Self { classes }
    }
}

impl Generator for RoofGenerator {
    fn id(&self) -> GeneratorId {
        GeneratorId::ROOF
    }

    fn version(&self) -> u32 {
        1
    }

    fn plan(&self, params: &GenParams, seed: u64) -> Result<Arc<dyn GenPlan>, GenError> {
        let cfg: RoofConfig = params.decode_json(GeneratorId::ROOF)?;
        cfg.validate()?;
        Ok(Arc::new(construire(&cfg, &self.classes, seed)?))
    }
}

fn construire(cfg: &RoofConfig, classes: &BuildingClasses, seed: u64) -> Result<DensePlan, GenError> {
    let (w, rows, run, ep) = (
        cfg.width as i32,
        cfg.rows as i32,
        cfg.run as i32,
        cfg.thickness as i32,
    );
    let mut g = PlanGrid::new(
        VoxelBox::new(
            VoxelCoord::new(0, 0, 0),
            VoxelCoord::new(w, rows - 1 + ep, rows * run),
        )
        .map_err(|e| GenError::BadParams(e.to_string()))?,
    )?;
    let mut tirage = Draw::new(seed, 0x54_4F49);
    let graine_mousse = hash_combine(seed, 0x4D_4F54);
    for r in 0..rows {
        let mut x = -(tirage.below(cfg.tile_min) as i32); // les rangées sont décalées
        while x < w {
            let mut longueur = tirage.between(cfg.tile_min, cfg.tile_max) as i32;
            if w - (x + longueur + 1) < cfg.tile_min as i32 {
                longueur = w - x;
            }
            let ton = 20 + tirage.below(90) as u8; // ton propre à la tuile : la recette pose la couleur
            let moussue = tirage.percent(cfg.moss_percent);
            for xx in x.max(0)..(x + longueur).min(w) {
                for yy in r..r + ep {
                    for zz in r * run..(r + 1) * run {
                        let haut = yy == r + ep - 1;
                        let a_la_mousse = moussue
                            && haut
                            && hash3(graine_mousse, i64::from(xx), i64::from(zz), 1) % 100 < 70;
                        let valeur = if a_la_mousse {
                            let v = 50
                                + (hash3(graine_mousse, i64::from(xx), i64::from(yy), i64::from(zz)) % 60)
                                    as u8;
                            VoxelValue::new(classes.moss(), v)
                        } else {
                            VoxelValue::new(classes.roof(), ton)
                        };
                        g.set(VoxelCoord::new(xx, yy, zz), valeur);
                    }
                }
            }
            // voxel de joint sombre entre deux tuiles
            let xj = x + longueur;
            if (0..w).contains(&xj) {
                for yy in r..r + ep {
                    for zz in r * run..(r + 1) * run {
                        g.set(
                            VoxelCoord::new(xj, yy, zz),
                            VoxelValue::new(classes.roof(), TON_JOINT),
                        );
                    }
                }
            }
            x += longueur + 1;
        }
    }
    DensePlan::new(g, vec![classes.roof(), classes.moss()])
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn configuration_validee() {
        assert!(RoofConfig::default().validate().is_ok());
        assert!(
            RoofConfig {
                rows: 0,
                ..Default::default()
            }
            .validate()
            .is_err()
        );
        assert!(
            RoofConfig {
                tile_min: 9,
                tile_max: 5,
                ..Default::default()
            }
            .validate()
            .is_err()
        );
    }
}
