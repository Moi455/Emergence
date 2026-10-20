//! Erreurs typées de la table de matières (les bibliothèques n'utilisent pas `anyhow`, docs/19 § 2.7).

use std::path::PathBuf;

/// Tout ce qui peut échouer en chargeant ou en construisant la table de matières.
#[derive(Debug, thiserror::Error, PartialEq, Eq)]
pub enum MaterialError {
    /// Lecture d'un fichier impossible.
    #[error("lecture de {chemin} impossible : {raison}")]
    Lecture { chemin: PathBuf, raison: String },
    /// Ligne ou en-tête du CSV invalide.
    #[error("materials.csv, ligne {ligne} : {raison}")]
    Csv { ligne: usize, raison: String },
    /// TOML d'aspect invalide (syntaxe ou champ inconnu).
    #[error("material_render.toml : {0}")]
    Toml(String),
    /// Valeur d'aspect hors des bornes permises.
    #[error("material_render.toml, [{section}] champ « {champ} » : {raison}")]
    Valeur {
        section: String,
        champ: &'static str,
        raison: String,
    },
    /// Un champ obligatoire manque dans `[default]`.
    #[error("material_render.toml : le champ « {0} » manque dans [default]")]
    ChampManquant(&'static str),
    /// Une entrée `[material.x]` désigne une classe absente du CSV.
    #[error("material_render.toml : la matière « {0} » n'existe pas dans materials.csv")]
    MatiereInconnue(String),
    /// Plus de 32 essences de végétation (la teinte n'a que 5 bits d'essence).
    #[error("trop d'essences de végétation : au plus {max}, « {cle} » est la {rang}e")]
    TropDEssences { max: usize, cle: String, rang: usize },
    /// Trop de rampes pour un rôle (4 au plus, 2 pour les fruits).
    #[error("essence « {cle} » : {demande} rampes demandées pour ce rôle, au plus {max}")]
    TropDeRampes { cle: String, demande: usize, max: usize },
}
