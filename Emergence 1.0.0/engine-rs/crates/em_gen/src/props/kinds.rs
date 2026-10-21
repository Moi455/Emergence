//! Les RECETTES de props : chacune dessine un objet dans le repère local de `PropBuilder` (x est, y haut, z devant),
//! centré sur son emprise au sol, avec des variantes tirées de la graine. Les cotes sont en voxels de 5 cm, sauf les
//! recettes « petites » (bougie, vaisselle, pain, fruits, livre, clé, outils) cotées en MILLIMÈTRES et dessinées
//! à la taille du voxel de la configuration (20 mm : pixel art soigné ; 50 mm : repli grossier).

use em_core::q16::atan2_turns;
use em_core::{Q16, VoxelValue};

use super::builder::{PropBuilder, ton3};
use super::tex::Tex;
use crate::batiments::kit::matieres::{Ton, bois, ton, val};
use crate::batiments::kit::prims::Cell;
use crate::batiments::kit::rng::{hh, hh_below};

fn secteur(x: i32, z: i32) -> i32 {
    let a = atan2_turns(
        Q16::from_raw(i64::from(z) * 1000 + 1),
        Q16::from_raw(i64::from(x) * 1000 + 1),
    )
    .raw();
    ((a * 6283 / 65_536 + 3200) * 32 / 10_000) as i32
}

impl PropBuilder {
    /// Tonneau cerclé de fer, parfois ouvert (eau) ou couvert d'un couvercle.
    pub fn tonneau(&mut self) {
        let m = self.m;
        let h = 12 + self.pick(1, 4) as i32;
        let ouvert = self.pick(2, 3) == 0;
        self.rule([-7, 0, -7], [8, h, 8], move |x, y, z| {
            let bl = 640 - 130 * (2 * y - h + 1) * (2 * y - h + 1) / (h * h);
            let r2 = 10_000 * (x * x + z * z);
            if r2 > bl * bl {
                return Cell::Keep;
            }
            let haut = y == h - 1;
            if ouvert && y >= h - 2 {
                if r2 > (bl - 120) * (bl - 120) {
                    return Cell::Put(bois(m.oak_raw, 1, 8));
                }
                return if y == h - 2 {
                    Cell::Put(val(m.paint_blue, 70 + (hh(x, y, z, 1) % 20) as u8))
                } else {
                    Cell::Air
                };
            }
            if haut {
                return Cell::Put(if r2 > (bl - 120) * (bl - 120) {
                    bois(m.oak_raw, 1, 9)
                } else {
                    bois(m.timber, 3, 3)
                });
            }
            if y == 3 || y == h - 4 {
                return Cell::Put(val(m.iron, 28 + (hh(x, y, z, 2) % 20) as u8));
            }
            Cell::Put(bois(
                m.oak_raw,
                1,
                3 + (hh(secteur(x, z), y >> 2, 1, 3) % 10) as u8,
            ))
        });
    }

    /// Caisse de planches cerclée de lattes, seule ou empilée.
    pub fn caisse(&mut self) {
        let m = self.m;
        let haute = self.pick(1, 3);
        let caisse = move |ox: i32, oy: i32, oz: i32, s: i32| {
            move |x: i32, y: i32, z: i32| {
                let (a, b, c) = (x - ox, y - oy, z - oz);
                let bord = (a < 2 || a >= s - 2) as i32
                    + (b < 2 || b >= s - 2) as i32
                    + (c < 2 || c >= s - 2) as i32;
                if bord >= 2 {
                    Cell::Put(bois(
                        m.timber,
                        if a < 2 || a >= s - 2 { 1 } else { 0 },
                        4 + (hh(x, y, z, 4) % 6) as u8,
                    ))
                } else {
                    Cell::Put(val(m.oak_planks, 40 + (hh(x, y, z, 5) % 30) as u8))
                }
            }
        };
        self.rule([-5, 0, -5], [5, 10, 5], caisse(-5, 0, -5, 10));
        if haute > 0 {
            self.rule([-4, 10, -4], [4, 18, 4], caisse(-4, 10, -4, 8));
        }
        if haute > 1 {
            self.rule([2, 0, 3], [10, 8, 11], caisse(2, 0, 3, 8));
        }
    }

    /// Tas de sacs de toile, noués par le haut.
    pub fn sacs(&mut self) {
        let n = 3 + self.pick(1, 4) as i32;
        let spots = [
            (-4, 0, 0),
            (3, 0, 1),
            (-1, 0, 6),
            (-2, 5, 2),
            (5, 0, -5),
            (-7, 0, -4),
            (1, 5, 4),
        ];
        for (i, (x, y, z)) in spots.iter().take(n as usize).enumerate() {
            let t = Tex::Ramp(self.m.cloth, 52 + (hh(i as i32, 0, 0, 3) % 24) as u8, 12);
            self.ball([100 * x + 50, 100 * y + 150, 100 * z + 50], [330, 270, 280], t);
            self.ball(
                [100 * x + 50, 100 * y + 300, 100 * z + 50],
                [110, 80, 110],
                Tex::Ramp(self.m.leather, 40, 10),
            );
        }
    }

