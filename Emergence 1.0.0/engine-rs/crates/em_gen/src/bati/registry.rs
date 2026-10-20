//! Registre des générateurs par nom : la scène désigne une recette par son nom (`stone_wall`, `beam`, `post`,
//! `roof`), jamais par un `match` : le polymorphisme passe par le trait `Generator`.

use std::collections::BTreeMap;

use super::beam::BeamGenerator;
use super::classes::BuildingClasses;
use super::post::PostGenerator;
use super::roof::RoofGenerator;
use super::wall::StoneWallGenerator;
use crate::error::GenError;
use crate::generator::{Generator, GeneratorId};

/// Les générateurs connus, par nom.
#[derive(Default)]
pub struct GeneratorRegistry {
    par_nom: BTreeMap<String, Box<dyn Generator>>,
}

impl GeneratorRegistry {
    /// Registre vide.
    pub fn new() -> Self {
        Self::default()
    }

    /// Les quatre recettes du bâti (L23p), avec leurs classes de matière.
    pub fn bati(classes: BuildingClasses) -> Self {
        let mut r = Self::new();
        let sources: [(&str, Box<dyn Generator>); 4] = [
            ("stone_wall", Box::new(StoneWallGenerator::new(classes))),
            ("beam", Box::new(BeamGenerator::new(classes))),
            ("post", Box::new(PostGenerator::new(classes))),
            ("roof", Box::new(RoofGenerator::new(classes))),
        ];
        for (nom, g) in sources {
            r.register(nom, g).expect("noms et identifiants distincts");
        }
        r
    }

    /// Enregistre un générateur ; refuse un nom ou un identifiant déjà pris.
    pub fn register(&mut self, nom: &str, generator: Box<dyn Generator>) -> Result<(), GenError> {
        let id = generator.id();
        if self.par_nom.contains_key(nom) || self.par_nom.values().any(|g| g.id() == id) {
            return Err(GenError::BadParams(format!(
                "générateur « {nom} » (identifiant {}) déjà enregistré",
                id.raw()
            )));
        }
        self.par_nom.insert(nom.to_owned(), generator);
        Ok(())
    }

    /// Le générateur de ce nom.
    pub fn get(&self, nom: &str) -> Result<&dyn Generator, GenError> {
        self.par_nom.get(nom).map(Box::as_ref).ok_or_else(|| {
            GenError::BadParams(format!(
                "générateur « {nom} » inconnu (disponibles : {})",
                self.noms().join(", ")
            ))
        })
    }

    /// Noms enregistrés, triés.
    pub fn noms(&self) -> Vec<&str> {
        self.par_nom.keys().map(String::as_str).collect()
    }

    /// Identifiant du générateur d'un nom.
    pub fn id_of(&self, nom: &str) -> Result<GeneratorId, GenError> {
        self.get(nom).map(Generator::id)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn les_quatre_recettes_sont_enregistrees_et_un_nom_inconnu_est_refuse() {
        let r = GeneratorRegistry::bati(BuildingClasses::standard());
        assert_eq!(r.noms(), ["beam", "post", "roof", "stone_wall"]);
        assert_eq!(r.id_of("stone_wall").unwrap(), GeneratorId::STONE_WALL);
        assert!(r.get("cheminee").is_err());
    }

    #[test]
    fn un_doublon_est_refuse() {
        let mut r = GeneratorRegistry::bati(BuildingClasses::standard());
        let doublon = Box::new(BeamGenerator::new(BuildingClasses::standard()));
        assert!(r.register("autre_poutre", doublon).is_err());
    }
}
