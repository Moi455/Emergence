//! `VoxelTracePass` : lancer de rayons primaire en COMPUTE dans la clipmap de briques (docs/19 § 4.5). Un rayon par
//! pixel, DDA hiérarchique chunk -> brique -> voxel ; écrit l'impact brut (valeur, face, voxel touché) et la
//! distance. Crée aussi les textures du G-buffer et l'uniforme d'image que les passes suivantes lisent.

use super::gbuffer::{self, noms};
use super::gpu::VoxelFrame;
use super::shaders;
use super::world::WorldBindings;
use crate::camera::FrameContext;
use crate::gpu::GpuContext;
use crate::graph::{PassContext, PassName, PassSetup, RenderPass, Resources};
use crate::liaisons::MiseEnPage;
use crate::voxel::camera::{Projection, VoxelCamera};
use wgpu::ShaderStages as Etage;

/// Portée maximale d'un rayon primaire, en voxels (la fenêtre du niveau 0 mesure 1 024 voxels de côté).
const PORTEE_VOXELS: f32 = 4_000.0;

impl VoxelFrame {
    /// Compose l'uniforme d'image depuis le contexte d'image et la caméra voxel.
    pub fn compose(f: &FrameContext, cam: &VoxelCamera) -> Self {
        let (w, h) = (f.width() as f32, f.height() as f32);
        let aspect = f.aspect();
        let (d, u, a) = (cam.droite(), cam.haut(), cam.avant());
        let (right, up, ortho) = match cam.projection() {
            Projection::Perspective { .. } => {
                let (tx, ty) = cam.demi_tangentes(aspect);
                (d * tx, u * ty, 0.0)
            }
            Projection::Orthographic { height_m } => {
                let voxels = |m: f32| m / VOXEL_M;
                (
                    d * voxels(height_m * 0.5 * aspect),
                    u * voxels(height_m * 0.5),
                    1.0,
                )
            }
        };
        let v = cam.voxel();
        let fr = cam.fraction_voxels();
        Self {
            ray_right: [right.x, right.y, right.z, 0.0],
            ray_up: [up.x, up.y, up.z, 0.0],
            ray_fwd: [a.x, a.y, a.z, ortho],
            cam_voxel: [v[0], v[1], v[2], f.index() as i32],
            cam_frac: [fr[0], fr[1], fr[2], f.time_s()],
            screen: [w, h, 1.0 / w, 1.0 / h],
            params: [VoxelCamera::PROCHE_M, PORTEE_VOXELS, 0.0, 0.0],
        }
    }
}

/// Taille d'un voxel de niveau 0 en mètres.
const VOXEL_M: f32 = em_core::VOXEL_MM as f32 * 0.001;

struct Gpu {
    pipeline: wgpu::ComputePipeline,
    groupe: wgpu::BindGroup,
    frame: wgpu::Buffer,
}

/// Passe de tracé primaire.
pub struct VoxelTracePass {
    monde: WorldBindings,
    gpu: Option<Gpu>,
}

impl VoxelTracePass {
    /// Nom de la passe dans le profil.
    pub const NOM: PassName = PassName::new("voxel_trace");

    /// Crée la passe sur les liaisons du monde (injection par le constructeur).
    pub fn new(monde: WorldBindings) -> Self {
        Self { monde, gpu: None }
    }
}

impl RenderPass for VoxelTracePass {
    fn name(&self) -> PassName {
        Self::NOM
    }

    fn prepare(&mut self, g: &GpuContext, setup: &PassSetup, res: &mut Resources) {
        let dev = g.device();
        gbuffer::creer(dev, setup.size, res);
        let (Some(frame), Some(hit), Some(dist)) = (
            res.buffer(noms::FRAME).cloned(),
            res.view(noms::HIT),
            res.view(noms::DIST),
        ) else {
            self.gpu = None;
            return;
        };
        let c = Etage::COMPUTE;
        let bgl = MiseEnPage::new()
            .uniforme(c)
            .stockage_ecriture(c, gbuffer::FORMAT_HIT)
            .stockage_ecriture(c, gbuffer::FORMAT_DIST)
            .creer(dev, "voxel trace bgl");
        let groupe = dev.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("voxel trace groupe"),
            layout: &bgl,
            entries: &[
                wgpu::BindGroupEntry {
                    binding: 0,
                    resource: frame.as_entire_binding(),
                },
                wgpu::BindGroupEntry {
                    binding: 1,
                    resource: wgpu::BindingResource::TextureView(&hit),
                },
                wgpu::BindGroupEntry {
                    binding: 2,
                    resource: wgpu::BindingResource::TextureView(&dist),
                },
            ],
        });
        let module = shaders::trace();
        let shader = dev.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some(module.nom()),
            source: wgpu::ShaderSource::Wgsl(module.source().into()),
        });
        let layout = dev.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
            label: Some("voxel trace layout"),
            bind_group_layouts: &[Some(&bgl), Some(self.monde.layout())],
            immediate_size: 0,
        });
        let pipeline = dev.create_compute_pipeline(&wgpu::ComputePipelineDescriptor {
            label: Some("voxel trace"),
            layout: Some(&layout),
            module: &shader,
            entry_point: Some("main"),
            compilation_options: Default::default(),
            cache: None,
        });
        self.gpu = Some(Gpu {
            pipeline,
            groupe,
            frame,
        });
    }

    fn encode(&mut self, ctx: &mut PassContext<'_>) {
        let Some(gpu) = &self.gpu else { return };
        let Some(cam) = ctx.frame().voxel_camera().copied() else {
            log::error!("voxel_trace : le contexte d'image n'a pas de caméra voxel");
            return;
        };
        let u = VoxelFrame::compose(ctx.frame(), &cam);
        ctx.gpu()
            .queue()
            .write_buffer(&gpu.frame, 0, bytemuck::bytes_of(&u));
        let (l, h) = (ctx.frame().width(), ctx.frame().height());
        let mut pass = ctx.compute_pass("voxel trace");
        pass.set_pipeline(&gpu.pipeline);
        pass.set_bind_group(0, &gpu.groupe, &[]);
        pass.set_bind_group(1, self.monde.group(), &[]);
        pass.dispatch_workgroups(l.div_ceil(8), h.div_ceil(8), 1);
    }
}