    /// Roue à rayons, dans le plan (y, z) à l'abscisse `x`, de rayon `r` voxels et de centre (cy, cz).
    fn roue(&mut self, x: i32, cy: i32, cz: i32, r: i32) {
        let m = self.m;
        self.rule(
            [x, cy - r - 1, cz - r - 1],
            [x + 2, cy + r + 2, cz + r + 2],
            move |_, y, z| {
                let (dy, dz) = (y - cy, z - cz);
                let d2 = 100 * (dy * dy + dz * dz);
                let rr = 100 * r * r;
                if d2 > rr {
                    return Cell::Keep;
                }
                let jante = d2 >= 100 * (r - 2) * (r - 2);
                let moyeu = d2 <= 100 * 5;
                let rayon = dy == 0 || dz == 0 || (dy - dz).abs() <= 0 || (dy + dz).abs() <= 0;
                if jante {
                    Cell::Put(bois(m.timber, 3, 2 + (hh(y, z, 0, 1) % 6) as u8))
                } else if moyeu {
                    Cell::Put(val(m.iron, 30))
                } else if rayon {
                    Cell::Put(bois(m.oak_raw, 2, 6))
                } else {
                    Cell::Keep
                }
            },
        );
    }

    /// Charrette à bras : plateau, ridelles, deux roues, brancards, chargement.
    pub fn charrette(&mut self) {
        let m = self.m;
        self.bx((-12, 12), (8, 10), (-8, 8), Tex::Planks);
        for z in [-8, 7] {
            self.bx((-12, 12), (10, 15), (z, z + 1), Tex::Oak(0));
        }
        self.bx((-12, -11), (10, 15), (-8, 8), Tex::Oak(2));
        self.bx((-12, 12), (6, 8), (-6, -4), Tex::Timber(0));
        self.bx((-12, 12), (6, 8), (3, 5), Tex::Timber(0));
        self.bx((-1, 1), (8, 9), (-11, 11), Tex::Flat(val(m.iron, 40)));
        self.roue(-1, 9, -10, 9);
        self.roue(-1, 9, 10, 9);
        // brancards : deux perches qui descendent vers l'avant (x croissant)
        for z in [-5, 4] {
            self.bar([12, 9, z], [32, 6, z], 1, Tex::Oak(0));
        }
        self.bx((30, 33), (5, 7), (-5, 5), Tex::Oak(2));
        match self.pick(3, 3) {
            0 => self.ball([-250, 1150, 0], [900, 450, 650], Tex::Ramp(m.hay, 55, 40)),
            1 => {
                self.ball([-450, 1450, -300], [330, 400, 330], Tex::Oak(1));
                self.bx((-10, -2), (10, 17), (-6, 0), Tex::Oak(0));
                self.bx((2, 9), (10, 15), (1, 7), Tex::Timber(0));
            }
            _ => {}
        }
    }

    /// Étal de marché : comptoir, auvent rayé, auvent incliné, étagère de produits.
    pub fn etal(&mut self) {
        let m = self.m;
        let (a, b) = match self.pick(1, 3) {
            0 => (ton3(m.fabric_a, 0), ton3(m.fabric_b, 2)),
            1 => (ton3(m.fabric_a, 1), ton3(m.fabric_b, 2)),
            _ => (ton3(m.fabric_a, 2), ton3(m.fabric_b, 1)),
        };
        self.bx((-16, 16), (14, 16), (-8, 7), Tex::Planks);
        self.bx((-16, 16), (0, 14), (4, 6), Tex::Oak(0));
        self.bx((-16, 16), (0, 14), (-8, -6), Tex::Timber(0));
        for (x, z) in [(-16, -8), (14, -8), (-16, 5), (14, 5)] {
            self.bx(
                (x, x + 2),
                (0, if z < 0 { 38 } else { 32 }),
                (z, z + 2),
                Tex::Timber(1),
            );
        }
        // auvent : plan incliné rayé de l'arrière (38) vers l'avant (32)
        self.rule([-18, 30, -10], [18, 40, 9], move |x, y, z| {
            let t = 38 - (z + 10) * 6 / 19;
            if y == t || y == t - 1 {
                Cell::Put(if (x + 40).div_euclid(4) % 2 == 0 { a } else { b })
            } else {
                Cell::Keep
            }
        });
        // pendentif de l'auvent
        self.rule([-18, 24, 7], [18, 33, 10], move |x, y, z| {
            let _ = z;
            let onde = (x + 40).rem_euclid(4) < 2;
            if y >= 31 - i32::from(onde) * 2 && y < 33 {
                Cell::Put(if (x + 40).div_euclid(4) % 2 == 0 { a } else { b })
            } else {
                Cell::Keep
            }
        });
        // produits : paniers de fruits et pains
        for i in 0..4 {
            let x = -13 + 7 * i;
            self.bx((x, x + 5), (16, 18), (-3, 3), Tex::Trim(0));
            let c = match self.pick(10 + i, 4) {
                0 => ton3(m.flower_b, 1),
                1 => ton3(m.flower_a, 1),
                2 => ton3(m.paint_green, 2),
                _ => ton3(m.hay, 1),
            };
            self.ball(
                [100 * x + 250, 1800, 0],
                [220, 120, 250],
                Tex::Ramp(c.material(), c.tint(), 8),
            );
        }
    }

