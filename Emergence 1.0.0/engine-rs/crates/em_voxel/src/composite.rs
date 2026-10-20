//! `CompositeSource` : des couches de sources empilées dans un ordre fixe (docs/19 § 3.2).

use std::sync::Arc;

use em_core::{ChunkKey, Lod, VoxelValue, hash_combine};

use crate::brick::{BRICK_VOLUME, Brick};
use crate::chunk::{CHUNK_BRICKS, Chunk, ChunkHint};
use crate::error::CompositeError;
use crate::source::VoxelSource;

/// Façon dont une couche se pose sur celles du dessous.
#[derive(Copy, Clone, Debug, PartialEq, Eq)]
pub enum CompositeMode {
    /// Les voxels non nuls de la couche remplacent ceux du dessous ; son air laisse voir le dessous.
    Overlay,
    /// Toute brique de la couche qui n'est pas de l'air pur remplace la brique du dessous
    /// (les briques réécrites d'un delta de région) ; une brique d'air pur laisse voir le dessous.
    ReplaceBricks,
}

/// Une couche : une source et son mode de pose.
#[derive(Clone)]
pub struct CompositeLayer {
    source: Arc<dyn VoxelSource>,
    mode: CompositeMode,
}

impl CompositeLayer {
    /// Couche faite de `source` posée selon `mode`.
    pub fn new(source: Arc<dyn VoxelSource>, mode: CompositeMode) -> Self {
        Self { source, mode }
    }
}

/// Composition de couches : la première est le fond (son mode est sans effet), les suivantes se posent dans l'ordre.
pub struct CompositeSource {
    layers: Vec<CompositeLayer>,
}

impl CompositeSource {
    /// Compose des couches ; exige au moins une couche.
    pub fn new(layers: Vec<CompositeLayer>) -> Result<Self, CompositeError> {
        if layers.is_empty() {
            return Err(CompositeError::AucuneCouche);
        }
        Ok(Self { layers })
    }

    /// Nombre de couches.
    pub fn layer_count(&self) -> usize {
        self.layers.len()
    }

    /// Pose la brique `dessus` sur `dessous` selon le mode.
    fn poser(mode: CompositeMode, dessous: &Brick, dessus: &Brick) -> Option<Brick> {
        if dessus.is_air() {
            return None;
        }
        match mode {
            CompositeMode::ReplaceBricks => Some(dessus.clone()),
            CompositeMode::Overlay => {
                if dessous.is_air() {
                    return Some(dessus.clone());
                }
                if dessus.is_uniform().is_some_and(|v| !v.is_air()) {
                    return Some(dessus.clone());
                }
                let mut bas = [VoxelValue::AIR; BRICK_VOLUME];
                let mut haut = [VoxelValue::AIR; BRICK_VOLUME];
                dessous.to_dense(&mut bas);
                dessus.to_dense(&mut haut);
                for (b, h) in bas.iter_mut().zip(haut.iter()) {
                    if !h.is_air() {
                        *b = *h;
                    }
                }
                Some(Brick::from_dense(&bas))
            }
        }
    }
}

impl VoxelSource for CompositeSource {
    fn fill_chunk(&self, key: ChunkKey, lod: Lod, out: &mut Chunk) {
        self.layers[0].source.fill_chunk(key, lod, out);
        let mut calque = Chunk::new_air();
        for couche in &self.layers[1..] {
            if couche.source.classify(key, lod) == ChunkHint::Air {
                continue;
            }
            couche.source.fill_chunk(key, lod, &mut calque);
            for b in 0..CHUNK_BRICKS as u16 {
                if let Some(nouvelle) = Self::poser(couche.mode, out.brick(b), calque.brick(b)) {
                    out.set_brick(b, nouvelle);
                }
            }
        }
        out.compact();
    }

    fn classify(&self, key: ChunkKey, lod: Lod) -> ChunkHint {
        if self
            .layers
            .iter()
            .all(|c| c.source.classify(key, lod) == ChunkHint::Air)
        {
            ChunkHint::Air
        } else {
            ChunkHint::Unknown
        }
    }

    fn version_tag(&self) -> u64 {
        self.layers.iter().fold(0xC0A0_5171, |h, c| {
            hash_combine(hash_combine(h, c.source.version_tag()), c.mode as u64)
        })
    }
}
