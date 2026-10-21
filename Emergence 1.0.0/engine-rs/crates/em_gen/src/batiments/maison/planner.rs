//! Le PLANIFICATEUR de la maison : port de la première moitié de `build(P)` de « nouvelle référence.html » -- tout ce
//! qui décide, rien de ce qui peint. Il produit un `HousePlan` : emprise, distance au vide, hauteur du toit, table des
//! assises de pierre, porte, escalier, cheminée, appentis, fenêtres, cloisons et portes intérieures, pièces, meubles.
//!
//! L'ordre des tirages du hasard (`JsRng`) est celui du JavaScript, tirage par tirage : un seul de plus et toute la
//! maison change. Les tableaux 2D (emprise, distances, hauteur du toit, occupation des pièces) sont des données de
//! PLAN (une cellule par colonne), jamais des voxels.

mod furnish;

use super::furniture::Kind;
use super::params::{HouseParams, PlanKind, Side, WallStyle};
use crate::batiments::kit::intmath::{isqrt, round_div};
use crate::batiments::kit::rng::{JsRng, hh, hh_below, hh_lt, hs};

/// Couches de sol sous le zéro (le JavaScript les compte dans sa grille).
pub const G: i32 = 6;
/// Épaisseur des murs.
pub const T: i32 = 6;
/// Hauteur d'un étage.
pub const SH: i32 = 54;
/// Hauteur du soubassement de pierre.
pub const PL: i32 = 8;
/// Épaisseur du toit.
pub const TH: i32 = 6;
/// Épaisseur d'une cloison.
pub const TP: i32 = 3;
/// Largeur d'une porte intérieure.
pub const DW: i32 = 14;
/// Hauteur d'une porte intérieure.
pub const DHT: i32 = 36;
/// Largeur de la cage d'escalier.
pub const SW: i32 = 30;
/// Nombre de marches.
pub const NS: i32 = 14;
const VMAX: usize = 320;
const UM: usize = 1100;
/// Marge de la grille de plan autour de l'emprise.
pub const MG: i32 = 64;
/// Valeur « pas de toit » de la hauteur de toit.
pub const SANS_TOIT: i32 = -32_000;

/// Un corps de bâtiment (le principal ou l'aile).
#[derive(Copy, Clone, Debug, PartialEq, Eq)]
pub struct Body {
    /// Mur ouest (inclus).
    pub x0: i32,
    /// Mur est (exclu).
    pub x1: i32,
    /// Mur nord (inclus).
    pub z0: i32,
    /// Mur sud (exclu).
    pub z1: i32,
    /// Vrai pour le corps principal (faîtage selon x), faux pour l'aile (faîtage selon z).
    pub main: bool,
    /// Sens de l'aile (+1 sud, -1 nord).
    pub dir: i32,
    /// Emprise du toit.
    pub rx0: i32,
    /// Emprise du toit.
    pub rx1: i32,
    /// Emprise du toit.
    pub rz0: i32,
    /// Emprise du toit.
    pub rz1: i32,
}

/// Une façade : repère local (u le long, d la profondeur vers l'intérieur, d < 0 dehors). f : 0 est, 1 ouest,
/// 2 sud, 3 nord.
#[derive(Copy, Clone, Debug, PartialEq, Eq)]
pub struct Frame {
    /// Numéro du corps.
    pub b: u8,
    /// Face.
    pub f: u8,
    /// Longueur de la façade.
    pub len: i32,
    x0: i32,
    x1: i32,
    z0: i32,
    z1: i32,
}

impl Frame {
    /// Façade `f` du corps `b` (numéro `bi`).
    pub fn new(bi: u8, b: &Body, f: u8) -> Self {
        Self {
            b: bi,
            f,
            len: if f < 2 { b.z1 - b.z0 } else { b.x1 - b.x0 },
            x0: b.x0,
            x1: b.x1,
            z0: b.z0,
            z1: b.z1,
        }
    }

    /// Cellule (x, z) du point (u, d).
    #[inline]
    pub fn xz(&self, u: i32, d: i32) -> (i32, i32) {
        match self.f {
            0 => (self.x1 - 1 - d, self.z1 - 1 - u),
            1 => (self.x0 + d, self.z0 + u),
            2 => (self.x0 + u, self.z1 - 1 - d),
            _ => (self.x1 - 1 - u, self.z0 + d),
        }
    }

    /// Vecteur unitaire de u dans le plan (x, z).
    pub fn u_vec(&self) -> (i32, i32) {
        let a = self.xz(0, 0);
        let b = self.xz(1, 0);
        (b.0 - a.0, b.1 - a.1)
    }
}

/// Cloison intérieure.
#[derive(Copy, Clone, Debug, PartialEq, Eq)]
pub struct Cut {
    /// 0 : cloison le long de z (position c0..c1 en x) ; 1 : le long de x.
    pub ax: u8,
    /// Début de l'épaisseur.
    pub c0: i32,
    /// Fin de l'épaisseur.
    pub c1: i32,
    /// Début de la longueur.
    pub a0: i32,
    /// Fin de la longueur.
    pub a1: i32,
    /// Début de la porte le long de la cloison.
    pub door: i32,
}

/// Cage d'escalier.
#[derive(Copy, Clone, Debug, PartialEq, Eq)]
pub struct Strip {
    /// Début en x.
    pub sx0: i32,
    /// Fin en x.
    pub sx1: i32,
    /// Cloison de la cage (début).
    pub p0: i32,
    /// Sens de montée en z.
    pub dir: i32,
    /// Porte de la cage.
    pub d0: i32,
}

/// Une fenêtre retenue.
#[derive(Copy, Clone, Debug, PartialEq, Eq)]
pub struct WinSpec {
    /// Façade.
    pub fr: Frame,
    /// Début le long de la façade.
    pub u0: i32,
    /// Hauteur du bas.
    pub v0: i32,
    /// Étage.
    pub s: i32,
}

/// Un œil-de-bœuf de pignon.
#[derive(Copy, Clone, Debug, PartialEq, Eq)]
pub struct Vent {
    /// Façade.
    pub fr: Frame,
    /// Centre.
    pub uc: i32,
    /// Hauteur du bas.
    pub v0: i32,
}

/// Une porte intérieure.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct IntDoor {
    /// Étage.
    pub s: i32,
    /// Axe de la cloison.
    pub ax: u8,
    /// Début de l'épaisseur.
    pub c0: i32,
    /// Fin de l'épaisseur.
    pub c1: i32,
    /// Début de la porte.
    pub d: i32,
    /// Cellules de passage.
    pub xz: Vec<(i32, i32)>,
}

/// Type d'une pièce.
#[derive(Copy, Clone, Debug, PartialEq, Eq)]
pub enum RoomType {
    /// Couloir d'escalier.
    Hall,
    /// Séjour.
    Living,
    /// Cuisine.
    Kitchen,
    /// Réserve.
    Store,
    /// Chambre.
    Bedroom,
    /// Bureau.
    Study,
}

