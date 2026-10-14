//! em_water: shallow water on a graph of columns, for Emergence.
//!
//! Model (see the design note delivered with this crate):
//! * Water is a volume per column (integer mm^3), never voxels. Cells are one
//!   voxel column (5 cm, "fine") or 5x5 columns (25 cm, "coarse") in the same
//!   graph, so the 5 cm zone can be limited to the neighbourhood of the player.
//! * Edges carry one opening per voxel pair across the boundary, each with its
//!   own sill height: a one-voxel wall or a one-voxel gap is seen by the water
//!   even through a 25 cm cell.
//! * Flux law: local inertial approximation of the shallow water equations
//!   (Bates, Horritt & Fewtrell 2010, as in LISFLOOD-FP) with Manning friction,
//!   capped by critical (weir) flow when the water falls over a sill.
//! * Exact conservation: every edge flux is subtracted from one cell and added
//!   to the other as the same integer. Two-phase update (all fluxes from the old
//!   state, then apply), so results do not depend on iteration order.
//! * Deterministic: only + - * / and sqrt (IEEE, correctly rounded); the cube
//!   root is a fixed Newton iteration. No powf/exp/sin.
//! * Cheap: only awake cells and their edges are visited; a cell with no flux
//!   goes to sleep and costs nothing until something touches it.

pub const VOX: f64 = 0.05;
pub const SUB: usize = 5;
pub const G: f64 = 9.81;
const VOX_AREA: f64 = VOX * VOX;
const MM3_PER_M3: f64 = 1.0e9;

/// Deterministic cube root (pure arithmetic).
#[inline]
pub fn cbrt_det(x: f64) -> f64 {
    if x <= 0.0 {
        return 0.0;
    }
    let bits = x.to_bits();
    let mut y = f64::from_bits(bits / 3 + (682u64 << 52));
    for _ in 0..4 {
        y = (2.0 * y + x / (y * y)) * (1.0 / 3.0);
    }
    y
}

#[derive(Clone, Debug)]
pub struct Params {
    /// Manning roughness (s/m^(1/3)); 0.03-0.05 for natural streams.
    pub manning_n: f64,
    /// CFL safety factor. The literature gives 0.7 as the limit of this scheme;
    /// on this graph with the flux cap the pond test goes unstable above ~0.45
    /// when the step is cut short, so the default keeps a wide margin.
    pub alpha: f64,
    pub dt_max: f64,
    pub dt_min: f64,
    /// Below this head over a sill nothing flows (m).
    pub d_min: f64,
    /// Added to |q| in the friction term: gives a viscous-like damping near rest.
    pub q_floor: f64,
    /// A flux this small across a level difference this small is snapped to rest.
    pub rest_eta: f64,
    pub rest_q: f64,
    /// Broad-crested weir coefficient (Q = c H^1.5 per metre of width).
    pub c_free: f64,
    /// Critical-flow coefficient when the edge is submerged: sqrt(g).
    pub c_sub: f64,
}

impl Default for Params {
    fn default() -> Self {
        Params {
            manning_n: 0.04,
            alpha: 0.35,
            dt_max: 1.0 / 30.0,
            dt_min: 2.0e-4,
            d_min: 5.0e-4,
            q_floor: 0.003,
            rest_eta: 2.0e-5,
            rest_q: 2.0e-4,
            c_free: 1.705,
            c_sub: G.sqrt(),
        }
    }
}

/// Domain of `w` x `h` voxel columns (multiples of 5). Cells inside the `fine`
/// rectangle (voxel coordinates `[x0, z0, x1, z1)`, multiples of 5) are single
/// columns; the rest of the domain is made of 5x5 cells.
#[derive(Clone, Debug)]
pub struct Layout {
    pub w: usize,
    pub h: usize,
    pub fine: Option<[usize; 4]>,
}

impl Layout {
    pub fn all_fine(w: usize, h: usize) -> Self {
        Layout { w, h, fine: Some([0, 0, w, h]) }
    }
    pub fn all_coarse(w: usize, h: usize) -> Self {
        Layout { w, h, fine: None }
    }
    pub fn with_fine(w: usize, h: usize, rect: [usize; 4]) -> Self {
        Layout { w, h, fine: Some(rect) }
    }
}

