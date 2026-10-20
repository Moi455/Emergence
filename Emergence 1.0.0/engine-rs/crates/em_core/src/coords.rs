//! Coordonnées, clés et constantes du monde (docs/19 § 3.1).
//!
//! Repère monde : x est, y haut, z nord. Ordre dense dans une brique et un chunk : x le plus rapide,
//! puis z, puis y. Les divisions des négatifs arrondissent vers moins l'infini (le sous-sol est en y < 0).

/// Taille d'un voxel en millimètres.
pub const VOXEL_MM: i64 = 50;
/// Arête d'un chunk, en voxels (64 : 3,2 m).
pub const CHUNK_EDGE: i32 = 64;
/// Arête d'une brique, en voxels (8 : 40 cm).
pub const BRICK_EDGE: i32 = 8;
/// Largeur d'une région en chunks, sur x et z.
pub const REGION_CHUNKS_XZ: i32 = 32;
/// Hauteur d'une région en chunks, sur y.
pub const REGION_CHUNKS_Y: i32 = 16;
/// Côté du monde, en voxels.
pub const WORLD_SIZE_VOXELS: i32 = 400_000;
/// Voxel le plus bas du monde (-500 m).
pub const WORLD_BOTTOM_VOXEL: i32 = -10_000;
/// Voxel le plus haut du monde (3,5 km).
pub const WORLD_TOP_VOXEL: i32 = 70_000;
/// Niveau de détail : un voxel du niveau `k` mesure `2^k` voxels de base.
pub type Lod = u8;

/// Division entière arrondie vers moins l'infini (`floor_div` du C++). Panique si `b == 0`.
pub const fn floor_div(a: i64, b: i64) -> i64 {
    let q = a / b;
    if a % b != 0 && ((a < 0) != (b < 0)) {
        q - 1
    } else {
        q
    }
}

/// Voxel dans le monde, en voxels du niveau.
#[derive(Copy, Clone, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct VoxelCoord {
    pub x: i32,
    pub y: i32,
    pub z: i32,
}

impl VoxelCoord {
    /// Construit une coordonnée.
    pub const fn new(x: i32, y: i32, z: i32) -> Self {
        Self { x, y, z }
    }
    /// Chunk qui contient ce voxel.
    pub const fn chunk(self) -> ChunkKey {
        chunk_of(self)
    }
    /// Position du voxel dans son chunk, chaque axe dans 0..64.
    pub const fn local_in_chunk(self) -> [u32; 3] {
        [
            (self.x & (CHUNK_EDGE - 1)) as u32,
            (self.y & (CHUNK_EDGE - 1)) as u32,
            (self.z & (CHUNK_EDGE - 1)) as u32,
        ]
    }
}

/// Clé d'un chunk : coordonnée du voxel décalée de 6 bits, au même niveau.
#[derive(Copy, Clone, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct ChunkKey {
    pub x: i32,
    pub y: i32,
    pub z: i32,
}

impl ChunkKey {
    /// Construit une clé de chunk.
    pub const fn new(x: i32, y: i32, z: i32) -> Self {
        Self { x, y, z }
    }
    /// Voxel de plus petite coordonnée de ce chunk.
    pub const fn origin(self) -> VoxelCoord {
        VoxelCoord::new(self.x * CHUNK_EDGE, self.y * CHUNK_EDGE, self.z * CHUNK_EDGE)
    }
    /// Région qui contient ce chunk.
    pub const fn region(self) -> RegionKey {
        region_of(self)
    }
}

/// Clé d'une région (32 × 16 × 32 chunks).
#[derive(Copy, Clone, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct RegionKey {
    pub x: i32,
    pub y: i32,
    pub z: i32,
}

impl RegionKey {
    /// Construit une clé de région.
    pub const fn new(x: i32, y: i32, z: i32) -> Self {
        Self { x, y, z }
    }
}

/// Boîte de voxels demi-ouverte `[min, max)`. Invariant : `min <= max` sur chaque axe.
#[derive(Copy, Clone, Debug, PartialEq, Eq, Hash)]
pub struct VoxelBox {
    min: VoxelCoord,
    max: VoxelCoord,
}

