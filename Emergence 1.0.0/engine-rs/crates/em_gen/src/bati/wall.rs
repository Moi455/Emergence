//! Recette du MUR DE PIERRE : appareil irrégulier (assises de hauteurs variées, pierres de longueurs variées et
//! décalées d'une assise à l'autre), joints de mortier d'un voxel, quelques pierres saillantes, mousse au pied du
//! mur et sur le dessus. Chaque pierre porte son numéro (1..=127) dans la teinte ; le mortier est la teinte 0.
//!
//! Repère local : x le long du mur, y vers le haut, z dans l'épaisseur ; la face avant est à z = 0 (les pierres
//! saillantes avancent jusqu'à z = -1) ; l'origine est le coin avant-bas-gauche.
//!
//! Le numéro de pierre vient de la RECETTE (jamais du chunk) : une pierre coupée par un bord de chunk garde son
//! numéro de part et d'autre.

use std::sync::Arc;

use em_core::{VoxelBox, VoxelCoord, VoxelValue, hash_combine, hash3};
use em_material::tint_stone;
use serde::{Deserialize, Serialize};

use super::classes::BuildingClasses;
use super::draw::Draw;
use super::grid::{DensePlan, PlanGrid};
use crate::error::GenError;
use crate::generator::{GenParams, GenPlan, Generator, GeneratorId};

/// Paramètres du mur (voxels de 5 cm). Configuration validée par `validate`.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct StoneWallConfig {
    /// Longueur du mur (voxels).
    pub length: u32,
    /// Hauteur du mur (voxels).
    pub height: u32,
    /// Épaisseur du mur (voxels).
    pub thickness: u32,
    /// Hauteur minimale d'une assise de pierres (voxels, joint non compris).
    pub course_min: u32,
    /// Hauteur maximale d'une assise (voxels).
    pub course_max: u32,
    /// Longueur minimale d'une pierre (voxels).
    pub stone_min: u32,
    /// Longueur maximale d'une pierre (voxels).
    pub stone_max: u32,
    /// Retrait du mortier sur la face avant : 0 (affleurant) ou 1 voxel.
    pub joint_recess: u32,
    /// Pourcentage de pierres saillantes d'un voxel sur la face avant.
    pub protrusion_percent: u32,
    /// Nombre d'assises du pied du mur qui peuvent porter de la mousse.
    pub moss_foot_rows: u32,
    /// Densité de la mousse au ras du sol (pourcent, décroît avec la hauteur).
    pub moss_foot_percent: u32,
    /// Densité de la mousse sur le dessus du mur (pourcent).
    pub moss_top_percent: u32,
}

impl Default for StoneWallConfig {
    fn default() -> Self {
        Self {
            length: 72,
            height: 44,
            thickness: 6,
            course_min: 4,
            course_max: 7,
            stone_min: 8,
            stone_max: 16,
            joint_recess: 0,
            protrusion_percent: 8,
            moss_foot_rows: 7,
            moss_foot_percent: 60,
            moss_top_percent: 50,
        }
    }
}

impl StoneWallConfig {
    /// Vérifie les bornes ; une configuration invalide ne donne aucun plan.
    pub fn validate(&self) -> Result<(), GenError> {
        let ok = |c: bool, m: &str| {
            if c {
                Ok(())
            } else {
                Err(GenError::BadParams(format!("mur de pierre : {m}")))
            }
        };
        ok(
            (8..=400).contains(&self.length),
            "longueur hors de 8..=400 voxels",
        )?;
        ok((4..=200).contains(&self.height), "hauteur hors de 4..=200 voxels")?;
        ok(
            (2..=40).contains(&self.thickness),
            "épaisseur hors de 2..=40 voxels",
        )?;
        ok(
            self.course_min >= 2 && self.course_max >= self.course_min && self.course_max <= 20,
            "assises : 2 <= min <= max <= 20",
        )?;
        ok(
            self.stone_min >= 3 && self.stone_max >= self.stone_min && self.stone_max <= 60,
            "pierres : 3 <= min <= max <= 60",
        )?;
        ok(
            self.joint_recess <= 1 && self.joint_recess < self.thickness,
            "retrait du joint : 0 ou 1",
        )?;
        ok(
            self.protrusion_percent <= 100 && self.moss_foot_percent <= 100 && self.moss_top_percent <= 100,
            "pourcentages hors de 0..=100",
        )?;
        ok(
            self.moss_foot_rows <= self.height,
            "mousse du pied plus haute que le mur",
        )
    }

