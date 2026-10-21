//! Les ROCHERS et le relief ponctuel (L37) : galets, blocs, dalles, falaises à strates, menhirs et cromlechs, ruines
//! (pan de mur, colonne brisée), entrées de grotte, arches naturelles. Un seul générateur `rock` ; chaque recette est
//! une règle de voxels (ellipsoïdes bruités, strates, tranches) tirée de la graine, avec le bruit de valeur entier
//! de la trousse : même position, même voxel, quel que soit le découpage en chunks.

// Les recettes sont des PORTS fidèles de règles écrites en coordonnées entières : les bornes explicites
// (`a >= 5 && a < 10`) restent lisibles comme dans le générateur d'origine.
#![allow(
    clippy::manual_range_contains,
    clippy::too_many_arguments,
    clippy::needless_range_loop,
    clippy::collapsible_if,
    clippy::int_plus_one,
    clippy::identity_op
)]

use std::sync::Arc;

use em_core::MaterialId;
use serde::{Deserialize, Serialize};

use crate::batiments::ids;
use crate::batiments::kit::matieres::{Matieres, bois, pierre, val};
use crate::batiments::kit::noise::vnoise3;
use crate::batiments::kit::plan::{Placement, ShapePlan};
use crate::batiments::kit::prims::{Cell, in_ellipsoid};
use crate::batiments::kit::rng::hh;
use crate::error::GenError;
use crate::generator::{GenParams, GenPlan, Generator, GeneratorId};
use crate::props::PropBuilder;

/// Les recettes de rochers (noms stables).
pub const KINDS: &[&str] = &[
    "galets",
    "bloc",
    "dalle",
    "falaise",
    "menhir",
    "cromlech",
    "ruine_mur",
    "colonne_brisee",
    "grotte",
    "arche",
];

/// Configuration de la recette de rocher.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct RockConfig {
    /// Nom de la recette (`KINDS`).
    pub kind: String,
    /// Roche : `grise`, `chaude` ; vide : tirée de la graine.
    pub rock: String,
}

impl Default for RockConfig {
    fn default() -> Self {
        Self {
            kind: "bloc".into(),
            rock: String::new(),
        }
    }
}

impl RockConfig {
    /// Paramètres de générateur de cette configuration.
    pub fn to_params(&self) -> Result<GenParams, GenError> {
        GenParams::json(ids::ROCK, 1, self)
    }
}

/// Le générateur de rochers.
#[derive(Clone, Debug)]
pub struct RockGenerator {
    matieres: Matieres,
}

/// Teinte d'une pierre numérotée pour une couche (strate) et un bloc de largeur `lg`.
fn piece(c: MaterialId, strate: i32, x: i32, z: i32, lg: i32) -> em_core::VoxelValue {
    pierre(
        c,
        1 + (hh(strate, x.div_euclid(lg.max(1)), z.div_euclid(lg.max(1)), 91) % 126) as u8,
    )
}

impl RockGenerator {
    /// Crée le générateur.
    pub fn new(matieres: Matieres) -> Self {
        Self { matieres }
    }

    /// Construit le plan d'un rocher.
    pub fn build(&self, cfg: &RockConfig, seed: u64) -> Result<ShapePlan, GenError> {
        let m = self.matieres;
        let mut b = PropBuilder::new(m, 50, seed);
        let roche = match cfg.rock.as_str() {
            "grise" => m.rock_grey,
            "chaude" => m.rock_warm,
            "" => {
                if b.pick(1, 2) == 0 {
                    m.rock_grey
                } else {
                    m.rock_warm
                }
            }
            autre => {
                return Err(GenError::BadParams(format!(
                    "roche « {autre} » inconnue (grise, chaude)"
                )));
            }
        };
        let s = (seed as i32).wrapping_mul(31).wrapping_add(7);
        match cfg.kind.as_str() {
            "galets" => galets(&mut b, roche, s),
            "bloc" => bloc(&mut b, roche, s),
            "dalle" => dalle(&mut b, roche, s),
            "falaise" => falaise(&mut b, roche, s),
            "menhir" => menhir(&mut b, roche, s),
            "cromlech" => cromlech(&mut b, roche, s),
            "ruine_mur" => ruine_mur(&mut b, s),
            "colonne_brisee" => colonne_brisee(&mut b, s),
            "grotte" => grotte(&mut b, roche, s),
            "arche" => arche(&mut b, roche, s),
            autre => {
                return Err(GenError::BadParams(format!(
                    "rocher « {autre} » inconnu (disponibles : {})",
                    KINDS.join(", ")
                )));
            }
        }
        let placement = Placement {
            mirror_z: true,
            ..Placement::IDENTITE
        };
        Ok(ShapePlan::new(b.finish(), placement, 50, m.priority()))
    }
}