impl VoxelBox {
    /// Construit une boîte ; échoue si `min` dépasse `max` sur un axe.
    pub fn new(min: VoxelCoord, max: VoxelCoord) -> Result<Self, crate::CoreError> {
        let (a, b) = ([min.x, min.y, min.z], [max.x, max.y, max.z]);
        for axe in 0..3 {
            if a[axe] > b[axe] {
                return Err(crate::CoreError::BoiteInvalide { axe });
            }
        }
        Ok(Self { min, max })
    }
    /// Coin minimal (inclus).
    pub const fn min(&self) -> VoxelCoord {
        self.min
    }
    /// Coin maximal (exclu).
    pub const fn max(&self) -> VoxelCoord {
        self.max
    }
    /// Vrai si la boîte ne contient aucun voxel.
    pub const fn is_empty(&self) -> bool {
        self.min.x == self.max.x || self.min.y == self.max.y || self.min.z == self.max.z
    }
    /// Vrai si le voxel est dans la boîte.
    pub const fn contains(&self, v: VoxelCoord) -> bool {
        v.x >= self.min.x
            && v.x < self.max.x
            && v.y >= self.min.y
            && v.y < self.max.y
            && v.z >= self.min.z
            && v.z < self.max.z
    }
    /// Étendue sur chaque axe, en voxels.
    pub const fn size(&self) -> [i64; 3] {
        [
            self.max.x as i64 - self.min.x as i64,
            self.max.y as i64 - self.min.y as i64,
            self.max.z as i64 - self.min.z as i64,
        ]
    }
}

/// Chunk qui contient le voxel (décalage arithmétique : correct pour les négatifs).
pub const fn chunk_of(v: VoxelCoord) -> ChunkKey {
    ChunkKey::new(v.x >> 6, v.y >> 6, v.z >> 6)
}

/// Région qui contient le chunk (division vers moins l'infini).
pub const fn region_of(c: ChunkKey) -> RegionKey {
    RegionKey::new(
        floor_div(c.x as i64, REGION_CHUNKS_XZ as i64) as i32,
        floor_div(c.y as i64, REGION_CHUNKS_Y as i64) as i32,
        floor_div(c.z as i64, REGION_CHUNKS_XZ as i64) as i32,
    )
}

/// Indice d'un voxel dans sa brique 8³ : `x + 8z + 64y`. Panique si une coordonnée dépasse 7.
pub const fn voxel_index(x: u32, y: u32, z: u32) -> u16 {
    assert!(
        x < 8 && y < 8 && z < 8,
        "coordonnée de voxel hors de la brique 8³"
    );
    (x + 8 * z + 64 * y) as u16
}

/// Indice d'une brique dans son chunk (8³ briques) : `bx + 8bz + 64by`. Panique si une coordonnée dépasse 7.
pub const fn brick_index(bx: u32, by: u32, bz: u32) -> u16 {
    assert!(
        bx < 8 && by < 8 && bz < 8,
        "coordonnée de brique hors du chunk 8³"
    );
    (bx + 8 * bz + 64 * by) as u16
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn negatifs_vers_moins_l_infini() {
        assert_eq!(floor_div(-1, 64), -1);
        assert_eq!(floor_div(-64, 64), -1);
        assert_eq!(floor_div(-65, 64), -2);
        assert_eq!(chunk_of(VoxelCoord::new(-1, -64, -65)), ChunkKey::new(-1, -1, -2));
        assert_eq!(region_of(ChunkKey::new(-1, 16, 31)), RegionKey::new(-1, 1, 0));
        assert_eq!(VoxelCoord::new(-1, 0, 65).local_in_chunk(), [63, 0, 1]);
    }

    #[test]
    fn boite_et_indices() {
        let a = VoxelCoord::new(0, 0, 0);
        let b = VoxelCoord::new(2, 2, 2);
        let bx = VoxelBox::new(a, b).unwrap();
        assert!(bx.contains(VoxelCoord::new(1, 1, 1)) && !bx.contains(b));
        assert!(VoxelBox::new(b, a).is_err());
        assert_eq!(voxel_index(7, 7, 7), 511);
        assert_eq!(voxel_index(1, 0, 1), 9);
        assert_eq!(brick_index(0, 1, 0), 64);
    }
}