struct Source {
    cells: Vec<u32>,
    rate_m3s: f64,
    acc_mm3: f64,
}

struct Pair {
    a: u32,
    b: u32,
    u: u32,
    v: u32,
    axis: u8,
}

pub struct Sim {
    pub p: Params,
    pub w: usize,
    pub h: usize,
    top: Vec<f32>,
    cell_of: Vec<u32>,
    // cells
    cox: Vec<u32>,
    coz: Vec<u32>,
    cr: Vec<u8>,
    csize: Vec<f64>,
    poff: Vec<u32>,
    psort: Vec<f64>,
    pcum: Vec<f64>,
    cmin: Vec<f64>,
    vol: Vec<i64>,
    lvl: Vec<f64>,
    // edges
    ea: Vec<u32>,
    eb: Vec<u32>,
    el: Vec<f64>,
    oo: Vec<u32>,
    osill: Vec<f64>,
    oq: Vec<f64>,
    ou: Vec<u32>,
    ov: Vec<u32>,
    adj_off: Vec<u32>,
    adj: Vec<u32>,
    // dynamic state
    active: Vec<u32>,
    inact: Vec<bool>,
    pending: Vec<u32>,
    next_active: Vec<u32>,
    act_edges: Vec<u32>,
    touched: Vec<u32>,
    edv: Vec<f64>,
    ev: Vec<f64>,
    efrac: Vec<f64>,
    cm1: Vec<f64>,
    ce1: Vec<u32>,
    cm2: Vec<f64>,
    out: Vec<f64>,
    scl: Vec<f64>,
    estamp: Vec<u64>,
    cstamp: Vec<u64>,
    astamp: Vec<u64>,
    stamp: u64,
    sources: Vec<Source>,
    sinks: Vec<u32>,
    pub drained_mm3: i64,
    pub injected_mm3: i64,
    pub time: f64,
    pub steps: u64,
    pub last_dt: f64,
}

impl Sim {
    pub fn new(layout: Layout, top: Vec<f32>, p: Params) -> Sim {
        Self::new_ordered(layout, top, p, false)
    }

