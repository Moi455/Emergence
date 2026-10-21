//! Le mobilier de la maison : la bibliothèque `IT` de « nouvelle référence.html » portée en `Kind`. Chaque meuble
//! a ses dimensions (largeur le long du mur `w`, profondeur `dp`, hauteur `h`, hauteur d'accrochage `j0`) et se
//! dessine dans un repère local (i le long du mur, j en hauteur, k depuis le mur) avec des `Paint`, des
//! intentions de matière résolues plus tard en voxels (classe + teinte) selon la position.
//!
//! Les ellipses et cylindres du JavaScript (`Math.hypot` en flottants) sont calculés en centièmes de voxel.

use crate::batiments::kit::intmath::{cos100, in_disc100, sin100};
use crate::batiments::kit::rng::{hh, hh_below, hh_lt};

/// Une intention de peinture : ce que le JavaScript écrivait en RVB devient une famille de matière.
#[derive(Copy, Clone, Debug, PartialEq, Eq)]
pub enum Paint {
    /// Bois du mobilier de la pièce (teinte de la pièce), `amp` : gigue (0 = aucune).
    Wood,
    /// Bois sombre (pieds, tiroirs).
    WoodDark,
    /// Bois clair (tonneaux).
    WoodLight,
    /// Fer.
    Iron,
    /// Fer très sombre (marmite).
    IronDark,
    /// Acier clair.
    Steel,
    /// Draps.
    Linen,
    /// Oreillers.
    Pillow,
    /// Étoffe numéro `n` (palette BLK : rouge, bleu, vert, jaune, violet, blanc).
    Fabric(u8),
    /// Étoffe numéro `n`, plus sombre.
    FabricDark(u8),
    /// Laiton et dorures.
    Brass,
    /// Pierre claire de plan de travail.
    StoneTop,
    /// Pierre du fourneau.
    StoneDark,
    /// Charbon, ouverture sombre.
    Coal,
    /// Braise (émissive).
    Ember,
    /// Cire, papier, pages.
    Wax,
    /// Flamme (émissive).
    Flame,
    /// Terre cuite, ton 0..127.
    Ceramic(u8),
    /// Pain et nourriture claire.
    Bread,
    /// Feuillage de plante.
    Leaf,
    /// Terreau.
    Soil,
    /// Eau.
    Water,
    /// Verre.
    Glass,
    /// Plâtre blanc.
    Plaster,
    /// Bleu peint.
    PaintBlue,
    /// Vert peint.
    PaintGreen,
    /// Rouge peint.
    PaintRed,
    /// Cuir.
    Leather,
    /// Fruit rouge.
    FruitRed,
    /// Fruit jaune.
    FruitYellow,
}

/// Où un meuble dessine : `l(i, j, k, peinture)`.
pub trait Canvas {
    /// Pose un voxel du meuble.
    fn l(&mut self, i: i32, j: i32, k: i32, p: Paint);
    /// Creuse un voxel du meuble.
    fn air(&mut self, i: i32, j: i32, k: i32);
}

fn bx(c: &mut dyn Canvas, i: (i32, i32), j: (i32, i32), k: (i32, i32), p: Paint) {
    for a in i.0..i.1 {
        for b in j.0..j.1 {
            for d in k.0..k.1 {
                c.l(a, b, d, p);
            }
        }
    }
}

/// Cylindre plein de centre (cx, cz) et de rayon `r` en centièmes de voxel, entre les hauteurs j0 et j1.
fn cyl(c: &mut dyn Canvas, cx100: i32, cz100: i32, r100: i32, j0: i32, j1: i32, p: Paint) {
    let n = (r100 + cx100.max(cz100)) / 100 + 2;
    for i in 0..=n {
        for k in 0..=n {
            if in_disc100(100 * i, 100 * k, cx100, cz100, r100) {
                for j in j0..j1 {
                    c.l(i, j, k, p);
                }
            }
        }
    }
}

const BLK_COUNT: i32 = 5;

/// Les meubles.
#[derive(Copy, Clone, Debug, PartialEq, Eq, Hash)]
#[allow(missing_docs)]
pub enum Kind {
    Bed,
    Ward,
    Chest,
    Table,
    Stool,
    Chair,
    Bench,
    Shelf,
    Counter,
    Crate,
    Barrel,
    Night,
    BedS,
    BedD,
    Cot,
    Armchair,
    Settle,
    Dresser,
    Cupboard,
    BookL,
    Stove,
    Bench2,
    Anvil,
    Sacks,
    CrateS,
    Bucket,
    Plant,
    Globe,
    Lectern,
    RoundT,
    Wheel,
    Mirror,
    Painting,
    Banner,
    Shield,
    Herbs,
    Swords,
    MapD,
    Sconce,
}

