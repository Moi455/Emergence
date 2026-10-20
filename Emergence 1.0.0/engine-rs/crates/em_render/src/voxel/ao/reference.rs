//! Référence CPU de l'occlusion ambiante (L14) : mêmes directions, même hachage, même atténuation que le WGSL, mais un
//! DDA d'Amanatides et Woo en `f64`, voxel par voxel, sur un prédicat « plein ». Les essais GPU comparent à lui.

use super::params::{AmbientOcclusionParams, local_direction, position_hash};

/// Point de surface d'un pixel : voxel touché, face (2 × axe + 1 si la normale est positive) et position de départ des
/// rayons dans le repère du voxel (voxels, décalée de 0,02 hors de la face).
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct SurfacePoint {
    /// Voxel plein touché (cellule absolue).
    pub voxel: [i32; 3],
    /// Face touchée : 2 × axe + 1 si la normale est positive.
    pub face: u32,
    /// Départ des rayons, relatif au voxel touché.
    pub origin: [f32; 3],
}

impl SurfacePoint {
    /// Construit le point de départ des rayons à partir de la position `q` du point touché dans le voxel (voxels) :
    /// les coordonnées tangentes sont ramenées dans la face, la coordonnée normale est posée à 0,02 voxel hors du voxel
    /// (miroir du WGSL).
    pub fn new(voxel: [i32; 3], face: u32, q: [f32; 3]) -> Self {
        let axe = (face >> 1) as usize;
        let mut origin = q.map(|v| v.clamp(0.002, 0.998));
        origin[axe] = if face & 1 == 1 { 1.02 } else { -0.02 };
        Self { voxel, face, origin }
    }

    /// Axes unitaires : (tangent 1, tangent 2, normale).
    pub fn repere(&self) -> ([f32; 3], [f32; 3], [f32; 3]) {
        let axe = (self.face >> 1) as usize;
        let signe = if self.face & 1 == 1 { 1.0 } else { -1.0 };
        let unite = |a: usize| {
            let mut v = [0.0; 3];
            v[a % 3] = 1.0;
            v
        };
        let mut n = unite(axe);
        n[axe] = signe;
        (unite(axe + 1), unite(axe + 2), n)
    }
}

/// Fraction occultée moyenne (avant la force) du point de surface, par `p.rays()` rayons cosinus.
pub fn occlusion_cpu(
    plein: &dyn Fn([i32; 3]) -> bool,
    point: &SurfacePoint,
    p: &AmbientOcclusionParams,
) -> f32 {
    let hash = position_hash(point.voxel, point.origin, point.face);
    let (t1, t2, n) = point.repere();
    let portee = f64::from(p.range_voxels());
    let mut somme = 0.0_f32;
    for i in 0..p.rays() {
        let l = local_direction(i, p.rays(), hash);
        let mut d = [0.0_f64; 3];
        for a in 0..3 {
            d[a] = f64::from(t1[a] * l[0] + t2[a] * l[1] + n[a] * l[2]);
        }
        let origine = [0, 1, 2].map(|a| f64::from(point.voxel[a]) + f64::from(point.origin[a]));
        if let Some(t) = premier_plein(plein, origine, d, portee) {
            somme += p.weight(t as f32);
        }
    }
    somme / p.rays() as f32
}

/// Distance (voxels) d'entrée dans le premier voxel plein rencontré avant `portee`, `None` sinon.
fn premier_plein(
    plein: &dyn Fn([i32; 3]) -> bool,
    origine: [f64; 3],
    dir: [f64; 3],
    portee: f64,
) -> Option<f64> {
    let mut c = [0_i32; 3];
    let mut t_axe = [f64::INFINITY; 3];
    let mut delta = [f64::INFINITY; 3];
    let mut pas = [0_i32; 3];
    for a in 0..3 {
        c[a] = origine[a].floor() as i32;
        pas[a] = if dir[a] >= 0.0 { 1 } else { -1 };
        if dir[a].abs() > 1e-12 {
            let bord = if dir[a] > 0.0 {
                f64::from(c[a] + 1)
            } else {
                f64::from(c[a])
            };
            t_axe[a] = (bord - origine[a]) / dir[a];
            delta[a] = (1.0 / dir[a]).abs();
        }
    }
    let mut t = 0.0;
    for _ in 0..4_000 {
        if plein(c) {
            return Some(t);
        }
        let a = if t_axe[0] <= t_axe[1] && t_axe[0] <= t_axe[2] {
            0
        } else if t_axe[1] <= t_axe[2] {
            1
        } else {
            2
        };
        t = t_axe[a];
        if t > portee {
            return None;
        }
        c[a] += pas[a];
        t_axe[a] += delta[a];
    }
    None
}

#[cfg(test)]
mod tests {
    use super::*;

    fn params() -> AmbientOcclusionParams {
        AmbientOcclusionParams::new(8, 1.0).unwrap()
    }

    #[test]
    fn un_sol_degage_n_est_pas_occulte() {
        let sol = |c: [i32; 3]| c[1] < 0;
        let pt = SurfacePoint::new([5, -1, 5], 3, [0.5, 1.0, 0.5]); // face +y du voxel (5,-1,5)
        assert_eq!(pt.face, 3);
        assert_eq!(occlusion_cpu(&sol, &pt, &params()), 0.0);
    }

    #[test]
    fn le_coin_de_trois_murs_est_tres_occulte() {
        // Sol y < 0, murs x < 0 et z < 0 (hauteur illimitée) : le point de sol contre les deux murs.
        let plein = |c: [i32; 3]| c[1] < 0 || c[0] < 0 || c[2] < 0;
        let coin = SurfacePoint::new([0, -1, 0], 3, [0.1, 1.0, 0.1]);
        let libre = SurfacePoint::new([100, -1, 100], 3, [0.5, 1.0, 0.5]);
        let o_coin = occlusion_cpu(&plein, &coin, &params());
        assert!(o_coin > 0.3, "coin {o_coin}");
        assert_eq!(occlusion_cpu(&plein, &libre, &params()), 0.0);
        // Contre un seul mur : moins occulté que dans le coin.
        let un_mur = SurfacePoint::new([0, -1, 100], 3, [0.1, 1.0, 0.5]);
        let o_mur = occlusion_cpu(&plein, &un_mur, &params());
        assert!(o_mur > 0.05 && o_mur < o_coin, "mur {o_mur} coin {o_coin}");
    }

    #[test]
    fn la_normale_et_les_tangentes_forment_un_repere_direct_unitaire() {
        for face in 0..6 {
            let pt = SurfacePoint::new([0, 0, 0], face, [0.5, 0.5, 0.5]);
            let (t1, t2, n) = pt.repere();
            let dot = |a: [f32; 3], b: [f32; 3]| a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
            assert_eq!(dot(t1, t2), 0.0);
            assert_eq!(dot(t1, n), 0.0);
            assert_eq!(dot(n, n), 1.0);
        }
    }
}
