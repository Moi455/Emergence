//! `PlacedModel` : un modèle posé sur la grille monde (pivot, quarts de tour, essence), servi en lecture seule.

use std::sync::Arc;

use em_core::{ChunkKey, Lod, VoxelBox, VoxelCoord, VoxelValue, floor_div, hash_combine};
use em_voxel::{Chunk, ChunkHint, ChunkWriter, VoxelSource};

use super::classes::{TintTable, VxmClasses};
use super::model::VxmModel;
use super::rotation::QuarterTurns;
use crate::error::GenError;

/// Un modèle `.vxm` posé dans le monde.
///
/// Position monde d'un voxel du LOD k : `floor_div(pivot_LOD0, 2^k) + rot(local)`, la rotation d'un quart
/// de tour (est vers nord) se faisant autour du centre de la cellule pivot (docs/19a § 1.4).
#[derive(Clone, Debug)]
pub struct PlacedModel {
    model: Arc<VxmModel>,
    pivot: VoxelCoord,
    turns: QuarterTurns,
    species_slot: u8,
    tints: TintTable,
}

impl PlacedModel {
    /// Pose `model` : `pivot` est la cellule du pied du tronc au LOD 0 (repère monde), `quarter_turns` dans 0..=3,
    /// `species_slot` la case d'essence de la teinte (0..=31). Classes de matière du catalogue.
    pub fn new(
        model: Arc<VxmModel>,
        pivot: VoxelCoord,
        quarter_turns: u8,
        species_slot: u8,
    ) -> Result<Self, GenError> {
        Self::with_classes(model, pivot, quarter_turns, species_slot, &VxmClasses::standard())
    }

    /// Comme `new`, avec des classes de matière explicites (issues d'une `MaterialTable`).
    pub fn with_classes(
        model: Arc<VxmModel>,
        pivot: VoxelCoord,
        quarter_turns: u8,
        species_slot: u8,
        classes: &VxmClasses,
    ) -> Result<Self, GenError> {
        Ok(Self {
            model,
            pivot,
            turns: QuarterTurns::new(quarter_turns)?,
            species_slot,
            tints: TintTable::new(classes, species_slot)?,
        })
    }

    /// Le modèle posé.
    pub fn model(&self) -> &Arc<VxmModel> {
        &self.model
    }

    /// Pivot au LOD 0, repère monde.
    pub fn pivot(&self) -> VoxelCoord {
        self.pivot
    }

    /// Quarts de tour.
    pub fn quarter_turns(&self) -> QuarterTurns {
        self.turns
    }

    /// Case d'essence de la teinte.
    pub fn species_slot(&self) -> u8 {
        self.species_slot
    }

    /// Pivot au niveau `lod` : `floor_div(pivot, 2^lod)`.
    pub fn pivot_at(&self, lod: Lod) -> VoxelCoord {
        let pas = 1_i64 << lod.min(31);
        let f = |v: i32| floor_div(i64::from(v), pas) as i32;
        VoxelCoord::new(f(self.pivot.x), f(self.pivot.y), f(self.pivot.z))
    }

    /// Boîte du modèle dans le monde au niveau `lod` (vide au-delà du LOD 5).
    pub fn bounds(&self, lod: Lod) -> VoxelBox {
        let local = self.model.bounds(lod);
        let (a, b) = (local.min(), local.max());
        let p = self.pivot_at(lod);
        if local.is_empty() {
            return VoxelBox::new(p, p).expect("boîte vide valide");
        }
        let (rmin, rmax) = self
            .turns
            .rotate_box([i64::from(a.x), i64::from(a.z)], [i64::from(b.x), i64::from(b.z)]);
        VoxelBox::new(
            VoxelCoord::new(p.x + rmin[0] as i32, p.y + a.y, p.z + rmin[1] as i32),
            VoxelCoord::new(p.x + rmax[0] as i32, p.y + b.y, p.z + rmax[1] as i32),
        )
        .expect("boîte tournée valide")
    }

    /// Nombre de voxels pleins au niveau `lod`.
    pub fn voxel_count(&self, lod: Lod) -> usize {
        self.model.voxel_count(lod)
    }

    /// Tous les voxels pleins du niveau `lod`, en coordonnées monde de ce niveau, triés comme le fichier
    /// (y, z, x locaux).
    pub fn world_voxels(&self, lod: Lod) -> impl Iterator<Item = (VoxelCoord, VoxelValue)> + '_ {
        let p = self.pivot_at(lod);
        let layer = self.model.layer(lod);
        layer.into_iter().flat_map(move |l| {
            l.cells().iter().map(move |c| {
                let q = l.local_of(c);
                let (dx, dz) = self.turns.rotate(i64::from(q[0]), i64::from(q[2]));
                (
                    VoxelCoord::new(p.x + dx as i32, p.y + q[1], p.z + dz as i32),
                    self.tints.value(c.kind, c.variant),
                )
            })
        })
    }
}

impl VoxelSource for PlacedModel {
    fn fill_chunk(&self, key: ChunkKey, lod: Lod, out: &mut Chunk) {
        *out = Chunk::new_air();
        let Some(layer) = self.model.layer(lod) else {
            return;
        };
        if self.classify(key, lod) == ChunkHint::Air {
            return;
        }
        // Fenêtre du chunk ramenée au repère local du modèle : on tourne la boîte dans l'autre sens.
        let p = self.pivot_at(lod);
        let o = key.origin();
        let (ex, ez) = (i64::from(o.x - p.x), i64::from(o.z - p.z));
        let (lo_xz, hi_xz) = self.turns.inverse().rotate_box([ex, ez], [ex + 64, ez + 64]);
        let lo = [lo_xz[0], i64::from(o.y - p.y), lo_xz[1]];
        let hi = [hi_xz[0], i64::from(o.y - p.y) + 64, hi_xz[1]];
        let mut writer = ChunkWriter::new(out, key);
        for (q, c) in layer.in_window(lo, hi) {
            let (dx, dz) = self.turns.rotate(i64::from(q[0]), i64::from(q[2]));
            let monde = VoxelCoord::new(p.x + dx as i32, p.y + q[1], p.z + dz as i32);
            writer.set(monde, self.tints.value(c.kind, c.variant));
        }
        writer.finish();
    }

    fn classify(&self, key: ChunkKey, lod: Lod) -> ChunkHint {
        let b = self.bounds(lod);
        let (o, m) = (key.origin(), b.max());
        let n = b.min();
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
        let mut h = hash_combine(0x5658_4D01, self.model.fingerprint());
        for v in [self.pivot.x, self.pivot.y, self.pivot.z] {
            h = hash_combine(h, v as u64);
        }
        hash_combine(
            hash_combine(h, u64::from(self.turns.get())),
            u64::from(self.species_slot),
        )
    }
}