/// Une pièce.
#[derive(Clone, Debug)]
pub struct Room {
    /// Numéro.
    pub id: usize,
    /// Étage.
    pub s: i32,
    /// Boîte englobante (x0, x1, z0, z1).
    pub bx: [i32; 4],
    /// Cellules (indices de grille) dans l'ordre du remplissage.
    pub cells: Vec<usize>,
    /// Ancres de passage.
    pub anch: Vec<usize>,
    /// Type.
    pub kind: Option<RoomType>,
    base: Option<(bool, i32)>,
    kit: bool,
    bed: bool,
}

/// Une transformation affine locale -> monde : (x, z) = o + i * iv + k * kv.
#[derive(Copy, Clone, Debug, PartialEq, Eq)]
pub struct Affine {
    /// Origine.
    pub o: (i32, i32),
    /// Image de l'axe i.
    pub iv: (i32, i32),
    /// Image de l'axe k.
    pub kv: (i32, i32),
}

impl Affine {
    #[inline]
    fn at(&self, i: i32, k: i32) -> (i32, i32) {
        (
            self.o.0 + i * self.iv.0 + k * self.kv.0,
            self.o.1 + i * self.iv.1 + k * self.kv.1,
        )
    }
}

/// Une chose posée dans l'intérieur, dans l'ordre du JavaScript (le dernier qui écrit gagne).
#[derive(Clone, Debug)]
pub enum Deco {
    /// Un meuble.
    Item {
        /// Type.
        kind: Kind,
        /// Tirage de la pose (0..1000).
        q: i32,
        /// Placement.
        map: Affine,
        /// Hauteur du pied (étage * SH + j0).
        base: i32,
        /// Bois de la pièce (0..4).
        tone: u8,
    },
    /// Un tapis : cellules (x, z, distance au bord, rond) à peindre sous réserve de vide.
    Rug {
        /// Hauteur du sol.
        base: i32,
        /// Couleur (0..4).
        color: u8,
        /// Cellules (x, z, e) : e est la distance au bord (rectangle) ou le rayon restant (rond).
        cells: Vec<(i32, i32, i32)>,
    },
    /// Une lampe (suspension ronde ou lanterne carrée).
    Lamp {
        /// Cellule sous la lampe.
        x: i32,
        /// Cellule sous la lampe.
        z: i32,
        /// Hauteur du plafond.
        vc: i32,
        /// Suspension ronde (séjour, grandes pièces).
        round: bool,
    },
}

/// Table des assises de pierre : hauteur de chaque assise et position des joints verticaux (tirées du hasard).
#[derive(Clone, Debug)]
pub struct Courses {
    cv: Vec<u16>,
    cf: Vec<u16>,
    ch: Vec<u16>,
    sid: Vec<Vec<u16>>,
    sb: Vec<Vec<i32>>,
}

impl Courses {
    /// Table d'assises tirée d'une graine texte (pour les bâtiments autres que la maison).
    pub fn from_seed(seed: &str) -> Self {
        Self::tirer(&mut JsRng::new(hs(seed)))
    }

    /// Tire la table (ordre exact du JavaScript : hauteur de l'assise, décalage, longueurs des pierres).
    fn tirer(r: &mut JsRng) -> Self {
        let mut cv = vec![0_u16; VMAX];
        let mut cf = vec![0_u16; VMAX];
        let mut ch = Vec::new();
        let mut sid = Vec::new();
        let mut sb_all = Vec::new();
        let (mut v, mut c) = (0_usize, 0_usize);
        while v < VMAX {
            let h = if (v as i32) < PL {
                PL as usize
            } else {
                5 + r.below(4) as usize
            };
            for k in 0..h {
                if v + k < VMAX {
                    cv[v + k] = c as u16;
                    cf[v + k] = k as u16;
                }
            }
            ch.push(h as u16);
            let mut s = vec![0_u16; UM];
            let mut sb: Vec<i32> = Vec::new();
            let mut p = -(r.below(24) as i32);
            sb.push(p);
            while p < UM as i32 + 40 {
                p += if c > 0 {
                    // (9 + R() * 11) | 0
                    9 + r.below(11) as i32
                } else {
                    18 + r.below(10) as i32
                };
                sb.push(p);
            }
            let mut idx = 0;
            for (u, cell) in s.iter_mut().enumerate() {
                while sb[idx + 1] <= u as i32 {
                    idx += 1;
                }
                *cell = idx as u16;
            }
            sid.push(s);
            sb_all.push(sb);
            v += h;
            c += 1;
        }
        Self {
            cv,
            cf,
            ch,
            sid,
            sb: sb_all,
        }
    }

    /// Cellule de pierre à (u, v, d) : `None` (rien), `Some(0)` mortier, `Some(n)` pièce n (1..127).
    /// `ex` : retrait supplémentaire (colombage), `solid` : pas de retrait (cheminée).
    pub fn stone(&self, u: i32, v: i32, d: i32, ex: i32, solid: bool) -> Option<u8> {
        let vi = v.clamp(0, VMAX as i32 - 1) as usize;
        let c = self.cv[vi] as usize;
        let cf = i32::from(self.cf[vi]);
        let h = i32::from(self.ch[c]);
        let ui = u.clamp(0, UM as i32 - 1) as usize;
        let s = self.sid[c][ui] as usize;
        let (a, b) = (self.sb[c][s], self.sb[c][s + 1]);
        let mut r = if hh_lt(hh(c as i32, s as i32, 7, 0), 35) {
            0
        } else {
            1
        };
        let mut mortier = false;
        if cf == 0 || u == a {
            r = 2;
            mortier = true;
        } else if (u == a + 1 || u == b - 1) && (cf == 1 || cf == h - 1) {
            r += 1;
        }
        r += ex;
        if d < r && !solid {
            return None;
        }
        if mortier {
            return Some(0);
        }
        Some(1 + (hh(c as i32, s as i32, 1, 0) % 126) as u8)
    }

    /// Jouvence de la table : numéro de la pierre (pour la teinte de la nuance), `(assise, rang)` d'un point.
    pub fn stone_id(&self, u: i32, v: i32) -> (i32, i32) {
        let vi = v.clamp(0, VMAX as i32 - 1) as usize;
        let c = self.cv[vi] as usize;
        let ui = u.clamp(0, UM as i32 - 1) as usize;
        (c as i32, i32::from(self.sid[c][ui]))
    }
}

/// Un sol d'étage ou de plafond à ne pas peindre (trou d'escalier) -- réponse de `inHole`.
#[derive(Copy, Clone, Debug)]
struct Occ {
    b: u8,
    f: u8,
    u0: i32,
    u1: i32,
    vm: i32,
}

/// Appui du JavaScript : `FT` (zones de façade à garder libres de cloisons).
#[derive(Copy, Clone, Debug)]
struct Ft {
    b: u8,
    f: u8,
    u0: i32,
    u1: i32,
    s: i32,
}

