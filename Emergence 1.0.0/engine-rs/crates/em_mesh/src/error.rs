//! Erreurs typées de `em_mesh`.

/// Tout ce qui peut échouer en construisant un quad ou en maillant une région.
#[derive(Debug, thiserror::Error, PartialEq, Eq)]
pub enum MeshError {
    /// Un champ d'un quad dépasse la place qu'il a dans le format de 12 octets.
    #[error("quad invalide : {0}")]
    QuadInvalide(String),
    /// Le voisinage fourni n'a pas la taille d'un chunk et de sa bordure.
    #[error("voisinage invalide : {0}")]
    VoisinageInvalide(String),
}

/// Réglage hors de sa plage (paramètres de l'occlusion creuse).
#[derive(Debug, thiserror::Error, PartialEq)]
pub enum ParamError {
    /// Un paramètre dépasse sa plage.
    #[error("{nom} = {valeur} hors de {min}..={max}")]
    HorsPlage {
        /// Nom du paramètre.
        nom: &'static str,
        /// Valeur refusée.
        valeur: f32,
        /// Borne basse.
        min: f32,
        /// Borne haute.
        max: f32,
    },
    /// Les niveaux d'occlusion ne sont pas croissants dans (0, 1] avec un dernier niveau dégagé (1).
    #[error("niveaux d'occlusion {0:?} : il faut croissants, dans (0, 1], le dernier égal à 1")]
    NiveauxInvalides([f32; 4]),
}
