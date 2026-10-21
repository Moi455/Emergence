//! `MeshAmbientPass` : l'ambiance du ciel des six faces d'un voxel et l'éclairement du soleil, calculés une fois par
//! image dans une texture de 7 x 1 que lit le fragment du maillage (au lieu de 8 lectures du ciel par pixel).

use super::shaders;
use crate::gpu::GpuContext;
use crate::graph::{PassContext, PassName, PassSetup, RenderPass, ResourceName, Resources};
use crate::liaisons::{
    HDR_FORMAT, MiseEnPage, echantillonneur_lineaire, entree_tampon, entree_vue, texture_2d,
};
use crate::sky::noms as noms_ciel;
use wgpu::ShaderStages as Etage;

/// Texture d'ambiance (7 x 1, `Rgba16Float`) publiée dans le graphe.
pub const AMBIANCE: ResourceName = ResourceName::new("mesh_ambiance");

struct Gpu {
    pipeline: wgpu::RenderPipeline,
    groupe: wgpu::BindGroup,
    vue: wgpu::TextureView,
}

/// Passe d'ambiance du ciel du rendu par maillage.
#[derive(Default)]
pub struct MeshAmbientPass {
    gpu: Option<Gpu>,
}

impl MeshAmbientPass {
    /// Nom de la passe dans le profil.
    pub const NOM: PassName = PassName::new("maillage_ambiance");

    /// Passe non préparée.
    pub fn new() -> Self {
        Self::default()
    }
}

impl RenderPass for MeshAmbientPass {
    fn name(&self) -> PassName {
        Self::NOM
    }

    fn prepare(&mut self, g: &GpuContext, _setup: &PassSetup, res: &mut Resources) {
        self.gpu = None;
        let (Some(frame), Some(trans), Some(ciel)) = (
            res.buffer(noms_ciel::FRAME).cloned(),
            res.view(noms_ciel::TRANSMITTANCE),
            res.view(noms_ciel::VUE_DU_CIEL),
        ) else {
            log::error!("maillage_ambiance : le ciel manque (SkyPass doit précéder)");
            return;
        };
        let dev = g.device();
        let f = Etage::FRAGMENT;
        let bgl = MiseEnPage::new()
            .uniforme(f)
            .texture(f)
            .texture(f)
            .echantillonneur(f)
            .creer(dev, "maillage ambiance bgl");
        let texture = texture_2d(
            dev,
            "maillage ambiance",
            (7, 1),
            1,
            wgpu::TextureUsages::RENDER_ATTACHMENT | wgpu::TextureUsages::TEXTURE_BINDING,
        );
        let vue = texture.create_view(&wgpu::TextureViewDescriptor::default());
        res.insert_texture(AMBIANCE, texture);
        let ech = echantillonneur_lineaire(dev);
        let groupe = dev.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("maillage ambiance groupe"),
            layout: &bgl,
            entries: &[
                entree_tampon(0, &frame),
                entree_vue(1, &trans),
                entree_vue(2, &ciel),
                wgpu::BindGroupEntry {
                    binding: 3,
                    resource: wgpu::BindingResource::Sampler(&ech),
                },
            ],
        });
        let module = shaders::ambiance();
        let shader = dev.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some(module.nom()),
            source: wgpu::ShaderSource::Wgsl(module.source().into()),
        });
        let layout = dev.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
            label: Some("maillage ambiance layout"),
            bind_group_layouts: &[Some(&bgl)],
            immediate_size: 0,
        });
        let pipeline = dev.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
            label: Some("maillage ambiance"),
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
                    format: HDR_FORMAT,
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
            vue,
        });
    }

    fn encode(&mut self, ctx: &mut PassContext<'_>) {
        let Some(gpu) = &self.gpu else { return };
        let mut pass = ctx.render_pass_to(
            "maillage ambiance",
            &gpu.vue,
            wgpu::LoadOp::Clear(wgpu::Color::BLACK),
        );
        pass.set_pipeline(&gpu.pipeline);
        pass.set_bind_group(0, &gpu.groupe, &[]);
        pass.draw(0..3, 0..1);
    }
}
