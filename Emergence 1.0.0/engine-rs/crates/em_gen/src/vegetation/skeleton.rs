//! Le squelette : croissance stochastique ordre par ordre (tronc, charpentières, branches, rameaux,
//! brindilles) avec phyllotaxie à l'angle d'or, tropismes, enveloppe de couronne propre à l'essence et
//! auto-élagage par cellules d'encombrement. Port de `Grower` / `BushGrower` de `voxel_tree.py` /
//! `voxel_bush.py` : on porte la sémantique, pas les bits du générateur numpy.
//!
//! Toute l'arithmétique est entière (Q16 de voxel, tours Q16). L'architecture (flèche qui se fourche ou touffe
//! multi-tiges) est un trait : `TreeArchitecture` et `MultiStemArchitecture` remplacent la sous-classe Python.

use std::collections::BTreeMap;

use super::fx::{self, Stream, UN, V3, VOX_PAR_M};
use super::species::{ArchKind, CrownShape, Species};

/// Angle d'or en tours Q16 (0,381966).
const ANGLE_OR: i64 = 25_033;
/// 0,25 radian en tours Q16.
const QUART_RADIAN: i64 = 2_608;
/// 0,35 radian en tours Q16.
const TIERS_RADIAN: i64 = 3_651;

/// Un nœud du squelette.
#[derive(Copy, Clone, Debug, PartialEq, Eq)]
pub struct Node {
    /// Position (Q16 de voxel, pied du tronc à l'origine).
    pub pos: V3,
    /// Direction unitaire de la pousse.
    pub dir: V3,
    /// Nœud parent (-1 pour la racine).
    pub par: i32,
    /// Ordre de la branche (0 tronc, 1 charpentière, 2 branche, 3 rameau, 4 brindille).
    pub order: u8,
    /// Position le long de la branche, de 0 à 1 (Q16).
    pub t: i64,
}

/// Le squelette obtenu.
#[derive(Clone, Debug, Default)]
pub struct Skeleton {
    /// Les nœuds (la racine d'abord).
    pub nodes: Vec<Node>,
    /// Bouquets de feuilles : (nœud, rayon en Q16 de voxel).
    pub leafy: Vec<(usize, i64)>,
    /// Nœuds sans feuilles pouvant porter fleurs et fruits.
    pub bloom: Vec<usize>,
}

impl Skeleton {
    fn add(&mut self, pos: V3, par: i32, order: u8, t: i64, dir: V3) -> usize {
        self.nodes.push(Node {
            pos,
            dir,
            par,
            order,
            t,
        });
        self.nodes.len() - 1
    }
}

/// Une pousse à faire : (nœud de départ, direction, longueur, ordre, charpentière maîtresse).
#[derive(Copy, Clone, Debug)]
struct Job {
    start: usize,
    dir: V3,
    len: i64,
    order: usize,
    leader: bool,
}

/// Architecture de l'axe : place les premières pousses (le tronc ou les tiges).
pub trait Architecture: Send + Sync {
    /// Côté des cellules d'encombrement (Q16 de voxel).
    fn cell(&self) -> i64;
    /// Ajoute les pousses de départ et la racine.
    fn seed_jobs(&self, g: &mut Grower<'_>);
}

/// Arbre à tronc : une flèche, légèrement inclinée.
#[derive(Debug, Default, Copy, Clone)]
pub struct TreeArchitecture;

/// Arbuste : une touffe de tiges qui partent du sol.
#[derive(Debug, Default, Copy, Clone)]
pub struct MultiStemArchitecture;

impl Architecture for TreeArchitecture {
    fn cell(&self) -> i64 {
        10 * UN // 0,5 m
    }

