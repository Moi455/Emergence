//! Les PARTIES de la maison (première moitié) : murs et sols, toit, porte et perron, cheminée, appentis. Chacune est
//! un `Part` : une boîte et une règle de peinture, appliquée dans l'ORDRE du JavaScript (le dernier qui écrit gagne).
//! Aucune ne garde de voxel ; toutes lisent le `HousePlan` partagé.

use std::sync::Arc;

use em_core::{VoxelBox, VoxelCoord, VoxelValue};

use super::look::{HouseOptions, Look};
use super::params::WallStyle;
use super::planner::{Frame, HousePlan, PL, SANS_TOIT, SH, T, TH, roof_at};
use crate::batiments::kit::matieres::val;
use crate::batiments::kit::plan::Part;
use crate::batiments::kit::rng::{hh, hh_below, hh_lt};
use crate::batiments::kit::window::Window;

/// Plan, aspect et options partagés par les parties.
pub struct Ctx {
    /// Le plan.
    pub plan: HousePlan,
    /// L'aspect.
    pub look: Look,
    /// Les options.
    pub opts: HouseOptions,
}

/// Boîte englobante qu'on agrandit au fil des boucles d'une partie.
pub struct Bb {
    lo: [i32; 3],
    hi: [i32; 3],
}

impl Bb {
    /// Boîte vide.
    pub fn new() -> Self {
        Self {
            lo: [i32::MAX; 3],
            hi: [i32::MIN; 3],
        }
    }

    /// Ajoute la boîte (x, y, z) demi-ouverte.
    pub fn add(&mut self, lo: [i32; 3], hi: [i32; 3]) {
        for k in 0..3 {
            self.lo[k] = self.lo[k].min(lo[k]);
            self.hi[k] = self.hi[k].max(hi[k]);
        }
    }

    /// Ajoute des intervalles `[u0, u1) x [v0, v1) x [d0, d1)` d'une façade.
    pub fn frame(&mut self, fr: &Frame, u: (i32, i32), v: (i32, i32), d: (i32, i32)) {
        let c = [
            fr.xz(u.0, d.0),
            fr.xz(u.1 - 1, d.0),
            fr.xz(u.0, d.1 - 1),
            fr.xz(u.1 - 1, d.1 - 1),
        ];
        let x0 = c.iter().map(|p| p.0).min().unwrap_or(0);
        let x1 = c.iter().map(|p| p.0).max().unwrap_or(0) + 1;
        let z0 = c.iter().map(|p| p.1).min().unwrap_or(0);
        let z1 = c.iter().map(|p| p.1).max().unwrap_or(0) + 1;
        self.add([x0, v.0, z0], [x1, v.1, z1]);
    }

    /// La boîte (vide si rien n'a été ajouté).
    pub fn into_box(self) -> VoxelBox {
        if self.lo[0] > self.hi[0] {
            return VoxelBox::new(VoxelCoord::new(0, 0, 0), VoxelCoord::new(0, 0, 0)).expect("vide");
        }
        VoxelBox::new(
            VoxelCoord::new(self.lo[0], self.lo[1], self.lo[2]),
            VoxelCoord::new(self.hi[0], self.hi[1], self.hi[2]),
        )
        .expect("boîte ordonnée")
    }
}

impl Default for Bb {
    fn default() -> Self {
        Self::new()
    }
}

/// Pose un voxel dans le repère d'une façade.
#[inline]
pub fn put(w: &mut Window, fr: &Frame, u: i32, v: i32, d: i32, val: VoxelValue) {
    let (x, z) = fr.xz(u, d);
    w.put(x, v, z, val);
}

/// `op(uu, vv, w, h, arch, e)` : le point est-il dans l'ouverture (agrandie de `e`) ? Calcul entier exact.
pub fn op(uu: i32, vv: i32, w: i32, h: i32, arch: bool, e: i32) -> bool {
    if uu < -e || uu >= w + e || vv < -e {
        return false;
    }
    if arch {
        let cy2 = 2 * h - w;
        if 2 * vv < cy2 {
            return true;
        }
        let (a, b) = (2 * uu + 1 - w, 2 * vv + 1 - cy2);
        return a * a + b * b <= (w + 2 * e) * (w + 2 * e);
    }
    vv < h + e
}

fn corps_box(plan: &HousePlan) -> ([i32; 2], [i32; 2]) {
    let x0 = plan.bodies.iter().map(|b| b.x0).min().unwrap_or(0);
    let x1 = plan.bodies.iter().map(|b| b.x1).max().unwrap_or(0);
    let z0 = plan.bodies.iter().map(|b| b.z0).min().unwrap_or(0);
    let z1 = plan.bodies.iter().map(|b| b.z1).max().unwrap_or(0);
    ([x0, x1], [z0, z1])
}

