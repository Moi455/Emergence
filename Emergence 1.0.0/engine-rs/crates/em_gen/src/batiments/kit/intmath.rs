//! Petits calculs entiers communs aux recettes (la crate interdit les flottants).

use em_core::Q16;
use em_core::q16::{cos_turns, isqrt64, sin_turns};

/// Racine carrée entière par défaut (`floor(sqrt(v))`).
pub fn isqrt(v: u128) -> u128 {
    if v < (1 << 64) {
        return u128::from(isqrt64(v as u64));
    }
    // Newton sur 128 bits
    let bits = 128 - v.leading_zeros();
    let mut x = 1_u128 << bits.div_ceil(2);
    loop {
        let y = (x + v / x) >> 1;
        if y >= x {
            return x;
        }
        x = y;
    }
}

/// Division euclidienne par le bas.
#[inline]
pub const fn fdiv(a: i32, b: i32) -> i32 {
    a.div_euclid(b)
}

/// Arrondi au plus proche, moitiés vers le haut (`Math.round`) de `a / b`, `b > 0`.
#[inline]
pub const fn round_div(a: i32, b: i32) -> i32 {
    (2 * a + b).div_euclid(2 * b)
}

/// Cosinus d'un angle en tours exprimé en 1/65536e de tour, résultat en centièmes (-100..=100).
pub fn cos100(tours_q16: i32) -> i32 {
    ((cos_turns(Q16::from_raw(i64::from(tours_q16))).raw() * 100 + 32_768) >> 16) as i32
}

/// Sinus d'un angle en tours (1/65536e de tour), résultat en centièmes.
pub fn sin100(tours_q16: i32) -> i32 {
    ((sin_turns(Q16::from_raw(i64::from(tours_q16))).raw() * 100 + 32_768) >> 16) as i32
}

/// Cosinus en millièmes.
pub fn cos1000(tours_q16: i32) -> i32 {
    ((cos_turns(Q16::from_raw(i64::from(tours_q16))).raw() * 1000 + 32_768) >> 16) as i32
}

/// Sinus en millièmes.
pub fn sin1000(tours_q16: i32) -> i32 {
    ((sin_turns(Q16::from_raw(i64::from(tours_q16))).raw() * 1000 + 32_768) >> 16) as i32
}

/// Vrai si le point (x, z) (entiers) est dans le disque de centre (cx, cz) et de rayon `r`, le tout en centièmes
/// de voxel : `(100x - cx)^2 + (100z - cz)^2 <= r^2` (le point est le coin bas du voxel + 0 : l'appelant ajoute 50
/// pour viser le centre).
#[inline]
pub fn in_disc100(x100: i32, z100: i32, cx100: i32, cz100: i32, r100: i32) -> bool {
    let (dx, dz, r) = (i64::from(x100 - cx100), i64::from(z100 - cz100), i64::from(r100));
    dx * dx + dz * dz <= r * r
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn racines_et_arrondis() {
        assert_eq!(isqrt(0), 0);
        assert_eq!(isqrt(99), 9);
        assert_eq!(isqrt(1 << 100), 1 << 50);
        assert_eq!(isqrt((1 << 100) - 1), (1 << 50) - 1);
        assert_eq!(round_div(5, 2), 3);
        assert_eq!(round_div(-5, 2), -2);
        assert_eq!(round_div(7, 3), 2);
        assert_eq!(cos100(0), 100);
        assert_eq!(sin100(16_384), 100);
    }
}
