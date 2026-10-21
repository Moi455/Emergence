//! Erreurs typées de `em_mesh`.

/// Tout ce qui peut échouer en construisant un quad ou en maillant une région.
#[derive(Debug, thiserror::Error, PartialEq, Eq)]
pub enum MeshError {
    /// Un champ d'un quad dépasse la place qu'il a dans le format de 12 octets.
    #[error("quad invalide : {0}")]
    QuadInvalide(String),
    /// Le voisinage fourni n'a pas la taille d'un chunk et de sa bordure d'un voxel.
    #[error("voisinage invalide : {0}")]
    VoisinageInvalide(String),
}
