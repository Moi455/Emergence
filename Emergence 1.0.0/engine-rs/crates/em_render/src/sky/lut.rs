//! `SkyPass` : LUT d'atmosphère de Hillaire. Recalcul paresseux (docs/19 § 1.4 ligne 2).

use super::gpu::{AtmoUniforme, SkyFrame};
use super::noms;
use super::params::SkyParams;
use super::shaders::{self, ModuleWgsl};
use crate::gpu::GpuContext;
use crate::graph::{PassContext, PassName, PassSetup, RenderPass, Resources};
use crate::liaisons::{HDR_FORMAT, MiseEnPage, echantillonneur_lineaire, texture_2d};
use crate::partage::Partage;
use wgpu::ShaderStages as Etage;

/// Taille de la LUT de transmittance (module `trans_lut`).
const TRANS: (u32, u32) = (256, 64);
/// Taille de la LUT de diffusion multiple.
const MS: (u32, u32) = (32, 32);
/// Taille de la LUT de vue du ciel.
const VUE: (u32, u32) = (256, 144);
/// Nombre d'azimuts de la LUT des crêtes (miroir de `crete_lut.wgsl`).
const CRETES_N: u32 = 4096;

/// Ce qui a servi au dernier calcul des LUT : sert à décider d'un recalcul.
#[derive(Clone, Copy, PartialEq)]
struct Empreinte {
    turbidite: f32,
    soleil_y: f32,
    altitude_km: f32,
}

/// Objets GPU de la passe, recréés par `prepare`.
struct Gpu {
    frame: wgpu::Buffer,
    atmo: wgpu::Buffer,
    pipe_trans: wgpu::ComputePipeline,
    pipe_ms: wgpu::ComputePipeline,
    pipe_vue: wgpu::ComputePipeline,
    groupe_trans: wgpu::BindGroup,
    groupe_ms: wgpu::BindGroup,
    groupe_vue: wgpu::BindGroup,
    pipe_cretes: wgpu::ComputePipeline,
    groupe_cretes: wgpu::BindGroup,
    cretes_a_faire: bool,
}

/// LUT d'atmosphère + uniforme `Frame` du ciel.
pub struct SkyPass {
    params: Partage<SkyParams>,
    gpu: Option<Gpu>,
    derniere: Option<Empreinte>,
}

impl SkyPass {
    /// Nom de la passe dans le profil.
    pub const NOM: PassName = PassName::new("ciel_lut");

    /// Crée la passe sur des paramètres partagés avec la scène.
    pub fn new(params: Partage<SkyParams>) -> Self {
        Self {
            params,
            gpu: None,
            derniere: None,
        }
    }

    fn pipeline(
        dev: &wgpu::Device,
        module: &ModuleWgsl,
        layout: &wgpu::BindGroupLayout,
    ) -> wgpu::ComputePipeline {
        let shader = dev.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some(module.nom()),
            source: wgpu::ShaderSource::Wgsl(module.source().into()),
        });
        let pl = dev.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
            label: Some(module.nom()),
            bind_group_layouts: &[Some(layout)],
            immediate_size: 0,
        });
        dev.create_compute_pipeline(&wgpu::ComputePipelineDescriptor {
            label: Some(module.nom()),
            layout: Some(&pl),
            module: &shader,
            entry_point: Some("main"),
            compilation_options: Default::default(),
            cache: None,
        })
    }
}

