//! Silhouettes lointaines, souches et troncs tombés : des plans « sans croissance » bâtis directement en capsules
//! et en amas, avec les tirages de départ du squelette pour que la silhouette tombe sous le vrai houppier.

use std::sync::Arc;

use em_core::hash_combine;
use serde::{Deserialize, Serialize};

use super::blob::Blob;
use super::frame::Segment;
use super::fx::{self, Stream, UN, V3, VOX_PAR_M};
use super::plan::{Parts, PlanStats, PlantPlan};
use super::skeleton::crown_profile;
use super::species::{ArchKind, Season, Species, SpeciesTable};
use crate::error::GenError;
use crate::generator::{GenParams, GenPlan, Generator, GeneratorId};
use crate::vxm::VxmClasses;

fn etiquette(s: &str) -> u64 {
    s.bytes().fold(0xcbf2_9ce4_8422_2325_u64, |h, b| {
        (h ^ u64::from(b)).wrapping_mul(0x0100_0000_01b3)
    })
}

/// Silhouette lointaine : un fût et des disques de houppier empilés, sans croissance. Les premiers tirages sont
/// ceux de `Grower::new` et de `TreeArchitecture::seed_jobs` : mêmes `z_bole`, rayon de couronne et longueur de fût
/// que l'arbre complet de la même graine.
pub fn silhouette_plan(
    sp: &Species,
    h: i64,
    season: Season,
    seed: u64,
    classes: &VxmClasses,
) -> Result<PlantPlan, GenError> {
    silhouette_plan_reglee(sp, h, season, seed, classes, sp.sil_env, sp.sil_dens)
}

/// Comme `silhouette_plan`, avec l'échelle de l'enveloppe et la densité des disques (Q16) : sert au réglage.
pub fn silhouette_plan_reglee(
    sp: &Species,
    h: i64,
    season: Season,
    seed: u64,
    classes: &VxmClasses,
    enveloppe: i64,
    densite: i64,
) -> Result<PlantPlan, GenError> {
    let mut rng = Stream::new(hash_combine(seed, etiquette("squelette")), 0x4752_4F57);
    let z_bole = fx::mul(h, rng.uniform(sp.bole.0, sp.bole.1));
    let crown_r = fx::mul(fx::mul(h, sp.crown_r), rng.uniform(UN * 85 / 100, UN * 115 / 100));
    let _tilt = rng.uniform(0, 3 * UN / 360);
    let _az = rng.unit();
    let tronc = if sp.arch == ArchKind::Excurrent {
        h
    } else {
        fx::mul(h, rng.uniform(sp.trunk_frac.0, sp.trunk_frac.1))
    };
    let h_m = h / VOX_PAR_M;
    let r_base = fx::mul(fx::mul(sp.trunk_k, h_m), UN) * VOX_PAR_M;
    let mut segments = Vec::new();
    // fût : un segment par mètre, effilé jusqu'à 45 % de la base
    let haut_fut = if sp.arch == ArchKind::Excurrent {
        h * 9 / 10
    } else {
        tronc
    };
    let n = (haut_fut / (VOX_PAR_M * UN)).max(1);
    for i in 0..n {
        let (z0, z1) = (haut_fut * i / n, haut_fut * (i + 1) / n);
        let eff = |z: i64| fx::mul(r_base, UN - fx::mul(UN * 55 / 100, fx::div(z, h.max(1))));
        let flare = |z: i64| UN + fx::mul(UN * 6 / 10, fx::exp_neg(fx::div(z / VOX_PAR_M, 42_598)));
        segments.push(Segment {
            a: V3::new(0, 0, z0),
            b: V3::new(0, 0, z1),
            r0: fx::mul(eff(z0), flare(z0)),
            r1: fx::mul(eff(z1), flare(z1)),
            trunk: true,
        });
    }
    // houppier : disques de 1 m d'épaisseur dont le rayon suit l'enveloppe de l'essence
    let mut leaves = Vec::new();
    let feuillu = sp.season_leaf_factor(season) > 0;
    if feuillu {
        let pas = VOX_PAR_M * UN * 3 / 4;
        let mut z = z_bole.max(h / 8);
        while z < h {
            let hr = fx::div(z - z_bole, (h - z_bole).max(10 * UN));
            let rho = fx::mul(fx::mul(crown_r, crown_profile(sp.crown_shape, hr)), enveloppe).max(2 * UN);
            let demi = pas * 6 / 10;
            leaves.push(Blob {
                center: V3::new(0, 0, z),
                dir: V3::HAUT,
                r: rho,
                stretch: UN,
                flat: fx::div(demi, rho),
                density: densite,
                variant: 0,
            });
            z += pas;
        }
    }
    let stats = PlanStats {
        nodes: segments.len(),
        leafy: leaves.len(),
        segments: segments.len(),
        base_radius: r_base,
    };
    let _ = seed;
    PlantPlan::assemble(
        Parts {
            seed,
            height: h,
            segments,
            leaves,
            flowers: Vec::new(),
            fruits: Vec::new(),
            leaf_big: 0,
            alt_rule: sp.alt_rule,
            topiary: None,
            slot: sp.slot,
            grossier: true,
            stats,
        },
        classes,
    )
}

