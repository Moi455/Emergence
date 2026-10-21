//! Les PROPS (L36) : tonneaux, caisses, sacs, charrette, étal, mobilier de plein air, clôtures, portail, enseignes,
//! lanternes, foin, bois, feu de camp, tombes, panneaux, puits de décor, échelle, râtelier, ruches, et les petits
//! objets (bougie, vaisselle, pain, fruits, livre, clé, outils) en voxels de 2 cm. Un seul générateur `prop`, dont la
//! configuration choisit la recette par son nom et la graine tire les variantes.

// Les recettes sont des PORTS fidèles de règles écrites en coordonnées entières : les bornes explicites
// (`a >= 5 && a < 10`) restent lisibles comme dans le générateur d'origine.
#![allow(
    clippy::manual_range_contains,
    clippy::too_many_arguments,
    clippy::needless_range_loop,
    clippy::collapsible_if,
    clippy::int_plus_one,
    clippy::identity_op
)]

mod builder;
mod kinds;
mod tex;

use std::sync::Arc;

use serde::{Deserialize, Serialize};

pub use builder::PropBuilder;
pub use tex::Tex;

use crate::batiments::ids;
use crate::batiments::kit::matieres::Matieres;
use crate::batiments::kit::plan::{Placement, ShapePlan};
use crate::error::GenError;
use crate::generator::{GenParams, GenPlan, Generator, GeneratorId};

/// Les recettes de props (noms stables) et si elles sont « petites » (voxel de 2 cm).
pub const KINDS: &[(&str, bool)] = &[
    ("tonneau", false),
    ("caisse", false),
    ("sacs", false),
    ("charrette", false),
    ("etal", false),
    ("banc", false),
    ("table", false),
    ("chaise", false),
    ("cloture_bois", false),
    ("cloture_pierre", false),
    ("treillis", false),
    ("portail", false),
    ("enseigne", false),
    ("lanterne", false),
    ("foin", false),
    ("tas_bois", false),
    ("feu_camp", false),
    ("tombe", false),
    ("panneau", false),
    ("puits_deco", false),
    ("echelle", false),
    ("ratelier", false),
    ("ruche", true),
    ("bougie", true),
    ("vaisselle", true),
    ("pain", true),
    ("fruits", true),
    ("livre", true),
    ("cle", true),
    ("outils", true),
];

/// Configuration de la recette de prop.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct PropConfig {
    /// Nom de la recette (`KINDS`).
    pub kind: String,
    /// Taille du voxel en millimètres ; 0 : celle de la recette (50, ou 20 pour le petit).
    pub voxel_mm: u32,
}

impl Default for PropConfig {
    fn default() -> Self {
        Self {
            kind: "tonneau".into(),
            voxel_mm: 0,
        }
    }
}

impl PropConfig {
    /// Paramètres de générateur de cette configuration.
    pub fn to_params(&self) -> Result<GenParams, GenError> {
        GenParams::json(ids::PROP, 1, self)
    }
}

/// Le générateur de props.
#[derive(Clone, Debug)]
pub struct PropGenerator {
    matieres: Matieres,
}

impl PropGenerator {
    /// Crée le générateur.
    pub fn new(matieres: Matieres) -> Self {
        Self { matieres }
    }

    /// Construit le plan d'un prop.
    pub fn build(&self, cfg: &PropConfig, seed: u64) -> Result<ShapePlan, GenError> {
        let (parts, unit) = self.assemble(cfg, seed)?;
        // repère du monde : devant (z local +) vers le sud (z monde -)
        let placement = Placement {
            mirror_z: true,
            ..Placement::IDENTITE
        };
        Ok(ShapePlan::new(
            parts,
            placement,
            unit as u32,
            self.matieres.priority(),
        ))
    }

    /// Les parties d'un prop dans son repère local (pour les composer dans un bâtiment) à la taille de voxel de 50 mm.
    pub fn parts(
        &self,
        cfg: &PropConfig,
        seed: u64,
    ) -> Result<Vec<Box<dyn crate::batiments::kit::plan::Part>>, GenError> {
        Ok(self.assemble(cfg, seed)?.0)
    }

    fn assemble(
        &self,
        cfg: &PropConfig,
        seed: u64,
    ) -> Result<(Vec<Box<dyn crate::batiments::kit::plan::Part>>, i32), GenError> {
        let Some((_, petit)) = KINDS.iter().find(|(n, _)| *n == cfg.kind) else {
            let noms: Vec<&str> = KINDS.iter().map(|(n, _)| *n).collect();
            return Err(GenError::BadParams(format!(
                "prop « {} » inconnu (disponibles : {})",
                cfg.kind,
                noms.join(", ")
            )));
        };
        let unit = match cfg.voxel_mm {
            0 => {
                if *petit {
                    20
                } else {
                    50
                }
            }
            20 | 50 => cfg.voxel_mm as i32,
            autre => {
                return Err(GenError::BadParams(format!(
                    "voxel_mm {autre} : 20 ou 50 attendu"
                )));
            }
        };
        let mut b = PropBuilder::new(self.matieres, unit, seed);
        match cfg.kind.as_str() {
            "tonneau" => b.tonneau(),
            "caisse" => b.caisse(),
            "sacs" => b.sacs(),
            "charrette" => b.charrette(),
            "etal" => b.etal(),
            "banc" => b.banc(),
            "table" => b.table(),
            "chaise" => b.chaise(),
            "cloture_bois" => b.cloture_bois(),
            "cloture_pierre" => b.cloture_pierre(),
            "treillis" => b.treillis(),
            "portail" => b.portail(),
            "enseigne" => b.enseigne(),
            "lanterne" => b.lanterne(),
            "foin" => b.foin(),
            "tas_bois" => b.tas_bois(),
            "feu_camp" => b.feu_camp(),
            "tombe" => b.tombe(),
            "panneau" => b.panneau(),
            "puits_deco" => b.puits_deco(),
            "echelle" => b.echelle(),
            "ratelier" => b.ratelier(),
            "ruche" => b.ruche(),
            "bougie" => b.bougie(),
            "vaisselle" => b.vaisselle(),
            "pain" => b.pain(),
            "fruits" => b.fruits(),
            "livre" => b.livre(),
            "cle" => b.cle(),
            _ => b.outils(),
        }
        Ok((b.finish(), unit))
    }
}

impl Generator for PropGenerator {
    fn id(&self) -> GeneratorId {
        ids::PROP
    }

    fn version(&self) -> u32 {
        1
    }

    fn plan(&self, params: &GenParams, seed: u64) -> Result<Arc<dyn GenPlan>, GenError> {
        let cfg: PropConfig = params.decode_json(ids::PROP)?;
        Ok(Arc::new(self.build(&cfg, seed)?))
    }
}