/// Bruit signé -n..n (voxels) autour de 0 pour une position et une échelle.
fn bruit(x: i32, y: i32, z: i32, cell: i32, amp: i32, s: i32) -> i32 {
    (i64::from(vnoise3(x, y, z, cell, s)) * i64::from(2 * amp + 1) / 65_536) as i32 - amp
}

fn mousse(m: &Matieres, x: i32, y: i32, z: i32) -> em_core::VoxelValue {
    val(m.moss, 42 + (hh(x, y, z, 5) % 55) as u8)
}

/// Un galet : ellipsoïde lisse de rayons (rx, ry, rz) en centièmes, posé et à moitié enterré.
fn galet(b: &mut PropBuilder, c: [i32; 3], r: [i32; 3], roche: MaterialId, s: i32) {
    let m = b.m;
    let lo = [
        (c[0] - r[0]).div_euclid(100) - 1,
        (c[1] - r[1]).div_euclid(100).max(0),
        (c[2] - r[2]).div_euclid(100) - 1,
    ];
    let hi = [
        (c[0] + r[0]).div_euclid(100) + 2,
        (c[1] + r[1]).div_euclid(100) + 2,
        (c[2] + r[2]).div_euclid(100) + 2,
    ];
    b.rule(lo, hi, move |x, y, z| {
        if y < 0 || !in_ellipsoid(x, y, z, c, r) {
            return Cell::Keep;
        }
        // un voxel de mousse sur le dessus abrité
        if y * 100 + 50 > c[1] + r[1] * 6 / 10 && hh(x, y, z, s) % 100 < 22 {
            return Cell::Put(mousse(&m, x, y, z));
        }
        Cell::Put(pierre(roche, 1 + (hh(c[0] / 50, c[2] / 50, 3, 92) % 126) as u8))
    });
}

fn galets(b: &mut PropBuilder, roche: MaterialId, s: i32) {
    let n = 6 + b.pick(2, 4) as i32;
    for i in 0..n {
        let h = hh(s, i, 5, 6);
        let (x, z) = ((h % 40) as i32 - 20, ((h >> 8) % 36) as i32 - 18);
        let rr = 250 + (hh(s, i, 6, 6) % 380) as i32;
        galet(
            b,
            [100 * x + 50, rr / 3, 100 * z + 50],
            [rr, rr * 6 / 10, rr * 8 / 10],
            roche,
            s,
        );
    }
}

/// Bloc erratique : ellipsoïde bruité aux facettes franches, mousse au sommet, fentes.
fn bloc(b: &mut PropBuilder, roche: MaterialId, s: i32) {
    let m = b.m;
    let (rx, ry, rz) = (
        1500 + (b.pick(3, 9) as i32) * 100,
        1100 + (b.pick(4, 6) as i32) * 100,
        1300 + (b.pick(5, 7) as i32) * 100,
    );
    let c = [0, ry * 55 / 100, 0];
    let r = [rx, ry, rz];
    b.rule(
        [-rx / 100 - 3, 0, -rz / 100 - 3],
        [rx / 100 + 4, ry / 100 * 2 + 4, rz / 100 + 4],
        move |x, y, z| {
            let rr = [
                r[0] + 70 * bruit(x, y, z, 7, 5, s),
                r[1] + 70 * bruit(x, y, z, 6, 4, s + 1),
                r[2] + 70 * bruit(x, y, z, 7, 5, s + 2),
            ];
            if y < 0 || !in_ellipsoid(x, y, z, c, rr) {
                return Cell::Keep;
            }
            let fente =
                (x * 3 + z * 2 + 400).rem_euclid(23) == 0 && y > 4 && hh(y / 3, 0, s, 9).is_multiple_of(3);
            if fente {
                return Cell::Keep;
            }
            let haut = in_ellipsoid(x, y + 3, z, c, rr) && !in_ellipsoid(x, y + 4, z, c, rr);
            if (haut || y * 100 > c[1] + rr[1] * 55 / 100) && vnoise3(x, y, z, 5, s + 3) > 25_000 {
                return Cell::Put(mousse(&m, x, y, z));
            }
            Cell::Put(piece(roche, y.div_euclid(6), x, z, 9))
        },
    );
}