/// Le plan complet d'une maison.
#[derive(Clone, Debug)]
pub struct HousePlan {
    /// Paramètres dérivés.
    pub params: HouseParams,
    /// Corps (principal puis aile).
    pub bodies: Vec<Body>,
    /// Hauteur des murs sous le toit (étages x SH).
    pub hw: i32,
    /// Nombre d'étages.
    pub st: i32,
    /// Origine de la grille de plan (x).
    pub ox: i32,
    /// Origine de la grille de plan (z).
    pub oz: i32,
    /// Largeur de la grille de plan.
    pub nx: i32,
    /// Profondeur de la grille de plan.
    pub nz: i32,
    /// Emprise (1 dans le bâtiment).
    pub fm: Vec<u8>,
    /// Distance au vide (1 = face extérieure) jusqu'à T+1 ; 0 à l'intérieur.
    pub ds: Vec<u8>,
    /// Face du mur le plus proche (0 est, 1 ouest, 2 sud, 3 nord) : index de voisin 0..3.
    pub fc: Vec<u8>,
    /// Bas du toit par colonne (`SANS_TOIT` hors toit).
    pub rb: Vec<i32>,
    /// Assises de pierre.
    pub courses: Courses,
    /// Façade de la porte d'entrée.
    pub dfr: Frame,
    /// Début de la porte le long de sa façade.
    pub du0: i32,
    /// x du centre de la porte.
    pub dxw: i32,
    /// z du bord sud du corps de la porte.
    pub dz1: i32,
    /// Escalier.
    pub strip: Option<Strip>,
    /// Trou d'escalier (début en z).
    pub hz0: i32,
    /// Trou d'escalier (fin en z).
    pub hz1: i32,
    /// Façade de la cheminée.
    pub cfr: Frame,
    /// Centre de la cheminée sur sa façade.
    pub chim_uc: i32,
    /// Haut de la cheminée.
    pub chim_top: i32,
    /// Appentis : (façade, début, fin).
    pub shed: Option<(Frame, i32, i32)>,
    /// Fenêtres retenues.
    pub wins: Vec<WinSpec>,
    /// Œils-de-bœuf.
    pub vents: Vec<Vent>,
    /// Cloisons par étage.
    pub cuts: [Vec<Cut>; 2],
    /// Portes intérieures.
    pub int_doors: Vec<IntDoor>,
    /// Pièces.
    pub rooms: Vec<Room>,
    /// Numéro de pièce par cellule et par étage (-1 : aucune).
    pub rm: [Vec<i16>; 2],
    /// Décors intérieurs dans l'ordre de pose.
    pub decos: Vec<Deco>,
    /// Nombre de meubles.
    pub n_furniture: i32,
    /// Nombre de lits.
    pub n_beds: i32,
    /// Nombre de cuisines.
    pub n_kitchens: i32,
    /// Nombre de lumières.
    pub n_lights: i32,
    /// Hauteur maximale des murs avec toit (pour les bornes).
    pub top_y: i32,
}

impl HousePlan {
    /// Indice de grille d'une cellule.
    #[inline]
    pub fn ix(&self, x: i32, z: i32) -> usize {
        ((z + self.oz) * self.nx + x + self.ox) as usize
    }

    /// Vrai si (x, z) est dans l'emprise.
    #[inline]
    pub fn in_f(&self, x: i32, z: i32) -> bool {
        let (gx, gz) = (x + self.ox, z + self.oz);
        gx >= 0 && gz >= 0 && gx < self.nx && gz < self.nz && self.fm[(gz * self.nx + gx) as usize] == 1
    }

    /// Vrai si la cellule est dans le volume intérieur (hors épaisseur des murs).
    #[inline]
    pub fn intr(&self, x: i32, z: i32) -> bool {
        let (gx, gz) = (x + self.ox, z + self.oz);
        if gx < 0 || gz < 0 || gx >= self.nx || gz >= self.nz {
            return false;
        }
        let i = (gz * self.nx + gx) as usize;
        self.fm[i] == 1 && (self.ds[i] == 0 || i32::from(self.ds[i]) > T)
    }

    /// Vrai si (x, z) est dans le trou d'escalier de l'étage 1.
    #[inline]
    pub fn in_hole(&self, x: i32, z: i32) -> bool {
        match &self.strip {
            Some(s) => x >= s.sx0 && x < s.sx1 && z >= self.hz0 && z < self.hz1,
            None => false,
        }
    }

    /// La pièce de l'étage `s` qui contient la cellule (x, z).
    pub fn room_at(&self, s: usize, x: i32, z: i32) -> Option<usize> {
        let id = *self.rm[s].get(self.ix(x, z))?;
        (id >= 0).then_some(id as usize)
    }

    /// Nombre de portes intérieures.
    pub fn interior_door_count(&self) -> usize {
        self.int_doors.len()
    }
}

/// Planifie la maison de ces paramètres.
pub fn planifier(params: &HouseParams) -> HousePlan {
    Planner::new(params).run()
}

struct Planner {
    p: HouseParams,
    r: JsRng,
    bodies: Vec<Body>,
    st: i32,
    hw: i32,
    ev: i32,
    sl100: i32,
    ox: i32,
    oz: i32,
    nx: i32,
    nz: i32,
    fm: Vec<u8>,
    ds: Vec<u8>,
    fc: Vec<u8>,
    rb: Vec<i32>,
    occ: Vec<Occ>,
    ft: Vec<Ft>,
    // intérieur
    pmc: [Vec<u8>; 2],
    pmd: [Vec<u8>; 2],
    occ2: [Vec<u8>; 2],
    oh: [Vec<i32>; 2],
    rm: [Vec<i16>; 2],
    ins: Vec<u8>,
    rooms: Vec<Room>,
    decos: Vec<Deco>,
    wood_tone: u8,
    n_fur: i32,
    n_bed: i32,
    n_kit: i32,
    strip: Option<Strip>,
    hz0: i32,
    hz1: i32,
}

impl Planner {
    fn new(p: &HouseParams) -> Self {
        let r = JsRng::new(hs(&format!("{}/d", p.seed)));
        let st = p.stories;
        Self {
            p: p.clone(),
            r,
            bodies: Vec::new(),
            st,
            hw: st * SH,
            ev: p.roof.eave,
            sl100: p.roof.slope100,
            ox: 0,
            oz: 0,
            nx: 0,
            nz: 0,
            fm: Vec::new(),
            ds: Vec::new(),
            fc: Vec::new(),
            rb: Vec::new(),
            occ: Vec::new(),
            ft: Vec::new(),
            pmc: [Vec::new(), Vec::new()],
            pmd: [Vec::new(), Vec::new()],
            occ2: [Vec::new(), Vec::new()],
            oh: [Vec::new(), Vec::new()],
            rm: [Vec::new(), Vec::new()],
            ins: Vec::new(),
            rooms: Vec::new(),
            decos: Vec::new(),
            wood_tone: 0,
            n_fur: 0,
            n_bed: 0,
            n_kit: 0,
            strip: None,
            hz0: 0,
            hz1: 0,
        }
    }

    #[inline]
    fn ix(&self, x: i32, z: i32) -> usize {
        ((z + self.oz) * self.nx + x + self.ox) as usize
    }

    #[inline]
    fn in_f(&self, x: i32, z: i32) -> bool {
        let (gx, gz) = (x + self.ox, z + self.oz);
        gx >= 0 && gz >= 0 && gx < self.nx && gz < self.nz && self.fm[(gz * self.nx + gx) as usize] == 1
    }

