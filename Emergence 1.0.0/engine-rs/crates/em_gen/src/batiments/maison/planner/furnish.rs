//! L'ameublement : port de la fin de `build(P)` (placement des meubles, tapis, lampes, décors muraux). Tout est
//! décision : les meubles sont enregistrés (`Deco`) dans l'ordre du JavaScript et ne seront dessinés qu'à la
//! rastérisation. La connectivité des pièces (`rInfo`) est vérifiée à chaque pose : un meuble qui couperait une
//! pièce en deux (ou fermerait une porte) est refusé, comme dans le générateur de Monsieur.

use super::{Affine, Deco, Planner, Room, RoomType, SH};
use crate::batiments::kit::intmath::isqrt;
use crate::batiments::maison::furniture::Kind;

/// Résultat de `wallPlace` : face et position le long de la face.
#[derive(Copy, Clone)]
struct Wall {
    side: u8,
    a: i32,
}

/// Résultat de `freePlace` : table posée librement.
#[derive(Copy, Clone)]
struct Table {
    rot: bool,
    x: i32,
    z: i32,
    tw: i32,
    td: i32,
}

fn wall_map(bx: [i32; 4], side: u8, a: i32, ko: i32) -> Affine {
    match side {
        0 => Affine {
            o: (a, bx[2] + ko),
            iv: (1, 0),
            kv: (0, 1),
        },
        1 => Affine {
            o: (a, bx[3] - 1 - ko),
            iv: (1, 0),
            kv: (0, -1),
        },
        2 => Affine {
            o: (bx[0] + ko, a),
            iv: (0, 1),
            kv: (1, 0),
        },
        _ => Affine {
            o: (bx[1] - 1 - ko, a),
            iv: (0, 1),
            kv: (-1, 0),
        },
    }
}

impl Planner {
    fn shuffle<T>(&mut self, a: &mut [T]) {
        for i in (1..a.len()).rev() {
            let j = self.r.below(i as u32 + 1) as usize;
            a.swap(i, j);
        }
    }

    fn set_tone(&mut self, rid: usize) {
        let r = &self.rooms[rid];
        self.wood_tone = super::HousePlan::room_tone(r.id, r.s);
    }

    /// `fitM` : les cellules du meuble si elles sont toutes libres et dans la pièce.
    fn fit_m(&self, rid: usize, kind: Kind, map: Affine, soft: bool) -> Option<Vec<usize>> {
        let s = self.rooms[rid].s as usize;
        let mut cells = Vec::with_capacity((kind.w() * kind.dp()) as usize);
        for i in 0..kind.w() {
            for k in 0..kind.dp() {
                let q = map.at(i, k);
                let c = self.ix(q.0, q.1);
                let o = self.occ2[s][c];
                if i32::from(self.rm[s][c]) != rid as i32 || (o != 0 && !(soft && o == 4)) {
                    return None;
                }
                cells.push(c);
            }
        }
        Some(cells)
    }

