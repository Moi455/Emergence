//! Les amas ellipsoïdaux (feuilles, fleurs, fruits) et leur rastérisation « par densité » : un amas de `N` points
//! tirés dans un ellipsoïde donne, pour chaque voxel intérieur, une espérance de `N / volume` points ; un voxel
//! est plein avec la probabilité `1 - exp(-lambda)` où `lambda` somme les amas qui le recouvrent. Le tirage vient
//! d'un hachage des coordonnées MONDE du voxel : il ne dépend ni de la fenêtre ni de l'ordre de parcours
//! (piège de L31). C'est la loi de Poisson que le tirage de points de `make_leaf_voxels` approche.

use em_core::hash_combine;

use super::fx::{self, UN, V3};

/// Un amas ellipsoïdal : disque aplati allongé le long de `dir`, comme `make_leaf_voxels`.
#[derive(Copy, Clone, Debug, PartialEq, Eq)]
pub struct Blob {
    /// Centre (Q16 de voxel du niveau 0), affaissement déjà appliqué.
    pub center: V3,
    /// Direction du rameau (allongement).
    pub dir: V3,
    /// Rayon (Q16 de voxel du niveau 0).
    pub r: i64,
    /// Allongement le long de `dir` (Q16, ≥ 1).
    pub stretch: i64,
    /// Aplatissement vertical (Q16).
    pub flat: i64,
    /// Points par voxel du niveau 0 dans l'amas (Q16).
    pub density: i64,
    /// Variante de teinte des voxels de l'amas (rampe de fleur ou de fruit).
    pub variant: u8,
}

/// Sous ce rayon (en voxels du niveau) l'amas n'est plus un volume : ses points tombent dans une ou deux cases,
/// qu'on tire explicitement (comme le Python), au lieu d'une densité.
const RAYON_PONCTUEL: i64 = UN / 2;
/// Demi-largeur de la lisière douce, en voxels : un voxel recouvre la surface sur 1 à 1,7 voxel selon l'obliquité.
pub const LISIERE_FEUILLES: i64 = UN * 3 / 4;
/// Demi-largeur pour les fleurs et les fruits (amas serrés).
pub const LISIERE_ORGANES: i64 = UN * 2 / 5;
/// Densité qui rend une case certainement pleine.
const SATURE: u32 = 20 * 1024;

impl Blob {
    /// Demi-étendues de la boîte englobante de l'ellipsoïde, en Q16 de voxel du niveau 0 :
    /// `R · F_i · sqrt(1 + (stretch² − 1) D_i²)`.
    pub fn half_extents(&self) -> V3 {
        let s2m1 = fx::mul(self.stretch, self.stretch) - UN;
        let h = |d: i64, f: i64| {
            let rac = fx::sqrt(UN + fx::mul(s2m1.max(0), fx::mul(d, d)));
            fx::mul(fx::mul(self.r, f), rac)
        };
        V3::new(h(self.dir.x, UN), h(self.dir.y, UN), h(self.dir.z, self.flat))
    }

    /// Volume en voxels du niveau 0 (Q16) : 4/3 π R³ · stretch · flat.
    pub fn volume(&self) -> i64 {
        let r3 = fx::mul(fx::mul(self.r, self.r), self.r);
        fx::mul(fx::mul(r3, 274_529), fx::mul(self.stretch, self.flat))
    }
}

/// Un amas préparé pour un niveau : matrice inverse, centre et densité à ce niveau.
struct Prepare {
    colonnes: [V3; 3],
    centre: V3,
    demi: V3,
    lambda: u32,
    variant: u8,
    /// Rayon moyen en voxels du niveau (Q16) : sert à la lisière douce.
    rbar: i64,
}

/// `lambda` est en Q10 (1/1024) dans la grille.
const Q10: i64 = 1024;