/// Murs, planchers et plafonds des étages.
pub struct WallsPart {
    ctx: Arc<Ctx>,
}

impl WallsPart {
    /// Crée la partie.
    pub fn new(ctx: Arc<Ctx>) -> Self {
        Self { ctx }
    }

    /// `wallC(x, z, v, d, f, cor)`.
    fn wall_cell(&self, x: i32, z: i32, v: i32, d: i32, f: u8, cor: bool) -> Option<VoxelValue> {
        let (plan, look) = (&self.ctx.plan, &self.ctx.look);
        let u = HousePlan::wall_u(f, x, z);
        let sty = plan.style();
        let st = plan.st;
        let pierre = |ex: i32| -> Option<VoxelValue> {
            plan.courses.stone(u, v, d, ex, false).map(|n| {
                if v < PL + 8 && n != 0 {
                    // mousse au pied du mur
                    let b = crate::batiments::kit::noise::vnoise2(u * 3, v * 2, 5, 3);
                    if b > 40_000 {
                        return val(look.m.moss, 40 + (hh(x, v, z, 16) % 50) as u8);
                    }
                }
                crate::batiments::kit::matieres::pierre(look.stone, n)
            })
        };
        if sty != WallStyle::Stone && v >= PL {
            let mut bm = v < PL + 3;
            for k in 1..=st {
                let c0 = if k == st { plan.hw - 5 } else { k * SH - 2 };
                if v >= c0 && v < c0 + if k == st { 5 } else { 4 } {
                    bm = true;
                }
            }
            let along = if f < 2 { 2 } else { 0 };
            if bm {
                return Some(look.timber(v, d, 2, along));
            }
            if cor || u.rem_euclid(plan.params.wall.posts) < 5 {
                return Some(look.timber(u, d, 1, 1));
            }
            if sty == WallStyle::TimberPlaster {
                if d < 1 {
                    return None;
                }
                return Some(look.plaster(x, v, z, PL + 12));
            }
            return pierre(1);
        }
        pierre(0)
    }
}

impl Part for WallsPart {
    fn bounds(&self) -> VoxelBox {
        let plan = &self.ctx.plan;
        let (xr, zr) = corps_box(plan);
        VoxelBox::new(
            VoxelCoord::new(xr[0], -1, zr[0]),
            VoxelCoord::new(xr[1], plan.top_y, zr[1]),
        )
        .expect("boîte")
    }

    fn paint(&self, w: &mut Window) {
        let (plan, look) = (&self.ctx.plan, &self.ctx.look);
        let b = self.bounds();
        let (a, c) = (b.min(), b.max());
        let Some((lo, hi)) = w.clip([a.x, a.y, a.z], [c.x, c.y, c.z]) else {
            return;
        };
        for z in lo[2]..hi[2] {
            for x in lo[0]..hi[0] {
                let i = plan.ix(x, z);
                if plan.fm[i] == 0 {
                    continue;
                }
                let ds = i32::from(plan.ds[i]);
                if ds == 0 || ds > T {
                    if lo[1] <= -1 {
                        w.put(x, -1, z, look.floor(x, z));
                    }
                    for k in 1..=plan.st {
                        if k == 1 && plan.in_hole(x, z) {
                            continue;
                        }
                        for v in (k * SH - 3).max(lo[1])..(k * SH).min(hi[1]) {
                            w.put(x, v, z, look.ceiling(x, v, z));
                        }
                    }
                    continue;
                }
                let f = plan.fc[i];
                let d = ds - 1;
                let top = plan.wall_top(i);
                let mut ox = false;
                let mut oz = false;
                for k in 1..=6 {
                    if !plan.in_f(x + k, z) || !plan.in_f(x - k, z) {
                        ox = true;
                    }
                    if !plan.in_f(x, z + k) || !plan.in_f(x, z - k) {
                        oz = true;
                    }
                }
                let cor = ox && oz;
                for v in lo[1].max(0)..top.min(hi[1]) {
                    if let Some(val) = self.wall_cell(x, z, v, d, f, cor) {
                        w.put(x, v, z, val);
                    }
                }
            }
        }
    }
}

/// Le toit d'un corps : remplissage, bords en bois, queues de chevrons.
pub struct RoofPart {
    ctx: Arc<Ctx>,
    body: usize,
}

impl RoofPart {
    /// Toit du corps `body`.
    pub fn new(ctx: Arc<Ctx>, body: usize) -> Self {
        Self { ctx, body }
    }
}

