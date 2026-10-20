//! `AmbientOcclusionParams` : réglages de l'occlusion ambiante tracée (L14), validés à la construction (docs/19 § 2.7,
//! règle 1 : champs privés, constructeur qui vérifie l'invariant, accesseurs).
//!
//! Elle porte aussi les fonctions CPU qui MIROITENT le WGSL (`voxel_ao.wgsl`) : le hachage de la position monde, les
//! directions cosinus, l'atténuation en distance. Les essais comparent le GPU à ces calculs.

use crate::error::ParamError;

/// Taille d'un voxel en mètres (miroir de `VOXEL_M` du WGSL).
pub const VOXEL_M: f32 = 0.05;

/// Angle d'or en radians (miroir de la constante du WGSL).
const ANGLE_D_OR: f32 = 2.399_963;

fn verifie(nom: &str, v: f32, min: f32, max: f32) -> Result<f32, ParamError> {
    if v.is_finite() && (min..=max).contains(&v) {
        Ok(v)
    } else {
        Err(ParamError::Invalide(format!(
            "occlusion ambiante : {nom} = {v} hors de [{min}, {max}]"
        )))
    }
}

/// Réglages de l'occlusion ambiante.
///
/// Défauts (étalonnés sur le chêne 42 et le mur de pierre, `docs/19c_journal_style.md`) : 4 rayons, portée 1 m, force 1,6,
/// filtre de 2 pixels, rayons tracés en demi-résolution.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct AmbientOcclusionParams {
    rays: u32,
    range_m: f32,
    strength: f32,
    filter_px: u32,
    resolution_divisor: u32,
}

impl Default for AmbientOcclusionParams {
    fn default() -> Self {
        Self {
            rays: 4,
            range_m: 1.0,
            strength: 1.6,
            filter_px: 2,
            resolution_divisor: 2,
        }
    }
}

impl AmbientOcclusionParams {
    /// `rays` dans [1, 16] rayons par pixel ; `range_m` dans [0,1 ; 4] mètres de portée.
    pub fn new(rays: u32, range_m: f32) -> Result<Self, ParamError> {
        if !(1..=16).contains(&rays) {
            return Err(ParamError::Invalide(format!(
                "occlusion ambiante : {rays} rayons hors de [1, 16]"
            )));
        }
        Ok(Self {
            rays,
            range_m: verifie("portée (m)", range_m, 0.1, 4.0)?,
            ..Self::default()
        })
    }

    /// Force dans [0, 2] : part de la fraction occultée retranchée de l'ambiance (0 = éteinte, 1 = pleine).
    pub fn with_strength(mut self, strength: f32) -> Result<Self, ParamError> {
        self.strength = verifie("force", strength, 0.0, 2.0)?;
        Ok(self)
    }

    /// Rayon du filtre bilatéral en pixels, de 0 (aucun) à 3.
    pub fn with_filter(mut self, pixels: u32) -> Result<Self, ParamError> {
        if pixels > 3 {
            return Err(ParamError::Invalide(format!(
                "occlusion ambiante : filtre de {pixels} pixels hors de [0, 3]"
            )));
        }
        self.filter_px = pixels;
        Ok(self)
    }

    /// Diviseur de la résolution du tracé des rayons : 1 (un jeu de rayons par pixel) ou 2 (un par bloc de 2 × 2 pixels,
    /// remonté en pleine résolution par le filtre bilatéral qui se guide sur la face et le plan du voxel).
    pub fn with_resolution_divisor(mut self, diviseur: u32) -> Result<Self, ParamError> {
        if !(1..=2).contains(&diviseur) {
            return Err(ParamError::Invalide(format!(
                "occlusion ambiante : diviseur de résolution {diviseur} hors de [1, 2]"
            )));
        }
        self.resolution_divisor = diviseur;
        Ok(self)
    }

    /// Diviseur de résolution du tracé (1 ou 2).
    pub fn resolution_divisor(&self) -> u32 {
        self.resolution_divisor
    }

    /// Rayons par pixel.
    pub fn rays(&self) -> u32 {
        self.rays
    }

    /// Portée des rayons en mètres.
    pub fn range_m(&self) -> f32 {
        self.range_m
    }

    /// Portée des rayons en voxels.
    pub fn range_voxels(&self) -> f32 {
        self.range_m / VOXEL_M
    }

    /// Force.
    pub fn strength(&self) -> f32 {
        self.strength
    }

    /// Rayon du filtre en pixels.
    pub fn filter_px(&self) -> u32 {
        self.filter_px
    }

    /// Poids d'un rayon arrêté à `t` voxels : 1 au contact, 0 à la portée (décroissance quadratique).
    pub fn weight(&self, t_voxels: f32) -> f32 {
        let x = (1.0 - t_voxels / self.range_voxels()).clamp(0.0, 1.0);
        x * x
    }