    /// `reverse_edges` only exists to test that results do not depend on edge order.
    pub fn new_ordered(layout: Layout, top: Vec<f32>, p: Params, reverse_edges: bool) -> Sim {
        let (w, h) = (layout.w, layout.h);
        assert!(w % SUB == 0 && h % SUB == 0, "domain must be a multiple of 5 voxels");
        assert_eq!(top.len(), w * h);
        let mut cell_of = vec![u32::MAX; w * h];
        let (mut cox, mut coz, mut cr) = (Vec::new(), Vec::new(), Vec::new());
        let in_fine = |x: usize, z: usize| match layout.fine {
            Some([x0, z0, x1, z1]) => x >= x0 && x < x1 && z >= z0 && z < z1,
            None => false,
        };
        if let Some([x0, z0, x1, z1]) = layout.fine {
            assert!(x0 % SUB == 0 && z0 % SUB == 0 && x1 % SUB == 0 && z1 % SUB == 0);
            for z in z0..z1 {
                for x in x0..x1 {
                    cell_of[z * w + x] = cox.len() as u32;
                    cox.push(x as u32);
                    coz.push(z as u32);
                    cr.push(1u8);
                }
            }
        }
        for bz in 0..h / SUB {
            for bx in 0..w / SUB {
                let (x, z) = (bx * SUB, bz * SUB);
                if in_fine(x, z) {
                    continue;
                }
                let id = cox.len() as u32;
                cox.push(x as u32);
                coz.push(z as u32);
                cr.push(SUB as u8);
                for dz in 0..SUB {
                    for dx in 0..SUB {
                        cell_of[(z + dz) * w + x + dx] = id;
                    }
                }
            }
        }
        let nc = cox.len();
        let csize: Vec<f64> = cr.iter().map(|&r| r as f64 * VOX).collect();

        // Profiles.
        let mut poff = vec![0u32; nc + 1];
        for c in 0..nc {
            poff[c + 1] = poff[c] + (cr[c] as u32) * (cr[c] as u32);
        }
        let total = poff[nc] as usize;
        let mut sim = Sim {
            p,
            w,
            h,
            top,
            cell_of,
            cox,
            coz,
            cr,
            csize,
            poff,
            psort: vec![0.0; total],
            pcum: vec![0.0; total],
            cmin: vec![0.0; nc],
            vol: vec![0; nc],
            lvl: vec![0.0; nc],
            ea: Vec::new(),
            eb: Vec::new(),
            el: Vec::new(),
            oo: vec![0],
            osill: Vec::new(),
            oq: Vec::new(),
            ou: Vec::new(),
            ov: Vec::new(),
            adj_off: Vec::new(),
            adj: Vec::new(),
            active: Vec::new(),
            inact: vec![false; nc],
            pending: Vec::new(),
            next_active: Vec::new(),
            act_edges: Vec::new(),
            touched: Vec::new(),
            edv: Vec::new(),
            ev: Vec::new(),
            efrac: Vec::new(),
            cm1: vec![0.0; nc],
            ce1: vec![u32::MAX; nc],
            cm2: vec![0.0; nc],
            out: vec![0.0; nc],
            scl: vec![1.0; nc],
            estamp: Vec::new(),
            cstamp: vec![0; nc],
            astamp: vec![0; nc],
            stamp: 0,
            sources: Vec::new(),
            sinks: Vec::new(),
            drained_mm3: 0,
            injected_mm3: 0,
            time: 0.0,
            steps: 0,
            last_dt: 0.0,
        };
        for c in 0..nc {
            sim.build_profile(c);
            sim.lvl[c] = sim.cmin[c];
        }

        // Edges: every voxel adjacency that crosses a cell boundary is one opening.
        let mut pairs: Vec<Pair> = Vec::new();
        for z in 0..h {
            for x in 0..w {
                let i = z * w + x;
                let c = sim.cell_of[i];
                if x + 1 < w {
                    let j = i + 1;
                    let c2 = sim.cell_of[j];
                    if c != c2 {
                        pairs.push(if c < c2 {
                            Pair { a: c, b: c2, u: i as u32, v: j as u32, axis: 0 }
                        } else {
                            Pair { a: c2, b: c, u: j as u32, v: i as u32, axis: 0 }
                        });
                    }
                }
                if z + 1 < h {
                    let j = i + w;
                    let c2 = sim.cell_of[j];
                    if c != c2 {
                        pairs.push(if c < c2 {
                            Pair { a: c, b: c2, u: i as u32, v: j as u32, axis: 1 }
                        } else {
                            Pair { a: c2, b: c, u: j as u32, v: i as u32, axis: 1 }
                        });
                    }
                }
            }
        }
        pairs.sort_by_key(|p| (p.a, p.b, p.u));
        let mut groups: Vec<(usize, usize)> = Vec::new(); // [start, end) in pairs
        let mut s = 0;
        while s < pairs.len() {
            let mut e = s + 1;
            while e < pairs.len() && pairs[e].a == pairs[s].a && pairs[e].b == pairs[s].b {
                e += 1;
            }
            groups.push((s, e));
            s = e;
        }
        if reverse_edges {
            groups.reverse();
        }
        for &(s, e) in &groups {
            let (a, b) = (pairs[s].a as usize, pairs[s].b as usize);
            let axis = pairs[s].axis;
            let center = |c: usize, ax: u8| -> f64 {
                let o = if ax == 0 { sim.cox[c] } else { sim.coz[c] } as f64;
                (o + sim.cr[c] as f64 * 0.5) * VOX
            };
            let l = (center(a, axis) - center(b, axis)).abs();
            sim.ea.push(a as u32);
            sim.eb.push(b as u32);
            sim.el.push(l);
            for pr in &pairs[s..e] {
                let sill = sim.top[pr.u as usize].max(sim.top[pr.v as usize]) as f64;
                sim.osill.push(sill);
                sim.oq.push(0.0);
                sim.ou.push(pr.u);
                sim.ov.push(pr.v);
            }
            sim.oo.push(sim.osill.len() as u32);
        }
        let ne = sim.ea.len();
        sim.edv = vec![0.0; ne];
        sim.ev = vec![0.0; ne];
        sim.efrac = vec![0.0; ne];
        sim.estamp = vec![0; ne];
        // Adjacency (CSR).
        let mut cnt = vec![0u32; nc + 1];
        for e in 0..ne {
            cnt[sim.ea[e] as usize + 1] += 1;
            cnt[sim.eb[e] as usize + 1] += 1;
        }
        for c in 0..nc {
            cnt[c + 1] += cnt[c];
        }
        sim.adj_off = cnt.clone();
        sim.adj = vec![0; cnt[nc] as usize];
        let mut fill = cnt;
        for e in 0..ne {
            for &c in &[sim.ea[e], sim.eb[e]] {
                sim.adj[fill[c as usize] as usize] = e as u32;
                fill[c as usize] += 1;
            }
        }
        sim
    }

