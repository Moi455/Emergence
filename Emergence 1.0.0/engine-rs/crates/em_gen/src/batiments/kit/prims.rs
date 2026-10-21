//! Parties génériques : une boîte et une règle `f(x, y, z) -> Cell` évaluée par voxel. C'est la brique commune des
//! props, des rochers et des détails de bâtiments : un cube plein, un cylindre, une ellipsoïde, une arche sont des
//! règles de six lignes, jamais des tableaux de voxels.

use em_core::{VoxelBox, VoxelCoord, VoxelValue};

use super::plan::Part;
use super::window::Window;

/// Ce qu'une règle décide pour un voxel.
#[derive(Copy, Clone, Debug, PartialEq, Eq)]
pub enum Cell {
    /// Ne touche pas au voxel.
    Keep,
    /// Creuse.
    Air,
    /// Pose la valeur.
    Put(VoxelValue),
    /// Pose la valeur seulement sur du vide.
    PutIfEmpty(VoxelValue),
}

/// Règle de peinture d'une partie.
pub type Rule = dyn Fn(i32, i32, i32) -> Cell + Send + Sync;

/// Une partie définie par sa boîte et sa règle.
pub struct RulePart {
    lo: [i32; 3],
    hi: [i32; 3],
    rule: Box<Rule>,
}

/// Boîte `[lo, hi)`.
pub fn vbox(lo: [i32; 3], hi: [i32; 3]) -> VoxelBox {
    let a = [lo[0].min(hi[0]), lo[1].min(hi[1]), lo[2].min(hi[2])];
    let b = [lo[0].max(hi[0]), lo[1].max(hi[1]), lo[2].max(hi[2])];
    VoxelBox::new(
        VoxelCoord::new(a[0], a[1], a[2]),
        VoxelCoord::new(b[0], b[1], b[2]),
    )
    .expect("boîte ordonnée")
}

impl RulePart {
    /// Partie sur `[lo, hi)` avec la règle `rule`.
    pub fn new(
        lo: [i32; 3],
        hi: [i32; 3],
        rule: impl Fn(i32, i32, i32) -> Cell + Send + Sync + 'static,
    ) -> Self {
        Self {
            lo,
            hi,
            rule: Box::new(rule),
        }
    }

    /// Même chose, déjà boîtée.
    pub fn boxed(
        lo: [i32; 3],
        hi: [i32; 3],
        rule: impl Fn(i32, i32, i32) -> Cell + Send + Sync + 'static,
    ) -> Box<dyn Part> {
        Box::new(Self::new(lo, hi, rule))
    }

    /// Boîte pleine d'une valeur.
    pub fn fill(lo: [i32; 3], hi: [i32; 3], v: VoxelValue) -> Box<dyn Part> {
        Self::boxed(lo, hi, move |_, _, _| Cell::Put(v))
    }

    /// Boîte creusée.
    pub fn carve(lo: [i32; 3], hi: [i32; 3]) -> Box<dyn Part> {
        Self::boxed(lo, hi, |_, _, _| Cell::Air)
    }
}

impl Part for RulePart {
    fn bounds(&self) -> VoxelBox {
        vbox(self.lo, self.hi)
    }

    fn paint(&self, w: &mut Window) {
        let Some((a, b)) = w.clip(self.lo, self.hi) else {
            return;
        };
        for y in a[1]..b[1] {
            for z in a[2]..b[2] {
                for x in a[0]..b[0] {
                    match (self.rule)(x, y, z) {
                        Cell::Keep => {}
                        Cell::Air => w.carve(x, y, z),
                        Cell::Put(v) => w.put(x, y, z, v),
                        Cell::PutIfEmpty(v) => w.put_if_empty(x, y, z, v),
                    }
                }
            }
        }
    }
}

/// Dans l'ellipsoïde de centre (cx, cy, cz) et de demi-axes (rx, ry, rz), le tout en CENTIÈMES de voxel
/// (le voxel (x, y, z) est visé en son centre : 100 x + 50).
#[inline]
pub fn in_ellipsoid(x: i32, y: i32, z: i32, c: [i32; 3], r: [i32; 3]) -> bool {
    let d = |p: i32, c: i32, r: i32| -> i128 {
        let dx = i128::from(100 * p + 50 - c);
        // (dx / r)^2 en millionièmes
        dx * dx * 1_000_000 / (i128::from(r.max(1)) * i128::from(r.max(1)))
    };
    d(x, c[0], r[0]) + d(y, c[1], r[1]) + d(z, c[2], r[2]) <= 1_000_000
}

/// Distance horizontale au carré (centièmes de voxel au carré) du centre du voxel au point (cx, cz) en centièmes.
#[inline]
pub fn d2_xz(x: i32, z: i32, cx: i32, cz: i32) -> i64 {
    let (dx, dz) = (i64::from(100 * x + 50 - cx), i64::from(100 * z + 50 - cz));
    dx * dx + dz * dz
}

/// Dans le disque horizontal de centre (cx, cz) en centièmes et de rayon r en centièmes.
#[inline]
pub fn in_disc(x: i32, z: i32, cx: i32, cz: i32, r: i32) -> bool {
    d2_xz(x, z, cx, cz) <= i64::from(r) * i64::from(r)
}

