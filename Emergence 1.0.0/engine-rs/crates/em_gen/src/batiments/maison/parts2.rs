//! Les PARTIES de la maison (seconde moitié) : cloisons, escalier, fenêtres, œils-de-bœuf, foyer, intérieur meublé,
//! tonneaux et jardin. Même contrat que `parts` : une boîte, une règle de peinture, l'ordre du JavaScript.

use std::sync::Arc;

use em_core::{VoxelBox, VoxelValue};

use super::furniture::{Canvas, Kind, Paint};
use super::parts::{Bb, Ctx, op, put};
use super::planner::{Affine, Cut, DHT, DW, Deco, NS, SH, T, WinSpec};
use crate::batiments::kit::intmath::{cos100, round_div, sin100};
use crate::batiments::kit::matieres::{Ton, bois, ton, val};
use crate::batiments::kit::plan::Part;
use crate::batiments::kit::rng::{hh, hh_below, hh_lt};
use crate::batiments::kit::window::Window;

/// Une cloison d'un étage, avec sa porte et son chambranle (`fillCut`).
pub struct CutPart {
    ctx: Arc<Ctx>,
    cut: Cut,
    s: i32,
}

impl CutPart {
    /// Cloison `cut` de l'étage `s`.
    pub fn new(ctx: Arc<Ctx>, cut: Cut, s: i32) -> Self {
        Self { ctx, cut, s }
    }

    fn ranges(&self) -> ((i32, i32), (i32, i32)) {
        let c = &self.cut;
        if c.ax == 0 {
            ((c.c0, c.c1), (c.a0, c.a1))
        } else {
            ((c.a0, c.a1), (c.c0, c.c1))
        }
    }
}

impl Part for CutPart {
    fn bounds(&self) -> VoxelBox {
        let (xr, zr) = self.ranges();
        let mut b = Bb::new();
        b.add([xr.0, self.s * SH, zr.0], [xr.1, (self.s + 1) * SH, zr.1]);
        b.into_box()
    }

    fn paint(&self, w: &mut Window) {
        let (plan, look) = (&self.ctx.plan, &self.ctx.look);
        let c = &self.cut;
        let (v0, v1) = (self.s * SH, (self.s + 1) * SH - 3);
        let (xr, zr) = self.ranges();
        for z in zr.0..zr.1 {
            for x in xr.0..xr.1 {
                if !plan.intr(x, z) {
                    continue;
                }
                for v in v0..v1 {
                    let val = if v < v0 + 3 {
                        look.timber(x, v, z, 0)
                    } else {
                        look.partition(x, v, z)
                    };
                    w.put(x, v, z, val);
                }
            }
        }
        let d = c.door;
        for a in d - 2..d + DW + 2 {
            for t in c.c0..c.c1 {
                let (x, z) = if c.ax == 0 { (t, a) } else { (a, t) };
                if !plan.intr(x, z) {
                    continue;
                }
                let open = a >= d && a < d + DW;
                for v in v0..v0 + DHT + 3 {
                    if open && v < v0 + DHT {
                        w.carve(x, v, z);
                    } else {
                        w.put(x, v, z, look.timber(x, v, z, 1));
                    }
                }
            }
        }
    }
}

/// L'escalier de bois (14 marches) et sa rambarde.
pub struct StairsPart {
    ctx: Arc<Ctx>,
}

impl StairsPart {
    /// Crée la partie.
    pub fn new(ctx: Arc<Ctx>) -> Self {
        Self { ctx }
    }
}

impl Part for StairsPart {
    fn bounds(&self) -> VoxelBox {
        let plan = &self.ctx.plan;
        let mut b = Bb::new();
        if let Some(s) = &plan.strip {
            b.add([s.sx0 - 2, 0, plan.hz0 - 2], [s.sx1 + 2, SH + 20, plan.hz1 + 2]);
        }
        b.into_box()
    }

