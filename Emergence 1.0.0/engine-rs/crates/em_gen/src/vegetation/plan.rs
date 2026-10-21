//! Le plan d'un sujet (arbre ou arbuste) : squelette, bois, amas de feuilles, fleurs et fruits, rangés dans un
//! index de seaux. `rasterize` écrit n'importe quelle fenêtre de n'importe quel niveau à la demande, sans état :
//! le résultat d'un voxel ne dépend que de ses coordonnées monde (donc ni de la fenêtre, ni du fil).
//!
//! Repère : le plan est calculé dans les axes du Python (x est, y nord, z haut, unité = voxel de 5 cm en Q16) ;
//! `rasterize` le permute vers le repère monde (x est, y haut, z nord) en écrivant.

use em_core::{Lod, VoxelBox, VoxelCoord, hash_combine};
use em_voxel::{PutMode, VoxelSink};

use super::bark::SegmentNiveau;
use super::blob::{Blob, DensityGrid, LISIERE_FEUILLES, LISIERE_ORGANES};
use super::frame::{Frame, Segment, build_frame};
use super::fx::{self, Stream, UN, V3, VOX_PAR_M};
use super::skeleton::grow_skeleton;
use super::species::{AltRule, Season, Species};
use super::topiary::{Topiary, TopiaryShape};
use crate::generator::GenPlan;
use crate::vxm::{TintTable, VxmClasses, VxmKind};

/// Le seau de l'index mesure 16 voxels de côté (64 pour les silhouettes, qui n'ont que quelques pièces).
const SEAU: u32 = 4;
/// Niveaux de détail servis (comme les modèles `.vxm`).
pub const LOD_MAX: Lod = 5;

/// Demande de plan : tout ce qui, avec la graine, détermine un sujet.
#[derive(Clone, Debug)]
pub struct PlantRequest<'a> {
    /// Essence.
    pub species: &'a Species,
    /// Graine du sujet.
    pub seed: u64,
    /// Hauteur (Q16 de voxel), déjà bornée.
    pub height: i64,
    /// Saison.
    pub season: Season,
    /// Multiplicateur de densité du feuillage (Q16).
    pub leaf_density: i64,
    /// Taille topiaire éventuelle.
    pub topiary: Option<TopiaryShape>,
}

/// Mesures du plan (pour les essais de parité et les bancs).
#[derive(Copy, Clone, Debug, PartialEq, Eq)]
pub struct PlanStats {
    /// Nœuds du squelette.
    pub nodes: usize,
    /// Bouquets de feuilles.
    pub leafy: usize,
    /// Capsules de bois (dont chicots et racines).
    pub segments: usize,
    /// Rayon à la base du fût (Q16 de voxel).
    pub base_radius: i64,
}

/// Index spatial par seaux de 16 voxels (niveau 0).
#[derive(Clone, Debug)]
struct Index {
    shift: u32,
    origin: [i32; 3],
    dim: [usize; 3],
    seaux: Vec<Vec<u32>>,
}

impl Index {
    fn new(min: [i32; 3], max: [i32; 3], shift: u32) -> Self {
        let origin = [min[0] >> shift, min[1] >> shift, min[2] >> shift];
        let dim = [
            ((max[0] >> shift) - origin[0] + 1) as usize,
            ((max[1] >> shift) - origin[1] + 1) as usize,
            ((max[2] >> shift) - origin[2] + 1) as usize,
        ];
        Self {
            shift,
            origin,
            dim,
            seaux: vec![Vec::new(); dim[0] * dim[1] * dim[2]],
        }
    }

    fn plage(&self, lo: [i32; 3], hi: [i32; 3]) -> Option<([usize; 3], [usize; 3])> {
        let mut a = [0_usize; 3];
        let mut b = [0_usize; 3];
        for i in 0..3 {
            let l = (lo[i] >> self.shift) - self.origin[i];
            let h = (hi[i] >> self.shift) - self.origin[i];
            if h < 0 || l >= self.dim[i] as i32 {
                return None;
            }
            a[i] = l.max(0) as usize;
            b[i] = h.min(self.dim[i] as i32 - 1) as usize;
        }
        Some((a, b))
    }