fn preparer(b: &Blob, lod: u8) -> Option<Prepare> {
    // niveau k : toutes les longueurs sont divisées par 2^k (le Q16 reste Q16)
    let k = u32::from(lod);
    let r = b.r >> k;
    let centre = V3::new(b.center.x >> k, b.center.y >> k, b.center.z >> k);
    let petit = r.min(fx::mul(r, b.flat)).min(fx::mul(r, b.stretch));
    // densité du niveau : lambda × 2^k (la couverture projetée est conservée)
    let lambda = b.density << k;
    if petit < RAYON_PONCTUEL {
        return None;
    }
    if r <= 0 {
        return None;
    }
    let inv_r = fx::div(UN, r);
    let c = UN - fx::div(UN, b.stretch.max(UN)); // 1 - 1/stretch
    let d = b.dir;
    let f = [UN, UN, fx::div(UN, b.flat.max(1))];
    let dj = [d.x, d.y, d.z];
    let colonne = |j: usize| -> V3 {
        let mut e = [0_i64, 0, 0];
        e[j] = UN;
        let cd = fx::mul(c, dj[j]);
        let v = V3::new(
            e[0] - fx::mul(cd, d.x),
            e[1] - fx::mul(cd, d.y),
            e[2] - fx::mul(cd, d.z),
        );
        v.scale(fx::mul(f[j], inv_r))
    };
    let bm = Blob { r, ..*b };
    let he = bm.half_extents();
    let l = ((lambda * Q10) >> 16).clamp(0, 60 * Q10) as u32;
    Some(Prepare {
        colonnes: [colonne(0), colonne(1), colonne(2)],
        centre,
        demi: he,
        lambda: l,
        variant: b.variant,
        rbar: fx::mul(r, fx::pow(fx::mul(b.stretch.max(UN), b.flat.max(1)), UN / 3)),
    })
}

/// Grille de densité d'une fenêtre (marge d'un voxel autour) : accumule les amas puis tire les voxels pleins.
pub struct DensityGrid {
    min: [i32; 3],
    dim: [usize; 3],
    lam: Vec<u32>,
    variant: Vec<u8>,
    lisiere: i64,
    /// Boîte des cases touchées (voxels, `[min, max)`), pour ne parcourir que l'utile.
    touche: Option<([i32; 3], [i32; 3])>,
}

impl DensityGrid {
    /// Grille couvrant `[min, max)` (voxels du niveau) plus une marge d'un voxel.
    pub fn new(min: [i32; 3], max: [i32; 3], lisiere: i64) -> Self {
        let m = [min[0] - 1, min[1] - 1, min[2] - 1];
        let dim = [
            (max[0] - min[0] + 2) as usize,
            (max[1] - min[1] + 2) as usize,
            (max[2] - min[2] + 2) as usize,
        ];
        Self {
            min: m,
            dim,
            lam: vec![0; dim[0] * dim[1] * dim[2]],
            variant: vec![0; dim[0] * dim[1] * dim[2]],
            lisiere,
            touche: None,
        }
    }

    fn marquer(&mut self, a: [i32; 3], b: [i32; 3]) {
        self.touche = Some(match self.touche {
            None => (a, b),
            Some((l, h)) => (
                [l[0].min(a[0]), l[1].min(a[1]), l[2].min(a[2])],
                [h[0].max(b[0]), h[1].max(b[1]), h[2].max(b[2])],
            ),
        });
    }

    fn idx(&self, x: usize, y: usize, z: usize) -> usize {
        (z * self.dim[1] + y) * self.dim[0] + x
    }

