//! `SparseWorld` : un monde de base recalculable + les briques modifiées seulement (docs/19 § 3.1).
//!
//! Aucune allocation par voxel : une édition réécrit des briques, et une brique redevenue égale à
//! celle du monde de base est retirée. L'état dépend du contenu, jamais de l'ordre des éditions.

use std::collections::BTreeMap;
use std::sync::Arc;

use em_core::{
    ChunkKey, Fnv64, LeReader, LeWriter, Lod, RegionKey, VoxelCoord, VoxelValue, brick_index, hash_combine,
    voxel_index,
};

use crate::brick::Brick;
use crate::chunk::{CHUNK_BRICKS, Chunk, ChunkHint};
use crate::error::DecodeError;
use crate::region::{ChunkEdits, Region};
use crate::source::VoxelSource;
use crate::writer::ChunkWriter;

/// Monde creux : `base` (pure) plus des éditions au niveau 0, rangées par région.
pub struct SparseWorld {
    base: Arc<dyn VoxelSource>,
    regions: BTreeMap<RegionKey, Region>,
}

impl SparseWorld {
    /// Monde sans édition au-dessus de `base`.
    pub fn new(base: Arc<dyn VoxelSource>) -> Self {
        Self {
            base,
            regions: BTreeMap::new(),
        }
    }

    /// Monde de base.
    pub fn base(&self) -> &Arc<dyn VoxelSource> {
        &self.base
    }

    /// Éditions d'un chunk du niveau 0.
    pub fn edits(&self, key: ChunkKey) -> Option<&ChunkEdits> {
        self.regions.get(&key.region())?.chunk(key)
    }