    fn insert(&mut self, id: u32, lo: [i32; 3], hi: [i32; 3]) {
        let Some((a, b)) = self.plage(lo, hi) else { return };
        for z in a[2]..=b[2] {
            for y in a[1]..=b[1] {
                for x in a[0]..=b[0] {
                    let i = (z * self.dim[1] + y) * self.dim[0] + x;
                    self.seaux[i].push(id);
                }
            }
        }
    }

    /// Identifiants dont la boîte touche `[lo, hi]` (niveau 0, inclus), triés et sans doublon.
    fn query(&self, lo: [i32; 3], hi: [i32; 3]) -> Vec<u32> {
        let mut out = Vec::new();
        if let Some((a, b)) = self.plage(lo, hi) {
            for z in a[2]..=b[2] {
                for y in a[1]..=b[1] {
                    for x in a[0]..=b[0] {
                        out.extend_from_slice(&self.seaux[(z * self.dim[1] + y) * self.dim[0] + x]);
                    }
                }
            }
        }
        out.sort_unstable();
        out.dedup();
        out
    }
}

/// Les pièces d'un plan : tout ce que `assemble` range dans l'index.
pub struct Parts {
    /// Graine.
    pub seed: u64,
    /// Hauteur (Q16 de voxel).
    pub height: i64,
    /// Capsules de bois.
    pub segments: Vec<Segment>,
    /// Amas de feuilles.
    pub leaves: Vec<Blob>,
    /// Amas de fleurs.
    pub flowers: Vec<Blob>,
    /// Amas de fruits.
    pub fruits: Vec<Blob>,
    /// Part des points qui débordent d'un voxel.
    pub leaf_big: i64,
    /// Règle de l'écorce secondaire.
    pub alt_rule: AltRule,
    /// Taille topiaire (forme, boîte du feuillage).
    pub topiary: Option<(TopiaryShape, [i64; 3], [i64; 3])>,
    /// Case d'essence.
    pub slot: u8,
    /// Index à gros seaux (silhouettes : très peu de pièces).
    pub grossier: bool,
    /// Mesures.
    pub stats: PlanStats,
}

/// Le plan d'un sujet.
pub struct PlantPlan {
    seed: u64,
    height: i64,
    segments: Vec<Segment>,
    leaves: Vec<Blob>,
    flowers: Vec<Blob>,
    fruits: Vec<Blob>,
    leaf_big: i64,
    alt_rule: AltRule,
    topiary: Option<(TopiaryShape, [i64; 3], [i64; 3])>,
    tint: TintTable,
    idx_seg: Index,
    idx_leaf: Index,
    idx_flower: Index,
    idx_fruit: Index,
    box0: ([i32; 3], [i32; 3]),
    stats: PlanStats,
}

fn etiquette(s: &str) -> u64 {
    s.bytes().fold(0xcbf2_9ce4_8422_2325_u64, |h, b| {
        (h ^ u64::from(b)).wrapping_mul(0x0100_0000_01b3)
    })
}

impl PlantPlan {
    /// Construit le plan : croissance, rayons, amas, index.
    pub fn build(req: &PlantRequest<'_>, classes: &VxmClasses) -> Result<Self, crate::error::GenError> {
        let sp = req.species;
        let sk = grow_skeleton(sp, req.height, hash_combine(req.seed, etiquette("squelette")));
        let frame = build_frame(&sk, sp, req.height, hash_combine(req.seed, etiquette("forme")));
        let mult = fx::mul(req.leaf_density, sp.season_leaf_factor(req.season));
        let (leaves, leaf_box) = leaf_blobs(&frame, sp, mult, hash_combine(req.seed, etiquette("feuilles")));

        let mut flo = Stream::new(req.seed, etiquette("fleurs"));
        let topiary = if mult > 0 && !leaves.is_empty() {
            req.topiary.map(|s| (s, leaf_box.0, leaf_box.1))
        } else {
            None
        };
        let (mut flowers, mut fruits) = (Vec::new(), Vec::new());
        if req.topiary.is_none() {
            if sp.flower.active(req.season) {
                flowers = feature_blobs(&frame, &sp.flower, &mut flo);
            }
            if sp.fruit.active(req.season) {
                fruits = feature_blobs(&frame, &sp.fruit, &mut flo);
            }
        }

        let stats = PlanStats {
            nodes: frame.node_count,
            leafy: frame.leaves.len(),
            segments: frame.segments.len(),
            base_radius: frame.base_radius,
        };
        Self::assemble(
            Parts {
                seed: req.seed,
                height: req.height,
                segments: frame.segments,
                leaves,
                flowers,
                fruits,
                leaf_big: sp.leaf_big,
                alt_rule: sp.alt_rule,
                topiary,
                slot: sp.slot,
                grossier: false,
                stats,
            },
            classes,
        )
    }

