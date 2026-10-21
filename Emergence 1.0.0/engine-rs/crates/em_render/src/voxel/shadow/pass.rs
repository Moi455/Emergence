//! `ShadowCascades` : la passe qui remplit les cascades d'ombre du soleil par TRAVERSÉE DE LA GRILLE VOXEL en compute
//! (docs/19 § 5.3). Même structure de briques et même fonction `trace()` que le tracé primaire : aucun maillage.
//!
//! Responsabilités : le [`ShadowPlanner`] décide (CPU), cette passe exécute (GPU) et publie dans le graphe l'uniforme
//! et le tableau de profondeurs que l'éclairage lit ([`noms`]).

use super::grid::SunBasis;
use super::params::{ShadowParams, TUILE};
use super::planner::{Generation, ShadowPlanner};
use crate::gpu::GpuContext;
use crate::graph::{PassContext, PassName, PassSetup, RenderPass, Resources};
use crate::partage::Partage;
use crate::sky::SkyParams;
use crate::voxel::gpu::{ShadowCascadeUniform, ShadowFillCascade, ShadowTileGpu, ShadowUniform};
use crate::voxel::shaders;
use crate::voxel::world::WorldBindings;
use glam::DVec3;
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};

/// Taille d'un voxel de niveau 0 en mètres.
const VOXEL_M: f64 = em_core::VOXEL_MM as f64 * 0.001;
/// Tangente du demi-angle du disque solaire (0,2665°).
const TAN_DEMI_SOLEIL: f32 = 0.004_651;

/// Ressources que les ombres publient dans le graphe.
pub mod noms {
    use crate::graph::ResourceName;

    /// Uniforme des cascades (`ShadowUniform`), réécrit à chaque image.
    pub const UNIFORME: ResourceName = ResourceName::new("ombres_uniforme");
    /// Tableau de profondeurs `R32Float` : `2 × cascades` couches (génération avant et arrière de chaque cascade).
    pub const CASCADES: ResourceName = ResourceName::new("ombres_cascades");
}

/// Poignée partagée pour dire aux cascades que le monde a changé (édition, chunks arrivés) : elles sont refaites
/// dès que possible. Clonable ; ce n'est pas une globale (la scène la crée et la prête à la passe).
#[derive(Clone, Default)]
pub struct ShadowControl {
    sale: Arc<AtomicBool>,
}

impl ShadowControl {
    /// Poignée neuve.
    pub fn new() -> Self {
        Self::default()
    }

    /// Le monde a changé : refaire les cascades.
    pub fn invalidate(&self) {
        self.sale.store(true, Ordering::Release);
    }

    pub(crate) fn prendre(&self) -> bool {
        self.sale.swap(false, Ordering::AcqRel)
    }
}

struct Gpu {
    pipeline: wgpu::ComputePipeline,
    groupe: wgpu::BindGroup,
    remplissage: wgpu::Buffer,
    tuiles: wgpu::Buffer,
    uniforme: wgpu::Buffer,
}

/// Passe de remplissage des cascades d'ombre.
pub struct ShadowCascades {
    params: ShadowParams,
    planner: ShadowPlanner,
    ciel: Partage<SkyParams>,
    monde: WorldBindings,
    controle: ShadowControl,
    gpu: Option<Gpu>,
}

impl ShadowCascades {
    /// Nom de la passe dans le profil.
    pub const NOM: PassName = PassName::new("voxel_ombres");

    /// Crée la passe. Le soleil vient du ciel partagé, les voxels des liaisons du monde (injection).
    pub fn new(params: ShadowParams, ciel: Partage<SkyParams>, monde: WorldBindings) -> Self {
        Self {
            planner: ShadowPlanner::new(params),
            params,
            ciel,
            monde,
            controle: ShadowControl::new(),
            gpu: None,
        }
    }

    /// Poignée pour invalider les cascades depuis la scène.
    pub fn control(&self) -> ShadowControl {
        self.controle.clone()
    }

    /// Réglages.
    pub fn params(&self) -> &ShadowParams {
        &self.params
    }
}

fn dvec(v: glam::Vec3) -> DVec3 {
    DVec3::new(f64::from(v.x), f64::from(v.y), f64::from(v.z))
}

fn f4(v: DVec3, w: f32) -> [f32; 4] {
    [v.x as f32, v.y as f32, v.z as f32, w]
}