impl Part for RoofPart {
    fn bounds(&self) -> VoxelBox {
        let plan = &self.ctx.plan;
        let b = &plan.bodies[self.body];
        let ev = plan.params.roof.eave;
        let lo = (plan.hw + (-plan.params.roof.slope100 * ev).div_euclid(100) - 6).max(0);
        VoxelBox::new(
            VoxelCoord::new(b.rx0, lo, b.rz0),
            VoxelCoord::new(b.rx1, plan.top_y, b.rz1),
        )
        .expect("boîte")
    }

    fn paint(&self, w: &mut Window) {
        let (plan, look) = (&self.ctx.plan, &self.ctx.look);
        let b = &plan.bodies[self.body];
        let (ev, sl100, moss) = (
            plan.params.roof.eave,
            plan.params.roof.slope100,
            plan.params.roof.moss100,
        );
        let bb = self.bounds();
        let (a, c) = (bb.min(), bb.max());
        let Some((lo, hi)) = w.clip([a.x, a.y, a.z], [c.x, c.y, c.z]) else {
            return;
        };
        for z in lo[2]..hi[2] {
            for x in lo[0]..hi[0] {
                let Some(r) = roof_at(b, x, z, plan.hw, ev, sl100) else {
                    continue;
                };
                let (a_lo, a_hi) = if b.main { (b.rx0, b.rx1) } else { (b.rz0, b.rz1) };
                let edge = r.p2 < -2 * ev + 4 || r.al < a_lo + 2 || r.al >= a_hi - 2;
                let along = if b.main { 0 } else { 2 };
                for v in r.bot.max(lo[1])..=r.top.min(hi[1] - 1) {
                    let val = if v == r.bot {
                        look.timber_dark(along)
                    } else if edge {
                        look.timber(x, v, z, along)
                    } else if r.cap {
                        look.ridge(x, v, z)
                    } else {
                        look.roof_tile(r.sl_k, r.al + 1000, x, z, moss)
                    };
                    w.put(x, v, z, val);
                }
                // queues de chevrons sous l'égout
                let pos = if b.main { x } else { z };
                if r.p2 < 0
                    && !plan.in_f(x, z)
                    && !((x - plan.dxw).abs() < 24 && z >= plan.dz1 - 1)
                    && pos.rem_euclid(10) < 2
                {
                    for v in (r.bot - 3).max(0)..r.bot {
                        w.put_if_empty(x, v, z, look.timber(x, v, z, if b.main { 2 } else { 0 }));
                    }
                }
            }
        }
        let _ = (TH, SANS_TOIT);
    }
}

/// La porte d'entrée, ses marches, son auvent (perron) et sa lanterne.
pub struct DoorPart {
    ctx: Arc<Ctx>,
}

impl DoorPart {
    /// Crée la partie.
    pub fn new(ctx: Arc<Ctx>) -> Self {
        Self { ctx }
    }
}

/// Hauteur du bord de l'auvent à la profondeur `d` (négative) : `bt`.
fn porch_bt(pt: i32, d: i32) -> i32 {
    pt - ((-d - 1) / 4)
}

impl Part for DoorPart {
    fn bounds(&self) -> VoxelBox {
        let plan = &self.ctx.plan;
        let (fr, dr, u0) = (&plan.dfr, plan.params.door, plan.du0);
        let mut b = Bb::new();
        b.frame(fr, (u0 - 8, u0 + dr.w + 8), (0, dr.h + 6), (-12, T));
        b.frame(fr, (u0 - 16, u0 + dr.w + 17), (0, plan.hw + 2), (-31, 0));
        b.into_box()
    }

