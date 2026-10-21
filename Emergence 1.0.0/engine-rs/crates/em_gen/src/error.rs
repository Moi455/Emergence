//! Erreurs typées de `em_gen` (les bibliothèques n'utilisent pas `anyhow`, docs/19 § 2.7).

use std::path::PathBuf;

use thiserror::Error;

/// Refus d'un fichier `.vxm` : le format est strict, tout ce qui est douteux est rejeté en fermant
/// (docs/19a § 1 : une version future est refusée, jamais devinée).
#[derive(Debug, Clone, PartialEq, Eq, Error)]
pub enum VxmError {
    /// Fichier plus court que le minimum possible (signature, version, drapeaux, longueur JSON, CRC).
    #[error("fichier trop court : {0} octet(s)")]
    TropCourt(usize),
    /// La signature `VXM1` manque.
    #[error("signature « VXM1 » absente")]
    Signature,
    /// La somme de contrôle ne correspond pas.
    #[error("CRC32 invalide (attendu {attendu:#010x}, calculé {calcule:#010x})")]
    Crc {
        /// Valeur stockée en fin de fichier.
        attendu: u32,
        /// Valeur recalculée.
        calcule: u32,
    },
    /// Version du format que ce code ne sait pas lire.
    #[error("version {0} du format .vxm non prise en charge (attendu 1)")]
    VersionNonGeree(u16),
    /// Des drapeaux inconnus sont levés.
    #[error("drapeaux inconnus : {0:#06x}")]
    DrapeauxInconnus(u16),
    /// Le fichier se termine avant la fin d'une section.
    #[error("fichier tronqué")]
    Tronque,
    /// L'en-tête JSON n'est pas lisible.
    #[error("en-tête JSON illisible : {0}")]
    EnTeteJson(String),
    /// L'en-tête est lisible mais incohérent.
    #[error("en-tête invalide : {0}")]
    EnTeteInvalide(String),
    /// Le voxel du fichier n'est pas celui de la grille du monde (5 cm).
    #[error("voxel de {0} m dans le fichier au lieu de 0,05 m")]
    VoxelHorsGrille(String),
    /// Un LOD hors de 0..=5.
    #[error("LOD {0} hors de 0..=5")]
    LodHorsPlage(u8),
    /// Le LOD 0 manque : aucun repli n'est possible.
    #[error("le LOD 0 est absent ou vide")]
    LodZeroAbsent,
    /// La section lue n'est pas celle que l'en-tête annonce.
    #[error("section de LOD {lu} inattendue (en-tête : {attendu})")]
    LodInattendu {
        /// LOD lu dans la section.
        lu: u8,
        /// LOD annoncé par l'en-tête.
        attendu: u8,
    },
    /// Octets réservés non nuls.
    #[error("LOD {0} : octets réservés non nuls")]
    ReservesNonNuls(u8),
    /// Boîte de LOD invalide (dimension nulle ou trop grande, coin hors de la plage).
    #[error("LOD {lod} : boîte invalide ({raison})")]
    BoiteInvalide {
        /// LOD fautif.
        lod: u8,
        /// Détail.
        raison: String,
    },
    /// Corps zlib invalide.
    #[error("LOD {lod} : corps zlib invalide ({raison})")]
    CorpsZlib {
        /// LOD fautif.
        lod: u8,
        /// Détail.
        raison: String,
    },
    /// Taille du corps différente de celle que le nombre de voxels impose.
    #[error("LOD {lod} : corps de {lu} octet(s) au lieu de {attendu}")]
    CorpsTaille {
        /// LOD fautif.
        lod: u8,
        /// Taille lue.
        lu: u64,
        /// Taille attendue.
        attendu: u64,
    },
    /// Une coordonnée sort de la boîte du LOD.
    #[error("LOD {lod} : coordonnée {axe} hors de la boîte")]
    CoordHorsBoite {
        /// LOD fautif.
        lod: u8,
        /// Axe (`x`, `y` ou `z`).
        axe: char,
    },
    /// Sorte de voxel hors de 1..=5.
    #[error("LOD {lod} : sorte {sorte} hors de 1..=5")]
    SorteInvalide {
        /// LOD fautif.
        lod: u8,
        /// Sorte lue.
        sorte: u8,
    },
    /// Indice de rampe absent de l'en-tête.
    #[error("LOD {lod} : indice de rampe {rampe} hors de l'en-tête")]
    RampeHorsEnTete {
        /// LOD fautif.
        lod: u8,
        /// Indice lu.
        rampe: u8,
    },
    /// Rang de la rampe dans son rôle trop grand pour les 2 bits de variante de la teinte.
    #[error("rampe {0} : rang dans son rôle au-delà de 3 (la teinte n'a que 2 bits de variante)")]
    RangDeRampeTropGrand(u8),
    /// Voxels non triés par (y, z, x) ou cellule en double.
    #[error("LOD {lod} : voxels non triés par (y, z, x) ou cellule en double (voxel n° {index})")]
    Ordre {
        /// LOD fautif.
        lod: u8,
        /// Rang du premier voxel hors d'ordre.
        index: usize,
    },
    /// Octets après la dernière section.
    #[error("{0} octet(s) en trop après la dernière section")]
    OctetsEnTrop(usize),
}