    fn seed_jobs(&self, g: &mut Grower<'_>) {
        let sp = g.sp;
        let root = g.sk.add(V3::ZERO, -1, 0, 0, V3::HAUT);
        let tilt = g.rng.uniform(0, 3 * UN / 360);
        let az = g.rng.unit();
        let d0 = V3::new(
            fx::mul(fx::sin(tilt), fx::cos(az)),
            fx::mul(fx::sin(tilt), fx::sin(az)),
            fx::cos(tilt),
        );
        let len = if sp.arch == ArchKind::Excurrent {
            g.h
        } else {
            fx::mul(g.h, g.rng.uniform(sp.trunk_frac.0, sp.trunk_frac.1))
        };
        g.queue[0].push(Job {
            start: root,
            dir: d0,
            len,
            order: 0,
            leader: false,
        });
    }
}

impl Architecture for MultiStemArchitecture {
    fn cell(&self) -> i64 {
        4 * UN // 0,2 m
    }

    fn seed_jobs(&self, g: &mut Grower<'_>) {
        let sp = g.sp;
        let root = g.sk.add(V3::ZERO, -1, 0, 0, V3::HAUT);
        let n = g.rng.integers(sp.multistem.0, sp.multistem.1).max(1);
        let az0 = g.rng.unit();
        for k in 0..n {
            let az = az0 + UN * k / n + fx::mul(g.rng.normal(), TIERS_RADIAN);
            let lean = g.rng.uniform(sp.stem_lean.0, sp.stem_lean.1);
            let d0 = V3::new(
                fx::mul(fx::sin(lean), fx::cos(az)),
                fx::mul(fx::sin(lean), fx::sin(az)),
                fx::cos(lean),
            );
            let len = fx::mul(g.h, g.rng.uniform(sp.stem_len.0, sp.stem_len.1));
            let mut start = root;
            if n > 1 {
                // les tiges naissent sur un petit cercle autour du pied
                let rho = fx::mul(g.h, g.rng.uniform(UN * 2 / 100, UN * 7 / 100));
                let pos = V3::new(fx::mul(rho, fx::cos(az)), fx::mul(rho, fx::sin(az)), 0);
                start = g.sk.add(pos, root as i32, 0, 0, V3::HAUT);
            }
            g.queue[0].push(Job {
                start,
                dir: d0,
                len,
                order: 0,
                leader: false,
            });
        }
    }
}

/// Longueur relative des charpentières selon la hauteur relative `h` (Q16) dans la couronne.
pub fn crown_profile(shape: CrownShape, h: i64) -> i64 {
    let h = h.clamp(0, UN);
    let pi_sin = |x: i64| fx::sin(x / 2); // sin(π x) = sin_turns(x / 2)
    match shape {
        CrownShape::Conique => 7_864 + fx::mul(57_671, fx::pow(UN - h, 62_259)),
        CrownShape::Colonne => 29_491 + fx::mul(36_045, pi_sin(9_830 + fx::mul(45_875, h))),
        CrownShape::Ovale => 11_796 + fx::mul(53_740, pi_sin(3_277 + fx::mul(58_982, h))),
        CrownShape::Dome => {
            let x = fx::pow(6_554 + fx::mul(52_429, h), 55_706);
            19_661 + fx::mul(45_875, pi_sin(x))
        }
    }
}

/// Plan des directions : base orthonormée perpendiculaire à `d`.
fn perp_basis(d: V3) -> (V3, V3) {
    let a = if d.x.abs() < UN * 9 / 10 {
        V3::new(UN, 0, 0)
    } else {
        V3::new(0, UN, 0)
    };
    let u = d.cross(a).unit();
    let v = d.cross(u);
    (u, v)
}

/// Ramène `d.z` à au moins `min_dz` en conservant la direction horizontale.
fn clamp_dz(d: V3, min_dz: i64) -> V3 {
    if d.z >= min_dz {
        return d;
    }
    let hz = V3::new(d.x, d.y, 0).norm();
    if hz < 1 {
        return V3::HAUT;
    }
    let s = fx::div(fx::sqrt((UN - fx::mul(min_dz, min_dz)).max(0)), hz);
    V3::new(fx::mul(d.x, s), fx::mul(d.y, s), min_dz)
}

/// Fait pousser le squelette ordre par ordre (parcours en largeur : arbitrage équitable de l'espace).
pub struct Grower<'a> {
    sp: &'a Species,
    /// Hauteur visée (Q16 de voxel).
    h: i64,
    rng: Stream,
    sk: Skeleton,
    occ: BTreeMap<u64, u16>,
    z_bole: i64,
    crown_r: i64,
    queue: [Vec<Job>; 6],
    leaf_scale: i64,
    cell: i64,
}