/// Dalles : deux ou trois dalles posées sur chant ou à plat, légèrement inclinées.
fn dalle(b: &mut PropBuilder, roche: MaterialId, s: i32) {
    let m = b.m;
    let n = 2 + b.pick(2, 2) as i32;
    for i in 0..n {
        let (w, d, e) = (
            22 + (hh(s, i, 1, 2) % 16) as i32,
            14 + (hh(s, i, 2, 2) % 12) as i32,
            4 + (hh(s, i, 3, 2) % 3) as i32,
        );
        let (ox, oz) = (i * 9 - 10, i * 7 - 6);
        let pente = (hh(s, i, 4, 2) % 7) as i32 - 3;
        b.rule(
            [ox - w / 2 - 1, i * 3, oz - d / 2 - 1],
            [ox + w / 2 + 2, i * 3 + e + 12, oz + d / 2 + 2],
            move |x, y, z| {
                let (a, c) = (x - ox, z - oz);
                let base = i * 3 + a * pente / 10;
                if a.abs() > w / 2 - (c * c) / (d * 3).max(1) || c.abs() > d / 2 - (a * a) / (w * 4).max(1) {
                    return Cell::Keep;
                }
                if y >= base && y < base + e {
                    if y == base + e - 1 && hh(x, y, z, s) % 100 < 18 {
                        return Cell::Put(mousse(&m, x, y, z));
                    }
                    return Cell::Put(piece(roche, i * 10 + y, x, z, 7));
                }
                Cell::Keep
            },
        );
    }
}

/// Falaise à strates : face irrégulière, bancs de tons alternés, surplombs, éboulis au pied, coiffe d'herbe moussue.
fn falaise(b: &mut PropBuilder, roche: MaterialId, s: i32) {
    let m = b.m;
    let (w, h, d) = (120, 84 + 6 * b.pick(2, 4) as i32, 44);
    b.rule(
        [-w / 2 - 6, 0, -d / 2 - 6],
        [w / 2 + 7, h + 10, d / 2 + 14],
        move |x, y, z| {
            // profil du haut de la falaise et face avant : z croît vers l'avant
            let haut = h - 10 + bruit(x, 0, 0, 14, 8, s) + bruit(x, 3, z, 5, 2, s + 1);
            let avant = -d / 2 + 18 + bruit(x, y, 0, 9, 6, s + 2) + (y * 18 / h.max(1)) - ((y % 20) / 4)
                + if (y / 7) % 3 == 0 { 3 } else { 0 };
            // pied d'éboulis : talus qui remonte
            let talus = y * 100 / 14;
            let eboul = y < 14
                && z >= avant - 8 + talus / 12
                && z < avant + 14 - y / 2
                && hh(x / 3, y / 2, z / 3, s) % 100 < 80;
            let dans = y <= haut && z >= -d / 2 && z <= avant + 10 && z >= avant - 40;
            let arriere = z >= -d / 2;
            let _ = arriere;
            let plein = y <= haut && z >= avant - 40 && z <= avant + 0 && z >= -d / 2;
            let _ = dans;
            if plein || eboul && !plein {
                if eboul && !plein {
                    return Cell::Put(pierre(roche, 1 + (hh(x / 4, y / 3, z / 4, s) % 126) as u8));
                }
                // coiffe : herbe et mousse sur le dessus
                if y >= haut - 1 {
                    return Cell::Put(val(m.turf, 30 + (hh(x, y, z, 3) % 40) as u8));
                }
                if y >= haut - 3 && hh(x, y, z, 4) % 100 < 20 {
                    return Cell::Put(val(m.dirt, 30 + (hh(x, y, z, 5) % 30) as u8));
                }
                let strate = y / 8 + bruit(x, 0, 0, 20, 1, s + 7);
                let moussu = y % 8 == 7 && hh(x / 2, y, z, 6) % 100 < 28 && z > avant - 6;
                if moussu {
                    return Cell::Put(mousse(&m, x, y, z));
                }
                return Cell::Put(piece(roche, strate, x, z / 3, 11));
            }
            Cell::Keep
        },
    );
}