    /// Banc de planches, avec ou sans dossier.
    pub fn banc(&mut self) {
        self.bx((-14, 14), (8, 10), (-3, 4), Tex::Planks);
        for x in [-12, 10] {
            self.bx((x, x + 2), (0, 8), (-2, 3), Tex::Timber(1));
        }
        self.bx((-12, 12), (4, 6), (-1, 1), Tex::Timber(0));
        if self.pick(1, 2) == 0 {
            self.bx((-14, 14), (13, 15), (-3, -1), Tex::Planks);
            self.bx((-14, 14), (17, 19), (-3, -1), Tex::Planks);
            for x in [-13, 11] {
                self.bx((x, x + 2), (10, 19), (-3, -1), Tex::Timber(1));
            }
        }
    }

    /// Table de planches sur quatre pieds, avec une nappe ou un chemin de table.
    pub fn table(&mut self) {
        let longue = self.pick(1, 2) == 0;
        let l = if longue { 28 } else { 18 };
        self.bx((-l, l), (13, 15), (-9, 9), Tex::Planks);
        for (x, z) in [(-l + 2, -7), (l - 4, -7), (-l + 2, 6), (l - 4, 6)] {
            self.bx((x, x + 2), (0, 13), (z, z + 2), Tex::Timber(1));
        }
        self.bx((-l + 3, l - 3), (9, 10), (-1, 1), Tex::Timber(0));
        if self.pick(2, 2) == 0 {
            let c = ton3(self.m.fabric_a, 0);
            self.bx((-8, 8), (15, 16), (-6, 6), Tex::Flat(c));
        }
    }

    /// Chaise à dossier.
    pub fn chaise(&mut self) {
        self.bx((-4, 4), (8, 9), (-4, 4), Tex::Planks);
        for (x, z) in [(-4, -4), (2, -4), (-4, 2), (2, 2)] {
            self.bx((x, x + 2), (0, 8), (z, z + 2), Tex::Timber(1));
        }
        for x in [-4, 2] {
            self.bx((x, x + 2), (9, 19), (-4, -2), Tex::Timber(1));
        }
        self.bx((-2, 2), (14, 17), (-4, -3), Tex::Planks);
    }

    fn longueur(&self) -> i32 {
        24 + 8 * self.pick(77, 4) as i32
    }

    /// Clôture de bois : poteaux, deux lisses, piquets à pointe.
    pub fn cloture_bois(&mut self) {
        let l = self.longueur();
        let piquets = self.pick(1, 2) == 0;
        let mut x = -l;
        while x <= l {
            self.bx(
                (x - 1, x + 1),
                (0, 16 + (hh(x, 0, 0, 5) % 3) as i32),
                (-1, 1),
                Tex::Oak(1),
            );
            x += 12;
        }
        for y in [6, 11] {
            self.bx((-l, l + 1), (y, y + 2), (1, 2), Tex::Oak(0));
        }
        if piquets {
            let mut x = -l + 3;
            while x < l {
                let h = 13 + (hh(x, 1, 0, 5) % 3) as i32;
                self.bx((x, x + 2), (2, h), (-2, -1), Tex::Planks);
                self.bx((x, x + 1), (h, h + 1), (-2, -1), Tex::Planks);
                x += 4;
            }
        }
    }

    /// Mur de pierre sèche : profil irrégulier, blocs, mousse sur le dessus.
    pub fn cloture_pierre(&mut self) {
        let m = self.m;
        let l = self.longueur();
        let c = if self.pick(1, 2) == 0 {
            m.rubble
        } else {
            m.stone_grey
        };
        self.rule([-l, 0, -4], [l + 1, 13, 4], move |x, y, z| {
            let haut = 9 + (hh(x.div_euclid(3), 0, 0, 5) % 4) as i32;
            let largeur = 3 + i32::from(y < 4);
            if y >= haut || z.abs() >= largeur + 1 - i32::from(y > 7) {
                return Cell::Keep;
            }
            if y == haut - 1 && hh(x, z, 0, 6) % 100 < 45 {
                return Cell::Put(val(m.moss, 50 + (hh(x, y, z, 7) % 50) as u8));
            }
            Cell::Put(Tex::Block(c, 3).at(&m, x, y, z))
        });
    }

    /// Treillis de lattes avec une plante grimpante.
    pub fn treillis(&mut self) {
        let m = self.m;
        let fleurs = self.pick(1, 2) == 0;
        for x in [-12, 11] {
            self.bx((x, x + 2), (0, 32), (-1, 1), Tex::Oak(1));
        }
        self.rule([-12, 2, -1], [13, 34, 1], move |x, y, z| {
            let diag = (x + y).rem_euclid(5) == 0 || (x - y).rem_euclid(5) == 0;
            if z != 0 || !diag {
                return Cell::Keep;
            }
            Cell::Put(bois(m.timber, 0, 6))
        });
        self.rule([-12, 2, -2], [13, 34, 2], move |x, y, z| {
            let n = crate::batiments::kit::noise::vnoise2(x * 3, y * 3, 12, 8);
            if n > 28_000 && z.abs() == 1 && hh(x, y, z, 9) % 100 < 70 {
                if fleurs && hh(x, y, z, 10) % 100 < 12 {
                    return Cell::Put(ton(
                        m.flower_a,
                        [Ton::Sombre, Ton::Moyen, Ton::Clair][(hh(x, y, 0, 11) % 3) as usize],
                    ));
                }
                Cell::Put(val(m.moss, 45 + (hh(x, y, z, 12) % 60) as u8))
            } else {
                Cell::Keep
            }
        });
    }

