//! `BloomPass` : pyramide de 8 niveaux (descente de Karis, remontée additive) sur la cible HDR.

use crate::gpu::GpuContext;
use crate::graph::{PassContext, PassName, PassSetup, RenderPass, Resources};
use crate::liaisons::{HDR_FORMAT, MiseEnPage, echantillonneur_lineaire, texture_2d};
use crate::sky::noms;
use crate::sky::shaders::{self, ModuleWgsl};
use wgpu::ShaderStages as Etage;
use wgpu::util::DeviceExt;

/// Niveaux de la pyramide en préréglage `haut` (docs/19 § 1.4 ligne 16).
pub const NIVEAUX_BLOOM: u32 = 8;

struct Gpu {
    descente: wgpu::RenderPipeline,
    remontee: wgpu::RenderPipeline,
    vues: Vec<wgpu::TextureView>,
    groupes_descente: Vec<wgpu::BindGroup>,
    /// Remontée du niveau n-1 vers 0 : `(niveau source, groupe)`.
    groupes_remontee: Vec<(usize, wgpu::BindGroup)>,
}

/// Bloom à `niveaux` niveaux de demi-résolution décroissante ; publie la texture `bloom` (niveau 0).
pub struct BloomPass {
    niveaux: u32,
    gpu: Option<Gpu>,
}

impl BloomPass {
    /// Nom de la passe dans le profil.
    pub const NOM: PassName = PassName::new("bloom");
    /// Nom de la texture de bloom dans les ressources du graphe.
    pub const TEXTURE: crate::graph::ResourceName = crate::graph::ResourceName::new("bloom");

    /// Bloom à 8 niveaux (préréglage `haut`).
    pub fn new() -> Self {
        Self::avec_niveaux(NIVEAUX_BLOOM).expect("8 est un nombre de niveaux valide")
    }

    /// Bloom à `niveaux` niveaux, entre 2 et 8 (préréglages `moyen` : 6, `bas` : 4).
    pub fn avec_niveaux(niveaux: u32) -> Result<Self, crate::error::ParamError> {
        if !(2..=NIVEAUX_BLOOM).contains(&niveaux) {
            return Err(crate::error::ParamError::Invalide(format!(
                "bloom : {niveaux} niveaux hors de [2, {NIVEAUX_BLOOM}]"
            )));
        }
        Ok(Self { niveaux, gpu: None })
    }

    fn pipeline(
        dev: &wgpu::Device,
        module: &ModuleWgsl,
        layout: &wgpu::BindGroupLayout,
        blend: Option<wgpu::BlendState>,
    ) -> wgpu::RenderPipeline {
        let shader = dev.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some(module.nom()),
            source: wgpu::ShaderSource::Wgsl(module.source().into()),
        });
        let pl = dev.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
            label: Some(module.nom()),
            bind_group_layouts: &[Some(layout)],
            immediate_size: 0,
        });
        dev.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
            label: Some(module.nom()),
            layout: Some(&pl),
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
                    blend,
                    write_mask: wgpu::ColorWrites::ALL,
                })],
            }),
            primitive: wgpu::PrimitiveState::default(),
            depth_stencil: None,
            multisample: wgpu::MultisampleState::default(),
            multiview_mask: None,
            cache: None,
        })
    }
}

impl Default for BloomPass {
    fn default() -> Self {
        Self::new()
    }
}

impl RenderPass for BloomPass {
    fn name(&self) -> PassName {
        Self::NOM
    }