/// Une partie composée d'autres parties (un prop, un détail) déplacée par `d` après `rot` quarts de tour autour de
/// l'axe y (le voxel (x, z) devient (-z - 1, x) à chaque quart de tour). Elle lit ses enfants dans leur repère,
/// dans une fenêtre propre, puis recopie leurs voxels PLEINS dans le repère de la scène.
pub struct TransformPart {
    inner: Vec<Box<dyn Part>>,
    d: [i32; 3],
    rot: u8,
}

fn rot_cell(x: i32, z: i32, rot: u8) -> (i32, i32) {
    let (mut x, mut z) = (x, z);
    for _ in 0..rot % 4 {
        (x, z) = (-z - 1, x);
    }
    (x, z)
}

fn unrot_cell(x: i32, z: i32, rot: u8) -> (i32, i32) {
    let (mut x, mut z) = (x, z);
    for _ in 0..(4 - rot % 4) % 4 {
        (x, z) = (-z - 1, x);
    }
    (x, z)
}

impl TransformPart {
    /// Déplace `inner` de `d` après `rot` quarts de tour.
    pub fn new(inner: Vec<Box<dyn Part>>, d: [i32; 3], rot: u8) -> Self {
        Self { inner, d, rot }
    }

    fn inner_union(&self) -> Option<([i32; 3], [i32; 3])> {
        let mut lo = [i32::MAX; 3];
        let mut hi = [i32::MIN; 3];
        for p in &self.inner {
            let b = p.bounds();
            if b.is_empty() {
                continue;
            }
            let (a, c) = (b.min(), b.max());
            for (k, (u, v)) in [(a.x, c.x), (a.y, c.y), (a.z, c.z)].into_iter().enumerate() {
                lo[k] = lo[k].min(u);
                hi[k] = hi[k].max(v);
            }
        }
        (lo[0] < hi[0]).then_some((lo, hi))
    }
}

impl Part for TransformPart {
    fn bounds(&self) -> VoxelBox {
        let Some((lo, hi)) = self.inner_union() else {
            return vbox([0; 3], [0; 3]);
        };
        let (p, q) = (
            rot_cell(lo[0], lo[2], self.rot),
            rot_cell(hi[0] - 1, hi[2] - 1, self.rot),
        );
        vbox(
            [
                p.0.min(q.0) + self.d[0],
                lo[1] + self.d[1],
                p.1.min(q.1) + self.d[2],
            ],
            [
                p.0.max(q.0) + 1 + self.d[0],
                hi[1] + self.d[1],
                p.1.max(q.1) + 1 + self.d[2],
            ],
        )
    }

    fn paint(&self, w: &mut Window) {
        let Some((ilo, ihi)) = self.inner_union() else {
            return;
        };
        // boîte de la fenêtre dans le repère des enfants
        let (wl, wh) = (w.min(), w.max());
        let (p, q) = (
            unrot_cell(wl[0] - self.d[0], wl[2] - self.d[2], self.rot),
            unrot_cell(wh[0] - 1 - self.d[0], wh[2] - 1 - self.d[2], self.rot),
        );
        let lo = [
            p.0.min(q.0).max(ilo[0]),
            (wl[1] - self.d[1]).max(ilo[1]),
            p.1.min(q.1).max(ilo[2]),
        ];
        let hi = [
            (p.0.max(q.0) + 1).min(ihi[0]),
            (wh[1] - self.d[1]).min(ihi[1]),
            (p.1.max(q.1) + 1).min(ihi[2]),
        ];
        if lo[0] >= hi[0] || lo[1] >= hi[1] || lo[2] >= hi[2] {
            return;
        }
        let mut local = Window::new(vbox(lo, hi));
        for part in &self.inner {
            let b = part.bounds();
            let (a, c) = (b.min(), b.max());
            if a.x >= hi[0] || c.x <= lo[0] || a.y >= hi[1] || c.y <= lo[1] || a.z >= hi[2] || c.z <= lo[2] {
                continue;
            }
            part.paint(&mut local);
        }
        for (v, valeur) in local.solids() {
            let (x, z) = rot_cell(v.x, v.z, self.rot);
            w.put(x + self.d[0], v.y + self.d[1], z + self.d[2], valeur);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use em_core::MaterialId;

    #[test]
    fn ellipsoide_et_disque() {
        assert!(in_ellipsoid(5, 5, 5, [550, 550, 550], [300, 300, 300]));
        assert!(!in_ellipsoid(9, 5, 5, [550, 550, 550], [300, 300, 300]));
        assert!(in_disc(0, 0, 50, 50, 10));
        assert!(!in_disc(3, 0, 50, 50, 200));
    }

    #[test]
    fn regle_peint_et_creuse() {
        let v = VoxelValue::new(MaterialId::new(20), 1);
        let mut w = Window::new(vbox([0; 3], [8; 3]));
        RulePart::fill([0; 3], [8; 3], v).paint(&mut w);
        RulePart::carve([2; 3], [4; 3]).paint(&mut w);
        assert_eq!(w.solid_count(), 512 - 8);
    }
}
