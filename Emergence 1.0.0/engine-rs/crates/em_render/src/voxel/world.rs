//! `VoxelGpuWorld` : la mémoire GPU des voxels (docs/19 § 4.4, docs/19a § 5.1). Il POSSÈDE les tampons et les
//! allocateurs ; il ne décide jamais quoi charger (c'est le `ClipmapStreamer`) ni ne dessine (c'est
//! `VoxelTracePass`). Les passes reçoivent seulement une copie bon marché des liaisons (`WorldBindings`).

use super::alloc::{PayloadAllocator, SlotAllocator};
use super::gpu::*;
use super::pack::PackedBrick;
use crate::error::WorldError;
use crate::gpu::GpuContext;
use em_core::ChunkKey;
use em_voxel::{CHUNK_BRICKS, Chunk, ChunkClass};
use std::collections::BTreeMap;

/// Configuration de la clipmap (docs/19b L09), validée à la construction du monde.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ClipmapConfig {
    /// Nombre de niveaux (1 en L09, 6 en L26).
    pub levels: u8,
    /// Chunks par axe et par niveau : 16 (adressage torique `& 15`).
    pub chunks_per_axis: u32,
    /// Briques à palette que la mémoire peut porter (cases de 24 bits moins la case réservée).
    pub brick_capacity: u32,
    /// Mots de 32 bits du tas des palettes et indices.
    pub payload_words: u32,
    /// Chunks mixtes que le tas de chunks peut porter (écart de signature : nécessaire pour dimensionner le tampon).
    pub chunk_capacity: u32,
}

impl ClipmapConfig {
    /// Configuration du laboratoire pour un niveau : de quoi porter une forêt de quelques arbres.
    pub fn laboratoire() -> Self {
        Self {
            levels: 1,
            chunks_per_axis: CHUNKS_PAR_AXE,
            brick_capacity: 200_000,
            payload_words: 24_000_000,
            chunk_capacity: 2_048,
        }
    }

    /// Vérifie les invariants ; l'objet qui reçoit la configuration l'appelle.
    pub fn validate(&self) -> Result<(), WorldError> {
        let refus = |m: String| Err(WorldError::Config(m));
        if !(1..=NIVEAUX_MAX as u8).contains(&self.levels) {
            return refus(format!("{} niveaux (de 1 à {NIVEAUX_MAX})", self.levels));
        }
        if self.chunks_per_axis != CHUNKS_PAR_AXE {
            return refus(format!(
                "{} chunks par axe : l'adressage torique du shader suppose {CHUNKS_PAR_AXE}",
                self.chunks_per_axis
            ));
        }
        if self.brick_capacity == 0 || self.brick_capacity >= CASE_BRIQUE_RESERVEE {
            return refus(format!(
                "capacité de briques {} hors de 1..{CASE_BRIQUE_RESERVEE}",
                self.brick_capacity
            ));
        }
        if self.chunk_capacity == 0 || self.chunk_capacity >= 1 << 24 {
            return refus(format!(
                "capacité de chunks {} hors de 1..16 777 216",
                self.chunk_capacity
            ));
        }
        if self.payload_words < 256 {
            return refus(format!("tas de {} mots : au moins 256", self.payload_words));
        }
        let plus_gros = [
            u64::from(self.chunk_capacity) * OCTETS_PAR_CHUNK,
            u64::from(self.payload_words) * 4,
            u64::from(self.brick_capacity) * 64,
        ]
        .into_iter()
        .max()
        .unwrap_or(0);
        if plus_gros > 1 << 30 {
            return refus(format!(
                "un tampon de {plus_gros} octets dépasse la limite de liaison de 1 Gio"
            ));
        }
        Ok(())
    }
}

/// Drapeaux d'un chunk téléversé (docs/19a § 5.1 : bits 24 et 25 de l'entrée de la table).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub struct ChunkFlags {
    has_skin: bool,
    has_visible: bool,
    edited: bool,
}

impl ChunkFlags {
    /// Drapeaux explicites.
    pub const fn new(has_skin: bool, has_visible: bool, edited: bool) -> Self {
        Self {
            has_skin,
            has_visible,
            edited,
        }
    }