    fn build_profile(&mut self, c: usize) {
        let r = self.cr[c] as usize;
        let (ox, oz) = (self.cox[c] as usize, self.coz[c] as usize);
        let po = self.poff[c] as usize;
        let n = r * r;
        let mut k = 0;
        for dz in 0..r {
            for dx in 0..r {
                self.psort[po + k] = self.top[(oz + dz) * self.w + ox + dx] as f64;
                k += 1;
            }
        }
        self.psort[po..po + n].sort_by(|a, b| a.partial_cmp(b).unwrap());
        for m in 0..n {
            let sm = self.psort[po + m];
            let mut acc = 0.0;
            for j in 0..m {
                acc += sm - self.psort[po + j];
            }
            self.pcum[po + m] = acc * VOX_AREA;
        }
        self.cmin[c] = self.psort[po];
    }

    #[inline]
    fn level_of(&self, c: usize, v: i64) -> f64 {
        let po = self.poff[c] as usize;
        let vm3 = v as f64 / MM3_PER_M3;
        let n = (self.cr[c] as usize) * (self.cr[c] as usize);
        if n == 1 {
            return self.psort[po] + vm3 / VOX_AREA;
        }
        let s = &self.psort[po..po + n];
        let cu = &self.pcum[po..po + n];
        let mut m = 0;
        while m + 1 < n && cu[m + 1] <= vm3 {
            m += 1;
        }
        s[m] + (vm3 - cu[m]) / ((m + 1) as f64 * VOX_AREA)
    }

    // ---- public API -----------------------------------------------------

    pub fn n_cells(&self) -> usize {
        self.cox.len()
    }
    pub fn n_edges(&self) -> usize {
        self.ea.len()
    }
    pub fn n_openings(&self) -> usize {
        self.osill.len()
    }
    pub fn n_active_cells(&self) -> usize {
        self.active.len()
    }
    pub fn n_active_edges(&self) -> usize {
        self.act_edges.len()
    }
    pub fn cell_at(&self, vx: usize, vz: usize) -> usize {
        self.cell_of[vz * self.w + vx] as usize
    }
    pub fn top_at(&self, vx: usize, vz: usize) -> f64 {
        self.top[vz * self.w + vx] as f64
    }
    pub fn total_volume_mm3(&self) -> i64 {
        self.vol.iter().sum()
    }
    pub fn total_volume_m3(&self) -> f64 {
        self.total_volume_mm3() as f64 / MM3_PER_M3
    }
    pub fn cell_volume_mm3(&self, c: usize) -> i64 {
        self.vol[c]
    }
    pub fn cell_level(&self, c: usize) -> f64 {
        self.lvl[c]
    }
    pub fn min_volume_mm3(&self) -> i64 {
        *self.vol.iter().min().unwrap_or(&0)
    }

