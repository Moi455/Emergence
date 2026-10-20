//! `DepthMergePass` : convertit la distance du tracé en profondeur Z inversé infini (docs/19 § 5.1, ligne 7).
//! En L09 il n'y a pas de peau de terrain à fusionner (L17) : seul le tracé écrit la profondeur.

use super::gbuffer::{self, noms};
use super::shaders;
use crate::gpu::GpuContext;
use crate::graph::{PassContext, PassName, PassSetup, RenderPass, Resources};
use crate::liaisons::MiseEnPage;
use wgpu::ShaderStages as Etage;

struct Gpu {
    pipeline: wgpu::RenderPipeline,
    groupe: wgpu::BindGroup,
    profondeur: wgpu::TextureView,
}

/// Passe de fusion des profondeurs.
#[derive(Default)]
pub struct DepthMergePass {
    gpu: Option<Gpu>,
}

impl DepthMergePass {
    /// Nom de la passe dans le profil.
    pub const NOM: PassName = PassName::new("voxel_profondeur");

    /// Passe non préparée.
    pub fn new() -> Self {
        Self::default()
    }
}

impl RenderPass for DepthMergePass {
    fn name(&self) -> PassName {
        Self::NOM
    }

    fn prepare(&mut self, g: &GpuContext, _setup: &PassSetup, res: &mut Resources) {
        self.gpu = None;
        let (Some(frame), Some(dist), Some(profondeur)) = (
            res.buffer(noms::FRAME).cloned(),
            res.view(noms::DIST),
            res.view(noms::PROFONDEUR),
        ) else {
            log::error!("voxel_profondeur : le G-buffer manque");
            return;
        };
        let dev = g.device();
        let f = Etage::FRAGMENT;
        let bgl = MiseEnPage::new()
            .uniforme(f)
            .texture_float_brute(f)
            .creer(dev, "voxel profondeur bgl");
        let groupe = dev.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("voxel profondeur groupe"),
            layout: &bgl,
            entries: &[
                wgpu::BindGroupEntry {
                    binding: 0,
                    resource: frame.as_entire_binding(),
                },
                wgpu::BindGroupEntry {
                    binding: 1,
                    resource: wgpu::BindingResource::TextureView(&dist),
                },
            ],
        });
        let module = shaders::profondeur();
        let shader = dev.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some(module.nom()),
            source: wgpu::ShaderSource::Wgsl(module.source().into()),
        });
        let layout = dev.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
            label: Some("voxel profondeur layout"),
            bind_group_layouts: &[Some(&bgl)],
            immediate_size: 0,
        });
        let pipeline = dev.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
            label: Some("voxel profondeur"),
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
                targets: &[],
            }),
            primitive: wgpu::PrimitiveState::default(),
            depth_stencil: Some(wgpu::DepthStencilState {
                format: gbuffer::FORMAT_PROFONDEUR,
                depth_write_enabled: Some(true),
                depth_compare: Some(wgpu::CompareFunction::Always),
                stencil: wgpu::StencilState::default(),
                bias: wgpu::DepthBiasState::default(),
            }),
            multisample: wgpu::MultisampleState::default(),
            multiview_mask: None,
            cache: None,
        });
        self.gpu = Some(Gpu {
            pipeline,
            groupe,
            profondeur,
        });
    }

    fn encode(&mut self, ctx: &mut PassContext<'_>) {
        let Some(gpu) = &self.gpu else { return };
        let mut pass = ctx.render_pass_depth("voxel profondeur", &gpu.profondeur);
        pass.set_pipeline(&gpu.pipeline);
        pass.set_bind_group(0, &gpu.groupe, &[]);
        pass.draw(0..3, 0..1);
    }
}