    fn paint(&self, win: &mut Window) {
        let (plan, look, opts) = (&self.ctx.plan, &self.ctx.look, self.ctx.opts);
        let (fr, dr, u0) = (&plan.dfr, plan.params.door, plan.du0);
        let (w, h) = (dr.w, dr.h);
        // ouverture dans le mur, encadrement de pierre
        for uu in -6..w + 6 {
            for vv in 0..h + 6 {
                let o = op(uu, vv, w, h, dr.arch, 0);
                let rg = op(uu, vv, w, h, dr.arch, 3);
                let u = u0 + uu;
                if rg && !o {
                    for d in 0..T {
                        put(win, fr, u, vv, d, look.trim_stone(u, vv, d));
                    }
                } else if o {
                    for d in 0..T {
                        put(win, fr, u, vv, d, VoxelValue::AIR);
                    }
                }
            }
        }
        // battant de bois
        if opts.door_leaf {
            for uu in 0..w {
                for vv in 0..h {
                    if !op(uu, vv, w, h, dr.arch, 0) {
                        continue;
                    }
                    for d in T - 3..T - 1 {
                        let planche = uu % 4 == 3;
                        let sangle = vv == 8 || vv == h - 10;
                        let v = if sangle {
                            look.iron(uu, vv, d)
                        } else if planche {
                            look.timber_dark(1)
                        } else {
                            look.accent(look.door_accent, 1, 0, (u0 + uu, vv, d))
                        };
                        put(win, fr, u0 + uu, vv, d, v);
                    }
                    if uu == w - 4 && vv == h / 2 {
                        put(win, fr, u0 + uu, vv, T - 4, look.iron(uu, vv, 1));
                    }
                }
            }
        }
        // marches de pierre
        for uu in -8..w + 8 {
            for d in -12..=-1 {
                for v in 0..3 {
                    put(win, fr, u0 + uu, v, d, look.trim_stone(uu, d, v));
                }
            }
        }
        if dr.porch {
            let (pu0, pu1, pd) = (u0 - 16, u0 + w + 16, 30);
            let pt = (h + 14).min(plan.hw - 3);
            for u in pu0..pu1 {
                for d in (-pd..=-1).rev() {
                    let t = porch_bt(pt, d);
                    let (x, z) = fr.xz(u, d);
                    let sl_k = i64::from(pd - 1 - (-d - 1)) * 103 * (1 << 20) / 100;
                    let edge = u < pu0 + 2 || u >= pu1 - 2 || d < -pd + 2;
                    for v in t - 3..=t {
                        let val = if v == t - 3 {
                            look.timber_dark(0)
                        } else if edge {
                            look.timber(u, v, d, 0)
                        } else {
                            look.roof_tile(sl_k, u + 1000, x, z, plan.params.roof.moss100)
                        };
                        win.put(x, v, z, val);
                    }
                }
            }
            for pu in [pu0 + 3, pu1 - 7] {
                let top = porch_bt(pt, -pd + 3) - 3;
                for a in 0..4 {
                    for c in 0..4 {
                        for v in 0..top {
                            put(win, fr, pu + a, v, -pd + 2 + c, look.timber(pu + a, v, c, 1));
                        }
                    }
                }
                let dir = if pu < u0 { 1 } else { -1 };
                let x0 = if dir > 0 { pu + 4 } else { pu - 1 };
                for k in 1..=9 {
                    for c in 0..4 {
                        let t = look.timber(k, c, pu, 0);
                        put(win, fr, x0 + dir * (k - 1), top - k, -pd + 2 + c, t);
                        put(win, fr, x0 + dir * (k - 1), top - k - 1, -pd + 2 + c, t);
                    }
                }
            }
            // lanterne suspendue
            let (lu, ld) = (u0 + w + 5, -14);
            let lb = porch_bt(pt, ld) - 3;
            for v in lb - 3..lb {
                put(win, fr, lu + 1, v, ld - 1, look.iron(lu, v, 0));
            }
            for a in 0..4 {
                for c in 0..4 {
                    for k in 0..6 {
                        let corner = (a == 0 || a == 3) && (c == 0 || c == 3);
                        let cap = k == 0 || k == 5;
                        let v = if corner || cap {
                            look.iron(a, k, c)
                        } else {
                            val(look.m.glow, 64)
                        };
                        put(win, fr, lu + a, lb - 3 - k - 1, ld - c, v);
                    }
                }
            }
        }
    }
}

/// La cheminée extérieure (fût, base large, couronnement ajouré).
pub struct ChimneyPart {
    ctx: Arc<Ctx>,
}

impl ChimneyPart {
    /// Crée la partie.
    pub fn new(ctx: Arc<Ctx>) -> Self {
        Self { ctx }
    }
}

impl Part for ChimneyPart {
    fn bounds(&self) -> VoxelBox {
        let plan = &self.ctx.plan;
        let mut b = Bb::new();
        b.frame(
            &plan.cfr,
            (plan.chim_uc - 14, plan.chim_uc + 15),
            (0, plan.chim_top + 9),
            (-18, 0),
        );
        b.into_box()
    }