    /// Surface level above the column's top (0 if dry in this column).
    pub fn depth_at(&self, vx: usize, vz: usize) -> f64 {
        let c = self.cell_at(vx, vz);
        (self.lvl[c] - self.top[vz * self.w + vx] as f64).max(0.0)
    }
    pub fn level_at(&self, vx: usize, vz: usize) -> f64 {
        self.lvl[self.cell_at(vx, vz)]
    }

    pub fn add_volume_mm3(&mut self, c: usize, mm3: i64) {
        self.vol[c] += mm3;
        self.injected_mm3 += mm3;
        self.lvl[c] = self.level_of(c, self.vol[c]);
        self.pending.push(c as u32);
    }

    /// Bucket: removes up to `mm3` from a cell, returns what was taken.
    pub fn take_volume_mm3(&mut self, c: usize, mm3: i64) -> i64 {
        let t = mm3.min(self.vol[c]).max(0);
        self.vol[c] -= t;
        self.drained_mm3 += t;
        self.lvl[c] = self.level_of(c, self.vol[c]);
        self.pending.push(c as u32);
        t
    }

    /// Continuous inflow spread evenly over `cells`. Returns the source index.
    pub fn add_source(&mut self, cells: Vec<u32>, rate_m3s: f64) -> usize {
        self.sources.push(Source { cells, rate_m3s, acc_mm3: 0.0 });
        self.sources.len() - 1
    }
    pub fn set_source_rate(&mut self, i: usize, rate_m3s: f64) {
        self.sources[i].rate_m3s = rate_m3s;
    }
    /// Cells that empty completely each step (free outflow boundary).
    pub fn add_sinks(&mut self, cells: &[u32]) {
        self.sinks.extend_from_slice(cells);
    }

    /// Changes the height of one voxel column (dig, place a block).
    /// Water volume is kept: the level rises or falls to conserve it.
    pub fn set_top(&mut self, vx: usize, vz: usize, new_top: f32) {
        let i = vz * self.w + vx;
        self.top[i] = new_top;
        let c = self.cell_of[i] as usize;
        self.build_profile(c);
        self.lvl[c] = self.level_of(c, self.vol[c]);
        self.pending.push(c as u32);
        // openings that touch this voxel
        for &e in &self.adj[self.adj_off[c] as usize..self.adj_off[c + 1] as usize] {
            let e = e as usize;
            let (o0, o1) = (self.oo[e] as usize, self.oo[e + 1] as usize);
            for k in o0..o1 {
                if self.ou[k] as usize == i || self.ov[k] as usize == i {
                    let s = self.top[self.ou[k] as usize].max(self.top[self.ov[k] as usize]) as f64;
                    self.osill[k] = s;
                }
            }
            let other = if self.ea[e] as usize == c { self.eb[e] } else { self.ea[e] };
            self.pending.push(other);
        }
    }

    /// Per-voxel volumes (mm^3): coarse cells are spread over their columns at
    /// the cell's level. The sum is exactly the total volume.
    pub fn voxel_volumes(&self) -> Vec<i64> {
        let mut out = vec![0i64; self.w * self.h];
        for c in 0..self.n_cells() {
            let r = self.cr[c] as usize;
            let (ox, oz) = (self.cox[c] as usize, self.coz[c] as usize);
            if r == 1 {
                out[oz * self.w + ox] = self.vol[c];
                continue;
            }
            let eta = self.lvl[c];
            let mut sum = 0i64;
            let mut lowest = (f32::MAX, 0usize);
            for dz in 0..r {
                for dx in 0..r {
                    let i = (oz + dz) * self.w + ox + dx;
                    let t = self.top[i];
                    if t < lowest.0 {
                        lowest = (t, i);
                    }
                    let v = ((eta - t as f64).max(0.0) * VOX_AREA * MM3_PER_M3).floor() as i64;
                    out[i] = v;
                    sum += v;
                }
            }
            out[lowest.1] += self.vol[c] - sum;
        }
        out
    }