    /// Connectivité de la pièce : (toutes les ancres atteignables, nombre de cases libres coupées de la première ancre).
    fn r_info(&self, rid: usize) -> (bool, i32) {
        let r = &self.rooms[rid];
        let s = r.s as usize;
        let (w, h) = (r.bx[1] - r.bx[0] + 10, r.bx[3] - r.bx[2] + 10);
        let (ox, oz) = (r.bx[0] - 5, r.bx[2] - 5);
        let w1 = w + 1;
        let bl = |x: i32, y: i32| -> i32 {
            let (xx, zz) = (ox + x, oz + y);
            let c = self.ix(xx, zz);
            i32::from(
                self.ins[c] == 0
                    || self.pmc[s][c] != 0
                    || self.occ2[s][c] == 1
                    || (s == 1 && self.in_hole(xx, zz))
                    || (s == 0 && self.in_stair(xx, zz)),
            )
        };
        let mut q = vec![0_i32; ((w + 1) * (h + 1)) as usize];
        for y in 0..h {
            let mut row = 0;
            for x in 0..w {
                row += bl(x, y);
                q[((y + 1) * w1 + x + 1) as usize] = q[(y * w1 + x + 1) as usize] + row;
            }
        }
        let ok = |x: i32, y: i32| -> bool {
            x >= 3
                && y >= 3
                && x < w - 4
                && y < h - 4
                && q[((y + 4) * w1 + x + 4) as usize]
                    - q[((y - 3) * w1 + x + 4) as usize]
                    - q[((y + 4) * w1 + x - 3) as usize]
                    + q[((y - 3) * w1 + x - 3) as usize]
                    == 0
        };
        let dirs = [(1, 0), (-1, 0), (0, 1), (0, -1)];
        let near = |a: usize| -> Option<usize> {
            let x0 = (a as i32 % self.nx) - self.ox - ox;
            let y0 = (a as i32 / self.nx) - self.oz - oz;
            if x0 < 0 || y0 < 0 || x0 >= w || y0 >= h {
                return None;
            }
            let mut vis = vec![false; (w * h) as usize];
            let mut qq = vec![(y0 * w + x0) as usize];
            vis[qq[0]] = true;
            let mut hd = 0;
            while hd < qq.len() && hd < 900 {
                let k = qq[hd];
                hd += 1;
                let (x, y) = (k as i32 % w, k as i32 / w);
                if ok(x, y) {
                    return Some(k);
                }
                for (dx, dy) in dirs {
                    let (nx, ny) = (x + dx, y + dy);
                    if nx < 0 || ny < 0 || nx >= w || ny >= h {
                        continue;
                    }
                    let n = (ny * w + nx) as usize;
                    if !vis[n] && bl(nx, ny) == 0 {
                        vis[n] = true;
                        qq.push(n);
                    }
                }
            }
            None
        };
        if r.anch.is_empty() {
            return (true, 0);
        }
        let Some(sd) = near(r.anch[0]) else {
            return (false, 0);
        };
        let mut seen = vec![false; (w * h) as usize];
        let mut q2 = vec![sd];
        seen[sd] = true;
        let mut hd = 0;
        while hd < q2.len() {
            let k = q2[hd];
            hd += 1;
            let (x, y) = (k as i32 % w, k as i32 / w);
            for (dx, dy) in dirs {
                let (nx, ny) = (x + dx, y + dy);
                if nx < 0 || ny < 0 || nx >= w || ny >= h {
                    continue;
                }
                let n = (ny * w + nx) as usize;
                if !seen[n] && ok(nx, ny) {
                    seen[n] = true;
                    q2.push(n);
                }
            }
        }
        let mut un = 0;
        for y in 0..h {
            for x in 0..w {
                if i32::from(self.rm[s][self.ix(ox + x, oz + y)]) == rid as i32
                    && ok(x, y)
                    && !seen[(y * w + x) as usize]
                {
                    un += 1;
                }
            }
        }
        let tous = r.anch.iter().all(|a| near(*a).is_some_and(|k| seen[k]));
        (tous, un)
    }

    /// `putIt` : pose le meuble si la pièce reste connexe, et l'enregistre.
    fn put_it(&mut self, rid: usize, kind: Kind, map: Affine, cells: &[usize]) -> bool {
        let s = self.rooms[rid].s as usize;
        if self.rooms[rid].base.is_none() {
            self.rooms[rid].base = Some(self.r_info(rid));
        }
        for c in cells {
            self.occ2[s][*c] = 1;
        }
        let ri = self.r_info(rid);
        let base = self.rooms[rid].base.unwrap_or((true, 0));
        if (base.0 && !ri.0) || ri.1 > base.1 + 8 {
            for c in cells {
                self.occ2[s][*c] = 0;
            }
            return false;
        }
        for c in cells {
            self.oh[s][*c] = kind.h();
        }
        let q = self.r.below(1000) as i32;
        self.decos.push(Deco::Item {
            kind,
            q,
            map,
            base: s as i32 * SH,
            tone: self.wood_tone,
        });
        true
    }