    /// Assemble un plan à partir de ses pièces (bois, amas) : boîte du niveau 0 et index de seaux.
    pub fn assemble(p: Parts, classes: &VxmClasses) -> Result<Self, crate::error::GenError> {
        let Parts {
            seed,
            height,
            segments,
            leaves,
            flowers,
            fruits,
            leaf_big,
            alt_rule,
            topiary,
            slot,
            grossier,
            stats,
        } = p;
        let frame = Frame {
            segments,
            leaves: Vec::new(),
            anchors: Vec::new(),
            base_radius: stats.base_radius,
            node_count: stats.nodes,
        };
        // boîte du niveau 0 (axes du Python), puis index
        let mut lo = [i64::MAX; 3];
        let mut hi = [i64::MIN; 3];
        let mut etendre = |a: V3, b: V3| {
            lo = [lo[0].min(a.x), lo[1].min(a.y), lo[2].min(a.z)];
            hi = [hi[0].max(b.x), hi[1].max(b.y), hi[2].max(b.z)];
        };
        let seg_box = |s: &Segment| -> (V3, V3) {
            let m = s.r0.max(s.r1).max(UN * 8 / 10) * 125 / 100 + UN;
            (
                V3::new(s.a.x.min(s.b.x) - m, s.a.y.min(s.b.y) - m, s.a.z.min(s.b.z) - m),
                V3::new(s.a.x.max(s.b.x) + m, s.a.y.max(s.b.y) + m, s.a.z.max(s.b.z) + m),
            )
        };
        let blob_box = |b: &Blob| -> (V3, V3) {
            let h = b.half_extents();
            let m = UN;
            (
                V3::new(b.center.x - h.x - m, b.center.y - h.y - m, b.center.z - h.z - m),
                V3::new(b.center.x + h.x + m, b.center.y + h.y + m, b.center.z + h.z + m),
            )
        };
        for s in &frame.segments {
            let (a, b) = seg_box(s);
            etendre(a, b);
        }
        for b in leaves.iter().chain(&flowers).chain(&fruits) {
            let (a, c) = blob_box(b);
            etendre(a, c);
        }
        let fl = |v: i64| (v >> 16) as i32;
        let box0 = (
            [fl(lo[0]), fl(lo[1]), fl(lo[2]).max(0)],
            [
                fl(hi[0]) + 1,
                fl(hi[1]) + 1,
                (fl(hi[2]) + 1).min((height >> 16) as i32 + 1),
            ],
        );
        let mk = |n: usize| {
            let _ = n;
            Index::new(box0.0, box0.1, if grossier { 6 } else { SEAU })
        };
        let (mut idx_seg, mut idx_leaf, mut idx_flower, mut idx_fruit) = (mk(0), mk(1), mk(2), mk(3));
        for (i, s) in frame.segments.iter().enumerate() {
            let (a, b) = seg_box(s);
            idx_seg.insert(i as u32, [fl(a.x), fl(a.y), fl(a.z)], [fl(b.x), fl(b.y), fl(b.z)]);
        }
        for (set, idx) in [
            (&leaves, &mut idx_leaf),
            (&flowers, &mut idx_flower),
            (&fruits, &mut idx_fruit),
        ] {
            for (i, b) in set.iter().enumerate() {
                let (a, c) = blob_box(b);
                idx.insert(i as u32, [fl(a.x), fl(a.y), fl(a.z)], [fl(c.x), fl(c.y), fl(c.z)]);
            }
        }
        Ok(Self {
            seed,
            height,
            segments: frame.segments,
            leaves,
            flowers,
            fruits,
            leaf_big,
            alt_rule,
            topiary,
            tint: TintTable::new(classes, slot)?,
            idx_seg,
            idx_leaf,
            idx_flower,
            idx_fruit,
            box0,
            stats,
        })
    }

    /// Mesures du plan.
    pub const fn stats(&self) -> PlanStats {
        self.stats
    }

