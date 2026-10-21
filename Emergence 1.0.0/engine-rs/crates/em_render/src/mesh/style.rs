//! Réglages de style du rendu par maillage (L34) : relief froissé sous-voxel, occlusion creuse, chaleur de l'ambiance.
//!
//! - [`ReliefParams`] : la perturbation de la normale des surfaces (pierre, bois, toit) par un bruit ancré au MONDE ;
//!   force, portée de pleine force et distance où le relief s'éteint. Le bruit de COULEUR sous-voxel n'existe pas :
//!   décision de Monsieur du 21 oct. 2026, un voxel = une couleur plate.
//! - [`MeshStyle`] : tout ce que le fragment lit en plus de la lumière (table de l'occlusion, creux, chaleur, atténuation
//!   des faces intérieures), rangé en uniforme.

use bytemuck::{Pod, Zeroable};
use em_mesh::CreuxAoParams;

/// Réglage hors de sa plage.
#[derive(Debug, Clone, PartialEq, thiserror::Error)]
#[error("{nom} = {valeur} hors de {min}..={max}")]
pub struct StyleError {
    nom: &'static str,
    valeur: f32,
    min: f32,
    max: f32,
}

fn dans(nom: &'static str, valeur: f32, min: f32, max: f32) -> Result<f32, StyleError> {
    if (min..=max).contains(&valeur) {
        Ok(valeur)
    } else {
        Err(StyleError {
            nom,
            valeur,
            min,
            max,
        })
    }
}

/// Relief froissé sous-voxel (port de `patchStd` de `maison-voxel.html`) : la normale est perturbée par les dérivées
/// d'écran d'une hauteur (luminance de l'albédo, bruit de valeur à deux octaves, biseau léger d'arête de voxel), pente
/// limitée. Amplitude par matière = `relief` de la classe (octet de rendu) x `force`.
#[derive(Copy, Clone, Debug, PartialEq)]
pub struct ReliefParams {
    strength: f32,
    full_m: f32,
    zero_m: f32,
}

impl ReliefParams {
    /// Force maximale.
    pub const FORCE_MAX: f32 = 4.0;

    /// Relief éteint (les surfaces restent planes, comme avant L34).
    pub const fn off() -> Self {
        Self {
            strength: 0.0,
            full_m: 3.0,
            zero_m: 12.0,
        }
    }

    /// Force 0 à 4 (1 = la démo de Monsieur), fondu par défaut : plein jusqu'à 3 m, nul au-delà de 12 m.
    pub fn new(strength: f32) -> Result<Self, StyleError> {
        Ok(Self {
            strength: dans("relief-force", strength, 0.0, Self::FORCE_MAX)?,
            ..Self::default()
        })
    }

    /// Fondu avec la distance : relief plein jusqu'à `full_m`, nul à partir de `zero_m` (mètres, `zero_m > full_m`).
    pub fn with_range(mut self, full_m: f32, zero_m: f32) -> Result<Self, StyleError> {
        let f = dans("relief-portee (plein)", full_m, 0.1, 50.0)?;
        let z = dans("relief-portee (nul)", zero_m, 0.2, 100.0)?;
        if z <= f {
            return Err(StyleError {
                nom: "relief-portee (nul doit dépasser plein)",
                valeur: z,
                min: f,
                max: 100.0,
            });
        }
        self.full_m = f;
        self.zero_m = z;
        Ok(self)
    }

    /// Force.
    pub const fn strength(&self) -> f32 {
        self.strength
    }

    /// Distance de pleine force, en mètres.
    pub const fn full_m(&self) -> f32 {
        self.full_m
    }

    /// Distance où le relief s'éteint, en mètres.
    pub const fn zero_m(&self) -> f32 {
        self.zero_m
    }

    /// Vrai si le relief est actif.
    pub fn enabled(&self) -> bool {
        self.strength > 0.0
    }
}

impl Default for ReliefParams {
    /// Relief ÉTEINT par défaut (décision de Monsieur du 21 oct. : « on fait sans le relief ») ; réglage de labo : `--relief-force 1.5`
    /// (plein jusqu'à 3 m, nul à 12 m).
    fn default() -> Self {
        Self {
            strength: 0.0,
            full_m: 3.0,
            zero_m: 12.0,
        }
    }
}

