//! Les bâtiments CIVILS et de défense : église et chapelle, halle de marché, tour de guet, rempart et porte de ville,
//! puits, ponts de pierre et de bois.

use super::bld::{Bld, Rect, RoofSpec, Wall, cs};
use crate::batiments::kit::intmath::isqrt;
use crate::batiments::kit::matieres::{Ton, bois, pierre, ton, val};
use crate::batiments::kit::prims::Cell;
use crate::batiments::kit::rng::hh;
use crate::batiments::maison::params::{Accent, WindowParams};

fn fen(w: i32, h: i32, arch: bool) -> WindowParams {
    WindowParams {
        w,
        h,
        sill: 0,
        arch,
        shutters: false,
        box_: false,
        color: Accent::Brown,
        lit100: 80,
        gap: 50,
    }
}

/// Église (clocher-porche, nef, contreforts) ou chapelle (nef seule, clocheton de pignon).
pub fn eglise(b: &mut Bld, chapelle: bool) -> (i32, i32) {
    let m = b.m;
    let (w, l) = if chapelle {
        (b.range(1, 56, 64), b.range(2, 74, 90))
    } else {
        (b.range(1, 70, 80), b.range(2, 104, 124))
    };
    let nef = Rect::new(0, w, 0, l);
    let wh = if chapelle { 56 } else { 68 };
    let (ev, rk, sl) = (6, 4, 125);
    let spec = RoofSpec {
        body: nef.body(false, ev, rk),
        hw: wh,
        eave: ev,
        slope100: sl,
    };
    b.walls(nef, 0, wh, 6, Wall::Stone, Some(spec), 0);
    b.gable_roof(spec, 25);
    // vitraux : fenêtres hautes cintrées sur les longs pans
    for f in [0, 1] {
        let fr = nef.frame(false, f);
        let n = if chapelle { 2 } else { 4 };
        for i in 0..n {
            let u = 16 + i * ((l - 32 - 12) / (n - 1).max(1));
            b.window(fr, u, 20, fen(12, 32, true));
        }
        // contreforts entre les fenêtres
        for i in 0..=n {
            let u = 10 + i * ((l - 20) / n);
            let (x0, x1) = if f == 0 { (w, w + 5) } else { (-5, 0) };
            let _ = u;
            b.rule([x0, 0, u], [x1, 52, u + 5], move |x, y, z| {
                let k = if f == 0 { x - w } else { -1 - x };
                if y < 52 - k * 6 {
                    Cell::Put(pierre(m.stone_grey, 1 + (hh(x / 3, y / 4, z / 3, 8) % 100) as u8))
                } else {
                    Cell::Keep
                }
            });
        }
    }
    let fs = nef.frame(false, 2);
    if chapelle {
        b.door(fs, w / 2 - 11, 22, 40, true, Accent::Red, true);
        b.window(fs, w / 2 - 7, 52, fen(14, 20, true));
        // clocheton de pignon : deux piliers et une petite pyramide
        let top = wh + 6 + sl * w / 200 + 2;
        let (cx, cz) = (w / 2, l);
        b.rule(
            [cx - 8, top - 8, cz - 2],
            [cx + 9, top + 12, cz + 4],
            move |x, y, z| {
                let a = (x - cx).abs();
                if a == 7 && z >= cz && z < cz + 3 && y < top + 8 {
                    Cell::Put(pierre(m.stone_grey, 7))
                } else if a <= 6 && z >= cz && z < cz + 3 && y == top + 8 {
                    Cell::Put(pierre(m.stone_grey, 9))
                } else {
                    Cell::Keep
                }
            },
        );
        b.fill([cx - 1, top - 8, cz], [cx + 1, top - 2, cz + 3], val(m.brass, 70));
        b.pyramid_roof(cx, cz + 1, 8, top + 9, 12);
        b.prop("banc", 2, [w / 2, 0, 30], 0);
        b.prop("banc", 3, [w / 2, 0, 44], 0);
    } else {
        // clocher-porche au sud de la nef
        let tw = 44;
        let tower = Rect::new((w - tw) / 2, (w + tw) / 2, l, l + tw);
        let th = 146;
        b.walls(tower, 0, th, 7, Wall::Stone, None, 0);
        let ft = Rect::new(0, 0, 0, 0);
        let _ = ft;
        let frt = Frame2::south(tower);
        b.door(frt, tw / 2 - 12, 24, 44, true, Accent::Red, true);
        b.window(frt, tw / 2 - 7, 62, fen(14, 26, true));
        let g = b.opts.glazing;
        b.opts.glazing = false;
        for f in 0..4u8 {
            let fr = crate::batiments::maison::planner::Frame::new(0, &tower.body(true, 0, 0), f);
            b.window(fr, tw / 2 - 7, 100, fen(14, 30, true));
        }
        b.opts.glazing = g;
        b.pyramid_roof(
            (tower.x0 + tower.x1) / 2,
            (tower.z0 + tower.z1) / 2,
            tw / 2 + 3,
            th,
            62,
        );
        // croix de fer au sommet
        let (cx, cz) = ((tower.x0 + tower.x1) / 2, (tower.z0 + tower.z1) / 2);
        b.fill([cx, th + 62, cz], [cx + 1, th + 76, cz + 1], val(m.iron, 30));
        b.fill([cx - 4, th + 70, cz], [cx + 5, th + 71, cz + 1], val(m.iron, 30));
        // rosace dans le pignon
        b.window(nef.frame(false, 3), w / 2 - 6, wh + 6, fen(12, 12, true));
        for i in 0..4 {
            b.prop("banc", 2 + i as u64, [w / 2 - 16, 0, 20 + 18 * i], 1);
            b.prop("banc", 7 + i as u64, [w / 2 + 16, 0, 20 + 18 * i], 1);
        }
        // autel et nappe au fond
        b.fill([w / 2 - 12, 0, 6], [w / 2 + 12, 14, 18], pierre(m.stone_grey, 11));
        b.fill(
            [w / 2 - 12, 14, 6],
            [w / 2 + 12, 16, 18],
            ton(m.fabric_b, Ton::Clair),
        );
    }
    nef.center()
}