fn entree(binding: u32, resource: wgpu::BindingResource<'_>) -> wgpu::BindGroupEntry<'_> {
    wgpu::BindGroupEntry { binding, resource }
}

impl RenderPass for SkyPass {
    fn name(&self) -> PassName {
        Self::NOM
    }

    fn prepare(&mut self, g: &GpuContext, _setup: &PassSetup, res: &mut Resources) {
        let dev = g.device();
        let usage_lut = wgpu::TextureUsages::STORAGE_BINDING
            | wgpu::TextureUsages::TEXTURE_BINDING
            | wgpu::TextureUsages::COPY_SRC;
        let trans = texture_2d(dev, "ciel transmittance", TRANS, 1, usage_lut);
        let ms = texture_2d(dev, "ciel diffusion multiple", MS, 1, usage_lut);
        let vue = texture_2d(dev, "ciel vue", VUE, 1, usage_lut);
        let vt = trans.create_view(&wgpu::TextureViewDescriptor::default());
        let vm = ms.create_view(&wgpu::TextureViewDescriptor::default());
        let vv = vue.create_view(&wgpu::TextureViewDescriptor::default());
        let frame = dev.create_buffer(&wgpu::BufferDescriptor {
            label: Some("ciel frame"),
            size: std::mem::size_of::<SkyFrame>() as u64,
            usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        });
        let atmo = dev.create_buffer(&wgpu::BufferDescriptor {
            label: Some("ciel atmosphère"),
            size: std::mem::size_of::<AtmoUniforme>() as u64,
            usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        });
        let ech = echantillonneur_lineaire(dev);
        let c = Etage::COMPUTE;
        let cretes = texture_2d(dev, "ciel crêtes", (CRETES_N, 1), 1, usage_lut);
        let vc = cretes.create_view(&wgpu::TextureViewDescriptor::default());
        let bgl_cretes = MiseEnPage::new()
            .stockage_ecriture(c, HDR_FORMAT)
            .creer(dev, "crêtes bgl");
        let groupe_cretes = dev.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("crêtes groupe"),
            layout: &bgl_cretes,
            entries: &[entree(0, wgpu::BindingResource::TextureView(&vc))],
        });

        // trans : A (0), dst (1)
        let bgl_trans = MiseEnPage::new()
            .uniforme(c)
            .stockage_ecriture(c, HDR_FORMAT)
            .creer(dev, "trans bgl");
        // ms : A (0), transLUT (1), sampC (2), dst (3)
        let bgl_ms = MiseEnPage::new()
            .uniforme(c)
            .texture(c)
            .echantillonneur(c)
            .stockage_ecriture(c, HDR_FORMAT)
            .creer(dev, "ms bgl");
        // vue : F (0), transLUT (1), msLUT (2), sampC (3), dst (4)
        let bgl_vue = MiseEnPage::new()
            .uniforme(c)
            .texture(c)
            .texture(c)
            .echantillonneur(c)
            .stockage_ecriture(c, HDR_FORMAT)
            .creer(dev, "vue bgl");

        let groupe_trans = dev.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("trans groupe"),
            layout: &bgl_trans,
            entries: &[
                entree(0, atmo.as_entire_binding()),
                entree(1, wgpu::BindingResource::TextureView(&vt)),
            ],
        });
        let groupe_ms = dev.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("ms groupe"),
            layout: &bgl_ms,
            entries: &[
                entree(0, atmo.as_entire_binding()),
                entree(1, wgpu::BindingResource::TextureView(&vt)),
                entree(2, wgpu::BindingResource::Sampler(&ech)),
                entree(3, wgpu::BindingResource::TextureView(&vm)),
            ],
        });
        let groupe_vue = dev.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("vue groupe"),
            layout: &bgl_vue,
            entries: &[
                entree(0, frame.as_entire_binding()),
                entree(1, wgpu::BindingResource::TextureView(&vt)),
                entree(2, wgpu::BindingResource::TextureView(&vm)),
                entree(3, wgpu::BindingResource::Sampler(&ech)),
                entree(4, wgpu::BindingResource::TextureView(&vv)),
            ],
        });
        self.gpu = Some(Gpu {
            pipe_trans: Self::pipeline(dev, &shaders::transmittance(), &bgl_trans),
            pipe_ms: Self::pipeline(dev, &shaders::diffusion_multiple(), &bgl_ms),
            pipe_vue: Self::pipeline(dev, &shaders::vue_du_ciel(), &bgl_vue),
            pipe_cretes: Self::pipeline(dev, &shaders::cretes(), &bgl_cretes),
            groupe_cretes,
            cretes_a_faire: true,
            frame: frame.clone(),
            atmo,
            groupe_trans,
            groupe_ms,
            groupe_vue,
        });
        res.insert_texture(noms::TRANSMITTANCE, trans);
        res.insert_texture(noms::VUE_DU_CIEL, vue);
        res.insert_texture(noms::CRETES, cretes);
        res.insert_buffer(noms::FRAME, frame);
        // Les LUT neuves sont vides : tout recalculer.
        self.derniere = None;
    }

    fn encode(&mut self, ctx: &mut PassContext<'_>) {
        let Some(gpu) = self.gpu.as_mut() else { return };
        let (params, _revision) = self.params.lire();
        let uniforme = SkyFrame::compose(&params, ctx.frame());
        ctx.gpu()
            .queue()
            .write_buffer(&gpu.frame, 0, bytemuck::bytes_of(&uniforme));

        let maintenant = Empreinte {
            turbidite: params.turbidity(),
            soleil_y: params.sun_direction().y,
            altitude_km: SkyFrame::altitude_km(ctx.frame().view().position().y),
        };
        let precedente = self.derniere;
        let atmo_change = precedente.is_none_or(|p| p.turbidite != maintenant.turbidite);
        let vue_change = atmo_change
            || precedente.is_none_or(|p| {
                p.soleil_y != maintenant.soleil_y || (p.altitude_km - maintenant.altitude_km).abs() > 1e-4
            });
        if !vue_change && !gpu.cretes_a_faire {
            return; // rien ne bouge : aucune passe, coût nul (docs/19 § 1.4)
        }
        self.derniere = Some(maintenant);
        if atmo_change {
            let a = AtmoUniforme {
                haze: [params.turbidity(), 0.0, 0.0, 0.0],
            };
            ctx.gpu()
                .queue()
                .write_buffer(&gpu.atmo, 0, bytemuck::bytes_of(&a));
        }
        let mut pass = ctx.compute_pass("ciel lut");
        if std::mem::take(&mut gpu.cretes_a_faire) {
            pass.set_pipeline(&gpu.pipe_cretes);
            pass.set_bind_group(0, &gpu.groupe_cretes, &[]);
            pass.dispatch_workgroups(CRETES_N / 64, 1, 1);
        }
        if !vue_change {
            return;
        }
        if atmo_change {
            pass.set_pipeline(&gpu.pipe_trans);
            pass.set_bind_group(0, &gpu.groupe_trans, &[]);
            pass.dispatch_workgroups(TRANS.0 / 8, TRANS.1 / 8, 1);
            pass.set_pipeline(&gpu.pipe_ms);
            pass.set_bind_group(0, &gpu.groupe_ms, &[]);
            pass.dispatch_workgroups(MS.0 / 8, MS.1 / 8, 1);
        }
        pass.set_pipeline(&gpu.pipe_vue);
        pass.set_bind_group(0, &gpu.groupe_vue, &[]);
        pass.dispatch_workgroups(VUE.0.div_ceil(8), VUE.1.div_ceil(8), 1);
    }
}
