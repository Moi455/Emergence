//! `ShadowParams` : réglages des ombres du soleil, validés à la construction (docs/19 § 2.7, règle 1 : champs
//! privés, constructeur qui vérifie l'invariant, accesseurs).

use crate::error::ParamError;

/// Côté d'une tuile de remplissage, en texels (un groupe de 16 × 16 groupes de travail de 8 × 8).
pub const TUILE: u32 = 128;

/// Quand une cascade est-elle refaite ?
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum Regeneration {
    /// Seulement quand le soleil a tourné de plus d'un pas, que la fenêtre a glissé d'un cran ou qu'une
    /// édition a invalidé la cascade (le cas du jeu : coût nul sur une scène qui ne bouge pas).
    #[default]
    SurChangement,
    /// Toujours : dès qu'une génération est finie, la suivante commence (mesure du coût soutenu au banc).
    Continue,
}

fn verifie(nom: &str, v: f32, min: f32, max: f32) -> Result<f32, ParamError> {
    if v.is_finite() && (min..=max).contains(&v) {
        Ok(v)
    } else {
        Err(ParamError::Invalide(format!(
            "ombres : {nom} = {v} hors de [{min}, {max}]"
        )))
    }
}

/// Réglages des cascades d'ombre et de leur échantillonnage.
///
/// Les cascades se suivent par doublement du texel : le texel de la cascade `c` vaut `texel_0 × 2^c`. Avec le
/// préréglage `haut` (4 cascades de 1024², texel de départ 1,25 cm = un quart de voxel) : texels de 1,25 / 2,5 / 5 /
/// 10 cm, portées pleines de 5,6 / 11,2 / 22,4 / 44,8 m. La portée pleine d'une cascade est celle dont le disque
/// reste dans la fenêtre malgré le calage de son centre (un cran de `taille / 32` texels).
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct ShadowParams {
    cascades: u32,
    first_texel_m: f32,
    size: u32,
    tiles_per_frame: u32,
    sun_step_deg: f32,
    normal_offset: f32,
    depth_bias_m: f32,
    slope_bias: f32,
    penumbra_scale: f32,
    penumbra_max_m: f32,
    blend_fraction: f32,
    regeneration: Regeneration,
}

impl ShadowParams {
    /// Nombre maximal de cascades (taille des tableaux de l'uniforme GPU).
    pub const CASCADES_MAX: u32 = 4;

    /// Réglages explicites ; les autres champs prennent la valeur du préréglage `haut`.
    ///
    /// - `cascades` : de 3 à 4 ;
    /// - `first_texel_m` : texel de la cascade 0, de 0,5 cm à 5 cm ;
    /// - `size` : côté des cascades en texels, puissance de 2 de 256 à 2048.
    pub fn new(cascades: u32, first_texel_m: f32, size: u32) -> Result<Self, ParamError> {
        if !(3..=Self::CASCADES_MAX).contains(&cascades) {
            return Err(ParamError::Invalide(format!(
                "ombres : {cascades} cascades (de 3 à {})",
                Self::CASCADES_MAX
            )));
        }
        if !size.is_power_of_two() || !(256..=2048).contains(&size) {
            return Err(ParamError::Invalide(format!(
                "ombres : taille {size} (puissance de 2 de 256 à 2048)"
            )));
        }
        let first_texel_m = verifie("texel de la cascade 0 (m)", first_texel_m, 0.005, 0.05)?;
        Ok(Self {
            cascades,
            first_texel_m,
            size,
            tiles_per_frame: 9,
            sun_step_deg: 0.033,
            normal_offset: 1.0,
            depth_bias_m: 0.001,
            slope_bias: 1.0,
            penumbra_scale: 1.0,
            penumbra_max_m: 0.04,
            blend_fraction: 0.15,
            regeneration: Regeneration::SurChangement,
        })
    }

    /// Tuiles remplies par image (de 1 à 1024). Une génération entière coûte `cascades × (taille / 128)²` tuiles.
    pub fn with_tiles_per_frame(mut self, n: u32) -> Result<Self, ParamError> {
        if !(1..=1024).contains(&n) {
            return Err(ParamError::Invalide(format!(
                "ombres : {n} tuiles par image (de 1 à 1024)"
            )));
        }
        self.tiles_per_frame = n;
        Ok(self)
    }

    /// Angle de soleil (degrés) au-delà duquel une cascade est refaite, de 0,005° à 2°.
    pub fn with_sun_step_deg(mut self, v: f32) -> Result<Self, ParamError> {
        self.sun_step_deg = verifie("pas de soleil (°)", v, 0.005, 2.0)?;
        Ok(self)
    }

    /// Décalage du point éclairé selon la normale, en texels de la cascade (0 à 4), multiplié par le sinus de
    /// l'angle entre la normale et le soleil.
    pub fn with_normal_offset(mut self, v: f32) -> Result<Self, ParamError> {
        self.normal_offset = verifie("décalage normal (texels)", v, 0.0, 4.0)?;
        Ok(self)
    }

    /// Biais de profondeur constant (m, 0 à 0,1) et biais de pente (en texels × tangente, 0 à 4).
    pub fn with_bias(mut self, constant_m: f32, pente: f32) -> Result<Self, ParamError> {
        self.depth_bias_m = verifie("biais de profondeur (m)", constant_m, 0.0, 0.1)?;
        self.slope_bias = verifie("biais de pente", pente, 0.0, 4.0)?;
        Ok(self)
    }