/// Menhir : monolithe effilé, façonné par le bruit, mousse au pied, cupules.
fn menhir(b: &mut PropBuilder, roche: MaterialId, s: i32) {
    let m = b.m;
    let h = 64 + 5 * b.pick(2, 6) as i32;
    b.rule([-9, 0, -8], [10, h + 2, 9], move |x, y, z| {
        let t = y * 100 / h;
        let (rx, rz) = (
            5 * (130 - t / 2 * 7 / 10 - t * 3 / 10) / 100 + 2 + bruit(y / 2, 0, 0, 8, 1, s),
            4 * (125 - t * 6 / 10) / 100 + 1 + bruit(0, y / 2, 0, 9, 1, s + 1),
        );
        let (dx, dz) = (100 * x + 50 + 40 * bruit(y, 0, 0, 22, 2, s), 100 * z + 50);
        let e2 = i64::from(dx).pow(2) * 100 / i64::from((rx.max(1) * 100).pow(2))
            + i64::from(dz).pow(2) * 100 / i64::from((rz.max(1) * 100).pow(2));
        if y >= h - (x.abs() * 3 / 2).min(3) || e2 > 100 {
            return Cell::Keep;
        }
        if y < 10 && vnoise3(x, y, z, 4, s + 3) > 24_000 || (y < h - 6 && hh(x, y, z, 7) % 1000 < 6) {
            return Cell::Put(mousse(&m, x, y, z));
        }
        Cell::Put(piece(roche, y / 9, x, z, 6))
    });
}

/// Cromlech : cercle de cinq à sept pierres levées de tailles voisines.
fn cromlech(b: &mut PropBuilder, roche: MaterialId, s: i32) {
    let n = 5 + b.pick(2, 3) as i32;
    for i in 0..n {
        let a = i * 65_536 / n;
        let (c, sn) = (
            crate::batiments::kit::intmath::cos100(a),
            crate::batiments::kit::intmath::sin100(a),
        );
        let (px, pz) = (c * 26 / 100, sn * 26 / 100);
        let h = 22 + (hh(s, i, 1, 3) % 16) as i32;
        let lm = b.m;
        b.rule([px - 5, 0, pz - 4], [px + 6, h + 1, pz + 5], move |x, y, z| {
            let (dx, dz) = (x - px, z - pz);
            let r = 4 - y * 2 / h.max(1);
            if y < h - dx.abs() / 2 && dx.abs() <= r + 1 && dz.abs() <= r - 1 + i32::from(y < 6) {
                if y < 5 && hh(x, y, z, 2) % 100 < 35 {
                    return Cell::Put(mousse(&lm, x, y, z));
                }
                return Cell::Put(piece(roche, i * 7 + y / 8, x, z, 5));
            }
            Cell::Keep
        });
    }
    b.rule([-12, 0, -12], [13, 2, 13], move |x, y, z| {
        if y == 0 && x * x + z * z < 120 && hh(x, y, z, 9) % 100 < 30 {
            Cell::Put(val(b_turf(), 40 + (hh(x, 0, z, 2) % 30) as u8))
        } else {
            Cell::Keep
        }
    });
}

fn b_turf() -> MaterialId {
    Matieres::standard().turf
}

