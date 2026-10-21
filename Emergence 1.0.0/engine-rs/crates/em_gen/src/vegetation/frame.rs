//! Du squelette à la forme : mise à l'échelle à la hauteur demandée, rayons par le modèle des tuyaux
//! (Léonard de Vinci, exposant 2,4), empattement du fût, chicots et racines de surface.
//! Port de `finalize_skeleton` de `voxel_tree.py`.

use em_core::q16::{Q16, qexp2, qlog2};

use super::fx::{self, Stream, UN, V3, VOX_PAR_M};
use super::skeleton::Skeleton;
use super::species::Species;

/// Un segment de bois : capsule effilée de `a` vers `b`.
#[derive(Copy, Clone, Debug, PartialEq, Eq)]
pub struct Segment {
    /// Départ.
    pub a: V3,
    /// Arrivée.
    pub b: V3,
    /// Rayon au départ (Q16 de voxel).
    pub r0: i64,
    /// Rayon à l'arrivée.
    pub r1: i64,
    /// Segment du fût (relief de l'écorce).
    pub trunk: bool,
}

/// Un amas de feuilles posé sur un rameau terminal.
#[derive(Copy, Clone, Debug, PartialEq, Eq)]
pub struct LeafSpec {
    /// Centre.
    pub pos: V3,
    /// Direction du rameau.
    pub dir: V3,
    /// Rayon (Q16 de voxel).
    pub r: i64,
}

/// Un point d'ancrage de fleur ou de fruit (bouquet de feuilles ou nœud nu).
#[derive(Copy, Clone, Debug, PartialEq, Eq)]
pub struct Anchor {
    /// Position.
    pub pos: V3,
    /// Direction du rameau.
    pub dir: V3,
    /// Position le long de la branche (Q16).
    pub t: i64,
}

/// La forme complète d'un sujet, en Q16 de voxel.
#[derive(Clone, Debug)]
pub struct Frame {
    /// Les capsules de bois.
    pub segments: Vec<Segment>,
    /// Les amas de feuilles.
    pub leaves: Vec<LeafSpec>,
    /// Les ancrages de fleurs et de fruits.
    pub anchors: Vec<Anchor>,
    /// Rayon à la base du fût (Q16 de voxel).
    pub base_radius: i64,
    /// Nombre de nœuds du squelette.
    pub node_count: usize,
}

/// `N^2,4` en Q16 pour `N` entier (le rayon en huitièmes d'unité brute) : somme exacte en `i128`.
fn pow24(n: i64) -> i128 {
    if n <= 0 {
        return 0;
    }
    let log2n = qlog2(Q16(n)).raw() + 16 * UN;
    i128::from(qexp2(fx::mul(157_286, log2n)))
}

/// Inverse de `pow24` : rayon brut (Q16 de voxel) dont la puissance 2,4 vaut `somme`.
fn racine24(somme: i128) -> i64 {
    if somme <= 0 {
        return 0;
    }
    let bits = 128 - somme.leading_zeros() as i64;
    let s = (bits - 60).max(0);
    let a = (somme >> s) as i64;
    // pow24 renvoie N^2,4 × 65536 : log2(somme / 65536) = la, donc log2 N = la / 2,4
    let la = qlog2(Q16(a)).raw() + s * UN;
    let ln = fx::div(la, 157_286);
    qexp2(ln) >> 13 // N × 8 : le rayon brut
}

