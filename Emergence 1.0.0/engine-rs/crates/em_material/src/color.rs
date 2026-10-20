//! Couleurs en virgule fixe : sRGB 8 bits -> linéaire Q16 (une seule fois, par table), rampes de 3 couleurs.
//! Aucun flottant : la vérité de la couleur est entière ; les flottants n'apparaissent qu'à la frontière GPU.

use em_core::q16::{Q16, qlerp, qpow};

/// Couleur linéaire (r, g, b), chaque canal en Q16 (1,0 = 65 536), dans [0, 1] pour une albédo.
#[derive(Copy, Clone, Debug, Default, PartialEq, Eq)]
pub struct LinearRgb([Q16; 3]);

impl LinearRgb {
    /// Noir.
    pub const BLACK: LinearRgb = LinearRgb([Q16::ZERO; 3]);

    /// Construit une couleur ; chaque canal est borné à [0, 1].
    pub fn new(r: Q16, g: Q16, b: Q16) -> Self {
        let borne = |c: Q16| c.clamp(Q16::ZERO, Q16::ONE);
        LinearRgb([borne(r), borne(g), borne(b)])
    }
    /// Les trois canaux.
    pub const fn channels(self) -> [Q16; 3] {
        self.0
    }
    /// Interpolation linéaire de `self` vers `o`, `t` dans [0, 1].
    pub fn lerp(self, o: LinearRgb, t: Q16) -> LinearRgb {
        let t = t.raw().clamp(0, 65_536);
        let c = |i: usize| Q16::from_raw(qlerp(self.0[i].raw(), o.0[i].raw(), t));
        LinearRgb::new(c(0), c(1), c(2))
    }
    /// Multiplie chaque canal par `k` (Q16), résultat borné à [0, 1].
    pub fn scale(self, k: Q16) -> LinearRgb {
        LinearRgb::new(self.0[0] * k, self.0[1] * k, self.0[2] * k)
    }
    /// Luminance relative (Rec. 709), Q16.
    pub fn luminance(self) -> Q16 {
        Q16::from_raw((13_933 * self.0[0].raw() + 46_871 * self.0[1].raw() + 4_732 * self.0[2].raw()) >> 16)
    }
    /// Plus grand écart absolu entre deux couleurs, en Q16 (pour les tests de continuité).
    pub fn max_abs_diff(self, o: LinearRgb) -> Q16 {
        (0..3)
            .map(|i| (self.0[i] - o.0[i]).abs())
            .max()
            .unwrap_or(Q16::ZERO)
    }
}

/// Table de conversion sRGB 8 bits -> linéaire Q16, construite une seule fois par l'objet qui la possède.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SrgbTable {
    lineaire: [Q16; 256],
}

impl SrgbTable {
    /// Construit les 256 entrées par la courbe sRGB (tronçon linéaire puis puissance 2,4), en entiers.
    pub fn new() -> Self {
        let mut lineaire = [Q16::ZERO; 256];
        let exposant = Q16::from_ratio(12, 5); // 2,4
        let mut precedent = Q16::ZERO;
        for (v, case) in lineaire.iter_mut().enumerate() {
            let c = Q16::from_ratio(v as i64, 255);
            // seuil 0,04045 = 2651 / 65536
            let l = if c.raw() <= 2_651 {
                Q16::from_raw(c.raw() * 100 / 1_292)
            } else {
                // ((c + 0,055) / 1,055) ^ 2,4
                let x = Q16::from_raw((c.raw() + 3_604) * 65_536 / 69_140);
                qpow(x, exposant)
            };
            // la puissance entière a une erreur ~1e-4 : on garantit la monotonie et le plafond à 1
            precedent = Q16::from_raw(l.raw().clamp(precedent.raw(), 65_536));
            *case = precedent;
        }
        lineaire[255] = Q16::ONE;
        SrgbTable { lineaire }
    }
    /// Un canal sRGB 8 bits en linéaire.
    pub fn channel(&self, v: u8) -> Q16 {
        self.lineaire[usize::from(v)]
    }
    /// Une couleur sRGB 8 bits en linéaire.
    pub fn convert(&self, srgb: [u8; 3]) -> LinearRgb {
        LinearRgb::new(
            self.channel(srgb[0]),
            self.channel(srgb[1]),
            self.channel(srgb[2]),
        )
    }
}

impl Default for SrgbTable {
    fn default() -> Self {
        Self::new()
    }
}

/// Rampe de trois couleurs : sombre, moyen, clair.
#[derive(Copy, Clone, Debug, PartialEq, Eq)]
pub struct Ramp3 {
    dark: LinearRgb,
    mid: LinearRgb,
    light: LinearRgb,
}

impl Ramp3 {
    /// Construit une rampe depuis ses trois couleurs.
    pub const fn new(dark: LinearRgb, mid: LinearRgb, light: LinearRgb) -> Self {
        Ramp3 { dark, mid, light }
    }
    /// Rampe dérivée d'une couleur moyenne : sombre = 55 % de la couleur, clair = 35 % du chemin vers le blanc.
    pub fn derived_from(mid: LinearRgb) -> Self {
        let blanc = LinearRgb::new(Q16::ONE, Q16::ONE, Q16::ONE);
        Ramp3 {
            dark: mid.scale(Q16::from_ratio(55, 100)),
            mid,
            light: mid.lerp(blanc, Q16::from_ratio(35, 100)),
        }
    }
    /// Les trois couleurs `[sombre, moyen, clair]`.
    pub const fn colors(&self) -> [LinearRgb; 3] {
        [self.dark, self.mid, self.light]
    }
    /// Couleur à la position `t` dans [0, 1] : 0 = sombre, 0,5 = moyen, 1 = clair.
    pub fn sample(&self, t: Q16) -> LinearRgb {
        let t = t.raw().clamp(0, 65_536);
        if t <= 32_768 {
            self.dark.lerp(self.mid, Q16::from_raw(t * 2))
        } else {
            self.mid.lerp(self.light, Q16::from_raw((t - 32_768) * 2))
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn srgb_bornes_et_monotonie() {
        let t = SrgbTable::new();
        assert_eq!(t.channel(0), Q16::ZERO);
        assert_eq!(t.channel(255), Q16::ONE);
        for v in 1..=255u8 {
            assert!(t.channel(v) >= t.channel(v - 1));
        }
        // 128 sRGB ≈ 0,2158 linéaire
        let m = t.channel(128).raw();
        assert!((m - 14_144).abs() < 120, "{m}");
    }

    #[test]
    fn rampe_milieu_exact() {
        let r = Ramp3::derived_from(SrgbTable::new().convert([120, 100, 60]));
        assert_eq!(r.sample(Q16::HALF), r.colors()[1]);
        assert_eq!(r.sample(Q16::ZERO), r.colors()[0]);
        assert_eq!(r.sample(Q16::ONE), r.colors()[2]);
    }
}