/// Données de remplissage d'une génération : voxel entier et fraction du texel (0, 0), pas des texels, direction.
fn remplissage(g: &Generation) -> ShadowFillCascade {
    let p = g.placement();
    let b = g.basis();
    let voxels = p.origin(b) / VOXEL_M;
    let entier = voxels.floor();
    let pas = p.texel_m() / VOXEL_M;
    ShadowFillCascade {
        base: [entier.x as i32, entier.y as i32, entier.z as i32, 0],
        frac: f4(voxels - entier, 0.0),
        du: f4(b.right() * pas, 0.0),
        dv: f4(b.up() * pas, 0.0),
        dir: f4(-b.sun(), 0.0),
        meta: [g.layer(), p.size(), 0, 0],
    }
}

/// Ce que l'éclairage lit d'une génération avant : repère CAMÉRA (le tracé de l'image travaille relatif à la caméra).
fn cote_eclairage(g: &Generation, camera: DVec3, far_m: f64) -> ShadowCascadeUniform {
    let p = g.placement();
    let b: &SunBasis = g.basis();
    ShadowCascadeUniform {
        origin: f4(p.origin(b) - camera, p.texel_m() as f32),
        right: f4(b.right(), g.layer() as f32),
        up: f4(b.up(), p.size() as f32),
        sun: f4(b.sun(), 1.0),
        limits: [far_m as f32, 0.0, 0.0, 0.0],
    }
}

impl RenderPass for ShadowCascades {
    fn name(&self) -> PassName {
        Self::NOM
    }