    /// Ajoute un amas au niveau `lod` ; `sel` est le sel de hachage de l'amas (sa graine et son rang).
    pub fn add(&mut self, b: &Blob, lod: u8, sel: u64) {
        let Some(p) = preparer(b, lod) else {
            self.add_points(b, lod, sel);
            return;
        };
        if p.lambda == 0 {
            return;
        }
        let g = self.min;
        let lim = [
            g[0] + self.dim[0] as i32,
            g[1] + self.dim[1] as i32,
            g[2] + self.dim[2] as i32,
        ];
        // boîte de l'amas en voxels du niveau (centres de voxels dans l'ellipsoïde)
        let bornes = |c: i64, h: i64, i: usize| -> (i32, i32) {
            let lo = ((c - h) >> 16) as i32 - 1;
            let hi = ((c + h) >> 16) as i32 + 1;
            (lo.max(g[i]), (hi + 1).min(lim[i]))
        };
        let (x0, x1) = bornes(p.centre.x, p.demi.x, 0);
        let (y0, y1) = bornes(p.centre.y, p.demi.y, 1);
        let (z0, z1) = bornes(p.centre.z, p.demi.z, 2);
        if x0 >= x1 || y0 >= y1 || z0 >= z1 {
            return;
        }
        self.marquer([x0, y0, z0], [x1, y1, z1]);
        let [cx, cy, cz] = p.colonnes;
        // lisière douce : un voxel à cheval sur la surface reçoit la part du volume qui le recouvre (rampe d'un
        // voxel de large), comme les points du Python qui tombent dans des voxels de bord
        let rbar = p.rbar.max(1);
        let bande = fx::div(self.lisiere, rbar).min(UN);
        let interieur = fx::mul(UN - bande, UN - bande);
        let exterieur = fx::mul(UN + bande, UN + bande);
        for z in z0..z1 {
            for y in y0..y1 {
                // vecteur de départ au centre du premier voxel de la rangée
                let w0 = V3::new(
                    (i64::from(x0) << 16) + 32_768 - p.centre.x,
                    (i64::from(y) << 16) + 32_768 - p.centre.y,
                    (i64::from(z) << 16) + 32_768 - p.centre.z,
                );
                let mut u = V3::new(
                    mul3(cx.x, w0.x, cy.x, w0.y, cz.x, w0.z),
                    mul3(cx.y, w0.x, cy.y, w0.y, cz.y, w0.z),
                    mul3(cx.z, w0.x, cy.z, w0.y, cz.z, w0.z),
                );
                let debut = self.idx((x0 - g[0]) as usize, (y - g[1]) as usize, (z - g[2]) as usize);
                for i in debut..debut + (x1 - x0) as usize {
                    let d2 = (u.x * u.x + u.y * u.y + u.z * u.z) >> 16;
                    if d2 <= exterieur {
                        let part = if d2 <= interieur {
                            UN
                        } else {
                            {
                                // |u| - 1 par le développement d'ordre 2 de la racine autour de 1 (pas de racine entière)
                                let e = d2 - UN;
                                let ecart = e / 2 - (((e >> 8) * (e >> 8)) >> 3);
                                (UN / 2 - fx::div(fx::mul(ecart, rbar), 2 * self.lisiere)).clamp(0, UN)
                            }
                        };
                        if part > 0 {
                            self.lam[i] =
                                self.lam[i].saturating_add(((i64::from(p.lambda) * part) >> 16) as u32);
                            self.variant[i] = p.variant;
                        }
                    }
                    u = V3::new(u.x + cx.x, u.y + cx.y, u.z + cx.z);
                }
            }
        }
    }

    /// Amas plus petit qu'un demi-voxel : ses points (autant que `densité × volume`, au moins un) sont tirés un à
    /// un dans l'ellipsoïde, par hachage de `sel`, et la case de chacun devient pleine.
    fn add_points(&mut self, b: &Blob, lod: u8, sel: u64) {
        let n = ((b.density * b.volume()) >> 32).clamp(1, 64);
        let k = u32::from(lod);
        let s2 = fx::mul(b.stretch, b.stretch) - UN;
        let _ = s2;
        for j in 0..n {
            // point uniforme dans la boule unité par rejet sur trois hachages
            let mut u = V3::ZERO;
            for essai in 0..16_i64 {
                let h = |c: i64| 2 * fx::hash_unit(hash_combine(sel, j as u64), essai, c, 0) - UN;
                u = V3::new(h(0), h(1), h(2));
                if (fx::mul(u.x, u.x) + fx::mul(u.y, u.y) + fx::mul(u.z, u.z)) <= UN {
                    break;
                }
            }
            // allongement le long de la direction puis aplatissement vertical
            let ua = u.dot(b.dir);
            let mut w = u.add(b.dir.scale(fx::mul(b.stretch - UN, ua)));
            w.z = fx::mul(w.z, b.flat);
            let p = b.center.add(w.scale(b.r));
            let (x, y, z) = (
                (p.x >> (16 + k)) as i32,
                (p.y >> (16 + k)) as i32,
                (p.z >> (16 + k)) as i32,
            );
            let g = self.min;
            let (ix, iy, iz) = (x - g[0], y - g[1], z - g[2]);
            if ix >= 0
                && iy >= 0
                && iz >= 0
                && (ix as usize) < self.dim[0]
                && (iy as usize) < self.dim[1]
                && (iz as usize) < self.dim[2]
            {
                let i = self.idx(ix as usize, iy as usize, iz as usize);
                self.marquer([x, y, z], [x + 1, y + 1, z + 1]);
                self.lam[i] = SATURE;
                self.variant[i] = b.variant;
            }
        }
    }