    /// Drapeaux d'un chunk sans peau (L09 : le terrain est tracé comme les autres voxels) : « visible » dès qu'il
    /// contient quelque chose.
    pub const fn sans_peau() -> Self {
        Self::new(false, true, false)
    }

    /// Le chunk contient des briques de peau (terrain non édité).
    pub const fn has_skin(&self) -> bool {
        self.has_skin
    }

    /// Le chunk contient des briques visibles (non peau).
    pub const fn has_visible(&self) -> bool {
        self.has_visible
    }

    /// Le chunk a été édité.
    pub const fn edited(&self) -> bool {
        self.edited
    }
}

/// Ce qu'a fait `upload_chunk`.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum UploadOutcome {
    /// Le contenu (empreinte) et les drapeaux étaient déjà sur le GPU : rien n'a été écrit.
    Unchanged,
    /// Le chunk est maintenant sur le GPU ; octets envoyés.
    Uploaded {
        /// Octets écrits dans les tampons.
        bytes: u64,
    },
}

/// Mesures de la mémoire GPU (rapport en lecture seule).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub struct GpuWorldStats {
    /// Chunks mixtes dans le tas de chunks.
    pub chunks_pool: u32,
    /// Chunks pleins uniformes (une entrée de table, rien d'alloué).
    pub chunks_uniform: u32,
    /// Briques à palette allouées.
    pub bricks: u32,
    /// Mots du tas utilisés.
    pub payload_words: u64,
    /// Octets écrits depuis la création.
    pub bytes_uploaded: u64,
    /// Nombre de chunks téléversés depuis la création.
    pub chunks_uploaded: u64,
    /// Mémoire GPU réservée par les tampons, en octets.
    pub bytes_reserved: u64,
}

/// Liaisons du monde pour les passes (copie bon marché : les objets `wgpu` sont comptés par référence).
#[derive(Clone)]
pub struct WorldBindings {
    layout: wgpu::BindGroupLayout,
    group: wgpu::BindGroup,
}

impl WorldBindings {
    /// Mise en page du groupe (à placer en groupe 1 des pipelines de tracé).
    pub fn layout(&self) -> &wgpu::BindGroupLayout {
        &self.layout
    }

    /// Groupe de liaisons.
    pub fn group(&self) -> &wgpu::BindGroup {
        &self.group
    }
}

/// Ce que le monde sait d'un chunk non vide.
struct Resident {
    entree_table: u32,
    empreinte: u64,
    flags: ChunkFlags,
    genre: Genre,
}

enum Genre {
    Uniforme,
    /// Case dans le tas de chunks et briques allouées : (case de brique, décalage et bits dans le tas).
    Pool {
        case: u32,
        briques: Vec<(u32, u32, u8)>,
    },
}

/// Écritures à envoyer, fusionnées quand elles se touchent (une écriture par plage au lieu d'une par brique).
#[derive(Default)]
struct Ecritures {
    plages: Vec<(u64, Vec<u8>)>,
}

impl Ecritures {
    fn ajouter(&mut self, decalage: u64, octets: &[u8]) {
        self.plages.push((decalage, octets.to_vec()));
    }

    fn envoyer(mut self, queue: &wgpu::Queue, tampon: &wgpu::Buffer) -> u64 {
        self.plages.sort_by_key(|p| p.0);
        let mut fusionnees: Vec<(u64, Vec<u8>)> = Vec::new();
        for (o, d) in self.plages {
            match fusionnees.last_mut() {
                Some((lo, ld)) if *lo + ld.len() as u64 == o => ld.extend_from_slice(&d),
                _ => fusionnees.push((o, d)),
            }
        }
        let mut total = 0;
        for (o, d) in fusionnees {
            queue.write_buffer(tampon, o, &d);
            total += d.len() as u64;
        }
        total
    }
}

