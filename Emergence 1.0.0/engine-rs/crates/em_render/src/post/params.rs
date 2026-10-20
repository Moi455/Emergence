//! Réglages de la post-production (exposition, bloom, regard AgX), validés à la construction.

use crate::error::ParamError;

fn verifie(nom: &str, v: f32, min: f32, max: f32) -> Result<f32, ParamError> {
    if v.is_finite() && (min..=max).contains(&v) {
        Ok(v)
    } else {
        Err(ParamError::Invalide(format!(
            "{nom} = {v} hors de [{min}, {max}]"
        )))
    }
}

/// Réglages de composition : exposition, force du bloom et regard (vignette, saturation, contraste, chaleur).
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct PostParams {
    exposure: f32,
    bloom: f32,
    vignette: f32,
    saturation: f32,
    contrast: f32,
    warmth: f32,
}

impl PostParams {
    /// Exposition dans [0,01 ; 256] (multiplicateur linéaire) et force du bloom dans [0, 1] ; regard par défaut.
    pub fn new(exposure: f32, bloom: f32) -> Result<Self, ParamError> {
        Ok(Self {
            exposure: verifie("exposition", exposure, 0.01, 256.0)?,
            bloom: verifie("bloom", bloom, 0.0, 1.0)?,
            ..Self::default()
        })
    }

    /// Règle le regard : vignette [0, 1], saturation [0, 2], contraste (puissance) [0,5 ; 2], chaleur [-0,5 ; 0,5].
    pub fn with_look(
        mut self,
        vignette: f32,
        saturation: f32,
        contrast: f32,
        warmth: f32,
    ) -> Result<Self, ParamError> {
        self.vignette = verifie("vignette", vignette, 0.0, 1.0)?;
        self.saturation = verifie("saturation", saturation, 0.0, 2.0)?;
        self.contrast = verifie("contraste", contrast, 0.5, 2.0)?;
        self.warmth = verifie("chaleur", warmth, -0.5, 0.5)?;
        Ok(self)
    }

    /// Exposition (multiplicateur linéaire).
    pub fn exposure(&self) -> f32 {
        self.exposure
    }

    /// Force du bloom.
    pub fn bloom(&self) -> f32 {
        self.bloom
    }

    /// Vignette.
    pub fn vignette(&self) -> f32 {
        self.vignette
    }

    /// Saturation du regard.
    pub fn saturation(&self) -> f32 {
        self.saturation
    }

    /// Contraste du regard (puissance).
    pub fn contrast(&self) -> f32 {
        self.contrast
    }

    /// Chaleur (positif : plus rouge).
    pub fn warmth(&self) -> f32 {
        self.warmth
    }
}

impl Default for PostParams {
    /// Réglages de `web-ocean`, sans le refroidissement de l'océan : exposition 1,35, bloom 0,10.
    fn default() -> Self {
        Self {
            exposure: 1.35,
            bloom: 0.10,
            vignette: 0.10,
            saturation: 1.05,
            contrast: 1.06,
            warmth: 0.0,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn les_reglages_invalides_sont_refuses() {
        assert!(PostParams::new(0.0, 0.1).is_err());
        assert!(PostParams::new(1.0, 2.0).is_err());
        assert!(PostParams::new(f32::NAN, 0.1).is_err());
        assert!(PostParams::default().with_look(0.1, 3.0, 1.0, 0.0).is_err());
        assert!(
            PostParams::new(2.0, 0.2)
                .unwrap()
                .with_look(0.1, 1.0, 1.0, 0.1)
                .is_ok()
        );
    }
}
