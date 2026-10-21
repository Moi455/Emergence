//! `Bld` : l'établi des bâtiments du village. Il garde l'aspect (classes de matière, pierre, couverture), la table
//! d'assises de pierre et la liste des parties, et offre les éléments communs : murs (pierre, colombage, planches,
//! rondins), planchers, toits (deux pans, pyramide, cône), tour ronde, cheminée, fenêtres et portes. Tout est écrit dans
//! le repère de la maison (x est, y haut, z croissant = devant, façade sud).

use std::sync::Arc;

use em_core::q16::atan2_turns;
use em_core::{Q16, VoxelBox, VoxelValue};

use crate::batiments::kit::intmath::{cos100, sin100};
use crate::batiments::kit::matieres::{Matieres, bois, pierre, val};
use crate::batiments::kit::plan::Part;
use crate::batiments::kit::prims::{Cell, RulePart, TransformPart, vbox};
use crate::batiments::kit::rng::{hh, hh_below};
use crate::batiments::kit::window::Window;
use crate::batiments::maison::look::{HouseOptions, Look};
use crate::batiments::maison::params::{Accent, StoneTone, TileKind, WindowParams};
use crate::batiments::maison::parts::{Bb, op, put};
use crate::batiments::maison::parts2::WindowPart;
use crate::batiments::maison::planner::{Body, Courses, Frame, WinSpec, roof_at};

/// Un rectangle au sol.
#[derive(Copy, Clone, Debug, PartialEq, Eq)]
pub struct Rect {
    /// Ouest (inclus).
    pub x0: i32,
    /// Est (exclu).
    pub x1: i32,
    /// Nord (inclus).
    pub z0: i32,
    /// Sud, le devant (exclu).
    pub z1: i32,
}

impl Rect {
    /// Rectangle.
    pub const fn new(x0: i32, x1: i32, z0: i32, z1: i32) -> Self {
        Self { x0, x1, z0, z1 }
    }

    /// Largeur en x.
    pub const fn w(&self) -> i32 {
        self.x1 - self.x0
    }

    /// Profondeur en z.
    pub const fn d(&self) -> i32 {
        self.z1 - self.z0
    }

    /// Centre.
    pub const fn center(&self) -> (i32, i32) {
        ((self.x0 + self.x1) / 2, (self.z0 + self.z1) / 2)
    }

    /// Le corps de toit de ce rectangle : `ridge_x` vrai, le faîtage court le long de x.
    pub fn body(&self, ridge_x: bool, eave: i32, rake: i32) -> Body {
        let (rx0, rx1, rz0, rz1) = if ridge_x {
            (self.x0 - rake, self.x1 + rake, self.z0 - eave, self.z1 + eave)
        } else {
            (self.x0 - eave, self.x1 + eave, self.z0 - rake, self.z1 + rake)
        };
        Body {
            x0: self.x0,
            x1: self.x1,
            z0: self.z0,
            z1: self.z1,
            main: ridge_x,
            dir: 0,
            rx0,
            rx1,
            rz0,
            rz1,
        }
    }

    /// Façade `f` (0 est, 1 ouest, 2 sud, 3 nord).
    pub fn frame(&self, ridge_x: bool, f: u8) -> Frame {
        Frame::new(0, &self.body(ridge_x, 0, 0), f)
    }
}

/// Nature d'un mur.
#[derive(Copy, Clone, Debug, PartialEq, Eq)]
pub enum Wall {
    /// Pierre apparente (assises irrégulières).
    Stone,
    /// Soubassement de moellons, planches verticales à couvre-joints (granges, étables).
    Boards,
    /// Colombage et plâtre au-dessus d'un soubassement de pierre.
    TimberPlaster,
    /// Colombage et remplissage de pierre.
    TimberStone,
}

/// Toit à deux pans d'un corps.
#[derive(Copy, Clone, Debug)]
pub struct RoofSpec {
    /// Le corps (rectangle et emprise du toit).
    pub body: Body,
    /// Hauteur du haut des murs.
    pub hw: i32,
    /// Débord d'égout.
    pub eave: i32,
    /// Pente en centièmes.
    pub slope100: i32,
}