    fn intr(&self, x: i32, z: i32) -> bool {
        let (gx, gz) = (x + self.ox, z + self.oz);
        if gx < 0 || gz < 0 || gx >= self.nx || gz >= self.nz {
            return false;
        }
        let i = (gz * self.nx + gx) as usize;
        self.fm[i] == 1 && (self.ds[i] == 0 || i32::from(self.ds[i]) > T)
    }

    fn in_hole(&self, x: i32, z: i32) -> bool {
        match &self.strip {
            Some(s) => x >= s.sx0 && x < s.sx1 && z >= self.hz0 && z < self.hz1,
            None => false,
        }
    }

    fn stair_z0(&self) -> i32 {
        match &self.strip {
            Some(s) => {
                let m = &self.bodies[0];
                if s.dir > 0 { T + 14 } else { m.z1 - T - 14 - 4 * NS }
            }
            None => 0,
        }
    }

    fn in_stair(&self, x: i32, z: i32) -> bool {
        match &self.strip {
            Some(s) => x >= s.sx0 && x < s.sx1 && z >= self.stair_z0() && z < self.stair_z0() + 4 * NS,
            None => false,
        }
    }

    fn frame(&self, b: usize, f: u8) -> Frame {
        Frame::new(b as u8, &self.bodies[b], f)
    }

    fn ext(&self, fr: &Frame, u0: i32, u1: i32) -> bool {
        for u in u0..u1 {
            if u < 0 || u >= fr.len {
                return false;
            }
            let a = fr.xz(u, 0);
            let b = fr.xz(u, -1);
            if !self.in_f(a.0, a.1) || self.in_f(b.0, b.1) {
                return false;
            }
        }
        true
    }

    fn free_out(&self, fr: &Frame, u0: i32, u1: i32, dd: i32) -> bool {
        let mut u = u0;
        while u < u1 {
            for d in 1..=dd {
                let p = fr.xz(u, -d);
                if self.in_f(p.0, p.1) {
                    return false;
                }
            }
            u += 2;
        }
        true
    }

    fn busy(&self, fr: &Frame, u0: i32, u1: i32, v: i32) -> bool {
        self.occ
            .iter()
            .any(|o| o.b == fr.b && o.f == fr.f && u1 > o.u0 && u0 < o.u1 && v < o.vm)
    }

    fn mark(&mut self, fr: &Frame, u0: i32, u1: i32, vm: i32) {
        self.occ.push(Occ {
            b: fr.b,
            f: fr.f,
            u0,
            u1,
            vm,
        });
    }

    fn u_range(&self, b: usize, f: u8, c0: i32, c1: i32) -> (i32, i32) {
        let bb = &self.bodies[b];
        match f {
            2 => (c0 - bb.x0, c1 - bb.x0),
            3 => (bb.x1 - c1, bb.x1 - c0),
            0 => (bb.z1 - c1, bb.z1 - c0),
            _ => (c0 - bb.z0, c1 - bb.z0),
        }
    }

    fn rnd(&mut self, a: i32, b: i32) -> i32 {
        a + self.r.below((b - a + 1) as u32) as i32
    }

    /// `pickD(a0, a1, forb)`.
    fn pick_d(&mut self, a0: i32, a1: i32, forb: &[(i32, i32)]) -> Option<i32> {
        let mut c = Vec::new();
        let mut k = a0 + 4;
        while k <= a1 - 4 - DW {
            if !forb.iter().any(|f| k - 2 < f.1 && k + DW + 2 > f.0) {
                c.push(k);
            }
            k += 2;
        }
        if c.is_empty() {
            None
        } else {
            let i = self.r.below(c.len() as u32) as usize;
            Some(c[i])
        }
    }

    fn roof_bot(&self, b: &Body, x: i32, z: i32) -> Option<i32> {
        roof_at(b, x, z, self.hw, self.ev, self.sl100).map(|r| r.bot)
    }

