//! Rastérisation du bois : capsules effilées pour le bois épais, tracé continu d'un voxel pour les brindilles
//! (`rasterize_segments` de `voxel_tree.py`). Tout se calcule dans les voxels du niveau demandé : les positions du
//! niveau 0 sont décalées de `lod` bits, les seuils du Python (`0,032·k` m, `0,04·k` m) deviennent des seuils
//! fixes en voxels du niveau.

use super::frame::Segment;
use super::fx::{self, UN, V3};

/// Seuil de finesse : un segment dont le rayon maximal est sous 0,64 voxel du niveau est tracé en ligne.
const SEUIL_FIN: i64 = UN * 64 / 100;
/// Rayon minimal d'une capsule (0,8 voxel du niveau).
const RAYON_MIN: i64 = UN * 8 / 10;
/// Pas du tracé fin : 0,35 voxel.
const PAS_FIN: i64 = UN * 35 / 100;

/// Un segment ramené aux voxels du niveau.
#[derive(Copy, Clone, Debug)]
pub struct SegmentNiveau {
    a: V3,
    b: V3,
    r0: i64,
    r1: i64,
    trunk: bool,
    /// Rayon du niveau 0 supérieur à 10 cm : seul le gros fût reçoit le relief d'écorce.
    gros: bool,
}

impl SegmentNiveau {
    /// Segment `s` au niveau `lod`.
    pub fn new(s: &Segment, lod: u8) -> Self {
        let k = u32::from(lod);
        let sh = |v: V3| V3::new(v.x >> k, v.y >> k, v.z >> k);
        Self {
            a: sh(s.a),
            b: sh(s.b),
            r0: s.r0 >> k,
            r1: s.r1 >> k,
            trunk: s.trunk,
            gros: s.r0.max(s.r1) > 2 * UN,
        }
    }

    /// Segment fin (tracé en ligne, sorte « rameau »).
    pub fn is_thin(&self) -> bool {
        self.r0.max(self.r1) < SEUIL_FIN
    }

    /// Trace une brindille : appelle `f(x, y, z)` pour chaque voxel touché (avec répétitions possibles).
    pub fn trace_thin(&self, mut f: impl FnMut(i32, i32, i32)) {
        let ab = self.b.sub(self.a);
        let len = ab.norm();
        let n = ((len + PAS_FIN - 1) / PAS_FIN + 1).max(2);
        for i in 0..n {
            let t = i * UN / (n - 1);
            let p = self.a.add(ab.scale(t));
            f((p.x >> 16) as i32, (p.y >> 16) as i32, (p.z >> 16) as i32);
        }
    }

    /// Boîte entière des voxels qu'une capsule peut toucher : `[min, max]` inclus.
    pub fn thick_box(&self) -> ([i32; 3], [i32; 3]) {
        let ra = self.r0.max(RAYON_MIN);
        let rb = self.r1.max(RAYON_MIN);
        let rm = fx::mul(ra.max(rb), UN * 125 / 100) + UN / 2;
        let lo = |a: i64, b: i64| ((a.min(b) - rm) >> 16) as i32;
        let hi = |a: i64, b: i64| ((a.max(b) + rm) >> 16) as i32;
        (
            [
                lo(self.a.x, self.b.x),
                lo(self.a.y, self.b.y),
                lo(self.a.z, self.b.z),
            ],
            [
                hi(self.a.x, self.b.x),
                hi(self.a.y, self.b.y),
                hi(self.a.z, self.b.z),
            ],
        )
    }

    /// Rastérise la capsule dans `[min, max]` (inclus) : `f(x, y, z)` reçoit chaque voxel dont le centre est dans
    /// la capsule. `bruit(x, y, z)` module le rayon du fût (Q16 autour de 0,5) pour le relief de l'écorce.
    pub fn fill_thick(
        &self,
        min: [i32; 3],
        max: [i32; 3],
        bruit: &dyn Fn(i64, i64, i64) -> i64,
        mut f: impl FnMut(i32, i32, i32),
    ) {
        let (bmin, bmax) = self.thick_box();
        let lo = [min[0].max(bmin[0]), min[1].max(bmin[1]), min[2].max(bmin[2])];
        let hi = [max[0].min(bmax[0]), max[1].min(bmax[1]), max[2].min(bmax[2])];
        if lo[0] > hi[0] || lo[1] > hi[1] || lo[2] > hi[2] {
            return;
        }
        let ra = self.r0.max(RAYON_MIN);
        let rb = self.r1.max(RAYON_MIN);
        let ab = self.b.sub(self.a);
        let l2 = (fx::mul(ab.x, ab.x) + fx::mul(ab.y, ab.y) + fx::mul(ab.z, ab.z)).max(1);
        // le Python ne module que le gros fût (rayon > 0,10 m)
        let relief = self.trunk && self.gros;
        for z in lo[2]..=hi[2] {
            let pz = (i64::from(z) << 16) + 32_768;
            for y in lo[1]..=hi[1] {
                let py = (i64::from(y) << 16) + 32_768;
                for x in lo[0]..=hi[0] {
                    let px = (i64::from(x) << 16) + 32_768;
                    let (dx, dy, dz) = (px - self.a.x, py - self.a.y, pz - self.a.z);
                    let t = (fx::mul(dx, ab.x) + fx::mul(dy, ab.y) + fx::mul(dz, ab.z)) * UN / l2;
                    let t = t.clamp(0, UN);
                    let ex = dx - fx::mul(t, ab.x);
                    let ey = dy - fx::mul(t, ab.y);
                    let ez = dz - fx::mul(t, ab.z);
                    let d2 = (ex * ex + ey * ey + ez * ez) >> 16;
                    let mut rad = ra + fx::mul(t, rb - ra);
                    if relief {
                        let nz = bruit(px, py, pz);
                        rad = fx::mul(rad, UN + fx::mul(UN * 16 / 100, nz - UN / 2));
                    }
                    if d2 <= fx::mul(rad, rad) {
                        f(x, y, z);
                    }
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn seg(r: i64) -> Segment {
        Segment {
            a: V3::new(0, 0, 0),
            b: V3::new(0, 0, 10 * UN),
            r0: r,
            r1: r,
            trunk: false,
        }
    }

    #[test]
    fn un_fut_de_deux_voxels_de_rayon_fait_un_cylindre_plein() {
        let s = SegmentNiveau::new(&seg(2 * UN), 0);
        assert!(!s.is_thin());
        let mut n = 0;
        s.fill_thick([-6, -6, -3], [6, 6, 14], &|_, _, _| UN / 2, |_, _, _| n += 1);
        // π r² h ≈ 12,6 × 10 = 126 voxels, plus les bouts arrondis
        assert!((110..230).contains(&n), "{n}");
    }

    #[test]
    fn une_brindille_est_tracee_en_ligne() {
        let s = SegmentNiveau::new(&seg(UN / 10), 0);
        assert!(s.is_thin());
        let mut v = Vec::new();
        s.trace_thin(|x, y, z| v.push((x, y, z)));
        v.sort_unstable();
        v.dedup();
        assert_eq!(v.len(), 11);
    }

    #[test]
    fn au_niveau_trois_la_meme_capsule_devient_fine() {
        let s = SegmentNiveau::new(&seg(2 * UN), 3);
        assert!(s.is_thin());
    }
}
