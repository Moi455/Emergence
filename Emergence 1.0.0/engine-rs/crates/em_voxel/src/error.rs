//! Erreurs typées de `em_voxel`.

use em_core::IoError;
use thiserror::Error;

/// Échec du décodage d'une brique, d'un chunk ou d'une liste d'éditions : le format est refusé en fermant.
#[derive(Debug, Clone, PartialEq, Eq, Error)]
pub enum DecodeError {
    /// Le tampon est tronqué.
    #[error("lecture impossible : {0}")]
    Io(#[from] IoError),
    /// Étiquette de brique inconnue (attendu 0 ou 1).
    #[error("étiquette de brique inconnue : {0}")]
    EtiquetteInconnue(u8),
    /// Nombre de bits par indice hors de {1, 2, 4, 8, 16}.
    #[error("nombre de bits invalide pour une brique : {0} (attendu 1, 2, 4, 8 ou 16)")]
    BitsInvalides(u8),
    /// Taille de palette incompatible avec le nombre de bits.
    #[error("taille de palette invalide : {longueur} entrée(s) pour {bits} bit(s)")]
    PaletteInvalide {
        /// Nombre de bits annoncé.
        bits: u8,
        /// Longueur de palette annoncée.
        longueur: u16,
    },
    /// Un indice désigne une entrée absente de la palette.
    #[error("indice {indice} hors de la palette de {longueur} entrée(s)")]
    IndiceHorsPalette {
        /// Indice lu.
        indice: u16,
        /// Longueur de la palette.
        longueur: u16,
    },
    /// La signature `EMCK` manque.
    #[error("signature de chunk invalide")]
    SignatureInvalide,
    /// Version de format plus récente que celle que ce code sait lire.
    #[error("version de chunk non gérée : {0}")]
    VersionFuture(u8),
    /// La somme de contrôle ne correspond pas.
    #[error("somme de contrôle invalide (attendu {attendu:#010x}, calculé {calcule:#010x})")]
    CrcInvalide {
        /// Valeur stockée.
        attendu: u32,
        /// Valeur recalculée.
        calcule: u32,
    },
    /// Des octets restent après la fin de l'objet décodé.
    #[error("{0} octet(s) en trop après la fin de l'objet")]
    OctetsEnTrop(usize),
    /// Numéro de brique hors de 0..512.
    #[error("numéro de brique invalide : {0}")]
    BriqueInvalide(u16),
    /// Briques d'une liste d'éditions non triées ou dupliquées.
    #[error("briques non strictement croissantes dans la liste d'éditions")]
    BriquesDesordonnees,
}

/// Violation d'un invariant de dimension d'un chunk.
#[derive(Debug, Clone, PartialEq, Eq, Error)]
pub enum ChunkError {
    /// Le tableau dense ne compte pas 64³ voxels.
    #[error("tableau dense de {recu} voxel(s) au lieu de {attendu}")]
    TailleDense {
        /// Taille attendue.
        attendu: usize,
        /// Taille reçue.
        recu: usize,
    },
}

/// Violation d'un invariant de `CompositeSource`.
#[derive(Debug, Clone, PartialEq, Eq, Error)]
pub enum CompositeError {
    /// Une composition sans aucune couche n'a pas de sens.
    #[error("une source composite exige au moins une couche")]
    AucuneCouche,
}