impl<'a> Grower<'a> {
    /// Prépare la croissance d'un sujet de hauteur `h` (Q16 de voxel).
    pub fn new(sp: &'a Species, h: i64, rng: Stream, arch: &dyn Architecture) -> Self {
        let mut rng = rng;
        let z_bole = fx::mul(h, rng.uniform(sp.bole.0, sp.bole.1));
        let crown_r = fx::mul(fx::mul(h, sp.crown_r), rng.uniform(UN * 85 / 100, UN * 115 / 100));
        let leaf_scale = if sp.multistem.1 == 0 {
            // min(1, max(0.6, sqrt(H / 12))) avec H en mètres
            fx::sqrt(h / (12 * VOX_PAR_M)).clamp(UN * 6 / 10, UN)
        } else {
            UN
        };
        Self {
            sp,
            h,
            rng,
            sk: Skeleton::default(),
            occ: BTreeMap::new(),
            z_bole,
            crown_r,
            queue: Default::default(),
            leaf_scale,
            cell: arch.cell(),
        }
    }

    fn key(&self, p: V3) -> u64 {
        let c = self.cell;
        let (x, y, z) = (p.x.div_euclid(c), p.y.div_euclid(c), p.z.div_euclid(c));
        ((x as u64) & 0x1F_FFFF) | (((y as u64) & 0x1F_FFFF) << 21) | (((z as u64) & 0x1F_FFFF) << 42)
    }

    fn touch(&mut self, p: V3) {
        let k = self.key(p);
        *self.occ.entry(k).or_insert(0) += 1;
    }

    fn child_dir(&self, d: V3, theta: i64, phi: i64, up_bias: i64, min_dz: i64) -> V3 {
        let (u, v) = perp_basis(d);
        let (st, ct) = (fx::sin(theta), fx::cos(theta));
        let lat = u.scale(fx::cos(phi)).add(v.scale(fx::sin(phi))).scale(st);
        let c = d.scale(ct).add(lat).add(V3::new(0, 0, up_bias));
        clamp_dz(c.unit(), min_dz)
    }

    /// Pousse une branche ; renvoie les nœuds (le départ d'abord) et le pas (Q16 de voxel).
    fn grow(&mut self, job: Job) -> (Vec<usize>, i64) {
        let sp = self.sp;
        let o = job.order;
        let n = ((job.len + sp.step[o] / 2) / sp.step[o].max(1)).max(2);
        let ds = job.len / n;
        let ds_m = ds / VOX_PAR_M;
        let mut d = job.dir;
        let mut pos = self.sk.nodes[job.start].pos;
        let reduc = if job.leader { UN * 55 / 100 } else { UN };
        let wob = fx::mul(fx::mul(sp.wobble[o], reduc), fx::sqrt(ds_m));
        let trop = sp.tropism[o] + if job.leader { UN * 18 / 100 } else { 0 };
        let mut ids = vec![job.start];
        for k in 0..n {
            let t = (k + 1) * UN / n;
            d = V3::new(
                d.x + fx::mul(self.rng.normal(), wob),
                d.y + fx::mul(self.rng.normal(), wob),
                d.z + fx::mul(self.rng.normal(), wob),
            );
            let facteur = if o == 0 {
                UN
            } else {
                UN * 35 / 100 + fx::mul(UN * 65 / 100, t)
            };
            d.z += fx::mul(fx::mul(trop, ds_m), facteur);
            d = d.unit();
            if o >= 1 || sp.multistem.1 > 0 {
                d = clamp_dz(d, sp.min_dz);
            }
            pos = pos.add(d.scale(ds));
            let nid = self
                .sk
                .add(pos, *ids.last().unwrap_or(&job.start) as i32, o as u8, t, d);
            self.touch(pos);
            ids.push(nid);
        }
        (ids, ds)
    }