    /// Portail : deux piliers de pierre, deux vantaux à croix de Saint-André.
    pub fn portail(&mut self) {
        let m = self.m;
        for x in [-16, 13] {
            self.bx((x, x + 4), (0, 32), (-2, 2), Tex::Stone(m.stone_grey));
            self.bx((x - 1, x + 5), (32, 34), (-3, 3), Tex::Stone(m.stone_grey));
        }
        for v in [(-12, -1), (0, 12)] {
            let (a, b) = v;
            self.bx((a, b + 1), (3, 5), (0, 1), Tex::Oak(0));
            self.bx((a, b + 1), (22, 24), (0, 1), Tex::Oak(0));
            self.bx((a, a + 1), (3, 24), (0, 1), Tex::Oak(1));
            self.bx((b, b + 1), (3, 24), (0, 1), Tex::Oak(1));
            self.bar([a, 4, 0], [b, 23, 0], 0, Tex::Oak(0));
            for x in (a + 2..b).step_by(2) {
                self.bx((x, x + 1), (5, 22), (-1, 0), Tex::Planks);
            }
        }
        self.bx((-1, 1), (3, 24), (-1, 1), Tex::Flat(val(m.iron, 40)));
    }

    /// Enseigne suspendue : potence de fer, planche, emblème selon la variante (chope, enclume, pain, clé).
    pub fn enseigne(&mut self) {
        let m = self.m;
        let v = self.pick(1, 4);
        self.bx((-2, 2), (0, 44), (-2, 2), Tex::Oak(1));
        self.bar([2, 40, 0], [20, 40, 0], 0, Tex::Flat(val(m.iron, 30)));
        self.bar([2, 33, 0], [14, 40, 0], 0, Tex::Flat(val(m.iron, 30)));
        for x in [4, 17] {
            self.bx((x, x + 1), (30, 40), (0, 1), Tex::Flat(val(m.iron, 60)));
        }
        let fond = [
            ton3(m.paint_blue, 1),
            ton3(m.paint_green, 1),
            ton3(m.fabric_b, 0),
            ton3(m.paint_red, 1),
        ][v as usize];
        self.bx((2, 20), (22, 31), (0, 2), Tex::Planks);
        self.bx((3, 19), (23, 30), (-1, 0), Tex::Flat(fond));
        let motif = [
            ton3(m.fabric_b, 2),
            val(m.iron, 90),
            ton3(m.hay, 1),
            ton3(m.brass, 1),
        ][v as usize];
        self.rule([3, 23, -2], [19, 30, 0], move |x, y, z| {
            let (a, b) = (x - 3, y - 23);
            let ok = match v {
                0 => (a >= 5 && a < 10 && b >= 1 && b < 6) || (a >= 10 && a < 12 && b >= 2 && b < 5),
                1 => (a >= 3 && a < 13 && b >= 4 && b < 6) || (a >= 6 && a < 10 && b >= 1 && b < 4),
                2 => (a - 8) * (a - 8) / 3 + (b - 3) * (b - 3) <= 4,
                _ => (a >= 3 && a < 6 && b >= 2 && b < 5) || (a >= 6 && a < 13 && b == 3),
            };
            if ok && z == -1 {
                Cell::Put(motif)
            } else {
                Cell::Keep
            }
        });
    }

    /// Lampadaire de village : poteau, bras de fer, lanterne à flamme.
    pub fn lanterne(&mut self) {
        let m = self.m;
        self.bx((-1, 1), (0, 46), (-1, 1), Tex::Oak(1));
        self.bx((-2, 2), (0, 4), (-2, 2), Tex::Stone(m.stone_grey));
        self.bar([0, 44, 0], [7, 44, 0], 0, Tex::Flat(val(m.iron, 30)));
        self.bar([0, 36, 0], [6, 43, 0], 0, Tex::Flat(val(m.iron, 30)));
        self.rule([4, 34, -2], [10, 44, 3], move |x, y, z| {
            let (a, b, c) = (x - 4, y - 34, z + 2);
            let bord = (a == 0 || a == 5) && (c == 0 || c == 4);
            let cap = b == 0 || b == 9 || b == 8;
            if cap || bord {
                Cell::Put(val(m.iron, 30 + (hh(x, y, z, 1) % 12) as u8))
            } else if b < 8 && a > 0 && a < 5 && c > 0 && c < 4 {
                Cell::Put(ton(m.glow, Ton::Moyen))
            } else {
                Cell::Keep
            }
        });
    }

    /// Tas de foin ou meule : monticule d'herbe sèche hérissé de brins, ou botte liée.
    pub fn foin(&mut self) {
        let m = self.m;
        if self.pick(1, 3) == 0 {
            self.bx((-8, 8), (0, 9), (-5, 5), Tex::Ramp(m.hay, 50, 40));
            for x in [-5, 0, 5] {
                self.bx((x, x + 1), (0, 9), (-6, 6), Tex::Ramp(m.leather, 30, 10));
            }
            self.bx((-8, 8), (9, 10), (-4, 4), Tex::Ramp(m.hay, 70, 40));
            return;
        }
        self.ball([0, 600, 0], [1300, 950, 1100], Tex::Ramp(m.hay, 45, 55));
        self.rule([-14, 0, -12], [15, 18, 13], move |x, y, z| {
            let h = hh(x, y, z, 3);
            let r2 =
                i64::from(x * x) * 100 / 170 + i64::from(y * y) * 100 / 90 + i64::from(z * z) * 100 / 125;
            if r2 > 95 && r2 < 112 && h % 100 < 22 {
                Cell::Put(val(m.hay, 90 + (h % 30) as u8))
            } else {
                Cell::Keep
            }
        });
    }

