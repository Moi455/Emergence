//! Le CATALOGUE des recettes nommées (`engine/data/assets/*.toml`) : chaque recette a un identifiant stable, un
//! générateur du registre, une graine et ses paramètres. La scène, les tests d'empreinte et le jeu désignent une
//! recette par son identifiant, jamais par une liste de nombres.
//!
//! ```toml
//! [[asset]]
//! id = "maison_gravit"
//! generator = "house"
//! seed = 1
//! [asset.params]
//! seed_text = "gravit"
//! ```

use std::collections::BTreeMap;
use std::path::Path;
use std::sync::Arc;

use serde::Deserialize;

use crate::bati::GeneratorRegistry;
use crate::error::GenError;
use crate::generator::{GenParams, GenPlan};

/// Une recette nommée.
#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct AssetRecipe {
    /// Identifiant stable.
    pub id: String,
    /// Nom du générateur dans le registre.
    pub generator: String,
    /// Graine.
    #[serde(default)]
    pub seed: u64,
    /// Paramètres du générateur (champs de sa configuration).
    #[serde(default)]
    pub params: toml::Table,
    /// Description libre.
    #[serde(default)]
    pub note: String,
}

#[derive(Deserialize)]
struct Fichier {
    #[serde(default)]
    asset: Vec<AssetRecipe>,
}

/// L'ensemble des recettes nommées, par identifiant.
#[derive(Clone, Debug, Default)]
pub struct AssetCatalogue {
    par_id: BTreeMap<String, AssetRecipe>,
}

impl AssetCatalogue {
    /// Catalogue vide.
    pub fn new() -> Self {
        Self::default()
    }

    /// Ajoute les recettes d'un texte TOML ; refuse un identifiant déjà pris.
    pub fn add_text(&mut self, texte: &str) -> Result<(), GenError> {
        let f: Fichier =
            toml::from_str(texte).map_err(|e| GenError::BadParams(format!("catalogue : {e}")))?;
        for a in f.asset {
            if self.par_id.contains_key(&a.id) {
                return Err(GenError::BadParams(format!("recette « {} » en double", a.id)));
            }
            self.par_id.insert(a.id.clone(), a);
        }
        Ok(())
    }

    /// Charge tous les `*.toml` d'un dossier (dans l'ordre des noms) ; un dossier absent donne un catalogue vide.
    pub fn load_dir(dossier: &Path) -> Result<Self, GenError> {
        let mut c = Self::new();
        let Ok(entrees) = std::fs::read_dir(dossier) else {
            return Ok(c);
        };
        let mut chemins: Vec<_> = entrees
            .filter_map(Result::ok)
            .map(|e| e.path())
            .filter(|p| p.extension().is_some_and(|e| e == "toml"))
            .collect();
        chemins.sort();
        for p in chemins {
            let t = std::fs::read_to_string(&p)
                .map_err(|e| GenError::BadParams(format!("{}: {e}", p.display())))?;
            c.add_text(&t)
                .map_err(|e| GenError::BadParams(format!("{}: {e}", p.display())))?;
        }
        Ok(c)
    }

    /// La recette d'un identifiant.
    pub fn get(&self, id: &str) -> Result<&AssetRecipe, GenError> {
        self.par_id.get(id).ok_or_else(|| {
            GenError::BadParams(format!(
                "recette « {id} » absente de engine/data/assets ({} recettes)",
                self.par_id.len()
            ))
        })
    }

    /// Identifiants, triés.
    pub fn ids(&self) -> Vec<&str> {
        self.par_id.keys().map(String::as_str).collect()
    }

    /// Nombre de recettes.
    pub fn len(&self) -> usize {
        self.par_id.len()
    }

    /// Vrai si le catalogue est vide.
    pub fn is_empty(&self) -> bool {
        self.par_id.is_empty()
    }

    /// Fabrique le plan d'une recette avec le registre donné.
    pub fn plan(&self, id: &str, registre: &GeneratorRegistry) -> Result<Arc<dyn GenPlan>, GenError> {
        let a = self.get(id)?;
        let g = registre.get(&a.generator)?;
        let octets = serde_json::to_vec(
            &serde_json::to_value(&a.params).map_err(|e| GenError::BadParams(e.to_string()))?,
        )
        .map_err(|e| GenError::BadParams(e.to_string()))?;
        g.plan(&GenParams::new(g.id(), g.version(), octets), a.seed)
    }
}
