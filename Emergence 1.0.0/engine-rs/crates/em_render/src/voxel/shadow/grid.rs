//! Géométrie des cascades : base du soleil et CALAGE d'une cascade sur le réseau de texels (docs/19 § 5.3,
//! « stables »). Calcul CPU en `f64`, sans GPU : les tests prouvent la stabilité sans carte graphique.
//!
//! Le réseau de texels est ancré dans le MONDE : le texel d'indice absolu `(K, M)` est le point
//! `right × (K + ½) × texel + up × (M + ½) × texel + sun × w` quelle que soit la caméra. Bouger ou tourner la caméra
//! ne fait que décaler la fenêtre de `(K, M)` par crans entiers : la valeur d'un texel ne change JAMAIS, donc rien
//! ne scintille.

use glam::DVec3;

/// Distance du plan de départ des rayons au-delà de la caméra, en mètres, avant calage de `w`. Elle dépasse la
/// demi-diagonale de la fenêtre de la clipmap (≈ 50 m) plus le calage de `w` (± 8 m) : tout le monde chargé est
/// devant le plan.
pub const PLAN_M: f64 = 64.0;

/// Cran du calage de la profondeur du plan, en mètres (la profondeur n'a pas besoin d'être fine).
pub const CRAN_PLAN_M: f64 = 16.0;

/// Soleil trop bas : pas de cascade (les ombres seraient infinies et le soleil éclaire à peine).
pub const SOLEIL_Y_MIN: f64 = 0.02;

/// Base orthonormée liée au soleil : `sun` vers le soleil, `right` et `up` dans le plan des texels.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct SunBasis {
    right: DVec3,
    up: DVec3,
    sun: DVec3,
}

impl SunBasis {
    /// Base pour une direction VERS le soleil (normalisée ici). `right` est horizontal (`Y × sun`) tant que le
    /// soleil n'est pas au zénith : la base tourne en continu avec l'azimut.
    pub fn new(vers_le_soleil: DVec3) -> Self {
        let sun = vers_le_soleil.normalize();
        let reference = if sun.y.abs() > 0.95 { DVec3::Z } else { DVec3::Y };
        let right = reference.cross(sun).normalize();
        let up = sun.cross(right);
        Self { right, up, sun }
    }

    /// Axe des u des texels.
    pub fn right(&self) -> DVec3 {
        self.right
    }

    /// Axe des v des texels.
    pub fn up(&self) -> DVec3 {
        self.up
    }

    /// Direction vers le soleil.
    pub fn sun(&self) -> DVec3 {
        self.sun
    }

    /// Angle (degrés) entre deux directions de soleil.
    pub fn angle_deg(&self, autre: &SunBasis) -> f64 {
        self.sun.dot(autre.sun).clamp(-1.0, 1.0).acos().to_degrees()
    }
}

/// Calage d'UNE cascade : indices absolus du texel `(0, 0)` de la fenêtre, taille, profondeur du plan.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct CascadePlacement {
    k0: i64,
    m0: i64,
    size: u32,
    texel_m: f64,
    plan_w: f64,
}

impl CascadePlacement {
    /// Fenêtre centrée sur `camera` (mètres, repère monde absolu) : le centre est calé sur un multiple de
    /// `quantum` texels, la profondeur du plan sur un multiple de [`CRAN_PLAN_M`].
    pub fn around(base: &SunBasis, camera: DVec3, texel_m: f64, size: u32, quantum: u32) -> Self {
        let q = f64::from(quantum);
        let demi = i64::from(size / 2);
        let cale =
            |coordonnee: f64| -> i64 { (coordonnee / texel_m / q).round() as i64 * i64::from(quantum) };
        let plan_w = ((camera.dot(base.sun) + PLAN_M) / CRAN_PLAN_M).round() * CRAN_PLAN_M;
        Self {
            k0: cale(camera.dot(base.right)) - demi,
            m0: cale(camera.dot(base.up)) - demi,
            size,
            texel_m,
            plan_w,
        }
    }

    /// Indice absolu du texel (0, 0) selon u.
    pub fn k0(&self) -> i64 {
        self.k0
    }

    /// Indice absolu du texel (0, 0) selon v.
    pub fn m0(&self) -> i64 {
        self.m0
    }

    /// Côté en texels.
    pub fn size(&self) -> u32 {
        self.size
    }

    /// Taille d'un texel en mètres.
    pub fn texel_m(&self) -> f64 {
        self.texel_m
    }

