//! `PropBuilder` : l'établi des props et des rochers. Il accumule des parties (boîtes, cylindres, ellipsoïdes,
//! règles libres) dans un repère local (x est, y haut, z sud = devant) ; `unit` est la taille du voxel en millimètres
//! (50 par défaut, 20 pour le petit : bougies, vaisselle, outils) et `mm()` convertit une cote en voxels.

use em_core::{MaterialId, VoxelValue};

use super::tex::Tex;
use crate::batiments::kit::matieres::Matieres;
use crate::batiments::kit::plan::Part;
use crate::batiments::kit::prims::{Cell, RulePart, d2_xz, in_ellipsoid};
use crate::batiments::kit::rng::hh;

/// L'établi.
pub struct PropBuilder {
    /// Classes de matière.
    pub m: Matieres,
    /// Taille du voxel en millimètres.
    pub unit: i32,
    /// Hachage de la graine (variantes).
    pub h: u32,
    parts: Vec<Box<dyn Part>>,
}

impl PropBuilder {
    /// Établi vide.
    pub fn new(m: Matieres, unit: i32, seed: u64) -> Self {
        let h = hh(seed as i32, (seed >> 32) as i32, 12_345, 6);
        Self {
            m,
            unit,
            h,
            parts: Vec::new(),
        }
    }

    /// Millimètres -> voxels (arrondi au plus proche).
    pub fn mm(&self, mm: i32) -> i32 {
        (2 * mm + self.unit).div_euclid(2 * self.unit)
    }

    /// Variante 0..n de la graine pour l'usage `sel`.
    pub fn pick(&self, sel: i32, n: u32) -> u32 {
        hh(self.h as i32, sel, 3, 9) % n.max(1)
    }

    /// Termine : les parties.
    pub fn finish(self) -> Vec<Box<dyn Part>> {
        self.parts
    }

    /// Ajoute une partie.
    pub fn add(&mut self, p: Box<dyn Part>) {
        self.parts.push(p);
    }

    /// Boîte pleine d'une texture.
    pub fn bx(&mut self, x: (i32, i32), y: (i32, i32), z: (i32, i32), t: Tex) {
        let m = self.m;
        self.parts.push(RulePart::boxed(
            [x.0, y.0, z.0],
            [x.1, y.1, z.1],
            move |a, b, c| Cell::Put(t.at(&m, a, b, c)),
        ));
    }

    /// Boîte d'une valeur fixe.
    pub fn flat(&mut self, x: (i32, i32), y: (i32, i32), z: (i32, i32), v: VoxelValue) {
        self.bx(x, y, z, Tex::Flat(v));
    }

    /// Boîte creusée.
    pub fn carve(&mut self, x: (i32, i32), y: (i32, i32), z: (i32, i32)) {
        self.parts.push(RulePart::carve([x.0, y.0, z.0], [x.1, y.1, z.1]));
    }

    /// Cylindre vertical de centre (cx, cz) et de rayon `r` (centièmes de voxel), de y.0 à y.1.
    pub fn cyl(&mut self, cx: i32, cz: i32, r: i32, y: (i32, i32), t: Tex) {
        let m = self.m;
        let (x0, x1) = ((cx - r).div_euclid(100) - 1, (cx + r).div_euclid(100) + 2);
        let (z0, z1) = ((cz - r).div_euclid(100) - 1, (cz + r).div_euclid(100) + 2);
        let r2 = i64::from(r) * i64::from(r);
        self.parts
            .push(RulePart::boxed([x0, y.0, z0], [x1, y.1, z1], move |a, b, c| {
                if d2_xz(a, c, cx, cz) <= r2 {
                    Cell::Put(t.at(&m, a, b, c))
                } else {
                    Cell::Keep
                }
            }));
    }