    /// Tas de bois : bûches rangées en pyramide, bouts visibles ; billot et hache en variante.
    pub fn tas_bois(&mut self) {
        let m = self.m;
        let long = 14 + 2 * self.pick(1, 3) as i32;
        self.rule([-14, 0, -long], [15, 16, long + 1], move |x, y, z| {
            // rangées de rondins de 5 voxels : 5, 4, 3 rondins
            let rangee = y / 5;
            let n = 5 - rangee;
            if rangee > 2 {
                return Cell::Keep;
            }
            let (cy100, _) = (rangee * 500 + 250, 0);
            let ofs = rangee * 250;
            let i = (100 * x + 50 + 1250 - ofs).div_euclid(500);
            if i < 0 || i >= n {
                return Cell::Keep;
            }
            let cx100 = i * 500 + 250 - 1250 + ofs;
            let (dx, dy) = (100 * x + 50 - cx100, 100 * y + 50 - cy100);
            if dx * dx + dy * dy > 245 * 245 {
                return Cell::Keep;
            }
            if z == long - 1 || z == -long + 1 {
                let r2 = dx * dx + dy * dy;
                let c = if r2 < 80 * 80 {
                    105
                } else if r2 < 160 * 160 {
                    70
                } else {
                    40
                };
                return Cell::Put(val(m.oak_planks, c + (hh(x, y, z, 2) % 8) as u8));
            }
            Cell::Put(bois(m.oak_raw, 2, (hh(i, rangee, 0, 4) % 9) as u8 + 2))
        });
        if self.pick(2, 2) == 0 {
            self.cyl(2200, 0, 450, (0, 9), Tex::Oak(1));
            self.bar([22, 9, -1], [22, 17, 3], 0, Tex::Oak(1));
            self.bx((20, 25), (9, 10), (-1, 1), Tex::Flat(val(m.iron, 90)));
        }
    }

    /// Feu de camp : couronne de pierres, bûches en étoile, braises et flammes.
    pub fn feu_camp(&mut self) {
        let m = self.m;
        self.ring(0, 0, 780, 520, (0, 4), Tex::Stone(m.stone_grey));
        self.rule([-8, 0, -8], [9, 4, 9], move |x, y, z| {
            let r2 = 10_000 * (x * x + z * z);
            if r2 < 520 * 520 && y < 2 {
                Cell::Put(val(m.coal, 8 + (hh(x, y, z, 1) % 14) as u8))
            } else {
                Cell::Keep
            }
        });
        for k in 0..5 {
            let a = k * 13_107; // tours Q16
            let (c, s) = (
                crate::batiments::kit::intmath::cos100(a),
                crate::batiments::kit::intmath::sin100(a),
            );
            self.bar([0, 3, 0], [c * 5 / 100, 6, s * 5 / 100], 0, Tex::Oak(0));
            self.bar(
                [c * 5 / 100, 3, s * 5 / 100],
                [c * 7 / 100, 2, s * 7 / 100],
                0,
                Tex::Oak(0),
            );
        }
        self.rule([-4, 1, -4], [5, 12, 5], move |x, y, z| {
            let r = x * x + z * z;
            let h = 3 + (hh(x, z, 0, 8) % 6) as i32;
            if r <= 7 && y >= 2 && y < 2 + h && hh(x, y, z, 9) % 100 < (80 - 5 * y) as u32 {
                let t = if y < 4 {
                    Ton::Sombre
                } else if y < 6 {
                    Ton::Moyen
                } else {
                    Ton::Clair
                };
                Cell::Put(ton(if y < 4 { m.ember } else { m.glow }, t))
            } else {
                Cell::Keep
            }
        });
    }

    /// Tombe : tertre, stèle à sommet arrondi ou croix, mousse et fleurs.
    pub fn tombe(&mut self) {
        let m = self.m;
        let croix = self.pick(1, 2) == 0;
        self.ball([0, 0, 600], [550, 150, 1000], Tex::Ramp(m.turf, 40, 30));
        if croix {
            self.bx((-1, 1), (0, 22), (-2, 0), Tex::Block(m.stone_grey, 4));
            self.bx((-5, 5), (13, 16), (-2, 0), Tex::Block(m.stone_grey, 4));
        } else {
            self.rule([-6, 0, -3], [7, 24, 1], move |x, y, z| {
                let haut = 20 + 3 - (x * x * 3 / 20).min(3) - i32::from(x.abs() > 4) * 2;
                if y >= haut || z > -1 + i32::from(y < 2) {
                    return Cell::Keep;
                }
                if y < 4 && hh(x, y, z, 5) % 100 < 40 {
                    Cell::Put(val(m.moss, 50 + (hh(x, y, z, 6) % 40) as u8))
                } else {
                    Cell::Put(Tex::Block(m.stone_grey, 4).at(&m, x, y, z))
                }
            });
        }
        for k in 0..6 {
            let (x, z) = (hh(k, 1, 2, 3) as i32 % 9 - 4, 3 + (hh(k, 2, 2, 3) as i32 % 6));
            self.bx(
                (x, x + 1),
                (1, 2),
                (z, z + 1),
                Tex::Flat(ton(
                    m.flower_a,
                    [Ton::Sombre, Ton::Moyen, Ton::Clair][k as usize % 3],
                )),
            );
        }
    }

