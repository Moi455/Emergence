//! Arithmétique en virgule fixe de la végétation : vecteurs Q16, tirages (`Stream`) et bruit de valeur 3D.
//!
//! **Unité** : toutes les longueurs du squelette sont en Q16 de VOXEL de 5 cm (1,0 = 65 536 = 5 cm ; 1 m =
//! 20 voxels). Le niveau de détail k est alors exact : un voxel du niveau k mesure `2^k` unités. Les angles
//! sont en tours Q16 (1,0 = un tour). Les axes sont ceux de `voxel_tree.py` (x est, y nord, **z haut**) ; la
//! permutation vers le repère monde (x est, y haut, z nord) n'a lieu qu'à l'écriture des voxels.
//!
//! Aucun flottant ici : tout ce qui est « vérité » passe par les entiers.

use em_core::q16::{Q16, cos_turns, isqrt64, qexp2, qlog2, qmul, qsqrt, sin_turns};
use em_core::{SplitMix64, hash_combine, mix64};

/// Un (1,0) en Q16.
pub const UN: i64 = 65_536;
/// Voxels par mètre.
pub const VOX_PAR_M: i64 = 20;
/// Un tour complet moins un : masque des angles.
pub const MASQUE_TOUR: i64 = 0xFFFF;

/// Produit Q16 (décalage arithmétique).
#[inline]
pub fn mul(a: i64, b: i64) -> i64 {
    qmul(a, b)
}

/// Quotient Q16 ; un diviseur nul donne zéro (jamais de panique dans un générateur).
#[inline]
pub fn div(a: i64, b: i64) -> i64 {
    if b == 0 {
        0
    } else {
        ((i128::from(a) << 16) / i128::from(b)) as i64
    }
}

/// Mètres (en Q16) -> voxels (en Q16).
#[inline]
pub const fn m_vers_vox(m_q16: i64) -> i64 {
    m_q16 * VOX_PAR_M
}

/// Voxels (en Q16) -> mètres (en Q16).
#[inline]
pub const fn vox_vers_m(v_q16: i64) -> i64 {
    v_q16 / VOX_PAR_M
}

/// Racine carrée Q16.
#[inline]
pub fn sqrt(x: i64) -> i64 {
    qsqrt(Q16(x)).raw()
}

/// Sinus d'un angle en tours Q16.
#[inline]
pub fn sin(t: i64) -> i64 {
    sin_turns(Q16(t)).raw()
}

/// Cosinus d'un angle en tours Q16.
#[inline]
pub fn cos(t: i64) -> i64 {
    cos_turns(Q16(t)).raw()
}

/// Puissance `x^e` (x > 0, Q16 -> Q16) ; précision de `qexp2` (~1e-4 relatif).
pub fn pow(x: i64, e: i64) -> i64 {
    if x <= 0 {
        return 0;
    }
    qexp2(mul(e, qlog2(Q16(x)).raw()))
}

/// `e^(-x)` pour `x >= 0` en Q16.
pub fn exp_neg(x: i64) -> i64 {
    // e^-x = 2^(-x log2 e), log2 e = 1,442695
    qexp2(-mul(x.max(0), 94_548))
}

/// Angle (0 à 63) du vecteur `(x, y)` : l'azimut quantifié, pour des choix par secteur ondulés.
pub fn atan2(y: i64, x: i64) -> i32 {
    let t = em_core::q16::atan2_turns(Q16(y << 8), Q16(x << 8)).raw();
    (t.rem_euclid(UN) >> 10) as i32
}

/// Un vecteur en Q16 (voir l'unité en tête de module).
#[derive(Copy, Clone, Debug, Default, PartialEq, Eq)]
pub struct V3 {
    /// Est.
    pub x: i64,
    /// Nord.
    pub y: i64,
    /// Haut.
    pub z: i64,
}

impl V3 {
    /// Le vecteur nul.
    pub const ZERO: V3 = V3 { x: 0, y: 0, z: 0 };
    /// Le haut unitaire.
    pub const HAUT: V3 = V3 { x: 0, y: 0, z: UN };