    /// Rebuild with another layout (the fine zone follows the player), keeping every mm^3.
    pub fn regrid(&self, layout: Layout) -> Sim {
        let vv = self.voxel_volumes();
        let mut s = Sim::new(layout, self.top.clone(), self.p.clone());
        for c in 0..s.n_cells() {
            let r = s.cr[c] as usize;
            let (ox, oz) = (s.cox[c] as usize, s.coz[c] as usize);
            let mut v = 0i64;
            for dz in 0..r {
                for dx in 0..r {
                    v += vv[(oz + dz) * s.w + ox + dx];
                }
            }
            s.vol[c] = v;
            s.lvl[c] = s.level_of(c, v);
            if v > 0 {
                s.pending.push(c as u32);
            }
        }
        s.injected_mm3 = self.injected_mm3;
        s.drained_mm3 = self.drained_mm3;
        s.time = self.time;
        s
    }

    /// FNV-1a over the volumes (cell order does not depend on edge order).
    pub fn state_hash(&self) -> u64 {
        let mut h = 0xcbf29ce484222325u64;
        for &v in &self.vol {
            h ^= v as u64;
            h = h.wrapping_mul(0x100000001b3);
        }
        h
    }

    /// Net flow (m^3/s) across the plane between columns xb-1 and xb, toward +x.
    pub fn flux_across_x(&self, xb: usize) -> f64 {
        let mut tot = 0.0;
        for k in 0..self.osill.len() {
            let (ux, vx) = (self.ou[k] as usize % self.w, self.ov[k] as usize % self.w);
            let (uz, vz) = (self.ou[k] as usize / self.w, self.ov[k] as usize / self.w);
            if uz != vz {
                continue;
            }
            if ux + 1 == xb && vx == xb {
                tot += self.oq[k] * VOX;
            } else if ux == xb && vx + 1 == xb {
                tot -= self.oq[k] * VOX;
            }
        }
        tot
    }

    // ---- time stepping ---------------------------------------------------

    fn merge_pending(&mut self) {
        for i in 0..self.sources.len() {
            for j in 0..self.sources[i].cells.len() {
                let c = self.sources[i].cells[j];
                self.pending.push(c);
            }
        }
        for j in 0..self.sinks.len() {
            let c = self.sinks[j];
            self.pending.push(c);
        }
        for i in 0..self.pending.len() {
            let c = self.pending[i] as usize;
            if !self.inact[c] {
                self.inact[c] = true;
                self.active.push(c as u32);
            }
        }
        self.pending.clear();
    }

    fn stable_dt(&self) -> f64 {
        let mut dt = self.p.dt_max;
        for &c in &self.active {
            let c = c as usize;
            let depth = (self.lvl[c] - self.cmin[c]).max(0.02);
            let d = self.p.alpha * self.csize[c] / (G * depth).sqrt();
            if d < dt {
                dt = d;
            }
        }
        dt.max(self.p.dt_min)
    }

    /// Advances by `t` seconds with adaptive sub-steps. Returns the number of steps.
    pub fn advance(&mut self, t: f64) -> u64 {
        let mut rem = t;
        let mut n = 0;
        while rem > 1e-12 {
            self.merge_pending();
            let mut dt = self.stable_dt();
            if dt > rem {
                dt = rem;
            }
            self.step(dt);
            rem -= dt;
            n += 1;
        }
        n
    }