    /// Paramètres de générateur de cette configuration.
    pub fn to_params(&self) -> Result<GenParams, GenError> {
        GenParams::json(GeneratorId::STONE_WALL, 1, self)
    }
}

/// Le générateur de mur de pierre.
#[derive(Clone, Debug)]
pub struct StoneWallGenerator {
    classes: BuildingClasses,
}

impl StoneWallGenerator {
    /// Crée le générateur avec ses classes de matière (injectées).
    pub fn new(classes: BuildingClasses) -> Self {
        Self { classes }
    }
}

/// Une pierre posée : intervalle en x et numéro, pour éviter deux numéros égaux côte à côte.
#[derive(Copy, Clone)]
struct Posee {
    x0: i32,
    x1: i32,
    piece: u8,
}

/// Numéro de pierre (1..=127) différent de tous les `interdits`.
fn numero(draw: &mut Draw, interdits: &[u8]) -> u8 {
    for _ in 0..32 {
        let p = 1 + draw.below(127) as u8;
        if !interdits.contains(&p) {
            return p;
        }
    }
    (1..=127_u8).find(|p| !interdits.contains(p)).unwrap_or(1)
}

impl Generator for StoneWallGenerator {
    fn id(&self) -> GeneratorId {
        GeneratorId::STONE_WALL
    }

    fn version(&self) -> u32 {
        1
    }

    fn plan(&self, params: &GenParams, seed: u64) -> Result<Arc<dyn GenPlan>, GenError> {
        let cfg: StoneWallConfig = params.decode_json(GeneratorId::STONE_WALL)?;
        cfg.validate()?;
        Ok(Arc::new(construire(&cfg, &self.classes, seed)?))
    }
}

fn construire(cfg: &StoneWallConfig, classes: &BuildingClasses, seed: u64) -> Result<DensePlan, GenError> {
    let (l, h, t) = (cfg.length as i32, cfg.height as i32, cfg.thickness as i32);
    let boite = VoxelBox::new(VoxelCoord::new(0, 0, -1), VoxelCoord::new(l, h + 1, t))
        .map_err(|e| GenError::BadParams(e.to_string()))?;
    let mut g = PlanGrid::new(boite)?;
    let pierre = |p: u8| VoxelValue::new(classes.stone(), tint_stone(p));
    let mortier = pierre(0);

    // 1. le mortier remplit tout le volume du mur (les joints sont ce qui reste entre les pierres)
    for y in 0..h {
        for z in cfg.joint_recess as i32..t {
            for x in 0..l {
                g.set(VoxelCoord::new(x, y, z), mortier);
            }
        }
    }

    // 2. les assises : hauteur, décalage et longueur des pierres tirés de la graine
    let mut assises = Draw::new(seed, 0x41_5353);
    let mut pierres = Draw::new(seed, 0x50_4945);
    let mut precedente: Vec<Posee> = Vec::new();
    let mut y = 0;
    while y < h {
        let reste = h - y;
        let mut hauteur = assises.between(cfg.course_min, cfg.course_max) as i32;
        if reste - hauteur < cfg.course_min as i32 + 1 {
            hauteur = reste; // dernière assise : prend le reste
        }
        let hauteur = hauteur.min(reste);
        let mut courante: Vec<Posee> = Vec::new();
        let mut x = -(pierres.below(cfg.stone_min / 2 + 1) as i32); // décalage d'assise
        while x < l {
            let mut longueur = pierres.between(cfg.stone_min, cfg.stone_max) as i32;
            // joints verticaux décalés : jamais à moins d'un voxel d'un joint de l'assise précédente (pas de « coulée »)
            if let Some(ajuste) = (0..=8_i32)
                .flat_map(|d| [d, -d])
                .map(|d| longueur + d)
                .filter(|n| (cfg.stone_min as i32..=cfg.stone_max as i32).contains(n))
                .find(|n| precedente.iter().all(|p| (p.x1 - (x + n)).abs() > 1))
            {
                longueur = ajuste;
            }
            if l - (x + longueur + 1) < cfg.stone_min as i32 {
                longueur = l - x; // dernière pierre de l'assise : prend le reste
            }
            let (x0, x1) = (x.max(0), (x + longueur).min(l));
            let mut interdits: Vec<u8> = courante.last().map(|p| p.piece).into_iter().collect();
            interdits.extend(
                precedente
                    .iter()
                    .filter(|p| p.x0 <= x1 && p.x1 >= x0)
                    .map(|p| p.piece),
            );
            let numero = numero(&mut pierres, &interdits);
            let haut_pierre = if pierres.percent(30) && hauteur > cfg.course_min as i32 {
                hauteur - 1
            } else {
                hauteur
            };
            let saillante = pierres.percent(cfg.protrusion_percent);
            let valeur = pierre(numero);
            for yy in y..y + haut_pierre {
                for zz in (if saillante { -1 } else { 0 })..t {
                    for xx in x0..x1 {
                        g.set(VoxelCoord::new(xx, yy, zz), valeur);
                    }
                }
            }
            courante.push(Posee {
                x0,
                x1,
                piece: numero,
            });
            x += longueur + 1;
        }
        precedente = courante;
        y += hauteur + 1;
    }

    // 3. la mousse : pied du mur (face avant) et dessus
    poser_mousse(&mut g, cfg, classes, seed);
    DensePlan::new(g, vec![classes.stone(), classes.moss()])
}