    fn prepare(&mut self, g: &GpuContext, _setup: &PassSetup, res: &mut Resources) {
        use wgpu::TextureUsages as U;
        let dev = g.device();
        // Un changement de sortie recrée les textures : tout est à refaire.
        self.planner = ShadowPlanner::new(self.params);
        let n = self.params.cascades();
        let taille = self.params.size();
        let couches = 2 * n;
        let texture = dev.create_texture(&wgpu::TextureDescriptor {
            label: Some("ombres cascades"),
            size: wgpu::Extent3d {
                width: taille,
                height: taille,
                depth_or_array_layers: couches,
            },
            mip_level_count: 1,
            sample_count: 1,
            dimension: wgpu::TextureDimension::D2,
            format: wgpu::TextureFormat::R32Float,
            usage: U::STORAGE_BINDING | U::TEXTURE_BINDING | U::COPY_SRC,
            view_formats: &[],
        });
        let vue = texture.create_view(&wgpu::TextureViewDescriptor {
            label: Some("ombres cascades vue"),
            dimension: Some(wgpu::TextureViewDimension::D2Array),
            ..Default::default()
        });
        res.insert_texture(noms::CASCADES, texture);
        let tampon = |nom: &str, taille: u64, usage: wgpu::BufferUsages| {
            dev.create_buffer(&wgpu::BufferDescriptor {
                label: Some(nom),
                size: taille,
                usage: usage | wgpu::BufferUsages::COPY_DST,
                mapped_at_creation: false,
            })
        };
        let uniforme = tampon(
            "ombres uniforme",
            size_of::<ShadowUniform>() as u64,
            wgpu::BufferUsages::UNIFORM,
        );
        res.insert_buffer(noms::UNIFORME, uniforme.clone());
        let remplissage = tampon(
            "ombres remplissage",
            (4 * size_of::<ShadowFillCascade>()) as u64,
            wgpu::BufferUsages::UNIFORM,
        );
        let tuiles = tampon(
            "ombres tuiles",
            u64::from(self.params.tiles_per_generation()) * size_of::<ShadowTileGpu>() as u64,
            wgpu::BufferUsages::STORAGE,
        );

        let c = wgpu::ShaderStages::COMPUTE;
        let entree = |binding: u32, ty: wgpu::BindingType| wgpu::BindGroupLayoutEntry {
            binding,
            visibility: c,
            ty,
            count: None,
        };
        let tampon_ty = |ty| wgpu::BindingType::Buffer {
            ty,
            has_dynamic_offset: false,
            min_binding_size: None,
        };
        let bgl = dev.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
            label: Some("ombres remplissage bgl"),
            entries: &[
                entree(0, tampon_ty(wgpu::BufferBindingType::Uniform)),
                entree(1, tampon_ty(wgpu::BufferBindingType::Storage { read_only: true })),
                entree(
                    2,
                    wgpu::BindingType::StorageTexture {
                        access: wgpu::StorageTextureAccess::WriteOnly,
                        format: wgpu::TextureFormat::R32Float,
                        view_dimension: wgpu::TextureViewDimension::D2Array,
                    },
                ),
            ],
        });
        let groupe = dev.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("ombres remplissage groupe"),
            layout: &bgl,
            entries: &[
                wgpu::BindGroupEntry {
                    binding: 0,
                    resource: remplissage.as_entire_binding(),
                },
                wgpu::BindGroupEntry {
                    binding: 1,
                    resource: tuiles.as_entire_binding(),
                },
                wgpu::BindGroupEntry {
                    binding: 2,
                    resource: wgpu::BindingResource::TextureView(&vue),
                },
            ],
        });
        let module = shaders::ombres_remplissage();
        let shader = dev.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some(module.nom()),
            source: wgpu::ShaderSource::Wgsl(module.source().into()),
        });
        let layout = dev.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
            label: Some("ombres remplissage layout"),
            bind_group_layouts: &[Some(&bgl), Some(self.monde.layout())],
            immediate_size: 0,
        });
        let pipeline = dev.create_compute_pipeline(&wgpu::ComputePipelineDescriptor {
            label: Some("ombres remplissage"),
            layout: Some(&layout),
            module: &shader,
            entry_point: Some("main"),
            compilation_options: Default::default(),
            cache: None,
        });
        self.gpu = Some(Gpu {
            pipeline,
            groupe,
            remplissage,
            tuiles,
            uniforme,
        });
    }

    fn encode(&mut self, ctx: &mut PassContext<'_>) {
        let Some(gpu) = &self.gpu else { return };
        let Some(cam) = ctx.frame().voxel_camera().copied() else {
            log::error!("voxel_ombres : le contexte d'image n'a pas de caméra voxel");
            return;
        };
        if self.controle.prendre() {
            self.planner.invalidate();
        }
        let (ciel, _) = self.ciel.lire();
        let camera_m = DVec3::from_array(cam.pos_mm().map(|v| v as f64 * 0.001));
        let plan = self.planner.plan(dvec(ciel.sun_direction()), camera_m);

        let n = self.params.cascades() as usize;
        let mut remplissages = [ShadowFillCascade::default(); 4];
        let mut lumiere = ShadowUniform {
            cfg0: [n as f32, 0.0, self.params.blend_fraction(), TAN_DEMI_SOLEIL],
            cfg1: [
                self.params.normal_offset(),
                self.params.depth_bias_m(),
                self.params.slope_bias(),
                self.params.penumbra_scale(),
            ],
            cfg2: [self.params.penumbra_max_m(), 0.0, 0.0, 0.0],
            ..Default::default()
        };
        #[allow(clippy::needless_range_loop)] // `c` indexe aussi le plan et les réglages
        for c in 0..n {
            if let Some(g) = plan.building(c) {
                remplissages[c] = remplissage(g);
            }
            if let Some(g) = plan.front(c) {
                lumiere.cfg0[1] = 1.0;
                lumiere.cascades[c] = cote_eclairage(g, camera_m, self.params.far_m(c as u32));
            }
        }
        let q = ctx.gpu().queue();
        q.write_buffer(&gpu.uniforme, 0, bytemuck::bytes_of(&lumiere));
        let jobs = plan.jobs();
        if !jobs.is_empty() {
            let liste: Vec<ShadowTileGpu> = jobs
                .iter()
                .map(|j| ShadowTileGpu {
                    tuile: [j.cascade(), j.tx(), j.ty(), 0],
                })
                .collect();
            q.write_buffer(&gpu.remplissage, 0, bytemuck::cast_slice(&remplissages));
            q.write_buffer(&gpu.tuiles, 0, bytemuck::cast_slice(&liste));
        }
        // La passe est toujours ouverte (même sans tuile) : le profil montre alors ~0 ms au lieu de s'absenter.
        let mut pass = ctx.compute_pass("voxel ombres");
        if jobs.is_empty() {
            return;
        }
        pass.set_pipeline(&gpu.pipeline);
        pass.set_bind_group(0, &gpu.groupe, &[]);
        pass.set_bind_group(1, self.monde.group(), &[]);
        pass.dispatch_workgroups(TUILE / 8, TUILE / 8, jobs.len() as u32);
    }
}