    /// One explicit step of length `dt` (the caller must respect the CFL limit).
    pub fn step(&mut self, dt: f64) {
        self.merge_pending();
        // sources
        for i in 0..self.sources.len() {
            self.sources[i].acc_mm3 += self.sources[i].rate_m3s * dt * MM3_PER_M3;
            let whole = self.sources[i].acc_mm3.floor();
            if whole >= 1.0 {
                self.sources[i].acc_mm3 -= whole;
                let whole = whole as i64;
                let n = self.sources[i].cells.len() as i64;
                let (share, rest) = (whole / n, whole % n);
                for j in 0..self.sources[i].cells.len() {
                    let c = self.sources[i].cells[j] as usize;
                    let add = share + if (j as i64) < rest { 1 } else { 0 };
                    self.vol[c] += add;
                    self.injected_mm3 += add;
                    self.lvl[c] = self.level_of(c, self.vol[c]);
                }
            }
        }

        self.stamp += 1;
        let st = self.stamp;
        // active edges
        self.act_edges.clear();
        for ai in 0..self.active.len() {
            let c = self.active[ai] as usize;
            for j in self.adj_off[c] as usize..self.adj_off[c + 1] as usize {
                let e = self.adj[j] as usize;
                if self.estamp[e] != st {
                    self.estamp[e] = st;
                    self.act_edges.push(e as u32);
                }
            }
        }

        let n2 = self.p.manning_n * self.p.manning_n;
        let (dmin, qfl, rest_eta, rest_q) = (self.p.d_min, self.p.q_floor, self.p.rest_eta, self.p.rest_q);
        let (cfree, c_sub) = (self.p.c_free, self.p.c_sub);

        // phase 1: proposed fluxes from the old state
        for ei in 0..self.act_edges.len() {
            let e = self.act_edges[ei] as usize;
            let a = self.ea[e] as usize;
            let b = self.eb[e] as usize;
            let (la, lb) = (self.lvl[a], self.lvl[b]);
            let hi = la.max(lb);
            let lo = la.min(lb);
            let grad = (lb - la) / self.el[e];
            let rest = (lb - la).abs() < rest_eta;
            let mut dvq = 0.0;
            let mut evmax = 0.0f64;
            for k in self.oo[e] as usize..self.oo[e + 1] as usize {
                let sill = self.osill[k];
                let d = hi - sill;
                if d <= dmin {
                    self.oq[k] = 0.0;
                    continue;
                }
                let qo = self.oq[k];
                let d73 = d * d * cbrt_det(d);
                let fr = dt * G * n2 * (qo.abs() + qfl) / d73;
                let mut q = (qo - dt * G * d * grad) / (1.0 + fr);
                if q > 0.0 && la - sill <= dmin {
                    q = 0.0;
                } else if q < 0.0 && lb - sill <= dmin {
                    q = 0.0;
                }
                // Maximum discharge. Over a sill with a free drop downstream this
                // is the broad-crested weir law (critical flow, c_free ~ 1.705);
                // when the downstream water covers the sill it rises to critical
                // flow at the local depth (sqrt(g) d^1.5). It depends only on
                // the current levels (no lagged state), which keeps it stable.
                let dn = (lo - sill).max(0.0);
                // KNOWN LIMITATION (measured, see tests T5b/T3b): this stateless ramp over-opens a
                // narrow slot (one-voxel gap leaks ~35 % more than the thin-weir law) and makes
                // 5 cm stairs ~15 % too deep. Alternatives tried and rejected because they broke
                // torrents or produced piled-up cells: tailwater/head threshold ramps (0.3..0.7),
                // tailwater/critical-depth ramps, energy-based caps with approach velocity.
                let sub = (dn / d).min(1.0);
                let cap = d * d.sqrt() * (cfree + (c_sub - cfree) * sub);
                if q > cap {
                    q = cap;
                } else if q < -cap {
                    q = -cap;
                }
                if rest && q.abs() < rest_q {
                    q = 0.0;
                }
                self.oq[k] = q;
                dvq += q;
                let vk = q.abs() / d;
                if vk > evmax {
                    evmax = vk;
                }
            }
            self.ev[e] = evmax;
            let dv = dvq * VOX * dt;
            self.edv[e] = dv;
            if dv > 0.0 {
                self.out[a] += dv;
            } else if dv < 0.0 {
                self.out[b] -= dv;
            }
        }

        // phase 2: a cell cannot give more than it holds
        self.touched.clear();
        for ei in 0..self.act_edges.len() {
            let e = self.act_edges[ei] as usize;
            for &c in &[self.ea[e], self.eb[e]] {
                let c = c as usize;
                if self.cstamp[c] != st {
                    self.cstamp[c] = st;
                    self.touched.push(c as u32);
                    let o = self.out[c] * MM3_PER_M3;
                    let v = self.vol[c] as f64;
                    self.scl[c] = if o > v { v / o } else { 1.0 };
                }
            }
        }

        // phase 3: apply integer transfers
        self.next_active.clear();
        for ei in 0..self.act_edges.len() {
            let e = self.act_edges[ei] as usize;
            let a = self.ea[e] as usize;
            let b = self.eb[e] as usize;
            let dv = self.edv[e];
            let mut alive = false;
            let mut want = dv * MM3_PER_M3; // signed, mm^3, a -> b positive
            if dv != 0.0 {
                let src = if dv > 0.0 { a } else { b };
                let sc = self.scl[src];
                if sc < 1.0 {
                    // supply-limited: the cell cannot give more than it holds
                    want *= sc;
                    for k in self.oo[e] as usize..self.oo[e + 1] as usize {
                        self.oq[k] *= sc;
                    }
                }
            }
            // Integer transfer with the rounding remainder carried to the next
            // step, so slow flows are not biased by truncation.
            let t = want + self.efrac[e];
            let amt = t.trunc();
            self.efrac[e] = t - amt;
            let mut ai = amt as i64;
            if ai > 0 {
                ai = ai.min(self.vol[a]);
            } else if ai < 0 {
                ai = -((-ai).min(self.vol[b]));
            }
            if ai != 0 {
                self.vol[a] -= ai;
                self.vol[b] += ai;
                alive = true;
            }
            if !alive {
                for k in self.oo[e] as usize..self.oo[e + 1] as usize {
                    if self.oq[k] != 0.0 {
                        alive = true;
                        break;
                    }
                }
            }
            if !alive {
                self.ev[e] = 0.0;
            }
            if alive {
                for &c in &[a, b] {
                    if self.astamp[c] != st {
                        self.astamp[c] = st;
                        self.next_active.push(c as u32);
                    }
                }
            }
        }
        // refresh levels, reset scratch
        for ti in 0..self.touched.len() {
            let c = self.touched[ti] as usize;
            self.out[c] = 0.0;
            self.lvl[c] = self.level_of(c, self.vol[c]);
            let (mut m1, mut e1, mut m2) = (0.0f64, u32::MAX, 0.0f64);
            for j in self.adj_off[c] as usize..self.adj_off[c + 1] as usize {
                let e = self.adj[j];
                let v = self.ev[e as usize];
                if v > m1 {
                    m2 = m1;
                    m1 = v;
                    e1 = e;
                } else if v > m2 {
                    m2 = v;
                }
            }
            self.cm1[c] = m1;
            self.ce1[c] = e1;
            self.cm2[c] = m2;
        }
        // sinks
        for si in 0..self.sinks.len() {
            let c = self.sinks[si] as usize;
            self.drained_mm3 += self.vol[c];
            self.vol[c] = 0;
            self.lvl[c] = self.cmin[c];
        }
        // sleep / wake bookkeeping
        for i in 0..self.active.len() {
            self.inact[self.active[i] as usize] = false;
        }
        std::mem::swap(&mut self.active, &mut self.next_active);
        for i in 0..self.active.len() {
            self.inact[self.active[i] as usize] = true;
        }
        self.time += dt;
        self.steps += 1;
        self.last_dt = dt;
    }
}

/// Height field helper for tests and benchmarks.
pub fn heights(w: usize, h: usize, f: impl Fn(f64, f64) -> f64) -> Vec<f32> {
    let mut v = Vec::with_capacity(w * h);
    for z in 0..h {
        for x in 0..w {
            v.push(f((x as f64 + 0.5) * VOX, (z as f64 + 0.5) * VOX) as f32);
        }
    }
    v
}

#[cfg(test)]
mod unit {
    use super::*;
    #[test]
    fn cbrt_accuracy() {
        let mut x = 1e-6;
        while x < 1e6 {
            let r = (cbrt_det(x) - x.cbrt()).abs() / x.cbrt();
            assert!(r < 1e-13, "x={} rel={}", x, r);
            x *= 1.37;
        }
    }
}
