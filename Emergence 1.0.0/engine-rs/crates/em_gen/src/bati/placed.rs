//! `PlacedPlan` : un plan de générateur posé dans le monde (pivot en voxels de niveau 0), servi comme `VoxelSource`
//! en lecture seule. Le numéro de pierre ou de tuile vient du plan, donc ne dépend ni du chunk ni du niveau.
//!
//! Position monde d'un voxel du niveau `k` : `floor_div(pivot, 2^k) + local`, comme `PlacedModel` ; poser le pivot
//! sur un multiple de 32 voxels garde les niveaux grossiers alignés sur la réduction du monde.

use std::sync::Arc;

use em_core::{ChunkKey, Lod, VoxelBox, VoxelCoord, VoxelValue, floor_div, hash_combine};
use em_voxel::{Chunk, ChunkHint, ChunkWriter, PutMode, VoxelSink, VoxelSource};

use crate::generator::GenPlan;

/// Puits qui décale chaque voxel écrit (repère local du plan -> repère monde).
struct SinkDecale<'a> {
    interieur: &'a mut dyn VoxelSink,
    delta: VoxelCoord,
}

impl VoxelSink for SinkDecale<'_> {
    fn put(&mut self, at: VoxelCoord, value: VoxelValue, mode: PutMode) {
        let monde = VoxelCoord::new(at.x + self.delta.x, at.y + self.delta.y, at.z + self.delta.z);
        self.interieur.put(monde, value, mode);
    }
}

/// Un plan posé dans le monde.
#[derive(Clone)]
pub struct PlacedPlan {
    plan: Arc<dyn GenPlan>,
    pivot: VoxelCoord,
    tag: u64,
}

impl PlacedPlan {
    /// Pose `plan` : `pivot` est la cellule de l'origine locale au niveau 0 ; `tag` (version et graine du
    /// générateur) invalide les caches quand le plan change.
    pub fn new(plan: Arc<dyn GenPlan>, pivot: VoxelCoord, tag: u64) -> Self {
        Self { plan, pivot, tag }
    }

    /// Pivot au niveau 0.
    pub const fn pivot(&self) -> VoxelCoord {
        self.pivot
    }

    /// Pivot au niveau `lod` : `floor_div(pivot, 2^lod)`.
    pub fn pivot_at(&self, lod: Lod) -> VoxelCoord {
        let pas = 1_i64 << lod.min(31);
        let f = |v: i32| floor_div(i64::from(v), pas) as i32;
        VoxelCoord::new(f(self.pivot.x), f(self.pivot.y), f(self.pivot.z))
    }

    /// Boîte du plan dans le monde au niveau `lod`.
    pub fn bounds(&self, lod: Lod) -> VoxelBox {
        let local = self.plan.bounds(lod);
        let p = self.pivot_at(lod);
        let (a, b) = (local.min(), local.max());
        VoxelBox::new(
            VoxelCoord::new(a.x + p.x, a.y + p.y, a.z + p.z),
            VoxelCoord::new(b.x + p.x, b.y + p.y, b.z + p.z),
        )
        .expect("boîte du plan valide")
    }
}

impl VoxelSource for PlacedPlan {
    fn fill_chunk(&self, key: ChunkKey, lod: Lod, out: &mut Chunk) {
        *out = Chunk::new_air();
        if self.classify(key, lod) == ChunkHint::Air {
            return;
        }
        let p = self.pivot_at(lod);
        let o = key.origin();
        let a = VoxelCoord::new(o.x - p.x, o.y - p.y, o.z - p.z);
        let b = VoxelCoord::new(a.x + 64, a.y + 64, a.z + 64);
        let Ok(fenetre) = VoxelBox::new(a, b) else { return };
        let mut writer = ChunkWriter::new(out, key);
        let mut sink = SinkDecale {
            interieur: &mut writer,
            delta: p,
        };
        self.plan.rasterize(lod, fenetre, &mut sink);
        writer.finish();
    }

    fn classify(&self, key: ChunkKey, lod: Lod) -> ChunkHint {
        let b = self.bounds(lod);
        let (o, m, n) = (key.origin(), b.max(), b.min());
        let disjoint = b.is_empty()
            || o.x + 64 <= n.x
            || o.x >= m.x
            || o.y + 64 <= n.y
            || o.y >= m.y
            || o.z + 64 <= n.z
            || o.z >= m.z;
        if disjoint {
            ChunkHint::Air
        } else {
            ChunkHint::Unknown
        }
    }

    fn version_tag(&self) -> u64 {
        let mut h = hash_combine(0x504C_414E, self.tag);
        for v in [self.pivot.x, self.pivot.y, self.pivot.z] {
            h = hash_combine(h, i64::from(v) as u64);
        }
        h
    }
}