    /// Régions éditées par clé croissante.
    pub fn regions(&self) -> impl Iterator<Item = &Region> + '_ {
        self.regions.values()
    }

    /// Nombre de régions éditées.
    pub fn region_count(&self) -> usize {
        self.regions.len()
    }

    /// Nombre de chunks édités.
    pub fn edited_chunk_count(&self) -> usize {
        self.regions.values().map(Region::chunk_count).sum()
    }

    /// Nombre de briques réécrites.
    pub fn edited_brick_count(&self) -> usize {
        self.regions.values().map(Region::brick_count).sum()
    }

    /// Empreinte FNV-1a des éditions, en ordre canonique des clés : identique quel que soit l'ordre des éditions.
    pub fn fingerprint(&self) -> u64 {
        let mut h = Fnv64::new();
        h.add(&(self.regions.len() as u64).to_le_bytes());
        for r in self.regions.values() {
            r.fingerprint(&mut h);
        }
        h.value()
    }

    /// Chunk du niveau 0 tel que le monde le montre (base + éditions).
    fn chunk_courant(&self, key: ChunkKey, base_chunk: &Chunk) -> Chunk {
        let mut chunk = base_chunk.clone();
        if let Some(e) = self.edits(key) {
            e.apply_to(&mut chunk);
        }
        chunk
    }

    /// Modifie le chunk `key` (niveau 0) par une fonction qui reçoit une fenêtre d'écriture. Ne garde que les
    /// briques qui diffèrent de la base ; retire celles qui lui redeviennent égales. Renvoie le nombre de briques changées.
    pub fn edit_chunk(&mut self, key: ChunkKey, edit: impl FnOnce(&mut ChunkWriter<'_>)) -> usize {
        let mut base_chunk = Chunk::new_air();
        self.base.fill_chunk(key, 0, &mut base_chunk);
        let courant = self.chunk_courant(key, &base_chunk);
        let mut modifie = courant.clone();
        {
            let mut fenetre = ChunkWriter::new(&mut modifie, key);
            edit(&mut fenetre);
        }
        let mut changees = 0;
        for b in 0..CHUNK_BRICKS as u16 {
            let nouvelle = modifie.brick(b);
            if nouvelle == courant.brick(b) {
                continue;
            }
            changees += 1;
            if nouvelle == base_chunk.brick(b) {
                self.retirer(key, b);
            } else {
                self.regions
                    .entry(key.region())
                    .or_insert_with(|| Region::new(key.region()))
                    .insert_brick(key, b, nouvelle.clone());
            }
        }
        changees
    }

    /// Écrit un voxel du niveau 0 (valeur brute, air compris). Pour beaucoup de voxels, utiliser `edit_chunk`.
    pub fn set_voxel(&mut self, at: VoxelCoord, value: VoxelValue) {
        self.edit_chunk(at.chunk(), |w| {
            w.set(at, value);
        });
    }

    /// Voxel du niveau 0 : brique éditée si elle existe, sinon la base.
    pub fn voxel(&self, at: VoxelCoord) -> VoxelValue {
        let key = at.chunk();
        let [x, y, z] = at.local_in_chunk();
        let b = brick_index(x >> 3, y >> 3, z >> 3);
        match self.edits(key).and_then(|e| e.get(b)) {
            Some(brick) => brick.get(voxel_index(x & 7, y & 7, z & 7)),
            None => self.base.voxel_at(at, 0),
        }
    }

    fn retirer(&mut self, key: ChunkKey, b: u16) {
        let rk = key.region();
        if let Some(r) = self.regions.get_mut(&rk) {
            r.remove_brick(key, b);
            if r.is_empty() {
                self.regions.remove(&rk);
            }
        }
    }

    /// Écrit les éditions d'un chunk au format de charge de docs/19a § 2.4 : `u32 n`, puis n × (`u16 brique`, EMBK), triées.
    pub fn encode_chunk_edits(&self, key: ChunkKey, w: &mut LeWriter) {
        match self.edits(key) {
            None => {
                w.u32(0);
            }
            Some(e) => {
                w.u32(e.len() as u32);
                for (b, brick) in e.iter() {
                    w.u16(b);
                    brick.encode(w);
                }
            }
        }
    }

    /// Remplace les éditions du chunk `key` par celles d'une charge `encode_chunk_edits`. Refus fermé si la charge
    /// est invalide (le monde reste inchangé). Les briques égales à la base sont écartées.
    pub fn load_chunk_edits(&mut self, key: ChunkKey, charge: &[u8]) -> Result<(), DecodeError> {
        let mut r = LeReader::new(charge);
        let n = r.u32()?;
        let mut lues: Vec<(u16, Brick)> = Vec::new();
        let mut precedente: Option<u16> = None;
        for _ in 0..n {
            let b = r.u16()?;
            if usize::from(b) >= CHUNK_BRICKS {
                return Err(DecodeError::BriqueInvalide(b));
            }
            if precedente.is_some_and(|p| p >= b) {
                return Err(DecodeError::BriquesDesordonnees);
            }
            precedente = Some(b);
            lues.push((b, Brick::decode(&mut r)?));
        }
        if !r.is_finished() {
            return Err(DecodeError::OctetsEnTrop(r.remaining()));
        }
        let mut base_chunk = Chunk::new_air();
        self.base.fill_chunk(key, 0, &mut base_chunk);
        let rk = key.region();
        if let Some(region) = self.regions.get_mut(&rk) {
            region.clear_chunk(key);
            if region.is_empty() {
                self.regions.remove(&rk);
            }
        }
        for (b, brick) in lues {
            if brick != *base_chunk.brick(b) {
                self.regions
                    .entry(rk)
                    .or_insert_with(|| Region::new(rk))
                    .insert_brick(key, b, brick);
            }
        }
        Ok(())
    }
}

impl VoxelSource for SparseWorld {
    /// Niveau 0 : base puis briques réécrites. Niveaux grossiers : la base seule (la réduction des
    /// briques éditées vers les niveaux grossiers relève de `em_world`, L19).
    fn fill_chunk(&self, key: ChunkKey, lod: Lod, out: &mut Chunk) {
        self.base.fill_chunk(key, lod, out);
        if lod == 0
            && let Some(e) = self.edits(key)
        {
            e.apply_to(out);
            out.compact();
        }
    }

    fn classify(&self, key: ChunkKey, lod: Lod) -> ChunkHint {
        if lod == 0 && self.edits(key).is_some() {
            ChunkHint::Unknown
        } else {
            self.base.classify(key, lod)
        }
    }

    /// Combine la version de la base et l'empreinte des éditions (coût proportionnel au nombre d'éditions).
    fn version_tag(&self) -> u64 {
        hash_combine(self.base.version_tag(), self.fingerprint())
    }
}