/// Mousse en plaques (cellules hachées) aux bords effilochés (hachage par voxel) : tout vient d'entiers.
fn poser_mousse(g: &mut PlanGrid, cfg: &StoneWallConfig, classes: &BuildingClasses, seed: u64) {
    let (l, h, t) = (cfg.length as i32, cfg.height as i32, cfg.thickness as i32);
    let graine = hash_combine(seed, 0x4D_4F53);
    let tirage = |a: i64, b: i64, c: i64, k: u64| hash3(hash_combine(graine, k), a, b, c) % 100;
    let vert = |x: i32, y: i32, z: i32| {
        VoxelValue::new(
            classes.moss(),
            48 + (hash3(graine, i64::from(x), i64::from(y), i64::from(z)) % 64) as u8,
        )
    };
    // pied : la face avant visible (saillie comprise), plus dense au ras du sol
    let rangs = cfg.moss_foot_rows as i32;
    for y in 0..rangs.min(h) {
        let densite = u64::from(cfg.moss_foot_percent) * (rangs - y) as u64 / rangs as u64;
        for x in 0..l {
            let plaque = tirage(i64::from(x / 5), i64::from(y / 3), 1, 1) < densite;
            let bord = tirage(i64::from(x), i64::from(y), 2, 2) < 78;
            if !(plaque && bord) {
                continue;
            }
            if let Some(z) = (-1..t).find(|z| !g.get(VoxelCoord::new(x, y, *z)).is_air()) {
                g.set(VoxelCoord::new(x, y, z), vert(x, y, z));
            }
        }
    }
    // dessus : plaques sur la dernière rangée, et une touffe d'un voxel de plus par endroits
    for z in -1..t {
        for x in 0..l {
            if g.get(VoxelCoord::new(x, h - 1, z)).is_air() {
                continue;
            }
            let plaque = tirage(i64::from(x / 4), 7, i64::from(z / 2), 3) < u64::from(cfg.moss_top_percent);
            let bord = tirage(i64::from(x), 8, i64::from(z), 4) < 72;
            if plaque && bord {
                g.set(VoxelCoord::new(x, h - 1, z), vert(x, h - 1, z));
                if tirage(i64::from(x), 9, i64::from(z), 5) < 55 {
                    g.set(VoxelCoord::new(x, h, z), vert(x, h, z));
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn la_configuration_par_defaut_est_valide_et_les_bornes_sont_refusees() {
        assert!(StoneWallConfig::default().validate().is_ok());
        for mauvaise in [
            StoneWallConfig {
                length: 3,
                ..Default::default()
            },
            StoneWallConfig {
                course_max: 1,
                ..Default::default()
            },
            StoneWallConfig {
                stone_min: 20,
                stone_max: 10,
                ..Default::default()
            },
            StoneWallConfig {
                joint_recess: 2,
                ..Default::default()
            },
            StoneWallConfig {
                moss_top_percent: 101,
                ..Default::default()
            },
        ] {
            assert!(mauvaise.validate().is_err(), "{mauvaise:?}");
        }
    }
}
