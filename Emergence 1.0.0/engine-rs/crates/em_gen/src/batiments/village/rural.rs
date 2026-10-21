//! Les bâtiments RURAUX : grange, étable, forge, cabane de bûcheron, moulin à vent, moulin à eau.

use em_core::VoxelValue;

use super::bld::{Bld, Rect, RoofSpec, Wall, cs};
use crate::batiments::kit::intmath::isqrt;
use crate::batiments::kit::matieres::{Ton, bois, pierre, ton, val};
use crate::batiments::kit::prims::Cell;
use crate::batiments::kit::rng::hh;
use crate::batiments::maison::params::{Accent, WindowParams};

fn fen(w: i32, h: i32, arch: bool, shutters: bool, color: Accent) -> WindowParams {
    WindowParams {
        w,
        h,
        sill: 0,
        arch,
        shutters,
        box_: false,
        color,
        lit100: 80,
        gap: 50,
    }
}

/// Grange : planches à couvre-joints sur soubassement de moellons, grande porte de pignon, lucarne de fenil.
pub fn grange(b: &mut Bld) -> (i32, i32) {
    let m = b.m;
    let (w, l) = (b.range(1, 84, 104), b.range(2, 110, 140));
    let r = Rect::new(0, w, 0, l);
    let wh = b.range(3, 44, 54);
    let (ev, rk, sl) = (8, 6, 100);
    let spec = RoofSpec {
        body: r.body(false, ev, rk),
        hw: wh,
        eave: ev,
        slope100: sl,
    };
    b.walls(r, 0, wh, 6, Wall::Boards, Some(spec), 0);
    b.gable_roof(spec, 6);
    let fr = r.frame(false, 2);
    let (dw, dh) = (38, 42);
    b.stone_frames = false;
    b.door(fr, (fr.len - dw) / 2, dw, dh, false, Accent::Brown, false);
    // croix de Saint-André sur les vantaux
    let (x0, z1) = (r.x0 + (fr.len - dw) / 2, r.z1);
    b.rule([x0, 2, z1 - 6], [x0 + dw, dh, z1 - 3], move |x, y, z| {
        let (a, c) = (x - x0, y - 2);
        let diag = (a * (dh - 4) / dw - c).abs() <= 1 || ((dw - 1 - a) * (dh - 4) / dw - c).abs() <= 1;
        if z == z1 - 6 && (diag || a == dw / 2 || a == dw / 2 - 1) && c < dh - 4 {
            Cell::Put(bois(m.timber, 1, 5))
        } else {
            Cell::Keep
        }
    });
    b.window(
        fr,
        (fr.len - 14) / 2,
        wh + 8,
        fen(14, 16, false, true, Accent::Brown),
    );
    for f in [0, 1] {
        let fr = r.frame(false, f);
        for u in [28, l - 42] {
            b.window(fr, u, 26, fen(12, 12, false, false, Accent::Brown));
        }
    }
    // foin et bottes à l'intérieur, charrette et meule dehors
    b.prop("foin", 2, [18, 0, 40], 0);
    b.prop("foin", 5, [w - 20, 0, 70], 0);
    b.prop("caisse", 1, [w - 14, 0, 18], 0);
    b.prop("charrette", 3, [-34, 0, l + 4], 3);
    b.prop("tonneau", 4, [w + 12, 0, l - 6], 0);
    b.prop("foin", 9, [w + 24, 0, 40], 0);
    r.center()
}