struct Frame2;
impl Frame2 {
    fn south(r: Rect) -> crate::batiments::maison::planner::Frame {
        crate::batiments::maison::planner::Frame::new(0, &r.body(true, 0, 0), 2)
    }
}

/// Halle de marché : plate-forme pavée, poteaux de chêne, grand toit de bardeaux, étals à l'intérieur.
pub fn halle(b: &mut Bld) -> (i32, i32) {
    let m = b.m;
    let (w, d) = (b.range(1, 132, 160), 84);
    let r = Rect::new(0, w, 0, d);
    // plate-forme pavée
    b.rule([-6, 0, -6], [w + 6, 3, d + 6], move |x, y, z| {
        Cell::Put(pierre(m.cobble, 1 + (hh(x / 3, y, z / 3, 9) % 126) as u8))
    });
    let hw = 64;
    let (ev, rk, sl) = (12, 10, 100);
    let spec = RoofSpec {
        body: r.body(true, ev, rk),
        hw,
        eave: ev,
        slope100: sl,
    };
    b.gable_roof(spec, 15);
    let n = (w - 8) / 32;
    for i in 0..=n {
        let x = 4 + i * ((w - 12) / n);
        for z in [4, d - 8] {
            b.fill([x, 3, z], [x + 4, 4, z + 4], pierre(m.stone_grey, 5));
            b.rule([x, 4, z], [x + 4, hw + 2, z + 4], move |a, y, c| {
                Cell::Put(bois(m.oak_raw, 1, 3 + (hh(a, y, c, 3) % 10) as u8))
            });
        }
        // entrait transversal et jambes de force
        b.rule([x, hw - 2, 4], [x + 4, hw + 2, d - 4], move |a, y, c| {
            Cell::Put(bois(m.timber, 2, 3 + (hh(a, y, c, 4) % 8) as u8))
        });
        for (z0, dz) in [(4, 1), (d - 4, -1)] {
            b.rule(
                [x, hw - 16, z0.min(z0 + dz * 14)],
                [x + 4, hw, z0.max(z0 + dz * 14) + 1],
                move |a, y, c| {
                    let k = (hw - 1 - y).max(0);
                    let want = z0 + dz * (14 - k);
                    if (c - want).abs() <= 1 {
                        Cell::Put(bois(m.timber, 1, 5 + (hh(a, y, c, 5) % 5) as u8))
                    } else {
                        Cell::Keep
                    }
                },
            );
        }
    }
    for z in [4, d - 8] {
        b.rule([4, hw - 2, z], [w, hw + 2, z + 4], move |a, y, c| {
            Cell::Put(bois(m.timber, 0, 3 + (hh(a, y, c, 6) % 8) as u8))
        });
    }
    // étals et marchandises
    for (i, x) in [24, 66, 108].into_iter().enumerate() {
        if x < w - 20 {
            b.prop("etal", 1 + i as u64, [x, 3, 16], 0);
        }
    }
    b.prop("etal", 5, [30, 3, d - 18], 2);
    b.prop("caisse", 2, [w - 26, 3, d - 24], 0);
    b.prop("tonneau", 3, [w - 40, 3, d - 20], 0);
    b.prop("sacs", 4, [w / 2, 3, d - 22], 0);
    r.center()
}