    /// Pénombre : échelle de la pénombre physique (0 = ombre dure, 1 = disque solaire réel) et rayon maximal de
    /// filtrage en mètres (0 à 25 cm).
    pub fn with_penumbra(mut self, echelle: f32, max_m: f32) -> Result<Self, ParamError> {
        self.penumbra_scale = verifie("échelle de pénombre", echelle, 0.0, 1.0)?;
        self.penumbra_max_m = verifie("pénombre maximale (m)", max_m, 0.0, 0.25)?;
        Ok(self)
    }

    /// Part de la portée d'une cascade réservée au fondu vers la suivante (de 2 % à 50 %).
    pub fn with_blend_fraction(mut self, v: f32) -> Result<Self, ParamError> {
        self.blend_fraction = verifie("fraction de fondu", v, 0.02, 0.5)?;
        Ok(self)
    }

    /// Mode de régénération.
    pub fn with_regeneration(mut self, r: Regeneration) -> Self {
        self.regeneration = r;
        self
    }

    /// Nombre de cascades.
    pub fn cascades(&self) -> u32 {
        self.cascades
    }

    /// Côté d'une cascade en texels.
    pub fn size(&self) -> u32 {
        self.size
    }

    /// Texel de la cascade 0, en mètres.
    pub fn first_texel_m(&self) -> f32 {
        self.first_texel_m
    }

    /// Texel de la cascade `c`, en mètres : double à chaque cascade.
    pub fn texel_m(&self, c: u32) -> f64 {
        f64::from(self.first_texel_m) * f64::from(1_u32 << c)
    }

    /// Cran du calage du centre d'une cascade, en texels (`taille / 32`).
    pub fn quantum(&self) -> u32 {
        self.size / 32
    }

    /// Portée pleine de la cascade `c` en mètres : le disque qui reste dans la fenêtre malgré le calage.
    pub fn far_m(&self, c: u32) -> f64 {
        self.texel_m(c) * f64::from(self.size) * (0.5 - 1.0 / 16.0)
    }

    /// Tuiles par côté d'une cascade.
    pub fn tiles_per_side(&self) -> u32 {
        self.size / TUILE
    }

    /// Tuiles d'une génération complète (toutes les cascades).
    pub fn tiles_per_generation(&self) -> u32 {
        self.cascades * self.tiles_per_side() * self.tiles_per_side()
    }

    /// Tuiles remplies par image.
    pub fn tiles_per_frame(&self) -> u32 {
        self.tiles_per_frame
    }

    /// Pas de soleil de régénération, degrés.
    pub fn sun_step_deg(&self) -> f32 {
        self.sun_step_deg
    }

    /// Décalage normal, texels.
    pub fn normal_offset(&self) -> f32 {
        self.normal_offset
    }

    /// Biais de profondeur constant, mètres.
    pub fn depth_bias_m(&self) -> f32 {
        self.depth_bias_m
    }

    /// Biais de pente.
    pub fn slope_bias(&self) -> f32 {
        self.slope_bias
    }

    /// Échelle de la pénombre.
    pub fn penumbra_scale(&self) -> f32 {
        self.penumbra_scale
    }

    /// Rayon maximal de la pénombre, mètres.
    pub fn penumbra_max_m(&self) -> f32 {
        self.penumbra_max_m
    }

    /// Fraction de fondu.
    pub fn blend_fraction(&self) -> f32 {
        self.blend_fraction
    }

    /// Mode de régénération.
    pub fn regeneration(&self) -> Regeneration {
        self.regeneration
    }
}

impl Default for ShadowParams {
    /// Préréglage `haut` du laboratoire : 4 cascades de 1024², texel de 1,25 cm.
    fn default() -> Self {
        Self::new(4, 0.0125, 1024).expect("le préréglage haut est valide")
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn le_prereglage_haut_double_le_texel_et_la_portee() {
        let p = ShadowParams::default();
        assert_eq!(p.cascades(), 4);
        assert!((p.texel_m(0) - 0.0125).abs() < 1e-6);
        assert!((p.texel_m(3) - 0.1).abs() < 1e-6);
        assert!((p.far_m(0) - 5.6).abs() < 1e-6);
        assert!((p.far_m(3) - 44.8).abs() < 1e-6);
        assert_eq!(p.tiles_per_generation(), 4 * 64);
    }

    #[test]
    fn les_valeurs_invalides_sont_refusees() {
        assert!(ShadowParams::new(2, 0.0125, 1024).is_err());
        assert!(ShadowParams::new(5, 0.0125, 1024).is_err());
        assert!(ShadowParams::new(4, 0.0125, 1000).is_err());
        assert!(ShadowParams::new(4, 0.0125, 4096).is_err());
        assert!(ShadowParams::new(4, f32::NAN, 1024).is_err());
        assert!(ShadowParams::new(4, 0.5, 1024).is_err());
        let p = ShadowParams::default();
        assert!(p.with_tiles_per_frame(0).is_err());
        assert!(p.with_sun_step_deg(0.0).is_err());
        assert!(p.with_normal_offset(-1.0).is_err());
        assert!(p.with_bias(0.5, 1.0).is_err());
        assert!(p.with_penumbra(2.0, 0.01).is_err());
        assert!(p.with_blend_fraction(0.9).is_err());
    }
}