    /// Tire les voxels pleins de la fenêtre `[min, max)` : `lambda` de la case plus `grandes/6` fois celui de ses
    /// six voisines (les points qui débordent d'un voxel), puis un hachage monde contre `1 - exp(-lambda)`.
    /// `f(x, y, z, variante)` reçoit chaque voxel plein, dans l'ordre z, y, x.
    pub fn emit(
        &self,
        min: [i32; 3],
        max: [i32; 3],
        grandes: i64,
        graine: u64,
        mut f: impl FnMut(i32, i32, i32, u8),
    ) {
        let g6 = grandes / 6;
        let Some((tl, th)) = self.touche else { return };
        // les points qui débordent d'un voxel étalent la boîte touchée d'un voxel
        let m = i32::from(g6 > 0);
        let lo = [
            min[0].max(tl[0] - m),
            min[1].max(tl[1] - m),
            min[2].max(tl[2] - m),
        ];
        let hi = [
            max[0].min(th[0] + m),
            max[1].min(th[1] + m),
            max[2].min(th[2] + m),
        ];
        for z in lo[2]..hi[2] {
            for y in lo[1]..hi[1] {
                for x in lo[0]..hi[0] {
                    let (ix, iy, iz) = (
                        (x - self.min[0]) as usize,
                        (y - self.min[1]) as usize,
                        (z - self.min[2]) as usize,
                    );
                    let i = self.idx(ix, iy, iz);
                    let mut l = i64::from(self.lam[i]);
                    if g6 > 0 {
                        let sx = self.idx(1, 0, 0) - self.idx(0, 0, 0);
                        let sy = self.idx(0, 1, 0) - self.idx(0, 0, 0);
                        let sz = self.idx(0, 0, 1) - self.idx(0, 0, 0);
                        let voisins = i64::from(self.lam[i - sx])
                            + i64::from(self.lam[i + sx])
                            + i64::from(self.lam[i - sy])
                            + i64::from(self.lam[i + sy])
                            + i64::from(self.lam[i - sz])
                            + i64::from(self.lam[i + sz]);
                        l += fx::mul(voisins, g6);
                    }
                    if l == 0 {
                        continue;
                    }
                    let p = UN - fx::exp_neg((l << 16) / Q10);
                    if fx::hash_unit(graine, i64::from(x), i64::from(y), i64::from(z)) < p {
                        f(x, y, z, self.variant[i]);
                    }
                }
            }
        }
    }
}

#[inline]
fn mul3(a: i64, x: i64, b: i64, y: i64, c: i64, z: i64) -> i64 {
    fx::mul(a, x) + fx::mul(b, y) + fx::mul(c, z)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn amas(r_vox: i64) -> Blob {
        Blob {
            center: V3::new(0, 0, 0),
            dir: V3::HAUT,
            r: r_vox * UN,
            stretch: UN,
            flat: UN,
            density: UN / 2,
            variant: 0,
        }
    }

    #[test]
    fn un_amas_remplit_la_part_attendue_de_son_volume() {
        let b = amas(8);
        let mut g = DensityGrid::new([-12, -12, -12], [12, 12, 12], LISIERE_FEUILLES);
        g.add(&b, 0, 1);
        let mut n = 0_i64;
        g.emit([-12, -12, -12], [12, 12, 12], 0, 9, |_, _, _, _| n += 1);
        // volume 4/3 π 8³ = 2144 voxels ; 1 - e^-0,5 = 39,3 % -> 843
        assert!((760..930).contains(&n), "{n} voxels");
    }

    #[test]
    fn la_fenetre_ne_change_pas_les_voxels() {
        let b = amas(6);
        let mut g1 = DensityGrid::new([-10, -10, -10], [10, 10, 10], LISIERE_FEUILLES);
        g1.add(&b, 0, 1);
        let mut tout = Vec::new();
        g1.emit([-10, -10, -10], [10, 10, 10], 0, 5, |x, y, z, _| {
            tout.push((x, y, z))
        });
        let mut g2 = DensityGrid::new([0, -10, -10], [10, 10, 10], LISIERE_FEUILLES);
        g2.add(&b, 0, 1);
        let mut moitie = Vec::new();
        g2.emit([0, -10, -10], [10, 10, 10], 0, 5, |x, y, z, _| {
            moitie.push((x, y, z))
        });
        let attendu: Vec<_> = tout.into_iter().filter(|v| v.0 >= 0).collect();
        assert_eq!(moitie, attendu);
    }

    #[test]
    fn un_niveau_grossier_garde_un_amas_visible() {
        let b = amas(2); // 2 voxels de rayon au niveau 0 -> 0,25 au niveau 3 : gonflé
        let mut g = DensityGrid::new([-4, -4, -4], [4, 4, 4], LISIERE_FEUILLES);
        g.add(&b, 3, 1);
        let mut n = 0;
        g.emit([-4, -4, -4], [4, 4, 4], 0, 1, |_, _, _, _| n += 1);
        assert!(n >= 1);
    }
}
