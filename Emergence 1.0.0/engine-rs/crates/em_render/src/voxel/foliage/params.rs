//! `FoliageLightParams` : réglages de la lumière du feuillage (L10 étendue), validés à la construction (docs/19 § 2.7,
//! règle 1 : champs privés, constructeur qui vérifie l'invariant, accesseurs).
//!
//! Elle porte aussi la RÉFÉRENCE CPU de la translucidité ([`FoliageLightParams::translucent_radiance`]), miroir exact
//! du WGSL de `voxel_light.wgsl` : les essais comparent le GPU à ce calcul.

use crate::error::ParamError;

fn verifie(nom: &str, v: f32, min: f32, max: f32) -> Result<f32, ParamError> {
    if v.is_finite() && (min..=max).contains(&v) {
        Ok(v)
    } else {
        Err(ParamError::Invalide(format!(
            "feuillage : {nom} = {v} hors de [{min}, {max}]"
        )))
    }
}

fn verifie_teinte(nom: &str, t: [f32; 3]) -> Result<[f32; 3], ParamError> {
    Ok([
        verifie(&format!("{nom}.r"), t[0], 0.0, 2.0)?,
        verifie(&format!("{nom}.v"), t[1], 0.0, 2.0)?,
        verifie(&format!("{nom}.b"), t[2], 0.0, 2.0)?,
    ])
}

const LUMA: [f32; 3] = [0.2126, 0.7152, 0.0722];

fn luma(c: [f32; 3]) -> f32 {
    c[0] * LUMA[0] + c[1] * LUMA[1] + c[2] * LUMA[2]
}

fn smoothstep(a: f32, b: f32, x: f32) -> f32 {
    let t = ((x - a) / (b - a)).clamp(0.0, 1.0);
    t * t * (3.0 - 2.0 * t)
}

/// Un point de feuille et son éclairage : tout ce que la translucidité lit (miroir des variables du WGSL).
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct LeafLightSample {
    /// Éclairement du soleil au point (transmittance de l'atmosphère × échelle × ombre de la planète).
    pub sun: [f32; 3],
    /// Albédo de la feuille APRÈS saturation.
    pub albedo: [f32; 3],
    /// Translucidité de la matière (0 à 1).
    pub leaf_translucency: f32,
    /// `n · soleil` : la normale regarde l'observateur, négatif quand le soleil est derrière la feuille.
    pub cos_ns: f32,
    /// `direction du regard · soleil` : positif quand on regarde vers le soleil.
    pub cos_vs: f32,
    /// Feuillage traversé le long du soleil, en mètres ([`FoliageLightParams::BLOQUE_M`] si un solide le barre).
    pub thickness_m: f32,
    /// Visibilité du soleil au-delà de la zone comptée (ombre en cascades de L11), 0 à 1.
    pub visibility: f32,
}

/// Lumière du feuillage : translucidité du soleil, liseré de contre-jour, saturation, ombres colorées et regard
/// (exposition et courbe AgX) de la scène de l'arbre.
///
/// Défauts (réglés à l'œil sur le chêne 42 à 18 h 15 et 18 h 45, `docs/19c_journal_style.md`) :
/// - translucidité 1,1 ; longueur d'absorption 1,0 m (les amas de voxels sont pleins alors qu'un vrai houppier est
///   poreux : on les éteint plus lentement qu'une feuille) ; lobe vers l'avant 0,5 ; teinte de transmission
///   (0,7 ; 1 ; 0,2) : un vert-jaune saturé ;
/// - liseré 0,3 sur les 0,20 m les plus minces du feuillage, face au soleil ;
/// - saturation du feuillage 1,05 ; ombres relevées de 0,02 de l'éclairement du soleil, en bleu-violet ;
/// - zone de comptage de l'épaisseur : 48 voxels (2,4 m) le long du soleil ;
/// - regard : gain d'exposition 0,8, saturation 1,1, contraste 1,2 et chaleur de golden hour 0,10 de la composition AgX.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct FoliageLightParams {
    translucency: f32,
    absorption_m: f32,
    forward: f32,
    tint: [f32; 3],
    rim: f32,
    rim_thickness_m: f32,
    saturation: f32,
    shadow_lift: f32,
    shadow_tint: [f32; 3],
    zone_voxels: u32,
    exposure_gain: f32,
    grade_saturation: f32,
    grade_contrast: f32,
    grade_warmth: f32,
}

