//! Le registre des générateurs des familles bâtiments, props et rochers : on ajoute ses recettes au registre du bâti
//! de L23p (`stone_wall`, `beam`, `post`, `roof`) sous des noms stables.

use super::ids;
use super::kit::matieres::Matieres;
use super::maison::HouseGenerator;
use crate::bati::{BuildingClasses, GeneratorRegistry};
use crate::generator::Generator;

/// Registre complet : le bâti de L23p plus les recettes de L35 à L37.
pub fn registre_complet(classes: BuildingClasses, matieres: Matieres) -> GeneratorRegistry {
    let mut r = GeneratorRegistry::bati(classes);
    let recettes: Vec<(&str, Box<dyn Generator>)> = vec![
        ("house", Box::new(HouseGenerator::new(matieres))),
        (
            "building",
            Box::new(super::village::BuildingGenerator::new(matieres)),
        ),
        ("rock", Box::new(crate::rochers::RockGenerator::new(matieres))),
        ("prop", Box::new(crate::props::PropGenerator::new(matieres))),
    ];
    for (nom, g) in recettes {
        r.register(nom, g).expect("noms et identifiants distincts");
    }
    let _ = ids::HOUSE;
    r
}