    fn wall_place(&mut self, rid: usize, kind: Kind, ko: i32, soft: bool) -> Option<Wall> {
        let bx = self.rooms[rid].bx;
        let s = self.rooms[rid].s as usize;
        let mut cs: Vec<(u8, i32)> = Vec::new();
        for side in 0..4_u8 {
            let hz = side < 2;
            let (lo, hi) = if hz { (bx[0], bx[1]) } else { (bx[2], bx[3]) };
            let mut a = lo;
            while a <= hi - kind.w() {
                cs.push((side, a));
                a += 2;
            }
        }
        self.shuffle(&mut cs);
        for (side, a) in cs {
            let m = wall_map(bx, side, a, ko);
            let Some(cells) = self.fit_m(rid, kind, m, soft) else {
                continue;
            };
            if ko == 0 {
                let mut wl = 0;
                for i in 0..kind.w() {
                    let q = m.at(i, -1);
                    if i32::from(self.rm[s][self.ix(q.0, q.1)]) != rid as i32 {
                        wl += 1;
                    }
                }
                if wl * 10 < kind.w() * 7 {
                    continue;
                }
            }
            if self.put_it(rid, kind, m, &cells) {
                return Some(Wall { side, a });
            }
        }
        None
    }

    fn ring_ok(&self, rid: usize, x0: i32, z0: i32, w: i32, d: i32, g: i32) -> bool {
        let s = self.rooms[rid].s as usize;
        for z in z0 - g..z0 + d + g {
            for x in x0 - g..x0 + w + g {
                let c = self.ix(x, z);
                if i32::from(self.rm[s][c]) != rid as i32 || self.occ2[s][c] == 1 {
                    return false;
                }
            }
        }
        true
    }

    fn free_place(&mut self, rid: usize, kind: Kind, ring: i32) -> Option<Table> {
        let bx = self.rooms[rid].bx;
        let mut cs: Vec<(bool, i32, i32, u128)> = Vec::new();
        for rot in [false, true] {
            let mut x = bx[0] + 4;
            while x < bx[1] - 4 {
                let mut z = bx[2] + 4;
                while z < bx[3] - 4 {
                    let (tw, td) = if rot {
                        (kind.dp(), kind.w())
                    } else {
                        (kind.w(), kind.dp())
                    };
                    let dx2 = i128::from(2 * x + tw - (bx[0] + bx[1]));
                    let dz2 = i128::from(2 * z + td - (bx[2] + bx[3]));
                    let n = u128::from(self.r.next_u32());
                    let key = isqrt(((dx2 * dx2 + dz2 * dz2) as u128) << 64) / 2 + 6 * n;
                    cs.push((rot, x, z, key));
                    z += 2;
                }
                x += 2;
            }
        }
        cs.sort_by_key(|c| c.3);
        for (rot, x, z, _) in cs.into_iter().take(500) {
            let m = if rot {
                Affine {
                    o: (x, z),
                    iv: (0, 1),
                    kv: (1, 0),
                }
            } else {
                Affine {
                    o: (x, z),
                    iv: (1, 0),
                    kv: (0, 1),
                }
            };
            let Some(cells) = self.fit_m(rid, kind, m, false) else {
                continue;
            };
            let (tw, td) = if rot {
                (kind.dp(), kind.w())
            } else {
                (kind.w(), kind.dp())
            };
            if self.ring_ok(rid, x, z, tw, td, ring) && self.put_it(rid, kind, m, &cells) {
                return Some(Table { rot, x, z, tw, td });
            }
        }
        None
    }

    fn pl(&mut self, rid: usize, kind: Kind, m: Affine) {
        if let Some(cells) = self.fit_m(rid, kind, m, false) {
            self.put_it(rid, kind, m, &cells);
        }
    }

    fn around(&mut self, rid: usize, t: Table) {
        let (tw, td) = if t.rot { (18, 34) } else { (34, 18) };
        let aff = |o: (i32, i32), iv: (i32, i32), kv: (i32, i32)| Affine { o, iv, kv };
        if !t.rot {
            for i0 in [4, 22] {
                self.pl(rid, Kind::Chair, aff((t.x + i0, t.z - 9), (1, 0), (0, 1)));
                self.pl(
                    rid,
                    Kind::Chair,
                    aff((t.x + i0, t.z + td + 1 + 7), (1, 0), (0, -1)),
                );
            }
            self.pl(rid, Kind::Stool, aff((t.x - 8, t.z + 5), (1, 0), (0, 1)));
            self.pl(rid, Kind::Stool, aff((t.x + tw + 1, t.z + 5), (1, 0), (0, 1)));
        } else {
            for i0 in [4, 22] {
                self.pl(rid, Kind::Chair, aff((t.x - 9, t.z + i0), (0, 1), (1, 0)));
                self.pl(
                    rid,
                    Kind::Chair,
                    aff((t.x + tw + 1 + 7, t.z + i0), (0, 1), (-1, 0)),
                );
            }
            self.pl(rid, Kind::Stool, aff((t.x + 5, t.z - 8), (1, 0), (0, 1)));
            self.pl(rid, Kind::Stool, aff((t.x + 5, t.z + td + 1), (1, 0), (0, 1)));
        }
    }