/// Étable : longue façade à trois portes en deux vantaux (haut ouvert), toit à faible pente, auges et foin.
pub fn etable(b: &mut Bld) -> (i32, i32) {
    let m = b.m;
    let (w, d) = (b.range(1, 124, 150), 60);
    let r = Rect::new(0, w, 0, d);
    let wh = 40;
    let (ev, rk, sl) = (10, 6, 90);
    let spec = RoofSpec {
        body: r.body(true, ev, rk),
        hw: wh,
        eave: ev,
        slope100: sl,
    };
    b.walls(r, 0, wh, 6, Wall::Boards, Some(spec), 0);
    b.gable_roof(spec, 12);
    let fr = r.frame(true, 2);
    b.stone_frames = false;
    let n = 3;
    for i in 0..n {
        let u0 = 12 + i * ((w - 24 - 20) / (n - 1));
        b.door(fr, u0, 20, 34, false, Accent::Brown, false);
        // le haut des vantaux est ouvert
        b.carve([r.x0 + u0 + 1, 17, r.z1 - 6], [r.x0 + u0 + 19, 33, r.z1 - 2]);
        b.prop("sacs", 2 + i as u64, [r.x0 + u0 + 10, 0, r.z1 + 7], 0);
    }
    for u in [w / 2 - 30, w / 2 + 14] {
        b.window(fr, u.max(36), 22, fen(12, 10, false, true, Accent::Green));
    }
    b.fill(
        [r.x0 + 6, 0, r.z0 + 6],
        [r.x1 - 6, 3, r.z0 + 10],
        bois(m.timber, 0, 4),
    );
    b.prop("foin", 7, [w - 22, 0, 24], 0);
    b.prop("tonneau", 3, [-12, 0, d + 4], 0);
    b.prop("banc", 2, [w / 2, 0, d + 12], 0);
    r.center()
}

/// Forge : murs de pierre, grande ouverture de façade, âtre sous hotte, grosse cheminée, enclume et soufflet.
pub fn forge(b: &mut Bld) -> (i32, i32) {
    let m = b.m;
    let (w, d) = (b.range(1, 70, 84), 62);
    let r = Rect::new(0, w, 0, d);
    let wh = 46;
    let (ev, rk, sl) = (8, 6, 100);
    let spec = RoofSpec {
        body: r.body(true, ev, rk),
        hw: wh,
        eave: ev,
        slope100: sl,
    };
    b.walls(r, 0, wh, 6, Wall::Stone, Some(spec), 0);
    b.gable_roof(spec, 3);
    let fr = r.frame(true, 2);
    let leaf = b.opts.door_leaf;
    b.opts.door_leaf = false;
    b.door(fr, (w - 40) / 2 + 10, 40, 34, true, Accent::Brown, false);
    b.opts.door_leaf = leaf;
    b.window(fr, 12, 18, fen(12, 16, false, true, Accent::Red));
    let fe = r.frame(true, 0);
    b.window(fe, 26, 18, fen(12, 16, false, true, Accent::Red));
    // âtre contre le mur ouest, hotte et grosse cheminée dehors
    let hy = 14;
    b.rule([6, 0, 22], [26, 40, 42], move |x, y, z| {
        let (a, c) = (x - 6, z - 22);
        if y < hy {
            let foyer = (3..17).contains(&a) && (3..17).contains(&c) && y >= 2;
            if foyer {
                return if y == 2 {
                    Cell::Put(val(m.ember, 30 + (hh(x, y, z, 3) % 80) as u8))
                } else {
                    Cell::Air
                };
            }
            return Cell::Put(pierre(m.stone_dark, 1 + (hh(x / 3, y / 3, z / 3, 5) % 100) as u8));
        }
        // hotte : pyramide inversée vers la cheminée (ouest)
        let k = y - hy;
        let r = 10 - k * 7 / 26;
        if (a - 10).abs() <= r && (c - 10).abs() <= r && ((a - 10).abs() >= r - 1 || (c - 10).abs() >= r - 1)
        {
            Cell::Put(pierre(m.stone_dark, 1 + (hh(x / 3, y / 3, z / 3, 6) % 100) as u8))
        } else {
            Cell::Keep
        }
    });
    b.chimney(-12, 6, 26, 40, 0, wh + 44);
    // conduit : perce le mur entre la hotte et la cheminée
    b.carve([-3, 36, 30], [8, 40, 36]);
    // enclume sur son billot, soufflet, baquet, râtelier d'outils
    b.rule([w / 2 + 6, 0, 22], [w / 2 + 30, 22, 38], move |x, y, z| {
        let (a, c) = (x - (w / 2 + 6), z - 22);
        if y < 9 && (a - 6) * (a - 6) + (c - 8) * (c - 8) <= 20 {
            return Cell::Put(bois(m.timber, 1, 5 + (hh(x, y, z, 1) % 6) as u8));
        }
        let ah = (9..12).contains(&y)
            && (1..11).contains(&a)
            && (4..12).contains(&c)
            && !(a > 8 && c > 9 && y > 10);
        let tail = (12..14).contains(&y) && (3..9).contains(&a) && (5..11).contains(&c);
        if ah || tail || ((9..11).contains(&y) && (11..15).contains(&a) && (6..9).contains(&c)) {
            Cell::Put(val(m.iron, 18 + (hh(x, y, z, 2) % 20) as u8))
        } else {
            Cell::Keep
        }
    });
    b.rule([8, 0, 44], [30, 18, 56], move |x, y, z| {
        let (a, c) = (x - 8, z - 44);
        let h = 4 + (a * 12 / 22);
        if y < h && a < 18 && c < 10 && y > 1 && (c - 5).abs() <= (10 - y.min(8)) / 2 + 2 {
            Cell::Put(val(m.leather, 25 + (hh(x, y, z, 4) % 20) as u8))
        } else {
            Cell::Keep
        }
    });
    b.prop("tonneau", 6, [w - 14, 0, 12], 0);
    b.prop("ratelier", 2, [w / 2 - 10, 0, 8], 0);
    b.prop("tas_bois", 2, [-26, 0, 40], 1);
    b.prop("caisse", 4, [w + 10, 0, d - 8], 0);
    r.center()
}

