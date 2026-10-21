//! `MeshWorld` : les quads de tous les chunks maillés, sur le GPU. UN tampon de stockage contient les quads de tous les
//! chunks (chacun à sa place, `first_quad`) ; un tampon uniforme à décalage dynamique porte, par chunk, son origine
//! en mètres RELATIVE à la caméra (réécrite à chaque image). Un chunk visible = un `draw(0..4, first..first + n)` :
//! quatre sommets par quad (bande de triangles), reconstruits dans le shader (aucun tampon de sommets ni d'indices).
//!
//! Le monde est partagé (clonable) entre les passes : la scène le remplit entre deux images, les passes le lisent.

use super::frustum::Frustum;
use crate::gpu::GpuContext;
use em_core::{ChunkKey, VOXEL_MM};
use em_mesh::ChunkMesh;
use glam::Vec3;
use std::sync::{Arc, Mutex, MutexGuard};
use wgpu::util::DeviceExt;

/// Un chunk sur le GPU.
#[derive(Debug, Clone, Copy)]
pub struct ChunkGpu {
    key: ChunkKey,
    lod: u8,
    first_quad: u32,
    quad_count: u32,
    /// Boîte englobante locale du chunk, en mètres depuis son origine.
    bounds_m: [[f32; 3]; 2],
}

impl ChunkGpu {
    /// Clé du chunk.
    pub fn key(&self) -> ChunkKey {
        self.key
    }

    /// Nombre de quads.
    pub fn quad_count(&self) -> u32 {
        self.quad_count
    }
}

/// Un chunk à dessiner cette image : indice, décalage dynamique de son uniforme, plage de quads.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct DrawChunk {
    index: usize,
    offset: u32,
    first_quad: u32,
    quad_count: u32,
}

impl DrawChunk {
    /// Décalage dynamique de l'uniforme du chunk.
    pub fn offset(&self) -> u32 {
        self.offset
    }

    /// Plage d'instances (un quad par instance).
    pub fn instances(&self) -> std::ops::Range<u32> {
        self.first_quad..self.first_quad + self.quad_count
    }

    /// Indice du chunk dans le monde.
    pub fn index(&self) -> usize {
        self.index
    }
}

/// Boîte d'un chunk en mètres relatifs à la caméra, pour les tests de visibilité.
#[derive(Debug, Clone, Copy)]
pub struct ChunkBox {
    /// Coin minimal.
    pub min: Vec3,
    /// Coin maximal.
    pub max: Vec3,
}

/// Statistiques du monde de maillages.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct MeshWorldStats {
    /// Chunks maillés.
    pub chunks: usize,
    /// Quads au total.
    pub quads: usize,
    /// Octets de quads sur le GPU.
    pub quad_bytes: u64,
}

/// Pas entre deux uniformes de chunk (alignement dynamique minimal de wgpu).
const PAS_UNIFORME: u64 = 256;

/// État interne du monde (verrouillé par `MeshWorld::lock`).
pub struct MeshWorldState {
    device: wgpu::Device,
    layout: wgpu::BindGroupLayout,
    chunks: Vec<ChunkGpu>,
    quads: Option<wgpu::Buffer>,
    uniformes: Option<wgpu::Buffer>,
    groupe: Option<wgpu::BindGroup>,
    origines: Vec<[f32; 3]>,
    image_courante: Option<(u64, [i64; 3])>,
    stats: MeshWorldStats,
    revision: u64,
    foliage_zone_m: Option<f32>,
}

impl MeshWorldState {
    /// Mise en page du groupe des chunks : uniforme dynamique (origine) et tampon des quads.
    pub fn layout(&self) -> &wgpu::BindGroupLayout {
        &self.layout
    }

    /// Groupe de liaison des chunks (`None` tant qu'aucun maillage n'est chargé).
    pub fn group(&self) -> Option<&wgpu::BindGroup> {
        self.groupe.as_ref()
    }

    /// Chunks chargés.
    pub fn chunks(&self) -> &[ChunkGpu] {
        &self.chunks
    }

    /// Statistiques.
    pub fn stats(&self) -> MeshWorldStats {
        self.stats
    }

    /// Zone (m) sur laquelle l'épaisseur de feuillage a été cuite, `None` si elle ne l'est pas.
    pub fn foliage_zone_m(&self) -> Option<f32> {
        self.foliage_zone_m
    }

    /// Vrai si l'épaisseur de feuillage des quads est cuite.
    pub fn foliage_baked(&self) -> bool {
        self.foliage_zone_m.is_some()
    }

