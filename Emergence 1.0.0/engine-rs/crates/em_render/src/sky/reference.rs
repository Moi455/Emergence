//! Référence CPU de la transmittance de l'atmosphère de Hillaire (module `trans_lut` de `web-ocean`) : MÊMES constantes,
//! MÊME paramétrage `(r, mu)` -> distance, MÊME intégration à 64 pas au point milieu. Les essais comparent la LUT du GPU et
//! la couleur du soleil rendue par l'éclairage à ce calcul : la teinte du soleil suit la transmittance.

use crate::error::ParamError;

/// Rayon du sol de la planète (km).
const RG: f32 = 6360.0;
/// Rayon du haut de l'atmosphère (km).
const RT: f32 = 6460.0;
/// Diffusion de Rayleigh au sol (km^-1).
const RAYLEIGH: [f32; 3] = [5.802e-3, 13.558e-3, 33.1e-3];
/// Extinction de Mie au sol (km^-1).
const MIE_EXT: f32 = 4.40e-3;
/// Absorption de l'ozone (km^-1).
const OZONE: [f32; 3] = [0.650e-3, 1.881e-3, 0.085e-3];
/// Pas d'intégration de la LUT.
const PAS: u32 = 64;

/// Calcul de référence de la transmittance du soleil, pour une turbidité (multiplicateur des aérosols) donnée.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct AtmosphereReference {
    turbidity: f32,
}

impl AtmosphereReference {
    /// Atmosphère de turbidité `turbidity` dans [0,5 ; 15] (même plage que `SkyParams`).
    pub fn new(turbidity: f32) -> Result<Self, ParamError> {
        if !(turbidity.is_finite() && (0.5..=15.0).contains(&turbidity)) {
            return Err(ParamError::Invalide(format!(
                "turbidité = {turbidity} hors de [0,5 ; 15]"
            )));
        }
        Ok(Self { turbidity })
    }

    /// Turbidité.
    pub fn turbidity(&self) -> f32 {
        self.turbidity
    }

    /// Extinction par km à la hauteur `h_km` au-dessus du sol (miroir de `medium` du WGSL).
    fn extinction(&self, h_km: f32) -> [f32; 3] {
        let h = h_km.max(0.0);
        let d_r = (-h / 8.0).exp();
        let d_m = (-h / 1.2).exp();
        let d_o = (1.0 - (h - 25.0).abs() / 15.0).max(0.0);
        let mut e = [0.0; 3];
        for (c, e_c) in e.iter_mut().enumerate() {
            *e_c = RAYLEIGH[c] * d_r + MIE_EXT * d_m * self.turbidity + OZONE[c] * d_o;
        }
        e
    }

    /// Transmittance du soleil jusqu'à un point du rayon `r` (km depuis le centre de la planète), pour un `mu` (cosinus
    /// de l'angle zénithal, soit le sinus de l'élévation) : `exp(-profondeur optique)` jusqu'au haut de l'atmosphère.
    pub fn transmittance(&self, r: f32, mu: f32) -> [f32; 3] {
        let mu = mu.clamp(-1.0, 1.0);
        // Rayon (0, r) de direction (sqrt(1 - mu²), mu) : sortie de la sphère de rayon RT.
        let b = r * mu;
        let c = (r - RT) * (r + RT);
        let disc = b * b - c;
        let t_max = (-b + disc.max(0.0).sqrt()).max(0.0);
        let dt = t_max / PAS as f32;
        let horizontal = (1.0 - mu * mu).max(0.0).sqrt();
        let mut od = [0.0_f32; 3];
        for i in 0..PAS {
            let t = (i as f32 + 0.5) * dt;
            let (x, y) = (horizontal * t, r + mu * t);
            let e = self.extinction(x.hypot(y) - RG);
            for k in 0..3 {
                od[k] += e[k] * dt;
            }
        }
        od.map(|o| (-o).exp())
    }

    /// Transmittance pour une caméra à `altitude_km` au-dessus du sol et un soleil d'élévation `elevation_deg`.
    pub fn sun_transmittance(&self, altitude_km: f32, elevation_deg: f32) -> [f32; 3] {
        self.transmittance(RG + altitude_km, elevation_deg.to_radians().sin())
    }

    /// (r, mu) d'un texel de la LUT de transmittance 256 x 64 (miroir de `transUVToRMu`), `uv` dans [0, 1]².
    pub fn lut_r_mu(uv: [f32; 2]) -> (f32, f32) {
        let h = (RT * RT - RG * RG).sqrt();
        let rho = h * uv[1];
        let r = (rho * rho + RG * RG).sqrt();
        let d_min = RT - r;
        let d_max = rho + h;
        let d = d_min + uv[0] * (d_max - d_min);
        let mu = if d > 0.0 {
            (h * h - rho * rho - d * d) / (2.0 * r * d)
        } else {
            1.0
        };
        (r, mu.clamp(-1.0, 1.0))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn t(el: f32) -> [f32; 3] {
        AtmosphereReference::new(3.0)
            .unwrap()
            .sun_transmittance(0.010, el)
    }

    /// La teinte du soleil passe du blanc-jaune (midi) à l'orange doré (18 h 30) puis au rouge (coucher).
    #[test]
    fn la_teinte_du_soleil_suit_la_hauteur() {
        let (midi, soir, rasant, couchant) = (t(67.0), t(10.0), t(4.0), t(1.5));
        let rb = |c: [f32; 3]| c[0] / c[2];
        // Midi : peu de différence entre canaux (blanc légèrement jaune).
        assert!(rb(midi) > 1.1 && rb(midi) < 1.6, "midi {midi:?}");
        // 18 h 30 (élévation 10°) : orange doré, le bleu est à moins de 35 % du rouge.
        assert!(
            soir[2] < 0.35 * soir[0] && soir[1] > 0.45 * soir[0],
            "soir {soir:?}"
        );
        // Au coucher : rouge, le vert tombe sous 45 % du rouge et le bleu sous 15 %.
        assert!(
            rasant[1] < 0.45 * rasant[0] && rasant[2] < 0.15 * rasant[0],
            "rasant {rasant:?}"
        );
        assert!(
            couchant[1] < 0.25 * couchant[0] && couchant[2] < 0.02 * couchant[0],
            "couchant {couchant:?}"
        );
        assert!(rb(midi) < rb(soir) && rb(soir) < rb(rasant) && rb(rasant) < rb(couchant));
    }

    #[test]
    fn la_turbidite_hors_plage_est_refusee() {
        assert!(AtmosphereReference::new(0.0).is_err());
        assert!(AtmosphereReference::new(f32::NAN).is_err());
        assert!(AtmosphereReference::new(20.0).is_err());
    }

    /// Un texel de LUT donne un (r, mu) dans les bornes et revient au zénith au plus court trajet.
    #[test]
    fn le_parametrage_de_la_lut_est_coherent() {
        let (r, mu) = AtmosphereReference::lut_r_mu([0.0, 0.0]);
        assert!((r - RG).abs() < 1e-3 && (mu - 1.0).abs() < 1e-3, "{r} {mu}");
        let (r2, mu2) = AtmosphereReference::lut_r_mu([0.7, 0.5]);
        assert!((RG..=RT).contains(&r2) && (-1.0..=1.0).contains(&mu2));
    }
}
