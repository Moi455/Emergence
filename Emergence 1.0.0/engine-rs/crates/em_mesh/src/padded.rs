//! `PaddedChunk` : un chunk 64³ et sa bordure d'UN voxel (66³), lue dans les 26 chunks voisins. Le mailleur ne lit
//! que ce tableau dense : visibilité des faces et occlusion ambiante restent exactes aux bords du chunk.
//!
//! Un voisin absent (chunk non chargé, bord du monde) est traité comme PLEIN et opaque : aucune face n'est dessinée
//! contre un trou, aucune face de dessous n'apparaît au bord d'une région.

use em_core::{ChunkKey, VoxelValue, brick_index, voxel_index};
use em_voxel::{BRICK_VOLUME, Chunk, ChunkClass};

/// Arête du tableau avec sa bordure.
pub const PADDED_EDGE: usize = 66;
/// Voxels du tableau.
const VOLUME: usize = PADDED_EDGE * PADDED_EDGE * PADDED_EDGE;
/// Valeur d'un voisin absent : non nulle donc « solide ».
const ABSENT: u16 = 0xFFFF;

/// Valeur unique d'un chunk uniforme (l'air compris), `None` s'il est mélangé.
fn uniforme(chunk: &Chunk) -> Option<VoxelValue> {
    match chunk.classify() {
        ChunkClass::Air => Some(VoxelValue::AIR),
        ChunkClass::Uniform(v) => Some(v),
        ChunkClass::Mixed => None,
    }
}

/// Chunk et sa bordure, en valeurs brutes de 16 bits. Indice `(x+1) + 66 (z+1) + 66² (y+1)`, `x, y, z` dans -1..=64.
pub struct PaddedChunk {
    cells: Vec<u16>,
    non_air: u32,
}

impl PaddedChunk {
    /// Pas selon x, y, z dans le tableau.
    pub const STRIDE: [isize; 3] = [1, (PADDED_EDGE * PADDED_EDGE) as isize, PADDED_EDGE as isize];

    /// Indice du voxel `(x, y, z)` (chacun dans -1..=64).
    pub const fn index(x: i32, y: i32, z: i32) -> usize {
        (x + 1) as usize + PADDED_EDGE * (z + 1) as usize + PADDED_EDGE * PADDED_EDGE * (y + 1) as usize
    }