#[allow(non_snake_case)]
/// Cabane de bûcheron : rondins superposés aux angles entaillés, toit de bardeaux débordant, cheminée de pierre.
pub fn cabane(b: &mut Bld) -> (i32, i32) {
    let (w, d) = (b.range(1, 54, 66), b.range(2, 42, 50));
    let r = Rect::new(0, w, 0, d);
    let rangs = 8;
    let wh = rangs * 5;
    let m = b.m;
    // rondins : rangs pairs le long de x (murs nord et sud), rangs impairs le long de z (murs est et ouest)
    b.rule(
        [r.x0 - 4, 0, r.z0 - 4],
        [r.x1 + 4, wh, r.z1 + 4],
        move |x, y, z| {
            let (row, ly) = (y.div_euclid(5), y.rem_euclid(5));
            let epais = if ly == 0 || ly == 4 { 4 } else { 5 };
            let pair = row % 2 == 0;
            let (dw, de, dn, ds) = (x - r.x0, r.x1 - 1 - x, z - r.z0, r.z1 - 1 - z);
            let (en_x, en_z) = (x >= r.x0 - 3 && x < r.x1 + 3, z >= r.z0 - 3 && z < r.z1 + 3);
            let (bx, bz) = (dn.min(ds), dw.min(de));
            let bout = if pair {
                bx < epais && bx >= 0 && en_x && (dw < 0 || de < 0)
            } else {
                bz < epais && bz >= 0 && en_z && (dn < 0 || ds < 0)
            };
            let corps = if pair {
                bx >= 0 && bx < epais && x >= r.x0 && x < r.x1
            } else {
                bz >= 0 && bz < epais && z >= r.z0 && z < r.z1
            };
            if !(corps || bout) {
                return Cell::Keep;
            }
            let axe = if pair { 0 } else { 2 };
            // bout de rondin : disque clair dans la section
            let extremite = if pair {
                dw < 0 || de < 0 || dw == 0 || de == 0
            } else {
                dn < 0 || ds < 0 || dn == 0 || ds == 0
            };
            if extremite {
                return Cell::Put(val(m.oak_planks, 75 + (hh(x, y, z, 1) % 20) as u8));
            }
            Cell::Put(bois(
                m.oak_raw,
                axe,
                2 + (hh(row, if pair { z } else { x } / 6, 3, 2) % 11) as u8,
            ))
        },
    );
    let (ev, rk, sl) = (10, 8, 95);
    let spec = RoofSpec {
        body: r.body(true, ev, rk),
        hw: wh,
        eave: ev,
        slope100: sl,
    };
    b.gable_roof(spec, 18);
    // pignons en planches au-dessus des rondins
    b.rule([r.x0, wh, r.z0], [r.x1, wh + 40, r.z1], move |x, y, z| {
        let c =
            crate::batiments::maison::planner::roof_at(&spec.body, x, z, spec.hw, spec.eave, spec.slope100);
        match c {
            Some(c) if y < c.bot && (x < r.x0 + 4 || x >= r.x1 - 4) => {
                Cell::Put(bois(m.oak_planks, 1, 4 + (hh(z / 5, 0, 1, 1) % 8) as u8))
            }
            _ => Cell::Keep,
        }
    });
    let fr = r.frame(true, 2);
    b.stone_frames = false;
    b.door(fr, w / 2 - 22, 18, 34, false, Accent::Brown, true);
    b.window(fr, w / 2 + 6, 16, fen(12, 14, false, true, Accent::Green));
    let fe = r.frame(true, 1);
    b.window(fe, d / 2 - 6, 16, fen(12, 14, false, true, Accent::Green));
    b.chimney(w - 2, w + 12, d / 2 - 8, d / 2 + 6, 0, wh + 40);
    b.prop("tas_bois", 3, [-14, 0, d / 2], 1);
    b.prop("tas_bois", 4, [w / 2 + 20, 0, d + 20], 0);
    b.prop("tonneau", 2, [w + 10, 0, d + 4], 0);
    b.prop("lanterne", 1, [w / 2 - 36, 0, d + 14], 0);
    r.center()
}

