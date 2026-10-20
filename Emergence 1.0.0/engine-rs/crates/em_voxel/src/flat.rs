//! `FlatSource` : sol plat, source de test déterministe.

use em_core::{ChunkKey, Lod, VoxelValue, hash_combine};

use crate::brick::{BRICK_VOLUME, Brick};
use crate::chunk::{Chunk, ChunkHint};
use crate::source::VoxelSource;

/// Sol plat : tout voxel dont l'arête basse est strictement sous `height` (en voxels de niveau 0) est plein.
/// Au niveau `k`, le voxel `j` couvre la hauteur `j·2^k` : même sol à tous les niveaux, sans réduction.
#[derive(Clone, Debug)]
pub struct FlatSource {
    height: i32,
    solid: VoxelValue,
}

impl FlatSource {
    /// Sol de hauteur `height` (voxels de niveau 0, négatif permis) fait de `solid`.
    pub const fn new(height: i32, solid: VoxelValue) -> Self {
        Self { height, solid }
    }

    /// Hauteur de la surface, en voxels de niveau 0.
    pub const fn height(&self) -> i32 {
        self.height
    }

    /// Valeur du sol.
    pub const fn solid(&self) -> VoxelValue {
        self.solid
    }

    /// Vrai si la rangée `wy` (coordonnée du niveau `lod`) est pleine.
    fn rangee_pleine(&self, wy: i64, lod: Lod) -> bool {
        (wy << lod) < i64::from(self.height)
    }
}

impl VoxelSource for FlatSource {
    fn fill_chunk(&self, key: ChunkKey, lod: Lod, out: &mut Chunk) {
        *out = Chunk::new_air();
        let base = i64::from(key.y) * 64;
        for by in 0..8_i64 {
            let pleines: Vec<bool> = (0..8)
                .map(|ly| self.rangee_pleine(base + by * 8 + ly, lod))
                .collect();
            let brique = if pleines.iter().all(|&p| p) {
                Brick::uniform(self.solid)
            } else if pleines.iter().all(|&p| !p) {
                continue;
            } else {
                let mut dense = [VoxelValue::AIR; BRICK_VOLUME];
                for (i, v) in dense.iter_mut().enumerate() {
                    if pleines[i >> 6] {
                        *v = self.solid;
                    }
                }
                Brick::from_dense(&dense)
            };
            for bz in 0..8_u16 {
                for bx in 0..8_u16 {
                    out.set_brick(bx + 8 * bz + 64 * (by as u16), brique.clone());
                }
            }
        }
        out.compact();
    }

    fn classify(&self, key: ChunkKey, lod: Lod) -> ChunkHint {
        let bas = i64::from(key.y) * 64;
        match (self.rangee_pleine(bas, lod), self.rangee_pleine(bas + 63, lod)) {
            (true, true) => ChunkHint::Solid(self.solid),
            (false, false) => ChunkHint::Air,
            _ => ChunkHint::Unknown,
        }
    }

    fn version_tag(&self) -> u64 {
        hash_combine(
            hash_combine(0xF1A7_0001, self.height as u64),
            u64::from(self.solid.raw()),
        )
    }
}