/// Toit à deux pans : remplissage, bords et sous-face en bois, faîtière.
pub struct GableRoofPart {
    look: Look,
    r: RoofSpec,
    moss100: i32,
    top: i32,
}

impl GableRoofPart {
    /// Toit de ce corps.
    pub fn new(look: Look, r: RoofSpec, moss100: i32) -> Self {
        let dim = if r.body.main {
            r.body.z1 - r.body.z0
        } else {
            r.body.x1 - r.body.x0
        };
        let top = r.hw + 6 + (r.slope100 * dim + 199) / 200 + 4;
        Self {
            look,
            r,
            moss100,
            top,
        }
    }
}

impl Part for GableRoofPart {
    fn bounds(&self) -> VoxelBox {
        let b = &self.r.body;
        let lo = (self.r.hw + (-self.r.slope100 * self.r.eave).div_euclid(100) - 6).max(0);
        vbox([b.rx0, lo, b.rz0], [b.rx1, self.top, b.rz1])
    }

    fn paint(&self, w: &mut Window) {
        let (look, b, ev) = (&self.look, &self.r.body, self.r.eave);
        let bb = self.bounds();
        let (a, c) = (bb.min(), bb.max());
        let Some((lo, hi)) = w.clip([a.x, a.y, a.z], [c.x, c.y, c.z]) else {
            return;
        };
        let along = if b.main { 0 } else { 2 };
        for z in lo[2]..hi[2] {
            for x in lo[0]..hi[0] {
                let Some(r) = roof_at(b, x, z, self.r.hw, ev, self.r.slope100) else {
                    continue;
                };
                let (a_lo, a_hi) = if b.main { (b.rx0, b.rx1) } else { (b.rz0, b.rz1) };
                let edge = r.p2 < -2 * ev + 4 || r.al < a_lo + 2 || r.al >= a_hi - 2;
                for v in r.bot.max(lo[1])..=r.top.min(hi[1] - 1) {
                    let val = if v == r.bot {
                        look.timber_dark(along)
                    } else if edge {
                        look.timber(x, v, z, along)
                    } else if r.cap {
                        look.ridge(x, v, z)
                    } else {
                        look.roof_tile(r.sl_k, r.al + 1000, x, z, self.moss100)
                    };
                    w.put(x, v, z, val);
                }
            }
        }
    }
}

/// L'établi.
pub struct Bld {
    /// Classes de matière.
    pub m: Matieres,
    /// Aspect.
    pub look: Look,
    /// Options de rendu.
    pub opts: HouseOptions,
    /// Assises de pierre.
    pub courses: Arc<Courses>,
    /// Hachage de la graine.
    pub h: u32,
    /// Graine.
    pub seed: u64,
    /// Encadrement des portes en pierre (sinon en bois).
    pub stone_frames: bool,
    parts: Vec<Box<dyn Part>>,
}

impl Bld {
    /// Établi pour une graine : la pierre, la couverture et les accents en sont tirés si non imposés.
    pub fn new(m: Matieres, seed: u64, tile: Option<TileKind>) -> Self {
        let h = hh(seed as i32, (seed >> 32) as i32, 4_321, 8);
        let stone = [StoneTone::Warm, StoneTone::Grey, StoneTone::Dark][hh_below(h, 3) as usize];
        let tile = tile.unwrap_or(
            [TileKind::Slate, TileKind::Terracotta, TileKind::Shingle]
                [hh_below(hh(h as i32, 1, 1, 1), 3) as usize],
        );
        let accents = [Accent::Brown, Accent::Green, Accent::Blue, Accent::Red];
        let a = accents[hh_below(hh(h as i32, 2, 1, 1), 4) as usize];
        let b = accents[hh_below(hh(h as i32, 3, 1, 1), 4) as usize];
        Self {
            m,
            look: Look::custom(m, stone, tile, a, b),
            opts: HouseOptions::village(),
            courses: Arc::new(Courses::from_seed(&format!("v{seed}"))),
            h,
            seed,
            stone_frames: true,
            parts: Vec::new(),
        }
    }

    /// Variante 0..n pour l'usage `sel`.
    pub fn pick(&self, sel: i32, n: u32) -> i32 {
        (hh(self.h as i32, sel, 17, 5) % n.max(1)) as i32
    }