    /// Profondeur du plan : coordonnée sur l'axe du soleil, en mètres.
    pub fn plan_w(&self) -> f64 {
        self.plan_w
    }

    /// Position monde absolue (mètres) du centre du texel d'indice ABSOLU `(k, m)` sur le plan de départ.
    pub fn texel_center(&self, base: &SunBasis, k: i64, m: i64) -> DVec3 {
        base.right * ((k as f64 + 0.5) * self.texel_m)
            + base.up * ((m as f64 + 0.5) * self.texel_m)
            + base.sun * self.plan_w
    }

    /// Position monde absolue du texel (0, 0) de la fenêtre.
    pub fn origin(&self, base: &SunBasis) -> DVec3 {
        self.texel_center(base, self.k0, self.m0)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn soleil() -> SunBasis {
        // 40° de hauteur, azimut quelconque (vers le soleil, y haut)
        let (se, ce) = 40.0_f64.to_radians().sin_cos();
        let (sa, ca) = 215.0_f64.to_radians().sin_cos();
        SunBasis::new(DVec3::new(sa * ce, se, -ca * ce))
    }

    #[test]
    fn la_base_du_soleil_est_orthonormee() {
        let b = soleil();
        for (a, c) in [(b.right, b.up), (b.right, b.sun), (b.up, b.sun)] {
            assert!(a.dot(c).abs() < 1e-12);
        }
        assert!((b.right.length() - 1.0).abs() < 1e-12 && (b.up.length() - 1.0).abs() < 1e-12);
        assert!(b.right.y.abs() < 1e-12, "right reste horizontal");
    }

    #[test]
    fn le_centre_du_texel_ne_depend_pas_de_la_camera() {
        // Deux caméras décalées de moins d'un texel (et d'un cran) : un même texel absolu est au même point.
        let b = soleil();
        let (texel, taille, cran) = (0.0125, 1024, 32);
        let a = CascadePlacement::around(&b, DVec3::new(10_000.0, 1.7, 9_981.0), texel, taille, cran);
        let c = CascadePlacement::around(&b, DVec3::new(10_000.004, 1.7, 9_981.003), texel, taille, cran);
        let (k, m) = (a.k0() + 500, a.m0() + 300);
        assert_eq!(a.texel_center(&b, k, m), c.texel_center(&b, k, m));
    }

    #[test]
    fn la_fenetre_ne_bouge_que_par_crans_entiers() {
        let b = soleil();
        let (texel, taille, cran) = (0.0125, 1024, 32);
        let base = DVec3::new(10_000.0, 1.7, 9_981.0);
        let p0 = CascadePlacement::around(&b, base, texel, taille, cran);
        // un déplacement d'un dixième de cran ne change rien
        let petit = base + b.right * (0.1 * f64::from(cran) * texel);
        let p1 = CascadePlacement::around(&b, petit, texel, taille, cran);
        // un déplacement de plusieurs crans change k0 d'un multiple du cran
        let grand = base + b.right * (5.2 * f64::from(cran) * texel);
        let p2 = CascadePlacement::around(&b, grand, texel, taille, cran);
        assert_eq!(p0, p1);
        assert_eq!((p2.k0() - p0.k0()) % i64::from(cran), 0);
        assert_ne!(p0.k0(), p2.k0());
    }

    #[test]
    fn la_rotation_de_la_camera_ne_change_pas_le_calage() {
        // Le calage ne lit que la POSITION de la caméra, jamais son orientation (propriété par construction ;
        // ce test fige la signature : `around` n'a pas d'angle).
        let b = soleil();
        let a = CascadePlacement::around(&b, DVec3::new(3.0, 1.7, -4.0), 0.025, 1024, 32);
        let c = CascadePlacement::around(&b, DVec3::new(3.0, 1.7, -4.0), 0.025, 1024, 32);
        assert_eq!(a, c);
    }

    #[test]
    fn le_plan_est_derriere_tout_le_monde_charge() {
        let b = soleil();
        let cam = DVec3::new(10_000.0, 1.7, 10_000.0);
        let p = CascadePlacement::around(&b, cam, 0.0125, 1024, 32);
        // la fenêtre de la clipmap s'étend à 50 m au plus de la caméra : le plan doit rester au-delà
        let marge = p.plan_w() - cam.dot(b.sun());
        assert!(marge >= PLAN_M - CRAN_PLAN_M / 2.0, "marge du plan : {marge} m");
    }
}