/// Tour de guet carrée : meurtrières, mâchicoulis, créneaux, petit toit de bardeaux sur poteaux.
pub fn tour_guet(b: &mut Bld) -> (i32, i32) {
    let m = b.m;
    let s = b.range(1, 42, 50);
    let r = Rect::new(0, s, 0, s);
    let th = b.range(2, 168, 196);
    b.walls(r, 0, th, 7, Wall::Stone, None, 0);
    for f in 0..4u8 {
        let fr = crate::batiments::maison::planner::Frame::new(0, &r.body(true, 0, 0), f);
        for y in [46, 98, 140] {
            b.window(
                fr,
                s / 2 - 1,
                y,
                WindowParams {
                    w: 2,
                    h: 14,
                    ..fen(2, 14, false)
                },
            );
        }
    }
    let fs = r.frame(true, 2);
    b.door(fs, s / 2 - 8, 16, 30, true, Accent::Brown, true);
    // planchers intérieurs
    for y in [60, 112, 150] {
        b.floor(r, y, 3);
    }
    // mâchicoulis : couronne débordante sur corbeaux, puis parapet crénelé
    let (y0, ext) = (th - 12, 4);
    b.rule([-ext, y0, -ext], [s + ext, th + 12, s + ext], move |x, y, z| {
        let (dx, dz) = (x.min(s - 1 - x), z.min(s - 1 - z));
        let d = dx.min(dz);
        let k = y - y0;
        if k < 4 {
            // corbeaux : un sur deux dessous la dalle
            let ring = d < 0;
            return if ring && ((x + z).rem_euclid(4) < 2 || k >= 2) && d >= -ext {
                Cell::Put(pierre(m.stone_dark, 1 + (hh(x / 2, y, z / 2, 3) % 100) as u8))
            } else {
                Cell::Keep
            };
        }
        if k < 6 {
            return if d >= -ext && d < 7 {
                Cell::Put(pierre(m.stone_dark, 1 + (hh(x / 3, y, z / 3, 4) % 100) as u8))
            } else {
                Cell::Keep
            };
        }
        let ring = d >= -ext && d < -ext + 3;
        let merlon = (x + z + 100).rem_euclid(12) < 8;
        if ring && (merlon || k < 8) {
            Cell::Put(pierre(m.stone_dark, 1 + (hh(x / 2, y, z / 2, 5) % 100) as u8))
        } else {
            Cell::Keep
        }
    });
    // toit de bardeaux sur quatre poteaux
    for (x, z) in [(2, 2), (s - 5, 2), (2, s - 5), (s - 5, s - 5)] {
        b.fill([x, th + 6, z], [x + 3, th + 36, z + 3], bois(m.timber, 1, 6));
    }
    b.pyramid_roof(s / 2, s / 2, s / 2 + 3, th + 34, 26);
    b.fill(
        [s / 2 - 1, th + 60, s / 2 - 1],
        [s / 2 + 1, th + 74, s / 2 + 1],
        val(m.iron, 30),
    );
    b.rule(
        [s / 2, th + 70, s / 2 - 1],
        [s / 2 + 14, th + 79, s / 2 + 1],
        move |x, y, z| {
            let _ = z;
            let a = x - s / 2;
            if y > th + 70 + a / 4 && y < th + 78 - a / 5 {
                Cell::Put(ton(m.fabric_a, Ton::Sombre))
            } else {
                Cell::Keep
            }
        },
    );
    b.prop("echelle", 2, [s / 2 - 6, 0, s + 3], 0);
    b.prop("lanterne", 3, [s + 12, 0, s + 10], 0);
    r.center()
}