    /// Panneau indicateur : poteau et deux planches fléchées.
    pub fn panneau(&mut self) {
        let m = self.m;
        self.bx((-1, 1), (0, 40), (-1, 1), Tex::Oak(1));
        for (k, (y, sens)) in [(32, 1), (24, -1)].into_iter().enumerate() {
            let l = 12 + (hh(k as i32, 0, 0, 1) % 3) as i32;
            self.rule([-l - 2, y, -2], [l + 3, y + 6, 2], move |x, yy, z| {
                if z != 0 {
                    return Cell::Keep;
                }
                let pointe = if sens > 0 { x - l } else { -l - x };
                let (a, b) = (pointe, (yy - y) * 2 - 5);
                if x.abs() <= l && a <= 0 || (a > 0 && a <= 3 && b.abs() <= 6 - 2 * a) {
                    Cell::Put(Tex::Planks.at(&m, x, yy, z))
                } else {
                    Cell::Keep
                }
            });
        }
    }

    /// Puits de décor : margelle de pierre, deux montants, petit toit de bardeaux, seau.
    pub fn puits_deco(&mut self) {
        let m = self.m;
        self.ring(0, 0, 1000, 650, (0, 9), Tex::Stone(m.stone_grey));
        self.cyl(0, 0, 650, (0, 3), Tex::Flat(val(m.paint_blue, 40)));
        self.cyl(0, 0, 650, (3, 5), Tex::Flat(val(m.paint_blue, 70)));
        for x in [-10, 8] {
            self.bx((x, x + 2), (9, 34), (-1, 1), Tex::Oak(1));
        }
        self.bx((-10, 10), (30, 32), (-1, 1), Tex::Oak(0));
        // toit à deux pans
        self.rule([-13, 32, -8], [14, 44, 9], move |x, y, z| {
            let h = 41 - z.abs() * 6 / 8 - 0;
            let _ = x;
            if y == h || y == h - 1 {
                Cell::Put(val(m.leather, 30 + (hh(x, y, z, 3) % 30) as u8))
            } else {
                Cell::Keep
            }
        });
        self.bar([0, 31, 0], [0, 21, 0], 0, Tex::Flat(val(m.cloth, 70)));
        self.cyl(0, 0, 180, (19, 22), Tex::Oak(1));
    }

    /// Échelle de bois : deux montants, barreaux tous les 4 voxels.
    pub fn echelle(&mut self) {
        let h = 44 + 6 * self.pick(1, 3) as i32;
        for x in [-4, 3] {
            self.bx((x, x + 2), (0, h), (-1, 1), Tex::Oak(1));
        }
        let mut y = 3;
        while y < h - 2 {
            self.bx((-4, 5), (y, y + 1), (-1, 1), Tex::Timber(0));
            y += 4;
        }
    }

    /// Râtelier d'armes : cadre, lances et épées appuyées, écu.
    pub fn ratelier(&mut self) {
        let m = self.m;
        for x in [-14, 12] {
            self.bx((x, x + 2), (0, 26), (-2, 2), Tex::Oak(1));
        }
        for y in [8, 17] {
            self.bx((-14, 14), (y, y + 2), (-2, 0), Tex::Oak(0));
        }
        for (k, x) in (-11..11).step_by(4).enumerate() {
            let long = 36 + (hh(k as i32, 0, 0, 2) % 8) as i32;
            self.bx((x, x + 1), (2, long), (-1, 0), Tex::Oak(1));
            self.bx((x, x + 1), (long, long + 3), (-1, 0), Tex::Flat(val(m.iron, 100)));
        }
        let a = ton3(m.fabric_a, (self.pick(5, 3)) as u8);
        self.rule([8, 10, -3], [14, 20, -1], move |x, y, z| {
            let (dx, dy) = (100 * (x - 11) + 50, 100 * (y - 15) + 50);
            if z == -2 && dx * dx + dy * dy < 480 * 480 {
                Cell::Put(if dx * dx + dy * dy > 380 * 380 {
                    val(m.iron, 40)
                } else {
                    a
                })
            } else {
                Cell::Keep
            }
        });
    }