/// Refus d'un fichier `.vxh` (maison cuite par `tools/maisons`) : même rigueur que `.vxm`, tout ce qui est douteux
/// est rejeté (README_TECHNIQUE § 3 du générateur de maisons).
#[derive(Debug, Clone, PartialEq, Eq, Error)]
pub enum VxhError {
    /// Fichier plus court que l'en-tête de 32 octets.
    #[error("fichier trop court : {0} octet(s) (en-tête de 32 octets)")]
    TropCourt(usize),
    /// La signature `VXH1` manque.
    #[error("signature « VXH1 » absente")]
    Signature,
    /// Une dimension nulle ou supérieure à la borne.
    #[error("dimension {axe} = {valeur} hors de 1..={max}")]
    Dimension {
        /// Axe fautif (`x`, `y` ou `z`).
        axe: char,
        /// Valeur lue.
        valeur: u32,
        /// Borne.
        max: u32,
    },
    /// Trop de cellules pour la borne mémoire.
    #[error("{0} cellules : au-delà de la borne mémoire")]
    TropDeCellules(u64),
    /// Le voxel du fichier n'est pas celui de la grille du monde (5 cm).
    #[error("voxel de {0:#010x} (bits f32) au lieu de 0,05 m")]
    VoxelHorsGrille(u32),
    /// Couches de sol plus nombreuses que la hauteur.
    #[error("{couches} couche(s) de sol pour une hauteur de {ny}")]
    SolHorsGrille {
        /// Couches annoncées.
        couches: u32,
        /// Hauteur de la grille.
        ny: u32,
    },
    /// Octets réservés non nuls.
    #[error("octets réservés de l'en-tête non nuls")]
    ReservesNonNuls,
    /// Corps zlib invalide.
    #[error("corps zlib invalide ({0})")]
    CorpsZlib(String),
    /// Taille du corps différente de celle que les dimensions imposent (4 octets par cellule).
    #[error("corps de {lu} octet(s) au lieu de {attendu}")]
    CorpsTaille {
        /// Taille lue (au plus attendu + 1 : la lecture est bornée).
        lu: u64,
        /// Taille attendue.
        attendu: u64,
    },
    /// Matériau hors de 0..=5.
    #[error("cellule {index} : matériau {materiau} hors de 0..=5")]
    MateriauInvalide {
        /// Rang de la cellule.
        index: usize,
        /// Valeur lue.
        materiau: u8,
    },
    /// L'invariant couleur non nulle <=> matériau non nul est violé.
    #[error("cellule {index} : couleur {couleur:#06x} et matériau {materiau} incohérents")]
    Invariant {
        /// Rang de la cellule.
        index: usize,
        /// Couleur RGB565.
        couleur: u16,
        /// Matériau.
        materiau: u8,
    },
    /// Drapeaux inconnus (au-delà des bits 0 à 3) ou posés sur une cellule vide qui n'est pas du verre.
    #[error("cellule {index} : drapeaux {drapeaux:#04x} invalides")]
    DrapeauxInvalides {
        /// Rang de la cellule.
        index: usize,
        /// Drapeaux lus.
        drapeaux: u8,
    },
}

/// Échec d'un générateur ou du chargement d'un modèle.
#[derive(Debug, Error)]
pub enum GenError {
    /// Lecture d'un fichier impossible.
    #[error("lecture de {chemin} impossible : {source}")]
    Io {
        /// Fichier visé.
        chemin: PathBuf,
        /// Erreur système.
        source: std::io::Error,
    },
    /// Fichier `.vxm` refusé.
    #[error("{chemin} : {source}")]
    Vxm {
        /// Fichier refusé.
        chemin: PathBuf,
        /// Raison du refus.
        source: VxmError,
    },
    /// Octets `.vxm` refusés (sans fichier : mémoire).
    #[error("modèle .vxm refusé : {0}")]
    VxmMemoire(#[from] VxmError),
    /// Fichier `.vxh` refusé.
    #[error("{chemin} : {source}")]
    Vxh {
        /// Fichier refusé.
        chemin: PathBuf,
        /// Raison du refus.
        source: VxhError,
    },
    /// Octets `.vxh` refusés (sans fichier : mémoire).
    #[error("maison .vxh refusée : {0}")]
    VxhMemoire(#[from] VxhError),
    /// Paramètres de générateur invalides.
    #[error("paramètres invalides : {0}")]
    BadParams(String),
    /// Case d'essence hors de 0..=31 (5 bits de teinte).
    #[error("case d'essence {0} hors de 0..=31")]
    UnknownSpecies(u8),
    /// Une classe de matière nécessaire au modèle manque dans la table.
    #[error("classe de matière « {0} » absente de la table")]
    MatiereAbsente(String),
}