/// Moulin à vent : tour de pierre légèrement conique, galerie de bois, coiffe de bardeaux, quatre ailes à lattes.
pub fn moulin_vent(b: &mut Bld) -> (i32, i32) {
    let m = b.m;
    let (cx, cz) = (50, 50);
    let (cx100, cz100) = (100 * cx + 50, 100 * cz + 50);
    let (r0, r1, h) = (4200, 2800, 110);
    b.round_wall(cx100, cz100, r0, r1, 0, h, 5);
    // plancher intermédiaire et galerie
    b.rule([cx - 46, 40, cz - 46], [cx + 47, 42, cz + 47], move |x, y, z| {
        let d2 = i64::from(100 * x + 50 - cx100).pow(2) + i64::from(100 * z + 50 - cz100).pow(2);
        let rr = i64::from(r0 + (r1 - r0) * 40 / h);
        if d2 > (rr + 900).pow(2) || d2 < (rr - 200).pow(2) {
            return Cell::Keep;
        }
        Cell::Put(bois(m.oak_planks, 0, 4 + (hh(x, y, z, 1) % 8) as u8))
    });
    b.rule([cx - 46, 42, cz - 46], [cx + 47, 56, cz + 47], move |x, y, z| {
        let d2 = i64::from(100 * x + 50 - cx100).pow(2) + i64::from(100 * z + 50 - cz100).pow(2);
        let rr = i64::from(r0 + (r1 - r0) * 40 / h);
        let ext = rr + 800;
        if d2 > (ext + 100).pow(2) || d2 < (ext - 100).pow(2) {
            return Cell::Keep;
        }
        let k = y - 42;
        let a = em_core::q16::atan2_turns(
            em_core::Q16::from_raw(i64::from(100 * z + 50 - cz100) + 1),
            em_core::Q16::from_raw(i64::from(100 * x + 50 - cx100) + 1),
        )
        .raw();
        let poteau = (a * 24 / 65_536 + 24) % 2 == 0 && (a * 24 % 65_536).abs() < 9000;
        if k == 10 || k == 11 || (poteau && k < 11) {
            Cell::Put(bois(m.timber, 1, 6))
        } else {
            Cell::Keep
        }
    });
    // coiffe
    b.cone_roof(cx100, cz100, r1 + 450, h, 38);
    b.fill(
        [cx - 1, h + 38, cz - 1],
        [cx + 1, h + 46, cz + 1],
        val(m.iron, 30),
    );
    // porte
    let zs = cz + 38;
    b.carve([cx - 7, 0, zs - 4], [cx + 7, 22, zs + 8]);
    b.rule([cx - 8, 0, zs - 1], [cx + 8, 26, zs + 3], move |x, y, z| {
        let (a, c) = (x - cx, y);
        let o = a.abs() < 7 && (c < 18 || a * a + (c - 18) * (c - 18) < 49);
        let cadre = a.abs() < 9 && (c < 20 || a * a + (c - 18) * (c - 18) < 81);
        if o && z == zs {
            return Cell::Put(bois(m.oak_planks, 1, 4 + (hh(x, y, 1, 1) % 8) as u8));
        }
        if cadre && !o && z >= zs {
            return Cell::Put(pierre(m.stone_grey, 1 + (hh(x / 4, y / 4, 1, 1) % 100) as u8));
        }
        Cell::Keep
    });
    // meurtrières
    for (dx, dz) in [(32, -4), (-36, 6), (4, -36)] {
        b.carve([cx + dx, 66, cz + dz], [cx + dx + 7, 80, cz + dz + 6]);
    }
    // ailes
    let hy = h + 6;
    let zf = cz + 30;
    let a0 = (b.range(5, 8, 38) * 65_536) / 360;
    let (lo, hi) = ([cx - 78, hy - 78, zf], [cx + 79, hy + 79, zf + 5]);
    b.rule(lo, hi, move |x, y, z| {
        let (dx, dy) = (x - cx, y - hy);
        if z == zf + 2 && dx * dx + dy * dy <= 16 {
            return Cell::Put(bois(m.timber, 2, 6));
        }
        for k in 0..4 {
            let (c, s) = cs(a0 + k * 16_384);
            let t = (dx * c + dy * s) / 100;
            let ss = (-dx * s + dy * c) / 100;
            if (3..76).contains(&t) {
                if ss.abs() <= 1 && z >= zf + 1 && z <= zf + 3 {
                    return Cell::Put(bois(m.timber, 1, 8));
                }
                if (14..76).contains(&t) && (2..=13).contains(&ss) && z == zf + 3 {
                    let bar = (t % 6 == 0) || ss == 2 || ss == 13 || t == 75;
                    if bar {
                        return Cell::Put(bois(m.oak_raw, 0, 6));
                    }
                    if (t / 6 + k) % 2 == 0 {
                        return Cell::Put(ton(m.fabric_b, Ton::Clair));
                    }
                }
            }
        }
        Cell::Keep
    });
    b.prop("sacs", 3, [cx + 24, 0, cz + 52], 0);
    b.prop("charrette", 4, [cx - 40, 0, cz + 56], 2);
    (cx, cz)
}