    /// Rassemble le chunk `key` et sa bordure ; `lookup` rend un chunk voisin, `None` s'il est absent. Le chunk du
    /// milieu doit exister (sinon tout est « absent »).
    pub fn gather<'c>(key: ChunkKey, lookup: &dyn Fn(ChunkKey) -> Option<&'c Chunk>) -> Self {
        let mut cells = vec![ABSENT; VOLUME];
        let mut non_air = 0_u32;
        for dy in -1..=1_i32 {
            for dz in -1..=1_i32 {
                for dx in -1..=1_i32 {
                    let voisin = ChunkKey::new(key.x + dx, key.y + dy, key.z + dz);
                    let Some(chunk) = lookup(voisin) else { continue };
                    let centre = dx == 0 && dy == 0 && dz == 0;
                    if centre {
                        non_air = chunk.non_air_count();
                    }
                    Self::copier(&mut cells, chunk, [dx, dy, dz]);
                }
            }
        }
        Self { cells, non_air }
    }

    /// Copie dans `cells` la partie du chunk voisin `d` (décalage en chunks) qui touche la zone 66³.
    fn copier(cells: &mut [u16], chunk: &Chunk, d: [i32; 3]) {
        // plage locale à copier sur chaque axe : tout le chunk au centre, le voxel de bord 63 (ou 0) sinon
        let plage = |d: i32| -> (i32, i32) {
            match d {
                0 => (0, 63),
                -1 => (63, 63),
                _ => (0, 0),
            }
        };
        let ((x0, x1), (y0, y1), (z0, z1)) = (plage(d[0]), plage(d[1]), plage(d[2]));
        if let Some(v) = uniforme(chunk) {
            // chunk uniforme : un remplissage de plage, sans lire les briques
            let raw = v.raw();
            for y in y0..=y1 {
                for z in z0..=z1 {
                    let i0 = Self::index(x0 + 64 * d[0], y + 64 * d[1], z + 64 * d[2]);
                    cells[i0..i0 + (x1 - x0 + 1) as usize].fill(raw);
                }
            }
            return;
        }
        if d == [0, 0, 0] {
            // chunk du milieu : copie par briques (une brique dense de 8³ puis ses lignes de 8 voxels)
            let mut dense = [VoxelValue::AIR; BRICK_VOLUME];
            for by in 0..8_u32 {
                for bz in 0..8_u32 {
                    for bx in 0..8_u32 {
                        let brique = chunk.brick(brick_index(bx, by, bz));
                        match brique.is_uniform() {
                            Some(v) => dense.fill(v),
                            None => brique.to_dense(&mut dense),
                        }
                        for ly in 0..8_u32 {
                            for lz in 0..8_u32 {
                                let src = usize::from(voxel_index(0, ly, lz));
                                let dst =
                                    Self::index((bx * 8) as i32, (by * 8 + ly) as i32, (bz * 8 + lz) as i32);
                                for lx in 0..8 {
                                    cells[dst + lx] = dense[src + lx].raw();
                                }
                            }
                        }
                    }
                }
            }
            return;
        }
        // voisins : seulement la couche de bord (une face, une arête ou un coin)
        for y in y0..=y1 {
            for z in z0..=z1 {
                let i0 = Self::index(x0 + 64 * d[0], y + 64 * d[1], z + 64 * d[2]);
                for x in x0..=x1 {
                    cells[i0 + (x - x0) as usize] = chunk.get(x as u32, y as u32, z as u32).raw();
                }
            }
        }
    }

    /// Occupation des rangées : pour chaque rangée `(y, z)` (indice `(y + 1) 66 + (z + 1)`), un mot de 128 bits dont le
    /// bit `x + 1` dit si le voxel `(x, y, z)` est solide (x dans -1..=64).
    pub fn occupancy_rows(&self) -> Vec<u128> {
        let mut rangees = vec![0_u128; PADDED_EDGE * PADDED_EDGE];
        for (r, ligne) in self.cells.as_chunks::<PADDED_EDGE>().0.iter().enumerate() {
            // la rangée `r` du tableau est `z + 66 y` (x le plus rapide) : même ordre que `rangees`
            let mut mot = 0_u128;
            for (x, brut) in ligne.iter().enumerate() {
                mot |= u128::from(Self::is_solid(*brut)) << x;
            }
            rangees[r] = mot;
        }
        rangees
    }

    /// Valeur brute du voxel `(x, y, z)` (chacun dans -1..=64).
    pub fn raw(&self, x: i32, y: i32, z: i32) -> u16 {
        self.cells[Self::index(x, y, z)]
    }

    /// Valeur brute à l'indice du tableau.
    pub(crate) fn raw_at(&self, i: usize) -> u16 {
        self.cells[i]
    }

    /// Voxel `(x, y, z)` du chunk lui-même (0..64) ; `None` pour une valeur « absent » de la bordure.
    pub fn voxel(&self, x: i32, y: i32, z: i32) -> VoxelValue {
        VoxelValue::from_raw(self.raw(x, y, z))
    }

    /// Vrai si le voxel est solide (classe non nulle) : l'air et lui seul laisse passer la lumière.
    pub fn solid(&self, x: i32, y: i32, z: i32) -> bool {
        Self::is_solid(self.raw(x, y, z))
    }

    /// Une valeur brute est-elle solide ?
    pub const fn is_solid(raw: u16) -> bool {
        raw >> 7 != 0
    }

    /// Nombre de voxels non vides dans le chunk lui-même.
    pub fn non_air_count(&self) -> u32 {
        self.non_air
    }
}