/// Rempart et porte de ville : deux tours, passage voûté fermé par deux vantaux et une herse relevée, courtines crénelées.
pub fn rempart_porte(b: &mut Bld) -> (i32, i32) {
    let m = b.m;
    let (th, wallh) = (126, 92);
    let seg = b.range(1, 110, 150);
    let stone = move |x: i32, y: i32, z: i32, ax: i32| {
        let n = b_courses(ax, y, z);
        let _ = n;
        pierre(
            m.stone_grey,
            1 + (hh(x.div_euclid(5), y.div_euclid(4), z.div_euclid(5), 12) % 120) as u8,
        )
    };
    // courtines (de part et d'autre de la porte), épaisses de 16, avec chemin de ronde et parapet extérieur crénelé
    for sign in [-1, 1] {
        let (a, c) = if sign < 0 {
            (-60 - seg, -60)
        } else {
            (60, 60 + seg)
        };
        b.rule([a, 0, 10], [c, wallh + 11, 30], move |x, y, z| {
            let d = z - 10;
            if y < wallh {
                // fruit : le mur s'épaissit vers le bas côté extérieur
                let ext = 20 - (wallh - y) * 4 / wallh;
                return if d <= ext {
                    Cell::Put(stone(x, y, z, 0))
                } else {
                    Cell::Keep
                };
            }
            let k = y - wallh;
            if z >= 26 && z < 29 && (k < 3 || (x + 1000).rem_euclid(12) < 8) {
                return Cell::Put(stone(x, y, z, 1));
            }
            if z >= 10 && z < 12 && k < 4 {
                return Cell::Put(stone(x, y, z, 2));
            }
            if k == 0 && z >= 12 && z < 26 {
                return Cell::Put(pierre(m.cobble, 1 + (hh(x / 3, 1, z / 3, 2) % 120) as u8));
            }
            Cell::Keep
        });
    }
    // tours de porte
    for (x0, x1) in [(-60, -20), (20, 60)] {
        let r = Rect::new(x0, x1, 0, 44);
        b.walls(r, 0, th, 7, Wall::Stone, None, 0);
        b.floor(r, wallh, 3);
        b.pyramid_roof((x0 + x1) / 2, 22, 23, th, 34);
        let fs = r.frame(true, 2);
        b.window(
            fs,
            18,
            100,
            WindowParams {
                w: 3,
                h: 16,
                ..fen(3, 16, false)
            },
        );
        b.window(
            fs,
            18,
            50,
            WindowParams {
                w: 3,
                h: 16,
                ..fen(3, 16, false)
            },
        );
    }
    // masse de la porte : linteau voûté entre les tours, passage de 32 de large
    let ph = 56;
    b.rule([-21, 0, 0], [21, wallh + 11, 44], move |x, y, z| {
        let a = x.abs();
        let in_pass = a < 16 && (y < 38 || a * a + (y - 38) * (y - 38) < 16 * 16);
        let _ = ph;
        if in_pass {
            // vantaux fermés au milieu de la voûte, herse relevée dans sa rainure
            if (20..23).contains(&z) && a < 16 {
                return Cell::Put(if a == 0 || y % 14 < 2 {
                    val(m.iron, 30)
                } else {
                    bois(m.oak_planks, 1, 4 + (hh(x, y, 1, 3) % 9) as u8)
                });
            }
            if (8..10).contains(&z) && y >= 40 && ((x + 100).rem_euclid(5) == 0 || y % 6 == 0) {
                return Cell::Put(val(m.iron, 20 + (hh(x, y, z, 5) % 20) as u8));
            }
            return Cell::Air;
        }
        if y < wallh {
            return Cell::Put(stone(x, y, z, 3));
        }
        let k = y - wallh;
        if z >= 40 && k < 11 && (k < 3 || (x + 1000).rem_euclid(12) < 8) {
            return Cell::Put(stone(x, y, z, 4));
        }
        if k == 0 {
            return Cell::Put(pierre(m.cobble, 3));
        }
        Cell::Keep
    });
    b.prop("lanterne", 2, [-34, 0, 52], 0);
    b.prop("lanterne", 3, [34, 0, 52], 0);
    b.prop("tonneau", 4, [-30, 0, 62], 0);
    b.prop("charrette", 2, [10, 0, 80], 3);
    (0, 22)
}

