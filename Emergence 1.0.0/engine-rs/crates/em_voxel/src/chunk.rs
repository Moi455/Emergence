//! Chunk 64³ fait de 512 briques 8³, stockage creux (docs/19 § 3.1).
//!
//! Un chunk uniforme (air, roche pleine) n'alloue rien : une seule brique de remplissage. La table
//! des 512 briques n'existe qu'à partir de la première brique qui diffère du remplissage.
//! L'égalité et l'empreinte portent sur le contenu logique, jamais sur la représentation.

use em_core::{Fnv64, LeReader, LeWriter, VoxelValue, brick_index, crc32, voxel_index};

use crate::brick::{BRICK_VOLUME, Brick};
use crate::error::{ChunkError, DecodeError};

/// Nombre de briques d'un chunk.
pub const CHUNK_BRICKS: usize = 512;
/// Nombre de voxels d'un chunk.
pub const CHUNK_VOLUME: usize = 64 * 64 * 64;

/// Signature du format de chunk.
const SIGNATURE: &[u8; 4] = b"EMCK";
/// Version du format de chunk.
const VERSION: u8 = 1;

/// Classement d'un chunk rempli.
#[derive(Copy, Clone, Debug, PartialEq, Eq)]
pub enum ChunkClass {
    /// Que de l'air (valeur exactement `AIR`).
    Air,
    /// Une seule valeur non nulle partout.
    Uniform(VoxelValue),
    /// Plusieurs valeurs.
    Mixed,
}

/// Indication rapide d'une source, sans remplir le chunk.
#[derive(Copy, Clone, Debug, PartialEq, Eq)]
pub enum ChunkHint {
    /// Le chunk est de l'air.
    Air,
    /// Le chunk est plein de cette valeur.
    Solid(VoxelValue),
    /// La source ne sait pas sans le remplir.
    Unknown,
}

/// Chunk 64³ de voxels.
#[derive(Clone, Debug)]
pub struct Chunk {
    /// Contenu des briques absentes de la table.
    fill: Brick,
    /// Table des 512 briques (longueur toujours 512), absente tant que tout est égal au remplissage.
    bricks: Option<Box<[Brick]>>,
}

impl Chunk {
    /// Chunk d'air, sans allocation.
    pub const fn new_air() -> Self {
        Self::uniform(VoxelValue::AIR)
    }

    /// Chunk dont tous les voxels valent `v`, sans allocation.
    pub const fn uniform(v: VoxelValue) -> Self {
        Self {
            fill: Brick::uniform(v),
            bricks: None,
        }
    }

    /// Brique d'indice `b` (`bx + 8bz + 64by`). Panique si `b >= 512`.
    pub fn brick(&self, b: u16) -> &Brick {
        assert!(usize::from(b) < CHUNK_BRICKS, "numéro de brique hors du chunk");
        match &self.bricks {
            Some(table) => &table[usize::from(b)],
            None => &self.fill,
        }
    }

    /// Remplace la brique `b`. Panique si `b >= 512`.
    pub fn set_brick(&mut self, b: u16, brick: Brick) {
        assert!(usize::from(b) < CHUNK_BRICKS, "numéro de brique hors du chunk");
        match &mut self.bricks {
            Some(table) => table[usize::from(b)] = brick,
            None => {
                if brick == self.fill {
                    return;
                }
                let mut table = vec![self.fill.clone(); CHUNK_BRICKS].into_boxed_slice();
                table[usize::from(b)] = brick;
                self.bricks = Some(table);
            }
        }
    }

    /// Voxel de coordonnées locales (chacune dans 0..64). Panique au-delà.
    pub fn get(&self, x: u32, y: u32, z: u32) -> VoxelValue {
        assert!(x < 64 && y < 64 && z < 64, "coordonnée hors du chunk 64³");
        self.brick(brick_index(x >> 3, y >> 3, z >> 3))
            .get(voxel_index(x & 7, y & 7, z & 7))
    }

    /// Écrit un voxel (relit et recompose la brique : pour des écritures en masse, passer par `ChunkWriter`).
    pub fn set(&mut self, x: u32, y: u32, z: u32, v: VoxelValue) {
        assert!(x < 64 && y < 64 && z < 64, "coordonnée hors du chunk 64³");
        let b = brick_index(x >> 3, y >> 3, z >> 3);
        let nouvelle = self.brick(b).with_voxel(voxel_index(x & 7, y & 7, z & 7), v);
        self.set_brick(b, nouvelle);
    }