    /// Numéro de révision (change quand les maillages sont remplacés : les ombres doivent être refaites).
    pub fn revision(&self) -> u64 {
        self.revision
    }

    /// Prépare l'image : écrit l'origine de chaque chunk relative à la caméra. Sans effet si l'image et la position
    /// sont celles déjà préparées (la passe d'ombre et la passe principale l'appellent toutes deux).
    pub fn begin_frame(&mut self, queue: &wgpu::Queue, image: u64, camera_mm: [i64; 3]) {
        if self.image_courante == Some((image, camera_mm)) || self.chunks.is_empty() {
            return;
        }
        self.image_courante = Some((image, camera_mm));
        let mut octets = vec![0_u8; self.chunks.len() * PAS_UNIFORME as usize];
        self.origines.clear();
        for (i, c) in self.chunks.iter().enumerate() {
            let o = c.key.origin();
            let echelle = VOXEL_MM << c.lod;
            let rel = [
                (i64::from(o.x) * echelle - camera_mm[0]) as f64 * 0.001,
                (i64::from(o.y) * echelle - camera_mm[1]) as f64 * 0.001,
                (i64::from(o.z) * echelle - camera_mm[2]) as f64 * 0.001,
            ];
            let rel32 = [rel[0] as f32, rel[1] as f32, rel[2] as f32];
            self.origines.push(rel32);
            let u = [rel32[0], rel32[1], rel32[2], echelle as f32 * 0.001];
            // origine du chunk en voxels du niveau 0 (entiers exacts : le relief ancre son bruit au monde)
            let vox: [i32; 4] = [
                (i64::from(o.x) << c.lod) as i32,
                (i64::from(o.y) << c.lod) as i32,
                (i64::from(o.z) << c.lod) as i32,
                0,
            ];
            let debut = i * PAS_UNIFORME as usize;
            octets[debut..debut + 16].copy_from_slice(bytemuck::bytes_of(&u));
            octets[debut + 16..debut + 32].copy_from_slice(bytemuck::bytes_of(&vox));
        }
        if let Some(b) = &self.uniformes {
            queue.write_buffer(b, 0, &octets);
        }
    }

    /// Chunks à dessiner : ceux dont la boîte (mètres relatifs à la caméra) est acceptée, du plus proche au plus
    /// lointain (profondeur précoce), à égalité dans l'ordre des clés. Nécessite `begin_frame`.
    pub fn visible(&self, accepte: &dyn Fn(&ChunkBox) -> bool) -> Vec<DrawChunk> {
        let mut liste: Vec<(f32, DrawChunk)> = Vec::new();
        for (i, c) in self.chunks.iter().enumerate() {
            let Some(o) = self.origines.get(i) else { break };
            let o = Vec3::from(*o);
            let boite = ChunkBox {
                min: o + Vec3::from(c.bounds_m[0]),
                max: o + Vec3::from(c.bounds_m[1]),
            };
            if !accepte(&boite) {
                continue;
            }
            let centre = (boite.min + boite.max) * 0.5;
            liste.push((
                centre.length_squared(),
                DrawChunk {
                    index: i,
                    offset: (i as u64 * PAS_UNIFORME) as u32,
                    first_quad: c.first_quad,
                    quad_count: c.quad_count,
                },
            ));
        }
        liste.sort_by(|a, b| a.0.total_cmp(&b.0).then(a.1.index.cmp(&b.1.index)));
        liste.into_iter().map(|(_, d)| d).collect()
    }

    /// Tous les chunks, sans test (passe d'ombre : elle fait son propre test dans sa fenêtre).
    pub fn all(&self) -> Vec<DrawChunk> {
        self.visible(&|_| true)
    }

    /// Visibilité par le cône de vision.
    pub fn visible_in(&self, f: &Frustum) -> Vec<DrawChunk> {
        self.visible(&|b| f.intersects_box(b.min, b.max))
    }
}

/// Monde de maillages partagé entre la scène (qui le remplit) et les passes (qui le dessinent).
#[derive(Clone)]
pub struct MeshWorld {
    interieur: Arc<Mutex<MeshWorldState>>,
}