/// Moulin à eau : bâtiment de deux niveaux, roue à augets sur le pignon est, bief de bois, bassin.
pub fn moulin_eau(b: &mut Bld) -> (i32, i32) {
    let m = b.m;
    let (w, d) = (b.range(1, 90, 104), 66);
    let r = Rect::new(0, w, 0, d);
    let wh = 96;
    let (ev, rk, sl) = (10, 6, 100);
    let spec = RoofSpec {
        body: r.body(true, ev, rk),
        hw: wh,
        eave: ev,
        slope100: sl,
    };
    b.walls(r, 0, wh, 6, Wall::TimberPlaster, Some(spec), 46);
    b.floor(r, 50, 3);
    b.gable_roof(spec, 12);
    let fr = r.frame(true, 2);
    b.door(fr, w / 2 - 10, 20, 40, true, Accent::Brown, true);
    for u in [14, w - 30] {
        b.window(fr, u, 18, fen(14, 20, false, true, Accent::Green));
    }
    for u in [14, w / 2 - 7, w - 28] {
        b.window(fr, u, 62, fen(14, 20, false, true, Accent::Green));
    }
    // roue à augets sur le pignon est : plan (y, z), épaisseur 12 voxels
    let (wx0, cy, cz, rr) = (r.x1 + 4, 28, d / 2, 30);
    b.rule(
        [wx0, cy - rr - 1, cz - rr - 1],
        [wx0 + 12, cy + rr + 2, cz + rr + 2],
        move |x, y, z| {
            let (dy, dz) = (y - cy, z - cz);
            let d2 = dy * dy + dz * dz;
            if d2 > rr * rr {
                return Cell::Keep;
            }
            let a = em_core::q16::atan2_turns(
                em_core::Q16::from_raw(i64::from(dz) * 100 + 1),
                em_core::Q16::from_raw(i64::from(dy) * 100 + 1),
            )
            .raw();
            let side = x < wx0 + 2 || x >= wx0 + 10;
            let jante = d2 >= (rr - 3) * (rr - 3);
            if side && jante {
                return Cell::Put(bois(m.timber, 0, 3 + (hh(y, z, 0, 1) % 6) as u8));
            }
            let sect = (a * 12 / 65_536).rem_euclid(12);
            let frac = (a * 12).rem_euclid(65_536);
            let aug = d2 >= (rr - 8) * (rr - 8) && frac < 14_000;
            if aug && !side {
                return Cell::Put(bois(m.oak_raw, 0, 4 + sect as u8 % 8));
            }
            if d2 <= 25 {
                return Cell::Put(val(m.iron, 30));
            }
            let rayon = side && (dy == 0 || dz == 0 || (dy - dz).abs() <= 1 || (dy + dz).abs() <= 1);
            if rayon {
                Cell::Put(bois(m.oak_raw, 2, 6))
            } else {
                Cell::Keep
            }
        },
    );
    b.fill(
        [r.x1 - 3, cy - 1, cz - 1],
        [wx0 + 14, cy + 2, cz + 2],
        bois(m.timber, 0, 6),
    );
    // bief de bois au-dessus de la roue
    let by = cy + rr + 4;
    b.rule([wx0, by, cz - 1], [wx0 + 12, by + 5, d + 40], move |x, y, z| {
        let _ = z;
        let paroi = x == wx0 || x == wx0 + 11 || y == by;
        if paroi {
            Cell::Put(bois(m.oak_planks, 2, 4 + (hh(x, y, z, 2) % 8) as u8))
        } else if y == by + 1 {
            Cell::Put(val(m.paint_blue, 90 + (hh(x, y, z, 3) % 14) as u8))
        } else {
            Cell::Keep
        }
    });
    for z in [cz + 14, d + 30] {
        b.fill([wx0 + 1, 0, z], [wx0 + 4, by, z + 3], bois(m.timber, 1, 6));
        b.fill([wx0 + 8, 0, z], [wx0 + 11, by, z + 3], bois(m.timber, 1, 6));
    }
    // bassin
    b.rule(
        [r.x1 - 2, 0, cz - rr - 6],
        [wx0 + 34, 5, cz + rr + 8],
        move |x, y, z| {
            let bord = x >= wx0 + 31 || z < cz - rr - 3 || z >= cz + rr + 5;
            if bord {
                if y < 5 {
                    Cell::Put(pierre(m.stone_grey, 1 + (hh(x / 3, y / 2, z / 3, 4) % 100) as u8))
                } else {
                    Cell::Keep
                }
            } else if y < 3 {
                Cell::Put(val(m.paint_blue, 70 + (hh(x, y, z, 5) % 25) as u8))
            } else {
                Cell::Keep
            }
        },
    );
    b.chimney(-10, 4, 26, 38, 0, wh + 38);
    b.prop("sacs", 6, [w / 2 - 30, 0, d + 12], 0);
    b.prop("charrette", 2, [14, 0, d + 26], 0);
    b.prop("tonneau", 5, [w - 10, 0, d + 6], 0);
    let _ = (isqrt(1), VoxelValue::AIR);
    r.center()
}
