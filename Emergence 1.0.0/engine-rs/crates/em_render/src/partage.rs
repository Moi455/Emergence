//! Valeur partagée entre un propriétaire qui la modifie (la scène, la fenêtre) et des passes qui la lisent.
//! Ce n'est pas une globale : chaque `Partage` est créé par son propriétaire et prêté par `clone()` aux
//! passes qui le reçoivent à leur construction (injection, docs/19 § 2.7 règle 5).

use std::sync::{Arc, Mutex};

/// Valeur partagée avec numéro de révision (les passes ne recalculent que si la révision change).
pub struct Partage<T> {
    interieur: Arc<Mutex<(T, u64)>>,
}

impl<T> Clone for Partage<T> {
    fn clone(&self) -> Self {
        Self {
            interieur: Arc::clone(&self.interieur),
        }
    }
}

impl<T: Clone> Partage<T> {
    /// Crée un partage à la révision 0.
    pub fn new(valeur: T) -> Self {
        Self {
            interieur: Arc::new(Mutex::new((valeur, 0))),
        }
    }

    fn verrou(&self) -> std::sync::MutexGuard<'_, (T, u64)> {
        // Un verrou empoisonné ne vient que d'une panique ailleurs ; la valeur reste lisible.
        self.interieur.lock().unwrap_or_else(|e| e.into_inner())
    }

    /// Copie de la valeur courante et sa révision.
    pub fn lire(&self) -> (T, u64) {
        let g = self.verrou();
        (g.0.clone(), g.1)
    }

    /// Remplace la valeur et incrémente la révision.
    pub fn remplacer(&self, valeur: T) {
        let mut g = self.verrou();
        g.0 = valeur;
        g.1 += 1;
    }
}

#[cfg(test)]
mod tests {
    use super::Partage;

    #[test]
    fn la_revision_suit_les_remplacements() {
        let a = Partage::new(3_u32);
        let b = a.clone();
        assert_eq!(b.lire(), (3, 0));
        a.remplacer(7);
        assert_eq!(b.lire(), (7, 1));
    }
}
