//! Les bâtiments du village (L35) hors maison : grange, étable, forge, moulins, taverne, église et chapelle, halle,
//! boulangerie, cabane de bûcheron, tour de guet, rempart et porte, puits, ponts, mairie. Un seul générateur
//! `building` dont la configuration choisit la recette ; la graine tire les dimensions, la pierre, la couverture et les
//! accents. Les recettes de maison (taverne, boulangerie, mairie) passent par `HouseGenerator` avec ses forçages.

mod bld;
mod civic;
mod rural;

use std::sync::Arc;

use serde::{Deserialize, Serialize};

pub use bld::{Bld, Rect};

use super::ids;
use super::kit::matieres::Matieres;
use super::kit::plan::{Placement, ShapePlan};
use super::maison::{HouseConfig, HouseGenerator};
use crate::error::GenError;
use crate::generator::{GenParams, GenPlan, Generator, GeneratorId};

/// Les recettes de bâtiments (noms stables).
pub const KINDS: &[&str] = &[
    "grange",
    "etable",
    "forge",
    "moulin_vent",
    "moulin_eau",
    "taverne",
    "eglise",
    "chapelle",
    "halle",
    "boulangerie",
    "cabane_bucheron",
    "tour_guet",
    "rempart_porte",
    "puits",
    "pont_pierre",
    "pont_bois",
    "mairie",
];

/// Configuration de la recette de bâtiment.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct VillageConfig {
    /// Nom de la recette (`KINDS`).
    pub kind: String,
    /// Portée d'un pont en voxels (0 : 120 pour la pierre, 100 pour le bois).
    pub span: i32,
    /// Couverture imposée (`slate`, `shingle`, `terracotta`, `thatch`) ; vide : tirée de la graine.
    pub tile: String,
}

impl Default for VillageConfig {
    fn default() -> Self {
        Self {
            kind: "grange".into(),
            span: 0,
            tile: String::new(),
        }
    }
}

impl VillageConfig {
    /// Paramètres de générateur de cette configuration.
    pub fn to_params(&self) -> Result<GenParams, GenError> {
        GenParams::json(ids::BUILDING, 1, self)
    }
}

/// Le générateur de bâtiments.
#[derive(Clone, Debug)]
pub struct BuildingGenerator {
    matieres: Matieres,
}

impl BuildingGenerator {
    /// Crée le générateur.
    pub fn new(matieres: Matieres) -> Self {
        Self { matieres }
    }

    /// Construit le plan.
    pub fn build(&self, cfg: &VillageConfig, seed: u64) -> Result<ShapePlan, GenError> {
        use crate::batiments::maison::params::TileKind;
        let m = self.matieres;
        // recettes de maison : forçages de la maison, graine texte déterministe
        let maison = |extras: &str, c: HouseConfig| -> Result<ShapePlan, GenError> {
            let c = HouseConfig {
                extras: extras.to_owned(),
                ..c
            };
            let texte = [
                "clerc", "aubert", "hamel", "morel", "gravit", "bastien", "lorrain", "dumont",
            ][(seed % 8) as usize];
            Ok(HouseGenerator::new(m)
                .try_build(&format!("{texte}{seed}"), &c)?
                .shape)
        };
        match cfg.kind.as_str() {
            "taverne" => {
                return maison(
                    "taverne",
                    HouseConfig {
                        stories: 2,
                        plan: "l".into(),
                        walls: "timber_plaster".into(),
                        width: 150,
                        depth: 110,
                        shed: "non".into(),
                        ..HouseConfig::default()
                    },
                );
            }
            "boulangerie" => {
                return maison(
                    "boulangerie",
                    HouseConfig {
                        stories: 1,
                        plan: "rect".into(),
                        walls: "timber_stone".into(),
                        tile: "terracotta".into(),
                        shed: "non".into(),
                        ..HouseConfig::default()
                    },
                );
            }
            "mairie" => {
                return maison(
                    "mairie",
                    HouseConfig {
                        stories: 2,
                        plan: "rect".into(),
                        walls: "stone".into(),
                        tile: "slate".into(),
                        width: 190,
                        depth: 120,
                        shed: "non".into(),
                        ..HouseConfig::default()
                    },
                );
            }
            _ => {}
        }
        let tile = match cfg.tile.as_str() {
            "" => None,
            "slate" => Some(TileKind::Slate),
            "shingle" => Some(TileKind::Shingle),
            "terracotta" => Some(TileKind::Terracotta),
            "thatch" => Some(TileKind::Thatch),
            autre => return Err(GenError::BadParams(format!("couverture « {autre} » inconnue"))),
        };
        let tile = tile.or(match cfg.kind.as_str() {
            "grange" | "etable" => Some(if seed.is_multiple_of(2) {
                TileKind::Thatch
            } else {
                TileKind::Shingle
            }),
            "cabane_bucheron" | "halle" | "tour_guet" => Some(TileKind::Shingle),
            "eglise" | "chapelle" | "rempart_porte" => Some(TileKind::Slate),
            _ => None,
        });
        let mut b = Bld::new(m, seed, tile);
        let (cx, cz) = match cfg.kind.as_str() {
            "grange" => rural::grange(&mut b),
            "etable" => rural::etable(&mut b),
            "forge" => rural::forge(&mut b),
            "moulin_vent" => rural::moulin_vent(&mut b),
            "moulin_eau" => rural::moulin_eau(&mut b),
            "cabane_bucheron" => rural::cabane(&mut b),
            "eglise" => civic::eglise(&mut b, false),
            "chapelle" => civic::eglise(&mut b, true),
            "halle" => civic::halle(&mut b),
            "tour_guet" => civic::tour_guet(&mut b),
            "rempart_porte" => civic::rempart_porte(&mut b),
            "puits" => civic::puits(&mut b),
            "pont_pierre" => civic::pont_pierre(&mut b, if cfg.span > 0 { cfg.span } else { 120 }),
            "pont_bois" => civic::pont_bois(&mut b, if cfg.span > 0 { cfg.span } else { 100 }),
            autre => {
                return Err(GenError::BadParams(format!(
                    "bâtiment « {autre} » inconnu (disponibles : {})",
                    KINDS.join(", ")
                )));
            }
        };
        let placement = Placement {
            dx: -cx,
            dy: 0,
            dz: cz,
            mirror_z: true,
        };
        Ok(ShapePlan::new(b.finish(), placement, 50, m.priority()))
    }
}

impl Generator for BuildingGenerator {
    fn id(&self) -> GeneratorId {
        ids::BUILDING
    }

    fn version(&self) -> u32 {
        1
    }

    fn plan(&self, params: &GenParams, seed: u64) -> Result<Arc<dyn GenPlan>, GenError> {
        let cfg: VillageConfig = params.decode_json(ids::BUILDING)?;
        Ok(Arc::new(self.build(&cfg, seed)?))
    }
}
