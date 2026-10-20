//! Fenêtre d'écriture sur un chunk : un `VoxelSink` qui recompose chaque brique une seule fois.

use em_core::{ChunkKey, VoxelCoord, VoxelValue, brick_index, voxel_index};

use crate::brick::{BRICK_VOLUME, Brick};
use crate::chunk::{CHUNK_BRICKS, Chunk};
use crate::source::{PutMode, VoxelSink};

/// Brique en cours d'écriture : tableau dense et drapeau de modification.
struct BriqueOuverte {
    dense: Box<[VoxelValue; BRICK_VOLUME]>,
    sale: bool,
}

/// Fenêtre sur un chunk. Les voxels hors du chunk sont ignorés (et comptés). Chaque brique touchée est
/// tenue en tableau dense jusqu'à `finish` (ou la destruction), qui recompose une seule fois chaque
/// brique modifiée : le résultat ne dépend pas de l'ordre des écritures, et aucune brique n'est
/// recomposée par voxel.
pub struct ChunkWriter<'a> {
    chunk: &'a mut Chunk,
    origine: VoxelCoord,
    ouvertes: Vec<Option<BriqueOuverte>>,
    ignores: u64,
}

impl<'a> ChunkWriter<'a> {
    /// Ouvre une fenêtre sur `chunk`, qui est le chunk `key` du niveau courant.
    pub fn new(chunk: &'a mut Chunk, key: ChunkKey) -> Self {
        Self {
            chunk,
            origine: key.origin(),
            ouvertes: (0..CHUNK_BRICKS).map(|_| None).collect(),
            ignores: 0,
        }
    }

    /// Nombre d'écritures ignorées parce que hors du chunk ou sans effet (air en mode `Solid`).
    pub fn ignored(&self) -> u64 {
        self.ignores
    }

    /// Écrit la valeur telle quelle (air compris) ; renvoie faux si le voxel est hors du chunk.
    pub fn set(&mut self, at: VoxelCoord, value: VoxelValue) -> bool {
        let (lx, ly, lz) = (
            i64::from(at.x) - i64::from(self.origine.x),
            i64::from(at.y) - i64::from(self.origine.y),
            i64::from(at.z) - i64::from(self.origine.z),
        );
        if ![lx, ly, lz].iter().all(|c| (0..64).contains(c)) {
            self.ignores += 1;
            return false;
        }
        let (x, y, z) = (lx as u32, ly as u32, lz as u32);
        let b = brick_index(x >> 3, y >> 3, z >> 3);
        let i = usize::from(voxel_index(x & 7, y & 7, z & 7));
        let chunk = &*self.chunk;
        let ouverte = self.ouvertes[usize::from(b)].get_or_insert_with(|| {
            let mut dense = Box::new([VoxelValue::AIR; BRICK_VOLUME]);
            chunk.brick(b).to_dense(&mut dense);
            BriqueOuverte { dense, sale: false }
        });
        if ouverte.dense[i] != value {
            ouverte.dense[i] = value;
            ouverte.sale = true;
        }
        true
    }

    /// Termine : recompose les briques modifiées et compacte le chunk.
    pub fn finish(mut self) {
        self.terminer();
    }

    fn terminer(&mut self) {
        for (b, ouverte) in self.ouvertes.iter_mut().enumerate() {
            if let Some(o) = ouverte.take()
                && o.sale
            {
                self.chunk.set_brick(b as u16, Brick::from_dense(&o.dense));
            }
        }
        self.chunk.compact();
    }
}

impl VoxelSink for ChunkWriter<'_> {
    fn put(&mut self, at: VoxelCoord, value: VoxelValue, mode: PutMode) {
        match mode {
            PutMode::Solid => {
                if value.is_air() {
                    self.ignores += 1;
                } else {
                    self.set(at, value);
                }
            }
            PutMode::CarveAir => {
                self.set(at, VoxelValue::AIR);
            }
        }
    }
}

impl Drop for ChunkWriter<'_> {
    fn drop(&mut self) {
        self.terminer();
    }
}
