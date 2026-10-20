//! `SkyBackgroundPass` : le fond de ciel en HDR, producteur de la ressource `hdr`.

use super::noms;
use super::shaders;
use crate::gpu::GpuContext;
use crate::graph::{PassContext, PassName, PassSetup, RenderPass, Resources};
use crate::liaisons::{HDR_FORMAT, MiseEnPage, echantillonneur_lineaire, texture_2d};
use wgpu::ShaderStages as Etage;

struct Gpu {
    /// Étage 1 : ciel et nuages en demi-résolution.
    pipeline_ciel: wgpu::RenderPipeline,
    groupe_ciel: wgpu::BindGroup,
    vue_demi: wgpu::TextureView,
    /// Étage 2 : composition en pleine résolution.
    pipeline_fond: wgpu::RenderPipeline,
    groupe_fond: wgpu::BindGroup,
    vue_hdr: wgpu::TextureView,
}

/// Dessine ciel, nuages, soleil, crêtes, sol, étoiles et perspective aérienne dans la cible HDR, en deux
/// étages : (1) ciel de Hillaire et nuages en DEMI-résolution (le gros du coût), (2) composition en pleine
/// résolution (disque solaire net, crêtes anticrénelées, sol, étoiles). Doit suivre `SkyPass` dans le graphe (il lit ses LUT et son uniforme).
#[derive(Default)]
pub struct SkyBackgroundPass {
    gpu: Option<Gpu>,
}

impl SkyBackgroundPass {
    /// Nom de la passe dans le profil.
    pub const NOM: PassName = PassName::new("ciel_fond");

    /// Passe non préparée.
    pub fn new() -> Self {
        Self::default()
    }
}

impl RenderPass for SkyBackgroundPass {
    fn name(&self) -> PassName {
        Self::NOM
    }

    fn prepare(&mut self, g: &GpuContext, setup: &PassSetup, res: &mut Resources) {
        self.gpu = None;
        let (Some(frame), Some(vue_trans), Some(vue_ciel), Some(vue_cretes)) = (
            res.buffer(noms::FRAME).cloned(),
            res.view(noms::TRANSMITTANCE),
            res.view(noms::VUE_DU_CIEL),
            res.view(noms::CRETES),
        ) else {
            log::error!("ciel_fond : les LUT du ciel manquent (SkyPass doit précéder cette passe)");
            return;
        };
        let dev = g.device();
        let hdr = texture_2d(
            dev,
            "hdr",
            setup.size,
            1,
            wgpu::TextureUsages::RENDER_ATTACHMENT
                | wgpu::TextureUsages::TEXTURE_BINDING
                | wgpu::TextureUsages::COPY_SRC,
        );
        let vue_hdr = hdr.create_view(&wgpu::TextureViewDescriptor::default());
        res.insert_texture(noms::HDR, hdr);

        let demi = texture_2d(
            dev,
            "ciel demi-résolution",
            ((setup.size.0 / 2).max(1), (setup.size.1 / 2).max(1)),
            1,
            wgpu::TextureUsages::RENDER_ATTACHMENT | wgpu::TextureUsages::TEXTURE_BINDING,
        );
        let vue_demi = demi.create_view(&wgpu::TextureViewDescriptor::default());

        let f = Etage::FRAGMENT;
        let bgl_ciel = MiseEnPage::new()
            .uniforme(f)
            .texture(f)
            .texture(f)
            .echantillonneur(f)
            .creer(dev, "fond étage 1 bgl");
        let bgl_fond = MiseEnPage::new()
            .uniforme(f)
            .texture(f)
            .texture(f)
            .echantillonneur(f)
            .texture(f)
            .texture(f)
            .creer(dev, "fond étage 2 bgl");
        let ech = echantillonneur_lineaire(dev);
        let entree = |binding: u32, resource| wgpu::BindGroupEntry { binding, resource };
        let groupe_ciel = dev.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("fond étage 1 groupe"),
            layout: &bgl_ciel,
            entries: &[
                entree(0, frame.as_entire_binding()),
                entree(1, wgpu::BindingResource::TextureView(&vue_trans)),
                entree(2, wgpu::BindingResource::TextureView(&vue_ciel)),
                entree(3, wgpu::BindingResource::Sampler(&ech)),
            ],
        });
        let groupe_fond = dev.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("fond étage 2 groupe"),
            layout: &bgl_fond,
            entries: &[
                entree(0, frame.as_entire_binding()),
                entree(1, wgpu::BindingResource::TextureView(&vue_trans)),
                entree(2, wgpu::BindingResource::TextureView(&vue_ciel)),
                entree(3, wgpu::BindingResource::Sampler(&ech)),
                entree(4, wgpu::BindingResource::TextureView(&vue_demi)),
                entree(5, wgpu::BindingResource::TextureView(&vue_cretes)),
            ],
        });
        let module = shaders::fond_de_ciel();
        let shader = dev.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some(module.nom()),
            source: wgpu::ShaderSource::Wgsl(module.source().into()),
        });
        let pipeline = |bgl: &wgpu::BindGroupLayout, fs: &str| {
            let layout = dev.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
                label: Some("fond layout"),
                bind_group_layouts: &[Some(bgl)],
                immediate_size: 0,
            });
            dev.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
                label: Some(fs),
                layout: Some(&layout),
                vertex: wgpu::VertexState {
                    module: &shader,
                    entry_point: Some("vs"),
                    compilation_options: Default::default(),
                    buffers: &[],
                },
                fragment: Some(wgpu::FragmentState {
                    module: &shader,
                    entry_point: Some(fs),
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
            })
        };
        self.gpu = Some(Gpu {
            pipeline_ciel: pipeline(&bgl_ciel, "fs_ciel"),
            groupe_ciel,
            vue_demi,
            pipeline_fond: pipeline(&bgl_fond, "fs"),
            groupe_fond,
            vue_hdr,
        });
    }

    fn encode(&mut self, ctx: &mut PassContext<'_>) {
        let Some(gpu) = &self.gpu else { return };
        {
            let mut pass = ctx.render_pass_to(
                "ciel étage 1",
                &gpu.vue_demi,
                wgpu::LoadOp::Clear(wgpu::Color::BLACK),
            );
            pass.set_pipeline(&gpu.pipeline_ciel);
            pass.set_bind_group(0, &gpu.groupe_ciel, &[]);
            pass.draw(0..3, 0..1);
        }
        let mut pass = ctx.render_pass_to(
            "ciel étage 2",
            &gpu.vue_hdr,
            wgpu::LoadOp::Clear(wgpu::Color::BLACK),
        );
        pass.set_pipeline(&gpu.pipeline_fond);
        pass.set_bind_group(0, &gpu.groupe_fond, &[]);
        pass.draw(0..3, 0..1);
    }
}