    fn paint(&self, w: &mut Window) {
        let (plan, look) = (&self.ctx.plan, &self.ctx.look);
        let Some(sp) = &plan.strip else {
            return;
        };
        let (mz0, mz1) = (T, plan.bodies[0].z1 - T);
        for i in 0..NS {
            let h = round_div((i + 1) * SH, NS);
            let zs = if sp.dir > 0 {
                mz0 + 14 + 4 * i
            } else {
                mz1 - 14 - 4 * (i + 1)
            };
            for z in zs..zs + 4 {
                for x in sp.sx0..sp.sx1 {
                    for v in 0..h {
                        w.put(x, v, z, look.step(x, v, z, v == h - 1));
                    }
                }
            }
        }
        let s_w = plan.params.chimney == super::params::Side::E;
        let rx = if s_w { sp.sx1 } else { sp.sx0 - 1 };
        let za = if sp.dir > 0 { plan.hz0 - 1 } else { plan.hz0 + 10 };
        let zb = if sp.dir > 0 { plan.hz1 - 11 } else { plan.hz1 };
        let rail = |w: &mut Window, x: i32, z: i32| {
            for v in SH..SH + 19 {
                if (x + z).rem_euclid(6) < 2 || v >= SH + 16 {
                    w.put(x, v, z, look.timber(x, v, z, 1));
                }
            }
        };
        for z in za..=zb {
            rail(w, rx, z);
        }
        let zr = if sp.dir > 0 { plan.hz0 - 1 } else { plan.hz1 };
        for x in sp.sx0..sp.sx1 {
            rail(w, x, zr);
        }
    }
}

/// Une fenêtre : ouverture, vitrage, appui, linteau, volets, jardinière.
pub struct WindowPart {
    look: super::look::Look,
    opts: super::look::HouseOptions,
    wn: super::params::WindowParams,
    spec: WinSpec,
}

impl WindowPart {
    /// Fenêtre `spec` d'une maison.
    pub fn new(ctx: Arc<Ctx>, spec: WinSpec) -> Self {
        Self {
            look: ctx.look,
            opts: ctx.opts,
            wn: ctx.plan.params.win,
            spec,
        }
    }

    /// Fenêtre de forme libre (bâtiments du village).
    pub fn with(
        look: super::look::Look,
        opts: super::look::HouseOptions,
        wn: super::params::WindowParams,
        spec: WinSpec,
    ) -> Self {
        Self { look, opts, wn, spec }
    }
}

impl Part for WindowPart {
    fn bounds(&self) -> VoxelBox {
        let wn = self.wn;
        let sw = (wn.w >> 1) + 1;
        let (u0, v0) = (self.spec.u0, self.spec.v0);
        let mut b = Bb::new();
        b.frame(
            &self.spec.fr,
            (u0 - 4 - sw, u0 + wn.w + 4 + sw),
            (v0 - 12, v0 + wn.h + 6),
            (-6, T),
        );
        b.into_box()
    }

