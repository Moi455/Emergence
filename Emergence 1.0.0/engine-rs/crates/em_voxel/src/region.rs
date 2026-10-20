//! Régions (32 × 16 × 32 chunks) : regroupement en mémoire des éditions, ordre des clés toujours trié.

use std::collections::BTreeMap;

use em_core::{ChunkKey, Fnv64, RegionKey};

use crate::brick::Brick;
use crate::chunk::Chunk;

/// Les briques réécrites d'un chunk, triées par numéro de brique.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ChunkEdits {
    bricks: BTreeMap<u16, Brick>,
}

impl ChunkEdits {
    /// Nombre de briques réécrites.
    pub fn len(&self) -> usize {
        self.bricks.len()
    }

    /// Vrai si aucune brique n'est réécrite.
    pub fn is_empty(&self) -> bool {
        self.bricks.is_empty()
    }

    /// Brique réécrite `b`, si elle l'est.
    pub fn get(&self, b: u16) -> Option<&Brick> {
        self.bricks.get(&b)
    }

    /// Briques réécrites par numéro croissant.
    pub fn iter(&self) -> impl Iterator<Item = (u16, &Brick)> + '_ {
        self.bricks.iter().map(|(b, brick)| (*b, brick))
    }

    /// Pose les briques réécrites sur un chunk.
    pub fn apply_to(&self, chunk: &mut Chunk) {
        for (b, brick) in &self.bricks {
            chunk.set_brick(*b, brick.clone());
        }
    }

    pub(crate) fn insert(&mut self, b: u16, brick: Brick) {
        self.bricks.insert(b, brick);
    }

    pub(crate) fn remove(&mut self, b: u16) {
        self.bricks.remove(&b);
    }
}

/// Éditions d'une région : seulement les chunks qui ont au moins une brique réécrite.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Region {
    key: RegionKey,
    chunks: BTreeMap<ChunkKey, ChunkEdits>,
}

impl Region {
    pub(crate) fn new(key: RegionKey) -> Self {
        Self {
            key,
            chunks: BTreeMap::new(),
        }
    }

    /// Clé de la région.
    pub fn key(&self) -> RegionKey {
        self.key
    }

    /// Nombre de chunks édités.
    pub fn chunk_count(&self) -> usize {
        self.chunks.len()
    }

    /// Nombre de briques réécrites dans toute la région.
    pub fn brick_count(&self) -> usize {
        self.chunks.values().map(ChunkEdits::len).sum()
    }

    /// Éditions d'un chunk.
    pub fn chunk(&self, key: ChunkKey) -> Option<&ChunkEdits> {
        self.chunks.get(&key)
    }

    /// Chunks édités par clé croissante.
    pub fn chunks(&self) -> impl Iterator<Item = (ChunkKey, &ChunkEdits)> + '_ {
        self.chunks.iter().map(|(k, e)| (*k, e))
    }

    /// Vrai si la région n'a plus aucune édition.
    pub fn is_empty(&self) -> bool {
        self.chunks.is_empty()
    }

    /// Ajoute l'empreinte de la région (clé, chunks, briques, dans l'ordre des clés).
    pub fn fingerprint(&self, h: &mut Fnv64) {
        for v in [self.key.x, self.key.y, self.key.z] {
            h.add(&v.to_le_bytes());
        }
        h.add(&(self.chunks.len() as u64).to_le_bytes());
        for (k, edits) in &self.chunks {
            for v in [k.x, k.y, k.z] {
                h.add(&v.to_le_bytes());
            }
            h.add(&(edits.len() as u64).to_le_bytes());
            for (b, brick) in edits.iter() {
                h.add(&b.to_le_bytes());
                brick.fingerprint(h);
            }
        }
    }

    pub(crate) fn insert_brick(&mut self, chunk: ChunkKey, b: u16, brick: Brick) {
        self.chunks.entry(chunk).or_default().insert(b, brick);
    }

    pub(crate) fn remove_brick(&mut self, chunk: ChunkKey, b: u16) {
        if let Some(e) = self.chunks.get_mut(&chunk) {
            e.remove(b);
            if e.is_empty() {
                self.chunks.remove(&chunk);
            }
        }
    }

    pub(crate) fn clear_chunk(&mut self, chunk: ChunkKey) {
        self.chunks.remove(&chunk);
    }
}
