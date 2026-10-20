//! Recette de la POUTRE de bois : section carrée (20 cm = 4 voxels par défaut), fibres le long de l'axe, anneaux
//! de croissance et nœuds posés dans la teinte, extrémités en bois de bout.
//!
//! Repère local : le fil court de 0 à `length` le long de `axis` ; la section occupe `0..section` sur les deux
//! autres axes (dans l'ordre x, y, z). La teinte de bois (`tint_wood`) porte l'axe du fil (2 bits) et une variante
//! de 5 bits : phase d'anneau (bits 0 à 3) et drapeau de nœud (bit 4), que le mode `VoxelPixel` lit.

use std::sync::Arc;

use em_core::{VoxelBox, VoxelCoord, VoxelValue};
use em_material::{GrainAxis, tint_wood};
use serde::{Deserialize, Serialize};

use super::classes::BuildingClasses;
use super::draw::Draw;
use super::grid::{DensePlan, PlanGrid};
use crate::error::GenError;
use crate::generator::{GenParams, GenPlan, Generator, GeneratorId};

/// Axe du fil d'une pièce de bois.
#[derive(Copy, Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Axis {
    /// Le fil court le long de x.
    X,
    /// Le fil court vers le haut.
    Y,
    /// Le fil court le long de z.
    Z,
}

impl Axis {
    /// Axe de fil de la teinte de bois.
    pub const fn grain(self) -> GrainAxis {
        match self {
            Axis::X => GrainAxis::X,
            Axis::Y => GrainAxis::Y,
            Axis::Z => GrainAxis::Z,
        }
    }

    /// Coordonnée locale (le long du fil `s`, section `a`, `b`) -> voxel.
    pub const fn voxel(self, s: i32, a: i32, b: i32) -> VoxelCoord {
        match self {
            Axis::X => VoxelCoord::new(s, a, b),
            Axis::Y => VoxelCoord::new(a, s, b),
            Axis::Z => VoxelCoord::new(a, b, s),
        }
    }
}

/// Paramètres de la poutre. Configuration validée par `validate`.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct BeamConfig {
    /// Longueur (voxels) : 60 = 3 m.
    pub length: u32,
    /// Côté de la section carrée (voxels) : 4 = 20 cm.
    pub section: u32,
    /// Axe du fil.
    pub axis: Axis,
    /// Nombre de nœuds sur les faces.
    pub knots: u32,
    /// Anneaux de croissance dans la teinte (sinon une seule phase).
    pub rings: bool,
    /// Extrémités en bois de bout (la première et la dernière tranche).
    pub end_grain: bool,
}

impl Default for BeamConfig {
    fn default() -> Self {
        Self {
            length: 60,
            section: 4,
            axis: Axis::X,
            knots: 3,
            rings: true,
            end_grain: true,
        }
    }
}

impl BeamConfig {
    /// Vérifie les bornes.
    pub fn validate(&self) -> Result<(), GenError> {
        let ok = |c: bool, m: &str| {
            if c {
                Ok(())
            } else {
                Err(GenError::BadParams(format!("poutre : {m}")))
            }
        };
        ok(
            (4..=400).contains(&self.length),
            "longueur hors de 4..=400 voxels",
        )?;
        ok((2..=24).contains(&self.section), "section hors de 2..=24 voxels")?;
        ok(self.knots <= 40, "au plus 40 nœuds")
    }

    /// Paramètres de générateur de cette configuration.
    pub fn to_params(&self) -> Result<GenParams, GenError> {
        GenParams::json(GeneratorId::BEAM, 1, self)
    }
}

/// Phase d'anneau (0..=15) d'une colonne de la section : anneaux carrés ou ronds concentriques autour de la moelle.
pub(super) fn phase_anneau(a: i32, b: i32, section: i32, base: u32, ronds: bool) -> u8 {
    let (ca, cb) = (2 * a - (section - 1), 2 * b - (section - 1)); // coordonnées centrées, doublées
    let rang = if ronds {
        isqrt(ca * ca + cb * cb)
    } else {
        ca.abs().max(cb.abs())
    };
    ((rang as u32 * 5 + base) & 15) as u8
}

