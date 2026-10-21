//! Les DÉTAILS de fonction ajoutés à une maison pour en faire une taverne, une boulangerie ou une mairie : enseigne
//! et terrasse, four à pain extérieur, lanterneau d'horloge. Tout est posé dans le repère du plan de la maison
//! (devant = z croissant) à partir de ses façades ; chaque détail est refusé s'il tomberait dans le bâtiment.

use std::sync::Arc;

use super::parts::Ctx;
use super::planner::roof_at;
use crate::batiments::kit::matieres::{Matieres, Ton, bois, pierre, ton, val};
use crate::batiments::kit::plan::Part;
use crate::batiments::kit::prims::{Cell, RulePart, TransformPart, in_ellipsoid};
use crate::batiments::kit::rng::hh;
use crate::props::PropBuilder;

/// Les parties ajoutées pour la fonction `kind` (vide : aucune).
pub fn extras(ctx: &Arc<Ctx>, kind: &str, m: Matieres) -> Vec<Box<dyn Part>> {
    match kind {
        "taverne" => taverne(ctx, m),
        "boulangerie" => boulangerie(ctx, m),
        "mairie" => mairie(ctx, m),
        _ => Vec::new(),
    }
}

fn prop(m: Matieres, seed: u64, f: impl Fn(&mut PropBuilder)) -> Vec<Box<dyn Part>> {
    let mut b = PropBuilder::new(m, 50, seed);
    f(&mut b);
    b.finish()
}

/// Enseigne sur poteau devant la porte, tables et bancs de terrasse, tonneaux.
fn taverne(ctx: &Arc<Ctx>, m: Matieres) -> Vec<Box<dyn Part>> {
    let p = &ctx.plan;
    let mut v: Vec<Box<dyn Part>> = Vec::new();
    let w = p.params.door.w;
    let (x, z) = p.dfr.xz(p.du0 + w + 30, -36);
    v.push(Box::new(TransformPart::new(
        prop(m, 2, PropBuilder::enseigne),
        [x, 0, z],
        0,
    )));
    for (k, du) in [-62, -86].into_iter().enumerate() {
        let (tx, tz) = p.dfr.xz(p.du0 + du, -26);
        if (-12..=12)
            .step_by(6)
            .any(|a| p.in_f(tx + a, tz + 14) || p.in_f(tx + a, tz - 14))
            || p.dfr.len < 40
        {
            continue;
        }
        v.push(Box::new(TransformPart::new(
            prop(m, 5 + k as u64, PropBuilder::table),
            [tx, 0, tz],
            0,
        )));
        v.push(Box::new(TransformPart::new(
            prop(m, 6, PropBuilder::banc),
            [tx, 0, tz + 12],
            0,
        )));
        v.push(Box::new(TransformPart::new(
            prop(m, 7, PropBuilder::banc),
            [tx, 0, tz - 12],
            2,
        )));
    }
    v
}

/// Four à pain extérieur : dôme de pierre, bouche noircie, conduit, tas de bois.
fn boulangerie(ctx: &Arc<Ctx>, m: Matieres) -> Vec<Box<dyn Part>> {
    let p = &ctx.plan;
    let side = if p.params.chimney == super::params::Side::E {
        1
    } else {
        0
    };
    let fr = super::planner::Frame::new(0, &p.bodies[0], side);
    let (cx, cz) = fr.xz(fr.len / 2 + 6, -17);
    let c = [100 * cx + 50, 0, 100 * cz + 50];
    let r = [1500, 1150, 1300];
    let mut v: Vec<Box<dyn Part>> = Vec::new();
    v.push(RulePart::boxed(
        [cx - 17, 0, cz - 17],
        [cx + 18, 24, cz + 18],
        move |x, y, z| {
            if !in_ellipsoid(x, y, z, c, r)
                || in_ellipsoid(x, y, z, [c[0], c[1], c[2] + 250], [1100, 800, 1000])
            {
                return Cell::Keep;
            }
            Cell::Put(pierre(
                m.stone_grey,
                1 + (hh(x.div_euclid(3), y.div_euclid(3), z.div_euclid(3), 41) % 126) as u8,
            ))
        },
    ));
    // bouche de four, vers l'avant (z croissant), noircie
    v.push(RulePart::boxed(
        [cx - 5, 1, cz + 8],
        [cx + 6, 9, cz + 18],
        move |x, y, z| {
            let a = 100 * (x - cx) + 50;
            let b = 100 * y + 50 - 320;
            if (a * a / 4 + b * b) < 380 * 380 && b > -340 {
                if in_ellipsoid(x, y, z, c, [r[0] - 200, r[1] - 200, r[2] - 200]) || z > cz + 9 {
                    return Cell::Air;
                }
                Cell::Keep
            } else if z > cz + 8 && (a * a / 4 + b * b) < 560 * 560 {
                Cell::Put(val(m.coal, 12))
            } else {
                Cell::Keep
            }
        },
    ));
    v.push(RulePart::boxed(
        [cx - 2, 18, cz - 2],
        [cx + 2, 34, cz + 2],
        move |x, y, z| {
            let _ = (x, z);
            Cell::Put(pierre(m.stone_dark, 1 + (hh(x, y, z, 42) % 100) as u8))
        },
    ));
    let (tx, tz) = fr.xz(fr.len / 2 - 18, -12);
    v.push(Box::new(TransformPart::new(
        prop(m, 4, PropBuilder::tas_bois),
        [tx, 0, tz],
        1,
    )));
    v
}

