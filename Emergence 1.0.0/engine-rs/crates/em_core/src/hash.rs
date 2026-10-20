//! Hachage entier identique au C++ (`engine/core/base/include/emergence/base/hash.h`).
//!
//! Jamais de `rand` : tout tirage de la vérité passe par ces fonctions. Les conversions
//! `i64 as u64` sont le complément à deux, comme le `static_cast<uint64_t>` du C++.

use crate::q16::Q16;

/// Constante dorée de SplitMix64 (incrément d'état).
const INCREMENT_DORE: u64 = 0x9e37_79b9_7f4a_7c15;

/// Finaliseur de splitmix64 : bonne avalanche, bon marché, identique partout.
pub const fn mix64(mut x: u64) -> u64 {
    x ^= x >> 30;
    x = x.wrapping_mul(0xbf58_476d_1ce4_e5b9);
    x ^= x >> 27;
    x = x.wrapping_mul(0x94d0_49bb_1331_11eb);
    x ^= x >> 31;
    x
}

/// Combine un hachage et une valeur.
pub const fn hash_combine(h: u64, v: u64) -> u64 {
    mix64(h ^ v.wrapping_mul(INCREMENT_DORE).wrapping_add(0x632b_e59b_d9b4_e019))
}

/// Hachage d'un couple de coordonnées entières.
pub const fn hash2(seed: u64, x: i64, y: i64) -> u64 {
    hash_combine(hash_combine(seed, x as u64), y as u64)
}

/// Hachage d'un triplet de coordonnées entières.
pub const fn hash3(seed: u64, x: i64, y: i64, z: i64) -> u64 {
    hash_combine(hash2(seed, x, y), z as u64)
}

/// Graine propre à une couche de génération : en ajouter une ne décale jamais les tirages d'une autre.
pub const fn layer_seed(world_seed: u64, layer: u64) -> u64 {
    hash_combine(mix64(world_seed), layer.wrapping_mul(0xd6e8_feb8_6659_fd93))
}

/// Les couches de génération du C++ (`enum class Layer`), numérotées comme lui.
#[derive(Copy, Clone, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
#[repr(u64)]
pub enum Layer {
    Frontier = 1,
    CoreRelief,
    Mountain,
    Desert,
    Forest,
    Sea,
    Moisture,
    Geology,
    Snowline,
    Detail,
    Backdrop,
    Biome,
    Strata,
}

impl Layer {
    /// Numéro de la couche, tel que le C++ le passe à `layer_seed`.
    pub const fn id(self) -> u64 {
        self as u64
    }
    /// Graine de cette couche pour une graine de monde.
    pub const fn seed(self, world_seed: u64) -> u64 {
        layer_seed(world_seed, self.id())
    }
}

/// Générateur SplitMix64 : état += constante dorée, sortie = `mix64(état)`.
#[derive(Clone, Debug)]
pub struct SplitMix64 {
    etat: u64,
}

impl SplitMix64 {
    /// Crée un générateur à partir d'une graine.
    pub const fn new(seed: u64) -> Self {
        Self { etat: seed }
    }
    /// Tirage suivant sur 64 bits.
    pub fn next_u64(&mut self) -> u64 {
        self.etat = self.etat.wrapping_add(INCREMENT_DORE);
        mix64(self.etat)
    }
    /// Entier uniforme dans `[0, n)`, sans biais (rejet des tirages de la zone incomplète). Panique si `n == 0`.
    pub fn below(&mut self, n: u64) -> u64 {
        assert!(n > 0, "SplitMix64::below : n doit être non nul");
        let seuil = n.wrapping_neg() % n; // nombre de valeurs à rejeter en bas de plage
        loop {
            let r = self.next_u64();
            if r >= seuil {
                return r % n;
            }
        }
    }
    /// Fraction uniforme dans [0, 1) en Q16 (16 bits de poids fort du tirage).
    pub fn unit_q16(&mut self) -> Q16 {
        Q16((self.next_u64() >> 48) as i64)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn splitmix_reference_connue() {
        // Première sortie de SplitMix64 avec la graine 0 (valeur publiée de l'algorithme).
        assert_eq!(SplitMix64::new(0).next_u64(), 0xe220_a839_7b1d_cdaf);
    }

    #[test]
    fn below_reste_dans_la_plage() {
        let mut g = SplitMix64::new(7);
        for n in [1_u64, 2, 3, 10, 1 << 40, u64::MAX] {
            assert!(g.below(n) < n);
        }
    }

    #[test]
    fn unit_est_inferieur_a_un() {
        let mut g = SplitMix64::new(9);
        for _ in 0..1000 {
            let u = g.unit_q16();
            assert!(u >= Q16::ZERO && u < Q16::ONE);
        }
    }
}