    /// Construit un vecteur.
    pub const fn new(x: i64, y: i64, z: i64) -> V3 {
        V3 { x, y, z }
    }
    /// Somme.
    pub const fn add(self, o: V3) -> V3 {
        V3::new(self.x + o.x, self.y + o.y, self.z + o.z)
    }
    /// Différence.
    pub const fn sub(self, o: V3) -> V3 {
        V3::new(self.x - o.x, self.y - o.y, self.z - o.z)
    }
    /// Produit par un scalaire Q16.
    pub fn scale(self, s: i64) -> V3 {
        V3::new(mul(self.x, s), mul(self.y, s), mul(self.z, s))
    }
    /// Produit scalaire (Q16).
    pub fn dot(self, o: V3) -> i64 {
        mul(self.x, o.x) + mul(self.y, o.y) + mul(self.z, o.z)
    }
    /// Produit vectoriel.
    pub fn cross(self, o: V3) -> V3 {
        V3::new(
            mul(self.y, o.z) - mul(self.z, o.y),
            mul(self.z, o.x) - mul(self.x, o.z),
            mul(self.x, o.y) - mul(self.y, o.x),
        )
    }
    /// Norme (Q16).
    pub fn norm(self) -> i64 {
        let s = i128::from(self.x) * i128::from(self.x)
            + i128::from(self.y) * i128::from(self.y)
            + i128::from(self.z) * i128::from(self.z);
        if s <= i128::from(u64::MAX) {
            isqrt64(s as u64) as i64
        } else {
            (isqrt64((s >> 16) as u64) << 8) as i64
        }
    }
    /// Vecteur unitaire ; le vecteur nul donne le haut.
    pub fn unit(self) -> V3 {
        let n = self.norm();
        if n == 0 {
            return V3::HAUT;
        }
        V3::new(div(self.x, n), div(self.y, n), div(self.z, n))
    }
}

/// Source de tirages déterministe d'un usage (graine + étiquette), sur SplitMix64.
#[derive(Clone, Debug)]
pub struct Stream {
    flux: SplitMix64,
}

impl Stream {
    /// Flux de la graine `seed` pour l'usage `etiquette` : ajouter un usage ne décale jamais les autres.
    pub fn new(seed: u64, etiquette: u64) -> Self {
        Self {
            flux: SplitMix64::new(hash_combine(seed, etiquette)),
        }
    }
    /// Fraction uniforme dans [0, 1) en Q16.
    pub fn unit(&mut self) -> i64 {
        (self.flux.next_u64() >> 48) as i64
    }
    /// Uniforme dans `[lo, hi)` (Q16).
    pub fn uniform(&mut self, lo: i64, hi: i64) -> i64 {
        lo + mul(self.unit(), hi - lo)
    }
    /// Loi normale centrée réduite en Q16 : somme de douze uniformes de 16 bits (Irwin-Hall d'ordre 12, écart
    /// type exactement 1, queues bornées à 6 sigma). Un ordre plus bas (quatre) allège trop les queues et fait
    /// élaguer 8 % de branches en plus sur le hêtre (mesuré contre `numpy`).
    pub fn normal(&mut self) -> i64 {
        let mut s = 0_i64;
        for _ in 0..3 {
            let r = self.flux.next_u64();
            s += (r & 0xFFFF) as i64
                + ((r >> 16) & 0xFFFF) as i64
                + ((r >> 32) & 0xFFFF) as i64
                + (r >> 48) as i64;
        }
        s - 6 * UN
    }
    /// Entier uniforme dans `[lo, hi]` inclus.
    pub fn integers(&mut self, lo: i64, hi: i64) -> i64 {
        if hi <= lo {
            lo
        } else {
            lo + self.flux.below((hi - lo + 1) as u64) as i64
        }
    }
    /// Vrai avec la probabilité `p` (Q16).
    pub fn chance(&mut self, p: i64) -> bool {
        self.unit() < p
    }
    /// Permutation de `0..n` (Fisher-Yates).
    pub fn permutation(&mut self, n: usize) -> Vec<usize> {
        let mut v: Vec<usize> = (0..n).collect();
        for i in (1..n).rev() {
            let j = self.flux.below(i as u64 + 1) as usize;
            v.swap(i, j);
        }
        v
    }
}