/// Racine carrée entière par défaut.
fn isqrt(v: i32) -> i32 {
    let mut r = 0;
    while (r + 1) * (r + 1) <= v {
        r += 1;
    }
    r
}

/// Le générateur de poutre.
#[derive(Clone, Debug)]
pub struct BeamGenerator {
    classes: BuildingClasses,
}

impl BeamGenerator {
    /// Crée le générateur avec ses classes de matière (injectées).
    pub fn new(classes: BuildingClasses) -> Self {
        Self { classes }
    }
}

impl Generator for BeamGenerator {
    fn id(&self) -> GeneratorId {
        GeneratorId::BEAM
    }

    fn version(&self) -> u32 {
        1
    }

    fn plan(&self, params: &GenParams, seed: u64) -> Result<Arc<dyn GenPlan>, GenError> {
        let cfg: BeamConfig = params.decode_json(GeneratorId::BEAM)?;
        cfg.validate()?;
        Ok(Arc::new(construire(&cfg, &self.classes, seed)?))
    }
}

fn construire(cfg: &BeamConfig, classes: &BuildingClasses, seed: u64) -> Result<DensePlan, GenError> {
    let (l, n) = (cfg.length as i32, cfg.section as i32);
    let min = VoxelCoord::new(0, 0, 0);
    let max = cfg.axis.voxel(l, n, n);
    let mut g = PlanGrid::new(VoxelBox::new(min, max).map_err(|e| GenError::BadParams(e.to_string()))?)?;
    let mut tirage = Draw::new(seed, 0x42_4541);
    let base = tirage.below(16);
    let axe = cfg.axis.grain() as u8;

    // nœuds : un carré de 2 x 2 voxels sur une face (couche de bord), loin des extrémités
    let mut noeuds: Vec<(i32, i32, i32)> = Vec::new();
    for _ in 0..cfg.knots {
        let s = tirage.between(3, (l - 5).max(3) as u32) as i32;
        let a = tirage.below(n as u32) as i32;
        let face = if tirage.below(2) == 0 { 0 } else { n - 1 };
        let sur_a = tirage.below(2) == 0; // la face est perpendiculaire à la première ou à la seconde direction de la section
        noeuds.push(if sur_a { (s, face, a) } else { (s, a, face) });
    }
    let est_noeud = |s: i32, a: i32, b: i32| {
        noeuds.iter().any(|&(ns, na, nb)| {
            (ns..ns + 2).contains(&s) && (na..na + 2).contains(&a) && (nb..nb + 2).contains(&b)
        })
    };

    for s in 0..l {
        for a in 0..n {
            for b in 0..n {
                let phase = if cfg.rings {
                    phase_anneau(a, b, n, base, false)
                } else {
                    0
                };
                let variante = phase | if est_noeud(s, a, b) { 16 } else { 0 };
                let bout = cfg.end_grain && (s == 0 || s == l - 1);
                let axe_teinte = if bout { GrainAxis::End as u8 } else { axe };
                g.set(
                    cfg.axis.voxel(s, a, b),
                    VoxelValue::new(classes.wood(), tint_wood(axe_teinte, variante)),
                );
            }
        }
    }
    DensePlan::new(g, vec![classes.wood()])
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn les_phases_d_anneau_sont_dans_0_15_et_symetriques() {
        for a in 0..6 {
            for b in 0..6 {
                let p = phase_anneau(a, b, 6, 3, true);
                assert!(p < 16);
                assert_eq!(p, phase_anneau(5 - a, b, 6, 3, true));
                assert_eq!(p, phase_anneau(a, 5 - b, 6, 3, true));
            }
        }
    }

    #[test]
    fn configuration_validee() {
        assert!(BeamConfig::default().validate().is_ok());
        assert!(
            BeamConfig {
                section: 1,
                ..Default::default()
            }
            .validate()
            .is_err()
        );
        assert!(
            BeamConfig {
                length: 2,
                ..Default::default()
            }
            .validate()
            .is_err()
        );
    }
}