    fn paint(&self, win: &mut Window) {
        let (look, opts) = (&self.look, self.opts);
        let wn = self.wn;
        let (fr, u0, v0) = (&self.spec.fr, self.spec.u0, self.spec.v0);
        let (w, h, arch) = (wn.w, wn.h, wn.arch);
        for uu in -5..w + 5 {
            for vv in -5..h + 5 {
                let o = op(uu, vv, w, h, arch, 0);
                let rg = op(uu, vv, w, h, arch, 2);
                let (u, v) = (u0 + uu, v0 + vv);
                if rg && !o {
                    for d in 0..T {
                        put(win, fr, u, v, d, look.timber(u, v, d, 1));
                    }
                } else if o {
                    for d in 0..T {
                        put(win, fr, u, v, d, VoxelValue::AIR);
                    }
                }
            }
        }
        if opts.glazing {
            for uu in 0..w {
                for vv in 0..h {
                    if op(uu, vv, w, h, arch, 0) {
                        let croisee = uu == w / 2 || vv == h / 2 - 1 && vv >= 0;
                        let v = if croisee {
                            look.timber(uu, vv, 0, 1)
                        } else {
                            val(look.m.glass, 64)
                        };
                        put(win, fr, u0 + uu, v0 + vv, T - 3, v);
                    }
                }
            }
        }
        for uu in -5..w + 5 {
            for d in -2..=1 {
                put(win, fr, u0 + uu, v0 - 4, d, look.trim_stone(uu, d, v0));
                put(win, fr, u0 + uu, v0 - 3, d, look.trim_stone(uu, d, v0 + 1));
            }
            if !arch {
                for vv in h + 2..h + 5 {
                    for d in -1..=1 {
                        put(win, fr, u0 + uu, v0 + vv, d, look.trim_stone(uu, vv, d));
                    }
                }
            }
        }
        if wn.shutters {
            let sw = (w >> 1) + 1;
            for s0 in [-3 - sw, w + 3] {
                for uu in 0..sw {
                    for vv in -2..h + 2 {
                        let (u, v) = (u0 + s0 + uu, v0 + vv);
                        let gap = uu % 4 == 3;
                        let bat = vv == 4 || vv == h - 3;
                        let c = if gap {
                            look.accent(look.window_accent, 1, 0, (u, v, 1))
                                .tint_dark(look.m.timber)
                        } else {
                            look.accent(look.window_accent, 1, 8, (u, v, 1))
                        };
                        put(win, fr, u, v, -1, c);
                        if bat {
                            put(
                                win,
                                fr,
                                u,
                                v,
                                -2,
                                look.accent(look.window_accent, 0, 0, (u, v, 2)),
                            );
                        }
                    }
                }
            }
        }
        if wn.box_ {
            for uu in -3..w + 3 {
                for d in -5..=-1 {
                    for vv in -11..-5 {
                        let edge = uu < -2 || uu >= w + 2 || d == -5 || vv == -11;
                        if edge || vv == -6 {
                            let c = if edge {
                                look.timber(uu, vv, d, 0)
                            } else {
                                look.timber_dark(0)
                            };
                            put(win, fr, u0 + uu, v0 + vv, d, c);
                        }
                    }
                }
            }
            let f = i32::from(fr.f);
            for uu in -2..w + 2 {
                for d in -4..=-3 {
                    let hgt = 2 + hh_below(hh(u0 + uu, d, f, 8), 4) as i32;
                    for k in 0..hgt {
                        let fl = k == hgt - 1 && !hh_lt(hh(u0 + uu, d, f, 9), 40);
                        let c = if fl {
                            look.flower(hh_below(hh(u0 + uu, d, 2, 3), 4))
                        } else {
                            look.leaf(uu, k, d)
                        };
                        put(win, fr, u0 + uu, v0 - 5 + k, d, c);
                    }
                }
            }
        }
    }
}

pub(crate) trait TintDark {
    fn tint_dark(self, cls: em_core::MaterialId) -> VoxelValue;
}

impl TintDark for VoxelValue {
    /// Version plus sombre d'une peinture (joint entre deux planches de volet).
    fn tint_dark(self, _cls: em_core::MaterialId) -> VoxelValue {
        val(self.material(), self.tint().saturating_sub(34))
    }
}

/// Un œil-de-bœuf de pignon, à claire-voie.
pub struct VentPart {
    ctx: Arc<Ctx>,
    uc: i32,
    v0: i32,
    fr: super::planner::Frame,
}

impl VentPart {
    /// Œil-de-bœuf `vent`.
    pub fn new(ctx: Arc<Ctx>, vent: &super::planner::Vent) -> Self {
        Self {
            ctx,
            uc: vent.uc,
            v0: vent.v0,
            fr: vent.fr,
        }
    }
}

impl Part for VentPart {
    fn bounds(&self) -> VoxelBox {
        let mut b = Bb::new();
        b.frame(
            &self.fr,
            (self.uc - 6, self.uc + 6),
            (self.v0 - 1, self.v0 + 13),
            (0, 2),
        );
        b.into_box()
    }

    fn paint(&self, win: &mut Window) {
        let look = &self.ctx.look;
        let u0 = self.uc - 5;
        for uu in -1..11 {
            for vv in -1..13 {
                let o = op(uu, vv, 10, 12, true, 0);
                let r = op(uu, vv, 10, 12, true, 1);
                if r {
                    for d in 0..2 {
                        let c = if o {
                            if vv.rem_euclid(3) == 0 {
                                look.timber_dark(0)
                            } else {
                                look.timber(uu, vv, d, 0)
                            }
                        } else {
                            look.wood_light(uu, vv, d, 0)
                        };
                        put(win, &self.fr, u0 + uu, self.v0 + vv, d, c);
                    }
                }
            }
        }
    }
}