    fn zcap(&self, lod: Lod) -> i32 {
        (self.height >> (16 + u32::from(lod))) as i32
    }

    /// Variante d'écorce d'un voxel (0 écorce, 1 écorce secondaire) selon la règle de l'essence.
    fn bark_variant(&self, x: i32, y: i32, z: i32, lod: Lod) -> u8 {
        let k = u32::from(lod);
        let p = V3::new(
            ((i64::from(x) << 16) + 32_768) << k,
            ((i64::from(y) << 16) + 32_768) << k,
            ((i64::from(z) << 16) + 32_768) << k,
        );
        let s3 = hash_combine(self.seed, etiquette("ecorce"));
        match self.alt_rule {
            AltRule::None => 0,
            AltRule::Moss => {
                let m = fx::noise_at(p, 800, s3);
                let jm = fx::mul(
                    fx::hash_unit(s3 ^ 1, i64::from(x), i64::from(y), i64::from(z)) - UN / 2,
                    UN * 14 / 100,
                );
                let bas = p.z < fx::mul(self.height, UN * 18 / 100);
                u8::from(m + jm > UN * 68 / 100 && bas)
            }
            AltRule::Marks => {
                // bruit étiré : 7 cycles par mètre horizontalement, 35 verticalement
                let kx = fx::lattice_factor(7_000);
                let kz = fx::lattice_factor(35_000);
                let m = fx::value_noise(fx::mul(p.x, kx), fx::mul(p.y, kx), fx::mul(p.z, kz), s3);
                u8::from(m > UN * 66 / 100)
            }
            AltRule::Upper => {
                let m = fx::noise_at(p, 600, s3);
                let seuil = fx::mul(self.height, UN / 2 + fx::mul(m - UN / 2, UN * 15 / 100));
                u8::from(p.z > seuil)
            }
        }
    }

    fn put(&self, sink: &mut dyn VoxelSink, kind: VxmKind, variant: u8, x: i32, y: i32, z: i32) {
        // permutation vers le repère monde : (x est, y nord, z haut) -> (x, haut, nord)
        sink.put(
            VoxelCoord::new(x, z, y),
            self.tint.value(kind, variant),
            PutMode::Solid,
        );
    }

    fn rasterize_blobs(
        &self,
        passe: &PasseAmas<'_>,
        lod: Lod,
        pmin: [i32; 3],
        pmax: [i32; 3],
        sink: &mut dyn VoxelSink,
    ) {
        let (q0, q1) = niveau0(pmin, pmax, lod);
        let ids = passe.idx.query(q0, q1);
        if ids.is_empty() {
            return;
        }
        let lisiere = if passe.big > 0 {
            LISIERE_FEUILLES
        } else {
            LISIERE_ORGANES
        };
        let mut g = DensityGrid::new(pmin, pmax, lisiere);
        for id in ids {
            g.add(
                &passe.set[id as usize],
                lod,
                hash_combine(passe.seed, u64::from(id)),
            );
        }
        g.emit(
            pmin,
            pmax,
            passe.big,
            hash_combine(passe.seed, u64::from(lod)),
            |x, y, z, v| {
                self.put(sink, passe.kind, v, x, y, z);
            },
        );
    }
}

/// Une famille d'amas à rastériser : leurs données, leur index, leur sorte et leur graine.
struct PasseAmas<'a> {
    set: &'a [Blob],
    idx: &'a Index,
    kind: VxmKind,
    /// Part des points qui débordent d'un voxel (feuilles seulement).
    big: i64,
    seed: u64,
}

/// Boîte du niveau 0 couvrant la fenêtre `[pmin, pmax)` du niveau `lod`, avec une marge d'un voxel du niveau.
fn niveau0(pmin: [i32; 3], pmax: [i32; 3], lod: Lod) -> ([i32; 3], [i32; 3]) {
    let k = u32::from(lod);
    (
        [(pmin[0] - 1) << k, (pmin[1] - 1) << k, (pmin[2] - 1) << k],
        [(pmax[0] + 1) << k, (pmax[1] + 1) << k, (pmax[2] + 1) << k],
    )
}