impl Kind {
    /// Largeur le long du mur.
    pub const fn w(self) -> i32 {
        use Kind::*;
        match self {
            Bed | Ward | RoundT => 22,
            Chest => 16,
            Table => 34,
            Stool => 7,
            Chair => 8,
            Bench => 28,
            Shelf => 24,
            Counter => 30,
            Crate | Globe | Lectern => 10,
            Barrel => 13,
            Night => 9,
            BedS => 16,
            BedD | Settle => 30,
            Cot => 12,
            Armchair => 12,
            Dresser => 28,
            Cupboard | BookL => 20,
            Stove => 18,
            Bench2 => 36,
            Anvil => 12,
            Sacks => 12,
            CrateS => 12,
            Bucket => 7,
            Plant => 8,
            Wheel => 16,
            Mirror => 12,
            Painting => 12,
            Banner => 8,
            Shield => 10,
            Herbs => 10,
            Swords => 16,
            MapD => 14,
            Sconce => 3,
        }
    }

    /// Profondeur depuis le mur.
    pub const fn dp(self) -> i32 {
        use Kind::*;
        match self {
            Bed => 40,
            Ward => 10,
            Bench => 7,
            Shelf => 6,
            Dresser => 10,
            Settle => 9,
            BookL => 6,
            Cupboard => 9,
            Anvil => 8,
            Chest => 9,
            Table => 18,
            Stool => 7,
            Chair => 8,
            Counter => 12,
            Crate => 10,
            Barrel => 13,
            Night => 9,
            BedS => 34,
            BedD => 40,
            Cot => 20,
            Armchair => 12,
            Stove => 15,
            Bench2 => 14,
            Sacks => 10,
            CrateS => 10,
            Bucket => 7,
            Plant => 8,
            Globe => 10,
            Lectern => 10,
            RoundT => 22,
            Wheel => 12,
            Mirror => 5,
            Painting => 1,
            Banner => 1,
            Shield => 2,
            Herbs => 2,
            Swords => 2,
            MapD => 1,
            Sconce => 3,
        }
    }

    /// Hauteur (`it.h || HT[n] || 30`).
    pub const fn h(self) -> i32 {
        use Kind::*;
        match self {
            Bed => 18,
            Ward => 40,
            Chest => 9,
            Table => 20,
            Stool => 9,
            Chair => 18,
            Bench => 9,
            Shelf => 36,
            Counter => 21,
            Crate => 10,
            Barrel => 14,
            Night => 15,
            BedS => 14,
            BedD => 32,
            Cot => 10,
            Armchair => 20,
            Settle => 22,
            Dresser => 29,
            Cupboard => 34,
            BookL => 20,
            Stove => 50,
            Bench2 => 24,
            Anvil => 11,
            Sacks => 11,
            CrateS => 18,
            Bucket => 8,
            Plant => 16,
            Globe => 18,
            Lectern => 24,
            RoundT => 20,
            Wheel => 20,
            Mirror => 34,
            Painting => 10,
            Banner => 26,
            Shield => 10,
            Herbs => 10,
            Swords => 14,
            MapD => 11,
            Sconce => 6,
        }
    }

    /// Hauteur d'accrochage des décors muraux (0 pour un meuble posé).
    pub const fn j0(self) -> i32 {
        use Kind::*;
        match self {
            Painting => 24,
            Banner => 12,
            Shield => 24,
            Herbs => 30,
            Swords => 26,
            MapD => 22,
            Sconce => 28,
            _ => 0,
        }
    }