    fn pick_leaves(&mut self, ids: &[usize], order: usize, ds: i64) {
        let sp = self.sp;
        if order < sp.leaf_min_order || sp.leaf_r[order] <= 0 {
            return;
        }
        let r0 = fx::mul(sp.leaf_r[order], self.leaf_scale);
        let spacing = fx::mul(r0, sp.leaf_spacing).max(UN * 2); // au moins 10 cm
        let mut dist = self.rng.uniform(0, spacing);
        let last = ids.len() - 1;
        for (j, &nid) in ids.iter().enumerate().skip(1) {
            dist += ds;
            let t = self.sk.nodes[nid].t;
            if t > sp.leaf_end {
                self.sk.bloom.push(nid);
                continue;
            }
            if t >= sp.leaf_start && (dist >= spacing || j == last) {
                let mut r = fx::mul(r0, self.rng.uniform(UN * 8 / 10, UN * 125 / 100));
                if j == last {
                    r = fx::mul(r, UN * 12 / 10);
                }
                self.sk.leafy.push((nid, r));
                dist = 0;
            }
        }
    }

    fn spawn(&mut self, ids: &[usize], len: i64, order: usize, ds: i64) {
        let sp = self.sp;
        let nxt = order + 1;
        if order >= sp.max_order || sp.density[order] <= 0 {
            return;
        }
        let dens = sp.density[order];
        let ds_m = ds / VOX_PAR_M;
        let mut acc = self.rng.unit();
        let mut phi = self.rng.unit();
        let theta0 = sp.angle[nxt];
        let h = self.h;
        for &nid in ids.iter().skip(1) {
            let node = self.sk.nodes[nid];
            let (p, tj) = (node.pos, node.t);
            if order == 0 {
                if p.z < self.z_bole {
                    continue;
                }
                if sp.arch == ArchKind::Excurrent && tj > UN * 97 / 100 {
                    continue;
                }
            } else if tj < UN / 10 {
                continue;
            }
            acc += fx::mul(dens, ds_m);
            while acc >= UN {
                acc -= UN;
                phi += ANGLE_OR + fx::mul(self.rng.normal(), QUART_RADIAN);
                for w in 0..i64::from(sp.whorl) {
                    let ph = phi + UN * w / i64::from(sp.whorl);
                    let th = fx::mul(theta0, UN + self.rng.uniform(-sp.angle_var, sp.angle_var));
                    let cd = self.child_dir(node.dir, th, ph, sp.up_bias[nxt], sp.min_dz);
                    let lc = if order == 0 {
                        let hh = fx::div(p.z - self.z_bole, (h - self.z_bole).max(10 * UN));
                        fx::mul(
                            fx::mul(self.crown_r, crown_profile(sp.crown_shape, hh)),
                            self.rng.uniform(UN * 75 / 100, UN * 112 / 100),
                        )
                    } else {
                        let r = fx::mul(len, sp.len_ratio[nxt]);
                        fx::mul(
                            fx::mul(r, UN - fx::mul(UN * 55 / 100, tj)),
                            self.rng.uniform(UN * 75 / 100, UN * 12 / 10),
                        )
                    };
                    if lc >= sp.min_len[nxt] {
                        self.queue[nxt].push(Job {
                            start: nid,
                            dir: cd,
                            len: lc,
                            order: nxt,
                            leader: false,
                        });
                    }
                }
            }
        }
        // fourche du fût en charpentières maîtresses (feuillus)
        if order == 0 && sp.arch == ArchKind::Decurrent {
            let end = *ids.last().unwrap_or(&0);
            let n = self.rng.integers(sp.leaders.0, sp.leaders.1).max(1);
            let az0 = self.rng.unit();
            let z_end = self.sk.nodes[end].pos.z;
            let dir_end = self.sk.nodes[end].dir;
            for k in 0..n {
                let az = az0 + UN * k / n + fx::mul(self.rng.normal(), TIERS_RADIAN);
                let ang = self.rng.uniform(sp.leader_angle.0, sp.leader_angle.1);
                let cd = self.child_dir(dir_end, ang, az, UN / 5, -UN / 10);
                let cosang = fx::cos(ang).max(UN * 55 / 100);
                let reste = (h - z_end).max(VOX_PAR_M * UN);
                let lc = fx::mul(
                    fx::div(reste, cosang),
                    self.rng.uniform(UN * 9 / 10, UN * 11 / 10),
                );
                self.queue[1].push(Job {
                    start: end,
                    dir: cd,
                    len: lc,
                    order: 1,
                    leader: true,
                });
            }
        }
    }