impl MeshWorld {
    /// Monde vide ; crée la mise en page des chunks sur l'appareil.
    pub fn new(gpu: &GpuContext) -> Self {
        let dev = gpu.device();
        let entree = |binding: u32, ty: wgpu::BindingType, vis| wgpu::BindGroupLayoutEntry {
            binding,
            visibility: vis,
            ty,
            count: None,
        };
        let layout = dev.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
            label: Some("maillage chunks bgl"),
            entries: &[
                entree(
                    0,
                    wgpu::BindingType::Buffer {
                        ty: wgpu::BufferBindingType::Uniform,
                        has_dynamic_offset: true,
                        min_binding_size: wgpu::BufferSize::new(32),
                    },
                    wgpu::ShaderStages::VERTEX,
                ),
                entree(
                    1,
                    wgpu::BindingType::Buffer {
                        ty: wgpu::BufferBindingType::Storage { read_only: true },
                        has_dynamic_offset: false,
                        min_binding_size: None,
                    },
                    wgpu::ShaderStages::VERTEX,
                ),
            ],
        });
        Self {
            interieur: Arc::new(Mutex::new(MeshWorldState {
                device: dev.clone(),
                layout,
                chunks: Vec::new(),
                quads: None,
                uniformes: None,
                groupe: None,
                origines: Vec::new(),
                image_courante: None,
                stats: MeshWorldStats::default(),
                revision: 0,
                foliage_zone_m: None,
            })),
        }
    }

    /// Verrouille le monde pour lire (passes) ou modifier.
    pub fn lock(&self) -> MutexGuard<'_, MeshWorldState> {
        self.interieur.lock().unwrap_or_else(|e| e.into_inner())
    }

    /// Remplace tous les maillages (un seul tampon de quads, un seul tampon d'uniformes). Les chunks sont rangés
    /// dans l'ordre des clés : le GPU reçoit les mêmes octets à chaque fois.
    pub fn replace(&self, meshes: &[ChunkMesh]) {
        self.replace_with(meshes, None);
    }

    /// Comme `replace`, en précisant la zone d'épaisseur de feuillage cuite dans les quads (voxels), `None` sinon.
    pub fn replace_with(&self, meshes: &[ChunkMesh], foliage_zone_voxels: Option<u32>) {
        let mut s = self.lock();
        let mut ordre: Vec<&ChunkMesh> = meshes.iter().filter(|m| !m.is_empty()).collect();
        ordre.sort_by_key(|m| m.key());
        let mut octets: Vec<u8> = Vec::new();
        let mut chunks = Vec::with_capacity(ordre.len());
        let mut quads = 0_usize;
        for m in &ordre {
            let b = m.bounds();
            let vox = 0.05 * f32::from(1_u16 << m.lod());
            chunks.push(ChunkGpu {
                key: m.key(),
                lod: m.lod(),
                first_quad: quads as u32,
                quad_count: m.quad_count() as u32,
                bounds_m: [b[0].map(|v| f32::from(v) * vox), b[1].map(|v| f32::from(v) * vox)],
            });
            octets.extend_from_slice(m.as_bytes());
            quads += m.quad_count();
        }
        let dev = s.device.clone();
        if octets.is_empty() {
            s.quads = None;
            s.uniformes = None;
            s.groupe = None;
        } else {
            let tampon_quads = dev.create_buffer_init(&wgpu::util::BufferInitDescriptor {
                label: Some("maillage quads"),
                contents: &octets,
                usage: wgpu::BufferUsages::STORAGE,
            });
            let tampon_uniformes = dev.create_buffer(&wgpu::BufferDescriptor {
                label: Some("maillage origines de chunks"),
                size: chunks.len() as u64 * PAS_UNIFORME,
                usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
                mapped_at_creation: false,
            });
            let groupe = dev.create_bind_group(&wgpu::BindGroupDescriptor {
                label: Some("maillage chunks groupe"),
                layout: &s.layout,
                entries: &[
                    wgpu::BindGroupEntry {
                        binding: 0,
                        resource: wgpu::BindingResource::Buffer(wgpu::BufferBinding {
                            buffer: &tampon_uniformes,
                            offset: 0,
                            size: wgpu::BufferSize::new(32),
                        }),
                    },
                    wgpu::BindGroupEntry {
                        binding: 1,
                        resource: tampon_quads.as_entire_binding(),
                    },
                ],
            });
            s.quads = Some(tampon_quads);
            s.uniformes = Some(tampon_uniformes);
            s.groupe = Some(groupe);
        }
        s.stats = MeshWorldStats {
            chunks: chunks.len(),
            quads,
            quad_bytes: octets.len() as u64,
        };
        s.chunks = chunks;
        s.origines.clear();
        s.image_courante = None;
        s.revision += 1;
        s.foliage_zone_m = foliage_zone_voxels.map(|z| z as f32 * 0.05);
    }

    /// Statistiques.
    pub fn stats(&self) -> MeshWorldStats {
        self.lock().stats
    }

    /// Numéro de révision.
    pub fn revision(&self) -> u64 {
        self.lock().revision
    }
}