    /// Dessine le meuble dans son repère local ; `q` est le tirage 0..1000 de la pose.
    pub fn draw(self, q: i32, c: &mut dyn Canvas) {
        use Kind::*;
        use Paint::*;
        let blk = |n: i32| -> Paint { Fabric((n.rem_euclid(BLK_COUNT)) as u8) };
        match self {
            Bed => {
                let bl = blk(q);
                bx(c, (0, 22), (5, 7), (0, 40), Wood);
                for (i, k) in [(0, 0), (20, 0), (0, 38), (20, 38)] {
                    bx(c, (i, i + 2), (0, 5), (k, k + 2), WoodDark);
                }
                bx(c, (0, 22), (5, 18), (0, 2), WoodDark);
                bx(c, (0, 22), (5, 11), (38, 40), WoodDark);
                bx(c, (1, 21), (7, 10), (2, 38), Linen);
                bx(c, (1, 21), (10, 11), (14, 38), bl);
                bx(c, (4, 18), (10, 12), (3, 10), Pillow);
            }
            Ward => {
                bx(c, (0, 22), (0, 40), (0, 10), Wood);
                bx(c, (0, 22), (38, 40), (0, 10), WoodDark);
                bx(c, (11, 12), (1, 38), (9, 10), WoodDark);
                for i in [9, 13] {
                    c.l(i, 20, 9, Iron);
                    c.l(i, 21, 9, Iron);
                }
            }
            Chest => {
                bx(c, (0, 16), (0, 9), (0, 9), Wood);
                bx(c, (3, 4), (0, 9), (0, 9), Iron);
                bx(c, (12, 13), (0, 9), (0, 9), Iron);
                bx(c, (7, 9), (5, 7), (8, 9), Brass);
            }
            Table => {
                bx(c, (0, 34), (13, 15), (0, 18), Wood);
                for (i, k) in [(1, 1), (31, 1), (1, 15), (31, 15)] {
                    bx(c, (i, i + 2), (0, 13), (k, k + 2), WoodDark);
                }
                bx(c, (3, 31), (10, 11), (8, 10), WoodDark);
                table_deco(c, 12, 9, 15, q);
                if q & 8 != 0 {
                    table_deco(c, 24, 9, 15, q >> 3);
                }
            }
            Stool => {
                bx(c, (0, 7), (7, 9), (0, 7), Wood);
                for (i, k) in [(0, 0), (5, 0), (0, 5), (5, 5)] {
                    bx(c, (i, i + 2), (0, 7), (k, k + 2), WoodDark);
                }
            }
            Chair => {
                bx(c, (0, 8), (8, 9), (0, 8), Wood);
                for (i, k) in [(0, 0), (6, 0), (0, 6), (6, 6)] {
                    bx(c, (i, i + 2), (0, 8), (k, k + 2), WoodDark);
                }
                bx(c, (0, 2), (9, 18), (0, 2), WoodDark);
                bx(c, (6, 8), (9, 18), (0, 2), WoodDark);
                bx(c, (2, 6), (13, 17), (0, 1), Wood);
            }
            Bench => {
                bx(c, (0, 28), (7, 9), (0, 7), Wood);
                for i in [1, 25] {
                    bx(c, (i, i + 2), (0, 7), (1, 6), WoodDark);
                }
            }
            Shelf => {
                bx(c, (0, 24), (0, 36), (0, 1), WoodDark);
                bx(c, (0, 2), (0, 36), (0, 6), Wood);
                bx(c, (22, 24), (0, 36), (0, 6), Wood);
                for j in [0, 9, 18, 27, 34] {
                    bx(c, (0, 24), (j, j + 2), (0, 6), Wood);
                }
                for cc in 0..4 {
                    for i in (2..22).step_by(2) {
                        if hh_lt(hh(q, i, cc, 2), 15) {
                            continue;
                        }
                        let hgt = 4 + hh_below(hh(q, i, cc, 0), 3) as i32;
                        bx(
                            c,
                            (i, i + 2),
                            (cc * 9 + 2, cc * 9 + 2 + hgt),
                            (1, 5),
                            blk(hh_below(hh(q, i, cc, 3), 5) as i32),
                        );
                    }
                }
            }
            Counter => {
                bx(c, (0, 30), (0, 16), (0, 12), Wood);
                for i in [10, 20] {
                    bx(c, (i, i + 1), (1, 15), (11, 12), WoodDark);
                }
                bx(c, (0, 30), (16, 18), (0, 12), StoneTop);
                bx(c, (3, 11), (18, 19), (3, 9), Bread);
                cyl(c, 1900, 600, 250, 18, 19, Ceramic(90));
                cyl(c, 2500, 500, 180, 18, 23, Ceramic(40));
            }
            Crate => {
                bx(c, (0, 10), (0, 10), (0, 10), Wood);
                bx(c, (0, 10), (4, 6), (0, 10), WoodDark);
                bx(c, (4, 6), (0, 10), (0, 10), WoodDark);
            }
            Barrel => {
                for j in 0..14 {
                    // bl = 6,4 - ((j - 6,5) / 7)^2 * 1,3, en centièmes
                    let bl100 = 640 - 130 * (2 * j - 13) * (2 * j - 13) / 196;
                    for i in 0..13 {
                        for k in 0..13 {
                            let r2 = (100 * (i - 6)) * (100 * (i - 6)) + (100 * (k - 6)) * (100 * (k - 6));
                            if r2 > bl100 * bl100 {
                                continue;
                            }
                            let p = if j == 13 {
                                if r2 > (bl100 - 120) * (bl100 - 120) {
                                    WoodLight
                                } else {
                                    WoodDark
                                }
                            } else if j == 3 || j == 10 {
                                Iron
                            } else {
                                WoodLight
                            };
                            c.l(i, j, k, p);
                        }
                    }
                }
            }
            Night => {
                bx(c, (0, 9), (0, 10), (0, 9), Wood);
                bx(c, (0, 9), (10, 11), (0, 9), WoodDark);
                bx(c, (4, 5), (11, 14), (4, 5), Wax);
                c.l(4, 14, 4, Flame);
            }
            BedS => {
                let bl = blk(q);
                bx(c, (0, 16), (4, 6), (0, 34), Wood);
                for (i, k) in [(0, 0), (14, 0), (0, 32), (14, 32)] {
                    bx(c, (i, i + 2), (0, 4), (k, k + 2), WoodDark);
                }
                bx(c, (0, 16), (4, 14), (0, 2), WoodDark);
                bx(c, (1, 15), (6, 8), (2, 34), Linen);
                bx(c, (1, 15), (8, 9), (12, 34), bl);
                bx(c, (3, 13), (8, 10), (2, 9), Pillow);
            }
            BedD => {
                let (bl, cu) = (blk(q), blk(q + 2));
                bx(c, (0, 30), (5, 7), (0, 40), Wood);
                for (i, k) in [(0, 0), (28, 0), (0, 38), (28, 38)] {
                    bx(c, (i, i + 2), (0, 32), (k, k + 2), WoodDark);
                }
                bx(c, (0, 30), (7, 20), (0, 2), WoodDark);
                bx(c, (0, 30), (5, 11), (38, 40), WoodDark);
                bx(c, (2, 28), (7, 10), (2, 38), Linen);
                bx(c, (2, 28), (10, 11), (12, 38), bl);
                bx(c, (3, 14), (10, 12), (3, 10), Pillow);
                bx(c, (16, 27), (10, 12), (3, 10), Pillow);
                bx(c, (2, 28), (30, 32), (0, 2), cu);
            }
            Cot => {
                bx(c, (0, 12), (2, 3), (0, 20), Wood);
                bx(c, (0, 12), (2, 8), (0, 1), WoodDark);
                bx(c, (0, 12), (2, 8), (19, 20), WoodDark);
                bx(c, (0, 1), (2, 8), (0, 20), WoodDark);
                bx(c, (11, 12), (2, 8), (0, 20), WoodDark);
                bx(c, (1, 11), (3, 4), (1, 19), Linen);
                bx(c, (1, 11), (4, 5), (6, 19), blk(q));
                bx(c, (0, 12), (0, 2), (2, 4), WoodDark);
                bx(c, (0, 12), (0, 2), (16, 18), WoodDark);
            }
            Armchair => {
                let cu = blk(q);
                bx(c, (0, 12), (0, 6), (0, 12), WoodDark);
                bx(c, (1, 11), (6, 9), (1, 12), cu);
                bx(c, (1, 11), (9, 20), (0, 3), cu);
                bx(c, (0, 2), (6, 14), (0, 12), Wood);
                bx(c, (10, 12), (6, 14), (0, 12), Wood);
                bx(c, (2, 10), (9, 11), (3, 11), cu);
            }
            Settle => {
                let cu = blk(q);
                bx(c, (0, 30), (0, 7), (0, 9), WoodDark);
                bx(c, (1, 29), (7, 9), (1, 9), cu);
                bx(c, (0, 30), (9, 22), (0, 2), Wood);
                bx(c, (0, 2), (7, 15), (0, 9), Wood);
                bx(c, (28, 30), (7, 15), (0, 9), Wood);
                bx(
                    c,
                    (2, 28),
                    (9, 15),
                    (2, 3),
                    FabricDark((q.rem_euclid(BLK_COUNT)) as u8),
                );
            }
            Dresser => {
                bx(c, (0, 28), (0, 22), (0, 10), Wood);
                bx(c, (0, 28), (22, 24), (0, 10), WoodDark);
                for j in [7, 14] {
                    bx(c, (0, 28), (j, j + 1), (9, 10), WoodDark);
                }
                for j in [3, 10, 17] {
                    for i in [7, 20] {
                        bx(c, (i, i + 2), (j, j + 1), (9, 10), Brass);
                    }
                }
                cyl(c, 2200, 500, 250, 24, 28, Ceramic(90));
            }
            Cupboard => {
                bx(c, (0, 20), (0, 34), (0, 9), Wood);
                bx(c, (0, 20), (0, 12), (8, 9), WoodDark);
                bx(c, (3, 17), (14, 31), (8, 9), Glass);
                for i in 3..17 {
                    for j in 14..31 {
                        for k in 1..8 {
                            c.air(i, j, k);
                        }
                    }
                }
                for j in (18..31).step_by(6) {
                    bx(c, (2, 18), (j, j + 1), (1, 8), WoodDark);
                    for i in (4..17).step_by(3) {
                        bx(
                            c,
                            (i, i + 2),
                            (j + 1, j + 3),
                            (3, 5),
                            blk(hh_below(hh(q, i, j, 0), 5) as i32),
                        );
                    }
                }
            }
            BookL => {
                bx(c, (0, 20), (0, 20), (0, 1), WoodDark);
                bx(c, (0, 2), (0, 20), (0, 6), Wood);
                bx(c, (18, 20), (0, 20), (0, 6), Wood);
                for j in [0, 9, 18] {
                    bx(c, (0, 20), (j, j + 2), (0, 6), Wood);
                }
                for cc in 0..2 {
                    for i in (2..18).step_by(2) {
                        if hh_lt(hh(q, i, cc, 2), 20) {
                            continue;
                        }
                        let top = cc * 9 + 6 + hh_below(hh(q, i, cc, 0), 3) as i32;
                        bx(
                            c,
                            (i, i + 2),
                            (cc * 9 + 2, top),
                            (1, 5),
                            blk(hh_below(hh(q, i, cc, 3), 5) as i32),
                        );
                    }
                }
            }
            Stove => {
                bx(c, (0, 18), (0, 18), (0, 15), StoneDark);
                bx(c, (0, 18), (18, 20), (0, 15), Iron);
                bx(c, (5, 13), (4, 12), (14, 15), Coal);
                for i in 6..12 {
                    c.l(i, 5, 14, Ember);
                }
                cyl(c, 500, 700, 300, 20, 25, IronDark);
                bx(c, (7, 10), (20, 50), (10, 13), Iron);
            }
            Bench2 => {
                bx(c, (0, 36), (14, 17), (0, 14), Wood);
                for (i, k) in [(1, 1), (33, 1), (1, 11), (33, 11)] {
                    bx(c, (i, i + 2), (0, 14), (k, k + 2), WoodDark);
                }
                bx(c, (2, 34), (6, 8), (2, 4), WoodDark);
                bx(c, (2, 34), (6, 8), (10, 12), WoodDark);
                bx(c, (4, 8), (17, 19), (3, 9), Iron);
                bx(c, (12, 20), (17, 18), (4, 6), Steel);
                bx(c, (24, 32), (17, 19), (3, 9), WoodDark);
                bx(c, (26, 29), (19, 21), (4, 7), Wood);
            }
            Anvil => {
                bx(c, (3, 9), (0, 5), (2, 6), WoodDark);
                bx(c, (2, 10), (5, 8), (1, 7), Iron);
                bx(c, (0, 12), (8, 11), (2, 6), IronDark);
                bx(c, (10, 12), (9, 10), (3, 5), IronDark);
            }
            Sacks => {
                for (i, k, j) in [(0, 0, 0), (6, 0, 0), (3, 5, 0), (3, 1, 5)] {
                    bx(c, (i, i + 6), (j, j + 5), (k, k + 5), Bread);
                    bx(c, (i + 2, i + 4), (j + 5, j + 6), (k + 1, k + 3), Leather);
                }
            }
            CrateS => {
                bx(c, (0, 10), (0, 8), (0, 10), Wood);
                bx(c, (0, 10), (3, 4), (0, 10), WoodDark);
                bx(c, (4, 5), (0, 8), (0, 10), WoodDark);
                bx(c, (2, 9), (8, 14), (1, 8), Wood);
                bx(c, (2, 9), (10, 11), (1, 8), WoodDark);
                bx(c, (10, 12), (0, 5), (3, 8), Wood);
            }
            Bucket => {
                for j in 0..7 {
                    cyl(
                        c,
                        300,
                        300,
                        260 + j * 12,
                        j,
                        j + 1,
                        if j % 3 == 2 { Iron } else { Wood },
                    );
                }
                cyl(c, 300, 300, 200, 5, 6, Water);
            }
            Plant => {
                cyl(c, 350, 350, 300, 0, 5, Ceramic(60));
                cyl(c, 350, 350, 230, 5, 6, Soil);
                for j in 6..11 {
                    c.l(3, j, 3, Leaf);
                }
                for k in 0..22 {
                    let a_q16 = (hh(q, k, 0, 0) >> 16) as i32;
                    let rr100 = ((u64::from(hh(q, k, 1, 0)) * 320) >> 32) as i32;
                    let j = 6 + hh_below(hh(q, k, 2, 0), 9) as i32;
                    let px = (350 + cos100(a_q16) * rr100 / 100 + 50).div_euclid(100);
                    let pz = (350 + sin100(a_q16) * rr100 / 100 + 50).div_euclid(100);
                    c.l(px, j, pz, Leaf);
                }
            }
            Globe => {
                bx(c, (3, 7), (0, 2), (3, 7), WoodDark);
                bx(c, (4, 6), (2, 8), (4, 6), WoodDark);
                for i in 0..10 {
                    for j in 8..18 {
                        for k in 0..10 {
                            let (dx, dy, dz) = (100 * i - 450, 100 * j - 1250, 100 * k - 450);
                            if dx * dx + dy * dy + dz * dz <= 460 * 460 {
                                c.l(
                                    i,
                                    j,
                                    k,
                                    if hh_lt(hh(i, j, k, 0), 35) {
                                        PaintGreen
                                    } else {
                                        PaintBlue
                                    },
                                );
                            }
                        }
                    }
                }
            }
            Lectern => {
                bx(c, (3, 7), (0, 18), (3, 7), WoodDark);
                bx(c, (1, 9), (0, 2), (1, 9), WoodDark);
                for k in 0..8 {
                    let j = 18 + (k >> 1);
                    bx(c, (0, 10), (j, j + 1), (k + 1, k + 2), Wood);
                    bx(c, (1, 9), (j + 1, j + 2), (k + 1, k + 2), Wax);
                }
            }
            RoundT => {
                cyl(c, 1050, 1050, 1080, 13, 15, Wood);
                bx(c, (9, 12), (0, 13), (9, 12), WoodDark);
                cyl(c, 1050, 1050, 500, 0, 2, WoodDark);
                table_deco(c, 10, 10, 15, q);
            }
            Wheel => {
                bx(c, (0, 16), (0, 2), (2, 3), WoodDark);
                bx(c, (0, 16), (0, 2), (9, 10), WoodDark);
                bx(c, (12, 14), (0, 12), (2, 10), Wood);
                for t in 0..44 {
                    let tours = (i64::from(t) * 1428 * 65_536 / 62_832) as i32;
                    let px = (600 + cos100(tours) * 5 + 50).div_euclid(100);
                    let pz = (1100 + sin100(tours) * 55 / 10 + 50).div_euclid(100);
                    c.l(px, pz, 5, Wood);
                }
                bx(c, (5, 7), (10, 12), (4, 7), Iron);
                bx(c, (8, 13), (12, 14), (3, 8), Wood);
            }
            Mirror => {
                bx(c, (1, 11), (0, 2), (0, 5), WoodDark);
                bx(c, (0, 12), (2, 34), (1, 3), Wood);
                bx(c, (2, 10), (5, 31), (2, 3), Glass);
            }
            Painting => {
                let m = q % 3;
                bx(c, (0, 12), (0, 10), (0, 1), Brass);
                bx(c, (1, 11), (1, 9), (0, 1), PaintBlue);
                bx(c, (1, 11), (1, 4), (0, 1), PaintGreen);
                bx(c, (3 + m, 7 + m), (3, 6), (0, 1), blk(q));
                bx(c, (4 + m, 6 + m), (6, 7), (0, 1), PaintRed);
            }
            Banner => {
                let col = blk(q);
                bx(c, (0, 8), (24, 26), (0, 1), WoodDark);
                bx(c, (1, 7), (4, 24), (0, 1), col);
                for i in 1..7_i32 {
                    let m = ((2 * i - 7).abs() / 2).min(3);
                    bx(c, (i, i + 1), (3 - m, 4), (0, 1), col);
                }
                bx(c, (3, 5), (12, 18), (0, 1), Brass);
            }
            Shield => {
                let a = blk(q);
                for i in 0..10 {
                    for j in 0..10 {
                        let r2 = (100 * i - 450) * (100 * i - 450) + (100 * j - 450) * (100 * j - 450);
                        if r2 > 480 * 480 {
                            continue;
                        }
                        let p = if r2 > 390 * 390 {
                            Iron
                        } else if (i < 5) != (j < 5) {
                            a
                        } else {
                            Plaster
                        };
                        c.l(i, j, 0, p);
                        if r2 < 150 * 150 {
                            c.l(i, j, 1, Iron);
                        }
                    }
                }
            }
            Herbs => {
                bx(c, (0, 10), (9, 10), (0, 1), WoodDark);
                for i in [1, 4, 7] {
                    bx(c, (i, i + 1), (3, 9), (0, 1), Leather);
                    bx(c, ((i - 1).max(0), i + 2), (0, 4), (0, 2), Leaf);
                }
            }
            Swords => {
                for t in 0..14 {
                    c.l(1 + t, t, 0, Steel);
                    c.l(14 - t, t, 0, Steel);
                }
                bx(c, (0, 5), (2, 3), (0, 1), Brass);
                bx(c, (11, 16), (2, 3), (0, 1), Brass);
            }
            MapD => {
                bx(c, (0, 14), (0, 11), (0, 1), Wax);
                for i in (1..13).step_by(2) {
                    c.l(i, 3 + hh_below(hh(q, i, 0, 0), 5) as i32, 0, Leather);
                }
                c.l(8, 6, 0, PaintRed);
                bx(c, (0, 14), (0, 1), (0, 1), WoodDark);
                bx(c, (0, 14), (10, 11), (0, 1), WoodDark);
            }
            Sconce => {
                bx(c, (1, 2), (0, 2), (0, 1), Iron);
                bx(c, (0, 3), (2, 3), (0, 3), Iron);
                bx(c, (1, 2), (3, 5), (1, 2), Wax);
                c.l(1, 5, 1, Flame);
            }
        }
    }
}

