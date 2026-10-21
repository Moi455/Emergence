//! Taille topiaire : le feuillage naturel est remplacé par une coque lisse (sphère, dôme, cube, cône) ajustée à
//! l'emprise du feuillage, avec un léger bruit de surface ; le bois qui sort de la forme est « taillé » aussi.
//! Port de `topiary_shell` de `voxel_tree.py`, évalué voxel par voxel (donc par fenêtre) en coordonnées monde.

use serde::{Deserialize, Serialize};

use super::fx::{self, UN};

/// Forme de la taille.
#[derive(Copy, Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum TopiaryShape {
    /// Boule.
    Sphere,
    /// Demi-boule posée au sol.
    Dome,
    /// Cube aux arêtes adoucies.
    Cube,
    /// Cône pointu.
    Cone,
}

/// Épaisseur relative de la coque.
const EPAISSEUR: i64 = UN * 22 / 100;

/// Une taille topiaire à un niveau : sa boîte d'emprise en voxels du niveau.
#[derive(Copy, Clone, Debug)]
pub struct Topiary {
    shape: TopiaryShape,
    lo: [i64; 3],
    size: [i64; 3],
    lod: u8,
}

impl Topiary {
    /// Forme ajustée à la boîte `[lo, hi]` (voxels du niveau, inclus) du feuillage naturel.
    pub fn new(shape: TopiaryShape, lo: [i32; 3], hi: [i32; 3], lod: u8) -> Self {
        let l = [i64::from(lo[0]), i64::from(lo[1]), i64::from(lo[2])];
        Self {
            shape,
            lo: l,
            size: [
                i64::from(hi[0]) - l[0] + 1,
                i64::from(hi[1]) - l[1] + 1,
                i64::from(hi[2]) - l[2] + 1,
            ],
            lod,
        }
    }

    /// Boîte de la forme, `[lo, hi]` inclus.
    pub fn bounds(&self) -> ([i32; 3], [i32; 3]) {
        (
            [self.lo[0] as i32, self.lo[1] as i32, self.lo[2] as i32],
            [
                (self.lo[0] + self.size[0] - 1) as i32,
                (self.lo[1] + self.size[1] - 1) as i32,
                (self.lo[2] + self.size[2] - 1) as i32,
            ],
        )
    }

    /// Distance normalisée au centre : 1,0 = surface de la forme.
    pub fn dist(&self, gx: i32, gy: i32, gz: i32) -> i64 {
        let centre =
            |g: i32, i: usize| (2 * i64::from(g) + 1 - 2 * self.lo[i] - self.size[i]) * UN / self.size[i];
        let u = centre(gx, 0);
        let v = centre(gy, 1);
        let q = |x: i64| fx::mul(x, x);
        match self.shape {
            TopiaryShape::Dome => {
                let w = (2 * i64::from(gz) + 1 - 2 * self.lo[2]) * UN / (2 * self.size[2]);
                fx::sqrt(q(u) + q(v) + q(w))
            }
            TopiaryShape::Cone => {
                let zr = (2 * i64::from(gz) + 1 - 2 * self.lo[2]) * UN / (2 * self.size[2]);
                let r = fx::sqrt(q(u) + q(v));
                let denom = (UN - fx::mul(UN * 96 / 100, zr)).max(UN * 4 / 100);
                fx::div(r, denom).max(zr)
            }
            TopiaryShape::Cube => {
                let w = centre(gz, 2);
                let p8 = |x: i64| {
                    let x2 = q(x.abs());
                    let x4 = q(x2);
                    q(x4)
                };
                let s = p8(u) + p8(v) + p8(w);
                fx::sqrt(fx::sqrt(fx::sqrt(s)))
            }
            TopiaryShape::Sphere => {
                let w = centre(gz, 2);
                fx::sqrt(q(u) + q(v) + q(w))
            }
        }
    }

    /// Le voxel est-il dans la forme (pour tailler le bois) ?
    pub fn inside(&self, gx: i32, gy: i32, gz: i32) -> bool {
        self.dist(gx, gy, gz) <= UN
    }

    /// Le voxel appartient-il à la coque ? Bruit de surface (4 cycles par mètre) et 5 % de trous, ancrés au monde.
    pub fn in_shell(&self, gx: i32, gy: i32, gz: i32, seed: u64) -> bool {
        let d = self.dist(gx, gy, gz);
        if !(UN - EPAISSEUR - UN / 8..=UN + UN / 8).contains(&d) {
            return false;
        }
        // bruit : coordonnées de réseau = index × 0,05 m × 2^lod × 4 cycles/m
        let k = (13_107_i64) << self.lod;
        let nz = fx::value_noise(i64::from(gx) * k, i64::from(gy) * k, i64::from(gz) * k, seed);
        let d = d + fx::mul(nz - UN / 2, UN / 10);
        if !(UN - EPAISSEUR..=UN).contains(&d) {
            return false;
        }
        fx::hash_unit(seed ^ 0x544F_5049, i64::from(gx), i64::from(gy), i64::from(gz)) >= UN * 5 / 100
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn la_coque_d_une_sphere_est_creuse_et_a_peu_pres_ronde() {
        let t = Topiary::new(TopiaryShape::Sphere, [0, 0, 0], [19, 19, 19], 0);
        let mut n = 0;
        let mut centre = 0;
        for z in 0..20 {
            for y in 0..20 {
                for x in 0..20 {
                    if t.in_shell(x, y, z, 7) {
                        n += 1;
                        if (8..12).contains(&x) && (8..12).contains(&y) && (8..12).contains(&z) {
                            centre += 1;
                        }
                    }
                }
            }
        }
        assert_eq!(centre, 0);
        // surface 4π·10² ≈ 1257 ; épaisseur 22 % du rayon (2,2 voxels) : environ 2000 voxels
        assert!((1200..2800).contains(&n), "{n}");
    }

    #[test]
    fn le_cone_se_ferme_au_sommet_et_le_cube_remplit_ses_coins() {
        let c = Topiary::new(TopiaryShape::Cone, [0, 0, 0], [19, 19, 19], 0);
        assert!(c.inside(10, 10, 5));
        assert!(!c.inside(1, 1, 15));
        let cube = Topiary::new(TopiaryShape::Cube, [0, 0, 0], [19, 19, 19], 0);
        assert!(cube.inside(2, 2, 2));
        let sph = Topiary::new(TopiaryShape::Sphere, [0, 0, 0], [19, 19, 19], 0);
        assert!(!sph.inside(1, 1, 1));
    }
}
