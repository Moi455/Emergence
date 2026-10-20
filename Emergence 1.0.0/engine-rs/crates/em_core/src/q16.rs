//! Virgule fixe Q16 (16 bits fractionnaires, 1,0 = 65 536), identique au C++ `fixed.h`.
//!
//! Les fonctions libres reprennent `engine/core/base/include/emergence/base/fixed.h` au bit près
//! dans le domaine où le C++ est défini. Le C++ calcule `(a*b) >> 16` en `int64`, ce qui déborde
//! (comportement indéfini) dès que `|a·b| >= 2^63` : ici l'intermédiaire est un `i128`, et le domaine
//! est vérifié par `debug_assert!`. Les angles sont en tours (1,0 = un tour complet).

use std::ops::{Add, AddAssign, Div, Mul, Neg, Sub, SubAssign};

/// Un en Q16.
const UN: i64 = 65_536;

/// Ramène un intermédiaire `i128` en `i64` ; hors domaine (le C++ est alors indéfini), échoue en debug.
#[inline]
fn retrecir(v: i128) -> i64 {
    debug_assert!(
        i64::try_from(v).is_ok(),
        "dépassement de l'intermédiaire hors du domaine défini du C++"
    );
    v as i64
}

/// Nombre en virgule fixe Q16 : valeur brute `i64`, 1,0 = 65 536.
#[derive(Copy, Clone, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct Q16(pub i64);

impl Q16 {
    /// Zéro.
    pub const ZERO: Q16 = Q16(0);
    /// Un (65 536).
    pub const ONE: Q16 = Q16(UN);
    /// Un demi.
    pub const HALF: Q16 = Q16(UN / 2);

    /// Construit depuis la valeur brute (déjà en Q16).
    pub const fn from_raw(raw: i64) -> Q16 {
        Q16(raw)
    }
    /// Valeur brute (en unités de 2⁻¹⁶).
    pub const fn raw(self) -> i64 {
        self.0
    }
    /// Entier `v` converti en Q16.
    pub const fn from_int(v: i64) -> Q16 {
        Q16(v << 16)
    }
    /// Le rapport `n / d`, tronqué vers zéro comme `qdiv` du C++. Panique si `d == 0`.
    pub const fn from_ratio(n: i64, d: i64) -> Q16 {
        Q16((n * UN) / d)
    }
    /// Produit Q16 (`qmul`).
    #[allow(clippy::should_implement_trait)] // le contrat de la tâche L01 nomme ces méthodes ; `Mul` et `Div` délèguent ici
    pub fn mul(self, o: Q16) -> Q16 {
        Q16(qmul(self.0, o.0))
    }
    /// Quotient Q16 (`qdiv`). Panique si `o` est nul.
    #[allow(clippy::should_implement_trait)]
    pub fn div(self, o: Q16) -> Q16 {
        Q16(qdiv(self.0, o.0))
    }
    /// Partie entière, arrondie vers moins l'infini.
    pub const fn floor(self) -> i64 {
        self.0 >> 16
    }
    /// Valeur absolue.
    pub const fn abs(self) -> Q16 {
        Q16(if self.0 < 0 { -self.0 } else { self.0 })
    }
    /// Borne la valeur dans `[lo, hi]`.
    pub fn clamp(self, lo: Q16, hi: Q16) -> Q16 {
        Q16(self.0.clamp(lo.0, hi.0))
    }
}

impl Add for Q16 {
    type Output = Q16;
    fn add(self, o: Q16) -> Q16 {
        Q16(self.0 + o.0)
    }
}
impl Sub for Q16 {
    type Output = Q16;
    fn sub(self, o: Q16) -> Q16 {
        Q16(self.0 - o.0)
    }
}
impl Mul for Q16 {
    type Output = Q16;
    fn mul(self, o: Q16) -> Q16 {
        Q16::mul(self, o)
    }
}
impl Div for Q16 {
    type Output = Q16;
    fn div(self, o: Q16) -> Q16 {
        Q16::div(self, o)
    }
}
impl Neg for Q16 {
    type Output = Q16;
    fn neg(self) -> Q16 {
        Q16(-self.0)
    }
}
impl AddAssign for Q16 {
    fn add_assign(&mut self, o: Q16) {
        self.0 += o.0;
    }
}
impl SubAssign for Q16 {
    fn sub_assign(&mut self, o: Q16) {
        self.0 -= o.0;
    }
}

/// `(a * b) >> 16` (décalage arithmétique), comme `qmul` du C++ dans son domaine `|a·b| < 2^63`.
pub fn qmul(a: i64, b: i64) -> i64 {
    retrecir((i128::from(a) * i128::from(b)) >> 16)
}

/// `(a * 65536) / b` (division tronquée vers zéro), comme `qdiv`. Panique si `b == 0`.
pub fn qdiv(a: i64, b: i64) -> i64 {
    retrecir(i128::from(a) * i128::from(UN) / i128::from(b))
}