    fn around_r(&mut self, rid: usize, t: Table) {
        for (dx, dz) in [(-8, 7), (23, 7), (7, -8), (7, 23)] {
            let m = Affine {
                o: (t.x + dx, t.z + dz),
                iv: (1, 0),
                kv: (0, 1),
            };
            if let Some(cells) = self.fit_m(rid, Kind::Stool, m, false) {
                self.put_it(rid, Kind::Stool, m, &cells);
            }
        }
    }

    /// `rug` : un tapis rectangulaire (bordure, liseré) ou rond sous la table `t`.
    fn rug(&mut self, rid: usize, t_x: i32, t_z: i32, tw: i32, td: i32, rnd: bool) {
        let color = self.r.below(5) as u8;
        let r = &self.rooms[rid];
        let s = r.s as usize;
        let (x0, z0, w, d) = (t_x - 5, t_z - 5, tw + 10, td + 10);
        let mut cells = Vec::new();
        for z in z0..z0 + d {
            for x in x0..x0 + w {
                let c = self.ix(x, z);
                if i32::from(self.rm[s][c]) != rid as i32 || self.occ2[s][c] == 1 {
                    continue;
                }
                let e100 = if rnd {
                    let u = i64::from(2 * x + 1 - 2 * x0 - w) * 100 / i64::from(w);
                    let v = i64::from(2 * z + 1 - 2 * z0 - d) * 100 / i64::from(d);
                    let q = isqrt((u * u + v * v) as u128) as i64; // x100
                    if q > 100 {
                        continue;
                    }
                    ((100 - q) * i64::from(w.min(d)) / 2) as i32
                } else {
                    100 * (x - x0).min(x0 + w - 1 - x).min(z - z0).min(z0 + d - 1 - z)
                };
                cells.push((x, z, e100));
            }
        }
        self.decos.push(Deco::Rug {
            base: s as i32 * SH,
            color,
            cells,
        });
    }

    fn floor_rug(&mut self, rid: usize) {
        let bx = self.rooms[rid].bx;
        let (cx, cz) = ((bx[0] + bx[1]) >> 1, (bx[2] + bx[3]) >> 1);
        let w = 24 + self.r.below(10) as i32;
        let d = 18 + self.r.below(8) as i32;
        let rnd = self.r.half();
        self.rug(rid, cx - (w >> 1) + 5, cz - (d >> 1) + 5, w - 10, d - 10, rnd);
    }