impl FoliageLightParams {
    /// Réglages de la translucidité : `translucency` dans [0, 4] (0 = éteinte) et `absorption_m` dans [0,05 ; 2]
    /// (longueur sur laquelle le feuillage éteint la lumière, en mètres) ; les autres champs prennent leur défaut.
    pub fn new(translucency: f32, absorption_m: f32) -> Result<Self, ParamError> {
        Ok(Self {
            translucency: verifie("translucidité", translucency, 0.0, 4.0)?,
            absorption_m: verifie("longueur d'absorption (m)", absorption_m, 0.05, 2.0)?,
            ..Self::default()
        })
    }

    /// Lobe vers l'avant dans [0, 1] (0 : la translucidité ne dépend pas de l'angle de vue ; 1 : seulement quand on
    /// regarde vers le soleil) et teinte de transmission, chaque canal dans [0, 2].
    pub fn with_transmission(mut self, forward: f32, tint: [f32; 3]) -> Result<Self, ParamError> {
        self.forward = verifie("lobe avant", forward, 0.0, 1.0)?;
        self.tint = verifie_teinte("teinte de transmission", tint)?;
        Ok(self)
    }

    /// Liseré de contre-jour : force dans [0, 4] et épaisseur de feuillage (m) sous laquelle il brille, dans
    /// [0,05 ; 1].
    pub fn with_rim(mut self, rim: f32, thickness_m: f32) -> Result<Self, ParamError> {
        self.rim = verifie("liseré", rim, 0.0, 4.0)?;
        self.rim_thickness_m = verifie("épaisseur du liseré (m)", thickness_m, 0.05, 1.0)?;
        Ok(self)
    }

    /// Saturation du feuillage dans [0,5 ; 2] (1 = couleur de la matière) ; ombres colorées : soulèvement dans
    /// [0 ; 0,5] de l'éclairement du soleil et teinte de ce soulèvement.
    pub fn with_color(
        mut self,
        saturation: f32,
        shadow_lift: f32,
        shadow_tint: [f32; 3],
    ) -> Result<Self, ParamError> {
        self.saturation = verifie("saturation du feuillage", saturation, 0.5, 2.0)?;
        self.shadow_lift = verifie("soulèvement des ombres", shadow_lift, 0.0, 0.5)?;
        self.shadow_tint = verifie_teinte("teinte des ombres", shadow_tint)?;
        Ok(self)
    }

    /// Nombre de voxels (de 4 à 48) le long du soleil sur lesquels on compte l'épaisseur du feuillage ; au-delà,
    /// l'ombre de L11 prend le relais.
    pub fn with_zone(mut self, voxels: u32) -> Result<Self, ParamError> {
        if !(4..=48).contains(&voxels) {
            return Err(ParamError::Invalide(format!(
                "feuillage : zone = {voxels} voxels hors de [4, 48]"
            )));
        }
        self.zone_voxels = voxels;
        Ok(self)
    }

    /// Regard de la composition : gain d'exposition dans [0,25 ; 4] (multiplie l'exposition de la scène),
    /// saturation dans [0,5 ; 2], contraste (puissance AgX) dans [0,5 ; 2] et chaleur de la golden hour dans
    /// [0 ; 0,3] (voir [`Self::warmth_at`]).
    pub fn with_grade(
        mut self,
        exposure_gain: f32,
        saturation: f32,
        contrast: f32,
        warmth: f32,
    ) -> Result<Self, ParamError> {
        self.grade_warmth = verifie("chaleur du regard", warmth, 0.0, 0.3)?;
        self.exposure_gain = verifie("gain d'exposition", exposure_gain, 0.25, 4.0)?;
        self.grade_saturation = verifie("saturation du regard", saturation, 0.5, 2.0)?;
        self.grade_contrast = verifie("contraste du regard", contrast, 0.5, 2.0)?;
        Ok(self)
    }

    /// Force de la translucidité.
    pub fn translucency(&self) -> f32 {
        self.translucency
    }

    /// Longueur d'absorption du feuillage, en mètres.
    pub fn absorption_m(&self) -> f32 {
        self.absorption_m
    }

    /// Lobe vers l'avant.
    pub fn forward(&self) -> f32 {
        self.forward
    }

    /// Teinte de transmission.
    pub fn tint(&self) -> [f32; 3] {
        self.tint
    }

    /// Force du liseré.
    pub fn rim(&self) -> f32 {
        self.rim
    }

    /// Épaisseur de feuillage sous laquelle le liseré brille, en mètres.
    pub fn rim_thickness_m(&self) -> f32 {
        self.rim_thickness_m
    }

    /// Saturation du feuillage.
    pub fn saturation(&self) -> f32 {
        self.saturation
    }

    /// Soulèvement des ombres.
    pub fn shadow_lift(&self) -> f32 {
        self.shadow_lift
    }