    /// Entier dans [a, b] pour l'usage `sel`.
    pub fn range(&self, sel: i32, a: i32, b: i32) -> i32 {
        a + self.pick(sel, (b - a + 1) as u32)
    }

    /// Ajoute une partie.
    pub fn add(&mut self, p: Box<dyn Part>) {
        self.parts.push(p);
    }

    /// Termine.
    pub fn finish(self) -> Vec<Box<dyn Part>> {
        self.parts
    }

    /// Boîte pleine d'une valeur.
    pub fn fill(&mut self, lo: [i32; 3], hi: [i32; 3], v: VoxelValue) {
        self.parts.push(RulePart::fill(lo, hi, v));
    }

    /// Boîte creusée.
    pub fn carve(&mut self, lo: [i32; 3], hi: [i32; 3]) {
        self.parts.push(RulePart::carve(lo, hi));
    }

    /// Règle libre.
    pub fn rule(
        &mut self,
        lo: [i32; 3],
        hi: [i32; 3],
        f: impl Fn(i32, i32, i32) -> Cell + Send + Sync + 'static,
    ) {
        self.parts.push(RulePart::boxed(lo, hi, f));
    }

    /// Pose un prop (parties déjà construites) en (x, y, z) après `rot` quarts de tour.
    pub fn place(&mut self, parts: Vec<Box<dyn Part>>, at: [i32; 3], rot: u8) {
        self.parts.push(Box::new(TransformPart::new(parts, at, rot)));
    }

    /// Un prop par son nom.
    pub fn prop(&mut self, kind: &str, seed: u64, at: [i32; 3], rot: u8) {
        let cfg = crate::props::PropConfig {
            kind: kind.to_owned(),
            voxel_mm: 50,
        };
        if let Ok(plan) = crate::props::PropGenerator::new(self.m).parts(&cfg, seed) {
            self.place(plan, at, rot);
        }
    }

    // ---- murs ----

    /// Murs creux d'un rectangle, de `y0` à `y1` (les pignons montent jusqu'au toit), épaisseur `thick`.
    pub fn walls(
        &mut self,
        r: Rect,
        y0: i32,
        y1: i32,
        thick: i32,
        kind: Wall,
        roof: Option<RoofSpec>,
        posts: i32,
    ) {
        let (look, courses, h) = (self.look, self.courses.clone(), self.h);
        let top = match &roof {
            Some(s) => {
                y1.max(s.hw + 6 + (s.slope100 * (if s.body.main { r.d() } else { r.w() }) + 199) / 200 + 2)
            }
            None => y1,
        };
        self.rule([r.x0, y0, r.z0], [r.x1, top, r.z1], move |x, y, z| {
            let (dw, de, dn, ds) = (x - r.x0, r.x1 - 1 - x, z - r.z0, r.z1 - 1 - z);
            let d = dw.min(de).min(dn).min(ds);
            if d >= thick {
                return Cell::Keep;
            }
            let wt = match &roof {
                Some(s) => y1.max(roof_at(&s.body, x, z, s.hw, s.eave, s.slope100).map_or(y1, |c| c.bot)),
                None => y1,
            };
            if y >= wt {
                return Cell::Keep;
            }
            let f: u8 = if de == d {
                0
            } else if dw == d {
                1
            } else if ds == d {
                2
            } else {
                3
            };
            let u = (if f < 2 { z } else { x }) + 300 + i32::from(f) * 37;
            let cor = (dw.min(de) < 6) && (dn.min(ds) < 6);
            wall_voxel(&look, &courses, kind, u, y - y0, d, x, z, cor, posts, h, wt - y0)
                .map_or(Cell::Keep, Cell::Put)
        });
    }

    /// Plancher (planches) d'un rectangle, à la hauteur `y`, sur `ep` voxels.
    pub fn floor(&mut self, r: Rect, y: i32, ep: i32) {
        let look = self.look;
        self.rule(
            [r.x0 + 1, y, r.z0 + 1],
            [r.x1 - 1, y + ep, r.z1 - 1],
            move |x, yy, z| {
                if yy == y + ep - 1 {
                    Cell::Put(look.floor(x, z))
                } else {
                    Cell::Put(look.ceiling(x, yy, z))
                }
            },
        );
    }