    /// Ruche paille (cloche de rangs superposés) ou ruche de bois sur pieds, avec trou de vol.
    pub fn ruche(&mut self) {
        let m = self.m;
        let u = self.unit;
        let paille = self.pick(1, 2) == 0;
        if paille {
            // cloche de 120 mm de rayon, 190 mm de haut, rangs de 18 mm
            let (r, h) = (self.mm(120) * 100, self.mm(190));
            self.rule(
                [-self.mm(130), 0, -self.mm(130)],
                [self.mm(130) + 1, h + 2, self.mm(130) + 1],
                move |x, y, z| {
                    let t = 100 * y / h.max(1);
                    let rr = r * (100 - (t * t) / 100 * 100 / 100).max(0) / 100;
                    let rr = rr.max(0);
                    let r2 = 10_000 * (x * x + z * z);
                    if r2 > i64::from(rr).pow(2) as i32 && false {
                        return Cell::Keep;
                    }
                    if i64::from(r2) > i64::from(rr) * i64::from(rr) {
                        return Cell::Keep;
                    }
                    let rang = (y * u).div_euclid(18);
                    let trou = z > 0 && x.abs() * u < 25 && y * u > 10 && y * u < 36;
                    if trou {
                        return Cell::Air;
                    }
                    let ton_ = if (rang + (x * u).div_euclid(30)) % 2 == 0 {
                        60
                    } else {
                        85
                    };
                    Cell::Put(val(m.hay, ton_ + (hh(x, y, z, 1) % 12) as u8))
                },
            );
            self.cyl(0, 0, self.mm(40) * 100, (h, h + 1), Tex::Ramp(m.hay, 40, 10));
        } else {
            let (w, d, h) = (self.mm(260), self.mm(300), self.mm(260));
            let pied = self.mm(260);
            for (x, z) in [
                (-w / 2, -d / 2),
                (w / 2 - 2, -d / 2),
                (-w / 2, d / 2 - 2),
                (w / 2 - 2, d / 2 - 2),
            ] {
                self.bx((x, x + 2), (0, pied), (z, z + 2), Tex::Timber(1));
            }
            self.bx((-w / 2, w / 2), (pied, pied + 1), (-d / 2, d / 2), Tex::Planks);
            self.rule(
                [-w / 2, pied + 1, -d / 2],
                [w / 2, pied + 1 + h, d / 2],
                move |x, y, z| {
                    let trou = z >= d / 2 - 1 && x.abs() < 3 && y == pied + 2;
                    if trou {
                        return Cell::Air;
                    }
                    Cell::Put(if y % 4 == 0 {
                        Tex::Timber(0).at(&m, x, y, z)
                    } else {
                        Tex::Planks.at(&m, x, y, z)
                    })
                },
            );
            self.rule(
                [-w / 2 - 1, pied + 1 + h, -d / 2 - 1],
                [w / 2 + 1, pied + 4 + h, d / 2 + 1],
                move |x, y, z| {
                    let _ = (x, z);
                    if y < pied + 2 + h {
                        Cell::Put(Tex::Oak(0).at(&m, x, y, z))
                    } else {
                        Cell::Put(val(m.leather, 35))
                    }
                },
            );
        }
    }

    // ---- petits objets : cotes en millimètres ----

    /// Bougie sur un chandelier de laiton.
    pub fn bougie(&mut self) {
        let m = self.m;
        let (r, h) = (self.mm(11), self.mm(62));
        let base = self.mm(6);
        self.cyl(
            0,
            0,
            self.mm(32) * 100,
            (0, base.max(1)),
            Tex::Ramp(m.brass, 50, 30),
        );
        self.cyl(0, 0, r * 100, (base.max(1), base + h), Tex::Ramp(m.wax, 80, 40));
        let f = self.mm(24).max(2);
        self.bx(
            (0, 1),
            (base + h, base + h + 1),
            (0, 1),
            Tex::Flat(val(m.coal, 10)),
        );
        self.rule(
            [-1, base + h + 1, -1],
            [2, base + h + 1 + f, 2],
            move |x, y, z| {
                let k = y - (base + h + 1);
                if (x == 0 && z == 0)
                    || (k < f / 2 && x.abs() + z.abs() <= 1 && hh(x, y, z, 1).is_multiple_of(3))
                {
                    Cell::Put(ton(m.glow, if k < f / 3 { Ton::Moyen } else { Ton::Clair }))
                } else {
                    Cell::Keep
                }
            },
        );
    }

    /// Vaisselle : assiette, écuelle et chope de terre cuite.
    pub fn vaisselle(&mut self) {
        let m = self.m;
        let (e, h) = (self.mm(8).max(1), self.mm(70));
        self.cyl(
            -self.mm(70) * 100,
            0,
            self.mm(70) * 100,
            (0, e),
            Tex::Ramp(m.plaster, 108, 14),
        );
        self.ring(
            -self.mm(70) * 100,
            0,
            self.mm(74) * 100,
            self.mm(52) * 100,
            (e, e + 1),
            Tex::Ramp(m.plaster, 100, 14),
        );
        self.ring(
            self.mm(60) * 100,
            -self.mm(20) * 100,
            self.mm(55) * 100,
            self.mm(43) * 100,
            (0, self.mm(55)),
            Tex::Ramp(m.ceramic, 50, 20),
        );
        self.cyl(
            self.mm(60) * 100,
            -self.mm(20) * 100,
            self.mm(43) * 100,
            (0, 1),
            Tex::Ramp(m.ceramic, 50, 20),
        );
        self.ring(
            self.mm(30) * 100,
            self.mm(70) * 100,
            self.mm(30) * 100,
            self.mm(22) * 100,
            (0, h),
            Tex::Ramp(m.ceramic, 70, 25),
        );
        self.cyl(
            self.mm(30) * 100,
            self.mm(70) * 100,
            self.mm(30) * 100,
            (0, 1),
            Tex::Ramp(m.ceramic, 70, 25),
        );
        self.bx(
            (self.mm(54), self.mm(66)),
            (self.mm(18), h - self.mm(14)),
            (self.mm(66), self.mm(76)),
            Tex::Ramp(m.ceramic, 60, 20),
        );
    }

    /// Miche de pain : ellipsoïde dorée, entailles claires.
    pub fn pain(&mut self) {
        let m = self.m;
        let (a, b, c) = (self.mm(95) * 100, self.mm(45) * 100, self.mm(55) * 100);
        let u = self.unit;
        self.ball([0, b, 0], [a, b, c], Tex::Ramp(m.hay, 38, 18));
        self.rule(
            [-self.mm(100), 0, -self.mm(60)],
            [self.mm(100), self.mm(95), self.mm(60)],
            move |x, y, z| {
                let entaille = ((x * u + 400).rem_euclid(34) < 7) && z.abs() * u < 30 && y * u > 70;
                if entaille && in_top(x, y, z, a, b, c) {
                    Cell::Put(val(m.hay, 95 + (hh(x, y, z, 1) % 12) as u8))
                } else {
                    Cell::Keep
                }
            },
        );
    }