    /// Occlusion retenue pour une fraction occultée moyenne `occ` : `1 - force × occ`, bornée à [0, 1].
    pub fn visibility(&self, occ: f32) -> f32 {
        (1.0 - self.strength * occ).clamp(0.0, 1.0)
    }
}

/// Hachage de la position monde d'un point de surface : voxel absolu, position dans la face quantifiée au quart de
/// voxel, face. Il ne dépend ni de la caméra ni du temps : l'échantillonnage est le même à chaque image (miroir exact de
/// `ao_hash` du WGSL).
pub fn position_hash(voxel: [i32; 3], q: [f32; 3], face: u32) -> u32 {
    let c = |a: usize| {
        (voxel[a] as u32)
            .wrapping_mul(4)
            .wrapping_add((q[a] * 4.0).floor() as i32 as u32)
    };
    let mut h = c(0).wrapping_mul(0x8da6_b343)
        ^ c(1).wrapping_mul(0xd816_3841)
        ^ c(2).wrapping_mul(0xcb1a_b31f)
        ^ face.wrapping_mul(0x9e37_79b9);
    h ^= h >> 15;
    h = h.wrapping_mul(0x2c1b_3c6d);
    h ^= h >> 12;
    h = h.wrapping_mul(0x297a_2d39);
    h ^= h >> 15;
    h
}

/// Direction cosinus du rayon `i` sur `n` dans le repère de la face (x, y tangents, z selon la normale) : spirale de
/// Fibonacci (stratifiée en rayon) tournée d'un angle tiré du hachage de la position.
pub fn local_direction(i: u32, n: u32, hash: u32) -> [f32; 3] {
    let angle0 = (hash & 0xFFFF) as f32 / 65536.0 * std::f32::consts::TAU;
    let u = (i as f32 + 0.5) / n as f32;
    let r = u.sqrt();
    let phi = angle0 + i as f32 * ANGLE_D_OR;
    [r * phi.cos(), r * phi.sin(), (1.0 - u).max(0.0).sqrt()]
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn les_defauts_sont_valides_et_les_bornes_sont_refusees() {
        let d = AmbientOcclusionParams::default();
        assert!(AmbientOcclusionParams::new(d.rays(), d.range_m()).is_ok());
        assert!(AmbientOcclusionParams::new(0, 1.0).is_err());
        assert!(AmbientOcclusionParams::new(17, 1.0).is_err());
        assert!(AmbientOcclusionParams::new(4, 0.01).is_err());
        assert!(AmbientOcclusionParams::new(4, f32::NAN).is_err());
        assert!(d.with_strength(2.5).is_err());
        assert!(d.with_strength(-0.1).is_err());
        assert!(d.with_filter(4).is_err());
        assert_eq!(d.with_filter(0).unwrap().filter_px(), 0);
        assert!(d.with_resolution_divisor(0).is_err());
        assert!(d.with_resolution_divisor(3).is_err());
        assert_eq!(d.with_resolution_divisor(1).unwrap().resolution_divisor(), 1);
    }

    #[test]
    fn le_poids_decroit_du_contact_a_la_portee() {
        let p = AmbientOcclusionParams::new(4, 1.0).unwrap();
        assert!((p.weight(0.0) - 1.0).abs() < 1e-6);
        assert!(p.weight(10.0) < p.weight(5.0));
        assert_eq!(p.weight(20.0), 0.0);
        assert_eq!(p.weight(100.0), 0.0);
    }

    #[test]
    fn les_directions_sont_unitaires_dans_l_hemisphere_de_la_normale() {
        for h in [0_u32, 1, 0xdead_beef, 0xFFFF] {
            for i in 0..8 {
                let d = local_direction(i, 8, h);
                let n = (d[0] * d[0] + d[1] * d[1] + d[2] * d[2]).sqrt();
                assert!((n - 1.0).abs() < 1e-5, "norme {n}");
                assert!(d[2] > 0.0, "sous le plan");
            }
        }
    }

    #[test]
    fn la_distribution_est_cosinus() {
        // Moyenne de cos θ sur l'hémisphère cosinus : 2/3.
        let n = 16;
        let mut somme = 0.0;
        for i in 0..n {
            somme += local_direction(i, n, 1234)[2];
        }
        assert!((somme / n as f32 - 2.0 / 3.0).abs() < 0.02);
    }

    #[test]
    fn le_hachage_depend_de_la_position_et_de_rien_d_autre() {
        let a = position_hash([10, 5, -7], [0.3, 0.9, 0.0], 2);
        assert_eq!(a, position_hash([10, 5, -7], [0.3, 0.9, 0.0], 2));
        assert_ne!(a, position_hash([10, 5, -7], [0.6, 0.9, 0.0], 2));
        assert_ne!(a, position_hash([11, 5, -7], [0.3, 0.9, 0.0], 2));
        assert_ne!(a, position_hash([10, 5, -7], [0.3, 0.9, 0.0], 3));
    }
}