    /// Toit à deux pans.
    pub fn gable_roof(&mut self, spec: RoofSpec, moss100: i32) {
        self.parts
            .push(Box::new(GableRoofPart::new(self.look, spec, moss100)));
    }

    /// Toit pyramidal sur un carré de demi-côté `half`, de la hauteur `base` sur `height` voxels, centré en (cx, cz).
    pub fn pyramid_roof(&mut self, cx: i32, cz: i32, half: i32, base: i32, height: i32) {
        let look = self.look;
        let moss = 20;
        self.rule(
            [cx - half - 1, base, cz - half - 1],
            [cx + half + 2, base + height + 4, cz + half + 2],
            move |x, y, z| {
                let k = y - base;
                let r = (half + 1) * (height - k) / height.max(1);
                let (a, c) = ((x - cx).abs(), (z - cz).abs());
                let m = a.max(c);
                if k < height && m <= r && m >= r - 2 {
                    let sl = i64::from(k) * 14 * (1 << 20) / 10;
                    let (col, ex) = if a >= c { (x, 1) } else { (z, 2) };
                    let v = if k == 0 {
                        look.timber_dark(0)
                    } else {
                        look.roof_tile(sl, col + 1000 * ex, x, z, moss)
                    };
                    return Cell::Put(v);
                }
                if k >= height && k < height + 4 && a == 0 && c == 0 {
                    return Cell::Put(look.iron(x, y, z));
                }
                Cell::Keep
            },
        );
    }

    /// Toit conique centré (centièmes de voxel) de rayon `r100`, de la hauteur `base`, haut de `height` voxels.
    pub fn cone_roof(&mut self, cx100: i32, cz100: i32, r100: i32, base: i32, height: i32) {
        let look = self.look;
        let (x0, x1) = (
            (cx100 - r100).div_euclid(100) - 1,
            (cx100 + r100).div_euclid(100) + 2,
        );
        let (z0, z1) = (
            (cz100 - r100).div_euclid(100) - 1,
            (cz100 + r100).div_euclid(100) + 2,
        );
        self.rule([x0, base, z0], [x1, base + height + 4, z1], move |x, y, z| {
            let k = y - base;
            let r = i64::from(r100) * i64::from(height - k) / i64::from(height.max(1));
            let (dx, dz) = (i64::from(100 * x + 50 - cx100), i64::from(100 * z + 50 - cz100));
            let d2 = dx * dx + dz * dz;
            if k < height && d2 <= r * r && d2 + 200 * r >= r * r {
                let a = atan2_turns(Q16::from_raw(dz + 1), Q16::from_raw(dx + 1)).raw() as i32;
                let col = (a * 40) / 65_536;
                let sl = i64::from(k) * 15 * (1 << 20) / 10;
                return Cell::Put(if k == 0 {
                    look.timber_dark(0)
                } else {
                    look.roof_tile(sl, col + 1000, x, z, 20)
                });
            }
            if k >= height && k < height + 4 && d2 < 100 * 100 {
                return Cell::Put(look.iron(x, y, z));
            }
            Cell::Keep
        });
    }

    /// Tour ronde de pierre : rayon extérieur `r0` en bas et `r1` en haut (centièmes), épaisseur `thick` voxels.
    #[allow(clippy::too_many_arguments)]
    pub fn round_wall(&mut self, cx100: i32, cz100: i32, r0: i32, r1: i32, y0: i32, y1: i32, thick: i32) {
        let (look, courses) = (self.look, self.courses.clone());
        let rmax = r0.max(r1);
        let (x0, x1) = (
            (cx100 - rmax).div_euclid(100) - 1,
            (cx100 + rmax).div_euclid(100) + 2,
        );
        let (z0, z1) = (
            (cz100 - rmax).div_euclid(100) - 1,
            (cz100 + rmax).div_euclid(100) + 2,
        );
        self.rule([x0, y0, z0], [x1, y1, z1], move |x, y, z| {
            let r = i64::from(r0) + i64::from(r1 - r0) * i64::from(y - y0) / i64::from((y1 - y0).max(1));
            let (dx, dz) = (i64::from(100 * x + 50 - cx100), i64::from(100 * z + 50 - cz100));
            let d2 = dx * dx + dz * dz;
            if d2 > r * r {
                return Cell::Keep;
            }
            let ri = r - i64::from(100 * thick);
            if d2 < ri * ri {
                return Cell::Keep;
            }
            let a = atan2_turns(Q16::from_raw(dz + 1), Q16::from_raw(dx + 1)).raw();
            let circ = (r * 628 / 100 / 100) as i32; // circonférence en voxels
            let u = 300 + (a * i64::from(circ) / 65_536) as i32;
            let d = ((r - crate::batiments::kit::intmath::isqrt(d2 as u128) as i64).max(0) / 100) as i32;
            match courses.stone(u, y - y0, d, 0, false) {
                Some(n) => Cell::Put(pierre(look.stone, n)),
                None => Cell::Keep,
            }
        });
    }