/// Pan de mur en ruine : appareil de pierre, haut en dents de scie, fenêtre à demi écroulée, lierre, pierres tombées.
fn ruine_mur(b: &mut PropBuilder, s: i32) {
    let m = b.m;
    let (w, h) = (64 + b.pick(2, 4) as i32 * 4, 46);
    let courses = crate::batiments::maison::planner::Courses::from_seed(&format!("ruine{s}"));
    b.rule([-w / 2 - 2, 0, -4], [w / 2 + 3, h + 2, 5], move |x, y, z| {
        let top = h - 6 + bruit(x, 0, 0, 7, 12, s) - ((x.abs() - w / 3).max(0) * 3 / 2);
        if y >= top.max(8) || z.abs() > 3 {
            return Cell::Keep;
        }
        // fenêtre cintrée à demi effondrée
        let (a, c) = (x - 6, y - 20);
        let fen = a.abs() < 7 && (c < 14 || a * a + (c - 14) * (c - 14) < 49) && c >= 0;
        if fen && z.abs() <= 3 {
            return Cell::Air;
        }
        let d = 3 - z;
        if (3..6).contains(&(z + 3)) && false {
            return Cell::Keep;
        }
        if hh(x / 5, y / 3, 2, s) % 100 < 5 && y > 14 {
            return Cell::Keep;
        }
        match courses.stone(x + 330, y, d.min(3), 0, true) {
            Some(n) => {
                if y > 6 && vnoise3(x, y, z, 6, s + 3) > 36_000 {
                    return Cell::Put(mousse(&m, x, y, z));
                }
                Cell::Put(pierre(m.stone_grey, n.max(1)))
            }
            None => Cell::Keep,
        }
    });
    // pierres tombées
    for i in 0..5 {
        let (x, z) = (
            (hh(s, i, 8, 1) % 60) as i32 - 30,
            6 + (hh(s, i, 9, 1) % 10) as i32,
        );
        b.bx(
            (x, x + 5),
            (0, 3),
            (z, z + 4),
            crate::props::Tex::Block(m.stone_grey, 3),
        );
    }
    // lierre : traînées de mousse sur le mur
    b.rule([-w / 2, 0, 2], [w / 2, h, 6], move |x, y, z| {
        let trainee =
            vnoise3(x, 0, 0, 5, s + 9) > 40_000 && y < 8 + (vnoise3(x, 7, 7, 9, s) >> 11) as i32 && z == 3;
        if trainee && hh(x, y, z, 3) % 100 < 75 {
            Cell::Put(mousse(&m, x, y, z))
        } else {
            Cell::Keep
        }
    });
}

/// Colonne brisée : socle, fût cannelé tronqué en biseau, tambours renversés au sol.
fn colonne_brisee(b: &mut PropBuilder, s: i32) {
    let m = b.m;
    let h = 38 + 4 * b.pick(2, 5) as i32;
    b.rule([-9, 0, -9], [10, h + 4, 10], move |x, y, z| {
        let d2 = 100 * (x * x + z * z) + 50;
        let socle = y < 5 && x.abs() <= 8 && z.abs() <= 8;
        if socle {
            return Cell::Put(pierre(m.stone_grey, 1 + (hh(x / 3, y, z / 3, 3) % 100) as u8));
        }
        // cannelures : le rayon varie avec l'angle (huit rainures)
        let a = em_core::q16::atan2_turns(
            em_core::Q16::from_raw(i64::from(z) * 100 + 1),
            em_core::Q16::from_raw(i64::from(x) * 100 + 1),
        )
        .raw();
        let rainure = (a * 16 / 65_536).rem_euclid(2) == 0;
        let r = 560 - if rainure { 40 } else { 0 };
        let rr = (r * (100 - (y - 5).max(0) * 8 / h.max(1)) / 100) as i64;
        let cassure = h + (x * 4 + z * 2) / 5 - 6;
        if (y >= 5 || socle) && i64::from(d2) <= rr * rr && y < cassure.min(h) {
            if y > 5 && vnoise3(x, y, z, 5, s) > 44_000 {
                return Cell::Put(mousse(&m, x, y, z));
            }
            return Cell::Put(pierre(m.stone_grey, 1 + (hh(y / 8, 0, s, 4) % 120) as u8));
        }
        Cell::Keep
    });
    // tambour renversé (cylindre couché le long de x) et chapiteau
    b.rule([8, 0, -6], [34, 12, 8], move |x, y, z| {
        let (dy, dz) = (100 * (y - 5) + 50, 100 * (z - 1) + 50);
        let d2 = i64::from(dy * dy + dz * dz);
        if x < 30 && d2 <= 520 * 520 {
            Cell::Put(pierre(m.stone_grey, 1 + (hh(x / 6, 0, s, 5) % 100) as u8))
        } else {
            Cell::Keep
        }
    });
    b.bx(
        (-24, -14),
        (0, 6),
        (-8, 3),
        crate::props::Tex::Block(m.stone_grey, 4),
    );
}

