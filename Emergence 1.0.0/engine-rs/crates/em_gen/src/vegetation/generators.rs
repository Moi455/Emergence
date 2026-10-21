//! Les générateurs de la famille végétation : `TreeGenerator` (arbres) et `BushGenerator` (arbustes, topiaire).
//! Tous deux construisent un `PlantPlan` ; seules changent les bornes de hauteur et le droit à la taille topiaire.

use std::sync::Arc;

use serde::{Deserialize, Serialize};

use super::fx::{Stream, UN, VOX_PAR_M};
use super::plan::{PlantPlan, PlantRequest};
use super::species::{Season, Species, SpeciesTable};
use super::topiary::TopiaryShape;
use crate::error::GenError;
use crate::generator::{GenParams, GenPlan, Generator, GeneratorId};
use crate::vxm::VxmClasses;

fn feuillage_plein() -> u16 {
    1000
}

fn ete() -> Season {
    Season::Summer
}

/// Paramètres d'un arbre (docs/19b L30).
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct TreeParams {
    /// Clé de l'essence (`chene`, `bouleau`, ...).
    pub species: String,
    /// Hauteur en millimètres ; 0 = tirée dans la fourchette de l'essence.
    #[serde(default)]
    pub height_mm: u32,
    /// Saison.
    #[serde(default = "ete")]
    pub season: Season,
    /// Densité du feuillage en millièmes (1000 = pleine).
    #[serde(default = "feuillage_plein")]
    pub leaf_density_permille: u16,
}

impl TreeParams {
    /// Paramètres de générateur de cette configuration.
    pub fn to_params(&self) -> Result<GenParams, GenError> {
        GenParams::json(GeneratorId::TREE, 1, self)
    }
}

/// Paramètres d'un arbuste : ceux d'un arbre plus la taille topiaire.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct BushParams {
    /// Paramètres communs (hauteur en 0,3 à 2 m).
    #[serde(flatten)]
    pub plant: TreeParams,
    /// Taille topiaire : le feuillage devient une coque lisse, sans fleurs ni fruits.
    #[serde(default)]
    pub topiary: Option<TopiaryShape>,
}

impl BushParams {
    /// Paramètres de générateur de cette configuration.
    pub fn to_params(&self) -> Result<GenParams, GenError> {
        GenParams::json(GeneratorId::BUSH, 1, self)
    }
}

/// Bornes de hauteur d'une famille de sujets, en mètres (Q16 de voxel).
#[derive(Copy, Clone, Debug)]
struct Hauteurs {
    min: i64,
    max: i64,
}

/// Hauteur d'un arbre (2 à 20 m) : celle demandée, ou tirée dans la fourchette de l'essence.
pub fn hauteur_arbre(sp: &Species, h_mm: u32, seed: u64) -> i64 {
    hauteur(
        sp,
        h_mm,
        seed,
        Hauteurs {
            min: 2 * VOX_PAR_M * UN,
            max: 20 * VOX_PAR_M * UN,
        },
    )
}

fn hauteur(sp: &Species, h_mm: u32, seed: u64, b: Hauteurs) -> i64 {
    let h = if h_mm == 0 {
        let mut s = Stream::new(seed, 0x4845_4947); // « HEIG »
        let t = s.unit();
        sp.h_range.0 + super::fx::mul(t, sp.h_range.1 - sp.h_range.0)
    } else {
        i64::from(h_mm) * VOX_PAR_M * UN / 1000
    };
    h.clamp(b.min, b.max)
}

fn construire(
    table: &SpeciesTable,
    classes: &VxmClasses,
    p: &TreeParams,
    topiary: Option<TopiaryShape>,
    bornes: Hauteurs,
    bush: bool,
    seed: u64,
) -> Result<Arc<PlantPlan>, GenError> {
    let sp = table.get(&p.species)?;
    if sp.is_bush() != bush {
        return Err(GenError::BadParams(format!(
            "l'essence « {} » est {} : utiliser le générateur {}",
            sp.key,
            if sp.is_bush() { "un arbuste" } else { "un arbre" },
            if sp.is_bush() { "bush" } else { "tree" }
        )));
    }
    if p.leaf_density_permille > 4000 {
        return Err(GenError::BadParams(
            "densité de feuillage hors de 0..=4000 millièmes".into(),
        ));
    }
    let req = PlantRequest {
        species: sp,
        seed,
        height: hauteur(sp, p.height_mm, seed, bornes),
        season: p.season,
        leaf_density: i64::from(p.leaf_density_permille) * UN / 1000,
        topiary,
    };
    Ok(Arc::new(PlantPlan::build(&req, classes)?))
}

/// Générateur d'arbres (2 à 20 m).
#[derive(Clone, Debug)]
pub struct TreeGenerator {
    table: Arc<SpeciesTable>,
    classes: VxmClasses,
}

impl TreeGenerator {
    /// Générateur sur une table d'essences et des classes de matière injectées.
    pub fn new(table: Arc<SpeciesTable>, classes: VxmClasses) -> Self {
        Self { table, classes }
    }
}

impl TreeGenerator {
    /// Le plan concret (avec ses mesures), pour les essais et les bancs.
    pub fn plant_plan(&self, params: &GenParams, seed: u64) -> Result<Arc<PlantPlan>, GenError> {
        let p: TreeParams = params.decode_json(GeneratorId::TREE)?;
        let bornes = Hauteurs {
            min: 2 * VOX_PAR_M * UN,
            max: 20 * VOX_PAR_M * UN,
        };
        construire(&self.table, &self.classes, &p, None, bornes, false, seed)
    }
}

impl Generator for TreeGenerator {
    fn id(&self) -> GeneratorId {
        GeneratorId::TREE
    }

    fn version(&self) -> u32 {
        1
    }

    fn plan(&self, params: &GenParams, seed: u64) -> Result<Arc<dyn GenPlan>, GenError> {
        Ok(self.plant_plan(params, seed)?)
    }
}

/// Générateur d'arbustes (0,3 à 2 m), avec taille topiaire.
#[derive(Clone, Debug)]
pub struct BushGenerator {
    table: Arc<SpeciesTable>,
    classes: VxmClasses,
}

impl BushGenerator {
    /// Générateur sur une table d'essences et des classes de matière injectées.
    pub fn new(table: Arc<SpeciesTable>, classes: VxmClasses) -> Self {
        Self { table, classes }
    }
}

impl BushGenerator {
    /// Le plan concret (avec ses mesures), pour les essais et les bancs.
    pub fn plant_plan(&self, params: &GenParams, seed: u64) -> Result<Arc<PlantPlan>, GenError> {
        let p: BushParams = params.decode_json(GeneratorId::BUSH)?;
        let bornes = Hauteurs {
            min: 3 * VOX_PAR_M * UN / 10,
            max: 2 * VOX_PAR_M * UN,
        };
        construire(
            &self.table,
            &self.classes,
            &p.plant,
            p.topiary,
            bornes,
            true,
            seed,
        )
    }
}

impl Generator for BushGenerator {
    fn id(&self) -> GeneratorId {
        GeneratorId::BUSH
    }

    fn version(&self) -> u32 {
        1
    }

    fn plan(&self, params: &GenParams, seed: u64) -> Result<Arc<dyn GenPlan>, GenError> {
        Ok(self.plant_plan(params, seed)?)
    }
}