    /// Cheminée de pierre : fût plein de (x0..x1, z0..z1) de `y0` à `y1`, couronnement et conduit creux.
    pub fn chimney(&mut self, x0: i32, x1: i32, z0: i32, z1: i32, y0: i32, y1: i32) {
        let (look, courses) = (self.look, self.courses.clone());
        self.rule([x0 - 1, y0, z0 - 1], [x1 + 1, y1 + 8, z1 + 1], move |x, y, z| {
            let in_fut = x >= x0 && x < x1 && z >= z0 && z < z1;
            if y < y1 {
                if !in_fut {
                    return Cell::Keep;
                }
                // conduit creux du milieu
                let (cx, cz) = ((x0 + x1) / 2, (z0 + z1) / 2);
                if y >= y0 + 12 && (x - cx).abs() <= 1 && (z - cz).abs() <= 1 {
                    return Cell::Air;
                }
                return match courses.stone(x + z + 600, y, 0, 0, true) {
                    Some(n) => Cell::Put(pierre(look.stone, n)),
                    None => Cell::Keep,
                };
            }
            // couronnement : dalle débordante puis quatre piliers
            let k = y - y1;
            let in_cap = x >= x0 - 1 && x < x1 + 1 && z >= z0 - 1 && z < z1 + 1;
            if k < 3 && in_cap {
                let (cx, cz) = ((x0 + x1) / 2, (z0 + z1) / 2);
                if k >= 1 && (x - cx).abs() <= 1 && (z - cz).abs() <= 1 {
                    return Cell::Air;
                }
                return Cell::Put(look.trim_stone(x, y, z));
            }
            if k >= 3 && in_cap && ((x == x0 - 1 || x == x1) && (z == z0 - 1 || z == z1)) {
                return Cell::Put(look.trim_stone(x, y, z));
            }
            Cell::Keep
        });
    }

    /// Fenêtre de forme libre sur une façade.
    pub fn window(&mut self, fr: Frame, u0: i32, v0: i32, wn: WindowParams) {
        self.parts.push(Box::new(WindowPart::with(
            self.look,
            self.opts,
            wn,
            WinSpec { fr, u0, v0, s: 0 },
        )));
    }

    /// Porte (ouverture, encadrement de pierre, battant planches à ferrures) sur une façade.
    #[allow(clippy::too_many_arguments)]
    pub fn door(&mut self, fr: Frame, u0: i32, w: i32, h: i32, arch: bool, accent: Accent, steps: bool) {
        self.parts.push(Box::new(DoorwayPart {
            look: self.look,
            leaf: self.opts.door_leaf,
            fr,
            u0,
            w,
            h,
            arch,
            accent,
            steps,
            stone: self.stone_frames,
        }));
    }
}

/// Une porte de façade.
pub struct DoorwayPart {
    look: Look,
    leaf: bool,
    fr: Frame,
    u0: i32,
    w: i32,
    h: i32,
    arch: bool,
    accent: Accent,
    steps: bool,
    stone: bool,
}

impl Part for DoorwayPart {
    fn bounds(&self) -> VoxelBox {
        let mut b = Bb::new();
        b.frame(
            &self.fr,
            (self.u0 - 8, self.u0 + self.w + 8),
            (0, self.h + 7),
            (-8, 6),
        );
        b.into_box()
    }