/// La mémoire GPU des voxels : table de chunks par niveau, tas de chunks, briques, tas de mots.
pub struct VoxelGpuWorld {
    cfg: ClipmapConfig,
    niveaux: Vec<ClipLevel>,
    tampon_niveaux: wgpu::Buffer,
    table: wgpu::Buffer,
    pool: wgpu::Buffer,
    occupation: wgpu::Buffer,
    meta: wgpu::Buffer,
    payload: wgpu::Buffer,
    liaisons: WorldBindings,
    chunks: SlotAllocator,
    briques: SlotAllocator,
    tas: PayloadAllocator,
    residents: BTreeMap<(u8, ChunkKey), Resident>,
    octets_envoyes: u64,
    chunks_envoyes: u64,
    octets_reserves: u64,
}

impl VoxelGpuWorld {
    /// Crée la mémoire GPU. Refuse une configuration invalide.
    pub fn new(gpu: &GpuContext, cfg: ClipmapConfig) -> Result<Self, WorldError> {
        cfg.validate()?;
        let dev = gpu.device();
        let stockage = wgpu::BufferUsages::STORAGE | wgpu::BufferUsages::COPY_DST;
        let tampon = |etiquette: &str, octets: u64, usage: wgpu::BufferUsages| {
            dev.create_buffer(&wgpu::BufferDescriptor {
                label: Some(etiquette),
                size: octets.max(16),
                usage,
                mapped_at_creation: false,
            })
        };
        let octets_table = NIVEAUX_MAX as u64 * u64::from(ENTREES_PAR_NIVEAU) * 4;
        let octets_pool = u64::from(cfg.chunk_capacity) * OCTETS_PAR_CHUNK;
        let octets_occ = u64::from(cfg.brick_capacity) * 64;
        let octets_meta = u64::from(cfg.brick_capacity) * 8;
        let octets_payload = u64::from(cfg.payload_words) * 4;
        let tampon_niveaux = tampon(
            "voxel niveaux",
            (NIVEAUX_MAX * size_of::<ClipLevel>()) as u64,
            wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
        );
        let table = tampon("voxel table de chunks", octets_table, stockage);
        let pool = tampon("voxel tas de chunks", octets_pool, stockage);
        let occupation = tampon("voxel occupation des briques", octets_occ, stockage);
        let meta = tampon("voxel méta des briques", octets_meta, stockage);
        let payload = tampon("voxel tas de mots", octets_payload, stockage);

        let mut niveaux = vec![ClipLevel::default(); NIVEAUX_MAX];
        for (i, n) in niveaux.iter_mut().enumerate() {
            n.lod = i as u32;
            n.table_offset = i as u32 * ENTREES_PAR_NIVEAU;
        }
        gpu.queue()
            .write_buffer(&tampon_niveaux, 0, bytemuck::cast_slice(&niveaux));
        // Table entièrement vide au départ.
        let vide = vec![ENTREE_VIDE; (NIVEAUX_MAX as u32 * ENTREES_PAR_NIVEAU) as usize];
        gpu.queue().write_buffer(&table, 0, bytemuck::cast_slice(&vide));

        let etage = wgpu::ShaderStages::COMPUTE | wgpu::ShaderStages::FRAGMENT;
        let entree = |binding: u32, ty: wgpu::BufferBindingType| wgpu::BindGroupLayoutEntry {
            binding,
            visibility: etage,
            ty: wgpu::BindingType::Buffer {
                ty,
                has_dynamic_offset: false,
                min_binding_size: None,
            },
            count: None,
        };
        let lecture = wgpu::BufferBindingType::Storage { read_only: true };
        let layout = dev.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
            label: Some("voxel monde bgl"),
            entries: &[
                entree(0, wgpu::BufferBindingType::Uniform),
                entree(1, lecture),
                entree(2, lecture),
                entree(3, lecture),
                entree(4, lecture),
                entree(5, lecture),
            ],
        });
        let group = dev.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("voxel monde groupe"),
            layout: &layout,
            entries: &[
                wgpu::BindGroupEntry {
                    binding: 0,
                    resource: tampon_niveaux.as_entire_binding(),
                },
                wgpu::BindGroupEntry {
                    binding: 1,
                    resource: table.as_entire_binding(),
                },
                wgpu::BindGroupEntry {
                    binding: 2,
                    resource: pool.as_entire_binding(),
                },
                wgpu::BindGroupEntry {
                    binding: 3,
                    resource: occupation.as_entire_binding(),
                },
                wgpu::BindGroupEntry {
                    binding: 4,
                    resource: meta.as_entire_binding(),
                },
                wgpu::BindGroupEntry {
                    binding: 5,
                    resource: payload.as_entire_binding(),
                },
            ],
        });
        let octets_reserves = octets_table + octets_pool + octets_occ + octets_meta + octets_payload;
        Ok(Self {
            niveaux,
            tampon_niveaux,
            table,
            pool,
            occupation,
            meta,
            payload,
            liaisons: WorldBindings { layout, group },
            chunks: SlotAllocator::new("tas de chunks", cfg.chunk_capacity),
            briques: SlotAllocator::new("briques", cfg.brick_capacity),
            tas: PayloadAllocator::new(cfg.payload_words),
            residents: BTreeMap::new(),
            octets_envoyes: 0,
            chunks_envoyes: 0,
            octets_reserves,
            cfg,
        })
    }

    /// Configuration du monde.
    pub fn config(&self) -> &ClipmapConfig {
        &self.cfg
    }

    /// Mise en page des liaisons (groupe 1 des passes de tracé).
    pub fn bind_group_layout(&self) -> &wgpu::BindGroupLayout {
        &self.liaisons.layout
    }

    /// Groupe de liaisons.
    pub fn bind_group(&self) -> &wgpu::BindGroup {
        &self.liaisons.group
    }

    /// Copie des liaisons à confier à une passe.
    pub fn bindings(&self) -> WorldBindings {
        self.liaisons.clone()
    }

    /// Mesures de la mémoire.
    pub fn stats(&self) -> GpuWorldStats {
        let uniformes = self
            .residents
            .values()
            .filter(|r| matches!(r.genre, Genre::Uniforme))
            .count() as u32;
        GpuWorldStats {
            chunks_pool: self.chunks.en_usage(),
            chunks_uniform: uniformes,
            bricks: self.briques.en_usage(),
            payload_words: self.tas.mots_en_usage(),
            bytes_uploaded: self.octets_envoyes,
            chunks_uploaded: self.chunks_envoyes,
            bytes_reserved: self.octets_reserves,
        }
    }

    fn verifie_niveau(&self, niveau: u8) -> Result<(), WorldError> {
        if niveau >= self.cfg.levels {
            return Err(WorldError::Niveau {
                niveau,
                niveaux: self.cfg.levels,
            });
        }
        Ok(())
    }

    /// Coin du cube du niveau, en chunks du niveau.
    pub fn level_origin(&self, niveau: u8) -> Option<ChunkKey> {
        let n = self.niveaux.get(usize::from(niveau))?;
        Some(ChunkKey::new(
            n.origin_chunk[0],
            n.origin_chunk[1],
            n.origin_chunk[2],
        ))
    }

    fn dans_la_fenetre(&self, niveau: u8, k: ChunkKey) -> bool {
        let o = self.niveaux[usize::from(niveau)].origin_chunk;
        let n = CHUNKS_PAR_AXE as i32;
        (0..n).contains(&(k.x - o[0])) && (0..n).contains(&(k.y - o[1])) && (0..n).contains(&(k.z - o[2]))
    }

    /// Index de l'entrée de table d'un chunk (adressage torique), valable seulement dans la fenêtre.
    fn index_table(&self, niveau: u8, k: ChunkKey) -> u32 {
        let off = self.niveaux[usize::from(niveau)].table_offset;
        off + (k.x & 15) as u32 + 16 * (k.z & 15) as u32 + 256 * (k.y & 15) as u32
    }

    /// Le chunk est-il sur le GPU (non vide) ?
    pub fn is_resident(&self, niveau: u8, k: ChunkKey) -> bool {
        self.residents.contains_key(&(niveau, k))
    }

    /// Déplace le cube du niveau. Les chunks qui sortent de la fenêtre sont évincés (leur place torique
    /// serait sinon lue pour un autre chunk).
    pub fn set_level_origin(
        &mut self,
        gpu: &GpuContext,
        niveau: u8,
        origine: ChunkKey,
    ) -> Result<(), WorldError> {
        self.verifie_niveau(niveau)?;
        let n = &mut self.niveaux[usize::from(niveau)];
        if n.origin_chunk == [origine.x, origine.y, origine.z] {
            return Ok(());
        }
        n.origin_chunk = [origine.x, origine.y, origine.z];
        let octets = bytemuck::bytes_of(&self.niveaux[usize::from(niveau)]);
        gpu.queue().write_buffer(
            &self.tampon_niveaux,
            (usize::from(niveau) * size_of::<ClipLevel>()) as u64,
            octets,
        );
        let dehors: Vec<ChunkKey> = self
            .residents
            .keys()
            .filter(|(l, k)| *l == niveau && !self.dans_la_fenetre(niveau, *k))
            .map(|(_, k)| *k)
            .collect();
        for k in dehors {
            self.evict_chunk(gpu, niveau, k);
        }
        Ok(())
    }

    /// Retire un chunk du GPU : libère ses cases et vide son entrée de table. Sans effet s'il est absent.
    pub fn evict_chunk(&mut self, gpu: &GpuContext, niveau: u8, k: ChunkKey) {
        let Some(r) = self.residents.remove(&(niveau, k)) else {
            return;
        };
        self.liberer(&r.genre);
        gpu.queue().write_buffer(
            &self.table,
            u64::from(r.entree_table) * 4,
            bytemuck::bytes_of(&ENTREE_VIDE),
        );
    }

    fn liberer(&mut self, g: &Genre) {
        if let Genre::Pool { case, briques } = g {
            self.chunks.liberer(*case);
            for (b, off, bits) in briques {
                self.briques.liberer(*b);
                self.tas.liberer(*off, *bits);
            }
        }
    }

    /// Téléverse (ou remplace) un chunk : classement, empaquetage des briques, allocation, écritures groupées.
    /// Tout ou rien : si une mémoire sature, rien n'est changé et l'erreur dit laquelle.
    pub fn upload_chunk(
        &mut self,
        gpu: &GpuContext,
        niveau: u8,
        k: ChunkKey,
        chunk: &Chunk,
        flags: ChunkFlags,
    ) -> Result<UploadOutcome, WorldError> {
        self.verifie_niveau(niveau)?;
        if !self.dans_la_fenetre(niveau, k) {
            return Err(WorldError::HorsFenetre {
                niveau,
                x: k.x,
                y: k.y,
                z: k.z,
            });
        }
        let empreinte = chunk.fingerprint_value();
        let entree_table = self.index_table(niveau, k);
        if let Some(r) = self.residents.get(&(niveau, k))
            && r.empreinte == empreinte
            && r.flags == flags
        {
            return Ok(UploadOutcome::Unchanged);
        }
        // Libère l'ancien contenu (le remplacement ne double pas la mémoire).
        let ancien = self.residents.remove(&(niveau, k));
        if let Some(a) = &ancien {
            self.liberer(&a.genre);
        }
        let bits_flags = (if flags.has_skin() { BIT_CHUNK_PEAU } else { 0 })
            | (if flags.has_visible() { BIT_CHUNK_VISIBLE } else { 0 });
        let q = gpu.queue();
        match chunk.classify() {
            ChunkClass::Air => {
                q.write_buffer(
                    &self.table,
                    u64::from(entree_table) * 4,
                    bytemuck::bytes_of(&ENTREE_VIDE),
                );
                self.octets_envoyes += 4;
                Ok(UploadOutcome::Uploaded { bytes: 4 })
            }
            ChunkClass::Uniform(v) => {
                let entree = BIT_UNIFORME | u32::from(v.raw());
                q.write_buffer(
                    &self.table,
                    u64::from(entree_table) * 4,
                    bytemuck::bytes_of(&entree),
                );
                self.residents.insert(
                    (niveau, k),
                    Resident {
                        entree_table,
                        empreinte,
                        flags,
                        genre: Genre::Uniforme,
                    },
                );
                self.octets_envoyes += 4;
                self.chunks_envoyes += 1;
                Ok(UploadOutcome::Uploaded { bytes: 4 })
            }
            ChunkClass::Mixed => {
                let r =
                    self.televerser_mixte(gpu, niveau, k, chunk, flags, bits_flags, empreinte, entree_table);
                if r.is_err() {
                    // L'ancien contenu est libéré : la table ne doit plus le désigner.
                    q.write_buffer(
                        &self.table,
                        u64::from(entree_table) * 4,
                        bytemuck::bytes_of(&ENTREE_VIDE),
                    );
                }
                r
            }
        }
    }

    #[allow(clippy::too_many_arguments)]
    fn televerser_mixte(
        &mut self,
        gpu: &GpuContext,
        niveau: u8,
        k: ChunkKey,
        chunk: &Chunk,
        flags: ChunkFlags,
        bits_flags: u32,
        empreinte: u64,
        entree_table: u32,
    ) -> Result<UploadOutcome, WorldError> {
        let case_chunk = self.chunks.allouer()?;
        let mut alloues: Vec<(u32, u32, u8)> = Vec::new();
        // Écritures de briques à préparer avant d'engager quoi que ce soit.
        let mut occ = Ecritures::default();
        let mut meta = Ecritures::default();
        let mut tas = Ecritures::default();
        let mut mots_chunk = vec![0_u32; MOTS_PAR_CHUNK as usize];
        let (masque, entrees) = mots_chunk.split_at_mut(32);
        for (b, br) in chunk.bricks().enumerate().take(CHUNK_BRICKS) {
            let p = PackedBrick::from_brick(br);
            let mut entree = p.entree_sans_case(flags.edited());
            if let PackedBrick::Palette {
                occupancy,
                bits,
                words,
                ..
            } = &p
            {
                let allocation = self
                    .briques
                    .allouer()
                    .and_then(|case| match self.tas.allouer(*bits) {
                        Ok(off) => Ok((case, off)),
                        Err(e) => {
                            self.briques.liberer(case);
                            Err(e)
                        }
                    });
                let (case, off) = match allocation {
                    Ok(x) => x,
                    Err(e) => {
                        // Retour arrière : rien n'a été écrit sur le GPU.
                        self.chunks.liberer(case_chunk);
                        for (c, o, bt) in alloues {
                            self.briques.liberer(c);
                            self.tas.liberer(o, bt);
                        }
                        return Err(e);
                    }
                };
                alloues.push((case, off, *bits));
                entree |= case;
                occ.ajouter(u64::from(case) * 64, bytemuck::cast_slice(occupancy));
                meta.ajouter(u64::from(case) * 8, bytemuck::cast_slice(&[off, p.meta1()]));
                tas.ajouter(u64::from(off) * 4, bytemuck::cast_slice(words));
            }
            if entree != ENTREE_VIDE {
                masque[b >> 5] |= 1 << (b & 31);
                masque[16 + (b >> 5)] |= 1 << (b & 31);
            }
            entrees[b] = entree;
        }
        let mut octets = 0;
        octets += occ.envoyer(gpu.queue(), &self.occupation);
        octets += meta.envoyer(gpu.queue(), &self.meta);
        octets += tas.envoyer(gpu.queue(), &self.payload);
        gpu.queue().write_buffer(
            &self.pool,
            u64::from(case_chunk) * OCTETS_PAR_CHUNK,
            bytemuck::cast_slice(&mots_chunk),
        );
        octets += OCTETS_PAR_CHUNK;
        let entree = case_chunk | bits_flags;
        gpu.queue().write_buffer(
            &self.table,
            u64::from(entree_table) * 4,
            bytemuck::bytes_of(&entree),
        );
        octets += 4;
        self.residents.insert(
            (niveau, k),
            Resident {
                entree_table,
                empreinte,
                flags,
                genre: Genre::Pool {
                    case: case_chunk,
                    briques: alloues,
                },
            },
        );
        self.octets_envoyes += octets;
        self.chunks_envoyes += 1;
        Ok(UploadOutcome::Uploaded { bytes: octets })
    }
}