    /// Teinte des ombres.
    pub fn shadow_tint(&self) -> [f32; 3] {
        self.shadow_tint
    }

    /// Voxels comptés le long du soleil.
    pub fn zone_voxels(&self) -> u32 {
        self.zone_voxels
    }

    /// Longueur de la zone de comptage, en mètres.
    pub fn zone_m(&self) -> f32 {
        self.zone_voxels as f32 * em_core::VOXEL_MM as f32 * 0.001
    }

    /// Chaleur du regard à la golden hour (valeur maximale).
    pub fn grade_warmth(&self) -> f32 {
        self.grade_warmth
    }

    /// Chaleur appliquée par la composition quand le soleil est à `elevation_deg` : nulle au-dessus de 30°, pleine
    /// sous 5° (rouge vers le haut, bleu vers le bas, comme `PostParams::warmth`). Étalonnage : l'œil lit la
    /// lumière du soir plus dorée qu'un capteur ne l'enregistre.
    pub fn warmth_at(&self, elevation_deg: f32) -> f32 {
        self.grade_warmth * (1.0 - smoothstep(5.0, 30.0, elevation_deg))
    }

    /// Épaisseur de feuillage (en voxels) au-delà de laquelle la passe d'épaisseur s'arrête : la lumière qui reste
    /// (`exp(-3,5) ≈ 3 %`) est négligeable, et chaque voxel en moins est un pas de moins par pixel.
    pub fn cutoff_voxels(&self) -> f32 {
        (3.5 * self.absorption_m / (em_core::VOXEL_MM as f32 * 0.001)).min(self.zone_voxels as f32)
    }

    /// Gain d'exposition du regard.
    pub fn exposure_gain(&self) -> f32 {
        self.exposure_gain
    }

    /// Saturation du regard.
    pub fn grade_saturation(&self) -> f32 {
        self.grade_saturation
    }

    /// Contraste du regard.
    pub fn grade_contrast(&self) -> f32 {
        self.grade_contrast
    }

    /// Albédo du feuillage après saturation (miroir de `voxel_light.wgsl`).
    pub fn saturate_albedo(&self, albedo: [f32; 3]) -> [f32; 3] {
        let l = luma(albedo);
        albedo.map(|c| (l + self.saturation * (c - l)).max(0.0))
    }

    /// Part de l'épaisseur de feuillage qui traverse : `exp(-épaisseur / longueur d'absorption)`, nulle si le
    /// soleil est bloqué (épaisseur > 500 m : code « occulté » écrit par la passe d'épaisseur).
    pub fn attenuation(&self, thickness_m: f32) -> f32 {
        if thickness_m > Self::BLOQUE_M * 0.5 {
            0.0
        } else {
            (-thickness_m / self.absorption_m).exp()
        }
    }

    /// Épaisseur écrite par la passe d'épaisseur quand un solide qui n'est pas du feuillage barre le soleil.
    pub const BLOQUE_M: f32 = 1000.0;

    /// Rayonnement ajouté par la transmission du soleil à travers une feuille et par le liseré (miroir EXACT du
    /// WGSL), en HDR linéaire, pour l'échantillon `f` (voir [`LeafLightSample`]).
    pub fn translucent_radiance(&self, f: &LeafLightSample) -> [f32; 3] {
        let pi = std::f32::consts::PI;
        let back = smoothstep(0.35, -0.35, f.cos_ns);
        let att = self.attenuation(f.thickness_m);
        let cos_vs = f.cos_vs.clamp(0.0, 1.0);
        let lobe = (1.0 - self.forward) + self.forward * cos_vs * cos_vs;
        let k = f.leaf_translucency * self.translucency * back * att * f.visibility * lobe / pi;
        let tcol = [
            f.albedo[0].max(0.0).sqrt() * self.tint[0],
            f.albedo[1].max(0.0).sqrt() * self.tint[1],
            f.albedo[2].max(0.0).sqrt() * self.tint[2],
        ];
        // Liseré : seulement le feuillage mince (bord d'un amas), face au soleil, sans flou.
        let mince = if f.thickness_m > Self::BLOQUE_M * 0.5 {
            0.0
        } else {
            1.0 - smoothstep(0.04, self.rim_thickness_m, f.thickness_m)
        };
        let c2 = cos_vs * cos_vs;
        let rim = self.rim * (c2 * c2) * back * mince * f.visibility / pi;
        let dore = [1.0, 0.8, 0.35];
        let mut sortie = [0.0; 3];
        for c in 0..3 {
            let couleur_rim = tcol[c] * 0.5 + dore[c] * 0.5;
            sortie[c] = f.sun[c] * (k * tcol[c] + rim * couleur_rim);
        }
        sortie
    }