    /// Fait pousser tout le squelette.
    pub fn run(mut self, arch: &dyn Architecture) -> Skeleton {
        arch.seed_jobs(&mut self);
        for order in 0..=self.sp.max_order {
            let jobs = std::mem::take(&mut self.queue[order]);
            let perm = self.rng.permutation(jobs.len());
            for ji in perm {
                let job = jobs[ji];
                if job.order >= 2 {
                    let sonde = self.sk.nodes[job.start]
                        .pos
                        .add(job.dir.scale(fx::mul(job.len.min(18 * UN), UN * 7 / 10)));
                    let touches = self.occ.get(&self.key(sonde)).copied().unwrap_or(0);
                    if u32::from(touches) >= self.sp.crowd[job.order] {
                        continue;
                    }
                }
                let (ids, ds) = self.grow(job);
                self.pick_leaves(&ids, job.order, ds);
                self.spawn(&ids, job.len, job.order, ds);
            }
        }
        self.sk
    }
}

/// Fait pousser le squelette d'une essence : l'architecture vient de l'essence (arbuste ou arbre).
pub fn grow_skeleton(sp: &Species, h: i64, seed: u64) -> Skeleton {
    let arch: &dyn Architecture = if sp.is_bush() {
        &MultiStemArchitecture
    } else {
        &TreeArchitecture
    };
    let rng = Stream::new(seed, 0x4752_4F57); // « GROW »
    Grower::new(sp, h, rng, arch).run(arch)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::vegetation::species::SpeciesTable;

    #[test]
    fn le_chene_pousse_environ_dix_mille_noeuds_et_atteint_sa_hauteur() {
        let t = SpeciesTable::embedded();
        let sp = t.get("chene").unwrap();
        let h = 15 * VOX_PAR_M * UN;
        let sk = grow_skeleton(sp, h, 7);
        assert!(
            (4_000..25_000).contains(&sk.nodes.len()),
            "{} nœuds",
            sk.nodes.len()
        );
        let top = sk.nodes.iter().map(|n| n.pos.z).max().unwrap();
        assert!(top > h / 2 && top < h * 2, "sommet {top}");
        assert!(!sk.leafy.is_empty());
    }

    #[test]
    fn meme_graine_meme_squelette() {
        let t = SpeciesTable::embedded();
        let sp = t.get("bouleau").unwrap();
        let a = grow_skeleton(sp, 240 * UN, 3);
        let b = grow_skeleton(sp, 240 * UN, 3);
        assert_eq!(a.nodes, b.nodes);
        assert_ne!(a.nodes.len(), grow_skeleton(sp, 240 * UN, 4).nodes.len());
    }

    #[test]
    fn un_arbuste_a_plusieurs_tiges_depuis_le_sol() {
        let t = SpeciesTable::embedded();
        let sp = t.get("rosier").unwrap();
        let sk = grow_skeleton(sp, 24 * UN, 1);
        let tiges = sk.nodes.iter().filter(|n| n.par == 0).count();
        assert!(tiges >= 4, "{tiges} tiges");
    }
}
