//! `TonemapPass` : composition finale AgX (exposition, bloom, regard, vignette, tramage) vers la cible sRGB.

use super::bloom::BloomPass;
use super::params::PostParams;
use crate::gpu::GpuContext;
use crate::graph::{PassContext, PassName, PassSetup, RenderPass, Resources};
use crate::liaisons::{MiseEnPage, echantillonneur_lineaire};
use crate::partage::Partage;
use crate::sky::noms;
use crate::sky::shaders;
use bytemuck::{Pod, Zeroable};
use wgpu::ShaderStages as Etage;

/// Uniforme `P` du shader COMPOSITE : `p` = exposition, bloom, numéro d'image, vignette ;
/// `q` = saturation, contraste, chaleur, grain.
#[repr(C)]
#[derive(Clone, Copy, Pod, Zeroable)]
struct UniformeComposition {
    p: [f32; 4],
    q: [f32; 4],
}

struct Gpu {
    pipeline: wgpu::RenderPipeline,
    groupe: wgpu::BindGroup,
    ubo: wgpu::Buffer,
}

/// Passe finale : lit `hdr` et `bloom`, écrit la cible de l'image (sRGB) ; le tramage tourne sur 64 images.
pub struct TonemapPass {
    params: Partage<PostParams>,
    gpu: Option<Gpu>,
}

impl TonemapPass {
    /// Nom de la passe dans le profil.
    pub const NOM: PassName = PassName::new("tonemap");

    /// Crée la passe sur des réglages partagés avec la scène.
    pub fn new(params: Partage<PostParams>) -> Self {
        Self { params, gpu: None }
    }
}

impl RenderPass for TonemapPass {
    fn name(&self) -> PassName {
        Self::NOM
    }

    fn prepare(&mut self, g: &GpuContext, setup: &PassSetup, res: &mut Resources) {
        self.gpu = None;
        let (Some(hdr), Some(bloom)) = (res.view(noms::HDR), res.view(BloomPass::TEXTURE)) else {
            log::error!("tonemap : HDR ou bloom manquent (le ciel et le bloom doivent précéder)");
            return;
        };
        let dev = g.device();
        let f = Etage::FRAGMENT;
        let bgl = MiseEnPage::new()
            .texture(f)
            .texture(f)
            .echantillonneur(f)
            .uniforme(f)
            .creer(dev, "tonemap bgl");
        let ubo = dev.create_buffer(&wgpu::BufferDescriptor {
            label: Some("tonemap ubo"),
            size: std::mem::size_of::<UniformeComposition>() as u64,
            usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        });
        let ech = echantillonneur_lineaire(dev);
        let groupe = dev.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("tonemap groupe"),
            layout: &bgl,
            entries: &[
                wgpu::BindGroupEntry {
                    binding: 0,
                    resource: wgpu::BindingResource::TextureView(&hdr),
                },
                wgpu::BindGroupEntry {
                    binding: 1,
                    resource: wgpu::BindingResource::TextureView(&bloom),
                },
                wgpu::BindGroupEntry {
                    binding: 2,
                    resource: wgpu::BindingResource::Sampler(&ech),
                },
                wgpu::BindGroupEntry {
                    binding: 3,
                    resource: ubo.as_entire_binding(),
                },
            ],
        });
        let module = shaders::composition();
        let shader = dev.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some(module.nom()),
            source: wgpu::ShaderSource::Wgsl(module.source().into()),
        });
        let layout = dev.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
            label: Some("tonemap layout"),
            bind_group_layouts: &[Some(&bgl)],
            immediate_size: 0,
        });
        let pipeline = dev.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
            label: Some("tonemap"),
            layout: Some(&layout),
            vertex: wgpu::VertexState {
                module: &shader,
                entry_point: Some("vs"),
                compilation_options: Default::default(),
                buffers: &[],
            },
            fragment: Some(wgpu::FragmentState {
                module: &shader,
                entry_point: Some("fs"),
                compilation_options: Default::default(),
                targets: &[Some(wgpu::ColorTargetState {
                    format: setup.format,
                    blend: None,
                    write_mask: wgpu::ColorWrites::ALL,
                })],
            }),
            primitive: wgpu::PrimitiveState::default(),
            depth_stencil: None,
            multisample: wgpu::MultisampleState::default(),
            multiview_mask: None,
            cache: None,
        });
        self.gpu = Some(Gpu {
            pipeline,
            groupe,
            ubo,
        });
    }

    fn encode(&mut self, ctx: &mut PassContext<'_>) {
        let Some(gpu) = &self.gpu else { return };
        let (p, _) = self.params.lire();
        let u = UniformeComposition {
            p: [
                p.exposure(),
                p.bloom(),
                (ctx.frame().index() % 64) as f32,
                p.vignette(),
            ],
            q: [p.saturation(), p.contrast(), p.warmth(), 0.0],
        };
        ctx.gpu()
            .queue()
            .write_buffer(&gpu.ubo, 0, bytemuck::bytes_of(&u));
        let mut pass = ctx.render_pass("tonemap", wgpu::LoadOp::Clear(wgpu::Color::BLACK));
        pass.set_pipeline(&gpu.pipeline);
        pass.set_bind_group(0, &gpu.groupe, &[]);
        pass.draw(0..3, 0..1);
    }
}