/// Les amas de feuilles : un par bouquet, de densité tirée de la loi du Python
/// (`counts = max(1, vol · leaf_dens · mult · gate)`), avec les trouées à grande échelle.
fn leaf_blobs(frame: &Frame, sp: &Species, mult: i64, seed: u64) -> (Vec<Blob>, ([i64; 3], [i64; 3])) {
    let mut out = Vec::new();
    let mut lo = [i64::MAX; 3];
    let mut hi = [i64::MIN; 3];
    if mult <= 0 {
        return (out, (lo, hi));
    }
    let gate_seed = hash_combine(seed, 9);
    for l in &frame.leaves {
        let g = fx::noise_at(l.pos, 550, gate_seed);
        let gate = if g < UN * 38 / 100 {
            UN * 15 / 100 + fx::mul(UN * 6 / 10, g)
        } else {
            UN
        };
        let mut b = Blob {
            center: V3::new(l.pos.x, l.pos.y, l.pos.z - fx::mul(sp.leaf_droop, l.r)),
            dir: l.dir,
            r: l.r,
            stretch: sp.leaf_stretch.max(UN),
            flat: sp.leaf_flat,
            density: 0,
            variant: 0,
        };
        let vol = b.volume();
        let points = fx::mul(fx::mul(vol, sp.leaf_dens), fx::mul(mult, gate));
        let comptes = (points >> 16).max(1);
        b.density = fx::div(comptes << 16, vol.max(1));
        let h = b.half_extents();
        let (a, c) = (
            [b.center.x - h.x, b.center.y - h.y, b.center.z - h.z],
            [b.center.x + h.x, b.center.y + h.y, b.center.z + h.z],
        );
        for i in 0..3 {
            lo[i] = lo[i].min(a[i]);
            hi[i] = hi[i].max(c[i]);
        }
        out.push(b);
    }
    (out, (lo, hi))
}

/// Fleurs ou fruits : petits amas posés sur une fraction des ancrages (`make_feature_voxels`).
fn feature_blobs(frame: &Frame, f: &super::species::Feature, rng: &mut Stream) -> Vec<Blob> {
    let unique = if f.mix {
        None
    } else {
        Some(rng.integers(0, f.ramps.len() as i64 - 1) as u8)
    };
    let mut out = Vec::new();
    for a in &frame.anchors {
        let tire = rng.chance(f.frac);
        if a.t < f.tip || !tire {
            continue;
        }
        let r = fx::mul(f.r, rng.uniform(UN * 75 / 100, UN * 125 / 100));
        let mut b = Blob {
            center: a.pos.add(a.dir.scale(f.off)),
            dir: a.dir,
            r,
            stretch: f.stretch.max(UN),
            flat: UN,
            density: 0,
            variant: 0,
        };
        let vol = b.volume();
        let comptes = (fx::mul(vol, f.fill) >> 16).max(2);
        b.density = fx::div(comptes << 16, vol.max(1));
        b.variant = unique.unwrap_or_else(|| rng.integers(0, f.ramps.len() as i64 - 1) as u8);
        out.push(b);
    }
    out
}

impl GenPlan for PlantPlan {
    fn bounds(&self, lod: Lod) -> VoxelBox {
        let k = u32::from(lod.min(LOD_MAX));
        let (lo, hi) = self.box0;
        let zc = self.zcap(lod.min(LOD_MAX)).max(1);
        let mn = [lo[0] >> k, lo[1] >> k, (lo[2] >> k).max(0)];
        let mx = [(hi[0] >> k) + 1, (hi[1] >> k) + 1, ((hi[2] >> k) + 1).min(zc)];
        VoxelBox::new(
            VoxelCoord::new(mn[0], mn[2], mn[1]),
            VoxelCoord::new(mx[0].max(mn[0] + 1), mx[2].max(mn[2] + 1), mx[1].max(mn[1] + 1)),
        )
        .unwrap_or_else(|_| {
            VoxelBox::new(VoxelCoord::new(0, 0, 0), VoxelCoord::new(1, 1, 1)).expect("boîte unité")
        })
    }

