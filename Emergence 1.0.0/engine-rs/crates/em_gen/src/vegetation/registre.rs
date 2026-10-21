//! Enregistrement de la famille végétation dans le registre des générateurs du labo, et rampes de la saison.

use std::sync::Arc;

use em_material::VegetationRamps;

use super::compose::HedgeGenerator;
use super::crops::{CropClasses, CropGenerator, FernGenerator, MushroomGenerator};
use super::extra::{FallenLogGenerator, StumpGenerator, TreeSilhouetteGenerator};
use super::generators::{BushGenerator, TreeGenerator};
use super::species::{Season, SpeciesTable};
use crate::bati::GeneratorRegistry;
use crate::vxm::VxmClasses;

/// Ajoute au registre les générateurs de la végétation, sous leurs noms : `tree`, `bush`, `tree_silhouette`,
/// `hedge`, `stump`, `fallen_log`, et les motifs de 2 cm `crop`, `mushrooms`, `ferns`. Les essences sont celles de `engine/data/species.toml`.
pub fn register_default(r: &mut GeneratorRegistry) {
    let table = Arc::new(SpeciesTable::embedded());
    let c = VxmClasses::standard();
    let _ = r.register("tree", Box::new(TreeGenerator::new(table.clone(), c)));
    let _ = r.register("bush", Box::new(BushGenerator::new(table.clone(), c)));
    let _ = r.register(
        "tree_silhouette",
        Box::new(TreeSilhouetteGenerator::new(table.clone(), c)),
    );
    let _ = r.register("hedge", Box::new(HedgeGenerator::new(table.clone(), c)));
    let _ = r.register("stump", Box::new(StumpGenerator::new(table.clone(), c)));
    let _ = r.register("fallen_log", Box::new(FallenLogGenerator::new(table.clone(), c)));
    let cc = CropClasses::standard();
    let _ = r.register("crop", Box::new(CropGenerator::new(table.clone(), cc)));
    let _ = r.register("mushrooms", Box::new(MushroomGenerator::new(table.clone(), cc)));
    let _ = r.register("ferns", Box::new(FernGenerator::new(table, cc)));
}

/// Rampes de végétation d'une scène : si le texte TOML de la scène porte une clé `season` (`summer`, `spring`,
/// `autumn`, `winter`), les rampes de toutes les essences pour cette saison ; sinon un registre vide.
pub fn scene_ramps(texte_toml: &str) -> VegetationRamps {
    let Ok(t) = texte_toml.parse::<toml::Table>() else {
        return VegetationRamps::new();
    };
    let Some(s) = t.get("season").and_then(toml::Value::as_str) else {
        return VegetationRamps::new();
    };
    let season = Season::ALL
        .into_iter()
        .find(|x| x.name() == s)
        .unwrap_or(Season::Summer);
    SpeciesTable::embedded()
        .vegetation_ramps(season)
        .unwrap_or_else(|_| VegetationRamps::new())
}