/// Paramètres de la silhouette lointaine : ceux d'un arbre.
pub use super::generators::TreeParams as SilhouetteParams;

/// Générateur de silhouettes lointaines (niveaux 3 et plus).
#[derive(Clone, Debug)]
pub struct TreeSilhouetteGenerator {
    table: Arc<SpeciesTable>,
    classes: VxmClasses,
}

impl TreeSilhouetteGenerator {
    /// Générateur sur une table d'essences et des classes injectées.
    pub fn new(table: Arc<SpeciesTable>, classes: VxmClasses) -> Self {
        Self { table, classes }
    }

    /// Le plan concret.
    pub fn plant_plan(&self, params: &GenParams, seed: u64) -> Result<PlantPlan, GenError> {
        let p: SilhouetteParams = params.decode_json(GeneratorId::TREE_SILHOUETTE)?;
        let sp = self.table.get(&p.species)?;
        let h = super::generators::hauteur_arbre(sp, p.height_mm, seed);
        silhouette_plan(sp, h, p.season, seed, &self.classes)
    }
}

impl Generator for TreeSilhouetteGenerator {
    fn id(&self) -> GeneratorId {
        GeneratorId::TREE_SILHOUETTE
    }
    fn version(&self) -> u32 {
        1
    }
    fn plan(&self, params: &GenParams, seed: u64) -> Result<Arc<dyn GenPlan>, GenError> {
        Ok(Arc::new(self.plant_plan(params, seed)?))
    }
}

/// Paramètres d'une souche.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct StumpParams {
    /// Essence de l'arbre abattu.
    pub species: String,
    /// Hauteur qu'avait l'arbre (fixe la grosseur du fût), en millimètres.
    pub tree_height_mm: u32,
    /// Hauteur de la souche, en millimètres.
    pub cut_mm: u32,
}

/// Générateur de souches : fût coupé net, empattement et racines de surface.
#[derive(Clone, Debug)]
pub struct StumpGenerator {
    table: Arc<SpeciesTable>,
    classes: VxmClasses,
}

impl StumpGenerator {
    /// Générateur sur une table d'essences et des classes injectées.
    pub fn new(table: Arc<SpeciesTable>, classes: VxmClasses) -> Self {
        Self { table, classes }
    }
}

fn mm_vers_vox(mm: u32) -> i64 {
    i64::from(mm) * VOX_PAR_M * UN / 1000
}

impl Generator for StumpGenerator {
    fn id(&self) -> GeneratorId {
        GeneratorId::STUMP
    }
    fn version(&self) -> u32 {
        1
    }
    fn plan(&self, params: &GenParams, seed: u64) -> Result<Arc<dyn GenPlan>, GenError> {
        let p: StumpParams = params.decode_json(GeneratorId::STUMP)?;
        let sp = self.table.get(&p.species)?;
        if sp.is_bush() || p.cut_mm == 0 || p.tree_height_mm == 0 {
            return Err(GenError::BadParams(
                "souche : arbre, hauteur d'arbre et de coupe non nulles".into(),
            ));
        }
        let mut rng = Stream::new(seed, etiquette("souche"));
        let h = mm_vers_vox(p.tree_height_mm);
        let r = fx::mul(
            fx::mul(sp.trunk_k, h / VOX_PAR_M),
            rng.uniform(UN * 88 / 100, UN * 114 / 100),
        ) * VOX_PAR_M;
        let cut = mm_vers_vox(p.cut_mm);
        let mut segments = vec![Segment {
            a: V3::new(0, 0, -UN * 2),
            b: V3::new(0, 0, cut + UN * 2),
            r0: fx::mul(r, UN * 16 / 10),
            r1: fx::mul(r, UN * 12 / 10),
            trunk: true,
        }];
        racines(&mut segments, r, &mut rng);
        let stats = PlanStats {
            nodes: 1,
            leafy: 0,
            segments: segments.len(),
            base_radius: r,
        };
        Ok(Arc::new(PlantPlan::assemble(
            Parts {
                seed,
                height: cut,
                segments,
                leaves: Vec::new(),
                flowers: Vec::new(),
                fruits: Vec::new(),
                leaf_big: 0,
                alt_rule: sp.alt_rule,
                topiary: None,
                slot: sp.slot,
                grossier: false,
                stats,
            },
            &self.classes,
        )?))
    }
}