fn b_courses(_a: i32, _y: i32, _z: i32) -> i32 {
    0
}

/// Puits couvert : margelle moussue, deux montants, treuil à manivelle, petit toit à deux pans, seau.
pub fn puits(b: &mut Bld) -> (i32, i32) {
    let m = b.m;
    let (cx, cz) = (40, 40);
    let (cx100, cz100) = (100 * cx + 50, 100 * cz + 50);
    b.rule([cx - 20, 0, cz - 20], [cx + 21, 18, cz + 21], move |x, y, z| {
        let d2 = i64::from(100 * x + 50 - cx100).pow(2) + i64::from(100 * z + 50 - cz100).pow(2);
        let marche = d2 <= 1850_i64.pow(2) && d2 > 1300_i64.pow(2) && y < 2;
        let anneau = d2 <= 1300_i64.pow(2) && d2 >= 880_i64.pow(2) && y < 16;
        if marche || anneau {
            if y >= 14 && hh(x, y, z, 1) % 100 < 30 {
                return Cell::Put(val(m.moss, 50 + (hh(x, 0, z, 2) % 50) as u8));
            }
            return Cell::Put(pierre(
                m.stone_grey,
                1 + (hh(x.div_euclid(4), y.div_euclid(3), z.div_euclid(4), 7) % 120) as u8,
            ));
        }
        if d2 < 880_i64.pow(2) && (3..5).contains(&y) {
            return Cell::Put(val(m.paint_blue, 40 + (hh(x, y, z, 4) % 30) as u8));
        }
        Cell::Keep
    });
    for x in [cx - 17, cx + 15] {
        b.rule([x, 14, cz - 1], [x + 3, 58, cz + 2], move |a, y, c| {
            Cell::Put(bois(m.oak_raw, 1, 3 + (hh(a, y, c, 3) % 10) as u8))
        });
    }
    b.rule([cx - 18, 48, cz - 1], [cx + 18, 51, cz + 2], move |a, y, c| {
        Cell::Put(bois(m.timber, 0, 4 + (hh(a, y, c, 5) % 6) as u8))
    });
    // treuil
    b.rule([cx - 14, 36, cz - 3], [cx + 14, 43, cz + 4], move |_, y, z| {
        let d2 = (y - 39) * (y - 39) + (z - cz) * (z - cz);
        if d2 <= 9 {
            Cell::Put(bois(m.oak_raw, 0, 7))
        } else {
            Cell::Keep
        }
    });
    b.fill([cx + 14, 36, cz], [cx + 18, 38, cz + 1], val(m.iron, 40));
    b.fill([cx + 17, 30, cz], [cx + 18, 38, cz + 1], val(m.iron, 40));
    b.fill(
        [cx + 17, 29, cz - 1],
        [cx + 19, 31, cz + 2],
        bois(m.oak_raw, 1, 5),
    );
    // corde et seau
    b.fill([cx, 20, cz], [cx + 1, 36, cz + 1], val(m.cloth, 60));
    b.rule([cx - 4, 14, cz - 4], [cx + 5, 22, cz + 5], move |x, y, z| {
        let d2 = (x - cx) * (x - cx) + (z - cz) * (z - cz);
        if y >= 14 && y < 20 && d2 <= 16 && (d2 >= 9 || y == 14) {
            Cell::Put(if y == 16 {
                val(m.iron, 30)
            } else {
                bois(m.oak_raw, 1, 5)
            })
        } else {
            Cell::Keep
        }
    });
    // toit à deux pans
    let spec = RoofSpec {
        body: Rect::new(cx - 20, cx + 21, cz - 11, cz + 12).body(true, 4, 4),
        hw: 50,
        eave: 4,
        slope100: 115,
    };
    b.gable_roof(spec, 20);
    (cx, cz)
}