    fn run(mut self) -> HousePlan {
        let p = self.p.clone();
        let (m, wg, st, hw, ev, rk) = (p.main, p.wing, self.st, self.hw, p.roof.eave, p.roof.rake);
        // ---- volumes
        let mut main_b = Body {
            x0: 0,
            x1: m.w,
            z0: 0,
            z1: m.d,
            main: true,
            dir: 0,
            rx0: -rk,
            rx1: m.w + rk,
            rz0: -ev,
            rz1: m.d + ev,
        };
        let mut bodies = vec![main_b];
        if p.plan != PlanKind::Rect {
            let x0 = if p.plan == PlanKind::T {
                (m.w - wg.w) >> 1
            } else if wg.at != 0 {
                m.w - wg.w
            } else {
                0
            };
            let (z0, z1) = if wg.dir > 0 {
                (m.d - 24, m.d + wg.len)
            } else {
                (-wg.len, 24)
            };
            let mut b = Body {
                x0,
                x1: x0 + wg.w,
                z0,
                z1,
                main: false,
                dir: wg.dir,
                rx0: 0,
                rx1: 0,
                rz0: 0,
                rz1: 0,
            };
            let hwid = (b.x1 - b.x0) / 2;
            b.rx0 = b.x0 - ev;
            b.rx1 = b.x1 + ev;
            if b.dir > 0 {
                b.rz0 = m.d - hwid - 6;
                b.rz1 = b.z1 + rk;
            } else {
                b.rz0 = b.z0 - rk;
                b.rz1 = hwid + 6;
            }
            bodies.push(b);
        }
        main_b = bodies[0];
        self.bodies = bodies;
        let x0 = self.bodies.iter().map(|b| b.rx0).min().unwrap_or(0);
        let x1 = self.bodies.iter().map(|b| b.rx1).max().unwrap_or(0);
        let z0 = self.bodies.iter().map(|b| b.rz0).min().unwrap_or(0);
        let z1 = self.bodies.iter().map(|b| b.rz1).max().unwrap_or(0);
        self.ox = MG - x0;
        self.oz = MG - z0;
        self.nx = x1 - x0 + 2 * MG;
        self.nz = z1 - z0 + 2 * MG;
        let cells = (self.nx * self.nz) as usize;
        self.fm = vec![0; cells];
        let bodies = self.bodies.clone();
        for b in &bodies {
            for z in b.z0..b.z1 {
                for x in b.x0..b.x1 {
                    let i = self.ix(x, z);
                    self.fm[i] = 1;
                }
            }
        }
        // ---- distance au vide et face (BFS à 4 voisins, ordre de file du JavaScript)
        self.ds = vec![0; cells];
        self.fc = vec![0; cells];
        let nx = self.nx as isize;
        let d4: [isize; 4] = [1, -1, nx, -nx];
        let mut file: Vec<usize> = Vec::new();
        for i in 0..cells {
            if self.fm[i] == 1 {
                for (k, dd) in d4.iter().enumerate() {
                    let j = (i as isize + dd) as usize;
                    if self.fm[j] == 0 {
                        self.ds[i] = 1;
                        self.fc[i] = k as u8;
                        file.push(i);
                        break;
                    }
                }
            }
        }
        let mut h = 0;
        while h < file.len() {
            let i = file[h];
            h += 1;
            if i32::from(self.ds[i]) > T {
                continue;
            }
            for dd in &d4 {
                let j = (i as isize + dd) as usize;
                if self.fm[j] == 1 && self.ds[j] == 0 {
                    self.ds[j] = self.ds[i] + 1;
                    self.fc[j] = self.fc[i];
                    file.push(j);
                }
            }
        }
        // ---- porte : position
        let db = if p.plan != PlanKind::Rect && wg.dir > 0 {
            1
        } else {
            0
        };
        let dfr = self.frame(db, 2);
        let dr = p.door;
        let mut du0 = 16.max((dfr.len - dr.w - 16).min(round_div((dfr.len - dr.w) * dr.at100, 100)));
        let cs = p.chimney;
        let s_w = cs == Side::E;
        let mx0 = T;
        let mx1 = m.w - T;
        let mz0 = T;
        let mz1 = m.d - T;
        // ---- géométrie intérieure : cage d'escalier, cloison de jonction
        let mut strip: Option<Strip> = None;
        if st > 1 {
            let dir = if self.bodies.len() > 1 {
                if self.bodies[1].dir > 0 { -1 } else { 1 }
            } else if self.r.half() {
                1
            } else {
                -1
            };
            let mut s = Strip {
                sx0: if s_w { mx0 } else { mx1 - 16 },
                sx1: if s_w { mx0 + 16 } else { mx1 },
                p0: if s_w { mx0 + SW } else { mx1 - SW - TP },
                dir,
                d0: 0,
            };
            s.d0 = self.pick_d(mz0, mz1, &[]).unwrap_or(0);
            strip = Some(s);
        }
        self.strip = strip;
        let rr0 = if strip.is_some() && s_w {
            mx0 + SW + TP
        } else {
            mx0
        };
        let rr1 = if strip.is_some() && !s_w {
            mx1 - SW - TP
        } else {
            mx1
        };
        if strip.is_some() && db == 0 {
            let lo = if s_w { mx0 + SW + TP + 4 } else { 16 };
            let hi = if s_w {
                dfr.len - dr.w - 16
            } else {
                mx1 - SW - TP - 4 - dr.w
            };
            du0 = lo.max(hi.min(du0));
        }
        if let Some(s) = &strip {
            self.hz0 = if s.dir > 0 { mz0 + 22 } else { mz1 - 14 - 4 * NS };
            self.hz1 = if s.dir > 0 { mz0 + 14 + 4 * NS } else { mz1 - 22 };
        }
        let dxw = dfr.xz(du0 + (dr.w >> 1), 0).0;
        let dz1 = self.bodies[db].z1;
        let jun = if self.bodies.len() > 1 {
            let wb = self.bodies[1];
            Some((1_usize, if wb.dir > 0 { mz1 } else { mz0 - TP }))
        } else {
            None
        };
        let mut jd0 = 0;
        if let Some(s) = &strip {
            let (a, b2) = if s_w {
                (0, mx0 + SW + TP + 4)
            } else {
                (mx1 - SW - TP - 4, m.w)
            };
            for f in [2_u8, 3] {
                let rg = self.u_range(0, f, a, b2);
                let fr = self.frame(0, f);
                self.mark(&fr, rg.0, rg.1, 999);
            }
            let fr = self.frame(0, if s_w { 1 } else { 0 });
            self.mark(&fr, 0, 10_000, 999);
            let _ = s;
        }
        if let Some((wbi, jc0)) = jun {
            let wb = self.bodies[wbi];
            let forb: Vec<(i32, i32)> = match &strip {
                Some(s) => vec![(s.p0 - 3, s.p0 + TP + 3)],
                None => vec![],
            };
            jd0 = match self.pick_d(wb.x0 + T + 2, wb.x1 - T - 2, &forb) {
                Some(v) => v,
                None => {
                    let span = wb.x1 - wb.x0 - 2 * T - 12 - DW + 1;
                    wb.x0 + T + 6 + self.r.below(span.max(0) as u32) as i32
                }
            };
            for f in [0_u8, 1] {
                let rg = self.u_range(wbi, f, jc0 - 5, jc0 + TP + 5);
                let fr = self.frame(wbi, f);
                self.mark(&fr, rg.0, rg.1, 999);
            }
            let fj = if wb.dir > 0 { 2 } else { 3 };
            let rg = self.u_range(0, fj, jd0 - 4, jd0 + DW + 4);
            self.ft.push(Ft {
                b: 0,
                f: fj,
                u0: rg.0,
                u1: rg.1,
                s: -1,
            });
        }
        // ---- toit : bas par colonne
        self.rb = vec![SANS_TOIT; cells];
        for bi in 0..self.bodies.len() {
            let b = self.bodies[bi];
            for z in b.rz0..b.rz1 {
                for x in b.rx0..b.rx1 {
                    if let Some(bot) = self.roof_bot(&b, x, z) {
                        let i = self.ix(x, z);
                        if bot > self.rb[i] {
                            self.rb[i] = bot;
                        }
                    }
                }
            }
        }
        // ---- assises de pierre (tirages !)
        let courses = Courses::tirer(&mut self.r);
        // ---- porte : marque
        self.mark(&dfr, du0 - 22, du0 + dr.w + 22, 999);
        // ---- cheminée
        let cfr = self.frame(0, if s_w { 0 } else { 1 });
        let chim_uc = cfr.len >> 1;
        let rise = (self.sl100 * m.d + 199) / 200;
        let chim_top = hw + TH - 1 + rise + 12;
        self.mark(&cfr, chim_uc - 26, chim_uc + 26, 999);
        self.ft.push(Ft {
            b: 0,
            f: cfr.f,
            u0: chim_uc - 30,
            u1: chim_uc + 30,
            s: -1,
        });
        // ---- appentis à bois
        let sfr = self.frame(0, if s_w { 1 } else { 0 });
        let ls = 72.min(sfr.len - 50);
        let ds_ = 34;
        let mut shed = None;
        if p.shed && ls >= 40 {
            for us in [(sfr.len - ls) >> 1, 8.max(sfr.len - ls - 14), 14] {
                if self.ext(&sfr, us, us + ls) && self.free_out(&sfr, us, us + ls, ds_ + 2) {
                    shed = Some((sfr, us, us + ls));
                    break;
                }
            }
        }
        if let Some((fr, us, ue)) = &shed {
            let fr = *fr;
            self.mark(&fr, us - 8, ue + 8, SH);
        }
        // ---- fenêtres
        self.ft.push(Ft {
            b: db as u8,
            f: 2,
            u0: du0 - 8,
            u1: du0 + dr.w + 8,
            s: 0,
        });
        let win = p.win;
        let mut wins: Vec<WinSpec> = Vec::new();
        let mut vents: Vec<Vent> = Vec::new();
        let mut n_lights = 0;
        for bi in 0..self.bodies.len() {
            let b = self.bodies[bi];
            for f in 0..4_u8 {
                let fr = self.frame(bi, f);
                let n = 1.max(round_div(fr.len, win.gap));
                let gab = if b.main { f < 2 } else { f >= 2 };
                for s in 0..st {
                    for k in 0..n {
                        let uc = round_div((2 * k + 1) * fr.len, 2 * n);
                        let u0 = uc - (win.w >> 1);
                        let v0 = s * SH + win.sill;
                        let mg = if win.shutters { (win.w >> 1) + 6 } else { 6 };
                        if u0 - mg < 8
                            || u0 + win.w + mg > fr.len - 8
                            || !self.ext(&fr, u0 - mg, u0 + win.w + mg)
                            || !self.free_out(&fr, u0 - mg, u0 + win.w + mg, 6)
                            || self.busy(&fr, u0 - mg, u0 + win.w + mg, v0)
                        {
                            continue;
                        }
                        let mut ok = true;
                        let mut u = u0;
                        while u < u0 + win.w && ok {
                            for d in T..=T + 2 {
                                let q = fr.xz(u, d);
                                if !self.intr(q.0, q.1) {
                                    ok = false;
                                }
                            }
                            u += 2;
                        }
                        if !ok {
                            continue;
                        }
                        wins.push(WinSpec { fr, u0, v0, s });
                        self.ft.push(Ft {
                            b: bi as u8,
                            f,
                            u0: u0 - 6,
                            u1: u0 + win.w + 6,
                            s,
                        });
                        if bi == db
                            && f == 2
                            && n_lights < 3
                            && hh_lt(hh(b.x0 + u0, v0, i32::from(f), 17), win.lit100 as u32)
                        {
                            n_lights += 1;
                        }
                    }
                }
                if gab {
                    let uc = fr.len >> 1;
                    let v0 = hw + 8;
                    if !self.busy(&fr, uc - 12, uc + 12, v0) && self.ext(&fr, uc - 8, uc + 8) {
                        vents.push(Vent { fr, uc, v0 });
                    }
                }
            }
        }
        // ---- cloisons
        let mut cuts: [Vec<Cut>; 2] = [Vec::new(), Vec::new()];
        for s in 0..st as usize {
            if let Some(sp) = &strip {
                cuts[s].push(Cut {
                    ax: 0,
                    c0: sp.p0,
                    c1: sp.p0 + TP,
                    a0: mz0,
                    a1: mz1,
                    door: sp.d0,
                });
            }
            if let Some((wbi, jc0)) = jun {
                let wb = self.bodies[wbi];
                cuts[s].push(Cut {
                    ax: 1,
                    c0: jc0,
                    c1: jc0 + TP,
                    a0: wb.x0,
                    a1: wb.x1,
                    door: jd0,
                });
            }
            let mut c1: Option<Cut> = None;
            if rr1 - rr0 >= 70 && (s == 0 || self.r.percent(80)) {
                let mut t = 0;
                while t < 12 && c1.is_none() {
                    let px = self.rnd(rr0 + 32, rr1 - 32 - TP);
                    let mut c = Cut {
                        ax: 0,
                        c0: px,
                        c1: px + TP,
                        a0: mz0,
                        a1: mz1,
                        door: 0,
                    };
                    if !self.conflict(&c, s as i32, mx1, mz1, mx0, mz0) {
                        if let Some(d) = self.pick_d(mz0, mz1, &[]) {
                            c.door = d;
                            c1 = Some(c);
                        }
                    }
                    t += 1;
                }
            }
            if let Some(c) = c1 {
                cuts[s].push(c);
            }
            if self.r.percent(60) {
                let pcs: Vec<(i32, i32)> = match &c1 {
                    Some(c) => vec![(rr0, c.c0), (c.c1, rr1)],
                    None => vec![(rr0, rr1)],
                };
                let (pa, pb) = pcs[self.r.below(pcs.len() as u32) as usize];
                if pb - pa >= 40 {
                    let mut forb: Vec<(i32, i32)> = Vec::new();
                    if let Some(sp) = &strip
                        && ((s_w && pa == rr0) || (!s_w && pb == rr1))
                    {
                        forb.push((sp.d0 - 3, sp.d0 + DW + 3));
                    }
                    if let Some(c) = &c1
                        && (pa == c.c1 || pb == c.c0)
                    {
                        forb.push((c.door - 3, c.door + DW + 3));
                    }
                    for _ in 0..12 {
                        let pz = self.rnd(mz0 + 30, mz1 - 30 - TP);
                        if forb.iter().any(|f| pz < f.1 && pz + TP > f.0) {
                            continue;
                        }
                        let mut c = Cut {
                            ax: 1,
                            c0: pz,
                            c1: pz + TP,
                            a0: pa,
                            a1: pb,
                            door: 0,
                        };
                        if self.conflict(&c, s as i32, mx1, mz1, mx0, mz0) {
                            continue;
                        }
                        if let Some(d) = self.pick_d(pa, pb, &[]) {
                            c.door = d;
                            cuts[s].push(c);
                            break;
                        }
                    }
                }
            }
        }
        let _ = main_b;
        // ---- portes intérieures : sens d'ouverture (tirages) puis pièces
        let mut int_doors: Vec<IntDoor> = Vec::new();
        self.pmc = [vec![0; cells], vec![0; cells]];
        for s in 0..st as usize {
            for c in cuts[s].clone() {
                // fillCut : deux tirages (hi, sg) pour la charnière
                let _hi = self.r.half();
                let _sg = self.r.half();
                let (xr, zr) = if c.ax == 0 {
                    ((c.c0, c.c1), (c.a0, c.a1))
                } else {
                    ((c.a0, c.a1), (c.c0, c.c1))
                };
                for z in zr.0..zr.1 {
                    for x in xr.0..xr.1 {
                        if !self.intr(x, z) {
                            continue;
                        }
                        let i = self.ix(x, z);
                        self.pmc[s][i] = 1;
                    }
                }
                let d = c.door;
                for a in d - 2..d + DW + 2 {
                    for t in c.c0..c.c1 {
                        let (x, z) = if c.ax == 0 { (t, a) } else { (a, t) };
                        if !self.intr(x, z) {
                            continue;
                        }
                        if a >= d && a < d + DW {
                            let i = self.ix(x, z);
                            self.pmc[s][i] = 0;
                        }
                    }
                }
                let mut xz = Vec::new();
                for a in d..d + DW {
                    for t in c.c0..c.c1 {
                        let (x, z) = if c.ax == 0 { (t, a) } else { (a, t) };
                        if self.intr(x, z) {
                            xz.push((x, z));
                        }
                    }
                }
                int_doors.push(IntDoor {
                    s: s as i32,
                    ax: c.ax,
                    c0: c.c0,
                    c1: c.c1,
                    d,
                    xz,
                });
            }
        }
        // rampes (rail de l'escalier) : cellules du premier étage
        if let Some(sp) = strip {
            let rx = if s_w { sp.sx1 } else { sp.sx0 - 1 };
            let za = if sp.dir > 0 { self.hz0 - 1 } else { self.hz0 + 10 };
            let zb = if sp.dir > 0 { self.hz1 - 11 } else { self.hz1 };
            for z in za..=zb {
                let i = self.ix(rx, z);
                self.pmc[1][i] = 1;
            }
            let zr = if sp.dir > 0 { self.hz0 - 1 } else { self.hz1 };
            for x in sp.sx0..sp.sx1 {
                let i = self.ix(x, zr);
                self.pmc[1][i] = 1;
            }
        }
        // ---- pièces
        let hole_ok = |pl: &Planner, s: usize, x: i32, z: i32| -> bool {
            let c = pl.ix(x, z);
            pl.ins[c] == 1
                && pl.pmc[s][c] == 0
                && pl.pmd[s][c] == 0
                && !(s == 1 && pl.in_hole(x, z))
                && !(s == 0 && pl.in_stair(x, z))
        };
        self.ins = vec![0; cells];
        for i in 0..cells {
            if self.fm[i] == 1 && (self.ds[i] == 0 || i32::from(self.ds[i]) > T) {
                self.ins[i] = 1;
            }
        }
        self.pmd = [vec![0; cells], vec![0; cells]];
        for d in &int_doors {
            for (x, z) in &d.xz {
                let i = self.ix(*x, *z);
                self.pmd[d.s as usize][i] = 1;
            }
        }
        self.rm = [vec![-1; cells], vec![-1; cells]];
        self.occ2 = [vec![0; cells], vec![0; cells]];
        self.oh = [vec![0; cells], vec![0; cells]];
        let fx0 = self.bodies.iter().map(|b| b.x0).min().unwrap_or(0);
        let fx1 = self.bodies.iter().map(|b| b.x1).max().unwrap_or(0);
        let fz0 = self.bodies.iter().map(|b| b.z0).min().unwrap_or(0);
        let fz1 = self.bodies.iter().map(|b| b.z1).max().unwrap_or(0);
        for s in 0..st as usize {
            for z in fz0..fz1 {
                for x in fx0..fx1 {
                    let c = self.ix(x, z);
                    if self.rm[s][c] >= 0 || !hole_ok(&self, s, x, z) {
                        continue;
                    }
                    let id = self.rooms.len();
                    let mut rm = Room {
                        id,
                        s: s as i32,
                        bx: [x, x + 1, z, z + 1],
                        cells: Vec::new(),
                        anch: Vec::new(),
                        kind: None,
                        base: None,
                        kit: false,
                        bed: false,
                    };
                    let mut q = vec![c];
                    self.rm[s][c] = id as i16;
                    let mut h = 0;
                    while h < q.len() {
                        let k = q[h];
                        h += 1;
                        let kx = (k as i32 % self.nx) - self.ox;
                        let kz = (k as i32 / self.nx) - self.oz;
                        rm.cells.push(k);
                        rm.bx[0] = rm.bx[0].min(kx);
                        rm.bx[1] = rm.bx[1].max(kx + 1);
                        rm.bx[2] = rm.bx[2].min(kz);
                        rm.bx[3] = rm.bx[3].max(kz + 1);
                        for dd in &d4 {
                            let n = (k as isize + dd) as usize;
                            let (nx_, nz_) = ((n as i32 % self.nx) - self.ox, (n as i32 / self.nx) - self.oz);
                            if self.rm[s][n] < 0 && hole_ok(&self, s, nx_, nz_) {
                                self.rm[s][n] = id as i16;
                                q.push(n);
                            }
                        }
                    }
                    self.rooms.push(rm);
                }
            }
        }
        // ancres
        for d in &int_doors {
            let mid = d.d + DW / 2;
            let ds_ = d.s as usize;
            if d.ax == 0 {
                self.anchor(ds_, d.c0 - 2, mid);
                self.anchor(ds_, d.c1 + 1, mid);
            } else {
                self.anchor(ds_, mid, d.c0 - 2);
                self.anchor(ds_, mid, d.c1 + 1);
            }
        }
        let ec = dfr.xz(du0 + (dr.w >> 1), T + 3);
        self.anchor(0, ec.0, ec.1);
        // sens d'ouverture des portes : un tirage seulement en cas d'égalité des deux côtés
        for d in &int_doors {
            let mid = d.d + DW / 2;
            let s = d.s as usize;
            let (xa, za, xb, zb) = if d.ax == 0 {
                (d.c0 - 2, mid, d.c1 + 1, mid)
            } else {
                (mid, d.c0 - 2, mid, d.c1 + 1)
            };
            let area = |pl: &Planner, x: i32, z: i32| -> usize {
                let id = pl.rm[s][pl.ix(x, z)];
                if id < 0 {
                    0
                } else {
                    pl.rooms[id as usize].cells.len()
                }
            };
            let side = if area(&self, xb, zb) >= area(&self, xa, za) {
                1
            } else {
                -1
            };
            let (px, pz) = if side > 0 { (xb, zb) } else { (xa, za) };
            let run = |pl: &Planner, x: i32, z: i32, dx: i32, dz: i32| -> i32 {
                let mut n = 0;
                while n < 40 && {
                    let (xx, zz) = (x + dx * n, z + dz * n);
                    hole_ok(pl, s, xx, zz)
                } {
                    n += 1;
                }
                n
            };
            let (lo, hi) = if d.ax == 0 {
                (run(&self, px, d.d - 1, 0, -1), run(&self, px, d.d + DW, 0, 1))
            } else {
                (run(&self, d.d - 1, pz, -1, 0), run(&self, d.d + DW, pz, 1, 0))
            };
            let _low = lo < hi || (lo == hi && self.r.half());
        }
        // réservations
        for d in &int_doors {
            let s = d.s as usize;
            if d.ax == 0 {
                self.rsv(s, d.c0 - 16, d.c1 + 16, d.d - 1, d.d + DW + 1);
            } else {
                self.rsv(s, d.d - 1, d.d + DW + 1, d.c0 - 16, d.c1 + 16);
            }
        }
        self.rsv_f(0, &dfr, du0 - 1, du0 + dr.w + 1, T, T + 24, 2);
        for w in &wins {
            self.rsv_f(w.s as usize, &w.fr, w.u0 - 1, w.u0 + win.w + 1, T, T + 7, 4);
        }
        // foyer
        self.rsv_f(0, &cfr, chim_uc - 16, chim_uc + 16, T, T + 18, 2);
        self.rsv_f(0, &cfr, chim_uc - 14, chim_uc + 14, T, T + 7, 1);
        // ---- types de pièces
        let strip_hall = strip.map(|sp| {
            let start1 = (
                if s_w { sp.sx1 + 5 } else { sp.sx0 - 6 },
                (self.hz0 + self.hz1) >> 1,
            );
            self.ix(start1.0, start1.1)
        });
        let ent_c = self.ix(ec.0, ec.1);
        let mut wing_id: i32 = -1;
        if let Some((wbi, _)) = jun {
            let wb = self.bodies[wbi];
            let wx = (wb.x0 + wb.x1) >> 1;
            let wz = if wb.dir > 0 { wb.z1 - T - 8 } else { wb.z0 + T + 8 };
            wing_id = i32::from(self.rm[0][self.ix(wx, wz)]);
        }
        let mut bi = 0;
        for s in 0..st as usize {
            let mut rs: Vec<usize> = self
                .rooms
                .iter()
                .filter(|r| r.s as usize == s && r.cells.len() >= 150)
                .map(|r| r.id)
                .collect();
            rs.sort_by_key(|id| std::cmp::Reverse(self.rooms[*id].cells.len()));
            let mut kit = false;
            if s == 0 && wing_id >= 0 && wing_id != i32::from(self.rm[0][ent_c]) {
                self.rooms[wing_id as usize].kind = Some(RoomType::Kitchen);
                kit = true;
            }
            for id in rs {
                if self.rooms[id].kind.is_some() {
                    continue;
                }
                let hall = strip_hall.is_some_and(|hc| i32::from(self.rm[s][hc]) == id as i32);
                let kind = if hall {
                    RoomType::Hall
                } else if s == 0 && i32::from(self.rm[0][ent_c]) == id as i32 {
                    RoomType::Living
                } else if s == 0 && !kit {
                    kit = true;
                    RoomType::Kitchen
                } else if s == 0 && st > 1 {
                    RoomType::Store
                } else {
                    let k = if bi % 3 == 2 {
                        RoomType::Study
                    } else {
                        RoomType::Bedroom
                    };
                    bi += 1;
                    k
                };
                self.rooms[id].kind = Some(kind);
            }
        }
        // ---- mobilier
        self.furnish();
        let top_y = hw + TH + rise + 20;
        let _ = (x0, z1);
        HousePlan {
            params: p.clone(),
            bodies: self.bodies,
            hw,
            st,
            ox: self.ox,
            oz: self.oz,
            nx: self.nx,
            nz: self.nz,
            fm: self.fm,
            ds: self.ds,
            fc: self.fc,
            rb: self.rb,
            courses,
            dfr,
            du0,
            dxw,
            dz1,
            strip,
            hz0: self.hz0,
            hz1: self.hz1,
            cfr,
            chim_uc,
            chim_top,
            shed,
            wins,
            vents,
            cuts,
            int_doors,
            rooms: self.rooms,
            rm: self.rm,
            decos: self.decos,
            n_furniture: self.n_fur,
            n_beds: self.n_bed,
            n_kitchens: self.n_kit,
            n_lights,
            top_y,
        }
    }