/// Entrée de grotte : butte de roche, ouverture en arc, galerie creusée, étais de bois, éboulis et mousse.
fn grotte(b: &mut PropBuilder, roche: MaterialId, s: i32) {
    let m = b.m;
    let (rx, ry, rz) = (3600, 2900, 3200);
    let c = [0, 800, -1200];
    b.rule([-40, 0, -44], [41, 60, 20], move |x, y, z| {
        let rr = [
            rx + 60 * bruit(x, y, z, 8, 6, s),
            ry + 60 * bruit(x, y, z, 7, 5, s + 1),
            rz + 60 * bruit(x, y, z, 8, 6, s + 2),
        ];
        if y < 0 || !in_ellipsoid(x, y, z, c, rr) {
            return Cell::Keep;
        }
        // galerie : arc de 26 de large et 26 de haut, profondeur 30
        let (a, hy) = (x, y);
        let arc = a.abs() < 13 && (hy < 14 || a * a + (hy - 14) * (hy - 14) < 169) && z >= -30 + (hy / 3);
        if arc {
            return Cell::Air;
        }
        // dessus : herbe et mousse
        let dessus = !in_ellipsoid(x, y + 3, z, c, rr);
        if dessus && hh(x, y, z, 2) % 100 < 70 {
            return Cell::Put(val(m.turf, 28 + (hh(x, y, z, 3) % 40) as u8));
        }
        if (y < 6 || dessus) && vnoise3(x, y, z, 5, s + 4) > 30_000 {
            return Cell::Put(mousse(&m, x, y, z));
        }
        Cell::Put(piece(roche, y.div_euclid(7), x, z, 9))
    });
    // étais de bois à l'entrée
    let zf = 8;
    b.bx((-15, -12), (0, 24), (zf, zf + 3), crate::props::Tex::Timber(1));
    b.bx((12, 15), (0, 24), (zf, zf + 3), crate::props::Tex::Timber(1));
    b.bx((-16, 16), (22, 26), (zf, zf + 3), crate::props::Tex::Timber(0));
    for i in 0..6 {
        let (x, z) = (
            (hh(s, i, 1, 8) % 50) as i32 - 25,
            12 + (hh(s, i, 2, 8) % 9) as i32,
        );
        b.bx(
            (x, x + 4),
            (0, 2 + (i % 3)),
            (z, z + 3),
            crate::props::Tex::Block(roche, 3),
        );
    }
    let _ = bois(m.timber, 0, 0);
}

/// Arche naturelle : deux piliers et un linteau courbe, creusés par le bruit.
fn arche(b: &mut PropBuilder, roche: MaterialId, s: i32) {
    let m = b.m;
    let (rx, ry) = (4400, 3900);
    b.rule([-48, 0, -14], [49, 44, 15], move |x, y, z| {
        let ep = 11 + bruit(x, y, 0, 9, 3, s) - (z.abs() * z.abs()) / 24;
        if z.abs() > ep.max(3) {
            return Cell::Keep;
        }
        let ext = in_ellipsoid(
            x + bruit(0, y, z, 7, 2, s),
            y,
            0,
            [0, 0, 50],
            [
                rx + 100 * bruit(x, y, 0, 8, 3, s),
                ry + 100 * bruit(x, y, 0, 8, 3, s + 1),
                4000,
            ],
        );
        let int = in_ellipsoid(
            x,
            y,
            0,
            [0, 0, 50],
            [
                2300 + 100 * bruit(x, y, 0, 9, 2, s + 2),
                2200 + 100 * bruit(x, y, 0, 9, 2, s + 3),
                4000,
            ],
        );
        if !ext || int || y < 0 {
            return Cell::Keep;
        }
        if y > 33 && hh(x, y, z, 2) % 100 < 40 {
            return Cell::Put(val(m.turf, 30 + (hh(x, y, z, 3) % 40) as u8));
        }
        if y < 5 && vnoise3(x, y, z, 5, s + 4) > 30_000 {
            return Cell::Put(mousse(&m, x, y, z));
        }
        Cell::Put(piece(roche, y.div_euclid(6) + (x > 0) as i32 * 3, x, z, 8))
    });
}

impl Generator for RockGenerator {
    fn id(&self) -> GeneratorId {
        ids::ROCK
    }

    fn version(&self) -> u32 {
        1
    }

    fn plan(&self, params: &GenParams, seed: u64) -> Result<Arc<dyn GenPlan>, GenError> {
        let cfg: RockConfig = params.decode_json(ids::ROCK)?;
        Ok(Arc::new(self.build(&cfg, seed)?))
    }
}