    /// Les 512 briques dans l'ordre canonique (`bx + 8bz + 64by`).
    pub fn bricks(&self) -> impl Iterator<Item = &Brick> + '_ {
        (0..CHUNK_BRICKS as u16).map(|b| self.brick(b))
    }

    /// Libère la table de briques si tout est redevenu uniforme et égal ; sans effet sur le contenu logique.
    pub fn compact(&mut self) {
        let remplissage = match &self.bricks {
            Some(table) if table[0].is_uniform().is_some() && table.iter().all(|b| *b == table[0]) => {
                Some(table[0].clone())
            }
            _ => None,
        };
        if let Some(f) = remplissage {
            self.fill = f;
            self.bricks = None;
        }
    }

    /// Classement du contenu.
    pub fn classify(&self) -> ChunkClass {
        let Some(premier) = self.brick(0).is_uniform() else {
            return ChunkClass::Mixed;
        };
        if let Some(table) = &self.bricks
            && table.iter().any(|b| b.is_uniform() != Some(premier))
        {
            return ChunkClass::Mixed;
        }
        if premier == VoxelValue::AIR {
            ChunkClass::Air
        } else {
            ChunkClass::Uniform(premier)
        }
    }

    /// Nombre de voxels qui ne sont pas de l'air.
    pub fn non_air_count(&self) -> u32 {
        self.bricks().map(Brick::non_air_count).sum()
    }

    /// Nombre de briques non uniformes (donc allouées).
    pub fn palette_brick_count(&self) -> usize {
        self.bricks().filter(|b| b.is_uniform().is_none()).count()
    }

    /// Mémoire occupée en octets, structure comprise [Mesuré par `examples/mesures.rs`].
    pub fn memory_bytes(&self) -> usize {
        let table = self.bricks.as_ref().map_or(0, |t| {
            t.len() * size_of::<Brick>() + t.iter().map(Brick::heap_bytes).sum::<usize>()
        });
        size_of::<Self>() + self.fill.heap_bytes() + table
    }

    /// Ajoute le contenu à une empreinte FNV-1a, brique par brique dans l'ordre canonique.
    pub fn fingerprint(&self, h: &mut Fnv64) {
        for b in self.bricks() {
            b.fingerprint(h);
        }
    }

    /// Empreinte seule du chunk.
    pub fn fingerprint_value(&self) -> u64 {
        let mut h = Fnv64::new();
        self.fingerprint(&mut h);
        h.value()
    }

    /// Construit un chunk d'un tableau dense de 64³ voxels, indice `x + 64z + 4096y`.
    pub fn from_dense(d: &[VoxelValue]) -> Result<Self, ChunkError> {
        if d.len() != CHUNK_VOLUME {
            return Err(ChunkError::TailleDense {
                attendu: CHUNK_VOLUME,
                recu: d.len(),
            });
        }
        let mut chunk = Self::new_air();
        let mut brique = [VoxelValue::AIR; BRICK_VOLUME];
        for by in 0..8_u32 {
            for bz in 0..8_u32 {
                for bx in 0..8_u32 {
                    for ly in 0..8_u32 {
                        for lz in 0..8_u32 {
                            let src = ((by * 8 + ly) * 4096 + (bz * 8 + lz) * 64 + bx * 8) as usize;
                            let dst = usize::from(voxel_index(0, ly, lz));
                            brique[dst..dst + 8].copy_from_slice(&d[src..src + 8]);
                        }
                    }
                    chunk.set_brick(brick_index(bx, by, bz), Brick::from_dense(&brique));
                }
            }
        }
        chunk.compact();
        Ok(chunk)
    }

    /// Tableau dense de 64³ voxels, indice `x + 64z + 4096y`.
    pub fn to_dense(&self) -> Vec<VoxelValue> {
        let mut out = vec![VoxelValue::AIR; CHUNK_VOLUME];
        let mut brique = [VoxelValue::AIR; BRICK_VOLUME];
        for by in 0..8_u32 {
            for bz in 0..8_u32 {
                for bx in 0..8_u32 {
                    self.brick(brick_index(bx, by, bz)).to_dense(&mut brique);
                    for ly in 0..8_u32 {
                        for lz in 0..8_u32 {
                            let dst = ((by * 8 + ly) * 4096 + (bz * 8 + lz) * 64 + bx * 8) as usize;
                            let src = usize::from(voxel_index(0, ly, lz));
                            out[dst..dst + 8].copy_from_slice(&brique[src..src + 8]);
                        }
                    }
                }
            }
        }
        out
    }

    /// Écrit le chunk : `EMCK`, version, étiquette (0 uniforme, 1 briques), corps, puis CRC-32 de tout ce qui précède.
    pub fn encode(&self, w: &mut LeWriter) {
        let debut = w.len();
        w.bytes(SIGNATURE).u8(VERSION);
        match self.classify() {
            ChunkClass::Air => {
                w.u8(0).u16(VoxelValue::AIR.raw());
            }
            ChunkClass::Uniform(v) => {
                w.u8(0).u16(v.raw());
            }
            ChunkClass::Mixed => {
                w.u8(1);
                for b in self.bricks() {
                    b.encode(w);
                }
            }
        }
        let crc = crc32(&w.as_bytes()[debut..]);
        w.u32(crc);
    }

    /// Lit un chunk écrit par `encode` ; refuse signature, version future, CRC ou octets en trop erronés.
    pub fn decode(octets: &[u8]) -> Result<Self, DecodeError> {
        let mut r = LeReader::new(octets);
        if r.bytes(4)? != SIGNATURE {
            return Err(DecodeError::SignatureInvalide);
        }
        let version = r.u8()?;
        if version > VERSION {
            return Err(DecodeError::VersionFuture(version));
        }
        let etiquette = r.u8()?;
        let chunk = match etiquette {
            0 => Self::uniform(VoxelValue::from_raw(r.u16()?)),
            1 => {
                let mut c = Self::new_air();
                for b in 0..CHUNK_BRICKS as u16 {
                    c.set_brick(b, Brick::decode(&mut r)?);
                }
                c.compact();
                c
            }
            autre => return Err(DecodeError::EtiquetteInconnue(autre)),
        };
        let fin_corps = r.position();
        let attendu = r.u32()?;
        let calcule = crc32(&octets[..fin_corps]);
        if attendu != calcule {
            return Err(DecodeError::CrcInvalide { attendu, calcule });
        }
        if !r.is_finished() {
            return Err(DecodeError::OctetsEnTrop(r.remaining()));
        }
        Ok(chunk)
    }
}

impl Default for Chunk {
    fn default() -> Self {
        Self::new_air()
    }
}

impl PartialEq for Chunk {
    fn eq(&self, autre: &Self) -> bool {
        self.bricks().zip(autre.bricks()).all(|(a, b)| a == b)
    }
}

impl Eq for Chunk {}
