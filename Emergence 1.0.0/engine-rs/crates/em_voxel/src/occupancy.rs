//! Colonnes d'occupation d'un chunk : 64 × 64 colonnes de 64 bits, pour la peau et le GPU.

use crate::brick::Brick;
use crate::chunk::Chunk;
use em_core::brick_index;

/// Occupation d'un chunk : le bit `y` de la colonne `(x, z)` est 1 si le voxel n'est pas de l'air.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct OccupancyColumns {
    /// 4 096 colonnes, indice `x + 64z`.
    colonnes: Box<[u64]>,
}

impl OccupancyColumns {
    /// Calcule les colonnes d'un chunk.
    pub fn from_chunk(chunk: &Chunk) -> Self {
        let mut colonnes = vec![0_u64; 64 * 64].into_boxed_slice();
        for by in 0..8_u32 {
            for bz in 0..8_u32 {
                for bx in 0..8_u32 {
                    let brique: &Brick = chunk.brick(brick_index(bx, by, bz));
                    if brique.is_air() {
                        continue;
                    }
                    let occ = brique.occupancy();
                    for lz in 0..8_u32 {
                        for lx in 0..8_u32 {
                            let mut octet = 0_u64;
                            for (ly, mot) in occ.iter().enumerate() {
                                octet |= ((mot >> (lx + 8 * lz)) & 1) << ly;
                            }
                            colonnes[((bz * 8 + lz) * 64 + bx * 8 + lx) as usize] |= octet << (by * 8);
                        }
                    }
                }
            }
        }
        Self { colonnes }
    }

    /// Colonne `(x, z)`, chaque coordonnée dans 0..64. Panique au-delà.
    pub fn column(&self, x: u32, z: u32) -> u64 {
        assert!(x < 64 && z < 64, "colonne hors du chunk 64³");
        self.colonnes[(x + 64 * z) as usize]
    }

    /// Vrai si le voxel n'est pas de l'air.
    pub fn is_solid(&self, x: u32, y: u32, z: u32) -> bool {
        assert!(y < 64, "hauteur hors du chunk 64³");
        (self.column(x, z) >> y) & 1 == 1
    }

    /// Les 4 096 colonnes, indice `x + 64z` (pour un envoi au GPU).
    pub fn as_slice(&self) -> &[u64] {
        &self.colonnes
    }

    /// Nombre de voxels qui ne sont pas de l'air.
    pub fn solid_count(&self) -> u32 {
        self.colonnes.iter().map(|c| c.count_ones()).sum()
    }
}