    fn paint(&self, win: &mut Window) {
        let (plan, look) = (&self.ctx.plan, &self.ctx.look);
        let (cfr, uc, top) = (&plan.cfr, plan.chim_uc, plan.chim_top);
        for v in 0..top + 8 {
            let wide = v < plan.hw - 4;
            let (hw, dd) = if wide { (13, 18) } else { (11, 15) };
            for u in uc - hw..=uc + hw {
                for d in -dd..=-1 {
                    if v < top {
                        let (x, z) = cfr.xz(u, d);
                        if let Some(n) = plan.courses.stone(x + z + 600, v, 0, 0, true) {
                            put(
                                win,
                                cfr,
                                u,
                                v,
                                d,
                                crate::batiments::kit::matieres::pierre(look.stone, n),
                            );
                        }
                    }
                }
            }
        }
        let (cw, cd) = (13, 17);
        for v in top..top + 8 {
            for u in uc - cw..=uc + cw {
                for d in -cd..=-1 {
                    if v < top + 3 {
                        put(win, cfr, u, v, d, look.trim_stone(u, v, d));
                    } else {
                        let ring = (u - uc).abs() > cw - 4 || d < -cd + 3;
                        if ring && (u - uc).abs() > 2 && (d + 9).abs() > 2 {
                            put(win, cfr, u, v, d, look.trim_stone(u, v, d));
                        }
                    }
                }
            }
        }
    }
}

/// L'appentis à bois : auvent incliné, poteaux et tas de bûches rondes.
pub struct ShedPart {
    ctx: Arc<Ctx>,
}

impl ShedPart {
    /// Crée la partie.
    pub fn new(ctx: Arc<Ctx>) -> Self {
        Self { ctx }
    }
}

impl Part for ShedPart {
    fn bounds(&self) -> VoxelBox {
        let mut b = Bb::new();
        if let Some((fr, us, ue)) = &self.ctx.plan.shed {
            b.frame(fr, (*us - 4, *ue + 4), (0, self.ctx.plan.hw + 2), (-36, 0));
        }
        b.into_box()
    }

    fn paint(&self, win: &mut Window) {
        let (plan, look) = (&self.ctx.plan, &self.ctx.look);
        let Some((sfr, us, ue)) = &plan.shed else {
            return;
        };
        let (us, ue) = (*us, *ue);
        let (ls, ds): (i32, i32) = (ue - us, 34);
        let va = (plan.hw - 6).min(48);
        for u in us - 4..ue + 4 {
            for k in 0..ds + 2 {
                let d = -1 - k;
                let t = va + 2 - (k * 26).div_euclid(100);
                let (x, z) = sfr.xz(u, d);
                let sl_k = i64::from(ds + 1 - k) * 103 * (1 << 20) / 100;
                let edge = u < us - 2 || u >= ue + 2 || k >= ds;
                for v in t - 3..=t {
                    let val = if v == t - 3 {
                        look.timber_dark(0)
                    } else if edge {
                        look.timber(u, v, d, 0)
                    } else {
                        look.roof_tile(sl_k, u + 1000, x, z, plan.params.roof.moss100)
                    };
                    win.put(x, v, z, val);
                }
            }
        }
        let mut posts = vec![us, ue - 4];
        if ls > 60 {
            posts.push((us + ue) / 2);
        }
        for pu in posts {
            for a in 0..4 {
                for c in 0..4 {
                    let d = -ds + c + 1;
                    let t = va + 2 - ((ds - c) * 26).div_euclid(100) - 4;
                    for v in 0..t {
                        put(win, sfr, pu + a, v, d, look.timber(pu + a, v, c, 1));
                    }
                }
            }
        }
        // tas de bûches : rondins de 6 voxels de diamètre, rangées décalées
        for u in us + 2..ue - 2 {
            let tp = 20 + hh_below(hh(u.div_euclid(6), 1, 5, 0), 7) as i32;
            for v in 0..tp {
                let j = (v * 10).div_euclid(52);
                let sh = if j & 1 == 1 { 3 } else { 0 };
                let cx = crate::batiments::kit::intmath::round_div(u - sh, 6) * 6 + sh;
                let cy100 = j * 520 + 300;
                let dx100 = (u - cx) * 100;
                let dy100 = v * 100 + 50 - cy100;
                let dd2 = i64::from(dx100) * i64::from(dx100) + i64::from(dy100) * i64::from(dy100);
                for d in -16..=-1 {
                    let c = if dd2 < 290 * 290 {
                        if d == -16 {
                            // bout de la bille : cœur clair, cernes, écorce
                            if dd2 < 90 * 90 {
                                val(look.m.oak_planks, 100)
                            } else if dd2 < 200 * 200 {
                                val(look.m.oak_planks, 62)
                            } else {
                                val(
                                    look.m.timber,
                                    crate::batiments::kit::matieres::bois(look.m.timber, 3, 4).tint(),
                                )
                            }
                        } else {
                            look.timber(u, v, d, 0)
                        }
                    } else {
                        val(look.m.coal, 8)
                    };
                    put(win, sfr, u, v, d, c);
                }
            }
        }
        let _ = hh_lt;
    }
}