fn eau(b: &mut Bld, x0: i32, x1: i32, z0: i32, z1: i32) {
    let m = b.m;
    b.rule([x0, 0, z0], [x1, 4, z1], move |x, y, z| {
        let bord = z < z0 + 4 || z >= z1 - 4;
        if bord {
            if y < 3 {
                Cell::Put(val(m.sand, 40 + (hh(x, y, z, 1) % 30) as u8))
            } else {
                Cell::Keep
            }
        } else if y < 2 {
            Cell::Put(val(m.sand, 30))
        } else if y == 2 {
            Cell::Put(val(m.paint_blue, 70 + (hh(x / 3, 0, z / 2, 2) % 40) as u8))
        } else {
            Cell::Keep
        }
    });
}

/// Pont de pierre à arches en plein cintre : `span` voxels entre culées, tablier pavé, parapets, rampes d'accès.
pub fn pont_pierre(b: &mut Bld, span: i32) -> (i32, i32) {
    let m = b.m;
    let l = span.clamp(60, 240);
    let n = ((l + 43) / 44).max(1);
    let aw = l / n;
    let (hd, wdt) = (36, 24);
    let prof = move |x: i32| -> i32 {
        if x < 0 {
            2 + (hd - 2) * (x + 20).max(0) / 20
        } else if x >= l {
            2 + (hd - 2) * (l + 20 - x).max(0) / 20
        } else {
            hd + 5 - ((2 * x - l).abs() * 5 / l.max(1))
        }
    };
    b.rule([-20, 0, 0], [l + 20, hd + 18, wdt], move |x, y, z| {
        let h = prof(x);
        // arches : demi-ellipses passant dans toute la largeur
        if x >= 0 && x < l {
            let i = (x / aw).min(n - 1);
            let xc = i * aw + aw / 2;
            let a = aw / 2 - 4;
            let bh = h - 14;
            let dx = i64::from(x - xc) * 100 + 50;
            let (aa, bb) = (i64::from(a) * 100, i64::from(bh) * 100);
            if y < bh && dx * dx * bb * bb + i64::from(y * 100 + 50).pow(2) * aa * aa <= aa * aa * bb * bb {
                return Cell::Air;
            }
        }
        let parapet = z < 3 || z >= wdt - 3;
        if y < h - 1 {
            return Cell::Put(pierre(
                m.stone_grey,
                1 + (hh(x.div_euclid(5), y.div_euclid(4), z.div_euclid(5), 14) % 120) as u8,
            ));
        }
        if y == h - 1 {
            return Cell::Put(if parapet {
                pierre(m.stone_grey, 1 + (hh(x / 4, 0, z, 15) % 100) as u8)
            } else {
                pierre(m.cobble, 1 + (hh(x / 2, 0, z / 2, 16) % 120) as u8)
            });
        }
        if parapet && y < h + 7 {
            let cap = y >= h + 5;
            if cap && (z == 0 || z == wdt - 1) && false {
                return Cell::Keep;
            }
            if hh(x, y, z, 17) % 100 < 6 && y < h + 3 {
                return Cell::Put(val(m.moss, 50));
            }
            return Cell::Put(pierre(
                m.stone_grey,
                1 + (hh(x.div_euclid(5), y.div_euclid(3), z, 18) % 110) as u8,
            ));
        }
        Cell::Keep
    });
    eau(b, 6, l - 6, -30, wdt + 30);
    b.prop("lanterne", 2, [-26, 0, -4], 0);
    b.prop("lanterne", 3, [l + 26, 0, wdt + 4], 0);
    (l / 2, wdt / 2)
}

