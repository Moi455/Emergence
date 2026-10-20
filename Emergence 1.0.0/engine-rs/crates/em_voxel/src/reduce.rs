//! Réduction d'un niveau vers le suivant : 8 chunks enfants deviennent un chunk parent (règle 4/8 et classe majoritaire).

use em_core::{MaterialId, VoxelValue, brick_index};

use crate::brick::{BRICK_VOLUME, Brick};
use crate::chunk::Chunk;

/// Règle de réduction de 2×2×2 voxels en un.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum ReduceRule {
    /// Plein si au moins 4 voxels sur 8 ne sont pas de l'air ; matière la plus nombreuse parmi eux,
    /// à égalité la première de `priority`, puis la plus petite classe ; teinte du premier voxel
    /// (ordre x, z, y) de cette matière.
    Majority4of8 {
        /// Matières par priorité décroissante (celles qui manquent passent après).
        priority: Vec<MaterialId>,
    },
}

impl ReduceRule {
    /// Règle 4/8 avec une priorité sans doublon ; renvoie `None` si une matière est répétée.
    pub fn majority_4_of_8(priority: Vec<MaterialId>) -> Option<Self> {
        let mut tri = priority.clone();
        tri.sort_unstable();
        tri.dedup();
        (tri.len() == priority.len()).then_some(Self::Majority4of8 { priority })
    }

    /// Réduit 8 voxels (ordre x, puis z, puis y) en un.
    pub fn reduce8(&self, voxels: [VoxelValue; 8]) -> VoxelValue {
        match self {
            Self::Majority4of8 { priority } => {
                if voxels.iter().filter(|v| !v.is_air()).count() < 4 {
                    return VoxelValue::AIR;
                }
                // (matière, effectif, premier voxel rencontré)
                let mut bilan: [(MaterialId, u8, VoxelValue); 8] = [(MaterialId::AIR, 0, VoxelValue::AIR); 8];
                let mut n = 0;
                for v in voxels.iter().filter(|v| !v.is_air()) {
                    match bilan[..n].iter_mut().find(|e| e.0 == v.material()) {
                        Some(e) => e.1 += 1,
                        None => {
                            bilan[n] = (v.material(), 1, *v);
                            n += 1;
                        }
                    }
                }
                let rang = |m: MaterialId| priority.iter().position(|p| *p == m).unwrap_or(usize::MAX);
                bilan[..n]
                    .iter()
                    .min_by_key(|e| (std::cmp::Reverse(e.1), rang(e.0), e.0))
                    .map_or(VoxelValue::AIR, |e| e.2)
            }
        }
    }
}

/// Réduit 8 chunks enfants en un chunk parent. Enfant `i` = `cx + 2cz + 4cy` : il occupe l'octant
/// `(cx, cy, cz)` du parent, chaque voxel parent résumant 2×2×2 voxels enfants.
pub fn reduce_2x(children: [&Chunk; 8], rule: &ReduceRule, out: &mut Chunk) {
    *out = Chunk::new_air();
    let mut sources = vec![[VoxelValue::AIR; BRICK_VOLUME]; 8];
    let mut brique = [VoxelValue::AIR; BRICK_VOLUME];
    for cy in 0..2_u32 {
        for cz in 0..2_u32 {
            for cx in 0..2_u32 {
                let enfant = children[(cx + 2 * cz + 4 * cy) as usize];
                for oby in 0..4_u32 {
                    for obz in 0..4_u32 {
                        for obx in 0..4_u32 {
                            let bricks: [&Brick; 8] = std::array::from_fn(|k| {
                                let (sx, sz, sy) = (k as u32 & 1, (k as u32 >> 1) & 1, k as u32 >> 2);
                                enfant.brick(brick_index(2 * obx + sx, 2 * oby + sy, 2 * obz + sz))
                            });
                            let cible = brick_index(cx * 4 + obx, cy * 4 + oby, cz * 4 + obz);
                            // Chemin rapide : huit briques uniformes égales (le 2×2×2 réduit à la même valeur).
                            if let Some(v) = bricks[0].is_uniform()
                                && bricks.iter().all(|b| b.is_uniform() == Some(v))
                            {
                                out.set_brick(cible, Brick::uniform(rule.reduce8([v; 8])));
                                continue;
                            }
                            for (k, b) in bricks.iter().enumerate() {
                                b.to_dense(&mut sources[k]);
                            }
                            for ly in 0..8_usize {
                                for lz in 0..8_usize {
                                    for lx in 0..8_usize {
                                        let huit: [VoxelValue; 8] = std::array::from_fn(|k| {
                                            let (dx, dz, dy) = (k & 1, (k >> 1) & 1, k >> 2);
                                            let (px, py, pz) = (2 * lx + dx, 2 * ly + dy, 2 * lz + dz);
                                            let src = (px >> 3) + 2 * (pz >> 3) + 4 * (py >> 3);
                                            sources[src][(px & 7) + 8 * (pz & 7) + 64 * (py & 7)]
                                        });
                                        brique[lx + 8 * lz + 64 * ly] = rule.reduce8(huit);
                                    }
                                }
                            }
                            out.set_brick(cible, Brick::from_dense(&brique));
                        }
                    }
                }
            }
        }
    }
    out.compact();
}