/// Interpolation `a + (b - a) * t`, `t` dans [0, 1] en Q16 (`qlerp`).
pub fn qlerp(a: i64, b: i64, t: i64) -> i64 {
    a + retrecir(((i128::from(b) - i128::from(a)) * i128::from(t)) >> 16)
}

/// Rampe linéaire de `x` entre `e0` et `e1`, résultat dans [0, 1] en Q16 (`qramp`). Panique si `e0 == e1`.
pub fn qramp(e0: i64, e1: i64, x: i64) -> i64 {
    let t = i128::from(x - e0) * i128::from(UN) / i128::from(e1 - e0);
    retrecir(t.clamp(0, i128::from(UN)))
}

/// Lissage de Hermite de `x` entre `e0` et `e1`, résultat dans [0, 1] en Q16 (`qsmoothstep`).
pub fn qsmoothstep(e0: i64, e1: i64, x: i64) -> i64 {
    let t = i128::from(qramp(e0, e1, x));
    let t2 = (t * t) >> 16;
    retrecir((t2 * (3 * i128::from(UN) - 2 * t)) >> 16)
}

/// Racine entière : le plus grand `r` tel que `r*r <= v` (`isqrt64`).
pub fn isqrt64(mut v: u64) -> u64 {
    let mut r: u64 = 0;
    let mut bit: u64 = 1 << 62;
    while bit > v {
        bit >>= 2;
    }
    while bit != 0 {
        if v >= r + bit {
            v -= r + bit;
            r = (r >> 1) + bit;
        } else {
            r >>= 1;
        }
        bit >>= 2;
    }
    r
}

/// 2^x, `x` et résultat en Q16 (`qexp2`) : cubique minimax pour la fraction (erreur relative ~1e-4),
/// décalages exacts pour la partie entière. Sature à `i64::MAX` au-delà de 2^40 et à 0 en deçà de 2^-40.
pub fn qexp2(x: i64) -> i64 {
    let ip = x >> 16;
    let f = x & 0xFFFF;
    let p = UN + ((f * (45_560 + ((f * (14_823 + ((f * 5_154) >> 16))) >> 16))) >> 16);
    if ip >= 0 {
        if ip > 40 { i64::MAX } else { p << ip }
    } else if ip < -40 {
        0
    } else {
        p >> (-ip)
    }
}

/// Racine carrée en Q16 ; un argument négatif donne zéro.
pub fn qsqrt(x: Q16) -> Q16 {
    if x.0 <= 0 {
        return Q16::ZERO;
    }
    let brut = x.0 as u64;
    if brut < (1 << 48) {
        Q16(isqrt64(brut << 16) as i64)
    } else {
        // `brut << 16` déborderait : on perd 8 bits de précision, sans importance à cette échelle.
        Q16((isqrt64(brut) << 8) as i64)
    }
}

/// Logarithme en base 2, en Q16 (erreur < 2⁻¹⁶). Un argument ≤ 0 donne -40 (saturation, comme `qexp2`).
pub fn qlog2(x: Q16) -> Q16 {
    if x.0 <= 0 {
        return Q16::from_int(-40);
    }
    let brut = x.0 as u64;
    let msb = 63 - i64::from(brut.leading_zeros());
    // Partie entière : position du bit de poids fort, relativement au 1,0 = 2^16.
    let entier = msb - 16;
    // Mantisse m dans [1, 2) en Q30.
    let mut m: u64 = if msb >= 30 {
        brut >> (msb - 30)
    } else {
        brut << (30 - msb)
    };
    // Fraction : on extrait 17 bits par élévations au carré successives, le dernier sert à arrondir.
    let mut frac: i64 = 0;
    for _ in 0..17 {
        m = (m * m) >> 30;
        frac <<= 1;
        if m >= (2 << 30) {
            frac |= 1;
            m >>= 1;
        }
    }
    Q16((entier << 16) + ((frac + 1) >> 1))
}

/// `x` puissance `e`, par `2^(e·log2 x)` ; précision limitée à celle de `qexp2` (~1e-4 relatif).
/// Un `x` ≤ 0 donne zéro.
pub fn qpow(x: Q16, e: Q16) -> Q16 {
    if x.0 <= 0 {
        return Q16::ZERO;
    }
    Q16(qexp2(qmul(e.0, qlog2(x).0)))
}

// ---- Trigonométrie en tours (CORDIC entier) -------------------------------------------------------

/// Nombre d'itérations CORDIC (valeurs en Q30, angles en tours Q32).
const ITER: usize = 30;
/// atan(2^-i) / (2π) en tours Q32, i = 0..30 (calculé une fois hors ligne, arrondi au plus proche).
const ATAN_TOURS_Q32: [i64; ITER] = [
    536_870_912,
    316_933_406,
    167_458_907,
    85_004_756,
    42_667_331,
    21_354_465,
    10_679_838,
    5_340_245,
    2_670_163,
    1_335_087,
    667_544,
    333_772,
    166_886,
    83_443,
    41_722,
    20_861,
    10_430,
    5_215,
    2_608,
    1_304,
    652,
    326,
    163,
    81,
    41,
    20,
    10,
    5,
    3,
    1,
];
/// Produit des 1/√(1+2^-2i), i < 30, en Q30 (gain CORDIC inverse).
const GAIN_INVERSE_Q30: i64 = 652_032_874;

