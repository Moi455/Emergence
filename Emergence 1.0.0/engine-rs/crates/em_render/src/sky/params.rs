//! Paramètres du ciel : objets valeur à champs PRIVÉS, construits par des constructeurs qui vérifient
//! l'invariant (docs/19 § 2.7 règle 1). Aucune valeur invalide n'atteint le GPU.

use crate::error::ParamError;
use glam::Vec3;

fn verifie(nom: &str, v: f32, min: f32, max: f32) -> Result<f32, ParamError> {
    if v.is_finite() && (min..=max).contains(&v) {
        Ok(v)
    } else {
        Err(ParamError::Invalide(format!(
            "{nom} = {v} hors de [{min}, {max}]"
        )))
    }
}

/// Nuages : deux couches plates (cumulus bas, voile haut à 4,5 km), comme `web-ocean`.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct CloudParams {
    altitude_km: f32,
    coverage: f32,
    density: f32,
    wind_time: f32,
    veil: f32,
}

impl CloudParams {
    /// Construit des nuages. `altitude_km` de la couche basse dans [0,5 ; 4], `coverage` et `veil` (voile
    /// haut) dans [0, 1], `density` optique dans [0,1 ; 8], `wind_time` (déplacement des nuages) dans [0, 1e6].
    pub fn new(
        altitude_km: f32,
        coverage: f32,
        density: f32,
        wind_time: f32,
        veil: f32,
    ) -> Result<Self, ParamError> {
        Ok(Self {
            altitude_km: verifie("nuages : altitude (km)", altitude_km, 0.5, 4.0)?,
            coverage: verifie("nuages : couverture", coverage, 0.0, 1.0)?,
            density: verifie("nuages : densité", density, 0.1, 8.0)?,
            wind_time: verifie("nuages : temps de vent", wind_time, 0.0, 1.0e6)?,
            veil: verifie("nuages : voile haut", veil, 0.0, 1.0)?,
        })
    }

    /// Altitude de la couche basse (km).
    pub fn altitude_km(&self) -> f32 {
        self.altitude_km
    }

    /// Couverture de la couche basse, dans [0, 1].
    pub fn coverage(&self) -> f32 {
        self.coverage
    }

    /// Densité optique de la couche basse.
    pub fn density(&self) -> f32 {
        self.density
    }

    /// Temps de vent (dérive des nuages).
    pub fn wind_time(&self) -> f32 {
        self.wind_time
    }

    /// Couverture du voile haut, dans [0, 1].
    pub fn veil(&self) -> f32 {
        self.veil
    }
}

impl Default for CloudParams {
    /// Réglage de `web-ocean` : couverture 0,40, voile 0,36, couche basse à 1,5 km.
    fn default() -> Self {
        Self {
            altitude_km: 1.5,
            coverage: 0.40,
            density: 2.2,
            wind_time: 0.0,
            veil: 0.36,
        }
    }
}

/// Paramètres du ciel. Tout changement de `turbidity` ou d'élévation du soleil fait recalculer les LUT.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct SkyParams {
    sun_elevation_deg: f32,
    sun_azimuth_deg: f32,
    turbidity: f32,
    haze: f32,
    sun_illuminance: f32,
    clouds: CloudParams,
}

impl SkyParams {
    /// Éclairement solaire par défaut (échelle de `web-ocean`).
    pub const ECLAIREMENT_DEFAUT: f32 = 14.0;

    /// Construit des paramètres de ciel.
    ///
    /// - `sun_elevation_deg` dans [-30, 90] ;
    /// - `sun_azimuth_deg` fini (ramené dans [0, 360) ; 0 = vers -Z, 90 = vers +X, sens horaire vu d'en haut) ;
    /// - `turbidity` dans [0,5 ; 15] : multiplicateur des aérosols (diffusion de Mie) de l'atmosphère ;
    /// - `haze` (brume) dans [0, 1] : plancher d'extinction près du sol (perspective aérienne).
    pub fn new(
        sun_elevation_deg: f32,
        sun_azimuth_deg: f32,
        turbidity: f32,
        haze: f32,
    ) -> Result<Self, ParamError> {
        let azimut = if sun_azimuth_deg.is_finite() {
            sun_azimuth_deg.rem_euclid(360.0)
        } else {
            return Err(ParamError::Invalide(format!(
                "azimut du soleil non fini : {sun_azimuth_deg}"
            )));
        };
        Ok(Self {
            sun_elevation_deg: verifie("élévation du soleil (°)", sun_elevation_deg, -30.0, 90.0)?,
            sun_azimuth_deg: azimut,
            turbidity: verifie("turbidité", turbidity, 0.5, 15.0)?,
            haze: verifie("brume", haze, 0.0, 1.0)?,
            sun_illuminance: Self::ECLAIREMENT_DEFAUT,
            clouds: CloudParams::default(),
        })
    }