/// Construit la forme d'un sujet à partir de son squelette et de la hauteur demandée `h` (Q16 de voxel).
pub fn build_frame(sk: &Skeleton, sp: &Species, h: i64, seed: u64) -> Frame {
    let mut rng = Stream::new(seed, 0x4558_5452); // « EXTR »
    let n = sk.nodes.len();
    let multi = sp.multistem.1 > 0;

    // mise à l'échelle uniforme pour atteindre exactement la hauteur demandée (feuillage compris)
    let mut top = sk.nodes.iter().map(|x| x.pos.z).max().unwrap_or(1);
    for &(i, r) in &sk.leafy {
        let haut = sk.nodes[i].pos.z + fx::mul(fx::mul(UN * 85 / 100, r), sp.leaf_flat);
        top = top.max(haut);
    }
    let s = fx::div(h, top.max(1));
    let pos: Vec<V3> = sk.nodes.iter().map(|x| x.pos.scale(s)).collect();
    let par: Vec<i32> = sk.nodes.iter().map(|x| x.par).collect();

    // rayons : modèle des tuyaux + effilement (longueurs de segment en mètres pour l'effilement)
    let r_tip = if multi { 262 } else { 458 } * VOX_PAR_M; // 0,004 m ou 0,007 m en Q16 de voxel (par mètre × 20)
    let seglen_m: Vec<i64> = (0..n)
        .map(|i| {
            if par[i] < 0 {
                0
            } else {
                pos[i].sub(pos[par[i] as usize]).norm() / VOX_PAR_M
            }
        })
        .collect();
    let mut has_child = vec![false; n];
    for &p in par.iter().skip(1) {
        has_child[p as usize] = true;
    }
    let mut acc = vec![0_i128; n];
    let mut r = vec![0_i64; n];
    for i in (0..n).rev() {
        let ri = if has_child[i] { racine24(acc[i]) } else { r_tip };
        r[i] = ri;
        if par[i] >= 0 {
            let eff = fx::mul(ri, UN + fx::mul(sp.taper, seglen_m[i]));
            acc[par[i] as usize] += pow24(eff >> 3);
        }
    }
    let h_m = h / VOX_PAR_M;
    let r_target = fx::mul(
        fx::mul(sp.trunk_k, h_m),
        rng.uniform(UN * 88 / 100, UN * 114 / 100),
    ) * VOX_PAR_M;
    if multi {
        // arbuste : on étalonne la plus grosse tige, pas la somme des tiges
        let mut reference = 1;
        for i in 1..n {
            if par[i] == 0 && sk.nodes[i].order == 0 {
                reference = reference.max(fx::mul(r[i], UN + fx::mul(sp.taper, seglen_m[i])));
            }
        }
        for x in &mut r {
            *x = fx::mul(*x, fx::div(r_target, reference));
        }
    } else {
        let k = fx::div(r_target, r[0].max(1));
        for x in &mut r {
            *x = fx::mul(*x, k);
        }
    }

    let flare = |z: i64, trunk: bool| -> i64 {
        if trunk && !multi {
            // 1 + 0,60 e^(-z / 0,65 m)
            UN + fx::mul(UN * 6 / 10, fx::exp_neg(fx::div(z / VOX_PAR_M, 42_598)))
        } else {
            UN
        }
    };
    let mut segments = Vec::with_capacity(n + 64);
    for i in 1..n {
        let p = par[i] as usize;
        let trunk = sk.nodes[i].order == 0;
        let r1 = fx::mul(r[i], flare(pos[i].z, trunk));
        let r0 = fx::mul(
            r[p].min(fx::mul(r[i], UN + fx::mul(sp.taper, seglen_m[i]))),
            flare(pos[p].z, trunk),
        );
        segments.push(Segment {
            a: pos[p],
            b: pos[i],
            r0,
            r1,
            trunk,
        });
    }

    // chicots sur le fût (feuillus âgés)
    let tronc: Vec<usize> = (0..n).filter(|&i| sk.nodes[i].order == 0).collect();
    if sp.stubs > 0 && tronc.len() > 2 {
        let zt = tronc.iter().map(|&i| pos[i].z).max().unwrap_or(0);
        let z_bole = fx::mul(zt, UN * 6 / 10);
        let cnt = fx::mul(
            fx::mul(z_bole / VOX_PAR_M, rng.uniform(UN * 8 / 10, UN * 16 / 10)),
            sp.stubs,
        ) >> 16;
        for _ in 0..cnt {
            let j = rng.integers(1, tronc.len() as i64 - 1) as usize;
            let nid = tronc[j];
            if pos[nid].z > z_bole || pos[nid].z < 10 * UN {
                continue;
            }
            let a = rng.unit();
            let (ca, sa) = (fx::cos(a), fx::sin(a));
            let sortie = V3::new(ca, sa, UN * 3 / 10).unit();
            let rr = r[nid];
            let a0 = pos[nid].add(V3::new(
                fx::mul(ca, fx::mul(rr, UN * 9 / 10)),
                fx::mul(sa, fx::mul(rr, UN * 9 / 10)),
                0,
            ));
            let ln = rng.uniform(UN * 12 / 100, UN * 38 / 100) * VOX_PAR_M;
            let rs = rng.uniform(UN * 22 / 1000, UN * 42 / 1000) * VOX_PAR_M;
            segments.push(Segment {
                a: a0,
                b: a0.add(sortie.scale(ln)),
                r0: fx::mul(rs, UN * 135 / 100),
                r1: fx::mul(rs, UN * 8 / 10),
                trunk: false,
            });
        }
    }

    // racines de surface et contreforts
    let r_base = r[0];
    let nroots = if sp.roots { rng.integers(5, 7) } else { 0 };
    let az0 = rng.unit();
    const PROFIL: [i64; 6] = [62, 50, 38, 27, 17, 9];
    for k in 0..nroots {
        let a = az0 + UN * k / nroots.max(1) + fx::mul(rng.normal(), QUART_RADIAN_ROOT);
        let mut d = V3::new(fx::cos(a), fx::sin(a), -UN / 10);
        let mut p = V3::new(0, 0, fx::mul(UN * 45 / 100, r_base));
        let seg = fx::mul(
            18 * UN + fx::mul(UN * 32 / 10, r_base),
            rng.uniform(UN * 7 / 10, UN * 13 / 10),
        ) / 5;
        for q in 0..5 {
            d = V3::new(
                d.x + fx::mul(rng.normal(), UN * 12 / 100),
                d.y + fx::mul(rng.normal(), UN * 12 / 100),
                d.z + fx::mul(rng.normal(), UN * 3 / 100),
            );
            d.z = d.z.min(-UN * 2 / 100);
            d = d.unit();
            let pn = p.add(d.scale(seg));
            segments.push(Segment {
                a: p,
                b: pn,
                r0: r_base * PROFIL[q] / 100,
                r1: r_base * PROFIL[q + 1] / 100,
                trunk: false,
            });
            p = pn;
        }
    }

    let leaves: Vec<LeafSpec> = sk
        .leafy
        .iter()
        .map(|&(i, rr)| LeafSpec {
            pos: pos[i],
            dir: sk.nodes[i].dir,
            r: rr,
        })
        .collect();
    let mut anchors: Vec<Anchor> = sk
        .leafy
        .iter()
        .map(|&(i, _)| Anchor {
            pos: pos[i],
            dir: sk.nodes[i].dir,
            t: sk.nodes[i].t,
        })
        .collect();
    anchors.extend(sk.bloom.iter().map(|&i| Anchor {
        pos: pos[i],
        dir: sk.nodes[i].dir,
        t: sk.nodes[i].t,
    }));
    Frame {
        segments,
        leaves,
        anchors,
        base_radius: r_base,
        node_count: n,
    }
}

/// Écart type (en tours) de la variation d'azimut des racines : 0,25 radian.
const QUART_RADIAN_ROOT: i64 = 2_608;

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn la_puissance_et_la_racine_2_4_sont_inverses() {
        for r in [5_300_i64, 9_000, 40_000, 200_000] {
            let somme = pow24(r >> 3);
            let back = racine24(somme);
            assert!((back - r).abs() * 100 < r, "r={r} back={back}");
        }
    }

    #[test]
    fn deux_branches_egales_donnent_un_tronc_plus_gros_de_2_puissance_un_sur_2_4() {
        let r = 40_000_i64;
        let somme = pow24(r >> 3) * 2;
        let back = racine24(somme);
        // 2^(1/2.4) = 1.3348
        let rapport = back * 1000 / r;
        assert!((1320..1350).contains(&rapport), "{rapport}");
    }
}
