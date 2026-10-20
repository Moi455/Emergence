//! Contrats de lecture et d'écriture de voxels (docs/19 § 2.5).

use em_core::{ChunkKey, Lod, VoxelCoord, VoxelValue};

use crate::brick::Brick;
use crate::chunk::{Chunk, ChunkHint};

/// Mode d'écriture d'un voxel dans un puits.
#[derive(Copy, Clone, Debug, PartialEq, Eq)]
pub enum PutMode {
    /// Pose la valeur ; une valeur d'air est ignorée (elle ne creuse pas).
    Solid,
    /// Creuse : le voxel devient de l'air, quelle que soit la valeur donnée.
    CarveAir,
}

/// Toute source de voxels (sol, deltas, entités, modèle, composite).
pub trait VoxelSource: Send + Sync {
    /// Remplace entièrement `out` par le chunk `key` au niveau `lod`. Fonction pure : mêmes entrées,
    /// mêmes voxels, quel que soit le fil ou l'ordre des appels.
    fn fill_chunk(&self, key: ChunkKey, lod: Lod, out: &mut Chunk);

    /// Classement rapide sans remplir, pour sauter les chunks vides.
    fn classify(&self, _key: ChunkKey, _lod: Lod) -> ChunkHint {
        ChunkHint::Unknown
    }

    /// Étiquette de version (générateurs, deltas) pour invalider les caches.
    fn version_tag(&self) -> u64;

    /// Brique `b` du chunk `key` (par défaut : remplit le chunk entier puis en extrait la brique).
    fn brick_at(&self, key: ChunkKey, lod: Lod, b: u16) -> Brick {
        let mut chunk = Chunk::new_air();
        self.fill_chunk(key, lod, &mut chunk);
        chunk.brick(b).clone()
    }

    /// Voxel en coordonnées du niveau `lod` (par défaut : remplit le chunk entier).
    fn voxel_at(&self, at: VoxelCoord, lod: Lod) -> VoxelValue {
        let mut chunk = Chunk::new_air();
        self.fill_chunk(at.chunk(), lod, &mut chunk);
        let [x, y, z] = at.local_in_chunk();
        chunk.get(x, y, z)
    }
}

/// Puits de voxels : reçoit des écritures en coordonnées du niveau courant.
pub trait VoxelSink {
    /// Écrit un voxel selon le mode.
    fn put(&mut self, at: VoxelCoord, value: VoxelValue, mode: PutMode);
}