/// Le foyer intérieur, le manteau de pierre, le conduit de fumée creux.
pub struct HearthPart {
    ctx: Arc<Ctx>,
}

impl HearthPart {
    /// Crée la partie.
    pub fn new(ctx: Arc<Ctx>) -> Self {
        Self { ctx }
    }
}

impl Part for HearthPart {
    fn bounds(&self) -> VoxelBox {
        let plan = &self.ctx.plan;
        let uc = plan.chim_uc;
        let mut b = Bb::new();
        b.frame(
            &plan.cfr,
            (uc - 14, uc + 14),
            (0, plan.chim_top + 9),
            (-13, T + 7),
        );
        b.into_box()
    }

    fn paint(&self, win: &mut Window) {
        let (plan, look) = (&self.ctx.plan, &self.ctx.look);
        let (cfr, uc) = (&plan.cfr, plan.chim_uc);
        for u in uc - 8..uc + 8 {
            for v in 1..17 {
                for d in T - 3..T {
                    put(win, cfr, u, v, d, VoxelValue::AIR);
                }
                put(
                    win,
                    cfr,
                    u,
                    v,
                    T - 4,
                    val(look.m.coal, 12 + (hh(u, v, 0, 0) % 14) as u8),
                );
            }
        }
        for u in uc - 7..uc + 7 {
            for d in T - 3..T {
                if hh_lt(hh(u, d, 31, 0), 55) {
                    put(
                        win,
                        cfr,
                        u,
                        1,
                        d,
                        val(look.m.ember, 30 + (hh(u, d, 32, 0) % 90) as u8),
                    );
                } else if hh_lt(hh(u, d, 33, 0), 70) {
                    put(win, cfr, u, 1, d, look.timber(u, d, 3, 0));
                }
            }
        }
        for u in uc - 12..uc + 12 {
            for d in T..T + 5 {
                for v in 0..22 {
                    let hole = u >= uc - 8 && u < uc + 8 && (1..17).contains(&v);
                    put(
                        win,
                        cfr,
                        u,
                        v,
                        d,
                        if hole {
                            VoxelValue::AIR
                        } else {
                            look.trim_stone(u, v, d)
                        },
                    );
                }
            }
        }
        for u in uc - 14..uc + 14 {
            for d in T..T + 7 {
                for v in 22..25 {
                    put(win, cfr, u, v, d, look.timber(u, v, d, 0));
                }
            }
        }
        let top_c = plan.chim_top;
        for u in uc - 4..uc + 4 {
            for d in -4..T - 3 {
                for v in 13..17 {
                    put(win, cfr, u, v, d, VoxelValue::AIR);
                }
            }
            for d in -12..=-4 {
                for v in 13..top_c + 9 {
                    put(win, cfr, u, v, d, VoxelValue::AIR);
                }
            }
        }
        for v in 13..top_c {
            for (u, d) in [
                (uc - 5, -8),
                (uc + 4, -8),
                (uc - 1, -13),
                (uc, -13),
                (uc - 1, -3),
                (uc, -3),
            ] {
                let (x, z) = cfr.xz(u, d);
                if !win.get(x, v, z).is_air() {
                    win.put(x, v, z, val(look.m.coal, 30 + (hh(u, v, d, 0) % 20) as u8));
                }
            }
        }
    }
}

/// Peint les meubles dans une fenêtre (implémente `Canvas`).
struct ItemCanvas<'a> {
    win: &'a mut Window,
    ctx: &'a Ctx,
    map: Affine,
    base: i32,
    tone: u8,
}

impl Canvas for ItemCanvas<'_> {
    fn l(&mut self, i: i32, j: i32, k: i32, p: Paint) {
        let (x, z) = (
            self.map.o.0 + i * self.map.iv.0 + k * self.map.kv.0,
            self.map.o.1 + i * self.map.iv.1 + k * self.map.kv.1,
        );
        let y = self.base + j;
        let (v, _) = self.ctx.look.paint(p, (x, y, z), self.tone);
        self.win.put(x, y, z, v);
    }

    fn air(&mut self, i: i32, j: i32, k: i32) {
        let (x, z) = (
            self.map.o.0 + i * self.map.iv.0 + k * self.map.kv.0,
            self.map.o.1 + i * self.map.iv.1 + k * self.map.kv.1,
        );
        self.win.carve(x, self.base + j, z);
    }
}