    /// Corbeille de fruits : osier et pommes rouges, vertes et jaunes.
    pub fn fruits(&mut self) {
        let m = self.m;
        let (r, h) = (self.mm(85) * 100, self.mm(60));
        self.ring(0, 0, r, r - self.mm(14) * 100, (0, h), Tex::Ramp(m.hay, 30, 20));
        self.cyl(0, 0, r, (0, 1), Tex::Ramp(m.hay, 25, 15));
        let pommes = [
            (-45, -20),
            (30, -40),
            (45, 25),
            (-25, 45),
            (5, 5),
            (-60, 20),
            (20, 55),
        ];
        for (i, (dx, dz)) in pommes.iter().enumerate() {
            let c = [
                ton3(m.flower_b, 1),
                ton3(m.paint_green, 2),
                ton3(m.flower_a, 1),
                ton3(m.flower_b, 1),
            ][i % 4];
            let (cx, cz, rr) = (self.mm(*dx) * 100, self.mm(*dz) * 100, self.mm(17) * 100);
            self.ball(
                [cx + 50, self.mm(40) * 100 + (i as i32 % 2) * 100, cz + 50],
                [rr, rr, rr],
                Tex::Ramp(c.material(), c.tint(), 6),
            );
        }
    }

    /// Livre fermé, cuir ou toile, tranche claire ; un second posé dessus selon la variante.
    pub fn livre(&mut self) {
        let m = self.m;
        let c = [
            ton3(m.fabric_a, 0),
            ton3(m.fabric_a, 1),
            ton3(m.fabric_a, 2),
            ton3(m.fabric_b, 1),
        ][self.pick(1, 4) as usize];
        let (w, d, e) = (self.mm(95), self.mm(130), self.mm(24));
        self.bx((0, w), (0, e), (0, d), Tex::Flat(val(m.wax, 100)));
        self.bx((0, w), (0, 1), (0, d), Tex::Ramp(c.material(), c.tint(), 3));
        self.bx((0, w), (e - 1, e), (0, d), Tex::Ramp(c.material(), c.tint(), 3));
        self.bx((0, 1), (0, e), (0, d), Tex::Ramp(c.material(), c.tint(), 3));
        if self.pick(2, 2) == 0 {
            let c2 = ton3(m.fabric_b, 1);
            self.bx(
                (1, w - 1),
                (e, e + e / 2 + 1),
                (1, d - 1),
                Tex::Ramp(c2.material(), c2.tint(), 3),
            );
        }
    }

    /// Clé de fer : anneau, tige, panneton.
    pub fn cle(&mut self) {
        let m = self.m;
        let t = self.mm(8).max(1);
        self.ring(
            0,
            0,
            self.mm(22) * 100,
            self.mm(12) * 100,
            (0, t),
            Tex::Ramp(m.iron, 40, 20),
        );
        self.bx(
            (self.mm(20), self.mm(100)),
            (0, t),
            (-t / 2, t - t / 2),
            Tex::Ramp(m.iron, 40, 20),
        );
        self.bx(
            (self.mm(88), self.mm(100)),
            (0, t),
            (self.mm(8), self.mm(30)),
            Tex::Ramp(m.iron, 40, 20),
        );
        self.bx(
            (self.mm(76), self.mm(84)),
            (0, t),
            (self.mm(8), self.mm(22)),
            Tex::Ramp(m.iron, 40, 20),
        );
    }

    /// Outils à main : marteau et tenailles.
    pub fn outils(&mut self) {
        let m = self.m;
        let t = self.mm(12).max(1);
        self.bx((0, self.mm(140)), (0, t), (0, t), Tex::Oak(0));
        self.bx(
            (self.mm(120), self.mm(160)),
            (0, t + 1),
            (-1, t + 1),
            Tex::Ramp(m.iron, 60, 20),
        );
        self.bx(
            (self.mm(140), self.mm(160)),
            (0, t + 1),
            (t + 1, t + 3),
            Tex::Ramp(m.iron, 60, 20),
        );
        let z0 = self.mm(60);
        self.bx((0, self.mm(120)), (0, 1), (z0, z0 + 2), Tex::Ramp(m.iron, 80, 20));
        self.bx(
            (0, self.mm(120)),
            (0, 1),
            (z0 + 4, z0 + 6),
            Tex::Ramp(m.iron, 80, 20),
        );
        self.bx(
            (self.mm(120), self.mm(150)),
            (0, 1),
            (z0 - 1, z0 + 7),
            Tex::Ramp(m.iron, 60, 20),
        );
    }
}

fn in_top(x: i32, y: i32, z: i32, a: i32, b: i32, c: i32) -> bool {
    crate::batiments::kit::prims::in_ellipsoid(x, y + 0, z, [0, b, 0], [a + 100, b + 60, c + 100])
        && !crate::batiments::kit::prims::in_ellipsoid(x, y, z, [0, b, 0], [a - 40, b - 40, c - 40])
}

#[allow(dead_code)]
fn _inutile(_: VoxelValue, _: u32) -> u32 {
    hh_below(0, 1)
}