    /// `decor` : accroche un décor mural.
    fn decor(&mut self, rid: usize, kind: Kind) -> bool {
        let bx = self.rooms[rid].bx;
        let s = self.rooms[rid].s as usize;
        let mut cs: Vec<(u8, i32)> = Vec::new();
        for side in 0..4_u8 {
            let hz = side < 2;
            let (lo, hi) = if hz { (bx[0], bx[1]) } else { (bx[2], bx[3]) };
            let mut a = lo;
            while a <= hi - kind.w() {
                cs.push((side, a));
                a += 2;
            }
        }
        self.shuffle(&mut cs);
        'essai: for (side, a) in cs {
            let m = wall_map(bx, side, a, 0);
            let mut cells = Vec::new();
            for i in 0..kind.w() {
                let q = m.at(i, -1);
                if i32::from(self.rm[s][self.ix(q.0, q.1)]) == rid as i32 {
                    continue 'essai;
                }
                for k in 0..kind.dp() {
                    let p = m.at(i, k);
                    let c = self.ix(p.0, p.1);
                    if i32::from(self.rm[s][c]) != rid as i32
                        || self.occ2[s][c] >= 2
                        || (self.occ2[s][c] == 1 && self.oh[s][c] >= kind.j0() - 1)
                    {
                        continue 'essai;
                    }
                    cells.push(c);
                }
            }
            if self.rooms[rid].base.is_none() {
                self.rooms[rid].base = Some(self.r_info(rid));
            }
            let chg: Vec<usize> = cells.iter().copied().filter(|c| self.occ2[s][*c] == 0).collect();
            for c in &chg {
                self.occ2[s][*c] = 1;
            }
            let ri = self.r_info(rid);
            let base = self.rooms[rid].base.unwrap_or((true, 0));
            if (base.0 && !ri.0) || ri.1 > base.1 + 8 {
                for c in &chg {
                    self.occ2[s][*c] = 0;
                }
                continue;
            }
            for c in &cells {
                self.oh[s][*c] = self.oh[s][*c].max(kind.j0() + kind.h());
            }
            let q = self.r.below(1000) as i32;
            self.decos.push(Deco::Item {
                kind,
                q,
                map: m,
                base: s as i32 * SH + kind.j0(),
                tone: self.wood_tone,
            });
            return true;
        }
        false
    }

    fn lamp(&mut self, rid: usize) {
        let r = &self.rooms[rid];
        let (cx, cz) = ((r.bx[0] + r.bx[1]) >> 1, (r.bx[2] + r.bx[3]) >> 1);
        let mut best: Option<(i32, i32)> = None;
        let mut bd = i64::MAX;
        for c in &r.cells {
            let x = (*c as i32 % self.nx) - self.ox;
            let z = (*c as i32 / self.nx) - self.oz;
            let d = i64::from(x - cx).pow(2) + i64::from(z - cz).pow(2);
            if d < bd {
                bd = d;
                best = Some((x, z));
            }
        }
        let Some((x, z)) = best else {
            return;
        };
        let vc = (r.s + 1) * SH - 3;
        let big = r.cells.len() > 3500;
        let living = r.kind == Some(RoomType::Living);
        let round = living || (big && self.r.half());
        self.decos.push(Deco::Lamp { x, z, vc, round });
        self.n_lights_extra();
    }

    fn n_lights_extra(&mut self) {}

    fn place_bed(&mut self, rid: usize, area: usize, soft: bool) -> bool {
        let bi = if self.r.half() { Kind::BedD } else { Kind::BedS };
        let (b, bt) = match self.wall_place(rid, bi, 0, soft) {
            Some(b) => (b, bi),
            None => match self.wall_place(rid, Kind::BedS, 0, soft) {
                Some(b) => (b, Kind::BedS),
                None => return false,
            },
        };
        self.n_fur += 1;
        self.n_bed += 1;
        let bx = self.rooms[rid].bx;
        for a in [b.a + bt.w() + 1, b.a - Kind::Night.w() - 1] {
            let m = wall_map(bx, b.side, a, 0);
            if let Some(cells) = self.fit_m(rid, Kind::Night, m, false)
                && self.put_it(rid, Kind::Night, m, &cells)
            {
                self.n_fur += 1;
                if self.r.half() {
                    break;
                }
            }
        }
        let m = wall_map(bx, b.side, b.a + ((bt.w() - Kind::Chest.w()) >> 1), bt.dp() + 1);
        if let Some(cells) = self.fit_m(rid, Kind::Chest, m, false)
            && self.put_it(rid, Kind::Chest, m, &cells)
        {
            self.n_fur += 1;
        }
        if area > 3600 && self.r.percent(60) && self.wall_place(rid, Kind::BedS, 0, false).is_some() {
            self.n_fur += 1;
            self.n_bed += 1;
        }
        true
    }

    fn place_kit(&mut self, rid: usize, soft: bool) -> bool {
        if self.wall_place(rid, Kind::Stove, 0, soft).is_none() {
            return false;
        }
        self.n_fur += 1;
        self.n_kit += 1;
        if self.wall_place(rid, Kind::Counter, 0, soft).is_some() {
            self.n_fur += 1;
        }
        if self.r.half() && self.wall_place(rid, Kind::Counter, 0, soft).is_some() {
            self.n_fur += 1;
        }
        true
    }

    /// `w_(it, n, pr)` : tente `n` fois de poser `it` contre un mur (avec la probabilité `pr` en centièmes).
    fn w_(&mut self, rid: usize, kind: Kind, n: i32, pr: u32) {
        for _ in 0..n {
            if self.r.percent(pr) && self.wall_place(rid, kind, 0, false).is_some() {
                self.n_fur += 1;
            }
        }
    }

    fn pick<T: Copy>(&mut self, a: &[T]) -> T {
        a[self.r.below(a.len() as u32) as usize]
    }

    fn tbl(&mut self, rid: usize) {
        let rnd = self.r.percent(35);
        let kind = if rnd { Kind::RoundT } else { Kind::Table };
        let t = self
            .free_place(rid, kind, 9)
            .or_else(|| self.free_place(rid, kind, 4))
            .or_else(|| self.free_place(rid, kind, 0));
        if let Some(t) = t {
            self.n_fur += 1;
            self.rug(rid, t.x, t.z, t.tw, t.td, rnd);
            if rnd {
                self.around_r(rid, t);
            } else {
                self.around(rid, t);
            }
        }
    }

    /// Meuble toutes les pièces, dans l'ordre du JavaScript.
    pub(super) fn furnish(&mut self) {
        use Kind::*;
        use RoomType as RT;
        let cand = |r: &Room| r.cells.len() >= 150 && r.kind.is_some() && r.kind != Some(RT::Hall);
        let by_a = |pl: &Planner, mut ids: Vec<usize>| -> Vec<usize> {
            ids.sort_by_key(|i| std::cmp::Reverse(pl.rooms[*i].cells.len()));
            ids
        };
        // passe prioritaire : cuisine et lit
        let kitchens: Vec<usize> = self
            .rooms
            .iter()
            .filter(|r| cand(r) && r.kind == Some(RT::Kitchen))
            .map(|r| r.id)
            .collect();
        let others: Vec<usize> = self
            .rooms
            .iter()
            .filter(|r| cand(r) && r.kind != Some(RT::Kitchen))
            .map(|r| r.id)
            .collect();
        let mut kc = by_a(self, kitchens);
        kc.extend(by_a(self, others));
        for soft in [false, true] {
            if self.n_kit > 0 {
                break;
            }
            for rid in &kc {
                self.set_tone(*rid);
                if self.place_kit(*rid, soft) {
                    self.rooms[*rid].kit = true;
                    break;
                }
            }
        }
        let bedrooms: Vec<usize> = self
            .rooms
            .iter()
            .filter(|r| cand(r) && r.kind == Some(RT::Bedroom))
            .map(|r| r.id)
            .collect();
        let neither: Vec<usize> = self
            .rooms
            .iter()
            .filter(|r| cand(r) && r.kind != Some(RT::Bedroom) && r.kind != Some(RT::Kitchen))
            .map(|r| r.id)
            .collect();
        let kits: Vec<usize> = self
            .rooms
            .iter()
            .filter(|r| cand(r) && r.kind == Some(RT::Kitchen))
            .map(|r| r.id)
            .collect();
        let mut bc = by_a(self, bedrooms);
        bc.extend(by_a(self, neither));
        bc.extend(by_a(self, kits));
        for soft in [false, true] {
            if self.n_bed > 0 {
                break;
            }
            for rid in &bc {
                self.set_tone(*rid);
                let a = self.rooms[*rid].cells.len();
                if self.place_bed(*rid, a, soft) {
                    self.rooms[*rid].bed = true;
                    break;
                }
            }
        }
        // chaque pièce
        for rid in 0..self.rooms.len() {
            let (n, kind) = (self.rooms[rid].cells.len(), self.rooms[rid].kind);
            if n < 150 || kind.is_none() {
                continue;
            }
            self.set_tone(rid);
            self.lamp(rid);
            match kind {
                Some(RT::Living) => {
                    self.tbl(rid);
                    let k = self.pick(&[Settle, Bench]);
                    self.w_(rid, k, 1, 100);
                    let c = 1 + i32::from(self.r.half());
                    self.w_(rid, Armchair, c, 100);
                    let k = self.pick(&[BookL, Shelf]);
                    let c = 1 + i32::from(n > 2500);
                    self.w_(rid, k, c, 100);
                    let k = self.pick(&[Dresser, Cupboard]);
                    self.w_(rid, k, 1, 100);
                    self.w_(rid, Chest, 1, 70);
                    let k = self.pick(&[Barrel, Sacks]);
                    self.w_(rid, k, 1, 80);
                    let c = 1 + i32::from(self.r.half());
                    self.w_(rid, Plant, c, 90);
                }
                Some(RT::Kitchen) => {
                    if !self.rooms[rid].kit {
                        self.place_kit(rid, false);
                    }
                    self.tbl(rid);
                    self.w_(rid, Cupboard, 1, 60);
                    self.w_(rid, Shelf, 1, 100);
                    self.w_(rid, Barrel, 1, 80);
                    self.w_(rid, Sacks, 1, 100);
                    self.w_(rid, CrateS, 1, 100);
                    self.w_(rid, Bucket, 1, 70);
                    self.w_(rid, Plant, 1, 50);
                }
                Some(RT::Bedroom) => {
                    if !self.rooms[rid].bed {
                        self.place_bed(rid, n, false);
                    }
                    let k = self.pick(&[Ward, Dresser]);
                    self.w_(rid, k, 1, 100);
                    self.w_(rid, Mirror, 1, 60);
                    self.w_(rid, Armchair, 1, 50);
                    self.w_(rid, Wheel, 1, 30);
                    self.w_(rid, Cot, 1, 25);
                    self.w_(rid, BookL, 1, 40);
                    self.w_(rid, Plant, 1, 60);
                    self.w_(rid, Chest, 1, 40);
                    self.floor_rug(rid);
                }
                Some(RT::Study) => {
                    self.tbl(rid);
                    let k = self.pick(&[BookL, Shelf]);
                    let c = 2 + i32::from(self.r.half());
                    self.w_(rid, k, c, 100);
                    self.w_(rid, Globe, 1, 100);
                    self.w_(rid, Lectern, 1, 60);
                    self.w_(rid, Armchair, 1, 100);
                    self.w_(rid, Chest, 1, 60);
                    self.w_(rid, Plant, 1, 60);
                }
                Some(RT::Store) => {
                    self.w_(rid, Bench2, 1, 100);
                    self.w_(rid, Anvil, 1, 50);
                    self.w_(rid, CrateS, 2, 100);
                    self.w_(rid, Barrel, 2, 100);
                    self.w_(rid, Sacks, 2, 100);
                    self.w_(rid, Shelf, 1, 100);
                    self.w_(rid, Bucket, 1, 60);
                    self.w_(rid, Chest, 1, 50);
                }
                Some(RT::Hall) | None => {}
            }
        }
        // garanties : une cuisine et un lit dans chaque maison
        let mut big: Vec<usize> = self
            .rooms
            .iter()
            .filter(|r| r.cells.len() >= 150 && r.kind != Some(RT::Hall))
            .map(|r| r.id)
            .collect();
        big.sort_by_key(|i| std::cmp::Reverse(self.rooms[*i].cells.len()));
        if self.n_kit == 0 {
            for rid in &big {
                self.set_tone(*rid);
                if self.place_kit(*rid, true) {
                    break;
                }
            }
        }
        if self.n_bed == 0 {
            for rid in &big {
                self.set_tone(*rid);
                let a = self.rooms[*rid].cells.len();
                if self.place_bed(*rid, a, true) {
                    break;
                }
            }
        }
        for rid in 0..self.rooms.len() {
            if self.rooms[rid].cells.len() < 150 || self.rooms[rid].kind.is_none() {
                continue;
            }
            self.set_tone(rid);
            let mut decs: Vec<Kind> = match self.rooms[rid].kind {
                Some(RT::Living) => vec![Painting, Banner, Shield, Swords, Sconce, Sconce],
                Some(RT::Kitchen) => vec![Herbs, Herbs, Painting, Sconce],
                Some(RT::Bedroom) => vec![Painting, Painting, Banner, Sconce],
                Some(RT::Study) => vec![MapD, MapD, Painting, Shield, Sconce],
                Some(RT::Store) => vec![Swords, Shield, Sconce],
                Some(RT::Hall) => vec![Banner, Painting, Sconce],
                None => vec![],
            };
            self.shuffle(&mut decs);
            let mut nd = 0;
            for k in decs {
                if nd >= 5 {
                    break;
                }
                if self.decor(rid, k) {
                    nd += 1;
                    self.n_fur += 1;
                }
            }
        }
    }
}