/// Lanterneau d'horloge sur le faîtage : base de pierre, claire-voie, cadran, flèche et girouette.
fn mairie(ctx: &Arc<Ctx>, m: Matieres) -> Vec<Box<dyn Part>> {
    let p = &ctx.plan;
    let b = &p.bodies[0];
    let (cx, cz) = ((b.x0 + b.x1) / 2, (b.z0 + b.z1) / 2);
    let Some(top) = roof_at(b, cx, cz, p.hw, p.params.roof.eave, p.params.roof.slope100).map(|r| r.top)
    else {
        return Vec::new();
    };
    let (h0, w) = (top - 3, 9);
    let mut v: Vec<Box<dyn Part>> = Vec::new();
    // base carrée de pierre (4 voxels de haut), puis colonnes d'angle et claire-voie
    v.push(RulePart::boxed(
        [cx - w - 2, h0, cz - w - 2],
        [cx + w + 2, h0 + 34, cz + w + 3],
        move |x, y, z| {
            let (a, c) = ((x - cx).abs(), (z - cz).abs());
            let k = y - h0;
            if k < 4 {
                return if a <= w + 1 && c <= w + 1 {
                    Cell::Put(pierre(
                        m.stone_grey,
                        1 + (hh(x / 3, y / 2, z / 3, 43) % 126) as u8,
                    ))
                } else {
                    Cell::Keep
                };
            }
            if k < 24 {
                let coin = a >= w - 1 && a <= w && c >= w - 1 && c <= w;
                let cadre = a <= w && c <= w && (a >= w - 1 || c >= w - 1);
                if coin {
                    return Cell::Put(bois(m.timber, 1, 6));
                }
                // claire-voie : lattes verticales sur les faces, sauf le cadran au sud
                if cadre && (x + z).rem_euclid(3) == 0 && k > 6 {
                    return Cell::Put(bois(m.timber, 1, 4));
                }
                if k == 24 - 1 && a <= w && c <= w {
                    return Cell::Put(bois(m.timber, 0, 5));
                }
            }
            Cell::Keep
        },
    ));
    // cadran au sud (z croissant)
    let (fy, fz) = (h0 + 15, cz + w + 1);
    v.push(RulePart::boxed(
        [cx - 7, fy - 7, fz],
        [cx + 8, fy + 8, fz + 2],
        move |x, y, z| {
            let (dx, dy) = (100 * (x - cx), 100 * (y - fy));
            let d2 = dx * dx + dy * dy;
            if z != fz || d2 > 640 * 640 {
                return Cell::Keep;
            }
            if d2 > 540 * 540 {
                return Cell::Put(val(m.brass, 70));
            }
            // aiguilles : heures et minutes
            let h = (x - cx == 0 && y > fy && y < fy + 5) || (y - fy == 0 && x > cx && x < cx + 4);
            if h {
                Cell::Put(val(m.iron, 20))
            } else {
                Cell::Put(val(m.wax, 100))
            }
        },
    ));
    // flèche pyramidale en bardeaux et girouette
    let base = h0 + 24;
    v.push(RulePart::boxed(
        [cx - w - 3, base, cz - w - 3],
        [cx + w + 4, base + 30, cz + w + 4],
        move |x, y, z| {
            let (a, c) = ((x - cx).abs(), (z - cz).abs());
            let k = y - base;
            let r = w + 2 - k * (w + 2) / 24;
            if k < 24 && a.max(c) <= r && a.max(c) >= r - 1 {
                return Cell::Put(val(m.slate, 24 + (hh(x, y, z, 44) % 40) as u8));
            }
            if (24..30).contains(&k) && a == 0 && c == 0 {
                return Cell::Put(val(m.iron, 30));
            }
            if k == 28 && a <= 3 && c == 0 && x >= cx {
                return Cell::Put(ton(m.brass, Ton::Moyen));
            }
            Cell::Keep
        },
    ));
    v
}
