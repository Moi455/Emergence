//! Erreurs typées de `em_core` (hors entrées-sorties, voir `io`).

use thiserror::Error;

/// Violation d'un invariant d'un type valeur de `em_core`.
#[derive(Debug, Clone, PartialEq, Eq, Error)]
pub enum CoreError {
    /// Un numéro de case d'entité hors de 1..=4 194 303.
    #[error("case d'entité invalide : {0} (attendu 1..=4194303)")]
    CaseEntiteInvalide(u32),
    /// Une génération d'entité au-delà de 10 bits.
    #[error("génération d'entité invalide : {0} (attendu 0..=1023)")]
    GenerationInvalide(u32),
    /// Un identifiant brut d'entité incohérent (case 0 avec génération non nulle).
    #[error("identifiant d'entité brut incohérent : {0:#010x}")]
    IdentifiantBrutInvalide(u32),
    /// Une classe de matière au-delà de 9 bits.
    #[error("classe de matière invalide : {0} (attendu 0..=511)")]
    MatiereInvalide(u16),
    /// Une boîte dont le minimum dépasse le maximum.
    #[error("boîte de voxels invalide : min dépasse max sur l'axe {axe}")]
    BoiteInvalide {
        /// Axe fautif (0 = x, 1 = y, 2 = z).
        axe: usize,
    },
}