    /// Remplace les nuages.
    pub fn with_clouds(mut self, clouds: CloudParams) -> Self {
        self.clouds = clouds;
        self
    }

    /// Remplace l'éclairement solaire, dans ]0 ; 100].
    pub fn with_sun_illuminance(mut self, valeur: f32) -> Result<Self, ParamError> {
        if !(valeur.is_finite() && valeur > 0.0 && valeur <= 100.0) {
            return Err(ParamError::Invalide(format!(
                "éclairement solaire = {valeur} hors de ]0, 100]"
            )));
        }
        self.sun_illuminance = valeur;
        Ok(self)
    }

    /// Élévation du soleil (degrés).
    pub fn sun_elevation_deg(&self) -> f32 {
        self.sun_elevation_deg
    }

    /// Azimut du soleil (degrés, [0, 360)).
    pub fn sun_azimuth_deg(&self) -> f32 {
        self.sun_azimuth_deg
    }

    /// Turbidité (multiplicateur de Mie).
    pub fn turbidity(&self) -> f32 {
        self.turbidity
    }

    /// Brume, dans [0, 1].
    pub fn haze(&self) -> f32 {
        self.haze
    }

    /// Échelle d'éclairement solaire.
    pub fn sun_illuminance(&self) -> f32 {
        self.sun_illuminance
    }

    /// Nuages.
    pub fn clouds(&self) -> &CloudParams {
        &self.clouds
    }

    /// Direction VERS le soleil (unitaire, y haut), formule de `web-ocean`.
    pub fn sun_direction(&self) -> Vec3 {
        let (se, ce) = self.sun_elevation_deg.to_radians().sin_cos();
        let (sa, ca) = self.sun_azimuth_deg.to_radians().sin_cos();
        Vec3::new(sa * ce, se, -ca * ce)
    }

    /// Plancher d'extinction de la brume près du sol (par mètre) : 0,3 donne 1,1e-4, la valeur de `web-ocean`.
    pub fn haze_floor_per_m(&self) -> f32 {
        2.0e-5 + self.haze * 3.0e-4
    }
}

impl Default for SkyParams {
    /// Soleil à 35° au sud-est, turbidité 3, brume 0,3, nuages par défaut.
    fn default() -> Self {
        Self {
            sun_elevation_deg: 35.0,
            sun_azimuth_deg: 135.0,
            turbidity: 3.0,
            haze: 0.3,
            sun_illuminance: Self::ECLAIREMENT_DEFAUT,
            clouds: CloudParams::default(),
        }
    }
}

/// Position du soleil d'un lieu et d'un jour (docs/19b L03). 1 jour de jeu = 1 h 30 réelle : géré par l'appelant.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct SunModel {
    latitude_deg: f32,
    day_of_year: u16,
}

impl SunModel {
    /// Latitude dans [-90, 90] (nord positif), jour de l'année dans [1, 366].
    pub fn new(latitude_deg: f32, day_of_year: u16) -> Result<Self, ParamError> {
        verifie("latitude (°)", latitude_deg, -90.0, 90.0)?;
        if !(1..=366).contains(&day_of_year) {
            return Err(ParamError::Invalide(format!(
                "jour de l'année = {day_of_year} hors de [1, 366]"
            )));
        }
        Ok(Self {
            latitude_deg,
            day_of_year,
        })
    }

    /// Latitude (degrés).
    pub fn latitude_deg(&self) -> f32 {
        self.latitude_deg
    }

    /// Jour de l'année.
    pub fn day_of_year(&self) -> u16 {
        self.day_of_year
    }