/// Q30 vers Q16 avec arrondi au plus proche.
fn q30_vers_q16(v: i64) -> i64 {
    (v + (1 << 13)) >> 14
}

/// Sinus et cosinus d'un angle en tours Q16 (période 1,0), résultats en Q16.
fn sin_cos_tours(t: Q16) -> (i64, i64) {
    let phase = t.0 & 0xFFFF; // tours dans [0, 1)
    let quadrant = phase >> 14;
    let reste = phase & 0x3FFF; // [0, 1/4 tour)
    let mut z = reste << 16; // tours Q32
    let (mut x, mut y) = (GAIN_INVERSE_Q30, 0_i64);
    for (i, atan) in ATAN_TOURS_Q32.iter().enumerate() {
        if z >= 0 {
            (x, y) = (x - (y >> i), y + (x >> i));
            z -= atan;
        } else {
            (x, y) = (x + (y >> i), y - (x >> i));
            z += atan;
        }
    }
    let (c, s) = (q30_vers_q16(x), q30_vers_q16(y));
    match quadrant {
        0 => (s, c),
        1 => (c, -s),
        2 => (-s, -c),
        _ => (-c, s),
    }
}

/// Sinus d'un angle en tours (1,0 = un tour), erreur < 2⁻¹⁵.
pub fn sin_turns(t: Q16) -> Q16 {
    Q16(sin_cos_tours(t).0)
}

/// Cosinus d'un angle en tours (1,0 = un tour), erreur < 2⁻¹⁵.
pub fn cos_turns(t: Q16) -> Q16 {
    Q16(sin_cos_tours(t).1)
}

/// Arc tangente à deux arguments, en tours dans ]-0,5 ; 0,5] (0 pour l'origine). Le résultat est
/// l'angle du vecteur (x, y) depuis l'axe des x, positif vers y.
pub fn atan2_turns(y: Q16, x: Q16) -> Q16 {
    if x.0 == 0 && y.0 == 0 {
        return Q16::ZERO;
    }
    // Mise à l'échelle (précision) : le plus grand côté vers le bit 40.
    let plus_grand = x.0.unsigned_abs().max(y.0.unsigned_abs());
    let msb = 63 - i64::from(plus_grand.leading_zeros());
    let (mut vx, mut vy) = if msb >= 40 {
        (x.0 >> (msb - 40), y.0 >> (msb - 40))
    } else {
        (x.0 << (40 - msb), y.0 << (40 - msb))
    };
    // Demi-plan x < 0 : on retourne le vecteur et on ajoutera ± un demi-tour.
    let retourne = vx < 0;
    if retourne {
        (vx, vy) = (-vx, -vy);
    }
    let mut z: i64 = 0; // tours Q32
    for (i, atan) in ATAN_TOURS_Q32.iter().enumerate() {
        if vy >= 0 {
            (vx, vy) = (vx + (vy >> i), vy - (vx >> i));
            z += atan;
        } else {
            (vx, vy) = (vx - (vy >> i), vy + (vx >> i));
            z -= atan;
        }
    }
    let mut tours_q32 = z;
    if retourne {
        // Le vecteur d'origine avait y >= 0 si le vecteur retourné a y' <= 0, c'est-à-dire z <= 0.
        tours_q32 += if y.0 >= 0 { 1_i64 << 31 } else { -(1_i64 << 31) };
    }
    Q16((tours_q32 + (1 << 15)) >> 16)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn constantes_et_conversions() {
        assert_eq!(Q16::ONE.raw(), 65_536);
        assert_eq!(Q16::from_int(-3).floor(), -3);
        assert_eq!(Q16::from_ratio(1, 2), Q16::HALF);
        assert_eq!(Q16(-1).floor(), -1);
    }

    #[test]
    fn isqrt_parfait() {
        assert_eq!(isqrt64(0), 0);
        assert_eq!(isqrt64(u64::MAX), 4_294_967_295);
        assert_eq!(isqrt64(1 << 62), 1 << 31);
    }

    #[test]
    fn quadrants_exacts() {
        assert_eq!(sin_turns(Q16(0)), Q16(0));
        assert_eq!(cos_turns(Q16(0)), Q16::ONE);
        assert_eq!(sin_turns(Q16(16_384)), Q16::ONE);
        assert_eq!(cos_turns(Q16(32_768)), -Q16::ONE);
        assert_eq!(atan2_turns(Q16::ZERO, -Q16::ONE), Q16::HALF);
    }
}
