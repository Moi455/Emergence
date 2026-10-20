//! `ClipmapStreamer` : décide QUOI charger dans la clipmap (docs/19 § 4.4). Il lit la `VoxelSource` (sur les fils
//! ouvriers de `rayon`), classe les chunks sans les remplir quand la source le sait, et les confie au
//! `VoxelGpuWorld`, qui possède la mémoire. Le plus proche d'abord, dans la limite d'un budget d'octets par appel.

use super::camera::VoxelCamera;
use super::world::{ChunkFlags, UploadOutcome, VoxelGpuWorld};
use crate::error::WorldError;
use crate::gpu::GpuContext;
use em_core::ChunkKey;
use em_voxel::{Chunk, ChunkHint, VoxelSource};
use rayon::prelude::*;
use std::collections::BTreeSet;

/// Bilan d'un appel à `update`.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub struct StreamReport {
    /// Chunks remplis puis téléversés (ou vérifiés) pendant l'appel.
    pub processed: u32,
    /// Chunks effectivement écrits sur le GPU.
    pub uploaded: u32,
    /// Chunks évincés parce que la fenêtre a glissé.
    pub evicted: u32,
    /// Chunks encore à traiter (le budget d'octets a coupé l'appel).
    pub pending: u32,
    /// Octets écrits pendant l'appel.
    pub bytes: u64,
}

/// Diffuse les chunks d'une source vers le monde GPU, un niveau à la fois.
pub struct ClipmapStreamer {
    /// Budget d'octets par appel (docs/19 § 1.4 : 8 Mo par image).
    budget_octets: u64,
    /// Chunks déjà traités par niveau (y compris les chunks d'air, qui n'ont rien sur le GPU).
    traites: Vec<BTreeSet<ChunkKey>>,
    /// Étiquette de version de la source au dernier passage.
    version: Option<u64>,
}

impl ClipmapStreamer {
    /// Budget par défaut : 8 Mio par image.
    pub const BUDGET_PAR_DEFAUT: u64 = 8 << 20;

    /// Streamer pour `niveaux` niveaux, avec un budget d'octets par appel (au moins 1 chunk par appel).
    pub fn new(niveaux: u8, budget_octets: u64) -> Self {
        Self {
            budget_octets,
            traites: vec![BTreeSet::new(); usize::from(niveaux)],
            version: None,
        }
    }

    /// Marque un chunk comme modifié : il sera relu et retéléversé (seul ce bloc, pas la fenêtre entière).
    pub fn mark_dirty(&mut self, niveau: u8, k: ChunkKey) {
        if let Some(t) = self.traites.get_mut(usize::from(niveau)) {
            t.remove(&k);
        }
    }

    /// Fenêtre centrée sur la caméra : le chunk de la caméra est au milieu (indice 8 sur 16).
    pub fn origine_pour(cam: &VoxelCamera, niveau: u8) -> ChunkKey {
        let v = cam.voxel();
        let c = |x: i32| (x >> (6 + u32::from(niveau))) - 8;
        ChunkKey::new(c(v[0]), c(v[1]), c(v[2]))
    }

    /// Met la clipmap à jour pour la caméra : glisse les fenêtres, évince, charge ce qui manque.
    pub fn update(
        &mut self,
        cam: &VoxelCamera,
        src: &dyn VoxelSource,
        world: &mut VoxelGpuWorld,
        gpu: &GpuContext,
    ) -> Result<StreamReport, WorldError> {
        let mut rapport = StreamReport::default();
        let version = src.version_tag();
        if self.version != Some(version) {
            // La source a changé : tout ce qui est sur le GPU est à revérifier (par empreinte, donc seuls les
            // blocs réellement modifiés sont réécrits) ; les chunks vides sont à reclasser.
            for t in &mut self.traites {
                t.clear();
            }
            self.version = Some(version);
        }
        for niveau in 0..world.config().levels {
            let origine = Self::origine_pour(cam, niveau);
            let avant = world.stats().chunks_pool + world.stats().chunks_uniform;
            world.set_level_origin(gpu, niveau, origine)?;
            let apres = world.stats().chunks_pool + world.stats().chunks_uniform;
            rapport.evicted += avant.saturating_sub(apres);
            let t = &mut self.traites[usize::from(niveau)];
            t.retain(|k| {
                (0..16).contains(&(k.x - origine.x))
                    && (0..16).contains(&(k.y - origine.y))
                    && (0..16).contains(&(k.z - origine.z))
            });
            // Chunks de la fenêtre pas encore traités, du plus proche de la caméra au plus lointain.
            let centre = ChunkKey::new(origine.x + 8, origine.y + 8, origine.z + 8);
            let mut a_faire: Vec<ChunkKey> = Vec::new();
            for y in 0..16 {
                for z in 0..16 {
                    for x in 0..16 {
                        let k = ChunkKey::new(origine.x + x, origine.y + y, origine.z + z);
                        if !t.contains(&k) {
                            a_faire.push(k);
                        }
                    }
                }
            }
            let dist2 = |k: &ChunkKey| {
                let d = [k.x - centre.x, k.y - centre.y, k.z - centre.z];
                d.iter().map(|v| i64::from(*v) * i64::from(*v)).sum::<i64>()
            };
            a_faire.sort_by_key(|k| (dist2(k), *k));
            // Remplissage en parallèle par lots, puis téléversement séquentiel (cases déterministes).
            let lod = niveau;
            let mut restants = a_faire.as_slice();
            while !restants.is_empty() {
                if rapport.bytes >= self.budget_octets && rapport.processed > 0 {
                    break;
                }
                let n = restants.len().min(64);
                let (lot, suite) = restants.split_at(n);
                restants = suite;
                let remplis: Vec<(ChunkKey, ChunkHint, Option<Chunk>)> = lot
                    .par_iter()
                    .map(|k| {
                        let indice = src.classify(*k, lod);
                        match indice {
                            ChunkHint::Air => (*k, indice, None),
                            ChunkHint::Solid(v) => (*k, indice, Some(Chunk::uniform(v))),
                            ChunkHint::Unknown => {
                                let mut c = Chunk::new_air();
                                src.fill_chunk(*k, lod, &mut c);
                                (*k, indice, Some(c))
                            }
                        }
                    })
                    .collect();
                for (k, _indice, chunk) in remplis {
                    rapport.processed += 1;
                    match chunk {
                        None => world.evict_chunk(gpu, niveau, k),
                        Some(c) => {
                            if let UploadOutcome::Uploaded { bytes } =
                                world.upload_chunk(gpu, niveau, k, &c, ChunkFlags::sans_peau())?
                            {
                                rapport.uploaded += 1;
                                rapport.bytes += bytes;
                            }
                        }
                    }
                    t.insert(k);
                }
            }
            rapport.pending += restants.len() as u32;
        }
        Ok(rapport)
    }

    /// Appelle `update` jusqu'à ce que tout soit chargé (préchargement d'une capture : pas de budget par image).
    pub fn update_until_complete(
        &mut self,
        cam: &VoxelCamera,
        src: &dyn VoxelSource,
        world: &mut VoxelGpuWorld,
        gpu: &GpuContext,
    ) -> Result<StreamReport, WorldError> {
        let mut total = StreamReport::default();
        loop {
            let r = self.update(cam, src, world, gpu)?;
            total.processed += r.processed;
            total.uploaded += r.uploaded;
            total.evicted += r.evicted;
            total.bytes += r.bytes;
            if r.pending == 0 {
                total.pending = 0;
                return Ok(total);
            }
        }
    }
}
