//! Flux de tirages d'une recette : dérivé de la graine ET d'une étiquette, pour qu'ajouter un usage du hasard
//! ne décale jamais les tirages d'un autre (comme `layer_seed`).

use em_core::{SplitMix64, hash_combine};

/// Flux de tirages déterministe.
#[derive(Clone, Debug)]
pub struct Draw {
    flux: SplitMix64,
}

impl Draw {
    /// Flux de la recette de graine `seed` pour l'usage `etiquette`.
    pub fn new(seed: u64, etiquette: u64) -> Self {
        Self {
            flux: SplitMix64::new(hash_combine(seed, etiquette)),
        }
    }

    /// Entier uniforme dans `[0, n)` ; `n` nul donne 0.
    pub fn below(&mut self, n: u32) -> u32 {
        if n == 0 {
            0
        } else {
            self.flux.below(u64::from(n)) as u32
        }
    }

    /// Entier uniforme dans `[lo, hi]` (bornes incluses ; `hi < lo` donne `lo`).
    pub fn between(&mut self, lo: u32, hi: u32) -> u32 {
        if hi <= lo {
            lo
        } else {
            lo + self.below(hi - lo + 1)
        }
    }

    /// Vrai avec la probabilité `pourcent` (0..=100).
    pub fn percent(&mut self, pourcent: u32) -> bool {
        self.below(100) < pourcent
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn deux_flux_de_meme_etiquette_sont_identiques_et_les_etiquettes_separent() {
        let (mut a, mut b, mut c) = (Draw::new(7, 1), Draw::new(7, 1), Draw::new(7, 2));
        let sa: Vec<u32> = (0..20).map(|_| a.below(1000)).collect();
        let sb: Vec<u32> = (0..20).map(|_| b.below(1000)).collect();
        let sc: Vec<u32> = (0..20).map(|_| c.below(1000)).collect();
        assert_eq!(sa, sb);
        assert_ne!(sa, sc);
    }

    #[test]
    fn les_bornes_sont_respectees() {
        let mut d = Draw::new(3, 3);
        for _ in 0..500 {
            let v = d.between(4, 7);
            assert!((4..=7).contains(&v));
        }
        assert_eq!(d.between(5, 5), 5);
        assert_eq!(d.between(9, 2), 9);
        assert!(!d.percent(0));
        assert!(d.percent(100));
    }
}