    /// Anneau vertical (cylindre creux) : rayon extérieur `r`, intérieur `ri` (centièmes).
    pub fn ring(&mut self, cx: i32, cz: i32, r: i32, ri: i32, y: (i32, i32), t: Tex) {
        let m = self.m;
        let (x0, x1) = ((cx - r).div_euclid(100) - 1, (cx + r).div_euclid(100) + 2);
        let (z0, z1) = ((cz - r).div_euclid(100) - 1, (cz + r).div_euclid(100) + 2);
        let (r2, i2) = (i64::from(r) * i64::from(r), i64::from(ri) * i64::from(ri));
        self.parts
            .push(RulePart::boxed([x0, y.0, z0], [x1, y.1, z1], move |a, b, c| {
                let d = d2_xz(a, c, cx, cz);
                if d <= r2 && d >= i2 {
                    Cell::Put(t.at(&m, a, b, c))
                } else {
                    Cell::Keep
                }
            }));
    }

    /// Ellipsoïde de centre `c` et de demi-axes `r` (centièmes de voxel).
    pub fn ball(&mut self, c: [i32; 3], r: [i32; 3], t: Tex) {
        let m = self.m;
        let lo = [
            (c[0] - r[0]).div_euclid(100) - 1,
            (c[1] - r[1]).div_euclid(100) - 1,
            (c[2] - r[2]).div_euclid(100) - 1,
        ];
        let hi = [
            (c[0] + r[0]).div_euclid(100) + 2,
            (c[1] + r[1]).div_euclid(100) + 2,
            (c[2] + r[2]).div_euclid(100) + 2,
        ];
        self.parts.push(RulePart::boxed(lo, hi, move |a, b, d| {
            if in_ellipsoid(a, b, d, c, r) {
                Cell::Put(t.at(&m, a, b, d))
            } else {
                Cell::Keep
            }
        }));
    }

    /// Règle libre sur `[lo, hi)`.
    pub fn rule(
        &mut self,
        lo: [i32; 3],
        hi: [i32; 3],
        f: impl Fn(i32, i32, i32) -> Cell + Send + Sync + 'static,
    ) {
        self.parts.push(RulePart::boxed(lo, hi, f));
    }

    /// Segment épais (barreau, rayon) entre deux points entiers, de demi-épaisseur `e` voxels : la règle teste la
    /// distance du voxel au segment.
    pub fn bar(&mut self, a: [i32; 3], b: [i32; 3], e: i32, t: Tex) {
        let m = self.m;
        let lo = [a[0].min(b[0]) - e, a[1].min(b[1]) - e, a[2].min(b[2]) - e];
        let hi = [
            a[0].max(b[0]) + e + 1,
            a[1].max(b[1]) + e + 1,
            a[2].max(b[2]) + e + 1,
        ];
        let d = [
            i64::from(b[0] - a[0]),
            i64::from(b[1] - a[1]),
            i64::from(b[2] - a[2]),
        ];
        let l2 = (d[0] * d[0] + d[1] * d[1] + d[2] * d[2]).max(1);
        self.parts.push(RulePart::boxed(lo, hi, move |x, y, z| {
            let p = [i64::from(x - a[0]), i64::from(y - a[1]), i64::from(z - a[2])];
            let t_num = (p[0] * d[0] + p[1] * d[1] + p[2] * d[2]).clamp(0, l2);
            // point le plus proche, en fraction t_num / l2
            let q = [
                p[0] * l2 - d[0] * t_num,
                p[1] * l2 - d[1] * t_num,
                p[2] * l2 - d[2] * t_num,
            ];
            let dist2 = (i128::from(q[0]).pow(2) + i128::from(q[1]).pow(2) + i128::from(q[2]).pow(2))
                / i128::from(l2)
                / i128::from(l2);
            let r = i128::from(2 * e + 1) * i128::from(2 * e + 1) / 4;
            if dist2 <= r {
                Cell::Put(t.at(&m, x, y, z))
            } else {
                Cell::Keep
            }
        }));
    }
}

/// Valeur d'une classe à trois couleurs à un ton franc (ton 0, 63, 127).
pub fn ton3(c: MaterialId, k: u8) -> VoxelValue {
    VoxelValue::new(c, [0, 63, 127][usize::from(k.min(2))])
}