    /// `conflict(c, s)` : la cloison toucherait-elle une zone de façade à garder libre ?
    fn conflict(&self, c: &Cut, s: i32, mx1: i32, mz1: i32, mx0: i32, mz0: i32) -> bool {
        let mut fs: Vec<u8> = Vec::new();
        if c.ax == 0 {
            if c.a1 >= mz1 {
                fs.push(2);
            }
            if c.a0 <= mz0 {
                fs.push(3);
            }
        } else {
            if c.a1 >= mx1 {
                fs.push(0);
            }
            if c.a0 <= mx0 {
                fs.push(1);
            }
        }
        fs.iter().any(|f| {
            let r = self.u_range(0, *f, c.c0, c.c1);
            self.ft
                .iter()
                .any(|t| t.b == 0 && t.f == *f && (t.s < 0 || t.s == s) && r.1 > t.u0 && r.0 < t.u1)
        })
    }

    fn anchor(&mut self, s: usize, x: i32, z: i32) {
        let c = self.ix(x, z);
        let id = self.rm[s][c];
        if id >= 0 {
            self.rooms[id as usize].anch.push(c);
        }
    }

    fn rsv(&mut self, s: usize, x0: i32, x1: i32, z0: i32, z1: i32) {
        for z in z0..z1 {
            for x in x0..x1 {
                let i = self.ix(x, z);
                self.occ2[s][i] = 2;
            }
        }
    }

