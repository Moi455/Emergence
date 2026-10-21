//! `WorldMesher` : maille une région depuis une `VoxelSource`. Chaque chunk nécessaire (les chunks demandés et leurs
//! 26 voisins) est rempli UNE seule fois puis partagé en lecture ; le maillage des chunks se fait en parallèle
//! (rayon), le résultat est rangé dans l'ordre des clés : identique quel que soit le nombre de fils.

use crate::appearance::VoxelColorer;
use crate::mesh::ChunkMesh;
use crate::mesher::{ChunkMesher, MesherConfig};
use crate::padded::PaddedChunk;
use em_core::{ChunkKey, Lod};
use em_voxel::{Chunk, ChunkHint, VoxelSource};
use rayon::prelude::*;
use std::collections::BTreeMap;

/// Mailleur de région.
pub struct WorldMesher<'a> {
    source: &'a dyn VoxelSource,
    colorer: &'a dyn VoxelColorer,
    lod: Lod,
    config: MesherConfig,
}

impl<'a> WorldMesher<'a> {
    /// Crée le mailleur d'une source, à un niveau de détail.
    pub fn new(
        source: &'a dyn VoxelSource,
        colorer: &'a dyn VoxelColorer,
        lod: Lod,
        config: MesherConfig,
    ) -> Self {
        Self {
            source,
            colorer,
            lod,
            config,
        }
    }

    fn remplir(&self, key: ChunkKey) -> Chunk {
        match self.source.classify(key, self.lod) {
            ChunkHint::Air => Chunk::new_air(),
            ChunkHint::Solid(v) => Chunk::uniform(v),
            ChunkHint::Unknown => {
                let mut c = Chunk::new_air();
                self.source.fill_chunk(key, self.lod, &mut c);
                c
            }
        }
    }

    /// Remplit (en parallèle, une fois chacun) les chunks de `cles` et leurs voisins.
    pub fn charger(&self, cles: &[ChunkKey]) -> BTreeMap<ChunkKey, Chunk> {
        let mut besoin = std::collections::BTreeSet::new();
        for k in cles {
            for dy in -1..=1 {
                for dz in -1..=1 {
                    for dx in -1..=1 {
                        besoin.insert(ChunkKey::new(k.x + dx, k.y + dy, k.z + dz));
                    }
                }
            }
        }
        let liste: Vec<ChunkKey> = besoin.into_iter().collect();
        liste
            .par_iter()
            .map(|k| (*k, self.remplir(*k)))
            .collect::<Vec<_>>()
            .into_iter()
            .collect()
    }

    /// Maille les chunks `cles` (dans l'ordre donné) à partir de chunks déjà chargés ; les maillages vides sont omis.
    pub fn mailler(&self, cles: &[ChunkKey], chunks: &BTreeMap<ChunkKey, Chunk>) -> Vec<ChunkMesh> {
        let mailleur = ChunkMesher::new(self.colorer, self.config);
        let cherche = |k: ChunkKey| chunks.get(&k);
        cles.par_iter()
            .map(|k| mailleur.mesh(*k, self.lod, &PaddedChunk::gather(*k, &cherche)))
            .collect::<Vec<_>>()
            .into_iter()
            .filter(|m| !m.is_empty())
            .collect()
    }

    /// Charge puis maille : le cas courant.
    pub fn mesh_chunks(&self, cles: &[ChunkKey]) -> Vec<ChunkMesh> {
        let chunks = self.charger(cles);
        self.mailler(cles, &chunks)
    }
}