    fn rasterize(&self, lod: Lod, window: VoxelBox, sink: &mut dyn VoxelSink) {
        let lod = lod.min(LOD_MAX);
        let (wa, wb) = (window.min(), window.max());
        let zcap = self.zcap(lod);
        // fenêtre dans les axes du Python, demi-ouverte [pmin, pmax)
        let pmin = [wa.x, wa.z, wa.y.max(0)];
        let pmax = [wb.x, wb.z, wb.y.min(zcap)];
        if pmin[0] >= pmax[0] || pmin[1] >= pmax[1] || pmin[2] >= pmax[2] {
            return;
        }
        let topiary = self.topiary.map(|(s, lo, hi)| {
            let k = 16 + u32::from(lod);
            let f = |v: i64| (v >> k) as i32;
            Topiary::new(
                s,
                [f(lo[0]), f(lo[1]), f(lo[2]).max(0)],
                [f(hi[0]), f(hi[1]), f(hi[2])],
                lod,
            )
        });
        let tailler = |x: i32, y: i32, z: i32| topiary.as_ref().is_none_or(|t| t.inside(x, y, z));

        // 1. feuilles (ou coque topiaire)
        match &topiary {
            Some(t) => {
                let (tl, th) = t.bounds();
                let seed = hash_combine(self.seed, etiquette("topiaire"));
                for z in pmin[2].max(tl[2])..pmax[2].min(th[2] + 1) {
                    for y in pmin[1].max(tl[1])..pmax[1].min(th[1] + 1) {
                        for x in pmin[0].max(tl[0])..pmax[0].min(th[0] + 1) {
                            if t.in_shell(x, y, z, seed) {
                                self.put(sink, VxmKind::Leaf, 0, x, y, z);
                            }
                        }
                    }
                }
            }
            None => self.rasterize_blobs(
                &PasseAmas {
                    set: &self.leaves,
                    idx: &self.idx_leaf,
                    kind: VxmKind::Leaf,
                    big: self.leaf_big,
                    seed: hash_combine(self.seed, etiquette("feuillage")),
                },
                lod,
                pmin,
                pmax,
                sink,
            ),
        }
        // 2. fruits, 3. fleurs (les fleurs l'emportent sur les fruits)
        for (set, idx, kind, nom) in [
            (&self.fruits, &self.idx_fruit, VxmKind::Fruit, "fruits"),
            (&self.flowers, &self.idx_flower, VxmKind::Flower, "fleurs"),
        ] {
            let passe = PasseAmas {
                set,
                idx,
                kind,
                big: 0,
                seed: hash_combine(self.seed, etiquette(nom)),
            };
            self.rasterize_blobs(&passe, lod, pmin, pmax, sink);
        }
        // 4. bois : brindilles (rameau) puis capsules (écorce), qui l'emportent
        let (q0, q1) = niveau0(pmin, pmax, lod);
        let ids = self.idx_seg.query(q0, q1);
        let segs: Vec<SegmentNiveau> = ids
            .iter()
            .map(|&i| SegmentNiveau::new(&self.segments[i as usize], lod))
            .collect();
        let dans = |x: i32, y: i32, z: i32| {
            x >= pmin[0]
                && x < pmax[0]
                && y >= pmin[1]
                && y < pmax[1]
                && z >= pmin[2]
                && z < pmax[2]
                && tailler(x, y, z)
        };
        for s in segs.iter().filter(|s| s.is_thin()) {
            s.trace_thin(|x, y, z| {
                if dans(x, y, z) {
                    self.put(sink, VxmKind::Twig, 2, x, y, z);
                }
            });
        }
        let k = u32::from(lod);
        let seed_relief = hash_combine(self.seed, etiquette("relief"));
        let bruit = |px: i64, py: i64, pz: i64| {
            // 2,4 cycles par mètre en x et y, 0,55 en z, sur les coordonnées du niveau 0
            let (kx, kz) = (fx::lattice_factor(2_400), fx::lattice_factor(550));
            fx::value_noise(
                fx::mul(px << k, kx),
                fx::mul(py << k, kx),
                fx::mul(pz << k, kz),
                seed_relief,
            )
        };
        let hi_incl = [pmax[0] - 1, pmax[1] - 1, pmax[2] - 1];
        for s in segs.iter().filter(|s| !s.is_thin()) {
            s.fill_thick(pmin, hi_incl, &bruit, |x, y, z| {
                if tailler(x, y, z) {
                    let v = self.bark_variant(x, y, z, lod);
                    self.put(sink, VxmKind::Bark, v, x, y, z);
                }
            });
        }
    }
}

#[allow(dead_code)]
const _: i64 = VOX_PAR_M;