    fn paint(&self, win: &mut Window) {
        let (look, fr, u0, w, h) = (&self.look, &self.fr, self.u0, self.w, self.h);
        for uu in -5..w + 5 {
            for vv in 0..h + 5 {
                let o = op(uu, vv, w, h, self.arch, 0);
                let rg = op(uu, vv, w, h, self.arch, 3);
                let u = u0 + uu;
                if rg && !o {
                    for d in 0..6 {
                        put(
                            win,
                            fr,
                            u,
                            vv,
                            d,
                            if self.stone {
                                look.trim_stone(u, vv, d)
                            } else {
                                look.timber(u, vv, d, 1)
                            },
                        );
                    }
                } else if o {
                    for d in 0..6 {
                        put(win, fr, u, vv, d, VoxelValue::AIR);
                    }
                }
            }
        }
        if self.leaf {
            for uu in 0..w {
                for vv in 0..h {
                    if !op(uu, vv, w, h, self.arch, 0) {
                        continue;
                    }
                    for d in 3..5 {
                        let v = if vv == 7 || vv == h - 9 {
                            look.iron(uu, vv, d)
                        } else if uu % 4 == 3 {
                            look.timber_dark(1)
                        } else {
                            look.accent(self.accent, 1, 0, (u0 + uu, vv, d))
                        };
                        put(win, fr, u0 + uu, vv, d, v);
                    }
                }
            }
        }
        if self.steps {
            for uu in -4..w + 4 {
                for d in -6..=-1 {
                    for v in 0..2 {
                        if v == 1 && d < -3 {
                            continue;
                        }
                        put(win, fr, u0 + uu, v, d, look.trim_stone(uu, d, v));
                    }
                }
            }
        }
    }
}

/// Le voxel d'un mur de ce genre (`None` : rien). `v` : hauteur depuis le sol, `d` : profondeur depuis la face extérieure.
#[allow(clippy::too_many_arguments)]
fn wall_voxel(
    look: &Look,
    courses: &Courses,
    kind: Wall,
    u: i32,
    v: i32,
    d: i32,
    x: i32,
    z: i32,
    cor: bool,
    posts: i32,
    h: u32,
    top: i32,
) -> Option<VoxelValue> {
    let pierre_cell = |ex: i32| -> Option<VoxelValue> {
        courses.stone(u, v, d, ex, false).map(|n| {
            if v < 16 && n != 0 && crate::batiments::kit::noise::vnoise2(u * 3, v * 2, 5, 3) > 41_000 {
                return val(look.m.moss, 40 + (hh(x, v, z, 16) % 50) as u8);
            }
            pierre(look.stone, n)
        })
    };
    match kind {
        Wall::Stone => pierre_cell(0),
        Wall::Boards => {
            if v < 8 {
                return courses.stone(u, v, d, 0, false).map(|n| pierre(look.m.rubble, n));
            }
            if d >= 3 && d < 5 && (u.rem_euclid(24) >= 2) {
                return None;
            }
            if u.rem_euclid(24) < 2 || v >= top - 3 {
                return Some(look.timber(u, v, d, if v >= top - 3 { 0 } else { 1 }));
            }
            let gap = u.rem_euclid(6) == 5;
            let teinte = 4 + (hh(u.div_euclid(6), 0, h as i32, 3) % 9) as u8;
            Some(if gap {
                bois(look.m.timber, 1, 1)
            } else {
                bois(look.m.oak_raw, 1, teinte)
            })
        }
        Wall::TimberPlaster | Wall::TimberStone => {
            if v < 8 {
                return pierre_cell(0);
            }
            let bm = v < 11 || v % 54 >= 52 || v >= top - 5;
            if bm {
                return Some(look.timber(v, d, 2, if x == z { 0 } else { 2 }));
            }
            if cor || u.rem_euclid(posts.max(8)) < 5 {
                return Some(look.timber(u, d, 1, 1));
            }
            if kind == Wall::TimberPlaster {
                if d < 1 {
                    return None;
                }
                return Some(look.plaster(x, v, z, 20));
            }
            pierre_cell(1)
        }
    }
}

/// Aide d'angle : (cos, sin) en centièmes d'un angle en tours Q16.
pub fn cs(a: i32) -> (i32, i32) {
    (cos100(a), sin100(a))
}