/// Décor de table : bougie, corbeille de fruits, assiettes, cruche ou nappe et pain (selon `q % 5`).
fn table_deco(c: &mut dyn Canvas, ci: i32, ck: i32, j: i32, q: i32) {
    use Paint::*;
    match q.rem_euclid(5) {
        0 => {
            for t in 0..2 {
                c.l(ci, j + t, ck, Wax);
            }
            c.l(ci, j + 2, ck, Flame);
        }
        1 => {
            cyl(c, 100 * ci, 100 * ck, 320, j, j + 1, Ceramic(60));
            let pts = [(2, 0), (1, 2), (-1, 2), (-2, 0), (-1, -1), (1, -2), (2, -1)];
            for (t, (dx, dz)) in pts.iter().enumerate() {
                let p = [FruitRed, FruitYellow, PaintGreen][t % 3];
                c.l(ci + dx, j + 1, ck + dz, p);
            }
        }
        2 => {
            cyl(c, 100 * (ci - 4), 100 * ck, 260, j, j + 1, Plaster);
            cyl(c, 100 * (ci + 4), 100 * ck, 260, j, j + 1, Plaster);
            c.l(ci - 4, j + 1, ck, Ceramic(30));
            c.l(ci + 4, j + 1, ck, Ceramic(100));
        }
        3 => {
            cyl(c, 100 * ci, 100 * ck, 180, j, j + 5, Ceramic(40));
            c.l(ci + 2, j + 3, ck, Ceramic(40));
        }
        _ => {
            for i in ci - 3..ci + 3 {
                for kk in ck - 2..ck + 2 {
                    c.l(i, j, kk, Fabric(0));
                    if i < ci + 2 && kk < ck + 1 {
                        c.l(i, j + 1, kk, Bread);
                    }
                }
            }
        }
    }
}