    /// Soulèvement coloré des ombres (miroir du WGSL) : radiance ajoutée avant l'albédo.
    pub fn shadow_lift_radiance(&self, sun: [f32; 3]) -> [f32; 3] {
        let l = luma(sun) * self.shadow_lift;
        self.shadow_tint.map(|c| c * l)
    }
}

impl Default for FoliageLightParams {
    fn default() -> Self {
        Self {
            translucency: 1.1,
            absorption_m: 1.0,
            forward: 0.5,
            tint: [0.7, 1.0, 0.2],
            rim: 0.3,
            rim_thickness_m: 0.20,
            saturation: 1.05,
            shadow_lift: 0.02,
            shadow_tint: [0.45, 0.55, 1.0],
            zone_voxels: 48,
            exposure_gain: 0.8,
            grade_saturation: 1.1,
            grade_contrast: 1.2,
            grade_warmth: 0.10,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn les_reglages_invalides_sont_refuses() {
        assert!(FoliageLightParams::new(5.0, 0.3).is_err());
        assert!(FoliageLightParams::new(1.0, 0.0).is_err());
        assert!(FoliageLightParams::new(f32::NAN, 0.3).is_err());
        let p = FoliageLightParams::default();
        assert!(p.with_transmission(1.5, [1.0; 3]).is_err());
        assert!(p.with_transmission(0.5, [1.0, 3.0, 1.0]).is_err());
        assert!(p.with_rim(0.5, 0.0).is_err());
        assert!(p.with_color(0.1, 0.0, [1.0; 3]).is_err());
        assert!(p.with_zone(2).is_err());
        assert!(p.with_zone(64).is_err());
        assert!(p.with_grade(0.0, 1.0, 1.0, 0.0).is_err());
        assert!(p.with_grade(1.0, 1.0, 1.0, 0.5).is_err());
        assert!(FoliageLightParams::new(2.0, 0.5).unwrap().with_zone(20).is_ok());
    }

    #[test]
    fn la_translucidite_est_plus_forte_mince_que_epais_et_nulle_si_occultee() {
        let p = FoliageLightParams::default();
        let soleil = [9.0, 5.7, 2.6];
        let albedo = [0.12, 0.35, 0.05];
        let rad = |epaisseur: f32, visibilite: f32, cos_ns: f32| {
            p.translucent_radiance(&LeafLightSample {
                sun: soleil,
                albedo,
                leaf_translucency: 0.45,
                cos_ns,
                cos_vs: 0.9,
                thickness_m: epaisseur,
                visibility: visibilite,
            })
        };
        let somme = |c: [f32; 3]| c[0] + c[1] + c[2];
        let mince = somme(rad(0.1, 1.0, -0.8));
        let epais = somme(rad(0.8, 1.0, -0.8));
        assert!(mince > 2.0 * epais && epais > 0.0, "{mince} / {epais}");
        // Ombre de L11 (une autre feuille devant) ou solide qui barre le soleil : rien ne passe.
        assert_eq!(somme(rad(0.1, 0.0, -0.8)), 0.0);
        assert_eq!(somme(rad(FoliageLightParams::BLOQUE_M, 1.0, -0.8)), 0.0);
        // Face tournée vers le soleil : c'est l'éclairage direct qui joue, pas la transmission.
        assert_eq!(somme(rad(0.1, 1.0, 0.6)), 0.0);
        // Le vert-jaune domine : le bleu est le plus faible.
        let c = rad(0.1, 1.0, -0.8);
        assert!(c[1] > c[2] && c[0] > c[2], "{c:?}");
    }

    #[test]
    fn la_chaleur_croit_quand_le_soleil_descend() {
        let p = FoliageLightParams::default();
        assert_eq!(p.warmth_at(67.0), 0.0);
        assert!(p.warmth_at(14.0) > 0.0 && p.warmth_at(9.0) > p.warmth_at(14.0));
        assert!((p.warmth_at(2.0) - p.grade_warmth()).abs() < 1e-6);
    }

    #[test]
    fn la_saturation_garde_la_luminance() {
        let p = FoliageLightParams::default();
        let a = [0.12, 0.35, 0.05];
        let s = p.saturate_albedo(a);
        assert!((luma(s) - luma(a)).abs() < 1e-5);
        assert!(s[1] - s[0] > a[1] - a[0], "plus saturé");
        let neutre = p.saturate_albedo([0.3; 3]);
        assert!(neutre.iter().all(|c| (c - 0.3).abs() < 1e-6));
    }
}
