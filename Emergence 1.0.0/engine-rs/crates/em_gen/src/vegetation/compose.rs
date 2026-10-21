//! Plans composites : plusieurs plans posés à des décalages entiers (une haie est une rangée d'arbustes).

use std::sync::Arc;

use em_core::{Lod, VoxelBox, VoxelCoord, VoxelValue, floor_div, hash_combine};
use em_voxel::{PutMode, VoxelSink};
use serde::{Deserialize, Serialize};

use super::fx::{UN, VOX_PAR_M};
use super::generators::{BushGenerator, BushParams, TreeParams};
use super::species::{Season, SpeciesTable};
use super::topiary::TopiaryShape;
use crate::error::GenError;
use crate::generator::{GenParams, GenPlan, Generator, GeneratorId};
use crate::vxm::VxmClasses;

/// Puits qui décale chaque voxel écrit.
struct SinkDecale<'a> {
    interieur: &'a mut dyn VoxelSink,
    delta: VoxelCoord,
}

impl VoxelSink for SinkDecale<'_> {
    fn put(&mut self, at: VoxelCoord, value: VoxelValue, mode: PutMode) {
        self.interieur.put(
            VoxelCoord::new(at.x + self.delta.x, at.y + self.delta.y, at.z + self.delta.z),
            value,
            mode,
        );
    }
}

/// Plusieurs plans posés à des décalages du niveau 0 (repère local du composite).
pub struct CompositePlan {
    parts: Vec<(VoxelCoord, Arc<dyn GenPlan>)>,
}

impl CompositePlan {
    /// Composite de ces pièces, chacune avec son décalage en voxels du niveau 0.
    pub fn new(parts: Vec<(VoxelCoord, Arc<dyn GenPlan>)>) -> Self {
        Self { parts }
    }

    fn decalage(off: VoxelCoord, lod: Lod) -> VoxelCoord {
        let pas = 1_i64 << lod;
        let f = |v: i32| floor_div(i64::from(v), pas) as i32;
        VoxelCoord::new(f(off.x), f(off.y), f(off.z))
    }
}

impl GenPlan for CompositePlan {
    fn bounds(&self, lod: Lod) -> VoxelBox {
        let mut lo = [i32::MAX; 3];
        let mut hi = [i32::MIN; 3];
        for (off, plan) in &self.parts {
            let d = Self::decalage(*off, lod);
            let b = plan.bounds(lod);
            let (a, c) = (b.min(), b.max());
            lo = [lo[0].min(a.x + d.x), lo[1].min(a.y + d.y), lo[2].min(a.z + d.z)];
            hi = [hi[0].max(c.x + d.x), hi[1].max(c.y + d.y), hi[2].max(c.z + d.z)];
        }
        VoxelBox::new(
            VoxelCoord::new(lo[0], lo[1], lo[2]),
            VoxelCoord::new(hi[0], hi[1], hi[2]),
        )
        .unwrap_or_else(|_| {
            VoxelBox::new(VoxelCoord::new(0, 0, 0), VoxelCoord::new(1, 1, 1)).expect("boîte unité")
        })
    }

    fn rasterize(&self, lod: Lod, window: VoxelBox, sink: &mut dyn VoxelSink) {
        for (off, plan) in &self.parts {
            let d = Self::decalage(*off, lod);
            let (a, b) = (window.min(), window.max());
            let local = VoxelBox::new(
                VoxelCoord::new(a.x - d.x, a.y - d.y, a.z - d.z),
                VoxelCoord::new(b.x - d.x, b.y - d.y, b.z - d.z),
            );
            let Ok(local) = local else { continue };
            let pb = plan.bounds(lod);
            let (m, n) = (pb.min(), pb.max());
            let (l0, l1) = (local.min(), local.max());
            if l1.x <= m.x || l0.x >= n.x || l1.y <= m.y || l0.y >= n.y || l1.z <= m.z || l0.z >= n.z {
                continue;
            }
            plan.rasterize(
                lod,
                local,
                &mut SinkDecale {
                    interieur: sink,
                    delta: d,
                },
            );
        }
    }
}

/// Paramètres d'une haie : une rangée d'arbustes le long de l'axe est.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct HedgeParams {
    /// Essence d'arbuste.
    pub species: String,
    /// Longueur de la haie en millimètres.
    pub length_mm: u32,
    /// Hauteur des arbustes en millimètres.
    pub height_mm: u32,
    /// Écart entre deux arbustes en millimètres.
    #[serde(default = "ecart_defaut")]
    pub spacing_mm: u32,
    /// Saison.
    #[serde(default = "ete")]
    pub season: Season,
    /// Taille de la haie : `cube` pour une haie taillée au cordeau.
    #[serde(default)]
    pub topiary: Option<TopiaryShape>,
}

fn ecart_defaut() -> u32 {
    700
}
fn ete() -> Season {
    Season::Summer
}

/// Générateur de haies.
#[derive(Clone, Debug)]
pub struct HedgeGenerator {
    bush: BushGenerator,
}

impl HedgeGenerator {
    /// Générateur sur une table d'essences et des classes injectées.
    pub fn new(table: Arc<SpeciesTable>, classes: VxmClasses) -> Self {
        Self {
            bush: BushGenerator::new(table, classes),
        }
    }
}

impl Generator for HedgeGenerator {
    fn id(&self) -> GeneratorId {
        GeneratorId::HEDGE
    }
    fn version(&self) -> u32 {
        1
    }
    fn plan(&self, params: &GenParams, seed: u64) -> Result<Arc<dyn GenPlan>, GenError> {
        let p: HedgeParams = params.decode_json(GeneratorId::HEDGE)?;
        if p.spacing_mm < 200 || p.length_mm < p.spacing_mm || p.length_mm > 60_000 {
            return Err(GenError::BadParams(
                "haie : écart ≥ 200 mm et longueur entre l'écart et 60 m".into(),
            ));
        }
        let n = p.length_mm / p.spacing_mm;
        let pas_vox = (i64::from(p.spacing_mm) * VOX_PAR_M / 1000) as i32;
        let mut parts: Vec<(VoxelCoord, Arc<dyn GenPlan>)> = Vec::new();
        for i in 0..n {
            let s = hash_combine(seed, u64::from(i));
            let bp = BushParams {
                plant: TreeParams {
                    species: p.species.clone(),
                    height_mm: p.height_mm,
                    season: p.season,
                    leaf_density_permille: 1000,
                },
                topiary: p.topiary,
            };
            let plan = self.bush.plant_plan(&bp.to_params()?, s)?;
            let jitter = ((s >> 20) % 5) as i32 - 2;
            parts.push((VoxelCoord::new(pas_vox * i as i32, 0, jitter), plan));
        }
        let _ = UN;
        Ok(Arc::new(CompositePlan::new(parts)))
    }
}