/// L'intérieur : meubles, tapis et lampes dans l'ordre de pose.
pub struct InteriorPart {
    ctx: Arc<Ctx>,
}

impl InteriorPart {
    /// Crée la partie.
    pub fn new(ctx: Arc<Ctx>) -> Self {
        Self { ctx }
    }

    fn deco_box(d: &Deco) -> ([i32; 3], [i32; 3]) {
        match d {
            Deco::Item { kind, map, base, .. } => {
                let a = (map.o.0, map.o.1);
                let b = (
                    map.o.0 + (kind.w() - 1) * map.iv.0 + (kind.dp() - 1) * map.kv.0,
                    map.o.1 + (kind.w() - 1) * map.iv.1 + (kind.dp() - 1) * map.kv.1,
                );
                // le cylindre ou le globe peuvent déborder d'un voxel
                (
                    [a.0.min(b.0) - 1, *base, a.1.min(b.1) - 1],
                    [a.0.max(b.0) + 2, base + kind.h() + 4, a.1.max(b.1) + 2],
                )
            }
            Deco::Rug { base, cells, .. } => {
                let x0 = cells.iter().map(|c| c.0).min().unwrap_or(0);
                let x1 = cells.iter().map(|c| c.0).max().unwrap_or(0);
                let z0 = cells.iter().map(|c| c.1).min().unwrap_or(0);
                let z1 = cells.iter().map(|c| c.1).max().unwrap_or(0);
                ([x0, *base, z0], [x1 + 1, base + 1, z1 + 1])
            }
            Deco::Lamp { x, z, vc, .. } => ([x - 7, vc - 15, z - 7], [x + 8, vc + 1, z + 8]),
        }
    }
}

impl Part for InteriorPart {
    fn bounds(&self) -> VoxelBox {
        let mut b = Bb::new();
        for d in &self.ctx.plan.decos {
            let (lo, hi) = Self::deco_box(d);
            b.add(lo, hi);
        }
        b.into_box()
    }