/// Style du rendu par maillage.
#[derive(Copy, Clone, Debug, PartialEq)]
pub struct MeshStyle {
    relief: ReliefParams,
    creux: CreuxAoParams,
    warmth: f32,
    interior: f32,
}

impl MeshStyle {
    /// Facteur d'ambiance d'une face intérieure : celui de la référence de Monsieur.
    pub const INTERIEUR_DEFAUT: f32 = 0.45;

    /// Style par défaut du labo : relief éteint, occlusion creuse de force 1, chaleur 0, intérieur x0,45.
    pub fn new() -> Self {
        Self {
            relief: ReliefParams::default(),
            creux: CreuxAoParams::default(),
            warmth: 0.0,
            interior: Self::INTERIEUR_DEFAUT,
        }
    }

    /// Le style de L33, sans rien de L34 : ni relief, ni creux.
    pub fn l33() -> Self {
        Self {
            relief: ReliefParams::off(),
            creux: CreuxAoParams::disabled(),
            warmth: 0.0,
            interior: 1.0,
        }
    }

    /// Change le relief.
    pub fn with_relief(mut self, r: ReliefParams) -> Self {
        self.relief = r;
        self
    }

    /// Change l'occlusion creuse.
    pub fn with_creux(mut self, c: CreuxAoParams) -> Self {
        self.creux = c;
        self
    }

    /// Chaleur de l'ambiance, 0 (ciel tel quel) à 1 : l'ambiance froide de la face à l'ombre est tirée vers le beige.
    pub fn with_warmth(mut self, w: f32) -> Result<Self, StyleError> {
        self.warmth = dans("ambiance-chaleur", w, 0.0, 1.0)?;
        Ok(self)
    }

    /// Relief.
    pub const fn relief(&self) -> ReliefParams {
        self.relief
    }

    /// Occlusion creuse.
    pub const fn creux(&self) -> CreuxAoParams {
        self.creux
    }

    /// Chaleur de l'ambiance.
    pub const fn warmth(&self) -> f32 {
        self.warmth
    }

    /// L'uniforme du shader.
    pub(crate) fn uniform(&self) -> StyleUniform {
        let v = self.creux.vertex_levels();
        let c = self.creux.creux_levels();
        StyleUniform {
            relief: [self.relief.strength, self.relief.full_m, self.relief.zero_m, 0.0],
            ao: v,
            creux: c,
            divers: [self.interior, self.warmth, 0.0, 0.0],
        }
    }
}

impl Default for MeshStyle {
    fn default() -> Self {
        Self::new()
    }
}

/// Miroir de `struct StyleU` de `mesh_main.wgsl`.
#[repr(C)]
#[derive(Clone, Copy, Pod, Zeroable)]
pub(crate) struct StyleUniform {
    relief: [f32; 4],
    ao: [f32; 4],
    creux: [f32; 4],
    divers: [f32; 4],
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn relief_valide_ses_plages() {
        assert!(ReliefParams::new(0.0).is_ok() && ReliefParams::new(4.0).is_ok());
        assert!(ReliefParams::new(-1.0).is_err() && ReliefParams::new(4.1).is_err());
        assert!(ReliefParams::new(f32::NAN).is_err());
        let r = ReliefParams::default();
        assert!(r.with_range(5.0, 5.0).is_err(), "le nul doit dépasser le plein");
        assert!(r.with_range(0.0, 3.0).is_err() && r.with_range(1.0, 400.0).is_err());
        let r = r.with_range(1.0, 4.0).unwrap();
        assert_eq!((r.full_m(), r.zero_m()), (1.0, 4.0));
    }

    #[test]
    fn par_defaut_le_relief_est_eteint_et_le_style_l33_est_plat() {
        assert!(!MeshStyle::new().relief().enabled());
        assert!(ReliefParams::new(1.5).unwrap().enabled());
        assert!(!ReliefParams::off().enabled());
        let s = MeshStyle::l33();
        assert!(!s.relief().enabled() && !s.creux().enabled());
        assert_eq!(s.uniform().ao, em_mesh::AO_FACTOR);
        assert!(MeshStyle::new().with_warmth(1.5).is_err());
        assert_eq!(MeshStyle::new().with_warmth(0.4).unwrap().warmth(), 0.4);
    }
}