    /// (élévation, azimut) du soleil en degrés pour l'heure solaire vraie `hour` (0 à 24, midi = 12).
    /// L'azimut suit la convention de `SkyParams` : 0 = nord (-Z), 90 = est (+X).
    pub fn position(&self, hour: f32) -> (f32, f32) {
        let declinaison = (23.44_f32
            * (std::f32::consts::TAU * (f32::from(self.day_of_year) + 284.0) / 365.0).sin())
        .to_radians();
        let latitude = self.latitude_deg.to_radians();
        let angle_horaire = (15.0 * (hour - 12.0)).to_radians();
        let (sd, cd) = declinaison.sin_cos();
        let (sl, cl) = latitude.sin_cos();
        let elevation = (sl * sd + cl * cd * angle_horaire.cos()).clamp(-1.0, 1.0).asin();
        let est = -cd * angle_horaire.sin();
        let nord = sd * cl - cd * sl * angle_horaire.cos();
        let azimut = est.atan2(nord).to_degrees().rem_euclid(360.0);
        (elevation.to_degrees(), azimut)
    }

    /// Direction vers le soleil (y haut) pour cette heure.
    pub fn sun_direction(&self, hour: f32) -> Vec3 {
        let (e, a) = self.position(hour);
        let (se, ce) = e.to_radians().sin_cos();
        let (sa, ca) = a.to_radians().sin_cos();
        Vec3::new(sa * ce, se, -ca * ce)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn les_parametres_invalides_sont_refuses() {
        assert!(SkyParams::new(95.0, 0.0, 3.0, 0.3).is_err());
        assert!(SkyParams::new(10.0, f32::NAN, 3.0, 0.3).is_err());
        assert!(SkyParams::new(10.0, 0.0, 0.1, 0.3).is_err());
        assert!(SkyParams::new(10.0, 0.0, 3.0, 1.5).is_err());
        assert!(
            SkyParams::new(10.0, 0.0, 3.0, 0.3)
                .unwrap()
                .with_sun_illuminance(0.0)
                .is_err()
        );
        assert!(CloudParams::new(1.5, 2.0, 2.0, 0.0, 0.3).is_err());
    }

    #[test]
    fn l_azimut_est_ramene_dans_0_360() {
        let p = SkyParams::new(10.0, -90.0, 3.0, 0.3).unwrap();
        assert!((p.sun_azimuth_deg() - 270.0).abs() < 1e-4);
    }

    #[test]
    fn la_direction_du_soleil_est_unitaire_et_orientee() {
        let p = SkyParams::new(30.0, 90.0, 3.0, 0.3).unwrap();
        let d = p.sun_direction();
        assert!((d.length() - 1.0).abs() < 1e-5);
        assert!(d.x > 0.8 && (d.y - 0.5).abs() < 1e-5, "est = +X, élévation 30°");
        let n = SkyParams::new(0.0, 0.0, 3.0, 0.3).unwrap().sun_direction();
        assert!((n - Vec3::NEG_Z).length() < 1e-5, "azimut 0 = -Z");
    }

    #[test]
    fn la_brume_de_0_3_redonne_le_plancher_de_web_ocean() {
        let p = SkyParams::new(10.0, 0.0, 3.0, 0.3).unwrap();
        assert!((p.haze_floor_per_m() - 1.1e-4).abs() < 1e-8);
    }

    #[test]
    fn le_modele_solaire_donne_midi_au_sud_et_le_soir_a_l_ouest() {
        let m = SunModel::new(46.0, 172).unwrap();
        let (e, a) = m.position(12.0);
        assert!((e - 67.4).abs() < 0.3, "élévation de midi au solstice : {e}");
        assert!((a - 180.0).abs() < 0.5, "midi plein sud : {a}");
        let (e19, a19) = m.position(19.0);
        assert!(
            e19 > 5.0 && e19 < 30.0 && (240.0..300.0).contains(&a19),
            "19 h : {e19} {a19}"
        );
        let (e0, _) = m.position(0.0);
        assert!(e0 < 0.0, "minuit sous l'horizon");
        assert!(SunModel::new(91.0, 1).is_err() && SunModel::new(0.0, 0).is_err());
    }
}
