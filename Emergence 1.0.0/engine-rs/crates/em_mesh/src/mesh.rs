//! `ChunkMesh` : le résultat du maillage d'un chunk, la liste de ses quads et quelques mesures.

use crate::quad::Quad;
use em_core::{ChunkKey, Fnv64, Lod};

/// Maillage d'un chunk. Champs privés : les quads sortent du mailleur dans un ordre canonique (face, tranche,
/// ligne, colonne), identique à chaque exécution.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ChunkMesh {
    key: ChunkKey,
    lod: Lod,
    quads: Vec<Quad>,
    faces: u32,
    bounds: [[u8; 3]; 2],
}

impl ChunkMesh {
    /// Maillage vide d'un chunk.
    pub fn empty(key: ChunkKey, lod: Lod) -> Self {
        Self {
            key,
            lod,
            quads: Vec::new(),
            faces: 0,
            bounds: [[0; 3]; 2],
        }
    }

    pub(crate) fn from_quads(key: ChunkKey, lod: Lod, quads: Vec<Quad>, faces: u32) -> Self {
        let mut bounds = [[u8::MAX; 3], [0; 3]];
        for q in &quads {
            for k in [0, 2] {
                let p = q.corner(k);
                for a in 0..3 {
                    bounds[0][a] = bounds[0][a].min(p[a]);
                    bounds[1][a] = bounds[1][a].max(p[a]);
                }
            }
        }
        if quads.is_empty() {
            bounds = [[0; 3]; 2];
        }
        Self {
            key,
            lod,
            quads,
            faces,
            bounds,
        }
    }

    /// Clé du chunk maillé.
    pub fn key(&self) -> ChunkKey {
        self.key
    }

    /// Niveau de détail.
    pub fn lod(&self) -> Lod {
        self.lod
    }

    /// Les quads, dans l'ordre canonique.
    pub fn quads(&self) -> &[Quad] {
        &self.quads
    }

    /// Les quads, modifiables (cuisson de l'épaisseur du feuillage).
    pub fn quads_mut(&mut self) -> &mut [Quad] {
        &mut self.quads
    }

    /// Nombre de quads.
    pub fn quad_count(&self) -> usize {
        self.quads.len()
    }

    /// Nombre de sommets logiques (4 par quad).
    pub fn vertex_count(&self) -> usize {
        4 * self.quads.len()
    }

    /// Nombre de faces de voxel visibles avant fusion.
    pub fn face_count(&self) -> u32 {
        self.faces
    }

    /// Vrai s'il n'y a aucune face.
    pub fn is_empty(&self) -> bool {
        self.quads.is_empty()
    }

    /// Boîte englobante locale `[min, max]` en voxels (les coins des quads).
    pub fn bounds(&self) -> [[u8; 3]; 2] {
        self.bounds
    }

    /// Octets des quads, tels que le GPU les lit.
    pub fn as_bytes(&self) -> &[u8] {
        bytemuck::cast_slice(&self.quads)
    }

    /// Mémoire des quads en octets.
    pub fn bytes(&self) -> usize {
        self.quads.len() * Quad::BYTES
    }

    /// Empreinte FNV-1a du contenu (clé, niveau, octets des quads) : égale d'une exécution à l'autre.
    pub fn fingerprint(&self) -> u64 {
        let mut h = Fnv64::new();
        for v in [self.key.x, self.key.y, self.key.z] {
            h.add(&v.to_le_bytes());
        }
        h.add(&[self.lod]);
        h.add(self.as_bytes());
        h.value()
    }
}