/// Racines de surface autour d'un fût de rayon `r_base` (comme `finalize_skeleton`).
fn racines(segments: &mut Vec<Segment>, r_base: i64, rng: &mut Stream) {
    const PROFIL: [i64; 6] = [62, 50, 38, 27, 17, 9];
    let nroots = rng.integers(5, 7);
    let az0 = rng.unit();
    for k in 0..nroots {
        let a = az0 + UN * k / nroots + fx::mul(rng.normal(), 2_608);
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
}

/// Paramètres d'un tronc tombé.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct LogParams {
    /// Essence.
    pub species: String,
    /// Longueur en millimètres.
    pub length_mm: u32,
    /// Rayon en millimètres.
    pub radius_mm: u32,
}

/// Générateur de troncs tombés : un fût couché, légèrement arqué, avec des chicots de branches.
#[derive(Clone, Debug)]
pub struct FallenLogGenerator {
    table: Arc<SpeciesTable>,
    classes: VxmClasses,
}

impl FallenLogGenerator {
    /// Générateur sur une table d'essences et des classes injectées.
    pub fn new(table: Arc<SpeciesTable>, classes: VxmClasses) -> Self {
        Self { table, classes }
    }
}

impl Generator for FallenLogGenerator {
    fn id(&self) -> GeneratorId {
        GeneratorId::FALLEN_LOG
    }
    fn version(&self) -> u32 {
        1
    }
    fn plan(&self, params: &GenParams, seed: u64) -> Result<Arc<dyn GenPlan>, GenError> {
        let p: LogParams = params.decode_json(GeneratorId::FALLEN_LOG)?;
        let sp = self.table.get(&p.species)?;
        if p.length_mm < 500 || p.radius_mm < 60 {
            return Err(GenError::BadParams(
                "tronc tombé : longueur ≥ 500 mm et rayon ≥ 60 mm".into(),
            ));
        }
        let mut rng = Stream::new(seed, etiquette("tronc_tombe"));
        let (len, r) = (mm_vers_vox(p.length_mm), mm_vers_vox(p.radius_mm));
        let n = (len / (VOX_PAR_M * UN / 2)).max(2);
        let mut segments = Vec::new();
        let (mut y, mut dy) = (0_i64, 0_i64);
        let mut prec = V3::new(0, 0, r);
        for i in 1..=n {
            dy += fx::mul(rng.normal(), UN / 40);
            y += dy;
            let x = len * i / n;
            let ray = fx::mul(r, UN - fx::mul(UN * 25 / 100, fx::div(x, len)));
            let cur = V3::new(x, y, ray);
            segments.push(Segment {
                a: prec,
                b: cur,
                r0: fx::mul(r, UN - fx::mul(UN * 25 / 100, fx::div(prec.x, len))),
                r1: ray,
                trunk: true,
            });
            prec = cur;
            // chicot de branche cassée tous les ~80 cm
            if i % 3 == 0 {
                let a = rng.uniform(UN / 8, UN * 3 / 8);
                let out = V3::new(fx::cos(a) / 3, fx::cos(a), fx::sin(a)).unit();
                segments.push(Segment {
                    a: cur,
                    b: cur.add(out.scale(rng.uniform(UN * 6 / 10, UN * 12 / 10) * 4)),
                    r0: ray / 4,
                    r1: ray / 6,
                    trunk: false,
                });
            }
        }
        let haut = r * 3 + UN * 4 * 4;
        let stats = PlanStats {
            nodes: 1,
            leafy: 0,
            segments: segments.len(),
            base_radius: r,
        };
        Ok(Arc::new(PlantPlan::assemble(
            Parts {
                seed,
                height: haut,
                segments,
                leaves: Vec::new(),
                flowers: Vec::new(),
                fruits: Vec::new(),
                leaf_big: 0,
                alt_rule: sp.alt_rule,
                topiary: None,
                slot: sp.slot,
                grossier: false,
                stats,
            },
            &self.classes,
        )?))
    }
}
