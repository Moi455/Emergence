//! Erreurs typées de l'hôte de rendu (docs/19 § 2.7, règle 7 : `thiserror` dans les bibliothèques).

use thiserror::Error;

/// Échec de la création du contexte GPU.
#[derive(Debug, Error)]
pub enum GpuError {
    /// Aucun adaptateur ne correspond à la demande ; le message dit quoi faire.
    #[error("{0}")]
    AdapterIntrouvable(String),
    /// L'adaptateur retenu n'offre pas les limites ou fonctions exigées.
    #[error("l'adaptateur « {adaptateur} » refuse les exigences de l'hôte : {details}")]
    LimitesInsuffisantes {
        /// Nom de l'adaptateur refusant.
        adaptateur: String,
        /// Une ligne par limite ou fonction manquante.
        details: String,
    },
    /// Le pilote a refusé de créer l'appareil malgré des limites annoncées suffisantes.
    #[error("création de l'appareil refusée : {0}")]
    AppareilRefuse(String),
}

/// Échec d'une cible d'image (fenêtre ou hors écran).
#[derive(Debug, Error)]
pub enum TargetError {
    /// Dimensions nulles ou hors de la limite de texture de l'appareil.
    #[error("dimensions de cible invalides : {largeur} x {hauteur} (maximum {maximum})")]
    Dimensions {
        /// Largeur demandée.
        largeur: u32,
        /// Hauteur demandée.
        hauteur: u32,
        /// Côté maximal permis.
        maximum: u32,
    },
    /// L'image doit être sautée (fenêtre masquée, surface périmée) ; on réessaie à la suivante.
    #[error("image sautée : {0}")]
    Sautee(&'static str),
    /// La surface est perdue ou invalide de façon durable.
    #[error("surface de présentation inutilisable : {0}")]
    Surface(String),
}

/// Échec du graphe de rendu.
#[derive(Debug, Error)]
pub enum GraphError {
    /// Deux passes portent le même nom.
    #[error("une passe nommée « {0} » existe déjà dans le graphe")]
    NomEnDouble(String),
    /// La cible n'a pas pu fournir d'image.
    #[error(transparent)]
    Cible(#[from] TargetError),
}

/// Échec de la lecture d'une texture ou de l'écriture du PNG.
#[derive(Debug, Error)]
pub enum CaptureError {
    /// Format de texture que la lecture ne sait pas convertir.
    #[error("format de texture non géré pour la capture : {0}")]
    Format(String),
    /// La texture n'a pas l'usage `COPY_SRC`.
    #[error("la texture à lire n'a pas l'usage COPY_SRC")]
    UsageManquant,
    /// Le mappage du tampon de lecture a échoué.
    #[error("lecture GPU impossible : {0}")]
    Lecture(String),
    /// Erreur d'entrée-sortie.
    #[error("écriture du PNG impossible : {0}")]
    Io(#[from] std::io::Error),
    /// Erreur de l'encodeur PNG.
    #[error("encodage PNG impossible : {0}")]
    Encodage(#[from] png::EncodingError),
}

/// Paramètre invalide à la construction d'un objet de rendu.
#[derive(Debug, Error)]
pub enum ParamError {
    /// Une valeur sort de son domaine ; le texte nomme le paramètre.
    #[error("paramètre invalide : {0}")]
    Invalide(String),
}

/// Échec du monde voxel côté GPU (configuration, saturation d'une mémoire).
#[derive(Debug, Error)]
pub enum WorldError {
    /// Une mémoire fixe est pleine : la capacité se règle dans `ClipmapConfig`.
    #[error(
        "mémoire GPU pleine : {ressource} (capacité {capacite}) ; augmenter la capacité dans ClipmapConfig"
    )]
    Sature {
        /// Ressource saturée.
        ressource: &'static str,
        /// Sa capacité.
        capacite: u64,
    },
    /// Configuration refusée.
    #[error("configuration de clipmap invalide : {0}")]
    Config(String),
    /// Niveau hors de la clipmap.
    #[error("niveau {niveau} hors de la clipmap ({niveaux} niveaux)")]
    Niveau {
        /// Niveau demandé.
        niveau: u8,
        /// Niveaux disponibles.
        niveaux: u8,
    },
    /// Le chunk n'est pas dans la fenêtre du niveau.
    #[error("le chunk ({x}, {y}, {z}) est hors de la fenêtre du niveau {niveau}")]
    HorsFenetre {
        /// Niveau.
        niveau: u8,
        /// Clé du chunk, x.
        x: i32,
        /// Clé du chunk, y.
        y: i32,
        /// Clé du chunk, z.
        z: i32,
    },
}