    #[allow(clippy::too_many_arguments)]
    fn rsv_f(&mut self, s: usize, fr: &Frame, u0: i32, u1: i32, d0: i32, d1: i32, val: u8) {
        for u in u0..u1 {
            for d in d0..d1 {
                let q = fr.xz(u, d);
                let i = self.ix(q.0, q.1);
                self.occ2[s][i] = val;
            }
        }
    }
}

/// Données du toit en une colonne.
#[derive(Copy, Clone, Debug)]
pub struct RoofCell {
    /// 2 x p (p : distance au faîtage, en demi-voxels, négatif sous les égouts).
    pub p2: i32,
    /// Bas.
    pub bot: i32,
    /// Haut.
    pub top: i32,
    /// Sommet (faîtière).
    pub cap: bool,
    /// Position le long du faîtage.
    pub al: i32,
    /// Longueur oblique (pente) en 1/1024 de voxel.
    pub sl_k: i64,
}

/// `roofAt(b, x, z)` du JavaScript, en entiers.
pub fn roof_at(b: &Body, x: i32, z: i32, hw: i32, ev: i32, sl100: i32) -> Option<RoofCell> {
    if x < b.rx0 || x >= b.rx1 || z < b.rz0 || z >= b.rz1 {
        return None;
    }
    let (dim, pos2) = if b.main {
        (b.z1 - b.z0, 2 * z + 1 - (b.z0 + b.z1))
    } else {
        (b.x1 - b.x0, 2 * x + 1 - (b.x0 + b.x1))
    };
    let p2 = dim - pos2.abs();
    let t0 = hw + TH - 1 + (sl100 * p2).div_euclid(200);
    // sl = (p + ev) * sqrt(1 + SL^2) = (p2 + 2 ev) / 2 * sqrt(10000 + sl100^2) / 100
    let sq = isqrt(((10_000 + i128::from(sl100) * i128::from(sl100)) as u128) << 40) as i64; // sqrt(.) * 2^20
    let sl_k = i64::from(p2 + 2 * ev) * sq / 200; // x 2^20
    let un = 1_i64 << 20;
    let cap = p2 > dim - 5;
    let fr5 = sl_k.rem_euclid(5 * un);
    let top = t0 + if cap || fr5 < 2 * un { 1 } else { 0 };
    Some(RoofCell {
        p2,
        bot: t0 - TH + 1,
        top,
        cap,
        al: if b.main { x } else { z },
        sl_k,
    })
}

impl HousePlan {
    /// Assigne la hauteur `u` le long de la façade `f` d'un corps pour une cellule du mur : (u, d).
    pub fn wall_u(f: u8, x: i32, z: i32) -> i32 {
        (if f < 2 { z } else { x }) + 300 + i32::from(f) * 37
    }

    /// Le style du mur.
    pub fn style(&self) -> WallStyle {
        self.params.wall.style
    }

    /// Haut du mur d'une colonne (jusqu'au bas du toit).
    pub fn wall_top(&self, i: usize) -> i32 {
        if self.rb[i] == SANS_TOIT {
            self.hw
        } else {
            self.rb[i]
        }
    }

    /// Hachage de variante (pour la teinte du bois du mobilier d'une pièce).
    pub fn room_tone(room_id: usize, s: i32) -> u8 {
        hh_below(hh(room_id as i32, s, 91, 0), 5) as u8
    }
}