    fn paint(&self, win: &mut Window) {
        let (plan, look) = (&self.ctx.plan, &self.ctx.look);
        for d in &plan.decos {
            let (lo, hi) = Self::deco_box(d);
            if win.clip(lo, hi).is_none() {
                continue;
            }
            match d {
                Deco::Item {
                    kind,
                    q,
                    map,
                    base,
                    tone,
                } => {
                    let mut cv = ItemCanvas {
                        win,
                        ctx: &self.ctx,
                        map: *map,
                        base: *base,
                        tone: *tone,
                    };
                    kind.draw(*q, &mut cv);
                }
                Deco::Rug { base, color, cells } => {
                    for (x, z, e100) in cells {
                        let v = if *e100 < 200 {
                            val(look.m.hay, 70 + (hh(*x, 0, *z, 22) % 10) as u8)
                        } else {
                            let (v, _) = look.paint(Paint::Fabric(*color), (*x, 0, *z), 0);
                            if *e100 < 400 {
                                val(v.material(), v.tint().saturating_sub(12))
                            } else {
                                v
                            }
                        };
                        win.put_if_empty(*x, *base, *z, v);
                    }
                }
                Deco::Lamp { x, z, vc, round } => {
                    let (x, z, vc) = (*x, *z, *vc);
                    if *round {
                        for v in vc - 8..vc {
                            win.put(x, v, z, look.iron(x, v, z));
                        }
                        for t in 0..24 {
                            let a = t * 65_536 / 24;
                            let (px, pz) = (
                                x + round_div(cos100(a) * 6, 100),
                                z + round_div(sin100(a) * 6, 100),
                            );
                            win.put(px, vc - 9, pz, look.iron(px, vc, pz));
                        }
                        win.put(x, vc - 9, z, look.iron(x, vc, z));
                        for t in 0..6 {
                            let a = t * 65_536 / 6;
                            let (px, pz) = (
                                x + round_div(cos100(a) * 6, 100),
                                z + round_div(sin100(a) * 6, 100),
                            );
                            win.put(px, vc - 8, pz, val(look.m.wax, 100));
                            win.put(px, vc - 7, pz, ton(look.m.glow, Ton::Moyen));
                        }
                    } else {
                        for v in vc - 9..vc {
                            win.put(x, v, z, look.iron(x, v, z));
                        }
                        for a in -1..=1 {
                            for b in -1..=1 {
                                for k in 0..5 {
                                    let edge = a != 0 && b != 0;
                                    let cap = k == 0 || k == 4;
                                    let v = if edge || cap {
                                        look.iron(a, k, b)
                                    } else {
                                        ton(look.m.glow, Ton::Moyen)
                                    };
                                    win.put(x + a, vc - 14 + k, z + b, v);
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

/// Un tonneau devant la façade.
pub struct BarrelPart {
    ctx: Arc<Ctx>,
    cx: i32,
    cz: i32,
}

impl BarrelPart {
    /// Tonneau centré en (cx, cz).
    pub fn new(ctx: Arc<Ctx>, cx: i32, cz: i32) -> Self {
        Self { ctx, cx, cz }
    }
}

impl Part for BarrelPart {
    fn bounds(&self) -> VoxelBox {
        let mut b = Bb::new();
        b.add([self.cx - 7, 0, self.cz - 7], [self.cx + 8, 14, self.cz + 8]);
        b.into_box()
    }

    fn paint(&self, win: &mut Window) {
        let look = &self.ctx.look;
        let h = 14;
        for v in 0..h {
            let bl100 = 640 - 130 * (2 * v - 13) * (2 * v - 13) / 196;
            for dx in -7..=7 {
                for dz in -7..=7 {
                    let r2 = 10_000 * (dx * dx + dz * dz);
                    if r2 > bl100 * bl100 {
                        continue;
                    }
                    let c = if v == h - 1 {
                        if r2 > (bl100 - 120) * (bl100 - 120) {
                            look.wood_light(dx, v, dz, 1)
                        } else {
                            look.timber_dark(3)
                        }
                    } else if v == 3 || v == h - 4 {
                        look.iron(dx, v, dz)
                    } else {
                        let a = em_core::q16::atan2_turns(
                            em_core::Q16::from_raw(i64::from(dz) * 1000),
                            em_core::Q16::from_raw(i64::from(dx) * 1000),
                        )
                        .raw();
                        let secteur = ((a * 6283 / 65_536 + 3200) * 32 / 10_000) as i32;
                        bois(
                            look.m.oak_raw,
                            1,
                            4 + (hh_below(hh(secteur, v >> 2, 1, 0), 10)) as u8,
                        )
                    };
                    win.put(self.cx + dx, v, self.cz + dz, c);
                }
            }
        }
    }
}

/// Le jardin : sol (herbe, chemin de gravier), puis herbes hautes et fleurs.
pub struct GardenPart {
    ctx: Arc<Ctx>,
    flore: bool,
}

impl GardenPart {
    /// Sol du jardin (`flore` faux) ou sa flore (`flore` vrai, peinte en dernier).
    pub fn new(ctx: Arc<Ctx>, flore: bool) -> Self {
        Self { ctx, flore }
    }

    fn region(&self) -> ([i32; 2], [i32; 2]) {
        let plan = &self.ctx.plan;
        let x0 = plan.bodies.iter().map(|b| b.rx0).min().unwrap_or(0);
        let x1 = plan.bodies.iter().map(|b| b.rx1).max().unwrap_or(0);
        let z0 = plan.bodies.iter().map(|b| b.rz0).min().unwrap_or(0);
        let z1 = plan.bodies.iter().map(|b| b.rz1).max().unwrap_or(0);
        ([x0 - 56, x1 + 56], [z0 - 56, z1 + 56])
    }

    fn sur_chemin(&self, x: i32, z: i32) -> Option<(bool, i32)> {
        let plan = &self.ctx.plan;
        // dx = |x - (dxw + 5 sin(0,06 z))| ; pw = 8 + 2 sin(0,13 z) - max(0, (z - dz1 - 60) / 12)
        let s1 = i64::from(sin100((i64::from(z) * 626) as i32 & 0xFFFF));
        let s2 = i64::from(sin100((i64::from(z) * 1347) as i32 & 0xFFFF));
        let dx100 = i64::from(x) * 100 - (i64::from(plan.dxw) * 100 + 5 * s1);
        let pw100 = 800 + 2 * s2
            - if z - plan.dz1 > 60 {
                i64::from(z - plan.dz1 - 60) * 100 / 12
            } else {
                0
            };
        let dx_abs = dx100.abs();
        if z >= plan.dz1 - 2 && dx_abs < pw100 {
            let bord = dx_abs > pw100 - 200 && hh(x, z, 13, 0) >= (1 << 31);
            return Some((!bord, 0));
        }
        None
    }
}

impl Part for GardenPart {
    fn bounds(&self) -> VoxelBox {
        let (xr, zr) = self.region();
        let mut b = Bb::new();
        if self.flore {
            b.add([xr[0], 0, zr[0]], [xr[1], 10, zr[1]]);
        } else {
            b.add([xr[0], -4, zr[0]], [xr[1], 0, zr[1]]);
        }
        b.into_box()
    }

    fn paint(&self, w: &mut Window) {
        let (plan, look) = (&self.ctx.plan, &self.ctx.look);
        let bb = self.bounds();
        let (a, c) = (bb.min(), bb.max());
        let Some((lo, hi)) = w.clip([a.x, a.y, a.z], [c.x, c.y, c.z]) else {
            return;
        };
        for z in lo[2]..hi[2] {
            for x in lo[0]..hi[0] {
                if !self.flore {
                    let chemin = self.sur_chemin(x, z);
                    for y in lo[1]..hi[1] {
                        let top = y == -1;
                        let v = if !top {
                            val(look.m.dirt, 20 + (hh(x, y, z, 17) % 25) as u8)
                        } else if let Some((true, _)) = chemin {
                            let s = hh_below(hh(x.div_euclid(5), z.div_euclid(5), 14, 0), 3);
                            val(
                                look.m.gravel,
                                [34, 56, 80][s as usize] + (hh(x, 0, z, 18) % 10) as u8,
                            )
                        } else {
                            let n = crate::batiments::kit::noise::vnoise2(x, z, 20, 11) >> 10;
                            val(look.m.turf, 30 + n as u8 + (hh(x, 0, z, 19) % 18) as u8)
                        };
                        w.put(x, y, z, v);
                    }
                } else {
                    if plan.in_f(x, z) || self.sur_chemin(x, z).is_some_and(|c| c.0) {
                        continue;
                    }
                    if !w.get(x, 0, z).is_air() {
                        continue;
                    }
                    let dp = plan.params.deco;
                    let h1 = hh(x, z, 21, 0);
                    let dn = if crate::batiments::kit::noise::vnoise2(x * 8, z * 8, 100, 9) > 32_768 {
                        3
                    } else {
                        1
                    };
                    if hh_lt(h1, dp.grass100 as u32) {
                        let h = 2 + hh_below(hh(x, z, 22, 0), 3) as i32;
                        for k in 0..h {
                            w.put(
                                x,
                                k,
                                z,
                                val(look.m.turf, 70 + (k * 40 / h) as u8 + (hh(x, z, k, 0) % 10) as u8),
                            );
                        }
                    } else if (u64::from(!h1) + 1) * 10_000 < (dp.flowers100 * dn * 35) as u64 * (1_u64 << 32)
                    {
                        let h = 3 + hh_below(hh(x, z, 23, 0), 4) as i32;
                        let fl = look.flower(hh_below(hh(x, z, 24, 0), 4));
                        for k in 0..h {
                            w.put(x, k, z, val(look.m.moss, 70));
                        }
                        w.put(x, h, z, fl);
                        if hh(x, z, 25, 0) > (1 << 31) {
                            w.put(x + 1, h, z, fl);
                            w.put(x - 1, h, z, fl);
                        }
                    }
                }
            }
        }
        let _ = Kind::Bed;
    }
}