/// Pont de bois : tablier de planches, garde-corps, appuis en chevalets, rampes d'accès.
pub fn pont_bois(b: &mut Bld, span: i32) -> (i32, i32) {
    let m = b.m;
    let l = span.clamp(48, 220);
    let (hd, wdt) = (18, 20);
    b.rule([-14, 0, 0], [l + 14, hd + 16, wdt], move |x, y, z| {
        let h = if x < 0 {
            4 + (hd - 4) * (x + 14).max(0) / 14
        } else if x >= l {
            4 + (hd - 4) * (l + 14 - x).max(0) / 14
        } else {
            hd
        };
        // tablier : planches en travers, longerons dessous
        if y == h || y == h - 1 {
            return Cell::Put(bois(
                m.oak_planks,
                2,
                3 + (hh(x.div_euclid(4), y, 3, 1) % 12) as u8,
            ));
        }
        if y >= h - 5 && y < h - 1 && (z.min(wdt - 1 - z) == 2 || z.min(wdt - 1 - z) == 3) && x >= 0 && x < l
        {
            return Cell::Put(bois(m.timber, 0, 3 + (hh(x, y, z, 2) % 8) as u8));
        }
        // garde-corps : poteaux tous les 20, lisses haute et médiane
        let bord = z < 2 || z >= wdt - 2;
        if bord && y > h && y < h + 14 {
            let poteau = (x + 1000).rem_euclid(20) < 2;
            let lisse = y == h + 12 || y == h + 13 || y == h + 6;
            if poteau || lisse {
                return Cell::Put(bois(
                    m.oak_raw,
                    if poteau { 1 } else { 0 },
                    3 + (hh(x, y, z, 3) % 10) as u8,
                ));
            }
        }
        // chevalets : deux poteaux inclinés par appui, entretoise en croix
        if x >= 0 && x < l && y < h - 5 {
            let step = (l / ((l / 36).max(1) + 1)).max(12);
            let k = (x + step / 2).rem_euclid(step);
            let (i, near) = ((x + step / 2) / step, (k - step / 2).abs());
            let _ = i;
            let _ = near;
            let col = (x % step) < 3 && x > 6 && x < l - 6;
            let pos = z.min(wdt - 1 - z);
            if col && (pos == 4 || pos == 5) {
                return Cell::Put(bois(m.oak_raw, 1, 5 + (hh(x, y, z, 4) % 6) as u8));
            }
            if col && y == (h - 12) && pos >= 4 && pos <= wdt - 6 {
                return Cell::Put(bois(m.timber, 2, 6));
            }
            if col && y == h - 8 && (z - wdt / 2).abs() <= 1 + (h - 8 - y).abs() {
                return Cell::Put(bois(m.timber, 2, 4));
            }
        }
        Cell::Keep
    });
    eau(b, 4, l - 4, -30, wdt + 30);
    b.prop("lanterne", 4, [-18, 0, -3], 0);
    b.prop("barriere_marker", 0, [0, 0, 0], 0);
    let _ = (isqrt(1), ton(m.glow, Ton::Moyen), cs(0));
    (l / 2, wdt / 2)
}