/// Fraction uniforme [0, 65 536) tirée d'un hachage de coordonnées entières (bruit ancré au monde).
#[inline]
pub fn hash_unit(seed: u64, x: i64, y: i64, z: i64) -> i64 {
    let h = mix64(
        seed ^ (x as u64).wrapping_mul(0x9E37_79B9_7F4A_7C15)
            ^ (y as u64).wrapping_mul(0xC2B2_AE3D_27D4_EB4F)
            ^ (z as u64).wrapping_mul(0x1656_67B1_9E37_79F9),
    );
    (h >> 48) as i64
}

/// Bruit de valeur 3D lissé dans [0, 65 536) ; `(qx, qy, qz)` sont les coordonnées de réseau en Q16
/// (déjà multipliées par la fréquence). Même résultat quel que soit l'ordre des appels.
pub fn value_noise(qx: i64, qy: i64, qz: i64, seed: u64) -> i64 {
    let (ix, iy, iz) = (qx >> 16, qy >> 16, qz >> 16);
    let lisse = |f: i64| mul(mul(f, f), 3 * UN - 2 * f);
    let (ux, uy, uz) = (
        lisse(qx & MASQUE_TOUR),
        lisse(qy & MASQUE_TOUR),
        lisse(qz & MASQUE_TOUR),
    );
    let c = |dx: i64, dy: i64, dz: i64| hash_unit(seed, ix + dx, iy + dy, iz + dz);
    let lerp = |a: i64, b: i64, t: i64| a + mul(b - a, t);
    let a = lerp(c(0, 0, 0), c(1, 0, 0), ux);
    let b = lerp(c(0, 1, 0), c(1, 1, 0), ux);
    let cc = lerp(c(0, 0, 1), c(1, 0, 1), ux);
    let d = lerp(c(0, 1, 1), c(1, 1, 1), ux);
    let e = lerp(a, b, uy);
    let g = lerp(cc, d, uy);
    lerp(e, g, uz)
}

/// Facteur Q16 qui transforme une coordonnée en voxels (Q16) en coordonnée de réseau pour une fréquence de
/// `f_milli` millièmes de cycle par mètre : `réseau = voxels × f / 20`.
pub fn lattice_factor(f_milli: i64) -> i64 {
    f_milli * UN / (1000 * VOX_PAR_M)
}

/// Bruit de valeur d'un point (Q16 voxels) à la fréquence `f_milli` (millièmes de cycle par mètre).
pub fn noise_at(p: V3, f_milli: i64, seed: u64) -> i64 {
    let k = lattice_factor(f_milli);
    value_noise(mul(p.x, k), mul(p.y, k), mul(p.z, k), seed)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn la_loi_normale_est_centree_reduite() {
        let mut s = Stream::new(1, 2);
        let n = 20_000_i64;
        let (mut m, mut v) = (0_i128, 0_i128);
        for _ in 0..n {
            let x = s.normal();
            m += i128::from(x);
            v += (i128::from(x) * i128::from(x)) >> 16;
        }
        let moy = m / i128::from(n);
        let var = v / i128::from(n);
        assert!(moy.abs() < 1500, "moyenne {moy}");
        assert!((var - 65_536).abs() < 3000, "variance {var}");
    }

    #[test]
    fn le_bruit_est_borne_et_reproductible() {
        for i in 0..200 {
            let a = value_noise(i * 7919, i * 104_729, i * 31, 5);
            assert!((0..=UN).contains(&a));
            assert_eq!(a, value_noise(i * 7919, i * 104_729, i * 31, 5));
        }
    }

    #[test]
    fn vecteur_unitaire_et_produit_vectoriel() {
        let u = V3::new(3 * UN, 4 * UN, 0).unit();
        assert!((u.x - 39_322).abs() < 4 && (u.y - 52_429).abs() < 4);
        let c = V3::new(UN, 0, 0).cross(V3::new(0, UN, 0));
        assert_eq!(c, V3::new(0, 0, UN));
    }

    #[test]
    fn puissance_et_exponentielle() {
        // 2^2.4 = 5.278
        let p = pow(2 * UN, 157_286);
        assert!((p - 345_900).abs() < 800, "{p}");
        // e^-1 = 0.3679
        assert!((exp_neg(UN) - 24_109).abs() < 60);
    }
}