    fn prepare(&mut self, g: &GpuContext, setup: &PassSetup, res: &mut Resources) {
        self.gpu = None;
        let Some(hdr) = res.view(noms::HDR) else {
            log::error!("bloom : la cible HDR manque (SkyBackgroundPass doit précéder cette passe)");
            return;
        };
        let dev = g.device();
        let (l, h) = (setup.size.0, setup.size.1);
        let (bw, bh) = ((l / 2).max(1), (h / 2).max(1));
        // Nombre de niveaux que la texture peut porter (jusqu'à 1 x 1).
        let max_niveaux = bw.max(bh).ilog2() + 1;
        let niveaux = self.niveaux.min(max_niveaux);
        let texture = texture_2d(
            dev,
            "bloom",
            (bw, bh),
            niveaux,
            wgpu::TextureUsages::RENDER_ATTACHMENT | wgpu::TextureUsages::TEXTURE_BINDING,
        );
        let vues: Vec<wgpu::TextureView> = (0..niveaux)
            .map(|m| {
                texture.create_view(&wgpu::TextureViewDescriptor {
                    label: Some("bloom niveau"),
                    base_mip_level: m,
                    mip_level_count: Some(1),
                    ..Default::default()
                })
            })
            .collect();
        let f = Etage::FRAGMENT;
        let bgl = MiseEnPage::new()
            .texture(f)
            .echantillonneur(f)
            .uniforme(f)
            .creer(dev, "bloom bgl");
        let ech = echantillonneur_lineaire(dev);
        let ubo = |valeurs: [f32; 4]| {
            dev.create_buffer_init(&wgpu::util::BufferInitDescriptor {
                label: Some("bloom ubo"),
                contents: bytemuck::bytes_of(&valeurs),
                usage: wgpu::BufferUsages::UNIFORM,
            })
        };
        let groupe = |src: &wgpu::TextureView, u: &wgpu::Buffer| {
            dev.create_bind_group(&wgpu::BindGroupDescriptor {
                label: Some("bloom groupe"),
                layout: &bgl,
                entries: &[
                    wgpu::BindGroupEntry {
                        binding: 0,
                        resource: wgpu::BindingResource::TextureView(src),
                    },
                    wgpu::BindGroupEntry {
                        binding: 1,
                        resource: wgpu::BindingResource::Sampler(&ech),
                    },
                    wgpu::BindGroupEntry {
                        binding: 2,
                        resource: u.as_entire_binding(),
                    },
                ],
            })
        };
        // Descente : le niveau m lit le niveau m-1 (le HDR pour m = 0, avec la moyenne de Karis).
        let mut groupes_descente = Vec::new();
        for m in 0..niveaux as usize {
            let (sw, sh) = if m == 0 {
                (l, h)
            } else {
                ((bw >> (m - 1)).max(1), (bh >> (m - 1)).max(1))
            };
            let u = ubo([
                1.0 / sw as f32,
                1.0 / sh as f32,
                if m == 0 { 1.0 } else { 0.0 },
                0.0,
            ]);
            let src = if m == 0 { &hdr } else { &vues[m - 1] };
            groupes_descente.push(groupe(src, &u));
        }
        // Remontée : le niveau m s'ajoute au niveau m-1.
        let mut groupes_remontee = Vec::new();
        for m in (1..niveaux as usize).rev() {
            let (sw, sh) = ((bw >> m).max(1), (bh >> m).max(1));
            let u = ubo([1.0 / sw as f32, 1.0 / sh as f32, 1.0, 1.0]);
            groupes_remontee.push((m, groupe(&vues[m], &u)));
        }
        let additif = wgpu::BlendComponent {
            src_factor: wgpu::BlendFactor::One,
            dst_factor: wgpu::BlendFactor::One,
            operation: wgpu::BlendOperation::Add,
        };
        self.gpu = Some(Gpu {
            descente: Self::pipeline(dev, &shaders::bloom_descente(), &bgl, None),
            remontee: Self::pipeline(
                dev,
                &shaders::bloom_remontee(),
                &bgl,
                Some(wgpu::BlendState {
                    color: additif,
                    alpha: additif,
                }),
            ),
            vues,
            groupes_descente,
            groupes_remontee,
        });
        res.insert_texture(Self::TEXTURE, texture);
    }

    fn encode(&mut self, ctx: &mut PassContext<'_>) {
        let Some(gpu) = &self.gpu else { return };
        for (m, groupe) in gpu.groupes_descente.iter().enumerate() {
            let mut pass = ctx.render_pass_to(
                "bloom descente",
                &gpu.vues[m],
                wgpu::LoadOp::Clear(wgpu::Color::BLACK),
            );
            pass.set_pipeline(&gpu.descente);
            pass.set_bind_group(0, groupe, &[]);
            pass.draw(0..3, 0..1);
        }
        for (m, groupe) in &gpu.groupes_remontee {
            let mut pass = ctx.render_pass_to("bloom remontée", &gpu.vues[m - 1], wgpu::LoadOp::Load);
            pass.set_pipeline(&gpu.remontee);
            pass.set_bind_group(0, groupe, &[]);
            pass.draw(0..3, 0..1);
        }
    }
}
